#!/usr/bin/env python3
"""EDU-10 — Active Learning Under Noise and Uncertainty.

    Can Torin learn the correct causal structure when observations are noisy,
    actions sometimes fail despite a correct rule, and some outcomes are
    UNKNOWN -- without either refusing to learn or corrupting valid knowledge?

EDU-09 had a clean world: same conditions, same outcome, and one contradiction
was a proof. Here a contradiction is merely unlikely, so a learner that treats
it as a proof deletes the correct rule the first time reality misbehaves.

SCALE IS DELIBERATELY REDUCED. Eight conditions rather than twelve, 256
hypotheses rather than 6,144. EDU-09 owns the combinatorial claim; the variable
under test here is NOISE, and thirty seeds across three conditions has to be
affordable. Making both hard at once would leave a failure unattributable.

    A  DETERMINISTIC   no noise, no UNKNOWN          -- an EDU-09-like control
    B  STOCHASTIC      10% failure under a valid structure
    C  PARTIAL         stochastic, plus 10% UNKNOWN observations

The target is no longer one surviving hypothesis. It is posterior mass on the
correct structure, with a separately calibrated execution reliability.
"""

from __future__ import annotations

import asyncio
import json
import os
import random
import statistics
import sys
from datetime import datetime, timezone
from itertools import combinations
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from core.learning.probabilistic_version_space import (  # noqa: E402
    RELIABILITY_PRIOR, ProbabilisticVersionSpace, StructuralHypothesis)
from experiments.warehouse_complex import (  # noqa: E402
    CAUSAL_NEGATIVE, CAUSAL_POSITIVE, DISTRACTORS as ALL_DISTRACTORS)
from experiments.warehouse_stochastic import (  # noqa: E402
    DETERMINISTIC, NOISY, NOISY_PARTIAL, Outcome, StochasticWarehouse,
    structure_satisfied)

# DERIVED FROM THE WORLD, NEVER RESTATED. An earlier version of this file
# declared REQUIRED as a literal four conditions while the world required five
# -- it also needs AUTHORISED -- and omitted the fifth from CONDITIONS
# entirely. The target structure was therefore UNREACHABLE: no situation the
# learner could construct ever satisfied it, every attempt ran at the leak
# rate, and 0% convergence was the honest answer to an impossible question.
#
# It reported a calibration error of 0.013 while doing it, because predicting
# "this will fail" is well calibrated in a world where nothing ever succeeds.
# That is the shape to watch for: a healthy-looking number produced by the
# complete ABSENCE of the phenomenon being measured. `assert_truth_reachable`
# below is the oracle that makes it impossible to happen again.
REQUIRED = CAUSAL_POSITIVE
FORBIDDEN = CAUSAL_NEGATIVE
# Two distractors, keeping the deliberate 8-condition / 256-hypothesis scale.
DISTRACTORS = ALL_DISTRACTORS[:2]
CONDITIONS = REQUIRED + FORBIDDEN + DISTRACTORS
CANDIDATES = tuple(c for c in CONDITIONS if c not in FORBIDDEN)


def assert_truth_reachable() -> None:
    """The structure under test must be satisfiable by the situations offered.

    Without this the experiment can run to completion, produce a full table of
    plausible statistics, and be measuring nothing at all.
    """
    reference = frozenset(CANDIDATES)
    if not structure_satisfied(reference):
        missing = sorted(set(CAUSAL_POSITIVE) - set(CONDITIONS))
        raise AssertionError(
            "the world's causal structure cannot be satisfied by any situation "
            f"this experiment can build; conditions absent from the vocabulary: {missing}")
    if structure_satisfied(reference | frozenset(FORBIDDEN)):
        raise AssertionError("the forbidden condition does not actually block the action")

BUDGET = int(os.environ.get("EDU10_BUDGET", "8"))
MAX_OBSERVATIONS = int(os.environ.get("EDU10_MAX_OBS", "200"))
SEEDS = int(os.environ.get("EDU10_SEEDS", "30"))
CRITERION = 0.95


def build_space() -> list:
    space = []
    for size in range(len(CANDIDATES) + 1):
        for chosen in combinations(CANDIDATES, size):
            for forbids in (frozenset(), frozenset(FORBIDDEN)):
                space.append(StructuralHypothesis(frozenset(chosen), forbids))
    return space


