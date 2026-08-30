#!/usr/bin/env python3
"""The ground demonstrations an operator is induced from, kept so induction can
be re-run as experience accumulates.

Induction needs at least two positive demonstrations, and the preconditions it
recovers are only as sharp as the negatives it has seen. A single executed
action is one demonstration; it cannot, by itself, teach an operator. So the
substrate must remember every before/action/after it observes and re-induce
over the growing set -- which is what "the substrate learns from its own
experience" concretely requires.

This is deliberately NOT the concept-ingestion demonstration path. That path
(`submit_demonstration`) records a transition's STRUCTURE -- predicate and arity
-- into the concept graph for the cross-domain matcher, and drops the ground
arguments. Induction cannot run on structure alone: `MOVE(z,HALL,LAB)` and
`MOVE(z,LAB,VAULT)` are the two positives that align to the general rule, and
their arguments are exactly what alignment reads. So the ground examples are
kept here, in full, keyed by the operator signature they teach.

One authority, one thing: this stores ground demonstrations and hands them back
as TrainingExamples. It does not induce, judge, or apply -- those belong to the
RuleInducer, the RuleStore, and the executor respectively.
"""

from __future__ import annotations

import json
import logging
from typing import List, Optional, Sequence

from core.learning.rule_induction import Fact, TrainingExample

logger = logging.getLogger(__name__)


DDL = """
CREATE TABLE IF NOT EXISTS unified.operator_demonstrations (
    evidence_id   VARCHAR PRIMARY KEY,
    domain_id     VARCHAR NOT NULL,
    predicate     VARCHAR NOT NULL,
    arity         INTEGER NOT NULL,
    before_facts  JSONB   NOT NULL,
    action        VARCHAR,
    after_facts   JSONB   NOT NULL,
    positive      BOOLEAN NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS operator_demonstrations_signature
    ON unified.operator_demonstrations (domain_id, predicate, arity, created_at);

-- The signatures with demonstrations recorded but not yet re-induced. This is
-- the queue that lets recording (cheap, on the acting path) and induction
-- (expensive, off it) run apart: a new demonstration enqueues its signature
-- here, and the always-online learner drains it in the background. A SET, not a
-- log -- one row per signature, re-marked idempotently -- so a burst of
-- demonstrations for one operator is one unit of pending work, not many.
CREATE TABLE IF NOT EXISTS unified.operator_induction_pending (
    domain_id   VARCHAR NOT NULL,
    predicate   VARCHAR NOT NULL,
    arity       INTEGER NOT NULL,
    enqueued_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (domain_id, predicate, arity)
);
"""


def _facts_json(facts: Sequence[Fact]) -> str:
    return json.dumps([str(f) for f in facts])


def _parse_facts(payload) -> tuple:
    if isinstance(payload, str):
        payload = json.loads(payload)
    return tuple(Fact.parse(text) for text in payload)


