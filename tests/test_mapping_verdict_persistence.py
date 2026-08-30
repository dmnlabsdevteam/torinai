#!/usr/bin/env python3
"""Oracle: an ontological verdict survives the trip to storage and back.

The validator can be perfectly correct and the system still learn nothing, if
the verdict is dropped at the persistence boundary. That is what happened here:
`_persist_mapping` computed ACCEPTED/REJECTED correctly and then omitted
`verified` from its INSERT column list, so every row took the column default
(FALSE). Both readers -- `DomainRegistry._load_mappings` and
`UniversalDomainMaster._find_cross_domain_mappings` -- select
`verified IS NULL OR verified IS TRUE`, so an ACCEPTED mapping was stored as
refuted and became invisible to every consumer, including the registry's own
loader on restart.

Nothing raised. The in-memory dict held the right object, the function returned
True, and the counts looked plausible. The only visible symptom was a number
that disagreed with another number.

Three properties are asserted, because each fails independently:

  1. ROUND TRIP -- each of the three verdicts reads back as itself. A writer
     that omits the column passes any test that only checks "a row exists".
  2. TRI-STATE IS PRESERVED -- None must not collapse to False. "Never tested"
     and "tested and refuted" are different claims about the world, and only
     the second is evidence about the two domains.
  3. IDENTITY IS THE RELATIONSHIP -- re-proposing the same concept pair updates
     one row instead of appending a second under a fresh uuid. Otherwise a
     mapping accumulates one row per rediscovery, each with its own verdict,
     and a reader counts repetition as corroboration.
"""

from pathlib import Path

import pytest

DOMAIN_SRC = "verdict_test_source"
DOMAIN_TGT = "verdict_test_target"


def _load_env():
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[1] / ".env.production", override=True)


async def _db():
    from core.database import get_database_manager
    db = get_database_manager()
    if not getattr(db, "initialized", False):
        await db.initialize()
    return db


async def _clean(db):
    await db.execute_query(
        "DELETE FROM unified.domain_mappings WHERE source_domain = $1",
        (DOMAIN_SRC,), commit=True)


def _mapping(registry, verdict, source_concept="c_src", target_concept="c_tgt"):
    from core.domain.domain_types import CrossDomainMapping
    return CrossDomainMapping(
        mapping_id=registry._mapping_key(
            DOMAIN_SRC, DOMAIN_TGT, source_concept, target_concept, "similarity"),
        source_domain_id=DOMAIN_SRC,
        target_domain_id=DOMAIN_TGT,
        source_concept_id=source_concept,
        target_concept_id=target_concept,
        mapping_type="similarity",
        strength=0.7,
        confidence=0.56,
        validated=verdict,
        validation_score=0.42 if verdict is not None else 0.0,
    )


async def _verified_column(db, mapping_id):
    rows = await db.execute_query(
        "SELECT verified FROM unified.domain_mappings WHERE mapping_id = $1",
        (mapping_id,), fetch_all=True)
    assert rows, f"no row persisted for {mapping_id}"
    return rows[0]["verified"]


@pytest.mark.asyncio
async def test_each_verdict_round_trips_to_its_own_column():
    """ACCEPTED/REJECTED/UNJUDGED each read back as themselves, not as a default."""
    _load_env()
    from core.domain.domain_registry import DomainRegistry

    db = await _db()
    registry = DomainRegistry()
    await registry.initialize()
    await _clean(db)
    try:
        for verdict, label in ((True, "ACCEPTED"), (False, "REJECTED"), (None, "UNJUDGED")):
            mapping = _mapping(registry, verdict, target_concept=f"c_tgt_{label}")
            assert await registry.add_cross_domain_mapping(mapping) is True

            stored = await _verified_column(db, mapping.mapping_id)
            assert stored is verdict, (
                f"{label} mapping stored as verified={stored!r}. The verdict was "
                f"computed and then lost on the way to the table -- most likely "
                f"`verified` is missing from the INSERT column list, so the row "
                f"took the column default instead of the decision."
            )
    finally:
        await _clean(db)


