#!/usr/bin/env python3
"""Focused tests for the bandit-based MetaLearner strategy selection.

These tests are intentionally self-contained and do not depend on the
legacy, broader test suite. They validate that:

- Thompson sampling prefers higher-success strategies over many trials.
- Latency-aware selection (`prefer_fast=True`) can favor a faster but
  slightly less successful strategy when appropriate.
- `MetaLearner.select_strategy` wires through to the bandit helper and
  returns one of the configured strategies for a given `TaskFamily`.
"""

from __future__ import annotations

import asyncio
from collections import Counter

from core.learning.bandit_policy import thompson_sample_strategy
from core.learning.meta_learning import MetaLearner, LearningStrategy, TaskFamily, LearningStrategyType


def _run(coro):
    """Synchronously run a coroutine, independent of any ambient loop.

    Was ``asyncio.get_event_loop().run_until_complete(coro)``. get_event_loop()
    only auto-creates a loop when one has never existed in the thread; once an
    earlier test has created and closed one it raises

        RuntimeError: There is no current event loop in thread 'MainThread'

    so this file passed alone and failed whenever anything async ran before it
    — a real defect in the harness that looked like flakiness. asyncio.run owns
    its loop for the call and closes it, so ordering cannot affect the result.
    """

    return asyncio.run(coro)


class DummyStrategy(LearningStrategy):
    """Thin wrapper so we can easily construct strategies for bandit tests."""

    def __init__(self, strategy_id: str, successes: int, failures: int, avg_time_ms: float) -> None:
        super().__init__(
            strategy_id=strategy_id,
            strategy_type=LearningStrategyType(strategy_id),
            task_type=TaskFamily.CLASSIFICATION,
            parameters={},
        )
        self.successes = successes
        self.failures = failures
        self.trials = successes + failures
        self.avg_time_ms = avg_time_ms


def test_thompson_sampling_prefers_higher_success_rate():
    """Bandit policy should favor the arm with clearly higher success rate."""

    fast_bad = DummyStrategy("fast_bad", successes=10, failures=40, avg_time_ms=100)
    slow_good = DummyStrategy("slow_good", successes=40, failures=10, avg_time_ms=1000)

    wins = Counter()
    for _ in range(500):
        chosen = thompson_sample_strategy([fast_bad, slow_good], prefer_fast=False)
        wins[chosen.strategy_id] += 1

    # With such different posteriors, slow_good should win a strong majority.
    assert wins["slow_good"] > wins["fast_bad"] * 3


def test_thompson_sampling_latency_breaks_ties_only():
    """Latency decides only among arms this draw could not separate.

    This asserted the opposite contract: slow=30/10 (75%) vs fast=28/12 (70%)
    with prefer_fast=True, expecting the faster arm to win. That was true when
    the score was `sample * 1/(1 + ms/1000)`, which let a 10x latency gap
    overrule a real 5pp difference in reward -- and stopped being Thompson
    sampling, since the score was no longer a draw from the posterior.

    Evidence decides first now, so the same setup gives the 75% arm the
    majority. What latency legitimately settles is a genuine tie.
    """

    # Identical evidence -> the draw cannot separate them -> speed decides.
    slow = DummyStrategy("slow", successes=30, failures=10, avg_time_ms=2000)
    fast = DummyStrategy("fast", successes=30, failures=10, avg_time_ms=200)

    wins = Counter()
    for _ in range(500):
        chosen = thompson_sample_strategy([slow, fast], prefer_fast=True)
        wins[chosen.strategy_id] += 1

    assert wins["fast"] > wins["slow"], (
        f"identical posteriors should hand every separable-by-speed draw to "
        f"the faster arm, got {dict(wins)}"
    )


def test_thompson_sampling_latency_never_overrides_evidence():
    """A real difference in reward survives an order-of-magnitude latency gap."""

    better_slow = DummyStrategy("better_slow", successes=30, failures=10, avg_time_ms=2000)
    worse_fast = DummyStrategy("worse_fast", successes=28, failures=12, avg_time_ms=200)

    wins = Counter()
    for _ in range(500):
        chosen = thompson_sample_strategy([better_slow, worse_fast], prefer_fast=True)
        wins[chosen.strategy_id] += 1

    assert wins["better_slow"] > wins["worse_fast"], (
        f"75% at 2000ms must still beat 70% at 200ms, got {dict(wins)}"
    )


def test_thompson_sampling_refuses_non_arms():
    """An object with no counts is a wiring defect, not an unexplored arm."""

    import pytest

    class NotAnArm:
        strategy_id = "impostor"

    with pytest.raises(TypeError, match="not a bandit arm"):
        thompson_sample_strategy([NotAnArm(), NotAnArm()])


def test_meta_learner_select_strategy_uses_bandit_layer():
    """MetaLearner.select_strategy should return a plausible strategy for a task type.

    This is a smoke test that the bandit-based selection path and
    task_strategy_map wiring are functioning.
    """

    ml = MetaLearner(config={"enable_adaptation": False})

    # Clear any auto-added defaults to control the environment tightly.
    ml.strategies.clear()
    ml.task_strategy_map.clear()

    # And KEEP it cleared. select_strategy() calls _ensure_loaded(), which
    # restores every persisted arm from meta_learning_strategies -- so the two
    # clears above are undone the moment the bandit is exercised, and a real arm
    # (classification_transfer, 130+ trials at confidence 1.0) beats the seeded
    # s1/s2 every time. The test only passed standalone because nothing had
    # initialised the database yet in that process; run after any test that
    # does, it failed. This test is about the selection layer, not persistence,
    # so the instance is marked loaded to make it hermetic either way.
    ml._loaded = True

    # Manually register two strategies for CLASSIFICATION.
    s1_id = ml._add_strategy(
        strategy_type=LearningStrategyType("s1"),
        task_type=TaskFamily.CLASSIFICATION,
        parameters={},
    )
    s2_id = ml._add_strategy(
        strategy_type=LearningStrategyType("s2"),
        task_type=TaskFamily.CLASSIFICATION,
        parameters={},
    )

    # Seed stats so both are above confidence threshold and valid.
    s1 = ml.strategies[s1_id]
    s2 = ml.strategies[s2_id]

    s1.trials = 20
    s1.successes = 15
    s1.failures = 5
    s1.success_rate = 0.75
    s1.avg_time_ms = 800
    s1.effectiveness_score = 80.0
    s1.confidence = 0.9

    s2.trials = 20
    s2.successes = 10
    s2.failures = 10
    s2.success_rate = 0.5
    s2.avg_time_ms = 500
    s2.effectiveness_score = 50.0
    s2.confidence = 0.9

    chosen = _run(
        ml.select_strategy(
            task_type=TaskFamily.CLASSIFICATION,
            prefer_fast=False,
            min_confidence=0.5,
            enable_hard_gate=False,
        )
    )

    assert chosen is not None
    assert chosen.strategy_id in {s1_id, s2_id}

    # Given the seeded statistics and no latency preference, the higher
    # success-rate arm should win much more often if we sample repeatedly.
    wins = Counter()
    for _ in range(200):
        c = _run(
            ml.select_strategy(
                task_type=TaskFamily.CLASSIFICATION,
                prefer_fast=False,
                min_confidence=0.5,
                enable_hard_gate=False,
            )
        )
        wins[c.strategy_id] += 1

    assert wins[s1_id] > wins[s2_id]
