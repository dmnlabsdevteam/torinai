#!/usr/bin/env python3
"""Regression oracles for learning a causal structure under noise.

Every test here corresponds to a defect that was actually present and was found
by an experiment failing, not by inspection. EDU-10 exercises them end to end;
these keep them in the suite so a regression is loud rather than silent.
"""

from itertools import combinations

import pytest

from core.learning.probabilistic_version_space import (
    LEAK_PRIOR, RELIABILITY_PRIOR, ProbabilisticVersionSpace,
    StructuralHypothesis)

REQUIRED = frozenset({"LOCATED", "ROUTE", "AVAILABLE"})
FORBIDDEN = frozenset({"LOCKED"})
CANDIDATES = ("LOCATED", "ROUTE", "AVAILABLE", "PAINTED_RED")


def build_space():
    return [StructuralHypothesis(frozenset(chosen), forbids)
            for size in range(len(CANDIDATES) + 1)
            for chosen in combinations(CANDIDATES, size)
            for forbids in (frozenset(), FORBIDDEN)]


def fresh():
    return ProbabilisticVersionSpace(hypotheses=build_space())


def test_priors_are_asymmetric_so_some_experiment_carries_information():
    """Uniform priors deadlock the learner into taking ZERO observations.

    With Beta(1,1) on both rates a satisfied structure and a violated one both
    predict success at 0.50, every hypothesis predicts identically, expected
    information gain is exactly zero everywhere, and refusing to observe is the
    CORRECT response to a question that cannot be answered. The bug is the
    prior, and it presents as a learner that looks broken.
    """
    assert RELIABILITY_PRIOR[0] / sum(RELIABILITY_PRIOR) > LEAK_PRIOR[0] / sum(LEAK_PRIOR)

    space = fresh()
    discriminating = frozenset(CANDIDATES) - {"LOCATED"}
    assert space.expected_information_gain(discriminating) > 1e-6, (
        "no situation carries information -- the learner cannot begin")


def test_a_situation_every_hypothesis_agrees_on_carries_no_information():
    """The other half of the same claim: gain must be zero when it should be."""
    space = fresh()
    # Every hypothesis fires here, so no outcome separates any of them.
    assert space.expected_information_gain(frozenset(CANDIDATES)) == pytest.approx(0.0, abs=1e-9)


def test_one_failure_does_not_refute_a_rule_its_own_reliability_predicts():
    """THE decisive trap. 4 successes then a failure must leave the rule standing.

    "Survived" is not "dropped by less than 10x". A rule pushed BELOW its own
    prior by a single unlucky trial has been refuted however gentle the
    arithmetic looked, and one that cannot climb back on the next success was
    being punished rather than weighed.
    """
    space = fresh()
    satisfied = REQUIRED
    for _ in range(4):
        space.observe(satisfied, "success")

    before = space.mass_on(REQUIRED, FORBIDDEN)
    space.observe(satisfied, "failure")
    after = space.mass_on(REQUIRED, FORBIDDEN)
    space.observe(satisfied, "success")
    recovered = space.mass_on(REQUIRED, FORBIDDEN)

    uniform = 1.0 / len(space.hypotheses)
    assert after > uniform, "one stochastic failure pushed the truth below its prior"
    assert recovered > after, "belief could not recover when the world cooperated again"
    assert before > uniform


def test_systematic_contradiction_still_moves_structural_belief():
    """Refusing to refute must not become refusing to learn.

    The mirror of the trap above: repeated failures whenever a condition is
    PRESENT have to shift belief toward that condition being forbidden.
    """
    space = fresh()
    locked = REQUIRED | FORBIDDEN
    for _ in range(6):
        space.observe(locked, "failure")

    forbidding = sum(p for h, p in zip(space.hypotheses, space.posterior())
                     if h.forbids == FORBIDDEN)
    assert forbidding > 0.5, "systematic contradiction failed to challenge structure"


def test_unknown_observations_change_absolutely_nothing():
    """UNKNOWN is inert. Reading it as failure manufactures evidence.

    It must not move the posterior AND must not touch the rate counts -- an
    attempt whose result was never established is not a trial of anything.
    """
    space = fresh()
    space.observe(REQUIRED, "success")
    posterior, reliability, leak = space.posterior(), space.reliability, space.leak
    fire_counts = list(space.fire_alpha), list(space.fire_beta)

    for _ in range(10):
        space.observe(REQUIRED, "unknown")

    assert space.posterior() == posterior
    assert space.reliability == reliability
    assert space.leak == leak
    assert (list(space.fire_alpha), list(space.fire_beta)) == fire_counts
    assert space.unknown_observations == 10
    assert space.observations == 11, "UNKNOWN must still be counted as an attempt"


