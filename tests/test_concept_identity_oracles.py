#!/usr/bin/env python3
"""Concept identity oracles.

Two DIFFERENT claims, deliberately not measured by one test:

  PERSISTENCE IDEMPOTENCY  (deterministic, absolute)
      same envelope + same candidates
      -> no concept growth, no evidence-link growth, no root growth

  INTERPRETATION STABILITY (non-deterministic extractor permitted)
      same evidence, independently re-extracted
      -> the ROOT SET is unchanged
      -> genuinely distinct proposals may add concepts
      -> but no concept gains corroboration

Conflating them produces a misleading result in both directions: a generative
extractor proposing one new label makes a correct persistence layer look broken,
and row-count equality can hide a root set that has quietly changed underneath.

The invariant that spans both is stronger than "row count stays fixed":

    Reinterpreting an observation may change Torin's semantic interpretation
    of it. It cannot manufacture additional independent evidence.
"""

import asyncio
import os
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


def _load_env():
    from dotenv import load_dotenv
    load_dotenv(REPO / ".env.production", override=True)


async def _db():
    _load_env()
    from core.database import get_database_manager
    db = get_database_manager()
    if not getattr(db, "initialized", False):
        await db.initialize()
    return db


async def _state(db):
    """Everything the oracles assert on — sets, not just counts."""
    concepts = await db.execute_query(
        "SELECT concept_id, epistemic_status, root_evidence_count "
        "FROM unified.concepts ORDER BY concept_id", fetch_all=True) or []
    links = await db.execute_query(
        "SELECT concept_id, root_evidence_id FROM unified.concept_evidence "
        "ORDER BY concept_id, root_evidence_id", fetch_all=True) or []
    roots = await db.execute_query(
        "SELECT DISTINCT root_evidence_id FROM unified.concept_evidence "
        "ORDER BY root_evidence_id", fetch_all=True) or []
    return {
        "concepts": {r["concept_id"]: (r["epistemic_status"], r["root_evidence_count"])
                     for r in concepts},
        "links": {(r["concept_id"], r["root_evidence_id"]) for r in links},
        "roots": {r["root_evidence_id"] for r in roots},
    }


class _FixedExtractor:
    """Deterministic extractor. Isolates persistence from interpretation."""

    name = "fixed_probe"

    def __init__(self, candidates):
        self._candidates = candidates

    def extract(self, envelope):
        from core.domain.concept_ingestion import ConceptCandidate
        from core.domain.domain_types import ConceptType
        return [
            ConceptCandidate(
                label=label, concept_kind=ConceptType.ENTITY,
                domain_candidates=(domain,), evidence_ids=(envelope.evidence_id,),
                extraction_confidence=1.0, extractor=self.name,
                description=f"probe concept {label}",
            )
            for label, domain in self._candidates
        ]


#: The database manager is a process singleton whose asyncpg pool is bound to
#: the event loop that created it. pytest-asyncio's default is a fresh loop per
#: test, so the second async test reused a pool from a dead loop and failed with
#: "another operation is in progress" — a harness artefact, not a defect in the
#: code under test. One loop for the module removes it.
pytestmark = pytest.mark.asyncio(loop_scope="session")


@pytest.mark.asyncio
async def test_persistence_idempotency_is_absolute():
    """Same envelope, same candidates, three times -> byte-identical state.

    No generative extractor is registered, so any change here is a persistence
    defect and cannot be blamed on the model.
    """
    from core.domain.concept_ingestion import (
        ConceptIngestionService, EvidenceEnvelope, EvidenceSourceType)

    db = await _db()
    svc = ConceptIngestionService(db)          # not the singleton: no shared extractors
    svc.extractors = []
    svc.register_extractor(_FixedExtractor([
        ("oracle probe alpha", "oracle_domain"),
        ("oracle probe beta", "oracle_domain"),
    ]))

    env = EvidenceEnvelope(
        evidence_id="oracle_persist_root",
        source_type=EvidenceSourceType.TOOL_OBSERVATION,
        source_id="oracle://persistence", producer="oracle",
        content="A deterministic observation used to isolate persistence.",
    )

    try:
        await svc.ingest(env)
        first = await _state(db)
        assert first["concepts"], "probe produced no concepts; oracle is vacuous"

        for _ in range(2):
            await svc.ingest(env)
            again = await _state(db)
            assert again["concepts"] == first["concepts"], (
                f"replay changed concepts: {set(again['concepts']) ^ set(first['concepts'])}")
            assert again["links"] == first["links"], "replay changed evidence links"
            assert again["roots"] == first["roots"], "replay changed the root set"
    finally:
        await db.execute_query(
            "DELETE FROM unified.concept_evidence WHERE concept_id LIKE 'oracle_domain:%'", commit=True)
        await db.execute_query(
            "DELETE FROM unified.concept_aliases WHERE concept_id LIKE 'oracle_domain:%'", commit=True)
        await db.execute_query(
            "DELETE FROM unified.concepts WHERE domain = 'oracle_domain'", commit=True)
        await db.execute_query(
            "DELETE FROM unified.evidence_envelopes WHERE evidence_id = 'oracle_persist_root'", commit=True)


