#!/usr/bin/env python3
"""Durable home for rules the substrate learned, and the evidence for each.

Without this a learned rule dies with the process, so a capability acquired
from demonstrations cannot be distinguished from one re-derived at every
startup. Persistence is what makes "the teacher left and the competence
remained" a checkable claim rather than a description.

Four epistemic states, defined semantically so they cannot blur:

  CANDIDATE   produced by induction; NOT executable
  SUPPORTED   has supporting evidence beyond its induction basis;
              still not necessarily executable
  VALIDATED   passed the required independent validation policy;
              MAY be consumed by execution
  REFUTED     at least one admissible observation contradicts it under
              conditions where it predicts an effect

REFUTED is not deletion. The rule, its refuting evidence and the rule that
superseded it are all retained, because "this generalization was too broad and
a narrower one succeeded" is itself learned knowledge, and a store that erases
its failures can only ever report survivorship.

The provenance invariant, enforced in `validate` rather than documented:

    A rule cannot validate itself using the evidence from which it was induced.

Evidence carries a role for exactly this reason -- induction and validation
draw on disjoint root observations. Root identity applies throughout: ten
transformed copies of one demonstration are one root observation, so a
duplicated evidence id can never inflate a count into apparent independence.

The canonical representation is the typed structure in `canonical_rule_json`.
`rendered_formula` is a projection for reading and for handing to the existing
inference machinery. Storing the string as the truth would trap learned
cognition in a textual encoding the moment negation, typing or arithmetic
arrive.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence, Set

from core.learning.learning_policy import guard_learning
from core.learning.rule_identity import semantic_fingerprint
from core.learning.rule_induction import (
    BindingOrigin, CandidateRule, Fact, InductionResult, OutputBinding,
    RuleEffects, TrainingExample, applies, contradicted_by, derives,
)

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 3
#: v1 lacked `action`; it reads back with action=None rather than being stranded.
#: v2 lacked `outputs`; it reads back with none, which is what a rule written
#: before actions could produce values actually said. Writing v3 for a rule
#: WITH outputs and reading it as v2 would silently drop the computation and
#: leave a rule that means something else -- so the version moves.
READABLE_SCHEMA_VERSIONS = {1, 2, 3}
INDUCTION_METHOD = "plotkin_lgg_minimal"
INDUCTION_VERSION = 1
VALIDATION_POLICY = "held_out_disjoint_roots"
VALIDATION_VERSION = 1


class EpistemicStatus(Enum):
    CANDIDATE = "candidate"
    SUPPORTED = "supported"
    VALIDATED = "validated"
    REFUTED = "refuted"
    #: An implementation defect produced a malformed hypothesis. NOT the same
    #: claim as REFUTED, which says evidence showed the hypothesis false --
    #: here nothing was ever tested, the rule should not have been written.
    #: Filing such a rule as REFUTED would put a fabricated negative result in
    #: the learning record and let a code bug read as knowledge gained.
    INVALID_ARTIFACT = "invalid_artifact"


def confers_execution_authority(status: EpistemicStatus) -> bool:
    """Whether a rule in this status may be consumed by execution.

    Defined once. Execution, the planner and the authority-change log all have
    to agree on what "may act on this" means; three copies of `status ==
    VALIDATED` would be three places to forget when a status is added.
    """
    return status is EpistemicStatus.VALIDATED


class EvidenceRole(Enum):
    """Why this observation is attached to this rule.

    The distinction between INDUCTION_* and VALIDATION_* is the whole basis of
    the independence claim; collapsing them would let a rule cite its own
    origin as confirmation.
    """

    INDUCTION_POSITIVE = "induction_positive"
    INDUCTION_NEGATIVE = "induction_negative"
    VALIDATION_POSITIVE = "validation_positive"
    VALIDATION_NEGATIVE = "validation_negative"
    RUNTIME_CONFIRMATION = "runtime_confirmation"
    RUNTIME_CONTRADICTION = "runtime_contradiction"


INDUCTION_ROLES = {EvidenceRole.INDUCTION_POSITIVE, EvidenceRole.INDUCTION_NEGATIVE}


class ProvenanceViolation(RuntimeError):
    """Raised when validation would reuse the evidence that induced the rule."""


def _fact_json(fact: Fact) -> Dict[str, Any]:
    return {"predicate": fact.predicate, "args": list(fact.args)}


def to_json(rule: CandidateRule) -> Dict[str, Any]:
    """The canonical typed structure. Sorted so the encoding is stable."""
    def facts(collection):
        return [_fact_json(f) for f in sorted(collection)]

    return {
        "schema_version": SCHEMA_VERSION,
        "body": facts(rule.body),
        "add_effects": facts(rule.effects.add),
        "delete_effects": facts(rule.effects.delete),
        "action": _fact_json(rule.action) if rule.action else None,
        "outputs": [
            {"variable": o.variable, "origin": o.origin.value,
             "producer": o.producer, "function": o.function,
             "inputs": list(o.inputs)}
            for o in rule.outputs
        ],
    }


def from_json(payload: Dict[str, Any]) -> CandidateRule:
    """Read a stored rule, including one written before `action` existed.

    v1 rules are readable and carry action=None. That is honest rather than
    lossy: a v1 encoding genuinely does not record which body literal was the
    action, and inferring one would invent provenance. Such a rule is usable
    for inference and NOT admissible as a planning operator, which is the
    correct consequence of not knowing what the agent did.
    """
    version = payload.get("schema_version")
    if version not in READABLE_SCHEMA_VERSIONS:
        raise ValueError(
            f"learned rule encoded at schema_version {version}, this build reads "
            f"{sorted(READABLE_SCHEMA_VERSIONS)}; refusing to guess at the difference"
        )

    def facts(key):
        return frozenset(
            Fact(entry["predicate"], tuple(entry["args"])) for entry in payload.get(key, [])
        )

    raw_action = payload.get("action")
    action = Fact(raw_action["predicate"], tuple(raw_action["args"])) if raw_action else None

    outputs = tuple(
        OutputBinding(
            variable=entry["variable"], origin=BindingOrigin(entry["origin"]),
            producer=entry.get("producer"), function=entry.get("function"),
            inputs=tuple(entry.get("inputs", [])))
        for entry in payload.get("outputs", [])
    )

    return CandidateRule(
        body=facts("body"),
        effects=RuleEffects(add=facts("add_effects"), delete=facts("delete_effects")),
        action=action,
        outputs=outputs,
    )


@dataclass
class StoredRule:
    rule_id: str
    rule: CandidateRule
    status: EpistemicStatus
    domain_id: Optional[str] = None
    rule_kind: str = "state_transition"
    positive_root_count: int = 0
    negative_root_count: int = 0
    supersedes_rule_id: Optional[str] = None
    validated_at: Optional[datetime] = None
    detail: str = ""
    semantic_fingerprint: Optional[str] = None

    @property
    def is_executable(self) -> bool:
        """Only VALIDATED rules may be consumed by execution."""
        return confers_execution_authority(self.status)


@dataclass
class ValidationOutcome:
    status: EpistemicStatus
    confirmed: int = 0
    contradicted: int = 0
    independent_roots: List[str] = field(default_factory=list)
    detail: str = ""


DDL = """
CREATE TABLE IF NOT EXISTS unified.learned_rules (
    rule_id             VARCHAR PRIMARY KEY,
    domain_id           VARCHAR,
    rule_kind           VARCHAR NOT NULL,
    canonical_rule_json JSONB   NOT NULL,
    rendered_formula    TEXT    NOT NULL,
    epistemic_status    VARCHAR NOT NULL,
    induction_method    VARCHAR NOT NULL,
    induction_version   INTEGER NOT NULL,
    validation_policy   VARCHAR,
    validation_version  INTEGER,
    positive_root_count INTEGER NOT NULL DEFAULT 0,
    negative_root_count INTEGER NOT NULL DEFAULT 0,
    detail              TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    validated_at        TIMESTAMPTZ,
    supersedes_rule_id  VARCHAR REFERENCES unified.learned_rules(rule_id),
    -- SHA-256 over the rule's MEANING (see core.learning.rule_identity).
    -- rule_id stays what it always was, so the frozen EDU manifests keep
    -- resolving. Identity moved here rather than being rewritten underneath
    -- them.
    semantic_fingerprint VARCHAR(64)
);

