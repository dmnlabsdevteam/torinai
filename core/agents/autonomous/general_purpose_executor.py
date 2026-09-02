#!/usr/bin/env python3
"""General Purpose Executor — SUBSTRATE-ONLY.

Executes a task the way the substrate itself would: a grounded operator from a
validated learned rule, a planned sequence over learned operators, or a
model-free type->tool handler. It holds NO model — the Teacher is the one model
consumer, consulted (if at all) elsewhere as a proposer, never here. A task the
substrate cannot yet do returns an honest gap, not a fabricated completion.

Completion is not a generator policing itself: the substrate re-observes the
world and confirms its own effects, which IS the verification. (The old
LLM-centric framing here — "delegate to the teacher model", the generator/
completion-protocol contract — described a design that has been retired.)
"""

import asyncio
import logging
import uuid
import json
import time
from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime

from .shared_types import Task, TaskType, TaskStatus, TaskSource
from core.database import TorinUnifiedDatabase

# Performance profiling
from core.learning.performance_profiler import profile_performance

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Agent loop tunables
# ─────────────────────────────────────────────────────────────────────────────

# Maximum entries kept in the execution ledger (oldest pruned first).
# Ledger is re-injected after every compression event so causal history
# (which tools ran, what failed, why revisions were requested) is never
# lost to the 8B summary.
EXECUTION_LEDGER_MAX_ENTRIES: int = 50