TRUE_REQUIRES, TRUE_FORBIDS = frozenset(REQUIRED), frozenset(FORBIDDEN)


def candidate_situations(rng, history, budget):
    """Structured ablations AND replays of situations already tried.

    RANDOM SAMPLING IS NOT A PROPOSER. Drawing arbitrary subsets was EDU-09's
    failing condition, and it fails here for the same reason: an arbitrary
    situation rarely separates anything, so the policy spends its budget on
    experiments that cannot teach. Measured with random candidates: 0%
    convergence and a reliability estimate of 0.08 against a true 0.90.

    The structured set is the one EDU-09 showed works -- a reference situation
    that satisfies everything, and one variation per condition removing it --
    so each experiment isolates a single condition.

    Replays are on the menu because under noise a repeat is often the most
    informative thing available: the first failure of a valid rule is ambiguous
    between a broken structure and bad luck, and only another trial of the SAME
    situation separates them. The policy chooses; this only offers.
    """
    reference = frozenset(c for c in CONDITIONS if c not in FORBIDDEN)
    proposals = [reference, reference | frozenset(FORBIDDEN)]
    for condition in CANDIDATES:
        proposals.append(reference - {condition})
    replays = list(dict.fromkeys(reversed(history)))[:3]
    rng.shuffle(proposals)
    return (proposals + replays)[:budget]


def run_trial(physics, seed):
    world = StochasticWarehouse(physics, seed=seed)
    rng = random.Random(seed * 7919 + 11)
    space = ProbabilisticVersionSpace(hypotheses=build_space())

    history, replications, false_refutations = [], 0, 0
    deliberate_replications = 0
    refutation_opportunities = 0
    misleading_successes = 0
    reached = None
    trace = []

    while space.observations < MAX_OBSERVATIONS:
        mass = space.mass_on(TRUE_REQUIRES, TRUE_FORBIDS)
        if mass >= CRITERION:
            reached = space.observations
            break

        candidates = candidate_situations(rng, history, BUDGET)
        gains = [space.expected_information_gain(c) for c in candidates]
        best = max(range(len(candidates)), key=gains.__getitem__)
        chosen = candidates[best]
        if gains[best] <= 1e-9:
            trace.append({"note": "nothing available carries information"})
            break
        # A REPLICATION ONLY COUNTS AS A CHOICE IF THERE WAS AN ALTERNATIVE.
        # The proposal set is small, so after the first pass every candidate is
        # trivially a repeat and "did it replicate" answers itself. What the
        # claim needs is the deliberate case: a situation already observed,
        # preferred over an untried one that was on the same menu.
        if chosen in history:
            replications += 1
            if any(c not in history for c in candidates):
                deliberate_replications += 1

        observed, _truth = world.attempt(chosen)
        history.append(chosen)

        satisfied_before = structure_satisfied(chosen)
        mass_before = space.mass_on(TRUE_REQUIRES, TRUE_FORBIDS)
        space.observe(chosen, observed.value)
        mass_after = space.mass_on(TRUE_REQUIRES, TRUE_FORBIDS)

        # A FALSE REFUTATION: the true structure held, the action failed for
        # variance, and belief in the truth collapsed anyway.
        # A ZERO IS ONLY MEANINGFUL IF THE TRAP WAS SPRUNG. Counting
        # refutations without counting opportunities lets "0 false
        # refutations" mean "the situation never arose" -- an absence
        # reported as a pass.
        # MISLEADING EVIDENCE, COUNTED RATHER THAN ASSUMED. A success under a
        # VIOLATED structure is the leak rate doing its job -- the observation
        # that would be logically impossible in a deterministic world and
        # would therefore be a valid refutation there. Claiming the learner
        # withstands it without checking it ever occurred is the same absence
        # -as-pass error as an uncounted trap.
        if not satisfied_before and observed is Outcome.SUCCESS:
            misleading_successes += 1
        if satisfied_before and observed is Outcome.FAILURE:
            refutation_opportunities += 1
            if mass_before > 0.10 and mass_after < mass_before / 10:
                false_refutations += 1

        if len(trace) < 6:
            trace.append({"n": space.observations, "outcome": observed.value,
                          "mass_on_truth": round(mass_after, 4),
                          "reliability": round(space.reliability, 3)})

    mass = space.mass_on(TRUE_REQUIRES, TRUE_FORBIDS)
    best, best_mass = space.most_probable()
    exam = held_out_calibration(space, rng, physics)
    return {
        "seed": seed,
        "observations": space.observations,
        "reached_criterion_at": reached,
        "final_mass_on_truth": round(mass, 4),
        "map_is_truth": best.key() == (tuple(sorted(TRUE_REQUIRES)),
                                       tuple(sorted(TRUE_FORBIDS))),
        "map_mass": round(best_mass, 4),
        "reliability_estimate": round(space.reliability, 4),
        "map_reliability": round(space.rates_of_most_probable()[0], 4),
        "map_firing_trials": round(
            space.fire_alpha[space.posterior().index(max(space.posterior()))]
            + space.fire_beta[space.posterior().index(max(space.posterior()))]
            - sum(RELIABILITY_PRIOR), 1),
        "leak_estimate": round(space.leak, 4),
        "replications": replications,
        "deliberate_replications": deliberate_replications,
        "false_refutations": false_refutations,
        "refutation_opportunities": refutation_opportunities,
        "misleading_successes": misleading_successes,
        "unknown_observations": space.unknown_observations,
        "brier_score": exam["brier_score"],
        "expected_calibration_error": exam["expected_calibration_error"],
        "oracle_probability_error": exam["oracle_probability_error"],
        "held_out_accuracy": exam["accuracy"],
        "restart_preserves_belief": restart_check(space),
        "trace": trace,
    }


