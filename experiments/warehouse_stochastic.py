#!/usr/bin/env python3
"""The EDU-09 warehouse, with reality made unreliable.

Same causal structure -- five required conditions and one forbidden -- so any
difference in what is learned is attributable to the noise rather than to a
different problem. What changes is that satisfying the structure no longer
guarantees the action works, violating it no longer guarantees it fails, and
the observer sometimes cannot tell.

    structure satisfied  -> succeeds SUCCESS_RATE of the time
    structure violated   -> succeeds LEAK_RATE of the time
    observer             -> returns UNKNOWN at UNKNOWN_RATE

These numbers are experiment policy, not a model of anything. The RNG is seeded
and the seed is recorded, so a run is reproducible exactly.

THE POINT OF THE LEAK RATE: without it, a single success under a violated
structure would be logically impossible, and one such observation would still
be a deterministic refutation. A world where "shouldn't work" means "never
works" is not actually stochastic in the direction that matters.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from enum import Enum
from typing import FrozenSet, Optional, Set, Tuple

from core.learning.rule_induction import Fact
from experiments.warehouse_complex import (
    ALL_CONDITIONS, ARGUMENT_OF, CAUSAL_NEGATIVE, CAUSAL_POSITIVE)


class Outcome(Enum):
    """What the observer could establish. UNKNOWN is a first-class answer.

    It is NOT failure and NOT success. Collapsing it either way manufactures
    evidence out of an observation that did not happen -- and it is the reading
    a learner is most tempted to take, because both other values are usable.
    """
    SUCCESS = "success"
    FAILURE = "failure"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class Physics:
    success_rate: float = 0.90      # P(succeeds | structure satisfied)
    leak_rate: float = 0.02         # P(succeeds | structure violated)
    unknown_rate: float = 0.10      # P(observer cannot tell)

    @property
    def deterministic(self) -> bool:
        return (self.success_rate == 1.0 and self.leak_rate == 0.0
                and self.unknown_rate == 0.0)


DETERMINISTIC = Physics(success_rate=1.0, leak_rate=0.0, unknown_rate=0.0)
NOISY = Physics(success_rate=0.90, leak_rate=0.02, unknown_rate=0.0)
NOISY_PARTIAL = Physics(success_rate=0.90, leak_rate=0.02, unknown_rate=0.10)


def structure_satisfied(conditions) -> bool:
    """Does the TRUE causal structure hold in this situation?"""
    if not all(c in conditions for c in CAUSAL_POSITIVE):
        return False
    return not any(c in conditions for c in CAUSAL_NEGATIVE)


class StochasticWarehouse:
    """Executes for real against seeded randomness, and reports what was seen."""

    def __init__(self, physics: Physics = NOISY_PARTIAL, seed: int = 0):
        self.physics = physics
        self.rng = random.Random(seed)
        self.seed = seed
        self.attempts = 0
        self.unknown_returned = 0

    def attempt(self, conditions) -> Tuple[Outcome, bool]:
        """Run the action. Returns (what the observer saw, what truly happened).

        The truth is returned ONLY so the experiment can measure calibration
        afterwards. The learner is given the observation, never the truth --
        passing it in would make every result a statement about an oracle.
        """
        self.attempts += 1
        conditions = frozenset(conditions)
        satisfied = structure_satisfied(conditions)
        rate = self.physics.success_rate if satisfied else self.physics.leak_rate
        truly_succeeded = self.rng.random() < rate

        if self.rng.random() < self.physics.unknown_rate:
            self.unknown_returned += 1
            return Outcome.UNKNOWN, truly_succeeded
        return (Outcome.SUCCESS if truly_succeeded else Outcome.FAILURE), truly_succeeded

    def statistics(self) -> dict:
        return {"seed": self.seed, "attempts": self.attempts,
                "unknown_returned": self.unknown_returned,
                "physics": {"success_rate": self.physics.success_rate,
                            "leak_rate": self.physics.leak_rate,
                            "unknown_rate": self.physics.unknown_rate}}


__all__ = ["Outcome", "Physics", "StochasticWarehouse", "structure_satisfied",
           "DETERMINISTIC", "NOISY", "NOISY_PARTIAL"]
