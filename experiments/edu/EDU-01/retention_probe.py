#!/usr/bin/env python3
"""EDU-01 delayed retention — does taught competence survive time and restarts?

EDU-01 froze a capability gain at T+0: one counterexample took a 9-problem exam
from 2/9 to 9/9. That measured LEARNING. It did not measure RETENTION, and the
two are different claims -- "persistent" is the first word of this
architecture's description, so it has to be evidence rather than an assumption.

This probe re-runs the frozen exam WITHOUT TEACHING ANYTHING. It reads the
repaired rule back out of the durable store in a fresh process and asks three
questions:

    does the rule still exist            -- durability of the record
    is it byte-identical to the frozen   -- no silent drift or re-induction
    does it still score 9/9              -- durability of the CAPABILITY

The third is the one that matters. A rule row that survives while the
capability it conferred does not is exactly the fabricated-persistence failure
this repository keeps finding: the record is there, so something reports
success, and nothing checks that it still does anything.

The log is APPEND-ONLY and every entry records the ACTUAL elapsed hours. A
checkpoint is only claimed when its nominal time has genuinely passed -- a
probe run at T+5.8h does not get to call itself T+6h.
"""

import asyncio
import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2]))

MILESTONES = (("T+6h", 6.0), ("T+24h", 24.0), ("T+7d", 168.0))


def _load_experiment():
    spec = importlib.util.spec_from_file_location("edu01", HERE / "experiment.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def milestone_for(elapsed_hours: float):
    """The highest milestone genuinely reached, or None. Never rounds up."""
    reached = [name for name, hours in MILESTONES if elapsed_hours >= hours]
    return reached[-1] if reached else None


async def main() -> int:
    edu01 = _load_experiment()
    frozen = json.loads((HERE / "manifest.json").read_text())
    recorded_at = datetime.fromisoformat(frozen["recorded_at"])
    now = datetime.now(timezone.utc)
    elapsed = (now - recorded_at).total_seconds() / 3600.0
    milestone = milestone_for(elapsed)

    print(f"EDU-01 frozen at {frozen['recorded_at'][:19]}  ·  elapsed {elapsed:.2f}h")
    if milestone is None:
        nxt, hours = MILESTONES[0]
        print(f"no milestone reached yet — {nxt} in {(hours - elapsed) * 60:.0f} minutes")
    else:
        print(f"milestone: {milestone}")

    from core.database.unified_database_postgres import get_unified_database
    from core.learning.rule_store import get_rule_store

    db = await get_unified_database()
    await db.initialize()
    store = get_rule_store()
    rules = {r.rule_id: r for r in await store.load(domain_id="kite17")}

    rule_id = frozen["post_lesson_rule"]["rule_id"]
    survives = rule_id in rules
    print(f"\nrule {rule_id} present in store : {survives}")
    if not survives:
        print("RETENTION FAILED — the taught rule is gone from the durable store")
        return 1

    rule = rules[rule_id]
    body = sorted(str(f) for f in rule.rule.body)
    unchanged = body == frozen["post_lesson_rule"]["body"]
    print(f"body identical to frozen manifest  : {unchanged}")
    if not unchanged:
        print(f"   frozen : {frozen['post_lesson_rule']['body']}")
        print(f"   now    : {body}")

    print("\nre-running the frozen exam, no teaching")
    score, rows = await edu01.score([rule], "retained")
    total = len(edu01.MAPS)
    expected = frozen["results"]["post"]["score"]
    retained = score == expected

    entry = {
        "probed_at": now.isoformat(),
        "elapsed_hours": round(elapsed, 3),
        "milestone": milestone,
        "rule_id": rule_id,
        "rule_present": survives,
        "rule_body_unchanged": unchanged,
        "score": score,
        "of": total,
        "frozen_score": expected,
        "capability_retained": retained,
        "detail": rows,
    }
    log_path = HERE / "retention.json"
    log = json.loads(log_path.read_text()) if log_path.exists() else {
        "benchmark": "EDU-01", "frozen_at": frozen["recorded_at"],
        "note": "append-only; elapsed_hours is measured, never assumed",
        "checkpoints": []}
    log["checkpoints"].append(entry)
    log_path.write_text(json.dumps(log, indent=2))

    verdict = survives and unchanged and retained
    print(f"\nretained {score}/{total} (frozen {expected}/{total})  ·  "
          f"EDU-01 retention {'PASS' if verdict else 'FAIL'}"
          + (f" at {milestone}" if milestone else " (pre-milestone probe)"))
    print(f"log -> {log_path}")
    return 0 if verdict else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
