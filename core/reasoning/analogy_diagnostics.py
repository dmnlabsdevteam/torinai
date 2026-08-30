#!/usr/bin/env python3
"""Analogy diagnostics — Oracle A and Oracle B.

`mappings=0` is not one outcome. It is at least eight different mechanisms
wearing the same result:

    the candidate pair was never generated
    the source name did not resolve
    the target domain did not resolve
    an early-exit gate fired before scoring
    attributes did not overlap (a HARD gate: relationships are then never read)
    relation labels differ lexically though the roles correspond
    the aggregation suppressed a good pair
    the threshold is miscalibrated

These oracles separate them. They OBSERVE the production scorer by calling its
own component methods; they do not reimplement it and they do not modify it.
Measuring a baseline against a scorer that has already been "improved" tells you
nothing about which repair mattered.

    Oracle A  — was the expected pair ever PRESENTED to the scorer?
    Oracle B  — once presented, how did each component score it?

Oracle A failing means the scorer is innocent and the repair belongs in
candidate enumeration, name resolution or domain filtering.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class PairTrace:
    """Every stage a single candidate pair passed or failed."""
    source: str
    target: str

    presented: bool = False
    #: Which gate stopped it, or None if it was fully scored.
    stopped_at: Optional[str] = None

    attribute_overlap: Optional[float] = None
    relationship_overlap: Optional[float] = None
    structural_similarity: Optional[float] = None
    functional_similarity: Optional[float] = None
    confidence: Optional[float] = None

    #: Raw relation labels each side carries, so lexical fragmentation is
    #: visible as data rather than inferred from a low score.
    source_relations: Tuple[str, ...] = ()
    target_relations: Tuple[str, ...] = ()
    shared_relation_labels: Tuple[str, ...] = ()
    #: Deliberately UNKNOWN until a canonical relation vocabulary exists. Left
    #: unmeasured rather than approximated, so the baseline can attribute a
    #: known share of the loss to relation-vocabulary fragmentation.
    relation_class_match: str = "UNMEASURED"

    source_attributes: Tuple[str, ...] = ()
    target_attributes: Tuple[str, ...] = ()
    shared_attribute_keys: Tuple[str, ...] = ()


@dataclass
class OracleAResult:
    """Candidate-generation recall, decomposed into three separable stages.

        A0  source resolution      surface query -> a learned concept
        A1  target availability    domain exists AND the target concept exists
        A2  candidate enumeration  the pair was actually handed to the scorer

    Each stage failing implies a different repair:

        A0 fails  -> identity / retrieval defect at the query boundary
        A1 fails  -> ingestion or graph-coverage gap
        A0,A1 ok but A2 fails -> candidate generator defect
        A2 ok     -> the scorer is implicated, and only then
    """
    source_query: str
    target_domain_query: str
    expected_target: Optional[str] = None

    # A0
    a0_source_resolved: bool = False
    source_resolved_to: Optional[str] = None
    source_resolution_note: str = ""

    # A1
    a1_target_domain_exists: bool = False
    a1_target_concept_exists: bool = False

    # A2 — global semantic resolution (identity, independent of classification)
    a2_target_resolved_globally: bool = False
    a2_resolutions: List[Tuple[str, str]] = field(default_factory=list)

    # A3 — domain membership of whatever A2 resolved
    a3_expected_domain_membership: bool = False
    a3_member_domains: List[str] = field(default_factory=list)
    target_domain_resolved_to: Optional[str] = None
    target_domain_note: str = ""
    target_concept_note: str = ""

    # A4
    a2_pair_presented: bool = False
    concepts_in_target_domain: int = 0
    pairs_presented: List[Tuple[str, str]] = field(default_factory=list)

    @property
    def first_failing_stage(self) -> Optional[str]:
        """Which boundary the expected correspondence disappeared at."""
        if not self.a0_source_resolved:
            return "A0_source_resolution"
        if not self.a1_target_domain_exists:
            return "A1_target_domain_missing"
        if self.expected_target and not self.a2_target_resolved_globally:
            return "A2_target_not_learned_anywhere"
        if self.expected_target and not self.a3_expected_domain_membership:
            return "A3_domain_membership"
        if self.expected_target and not self.a2_pair_presented:
            return "A4_candidate_enumeration"
        return None

    @property
    def scorer_is_implicated(self) -> bool:
        """False means the repair belongs upstream of scoring."""
        return self.first_failing_stage is None


class AnalogyDiagnostics:
    """Instrumented traversal that mirrors find_analogy's enumeration."""

    def __init__(self, engine):
        self.engine = engine

    # ---- Oracle A ------------------------------------------------------

    def resolve_source(self, name: str) -> Tuple[Optional[Any], Optional[str], str]:
        """Mirror find_analogy's source lookup, and report WHY it failed.

        find_analogy does `if source_concept in concepts` — an exact key match
        against the concept name. A learned concept called
        `electrical_resistance` is therefore invisible to a query for
        `resistance`, which is a candidate-generation failure, not a scoring one.
        """
        for domain, concepts in self.engine.concepts.items():
            if name in concepts:
                return concepts[name], domain, "exact match"

        near = [
            (d, n) for d, cs in self.engine.concepts.items() for n in cs
            if name in n or n in name
        ]
        if near:
            return None, None, (
                f"no exact key {name!r}; near names exist and are NOT reachable "
                f"by this lookup: {near[:6]}"
            )
        return None, None, f"no concept named {name!r} in any domain"

    def resolve_target_domain(self, domain: str) -> Tuple[Optional[str], str]:
        if domain in self.engine.concepts:
            return domain, "exact match"
        near = [d for d in self.engine.concepts if domain in d or d in domain]
        if near:
            return None, (
                f"no exact domain key {domain!r}; near domains exist and are NOT "
                f"reachable: {near}"
            )
        return None, f"no domain {domain!r}; known: {sorted(self.engine.concepts)}"

    async def oracle_a(
        self, source_query: str, target_domain_query: str,
        expected_target: Optional[str] = None,
    ) -> OracleAResult:
        """Was the expected pair ever handed to the scorer?"""
        res = OracleAResult(source_query=source_query,
                            target_domain_query=target_domain_query,
                            expected_target=expected_target)

        # A0 — source resolution
        source, src_domain, note = self.resolve_source(source_query)
        res.source_resolution_note = note
        res.a0_source_resolved = source is not None
        res.source_resolved_to = f"{src_domain}:{source.name}" if source else None

        # A1 — target availability
        tgt_domain, dnote = self.resolve_target_domain(target_domain_query)
        res.target_domain_resolved_to = tgt_domain
        res.target_domain_note = dnote
        res.a1_target_domain_exists = tgt_domain is not None

        if tgt_domain is not None and expected_target:
            targets = self.engine.concepts.get(tgt_domain, {})
            res.a1_target_concept_exists = expected_target in targets
            if not res.a1_target_concept_exists:
                near = [n for n in targets if expected_target in n or n in expected_target]
                res.target_concept_note = (
                    f"{expected_target!r} not in {tgt_domain}; near names present "
                    f"and unreachable by exact lookup: {near[:6]}" if near else
                    f"{expected_target!r} was never learned in {tgt_domain}"
                )

        # A2/A3 — global semantic resolution, then domain membership.
        # Separated because "never learned" and "learned but filed elsewhere"
        # imply different repairs, and the E1b census showed 2 of 4 targets were
        # the second while reporting as the first.
        if expected_target:
            try:
                from core.domain.concept_identity import ConceptIdentityService
                from core.database import get_database_manager
                ident = ConceptIdentityService(get_database_manager())
                res.a2_resolutions = await ident.resolve_query(expected_target)
                res.a2_target_resolved_globally = bool(res.a2_resolutions)
                doms = []
                for cid, _how in res.a2_resolutions:
                    doms += await ident.domains_of(cid)
                res.a3_member_domains = sorted(set(doms))
                res.a3_expected_domain_membership = (
                    target_domain_query in res.a3_member_domains)
            except Exception as e:
                logger.warning("Identity resolution unavailable in Oracle A: %s", e)

        if source is None or tgt_domain is None:
            return res

        # A4 — candidate enumeration
        targets = self.engine.concepts.get(tgt_domain, {})
        res.concepts_in_target_domain = len(targets)
        # find_analogy enumerates every concept in the target domain, so every
        # one of them IS presented to the scorer.
        res.pairs_presented = [(source.name, t) for t in targets]
        if expected_target:
            res.a2_pair_presented = expected_target in targets
        return res

    # ---- Oracle B ------------------------------------------------------

    async def oracle_b(self, source, target, min_similarity: float) -> PairTrace:
        """Score one pair through the PRODUCTION components, recording each."""
        e = self.engine
        t = PairTrace(source=source.name, target=target.name, presented=True)

        t.source_attributes = tuple(sorted(source.attributes or []))
        t.target_attributes = tuple(sorted(target.attributes or []))
        t.shared_attribute_keys = tuple(
            sorted(set(t.source_attributes) & set(t.target_attributes)))
        t.source_relations = tuple(sorted({r[0] for r in (source.relationships or [])}))
        t.target_relations = tuple(sorted({r[0] for r in (target.relationships or [])}))
        t.shared_relation_labels = tuple(
            sorted(set(t.source_relations) & set(t.target_relations)))

        t.attribute_overlap = await e._attribute_overlap(
            source.attributes, target.attributes)
        t.relationship_overlap = await e._relationship_overlap(
            source.relationships, target.relationships)

        # _structural_similarity returns 0.0 when attribute overlap is falsy,
        # WITHOUT consulting relationships. Recorded as its own stage so a pair
        # with strong relational correspondence is not reported as "dissimilar".
        if not t.attribute_overlap:
            t.structural_similarity = 0.0
            t.stopped_at = "attribute_overlap_gate (relationships never scored)"
            return t

        t.structural_similarity = await e._structural_similarity(source, target)
        if t.structural_similarity < min_similarity * 0.5:
            t.stopped_at = "structural_early_exit"
            return t

        t.functional_similarity = await e._functional_similarity(source, target)
        if t.functional_similarity < min_similarity * 0.5:
            t.stopped_at = "functional_early_exit"
            return t

        t.confidence = t.structural_similarity * 0.6 + t.functional_similarity * 0.4
        if t.confidence < min_similarity:
            t.stopped_at = "confidence_below_threshold"
        return t


