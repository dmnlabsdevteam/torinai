# TorinAI Safety & Governance Architecture

**Date**: 2026-08-11
**Scope**: The control plane — what decides whether an agent action may run, whether it really
happened, who authorized it, and under what policy.

This is **not** about network defense. Host/perimeter security (threat intel, firewall, WAF, IP
blocking) is covered by [SECURITY_GUARDIAN_ARCHITECTURE.md](SECURITY_GUARDIAN_ARCHITECTURE.md),
[SECURITY_FOLDER_AUDIT.md](SECURITY_FOLDER_AUDIT.md) and
[SECURITY_INTEGRATION_ANALYSIS.md](SECURITY_INTEGRATION_ANALYSIS.md).

---

## How this inventory was built

Reachability and call relationships were derived by AST-parsing all 249 modules under `core/`,
resolving both absolute and relative imports (361 relative imports exist; text greps miss them),
and walking the import graph from the real entry point `core.main`.

| Status | Meaning |
|---|---|
| `LIVE` | Reachable from `core.main` **and** something calls its entry point |
| `IMPORTED` | Reachable, but only constructed — its gate is never invoked |
| `ORPHANED` | Nothing in `core/` imports it |
| `DEAD PATH` | Reachable code whose only caller is itself unreachable |

---

## 1. Two planes, four concerns

**Safety** and **governance** are different questions that meet at exactly one point.

| Plane | Question | Concerns |
|---|---|---|
| **Safety** | Is this action dangerous? Did it really happen? | Admission risk · Completion verification · Change safety |
| **Governance** | Who authorized this, under what policy, with what oversight? | Directives · Policy/tiers · Enforcement mode · Approval · Audit |

They meet in the admission decision:

```
        SAFETY                              GOVERNANCE
   risk score (0.0-1.0)      ×      tier (ROUTINE / IMPORTANT / CRITICAL)
                          ↓
              ALLOW | ALLOW_MONITORED | APPROVE | BLOCK
```

Everything else in each plane is independent. Conflating them is why there are four parallel gates
today: some modules score risk, some apply policy, and nothing composes the two.

| Plane / concern | Modules | Lines | State |
|---|---|---|---|
| Safety — admission | 5 | ~4,500 | Fragmented; the composing gate is orphaned |
| Safety — verification | 5 | ~5,900 | Stacked; 3 verdict formats |
| Safety — change | 4 | ~2,800 | **Correctly pipelined** |
| Governance — directives | 6 | 3,885 | Live, but its safety monitor is orphaned |
| Governance — policy/approval/audit | 8 | ~3,300 | Policy live; approval dead; audit cannot record blocks |

---

# PART I — SAFETY

## 2. Admission control

| Module | Lines | Status | Responsibility |
|---|---|---|---|
| `security/safety_framework.py` | 806 | **ORPHANED** | Composite gate: content → params → code sanitization → ASI risk → governance → enforce |
| `security/asi_safety.py` | 1501 | **ORPHANED** | Risk scorer. Action-type base + complexity + criticality + rollback. Fails closed |
| `security/controller.py` | 1270 | LIVE | Regex SQLi / path-traversal / rate limit. Fails closed |
| `agents/autonomous/runtime_governance.py` | 1110 | LIVE | HALT/advisory pre-check; wraps `governance_agent` |
| `agents/autonomous/governance_agent.py` | 643 | LIVE | Called only by `runtime_governance` |

### How it works today

```
coordinator._execute_and_validate_task
  └─ security_controller.validate_request()        regex input gate, fail-closed
  └─ executor.execute_task()
       └─ runtime_governance pre-check             HALT / advisory
       └─ per tool call → tool_registry.execute_tool()
            └─ unified_governance.evaluate_action()      36-rule table → tier
                 ├─ MUST_BLOCK → ToolResult(success=False)     ← real block
                 ├─ CRITICAL   → _queue_for_governance()       ← STUB
                 └─ ROUTINE    → tool.execute()
```

