#!/usr/bin/env python3
"""Deciding whether unexplained variance hides a cause or is simply noise.

A learner that has settled on a causal structure still gets outcomes it did not
predict. There are two entirely different explanations, and treating them as
one is how a missing cause becomes a confident number:

    NOISE          the action is genuinely unreliable
    A HIDDEN CAUSE something real gates it that was never observed

From a single success rate these are identical. 47% success is 47% success. The
difference is not in HOW OFTEN the failures happen, it is in WHEN:

    noise scatters      -- outcomes are independent, runs are short
    a persistent cause clusters -- while it is absent everything fails together

So this module never asks "is the rate low". It asks whether the residual
sequence is independent, using the Wald-Wolfowitz runs test, and only then
tries to reconstruct the hidden state with a two-state HMM.

WHAT THIS DELIBERATELY REFUSES TO DO. If the hidden cause flips independently
every trial, it is mathematically indistinguishable from unreliability -- there
is no signature, in this or any other statistic computable from one sequence of
outcomes. Reporting a latent there would be fabricated knowledge, so an
i.i.d. hidden cause must come back NO_RESIDUAL_STRUCTURE. That is not a
limitation being tolerated, it is the correct answer, and EDU-11 measures it as
a pass condition rather than a caveat.

Likewise a short sequence returns UNDETERMINED. "Not enough evidence" and "no
structure" are different claims and must not share a return value.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Sequence, Tuple

#: Below this many trials the runs test has no power worth acting on.
MIN_OBSERVATIONS = 25
#: The runs statistic is normal only when BOTH outcomes occur enough times.
#: Measured without this guard: a 95%-reliable action produces ~4 failures in
#: 80 trials, the approximation breaks down, and the detector claimed a hidden
#: cause in 7% of runs where none existed -- three times its nominal rate. The
#: honest answer with four failures is not "no latent", it is "cannot tell".
MIN_MINORITY_OUTCOMES = 5
#: One-sided. Clustering only ever shows up as FEWER runs than chance.
CLUSTERING_Z = -2.0
HMM_ITERATIONS = 60


class ResidualVerdict(Enum):
    UNDETERMINED = "undetermined"                    # not enough evidence to say
    NO_RESIDUAL_STRUCTURE = "no_residual_structure"  # consistent with noise
    STRUCTURED_RESIDUAL = "structured_residual"      # a persistent hidden cause


@dataclass
class RunsResult:
    runs: int
    expected_runs: float
    z: float
    successes: int
    failures: int


@dataclass
class LatentDetection:
    verdict: ResidualVerdict
    runs: Optional[RunsResult] = None
    observations: int = 0
    #: Reconstructed hidden state per trial. Empty unless STRUCTURED_RESIDUAL.
    inferred_state: List[bool] = field(default_factory=list)
    emission_rates: Tuple[float, float] = (0.0, 0.0)

    @property
    def posits_latent(self) -> bool:
        return self.verdict is ResidualVerdict.STRUCTURED_RESIDUAL


def runs_test(sequence: Sequence[bool]) -> Optional[RunsResult]:
    """Wald-Wolfowitz. Fewer runs than chance means the outcomes clump."""
    n = len(sequence)
    successes = sum(1 for x in sequence if x)
    failures = n - successes
    if successes == 0 or failures == 0:
        return None                      # a constant sequence has no run structure

    runs = 1 + sum(1 for a, b in zip(sequence, sequence[1:]) if a != b)
    expected = 2.0 * successes * failures / n + 1.0
    variance = (2.0 * successes * failures * (2.0 * successes * failures - n)
                / (n * n * (n - 1.0)))
    if variance <= 0.0:
        return None
    return RunsResult(runs, expected, (runs - expected) / math.sqrt(variance),
                      successes, failures)


def _forward_backward(sequence, pi, transition, emission):
    n, states = len(sequence), 2
    alpha = [[0.0] * states for _ in range(n)]
    scale = [0.0] * n
    for s in range(states):
        rate = emission[s] if sequence[0] else 1.0 - emission[s]
        alpha[0][s] = pi[s] * rate
    scale[0] = sum(alpha[0]) or 1e-300
    alpha[0] = [a / scale[0] for a in alpha[0]]

    for t in range(1, n):
        for s in range(states):
            rate = emission[s] if sequence[t] else 1.0 - emission[s]
            alpha[t][s] = rate * sum(alpha[t - 1][p] * transition[p][s]
                                     for p in range(states))
        scale[t] = sum(alpha[t]) or 1e-300
        alpha[t] = [a / scale[t] for a in alpha[t]]

    beta = [[1.0] * states for _ in range(n)]
    for t in range(n - 2, -1, -1):
        for s in range(states):
            beta[t][s] = sum(
                transition[s][q]
                * (emission[q] if sequence[t + 1] else 1.0 - emission[q])
                * beta[t + 1][q] for q in range(states)) / scale[t + 1]
    return alpha, beta, scale


def fit_two_state_hmm(sequence: Sequence[bool], iterations: int = HMM_ITERATIONS):
    """Baum-Welch on binary emissions. Deterministic init, so runs reproduce.

    Two states because the question is binary -- the hidden condition either
    holds or it does not. Fitting more states would let the model absorb noise
    into structure, which is the failure this whole module exists to avoid.
    """
    pi = [0.5, 0.5]
    transition = [[0.8, 0.2], [0.2, 0.8]]
    emission = [0.85, 0.15]              # asymmetric, or the states never separate

    for _ in range(iterations):
        alpha, beta, _ = _forward_backward(sequence, pi, transition, emission)
        n = len(sequence)
        gamma = []
        for t in range(n):
            row = [alpha[t][s] * beta[t][s] for s in range(2)]
            total = sum(row) or 1e-300
            gamma.append([r / total for r in row])

        xi = [[0.0, 0.0], [0.0, 0.0]]
        for t in range(n - 1):
            total = 0.0
            cell = [[0.0, 0.0], [0.0, 0.0]]
            for s in range(2):
                for q in range(2):
                    rate = emission[q] if sequence[t + 1] else 1.0 - emission[q]
                    cell[s][q] = alpha[t][s] * transition[s][q] * rate * beta[t + 1][q]
                    total += cell[s][q]
            total = total or 1e-300
            for s in range(2):
                for q in range(2):
                    xi[s][q] += cell[s][q] / total

        pi = list(gamma[0])
        for s in range(2):
            outgoing = sum(xi[s]) or 1e-300
            transition[s] = [xi[s][q] / outgoing for q in range(2)]
            weight = sum(gamma[t][s] for t in range(n)) or 1e-300
            emission[s] = sum(gamma[t][s] for t in range(n) if sequence[t]) / weight

    alpha, beta, _ = _forward_backward(sequence, pi, transition, emission)
    states = []
    for t in range(len(sequence)):
        on = alpha[t][0] * beta[t][0]
        off = alpha[t][1] * beta[t][1]
        states.append(on >= off)
    # State 0 is whichever emits success more often, so the label means
    # something rather than depending on where the fit happened to land.
    if emission[1] > emission[0]:
        states = [not s for s in states]
        emission = [emission[1], emission[0]]
    return states, (emission[0], emission[1])


def detect_latent_cause(sequence: Sequence[bool],
                        min_observations: int = MIN_OBSERVATIONS) -> LatentDetection:
    """Does this residual sequence hide a persistent cause?"""
    sequence = [bool(x) for x in sequence]
    if len(sequence) < min_observations:
        return LatentDetection(ResidualVerdict.UNDETERMINED, observations=len(sequence))

    result = runs_test(sequence)
    if result is None:
        return LatentDetection(ResidualVerdict.UNDETERMINED, observations=len(sequence))
    if min(result.successes, result.failures) < MIN_MINORITY_OUTCOMES:
        return LatentDetection(ResidualVerdict.UNDETERMINED, runs=result,
                               observations=len(sequence))

    if result.z > CLUSTERING_Z:
        return LatentDetection(ResidualVerdict.NO_RESIDUAL_STRUCTURE, runs=result,
                               observations=len(sequence))

    states, rates = fit_two_state_hmm(sequence)
    return LatentDetection(ResidualVerdict.STRUCTURED_RESIDUAL, runs=result,
                           observations=len(sequence), inferred_state=states,
                           emission_rates=rates)


def alignment(inferred: Sequence[bool], truth: Sequence[bool]) -> float:
    """Agreement between a recovered latent and the real hidden state.

    Reported as max(agreement, 1 - agreement): the two states of a latent have
    no intrinsic names, so recovering it perfectly inverted is recovering it.
    Chance is 0.5, and only a value well above that is evidence.
    """
    if not inferred or len(inferred) != len(truth):
        return 0.0
    agree = sum(1 for a, b in zip(inferred, truth) if a == b) / len(truth)
    return max(agree, 1.0 - agree)


__all__ = ["ResidualVerdict", "RunsResult", "LatentDetection", "runs_test",
           "fit_two_state_hmm", "detect_latent_cause", "alignment",
           "MIN_OBSERVATIONS", "MIN_MINORITY_OUTCOMES", "CLUSTERING_Z"]