@pytest.mark.asyncio
async def test_reinterpretation_cannot_add_roots():
    """A DIFFERENT extraction of the same evidence adds no corroboration.

    Simulates a non-deterministic extractor by proposing a new label on the
    second pass. The new concept is legitimate; what must not happen is any
    change to the root set, or any existing concept gaining a root.
    """
    from core.domain.concept_ingestion import (
        ConceptIngestionService, EvidenceEnvelope, EvidenceSourceType)

    db = await _db()
    svc = ConceptIngestionService(db)
    svc.extractors = []
    svc.register_extractor(_FixedExtractor([("oracle probe gamma", "oracle_domain")]))

    env = EvidenceEnvelope(
        evidence_id="oracle_reinterp_root",
        source_type=EvidenceSourceType.TOOL_OBSERVATION,
        source_id="oracle://reinterpretation", producer="oracle",
        content="One observation, read twice, understood differently.",
    )

    try:
        await svc.ingest(env)
        before = await _state(db)

        # Second pass: the extractor now proposes an ADDITIONAL, distinct concept.
        svc.extractors = []
        svc.register_extractor(_FixedExtractor([
            ("oracle probe gamma", "oracle_domain"),
            ("oracle probe delta", "oracle_domain"),
        ]))
        await svc.ingest(env)
        after = await _state(db)

        assert after["roots"] == before["roots"], (
            f"reinterpretation changed the root set: "
            f"{after['roots'] ^ before['roots']} — an observation read again "
            f"became additional independent evidence")

        for cid, (_status, roots) in before["concepts"].items():
            assert after["concepts"][cid][1] == roots, (
                f"{cid} gained corroboration from re-reading the same evidence: "
                f"{roots} -> {after['concepts'][cid][1]}")

        assert len(after["concepts"]) >= len(before["concepts"]), (
            "a genuinely new proposal should be representable")
    finally:
        await db.execute_query(
            "DELETE FROM unified.concept_evidence WHERE concept_id LIKE 'oracle_domain:%'", commit=True)
        await db.execute_query(
            "DELETE FROM unified.concept_aliases WHERE concept_id LIKE 'oracle_domain:%'", commit=True)
        await db.execute_query(
            "DELETE FROM unified.concepts WHERE domain = 'oracle_domain'", commit=True)
        await db.execute_query(
            "DELETE FROM unified.evidence_envelopes WHERE evidence_id = 'oracle_reinterp_root'", commit=True)


def test_extractors_are_registered_not_appended():
    """Production ownership path, and it must be idempotent by name."""
    from core.domain.concept_ingestion import ConceptIngestionService, ConceptExtractor

    svc = ConceptIngestionService(db_manager=object())
    svc.extractors = []
    assert svc.register_extractor(ConceptExtractor()) is True
    assert svc.register_extractor(ConceptExtractor()) is False, (
        "a singleton service must not accumulate duplicate extractors")
    assert len(svc.extractors) == 1

    class Anonymous:
        name = ""

    with pytest.raises(ValueError):
        svc.register_extractor(Anonymous())


