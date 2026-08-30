#!/usr/bin/env python3
"""EDU-07 — Functional Cross-Domain Transfer.

    Prior knowledge from a structurally analogous source domain reduces the
    amount of TARGET-domain evidence required to acquire validated competence,
    without reducing held-out target performance.

EDU-06 showed two independently learned action models are isomorphic. That is
recognition. This asks whether the source model makes the target CHEAPER TO
LEARN, which is the claim that turns analogy into knowledge transfer.

THE INVARIANT THROUGHOUT: analogy proposes, only target evidence authorizes.
The projected rule enters as a CANDIDATE with zero evidence roots and reaches
VALIDATED only by surviving target observations it was not built from -- the
same bar a rule induced in the target must clear.

THE A/B, on identical observations in identical order:

    A  TRANSFER   source rule + mapping + projection available
    B  SCRATCH    same world, same stream, same inducer,
                  mapping severed, projection unavailable

Reported separately, because they are different claims:

    time-to-first-hypothesis   when a candidate first exists
    time-to-validation         when it earns executable authority

A transfer that proposes sooner but validates no sooner is still useful and is
NOT a reduction in the evidence required for operational authority.
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from core.database.unified_database_postgres import get_unified_database  # noqa: E402
from core.learning.analogical_projection import (  # noqa: E402
    ProjectionOutcome, derive_correspondence, project)
from core.learning.rule_induction import Fact, get_rule_inducer  # noqa: E402
from core.learning.rule_store import (  # noqa: E402
    EpistemicStatus, get_rule_store, training_example_from_runtime)
from core.model_policy import assert_model_free, model_telemetry  # noqa: E402
from experiments.warehouse_world import WarehouseWorld  # noqa: E402

TARGET_DOMAIN = "warehouse"
SOURCE_DOMAIN = "kite17"


async def reset_target_domain(db) -> None:
    """Remove this experiment's own target-domain rules, children first."""
    rows = await db.execute_query(
        "SELECT rule_id FROM unified.learned_rules WHERE domain_id = $1",
        (TARGET_DOMAIN,), fetch_all=True) or []
    for row in rows:
        rule_id = row["rule_id"]
        for table, column in (("unified.rule_projections", "rule_id"),
                              ("unified.learned_rule_evidence", "rule_id"),
                              ("unified.rule_authority_events", "rule_id"),
                              ("unified.rule_supersessions", "superseded_rule_id"),
                              ("unified.rule_supersessions", "replacement_rule_id")):
            try:
                await db.execute_query(
                    f"DELETE FROM {table} WHERE {column} = $1", (rule_id,), commit=True)
            except Exception:
                pass          # a table this build does not have cannot hold a row
        await db.execute_query(
            "DELETE FROM unified.learned_rules WHERE rule_id = $1", (rule_id,), commit=True)
    if rows:
        print(f"reset target domain: removed {len(rows)} prior {TARGET_DOMAIN} rule(s)")


def observe_run(world, pallet, source, destination, evidence_id, setup, act=True):
    """Execute for real, read the world on both sides, record what happened."""
    world.reset()
    setup(world)
    before = world.observe()
    moved = world.transfer(pallet, source, destination) if act else False
    after = world.observe()
    action = Fact("TRANSFER", (pallet, source, destination)) if act else None
    return training_example_from_runtime(
        before=before, action=action, after=after,
        evidence_id=evidence_id, positive=moved)


def stream(world):
    """The target experiences, in a FIXED ORDER shared by both conditions."""
    return [
        observe_run(world, "p1", "DOCK", "AISLE", "wh_1",
                    lambda w: (w.place("p1", "DOCK"), w.make_available("AISLE"))),
        observe_run(world, "p2", "AISLE", "VAULT", "wh_2",
                    lambda w: (w.place("p2", "AISLE"), w.make_available("VAULT"))),
        observe_run(world, "p3", "DOCK", "AISLE", "wh_no_ACTION",
                    lambda w: (w.place("p3", "DOCK"), w.make_available("AISLE")), act=False),
        observe_run(world, "p4", "DOCK", "AISLE", "wh_no_AVAILABLE",
                    lambda w: w.place("p4", "DOCK")),
        observe_run(world, "p5", "DOCK", "VAULT", "wh_no_ROUTE",
                    lambda w: (w.place("p5", "DOCK"), w.make_available("VAULT"))),
        observe_run(world, "p6", "DOCK", "AISLE", "wh_no_LOCATED",
                    lambda w: (w.place("p6", "VAULT"), w.make_available("AISLE"))),
    ]