**S1 — The only composing gate is disconnected.** `safety_framework` is the sole module that layers
risk scoring onto policy. Its only importer is `agents/agents.py`, itself orphaned. Consequence:
`asi_safety` is reachable *only* through it, so **the risk-scoring layer never executes**.

**S2 — Four gates, no shared verdict.** `controller`, `runtime_governance`, `unified_governance`
and (when connected) `safety_framework` fire at different layers with different return shapes.
`safety_framework` *also* calls `unified_governance` internally, so where both run, policy is
evaluated twice.

## 3. Completion verification

| Module | Lines | Status | Answers |
|---|---|---|---|
| `execution/convergence_gate.py` | 1057 | LIVE | Is it done? (invariants, uncertainty, state fixpoint) |
| `agents/autonomous/completion_protocol.py` | 2508 | LIVE | Is it real? (multi-layer + LLM critic) |
| `agents/autonomous/reality_verifier.py` | 907 | LIVE | Filesystem / process / socket / import checks |
| `agents/autonomous/content_quality_verifier.py` | 1130 | LIVE | Placeholder / duplication / grounding forensics |
| `agents/autonomous/success_validator.py` | ~340 | LIVE | Dict-shape checking |

**S3 — Three definitions of "verified."** Convergence gate, completion protocol and success
validator each decide independently with no shared verdict type. `success_validator` runs only when
`completion_protocol` didn't set `verification_state` — a fallback for the fallback — and validates
dict *shape*, not correctness.

**S4 — The formal gate is not formal.** `convergence_gate` documents *"Z3 SMT solver for invariant
proofs"* but touches `ConstraintSolver` once, to read `.available`. Convergence is decided by
tool-call counting and state-hash fixpoint. Z3 (4.15.8) is installed and never invoked here.

## 4. Change safety — the reference pattern

```
enhanced_asi → upgrade_validator (→ mutation_detector AST gate) → upgrade_sandbox → safe_upgrade_deployer
```

| Module | Lines | Status |
|---|---|---|
| `learning/upgrade_validator.py` | 1048 | LIVE |
| `learning/mutation_detector.py` | 355 | LIVE — blocks `sys.modules` tampering, `exec`/`eval`, critical-module patching |
| `learning/upgrade_sandbox.py` | 768 | LIVE |
| `learning/safe_upgrade_deployer.py` | ~600 | LIVE |

**This is the shape the other concerns should have**: one entry point, one direction, each stage
owning one question, sub-checks nested inside their owning stage.

**S5 — It fails open.** `upgrade_validator` has three `except → passed=True` branches;
`mutation_detector` fails open on `SyntaxError` and on any unexpected exception.

---

# PART II — GOVERNANCE

## 5. Directives — operator intent

The mechanism by which a human steers the agent's standing behaviour.

| Module | Lines | Status | Responsibility |
|---|---|---|---|
| `directive_system.py` | 517 | LIVE | Entry point; called by the coordinator |
| `directive_manager.py` | 976 | LIVE | CRUD + persistence (`internal_directives`, `directive_applications`) |
| `directive_types.py` | 674 | LIVE | Typed, range-validated directive schema |
| `directive_ab_testing.py` | 499 | LIVE | A/B tests competing directives |
| `directive_evolution_engine.py` | 458 | LIVE | Version lineage, improvement scoring, drift detection, audit trail |
| `directive_safety_monitor.py` | 761 | **ORPHANED** | — |

**G1 — Directives are consumed as prompt text.** The manager writes structured, validated records
to real tables, but the coordinator reads them back and injects them as f-strings into the LLM
prompt. The only programmatic use is `directive_system.py:218` merging `directive_parameters` into
task params. Typed governance data is flattened into prose at the point of use.

**G2 — The directive safety monitor is orphaned.** 761 lines, docstring *"100% COMPLETE
IMPLEMENTATION - NO STUBS"*, implementing exactly the failure modes a self-directing agent is prone
to:

