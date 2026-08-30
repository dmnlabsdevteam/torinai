# Autonomous Coordinator — through-and-through map

`core/agents/autonomous/autonomous_coordinator.py` — one class `AutonomousCoordinator`,
**10,965 lines, 146 methods**. Built from a full read of every line (six section
reviews) plus a whole-file caller trace. Line numbers are anchors; re-grep before editing.

---

## THE HEADLINE (it inverts the premise)

We came in believing the coordinator "has a brain in it" — an LLM *Singleton*
deciding what Torin does. **It doesn't, anymore.** The whole-file caller trace shows:

- **The live autonomous loop is already substrate-native.** `start_coordination` →
  `_coordination_cycle` (L3225) → a priority **tier scheduler** (`_run_idle_work`,
  L3780) driven by intrinsic motivation / appraisal / behaviour-arbiter and the
  model-free learning stack. No LLM decides the cycle.
- **The LLM "Singleton brain" is DEAD CODE.** `_singleton_thinking_cycle` (L3332),
  the prose ACT/REFLECT/WAIT decider everyone assumed was the mind, has **zero
  callers**. So does an entire *second* older architecture beside it: the
  `_autonomous_thinking_cycle` maintenance loop, the LLM goal-generation phase, the
  whole `_perception→_planning→_execution` phase pipeline, and the singleton
  maintenance chain. **Thousands of lines, orphaned.**
- **The remaining live LLM couplings are few and specific** — not a central brain,
  but leaves: health-event AI diagnosis, a couple of idle-tier LLM branches, and an
  external-API task-execution path.

So the body/brain refactor is far smaller and safer than feared: **mostly delete
dead code, re-home ~2 live brains, fix a cluster of confirmed defects.** The
coordinator's docstring claim — *"THE COGNITIVE SUBSTRATE IS THE BRAIN. A language
model is a TEACHER"* (L128) — is already true in the running code; the dead
Singleton loop is the ghost of the architecture it replaced.

---

## TWO ARCHITECTURES IN ONE FILE (one live, one dead)

```
LIVE  (substrate-native, tier-based)            DEAD (LLM "Singleton", orphaned)
──────────────────────────────────────          ─────────────────────────────────────
start_coordination (L988)                        _singleton_thinking_cycle (L3332)
  └─ _coordination_cycle (L3225)  ◄── loop         observe → LLM prose decide → act
       ├─ _refresh_motivation_signals (L3646)    _autonomous_thinking_cycle (L7765)
       ├─ _run_system_awareness_cycle (L3670)      LLM maintenance decide
       ├─ dequeue task → _launch_task (L3716)     _singleton_goal_generation_phase (L7851)
       │     └─ _execute_and_validate_task (6547)   LLM goal gen → _parse_and_create_goals (7917)
       ├─ _run_idle_work (L3780) ◄── the "mind"   _perception_phase (8904) → _replan_phase (8939)
       │     └─ 1 due tier from 16 (registry)       → _planning_phase (9000) → _execution_phase (9137)
       │     └─ else _run_exploration_cycle (5705) _execute_singleton_maintenance (8319, DEPRECATED)
       │           appraisal→arbiter→intrinsic      → _execute_singleton_action (8371)
       └─ _reap_finished_tasks (L3743)            _provide_longterm_memory_context (8433)
                                                  _gather_context_for_brain (8034, transitively dead)
```

Both were designed to answer "what should Torin do next?". The **tier scheduler
won**; the **LLM Singleton loop was severed and left in place.**

---

## THE LIVE CONTROL FLOW (what actually runs)

1. **`_coordination_cycle` (L3225)** — the one master loop, ~2 s/tick, `while self.active`. Pure BODY.
   - every 5 ticks `_refresh_motivation_signals` (→ `intrinsic_motivation.calculate_motivation`)
   - every 30 ticks `_run_system_awareness_cycle` (discovery / behavioural / world-model)
   - dequeues an extrinsic task → **`_launch_task` (L3716)** → runs `_execute_and_validate_task` on a bounded pool (`_max_parallel_tasks=3`)
   - when no task: **`_run_idle_work` (L3780)** runs the single highest-priority *due* tier, else falls through to **`_run_exploration_cycle` (L5705)**
   - `_reap_finished_tasks` (L3743) — on failure, `_mark_reflection_due` re-arms the self-observation tiers