def held_out_calibration(space, rng, physics, samples=60):
    """Predicted P(success) against what the world actually does."""
    probe = StochasticWarehouse(physics, seed=99991)
    predicted, actual, oracle_rate = [], [], []
    for _ in range(samples):
        size = rng.randint(0, len(CONDITIONS))
        situation = frozenset(rng.sample(CONDITIONS, size))
        predicted.append(space.probability_of_success(situation))
        outcome, truth = probe.attempt(situation)
        actual.append(1.0 if truth else 0.0)
        oracle_rate.append(physics.success_rate if structure_satisfied(situation)
                           else physics.leak_rate)
    # MEAN ABSOLUTE ERROR IS NOT A CALIBRATION MEASURE. It is minimised by
    # confident 0/1 predictions, so an overconfident learner scores better on
    # it than a correctly uncertain one -- the opposite of what is claimed.
    # Three honest measures instead:
    #   brier    a strictly proper score; only truthful probabilities minimise it
    #   ece      binned |predicted - observed frequency|, the reliability diagram
    #   oracle   |predicted - the world's ACTUAL rate|, exact because the world
    #            exposes its physics for measurement (never to the learner)
    brier = sum((p - a) ** 2 for p, a in zip(predicted, actual)) / samples
    oracle_error = sum(abs(p - t) for p, t in zip(predicted, oracle_rate)) / samples

    bins = {}
    for p, a in zip(predicted, actual):
        bins.setdefault(min(int(p * 10), 9), []).append((p, a))
    ece = sum(len(v) / samples * abs(sum(x for x, _ in v) / len(v)
                                     - sum(y for _, y in v) / len(v))
              for v in bins.values())

    correct = sum(1 for p, a in zip(predicted, actual) if (p >= 0.5) == (a >= 0.5))
    return {"brier_score": round(brier, 4),
            "expected_calibration_error": round(ece, 4),
            "oracle_probability_error": round(oracle_error, 4),
            "accuracy": round(correct / samples, 4)}


def restart_check(space) -> bool:
    reloaded = ProbabilisticVersionSpace.from_json(space.to_json())
    return (reloaded.posterior() == space.posterior()
            and reloaded.reliability == space.reliability
            and reloaded.observations == space.observations)


