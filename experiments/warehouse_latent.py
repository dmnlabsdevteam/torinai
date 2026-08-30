#!/usr/bin/env python3
"""The EDU-10 warehouse with a cause the learner cannot observe.

Every condition that mattered so far was in the observation vocabulary. The
learner's job was to work out which of the visible conditions were causal. Here
one genuine precondition -- CALIBRATED -- is never observable at all.

The failure this is built to catch: unexplained variance being laundered into
the reliability parameter. A learner that can only say "the action works 47% of
the time" has converted a MISSING CAUSE into a KNOWN QUANTITY, and will report
a confident, well-calibrated, completely wrong model of the world.

THREE REGIMES, WITH IDENTICAL MARGINALS. This is the whole design:

    NO_LATENT     the hidden condition is always satisfied
    IID_LATENT    it flips independently every trial,  P(on) = 0.5
    PERSISTENT    it is a Markov chain, stay prob 0.9, P(on) = 0.5

IID and PERSISTENT produce EXACTLY the same success rate. They differ only in
time structure. That matters because it draws the honest epistemic line:

    an i.i.d. hidden cause is INDISTINGUISHABLE from unreliability, and any
    learner claiming to detect one is fabricating knowledge

    a PERSISTENT hidden cause leaves a signature -- outcomes cluster into runs
    instead of scattering -- and that signature is detectable without ever
    observing the cause

So the correct behaviour is different in each regime, and "detects a latent"
is a wrong answer in two of the three.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from enum import Enum
from typing import Tuple

from experiments.warehouse_complex import CAUSAL_NEGATIVE, CAUSAL_POSITIVE

HIDDEN_CONDITION = "CALIBRATED"


class LatentRegime(Enum):
    NO_LATENT = "no_latent"
    IID_LATENT = "iid_latent"
    PERSISTENT_LATENT = "persistent_latent"


@dataclass(frozen=True)
class LatentPhysics:
    regime: LatentRegime
    success_rate: float = 0.95      # P(succeeds | structure AND hidden satisfied)
    leak_rate: float = 0.02         # P(succeeds | observable structure violated)
    stay_probability: float = 0.90  # PERSISTENT only: P(hidden keeps its state)
    hidden_on_rate: float = 0.50    # marginal P(hidden satisfied), all regimes


NO_LATENT = LatentPhysics(LatentRegime.NO_LATENT)
IID_LATENT = LatentPhysics(LatentRegime.IID_LATENT)
PERSISTENT_LATENT = LatentPhysics(LatentRegime.PERSISTENT_LATENT)


def observable_structure_satisfied(conditions) -> bool:
    """The part of the truth the learner could in principle see."""
    if not all(c in conditions for c in CAUSAL_POSITIVE):
        return False
    return not any(c in conditions for c in CAUSAL_NEGATIVE)


class LatentWarehouse:
    """Executes for real. The hidden state is never returned to the learner."""

    def __init__(self, physics: LatentPhysics = PERSISTENT_LATENT, seed: int = 0):
        self.physics = physics
        self.rng = random.Random(seed)
        self.seed = seed
        self.attempts = 0
        # Started from the stationary distribution, so there is no burn-in
        # artefact to mistake for structure.
        self.hidden = (physics.regime is LatentRegime.NO_LATENT
                       or self.rng.random() < physics.hidden_on_rate)
        self.hidden_trace = []

    def _advance_hidden(self) -> None:
        regime = self.physics.regime
        if regime is LatentRegime.NO_LATENT:
            self.hidden = True
        elif regime is LatentRegime.IID_LATENT:
            self.hidden = self.rng.random() < self.physics.hidden_on_rate
        else:
            if self.rng.random() >= self.physics.stay_probability:
                self.hidden = not self.hidden

    def attempt(self, conditions) -> Tuple[bool, bool]:
        """Run the action. Returns (observed success, TRUE hidden state).

        The hidden state is returned ONLY so the experiment can measure whether
        a recovered latent corresponds to anything real. Passing it to the
        learner would make every result a statement about an oracle.
        """
        self.attempts += 1
        self._advance_hidden()
        self.hidden_trace.append(self.hidden)

        conditions = frozenset(conditions)
        if not observable_structure_satisfied(conditions):
            return self.rng.random() < self.physics.leak_rate, self.hidden
        if not self.hidden:
            return False, self.hidden
        return self.rng.random() < self.physics.success_rate, self.hidden


__all__ = ["LatentRegime", "LatentPhysics", "LatentWarehouse", "HIDDEN_CONDITION",
           "observable_structure_satisfied", "NO_LATENT", "IID_LATENT",
           "PERSISTENT_LATENT"]
