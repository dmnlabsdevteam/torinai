#!/usr/bin/env python3
"""Concept identity relations and domain membership.

Two defects measured on the E1b control graph, both of which presented as
"target concept missing":

  1. CLASSIFICATION PARTICIPATED IN IDENTITY.
     `concept_id = "domain:name"` made whichever domain label an extractor
     happened to choose part of what a thing IS. Sixteen source artifacts
     produced eighteen domains; one coherent hydraulic corpus scattered across
     hydraulic / fluid_mechanics / fluid_dynamics / plumbing / flow_measurement.
     `pressure` and `flow_rate` existed as exact canonical concepts the whole
     time -- under `physics` and `fluid_dynamics` -- and a query for them in
     `hydraulic` reported them absent.

  2. QUALIFIED NAMES HAD NO RELATION TO THEIR HEAD.
     `hydraulic:hydraulic_accumulator` and `plumbing:flow_restriction` are
     semantically connected to `accumulator` and `restriction`, but nothing
     recorded that. Fuzzy suffix matching would have merged them, and would
     ALSO have merged `fluid_dynamics:system_pressure` into `physics:pressure`
     -- which are plausibly different concepts. A false merge is unrecoverable.

So identity relations are typed, and only one of them collapses identity:

    SAME_AS           the same concept under another name
    SPECIALIZATION_OF a narrower concept; NOT the same thing
    RELATED_TO        connected, relationship unspecified
    UNKNOWN           a lexical resemblance with no established relation

The rule that separates SAME_AS from SPECIALIZATION_OF is deterministic and
domain-aware rather than lexical:

    `hydraulic_accumulator` in domain `hydraulic`
        the qualifier IS the concept's own domain -> a domain-qualified name
        for the same thing -> SAME_AS accumulator

    `flow_restriction` in domain `plumbing`
        the qualifier `flow` is NOT the domain -> it narrows the head
        -> SPECIALIZATION_OF restriction

    `system_pressure` in domain `fluid_dynamics`
        `system` is not the domain -> SPECIALIZATION_OF pressure, NOT the same
        concept as physics:pressure
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


class IdentityRelation(Enum):
    """Only SAME_AS may collapse two concepts into one identity."""
    SAME_AS = "same_as"
    SPECIALIZATION_OF = "specialization_of"
    RELATED_TO = "related_to"
    UNKNOWN = "unknown"


#: Domain words that name the same field. Used ONLY to decide whether a
#: qualifier is the concept's own domain -- never to merge concepts directly.
_DOMAIN_SYNONYMS: Dict[str, Set[str]] = {
    "hydraulic": {"hydraulic", "hydraulics", "fluid", "fluid_mechanics",
                  "fluid_dynamics", "hydro"},
    "electrical": {"electrical", "electric", "electronics",
                   "electrical_engineering", "electronic"},
    "plumbing": {"plumbing", "plumb"},
    "physics": {"physics", "physical"},
    "chemistry": {"chemistry", "chemical"},
    "mechanics": {"mechanics", "mechanical"},
}


def _domain_family(domain: str) -> Set[str]:
    d = (domain or "").strip().lower()
    for _, syns in _DOMAIN_SYNONYMS.items():
        if d in syns:
            return syns
    return {d}


def classify_qualified_name(
    name: str, domain: str, head: str,
) -> Tuple[IdentityRelation, str]:
    """Relation between a qualified `name` and its bare `head`.

    Returns (relation, basis). The basis records WHY, so a merge can be audited
    rather than trusted.
    """
    n = (name or "").strip().lower()
    h = (head or "").strip().lower()
    if not n or not h or n == h:
        return IdentityRelation.UNKNOWN, "not a qualified form"

    if n.endswith("_" + h):
        qualifier = n[: -(len(h) + 1)]
    elif n.startswith(h + "_"):
        # `pressure_loss` is a thing that happens to pressure, not a pressure.
        return IdentityRelation.RELATED_TO, f"head-initial compound ({n} -> {h})"
    else:
        return IdentityRelation.UNKNOWN, "no qualifier/head decomposition"

    family = _domain_family(domain)
    if qualifier in family:
        return (IdentityRelation.SAME_AS,
                f"qualifier {qualifier!r} is the concept's own domain ({domain})")
    return (IdentityRelation.SPECIALIZATION_OF,
            f"qualifier {qualifier!r} narrows {h!r} and is not the domain ({domain})")


class ConceptIdentityService:
    """Derives and stores domain membership and identity relations."""

    def __init__(self, db):
        self.db = db

    # ---- domain membership ---------------------------------------------

    async def backfill_domain_memberships(self) -> int:
        """Record the domain currently embedded in each concept_id.

        Membership becomes a separate, many-to-many fact. Identity stops
        depending on which classification an extractor picked.
        """
        rows = await self.db.execute_query(
            "SELECT concept_id, domain FROM unified.concepts", fetch_all=True) or []
        n = 0
        for r in rows:
            await self.db.execute_query(
                """INSERT INTO unified.concept_domains (concept_id, domain, source)
                   VALUES ($1,$2,'extracted') ON CONFLICT DO NOTHING""",
                (r["concept_id"], r["domain"]), commit=True)
            n += 1
        return n

    async def add_membership(self, concept_id: str, domain: str, source: str,
                             evidence_id: Optional[str] = None) -> None:
        await self.db.execute_query(
            """INSERT INTO unified.concept_domains
                   (concept_id, domain, source, evidence_id)
               VALUES ($1,$2,$3,$4) ON CONFLICT DO NOTHING""",
            (concept_id, domain.strip().lower(), source, evidence_id), commit=True)

    async def domains_of(self, concept_id: str) -> List[str]:
        rows = await self.db.execute_query(
            "SELECT domain FROM unified.concept_domains WHERE concept_id=$1 ORDER BY 1",
            (concept_id,), fetch_all=True) or []
        return [r["domain"] for r in rows]

    # ---- identity relations --------------------------------------------

    async def record(self, subject: str, relation: IdentityRelation,
                     object_surface: str, basis: str,
                     object_concept_id: Optional[str] = None) -> None:
        await self.db.execute_query(
            """INSERT INTO unified.concept_identity_relations
                   (subject_concept_id, relation_kind, object_concept_id,
                    object_surface, basis)
               VALUES ($1,$2,$3,$4,$5)
               ON CONFLICT (subject_concept_id, relation_kind, object_surface)
               DO UPDATE SET object_concept_id =
                   COALESCE(EXCLUDED.object_concept_id,
                            unified.concept_identity_relations.object_concept_id)""",
            (subject, relation.value, object_concept_id, object_surface, basis),
            commit=True)

    async def derive_qualified_name_relations(self) -> Dict[str, int]:
        """Relate every qualified concept name to its head.

        The head need not already exist: `accumulator` is not a learned concept,
        but `hydraulic_accumulator` SAME_AS it is still a true statement about
        naming, and it is what lets a query for `accumulator` reach the concept
        Torin actually holds.
        """
        rows = await self.db.execute_query(
            "SELECT concept_id, name, domain FROM unified.concepts ORDER BY concept_id",
            fetch_all=True) or []
        by_name: Dict[str, str] = {r["name"]: r["concept_id"] for r in rows}

        counts = {k.value: 0 for k in IdentityRelation}
        for r in rows:
            name = r["name"]
            parts = name.split("_")
            if len(parts) < 2:
                continue
            # Every proper suffix is a candidate head: flow_restriction -> restriction
            for i in range(1, len(parts)):
                head = "_".join(parts[i:])
                if len(head) < 3:
                    continue
                rel, basis = classify_qualified_name(name, r["domain"], head)
                if rel is IdentityRelation.UNKNOWN:
                    continue
                await self.record(r["concept_id"], rel, head, basis,
                                  object_concept_id=by_name.get(head))
                counts[rel.value] += 1
        return counts

    async def resolve_query(self, surface: str) -> List[Tuple[str, str]]:
        """Concepts a query for `surface` should reach, with the reason.

        SAME_AS resolves to the concept. SPECIALIZATION_OF is returned too but
        LABELLED, so a caller can decide whether a narrower concept may occupy
        the requested structural role -- a decision the identity layer must not
        make on its behalf.
        """
        s = (surface or "").strip().lower()
        out: List[Tuple[str, str]] = []

        exact = await self.db.execute_query(
            "SELECT concept_id FROM unified.concepts WHERE name=$1", (s,), fetch_all=True) or []
        out += [(r["concept_id"], "exact") for r in exact]

        al = await self.db.execute_query(
            "SELECT concept_id FROM unified.concept_aliases WHERE alias=$1", (s,), fetch_all=True) or []
        out += [(r["concept_id"], "alias") for r in al
                if r["concept_id"] not in {c for c, _ in out}]

        rel = await self.db.execute_query(
            """SELECT subject_concept_id, relation_kind FROM unified.concept_identity_relations
               WHERE object_surface=$1 AND relation_kind IN ('same_as','specialization_of')
               ORDER BY relation_kind""", (s,), fetch_all=True) or []
        out += [(r["subject_concept_id"], r["relation_kind"]) for r in rel
                if r["subject_concept_id"] not in {c for c, _ in out}]
        return out


__all__ = ["IdentityRelation", "ConceptIdentityService", "classify_qualified_name"]