def decisive_trap():
    """4 successes then a failure must NOT refute a probabilistic rule."""
    space = ProbabilisticVersionSpace(hypotheses=build_space())
    valid = frozenset(REQUIRED)
    for outcome in ("success", "success", "success"):
        space.observe(valid, outcome)
    before = space.mass_on(TRUE_REQUIRES, TRUE_FORBIDS)
    space.observe(valid, "failure")
    after = space.mass_on(TRUE_REQUIRES, TRUE_FORBIDS)
    space.observe(valid, "success")
    recovered = space.mass_on(TRUE_REQUIRES, TRUE_FORBIDS)
    uniform = 1.0 / len(space.hypotheses)
    fire = space.fire_alpha[0] + space.fire_beta[0]
    return {"mass_before_failure": round(before, 4),
            "mass_after_failure": round(after, 4),
            "mass_after_recovery": round(recovered, 4),
            "uniform_prior_mass": round(uniform, 6),
            # SURVIVING IS NOT "DROPPED BY LESS THAN 10x". A rule that a single
            # unlucky trial pushed BELOW its own prior has been refuted no
            # matter how gentle the arithmetic looked, and a rule that cannot
            # climb back when the next trial succeeds was not being weighed,
            # it was being punished.
            "still_above_prior": after > uniform,
            "recovers_on_next_success": recovered > after,
            "survived": after > uniform and recovered > after,
            "reliability_counts": f"Beta({fire and space.fire_alpha[0]}, {space.fire_beta[0]})",
            "reliability": round(space.reliability, 4)}


def systematic_contradiction():
    """Five failures with LOCKED present must move belief toward FORBIDDEN."""
    space = ProbabilisticVersionSpace(hypotheses=build_space())
    locked = frozenset(REQUIRED) | frozenset(FORBIDDEN)
    before = space.mass_on(TRUE_REQUIRES, TRUE_FORBIDS)
    for _ in range(5):
        space.observe(locked, "failure")
    after = space.mass_on(TRUE_REQUIRES, TRUE_FORBIDS)
    forbidding = sum(p for h, p in zip(space.hypotheses, space.posterior())
                     if h.forbids == TRUE_FORBIDS)
    return {"mass_before": round(before, 6), "mass_after": round(after, 6),
            "belief_in_forbidden_polarity": round(forbidding, 4),
            "moved_toward_forbidden": forbidding > 0.5}


def unknown_is_inert():
    space = ProbabilisticVersionSpace(hypotheses=build_space())
    valid = frozenset(REQUIRED)
    space.observe(valid, "success")
    before, rel = space.posterior(), space.reliability
    for _ in range(10):
        space.observe(valid, "unknown")
    return {"posterior_unchanged": space.posterior() == before,
            "reliability_unchanged": space.reliability == rel,
            "counted_separately": space.unknown_observations == 10}


