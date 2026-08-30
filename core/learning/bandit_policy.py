"""Bandit policies for learning strategy selection.

This module provides lightweight multi-armed bandit helpers used by
MetaLearner and other components to select among strategies based on
observed success/failure outcomes.

The current implementation uses Thompson sampling with Beta priors
(Bernoulli rewards) and can optionally factor in average latency to
prefer faster strategies when desired.
"""

from __future__ import annotations

import logging
import random
from typing import Iterable, Protocol, runtime_checkable, List

logger = logging.getLogger(__name__)


@runtime_checkable
class BanditStrategyLike(Protocol):
    """Minimal interface required for bandit-based selection.

    This matches the attributes provided by MetaLearner's LearningStrategy
    dataclass without importing it directly (to avoid circular imports).
    """

    strategy_id: str
    successes: int
    failures: int
    avg_time_ms: float


# Two sampled rewards this close are not distinguishable by the evidence on
# this draw. Only inside that band may anything other than evidence decide.
# 0.02 = two percentage points of success probability.
TIE_TOLERANCE = 0.02


def _require_arms(candidates: List[BanditStrategyLike]) -> None:
    """Reject anything that is not a real bandit arm, loudly.

    ``getattr(s, "successes", 0)`` used to absorb this. An object carrying no
    counts became Beta(1,1) — indistinguishable from an arm with genuinely no
    evidence yet — so selection silently degraded to a uniform coin flip and
    reported a confident winner. Measured before this guard existed: 4000 draws
    over four enum members carrying no counts came out 1008/1006/1006/980.

    It was reachable by name alone. core/learning/core_types.py defined a second
    Enum also called ``LearningStrategy`` and ``core.learning`` star-exported
    it, so ``from core.learning import LearningStrategy`` handed the caller that
    enum rather than the arm dataclass at meta_learning.py:138. Both the
    duplicate and the star-export are gone; this guard is what stops the class
    of mistake from returning quietly.

    Absent counts are not zero counts. A malformed arm list is a wiring defect
    and must not be able to masquerade as an unexplored posterior.
    """
    required = ("successes", "failures")
    for s in candidates:
        missing = [a for a in required if not hasattr(s, a)]
        if missing:
            raise TypeError(
                f"bandit arm {s!r} (type {type(s).__name__}) is missing "
                f"{missing}; it is not a bandit arm. Expected the "
                f"LearningStrategy dataclass from core.learning.meta_learning, "
                f"not the same-named Enum star-exported from core.learning."
            )


def _posterior_sample(s: BanditStrategyLike) -> float:
    """One draw from Beta(successes+1, failures+1) — the evidence, untouched."""
    alpha = max(1.0, float(s.successes) + 1.0)
    beta = max(1.0, float(s.failures) + 1.0)
    return random.betavariate(alpha, beta)


def _pick(
    scored: List[tuple],
    prefer_fast: bool,
    tie_tolerance: float,
) -> BanditStrategyLike | None:
    """Argmax over posterior samples; speed breaks ties ONLY.

    Shared by selection and propensity estimation so the two can never describe
    different policies — a propensity that does not match the actual selection
    rule makes every IPS estimate built on it silently wrong.
    """
    if not scored:
        return None

    best_value = max(v for _, v in scored)
    if not prefer_fast:
        return max(scored, key=lambda sv: sv[1])[0]

    # Latency is a TIE-BREAK, never a weight.
    #
    # This used to be `score = sample * 1/(1 + ms/1000)`, which let latency
    # overrule the reward posterior outright: a coin-flip strategy at 200ms beat
    # a 95%-reliable one at 2s on 99.4% of draws, because a 10x latency gap is a
    # 2.5x score penalty while 95% vs 50% is only ~1.9x in sampled reward. It
    # also stopped being Thompson sampling, since the score was no longer a draw
    # from the posterior.
    #
    # Evidence decides first. Speed decides only among arms this draw could not
    # separate.
    contenders = [s for s, v in scored if v >= best_value - tie_tolerance]
    if len(contenders) == 1:
        return contenders[0]
    return min(
        contenders,
        key=lambda s: float(getattr(s, "avg_time_ms", 0.0) or 0.0),
    )


