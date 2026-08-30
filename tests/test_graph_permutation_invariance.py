#!/usr/bin/env python3
"""Oracle: the learned graph does not depend on ingestion order.

A concept can be named as a relation target before it has been learned, which
leaves a dangling edge. `relink_dangling_edges()` attaches it once the target
arrives. If that failed, the graph's topology would depend on which research
source happened to complete first — and any later analogy difference could be
caused by scheduling rather than by reasoning.

That matters more once asynchronous producers are involved: two runs over one
corpus would build different structures and the positive control would be
measuring the scheduler.

Extraction here is DETERMINISTIC on purpose. A generative extractor proposes
different labels each pass, which would make an order effect indistinguishable
from model variance — the same conflation the identity oracles were split to
avoid.
"""

import random

import pytest

DOMAIN = "permtest_domain"

#: Deliberately ordered so that EVERY envelope names at least one target that
#: is only learned later in this sequence. Ingested in this order the graph is
#: built almost entirely from dangling edges that must be relinked; reversed,
#: most targets already exist. If relinking is broken the two disagree.
#: Labels are PREFIXED because concept identity resolves a label across every
#: domain, by design -- one `electrolyte` observed twice is one concept. Bare
#: `alpha` collided with `reasoning:alpha`, a real tool parameter projected from
#: the registry, so the first envelope's target resolved immediately and the
#: fixture stopped exercising relinking at all. The precondition assertion below
#: caught it, which is what it is for.
CORPUS = [
    ("perm_ev_1", "alpha drives beta", [
        ("permtest_alpha", [("drives", "permtest_beta"), ("part_of", "permtest_delta")]),
    ]),
    ("perm_ev_2", "beta opposes gamma", [
        ("permtest_beta", [("opposes", "permtest_gamma")]),
    ]),
    ("perm_ev_3", "gamma stored in delta", [
        ("permtest_gamma", [("stored_in", "permtest_delta")]),
    ]),
    ("perm_ev_4", "delta contains alpha", [
        ("permtest_delta", [("contains", "permtest_alpha"), ("contains", "permtest_epsilon")]),
    ]),
]


class _DeterministicExtractor:
    name = "perm_probe"
    last_failure = None

    def __init__(self, concepts):
        self._concepts = concepts

    def extract(self, envelope):
        from core.domain.concept_ingestion import ConceptCandidate
        from core.domain.domain_types import ConceptType
        return [
            ConceptCandidate(
                label=label, concept_kind=ConceptType.ENTITY,
                domain_candidates=(DOMAIN,), evidence_ids=(envelope.evidence_id,),
                extraction_confidence=1.0, extractor=self.name,
                description=f"permutation probe {label}",
                attributes={"probe": label},
                relationships=tuple(rels),
            )
            for label, rels in self._concepts
        ]


async def _clean(db):
    await db.execute_query(
        "DELETE FROM unified.concept_relations WHERE source_concept_id LIKE $1",
        (f"{DOMAIN}:%",), commit=True)
    await db.execute_query(
        "DELETE FROM unified.concept_evidence WHERE concept_id LIKE $1",
        (f"{DOMAIN}:%",), commit=True)
    await db.execute_query(
        "DELETE FROM unified.concept_aliases WHERE concept_id LIKE $1",
        (f"{DOMAIN}:%",), commit=True)
    await db.execute_query(
        "DELETE FROM unified.concepts WHERE domain = $1", (DOMAIN,), commit=True)
    await db.execute_query(
        "DELETE FROM unified.evidence_envelopes WHERE evidence_id LIKE 'perm_ev_%'",
        commit=True)


async def _snapshot(db):
    """Everything that must be order-independent."""
    nodes = await db.execute_query(
        "SELECT concept_id, name FROM unified.concepts WHERE domain = $1 "
        "ORDER BY concept_id", (DOMAIN,), fetch_all=True) or []
    edges = await db.execute_query(
        "SELECT source_concept_id, relation, target_concept_id, target_surface "
        "FROM unified.concept_relations WHERE source_concept_id LIKE $1 "
        "ORDER BY 1,2,3,4", (f"{DOMAIN}:%",), fetch_all=True) or []
    roots = await db.execute_query(
        "SELECT concept_id, root_evidence_id FROM unified.concept_evidence "
        "WHERE concept_id LIKE $1 ORDER BY 1,2", (f"{DOMAIN}:%",), fetch_all=True) or []
    return {
        "nodes": {r["concept_id"] for r in nodes},
        "resolved_edges": {
            (r["source_concept_id"], r["relation"], r["target_concept_id"])
            for r in edges if r["target_concept_id"]
        },
        "dangling_surfaces": {
            (r["source_concept_id"], r["relation"], r["target_surface"])
            for r in edges if not r["target_concept_id"]
        },
        "roots": {(r["concept_id"], r["root_evidence_id"]) for r in roots},
    }


