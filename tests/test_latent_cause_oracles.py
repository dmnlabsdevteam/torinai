#!/usr/bin/env python3
"""Regression oracles for hidden-cause detection.

The whole value of this detector is what it REFUSES to claim, so most of these
tests assert an absence of findings. A detector that only gets credit for
positives will drift toward finding things.
"""

import random

from core.learning.latent_cause_detection import (
    MIN_MINORITY_OUTCOMES, LatentDetection, ResidualVerdict, alignment,
    detect_latent_cause, fit_two_state_hmm, runs_test)


def iid_sequence(rate, n, seed=7):
    rng = random.Random(seed)
    return [rng.random() < rate for _ in range(n)]


def persistent_sequence(n, stay=0.9, on_rate=0.95, seed=11):
    rng = random.Random(seed)
    hidden, outcomes, truth = True, [], []
    for _ in range(n):
        if rng.random() >= stay:
            hidden = not hidden
        truth.append(hidden)
        outcomes.append(hidden and rng.random() < on_rate)
    return outcomes, truth


def test_independent_outcomes_never_produce_a_latent():
    """An i.i.d. hidden cause is INDISTINGUISHABLE from unreliability.

    There is no statistic computable from one outcome sequence that separates
    them, so claiming a latent here is fabricated knowledge -- not a near miss.
    """
    for seed in range(12):
        detection = detect_latent_cause(iid_sequence(0.475, 120, seed=seed))
        assert not detection.posits_latent, (
            f"invented a hidden cause from independent noise (seed {seed}, "
            f"z={detection.runs.z if detection.runs else None})")


def test_a_persistent_hidden_cause_is_found_and_corresponds_to_something_real():
    outcomes, truth = persistent_sequence(160)
    detection = detect_latent_cause(outcomes)
    assert detection.verdict is ResidualVerdict.STRUCTURED_RESIDUAL
    assert detection.runs.z < -2.0
    assert alignment(detection.inferred_state, truth) > 0.8, (
        "a latent was posited that does not track the real hidden state")


def test_too_few_of_the_minority_outcome_is_undetermined_not_a_verdict():
    """The failure that made the control regime report 7% false positives.

    A 95%-reliable action gives ~4 failures in 80 trials. The runs statistic is
    not normal that far into the tail. "Cannot tell" and "nothing there" are
    different claims and must not share a return value.
    """
    sequence = [True] * 78 + [False, False]
    detection = detect_latent_cause(sequence)
    assert detection.verdict is ResidualVerdict.UNDETERMINED
    assert not detection.posits_latent
    assert min(detection.runs.successes, detection.runs.failures) < MIN_MINORITY_OUTCOMES


def test_short_and_constant_sequences_are_undetermined():
    assert detect_latent_cause([True, False] * 5).verdict is ResidualVerdict.UNDETERMINED
    assert detect_latent_cause([True] * 100).verdict is ResidualVerdict.UNDETERMINED
    assert detect_latent_cause([False] * 100).verdict is ResidualVerdict.UNDETERMINED


def test_clustering_is_one_sided():
    """Alternating outcomes are MORE random-looking than chance, not less.

    An over-dispersed sequence (too many runs) is not evidence of a persistent
    hidden cause, and a two-sided test would report one.
    """
    detection = detect_latent_cause([i % 2 == 0 for i in range(120)])
    assert detection.runs.z > 2.0, "alternation should show as excess runs"
    assert not detection.posits_latent


def test_alignment_is_invariant_to_the_latent_having_no_name():
    truth = [True, True, False, False, True]
    assert alignment(truth, truth) == 1.0
    assert alignment([not x for x in truth], truth) == 1.0
    assert alignment([], truth) == 0.0
    assert alignment([True, False], truth) == 0.0


def test_the_fit_is_deterministic_so_a_result_reproduces():
    outcomes, _truth = persistent_sequence(140, seed=3)
    first, rates_a = fit_two_state_hmm(outcomes)
    second, rates_b = fit_two_state_hmm(outcomes)
    assert first == second and rates_a == rates_b
    assert rates_a[0] > rates_a[1], "state 0 must be the higher-emitting state"


def test_runs_test_matches_its_closed_form():
    sequence = [True, True, False, False, True, False]
    result = runs_test(sequence)
    assert result.runs == 4
    assert result.successes == 3 and result.failures == 3
    assert result.expected_runs == 2.0 * 3 * 3 / 6 + 1.0
    assert runs_test([True] * 5) is None


def test_a_detection_that_posits_nothing_carries_no_inferred_state():
    """No half-answers: an unposited latent must not leave a state vector behind
    for a caller to read as if it meant something."""
    detection = detect_latent_cause(iid_sequence(0.5, 120))
    assert not detection.posits_latent
    assert detection.inferred_state == []
    assert LatentDetection(ResidualVerdict.UNDETERMINED).inferred_state == []
