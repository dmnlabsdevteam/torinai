#!/usr/bin/env python3
"""Explicit capability availability.

The invariant:

    Nothing advertised as available may resolve to None, and an unavailable
    capability must be explicitly represented as unavailable.

    A stub must never be capable of masquerading as a successful cognitive
    operation.

Two failure modes this exists to prevent, both observed in this codebase:

1. ``X = None`` under ``except ImportError``. The symbol exists, so
   ``if X is not None`` guards pass and ``from pkg import X`` succeeds; the
   defect surfaces later, far from its cause. ``CapabilityStatus`` says
   *unavailable, and here is why* instead.

2. A placeholder returning ``{"status": "completed", "findings": []}``.
   ``ResearchAgent.conduct_research`` did exactly this. Once agent dispatch is
   wired, 251 research tasks would report success, metrics would show success,
   and the learning substrate would update its posteriors from fiction --
   strictly worse than failing, because the failure becomes invisible.

Use ``CapabilityUnavailable`` for the second case: it is an error, so it cannot
be mistaken for a result, and it carries the reason so the caller can classify
the outcome as INFRASTRUCTURE_FAILURE / not-implemented rather than charging a
strategy for it (see core.learning.meta_learning.OutcomeClass).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CapabilityStatus:
    """Whether a capability is genuinely usable, and why not if it isn't."""

    name: str
    available: bool
    reason: Optional[str] = None
    detail: Dict[str, Any] = field(default_factory=dict)

    def __bool__(self) -> bool:
        return self.available

    def require(self) -> None:
        """Raise if this capability is not usable."""
        if not self.available:
            raise CapabilityUnavailable(self.name, self.reason or "unavailable", **self.detail)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "capability": self.name,
            "available": self.available,
            "reason": self.reason,
            **self.detail,
        }

    @classmethod
    def ok(cls, name: str, **detail: Any) -> "CapabilityStatus":
        return cls(name=name, available=True, reason=None, detail=detail)

    @classmethod
    def missing(cls, name: str, reason: str, **detail: Any) -> "CapabilityStatus":
        return cls(name=name, available=False, reason=reason, detail=detail)


class CapabilityUnavailable(RuntimeError):
    """Raised when a capability is invoked that is not actually implemented.

    Deliberately an exception rather than a return value: a success-shaped dict
    can be consumed as a result, recorded as a completion, and learned from. An
    exception cannot.
    """

    def __init__(self, capability: str, reason: str = "not_implemented", **detail: Any):
        self.capability = capability
        self.reason = reason
        self.detail = detail
        super().__init__(f"capability '{capability}' unavailable: {reason}")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": "capability_unavailable",
            "capability": self.capability,
            "reason": self.reason,
            **self.detail,
        }


def not_implemented(capability: str, detail: str = "") -> "CapabilityUnavailable":
    """Build the exception a placeholder should raise instead of faking success."""
    return CapabilityUnavailable(
        capability,
        reason="not_implemented",
        note=detail or "placeholder: no real implementation exists",
    )


# Exceptions that mean the CODE is wrong, not that the world answered "no".
#
# The same invariant as above, one level down. `CapabilityUnavailable` stops a
# stub from masquerading as a *success*; this stops a defect from masquerading
# as a legitimate *negative result* -- which is the harder one to notice,
# because a negative result looks exactly like a system working correctly and
# finding nothing.
#
# Observed: `transfer_learning_across_domains` called
# `cross_domain_reasoner.find_cross_domain_mapping()`, a method that class has
# never implemented. Every call raised AttributeError into a broad
# `except Exception -> return {"success": False, "error": ...}`. The system
# reported "no cross-domain mapping found" for the entire life of the code, and
# because that is a perfectly ordinary thing for it to report, nothing ever
# flagged it. The capability was dark, not absent -- the worst state to be in.
STRUCTURAL_DEFECT_TYPES = (AttributeError, NameError, ImportError, TypeError)


def raise_if_structural(exc: BaseException, where: str) -> None:
    """Re-raise `exc` if it indicates a wiring defect rather than a real failure.

    Call as the first line of a broad handler::

        except Exception as e:
            raise_if_structural(e, "module.function")
            logger.error(...)
            return {"success": False, "error": str(e)}

    A missing attribute, an undefined name, a failed import or a signature
    mismatch are never conditions the caller should absorb and report as an
    ordinary negative -- they mean this path has not run correctly, possibly
    ever. Operational failures (a database down, a timeout, a refused
    connection) fall through and are still handled as before.
    """
    if isinstance(exc, STRUCTURAL_DEFECT_TYPES):
        logger.critical(
            f"STRUCTURAL DEFECT in {where}: {type(exc).__name__}: {exc} "
            f"-- this is broken wiring, not a negative result; re-raising so it "
            f"cannot be recorded as an ordinary failure",
            exc_info=True,
        )
        raise exc


__all__ = [
    "CapabilityStatus",
    "CapabilityUnavailable",
    "not_implemented",
    "STRUCTURAL_DEFECT_TYPES",
    "raise_if_structural",
]
