#!/usr/bin/env python3
"""Constructing a program without a model: learn operators, plan, execute.

    Can the substrate build a working program from demonstrations alone, and
    does the program it builds work on inputs it never saw?

"Writing a program needs a language model" was asserted and is false. A program
is a PLAN, and every piece needed already existed:

    demonstrations -> RuleInducer          learns each operation as an operator
    operators      -> plan_for_state_goal  composes them (the BFS that chained
                                           6-hop MOVE in EDU-01)
    plan           -> OperatorBinding      executes against a real environment
    execution      -> DataWorld.observe    reports what actually happened

THE TEST IS GENERALISATION, NOT SOLVING. Planning against one input is
problem-solving; a program has to work on inputs it was not planned against. So
the operator sequence is discovered ONCE and then run unchanged over held-out
inputs, and it only counts if every one of them is right.

NO MODEL IS INVOLVED AT ANY POINT.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

logging.disable(logging.INFO)
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from core.learning.rule_grounding import ground_for_problem  # noqa: E402
from core.learning.rule_induction import (Fact, TrainingExample,  # noqa: E402
                                          canonical_term, get_rule_inducer)
from core.reasoning.temporal_reasoning import TemporalReasoningSystem  # noqa: E402
from experiments.data_world import DataWorld  # noqa: E402

TAUGHT = {"l1": [2, 4, 6, 8], "l2": [10, 20, 30], "l3": [1, 2, 3, 10]}
HELD_OUT = {"h1": [5, 15, 25, 35], "h2": [7, 7, 7, 100], "h3": [1, 1, 1, 1, 96]}


def _n(v):
    return canonical_term(str(v))


def _world_facts(name, values):
    world = DataWorld().put(name, values)
    return tuple(sorted(world.observe()))


def teach_mean_of():
    """Demonstrations of MEAN_OF, plus the negative that makes the action necessary."""
    examples = []
    for name, values in TAUGHT.items():
        facts = _world_facts(name, values)
        action = Fact("MEAN_OF", (name,))
        mean = sum(values) / len(values)
        examples.append(TrainingExample(
            before=facts + (action,), action=action,
            after=facts + (Fact("VALUE", (_n(mean),)),), positive=True))
        # Without acting, nothing is produced -- otherwise the learner concludes
        # the value appears on its own and the rule is not an operator.
        examples.append(TrainingExample(before=facts, action=None, after=facts,
                                        positive=False))
    return get_rule_inducer().induce(examples, target_predicate="VALUE")


def teach_count_exceeding():
    """Demonstrations of COUNT_EXCEEDING, which consumes a threshold."""
    examples = []
    for name, values in TAUGHT.items():
        facts = _world_facts(name, values)
        mean = sum(values) / len(values)
        threshold = Fact("VALUE", (_n(mean),))
        action = Fact("COUNT_EXCEEDING", (name,))
        count = len([v for v in values if v > mean])
        before = facts + (threshold, action)
        examples.append(TrainingExample(
            before=before, action=action,
            after=before + (Fact("RESULT", (_n(count),)),), positive=True))
        examples.append(TrainingExample(before=facts + (threshold,), action=None,
                                        after=facts + (threshold,), positive=False))
        # The threshold must already exist: acting without it produces nothing.
        examples.append(TrainingExample(before=facts + (action,), action=action,
                                        after=facts, positive=False))
    return get_rule_inducer().induce(examples, target_predicate="RESULT")


def discover_plan(rules, name, values):
    """Find the operator sequence ONCE, against a single input."""
    facts = list(_world_facts(name, values))
    available = [Fact(p, (name,)) for p in ("MEAN_OF", "COUNT_EXCEEDING")]
    mean = sum(values) / len(values)
    expected = len([v for v in values if v > mean])
    goal = [Fact("RESULT", (_n(expected),))]

    grounded = ground_for_problem(rules, facts + available, goal)
    result = TemporalReasoningSystem().plan_for_state_goal(
        [f.to_formula() for f in goal],
        {"conditions": [f.to_formula() for f in (facts + available)]},
        grounded.to_actions())
    steps = [s.get("action") if isinstance(s, dict) else str(s)
             for s in (getattr(result, "steps", None) or [])]
    return str(getattr(result, "status", None)), steps


def run_program(steps, name, values):
    """Execute the discovered sequence against a real environment."""
    world = DataWorld().put(name, values)
    operations = world.operations()
    for step in steps:
        predicate = str(step).split("(")[0].strip()
        operation = operations.get(predicate)
        if operation is None:
            return None, f"no binding for {predicate}"
        operation((name,))
    observed = world.observe() or frozenset()
    results = [f.args[0] for f in observed if f.predicate == "RESULT"]
    return (results[0] if results else None), "ok"


def main() -> int:
    print("EDU-12 — program construction without a model\n")

    mean_rule = teach_mean_of()
    count_rule = teach_count_exceeding()
    for label, result in (("MEAN_OF", mean_rule), ("COUNT_EXCEEDING", count_rule)):
        body = sorted(str(f) for f in result.rule.body) if result.rule else None
        print(f"learned {label:<16} {result.status.value:<20} {body}")
    if not (mean_rule.rule and count_rule.rule):
        print("\nan operator was not learned; nothing to compose")
        return 1

    rules = [mean_rule.rule, count_rule.rule]
    status, steps = discover_plan(rules, "l1", TAUGHT["l1"])
    print(f"\nplan discovered on l1: {status}")
    for step in steps:
        print(f"   {step}")
    if not steps:
        return 1

    print(f"\nrunning that same program on inputs it was never planned against")
    rows, correct = [], 0
    for name, values in HELD_OUT.items():
        mean = sum(values) / len(values)
        expected = len([v for v in values if v > mean])
        produced, note = run_program(steps, name, values)
        ok = produced is not None and float(produced) == float(expected)
        correct += ok
        rows.append({"input": name, "values": values, "expected": expected,
                     "produced": produced, "correct": ok, "note": note})
        print(f"   {name}  {str(values):<20} expected {expected}  produced {produced}  "
              f"{'OK' if ok else 'WRONG'}")

    passed = correct == len(HELD_OUT)
    manifest = Path(__file__).resolve().parent / "program_construction.json"
    manifest.write_text(json.dumps({
        "experiment": "EDU-12 program construction",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "model_calls": 0,
        "taught_on": TAUGHT,
        "learned": {
            "MEAN_OF": sorted(str(f) for f in mean_rule.rule.body),
            "COUNT_EXCEEDING": sorted(str(f) for f in count_rule.rule.body),
        },
        "plan_discovered_on": "l1",
        "plan": steps,
        "held_out": rows,
        "held_out_correct": f"{correct}/{len(HELD_OUT)}",
        "passed": passed,
    }, indent=2, default=str))
    print(f"\nheld-out: {correct}/{len(HELD_OUT)}   model calls: 0")
    print(f"{'PASS' if passed else 'FAIL'}  ->  {manifest.name}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