@pytest.mark.asyncio
async def test_acronym_identity_merges_and_never_guesses():
    """Acronym resolution is exact-initials only.

    Embedding similarity was tried here and is actively wrong on short labels.
    Measured on the real encoder:

        ysz ~ yttria stabilized zirconia              0.33   SAME referent
        oxygen vacancy ~ oxygen vacancy formation     0.94   DIFFERENT referents

    A substring embeds near its superset while an acronym embeds nowhere near
    its expansion, so every threshold admits the false merges first. This test
    pins the deterministic replacement, including what it must REFUSE to merge.
    """
    from core.domain.concept_ingestion import ConceptIngestionService

    db = await _db()
    svc = ConceptIngestionService(db)

    assert svc._acronym_of("yttria_stabilized_zirconia") == "ysz"
    assert svc._acronym_of("solid_oxide_fuel_cell") == "sofc"
    assert svc._acronym_of("cathode") is None, "a single word has no acronym"

    # 'proton_conducting_ceramic_fuel_cell' has initials 'pccfc', not 'pcfc'.
    # A near miss must NOT resolve — guessing is how cathode becomes anode.
    assert svc._acronym_of("proton_conducting_ceramic_fuel_cell") == "pccfc"

    try:
        await db.execute_query(
            """INSERT INTO unified.concepts
                   (concept_id, name, domain, description, concept_kind,
                    epistemic_status, root_evidence_count, created_at)
               VALUES ('oracle_domain:yttria_stabilized_zirconia',
                       'yttria_stabilized_zirconia','oracle_domain','',
                       'entity','OBSERVED',1, NOW())
               ON CONFLICT (concept_id) DO NOTHING""", commit=True)

        # Resolve to A registered expansion, not specifically the fixture: the
        # live store may already hold a real one (it does —
        # materials_science:yttria_stabilised_zirconia, learned from evidence),
        # and pinning the test to its own row would fail on correct behaviour.
        # WITH corroboration -- same domain as the expansion.
        hit = await svc._acronym_match("ysz", proposed_domain="oracle_domain")
        assert hit is not None, "an acronym must resolve to a registered expansion"

        # WITHOUT corroboration it must REFUSE. Initials alone are a proposal,
        # not evidence of sameness: `in` was fused with `include_number` on
        # i-n. A false merge is unrecoverable; a missed match is only UNKNOWN.
        assert await svc._acronym_match("ysz", proposed_domain="unrelated_field") is None, (
            "initials alone must not establish identity across domains")
        assert svc._acronym_of(hit.split(":", 1)[1]) == "ysz", (
            f"{hit} is not an expansion of 'ysz'")

        # And the reverse direction.
        # Reverse direction: a multi-word name resolving to a registered acronym.
        # 'zzq' cannot collide with learned data.
        await db.execute_query(
            """INSERT INTO unified.concepts
                   (concept_id, name, domain, description, concept_kind,
                    epistemic_status, root_evidence_count, created_at)
               VALUES ('oracle_domain:zzq','zzq','oracle_domain','',
                       'entity','OBSERVED',1, NOW())
               ON CONFLICT (concept_id) DO NOTHING""", commit=True)
        # The reverse direction, also corroborated by domain.
        assert await svc._acronym_match(
            "zeta_zonal_quench", proposed_domain="oracle_domain") == "oracle_domain:zzq"
        assert await svc._acronym_match(
            "zeta_zonal_quench", proposed_domain="somewhere_else") is None, (
            "an expansion must not claim an acronym in an unrelated domain")

        # Must refuse: not an acronym relation at all.
        assert await svc._acronym_match("anode") is None
        assert await svc._acronym_match("oxygen_vacancy_formation") is None
    finally:
        await db.execute_query(
            "DELETE FROM unified.concepts WHERE domain = 'oracle_domain'", commit=True)


def test_canonical_labels_merge_and_split_correctly():
    """Lexical identity, measured against variants seen in live extraction."""
    from core.domain.concept_ingestion import ConceptResolver

    r = ConceptResolver()
    must_merge = [
        ("pcfc", "pcfcs"),
        ("lithium_iron_phosphate", "lithium_iron_phosphate_batteries"),
        ("lifepo4", "introduction_of_lifepo4"),
        ("phosphoric_acid_fuel_cells", "phosphoric_acid_fuel_cells_pafc"),
        ("cathode", "cathode_material"),
        ("safety_characteristics", "safety_characteristic"),
        ("gas", "gases"), ("analysis", "analyses"), ("matrix", "matrices"),
    ]
    must_split = [
        ("electrolyte", "solid_oxide_electrolyte"),
        ("cathode", "anode"),
        ("oxygen_vacancy", "oxygen_vacancy_formation"),
        ("proton_diffusion", "ionic_conductivity"),
    ]
    for a, b in must_merge:
        assert r.canonical_label(a) == r.canonical_label(b), (
            f"{a!r} and {b!r} name one thing but canonicalise apart")
    for a, b in must_split:
        assert r.canonical_label(a) != r.canonical_label(b), (
            f"{a!r} and {b!r} are different things but canonicalise together")

    # Singular endings the general -s rule destroys. Both were found in live
    # data: 'synthesis' became 'synthesi', and 'physics' became 'physic',
    # which put physics concepts in a domain that does not exist.
    for w in ("synthesis", "hypothesis", "basis", "analysis",
              "physics", "mathematics", "economics", "statistics",
              "mechanics", "electronics", "ceramics"):
        assert r.canonical_label(w) == w, f"{w} must not be singularised"

    # ...but -ics that IS a plural must still reduce. A blanket -ics rule
    # cannot tell these apart, which is why the mass nouns are an explicit set.
    assert r.canonical_label("characteristics") == r.canonical_label("characteristic")
    assert r.canonical_label("metrics") == r.canonical_label("metric")
