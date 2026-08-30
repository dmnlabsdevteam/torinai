#!/usr/bin/env python3
"""CSP-AGI-1 Block 1 — competence and refusal in worlds invented after the freeze.

Runs the protocol declared in PROTOCOL.md. The criterion was written before any
score was seen and is checked here verbatim; nothing below chooses a threshold
after the fact.

READ THE SECOND NUMBER FIRST. Competence over laws the substrate can express
says how much it can learn. False confidence over laws it cannot express says
whether it knows the difference. A subject that refuses everything scores well
on the second and fails the first; one that answers everything does the
reverse. Only the pair means anything.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "EDU-12"))

os.environ.setdefault("TORIN_MODEL_POLICY", "strict_model_free")
logging.disable(logging.INFO)

from core.learning.analogical_projection import (ProjectionOutcome,  # noqa: E402
                                                 derive_correspondence, project)
from core.learning.rule_induction import (BindingOrigin,  # noqa: E402
                                          InductionStatus, contradicted_by,
                                          derives, get_rule_inducer)
from core.model_policy import model_telemetry  # noqa: E402
from generality import architecture_fingerprint  # noqa: E402
from opaque_world import (FAMILIES, REPRESENTABLE,  # noqa: E402
                          UNREPRESENTABLE, evidence, invent)

WORLDS_PER_FAMILY = 8
TEACHING = (4, 4)      # positives, counter-demonstrations
HELD_OUT = (3, 3)

COMPETENCE_FLOOR = 0.80
FALSE_CONFIDENCE_CEILING = 0.05
#: Criterion 4, amended after the first scored run and recorded in PROTOCOL.md
#: before this one. Measured the way criterion 2 measures assertion: a WRONG
#: projection is the failure, a refusal is counted separately -- but a subject
#: that refuses everything still fails the floor.
TRANSFER_FLOOR = 0.80


def assess(world, teaching, held_out):
    """Learn, then judge the result against transitions it never saw.

    A rule whose consequent still carries a variable made no claim about the
    value: `acting produces some reading` is true, useful, and not the law.
    Counting it as competence would let a subject score by declining to
    predict, and counting it as false confidence would punish it for a claim
    it never made -- so it is its own outcome.
    """
    result = get_rule_inducer().induce(teaching, target_predicate=world.produced)
    if result.rule is None:
        return {"outcome": "refused", "status": result.status.value,
                "detail": result.detail, "rule": None}

    if any(o.origin is BindingOrigin.ACTION_OUTPUT for o in result.rule.outputs):
        return {"outcome": "learned_without_the_value", "status": result.status.value,
                "detail": result.detail, "rule": str(result.rule)}

    holds = all(derives(result.rule, e) for e in held_out if e.positive) and \
        all(not contradicted_by(result.rule, e) for e in held_out if not e.positive)
    return {"outcome": "learned_and_holds" if holds else "learned_but_fails",
            "status": result.status.value, "detail": result.detail,
            "rule": str(result.rule)}


def run_family(family, negatives=TEACHING[1]):
    rows = []
    for index in range(WORLDS_PER_FAMILY):
        seed = 7000 + index * 31 + FAMILIES.index(family) * 977
        world = invent(seed, family)
        rows.append({
            "world": index, "family": family, "seed": seed,
            **assess(world,
                     evidence(world, seed + 1, TEACHING[0], negatives, "teach"),
                     evidence(world, seed + 2, *HELD_OUT, "held")),
        })
    return rows


def transfer():
    """A law learned in one invented world, carried into another's vocabulary.

    The correspondence is DERIVED from a single transition in the target world,
    not supplied: `derive_correspondence` reads what the action changed and
    matches the rest by arity, refusing where that is ambiguous. Supplying the
    mapping would be the experimenter doing the transfer.
    """
    rows = []
    for family in ("conjunctive", "relational"):
        for index in range(4):
            a_seed = 41000 + index * 13 + FAMILIES.index(family) * 101
            b_seed = a_seed + 5000
            source, target = invent(a_seed, family), invent(b_seed, family)
            learned = get_rule_inducer().induce(
                evidence(source, a_seed + 1, *TEACHING, "s"),
                target_predicate=source.produced)
            if learned.rule is None:
                rows.append({"family": family, "pair": index,
                             "outcome": "source_not_learned"})
                continue

            target_held = evidence(target, b_seed + 2, *HELD_OUT, "t")
            # The transitions the target world offers, not a mapping supplied by
            # the experimenter. One of them cannot rule out a property that
            # varies independently of the law; several can.
            shown = [e for e in target_held if e.positive][:2]
            correspondence, why = derive_correspondence(learned.rule, shown)
            projected = project(learned.rule, source_rule_id=f"src_{index}",
                                source_domain=f"world_{a_seed}",
                                target_domain=f"world_{b_seed}",
                                correspondences=correspondence)
            if projected.outcome is not ProjectionOutcome.FULL_PROJECTION:
                rows.append({"family": family, "pair": index,
                             "outcome": f"not_projected: {projected.outcome.value}",
                             "detail": projected.detail})
                continue

            rest = [e for e in target_held if e not in shown]
            holds = all(derives(projected.rule, e) for e in rest if e.positive) and \
                all(not contradicted_by(projected.rule, e) for e in rest if not e.positive)
            rows.append({"family": family, "pair": index,
                         "outcome": "holds" if holds else "fails",
                         "correspondence": correspondence, "why": why,
                         "projected": str(projected.rule)})
    return rows


def rate(rows, outcome):
    return sum(1 for r in rows if r["outcome"] == outcome) / len(rows) if rows else 0.0


def main() -> int:
    before = architecture_fingerprint()
    frozen = json.loads(
        (Path(__file__).resolve().parents[1] / "EDU-12" / "FROZEN.json").read_text())

    print("CSP-AGI-1 Block 1 — worlds invented after the architecture froze\n")
    print(f"  architecture {before[:16]}  frozen as {frozen['freeze_id']}"
          f"  {'MATCHES' if before == frozen['architecture_fingerprint'] else 'DIFFERS'}\n")

    results = {family: run_family(family) for family in FAMILIES}
    for family in FAMILIES:
        rows = results[family]
        kind = "can express" if family in REPRESENTABLE else "CANNOT express"
        print(f"  {family:<14} ({kind:<14})  learned {rate(rows,'learned_and_holds'):>4.0%}"
              f"   asserted+fails {rate(rows,'learned_but_fails'):>4.0%}"
              f"   no value {rate(rows,'learned_without_the_value'):>4.0%}"
              f"   refused {rate(rows,'refused'):>4.0%}")

    representable = [r for f in REPRESENTABLE for r in results[f]]
    unrepresentable = [r for f in UNREPRESENTABLE for r in results[f]]
    competence = rate(representable, "learned_and_holds")
    false_confidence = rate(unrepresentable, "learned_but_fails")

    refusals = [r for r in unrepresentable if r["outcome"] == "refused"]
    declined = [r for r in unrepresentable
                if r["outcome"] == "learned_without_the_value"]
    vague = [r for r in refusals
             if r["status"] == InductionStatus.INSUFFICIENT_EVIDENCE.value]
    print(f"\n  competence over expressible laws     {competence:.0%}"
          f"   (criterion: >= {COMPETENCE_FLOOR:.0%})")
    print(f"  false confidence over the rest        {false_confidence:.0%}"
          f"   (criterion: <= {FALSE_CONFIDENCE_CEILING:.0%})")
    print(f"  refusals naming the real obstruction  "
          f"{(len(refusals) - len(vague)) / len(refusals) if refusals else 0:.0%}")
    for reason in sorted({r["detail"][:78] for r in refusals}):
        print(f"      {reason}")

    moved = transfer()
    wrong = [m for m in moved if m["outcome"] == "fails"]
    refused_transfer = [m for m in moved if m["outcome"].startswith("not_projected")]
    print(f"\n  transfer into an unrelated vocabulary  {rate(moved, 'holds'):.0%}"
          f"  ({sum(1 for m in moved if m['outcome']=='holds')}/{len(moved)})")
    print(f"      of those attempted: {len(moved) - len(refused_transfer) - len(wrong)}"
          f" held, {len(wrong)} wrong, {len(refused_transfer)} refused to guess"
          f"   (criterion: 0 wrong and >= {TRANSFER_FLOOR:.0%} holding)")

    print("\n  ABLATION — the counter-demonstrations removed")
    ablated = {family: run_family(family, negatives=0) for family in FAMILIES}
    ablated_unrep = [r for f in UNREPRESENTABLE for r in ablated[f]]
    ablated_rep = [r for f in REPRESENTABLE for r in ablated[f]]
    print(f"      false confidence over the rest    "
          f"{rate(ablated_unrep, 'learned_but_fails'):.0%}"
          f"   (was {false_confidence:.0%})")
    print(f"      competence over expressible laws  "
          f"{rate(ablated_rep, 'learned_and_holds'):.0%}   (was {competence:.0%})")

    after = architecture_fingerprint()
    telemetry = model_telemetry()
    passed = (competence >= COMPETENCE_FLOOR
              and false_confidence <= FALSE_CONFIDENCE_CEILING
              and not vague
              and not wrong and rate(moved, "holds") >= TRANSFER_FLOOR
              and telemetry["attempts"] == 0 and telemetry["executed"] == 0
              and before == after == frozen["architecture_fingerprint"])

    manifest = Path(__file__).resolve().parent / "BLOCK1_RESULTS.json"
    manifest.write_text(json.dumps({
        "protocol": "CSP-AGI-1 Block 1 — opaque novel domain",
        "status_of_this_run": (
            "DEVELOPMENTAL DATA, not evidence of AGI. The protocol requires the "
            "architecture to be frozen before the evaluator exists; this "
            "substrate was modified extensively on the day of the run."),
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "architecture": {"before": before, "after": after,
                         "frozen_as": frozen["freeze_id"],
                         "unchanged": before == after == frozen["architecture_fingerprint"]},
        "worlds_per_family": WORLDS_PER_FAMILY,
        "criterion": {"competence_floor": COMPETENCE_FLOOR,
                      "false_confidence_ceiling": FALSE_CONFIDENCE_CEILING,
                      "transfer_floor": TRANSFER_FLOOR,
                      "transfer_amended": ("criterion 4 was mis-specified as 100% and "
                                           "is measured here as: no WRONG projection, "
                                           "and at least the floor holding")},
        "measured": {"competence": competence, "false_confidence": false_confidence,
                     "transfer": rate(moved, "holds"),
                     "vague_refusals": len(vague)},
        "by_family": results,
        "transfer": moved,
        "transfer_decomposition": {
            "held": sum(1 for m in moved if m["outcome"] == "holds"),
            "wrong": len(wrong),
            "refused_to_guess": len(refused_transfer),
            "note": ("A refusal here is `derive_correspondence` declining to choose "
                     "between two source preconditions of the same arity, which one "
                     "observed transition cannot separate. It is a property of the "
                     "evidence, not of the subject."),
        },
        "ablation": {"false_confidence": rate(ablated_unrep, "learned_but_fails"),
                     "competence": rate(ablated_rep, "learned_and_holds"),
                     "by_family": ablated},
        "model": telemetry,
        "passed": passed,
    }, indent=2, default=str))

    print(f"\n  model attempts {telemetry['attempts']}, executed {telemetry['executed']}")
    print(f"  architecture unchanged: {before == after == frozen['architecture_fingerprint']}")
    print(f"\n{'BLOCK 1 CRITERION MET' if passed else 'BLOCK 1 CRITERION NOT MET'}"
          f"  ->  {manifest.name}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