@pytest.mark.asyncio
async def test_unjudged_does_not_collapse_into_refuted():
    """A mapping never tested must not be stored as one that failed the test."""
    _load_env()
    from core.domain.domain_registry import DomainRegistry

    db = await _db()
    registry = DomainRegistry()
    await registry.initialize()
    await _clean(db)
    try:
        mapping = _mapping(registry, None, target_concept="c_tgt_untested")
        await registry.add_cross_domain_mapping(mapping)

        # The readers' filter, stated exactly as they state it.
        visible = await db.execute_query(
            """SELECT mapping_id FROM unified.domain_mappings
               WHERE source_domain = $1 AND (verified IS NULL OR verified IS TRUE)""",
            (DOMAIN_SRC,), fetch_all=True)
        assert any(r["mapping_id"] == mapping.mapping_id for r in visible), (
            "an untested candidate was filtered out as though it had been "
            "refuted; NULL and FALSE have been conflated"
        )
    finally:
        await _clean(db)


@pytest.mark.asyncio
async def test_rediscovery_updates_one_row_rather_than_appending():
    """A mapping's identity is the relationship, not the moment it was found."""
    _load_env()
    from core.domain.domain_registry import DomainRegistry

    db = await _db()
    registry = DomainRegistry()
    await registry.initialize()
    await _clean(db)
    try:
        first = _mapping(registry, None, target_concept="c_tgt_repeat")
        await registry.add_cross_domain_mapping(first)

        # Same relationship, later judged. Not a second mapping.
        second = _mapping(registry, True, target_concept="c_tgt_repeat")
        assert second.mapping_id == first.mapping_id, (
            "the same concept pair produced two different ids, so rediscovery "
            "can never update the earlier row"
        )
        await registry.add_cross_domain_mapping(second)

        rows = await db.execute_query(
            """SELECT mapping_id, verified FROM unified.domain_mappings
               WHERE source_domain = $1 AND target_concept = $2""",
            (DOMAIN_SRC, "c_tgt_repeat"), fetch_all=True)
        assert len(rows) == 1, (
            f"{len(rows)} rows for one relationship; repetition would be counted "
            f"as independent corroboration"
        )
        assert rows[0]["verified"] is True, (
            "the later verdict did not overwrite the earlier unjudged state"
        )
    finally:
        await _clean(db)


@pytest.mark.asyncio
async def test_writers_supply_every_mandatory_column():
    """A NOT NULL column with no default must be written by every writer.

    `_persist_transfer` omitted `concept_type`, so every insert raised
    NotNullViolation, which `create_knowledge_transfer` caught and returned as
    False. The table stayed empty while callers were told the transfer worked.
    This checks the contract structurally rather than waiting for the exception
    to be swallowed again.
    """
    _load_env()
    import inspect
    import re
    from core.domain import domain_registry as dr

    db = await _db()
    for table, writer in (("domain_mappings", dr.DomainRegistry._persist_mapping),
                          ("knowledge_transfers", dr.DomainRegistry._persist_transfer)):
        required = await db.execute_query(
            """SELECT column_name FROM information_schema.columns
               WHERE table_schema = 'unified' AND table_name = $1
                 AND is_nullable = 'NO' AND column_default IS NULL""",
            (table,), fetch_all=True)

        # Parse the INSERT's own column list. Searching the whole function body
        # for the column NAME is not the same check: this docstring names
        # `concept_type`, so a substring test passed while the INSERT had
        # dropped the column -- the test reproducing, on itself, the exact
        # confusion between a thing and a mention of it that it exists to catch.
        source = inspect.getsource(writer)
        stmt = re.search(rf"INSERT\s+INTO\s+unified\.{table}\s*\((.*?)\)\s*VALUES\s*\((.*?)\)",
                         source, re.S | re.I)
        assert stmt, f"{writer.__qualname__} has no INSERT INTO unified.{table}"
        written = {c.strip() for c in stmt.group(1).split(",") if c.strip()}
        placeholders = [v.strip() for v in stmt.group(2).split(",") if v.strip()]

        missing = sorted(r["column_name"] for r in required
                         if r["column_name"] not in written)
        assert not missing, (
            f"{writer.__qualname__}'s INSERT column list omits {missing}, which "
            f"{table} declares NOT NULL with no default; every insert it attempts "
            f"raises NotNullViolation"
        )
        assert len(written) == len(placeholders), (
            f"{writer.__qualname__} lists {len(written)} columns but "
            f"{len(placeholders)} values; the row would be built from "
            f"misaligned parameters"
        )