1. Metric gaming / Goodhart's Law
2. Directive drift — local improvements producing global misalignment
3. Bias amplification in governance agents
4. Evaluator collusion / monoculture
5. Security compromise via poisoned feedback or adversarial tasks

Nothing imports it. The system A/B-tests and tracks the evolution of its own directives with **no
safety monitor attached to that loop**.

## 6. Policy, enforcement mode, approval, audit

| Module | Lines | Status | Responsibility |
|---|---|---|---|
| `governance/unified_governance_trigger_system.py` | 780 | LIVE (12 importers) | 36 triggers → `(irreversibility, impact, safety_risk)` → tier |
| `governance/governance_block_schema.py` | 199 | LIVE | Typed block / task-outcome records for meta-memory |
| `governance/enforcement_mode_manager.py` | 575 | IMPORTED | LOG_ONLY / RECOMMEND_GOVERNANCE / ENFORCE |
| `governance/context_classifier.py` | 306 | LIVE | Context tagging for trigger matching |
| `governance/shadow_mode_coordinator.py` | 817 | **ORPHANED** | — |
| `integration/approval_pipeline.py` | 322 | DEAD PATH | Slack approval request/await |
| `integration/approval_manager.py` | 261 | DEAD PATH | Pending-approval store, timeouts |
| `learning/governance_pattern_learner.py` | 186 | **ORPHANED** | Learns approval patterns |
| `agents/autonomous/singleton_constitution.py` | 630 | LIVE (5 importers) | 5 laws, numeric compliance scoring |
| `learning/safety_audit_trail.py` | 542 | LIVE | JSONL audit to `/tmp/torin_audit` |

**G3 — Human approval is complete and dead.**

```
unified_governance.make_decision()                 ← NO CALLERS
  └─ _handle_important_tier() / _handle_critical_tier()
       └─ approval_pipeline.request_approval()
            └─ approval_manager.create_approval_request()  + Slack
                 └─ POST /approval  (chat_server.py:173)
                      └─ approval_manager.record_decision()
```

Every layer below `make_decision()` works. `make_decision()` is called by nothing.

**G4 — The live approval path cannot say yes.** `tool_registry._queue_for_governance()` is marked
*"For Phase 2… Full governance queue integration will be implemented later."* It returns
`requires_approval=True`, queues nothing, notifies no one. CRITICAL actions are permanently denied
with no route to approval.

**G5 — The constitution enforces nothing.** `assess_constitutional_alignment()` computes real
numeric compliance against 5 laws from psutil-derived state. Every consumer of `drift_severity` is
a log line, a Slack notification, or a prompt string. No code path blocks on constitutional drift.
Both `_check_law_compliance` and `_calculate_context_law_compliance` return `0.80` on exception —
above the `0.70` threshold, so an error scores as compliant.

**G6 — The audit trail cannot record blocks.** `SafetyEventType.BLOCKED_ACTION` does not exist in
the enum despite 11 call sites. Every *block* raises `AttributeError` instead of being written,
while approvals record normally. The on-disk trail is structurally biased toward success. It also
writes to `/tmp`, which the OS purges.

> **Correction (2026-08-11):** an earlier draft claimed the partitioned metrics tables had expired
> (no partition after 2026-08-01). That is **wrong**. Partitions run through `2027_07`, the
> `performance_logs_2026_08` partition covers today, and a live insert succeeds. Metrics writes
> are not blocked by partitioning.

**G7 — Enforcement mode is configured but not consulted.** `config/enforcement_config.json` sets
all 8 categories to `RECOMMEND_GOVERNANCE`, and `enforcement_mode_manager` is imported only by the
coordinator. `unified_governance` is constructed without an enforcement manager, so the JSON's
`MUST_BLOCK` values are used verbatim and the mode layer is bypassed.

---

# PART III — ENFORCEMENT LAYER