2. **`_execute_and_validate_task` (L6547, ~660 lines)** — the live task pipeline: safety gate → `self.executor.execute_task` (the substrate-first `GeneralPurposeExecutor`) → validation delegated to the executor's `verification_state` (+ `SuccessValidator` fallback) → credit/meta-memory → retry/fingerprint bookkeeping. **No LLM call of its own**; a metric-based uncertainty gate, not a model, is the only judgment.
3. **The 16 idle tiers** (registered in `_register_idle_subsystems`, L3870) — see table below.
4. **Input / user / security entry points** — `process_input` (L1338)→`_analyze_for_goal_creation`; `handle_user_request` (L7259, answers from held knowledge via `core.semantics.conversation`, no LLM); `handle_security_finding` (L7431, governance-gated).
5. **Live health path** — `monitoring_coordinator.singleton_callback = _receive_health_event` (L568) → **`_receive_health_event` L10458** (LLM diagnosis, see brains below).

---

## THE IDLE TIERS (the substrate's real "what to do next")

Registered at L3884–3939 (docstring says "6", actually **16**). One runs per idle cycle by priority+interval.

| Tier | L | Live | LLM? | Decision owner |
|---|---|---|---|---|
| idle_security | 3963 | ✅ | no | `IdleWorkPlaybook` |
| idle_health | 4103 | ✅ | no | `IdleWorkPlaybook` + recovery mgr (NB: its `_process_health_events()` call drains a dead empty queue) |
| idle_system_review | 4333 | ✅ | no (explicitly) | deterministic snapshot |
| idle_knowledge_refresh | 4468 | ✅ | **yes** (enqueues an LLM research task; agenda hard-coded here) | coordinator-embedded agenda |
| idle_self_improvement | 4841 | ✅ | **yes** (enqueues ASI/LLM-heavy task) | `IdleWorkPlaybook` targets |
| idle_meta_learning | 5420 | ✅ | no | `StrategyAdaptationGate` + `MetaLearner` |
| idle_memory | 5612 | ✅ | **yes (branch)** `self.llm._autonomous_memory_consolidation` | `IdleWorkPlaybook` |
| idle_abstraction | 5578 | ✅ | no | memory agent |
| idle_learning (`_learning_phase`) | 9706 | ✅ | no | `self.learning` + intrinsic motivation |
| idle_domain_expansion | 4962 | ✅ | no | `UnifiedLearningSystem` |
| **idle_domain_discovery** | 5132 | ✅ | no | UDM crystallize |
| **idle_operator_exploration** | 5156 | ✅ | no | UDM + `SubstrateExplorer` + intrinsic motivation |
| **idle_operator_induction** | 5230 | ✅ | no | `LearningAuthority.drain_pending_induction` |
| idle_self_optimization | 5966 | ✅ | via ASI | `_should_trigger_curiosity_optimization` heuristic |
| (`_run_exploration_cycle` fallback) | 5705 | ✅ | goal-gen delegated | appraisal → behavior_arbiter → intrinsic motivation |

The **bold** three are the substrate-first curiosity/learning loop from recent work.
Only 4 tiers touch the model, all as *leaves* (enqueue a task or an optional branch), none as the deciding authority.

---

## THE DEAD LLM-"SINGLETON" CLUSTER (safe-to-delete; verify no dynamic dispatch)

All confirmed by whole-file caller trace — **zero live callers** (only defs, docstrings, or `function=` log labels):

| Method | L | Was |
|---|---|---|
| `_singleton_thinking_cycle` | 3332 | LLM observe→prose-decide→act loop (the "brain") |
| `_parse_thinking_decision` | 3581 | parses its prose output |
| `_store_singleton_reflection` | 3613 | stores its REFLECT text |
| `apply_throttle` | 3565 | throttle knob for it (inert without it; still called by RecoveryManager → affects nothing) |
| `_autonomous_thinking_cycle` | 7765 | second LLM maintenance loop |
| `_singleton_goal_generation_phase` | 7851 | LLM goal generation |
| `_parse_and_create_goals` | 7917 | parses its output (dead by transitivity) |
| `_gather_context_for_brain` | 8034 | prose context builder (3 callers, all dead → dead) |
| `_execute_singleton_maintenance` | 8319 | self-labelled **DEPRECATED**, logs "OLD SYSTEM" |
| `_execute_singleton_action` | 8371 | dispatches to `self.llm._autonomous_*` |
| `_provide_longterm_memory_context` | 8433 | LLM deep-memory reassessment |
| `_perception_phase` | 8904 | phase pipeline (dead) |
| `_replan_phase` | 8939 | only called by dead `_planning_phase` |
| `_planning_phase` | 9000 | phase pipeline (dead) |
| `_execution_phase` | 9137 | phase pipeline (dead) |
| **Dead health/automation queue chain** | | |
| `_receive_health_event` (BODY) | 8622 | **shadowed by L10458** — never callable; the only appender to `health_event_queue` |
| `_process_health_events` | 8644 | drains a queue nothing fills (called by live idle_health, but always empty) |
| `_create_recovery_goal_from_health_event` | 8680 | reachable only from the above |
| `_receive_automation_proposal` | 8633 | never wired as a callback |
| `_process_automation_proposals` | 8704 | called only from dead `_perception_phase` |
| `_evaluate_automation_proposal` | 8729 | **LLM automation-approval brain — dead** |
| `integrate_domain_knowledge` | 3062 | no callers, and broken on its success path |

