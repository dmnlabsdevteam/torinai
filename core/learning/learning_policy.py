#!/usr/bin/env python3
"""Whether this process may acquire or promote learned rules.

An ablation asks whether removing learned state removes a capability. That
question is only answerable if the evaluating process cannot put the state
back: a run that re-induces the rule from whatever demonstrations remain
reachable would report the capability present and the ablation as having no
effect, which is the exact opposite of the truth.

FROZEN forbids the three ways a rule can come into existence or become
executable -- induction, persistence of a candidate, and validation -- while
leaving reading and applying existing rules untouched. That asymmetry is the
point: the evaluator must be able to use what the substrate holds and unable to
change it.

Process-wide for the same reason as core.model_policy: agent threads run their
own event loops, so a ContextVar set on the main loop would not reach them.
"""

from __future__ import annotations

import logging
import os
import threading
from enum import Enum

logger = logging.getLogger(__name__)


class LearningPolicy(Enum):
    OPEN = "open"
    FROZEN = "frozen"


class LearningForbidden(RuntimeError):
    """Raised when a frozen process attempts to acquire or promote a rule."""

    def __init__(self, operation: str):
        self.operation = operation
        super().__init__(
            f"{operation} is forbidden while the learning substrate is frozen"
        )


_lock = threading.Lock()


def _from_env() -> LearningPolicy:
    raw = (os.getenv("TORIN_LEARNING_POLICY") or "").strip().lower()
    if not raw:
        return LearningPolicy.OPEN
    try:
        return LearningPolicy(raw)
    except ValueError:
        raise ValueError(
            f"TORIN_LEARNING_POLICY={raw!r} is not a LearningPolicy; expected one "
            f"of {[p.value for p in LearningPolicy]}"
        )


_policy = _from_env()


def get_learning_policy() -> LearningPolicy:
    with _lock:
        return _policy


def set_learning_policy(policy: LearningPolicy) -> LearningPolicy:
    global _policy
    with _lock:
        previous, _policy = _policy, policy
    if previous is not policy:
        logger.warning("learning policy: %s -> %s", previous.value, policy.value)
    return previous


def guard_learning(operation: str) -> None:
    """Raise if this process is not permitted to change learned state."""
    if get_learning_policy() is LearningPolicy.FROZEN:
        logger.error("blocked %s under a frozen learning substrate", operation)
        raise LearningForbidden(operation)
