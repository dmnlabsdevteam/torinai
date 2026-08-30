#!/usr/bin/env python3
"""EDU-09 — Bounded Active Teaching in a Combinatorial Situation Space.

    Under a proposal budget far too small to enumerate the situation space, can
    the deterministic TeacherPolicy drive the substrate to validated competence,
    and how much does the quality of the PROPOSER matter?

EDU-08 could not answer this: three binary preconditions give 54 situations and
exhaustive proposal is free, so any proposer looks adequate. Here twelve binary
conditions give 4096 situations, five of them causal, one causal only by its
ABSENCE, and six pure distractors. The budget is eight proposals per lesson.
Enumeration is not a teaching strategy at that ratio.

No language model is involved. TeacherPolicy is the teacher; the proposers are
deterministic, and they differ only in how well they search.

    A  RANDOM     eight valid situations drawn at random
    B  SEARCH     a heuristic that varies conditions it has not yet separated
    D  ORACLE     the best eight the whole space contains -- a reference
                  CEILING, not a deployable competitor: it inspects all 4096
                  situations to choose, which is exactly what the budget exists
                  to forbid

Every condition is scored and chosen by the same policy, and every outcome comes
from the world. The proposers differ in what they OFFER, never in what they may
assert.
"""

from __future__ import annotations

import asyncio
import json
import os
import random
import sys
from datetime import datetime, timezone
from itertools import combinations
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from core.learning.rule_induction import (  # noqa: E402
    CandidateRule, Fact, RuleEffects, TrainingExample)
from core.learning.teacher_policy import (  # noqa: E402
    choose_lesson, information_gain, predicts)
from experiments.warehouse_complex import (  # noqa: E402
    ALL_CONDITIONS, ARGUMENT_OF, CAUSAL_NEGATIVE, CAUSAL_POSITIVE, run)

BUDGET = int(os.environ.get("EDU09_BUDGET", "8"))
# log2(6144) ~= 12.6, so a perfect binary search needs 13 lessons. A cap of 12
# cut B_search off at TWO surviving hypotheses and reported it as 0% converged
# -- measuring my cap, not the proposer. Set well clear of the optimum so the
# number that gets reported is lessons-to-converge.
MAX_LESSONS = int(os.environ.get("EDU09_MAX_LESSONS", "20"))
TRIALS = int(os.environ.get("EDU09_TRIALS", "3"))

ACTION = Fact("TRANSFER", ("?X", "?A", "?B"))
SLOTS = {"X": "?X", "A": "?A", "B": "?B"}
EFFECTS = RuleEffects(add=frozenset([Fact("LOCATED", ("?X", "?B"))]),
                      delete=frozenset([Fact("LOCATED", ("?X", "?A"))]))
POSITIVE_CANDIDATES = tuple(c for c in ALL_CONDITIONS if c not in CAUSAL_NEGATIVE)


def negative_condition() -> str:
    """The condition that gates by ABSENCE, read at call time.

    Four places hardcoded the string "LOCKED", so relabelling the vocabulary
    raised KeyError -- the harness was keying on a word. Found by the
    name-blindness check the first time it was made to actually run, which is
    the entire reason a check must execute rather than announce.
    """
    return CAUSAL_NEGATIVE[0]


def literal(condition: str) -> Fact:
    return Fact(condition, tuple(SLOTS[s] for s in ARGUMENT_OF[condition]))


def build_version_space():
    """Every rule that demands some conditions and forbids LOCKED, or does not.

    LOCKED gets three treatments -- required, forbidden, ignored -- because a
    condition that matters only by its ABSENCE is exactly the kind a learner
    that only ever collects positive requirements can never express.
    """
    space = []
    positives = tuple(c for c in ALL_CONDITIONS if c not in CAUSAL_NEGATIVE)
    for size in range(len(positives) + 1):
        for chosen in combinations(positives, size):
            base = [literal(c) for c in chosen]
            for locked in ("ignored", "forbidden", "required"):
                if locked == "required":
                    body = frozenset([ACTION] + base + [literal(negative_condition())])
                else:
                    body = frozenset([ACTION] + base)
                space.append({
                    "requires": frozenset(chosen),
                    "locked": locked,
                    "rule": CandidateRule(body=body, effects=EFFECTS, action=ACTION),
                })
    return space