Deleting this cluster removes the "brain in the body" almost entirely and shrinks
the god-object by a large fraction.

**Caveat:** liveness is from static grep of `.py` callers. No `getattr`/registry
dispatch reaches these was found, but confirm before deletion.

---

## THE LIVE LLM SURFACE (the real brains/couplings still wired)

These are the only places the model is actually in the loop today:

1. **Health-event diagnosis — `_receive_health_event` (L10458) → `_analyze_health_with_ai` (L10679).** LIVE via the monitoring callback (L568). Uses the **lightweight** LLM to produce a JSON severity/root-cause/action verdict that drives ASI code-repair / recovery. **A genuine live LLM brain to re-home** to substrate diagnosis. (Note: a *second* model dependency — `get_lightweight_llm_service()`.)
2. **External-API task execution — `_execute_task_with_singleton` (L9267)** via `core/api/external_api_server.py:190`. Hard-gated `if not self.llm: return False`. Runs `self.llm._autonomous_*` strategies chosen by the meta-learner. **Not part of the autonomous loop** — an external entry.
3. **Idle-tier LLM leaves:** `_idle_memory_work` LLM_AUTONOMOUS branch (L5649), `_idle_knowledge_refresh_work` (enqueues an LLM research task, L4468), `_idle_self_improvement_work`/`_curiosity_driven_optimization` (ASI engine, may be LLM-heavy).
4. **Inside task execution:** `self.executor.execute_task` (GeneralPurposeExecutor) uses the LLM as a *proposer* — that's the substrate-first executor from recent work, not a coordinator brain.

Everything else classified BODY / DELEGATION / UTILITY.

---

## CONFIRMED DEFECTS (prioritised, with line refs)

**Correctness / live bugs**
1. **Duplicate `_receive_health_event`** (L8622 shadowed by L10458) → the health-event *queue* is dead code; health handling silently moved from perception+goal to synchronous LLM analysis, old path left in place. *(verified)*
2. **`assessment_interval_hours` NameError** (L1049) — referenced in a log f-string, defined nowhere; raises if `asi_self_improvement` present and `enable_periodic_assessment` (default True). *(verified)*
3. **Fabricated-success strategy closures** (`_build_capability_map` L9489/9496/9503/9512) — 4 of 5 LLM strategies `return True` unconditionally, defeating the credit-assignment guard; every LLM-strategy run records a win.
4. **Fake-success governance stubs** — 6 near-identical `change_*` methods (L2038/2119/2164/2210/2255/2300) return synthetic success on the ROUTINE tier **without performing the mutation** ("For now, return success", L2109).
5. **`integrate_domain_knowledge` broken success path** (L3062) — reads 4 attributes it never set on a `SimpleNamespace`; any success is caught and reported as failure. (Also dead — no callers.)
6. **`shutdown` orphaned log** (L10406–10407) — logs "periodic performance assessment stopped" with no matching cancellation.

**State / discipline**
7. **Side-effecting getter** — `get_system_status` (L3167) mutates `stats["uptime_seconds"]` (L3172) and `["system_efficiency"]` (L3185) every call; repeated status reads inflate uptime.
8. **`tasks_completed` double-count** — incremented in both `_execution_phase` (dead) and `_check_task_completions` (L10192) / `_execute_and_validate_task`.
9. **Duplicate idle-timestamp state** — `_idle_last_*_at` (L345–359, the *read* set) vs non-suffixed `_idle_last_*` (L621–625, only ever assigned → dead). *(verified)*
10. **Mutable class-level `_resource_allocation_history`** (L2349) — cross-instance bleed risk.
11. **Hardcoded DB creds** targeting `torinai_db` (L438–443, L469–474) bypass `PostgresConfig`.