def held_out(world):
    """Target experiences NEITHER condition may learn from. The exam.

    THE EXAM MUST SEPARATE AN OVERGENERAL RULE FROM A CORRECT ONE, or the
    comparison is worthless. The first version tested only AVAILABLE, so a
    scratch rule that had learned nothing about ROUTE or LOCATED still scored
    3/3 and "held-out performance equal" was true of an exam that could not
    fail it. Every precondition of the true operator now has a case that
    isolates it.
    """
    return [
        observe_run(world, "h1", "DOCK", "AISLE", "wh_h1",
                    lambda w: (w.place("h1", "DOCK"), w.make_available("AISLE"))),
        observe_run(world, "h2", "AISLE", "VAULT", "wh_h2",
                    lambda w: (w.place("h2", "AISLE"), w.make_available("VAULT"))),
        # isolates AVAILABLE
        observe_run(world, "h3", "DOCK", "AISLE", "wh_h3_no_AVAILABLE",
                    lambda w: w.place("h3", "DOCK")),
        # isolates ROUTE -- everything else holds, no route DOCK->VAULT
        observe_run(world, "h4", "DOCK", "VAULT", "wh_h4_no_ROUTE",
                    lambda w: (w.place("h4", "DOCK"), w.make_available("VAULT"))),
        # isolates LOCATED -- pallet parked in a THIRD bay, so the predicted
        # add is FALSE in this example and it therefore discriminates
        observe_run(world, "h5", "DOCK", "AISLE", "wh_h5_no_LOCATED",
                    lambda w: (w.place("h5", "VAULT"), w.make_available("AISLE"))),
    ]


def scores(rule, exam):
    """How often the rule's prediction matches what the world actually did."""
    correct = 0
    for example in exam:
        bindings, fires = {}, True
        if rule.action is None or example.action is None:
            fires = False
        else:
            for slot, value in zip(rule.action.args, example.action.args):
                if slot.startswith("?"):
                    if bindings.setdefault(slot, value) != value:
                        fires = False
                elif slot != value:
                    fires = False
        if fires:
            for condition in rule.preconditions:
                grounded = condition.substitute(bindings)
                if not grounded.is_ground or grounded not in example.before:
                    fires = False
                    break
        predicted = fires
        if predicted == example.positive:
            correct += 1
    return correct, len(exam)


async def condition_scratch(store, observations, exam):
    """B: induce in the target from nothing, one observation at a time."""
    first_hypothesis, validated_at, final_rule = None, None, None
    for k in range(1, len(observations) + 1):
        seen = observations[:k]
        result = get_rule_inducer().induce(seen)
        if result.rule is None:
            continue
        if first_hypothesis is None:
            first_hypothesis = k
        correct, total = scores(result.rule, exam)
        if correct == total:
            validated_at, final_rule = k, result.rule
            break
        final_rule = result.rule
    return {"first_hypothesis_after": first_hypothesis,
            "validated_after": validated_at,
            "rule": final_rule.to_formula() if final_rule else None,
            "held_out": list(scores(final_rule, exam)) if final_rule else None}


async def condition_transfer(store, observations, exam, source_rule, source_rule_id,
                             mapping_available=True):
    """A: derive a mapping from the target, project the source rule, then test it."""
    first_hypothesis, validated_at, projected = None, None, None
    mapping, reason = {}, "mapping severed"

    for k in range(1, len(observations) + 1):
        latest = observations[k - 1]
        if mapping_available and not mapping:
            mapping, reason = derive_correspondence(source_rule, latest)
            if not mapping:
                continue
            result = project(source_rule, mapping,
                             source_rule_id=source_rule_id,
                             source_domain=SOURCE_DOMAIN, target_domain=TARGET_DOMAIN)
            if result.outcome is not ProjectionOutcome.FULL_PROJECTION:
                mapping = {}
                continue
            projected = result
            first_hypothesis = k
        if projected is not None:
            correct, total = scores(projected.rule, exam)
            if correct == total:
                validated_at = k
                break
    return {"first_hypothesis_after": first_hypothesis,
            "validated_after": validated_at,
            "mapping": mapping, "mapping_reason": reason,
            "rule": projected.rule.to_formula() if projected else None,
            "held_out": list(scores(projected.rule, exam)) if projected else None,
            "projection": projected}