TRUTH = {"requires": frozenset(CAUSAL_POSITIVE), "locked": "forbidden"}


def consistent(entry, lesson) -> bool:
    """Does this hypothesis predict what the world actually did?

    `forbidden` is checked here rather than encoded in the rule body, because
    the rule grammar has no negation -- so the version space carries the
    polarity and the predictor honours it.
    """
    negative = negative_condition()
    conditions = {f.predicate for f in lesson.before}
    fires = entry["requires"] <= conditions
    if entry["locked"] == "forbidden" and negative in conditions:
        fires = False
    if entry["locked"] == "required" and negative not in conditions:
        fires = False
    return fires == lesson.positive


def as_lesson(conditions, identifier: str) -> TrainingExample:
    """Set the world up, run it, and record what happened. Never asserted."""
    before, after, moved = run(sorted(conditions))
    return TrainingExample(before=tuple(sorted(before, key=str)), action=Fact(
        "TRANSFER", ("p", "DOCK", "AISLE")),
        after=tuple(sorted(after, key=str)), positive=moved,
        evidence_id=identifier)


def survivors(space, taught):
    return [e for e in space if all(consistent(e, l) for l in taught)]


def gain_of(alive, conditions) -> float:
    """Expected hypotheses eliminated, computed on the version space directly.

    Same measure the policy applies -- one block per predicted outcome, expected
    survivors = sum(|block|^2)/n -- evaluated on the compact representation so
    a proposer may search without materialising thousands of rule objects.
    """
    negative = negative_condition()
    fires = 0
    for entry in alive:
        f = entry["requires"] <= conditions
        if entry["locked"] == "forbidden" and negative in conditions:
            f = False
        if entry["locked"] == "required" and negative not in conditions:
            f = False
        fires += f
    total = len(alive)
    holds = total - fires
    return total - (fires * fires + holds * holds) / total if total else 0.0


# --- proposers -------------------------------------------------------------

def propose_random(alive, rng, budget):
    out = []
    for i in range(budget):
        size = rng.randint(0, len(ALL_CONDITIONS))
        out.append(frozenset(rng.sample(ALL_CONDITIONS, size)))
    return out


def propose_search(alive, rng, budget):
    """Vary one condition at a time around a situation that currently fires.

    Cheap and deployable: it never inspects the situation space, only the
    hypotheses still standing. The reference point is the union of what the
    surviving hypotheses demand, so each variation asks about a condition the
    version space still disagrees over.
    """
    contested = set()
    for entry in alive:
        contested |= set(entry["requires"])
    negative = negative_condition()
    contested |= {negative}
    reference = frozenset(c for c in ALL_CONDITIONS if c != negative)

    out = [reference]
    for condition in sorted(contested):
        if len(out) >= budget:
            break
        if condition == negative:
            out.append(reference | {negative})
        else:
            out.append(reference - {condition})
    while len(out) < budget:
        out.append(frozenset(rng.sample(ALL_CONDITIONS,
                                        rng.randint(0, len(ALL_CONDITIONS)))))
    return out[:budget]


def propose_oracle(alive, rng, budget):
    """The best the whole space contains. NOT deployable -- it reads all 4096."""
    scored = []
    for mask in range(1 << len(ALL_CONDITIONS)):
        conditions = frozenset(c for i, c in enumerate(ALL_CONDITIONS) if mask >> i & 1)
        scored.append((gain_of(alive, conditions), conditions))
    scored.sort(key=lambda pair: -pair[0])
    return [conditions for _gain, conditions in scored[:budget]]


PROPOSERS = {"A_random": propose_random,
             "B_search": propose_search,
             "D_oracle": propose_oracle}


