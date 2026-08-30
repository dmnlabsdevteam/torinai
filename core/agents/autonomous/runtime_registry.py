"""Runtime registry for the active AutonomousCoordinator.

This module avoids tight coupling / circular imports by providing a minimal,
optional way for components (e.g., tools) to update runtime counters that are
owned by the coordinator.

It is intentionally best-effort: if no coordinator is registered, calls are no-ops.
"""

from __future__ import annotations

import logging
import weakref
from typing import Any, Optional

logger = logging.getLogger(__name__)

_autonomous_coordinator_ref: Optional[weakref.ReferenceType[Any]] = None


def register_autonomous_coordinator(coordinator: Any) -> None:
    """Register the currently running AutonomousCoordinator instance."""
    global _autonomous_coordinator_ref
    try:
        _autonomous_coordinator_ref = weakref.ref(coordinator)
    except Exception:
        # Weakref can fail for some objects; fall back to strong ref.
        _autonomous_coordinator_ref = lambda: coordinator  # type: ignore[assignment]
    logger.debug("Registered AutonomousCoordinator in runtime registry")


def get_autonomous_coordinator() -> Optional[Any]:
    """Return the registered AutonomousCoordinator instance, if any."""
    if _autonomous_coordinator_ref is None:
        return None
    try:
        return _autonomous_coordinator_ref()
    except Exception:
        return None


def increment_cycles_completed(
    delta: int = 1,
    *,
    source: str = "unknown",
    cycle_id: Optional[str] = None,
) -> None:
    """Best-effort increment of coordinator.stats['cycles_completed']."""
    coordinator = get_autonomous_coordinator()
    if coordinator is None:
        return

    stats = getattr(coordinator, "stats", None)
    if not isinstance(stats, dict):
        return

    stats["cycles_completed"] = int(stats.get("cycles_completed", 0)) + int(delta)

    if cycle_id:
        stats["last_cycle_id"] = cycle_id
    stats["last_cycle_source"] = source

    logger.info(
        "✅ cycles_completed incremented to %s (source=%s, cycle_id=%s)",
        stats.get("cycles_completed", 0),
        source,
        cycle_id,
    )