Classification, limits and kill switches. This is where most decisions are *recorded* and least
often *enforced*.

## 7. Tool-layer classification

| Mechanism | Where | Status |
|---|---|---|
| `ToolSafety` — SAFE / MODERATE / DANGEROUS / CRITICAL / HIGH_RISK | `tool_registry.py:1337` | **Decorative by design** |
| `RiskLevel` — LOW / MEDIUM / HIGH / CRITICAL | `capabilities.py:332` | Branched on only by `requires_approval()` |
| `capabilities.requires_approval()` | `capabilities.py:578` | Real logic, **zero callers** |
| `execute_action_with_commitments` | imported at `tool_registry.py:40` | **Imported, never called** |

**E1 — Tool safety classification is explicitly not enforced.** All 371 tools carry a `ToolSafety`
level — 261 safe, 66 moderate, **39 dangerous, 4 critical, 1 high_risk**. The enum's own docstring
says *"for monitoring/logging purposes only"* and *"NOTE: No approval gates - Singleton has full
autonomy."* Grep confirms it: `ToolSafety` appears only in assignments, never in a comparison or
branch. A `dangerous` tool and a `safe` tool take exactly the same path through `execute_tool()`.

**E2 — Three incompatible risk taxonomies.** `capabilities.RiskLevel` uses `MEDIUM`;
`safety_framework.RiskLevel` uses `MODERATE`; `quantum_safety.QuantumRiskLevel` is a third. They
cannot be compared or composed without a mapping that does not exist.

**E3 — Commitment contracts are dead at the tool layer.** `tool_registry` imports
`CommitmentContract`, `CommitmentType` and `execute_action_with_commitments` from `core.safety` —
and calls none of them. Combined with the manager being reachable only from a health probe, the
entire commitment-contract mechanism (parameter-tamper detection at ±5%) is unreachable from any
execution path.

## 8. Resource limits and kill switch

| Module | Lines | Status |
|---|---|---|
| `health/system_watchdog.py` | 1021 | **Never started** |
| `monitoring/resource_config.py` | 12 | Defines `TORIN_RESOURCE_LIMITS` |
| `chaos/safety_controller.py` | 503 | **LIVE** |
| `quantum/quantum_safety.py` | 407 | Reachable only via quantum (unimportable) |
| `quantum/asi_quantum_safety.py` | 630 | ORPHANED |

**E4 — The watchdog is constructed with the wrong type and never started.**
`autonomous_coordinator.py:319` does `SystemWatchdog(TORIN_RESOURCE_LIMITS)`, but
`SystemWatchdog.__init__` expects a `WatchdogConfig`. The two dataclasses share only
`check_interval` — `ResourceLimits` has no `auto_recovery`, `max_recovery_attempts`,
`recovery_cooldown` or `alert_on_recovery`. Since `config or WatchdogConfig()` treats the wrong
object as truthy, it is stored as-is and every later config access raises `AttributeError`.

`.start()` is called only inside `system_watchdog.py` itself (its singleton helper and two
`__main__` demos). `monitoring_coordinator` fetches the singleton at `:159` and never starts it.
**There is no running resource enforcement and no kill switch.**

**E5 — Chaos has the one working guardrail.** `chaos/safety_controller.py` is live, imported by
`chaos/orchestrator.py`, and implements pre-flight checks and blast-radius limits for chaos
experiments. It is the only enforcement mechanism in this section that actually runs — and it
guards experiments rather than the agent.

---

## 9. Orphaned control-plane modules

| Module | Lines | Plane |
|---|---|---|
| `governance/shadow_mode_coordinator.py` | 817 | Governance |
| `agents/autonomous/directive_safety_monitor.py` | 761 | Governance |
| `security/asi_safety.py` | 1501 | Safety |
| `security/safety_framework.py` | 806 | Safety |
| `quantum/asi_quantum_safety.py` | 630 | Safety |
| `agents/autonomous/causal_traceability.py` | 573 | Governance (provenance) |
| `security/service_abstractions.py` | 280 | Safety |
| `learning/governance_pattern_learner.py` | 186 | Governance |

