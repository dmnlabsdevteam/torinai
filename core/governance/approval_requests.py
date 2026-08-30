#!/usr/bin/env python3
"""The one owner of "a human said yes".

`_is_deployment_safe` gate 2 read `context.get("human_approved", False)` — a
boolean the CALLER puts in its own dictionary. The thing being governed supplied
its own authorization, and nothing in `core/` ever set the key, so MAJOR and
TRANSFORMATIVE self-modifications were permanently blocked by a gate whose only
documented way to open was for the requester to write `True` into a dict.

That is fabricated authorization: an approval nobody granted, checkable by
nobody, revocable by nobody, and recorded nowhere.

    AN APPROVAL IS A ROW A PERSON CREATED, NOT A FLAG A CALLER PASSED.

So a request is persisted here, a human decides it in the dashboard, and the
decision is read back from the same row. The requester cannot write its own
answer: `request()` only ever inserts `status='pending'`, and `decide()` is the
only path that writes any other status.

WHY THE DEFAULT IS REFUSAL. `decision_for()` returns None while a request is
pending, and the gate treats that as "not approved". A cycle that asks and waits
is a cycle that does not deploy — which is the correct behaviour when nobody has
answered yet, and the one thing a `context.get(..., False)` could never
distinguish from "nobody was ever asked".

IDEMPOTENT PER ACTION. `action_id` is unique, so a cycle that re-checks its own
gate finds its existing request rather than filling the notification centre with
copies of one question. An approval is spent on exactly the action it names.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

PENDING, APPROVED, DECLINED = "pending", "approved", "declined"


@dataclass(frozen=True)
class ApprovalRequest:
    """One question put to a person, and their answer if they have given one."""

    approval_id: int
    action_id: str
    action_type: str
    tier: str
    scope: Optional[str]
    requester: str
    summary: Optional[str]
    rationale: Optional[str]
    details: Dict[str, Any]
    status: str
    created_at: Optional[datetime]
    decided_at: Optional[datetime]
    decided_by: Optional[str]
    decision_note: Optional[str]
    authenticated: bool

    @property
    def is_pending(self) -> bool:
        return self.status == PENDING

    def as_dict(self) -> Dict[str, Any]:
        return {
            "approval_id": self.approval_id,
            "action_id": self.action_id,
            "action_type": self.action_type,
            "tier": self.tier,
            "scope": self.scope,
            "requester": self.requester,
            "summary": self.summary,
            "rationale": self.rationale,
            "details": self.details,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "decided_at": self.decided_at.isoformat() if self.decided_at else None,
            "decided_by": self.decided_by,
            "decision_note": self.decision_note,
            "authenticated": self.authenticated,
        }


def _row(record) -> ApprovalRequest:
    raw = record["details"]
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (TypeError, ValueError):
            raw = {}
    return ApprovalRequest(
        approval_id=int(record["approval_id"]),
        action_id=record["action_id"],
        action_type=record["action_type"],
        tier=record["tier"],
        scope=record["scope"],
        requester=record["requester"],
        summary=record["summary"],
        rationale=record["rationale"],
        details=raw or {},
        status=record["status"],
        created_at=record["created_at"],
        decided_at=record["decided_at"],
        decided_by=record["decided_by"],
        decision_note=record["decision_note"],
        authenticated=bool(record["authenticated"]),
    )


_COLUMNS = ("approval_id, action_id, action_type, tier, scope, requester, "
            "summary, rationale, details, status, created_at, decided_at, "
            "decided_by, decision_note, authenticated")


async def _db(db_manager=None):
    if db_manager is not None:
        return db_manager
    from core.database import get_database_manager

    return get_database_manager()


async def request(action_id: str, action_type: str, tier: str,
                  requester: str, summary: str,
                  rationale: str = "", scope: Optional[str] = None,
                  details: Optional[Dict[str, Any]] = None,
                  db_manager=None) -> ApprovalRequest:
    """Ask a person. Returns the existing request if this action already asked.

    Never writes a status other than pending — the requester has no way to
    answer its own question through this function.
    """
    db = await _db(db_manager)
    existing = await find(action_id, db_manager=db)
    if existing is not None:
        return existing

    await db.execute_query(
        "INSERT INTO unified.pending_approvals "
        "(action_id, action_type, tier, scope, requester, summary, rationale, "
        " details, status, created_at) "
        "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,'pending',NOW()) "
        "ON CONFLICT (action_id) DO NOTHING",
        (action_id, action_type, tier, scope, requester, summary, rationale,
         json.dumps(details or {})), commit=True)

    created = await find(action_id, db_manager=db)
    if created is None:
        raise RuntimeError(
            f"approval request {action_id!r} was neither found nor inserted; "
            f"refusing to report an unrecorded request as made")
    logger.warning("APPROVAL REQUIRED (%s): %s", tier, summary)
    return created


async def find(action_id: str, db_manager=None) -> Optional[ApprovalRequest]:
    """The request for one action, whatever its status."""
    db = await _db(db_manager)
    rows = await db.execute_query(
        f"SELECT {_COLUMNS} FROM unified.pending_approvals WHERE action_id = $1",
        (action_id,), fetch_all=True)
    return _row(rows[0]) if rows else None


async def decision_for(action_id: str, db_manager=None) -> Optional[bool]:
    """True approved, False declined, None nobody has answered.

    THREE ANSWERS. Collapsing "pending" into False would be safe but would also
    make "declined" and "not yet asked" the same fact, and the caller needs to
    tell a refusal from a question still on someone's screen.
    """
    found = await find(action_id, db_manager=db_manager)
    if found is None or found.status == PENDING:
        return None
    return found.status == APPROVED


async def pending(limit: int = 50, db_manager=None) -> List[ApprovalRequest]:
    """Everything waiting on a person, newest first."""
    db = await _db(db_manager)
    rows = await db.execute_query(
        f"SELECT {_COLUMNS} FROM unified.pending_approvals "
        f"WHERE status = 'pending' ORDER BY created_at DESC LIMIT {int(limit)}",
        None, fetch_all=True)
    return [_row(r) for r in (rows or [])]


async def recent(limit: int = 50, db_manager=None) -> List[ApprovalRequest]:
    """Decided requests, newest decision first — the record of who said what."""
    db = await _db(db_manager)
    rows = await db.execute_query(
        f"SELECT {_COLUMNS} FROM unified.pending_approvals "
        f"WHERE status <> 'pending' ORDER BY decided_at DESC LIMIT {int(limit)}",
        None, fetch_all=True)
    return [_row(r) for r in (rows or [])]


async def decide(approval_id: int, approved: bool, decided_by: str,
                 note: str = "", authenticated: bool = False,
                 db_manager=None) -> ApprovalRequest:
    """Record a person's decision. Only callable once per request.

    A decided request is not re-decidable here. Changing an answer after the
    cycle has already read it would mean the record no longer says what the
    system acted on.
    """
    if not decided_by or not str(decided_by).strip():
        raise ValueError("a decision must name who made it")

    db = await _db(db_manager)
    rows = await db.execute_query(
        "UPDATE unified.pending_approvals "
        "SET status = $1, decided_at = NOW(), decided_by = $2, "
        "    decision_note = $3, authenticated = $4 "
        "WHERE approval_id = $5 AND status = 'pending' "
        f"RETURNING {_COLUMNS}",
        (APPROVED if approved else DECLINED, str(decided_by).strip(), note,
         bool(authenticated), int(approval_id)), fetch_all=True)

    if not rows:
        current = await db.execute_query(
            f"SELECT {_COLUMNS} FROM unified.pending_approvals WHERE approval_id = $1",
            (int(approval_id),), fetch_all=True)
        if not current:
            raise LookupError(f"no approval request {approval_id}")
        settled = _row(current[0])
        raise RuntimeError(
            f"approval {approval_id} was already {settled.status} by "
            f"{settled.decided_by} at {settled.decided_at}; it cannot be decided again")

    decided = _row(rows[0])
    logger.warning("APPROVAL %s by %s: %s", decided.status.upper(),
                   decided.decided_by, decided.summary)
    return decided


__all__ = ["ApprovalRequest", "PENDING", "APPROVED", "DECLINED",
           "request", "find", "decision_for", "pending", "recent", "decide"]
