#!/usr/bin/env python3
"""Re-deriving the primitives instead of being handed them.

    `data_world` supplies LENGTH, SUM, MEAN and MAXIMUM as observations. Every
    one of those is a fold that somebody else already wrote. Composing them is
    real work and it is not derivation. Can the substrate build them?

WHAT IS TAKEN AWAY. `list_machine` offers a cursor, two registers, a
comparator, an adder and six instructions -- TAKE PASS ACCUM TALLY CLEAR EMIT.
Nothing it observes is a fold. There is no maximum, no total, no count, no
mean, and no way to obtain one except by building it.

FOUR STAGES, EACH WITH A DISTINCT FAILURE.

  1  LEARN THE INSTRUCTION SET. Each instruction is demonstrated and its rule
     induced -- what it requires and what it changes. Nine rules. Anything less
     than RULE_LEARNED here stops the run: a procedure composed out of
     operators the substrate has not determined would be composed out of
     guesses.

  2  DERIVE THE FOLDS FROM INPUT/OUTPUT EVIDENCE ALONE. A list and the number
     required from it. No trace, no algorithm, no demonstration of the
     composition. Lists of at most four elements.

  3  RUN THEM ON LENGTHS NEVER SEEN. 5, 7, 11, 20 and 50, graded against
     Python's own `max`, `sum`, `len` and count. This is the generality claim
     and the only one that matters: a procedure derived on four elements that
     works on fifty is a program; one that does not is a lookup table.

  4  COMPOSE MEAN OUT OF WHAT WAS DERIVED. Total and count come from the
     substrate's OWN derived procedures -- there is no `sum` and no `len`
     under them -- and the planner composes them.

     THE DIVIDER ANNOUNCES NOTHING IN ADVANCE. It did, once: the library
     published the quotient of whatever the registers held, so DIVIDE could
     require it as an ordinary precondition. That made the answer exist before
     the question, and it was the shape of the first attempt at this stage --
     which the planner correctly reported UNREACHABLE the moment the world
     stopped announcing it. What the rule now carries is an OUTPUT, and which
     function produces it was learned from three demonstrations rather than
     written down.

THE MODEL IS LOAD-BEARING AND CHECKED. Every step executes against the machine
and is read back by observation; the learned rule's prediction is compared with
what the world then shows, through `effect_verification`. A run that reaches
the right answer while contradicting its own model is not counted as a success.

NO MODEL IS INVOLVED AT ANY POINT. Asserted from the policy census, not from
the absence of an obvious call site.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

os.environ.setdefault("TORIN_MODEL_POLICY", "strict_model_free")

logging.disable(logging.INFO)

from core.execution.procedure import Operator, Procedure, RunStatus  # noqa: E402
from core.learning.learning_authority import get_learning_authority  # noqa: E402
from core.learning.procedure_synthesis import (IOExample,  # noqa: E402
                                               SynthesisStatus)
from core.learning.rule_grounding import ground_for_problem  # noqa: E402
from core.learning.rule_induction import (Fact, TrainingExample,  # noqa: E402
                                          canonical_term)
from core.model_policy import model_telemetry  # noqa: E402
from core.reasoning.temporal_reasoning import TemporalReasoningSystem  # noqa: E402
from experiments.list_machine import FLAGS, INSTRUCTIONS, ListMachine  # noqa: E402

AUTHORITY = get_learning_authority()

#: Demonstrations of each instruction, as (values, B, instructions run first).
#: Chosen so the observation separates the hypotheses rather than by taste:
#: TAKE is shown once with A invalid, where the machine publishes no adder
#: output at all, which is what distinguishes "A := the value under the cursor"
#: from "A := an adder output"; ACCUM and TALLY are never shown with A at zero
#: or the head at one, where the two adder outputs coincide with each other or
#: with the head. Without those choices induction correctly returns
#: MULTIPLE_HYPOTHESES -- three rules for TAKE, two for EMIT.
DEMONSTRATIONS = {
    "TAKE":  [([3, 9, 7], None, []), ([5, 2, 9], None, ["TAKE"]),
              ([4, 8, 6], None, ["TAKE", "PASS"])],
    "PASS":  [([3, 9, 7], None, []), ([5, 2, 9], None, ["PASS"]),
              ([4, 8, 6], None, ["TAKE"])],
    "ACCUM": [([3, 9, 7], None, ["TAKE"]), ([5, 2, 9], None, ["TAKE", "ACCUM"]),
              ([4, 8, 6], None, ["TAKE"])],
    "TALLY": [([3, 9, 7], None, ["TAKE"]), ([5, 2, 9], None, ["TAKE", "TALLY"]),
              ([4, 8, 6], None, ["TAKE"])],
    "CLEAR": [([3, 9, 7], None, []), ([5, 2, 9], None, ["PASS"]),
              ([4, 8, 6], None, [])],
    "EMIT":  [([3, 9, 7], None, ["TAKE"]), ([5, 2, 9], None, ["TAKE", "ACCUM"]),
              ([4, 8, 6], None, ["TAKE", "PASS"])],
}

#: What each instruction is scoped to explain. A rule may only conclude about
#: terms its body binds, so an instruction is learned once per register it
#: writes rather than once in total.
TARGETS = {
    "TAKE": ["A", "AT"], "PASS": ["AT"], "ACCUM": ["A", "AT"],
    "TALLY": ["A", "AT"], "CLEAR": ["A_UNSET"], "EMIT": ["RESULT"],
}


def term(value) -> str:
    return canonical_term(str(float(value)))


def steps_for(values) -> int:
    return 2 * len(values) + 6


# --------------------------------------------------------------------------
# 1 — the instruction set
# --------------------------------------------------------------------------

def demonstrate(instruction: str) -> List[TrainingExample]:
    """Run the instruction in the machine and record what actually changed."""
    examples: List[TrainingExample] = []
    for values, threshold, prefix in DEMONSTRATIONS[instruction]:
        machine = ListMachine(values, threshold)
        for earlier in prefix:
            if not machine.perform(Fact(earlier, ())):
                raise RuntimeError(f"{instruction}: setup {earlier} was refused")
        before = tuple(sorted(machine.observe()))
        action = Fact(instruction, ())
        if not machine.perform(action):
            raise RuntimeError(f"{instruction} was refused on {values} after {prefix}")
        after = tuple(sorted(machine.observe()))
        examples.append(TrainingExample(before=before + (action,), action=action,
                                        after=after + (action,), positive=True))
        # Nothing happens without acting. Without this the learner may conclude
        # the register changes on its own, and the rule is not an operator.
        examples.append(TrainingExample(before=before, action=None, after=before,
                                        positive=False))
    return examples


def learn_instructions():
    operators, report = [], []
    for instruction in INSTRUCTIONS:
        examples = demonstrate(instruction)
        rules = []
        for target in TARGETS[instruction]:
            result = AUTHORITY.induce(examples, target_predicate=target)
            report.append({"instruction": instruction, "explains": target,
                           "status": result.status.value,
                           "rule": str(result.rule) if result.rule else None,
                           "candidates": len(result.candidates)})
            if result.rule is None:
                return None, report
            rules.append(result.rule)
        operators.append(Operator(action=Fact(instruction, ()), rules=tuple(rules)))
    return operators, report


# --------------------------------------------------------------------------
# 2 — derive the folds from what they must produce
# --------------------------------------------------------------------------

def example(values, expected, threshold=None) -> IOExample:
    label = f"{values}" + (f" | B={threshold}" if threshold is not None else "")
    return IOExample(
        label=label,
        build=lambda v=list(values), b=threshold: ListMachine(v, b),
        expected=term(expected),
        max_steps=steps_for(values))


#: Input/output evidence. Nothing longer than four elements, and each set
#: carries the case that separates the near-misses:
#:   MAXIMUM   an all-negative list. Without it "start the accumulator at zero
#:             and take anything larger" fits every example and is wrong.
#:   SUM/LENGTH the empty list. Without it "seed the accumulator with the first
#:             element" fits and has no answer for an empty input.
EVIDENCE = {
    "MAXIMUM": ([([3, 9, 7], 9), ([9, 3, 7], 9), ([5, 2, 8], 8), ([-5, -2, -9], -2)],
                None, max),
    "SUM": ([([3, 9, 7], 19), ([5, 2], 7), ([], 0), ([-4, 6], 2)], None, sum),
    "LENGTH": ([([3, 9, 7], 3), ([5], 1), ([], 0), ([4, 8, 6, 2], 4)], None, len),
    "EXCEEDING": ([([3, 9, 7], 2), ([1, 2, 3], 0), ([], 0), ([9, 9], 2)], 5,
                  lambda v, t=5: len([x for x in v if x > t])),
}


def derive_folds(operators):
    guards = tuple(Fact(flag, ()) for flag in FLAGS)
    derived, report = {}, []
    for name, (pairs, threshold, _) in EVIDENCE.items():
        result = AUTHORITY.derive_procedure(
            operators, guards,
            [example(values, expected, threshold) for values, expected in pairs])
        report.append({
            "fold": name, "status": result.status.value, "size": result.size,
            "candidates_run": result.candidates_run,
            "evidence": [f"{v} -> {e}" for v, e in pairs],
            "procedures": [[str(s) for s in p.steps] for p in result.procedures],
            "detail": result.detail,
        })
        if result.status in (SynthesisStatus.PROCEDURE_DERIVED,
                             SynthesisStatus.MULTIPLE_PROCEDURES):
            derived[name] = result
    return derived, report


# --------------------------------------------------------------------------
# 3 — run them on lengths never seen
# --------------------------------------------------------------------------

def held_out(length: int) -> List[int]:
    """A deterministic spread including negatives, repeats and a run of equals."""
    return [((index * 37 + 11) % 97) - 40 for index in range(length)]


HELD_OUT_LENGTHS = (5, 7, 11, 20, 50)
THRESHOLD = 5


def validate(name: str, procedure: Procedure, oracle) -> Dict:
    rows, correct, contradicted = [], 0, 0
    for length in HELD_OUT_LENGTHS:
        values = held_out(length)
        if name == "MAXIMUM" and not values:
            continue
        expected = oracle(values)
        threshold = THRESHOLD if name == "EXCEEDING" else None
        machine = ListMachine(values, threshold)
        outcome = procedure.run(machine, steps_for(values))
        produced = (float(outcome.answer.args[0])
                    if outcome.produced_answer else None)
        ok = produced is not None and produced == float(expected)
        correct += ok
        contradicted += len(outcome.contradictions)
        rows.append({"length": length, "expected": float(expected),
                     "produced": produced, "correct": ok,
                     "status": outcome.status.value,
                     "machine_steps": outcome.steps_taken,
                     "model_contradictions": len(outcome.contradictions)})
    return {"fold": name, "correct": correct, "of": len(rows),
            "model_contradictions": contradicted, "runs": rows}


# --------------------------------------------------------------------------
# 4 — compose MEAN from what was derived
# --------------------------------------------------------------------------

class DerivedLibrary:
    """A world whose observations are computed by the substrate's own folds.

    `TOTAL_OF` and `COUNT_OF` are not `sum` and `len`. Reading either one runs
    the procedure the substrate derived in stage 2, on a fresh machine, and
    reports what that procedure produced. The composition above is therefore
    standing on derived code the whole way down -- which is the difference
    between this and `data_world`, where the same two observations were
    Python's.

    NOTHING HERE PUBLISHES A QUOTIENT. The registers are observable and their
    ratio is not: what dividing them yields is the action's business, and an
    operator that had to read the answer out of the world before acting could
    never have composed a computation at all.
    """

    def __init__(self, folds: Dict[str, Procedure]):
        self.folds = folds
        self.collections: Dict[str, List[float]] = {}
        self.numerator: Optional[float] = None
        self.denominator: Optional[float] = None
        self.results: List[float] = []

    def put(self, name: str, values: Sequence[float]) -> "DerivedLibrary":
        self.collections[name] = [float(v) for v in values]
        return self

    def _run(self, fold: str, values: Sequence[float]) -> Optional[float]:
        outcome = self.folds[fold].run(ListMachine(values), steps_for(values))
        return float(outcome.answer.args[0]) if outcome.produced_answer else None

    def observe(self):
        if not self.collections:
            return None
        facts = set()
        for name, values in self.collections.items():
            facts.add(Fact("LIST", (name,)))
            total, count = self._run("SUM", values), self._run("LENGTH", values)
            if total is not None:
                facts.add(Fact("TOTAL_OF", (name, term(total))))
            if count is not None:
                facts.add(Fact("COUNT_OF", (name, term(count))))
        if self.numerator is not None:
            facts.add(Fact("NUMERATOR", (term(self.numerator),)))
        if self.denominator is not None:
            facts.add(Fact("DENOMINATOR", (term(self.denominator),)))
        for value in self.results:
            facts.add(Fact("RESULT", (term(value),)))
        return frozenset(facts)

    def take_total(self, name: str) -> bool:
        value = self._run("SUM", self.collections.get(name, []))
        if value is None:
            return False
        self.numerator = value
        return True

    def take_count(self, name: str) -> bool:
        value = self._run("LENGTH", self.collections.get(name, []))
        if value is None:
            return False
        self.denominator = value
        return True

    def divide(self, name: str) -> bool:
        if self.numerator is None or self.denominator in (None, 0.0):
            return False
        self.results.append(self.numerator / self.denominator)
        return True

    def operations(self):
        return {"TAKE_TOTAL": self.take_total, "TAKE_COUNT": self.take_count,
                "DIVIDE": self.divide}


COMPOSITION_TAUGHT = {"c1": [2, 4, 6, 8], "c2": [10, 20, 30], "c3": [1, 2, 3, 10]}

#: The list is REPLACED after the registers are loaded, so a demonstration of
#: DIVIDE holds a numerator that is not this list's total and a denominator
#: that is not its count. Without that, "divide the numerator by the
#: denominator" and "divide the total by the count" are the same claim on every
#: demonstration and induction reports both, correctly.
SWAPPED = {"c1": "c2", "c2": "c3", "c3": "c1"}


def teach_composition(folds):
    """Learn TAKE_TOTAL, TAKE_COUNT and DIVIDE as operators over the library."""
    learned, report = [], []
    plans = {"TAKE_TOTAL": ("NUMERATOR", []), "TAKE_COUNT": ("DENOMINATOR", ["TAKE_TOTAL"]),
             "DIVIDE": ("RESULT", ["TAKE_TOTAL", "TAKE_COUNT"])}
    for operation, (target, prefix) in plans.items():
        examples = []
        for name, values in COMPOSITION_TAUGHT.items():
            world = DerivedLibrary(folds).put(name, values)
            for earlier in prefix:
                world.operations()[earlier](name)
            if operation == "DIVIDE":
                world.put(name, COMPOSITION_TAUGHT[SWAPPED[name]])
            before = tuple(sorted(world.observe()))
            # The divider takes no list: it works on the registers, and giving
            # it an argument nothing constrains puts a meaningless term in the
            # plan -- DIVIDE(20) reads as dividing the number twenty.
            action = Fact(operation, () if operation == "DIVIDE" else (name,))
            if not world.operations()[operation](name):
                raise RuntimeError(f"{operation} was refused on {name}")
            after = tuple(sorted(world.observe()))
            examples.append(TrainingExample(before=before + (action,), action=action,
                                            after=after + (action,), positive=True))
            examples.append(TrainingExample(before=before, action=None, after=before,
                                            positive=False))
        result = AUTHORITY.induce(examples, target_predicate=target)
        report.append({"operation": operation, "explains": target,
                       "status": result.status.value,
                       "rule": str(result.rule) if result.rule else None,
                       "produces": [str(o) for o in (result.rule.outputs if result.rule else ())]})
        if result.rule is None:
            return None, report
        learned.append(result.rule)
    return learned, report


def compose_mean(folds, rules):
    """Discover the composition once, then run it on inputs it never saw."""
    name, values = "c1", COMPOSITION_TAUGHT["c1"]
    world = DerivedLibrary(folds).put(name, values)
    state = list(world.observe())
    available = [Fact(op, () if op == "DIVIDE" else (name,))
                 for op in world.operations()]
    goal = [Fact("RESULT", (term(sum(values) / len(values)),))]

    grounded = ground_for_problem(rules, state + available, goal)
    result = TemporalReasoningSystem().plan_for_state_goal(
        [f.to_formula() for f in goal],
        {"conditions": [f.to_formula() for f in (state + available)]},
        grounded.to_actions())
    steps = [s.get("action") if isinstance(s, dict) else str(s)
             for s in (getattr(result, "steps", None) or [])]
    return {"status": str(getattr(result, "status", None)),
            "guarantee": result.guarantee.value,
            "grounding_complete": grounded.complete,
            "operators": len(grounded.operators)}, steps


def run_composition(folds, steps, values) -> Optional[float]:
    world = DerivedLibrary(folds).put("h", values)
    operations = world.operations()
    for step in steps:
        operation = operations.get(str(step).split("(")[0].strip())
        if operation is None or not operation("h"):
            return None
    observed = world.observe() or frozenset()
    produced = [f.args[0] for f in observed if f.predicate == "RESULT"]
    return float(produced[0]) if produced else None


# --------------------------------------------------------------------------

def main() -> int:
    print("EDU-12 — re-deriving the primitives\n")

    operators, instruction_report = learn_instructions()
    for row in instruction_report:
        print(f"  {row['instruction']:<6} explains {row['explains']:<8} "
              f"{row['status']:<20} {row['rule'] or ''}")
    if operators is None:
        print("\nan instruction was not determined; nothing may be composed out of it")
        return 1

    print()
    derived, fold_report = derive_folds(operators)
    for row in fold_report:
        print(f"  {row['fold']:<10} {row['status']:<22} size={row['size']} "
              f"candidates_run={row['candidates_run']}")
        for procedure in row["procedures"]:
            print(f"      {' | '.join(procedure)}")
    missing = [name for name in EVIDENCE if name not in derived]
    if missing:
        print(f"\nnot derived: {missing}")
        return 1

    print(f"\nheld-out lengths {HELD_OUT_LENGTHS} — none of them trained on")
    validations, all_correct = [], True
    for name, (_, _, oracle) in EVIDENCE.items():
        for index, procedure in enumerate(derived[name].procedures):
            row = validate(name, procedure, oracle)
            row["procedure_index"] = index
            validations.append(row)
            all_correct &= row["correct"] == row["of"] and not row["model_contradictions"]
            suffix = f" [{index + 1} of {len(derived[name].procedures)}]" if len(
                derived[name].procedures) > 1 else ""
            print(f"  {name + suffix:<16} {row['correct']}/{row['of']}   "
                  f"model contradictions {row['model_contradictions']}")

    agreement = {}
    for name, result in derived.items():
        if len(result.procedures) > 1:
            answers = [tuple(r["produced"] for r in v["runs"])
                       for v in validations if v["fold"] == name]
            agreement[name] = len(set(answers)) == 1
            print(f"  {name}: {len(result.procedures)} procedures fit the evidence; "
                  f"they {'agree' if agreement[name] else 'DISAGREE'} on every held-out input")

    folds = {name: result.procedures[0] for name, result in derived.items()}
    composition_rules, composition_report = teach_composition(folds)
    print()
    for row in composition_report:
        print(f"  {row['operation']:<12} {row['status']:<20} {row['rule'] or ''}")
    if composition_rules is None:
        print("\na composition operator was not determined")
        return 1

    status, plan = compose_mean(folds, composition_rules)
    print(f"\n  MEAN composed by the planner: {status['status']} "
          f"({status['guarantee']}, {status['operators']} operator(s), "
          f"grounding complete={status['grounding_complete']})")
    for step in plan:
        print(f"      {step}")

    mean_rows, mean_correct = [], 0
    for length in HELD_OUT_LENGTHS:
        values = held_out(length)
        expected = sum(values) / len(values)
        produced = run_composition(folds, plan, values)
        ok = produced is not None and abs(produced - expected) < 1e-9
        mean_correct += ok
        mean_rows.append({"length": length, "expected": expected,
                          "produced": produced, "correct": ok})
        print(f"      length {length:<3} expected {expected:<10.4f} "
              f"produced {produced}  {'OK' if ok else 'WRONG'}")

    telemetry = model_telemetry()
    passed = (all_correct and mean_correct == len(mean_rows)
              and telemetry["attempts"] == 0 and telemetry["executed"] == 0
              and all(agreement.values()))

    manifest = Path(__file__).resolve().parent / "rederivation.json"
    manifest.write_text(json.dumps({
        "experiment": "EDU-12 re-derivation of the primitives",
        "question": ("can the substrate build LENGTH, SUM, MEAN, MAXIMUM and a "
                     "count over a threshold out of a cursor, two registers, a "
                     "comparator and an adder"),
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "model": telemetry,
        "instruction_set": instruction_report,
        "derivation": fold_report,
        "held_out_lengths": list(HELD_OUT_LENGTHS),
        "held_out_validation": validations,
        "underdetermined_folds_agree": agreement,
        "composition": {"operators": composition_report, "plan_status": status,
                        "plan": plan, "held_out": mean_rows,
                        "correct": f"{mean_correct}/{len(mean_rows)}"},
        "passed": passed,
    }, indent=2, default=str))

    print(f"\nmodel attempts {telemetry['attempts']}, executed {telemetry['executed']}")
    print(f"{'PASS' if passed else 'FAIL'}  ->  {manifest.name}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
