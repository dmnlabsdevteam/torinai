#!/usr/bin/env python3
"""What the approval gate has actually decided, learned from the real record.

THE SESSION MODEL IS GONE AND THIS WAS BUILT FOR IT. The previous version
recorded a `voter_type` per decision and aggregated "governance sessions" from
a multi-judge panel that no longer exists -- `make_decision`, the AI judge
votes and the approval queue were all retired. It kept its history in a Python
list capped at `max_history`, declared itself "a lightweight in-memory learner
used by the governance test-suite", and was therefore incapable of learning
anything that outlived a process.

    GOVERNANCE IS NOW ONE GATE: A PERSON ANSWERS A REQUEST.

`unified.pending_approvals` holds those decisions -- who asked, what for, at
what tier, who answered, when, and whether they re-authenticated. That is a
real record of real judgements, and it is what there is to learn from.

WHAT THIS LEARNS, AND WHAT IT MUST NEVER DO. It learns the shape of past
decisions: how often a kind of request is approved, how long it waits, whether
the approver re-authenticated. It offers that as GUIDANCE to anything that
wants to know what tends to happen.

It does not approve. It has no path to approve, by construction: nothing here
writes to `pending_approvals`, and `core.governance.approval_requests.decide`
is the only thing that can settle a request. A learner that could act on its
own pattern would be a system approving its own changes because it had
approved similar ones before -- which is precisely what the approval gate
exists to prevent.
"""

from __future__ import annotations

import hashlib
import logging
import statistics
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

#: Below this many decided requests, a rate is noise rather than a pattern.
MIN_DECISIONS_FOR_PATTERN = 3

#: Sample size at which a pattern is treated as fully established. Kept small
#: and explicit: approval decisions are made by a person and arrive slowly, so
#: the old 1-in-50 scale would have reported near-zero confidence forever.
CONFIDENCE_SATURATION = 20


@dataclass
class ApprovalPattern:
    """How one kind of request has actually been answered."""

    action_type: str
    tier: str
    decided: int
    approved: int
    declined: int
    approval_rate: float
    median_decision_sec: Optional[float]
    authenticated_rate: Optional[float]
    confidence: float
    learned_at: datetime = field(default_factory=datetime.now)

    @property
    def pattern_id(self) -> str:
        digest = hashlib.sha256(
            f"{self.action_type}|{self.tier}".encode()).hexdigest()[:20]
        return f"govpat_{digest}"

    def as_dict(self) -> Dict[str, Any]:
        return {
            "pattern_id": self.pattern_id, "action_type": self.action_type,
            "tier": self.tier, "decided": self.decided, "approved": self.approved,
            "declined": self.declined, "approval_rate": self.approval_rate,
            "median_decision_sec": self.median_decision_sec,
            "authenticated_rate": self.authenticated_rate,
            "confidence": self.confidence,
            "learned_at": self.learned_at.isoformat(),
        }