**Total: ~5,550 lines of control-plane code that never executes.**

---

## 10. Target architecture

**One entry point per concern. Everything else becomes a layer inside it.**

### Admission — where the two planes meet

```
ControlPlane.evaluate(action)          ← single entry: tool_registry AND executor

  SAFETY
   1. INPUT     controller.validate_request()        injection / rate limit   fail-closed
   2. CONTENT   content safety + params + code sanitization
   3. RISK      asi_safety.assess_action_safety()    risk 0.0-1.0             fail-closed

  GOVERNANCE
   4. DIRECTIVE active directives → constraints on this action (structured, not prose)
   5. POLICY    unified_governance.evaluate_action() 36 rules → tier
   6. MODE      enforcement_mode_manager             LOG_ONLY | RECOMMEND | ENFORCE

  DECISION
   7. DECIDE    risk × tier × mode → ALLOW | ALLOW_MONITORED | APPROVE | BLOCK
   8. ESCALATE  APPROVE → approval_pipeline → Slack → /approval → resume or expire
   9. AUDIT     safety_audit_trail.record()          every outcome, blocks included
```

`safety_framework.py` is already written to be steps 2–5 and 7. The work is folding in step 1,
reconnecting 3, 6 and 8, fixing 9, and routing `tool_registry` through it rather than past it.

### Verification

```
VerificationResult { done: bool, real: bool, quality: float, evidence: [...] }

  convergence_gate     → done     invariants, fixpoint, uncertainty
  completion_protocol  → real     reality_verifier + content_quality_verifier + critic
  <success_validator absorbed — shape-checking becomes a schema assertion>
```

### Directive governance

```
operator → directive_manager (typed record)
             ├→ directive_ab_testing        which variant performs better
             ├→ directive_evolution_engine  lineage, drift, audit
             └→ directive_safety_monitor    gaming, drift, bias, collusion, poisoning   ← RECONNECT
                     └→ feeds ControlPlane step 4 as constraints
```

### Change safety

Already correct. Close the five fail-open branches.

---

## 11. Migration order

| # | Step | Plane | Why here |
|---|---|---|---|
| 1 | Fix `SafetyEventType.BLOCKED_ACTION` + 8 wrong-signature `record_event` calls; move audit off `/tmp` | Gov | Nothing downstream is observable until blocks can be recorded |
| 2 | Route `tool_registry` through `safety_framework` instead of `unified_governance` | Both | Turns on the dark risk layer (`asi_safety`) |
| 3 | Replace `_queue_for_governance` stub with `approval_pipeline` | Gov | Gives CRITICAL a path to yes; revives ~600 lines of working approval code |
| 4 | Reconnect `directive_safety_monitor` to the directive loop | Gov | A/B testing + evolution currently run unmonitored |
| 5 | Fold `controller.validate_request` in as layer 1; drop the coordinator's separate call | Safety | Removes one parallel gate |
| 6 | Collapse `runtime_governance` into the escalation layer | Safety | Removes the second parallel gate |
| 7 | Consult `enforcement_mode_manager` in `unified_governance` | Gov | Makes the mode layer real |
| 8 | Introduce `VerificationResult`; absorb `success_validator` | Safety | Single verdict type |
| 9 | Close fail-open branches in `upgrade_validator` / `mutation_detector` | Safety | Hardening |
| 10 | Decide the remaining orphans | Both | ~3,200 lines either matter or they don't |

Steps 1–4 change behaviour. 5–8 consolidate. 9–10 harden and clean up.

---

## 12. Open decisions

1. **Constitutional enforcement.** Should drift be able to block an action, or stay advisory?
2. **Directive representation.** Directives are typed records flattened to prose at the point of
   use. Should they become structured constraints the gate evaluates (step 4), or stay as guidance?
