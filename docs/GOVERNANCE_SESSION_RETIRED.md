# Governance Session — Retired

**Date**: 2026-08-12
**Archived to**: `TorinAI/archive/governance_session/`

## What it was

A human-in-the-loop approval model. Actions were classified into decision tiers
(ROUTINE / IMPORTANT / CRITICAL); anything above ROUTINE routed to an approval queue,
sent a Slack request, and waited for a human decision. The design also specified a
multi-judge panel — `"ai_judge_count": 5`, `"approval_mechanism": "Full 11-phase
governance session with multi-judge panel"`.

## Why it was retired

**It contradicts the architecture.** TorinAI's Singleton retains full tool autonomy by
design. Safety's role is to score and record actions and hand the assessment back as
context the agent reasons over — not to gate execution behind human approval. A system
whose purpose was to block was always going to sit unused.

**It was already dead, and could not have run.** All four `GovernanceDecision(...)`
constructions passed `ai_judge_votes=`, a field the dataclass does not declare — every
path raised `TypeError`. The multi-judge field had been removed and the handlers never
updated, because nothing called them. `make_decision()` had zero callers repo-wide.

## What was archived

| Artifact | Origin |
|---|---|
| `unified_governance_session.py` | `GovernanceDecision`, `make_decision`, the three tier handlers, and two exception classes — 293 lines extracted from `core/governance/unified_governance_trigger_system.py` |
| `approval_pipeline.py` | `core/integration/` — Slack request/await |
| `approval_manager.py` | `core/integration/` — pending-approval store and timeouts |
| `approval_endpoint.py` | the `/approval` route from `core/api/chat_server.py` |
| `governance_triggers_session_keys.json` | the `decision_tiers` and `escalation_categories` blocks |

## What was deliberately kept

**The rule-matching engine.** `config/governance_triggers.json`'s `action_categories` and
the matcher in `unified_governance_trigger_system.py` are the only mechanism in the
codebase that assigns severity from *parameter values* rather than from which tool was
used — the only thing that can distinguish `echo hello` from `rm -rf /`. It is now the
designated home for per-invocation safety rules.

**`escalate_security_event()`.** Reclassified as notification rather than approval: it
tells a human that something happened, it does not ask permission. It was also fixed —
it read `evaluation.approved`, which does not exist on `GovernanceTriggerEvaluation`,
so every security escalation had been a silently-swallowed `AttributeError`.

**Per-trigger `escalation_category`.** The top-level dictionary was inert, but the
per-trigger string is read at evaluation time and is live on all 36 triggers.

**`enforcement_mode_manager`** (a real dependency of `evaluate_action`) and
**`shadow_mode_coordinator`** (consumes evaluations only).

## Verification

Removal was confirmed to be a no-op: `safety_assessments` and `governance_audit_log` row
counts were identical before and after (8 / 15), all touched modules import cleanly, and
the full safety test suite passes unchanged.

The one capability that would have been lost — `governance_audit_log` was written *only*
from the session path — is already covered, because `safety_framework._persist_evaluation()`
mirrors every evaluation into that same table.