async def main() -> int:
    assert_truth_reachable()
    print(f"conditions {len(CONDITIONS)} · hypotheses {len(build_space())} · "
          f"budget {BUDGET} · seeds {SEEDS} · criterion mass >= {CRITERION}\n")

    print("invariant probes")
    trap = decisive_trap()
    print(f"   4S then F, valid world : mass {trap['mass_before_failure']} -> "
          f"{trap['mass_after_failure']} -> {trap['mass_after_recovery']}  "
          f"above prior({trap['uniform_prior_mass']})={trap['still_above_prior']}  "
          f"recovers={trap['recovers_on_next_success']}")
    systematic = systematic_contradiction()
    print(f"   5F with LOCKED present : belief in FORBIDDEN polarity "
          f"{systematic['belief_in_forbidden_polarity']}  "
          f"moved={systematic['moved_toward_forbidden']}")
    inert = unknown_is_inert()
    print(f"   10 UNKNOWN             : posterior unchanged="
          f"{inert['posterior_unchanged']} reliability unchanged="
          f"{inert['reliability_unchanged']} counted={inert['counted_separately']}")

    conditions = {"A_deterministic": DETERMINISTIC, "B_stochastic": NOISY,
                  "C_partial": NOISY_PARTIAL}
    results = {}
    print(f"\n{'condition':<18}{'reached':>9}{'median obs':>12}{'95% hi':>9}"
          f"{'MAP=truth':>11}{'trap sprung':>13}{'false refut':>13}{'brier':>8}{'ECE':>8}")
    for name, physics in conditions.items():
        trials = [run_trial(physics, seed) for seed in range(SEEDS)]
        reached = [t for t in trials if t["reached_criterion_at"] is not None]
        obs = sorted(t["reached_criterion_at"] for t in reached)
        results[name] = {
            "trials": SEEDS,
            "reached_criterion": len(reached),
            "reached_rate": round(len(reached) / SEEDS, 3),
            "median_observations": obs[len(obs) // 2] if obs else None,
            "p95_observations": obs[int(len(obs) * 0.95) - 1] if len(obs) > 1 else None,
            "map_is_truth_rate": round(
                sum(1 for t in trials if t["map_is_truth"]) / SEEDS, 3),
            "false_refutation_total": sum(t["false_refutations"] for t in trials),
            "mean_reliability_estimate": round(
                statistics.mean(t["reliability_estimate"] for t in trials), 4),
            "mean_brier_score": round(
                statistics.mean(t["brier_score"] for t in trials), 4),
            "mean_expected_calibration_error": round(
                statistics.mean(t["expected_calibration_error"] for t in trials), 4),
            "mean_oracle_probability_error": round(
                statistics.mean(t["oracle_probability_error"] for t in trials), 4),
            "mean_map_reliability": round(
                statistics.mean(t["map_reliability"] for t in trials), 4),
            "refutation_opportunities": sum(
                t["refutation_opportunities"] for t in trials),
            "misleading_successes": sum(t["misleading_successes"] for t in trials),
            "mean_held_out_accuracy": round(
                statistics.mean(t["held_out_accuracy"] for t in trials), 4),
            "total_replications": sum(t["replications"] for t in trials),
            "deliberate_replications": sum(
                t["deliberate_replications"] for t in trials),
            "restart_preserved_all": all(t["restart_preserves_belief"] for t in trials),
            "all_trials": trials,
        }
        r = results[name]
        print(f"{name:<18}{r['reached_rate']:>9.0%}{str(r['median_observations']):>12}"
              f"{str(r['p95_observations']):>9}{r['map_is_truth_rate']:>11.0%}"
              f"{r['refutation_opportunities']:>13}{r['false_refutation_total']:>13}"
              f"{r['mean_brier_score']:>8.3f}{r['mean_expected_calibration_error']:>8.3f}")

    print(f"\nreplication over an untried option : "
          + "  ".join(f"{k}={results[k]['deliberate_replications']}" for k in results))
    print(f"reliability learned : "
          + "  ".join(f"{k}={results[k]['mean_reliability_estimate']}" for k in results)
          + "   (true 1.00 / 0.90 / 0.90)")
    print(f"misleading successes : "
          + "  ".join(f"{k}={results[k]['misleading_successes']}" for k in results)
          + "   (violated structure, world succeeded anyway)")
    print(f"MAP's own reliability : "
          + "  ".join(f"{k}={results[k]['mean_map_reliability']}" for k in results))
    print(f"restart preserved   : "
          + "  ".join(f"{k}={results[k]['restart_preserved_all']}" for k in results))

    passed = (
        trap["survived"] and systematic["moved_toward_forbidden"]
        and inert["posterior_unchanged"] and inert["reliability_unchanged"]
        and all(r["false_refutation_total"] == 0 for r in results.values())
        and results["B_stochastic"]["refutation_opportunities"] > 0
        and results["B_stochastic"]["misleading_successes"] > 0
        and all(r["reached_rate"] >= 0.9 for r in results.values())
        and all(r["deliberate_replications"] > 0 for r in results.values())
        and all(r["restart_preserved_all"] for r in results.values())
        and results["C_partial"]["map_is_truth_rate"] >= 0.9
    )

    manifest = Path(__file__).resolve().parent / "manifest.json"
    manifest.write_text(json.dumps({
        "benchmark": "EDU-10",
        "title": "Active Learning Under Noise and Uncertainty",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "passed": passed,
        "conditions_count": len(CONDITIONS),
        "hypotheses": len(build_space()),
        "seeds": SEEDS,
        "criterion_posterior_mass": CRITERION,
        "truth": {"requires": sorted(TRUE_REQUIRES), "forbids": sorted(TRUE_FORBIDS)},
        "invariants": {"decisive_trap": trap, "systematic_contradiction": systematic,
                       "unknown_is_inert": inert},
        "results": {k: {kk: vv for kk, vv in v.items() if kk != "all_trials"}
                    for k, v in results.items()},
        "per_trial": {k: v["all_trials"] for k, v in results.items()},
    }, indent=2, default=str))
    print(f"\nEDU-10: {'PASS' if passed else 'FAIL'}")
    print(f"manifest -> {manifest}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
