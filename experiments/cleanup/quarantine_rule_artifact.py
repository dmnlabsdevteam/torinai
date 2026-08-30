#!/usr/bin/env python3
"""Quarantine a rule that an implementation defect produced. Auditable, not destructive.

`rule_589ba8306c88` states `A_MAN(?X0) → MORTAL(?X0)`. The predicate carries the
indefinite article because the pattern-learning path normalised `a man` with
`lexical_normalization.normalise` instead of the parser's own `_normalize`,
which strips articles. So `a man` and `man` became two relations and the rule is
malformed — nothing about it was ever tested.

It is NOT marked REFUTED. Refuted means evidence showed a hypothesis false; this
one should never have been written. Recording a code defect as a negative
experimental result would put a fabricated finding in the learning record.

A census runs first. If the rule is referenced anywhere, the row and its
evidence links stay and only its operational authority is withdrawn --
INVALID_ARTIFACT is not VALIDATED, so `executable_rules()` already excludes it.
"""
from __future__ import annotations

import asyncio, json, sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from core.database.unified_database_postgres import get_unified_database  # noqa: E402
from core.learning.rule_store import EpistemicStatus, get_rule_store  # noqa: E402

TARGET = "rule_589ba8306c88"
REASON = "pre_fix_article_normalization_artifact"

REFERENCE_COLUMNS = [
    ("unified.learned_rule_evidence", "rule_id"),
    ("unified.rule_authority_events", "rule_id"),
    ("unified.rule_supersessions", "superseded_rule_id"),
    ("unified.rule_supersessions", "replacement_rule_id"),
    ("unified.learned_rules", "supersedes_rule_id"),
    ("unified.rule_identity_aliases", "canonical_rule_id"),
]


async def main() -> int:
    db = await get_unified_database()
    await db.initialize()
    store = get_rule_store()

    rows = await db.execute_query(
        "SELECT * FROM unified.learned_rules WHERE rule_id = $1", (TARGET,), fetch_all=True)
    if not rows:
        print(f"{TARGET} is not present; nothing to quarantine")
        return 0
    rule_row = {k: str(v) for k, v in dict(rows[0]).items()}

    census = {}
    for table, column in REFERENCE_COLUMNS:
        got = await db.execute_query(
            f"SELECT count(*) n FROM {table} WHERE {column} = $1", (TARGET,), fetch_all=True)
        if got and got[0]["n"]:
            census[f"{table}.{column}"] = got[0]["n"]

    evidence = [dict(r) for r in (await db.execute_query(
        "SELECT root_evidence_id, evidence_role, supports FROM unified.learned_rule_evidence"
        " WHERE rule_id = $1 ORDER BY root_evidence_id", (TARGET,), fetch_all=True) or [])]

    references = sum(census.values())
    print(f"reference census for {TARGET}: {census or 'NO REFERENCES'}")

    if references:
        action = "quarantined_in_place"
        await db.execute_query(
            "UPDATE unified.learned_rules SET epistemic_status = $1, detail = $2,"
            " updated_at = NOW() WHERE rule_id = $3",
            (EpistemicStatus.INVALID_ARTIFACT.value,
             f"malformed by {REASON}; withdrawn from operational authority, "
             f"record preserved because {references} reference(s) exist", TARGET),
            commit=True)
        print(f"-> {action}: status is now {EpistemicStatus.INVALID_ARTIFACT.value}, "
              f"row and {len(evidence)} evidence link(s) preserved")
    else:
        action = "deleted"
        await db.execute_query(
            "DELETE FROM unified.learned_rules WHERE rule_id = $1", (TARGET,), commit=True)
        print(f"-> {action}: genuinely orphaned, removed after snapshot")

    reloaded = await store.get(TARGET)
    executable = [r.rule_id for r in await store.executable_rules()]
    manifest = {
        "rule_id": TARGET,
        "reason": REASON,
        "canonical_content": rule_row.get("canonical_rule_json"),
        "rendered_formula": rule_row.get("rendered_formula"),
        "domain_id": rule_row.get("domain_id"),
        "semantic_fingerprint": rule_row.get("semantic_fingerprint"),
        "status_before": rule_row.get("epistemic_status"),
        "status_after": reloaded.status.value if reloaded else None,
        "references_found": census,
        "evidence_links_preserved": evidence,
        "action": action,
        "removed_from_executable_rules": TARGET not in executable,
        "snapshot": "experiments/cleanup/RULE_TABLES_SNAPSHOT_2026-08-19.json",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }
    out = Path(__file__).resolve().parent / "RULE_IDENTITY_CLEANUP_2026-08-19.json"
    out.write_text(json.dumps(manifest, indent=2, default=str))
    print(f"executable_rules excludes it: {manifest['removed_from_executable_rules']}")
    print(f"manifest -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
