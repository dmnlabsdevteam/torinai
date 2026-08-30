#!/usr/bin/env python3
"""Learn the ARCHIVE operator from REAL execution, not from a teacher's triples.

Every demonstration below is produced by actually calling `relocate` against a
real directory tree and reading the filesystem before and after. The label is
whatever the world did -- positives are runs that moved a file, negatives are
runs where the world refused and nothing changed. Nothing is asserted.

This is what EDU-05 wired: `training_example_from_runtime` turns an executed
action into a demonstration. Here it is used to acquire a second domain, so
that transfer has somewhere real to go.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.domain.concept_ingestion import EvidenceSourceType  # noqa: E402
from core.domain.evidence_producers import (  # noqa: E402
    submit_demonstration, submit_learned_rule)
from core.learning.rule_induction import Fact, get_rule_inducer  # noqa: E402
from core.learning.rule_store import (  # noqa: E402
    INDUCTION_ROLES, get_rule_store, training_example_from_runtime)
from experiments.archive_world import ArchiveWorld  # noqa: E402

DOMAIN = "archive"


def run_one(world, item, source, destination, evidence_id, setup):
    """Execute for real, observe both sides, and record what happened."""
    world.reset()
    setup(world)
    before = world.observe()
    moved = world.relocate(item, source, destination)
    after = world.observe()
    action = Fact("RELOCATE", (item, source, destination))
    return training_example_from_runtime(
        before=before, action=action, after=after,
        evidence_id=evidence_id, positive=moved), moved


def no_action(world, evidence_id, setup):
    """Preconditions hold and NOTHING is invoked. The world is observed twice.

    This is what separates "the state change follows from the situation" from
    "the state change follows from the ACTION". Without it, induction reports
    MULTIPLE_HYPOTHESES -- correctly, because the demonstrations genuinely do
    not determine which.
    """
    world.reset()
    setup(world)
    before = world.observe()
    after = world.observe()
    return training_example_from_runtime(
        before=before, action=None, after=after,
        evidence_id=evidence_id, positive=False), False


def demonstrations(world):
    out = []
    # Positives across DIFFERENT bucket pairs, so the buckets generalize to
    # variables instead of being frozen into the rule as INBOX/STAGING.
    out.append(run_one(world, "d1", "INBOX", "STAGING", "arc_d1",
                       lambda w: (w.place("d1", "INBOX"), w.mark_ready("STAGING"))))
    out.append(run_one(world, "d2", "STAGING", "PROCESSED", "arc_d2",
                       lambda w: (w.place("d2", "STAGING"), w.mark_ready("PROCESSED"))))
    # Nothing invoked, everything else in place.
    out.append(no_action(world, "arc_no_ACTION",
                         lambda w: (w.place("d6", "INBOX"), w.mark_ready("STAGING"))))
    # Negative: destination not READY.
    out.append(run_one(world, "d3", "INBOX", "STAGING", "arc_no_READY",
                       lambda w: w.place("d3", "INBOX")))
    # Negative: no LINK between these buckets.
    out.append(run_one(world, "d4", "INBOX", "PROCESSED", "arc_no_LINK",
                       lambda w: (w.place("d4", "INBOX"), w.mark_ready("PROCESSED"))))
    # Negative: the item is not in the source bucket.
    #
    # It is parked in a THIRD bucket, not in the destination. Placing it in the
    # destination made this negative useless: the rule predicts IN(item, dest)
    # and that was already true, so the demonstration contradicted nothing and
    # induction learned an operator with no IN precondition at all -- exactly
    # the defect KITE had before mv_no_AT_SOURCE. A negative only discriminates
    # if the predicted effect is FALSE in it.
    out.append(run_one(world, "d5", "INBOX", "STAGING", "arc_no_IN",
                       lambda w: (w.place("d5", "PROCESSED"), w.mark_ready("STAGING"))))
    return out


async def main() -> int:
    world = ArchiveWorld()
    results = demonstrations(world)
    examples = [e for e, _ in results]

    print("demonstrations produced by REAL execution:")
    for example, moved in results:
        print(f"   {example.evidence_id:<16} moved={str(moved):<5} "
              f"before={len(example.before)} after={len(example.after)}")

    for example in examples:
        result = await submit_demonstration(
            example, domain_id=DOMAIN,
            source_type=EvidenceSourceType.TASK_ARTIFACT,
            producer="archive_world_execution")
        if not result.read_successfully:
            print(f"ABORT: {example.evidence_id}: {result.extraction_failures}")
            return 1

    induction = get_rule_inducer().induce(examples)
    print(f"\ninduction: {induction.status.value}")
    if induction.rule is None:
        print("ABORT:", induction.detail)
        for candidate in induction.candidates:
            print("   candidate:", candidate)
        return 1
    print("rule     :", induction.rule)

    store = get_rule_store()
    stored = (await store.record_induction(
        induction, examples, domain_id=DOMAIN, rule_kind="relocate"))[0]
    print(f"persisted: {stored.rule_id} ({stored.status.value})")

    roots = await store.evidence_roots(stored.rule_id, INDUCTION_ROLES)
    projection = await submit_learned_rule(stored, roots)
    print(f"projected: {projection.candidates} candidate(s), "
          f"created={len(projection.created)} reinforced={len(projection.reinforced)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