async def main() -> int:
    db = await get_unified_database()
    await db.initialize()
    store = get_rule_store()

    source = next((r for r in await store.load(domain_id=SOURCE_DOMAIN)
                   if r.rule.action and r.rule.action.predicate == "MOVE"
                   and len(r.rule.preconditions) == 3), None)
    if source is None:
        print("ABORT: the corrected KITE MOVE rule is not in the store")
        return 1
    print(f"source rule : {source.rule_id} ({source.status.value})")
    print(f"            : {source.rule}")

    # The experiment resets its own target artifacts, exactly as it resets its
    # world. Without this, `record_projection` correctly returns the rule a
    # PREVIOUS run already validated -- fingerprint identity working as
    # designed -- and the evidence-free-at-projection invariant is measured on
    # a rule that was not projected in this run.
    await reset_target_domain(db)

    world = WarehouseWorld()
    observations, exam = stream(world), held_out(world)
    print(f"\ntarget stream: {len(observations)} observations, fixed order")
    print(f"held-out exam: {len(exam)} observations, learned from by neither condition")

    print("\nA — TRANSFER (source rule + derived mapping + projection)")
    a = await condition_transfer(store, observations, exam, source.rule, source.rule_id)
    print(f"   mapping            : {a['mapping'] or a['mapping_reason']}")
    print(f"   rule               : {a['rule']}")
    print(f"   first hypothesis   : after {a['first_hypothesis_after']} observation(s)")
    print(f"   validated          : after {a['validated_after']} observation(s)")
    print(f"   held-out           : {a['held_out']}")

    print("\nB — SCRATCH (same stream, same inducer, mapping severed)")
    b = await condition_scratch(store, observations, exam)
    print(f"   rule               : {b['rule']}")
    print(f"   first hypothesis   : after {b['first_hypothesis_after']} observation(s)")
    print(f"   validated          : after {b['validated_after']} observation(s)")
    print(f"   held-out           : {b['held_out']}")

    print("\nABLATION — mapping severed, everything else intact")
    ablated = await condition_transfer(store, observations, exam, source.rule,
                                       source.rule_id, mapping_available=False)
    print(f"   projected rule     : {ablated['rule']} (must be None)")

    # Persist the projected candidate, evidence-free, only if it earned nothing.
    stored_candidate, authorized, evidence_free_at_projection = None, False, False
    if a["projection"] is not None:
        stored_candidate = await store.record_projection(
            a["projection"], rule_kind="transfer")
        print(f"\npersisted candidate: {stored_candidate.rule_id} "
              f"({stored_candidate.status.value}, "
              f"+{stored_candidate.positive_root_count}/"
              f"-{stored_candidate.negative_root_count} evidence roots)")

        # MEASURED HERE, BEFORE any target evidence arrives. The invariant is
        # temporal: a projected rule must enter with nothing, and must gain its
        # roots only from the target. Checking it after validation would assert
        # the opposite of what validation is supposed to do.
        evidence_free_at_projection = (
            stored_candidate.positive_root_count == 0
            and stored_candidate.negative_root_count == 0
            and stored_candidate.status is EpistemicStatus.CANDIDATE)

        # THE AUTHORITY STEP, through the store's own validator rather than
        # this script's scoring. A projected rule has no induction basis, so
        # every target observation is legitimately held out for it -- and it
        # must clear the same bar as a rule induced here.
        outcome = await store.validate(stored_candidate, exam)
        stored_candidate = await store.get(stored_candidate.rule_id)
        print(f"target evidence    : {outcome.status.value} "
              f"(confirmed={outcome.confirmed} contradicted={outcome.contradicted}, "
              f"roots={len(outcome.independent_roots)})")
        print(f"executable now     : {stored_candidate.is_executable}")
        authorized = stored_candidate.status is EpistemicStatus.VALIDATED

    telemetry = model_telemetry()
    assert_model_free("edu07_functional_transfer")

    n_a, n_b = a["validated_after"], b["validated_after"]
    fewer = bool(n_a and n_b and n_a < n_b)
    not_worse = bool(a["held_out"] and b["held_out"] and a["held_out"][0] >= b["held_out"][0])
    ablation_ok = ablated["rule"] is None
    evidence_free = evidence_free_at_projection

    passed = (fewer and not_worse and ablation_ok and evidence_free
              and authorized and telemetry["executed"] == 0)
    print(f"\nN_A (transfer) = {n_a}   N_B (scratch) = {n_b}")
    print(f"fewer target observations : {fewer}")
    print(f"held-out not worse        : {not_worse}")
    print(f"ablation removes proposal : {ablation_ok}")
    print(f"evidence-free at projection: {evidence_free}")
    print(f"authorized by target evidence: {authorized}")
    print(f"model                     : executed={telemetry['executed']}")
    print(f"\nEDU-07: {'PASS' if passed else 'FAIL'}")

    manifest = Path(__file__).resolve().parent / "manifest.json"
    manifest.write_text(json.dumps({
        "benchmark": "EDU-07",
        "title": "Functional Cross-Domain Transfer",
        "claim": ("prior knowledge from a structurally analogous source domain "
                  "reduces the target-domain evidence required to acquire "
                  "validated competence, without reducing held-out performance"),
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "passed": passed,
        "model_calls": telemetry["executed"],
        "source": {"rule_id": source.rule_id, "domain": SOURCE_DOMAIN,
                   "formula": source.rule.to_formula()},
        "target_domain": TARGET_DOMAIN,
        "observations_in_stream": [o.evidence_id for o in observations],
        "held_out": [o.evidence_id for o in exam],
        "condition_A_transfer": {k: v for k, v in a.items() if k != "projection"},
        "condition_B_scratch": b,
        "ablation_mapping_severed": {k: v for k, v in ablated.items() if k != "projection"},
        "candidate": ({"rule_id": stored_candidate.rule_id,
                       "status": stored_candidate.status.value,
                       "positive_root_count": stored_candidate.positive_root_count,
                       "negative_root_count": stored_candidate.negative_root_count,
                       "authorized_by_target_evidence": authorized}
                      if stored_candidate else None),
        "criteria": {"fewer_observations": fewer, "held_out_not_worse": not_worse,
                     "ablation_removes_proposal": ablation_ok,
                     "candidate_evidence_free": evidence_free,
                     "authorized_by_target_evidence": authorized},
    }, indent=2, default=str))
    print(f"manifest -> {manifest}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