class DemonstrationStore:
    """Persists ground demonstrations and reloads them by operator signature."""

    def __init__(self, db_manager=None):
        self._db = db_manager

    def db(self):
        if self._db is None:
            from core.database import get_database_manager
            self._db = get_database_manager()
        return self._db

    async def _ready(self):
        db = self.db()
        if not getattr(db, "initialized", False):
            await db.initialize()

    async def ensure_schema(self):
        await self._ready()
        for statement in filter(None, (s.strip() for s in DDL.split(";"))):
            await self.db().execute_query(statement)

    #: The signature a demonstration with no action is filed under. An
    #: actionless demonstration is not about one operator -- it is contrastive
    #: evidence about the whole domain: a state held, nothing was done, and the
    #: effects did not occur on their own. It teaches every operator that its
    #: action is NECESSARY, which is why it belongs to the domain, not a
    #: predicate.
    CONTRASTIVE = ("", 0)

    async def append(self, example: TrainingExample, *, domain_id: str) -> bool:
        """Record one demonstration.

        An action-ful demonstration is filed under the operator signature it
        teaches. An ACTIONLESS one is filed as domain-level contrastive evidence
        -- a state in which no action was taken and the effects did not follow,
        which is what proves an action is necessary rather than incidental.
        Induction from action-ful demonstrations alone cannot establish that:
        the preconditions co-occur with the action in every positive, so the
        more general rule that drops the action fits the same evidence.

        Idempotent on `evidence_id`: an observation has one identity, and the
        same transition arriving twice must not read as independent
        corroboration. Returns True if a new row was written.
        """
        if not example.evidence_id:
            raise ValueError(
                "a demonstration carries no evidence_id; without it the store "
                "cannot keep one observation from counting twice")
        if not domain_id:
            raise ValueError("a demonstration must belong to a domain")

        await self.ensure_schema()
        predicate, arity = (
            example.action.signature if example.action is not None
            else self.CONTRASTIVE)
        rows = await self.db().execute_query(
            "INSERT INTO unified.operator_demonstrations"
            " (evidence_id, domain_id, predicate, arity, before_facts, action,"
            "  after_facts, positive)"
            " VALUES ($1, $2, $3, $4, $5, $6, $7, $8)"
            " ON CONFLICT (evidence_id) DO NOTHING"
            " RETURNING evidence_id",
            (example.evidence_id, domain_id, predicate, arity,
             _facts_json(example.before),
             str(example.action) if example.action is not None else None,
             _facts_json(example.after), bool(example.positive)),
            fetch_all=True,
        )
        written = bool(rows)
        if written:
            # Enqueue the signature for off-band induction. Cheap (one upsert),
            # so recording stays a hot-path operation; the hypothesis search it
            # triggers happens later, off the acting path. An actionless
            # contrastive enqueues under CONTRASTIVE -- the drain expands it to
            # every operator in the domain, because a new contrastive sharpens
            # them all.
            await self._mark_pending(domain_id, predicate, arity)
        logger.info("demonstration %s for %s in %s: %s", example.evidence_id,
                    f"{predicate}/{arity}" if example.action else "contrastive",
                    domain_id, "recorded" if written else "already present")
        return written

    async def _mark_pending(self, domain_id: str, predicate: str, arity: int) -> None:
        await self.db().execute_query(
            "INSERT INTO unified.operator_induction_pending (domain_id, predicate, arity)"
            " VALUES ($1, $2, $3)"
            " ON CONFLICT (domain_id, predicate, arity) DO UPDATE SET enqueued_at = NOW()",
            (domain_id, predicate, arity), commit=True)

    async def pending_signatures(self, *, limit: Optional[int] = None) -> List[tuple]:
        """Signatures awaiting re-induction, oldest enqueue first."""
        await self.ensure_schema()
        query = ("SELECT domain_id, predicate, arity FROM"
                 " unified.operator_induction_pending ORDER BY enqueued_at")
        if limit is not None:
            query += f" LIMIT {int(limit)}"
        rows = await self.db().execute_query(query, fetch_all=True) or []
        return [(r["domain_id"], r["predicate"], r["arity"]) for r in rows]

    async def clear_pending(self, *, domain_id: str, predicate: str, arity: int) -> None:
        await self.db().execute_query(
            "DELETE FROM unified.operator_induction_pending"
            " WHERE domain_id = $1 AND predicate = $2 AND arity = $3",
            (domain_id, predicate, arity), commit=True)

    async def load(self, *, domain_id: str, predicate: str,
                   arity: int) -> List[TrainingExample]:
        """Every demonstration recorded for one operator signature, oldest first.

        Oldest first so an induction/held-out split by recency is stable: the
        rule is induced from what was seen earlier and judged against what came
        after, and a run that reordered them could validate a rule on an
        observation it was induced from.
        """
        await self.ensure_schema()
        rows = await self.db().execute_query(
            "SELECT evidence_id, before_facts, action, after_facts, positive"
            " FROM unified.operator_demonstrations"
            " WHERE domain_id = $1 AND predicate = $2 AND arity = $3"
            " ORDER BY created_at, evidence_id",
            (domain_id, predicate, arity), fetch_all=True,
        ) or []

        return [self._example(row) for row in rows]

    async def load_contrastive(self, *, domain_id: str) -> List[TrainingExample]:
        """The domain's actionless contrastive negatives, oldest first.

        Included in the induction basis of every operator so induction can
        establish that the action -- not the co-occurring preconditions alone --
        produces the effect. Without them a runtime that only ever executes
        actions would induce operators that drop the action entirely.
        """
        await self.ensure_schema()
        predicate, arity = self.CONTRASTIVE
        rows = await self.db().execute_query(
            "SELECT evidence_id, before_facts, action, after_facts, positive"
            " FROM unified.operator_demonstrations"
            " WHERE domain_id = $1 AND predicate = $2 AND arity = $3"
            " ORDER BY created_at, evidence_id",
            (domain_id, predicate, arity), fetch_all=True,
        ) or []
        return [self._example(row) for row in rows]

    @staticmethod
    def _example(row) -> TrainingExample:
        action = row["action"]
        return TrainingExample(
            before=_parse_facts(row["before_facts"]),
            action=Fact.parse(action) if action else None,
            after=_parse_facts(row["after_facts"]),
            positive=bool(row["positive"]),
            evidence_id=row["evidence_id"],
        )

    async def signatures(self, *, domain_id: str) -> List[tuple]:
        """The (predicate, arity) signatures with demonstrations in a domain."""
        await self.ensure_schema()
        rows = await self.db().execute_query(
            "SELECT DISTINCT predicate, arity FROM unified.operator_demonstrations"
            " WHERE domain_id = $1 ORDER BY predicate, arity",
            (domain_id,), fetch_all=True,
        ) or []
        return [(row["predicate"], row["arity"]) for row in rows]


_store: Optional[DemonstrationStore] = None


def get_demonstration_store() -> DemonstrationStore:
    global _store
    if _store is None:
        _store = DemonstrationStore()
    return _store
