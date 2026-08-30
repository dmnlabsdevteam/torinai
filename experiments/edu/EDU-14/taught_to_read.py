#!/usr/bin/env python3
"""EDU-14 — can a language model teach the substrate to read?

    The model knows what sentences mean. The substrate cannot ask it at
    runtime without becoming dependent on it. Can the model hand over what it
    knows, once, and then be removed?

EDU-13 derived a reading from sentence/meaning pairs that a person wrote down.
Here the pairs come from the model, and the person writes nothing. Four phases,
and the third is the claim:

    TEACH     the model proposes what each of five sentences asserts. Model
              calls are permitted and counted.
    DERIVE    the reading is derived from those proposals alone, under a policy
              that BLOCKS the model. The answer key is not used.
    READ      sentences the derivation never saw, graded against a key the
              model never supplied, with the model still blocked. Any reach for
              it would be counted as a blocked attempt rather than silently
              succeeding.
    REFUSE    the same derivation from a teacher that is WRONG. A model may be
              confidently mistaken, and the thing that must not happen is a
              mistaken teacher becoming a confident substrate.

WHAT THE MODEL MAY AND MAY NOT DO. It proposes; it never attests. Every
proposal is parsed strictly and a malformed one is DECLINED rather than
repaired into something plausible -- `llm_teacher` states the reason: guessing
at malformed output is how a model's mistake becomes the substrate's belief.
Nothing the model says is evidence about the world; it is evidence about what a
sentence means, and the reading derived from it has to survive sentences the
model never saw.

THE NUMBER THAT MATTERS is the ratio: five sentences taught, and how many
never-taught sentences the substrate then reads with the teacher gone. If those
are equal, the model handed over answers. If the second is larger, the
substrate acquired a rule.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "EDU-13"))
logging.disable(logging.INFO)

from core.execution.procedure import Operator  # noqa: E402
from core.learning.procedure_synthesis import (IOExample,  # noqa: E402
                                               SynthesisStatus,
                                               derive_procedure)
from core.learning.rule_induction import Fact, get_rule_inducer  # noqa: E402
from core.model_policy import (ModelPolicy, model_telemetry,  # noqa: E402
                               reset_model_telemetry, set_model_policy)
from core.services.unified_llm import UnifiedLLMService  # noqa: E402
from experiments.sentence_machine import (FLAGS, INSTRUCTIONS,  # noqa: E402
                                          SentenceMachine)
from reading import TARGETS, budget, demonstrate  # noqa: E402

SYSTEM = ("You state what a sentence asserts, as a subject, an object and a polarity. "
          "Each of subject and object must be exactly ONE word taken from the sentence, "
          "with no article. Polarity is affirms or denies. "
          "Reply with one line and nothing else, in the form: subject | object | polarity")

#: Strict. Three fields, each a single token, polarity from a closed set.
#: Anything else is declined -- never repaired.
PROPOSAL = re.compile(
    r"^\s*([a-z][a-z0-9_]*)\s*\|\s*([a-z][a-z0-9_]*)\s*\|\s*(affirms|denies)\s*$",
    re.IGNORECASE)

TEACH = ["robin is a bird", "the vault is locked", "a dog is an animal",
         "robin is not a mammal", "the engine is not cold"]

#: The key the model never supplies and the derivation never sees.
HELD_OUT = {
    "sparrow is a bird": ("sparrow", "bird", "affirms"),
    "the turbine is hot": ("turbine", "hot", "affirms"),
    "an ostrich is a bird": ("ostrich", "bird", "affirms"),
    "mercury is a metal": ("mercury", "metal", "affirms"),
    "a whale is not a fish": ("whale", "fish", "denies"),
    "the ledger is not balanced": ("ledger", "balanced", "denies"),
    "copper is not brittle": ("copper", "brittle", "denies"),
}

MAX_RULES = 6


async def ask(service, sentence):
    """One proposal from the teacher, parsed strictly or declined."""
    reply = await service.generate(prompt=f"Sentence: {sentence}", system_prompt=SYSTEM,
                                   max_tokens=48, temperature=0.0,
                                   enable_thinking=False)
    lines = ((reply or {}).get("content") or "").strip().splitlines()
    first = lines[0] if lines else ""
    match = PROPOSAL.match(first)
    return (tuple(g.lower() for g in match.groups()) if match else None), first


def instruction_set():
    operators = []
    for instruction in INSTRUCTIONS:
        examples = demonstrate(instruction)
        rules = []
        for target in TARGETS[instruction]:
            result = get_rule_inducer().induce(examples, target_predicate=target)
            if result.rule is None:
                raise RuntimeError(f"{instruction}/{target}: {result.detail}")
            rules.append(result.rule)
        operators.append(Operator(action=Fact(instruction, ()), rules=tuple(rules)))
    return operators


def derive(operators, pairs):
    return derive_procedure(
        operators, tuple(Fact(flag, ()) for flag in FLAGS),
        [IOExample(label=s, build=lambda t=s: SentenceMachine(t), expected=m,
                   max_steps=budget(s)) for s, m in pairs],
        terminal="READING", max_rules=MAX_RULES)


def read(procedure, sentence):
    outcome = procedure.run(SentenceMachine(sentence), budget(sentence))
    return tuple(outcome.answer.args) if outcome.produced_answer else None


async def main() -> int:
    print("EDU-14 — can a language model teach the substrate to read?\n")

    # ---- TEACH ---------------------------------------------------------
    set_model_policy(ModelPolicy.NORMAL)
    reset_model_telemetry()
    service = UnifiedLLMService()
    await service.initialize()

    proposals, declined = [], []
    for sentence in TEACH:
        parsed, raw = await ask(service, sentence)
        if parsed is None:
            declined.append({"sentence": sentence, "raw": raw})
            print(f"  taught  {sentence:<26} DECLINED (unparseable: {raw!r})")
            continue
        proposals.append((sentence, parsed))
        print(f"  taught  {sentence:<26} {parsed}")
    teaching = model_telemetry()
    print(f"\n  teacher calls: {teaching['executed']} executed, "
          f"{len(declined)} proposal(s) declined")

    if len(proposals) < 2:
        print("  too few usable proposals to derive from")
        return 1

    # ---- DERIVE and READ, with the teacher blocked ----------------------
    set_model_policy(ModelPolicy.STRICT_MODEL_FREE)
    reset_model_telemetry()

    operators = instruction_set()
    derived = derive(operators, proposals)
    print(f"\n  derived from the teacher's proposals alone: {derived.status.value}"
          f"   size={derived.size}")
    for procedure in derived.procedures[:2]:
        print("     " + " | ".join(str(step) for step in procedure.steps))
    if not derived.procedures:
        print(f"  {derived.detail}")
        return 1

    print(f"\n  reading {len(HELD_OUT)} sentences the teacher never answered, "
          f"graded against a key it never supplied")
    rows, correct = [], 0
    procedure = derived.procedures[0]
    for sentence, meaning in HELD_OUT.items():
        produced = read(procedure, sentence)
        ok = produced == meaning
        correct += ok
        rows.append({"sentence": sentence, "expected": list(meaning),
                     "produced": list(produced) if produced else None, "correct": ok})
        print(f"     {sentence:<32} -> {str(produced):<34} "
              f"{'OK' if ok else 'expected ' + str(meaning)}")
    agree = len({tuple(read(p, s) for s in HELD_OUT) for p in derived.procedures}) == 1
    reading = model_telemetry()

    # ---- REFUSE: the same derivation from a teacher that is wrong -------
    corrupted = [(s, (m[1], m[0], m[2]) if index < 2 else m)
                 for index, (s, m) in enumerate(proposals)]
    wrong = derive(operators, corrupted)
    print(f"\n  the same derivation from a teacher whose first two answers have "
          f"subject and object swapped:")
    print(f"     {wrong.status.value} — {wrong.detail[:96]}")

    passed = (correct == len(HELD_OUT) and agree
              and wrong.status is SynthesisStatus.NO_PROCEDURE
              and reading["attempts"] == 0 and reading["executed"] == 0
              and teaching["executed"] == len(TEACH))

    manifest = Path(__file__).resolve().parent / "taught_to_read.json"
    manifest.write_text(json.dumps({
        "experiment": "EDU-14 taught to read by a language model",
        "question": ("can a model hand over what sentences mean, once, and then "
                     "be removed"),
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "teacher": {"model": service.remote_model or service.local_model_path,
                    "calls": teaching, "declined": declined,
                    "proposals": [{"sentence": s, "proposed": list(m)}
                                  for s, m in proposals]},
        "derivation": {"status": derived.status.value, "size": derived.size,
                       "candidates_run": derived.candidates_run,
                       "procedures": [[str(st) for st in p.steps]
                                      for p in derived.procedures]},
        "reading": {"held_out": rows, "correct": f"{correct}/{len(HELD_OUT)}",
                    "procedures_agree": agree, "model": reading},
        "wrong_teacher": {"status": wrong.status.value, "detail": wrong.detail},
        "taught_vs_read": {"sentences_taught": len(proposals),
                           "never_taught_sentences_read": correct},
        "passed": passed,
    }, indent=2, default=str))

    print(f"\n  taught {len(proposals)} sentences, read {correct} never taught")
    print(f"  during reading — model attempts {reading['attempts']}, "
          f"executed {reading['executed']}")
    print(f"{'PASS' if passed else 'FAIL'}  ->  {manifest.name}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
