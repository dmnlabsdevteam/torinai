#!/usr/bin/env python3
"""EDU-11 — Causal Discovery With an Unobservable Cause.

Every experiment up to EDU-10 gave the learner a vocabulary that CONTAINED the
answer. Its problem was picking the right conditions out of a list that
included them. Here one genuine precondition is not in the list at all.

The failure mode this is built to catch is not getting the structure wrong. It
is getting the structure RIGHT and then absorbing the missing cause into the
reliability parameter -- reporting "this action works 47% of the time" with
good calibration and complete confidence, when in truth it works 95% of the
time under a condition nobody ever looked at. A missing cause laundered into a
known quantity.

THREE REGIMES WITH IDENTICAL SUCCESS RATES, so only time structure differs:

    A  NO_LATENT     hidden condition always holds        -- negative control
    B  IID_LATENT    flips independently each trial       -- UNIDENTIFIABLE
    C  PERSISTENT    a Markov chain, stay probability 0.9 -- identifiable

Detecting a latent is the WRONG answer in A and B. An i.i.d. hidden cause is
mathematically indistinguishable from unreliability, so claiming to have found
one is fabricated knowledge, and B exists to make that failure visible rather
than to be excused in a footnote.
"""

from __future__ import annotations

import json
import os
import statistics
import sys
from datetime import datetime, timezone
from itertools import combinations
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from core.learning.latent_cause_detection import (  # noqa: E402
    ResidualVerdict, alignment, detect_latent_cause)
from core.learning.probabilistic_version_space import (  # noqa: E402
    ProbabilisticVersionSpace, StructuralHypothesis)
from experiments.warehouse_complex import (  # noqa: E402
    CAUSAL_NEGATIVE, CAUSAL_POSITIVE, DISTRACTORS as ALL_DISTRACTORS)
from experiments.warehouse_latent import (  # noqa: E402
    IID_LATENT, NO_LATENT, PERSISTENT_LATENT, LatentWarehouse,
    observable_structure_satisfied)

# Derived from the world, never restated -- EDU-10 lost a full run to a
# literal that had drifted from the world's actual structure.
REQUIRED = CAUSAL_POSITIVE
FORBIDDEN = CAUSAL_NEGATIVE
DISTRACTORS = ALL_DISTRACTORS[:2]
CONDITIONS = REQUIRED + FORBIDDEN + DISTRACTORS
CANDIDATES = tuple(c for c in CONDITIONS if c not in FORBIDDEN)
TRUE_REQUIRES, TRUE_FORBIDS = frozenset(REQUIRED), frozenset(FORBIDDEN)

SEEDS = int(os.environ.get("EDU11_SEEDS", "30"))
MAX_OBSERVATIONS = int(os.environ.get("EDU11_MAX_OBS", "400"))
RESIDUAL_TRIALS = int(os.environ.get("EDU11_RESIDUAL", "80"))
CRITERION = 0.90


def build_space():
    return [StructuralHypothesis(frozenset(chosen), forbids)
            for size in range(len(CANDIDATES) + 1)
            for chosen in combinations(CANDIDATES, size)
            for forbids in (frozenset(), frozenset(FORBIDDEN))]


def assert_truth_reachable() -> None:
    reference = frozenset(CANDIDATES)
    if not observable_structure_satisfied(reference):
        missing = sorted(set(CAUSAL_POSITIVE) - set(CONDITIONS))
        raise AssertionError(f"observable structure unreachable; missing: {missing}")
    if observable_structure_satisfied(reference | frozenset(FORBIDDEN)):
        raise AssertionError("the forbidden condition does not block the action")


def proposals():
    reference = frozenset(CANDIDATES)
    return ([reference, reference | frozenset(FORBIDDEN)]
            + [reference - {c} for c in CANDIDATES])