**Architecture (brain-in-body, model-mandatory)**
12. **`_infer_domain_from_task` (L1932)** — hand-rolled keyword domain classification; belongs to UDM/registry.
13. **LLM-mandatory hard gates** — `_evaluate_automation_proposal` returns reject with no LLM (L8737); `_execute_task_with_singleton` returns False with no LLM (L9280, though `general_executor` could serve it). Contradict the model-optional direction.
14. **Decision policy embedded in the body** — knowledge-refresh research agenda (L4550–4575), `_should_trigger_curiosity_optimization` thresholds (L6044), `_select_adaptive_task_type` keyword fallback (L6516). Small brains that belong to curiosity/appraisal/meta-learner.

**Cosmetic / drift**
15. Stale docstrings: `_coordination_cycle` (L3229, "AI thinks each cycle" — it doesn't), `_register_idle_subsystems` (L3872, "6" tiers — 16). Vestigial `cap - len(...) * 0` no-op (L5799). Duplicated Slack/DB blocks inside `_execute_and_validate_task`.

---

## WHAT THIS MEANS FOR THE BODY/BRAIN REFACTOR

1. **Delete the dead Singleton cluster** (table above). This removes the "brain in the coordinator" almost wholesale and massively shrinks the file — *before* any new center exists. Low risk (zero live callers), high clarity gain.
2. **Re-home the ~2 live brains** to the substrate: health-event diagnosis (`_analyze_health_with_ai`) → a substrate diagnosis mechanism (the deficit/appraisal machinery is the natural home), model as optional proposer; the idle-tier LLM branches → substrate mechanisms with LLM optional.
3. **Fix the confirmed defects** (esp. 1–6) — several are silent-success / dead-path hazards that make the body lie about what it did.
4. **The result is already the target topology:** `_coordination_cycle` + `_run_idle_work` + tiers is a clean **body** that senses, schedules, dispatches, and reports; it delegates every real decision to substrate engines (UDM, SubstrateExplorer, LearningAuthority, MetaLearner, appraisal, behavior_arbiter, IdleWorkPlaybook, PredictiveIntelligence). The new **Self/center** plugs in exactly where the dead Singleton loop used to sit — as the integrator the body reports to and asks for disposition — with far less to demolish than the file's size suggests.

---

## COMPLETE METHOD INDEX (all 146, grouped; class = BODY / DELEGATION / UTILITY / BRAIN / DEAD)

**Lifecycle & wiring** — `__init__` 140 BODY · `initialize` 627 BODY · `_report_failure` 967 DELEGATION · `start_coordination` 988 BODY · `start_background_tasks` 1010 BODY (bug L1049) · `shutdown` 10392 BODY (bug L10406) · module `create_autonomous_system` 10937 / `get_autonomous_coordinator` 10951 UTILITY.

**Registries** — `register_agent` 1056 · `unregister_agent` 1110 · `register_capability` 1185 · `unregister_capability` 1269 · `register_completion_callback` 1285 · `get_registered_agents` 1327 — all BODY/UTILITY. `_record_exploration_decision` 1155 · `_calculate_exploration_quota` 1171 UTILITY.

**Input & goals** — `process_input` 1338 BODY · `extract_state_conditions` 1363 DELEGATION(→Fact parser) · `set_goal` 1395 BODY · `generate_curiosity_driven_goals` 1440 DELEGATION(→intrinsic motivation) · `_analyze_for_goal_creation` 10231 BODY(keyword; LIVE via process_input).

**Memory** — `_build_memory_narrative` 1536 UTILITY · `store_memory` 1710 BODY · `_store_governance_block_meta_memory` 1800 · `_store_task_outcome_meta_memory` 1861 · `_infer_domain_from_task` 1932 **BRAIN(move out)** · `search_memories` 2015 DELEGATION · `get_intelligent_memory_context` 2553 DELEGATION · `_provide_longterm_memory_context` 8433 **DEAD/BRAIN**. Config changers `upgrade_memory_system` 2038 / `change_memory_tier_threshold` 2119 / `change_ranking_weights` 2164 / `change_ttl` 2210 / `change_storage_backend` 2255 / `change_query_filter_logic` 2300 — BODY, **all fake-success stubs**.

**Resources** — `allocate_resources` 2351 BODY (real mutation + governance).

**Reasoning/prediction/domain (delegations)** — `model_available` 2657 UTILITY · `reason_about` 2661 DELEGATION(→neural_bridge, substrate-only) · `_model_calls_on` 2757 UTILITY · `predict_system_behavior` 2772 · `perform_cross_domain_reasoning` 2821 · `make_enhanced_prediction` 2945 (overlaps 2772) · `get_domain_insights` 3013 · `integrate_domain_knowledge` 3062 **DEAD+broken** · `get_system_status` 3167 BODY (side-effecting getter) · `get_intelligence_capabilities` 10431 UTILITY.

**Master loop & dispatch** — `_coordination_cycle` 3225 BODY(loop) · `_launch_task` 3716 · `_reap_finished_tasks` 3743 · `_mark_reflection_due` 3761 · `_get_task_pool` 3770 · `_run_idle_work` 3780 · `_register_idle_subsystems` 3870 — all BODY. `_refresh_motivation_signals` 3646 · `_run_system_awareness_cycle` 3670 DELEGATION.

**DEAD Singleton loop** — `_singleton_thinking_cycle` 3332 · `apply_throttle` 3565 · `_parse_thinking_decision` 3581 · `_store_singleton_reflection` 3613 · `_autonomous_thinking_cycle` 7765 · `_singleton_goal_generation_phase` 7851 · `_parse_and_create_goals` 7917 · `_gather_context_for_brain` 8034 · `_execute_singleton_maintenance` 8319 · `_execute_singleton_action` 8371 · `_perception_phase` 8904 · `_replan_phase` 8939 · `_planning_phase` 9000 · `_execution_phase` 9137 — all **DEAD (LLM brain)**.

**Idle tiers** (all BODY-dispatch over the noted owner) — `_idle_security_work` 3963 · `_idle_health_work` 4103 · `_idle_system_review_work` 4333 · `_idle_knowledge_refresh_work` 4468 (LLM leaf) · `_idle_self_improvement_work` 4841 (ASI leaf) · `_idle_domain_expansion_work` 4962 · `_idle_domain_discovery_work` 5132 · `_idle_operator_exploration_work` 5156 · `_idle_operator_induction_work` 5230 · `_idle_meta_learning_work` 5420 · `_idle_abstraction_work` 5578 · `_idle_memory_work` 5612 (LLM branch) · `_run_exploration_cycle` 5705 · `_idle_self_optimization_work` 5966 · `_curiosity_driven_optimization` 6060 · `_learning_phase` 9706. Support: `_resolve_transfer_outcomes` 5274 · `_task_outcomes_by_field` 5379 · `_should_trigger_curiosity_optimization` 6034 · knowledge-cutoff helpers 4608–4784 · failed-fp helpers 4673–4696 · `_on_knowledge_refresh_complete` 4784.

**Task exec / strategy** — `_execute_and_validate_task` 6547 BODY(LIVE) · `_execute_completion_callbacks` 7208 BODY · `_execute_task_with_singleton` 9267 BODY/LLM (LIVE via external API only) · `_result_is_success` 9446 UTILITY · `_build_capability_map` 9476 UTILITY (**fabricated-success bug**) · `_select_execution_strategy` 9522 DELEGATION · `_record_strategy_outcome` 9585 · `_get_recent_task_outcomes` 9665 UTILITY · adaptive: `_decision_context` 6281 · `_task_family_for` 6319 · `_record_adaptive_type_outcome` 6344 · `_record_experience_outcome` 6412 · `_select_adaptive_task_type` 6443 (keyword fallback).

**User / security / health** — `handle_user_request` 7259 BODY(LIVE, delegates to semantics) · `_request_kind` 7355 · `_answer_from_what_is_held` 7372 DELEGATION · `handle_security_finding` 7431 BODY(LIVE) · `_collect_system_context_for_goals` 7589 BODY(sensing) · `_handle_idle_state` 7760 legacy shim · `handle_security_finding`→`_on_security_remediation_complete` 10830 BODY. Health: `_receive_health_event` **8622 DEAD** / **10458 LIVE BRAIN** · `_analyze_health_with_ai` 10679 **BRAIN(LLM)** · `_execute_recovery` 10773 · `_verify_recovery` 10910 DELEGATION. Automation (**all dead**): `_receive_automation_proposal` 8633 · `_process_health_events` 8644 · `_create_recovery_goal_from_health_event` 8680 · `_process_automation_proposals` 8704 · `_evaluate_automation_proposal` 8729.

**Constitutional / capabilities / state** — `_check_constitutional_alignment` 8504 DELEGATION · `_check_constitutional_alignment_quick` 8609 DELEGATION · `_execute_registered_capabilities` 9854 BODY · `_check_capability_conditions` 10017 UTILITY · `_check_task_completions` 10110 BODY (double-count) · `_apply_learning_recommendation` 10251 BODY · `_update_system_state` 10370 BODY · `_observe_system_performance` 6159 · `_predict_and_resolve_system_state` 6176 DELEGATION · `_persist_prediction_result` 6229 UTILITY · `_handle_error` 6115 BODY.

_Generated 2026-08-27 from a full read of all 146 methods + whole-file caller trace._
