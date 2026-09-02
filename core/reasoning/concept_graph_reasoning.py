#!/usr/bin/env python3
"""Reason over the REAL concept graph with the typed relation algebra.

`unified.concept_relations` stores the relation as the canonical name of a
`SemanticRelation` (written by the ingress now that reading is typed). This loads
the relevant subgraph, maps those names back to types, and answers a query
through `relation_algebra` -- so inference over stored knowledge is
type-licensed, never naive reachability.

A relation string that is NOT a known type is skipped, not coerced: a legacy or
unrecognised edge licenses no inference rather than a wrong one.
"""

from __future__ import annotations

import logging
from typing import FrozenSet, List, Sequence

from core.reasoning.relation_algebra import Answer, Edge, answer, derive_from
from core.semantics.relation_types import SemanticRelation

logger = logging.getLogger(__name__)

_BY_VALUE = {r.value: r for r in SemanticRelation}

_SUBGRAPH_SQL = (
    "SELECT c1.name AS subj, cr.relation AS rel, c2.name AS obj, cr.polarity AS pol "
    "FROM unified.concept_relations cr "
    "JOIN unified.concepts c1 ON cr.source_concept_id = c1.concept_id "
    "JOIN unified.concepts c2 ON cr.target_concept_id = c2.concept_id "
    "WHERE c1.name = ANY($1)")


async def load_subgraph(db, roots: Sequence[str], *, max_hops: int = 6
                        ) -> List[Edge]:
    """Typed edges reachable from `roots`, breadth-first to `max_hops`. Only edges
    whose relation names a known type are returned; the rest are skipped so an
    untyped edge cannot be walked to a conclusion."""
    edges: List[Edge] = []
    seen_nodes: set = set()
    frontier = [str(r) for r in roots]
    for _ in range(max_hops):
        frontier = [n for n in frontier if n not in seen_nodes]
        if not frontier:
            break
        rows = await db.execute_query(_SUBGRAPH_SQL, (frontier,), fetch_all=True) or []
        seen_nodes.update(frontier)
        nxt: List[str] = []
        for row in rows:
            # The ingress stores the relation with spaces ("has part"); the type
            # value is underscore-form ("has_part"). Map back before typing.
            rel = _BY_VALUE.get(str(row["rel"]).strip().replace(" ", "_"))
            if rel is None:
                continue                       # untyped/legacy edge: no inference
            # A denied edge is not a positive fact; skip it here (negatives are
            # passed separately to `answer`).
            if str(row.get("pol") or "affirms") == "denies":
                continue
            edges.append(Edge(row["subj"], rel, row["obj"]))
            if row["obj"] not in seen_nodes:
                nxt.append(row["obj"])
        frontier = nxt
    return edges


async def answer_over_graph(db, subject: str, relation: SemanticRelation, obj: str,
                            *, context_licenses: FrozenSet[SemanticRelation] = frozenset(),
                            max_hops: int = 6) -> Answer:
    """Answer `subject relation obj` against the live concept graph, open-world.

    Query terms are normalised the SAME way the ingress normalised them on the
    way in (plural->singular, etc.), so "flippers" matches the stored "flipper".
    Without this a query would miss its own taught fact on a surface variation."""
    from core.semantics.cognitive_ingress import normalize_term
    subject, obj = normalize_term(subject), normalize_term(obj)
    edges = await load_subgraph(db, [subject], max_hops=max_hops)
    return answer(subject, relation, obj, edges, context_licenses=context_licenses)


__all__ = ["load_subgraph", "answer_over_graph"]