3. **`EmergentMetaCognition`** (~900 of `asi_safety.py`'s 1501 lines). Loads a transformer plus two
   **untrained** torch networks per assessment; no longer feeds the risk score. Delete or keep?
4. **Approval channel.** Slack is wired end to end. Is that the intended surface?
5. **Fail-open vs fail-closed default.** `asi_safety` and `controller` fail closed;
   `safety_framework`, `upgrade_validator`, `mutation_detector` and the constitution fail open.
   Pick one policy for the control plane.
6. **The 8 orphans.** Revive or delete. `directive_safety_monitor` and `shadow_mode_coordinator`
   are the two that look like genuine capability loss.

---

## Implementation status (2026-08-12)

Steps 1–4 of the consolidation plan are complete and verified against the live database.

**Severity is now per-invocation.** The acceptance test — same tool, different arguments,
different verdict — passes 25/25:

```
INVOCATION            TOOL_SAFETY   RISK       ALLOWED
echo hello            critical      low        yes      <- same tool
rm -rf /              critical      critical   no       <- same tool
DELETE ... WHERE id=3 critical      high       yes
DELETE FROM users     critical      critical   no
```

A matched governance rule now **sets** the risk level; `ToolSafety` is only the prior when
nothing matches. 20 new rules cover destructive filesystem, privilege escalation, remote
code execution, credential paths, egress, process/service control, persistence, DB schema
and unbounded mutation, and safety-infrastructure writes (TOOL_EXECUTION: 10 -> 30).

**Governance session retired** — 293 lines plus `approval_pipeline`, `approval_manager`
and the `/approval` endpoint moved to `archive/governance_session/`. See
[GOVERNANCE_SESSION_RETIRED.md](GOVERNANCE_SESSION_RETIRED.md). Row counts identical
before and after; provably a no-op.

### Corrections to the plan made during implementation

- **`escalate_security_event` was kept, not archived.** It is escalation *notification*,
  not an approval gate, and it sits on a live path from `security_audit_worker`. Its
  `evaluation.approved` bug — which made every security escalation a swallowed
  `AttributeError` — is fixed.
- **The 12-pattern list was kept, not migrated away.** It matches `str(parameters)`, so it
  catches a dangerous string in *any* parameter name; the rules match *named* parameters.
  Different scope, so removing it would have lost coverage. Verified: `rm -rf` hidden in a
  `notes` parameter is still caught.
- **`capabilities.requires_approval()` was left in place.** Semantically obsolete (there is
  no approval gate) but correct and harmless, with 5 test references. Flagged rather than
  churned.
- **ASI is off the tool path.** `ASIActionType["EXECUTE_TOOL"]` raises `KeyError`, pinning
  ASI risk at a constant 0.3000 for every tool call — a value that was then discarded.

### Bugs found and fixed while implementing

| Bug | Effect |
|---|---|
| `is_internal=True` skipped SQLi validation entirely | injection would have passed; fixed at root by narrowing `(--[^\n]*$)` to `['\";]\s*--` |
| One global rate-limit bucket (`'unknown'`, 100/60s) | >100 evaluations/min hard-blocked every tool call |
| Declared pattern severities unpacked and discarded | `subprocess` (MINOR) blocked as hard as `rm -rf` (CRITICAL) |
| `GovernanceBlockError` raised, caught by a broad `except` | **a blocked action would have executed**; blocks now return `(False, evaluation)` |
| `_assess_risk` matched `action_type` | the operation table never fired once — `action_type` is always `"execute_tool"` |

### Retired

`_validate_parameters` (65-line no-op — every append was `... if False else None`) ·
`_sanitize_code`, `_analyze_dependencies` (zero refs) · `filter_profanity` (stub filtering
`badword1`/`badword2`) · the governance session (above).

---

## Appendix: verification status

Claims were verified against source, the import graph, or runtime. The three pre-existing security
documents (2026-02-05) describe the network-defense stack and were not used as a source.
