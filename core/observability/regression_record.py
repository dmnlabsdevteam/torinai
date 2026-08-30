#!/usr/bin/env python3
"""Where every part of the system says it got worse.

Regression was detected in several places and aggregated in none, so nothing
could see that three different parts of the system degraded in the same hour:

    rule_authority          a rule going VALIDATED -> REFUTED, in its own table
    capability_benchmarks   regression_detected, inside one report object
    improvement_monitor     trend_status='degrading', in long_term_baselines
    health_monitor          error rates, as a health issue string

Each is correct and each is private. A rule losing execution authority IS a
regression; it just was not counted as one alongside a capability score falling
or a component's health dropping below its own baseline.

    AUTHORITIES REPORT REGRESSION. THEY DO NOT CHECK FOR IT.

That distinction is the whole design. A *check* is a poll -- compare to a
baseline, apply a threshold and a window, decide -- and putting one inside every
authority means five implementations of comparison that will disagree. But an
authority is the only thing that knows when its own state got worse, because it
is the thing that changes that state: nobody outside the rule store can see a
rule lose authority at the moment it happens.

So each authority reports the fact at the moment it observes it, and the
consumers -- health, self-improvement -- read one record and decide what it
means. `rule_authority` already had exactly this shape internally and states
the principle: "the rule store emits the event because the rule store is what
changes the status; the planning layer reads it and decides what that means for
its plans. Neither knows about the other."

WHY REPORTING NEVER RAISES. Same reason as the failure record: this is called
from inside the code path that just discovered something degraded. A reporter
that throws replaces the regression being reported with a failure to report it.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

SEVERITIES = ("minor", "moderate", "major", "severe")

#: Percentage lost -> severity, for regressions that have a magnitude. Stated
#: once here rather than re-derived by each emitter, which is how four
#: subsystems end up with four meanings for "severe".
_SEVERITY_BANDS = ((30.0, "severe"), (20.0, "major"), (10.0, "moderate"))


def severity_for(pct_lost: Optional[float]) -> str:
    """Severity from magnitude. Anything measurable but small is minor."""
    if pct_lost is None:
        return "moderate"
    for threshold, severity in _SEVERITY_BANDS:
        if pct_lost >= threshold:
            return severity
    return "minor"


@dataclass(frozen=True)
class RegressionEvent:
    """One thing that got worse, as every consumer sees it."""

    regression_id: str
    subject: str
    dimension: str
    severity: str
    baseline_value: Optional[float]
    current_value: Optional[float]
    pct_lost: Optional[float]
    detail: str
    source_system: str
    metadata: Dict[str, Any]
    resolved: bool
    occurred_at: Optional[datetime]

    def as_dict(self) -> Dict[str, Any]:
        return {
            "regression_id": self.regression_id, "subject": self.subject,
            "dimension": self.dimension, "severity": self.severity,
            "baseline_value": self.baseline_value,
            "current_value": self.current_value, "pct_lost": self.pct_lost,
            "detail": self.detail, "source_system": self.source_system,
            "metadata": self.metadata, "resolved": self.resolved,
            "occurred_at": self.occurred_at.isoformat() if self.occurred_at else None,
        }


def _row(record) -> RegressionEvent:
    raw = record["metadata"]
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (TypeError, ValueError):
            raw = {}
    return RegressionEvent(
        regression_id=record["regression_id"], subject=record["subject"],
        dimension=record["dimension"], severity=record["severity"],
        baseline_value=record["baseline_value"], current_value=record["current_value"],
        pct_lost=record["pct_lost"], detail=record["detail"],
        source_system=record["source_system"], metadata=raw or {},
        resolved=bool(record["resolved"]), occurred_at=record["occurred_at"])


_COLUMNS = ("regression_id, subject, dimension, severity, baseline_value, "
            "current_value, pct_lost, detail, source_system, metadata, "
            "resolved, occurred_at")


def _db(db_manager=None):
    if db_manager is not None:
        return db_manager
    from core.database import get_database_manager

    return get_database_manager()


async def report(subject: str, dimension: str, detail: str, source_system: str,
                 baseline_value: Optional[float] = None,
                 current_value: Optional[float] = None,
                 severity: Optional[str] = None,
                 metadata: Optional[Dict[str, Any]] = None,
                 db_manager=None) -> Optional[str]:
    """Record that something degraded. Returns the id, or None. Never raises."""
    try:
        pct_lost = None
        if (baseline_value is not None and current_value is not None
                and float(baseline_value) > 0):
            pct_lost = ((float(baseline_value) - float(current_value))
                        / float(baseline_value)) * 100.0

        if severity is None:
            severity = severity_for(pct_lost)
        if severity not in SEVERITIES:
            logger.warning("Unknown regression severity %r for %s; recording as "
                           "'moderate'", severity, subject)
            severity = "moderate"

        # Deterministic per subject+dimension+minute: a detector that runs on a
        # loop reports the same standing regression every pass, and counting
        # those separately would make one degradation look like a worsening
        # trend.
        stamp = datetime.now().strftime("%Y%m%d%H%M")
        digest = hashlib.sha256(
            f"{subject}|{dimension}|{stamp}".encode()).hexdigest()[:24]
        regression_id = f"regr_{digest}"

        await _db(db_manager).execute_query(
            """INSERT INTO unified.regression_events
                   (regression_id, subject, dimension, severity, baseline_value,
                    current_value, pct_lost, detail, source_system, metadata,
                    occurred_at)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10::jsonb,NOW())
               ON CONFLICT (regression_id) DO NOTHING""",
            (regression_id, str(subject)[:160], str(dimension)[:64], severity,
             None if baseline_value is None else float(baseline_value),
             None if current_value is None else float(current_value),
             None if pct_lost is None else round(pct_lost, 4),
             str(detail)[:4000], str(source_system)[:64],
             json.dumps(metadata or {}, default=str)),
            commit=True)

        logger.warning("📉 REGRESSION (%s): %s.%s — %s", severity, subject,
                       dimension, str(detail)[:160])
        return regression_id

    except Exception as error:
        # Called from the path that just found the degradation. Raising here
        # would lose the regression and report only the reporting failure.
        logger.error("Regression NOT recorded for %s.%s: %s",
                     subject, dimension, error)
        return None


async def resolve(subject: str, dimension: str, db_manager=None) -> int:
    """Mark a subject's open regressions on one dimension as resolved.

    Recovery is a fact too. Without this an open regression stays open forever
    and the count only ever grows, which makes it useless as a signal.
    """
    try:
        rows = await _db(db_manager).execute_query(
            "UPDATE unified.regression_events SET resolved = true, "
            "resolved_at = NOW() WHERE subject = $1 AND dimension = $2 "
            "AND resolved = false RETURNING regression_id",
            (subject, dimension), fetch_all=True)
        return len(rows or ())
    except Exception as error:
        logger.error("Could not resolve regressions for %s.%s: %s",
                     subject, dimension, error)
        return 0


async def open_regressions(severity: Optional[str] = None,
                           within_minutes: Optional[int] = None,
                           limit: int = 100,
                           db_manager=None) -> List[RegressionEvent]:
    """Everything currently believed to be worse than it was."""
    clauses, params = ["resolved = false"], []
    if severity:
        params.append(severity)
        clauses.append(f"severity = ${len(params)}")
    if within_minutes:
        clauses.append(f"occurred_at > NOW() - INTERVAL '{int(within_minutes)} minutes'")

    try:
        rows = await _db(db_manager).execute_query(
            f"SELECT {_COLUMNS} FROM unified.regression_events "
            f"WHERE {' AND '.join(clauses)} "
            f"ORDER BY occurred_at DESC LIMIT {int(limit)}",
            tuple(params) or None, fetch_all=True)
    except Exception as error:
        logger.error("Regression history unavailable: %s", error)
        return []
    return [_row(r) for r in (rows or [])]


async def for_subject(subject: str, limit: int = 50,
                      db_manager=None) -> List[RegressionEvent]:
    """Everything that has degraded about one subject, newest first."""
    try:
        rows = await _db(db_manager).execute_query(
            f"SELECT {_COLUMNS} FROM unified.regression_events "
            f"WHERE subject = $1 ORDER BY occurred_at DESC LIMIT {int(limit)}",
            (subject,), fetch_all=True)
    except Exception as error:
        logger.error("Regression history unavailable for %s: %s", subject, error)
        return []
    return [_row(r) for r in (rows or [])]


async def summary(within_minutes: int = 1440, db_manager=None) -> Dict[str, Any]:
    """What is worse right now, by severity and by subject.

    None on failure, never an empty summary: "nothing has regressed" and "the
    regression record could not be read" are different answers, and only one of
    them is good news.
    """
    try:
        rows = await _db(db_manager).execute_query(
            f"SELECT severity, subject, dimension, COUNT(*) AS n "
            f"FROM unified.regression_events "
            f"WHERE resolved = false "
            f"  AND occurred_at > NOW() - INTERVAL '{int(within_minutes)} minutes' "
            f"GROUP BY severity, subject, dimension", None, fetch_all=True)
    except Exception as error:
        logger.error("Regression summary unavailable: %s", error)
        return {"available": False, "error": f"{type(error).__name__}: {error}"}

    by_severity: Dict[str, int] = {}
    subjects: Dict[str, int] = {}
    for row in (rows or []):
        by_severity[row["severity"]] = by_severity.get(row["severity"], 0) + int(row["n"])
        subjects[row["subject"]] = subjects.get(row["subject"], 0) + int(row["n"])
    return {"available": True, "total": sum(by_severity.values()),
            "by_severity": by_severity, "by_subject": subjects}


__all__ = ["RegressionEvent", "SEVERITIES", "severity_for", "report", "resolve",
           "open_regressions", "for_subject", "summary"]
