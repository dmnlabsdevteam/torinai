#!/usr/bin/env python3
"""Guarded, transactional purge of the LEGACY fixture concepts.

Run ONCE, before the first production concept ingestion, to establish a clean
slate: designed ontology and domain taxonomy present, learned semantic knowledge
absent.

THIS SCRIPT REFUSES TO RUN unless the database still looks like the pre-state it
was written for. An earlier version of this cleanup was a sequence of individual
DELETEs with no precondition; rerunning it six months from now would silently
erase everything Torin had learned. The guard below is the difference between a
one-time migration and a loaded gun.

Ordering and atomicity:
  * derived state (analogies, mappings, transfers) before source state (concepts)
  * one transaction — a failure halfway through must leave the substrate intact
  * export before delete, always

Usage:
    python scripts/purge_legacy_fixture_concepts.py            # dry run
    python scripts/purge_legacy_fixture_concepts.py --execute  # performs it
"""

import argparse
import asyncio
import json
import logging
import sys
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("purge")

#: FROZEN. These values describe the ONE historical pre-state this script is
#: authorized to destroy: the 13 fixture concepts written by the deleted
#: AnalogyDiscovery._load_sample_data, before any concept had been learned.
#:
#: DO NOT update these to match a database that has moved on. Editing them to
#: make today's substrate "eligible" converts a narrowly scoped one-time
#: migration into a learned-state deletion tool. If a different state genuinely
#: needs purging, that is a different script with its own authorization.
EXPECTED = {
    "fixture_concepts": 13,
    "provenanced_concepts": 0,     # nothing learned through ingestion yet
    "concept_evidence": 0,
    "evidence_envelopes": 0,
}

#: Deleted in this order. Derived state first so nothing is ever orphaned.
PURGE_ORDER = [
    "unified.analogies",
    "unified.domain_mappings",
    "unified.knowledge_transfers",
    "unified.concept_evidence",
    "unified.concept_aliases",
    "unified.concepts",
    "unified.evidence_envelopes",
]

#: Untouched. These are representation structure, not learned content.
PRESERVED = ["unified.domains"]


def _json(o):
    if isinstance(o, (datetime, date)):
        return o.isoformat()
    if isinstance(o, Decimal):
        return float(o)
    return str(o)


async def observe(db):
    """Measure the current state without changing it."""
    async def n(table):
        rows = await db.execute_query(f"SELECT count(*) n FROM {table}", fetch_all=True)
        return int(rows[0]["n"]) if rows else 0

    state = {t.split(".", 1)[1]: await n(t) for t in PURGE_ORDER + PRESERVED}
    prov = await db.execute_query(
        "SELECT count(*) n FROM unified.concepts WHERE provenance IS NOT NULL",
        fetch_all=True)
    state["provenanced_concepts"] = int(prov[0]["n"]) if prov else 0
    state["fixture_concepts"] = state["concepts"] - state["provenanced_concepts"]
    return state


def check_precondition(state):
    """Return a list of reasons the purge must not run. Empty means proceed."""
    problems = []
    for key, want in EXPECTED.items():
        got = state.get(key)
        if got != want:
            problems.append(f"{key}: expected {want}, found {got}")
    if state["provenanced_concepts"] > 0:
        problems.append(
            f"{state['provenanced_concepts']} concept(s) carry provenance — these "
            f"were LEARNED through ingestion and must never be purged by this script"
        )
    return problems


async def dependency_census(db):
    """Untyped references a foreign-key query would miss."""
    ids = [r["concept_id"] for r in (await db.execute_query(
        "SELECT concept_id FROM unified.concepts", fetch_all=True) or [])]
    ids += [r["analogy_id"] for r in (await db.execute_query(
        "SELECT analogy_id FROM unified.analogies", fetch_all=True) or [])]
    if not ids:
        return []

    cols = await db.execute_query(
        """SELECT table_name t, column_name c FROM information_schema.columns
           WHERE table_schema='unified'
             AND data_type IN ('text','character varying','jsonb','ARRAY')""",
        fetch_all=True) or []

    hits, scanned = [], 0
    for col in cols:
        t, c = col["t"], col["c"]
        if f"unified.{t}" in PURGE_ORDER:
            continue
        scanned += 1
        try:
            rows = await db.execute_query(
                f"SELECT count(*) n FROM unified.{t} WHERE EXISTS "
                f"(SELECT 1 FROM unnest($1::text[]) k WHERE {c}::text LIKE '%'||k||'%')",
                (ids,), fetch_all=True)
            if rows and int(rows[0]["n"]):
                hits.append((f"unified.{t}.{c}", int(rows[0]["n"])))
        except Exception:
            # A column type that cannot be cast is not a reference.
            pass
    logger.info("Scanned %d candidate columns outside the purge set", scanned)
    return hits


async def export(db, out: Path):
    out.mkdir(parents=True, exist_ok=True)
    for table in PURGE_ORDER:
        rows = await db.execute_query(f"SELECT * FROM {table}", fetch_all=True) or []
        name = table.split(".", 1)[1]
        (out / f"{name}.json").write_text(
            json.dumps([dict(r) for r in rows], indent=2, default=_json))
        logger.info("exported %-28s %4d rows", table, len(rows))


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--execute", action="store_true",
                    help="perform the purge; without this the script only reports")
    ap.add_argument("--out", default=str(REPO / "archive" / "fixture_purge"),
                    help="export directory")
    args = ap.parse_args()

    from dotenv import load_dotenv
    load_dotenv(REPO / ".env.production", override=True)
    from core.database import get_database_manager

    db = get_database_manager()
    await db.initialize()

    state = await observe(db)
    logger.info("current state: %s", state)

    problems = check_precondition(state)
    if problems:
        logger.error("PRECONDITION FAILED — refusing to purge:")
        for p in problems:
            logger.error("   %s", p)
        logger.error("This script targets one specific pre-state. If the intent is "
                     "to purge a different state, update EXPECTED deliberately.")
        return 1

    hits = await dependency_census(db)
    if hits:
        logger.error("untyped references found outside the purge set: %s", hits)
        logger.error("Audit these before deleting; refusing to cascade blindly.")
        return 1
    logger.info("dependency census: no untyped references outside the purge set")

    if not args.execute:
        logger.info("DRY RUN — precondition and census pass. Re-run with --execute.")
        return 0

    await export(db, Path(args.out))

    # ONE transaction. A failure halfway must leave the substrate intact.
    pool = getattr(db, "pool", None)
    if pool is None:
        logger.error("no connection pool available; refusing a non-transactional purge")
        return 1

    async with pool.acquire() as conn:
        async with conn.transaction():
            for table in PURGE_ORDER:
                deleted = await conn.execute(f"DELETE FROM {table}")
                logger.info("deleted from %-28s %s", table, deleted)

    after = await observe(db)
    logger.info("post-purge state: %s", after)
    if any(after[t.split('.', 1)[1]] for t in PURGE_ORDER):
        logger.error("purge did not empty every target table")
        return 1
    if after["domains"] != state["domains"]:
        logger.error("domain taxonomy was modified; it must be preserved")
        return 1
    logger.info("clean slate established; domain taxonomy preserved (%d domains)",
                after["domains"])
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
