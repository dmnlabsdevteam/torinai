#!/usr/bin/env python3
"""Whether a learned model may be invoked, and a census of every attempt.

The invariant:

    Every boundary that would invoke a pretrained learned model declares itself
    here first. Under STRICT_MODEL_FREE no such call executes, and the attempt
    is counted rather than silently absorbed.

Two counts, not one. A run that blocked forty attempts proves the guard works;
it does not prove the subsystem is model-free. The claim worth making is

    attempts == 0 and executed == 0

so ``attempts`` is recorded before the policy is consulted and survives the
block. A subsystem that keeps reaching for a model is still model-dependent,
and this is the only place that difference is observable.

Scope is every pretrained learned model, not only the LLM: a sentence encoder
ranking tools and an LSTM classifying a prompt are model inference just as much
as a chat completion is. Deterministic machinery -- BM25, Z3, the formula
parser -- is untouched and remains available in the strict lane, which is what
makes that lane usable rather than merely empty.

Policy is process-wide rather than a ContextVar: agent threads run their own
event loops, and a ContextVar set on the main loop would not reach them, so the
guard would pass by accident exactly where inference actually happens.
"""

from __future__ import annotations

import logging
import os
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Iterator, Optional

logger = logging.getLogger(__name__)


class ModelPolicy(Enum):
    """Whether learned-model inference is permitted in this process."""

    NORMAL = "normal"
    STRICT_MODEL_FREE = "strict_model_free"


class ModelClass(Enum):
    """Kinds of pretrained learned model, counted independently.

    Separated because an experiment may legitimately permit one and forbid
    another, and because "we called no LLM" is a much weaker claim than "we
    called no model" when retrieval still runs a sentence encoder.
    """

    LLM = "llm"
    VLM = "vlm"
    EMBEDDING = "embedding"
    RERANKER = "reranker"
    CLASSIFIER = "classifier"
    ENCODER = "encoder"


class ModelUseForbidden(RuntimeError):
    """Raised when a model boundary is reached under STRICT_MODEL_FREE.

    An error rather than a degraded return value: a caller that receives
    ``None`` or an empty result cannot distinguish "the model said nothing"
    from "the model was never consulted", and the substrate would learn from
    the difference without knowing it existed.
    """

    def __init__(self, model_class: ModelClass, site: str):
        self.model_class = model_class
        self.site = site
        super().__init__(
            f"{model_class.value} inference at {site} is forbidden under "
            f"{ModelPolicy.STRICT_MODEL_FREE.value}"
        )


@dataclass
class _Census:
    """Per-class tallies. Sites are kept so a nonzero count is actionable."""

    attempts: int = 0
    blocked: int = 0
    executed: int = 0
    sites: Dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "attempts": self.attempts,
            "blocked": self.blocked,
            "executed": self.executed,
            "sites": dict(self.sites),
        }


_lock = threading.Lock()
_policy = ModelPolicy.NORMAL
_census: Dict[ModelClass, _Census] = {c: _Census() for c in ModelClass}


def _policy_from_env() -> ModelPolicy:
    raw = (os.getenv("TORIN_MODEL_POLICY") or "").strip().lower()
    if not raw:
        return ModelPolicy.NORMAL
    try:
        return ModelPolicy(raw)
    except ValueError:
        raise ValueError(
            f"TORIN_MODEL_POLICY={raw!r} is not a ModelPolicy; expected one of "
            f"{[p.value for p in ModelPolicy]}"
        )


_policy = _policy_from_env()


def get_model_policy() -> ModelPolicy:
    with _lock:
        return _policy


def set_model_policy(policy: ModelPolicy) -> ModelPolicy:
    """Set the process-wide policy. Returns the previous value."""
    global _policy
    with _lock:
        previous, _policy = _policy, policy
    if previous is not policy:
        logger.warning("model policy: %s -> %s", previous.value, policy.value)
    return previous


def guard_model_use(model_class: ModelClass, site: str) -> None:
    """Declare an impending model invocation. Raises under STRICT_MODEL_FREE.

    Called before the model is touched, so the attempt is recorded whether or
    not it is permitted to proceed.
    """
    with _lock:
        entry = _census[model_class]
        entry.attempts += 1
        entry.sites[site] = entry.sites.get(site, 0) + 1
        forbidden = _policy is ModelPolicy.STRICT_MODEL_FREE
        if forbidden:
            entry.blocked += 1

    if forbidden:
        logger.error("blocked %s inference at %s", model_class.value, site)
        raise ModelUseForbidden(model_class, site)


def model_use_permitted(model_class: ModelClass, site: str) -> bool:
    """Same census as ``guard_model_use``, reported instead of raised.

    For the boundaries that have a deterministic alternative -- BM25 ranking,
    an unloaded encoder every caller already handles -- where degrading is the
    honest response and an exception would only be caught and discarded. The
    attempt is still counted, so ``assert_model_free`` still reports that this
    subsystem reached for a model.
    """
    try:
        guard_model_use(model_class, site)
        return True
    except ModelUseForbidden:
        return False


def record_model_executed(model_class: ModelClass, site: str) -> None:
    """Record that inference actually ran and produced a result."""
    with _lock:
        _census[model_class].executed += 1


@contextmanager
def model_use(model_class: ModelClass, site: str) -> Iterator[None]:
    """Guard a model invocation and count it as executed only if it completes.

    Usable from async code: neither enter nor exit awaits.
    """
    guard_model_use(model_class, site)
    yield
    record_model_executed(model_class, site)


def model_telemetry() -> Dict[str, Any]:
    """Census of model use since the last reset."""
    with _lock:
        per_class = {c.value: e.to_dict() for c, e in _census.items()}
        policy = _policy
    return {
        "policy": policy.value,
        "attempts": sum(e["attempts"] for e in per_class.values()),
        "blocked": sum(e["blocked"] for e in per_class.values()),
        "executed": sum(e["executed"] for e in per_class.values()),
        "by_class": per_class,
    }


def reset_model_telemetry() -> Dict[str, Any]:
    """Zero the census. Returns what it held, so a baseline is not lost."""
    previous = model_telemetry()
    with _lock:
        for model_class in _census:
            _census[model_class] = _Census()
    return previous


def assert_model_free(context: str = "run") -> None:
    """Raise unless nothing so much as reached for a model.

    The acceptance check for a STRICT_MODEL_FREE experiment. Fails on a nonzero
    ``attempts`` even when ``executed`` is zero, because a blocked attempt still
    identifies a subsystem that cannot yet operate without a model.
    """
    telemetry = model_telemetry()
    if telemetry["attempts"] == 0 and telemetry["executed"] == 0:
        return

    reaching = {
        name: entry["sites"]
        for name, entry in telemetry["by_class"].items()
        if entry["attempts"]
    }
    raise AssertionError(
        f"{context} was not model-free: "
        f"attempts={telemetry['attempts']} executed={telemetry['executed']} "
        f"blocked={telemetry['blocked']} reaching={reaching}"
    )