def run_trial(physics, seed):
    world = LatentWarehouse(physics, seed=seed)
    space = ProbabilisticVersionSpace(hypotheses=build_space())
    menu = proposals()

    reached = None
    while space.observations < MAX_OBSERVATIONS:
        if space.mass_on(TRUE_REQUIRES, TRUE_FORBIDS) >= CRITERION:
            reached = space.observations
            break
        gains = [space.expected_information_gain(s) for s in menu]
        best = max(range(len(menu)), key=gains.__getitem__)
        if gains[best] <= 1e-9:
            break
        chosen = menu[best]
        succeeded, _hidden = world.attempt(chosen)
        space.observe(chosen, "success" if succeeded else "failure")

    best_hypothesis, _mass = space.most_probable()
    structure_correct = (best_hypothesis.requires == TRUE_REQUIRES
                         and best_hypothesis.forbids == TRUE_FORBIDS)

    # THE RESIDUAL. Replications of a situation the learned structure says
    # should work. Whatever varies here is by definition not explained by the
    # structure the learner holds.
    reference = frozenset(CANDIDATES)
    outcomes, hidden_truth = [], []
    for _ in range(RESIDUAL_TRIALS):
        succeeded, hidden = world.attempt(reference)
        outcomes.append(succeeded)
        hidden_truth.append(hidden)

    detection = detect_latent_cause(outcomes)
    observed_rate = sum(outcomes) / len(outcomes)
    return {
        "seed": seed,
        "observations_to_structure": reached,
        "structure_correct": structure_correct,
        "learned_requires": sorted(best_hypothesis.requires),
        "learned_forbids": sorted(best_hypothesis.forbids),
        "residual_success_rate": round(observed_rate, 4),
        "verdict": detection.verdict.value,
        "posits_latent": detection.posits_latent,
        "runs_z": round(detection.runs.z, 3) if detection.runs else None,
        "latent_alignment": round(alignment(detection.inferred_state, hidden_truth), 4),
        "recovered_on_rate": (round(detection.emission_rates[0], 4)
                              if detection.posits_latent else None),
    }


def main() -> int:
    assert_truth_reachable()
    print(f"conditions {len(CONDITIONS)} · hypotheses {len(build_space())} · "
          f"seeds {SEEDS} · residual trials {RESIDUAL_TRIALS}\n")

    regimes = {"A_no_latent": NO_LATENT, "B_iid_latent": IID_LATENT,
               "C_persistent": PERSISTENT_LATENT}
    results = {}
    print(f"{'regime':<16}{'structure ok':>14}{'posits latent':>15}"
          f"{'alignment':>11}{'residual rate':>15}{'median obs':>12}")
    for name, physics in regimes.items():
        trials = [run_trial(physics, seed) for seed in range(SEEDS)]
        posited = [t for t in trials if t["posits_latent"]]
        solved = [t["observations_to_structure"] for t in trials
                  if t["observations_to_structure"] is not None]
        results[name] = {
            "trials": SEEDS,
            "structure_correct_rate": round(
                sum(1 for t in trials if t["structure_correct"]) / SEEDS, 3),
            "posits_latent_rate": round(len(posited) / SEEDS, 3),
            "mean_alignment": round(
                statistics.mean(t["latent_alignment"] for t in posited), 4)
            if posited else None,
            "mean_residual_success_rate": round(
                statistics.mean(t["residual_success_rate"] for t in trials), 4),
            "median_observations": (sorted(solved)[len(solved) // 2]
                                    if solved else None),
            "reached_structure_rate": round(len(solved) / SEEDS, 3),
            "verdicts": {v.value: sum(1 for t in trials if t["verdict"] == v.value)
                         for v in ResidualVerdict},
            "all_trials": trials,
        }
        r = results[name]
        align = f"{r['mean_alignment']:.3f}" if r["mean_alignment"] is not None else "--"
        print(f"{name:<16}{r['structure_correct_rate']:>14.0%}"
              f"{r['posits_latent_rate']:>15.0%}{align:>11}"
              f"{r['mean_residual_success_rate']:>15.3f}"
              f"{str(r['median_observations']):>12}")

    print("\nverdicts")
    for name, r in results.items():
        print(f"   {name:<16}" + "  ".join(f"{k}={v}" for k, v in r["verdicts"].items()))

    passed = (
        # A hidden cause must not corrupt what IS observable.
        all(r["structure_correct_rate"] >= 0.9 for r in results.values())
        # Never invent a cause where there is none...
        and results["A_no_latent"]["posits_latent_rate"] <= 0.1
        # ...nor where one exists but is provably unidentifiable.
        and results["B_iid_latent"]["posits_latent_rate"] <= 0.1
        # But find it when it leaves a signature, and have it mean something.
        and results["C_persistent"]["posits_latent_rate"] >= 0.9
        and (results["C_persistent"]["mean_alignment"] or 0.0) >= 0.8
    )

    manifest = Path(__file__).resolve().parent / "manifest.json"
    manifest.write_text(json.dumps({
        "benchmark": "EDU-11",
        "title": "Causal Discovery With an Unobservable Cause",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "passed": passed,
        "model_calls": 0,
        "seeds": SEEDS,
        "residual_trials": RESIDUAL_TRIALS,
        "truth": {"observable_requires": sorted(TRUE_REQUIRES),
                  "observable_forbids": sorted(TRUE_FORBIDS),
                  "hidden": "CALIBRATED"},
        "results": {k: {kk: vv for kk, vv in v.items() if kk != "all_trials"}
                    for k, v in results.items()},
        "per_trial": {k: v["all_trials"] for k, v in results.items()},
    }, indent=2, default=str))
    print(f"\nEDU-11: {'PASS' if passed else 'FAIL'}")
    print(f"manifest -> {manifest}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