def thompson_sample_strategy(
    candidates: Iterable[BanditStrategyLike],
    prefer_fast: bool = False,
    baseline_ms: float = 1000.0,
    tie_tolerance: float = TIE_TOLERANCE,
) -> BanditStrategyLike | None:
    """Select a strategy using Thompson sampling over Beta(successes, failures).

    Args:
        candidates: Iterable of strategy-like objects.
        prefer_fast: If True, prefer the faster arm AMONG arms the evidence
            cannot separate. Never overrides a real difference in reward.
        baseline_ms: Retained for signature compatibility; latency is no longer
            scaled against a baseline because it no longer scales the reward.
        tie_tolerance: How close two sampled rewards must be to count as
            indistinguishable on this draw.

    Returns:
        Selected strategy or None if candidates is empty.
    """

    candidates_list: List[BanditStrategyLike] = list(candidates)
    if not candidates_list:
        return None
    _require_arms(candidates_list)

    scored = [(s, _posterior_sample(s)) for s in candidates_list]
    best = _pick(scored, prefer_fast, tie_tolerance)

    logger.debug(
        "Bandit selection: picked %s among %d candidates",
        getattr(best, "strategy_id", "<unknown>"),
        len(candidates_list),
    )

    return best


def thompson_sample_with_propensities(
    candidates: Iterable[BanditStrategyLike],
    prefer_fast: bool = False,
    baseline_ms: float = 1000.0,
    propensity_draws: int = 128,
    tie_tolerance: float = TIE_TOLERANCE,
) -> tuple[BanditStrategyLike | None, List[dict]]:
    """Select a strategy AND report the propensity of every arm.

    Identical selection behaviour to ``thompson_sample_strategy`` -- it defers
    to that function for the actual pick -- but additionally estimates, for
    each arm, the probability that this policy would have chosen it in this
    state.

    Why this exists: Thompson sampling draws a Beta sample per arm and takes
    the argmax, then discards the samples. Off-policy estimation of "what would
    arm B have done?" (IPS, doubly-robust) requires the probability the policy
    assigned to each arm *at decision time*. That number cannot be recovered
    afterwards from the posterior alone, because the posterior has since moved.
    Every episode logged without it is an episode that can never be used for
    counterfactual credit assignment.

    Thompson propensities have no closed form, so they are estimated by Monte
    Carlo over the same Beta posteriors used for the selection.

    Returns:
        (selected strategy or None, list of per-arm dicts with strategy_id,
        alpha, beta, and propensity)
    """

    candidates_list: List[BanditStrategyLike] = list(candidates)
    if not candidates_list:
        return None, []
    _require_arms(candidates_list)

    params = []
    for s in candidates_list:
        alpha = max(1.0, float(s.successes) + 1.0)
        beta = max(1.0, float(s.failures) + 1.0)
        params.append((getattr(s, "strategy_id", "<unknown>"), alpha, beta))

    # Estimate by simulating the SAME rule the selector uses — via _pick — not a
    # reimplementation of it. The two previously shared a formula by copy, so a
    # change to one would have silently decalibrated the other, and a propensity
    # that does not match the real selection rule biases every IPS and
    # doubly-robust estimate downstream with nothing to reveal it.
    index_of = {id(s): i for i, s in enumerate(candidates_list)}
    wins = [0] * len(params)
    for _ in range(max(1, propensity_draws)):
        scored = [(s, _posterior_sample(s)) for s in candidates_list]
        winner = _pick(scored, prefer_fast, tie_tolerance)
        if winner is not None:
            wins[index_of[id(winner)]] += 1

    draws = float(max(1, propensity_draws))
    diagnostics = [
        {
            "strategy_id": sid,
            "alpha": alpha,
            "beta": beta,
            "propensity": wins[i] / draws,
        }
        for i, (sid, alpha, beta) in enumerate(params)
    ]

    selected = thompson_sample_strategy(
        candidates_list,
        prefer_fast=prefer_fast,
        baseline_ms=baseline_ms,
        tie_tolerance=tie_tolerance,
    )
    return selected, diagnostics


__all__ = [
    "BanditStrategyLike",
    "thompson_sample_strategy",
    "thompson_sample_with_propensities",
]
