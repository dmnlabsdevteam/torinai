#!/usr/bin/env python3
"""Run the frozen KITE evaluation against whatever substrate this process finds.

One condition of the ablation, executed in its own OS process so that no
singleton rule cache, warm connection pool or module-level residue can carry a
capability across a condition boundary. The process is told which substrate to
read through POSTGRES_DATABASE and nothing else.

Two policies are asserted, not assumed:

    STRICT_MODEL_FREE   no learned model may be consulted
    FROZEN              no rule may be induced, persisted or validated

The second is what makes a negative result meaningful. Without it, the
condition with its learned rules removed could re-derive them from anything
still reachable and report the capability intact, which would look exactly like
the ablation having no effect.

Emits one JSON object on stdout. Everything else goes to stderr, so the
orchestrator can keep the full log and still parse the result.

    POSTGRES_DATABASE=clone python3 experiments/kite_evaluate.py --condition FULL
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Both policies are set before any substrate module is imported, so no import
# side effect can perform the work these forbid.
os.environ.setdefault("TORIN_MODEL_POLICY", "strict_model_free")
os.environ.setdefault("TORIN_LEARNING_POLICY", "frozen")

from core.learning.learning_policy import (  # noqa: E402
    LearningPolicy, get_learning_policy,
)
from core.learning.rule_induction import (  # noqa: E402
    Fact, TrainingExample, applies, successor_state,
)
from core.learning.rule_store import EpistemicStatus, RuleStore  # noqa: E402
from core.model_policy import (  # noqa: E402
    ModelPolicy, get_model_policy, model_telemetry,
)

SUITE = Path(__file__).resolve().parent / "kite_evaluation_suite.json"
DOMAIN = "kite17"


def facts(items):
    return frozenset(Fact.parse(item) for item in items)


def derive(rules, state):
    """Every effect instance the executable rules assert for this state."""
    return [instance for rule in rules for instance in applies(
        rule, TrainingExample(before=tuple(state), action=None))]


def run_derive(rules, case):
    state = facts(case["state"])
    added = sorted(str(f) for instance in derive(rules, state) for f in instance.add)
    expected = sorted(case["expect_add"])
    return {
        "id": case["id"], "kind": "derive", "derived": added, "expected": expected,
        "passed": added == expected,
        "no_derivation": not added,
    }


def run_sequence(rules, case):
    state = facts(case["state"])
    for step in case["steps"]:
        # The action is a fact in the state for the step it is taken, then
        # retracted, so a later step cannot fire on a stale action.
        action = Fact.parse(step)
        stepped = state | {action}
        state = successor_state(stepped, derive(rules, stepped)) - {action}

    present = sorted(str(f) for f in state)
    missing = [f for f in case["expect_present"] if f not in present]
    lingering = [f for f in case["expect_absent"] if f in present]
    return {
        "id": case["id"], "kind": "sequence", "final_state": present,
        "expect_present": case["expect_present"], "expect_absent": case["expect_absent"],
        "passed": not missing and not lingering,
        "missing": missing, "lingering": lingering,
        "no_derivation": not any(
            str(f) in present for f in facts(case["expect_present"])
        ),
    }


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--condition", required=True)
    args = parser.parse_args()

    logging.getLogger().setLevel(logging.ERROR)

    # The database is passed to the constructor, not left to the environment.
    # TorinUnifiedDatabasePostgres loads .env.postgres with override=True BEFORE
    # reading POSTGRES_DATABASE, so an externally-set value is clobbered by the
    # file and every condition would silently evaluate the live substrate --
    # which is exactly the null result that first came back from this harness.
    from core.database.unified_database_postgres import TorinUnifiedDatabasePostgres

    requested = os.environ["POSTGRES_DATABASE"]
    manager = TorinUnifiedDatabasePostgres(database=requested)

    # Asked of the server, before a single case runs. Configuration agreeing
    # with itself is not evidence: the first run of this experiment had every
    # condition report success against a database none of them had ablated.
    connected = await manager.assert_database_identity(requested)

    store = RuleStore(db_manager=manager)
    all_rules = await store.load(domain_id=DOMAIN)
    executable = [r for r in all_rules if r.status is EpistemicStatus.VALIDATED]

    suite = json.loads(SUITE.read_text())
    rules = [r.rule for r in executable]
    results = [
        run_derive(rules, case) if case["kind"] == "derive" else run_sequence(rules, case)
        for case in suite["cases"]
    ]

    telemetry = model_telemetry()
    report = {
        "condition": args.condition,
        "database": {
            "requested": requested,
            "connected": connected,
            "configuration_source": manager.config.provenance.get("database"),
        },
        "pid": os.getpid(),
        "suite_version": suite["suite_version"],
        "policies": {
            "model": get_model_policy().value,
            "learning": get_learning_policy().value,
        },
        "loader": {
            "rules_available": len(all_rules),
            "rules_executable": len(executable),
            "rule_ids_loaded": sorted(r.rule_id for r in executable),
            "by_status": {
                status.value: sum(1 for r in all_rules if r.status is status)
                for status in EpistemicStatus
            },
        },
        "cases": results,
        "passed": sum(1 for r in results if r["passed"]),
        "total": len(results),
        "model": {
            "attempts": telemetry["attempts"],
            "executed": telemetry["executed"],
            "blocked": telemetry["blocked"],
        },
    }

    # Asserted rather than trusted: a condition that ran with either policy
    # relaxed proves nothing, and must not be quietly folded into the results.
    assert report["policies"]["model"] == ModelPolicy.STRICT_MODEL_FREE.value
    assert report["policies"]["learning"] == LearningPolicy.FROZEN.value

    print(json.dumps(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