async def _ingest(order):
    from core.domain.concept_ingestion import (
        ConceptIngestionService, EvidenceEnvelope, EvidenceSourceType)
    from core.database import get_database_manager

    db = get_database_manager()
    if not getattr(db, "initialized", False):
        await db.initialize()

    svc = ConceptIngestionService(db)
    for eid, text, concepts in order:
        svc.extractors = []
        svc.register_extractor(_DeterministicExtractor(concepts))
        await svc.ingest(EvidenceEnvelope(
            evidence_id=eid, source_type=EvidenceSourceType.TOOL_OBSERVATION,
            source_id=f"perm://{eid}", producer="permutation_oracle", content=text,
        ))
    return await _snapshot(db)


@pytest.mark.asyncio
async def test_graph_is_invariant_to_ingestion_order():
    from dotenv import load_dotenv
    from pathlib import Path
    load_dotenv(Path(__file__).resolve().parents[1] / ".env.production", override=True)
    from core.database import get_database_manager

    db = get_database_manager()
    if not getattr(db, "initialized", False):
        await db.initialize()

    try:
        await _clean(db)
        forward = await _ingest(CORPUS)

        await _clean(db)
        reverse = await _ingest(list(reversed(CORPUS)))

        await _clean(db)
        shuffled = list(CORPUS)
        random.Random(20260815).shuffle(shuffled)
        randomised = await _ingest(shuffled)

        assert forward["nodes"], "oracle is vacuous: no nodes were created"
        assert forward["resolved_edges"], (
            "oracle is vacuous: no edge resolved, so relinking is untested")

        for name, other in (("reversed", reverse), ("shuffled", randomised)):
            assert other["nodes"] == forward["nodes"], (
                f"{name} order produced different nodes: "
                f"{other['nodes'] ^ forward['nodes']}")
            assert other["resolved_edges"] == forward["resolved_edges"], (
                f"{name} order produced different resolved edges: "
                f"{other['resolved_edges'] ^ forward['resolved_edges']} — graph "
                f"topology depends on which source completed first")
            assert other["dangling_surfaces"] == forward["dangling_surfaces"], (
                f"{name} order left a different dangling set: "
                f"{other['dangling_surfaces'] ^ forward['dangling_surfaces']}")
            assert other["roots"] == forward["roots"], (
                f"{name} order produced different evidence roots")
    finally:
        await _clean(db)


@pytest.mark.asyncio
async def test_forward_order_actually_exercises_relinking():
    """Guard against a vacuous invariance result.

    If every target happened to exist when first named, the graph would be
    order-invariant trivially and this suite would prove nothing about
    relink_dangling_edges.
    """
    from dotenv import load_dotenv
    from pathlib import Path
    load_dotenv(Path(__file__).resolve().parents[1] / ".env.production", override=True)
    from core.database import get_database_manager
    from core.domain.concept_ingestion import (
        ConceptIngestionService, EvidenceEnvelope, EvidenceSourceType)

    db = get_database_manager()
    if not getattr(db, "initialized", False):
        await db.initialize()

    try:
        await _clean(db)
        svc = ConceptIngestionService(db)
        eid, text, concepts = CORPUS[0]
        svc.extractors = []
        svc.register_extractor(_DeterministicExtractor(concepts))
        await svc.ingest(EvidenceEnvelope(
            evidence_id=eid, source_type=EvidenceSourceType.TOOL_OBSERVATION,
            source_id=f"perm://{eid}", producer="permutation_oracle", content=text))

        snap = await _snapshot(db)
        assert snap["dangling_surfaces"], (
            "the first envelope must leave dangling edges, otherwise the "
            "invariance test never exercises relinking")

        # Now the rest arrive; the dangling edges must attach.
        for e2 in CORPUS[1:]:
            svc.extractors = []
            svc.register_extractor(_DeterministicExtractor(e2[2]))
            await svc.ingest(EvidenceEnvelope(
                evidence_id=e2[0], source_type=EvidenceSourceType.TOOL_OBSERVATION,
                source_id=f"perm://{e2[0]}", producer="permutation_oracle",
                content=e2[1]))

        after = await _snapshot(db)
        assert len(after["resolved_edges"]) > len(snap["resolved_edges"]), (
            "edges dangling at first mention never attached once their target "
            "was learned")
    finally:
        await _clean(db)