class GovernancePatternLearner:
    """Learns from the approval gate. Never operates it."""

    def __init__(self, db_manager=None):
        self._db = db_manager

    def db(self):
        if self._db is not None:
            return self._db
        from core.database import get_database_manager

        return get_database_manager()

    # ---- learning -------------------------------------------------------

    async def learn(self, min_decisions: int = MIN_DECISIONS_FOR_PATTERN,
                    persist: bool = True) -> List[ApprovalPattern]:
        """Aggregate every decided approval request into patterns.

        Reads the gate's own table rather than being told about decisions.
        Nothing has to remember to report here, so a decision made in another
        process, or before this object existed, is still learned from.
        """
        try:
            rows = await self.db().execute_query(
                """SELECT action_type, tier, status, authenticated,
                          EXTRACT(EPOCH FROM (decided_at - created_at)) AS wait_seconds
                     FROM unified.pending_approvals
                    WHERE status <> 'pending'""", fetch_all=True) or []
        except Exception as error:
            logger.error("Approval history unavailable: %s", error)
            return []

        buckets: Dict[tuple, List[Dict[str, Any]]] = {}
        for row in rows:
            key = (str(row["action_type"] or "unknown"), str(row["tier"] or "unknown"))
            buckets.setdefault(key, []).append(dict(row))

        patterns: List[ApprovalPattern] = []
        for (action_type, tier), decisions in buckets.items():
            decided = len(decisions)
            if decided < max(1, int(min_decisions)):
                continue

            approved = sum(1 for d in decisions if d["status"] == "approved")
            waits = [float(d["wait_seconds"]) for d in decisions
                     if d.get("wait_seconds") is not None]
            authed = [bool(d["authenticated"]) for d in decisions]

            patterns.append(ApprovalPattern(
                action_type=action_type, tier=tier, decided=decided,
                approved=approved, declined=decided - approved,
                approval_rate=approved / decided,
                # None, not 0.0: a decision with no recorded timing tells you
                # nothing about how long these take.
                median_decision_sec=(statistics.median(waits) if waits else None),
                authenticated_rate=(sum(authed) / len(authed) if authed else None),
                confidence=min(1.0, decided / CONFIDENCE_SATURATION),
            ))

        patterns.sort(key=lambda p: (p.confidence, p.decided), reverse=True)
        if persist and patterns:
            await self._persist(patterns)
        return patterns

    async def _persist(self, patterns: List[ApprovalPattern]) -> int:
        """Write the patterns down, so they outlive the process that learned them."""
        written = 0
        for pattern in patterns:
            try:
                await self.db().execute_query(
                    """INSERT INTO unified.governance_patterns
                           (pattern_id, action_type, tier, decided, approved,
                            declined, approval_rate, median_decision_sec,
                            authenticated_rate, confidence, learned_at)
                       VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,NOW())
                       ON CONFLICT (pattern_id) DO UPDATE SET
                           decided = EXCLUDED.decided,
                           approved = EXCLUDED.approved,
                           declined = EXCLUDED.declined,
                           approval_rate = EXCLUDED.approval_rate,
                           median_decision_sec = EXCLUDED.median_decision_sec,
                           authenticated_rate = EXCLUDED.authenticated_rate,
                           confidence = EXCLUDED.confidence,
                           learned_at = NOW()""",
                    (pattern.pattern_id, pattern.action_type, pattern.tier,
                     pattern.decided, pattern.approved, pattern.declined,
                     pattern.approval_rate, pattern.median_decision_sec,
                     pattern.authenticated_rate, pattern.confidence),
                    commit=True)
                written += 1
            except Exception as error:
                logger.error("Governance pattern not persisted (%s/%s): %s",
                             pattern.action_type, pattern.tier, error)
        return written

    # ---- guidance, never authority --------------------------------------

    async def guidance_for(self, action_type: str, tier: str) -> Dict[str, Any]:
        """What has happened to requests like this before.

        INFORMATION, NOT A VERDICT. The return value deliberately carries no
        field a caller could mistake for a decision -- no `approved`, no
        `allow`. A requester may use it to phrase a better request or to warn
        that this kind is usually declined; it may not use it to proceed.
        """
        try:
            rows = await self.db().execute_query(
                """SELECT decided, approved, declined, approval_rate,
                          median_decision_sec, authenticated_rate, confidence,
                          learned_at
                     FROM unified.governance_patterns
                    WHERE action_type = $1 AND tier = $2""",
                (action_type, tier), fetch_all=True)
        except Exception as error:
            logger.error("Governance guidance unavailable: %s", error)
            return {"known": False, "reason": f"{type(error).__name__}: {error}"}

        if not rows:
            # No history is not a prediction of approval OR refusal.
            return {"known": False,
                    "reason": f"no decided request of type {action_type!r} at "
                              f"tier {tier!r} has been recorded"}

        row = dict(rows[0])
        return {
            "known": True,
            "decided": int(row["decided"]),
            "approved": int(row["approved"]),
            "declined": int(row["declined"]),
            "approval_rate": float(row["approval_rate"]),
            "median_decision_sec": row["median_decision_sec"],
            "authenticated_rate": row["authenticated_rate"],
            "confidence": float(row["confidence"]),
            "learned_at": row["learned_at"],
            "note": ("history only; the approval gate decides each request on "
                     "its own merits and this cannot approve anything"),
        }

    async def stale_requests(self, older_than_minutes: int = 1440) -> List[Dict[str, Any]]:
        """Requests nobody has answered.

        A gate whose questions go unanswered is a gate that silently blocks
        everything behind it, and that is invisible from the approval side --
        the request just sits there. Surfaced so the wait is a fact somebody
        can see.
        """
        try:
            rows = await self.db().execute_query(
                f"""SELECT approval_id, action_type, tier, requester, summary,
                           created_at,
                           EXTRACT(EPOCH FROM (NOW() - created_at)) AS waiting_seconds
                      FROM unified.pending_approvals
                     WHERE status = 'pending'
                       AND created_at < NOW() - INTERVAL '{int(older_than_minutes)} minutes'
                     ORDER BY created_at""", fetch_all=True) or []
        except Exception as error:
            logger.error("Pending approval ages unavailable: %s", error)
            return []
        return [dict(r) for r in rows]

    async def get_statistics(self) -> Dict[str, Any]:
        """What the gate has done, from the record rather than from memory."""
        try:
            rows = await self.db().execute_query(
                """SELECT COUNT(*)                                  AS total,
                          COUNT(*) FILTER (WHERE status = 'pending')  AS pending,
                          COUNT(*) FILTER (WHERE status = 'approved') AS approved,
                          COUNT(*) FILTER (WHERE status = 'declined') AS declined,
                          COUNT(*) FILTER (WHERE authenticated)       AS authenticated
                     FROM unified.pending_approvals""", fetch_all=True)
            learned = await self.db().execute_query(
                "SELECT COUNT(*) AS n FROM unified.governance_patterns",
                fetch_all=True)
        except Exception as error:
            logger.error("Governance statistics unavailable: %s", error)
            return {"available": False, "error": f"{type(error).__name__}: {error}"}

        row = dict(rows[0]) if rows else {}
        decided = int(row.get("approved") or 0) + int(row.get("declined") or 0)
        return {
            "available": True,
            "total_requests": int(row.get("total") or 0),
            "pending": int(row.get("pending") or 0),
            "approved": int(row.get("approved") or 0),
            "declined": int(row.get("declined") or 0),
            "authenticated_approvals": int(row.get("authenticated") or 0),
            # None over zero decisions: an approval rate with nothing decided
            # is undefined, and 0.0 reads as "everything gets declined".
            "approval_rate": (int(row.get("approved") or 0) / decided) if decided else None,
            "patterns_learned": int(learned[0]["n"]) if learned else 0,
        }


_learner: Optional[GovernancePatternLearner] = None


def get_governance_pattern_learner(db_manager=None) -> GovernancePatternLearner:
    global _learner
    if _learner is None:
        _learner = GovernancePatternLearner(db_manager=db_manager)
    return _learner


__all__ = ["ApprovalPattern", "GovernancePatternLearner",
           "get_governance_pattern_learner", "MIN_DECISIONS_FOR_PATTERN"]
