#!/usr/bin/env python3
"""A durable record of a learned rule gaining or losing execution authority.

When runtime evidence refutes a rule, something has to happen to the plans
already built on it. The obvious wiring -- the executor telling the coordinator
"replan now" -- is the wrong shape: it puts planning policy inside execution,
and it only reaches the one plan the executor happened to be running. Anything
queued elsewhere, or queued in a process that was not running at the time,
never hears about it.

So the status change is written down instead. The rule store emits the event
because the rule store is what changes the status; the planning layer reads it
and decides what that means for its plans. Neither knows about the other.

    RuleAuthorityChanged(rule_id=R1, old=VALIDATED, new=REFUTED,
                         cause=RUNTIME_CONTRADICTION, task_id=..., plan_id=...)

`consumed_at` is a single drain marker for a single consumer, which is what
exists today. A second consumer would need a per-consumer cursor -- sharing one
marker would let whichever drained first silently starve the other. That is a
stated limit, not an oversight.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, List, Optional, Sequence

from core.learning.rule_store import EpistemicStatus, confers_execution_authority

logger = logging.getLogger(__name__)


class AuthorityCause(Enum):
    """Why the status moved. Kept distinct because they are not equivalent
    evidence: validation is a judgement over held-out demonstrations, a runtime
    contradiction is the world disagreeing with a rule already trusted enough
    to act on."""

    VALIDATION = "validation"
    RUNTIME_CONTRADICTION = "runtime_contradiction"
    SUPERSEDED = "superseded"


@dataclass(frozen=True)
class RuleAuthorityChanged:
    rule_id: str
    old_status: EpistemicStatus
    new_status: EpistemicStatus
    cause: AuthorityCause
    event_id: str = ""
    observation_id: Optional[str] = None
    task_id: Optional[str] = None
    plan_id: Optional[str] = None
    goal_id: Optional[str] = None
    detail: str = ""
    occurred_at: Optional[datetime] = None

    @property
    def lost_authority(self) -> bool:
        """The rule could be executed before this change and cannot now.

        A rule that was never executable did not lose anything, and a plan
        cannot have been built on authority it never had.
        """
        return (confers_execution_authority(self.old_status)
                and not confers_execution_authority(self.new_status))

    @property
    def gained_authority(self) -> bool:
        return (not confers_execution_authority(self.old_status)
                and confers_execution_authority(self.new_status))


DDL = """
CREATE TABLE IF NOT EXISTS unified.rule_authority_events (
    event_id       VARCHAR PRIMARY KEY,
    rule_id        VARCHAR NOT NULL REFERENCES unified.learned_rules(rule_id),
    old_status     VARCHAR NOT NULL,
    new_status     VARCHAR NOT NULL,
    lost_authority BOOLEAN NOT NULL,
    cause          VARCHAR NOT NULL,
    observation_id VARCHAR,
    task_id        VARCHAR,
    plan_id        VARCHAR,
    goal_id        VARCHAR,
    detail         TEXT,
    occurred_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    consumed_at    TIMESTAMPTZ,
    consumed_by    VARCHAR
);

CREATE INDEX IF NOT EXISTS rule_authority_events_pending_idx
    ON unified.rule_authority_events (occurred_at)
    WHERE consumed_at IS NULL;