async def graph_health(db) -> Dict[str, Any]:
    """Report the graph BEFORE any analogy experiment.

    Ingestion order, dangling edges and relation-vocabulary size all change what
    the scorer can possibly see, so a score difference is uninterpretable
    without them.
    """
    async def scalar(sql):
        rows = await db.execute_query(sql, fetch_all=True)
        return int(rows[0]["n"]) if rows else 0

    vocab = await db.execute_query(
        "SELECT relation, count(*) n FROM unified.concept_relations "
        "GROUP BY relation ORDER BY n DESC", fetch_all=True) or []
    domains = await db.execute_query(
        "SELECT domain, count(*) n FROM unified.concepts GROUP BY domain "
        "ORDER BY n DESC", fetch_all=True) or []

    total = await scalar("SELECT count(*) n FROM unified.concept_relations")
    resolved = await scalar(
        "SELECT count(*) n FROM unified.concept_relations WHERE target_concept_id IS NOT NULL")
    return {
        "concepts": await scalar("SELECT count(*) n FROM unified.concepts"),
        "with_attributes": await scalar(
            "SELECT count(*) n FROM unified.concepts WHERE attributes::text NOT IN ('{}','null')"),
        "edges_total": total,
        "edges_canonical": resolved,
        "edges_dangling": total - resolved,
        "relation_vocabulary": [(r["relation"], r["n"]) for r in vocab],
        "relation_vocabulary_size": len(vocab),
        "domains": [(d["domain"], d["n"]) for d in domains],
    }


__all__ = ["AnalogyDiagnostics", "PairTrace", "OracleAResult", "graph_health"]
