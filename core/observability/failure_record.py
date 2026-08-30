#!/usr/bin/env python3
"""The one place a failure is written, and the one place any subsystem reads it.

Every folder in `core/` produces errors -- roughly 1,500 exception handlers
across 30 packages -- and each one used to decide for itself where the error
went. The result was six consumers each reading a different store, and none of
them seeing the same system:

    autonomous_coordinator  -> system_failures      (recurring-failure check)
    health_monitor          -> tool_error_events    (asymmetric recording)
    improvement_monitor     -> component_health     (per-component score)
    intrinsic_motivation    -> last_failure         (goal generation)
    EnhancedASI             -> component_health     (improvement targets)
    RecoveryManager         -> system_failures      (recovery strategy)

Producers wrote to log files, `tool_error_events`, `security_events`,
`component_health.last_error`, an in-memory Python list capped at
`max_findings`, or nowhere. No producer wrote to more than one; no consumer
read more than one.

WHAT THAT COST, CONCRETELY. `autonomous_coordinator` decides
`is_recurring = failure_count >= 3` from `get_failure_history(component)`,
which read `unified.system_failures` -- a table holding ONE row, ever. A
component could fail every hour for a week and never be called recurring,
because its failures landed somewhere else. The logic was right and the store
was empty.

    A FAILURE IS REPORTED ONCE, HERE, AND EVERY SYSTEM READS IT FROM HERE.

The per-subsystem tables keep their detail -- `tool_error_events` still holds
tool specifics, `security_events` still holds security specifics. This holds
the fact that something failed, so the systems whose job depends on knowing
that can find out.

WHY REPORTING NEVER RAISES. This is called from inside exception handlers. A
reporter that can throw turns one failure into two and loses the first. Every
entry point here swallows its own errors and says so in the log, which is the
one place in this codebase where swallowing is the correct behaviour -- and it
returns None so a caller that cares can tell.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

SEVERITIES = ("low", "medium", "high", "critical")

#: Recurrence is a property of a WINDOW. "failed three times" means nothing
#: without saying over what period, and the coordinator's check had no window
#: at all -- it counted the last 10 rows whenever they happened.
DEFAULT_RECURRENCE_WINDOW_MIN = 60
DEFAULT_RECURRENCE_THRESHOLD = 3


@dataclass(frozen=True)
class FailureRecord:
    """One failure, as every consumer sees it."""

    failure_id: str
    component: str
    failure_type: str
    severity: str
    description: str
    source_system: str
    exception_type: Optional[str]
    metadata: Dict[str, Any]
    recovered: bool
    occurred_at: Optional[datetime]

    def as_dict(self) -> Dict[str, Any]:
        return {
            "failure_id": self.failure_id, "component": self.component,
            "failure_type": self.failure_type, "severity": self.severity,
            "description": self.description, "source_system": self.source_system,
            "exception_type": self.exception_type, "metadata": self.metadata,
            "recovered": self.recovered,
            "occurred_at": self.occurred_at.isoformat() if self.occurred_at else None,
        }


def _row(record) -> FailureRecord:
    raw = record["metadata"]
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (TypeError, ValueError):
            raw = {}
    return FailureRecord(
        failure_id=record["failure_id"], component=record["component"],
        failure_type=record["failure_type"], severity=record["severity"],
        description=record["description"], source_system=record["source_system"],
        exception_type=record["exception_type"], metadata=raw or {},
        recovered=bool(record["recovered"]), occurred_at=record["occurred_at"])


_COLUMNS = ("failure_id, component, failure_type, severity, description, "
            "source_system, exception_type, metadata, recovered, occurred_at")


def _db(db_manager=None):
    if db_manager is not None:
        return db_manager
    from core.database import get_database_manager

    return get_database_manager()


async def report(component: str, failure_type: str, description: str,
                 source_system: str, severity: str = "medium",
                 exception: Optional[BaseException] = None,
                 exception_type: Optional[str] = None,
                 metadata: Optional[Dict[str, Any]] = None,
                 recovered: bool = False,
                 db_manager=None) -> Optional[str]:
    """Record that something failed. Returns the failure id, or None.

    Safe to call from inside an `except` block: it never raises.
    """
    try:
        if severity not in SEVERITIES:
            logger.warning("Unknown severity %r for %s; recording as 'medium'",
                           severity, component)
            severity = "medium"

        # Deterministic id over the failure's identity plus the second it
        # happened. Two subsystems reporting the same failure in the same
        # second collapse to one row instead of double-counting it toward
        # recurrence -- which would make a single fault look like a pattern.
        stamp = datetime.now().strftime("%Y%m%d%H%M%S")
        digest = hashlib.sha256(
            f"{component}|{failure_type}|{description}|{stamp}".encode()
        ).hexdigest()[:24]
        failure_id = f"fail_{digest}"

        await _db(db_manager).execute_query(
            """INSERT INTO unified.failure_events
                   (failure_id, component, failure_type, severity, description,
                    source_system, exception_type, metadata, recovered, occurred_at)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8::jsonb,$9,NOW())
               ON CONFLICT (failure_id) DO NOTHING""",
            (failure_id, str(component)[:160], str(failure_type)[:64], severity,
             str(description)[:4000], str(source_system)[:64],
             # A caller may hold the live exception or only its name -- a log
             # record carries `exc_info`, not an object that outlives the
             # handler. Either resolves the same field.
             (type(exception).__name__ if exception is not None else exception_type),
             json.dumps(metadata or {}, default=str), bool(recovered)),
            commit=True)
        return failure_id

    except Exception as error:
        # THE ONE CORRECT SWALLOW IN THIS CODEBASE. This runs inside other
        # people's exception handlers; raising here would replace the failure
        # being reported with a failure to report it.
        logger.error("Failure NOT recorded for %s (%s): %s",
                     component, failure_type, error)
        return None


async def mark_recovered(failure_id: str, db_manager=None) -> bool:
    """Note that a recorded failure was subsequently recovered."""
    try:
        await _db(db_manager).execute_query(
            "UPDATE unified.failure_events SET recovered = true, "
            "recovered_at = NOW() WHERE failure_id = $1",
            (failure_id,), commit=True)
        return True
    except Exception as error:
        logger.error("Could not mark %s recovered: %s", failure_id, error)
        return False


async def recent(component: Optional[str] = None,
                 within_minutes: Optional[int] = None,
                 severity: Optional[str] = None,
                 limit: int = 100, db_manager=None) -> List[FailureRecord]:
    """Failures matching the filters, newest first."""
    clauses, params = [], []
    if component:
        params.append(component)
        clauses.append(f"component = ${len(params)}")
    if severity:
        params.append(severity)
        clauses.append(f"severity = ${len(params)}")
    if within_minutes:
        clauses.append(f"occurred_at > NOW() - INTERVAL '{int(within_minutes)} minutes'")
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""

    try:
        rows = await _db(db_manager).execute_query(
            f"SELECT {_COLUMNS} FROM unified.failure_events {where} "
            f"ORDER BY occurred_at DESC LIMIT {int(limit)}",
            tuple(params) or None, fetch_all=True)
    except Exception as error:
        logger.error("Failure history unavailable: %s", error)
        return []
    return [_row(r) for r in (rows or [])]


async def count_for(component: str, within_minutes: int = DEFAULT_RECURRENCE_WINDOW_MIN,
                    db_manager=None) -> Optional[int]:
    """How many times this component failed in the window. None if unknown."""
    try:
        rows = await _db(db_manager).execute_query(
            f"SELECT COUNT(*) AS n FROM unified.failure_events "
            f"WHERE component = $1 "
            f"  AND occurred_at > NOW() - INTERVAL '{int(within_minutes)} minutes'",
            (component,), fetch_all=True)
    except Exception as error:
        logger.error("Failure count unavailable for %s: %s", component, error)
        return None
    return int(rows[0]["n"]) if rows else 0


async def is_recurring(component: str,
                       threshold: int = DEFAULT_RECURRENCE_THRESHOLD,
                       within_minutes: int = DEFAULT_RECURRENCE_WINDOW_MIN,
                       db_manager=None) -> Optional[bool]:
    """Whether this is a pattern rather than an incident. None if unknown.

    THREE ANSWERS. "I cannot tell" is not "no": the caller escalates on True,
    and treating an unreadable store as a quiet system is how a component that
    fails constantly goes unescalated.
    """
    count = await count_for(component, within_minutes, db_manager=db_manager)
    return None if count is None else count >= threshold


async def failure_rate(within_minutes: int = 5,
                       db_manager=None) -> Optional[float]:
    """Failures per minute over the window, or None if it cannot be read.

    Used by the deployment canary. None means UNMEASURED, which a caller must
    not read as healthy -- the value it replaced was a hardcoded 0.01 that sat
    permanently under every threshold it was compared against.
    """
    try:
        rows = await _db(db_manager).execute_query(
            f"SELECT COUNT(*) AS n FROM unified.failure_events "
            f"WHERE occurred_at > NOW() - INTERVAL '{int(within_minutes)} minutes'",
            None, fetch_all=True)
    except Exception as error:
        logger.error("Failure rate unavailable: %s", error)
        return None
    if not rows:
        return None
    return int(rows[0]["n"]) / max(1, int(within_minutes))


async def by_component(within_minutes: int = 60,
                       db_manager=None) -> Dict[str, int]:
    """Failure counts per component in the window — what is worst right now."""
    try:
        rows = await _db(db_manager).execute_query(
            f"SELECT component, COUNT(*) AS n FROM unified.failure_events "
            f"WHERE occurred_at > NOW() - INTERVAL '{int(within_minutes)} minutes' "
            f"GROUP BY component ORDER BY n DESC", None, fetch_all=True)
    except Exception as error:
        logger.error("Failure breakdown unavailable: %s", error)
        return {}
    return {r["component"]: int(r["n"]) for r in (rows or [])}


__all__ = ["FailureRecord", "SEVERITIES", "report", "mark_recovered", "recent",
           "count_for", "is_recurring", "failure_rate", "by_component",
           "DEFAULT_RECURRENCE_THRESHOLD", "DEFAULT_RECURRENCE_WINDOW_MIN"]
