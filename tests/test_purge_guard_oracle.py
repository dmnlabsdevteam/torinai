#!/usr/bin/env python3
"""Oracle: the legacy purge refuses to touch learned knowledge.

A nonzero exit is NOT proof the guard worked. A database outage, an import
error, a syntax error or a missing environment variable all exit nonzero too,
and any of them would satisfy an oracle that only checks "failed". The guard is
proven only by a nonzero exit carrying the SPECIFIC diagnostic that names the
protected state.

Written as a test rather than a shell snippet on purpose. The previous harness
used ${PIPESTATUS[0]}, which is Bash-only and expands to nothing under zsh — a
measurement instrument whose correctness depended on which shell ran it.
"""

import importlib.util
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "purge_legacy_fixture_concepts.py"
PYTHON = REPO / "venv_torin" / "bin" / "python"


def _dry_run():
    proc = subprocess.run(
        [str(PYTHON), str(SCRIPT)],
        cwd=str(REPO), capture_output=True, text=True, timeout=600,
    )
    return proc.returncode, proc.stdout + proc.stderr


def test_script_is_named_for_its_scope():
    assert SCRIPT.exists(), f"{SCRIPT} is missing"
    assert "legacy" in SCRIPT.name, (
        "the name must scope it to the legacy fixtures; a generic 'cleanup' "
        "name invites it being pointed at learned state"
    )


def test_expected_pre_state_is_frozen():
    spec = importlib.util.spec_from_file_location("purge_legacy", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    assert mod.EXPECTED == {
        "fixture_concepts": 13,
        "provenanced_concepts": 0,
        "concept_evidence": 0,
        "evidence_envelopes": 0,
    }, (
        "EXPECTED has been edited. These values authorise destruction of ONE "
        "historical state (13 fixtures, nothing learned). Changing them to match "
        "a live database turns a migration into a deletion tool."
    )
    assert mod.EXPECTED["provenanced_concepts"] == 0, (
        "a purge authorised against provenanced concepts deletes learned "
        "knowledge by definition"
    )


def test_guard_refuses_when_learned_concepts_exist():
    """The adversarial case: point it at the data it must never delete."""
    rc, out = _dry_run()

    if "DRY RUN" in out and "precondition and census pass" in out:
        pytest.skip(
            "database still holds the authorised legacy pre-state; the guard "
            "correctly permits the migration, so the refusal case does not apply"
        )

    assert rc == 1, (
        f"expected a protected-state refusal (exit 1), got {rc}. A nonzero exit "
        f"from an unrelated failure would not prove the guard works.\n{out[-1500:]}"
    )
    assert "PRECONDITION FAILED" in out, (
        f"exit 1 was not the precondition refusal — it may have been an outage, "
        f"import error, or missing environment:\n{out[-1500:]}"
    )
    assert "refusing to purge" in out
    assert "carry provenance" in out, (
        "the refusal must name learned data as the reason, not merely report a "
        "count mismatch"
    )


def test_dry_run_does_not_modify_the_database():
    """A dry run observes only.

    Both measurements and the subprocess run inside ONE event loop. Two separate
    asyncio.run() calls each create and destroy a loop, while the database
    manager is a process singleton whose asyncpg pool binds to the loop that
    built it — so the second measurement failed with "another operation is in
    progress", a harness artefact that says nothing about the script.
    """
    import asyncio

    async def scenario():
        from dotenv import load_dotenv
        load_dotenv(REPO / ".env.production", override=True)
        from core.database import get_database_manager

        db = get_database_manager()
        if not getattr(db, "initialized", False):
            await db.initialize()

        async def counts():
            return {
                t: int((await db.execute_query(
                    f"SELECT count(*) n FROM unified.{t}", fetch_all=True))[0]["n"])
                for t in ("concepts", "concept_evidence", "evidence_envelopes", "domains")
            }

        before = await counts()
        await asyncio.to_thread(_dry_run)
        return before, await counts()

    before, after = asyncio.run(scenario())
    assert before == after, f"dry run modified the database: {before} -> {after}"
    assert before["concepts"] > 0, (
        "oracle is vacuous against an empty store; it must run where there is "
        "learned state to protect"
    )