async def teach(name, proposer, seed):
    space = build_version_space()
    rng = random.Random(seed)
    taught, trace = [], []
    offered = useful = 0
    first_discriminating = None

    for step in range(1, MAX_LESSONS + 1):
        alive = survivors(space, taught)
        if len(alive) <= 1:
            break
        candidates = proposer(alive, rng, BUDGET)
        offered += len(candidates)
        lessons = [as_lesson(c, f"{name}_{step}_{i}") for i, c in enumerate(candidates)]

        gains = [gain_of(alive, frozenset(f.predicate for f in l.before)) for l in lessons]
        useful += sum(1 for g in gains if g > 0)
        if first_discriminating is None and any(g > 0 for g in gains):
            first_discriminating = step

        best = max(range(len(lessons)), key=lambda i: gains[i])
        if gains[best] <= 0:
            trace.append({"step": step, "note": "nothing offered eliminates anything",
                          "alive": len(alive)})
            break
        taught.append(lessons[best])
        trace.append({"step": step, "alive_before": len(alive),
                      "alive_after": len(survivors(space, taught)),
                      "expected_eliminated": round(gains[best], 1)})

    alive = survivors(space, taught)
    learned = alive[0] if len(alive) == 1 else None
    correct = (learned is not None
               and learned["requires"] == TRUTH["requires"]
               and learned["locked"] == TRUTH["locked"])
    return {
        "condition": name, "seed": seed,
        "lessons": len(taught), "surviving": len(alive),
        "converged": learned is not None,
        "learned_correct_rule": correct,
        "learned": ({"requires": sorted(learned["requires"]), "locked": learned["locked"]}
                    if learned else None),
        "proposal_precision": round(useful / offered, 3) if offered else 0.0,
        "proposals_offered": offered,
        "first_discriminating_step": first_discriminating,
        "trace": trace,
    }


async def name_blindness_check():
    """Run B_search twice, once with the words replaced. Compare trajectories.

    A relabelling that changes the outcome would mean the teacher is reading
    the vocabulary rather than the version space.
    """
    import experiments.warehouse_complex as world

    semantic = await teach("B_search", propose_search, seed=0)

    original = dict(ALL=world.ALL_CONDITIONS, POS=world.CAUSAL_POSITIVE,
                    NEG=world.CAUSAL_NEGATIVE, ARG=dict(world.ARGUMENT_OF))
    mapping = {name: f"P{i:02d}" for i, name in enumerate(original["ALL"])}
    try:
        world.ALL_CONDITIONS = tuple(mapping[c] for c in original["ALL"])
        world.CAUSAL_POSITIVE = tuple(mapping[c] for c in original["POS"])
        world.CAUSAL_NEGATIVE = tuple(mapping[c] for c in original["NEG"])
        world.ARGUMENT_OF = {mapping[k]: v for k, v in original["ARG"].items()}

        module = sys.modules[__name__]
        saved = (module.ALL_CONDITIONS, module.CAUSAL_POSITIVE,
                 module.CAUSAL_NEGATIVE, module.ARGUMENT_OF,
                 module.POSITIVE_CANDIDATES, module.TRUTH)
        module.ALL_CONDITIONS = world.ALL_CONDITIONS
        module.CAUSAL_POSITIVE = world.CAUSAL_POSITIVE
        module.CAUSAL_NEGATIVE = world.CAUSAL_NEGATIVE
        module.ARGUMENT_OF = world.ARGUMENT_OF
        module.POSITIVE_CANDIDATES = tuple(
            c for c in world.ALL_CONDITIONS if c not in world.CAUSAL_NEGATIVE)
        module.TRUTH = {"requires": frozenset(world.CAUSAL_POSITIVE),
                        "locked": "forbidden"}
        opaque = await teach("B_search_opaque", propose_search, seed=0)
    finally:
        world.ALL_CONDITIONS, world.CAUSAL_POSITIVE = original["ALL"], original["POS"]
        world.CAUSAL_NEGATIVE, world.ARGUMENT_OF = original["NEG"], original["ARG"]
        (module.ALL_CONDITIONS, module.CAUSAL_POSITIVE, module.CAUSAL_NEGATIVE,
         module.ARGUMENT_OF, module.POSITIVE_CANDIDATES, module.TRUTH) = saved

    identical = (semantic["lessons"] == opaque["lessons"]
                 and semantic["learned_correct_rule"] == opaque["learned_correct_rule"]
                 and [t.get("alive_after") for t in semantic["trace"]]
                     == [t.get("alive_after") for t in opaque["trace"]])
    return {"semantic": semantic, "opaque": opaque, "identical": identical}