"""


async def ensure_schema(db) -> None:
    for statement in filter(None, (s.strip() for s in DDL.split(";"))):
        await db.execute_query(statement)


async def record_authority_change(db, event: RuleAuthorityChanged) -> RuleAuthorityChanged:
    """Write the change down. A no-op transition is not an event.

    Raises rather than logging: an authority change that is not durably
    recorded is one that outstanding plans will never learn about, and a
    swallowed write here reads downstream as "no rule ever lost authority".
    """
    if event.old_status is event.new_status:
        raise ValueError(
            f"{event.rule_id} did not change status ({event.old_status.value}); "
            "a transition to itself is not an authority change"
        )

    stamped = RuleAuthorityChanged(
        rule_id=event.rule_id,
        old_status=event.old_status,
        new_status=event.new_status,
        cause=event.cause,
        event_id=event.event_id or f"rac_{uuid.uuid4().hex[:12]}",
        observation_id=event.observation_id,
        task_id=event.task_id,
        plan_id=event.plan_id,
        goal_id=event.goal_id,
        detail=event.detail,
        occurred_at=event.occurred_at,
    )

    await ensure_schema(db)
    await db.execute_query(
        "INSERT INTO unified.rule_authority_events"
        " (event_id, rule_id, old_status, new_status, lost_authority, cause,"
        "  observation_id, task_id, plan_id, goal_id, detail)"
        " VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)",
        (stamped.event_id, stamped.rule_id, stamped.old_status.value,
         stamped.new_status.value, stamped.lost_authority, stamped.cause.value,
         stamped.observation_id, stamped.task_id, stamped.plan_id,
         stamped.goal_id, stamped.detail),
        commit=True,
    )
    logger.info(
        "rule authority changed: %s %s -> %s (%s)%s",
        stamped.rule_id, stamped.old_status.value, stamped.new_status.value,
        stamped.cause.value, " [LOST EXECUTION AUTHORITY]" if stamped.lost_authority else "",
    )

    # A RULE THAT CAN NO LONGER BE EXECUTED IS A CAPABILITY LOST.
    #
    # This event has always been recorded here and read by the planning layer,
    # which is exactly right for invalidating plans -- but nothing counted it
    # alongside a capability score falling or a component dropping below its
    # baseline. So the system could lose three validated rules in an hour and
    # no consumer of "how are we doing" would see anything.
    #
    # The authority reports; it does not decide what the loss means.
    if stamped.lost_authority:
        try:
            from core.observability import regression_record

            await regression_record.report(
                subject=f"rule.{stamped.rule_id}",
                dimension="execution_authority",
                detail=(f"{stamped.old_status.value} -> {stamped.new_status.value} "
                        f"({stamped.cause.value})"
                        + (f": {stamped.detail}" if stamped.detail else "")),
                source_system="rule_authority",
                # A runtime contradiction is the world disagreeing with a rule
                # already trusted enough to act on; a supersession is orderly
                # replacement. They are not the same loss.
                severity=("major" if stamped.cause is AuthorityCause.RUNTIME_CONTRADICTION
                          else "minor"),
                metadata={"rule_id": stamped.rule_id, "cause": stamped.cause.value,
                          "task_id": stamped.task_id, "plan_id": stamped.plan_id,
                          "observation_id": stamped.observation_id})
        except Exception as error:
            logger.error("Rule authority regression not recorded for %s: %s",
                         stamped.rule_id, error)
    elif stamped.gained_authority:
        # Recovery is a fact too: a rule regaining authority closes the
        # regression its loss opened, so the open count means something.
        try:
            from core.observability import regression_record

            await regression_record.resolve(f"rule.{stamped.rule_id}",
                                            "execution_authority")
        except Exception as error:
            logger.error("Rule authority recovery not recorded for %s: %s",
                         stamped.rule_id, error)

    return stamped


async def pending_authority_changes(
    db, *, lost_only: bool = True, limit: int = 200
) -> List[RuleAuthorityChanged]:
    """Undrained events, oldest first.

    `lost_only` is the planning layer's case: a rule that GAINED authority
    invalidates nothing, so replanning on it would be churn.
    """
    await ensure_schema(db)
    where = "consumed_at IS NULL" + (" AND lost_authority" if lost_only else "")
    rows = await db.execute_query(
        "SELECT event_id, rule_id, old_status, new_status, cause, observation_id,"
        " task_id, plan_id, goal_id, detail, occurred_at"
        f" FROM unified.rule_authority_events WHERE {where}"
        " ORDER BY occurred_at, event_id LIMIT $1",
        (limit,), fetch_all=True,
    ) or []

    return [
        RuleAuthorityChanged(
            rule_id=row["rule_id"],
            old_status=EpistemicStatus(row["old_status"]),
            new_status=EpistemicStatus(row["new_status"]),
            cause=AuthorityCause(row["cause"]),
            event_id=row["event_id"],
            observation_id=row["observation_id"],
            task_id=row["task_id"],
            plan_id=row["plan_id"],
            goal_id=row["goal_id"],
            detail=row["detail"] or "",
            occurred_at=row["occurred_at"],
        )
        for row in rows
    ]


async def mark_consumed(db, event_ids: Sequence[str], consumer: str) -> int:
    """Drain. Returns how many rows this call actually claimed.

    Already-consumed rows are left alone, so a second drainer cannot re-report
    work someone else has done.
    """
    ids = [e for e in event_ids if e]
    if not ids:
        return 0
    rows = await db.execute_query(
        "UPDATE unified.rule_authority_events SET consumed_at = NOW(), consumed_by = $1"
        " WHERE event_id = ANY($2::varchar[]) AND consumed_at IS NULL"
        " RETURNING event_id",
        (consumer, list(ids)), fetch_all=True,
    ) or []
    return len(rows)


async def authority_history(db, rule_id: str) -> List[RuleAuthorityChanged]:
    """Every recorded transition for one rule, oldest first."""
    await ensure_schema(db)
    rows = await db.execute_query(
        "SELECT event_id, rule_id, old_status, new_status, cause, observation_id,"
        " task_id, plan_id, goal_id, detail, occurred_at"
        " FROM unified.rule_authority_events WHERE rule_id = $1"
        " ORDER BY occurred_at, event_id",
        (rule_id,), fetch_all=True,
    ) or []
    return [
        RuleAuthorityChanged(
            rule_id=row["rule_id"],
            old_status=EpistemicStatus(row["old_status"]),
            new_status=EpistemicStatus(row["new_status"]),
            cause=AuthorityCause(row["cause"]),
            event_id=row["event_id"],
            observation_id=row["observation_id"],
            task_id=row["task_id"],
            plan_id=row["plan_id"],
            goal_id=row["goal_id"],
            detail=row["detail"] or "",
            occurred_at=row["occurred_at"],
        )
        for row in rows
    ]