def test_each_hypothesis_books_its_own_rates_rather_than_sharing_a_global():
    """The collapse that made learning impossible.

    A single shared reliability, split fractionally by posterior belief,
    charges part of every violated-structure failure to reliability. The
    discriminating experiments are exactly the ones that violate the true
    structure, so reliability collapsed to 0.05 against a true 0.90 and the
    learner stopped being able to tell any two hypotheses apart.

    Under a situation that satisfies A but not B, a failure must be booked to
    A's RELIABILITY and to B's LEAK -- never split between them.
    """
    space = fresh()
    satisfied = frozenset(CANDIDATES)          # fires for every hypothesis
    partial = frozenset({"LOCATED"})           # fires only for small hypotheses

    fires = [i for i, h in enumerate(space.hypotheses) if h.fires(partial)]
    misses = [i for i, h in enumerate(space.hypotheses) if not h.fires(partial)]
    assert fires and misses, "the probe situation does not separate anything"

    space.observe(partial, "failure")

    for i in fires:
        assert space.fire_beta[i] == RELIABILITY_PRIOR[1] + 1.0
        assert space.leak_beta[i] == LEAK_PRIOR[1], "a firing hypothesis booked a leak trial"
    for i in misses:
        assert space.leak_beta[i] == LEAK_PRIOR[1] + 1.0
        assert space.fire_beta[i] == RELIABILITY_PRIOR[1], (
            "a non-firing hypothesis was debited for reliability it never claimed")
    # Note the situation every hypothesis fires on is NOT informationless any
    # more: they now hold different rates, so its outcome separates them. That
    # is the whole point of per-hypothesis books. The fresh-space case is
    # covered by its own test above.
    assert space.expected_information_gain(satisfied) > 0.0


def test_the_correct_structure_wins_under_noise_and_misleading_evidence():
    """End to end: 90% reliable, 2% leak, and the truth still wins.

    Includes the two observations that are logically IMPOSSIBLE in a
    deterministic world -- a failure under a satisfied structure and a success
    under a violated one -- either of which would be a valid refutation there.
    """
    space = fresh()
    satisfied = REQUIRED | {"PAINTED_RED"}
    locked = satisfied | FORBIDDEN

    def truth_holds(situation):
        return REQUIRED <= situation and not (FORBIDDEN & situation)

    # ONE ABLATION PER CANDIDATE, INCLUDING THE DISTRACTOR. Removing several at
    # once cannot separate them, and never removing one at all leaves its role
    # unidentifiable: if PAINTED_RED is present in every situation, "requires
    # PAINTED_RED" explains the record exactly as well as the truth and the
    # posterior splits 0.5/0.5 between two observationally equivalent
    # structures. That is the learner being correct about what the evidence
    # supports, not a failure to learn.
    situations = [satisfied, locked] + [satisfied - {c} for c in CANDIDATES]

    for _ in range(12):
        for situation in situations:
            space.observe(situation, "success" if truth_holds(situation) else "failure")
    space.observe(satisfied, "failure")                     # unlucky: reliability, not structure
    space.observe(satisfied - {"LOCATED"}, "success")       # leak: misleading, must not mislead

    best, mass = space.most_probable()
    assert best.requires == REQUIRED, f"learned the wrong preconditions: {sorted(best.requires)}"
    assert best.forbids == FORBIDDEN, "lost the negative-only condition"
    assert mass > 0.95

    reliability, leak = space.rates_of_most_probable()
    assert reliability > leak, "reliability and leak are not separated"
    assert 0.6 < reliability < 1.0
    assert leak < 0.35


def test_belief_survives_a_restart_exactly():
    """Belief that does not survive a restart was never really held."""
    space = fresh()
    for outcome, situation in (("success", REQUIRED), ("failure", frozenset({"LOCATED"})),
                               ("unknown", REQUIRED), ("success", REQUIRED)):
        space.observe(situation, outcome)

    reloaded = ProbabilisticVersionSpace.from_json(space.to_json())
    assert reloaded.posterior() == space.posterior()
    assert reloaded.reliability == space.reliability
    assert reloaded.leak == space.leak
    assert reloaded.fire_alpha == space.fire_alpha
    assert reloaded.fire_beta == space.fire_beta
    assert reloaded.leak_alpha == space.leak_alpha
    assert reloaded.leak_beta == space.leak_beta
    assert reloaded.observations == space.observations
    assert reloaded.unknown_observations == space.unknown_observations
    # And it must keep LEARNING identically, not merely look identical.
    probe = frozenset({"LOCATED", "ROUTE"})
    space.observe(probe, "failure")
    reloaded.observe(probe, "failure")
    assert reloaded.posterior() == space.posterior()