ALTER TABLE unified.learned_rules
    ADD COLUMN IF NOT EXISTS semantic_fingerprint VARCHAR(64);

-- UNIQUE, partial. One meaning, one authoritative rule. Partial because rules
-- written before this column existed may carry NULL until backfilled, and a
-- NULL is "not yet computed", not "a meaning shared with every other NULL".
CREATE UNIQUE INDEX IF NOT EXISTS learned_rules_fingerprint_uniq
    ON unified.learned_rules (semantic_fingerprint)
    WHERE semantic_fingerprint IS NOT NULL;

-- Historical ids that were the same hypothesis under the old identity scheme.
-- Kept rather than deleted: a manifest or an authority event naming a legacy id
-- must still resolve to the rule it meant.
CREATE TABLE IF NOT EXISTS unified.rule_identity_aliases (
    legacy_rule_id    VARCHAR PRIMARY KEY,
    canonical_rule_id VARCHAR NOT NULL REFERENCES unified.learned_rules(rule_id),
    reason            TEXT    NOT NULL,
    migrated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS unified.learned_rule_evidence (
    rule_id          VARCHAR NOT NULL REFERENCES unified.learned_rules(rule_id),
    root_evidence_id VARCHAR NOT NULL,
    evidence_role    VARCHAR NOT NULL,
    supports         BOOLEAN NOT NULL,
    observed_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (rule_id, root_evidence_id, evidence_role)
);

CREATE INDEX IF NOT EXISTS learned_rules_status_idx
    ON unified.learned_rules (epistemic_status);
"""


class RuleStore:
    """Reads and writes learned rules. Decides status; never induces.

    Kept apart from RuleInducer on purpose: the component that judges a rule
    fit to execute must not be the component that proposed it.
    """

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

    # ---- writing --------------------------------------------------------

    async def record_induction(
        self,
        result: InductionResult,
        examples: Sequence[TrainingExample],
        domain_id: Optional[str] = None,
        rule_kind: str = "state_transition",
    ) -> List[StoredRule]:
        """Persist what induction produced, as CANDIDATE.

        Every surviving hypothesis is stored, not only the first. Discarding
        the rest would destroy the version space that a later demonstration is
        supposed to collapse, and the ambiguity would silently become a choice.
        """
        guard_learning("rule persistence")
        await self.ensure_schema()

        positives = _root_ids(e for e in examples if e.positive)
        negatives = _root_ids(e for e in examples if not e.positive)

        stored: List[StoredRule] = []
        reused = 0
        for candidate in result.candidates:
            fingerprint = semantic_fingerprint(
                candidate, domain_id=domain_id, rule_kind=rule_kind)

            # FINGERPRINT FIRST. Re-inducing the same hypothesis must strengthen
            # the rule that already states it, never mint a second one -- that
            # is the whole point of semantic identity. Six hours of lessons a
            # day over the same material would otherwise produce thousands of
            # "new" rules and every support count computed over them would be
            # counting copies.
            existing = await self._by_fingerprint(fingerprint)
            if existing is not None:
                await self._attach(existing.rule_id, positives,
                                   EvidenceRole.INDUCTION_POSITIVE, True)
                await self._attach(existing.rule_id, negatives,
                                   EvidenceRole.INDUCTION_NEGATIVE, False)
                refreshed = await self._refresh_root_counts(existing.rule_id)
                stored.append(refreshed)
                reused += 1
                continue

            record = StoredRule(
                # The id stays opaque and historical. Meaning lives in the
                # fingerprint, so old ids never have to be rewritten.
                rule_id=f"rule_{uuid.uuid4().hex[:12]}",
                rule=candidate,
                status=EpistemicStatus.CANDIDATE,
                domain_id=domain_id,
                rule_kind=rule_kind,
                positive_root_count=len(positives),
                negative_root_count=len(negatives),
                detail=result.detail,
                semantic_fingerprint=fingerprint,
            )
            await self._insert(record)
            await self._attach(record.rule_id, positives, EvidenceRole.INDUCTION_POSITIVE, True)
            await self._attach(record.rule_id, negatives, EvidenceRole.INDUCTION_NEGATIVE, False)
            stored.append(record)

        logger.info(
            "recorded %d rule(s) from %d positive / %d negative root observation(s) "
            "(%d new, %d already known and reinforced)",
            len(stored), len(positives), len(negatives), len(stored) - reused, reused,
        )
        return stored

    async def _by_fingerprint(self, fingerprint: str) -> Optional[StoredRule]:
        """The authoritative rule for this meaning, or None."""
        rows = await self.db().execute_query(
            "SELECT rule_id FROM unified.learned_rules WHERE semantic_fingerprint = $1"
            " ORDER BY created_at LIMIT 1", (fingerprint,), fetch_all=True)
        return await self.get(rows[0]["rule_id"]) if rows else None

    async def get(self, rule_id: str) -> Optional[StoredRule]:
        """One rule by id, following a legacy alias if that is what was named.

        A frozen manifest or an authority event may hold an id that migration
        folded into another rule. Resolving it here is what makes the migration
        non-destructive: the old identifier keeps meaning what it meant.
        """
        rows = await self.db().execute_query(
            "SELECT canonical_rule_id FROM unified.rule_identity_aliases"
            " WHERE legacy_rule_id = $1", (rule_id,), fetch_all=True)
        if rows:
            rule_id = rows[0]["canonical_rule_id"]

        rows = await self.db().execute_query(
            "SELECT rule_id, domain_id, rule_kind, canonical_rule_json, epistemic_status,"
            " positive_root_count, negative_root_count, supersedes_rule_id, validated_at,"
            " detail, semantic_fingerprint FROM unified.learned_rules WHERE rule_id = $1",
            (rule_id,), fetch_all=True)
        if not rows:
            return None
        row = rows[0]
        payload = row["canonical_rule_json"]
        if isinstance(payload, str):
            payload = json.loads(payload)
        return StoredRule(
            rule_id=row["rule_id"], rule=from_json(payload),
            status=EpistemicStatus(row["epistemic_status"]),
            domain_id=row["domain_id"], rule_kind=row["rule_kind"],
            positive_root_count=row["positive_root_count"],
            negative_root_count=row["negative_root_count"],
            supersedes_rule_id=row["supersedes_rule_id"],
            validated_at=row["validated_at"], detail=row["detail"] or "",
            semantic_fingerprint=row["semantic_fingerprint"],
        )

    async def _refresh_root_counts(self, rule_id: str) -> StoredRule:
        """Recount support from the evidence table.

        RECOUNTED, never incremented. Re-attaching roots the rule already had
        would otherwise inflate its support on every repeat of the same lesson,
        which is the duplicate-counting defect one level down from duplicate
        rules.
        """
        await self.db().execute_query(
            "UPDATE unified.learned_rules SET"
            " positive_root_count = (SELECT count(DISTINCT root_evidence_id)"
            "   FROM unified.learned_rule_evidence WHERE rule_id = $1 AND supports),"
            " negative_root_count = (SELECT count(DISTINCT root_evidence_id)"
            "   FROM unified.learned_rule_evidence WHERE rule_id = $1 AND NOT supports),"
            " updated_at = NOW() WHERE rule_id = $1", (rule_id,), commit=True)
        return await self.get(rule_id)

    async def record_projection(self, projection, *, rule_kind: str = "projected") -> StoredRule:
        """Persist an analogically projected rule as a CANDIDATE with NO evidence.

        THE ASYMMETRY IS THE POINT. A rule induced here earns CANDIDATE by
        generalizing observations made here. A projected rule has made no
        observations in this domain at all -- it is a proposal carried across a
        structural correspondence -- so it starts with zero evidence roots and
        cannot reach VALIDATED until the target world supplies its own.

        Analogy proposes; only target-domain evidence authorizes. This method
        therefore never touches evidence counts and never sets a status above
        CANDIDATE, and `validate()` remains the only route to executable
        authority for it, exactly as for anything else.
        """
        guard_learning("rule projection")
        await self.ensure_schema()

        if not projection.is_proposable:
            raise ValueError(
                f"{projection.outcome.value} is not proposable: {projection.detail}. "
                f"A partial operator would be tested, and the world's answer "
                f"attributed to a rule the analogy never claimed")

        fingerprint = semantic_fingerprint(
            projection.rule, domain_id=projection.target_domain, rule_kind=rule_kind)
        existing = await self._by_fingerprint(fingerprint)
        if existing is not None:
            logger.info("projection matches existing rule %s; not duplicating",
                        existing.rule_id)
            return existing

        record = StoredRule(
            rule_id=f"rule_{uuid.uuid4().hex[:12]}",
            rule=projection.rule,
            status=EpistemicStatus.CANDIDATE,
            domain_id=projection.target_domain,
            rule_kind=rule_kind,
            positive_root_count=0,
            negative_root_count=0,
            detail=(f"projected from {projection.source_rule_id} "
                    f"({projection.source_domain}) via {projection.mapping_id}"),
            semantic_fingerprint=fingerprint,
        )
        await self._insert(record)

        # Element-level provenance, so a later contradiction can be attributed
        # to the specific correspondence that was wrong rather than discarding
        # the whole analogy as opaque.
        await self.db().execute_query(
            """CREATE TABLE IF NOT EXISTS unified.rule_projections (
                   rule_id        VARCHAR NOT NULL REFERENCES unified.learned_rules(rule_id),
                   source_rule_id VARCHAR NOT NULL,
                   mapping_id     VARCHAR NOT NULL,
                   role           VARCHAR NOT NULL,
                   target_element VARCHAR NOT NULL,
                   source_element VARCHAR NOT NULL,
                   mapping_edge   VARCHAR NOT NULL,
                   projected_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                   PRIMARY KEY (rule_id, role, target_element, source_element)
               )""")
        for element in projection.provenance:
            await self.db().execute_query(
                "INSERT INTO unified.rule_projections (rule_id, source_rule_id,"
                " mapping_id, role, target_element, source_element, mapping_edge)"
                " VALUES ($1,$2,$3,$4,$5,$6,$7) ON CONFLICT DO NOTHING",
                (record.rule_id, projection.source_rule_id, projection.mapping_id,
                 element.role, element.target, element.source, element.mapping_edge),
                commit=True)

        logger.info("recorded projected CANDIDATE %s in %s (0 evidence roots)",
                    record.rule_id, projection.target_domain)
        return record

    async def _insert(self, record: StoredRule):
        await self.db().execute_query(
            "INSERT INTO unified.learned_rules ("
            " rule_id, domain_id, rule_kind, canonical_rule_json, rendered_formula,"
            " epistemic_status, induction_method, induction_version,"
            " positive_root_count, negative_root_count, detail, supersedes_rule_id,"
            " semantic_fingerprint)"
            " VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)",
            (
                record.rule_id, record.domain_id, record.rule_kind,
                json.dumps(to_json(record.rule)), record.rule.to_formula(),
                record.status.value, INDUCTION_METHOD, INDUCTION_VERSION,
                record.positive_root_count, record.negative_root_count,
                record.detail, record.supersedes_rule_id,
                record.semantic_fingerprint,
            ),
        )

    async def _attach(
        self, rule_id: str, roots: Sequence[str], role: EvidenceRole, supports: bool
    ):
        for root in roots:
            await self.db().execute_query(
                "INSERT INTO unified.learned_rule_evidence"
                " (rule_id, root_evidence_id, evidence_role, supports)"
                " VALUES ($1,$2,$3,$4) ON CONFLICT DO NOTHING",
                (rule_id, root, role.value, supports),
            )

    # ---- judging --------------------------------------------------------

    async def evidence_roots(
        self, rule_id: str, roles: Optional[Set[EvidenceRole]] = None
    ) -> Set[str]:
        rows = await self.db().execute_query(
            "SELECT root_evidence_id, evidence_role FROM unified.learned_rule_evidence"
            " WHERE rule_id = $1",
            (rule_id,), fetch_all=True,
        ) or []
        return {
            row["root_evidence_id"] for row in rows
            if roles is None or EvidenceRole(row["evidence_role"]) in roles
        }

    async def validate(
        self, record: StoredRule, held_out: Sequence[TrainingExample]
    ) -> ValidationOutcome:
        """Judge a candidate against observations it was not induced from.

        Raises rather than degrading when the held-out set overlaps the
        induction basis: a validation that quietly dropped the overlap would
        report a pass from a smaller, unstated sample, and the independence
        claim would be false without anything saying so.
        """
        guard_learning("rule validation")
        await self.ensure_schema()

        induction_roots = await self.evidence_roots(record.rule_id, INDUCTION_ROLES)
        held_out_roots = _root_ids(held_out)
        reused = induction_roots & set(held_out_roots)
        if reused:
            raise ProvenanceViolation(
                f"rule {record.rule_id} cannot be validated by {sorted(reused)}: "
                f"it was induced from those observations"
            )
        if not held_out_roots:
            return ValidationOutcome(
                status=record.status,
                detail="no independent observations supplied; status unchanged",
            )

        confirmed, contradicted = 0, 0
        confirming_roots: List[str] = []
        for example in held_out:
            # ASKED OF THE INDUCTION OWNER, not decided again here. This was a
            # second copy of the comparison and it had drifted to a subset
            # test, so a rule whose output the world supplies -- what a file
            # holds, what a request returns -- was REFUTED by every
            # demonstration of it working. Measured: a learned READ rule,
            # refuted by a held-out read that did exactly what it said.
            held = (derives(record.rule, example) if example.positive
                    else not contradicted_by(record.rule, example))
            if held:
                confirmed += 1
                confirming_roots.append(example.evidence_id)
            else:
                contradicted += 1

        if contradicted:
            outcome = ValidationOutcome(
                EpistemicStatus.REFUTED, confirmed, contradicted, held_out_roots,
                f"{contradicted} independent observation(s) contradict the rule",
            )
        elif confirmed:
            outcome = ValidationOutcome(
                EpistemicStatus.VALIDATED, confirmed, 0, held_out_roots,
                f"confirmed by {confirmed} independent observation(s)",
            )
        else:
            outcome = ValidationOutcome(
                EpistemicStatus.SUPPORTED, 0, 0, held_out_roots,
                "independent evidence attached but none exercised the rule",
            )

        await self._attach(
            record.rule_id, [r for r in held_out_roots if r in confirming_roots],
            EvidenceRole.VALIDATION_POSITIVE, True,
        )
        await self._attach(
            record.rule_id, [r for r in held_out_roots if r not in confirming_roots],
            EvidenceRole.VALIDATION_NEGATIVE, False,
        )
        await self._set_status(record, outcome)
        return outcome

    async def _set_status(self, record: StoredRule, outcome: ValidationOutcome):
        previous = record.status
        validated_at = (
            datetime.now(timezone.utc)
            if outcome.status is EpistemicStatus.VALIDATED else None
        )
        await self.db().execute_query(
            "UPDATE unified.learned_rules SET epistemic_status = $1, detail = $2,"
            " validation_policy = $3, validation_version = $4,"
            " validated_at = $5, updated_at = NOW() WHERE rule_id = $6",
            (outcome.status.value, outcome.detail, VALIDATION_POLICY,
             VALIDATION_VERSION, validated_at, record.rule_id),
        )
        record.status = outcome.status
        record.detail = outcome.detail
        record.validated_at = validated_at
        from core.learning.rule_authority import AuthorityCause
        await self._announce_authority(
            record.rule_id, previous, record.status, outcome.detail,
            AuthorityCause.VALIDATION)

    async def _announce_authority(
        self,
        rule_id: str,
        previous: EpistemicStatus,
        current: EpistemicStatus,
        detail: str,
        cause,
        observation_id: Optional[str] = None,
        task_id: Optional[str] = None,
        plan_id: Optional[str] = None,
        goal_id: Optional[str] = None,
    ) -> None:
        """Emit the durable authority-change record for a status transition.

        Every status write in this class goes through here so a rule cannot
        lose execution authority without the planning layer being able to find
        out. A transition to the same status is not an event and is skipped.
        """
        if previous is current:
            return
        from core.learning.rule_authority import (
            RuleAuthorityChanged, record_authority_change)

        await record_authority_change(self.db(), RuleAuthorityChanged(
            rule_id=rule_id,
            old_status=previous,
            new_status=current,
            cause=cause,
            observation_id=observation_id,
            task_id=task_id,
            plan_id=plan_id,
            goal_id=goal_id,
            detail=detail,
        ))

    async def supersede(self, refuted: StoredRule, replacement: StoredRule):
        """Record that a narrower rule replaced one that was too broad.

        The refuted rule is kept. That a generalization failed and how it was
        narrowed is learned knowledge in its own right.

        RECORDED IN A JOIN TABLE, not a column on the replacement. A single
        `supersedes_rule_id` can name one predecessor, so superseding a second
        rule with the same replacement OVERWROTE the first -- silently
        un-superseding it and returning it to execution. Narrowing a rule twice
        is ordinary (each new negative example can refute a further
        generalization), and the second correction must not undo the first.
        """
        await self.db().execute_query(
            "INSERT INTO unified.rule_supersessions"
            " (replacement_rule_id, superseded_rule_id) VALUES ($1, $2)"
            " ON CONFLICT DO NOTHING",
            (replacement.rule_id, refuted.rule_id),
            commit=True,
        )
        # Kept in step for readers of the row itself; the join table is the
        # authority, and is what executable_rules consults.
        await self.db().execute_query(
            "UPDATE unified.learned_rules SET supersedes_rule_id = $1, updated_at = NOW()"
            " WHERE rule_id = $2",
            (refuted.rule_id, replacement.rule_id),
            commit=True,
        )
        replacement.supersedes_rule_id = refuted.rule_id

    async def superseded_rule_ids(self) -> set:
        """Every rule that some other rule has replaced."""
        rows = await self.db().execute_query(
            "SELECT superseded_rule_id FROM unified.rule_supersessions",
            fetch_all=True) or []
        return {r["superseded_rule_id"] for r in rows}

    # ---- reading --------------------------------------------------------

    async def executable_rules(self, domain_id: Optional[str] = None) -> List[StoredRule]:
        """The rules execution may consume: VALIDATED, and not yet superseded.

        SUPERSESSION WAS RECORDED AND NEVER CONSUMED. `supersede()` writes the
        link, and this returned every VALIDATED rule regardless -- so a rule
        narrowed precisely because it was too broad went on supplying planning
        authority beside its replacement.

        Observed: a MOVE rule missing the AT(X,A) precondition stayed
        executable after a corrected rule replaced it, and the planner used the
        broad one to "reach" AT(z,VAULT) in one step from a world where z was
        in HALL. Valid for that rule; impossible in the world. Learning that a
        generalization was wrong is worth nothing while the wrong rule still
        gets a vote.

        The superseded rule is still stored and still readable through load();
        it is withheld from EXECUTION, which is a different question from
        whether it is remembered.
        """
        rules = await self.load(EpistemicStatus.VALIDATED, domain_id)
        replaced = await self.superseded_rule_ids()
        return [r for r in rules if r.rule_id not in replaced]

    async def load(
        self, status: Optional[EpistemicStatus] = None, domain_id: Optional[str] = None
    ) -> List[StoredRule]:
        await self.ensure_schema()
        clauses, params = [], []
        if status is not None:
            params.append(status.value)
            clauses.append(f"epistemic_status = ${len(params)}")
        if domain_id is not None:
            params.append(domain_id)
            clauses.append(f"domain_id = ${len(params)}")
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""

        rows = await self.db().execute_query(
            "SELECT rule_id, domain_id, rule_kind, canonical_rule_json, epistemic_status,"
            " positive_root_count, negative_root_count, supersedes_rule_id, validated_at,"
            " detail, semantic_fingerprint FROM unified.learned_rules" + where
            + " ORDER BY created_at",
            tuple(params) if params else None, fetch_all=True,
        ) or []

        out: List[StoredRule] = []
        for row in rows:
            payload = row["canonical_rule_json"]
            if isinstance(payload, str):
                payload = json.loads(payload)
            out.append(StoredRule(
                rule_id=row["rule_id"],
                rule=from_json(payload),
                status=EpistemicStatus(row["epistemic_status"]),
                domain_id=row["domain_id"],
                rule_kind=row["rule_kind"],
                positive_root_count=row["positive_root_count"],
                negative_root_count=row["negative_root_count"],
                supersedes_rule_id=row["supersedes_rule_id"],
                validated_at=row["validated_at"],
                detail=row["detail"] or "",
                semantic_fingerprint=row["semantic_fingerprint"],
            ))
        return out


def _root_ids(examples) -> List[str]:
    """Distinct root observations, order preserved.

    Ten transformed copies of one demonstration are one root observation, so a
    repeated id must not read as independent corroboration.
    """
    seen: List[str] = []
    for example in examples:
        if example.evidence_id and example.evidence_id not in seen:
            seen.append(example.evidence_id)
    return seen


_store: Optional[RuleStore] = None


def get_rule_store() -> RuleStore:
    global _store
    if _store is None:
        _store = RuleStore()
    return _store


async def record_runtime_evidence(
    store: "RuleStore",
    evidence,
    attribution,
    detail: str = "",
    task_id: Optional[str] = None,
    plan_id: Optional[str] = None,
    goal_id: Optional[str] = None,
) -> Optional[EpistemicStatus]:
    """Persist what execution established, and adjust authority if it counts.

    Only RULE_EVIDENCE may change a rule's status. A mismatch attributed to a
    misbound tool, a dead observer or external interference is recorded as
    having happened and explicitly NOT charged to the rule -- the credit
    invariant applied to runtime: never debit a strategy for an infrastructure
    failure.

    Returns the rule's status after the write, or None when nothing changed.
    """
    from core.execution.effect_verification import Attribution, RuntimeOutcome

    guard_learning("runtime evidence")
    await store.ensure_schema()

    if not evidence.rule_id:
        return None

    role = (EvidenceRole.RUNTIME_CONFIRMATION
            if evidence.outcome is RuntimeOutcome.CONFIRMATION
            else EvidenceRole.RUNTIME_CONTRADICTION)
    supports = evidence.outcome is RuntimeOutcome.CONFIRMATION

    # The observation is a root: it is something that happened, not an
    # interpretation of something else.
    await store._attach(evidence.rule_id, [evidence.observation_id], role, supports)

    if attribution is not Attribution.RULE_EVIDENCE:
        logger.info(
            "runtime %s for %s recorded but NOT charged to the rule (%s): %s",
            evidence.outcome.value, evidence.rule_id, attribution.value, detail,
        )
        return None

    if evidence.outcome is not RuntimeOutcome.CONTRADICTION:
        return None

    # Credible, attributable contradiction: the rule loses execution authority.
    # It is not deleted -- the rule, its evidence and what challenged it are the
    # epistemic history, and a store that erases its failures reports only
    # survivorship.
    #
    # The status is read before the write so the emitted event states what the
    # rule actually changed FROM. Assuming VALIDATED here would misreport a
    # contradiction that arrived against an already-refuted rule, and the
    # planning layer would invalidate plans on an authority loss that had
    # already happened.
    from core.learning.rule_authority import AuthorityCause

    row = await store.db().execute_query(
        "SELECT epistemic_status FROM unified.learned_rules WHERE rule_id = $1",
        (evidence.rule_id,), fetch_one=True,
    )
    if row is None:
        logger.warning(
            "runtime contradiction for unknown rule %s; nothing to revise",
            evidence.rule_id)
        return None
    previous = EpistemicStatus(row["epistemic_status"])
    revised_detail = (
        f"refuted by runtime observation {evidence.observation_id}: {evidence.detail}")

    await store.db().execute_query(
        "UPDATE unified.learned_rules SET epistemic_status = $1, validated_at = NULL,"
        " detail = $2, updated_at = NOW() WHERE rule_id = $3",
        (EpistemicStatus.REFUTED.value, revised_detail, evidence.rule_id),
    )
    logger.warning(
        "rule %s lost VALIDATED authority: %s", evidence.rule_id, evidence.detail)

    await store._announce_authority(
        evidence.rule_id, previous, EpistemicStatus.REFUTED, revised_detail,
        AuthorityCause.RUNTIME_CONTRADICTION,
        observation_id=evidence.observation_id,
        task_id=task_id, plan_id=plan_id, goal_id=goal_id,
    )
    return EpistemicStatus.REFUTED


def training_example_from_runtime(
    before, action, after, evidence_id: str, positive: bool
) -> TrainingExample:
    """Turn an executed action into a demonstration the inducer can learn from.

    Everything needed is already recorded: the observed state before, the action
    actually invoked, and the observed state after. Nothing is invented, which
    is what makes this admissible as evidence rather than as interpretation.
    """
    return TrainingExample(
        before=tuple(sorted(before)), action=action, after=tuple(sorted(after)),
        positive=positive, evidence_id=evidence_id,
    )
