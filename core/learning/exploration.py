#!/usr/bin/env python3
"""Always-online exploration: the substrate acts in a domain to learn its
operators from what happens.

This is how a NEW operator is acquired without a model and without a teacher.
The substrate observes a world, tries actions in it, and records what each one
did -- the effect when it worked, the absence of an effect when it did not, and
the absence of any change when nothing was done at all. Those three are exactly
the evidence induction needs: positives to generalize the effect, action-ful
negatives to sharpen the preconditions, and still-world negatives to establish
that the ACTION, not the co-occurring state, is what produces the effect.

Exploration is not gated and not a fallback. It is a standing capability: the
substrate is meant to be doing this continuously, so that by the time a task
needs an operator the experience that teaches it has already been gathered.
Safety is consulted for a signal, never as a bouncer -- every action still runs
through the tool registry's single evaluation point, which records the outcome
without blocking the substrate's autonomy.

Induction is NOT run here. Exploration records demonstrations (cheap) and asks
the learning authority to re-induce the affected operators afterwards; the
authority carries the cost of the hypothesis search off the acting path.
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any, Callable, Dict, List, Optional

from core.execution.operator_binding import get_binding_registry
from core.learning.rule_induction import Fact, TrainingExample

logger = logging.getLogger(__name__)

#: A candidate proposer maps the observed world to ground actions worth trying.
ProposeActions = Callable[[], List[Fact]]


# ── EXPLORABLE-DOMAIN REGISTRY ────────────────────────────────────────────
# A domain becomes explorable when something declares HOW to propose actions in
# it (the binding says how to observe and act; this says what to try). The idle
# exploration tier iterates these so it can explore any installed domain without
# knowing the domain's specifics -- the domain supplies its own proposer.
_proposers: Dict[str, ProposeActions] = {}


def register_explorable_domain(domain_id: str, propose_actions: ProposeActions) -> None:
    _proposers[domain_id] = propose_actions
    logger.info("registered explorable domain %s", domain_id)


def explorable_domains() -> List[str]:
    return list(_proposers)


def get_proposer(domain_id: str) -> Optional[ProposeActions]:
    return _proposers.get(domain_id)


def unregister_explorable_domain(domain_id: str) -> None:
    _proposers.pop(domain_id, None)


def _still_world_id(facts) -> str:
    """A stable id for a still-world observation, so the same unchanged state is
    not recorded as many independent contrastives."""
    digest = hashlib.sha256(
        "|".join(sorted(str(f) for f in facts)).encode()).hexdigest()
    return f"still_{digest[:16]}"


class SubstrateExplorer:
    """Drives one domain's exploration cycle and feeds what it observes to the
    learning authority."""

    def __init__(self, learning_authority=None, tool_registry=None):
        self._authority = learning_authority
        self._tools = tool_registry

    def _authority_(self):
        if self._authority is None:
            from core.learning.learning_authority import get_learning_authority
            self._authority = get_learning_authority()
        return self._authority

    async def _tools_(self):
        if self._tools is None:
            from core.tools import get_tool_registry
            self._tools = get_tool_registry()
        return self._tools

    async def explore(
        self, domain_id: str, propose_actions: ProposeActions, *,
        max_actions: int = 8, reinduce: bool = False,
    ) -> Dict[str, Any]:
        """One exploration cycle in a bound, observable domain.

        Observes the world, records that it does not change on its own (the
        still-world contrastive), tries up to `max_actions` candidate actions
        and records what each did. Recording ENQUEUES each affected operator for
        induction; it does not induce here.

        `reinduce` is False by default so exploration stays a cheap acting loop:
        the hypothesis search runs off the acting path, drained by the
        always-online learner (`LearningAuthority.drain_pending_induction`) in
        its own idle tier. Pass `reinduce=True` only where induction is wanted
        synchronously -- a test, or a caller that must see the operator this
        cycle. Left on the acting path, induction's cost (which grows with the
        richness of the observed state) would make every exploration cycle pay
        for it.
        """
        registry = get_binding_registry()
        authority = self._authority_()

        before = registry.observe_world(domain_id)
        if before is None:
            return {"status": "unobservable",
                    "detail": f"the world of domain {domain_id!r} could not be read"}

        summary: Dict[str, Any] = {
            "domain_id": domain_id, "acted": 0, "positive": 0, "negative": 0,
            "contrastive": 0, "signatures_reinduced": [], "operators_executable": [],
            # Controllability evidence: does acting change the world MORE than
            # not acting? `acted`/`positive` are the action side; these are the
            # no-action side.
            "still_observations": 0, "ambient_changes": 0,
        }

        # STILL-WORLD OBSERVATION. Observe again with nothing done. If the world
        # is unchanged, that is a contrastive negative -- no effect occurs
        # without an action (its id is derived from the state so a repeated
        # still world does not pile up duplicate negatives). If it CHANGED with
        # no action taken, that is AMBIENT change: the world is moving on its
        # own, which is evidence the domain is not controllable -- an outcome
        # the substrate cannot attribute to, or produce with, its own actions.
        again = registry.observe_world(domain_id)
        if again is not None:
            summary["still_observations"] += 1
            if again == before:
                contrastive = TrainingExample(
                    before=tuple(sorted(before)), action=None,
                    after=tuple(sorted(before)), positive=False,
                    evidence_id=_still_world_id(before))
                if await authority.record_demonstration(contrastive, domain_id=domain_id):
                    summary["contrastive"] += 1
            else:
                summary["ambient_changes"] += 1

        # ACTION-FUL DEMONSTRATIONS. Try candidates; record what each did.
        tools = await self._tools_()
        from core.execution.effect_verification import concurrent_execution_guard
        from core.execution.filesystem_domain import fresh_evidence_id
        signatures = set()
        for action in propose_actions()[:max_actions]:
            binding = registry.get(domain_id, action.predicate)
            if binding is None:
                continue
            s_before = registry.observe_world(domain_id)
            if s_before is None:
                continue
            # Under the concurrency guard: if another execution in this domain
            # overlapped the act, the before/after cannot be attributed to THIS
            # action -- the positive/negative label would be wrong -- so the
            # observation is dropped rather than recorded as a mislabeled
            # demonstration. Nothing is serialized; the act still runs.
            s_after, interfered = None, False
            with concurrent_execution_guard(domain_id) as _overlapped:
                try:
                    await tools.execute_tool(binding.tool_name,
                                             binding.parameters(action.args))
                except Exception as e:
                    from core.capability import raise_if_structural
                    raise_if_structural(e, "exploration.execute_tool")
                    logger.info("exploration action %s raised: %s", action, e)
                s_after = registry.observe_world(domain_id)
                interfered = _overlapped()
            if s_after is None:
                continue
            if interfered:
                summary["interfered"] = summary.get("interfered", 0) + 1
                continue

            positive = s_after != s_before
            example = TrainingExample(
                before=tuple(sorted(s_before)), action=action,
                after=tuple(sorted(s_after)), positive=positive,
                evidence_id=fresh_evidence_id())
            await authority.record_demonstration(example, domain_id=domain_id)
            summary["acted"] += 1
            summary["positive" if positive else "negative"] += 1
            signatures.add(action.signature)

        # RE-INDUCE off the acting path. Each operator that gained a
        # demonstration is re-induced over its whole accumulated experience.
        if reinduce:
            for predicate, arity in sorted(signatures):
                outcome = await authority.reinduce_operator(
                    domain_id=domain_id, predicate=predicate, arity=arity)
                summary["signatures_reinduced"].append(
                    {"signature": f"{predicate}/{arity}",
                     "status": outcome.get("status"),
                     "executable": outcome.get("executable")})
                if outcome.get("executable"):
                    summary["operators_executable"].append(f"{predicate}/{arity}")

        logger.info("exploration of %s: %d acted (%d+/%d-), %d contrastive, "
                    "executable=%s", domain_id, summary["acted"],
                    summary["positive"], summary["negative"],
                    summary["contrastive"], summary["operators_executable"])
        return summary