class GeneralPurposeExecutor:
    """General Purpose Task Executor — substrate-first, model-free.

    Executes tasks (RESEARCH, ANALYSIS, EXECUTION, ...) through the substrate's
    own faculties: proved operators, planned state goals, and per-type tool
    handlers. It carries no model and delegates no intelligence to one; where the
    substrate cannot yet act, it declines honestly rather than generating a result.
    """

    def __init__(self, torin_brain=None, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.active = False

        # Runtime config helpers
        self._env_loaded: bool = False
        #: Values read from .env, kept HERE rather than pushed into os.environ.
        self._dotenv_values: Optional[Dict[str, str]] = None

        # Database for persistence
        self.db = TorinUnifiedDatabase()

        # NO MODEL. The executor is substrate-only; it holds no model handle.
        # `torin_brain` is accepted for call-site compatibility and ignored — the
        # Teacher is the one model consumer. Task-outcome memory is owned by the
        # memory agent (the coordinator hands outcomes to
        # memory_agent.capture_task_outcome), so the executor keeps no memory or
        # context-manager handle of its own either.
        _ = torin_brain  # intentionally unused

        # Tool registry - access to all 300+ tools
        self.tool_registry = None

        # Execution stats
        self.stats = {
            'tasks_executed': 0,
            'tasks_successful': 0,
            'tasks_failed': 0,
            'by_type': {}
        }

    def _ensure_dotenv_loaded(self) -> None:
        """Read TorinAI's .env files for runtime integration checks, WITHOUT
        mutating the process environment.

        This previously called load_dotenv(), which writes every key in
        .env.production into os.environ for the life of the process. Two things
        followed. An operator who unset SLACK_BOT_TOKEN to disable Slack had it
        put back by the first integration check, so the executor's answer to
        "is Slack configured" could not be influenced by the environment it was
        actually running in. And the write was global: every other component
        thereafter saw variables that were never in the environment, attributed
        to nobody.

        Same failure as the POSTGRES_* one, same remedy: read the file into a
        dict and resolve with explicit precedence, so the file informs the
        answer instead of silently becoming the environment.
        """
        if self._env_loaded:
            return
        self._env_loaded = True

        try:
            from pathlib import Path
            from dotenv import dotenv_values

            base = Path(__file__).resolve()
            # Walk up until we find TorinAI root (has core/)
            for _ in range(6):
                if (base / "core").is_dir():
                    break
                base = base.parent

            env_prod = base / ".env.production"
            env_fallback = base / ".env"
            if env_prod.exists():
                self._dotenv_values = dict(dotenv_values(env_prod))
            elif env_fallback.exists():
                self._dotenv_values = dict(dotenv_values(env_fallback))
        except Exception:
            # Dotenv is optional; if missing, runtime checks fall back to os.environ
            return

    def _config_value(self, key: str) -> Optional[str]:
        """Resolve one setting: process environment first, then the .env file.

        A variable present in the environment wins, including when a launcher
        set it deliberately. One that is absent falls back to the file. Nothing
        here writes to os.environ, so asking a question never changes the
        answer for whoever asks next.
        """
        import os
        value = os.environ.get(key)
        if value is not None:
            return value
        self._ensure_dotenv_loaded()
        return (self._dotenv_values or {}).get(key)

    async def initialize(self) -> bool:
        """Initialize the executor and connect to the teacher model"""
        try:
            logger.info("Initializing general purpose executor...")

            # NO MODEL. The executor is SUBSTRATE-ONLY: it executes tasks via
            # proved operators, planned state goals, and per-type substrate tool
            # handlers, and returns an honest gap when the substrate cannot yet do
            # a task. It holds no model handle — the Teacher is the one model
            # consumer, and it owns its own model lifecycle (main.py brings the
            # teacher model up first, independently). The old model-connect + LLM
            # context-manager (conversation compression) here served the retired
            # ReAct loop; both are gone. A component that holds a reference it
            # never uses is claiming a connection it does not have.
            #
            # Task-outcome memory is owned by the memory agent (the authority):
            # the coordinator hands each completed task's outcome to
            # `memory_agent.capture_task_outcome(...)`, which composes the
            # semantic + procedural records model-free. The executor does not
            # store task memory itself.

            # Completion is not verified by a generator-policing protocol here:
            # the substrate re-observes the world and confirms its own effects
            # (verify_effects / goal re-observation), which IS the verification.
            # The model-era completion validator, convergence gate, and iteration
            # controller instances were initialised here but never dereferenced,
            # so they are gone; the live convergence/iteration modules remain and
            # are read by the health monitor.

            # Get tool registry FIRST (before database - it doesn't depend on DB)
            from core.tools.tool_registry import get_tool_registry
            self.tool_registry = get_tool_registry()
            # Count both lazy-loaded (factories) and eager-loaded (tools) tools
            tool_count = len(self.tool_registry.tool_factories) + len(self.tool_registry.tools)
            logger.info(f"Connected to tool registry: {tool_count} tools available ({len(self.tool_registry.tool_factories)} lazy + {len(self.tool_registry.tools)} eager)")

            # Initialize database (don't let this block tool registry)
            # Shadow mode: skip DB — task execution doesn't need persistent storage.
            import os as _gpe_os
            if _gpe_os.environ.get("TORIN_SHADOW_MODE"):
                logger.info("⚡ Shadow mode: database init suppressed (TORIN_SHADOW_MODE=1)")
            else:
                try:
                    await self.db.initialize()
                    # Restore epistemic beliefs from PostgreSQL so the convergence gate
                    # has historical context from previous runs.
                    try:
                        from core.reasoning.epistemic_engine import get_epistemic_engine
                        await get_epistemic_engine()._uncertainty().load_from_db()
                        logger.info("✓ Epistemic engine: beliefs loaded from PostgreSQL")
                    except Exception as _ep_e:
                        logger.warning(f"Epistemic belief load non-fatal: {_ep_e}")
                except Exception as e:
                    logger.warning(f"Database initialization failed (non-critical): {e}")

            self.active = True
            logger.info("General purpose executor ready")
            return True

        except Exception as e:
            logger.error(f"Failed to initialize executor: {e}")
            return False

    # ==================================================================
    # SUBSTRATE-FIRST DRIVE — Phase 1: goal derivation + world observation
    #
    # Before the substrate can plan a task it needs two things the model used
    # to supply implicitly: the state that would make the task done, and the
    # state the world is in now. Neither is invented here. The goal is read
    # from what the task carries; the world is OBSERVED through the domain's
    # bindings, never assumed. When the task carries no state semantics the
    # substrate does not guess one -- it declines, and the decision to fall
    # back to anything else is made above this method, not inside it.
    # ==================================================================

    def _observe_world(self, domain_id: str) -> Optional[List[str]]:
        """The world the substrate will plan against, read now from the domain.

        Returns the observed facts as strings, or None when the world cannot be
        read -- which is not the same as an empty world. Planning against a
        world that was never observed would authorise a plan on a state that
        does not exist, so an unreadable world stops the substrate path here
        rather than letting it proceed on an assumption.
        """
        from core.execution.operator_binding import get_binding_registry

        observed = get_binding_registry().observe_world(domain_id)
        if observed is None:
            return None
        return sorted(str(fact) for fact in observed)

    def _derive_goal_spec(self, task: Task) -> Optional[Dict[str, Any]]:
        """Turn a task into a state goal the planner can search, or decline.

        A state goal is (domain, goal_conditions, observed world). The goal
        conditions come from what the task declares -- its provenance for a task
        authored as a state goal, nothing read out of prose. The world is
        observed, not carried: a `world_state` recorded when the task was
        created is planning-time state, and the state that governs execution is
        the one observed now.

        Returns None, honestly, when the task carries no state goal or its world
        cannot be read. A None here is the substrate saying "not mine yet"; it
        never becomes a guessed goal.
        """
        provenance = getattr(task, "provenance", None) or {}

        # A task already carrying a grounded operator is a plan STEP, not a
        # goal to plan -- that is _execute_grounded_operator's work, not this.
        if provenance.get("grounded_operator"):
            return None

        raw_conditions = provenance.get("goal_conditions")
        domain_id = provenance.get("domain_id")
        if not raw_conditions or not domain_id:
            return None

        # The conditions must parse as facts, or they are not a state goal the
        # search can reason over. A malformed condition declines the whole task
        # rather than silently dropping the part that failed.
        from core.learning.rule_induction import Fact

        goal_conditions: List[str] = []
        for condition in raw_conditions:
            try:
                goal_conditions.append(str(Fact.parse(str(condition))))
            except ValueError as exc:
                logger.info("goal derivation declined task %s: condition %r does "
                            "not parse: %s", task.id, condition, exc)
                return None

        # ENCOUNTER-DRIVEN DOMAIN INSTALL. A task that declares a filesystem
        # workspace is the substrate WORKING in that domain for the first time;
        # install it now (idempotently, scoped to the declared directory) so the
        # world below is observable and the domain becomes explorable from here
        # on — the wire that was missing entirely in production. No workspace
        # declared ⇒ nothing installed; a domain already installed ⇒ no-op.
        workspace_root = provenance.get("workspace_root")
        if workspace_root:
            from core.execution.filesystem_domain import ensure_filesystem_domain
            ensure_filesystem_domain(domain_id, workspace_root)

        world_state = self._observe_world(domain_id)
        if world_state is None:
            logger.info("goal derivation declined task %s: the world of domain "
                        "%r could not be observed", task.id, domain_id)
            return None

        return {
            "domain_id": domain_id,
            "goal_conditions": goal_conditions,
            "world_state": world_state,
        }

    # ==================================================================
    # SUBSTRATE-FIRST DRIVE — Phase 2: plan a state goal and execute it
    #
    # Where _execute_grounded_operator runs one already-grounded operator, this
    # takes a task that names a STATE to reach, plans a sequence of learned
    # operators to reach it, and drives that sequence through the same verified
    # single-operator path. The substrate decides the steps; no model is asked
    # what to do. When the goal cannot be planned it says so -- UNREACHABLE or
    # INDETERMINATE -- and does not fall to generation.
    # ==================================================================

    async def _get_planning_engine(self):
        """The substrate's planner, created once and kept.

        Planning a state goal is the substrate choosing a sequence of its own
        learned operators. One engine is held so the goals and plans it creates
        persist across the tasks the executor drives, rather than a fresh engine
        forgetting them each call.
        """
        engine = getattr(self, "_planning_engine", None)
        if engine is None:
            from core.agents.autonomous.planning_engine import PlanningEngine
            engine = PlanningEngine(self.config)
            if not await engine.initialize():
                logger.error("planning engine failed to initialize; the "
                             "substrate cannot plan state goals")
                return None
            self._planning_engine = engine
        return engine

    async def _drive_substrate_goal(self, task: Task) -> Optional[Dict[str, Any]]:
        """Plan a state goal over learned operators and execute it, model-free.

        Returns None to decline -- the task names no state goal, or the planner
        is unavailable -- leaving what comes next to the caller. Otherwise the
        substrate owns the goal and the result says what happened: it reached
        the goal, proved it unreachable, or stopped at the step that diverged.

        The world is re-observed for authorization by each step (inside
        _execute_grounded_operator) and once more at the end to decide success.
        A plan that ran cleanly while the world did not reach the goal is not a
        success -- the world decides, not the plan's account of itself.
        """
        spec = self._derive_goal_spec(task)
        if spec is None:
            return None

        engine = await self._get_planning_engine()
        if engine is None:
            return None

        from core.reasoning.temporal_reasoning import PlanningStatus

        domain_id = spec["domain_id"]
        goal = await engine.create_goal(
            f"[substrate goal] {task.description}"[:200], task.priority,
            state_conditions=spec["goal_conditions"])
        if goal is None:
            return None

        outcome = await engine.plan_for_goal(
            goal.id, {"world_state": spec["world_state"], "domain_id": domain_id})

        if outcome.status is not PlanningStatus.PLAN_FOUND:
            # Honest inability. UNREACHABLE is a proof about the world;
            # INDETERMINATE is Torin not (yet) knowing enough of its own
            # repertoire. Neither is a reason to ask a model to guess -- but the
            # substrate can go further than "I cannot": the domain authority
            # diagnoses WHAT kind of knowledge is missing (operator, concept,
            # causal link, binding, prerequisite, observation, or none learnable).
            # The diagnosis is a MEASUREMENT, not a decision: it feeds the
            # AppraisalSystem, which owns the disposition (explore / replan /
            # disengage). Until now a planning failure fed appraisal nothing, so
            # the substrate's own inability never reached its disposition.
            from core.integration.universal_domain_master import get_universal_domain_master

            deficit = await get_universal_domain_master().diagnose_deficit(
                domain_id, spec["goal_conditions"], spec["world_state"], outcome)
            try:
                from core.agents.autonomous.appraisal import get_appraisal_system
                get_appraisal_system().update(
                    outcome_quality=0.0,
                    self_initiated=(
                        getattr(getattr(task, 'source', None), 'value', None) == 'autonomous'),
                    **deficit.appraisal_signals(),
                )
            except Exception as e:
                # Disposition is not allowed to decide whether the planning
                # result is returned; the deficit is already diagnosed.
                logger.warning("substrate planning-failure appraisal update failed: %s", e)
            return {
                'success': False,
                'task_id': task.id,
                'execution_path': 'substrate_plan',
                'model_free': True,
                'domain_id': domain_id,
                'goal_conditions': spec["goal_conditions"],
                'planning_status': outcome.status.value,
                'operators_considered': outcome.operators_considered,
                'grounding_complete': outcome.grounding_complete,
                'error': f"substrate could not plan the goal: {outcome.reason}",
                'reason': outcome.reason,
                'deficit': deficit.to_dict(),
            }

        # The proved chain, run in dependency order. Each step goes through the
        # same verified path a single operator takes; the plan's provenance
        # already carries what that path needs.
        step_results: List[Optional[Dict[str, Any]]] = []
        for step in outcome.plan.tasks:
            result = await self._execute_grounded_operator(step)
            step_results.append(result)
            if result is None:
                return {
                    'success': False, 'task_id': task.id,
                    'execution_path': 'substrate_plan', 'model_free': True,
                    'domain_id': domain_id,
                    'error': "a plan step did not present as a grounded operator",
                    'steps': step_results,
                }
            if not result.get('success'):
                # A step refused (authority not established now) or the world
                # did not move as the rule predicted. The drive stops at the
                # step that diverged, not somewhere downstream of it.
                return {
                    'success': False, 'task_id': task.id,
                    'execution_path': 'substrate_plan', 'model_free': True,
                    'domain_id': domain_id,
                    'goal_conditions': spec["goal_conditions"],
                    'stopped_at': step.description,
                    'error': f"step {step.description} did not confirm: "
                             f"{result.get('refused') or result.get('runtime_outcome')}",
                    'steps': step_results,
                }

        # Every step confirmed. Success is the RE-OBSERVED world holding the
        # goal, not the fact that the steps ran. Re-observing the goal-state IS
        # the verification — stronger and model-free — so the verdict is stated
        # here rather than left for a generator-policing protocol to guess.
        final_world = set(self._observe_world(domain_id) or [])
        reached = all(cond in final_world for cond in spec["goal_conditions"])
        return {
            'success': reached,
            'verification_state': 'verified' if reached else 'failed',
            'completion_score': 1.0 if reached else 0.0,
            'task_id': task.id,
            'execution_path': 'substrate_plan',
            'model_free': True,
            'domain_id': domain_id,
            'goal_conditions': spec["goal_conditions"],
            'steps_executed': len(step_results),
            'goal_reached': reached,
            'steps': step_results,
        }

    @profile_performance("general_purpose_executor", "execute_task")
    async def _execute_grounded_operator(self, task: Task) -> Optional[Dict[str, Any]]:
        """Execute deterministically when the substrate holds the authority to.

        Returns None to fall through to model-backed execution. Every authority
        condition is re-established HERE against current state, not inherited
        from the plan, because planning-time authorization goes stale:

            t0  rule VALIDATED, plan generated
            t1  rule REFUTED by new evidence
            t2  task executes

        "The plan already authorized it" is not an argument at t2. The same
        applies to the world: the planner proved applicability in a simulated
        state, and the state governing execution is the observed one.
        """
        provenance = getattr(task, "provenance", None) or {}
        rule_id = provenance.get("learned_rule_id")
        operator_name = provenance.get("grounded_operator")
        if not rule_id or not operator_name:
            return None

        from core.execution.effect_verification import (
            AttributionContext, RuntimeOutcome, ToolObservation, attribute, verify_effects)
        from core.execution.operator_binding import get_binding_registry
        from core.learning.rule_induction import (Fact, RuleEffects, is_variable,
                                                  resolve_outputs)
        from core.reasoning.unification import match_literal
        from core.learning.rule_store import (
            get_rule_store, record_runtime_evidence)

        def refuse(reason: str) -> Dict[str, Any]:
            """A task built on a learned rule fails closed; it never falls
            through to the model.

            Past this point the task IS a grounded operator -- its description
            is `MOVE(z,HALL,LAB)`, authorised by rule R. If the substrate
            cannot establish that authority now, handing the step to a model to
            interpret would substitute generation for the proof the plan was
            built on, and the plan would appear to proceed on authority that
            had already been withdrawn.
            """
            logger.info("substrate path refused task %s: %s", task.id, reason)
            return {
                'success': False,
                'task_id': task.id,
                'execution_path': 'substrate',
                'model_free': True,
                'learned_rule_id': rule_id,
                'operator': operator_name,
                'refused': reason,
                'error': f"substrate authority not established: {reason}",
            }

        domain = provenance.get("domain_id")
        stored = next((r for r in await get_rule_store().load(domain_id=domain)
                       if r.rule_id == rule_id), None)
        if stored is None:
            return refuse(f"rule {rule_id} is no longer in the store")
        if not stored.is_executable:
            return refuse(f"rule {rule_id} is {stored.status.value}, not validated")

        rule = stored.rule
        if rule.action is None:
            return refuse("rule records no action")

        try:
            action = Fact.parse(operator_name)
        except ValueError as e:
            return refuse(f"operator {operator_name!r} does not parse: {e}")
        if action.signature != rule.action.signature:
            return refuse(f"{action.predicate}/{action.arity} does not match the rule's action")

        bindings: Dict[str, str] = {}
        for slot, value in zip(rule.action.args, action.args):
            if is_variable(slot):
                if bindings.setdefault(slot, value) != value:
                    return refuse(f"{operator_name} is not an instance of {rule.action}")
            elif slot != value:
                return refuse(f"{operator_name} is not an instance of {rule.action}")

        binding = get_binding_registry().get(domain or "", action.predicate)
        if binding is None:
            return refuse(f"no tool bound to {action.predicate} in domain {domain!r}")

        before = binding.observe()
        if before is None:
            return refuse("the world could not be read before acting")

        # THE OBSERVED WORLD DECIDES THE BINDING, NOT THE PLAN.
        #
        # Substituting only what the operator's NAME carries leaves every other
        # precondition variable free, and a fact with a variable in it is in no
        # world -- so a rule whose preconditions bind anything the action does
        # not name refused every time, reported as "preconditions absent". The
        # plan does record its own bindings, and trusting them would be
        # inheriting planning-time state, which this method exists not to do.
        #
        # So the preconditions are matched against the world as it is now.
        # Nothing is loosened: a precondition that does not hold still refuses,
        # and it now refuses with the literal that failed.
        candidates = [bindings]
        for literal in sorted(rule.preconditions, key=str):
            candidates = [extended for candidate in candidates
                          for extended in match_literal(literal, before, candidate)]
            if not candidates:
                return refuse(
                    f"precondition {literal.substitute(bindings)} does not hold in "
                    f"the observed world")
        if len(candidates) > 1:
            return refuse(
                f"{operator_name} matches the observed world in {len(candidates)} "
                f"ways; which instance to act on is not determined")
        bindings = candidates[0]

        # A value the action computes is computed now, from what the world was
        # just observed to hold.
        resolved = resolve_outputs(rule, bindings)
        if resolved is None:
            return refuse(
                "a value this action produces has no result on the observed terms")
        bindings = resolved

        # Authorized. Safety and governance are enforced inside execute_tool,
        # which is the single evaluation point for every tool call.
        from core.tools import get_tool_registry

        # TOOL SCOPING (operator path). An agent may drive only the tools
        # the substrate granted it, even through a validated learned operator.
        # None = the substrate's own work (unrestricted).
        _allowed = getattr(task, "allowed_tools", None)
        if _allowed is not None and binding.tool_name not in _allowed:
            return refuse(
                f"tool {binding.tool_name!r} was not granted to this agent")

        observation_id = f"obs_{uuid.uuid4().hex[:12]}"
        # The world is read before and after under a concurrency guard: if
        # another substrate execution in this domain overlapped the act, a
        # mismatch is not this rule's to answer for. The guard serializes
        # nothing -- the act still runs concurrently; it only remembers the
        # overlap so attribution can be honest about it.
        from core.execution.effect_verification import concurrent_execution_guard
        with concurrent_execution_guard(domain) as _overlapped:
            result = await get_tool_registry().execute_tool(
                binding.tool_name, binding.parameters(action.args))
            after = binding.observe()
            interfered = _overlapped()
        observation = ToolObservation(
            observation_id=observation_id,
            tool_name=binding.tool_name,
            invoked=True,
            tool_reported_success=bool(getattr(result, "success", False)),
            observed=after is not None,
            facts=after if after is not None else frozenset(),
            before=before,
            error=getattr(result, "error", None),
            raw={"output": getattr(result, "output", None)},
        )
        # An effect still carrying a variable is one the rule declared it could
        # not predict. It is still checked -- against what the action CHANGED,
        # which is what `ToolObservation.before` is for.
        evidence = verify_effects(rule.effects.substitute(bindings), observation,
                                  rule_id=rule_id, operator=operator_name)

        # Attribution is built from what THIS method independently established
        # on the way to authorizing the call. Each flag was a gate above; none
        # is asserted on trust.
        #
        # `external_interference` means KNOWN interference. The executor still
        # cannot prove a quiet world in general, but it CAN know when another
        # substrate execution in the same domain overlapped this act -- and then
        # a mismatch is not attributable to this rule. Defaulting to False when
        # no overlap was seen keeps single-task and cross-domain learning intact;
        # the guard raises it only for a real, observed concurrent overlap, so a
        # correct rule is never revised because another task happened to run.
        attribution, why = attribute(evidence, AttributionContext(
            preconditions_observed=True,      # checked against `before`
            rule_validated_at_execution=True,  # status re-read above
            action_matches_rule=True,          # signature + instance check
            arguments_verified=True,           # built from the parsed operator
            invocation_occurred=True,
            observer_available=after is not None,
            post_state_observed=after is not None,
            external_interference=interfered,
        ))
        revised_status = await record_runtime_evidence(
            get_rule_store(), evidence, attribution, why,
            task_id=task.id,
            plan_id=provenance.get("plan_id"),
            goal_id=provenance.get("goal_id"),
        )

        logger.info("substrate execution %s: %s (%s) — %s",
                    operator_name, evidence.outcome.value, attribution.value,
                    evidence.detail)

        await self._appraise_substrate_execution(task, evidence, attribution, observation)
        await self._record_execution_demonstration(
            domain=domain, action=action, before=before, after=after,
            observation_id=observation_id, evidence=evidence)

        # Surface the substrate's OWN verdict so the coordinator trusts a
        # world-confirmed success instead of discounting it as unverified. This
        # is not self-attestation: `success` here is verify_effects against the
        # re-observed before/after world. A CONTRADICTION is an honest failure
        # (the rule was refuted); an INDETERMINATE outcome stays unverified —
        # "could not tell" must not be recorded as "failed".
        if evidence.outcome is RuntimeOutcome.CONFIRMATION:
            _verification_state, _completion_score = 'verified', 1.0
        elif evidence.outcome is RuntimeOutcome.CONTRADICTION:
            _verification_state, _completion_score = 'failed', 0.0
        else:
            _verification_state, _completion_score = None, None
        return {
            # Success means the world changed as the rule predicted. A tool that
            # returned cleanly while the world did not move is the case where
            # the action model is wrong and the substrate must find out.
            'success': evidence.outcome is RuntimeOutcome.CONFIRMATION,
            'verification_state': _verification_state,
            'completion_score': _completion_score,
            'task_id': task.id,
            'execution_path': 'substrate',
            'model_free': True,
            'learned_rule_id': rule_id,
            'operator': operator_name,
            'runtime_outcome': evidence.outcome.value,
            'attribution': attribution.value,
            'rule_status_after': revised_status.value if revised_status else None,
            'observation_id': observation_id,
            'effects': [
                {'effect': str(v.predicted_effect), 'polarity': v.polarity.value,
                 'verdict': v.verdict.value, 'detail': v.detail}
                for v in evidence.verifications
            ],
            'detail': evidence.detail,
        }

    async def _record_execution_demonstration(
        self, *, domain, action, before, after, observation_id, evidence,
    ) -> None:
        """File one executed action as a demonstration the learner can use.

        THIS IS THE ONLY PLACE THE SUBSTRATE OBSERVES ITS OWN STATE TRANSITIONS.
        `before`, the action invoked and `after` are all read from the world a
        few lines above, so this is the one point in real work that produces the
        before/action/after triple induction needs. Until it was wired, the
        learner could only generalize from demonstrations a TEACHER supplied,
        and every concept a projected rule contributed was confined to a taught
        domain -- which is why cross-domain transfer had exactly one source
        domain to draw on.

        `training_example_from_runtime` was built for this and had no callers.

        NOT recorded when the world could not be read afterwards, and NOT
        recorded for an INDETERMINATE outcome. A demonstration carries a
        verdict, and an unlabelled one defaults to positive -- which would file
        "we could not tell" as "the action worked".
        """
        from core.execution.effect_verification import RuntimeOutcome

        if after is None:
            logger.info(
                "%s: world unreadable after acting; no demonstration recorded "
                "(an unobserved after-state is not an empty one)", observation_id)
            return
        if evidence.outcome is RuntimeOutcome.INDETERMINATE:
            logger.info(
                "%s: outcome indeterminate; no demonstration recorded — an "
                "unlabelled example would be induced from as a positive",
                observation_id)
            return
        if not domain:
            logger.warning(
                "%s: no domain on the executed rule; a concept must belong "
                "somewhere and inventing a domain here is how one topic "
                "acquired 21", observation_id)
            return

        from core.domain.concept_ingestion import EvidenceSourceType
        from core.domain.evidence_producers import submit_demonstration
        from core.learning.rule_store import training_example_from_runtime

        example = training_example_from_runtime(
            before=before, action=action, after=after,
            evidence_id=observation_id,
            positive=evidence.outcome is RuntimeOutcome.CONFIRMATION)

        # THE OPERATOR-LEARNING PATHWAY. Independent of concept ingestion below:
        # this keeps the executed transition so the substrate's plannable
        # repertoire can grow from its own experience. It only RECORDS here --
        # induction is a hypothesis search whose cost grows with the richness of
        # the observed state, far too expensive to run inline, so the
        # always-online learner re-induces off the hot path. The concept path
        # records the transition's structure for cross-domain matching; this
        # records the operator's own evidence. One failing must not lose the
        # other, so they are separate blocks.
        try:
            from core.learning.unified_learning_system import get_learning_authority
            recorded = await get_learning_authority().record_demonstration(
                example, domain_id=domain)
            logger.info(
                "%s: demonstration %s for operator learning (%s)",
                observation_id, "kept" if recorded else "already held",
                "positive" if example.positive else "negative")
        except Exception as e:
            from core.capability import raise_if_structural
            raise_if_structural(e, "general_purpose_executor.record_demonstration")
            logger.error(
                "%s executed but its demonstration could not be kept: %s: %s",
                observation_id, type(e).__name__, e)

        try:
            result = await submit_demonstration(
                example, domain_id=domain,
                source_type=EvidenceSourceType.TASK_ARTIFACT,
                producer="substrate_execution",
                source_id=f"{domain}:{action.predicate}")
        except Exception as e:
            # Loud, never swallowed: the tool ran and the world moved, so
            # failing the execution over a projection defect would lose the
            # real result. A silent pass would make a broken projection
            # indistinguishable from an action with nothing to project.
            logger.error(
                "%s executed but its demonstration could not be recorded: %s: %s",
                observation_id, type(e).__name__, e)
            return

        if not result.read_successfully:
            logger.error(
                "%s: demonstration recorded but unreadable as structure: %s",
                observation_id, result.extraction_failures)
            return
        logger.info(
            "%s: demonstration recorded (%s) -> %d concept(s) accepted",
            observation_id,
            "positive" if example.positive else "negative", result.accepted)

    async def _appraise_substrate_execution(
        self, task: "Task", evidence, attribution, observation
    ) -> None:
        """Report a substrate execution to appraisal, in measured signals only.

        This is the learned-rule counterpart to `_appraise_tool_outcome`: both
        feed the one whole-self appraisal authority so acting — proved or raw —
        moves disposition, including when the proof turns out wrong. That is the
        one outcome disposition most needs.

        Two signals that look like one are kept apart deliberately:

            action_success_rate   did the action execute?     (the tool ran)
            outcome_quality       was the prediction right?   (the world moved)

        A refuted rule is the case where the first is 1.0 and the second is 0.0
        -- the tool worked perfectly and the model was wrong. Collapsing them
        would read as "we cannot affect the world", which is escalation, when
        the truth is "we still have control and this route is wrong", which is
        replanning.

        Signals with no measurement here are omitted rather than defaulted, so
        nothing invented reaches the appraisal.
        """
        from core.agents.autonomous.appraisal import get_appraisal_system
        from core.execution.effect_verification import RuntimeOutcome, outcome_class_for

        if evidence.outcome is RuntimeOutcome.CONFIRMATION:
            quality = 1.0
        elif evidence.outcome is RuntimeOutcome.CONTRADICTION:
            quality = 0.0
        else:
            quality = None   # nothing was established; do not score it

        try:
            get_appraisal_system().update(
                outcome_quality=quality,
                outcome_class=outcome_class_for(evidence, attribution),
                action_success_rate=(
                    1.0 if observation.tool_reported_success else 0.0),
                # The substrate authorises exactly one operator per step, so
                # there was no choice among options. Reporting otherwise would
                # inflate agency, which feeds replan pressure directly.
                options_considered=1,
                self_initiated=(
                    getattr(getattr(task, 'source', None), 'value', None) == 'autonomous'),
            )
        except Exception as e:
            # Disposition is not allowed to decide whether the execution result
            # is returned. The evidence is already durable at this point.
            logger.warning("substrate appraisal update failed: %s", e)

    async def _run_tool(self, tool_name: str, params: Dict[str, Any], task: Task) -> Optional[Dict[str, Any]]:
        """Execute one named tool and return a substrate result, or None.

        Every outcome is felt: the tool path reports to the SAME whole-self
        appraisal the learned-rule path uses, so a failing tool raises the
        substrate's own caution/avoidance and a run of failures restrains the
        whole self through those existing emotions (appraisal blends over time —
        no per-tool cooldown). Discipline lives in the self, not a counter.
        """
        # TOOL SCOPING. `task.allowed_tools` is None for the substrate's own work
        # (every tool), and a list for an agent the substrate deployed
        # with a granted subset. A copy of the self may reach ONLY what it was
        # granted; a tool outside the grant is refused here, honestly, before it
        # runs — the substrate decides what its copies can touch.
        allowed = getattr(task, "allowed_tools", None)
        if allowed is not None and tool_name not in allowed:
            logger.info("[substrate-tools] %s not granted to task %s (allowed=%s); refused",
                        tool_name, task.id, allowed)
            return None
        try:
            result = await self.tool_registry.execute_tool(tool_name, params)
        except Exception as e:
            logger.debug("[substrate-tools] %s raised: %s", tool_name, e)
            # The tool did not execute: no control established over the world.
            await self._appraise_tool_outcome(task, executed=False, succeeded=False)
            await self._observe_tool_belief(tool_name, params, None, success=False)
            return None
        if not getattr(result, "success", None):
            # The tool executed but reported failure — we can act, this route is
            # wrong. Felt as a poor outcome with control intact (replan, not
            # escalation), accumulating toward avoidance if it keeps happening.
            await self._appraise_tool_outcome(task, executed=True, succeeded=False)
            await self._observe_tool_belief(tool_name, params,
                                            getattr(result, "output", None), success=False)
            return None
        logger.info("[substrate-tools] task %s executed model-free via %s", task.id, tool_name)
        await self._appraise_tool_outcome(task, executed=True, succeeded=True)
        await self._observe_tool_belief(tool_name, params,
                                        getattr(result, "output", None), success=True)
        return {
            "success": True,
            "model_free": True,
            "tool": tool_name,
            "output": getattr(result, "output", None),
            "task_id": task.id,
            "method": "substrate_tool",
        }

    async def _appraise_tool_outcome(self, task: "Task", *, executed: bool,
                                     succeeded: bool) -> None:
        """Report a raw substrate tool outcome to the whole-self appraisal.

        The tool-path counterpart to `_appraise_substrate_execution` (which
        serves the learned-rule path). It feeds only what was actually measured,
        and the attribution is the honest STRUCTURAL read of the observed
        outcome — not a guess:
          • executed and succeeded    → SUCCESS            (approach engages)
          • executed but failed clean → STRATEGY_FAILURE   (the chosen approach,
              which the substrate controls, is the fault → the self replans)
          • could not execute at all  → EXECUTION_FAILURE  (the action itself
              failed → the self cannot act here: escalation/avoidance)
        Appraisal owns the emotional/behavioural response; this only reports.
        The outcome_class here drives appraisal's attribution only — it is not
        routed to meta-learning credit, so it moves no posteriors. Isolated: a
        fault here is logged, never fatal to execution.
        """
        try:
            from core.agents.autonomous.appraisal import get_appraisal_system
            from core.learning.meta_learning import OutcomeClass
            if succeeded:
                outcome_class = OutcomeClass.SUCCESS
            elif executed:
                outcome_class = OutcomeClass.STRATEGY_FAILURE
            else:
                outcome_class = OutcomeClass.EXECUTION_FAILURE
            get_appraisal_system().update(
                outcome_quality=1.0 if succeeded else 0.0,
                # "the tool ran" is distinct from "the outcome was right": an
                # executed-but-failed call keeps controllability (replan); a call
                # that could not execute lowers it (escalation/avoidance).
                action_success_rate=1.0 if executed else 0.0,
                outcome_class=outcome_class,
                # One handler binds exactly one tool per type — no choice among
                # options; reporting otherwise would inflate agency.
                options_considered=1,
                self_initiated=(
                    getattr(getattr(task, 'source', None), 'value', None) == 'autonomous'),
            )
        except Exception as e:
            logger.warning("substrate tool-outcome appraisal update failed: %s", e)

    async def _observe_tool_belief(self, tool_name: str, params: Dict[str, Any],
                                   output: Any, *, success: bool) -> None:
        """The THIRD consumer of the post-tool observation seam (beside
        appraisal and learning-evidence): fold what the tool OBSERVED into the
        belief graph, ROUTED THROUGH THE REASONING AUTHORITY. This is the
        substrate learning about its own capabilities from experience; the belief
        changes surface/resolve unstable regions that drive the epistemic
        exploration loop (intrinsic_motivation._generate_epistemic_goals). One
        seam, one observed outcome — never a parallel observation. Isolated: a
        fault here is logged, never fatal to execution."""
        try:
            from core.reasoning.neural_bridge import get_neural_bridge
            await get_neural_bridge().observe_tool_result(tool_name, params, output, success)
        except Exception as e:
            logger.debug("tool-belief observation skipped: %s", e)

    async def _execute_via_tool_handler(self, task: Task) -> Optional[Dict[str, Any]]:
        """Execute a task through an EXPLICIT, correct type→tool handler, model-free.

        There is no blind "top-ranked tool" dispatch here: a naive binding of the
        task description to whatever tool ranked first produced false successes
        (an analysis task "completed" by creating a directory named after the
        code). A handler is added only for a TaskType whose tool and argument
        binding are known-correct, and it declines (None) otherwise, leaving the
        task to whatever comes next. Nothing here consults a model.
        """
        # TaskType -> a handler proven correct for that type. Extended one
        # verified type at a time; every entry is tested to run model-free
        # without faking success.
        handlers = {
            TaskType.RESEARCH: self._substrate_research,
        }
        handler = handlers.get(task.type)
        if handler is None:
            return None
        return await handler(task)

    async def _substrate_research(self, task: Task) -> Optional[Dict[str, Any]]:
        """A RESEARCH task's description is a web query. Real search, verified non-empty."""
        result = await self._run_tool("web_search", {"query": task.description}, task)
        if result is None:
            return None
        output = result.get("output") or {}
        hits = output.get("results") if isinstance(output, dict) else None
        if not hits:  # a search that returned nothing is not a completed research task
            return None
        return result

    async def execute_task(self, task: Task) -> Dict[str, Any]:
        """
        Execute a task, substrate-first.

        A task carrying a grounded operator from a VALIDATED learned rule is
        already proved: the substrate knows what to do and why. That runs
        deterministically here, with no model consulted. Everything else falls
        through to model-backed execution, where the model acts as a proposer
        for work the substrate cannot yet do itself.

        This mirrors neural_bridge._substrate_solvers, which has routed reasoning
        this way all along. Execution previously went straight to the model
        unconditionally, so a step the substrate could prove was still decided
        by generation.

        Args:
            task: Task to execute

        Returns:
            Dict with execution results
        """
        substrate = await self._execute_grounded_operator(task)
        if substrate is not None:
            return substrate

        # A task that names a STATE to reach is planned over learned operators
        # and driven to completion here, still with no model consulted. Where
        # the single-operator path runs one proved step, this proves and runs a
        # whole sequence. It declines (None) only when the task carries no state
        # goal, and then execution falls through as before.
        driven = await self._drive_substrate_goal(task)
        if driven is not None:
            return driven

        # A task whose work maps to a tool the substrate can invoke model-free —
        # the ranker picks the tool, and its inputs bind from the task without
        # generation — runs here. Declines (None) when no tool's arguments can be
        # bound without a model, leaving what comes next unchanged.
        tooled = await self._execute_via_tool_handler(task)
        if tooled is not None:
            return tooled

        # SUBSTRATE-ONLY. The three paths above are the substrate's own
        # model-free execution. If none handled the task, the substrate cannot
        # YET do it — reported as an HONEST GAP, never delegated to a model.
        # The model path that used to follow here (self.llm /
        # _execute_task_with_tools) is retired; the capability is closed by
        # building a per-type substrate handler, not by generation.
        return {
            'success': False,
            'model_free': True,
            'verification_state': 'failed',
            'error': (f"no substrate handler for a {task.type.name} task yet; the "
                      f"substrate declined all model-free paths and the model is "
                      f"not a fallback"),
            'task_id': task.id,
            'task_type': task.type.name,
        }

    async def get_status(self) -> Dict[str, Any]:
        """Get executor status."""
        return {
            'active': self.active,
            'model_free': True,  # substrate-only executor; holds no model
            'stats': self.stats.copy(),
        }

    async def shutdown(self) -> None:
        """Shutdown executor"""
        self.active = False
        logger.info("General purpose executor shutdown")
