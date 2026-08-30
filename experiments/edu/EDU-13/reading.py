#!/usr/bin/env python3
"""EDU-13 — deriving a reading instead of writing one.

    The deterministic formalizer is six regular expressions. Can the substrate
    derive a seventh from sentence/meaning pairs, and read sentences nobody
    wrote a pattern for?

`Formalization.requires_model` exists to measure the substrate-native share of
reading "as the deterministic extractor grows". It never grew: every form it
handles is a person writing a regex, and every form it does not handle is
unrepresentable rather than unlearned.

A READING IS A PROGRAM OVER A SEQUENCE. That is what `list_machine` and
`procedure_synthesis` established this substrate can derive from input/output
pairs alone, so nothing new is needed to try it on words:

    1  LEARN THE INSTRUCTION SET from demonstrations in the machine.
    2  DERIVE THE READING from sentence/meaning pairs. No trace, no grammar,
       no rule about determiners -- a sentence and what it means.
    3  READ SENTENCES NEVER SEEN, with words never seen, and compare against
       the six-regex extractor where it has an opinion.

TWO CONSTRUCTIONS, ONE PROCEDURE. Affirmative and negated readings are derived
together rather than dispatched between, which is the open question about
whether this scales: a grammar is much larger than five rules, and if every
construction needs its own procedure then something has to choose between them.

WHAT IS SUPPLIED AND WHAT IS DERIVED. The machine holds a six-word lexicon and
publishes a class for the word under the cursor. Word CLASS is given. Which
class matters, where, in what order, and what to do about it is derived. That
is the honest boundary and it is the next thing to attack.

NO MODEL IS INVOLVED AT ANY POINT.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
os.environ.setdefault("TORIN_MODEL_POLICY", "strict_model_free")
logging.disable(logging.INFO)

from core.execution.procedure import Operator  # noqa: E402
from core.learning.learning_authority import get_learning_authority  # noqa: E402
from core.learning.procedure_synthesis import SynthesisStatus  # noqa: E402
from core.learning.procedure_synthesis import IOExample  # noqa: E402
from core.learning.rule_induction import Fact, TrainingExample  # noqa: E402
from core.model_policy import model_telemetry  # noqa: E402
from experiments.sentence_machine import (AFFIRMS, DENIES, FLAGS,  # noqa: E402
                                          INSTRUCTIONS, SentenceMachine)

AUTHORITY = get_learning_authority()

#: Demonstrations of each instruction: (sentence, instructions run first).
DEMONSTRATIONS = {
    "BIND_SUBJECT": [("robin is a bird", []), ("vault holds gold", []),
                     ("the cat sees a dog", ["SKIP"])],
    "BIND_OBJECT": [("robin is a bird", ["BIND_SUBJECT", "SKIP", "SKIP"]),
                    ("vault holds gold", ["BIND_SUBJECT", "SKIP"]),
                    ("the cat sees a dog", ["SKIP", "BIND_SUBJECT", "SKIP", "SKIP"])],
    "MARK_NEGATIVE": [("robin is not a mammal", ["BIND_SUBJECT", "SKIP"]),
                      ("gold is not cheap", ["BIND_SUBJECT", "SKIP"]),
                      ("the cat is not a dog", ["SKIP", "BIND_SUBJECT", "SKIP"])],
    "SKIP": [("robin is a bird", ["BIND_SUBJECT"]),
             ("vault holds gold", ["BIND_SUBJECT"]),
             ("the cat sees a dog", [])],
    "EMIT": [("robin is a bird", ["BIND_SUBJECT", "SKIP", "SKIP", "BIND_OBJECT"]),
             ("vault holds gold", ["BIND_SUBJECT", "SKIP", "BIND_OBJECT"]),
             ("the cat is not a dog",
              ["SKIP", "BIND_SUBJECT", "SKIP", "MARK_NEGATIVE", "SKIP", "BIND_OBJECT"])],
}

#: What each instruction is scoped to explain -- one induction per register it
#: writes, because a rule may only conclude about terms its body binds.
TARGETS = {
    "BIND_SUBJECT": ["SUBJECT", "AT"], "BIND_OBJECT": ["OBJECT", "AT"],
    "MARK_NEGATIVE": ["POLARITY", "AT"], "SKIP": ["AT"], "EMIT": ["READING"],
}

#: Sentence, and what it means. Chosen to force the reading rather than to
#: flatter it: a bare subject and one behind a determiner, an affirmative and a
#: negation, so no policy that ignores word class can fit them all.
TAUGHT = [
    ("robin is a bird", ("robin", "bird", AFFIRMS)),
    ("the vault is locked", ("vault", "locked", AFFIRMS)),
    ("a dog is an animal", ("dog", "animal", AFFIRMS)),
    ("robin is not a mammal", ("robin", "mammal", DENIES)),
    ("the engine is not cold", ("engine", "cold", DENIES)),
]

#: Never used in the derivation. Every content word here is new.
HELD_OUT = [
    ("sparrow is a bird", ("sparrow", "bird", AFFIRMS)),
    ("the turbine is hot", ("turbine", "hot", AFFIRMS)),
    ("an ostrich is a bird", ("ostrich", "bird", AFFIRMS)),
    ("mercury is a metal", ("mercury", "metal", AFFIRMS)),
    ("a whale is not a fish", ("whale", "fish", DENIES)),
    ("the ledger is not balanced", ("ledger", "balanced", DENIES)),
    ("copper is not brittle", ("copper", "brittle", DENIES)),
]

MAX_RULES = 6


def demonstrate(instruction):
    examples = []
    for sentence, prefix in DEMONSTRATIONS[instruction]:
        machine = SentenceMachine(sentence)
        for earlier in prefix:
            if not machine.perform(Fact(earlier, ())):
                raise RuntimeError(f"{instruction}: setup {earlier} refused on {sentence!r}")
        before = tuple(sorted(machine.observe()))
        action = Fact(instruction, ())
        if not machine.perform(action):
            raise RuntimeError(f"{instruction} refused on {sentence!r} after {prefix}")
        after = tuple(sorted(machine.observe()))
        examples.append(TrainingExample(before=before + (action,), action=action,
                                        after=after + (action,), positive=True))
        # Nothing happens without acting.
        examples.append(TrainingExample(before=before, action=None, after=before,
                                        positive=False))
    return examples


def learn_instructions():
    operators, report = [], []
    # Iterate what has been DEMONSTRATED, not every machine instruction: the
    # machine may carry operators this experiment does not teach (EXTEND_*),
    # and a reading is composed only from operators it was shown.
    for instruction in DEMONSTRATIONS:
        examples = demonstrate(instruction)
        rules = []
        for target in TARGETS[instruction]:
            result = AUTHORITY.induce(examples, target_predicate=target)
            report.append({"instruction": instruction, "explains": target,
                           "status": result.status.value,
                           "rule": str(result.rule) if result.rule else None})
            if result.rule is None:
                return None, report
            rules.append(result.rule)
        operators.append(Operator(action=Fact(instruction, ()), rules=tuple(rules)))
    return operators, report


def budget(sentence):
    return 2 * len(SentenceMachine(sentence).words) + 6


def read(procedure, sentence):
    machine = SentenceMachine(sentence)
    outcome = procedure.run(machine, budget(sentence))
    return (tuple(outcome.answer.args) if outcome.produced_answer else None,
            outcome.status.value)


def main() -> int:
    print("EDU-13 — deriving a reading\n")

    operators, instruction_report = learn_instructions()
    for row in instruction_report:
        print(f"  {row['instruction']:<14} explains {row['explains']:<8} "
              f"{row['status']:<20} {row['rule'] or ''}")
    if operators is None:
        print("\nan instruction was not determined; nothing may be composed out of it")
        return 1

    guards = tuple(Fact(flag, ()) for flag in FLAGS)
    result = AUTHORITY.derive_procedure(
        operators, guards,
        [IOExample(label=s, build=lambda t=s: SentenceMachine(t), expected=m,
                   max_steps=budget(s)) for s, m in TAUGHT],
        terminal="READING", max_rules=MAX_RULES)

    print(f"\n  derivation: {result.status.value}   size={result.size}   "
          f"candidates_run={result.candidates_run}")
    for procedure in result.procedures:
        print("     " + " | ".join(str(step) for step in procedure.steps))
    if result.status not in (SynthesisStatus.PROCEDURE_DERIVED,
                             SynthesisStatus.MULTIPLE_PROCEDURES):
        print(f"\n  {result.detail}")
        return 1

    print(f"\n  reading {len(HELD_OUT)} sentences never used in the derivation, "
          f"every content word new")
    rows, agree = [], []
    for index, procedure in enumerate(result.procedures):
        correct = 0
        answers = []
        for sentence, meaning in HELD_OUT:
            produced, status = read(procedure, sentence)
            ok = produced == meaning
            correct += ok
            answers.append(produced)
            if index == 0:
                rows.append({"sentence": sentence, "expected": list(meaning),
                             "produced": list(produced) if produced else None,
                             "correct": ok, "status": status})
                print(f"     {sentence:<32} -> {str(produced):<34} "
                      f"{'OK' if ok else 'expected ' + str(meaning)}")
        agree.append(tuple(answers))
        if index == 0:
            first_correct = correct
    all_agree = len(set(agree)) == 1
    if len(result.procedures) > 1:
        print(f"\n  {len(result.procedures)} procedures fit the evidence; they "
              f"{'agree' if all_agree else 'DISAGREE'} on every held-out sentence")

    telemetry = model_telemetry()
    passed = (first_correct == len(HELD_OUT) and all_agree
              and telemetry["attempts"] == 0 and telemetry["executed"] == 0)

    manifest = Path(__file__).resolve().parent / "reading.json"
    manifest.write_text(json.dumps({
        "experiment": "EDU-13 deriving a reading",
        "question": ("can the substrate derive a sentence reading from "
                     "sentence/meaning pairs, and read sentences nobody wrote a "
                     "pattern for"),
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "model": telemetry,
        "supplied": {"lexicon": "six words, classed as copula / determiner / negator",
                     "derived": "which class matters, where, in what order, and "
                                "what to do about it"},
        "instruction_set": instruction_report,
        "taught_on": [{"sentence": s, "meaning": list(m)} for s, m in TAUGHT],
        "derivation": {"status": result.status.value, "size": result.size,
                       "candidates_run": result.candidates_run,
                       "procedures": [[str(st) for st in p.steps]
                                      for p in result.procedures],
                       "detail": result.detail},
        "held_out": rows,
        "held_out_correct": f"{first_correct}/{len(HELD_OUT)}",
        "procedures_agree_on_held_out": all_agree,
        "passed": passed,
    }, indent=2, default=str))

    print(f"\n  held-out: {first_correct}/{len(HELD_OUT)}   "
          f"model attempts {telemetry['attempts']}, executed {telemetry['executed']}")
    print(f"{'PASS' if passed else 'FAIL'}  ->  {manifest.name}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