async def main() -> int:
    space_size = len(build_version_space())
    print(f"situation space   : {2 ** len(ALL_CONDITIONS)} "
          f"({len(ALL_CONDITIONS)} binary conditions)")
    print(f"version space     : {space_size} hypotheses")
    print(f"proposal budget   : {BUDGET} per lesson, max {MAX_LESSONS} lessons")
    print(f"ratio             : budget is {BUDGET / 2 ** len(ALL_CONDITIONS):.4%} "
          f"of the situation space\n")

    results = {}
    for name, proposer in PROPOSERS.items():
        trials = [await teach(name, proposer, seed) for seed in range(TRIALS)]
        converged = [t for t in trials if t["converged"]]
        correct = [t for t in trials if t["learned_correct_rule"]]
        results[name] = {
            "trials": trials,
            "convergence_rate": round(len(converged) / len(trials), 3),
            "correct_rule_rate": round(len(correct) / len(trials), 3),
            "false_knowledge_rate": round(
                sum(1 for t in trials if t["converged"] and not t["learned_correct_rule"])
                / len(trials), 3),
            "median_lessons": sorted(t["lessons"] for t in converged)[len(converged) // 2]
                              if converged else None,
            "mean_proposal_precision": round(
                sum(t["proposal_precision"] for t in trials) / len(trials), 3),
        }
        r = results[name]
        print(f"{name:<10} converged {r['convergence_rate']:.0%}  "
              f"correct {r['correct_rule_rate']:.0%}  "
              f"lessons {r['median_lessons']}  "
              f"precision {r['mean_proposal_precision']:.2f}  "
              f"false-knowledge {r['false_knowledge_rate']:.0%}")

    # NAME-BLINDNESS, ACTUALLY RUN.
    #
    # This was a print statement asserting an invariant it never tested -- it
    # announced the relabelling and checked nothing, which is the same defect
    # class as a passing test that exercises no code. A deterministic proposer
    # reads the version space, so relabelling the vocabulary must change
    # nothing; if it does, something is keying on words it should not see.
    blindness = await name_blindness_check()
    print("\nname-blindness (opaque relabelling, actually run)")
    print(f"   semantic vocabulary : {blindness['semantic']['lessons']} lessons, "
          f"correct={blindness['semantic']['learned_correct_rule']}")
    print(f"   opaque vocabulary   : {blindness['opaque']['lessons']} lessons, "
          f"correct={blindness['opaque']['learned_correct_rule']}")
    print(f"   identical trajectory: {blindness['identical']}")

    passed = (all(r["false_knowledge_rate"] == 0.0 for r in results.values())
              and blindness["identical"])

    manifest = Path(__file__).resolve().parent / "manifest.json"
    manifest.write_text(json.dumps({
        "benchmark": "EDU-09",
        "title": "Bounded Active Teaching in a Combinatorial Situation Space",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "situation_space": 2 ** len(ALL_CONDITIONS),
        "version_space": space_size,
        "budget_per_lesson": BUDGET,
        "max_lessons": MAX_LESSONS,
        "trials_per_condition": TRIALS,
        "truth": {"requires": sorted(TRUTH["requires"]), "locked": TRUTH["locked"]},
        "conditions": results,
        "safety_axis_passed": passed,
        "name_blindness": {
            "identical_trajectory": blindness["identical"],
            "semantic_lessons": blindness["semantic"]["lessons"],
            "opaque_lessons": blindness["opaque"]["lessons"],
        },
    }, indent=2, default=str))
    print(f"\nEDU-09 (safety axis): {'PASS' if passed else 'FAIL'}")
    print(f"manifest -> {manifest}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
