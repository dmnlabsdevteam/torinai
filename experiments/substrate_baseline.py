#!/usr/bin/env python3
"""Freeze what the substrate contained before an experiment taught it anything.

Test 0 of the acquisition battery. The claim a teaching experiment eventually
makes -- "this capability came from experience" -- is only as good as the
evidence that the capability was absent beforehand, so the baseline has to be
recorded before the first demonstration and be checkable afterwards.

Two things are frozen:

  counts   how many rows each substrate store held
  digest   an order-stable hash of their contents

The digest matters because counts alone cannot distinguish "nothing was
learned" from "one row was learned and one was evicted".

This is deliberately NOT `capability_baseline_freezes`, which
core.learning.capability_benchmark_suite owns and uses to freeze benchmark
*scores*. This is a census of substrate contents. Two different questions, kept
in two different places on purpose.

Usage:
    python3 experiments/substrate_baseline.py freeze  --label pre_kite
    python3 experiments/substrate_baseline.py compare --label pre_kite
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

import asyncpg

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.model_policy import model_telemetry  # noqa: E402

BASELINE_DIR = Path(__file__).resolve().parent / "baselines"

#: The stores that constitute learned state, grouped by the question each
#: answers. A store listed here and absent from the database is reported as
#: missing rather than skipped -- a category that silently vanishes would make
#: the baseline look cleaner than the substrate actually is.
SUBSTRATE: Dict[str, list] = {
    "memory": ["memory_hot.memory_hot", "memory_cold.memory_cold"],
    "concepts": [
        "unified.concepts", "unified.concept_relations", "unified.concept_evidence",
        "unified.concept_aliases", "unified.concept_domains", "unified.concept_mappings",
    ],
    "domains": ["unified.domains", "unified.domain_mappings", "unified.knowledge_transfers"],
    "beliefs": ["unified.beliefs", "unified.hypotheses", "unified.evidence", "unified.claims"],
    "learned_rules": ["unified.learned_rules"],
    "procedural": [
        "unified.meta_learning_strategies", "unified.meta_learning_tasks",
        "unified.tool_usage_history",
    ],
    "outcomes": [
        "unified.task_execution_history", "unified.meta_decision_records",
        "unified.improvement_cycles", "unified.tool_error_events",
    ],
    "competence": [
        "unified.capability_tracking", "unified.capability_benchmark_results",
        "unified.capability_baseline_freezes",
    ],
    "episodic": ["unified.thinking_states", "unified.reasoning_chains", "unified.analogies"],
    "working_state": ["unified.goals", "unified.plans"],
}


async def _census(conn: asyncpg.Connection) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for category, tables in SUBSTRATE.items():
        rows: Dict[str, Any] = {}
        for qualified in tables:
            schema, _, table = qualified.partition(".")
            exists = await conn.fetchval(
                "SELECT to_regclass($1) IS NOT NULL", qualified
            )
            if not exists:
                rows[qualified] = {"present": False}
                continue
            count = await conn.fetchval(f"SELECT count(*) FROM {qualified}")
            digest = await conn.fetchval(
                f"SELECT md5(coalesce(string_agg(t::text, '|' ORDER BY t::text), ''))"
                f" FROM {qualified} t"
            )
            rows[qualified] = {"present": True, "count": count, "digest": digest}
        out[category] = rows
    return out


async def _snapshot(label: str) -> Dict[str, Any]:
    # RESOLVED, NOT HARDCODED. This passed no port at all, and asyncpg's
    # default is 5432 -- the shared instance holding agentso's tenant
    # databases, whose copy of torinai_db last saw a write on 2026-08-18.
    # Every baseline this file measured was therefore taken against a stale
    # database rather than the live one on 5433.
    from core.database.postgres_config import PostgresConfig

    _cfg = PostgresConfig.resolve()
    conn = await asyncpg.connect(
        host=_cfg.host, port=_cfg.port, database=_cfg.database,
        user=_cfg.user, password=_cfg.password or None)
    try:
        census = await _census(conn)
    finally:
        await conn.close()

    total = sum(
        entry.get("count", 0)
        for tables in census.values()
        for entry in tables.values()
        if entry.get("present")
    )
    return {
        "label": label,
        "frozen_at": datetime.now(timezone.utc).isoformat(),
        "total_rows": total,
        "model": model_telemetry(),
        "substrate": census,
    }


def _path(label: str) -> Path:
    return BASELINE_DIR / f"{label}.json"


async def freeze(label: str) -> int:
    snapshot = await _snapshot(label)
    BASELINE_DIR.mkdir(parents=True, exist_ok=True)
    path = _path(label)
    if path.exists():
        print(f"refusing to overwrite existing baseline {path}", file=sys.stderr)
        return 1
    path.write_text(json.dumps(snapshot, indent=2))

    print(f"froze {snapshot['total_rows']} rows -> {path}")
    for category, tables in snapshot["substrate"].items():
        present = {t: e for t, e in tables.items() if e.get("present")}
        missing = [t for t, e in tables.items() if not e.get("present")]
        held = sum(e["count"] for e in present.values())
        note = f"   (absent: {', '.join(missing)})" if missing else ""
        print(f"  {held:>8}  {category}{note}")
    print(f"model: {snapshot['model']['attempts']} attempts, "
          f"{snapshot['model']['executed']} executed, policy={snapshot['model']['policy']}")
    return 0


async def compare(label: str) -> int:
    path = _path(label)
    if not path.exists():
        print(f"no baseline at {path}", file=sys.stderr)
        return 1
    before = json.loads(path.read_text())
    after = await _snapshot(label)

    changed = False
    for category, tables in after["substrate"].items():
        for qualified, entry in tables.items():
            was = before["substrate"].get(category, {}).get(qualified, {})
            if not entry.get("present") or not was.get("present"):
                if entry.get("present") != was.get("present"):
                    changed = True
                    print(f"  {qualified}: present {was.get('present')} -> {entry.get('present')}")
                continue
            if entry["digest"] != was["digest"]:
                changed = True
                delta = entry["count"] - was["count"]
                print(f"  {qualified}: {was['count']} -> {entry['count']} ({delta:+d}), contents differ")

    print(f"\n{'substrate changed' if changed else 'substrate identical to baseline'}"
          f" (total {before['total_rows']} -> {after['total_rows']})")
    print(f"model since freeze: {after['model']['attempts']} attempts, "
          f"{after['model']['executed']} executed")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["freeze", "compare"])
    parser.add_argument("--label", required=True)
    args = parser.parse_args()
    return asyncio.run(
        freeze(args.label) if args.action == "freeze" else compare(args.label)
    )


if __name__ == "__main__":
    raise SystemExit(main())
