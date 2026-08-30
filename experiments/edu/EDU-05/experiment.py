#!/usr/bin/env python3
"""EDU-05 — real execution becomes evidence.

Torin acts on the world through a learned rule, observes the result, and the
observed state transition is recorded as a ROOT observation in the semantic
layer. Model-free end to end.

WHY THIS IS THE MISSING LINK. Until it was wired, every demonstration the
learner had ever seen came from a TEACHER. `training_example_from_runtime` --
the function whose entire purpose is turning an executed action into a
demonstration -- had zero callers, so real work produced task outcomes in prose
and nothing the substrate could induce from. Cross-domain transfer therefore had
exactly one source domain: the one it had been taught.

The oracle is the FILESYSTEM, not the tool's return value. A rule confirmed by
its own invocation returning cleanly is not confirmed by anything.
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from core.agents.autonomous.general_purpose_executor import GeneralPurposeExecutor  # noqa: E402
from core.database.unified_database_postgres import get_unified_database  # noqa: E402
from core.model_policy import assert_model_free, model_telemetry  # noqa: E402
from experiments.e2e_world import FilesystemWorld, ITEM  # noqa: E402

DOMAIN = "kite17"
RULE = "rule_edbe5a8b4ad8"
OPERATOR = f"MOVE({ITEM},HALL,LAB)"


async def main() -> int:
    db = await get_unified_database()
    await db.initialize()

    world = FilesystemWorld().register(DOMAIN)
    world.clear(ITEM)
    world.place(ITEM, "HALL")
    before_disk = sorted(str(f) for f in world.observe())
    print("world before:", [f for f in before_disk if f.startswith("AT(")])

    task = SimpleNamespace(
        id=f"edu05_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}",
        description=OPERATOR,
        provenance={"learned_rule_id": RULE, "grounded_operator": OPERATOR,
                    "domain_id": DOMAIN, "plan_id": None, "goal_id": None},
    )

    executor = GeneralPurposeExecutor()
    result = await executor._try_substrate_execution(task)
    if result is None:
        print("ABORT: the substrate path did not engage")
        return 1
    print(f"execution: success={result.get('success')} "
          f"path={result.get('execution_path')} model_free={result.get('model_free')}")
    if result.get("refused"):
        print("ABORT: refused —", result["refused"])
        return 1

    after_disk = sorted(str(f) for f in world.observe())
    print("world after :", [f for f in after_disk if f.startswith("AT(")])
    moved = f"AT({ITEM}, LAB)" in after_disk and f"AT({ITEM}, HALL)" not in after_disk

    rows = await db.execute_query(
        "SELECT evidence_id, source_type, producer, structured_data "
        "FROM unified.evidence_envelopes WHERE source_type = 'task_artifact' "
        "ORDER BY observed_at DESC LIMIT 1", fetch_all=True) or []
    if not rows:
        print("FAIL: execution recorded no task_artifact evidence")
        return 1
    envelope = rows[0]
    structured = envelope["structured_data"]
    if isinstance(structured, str):
        structured = json.loads(structured)
    print(f"\nevidence  : {envelope['evidence_id']} "
          f"({envelope['source_type']} from {envelope['producer']})")
    observation = structured.get("observation") or {}
    print(f"observed  : action={observation.get('action')} "
          f"adds={observation.get('adds')} removes={observation.get('removes')}")

    concepts = await db.execute_query(
        "SELECT c.concept_id, c.concept_kind, c.epistemic_status "
        "FROM unified.concepts c JOIN unified.concept_evidence e "
        "  ON e.concept_id = c.concept_id "
        "WHERE e.evidence_id = $1 ORDER BY c.concept_id",
        (envelope["evidence_id"],), fetch_all=True) or []
    print(f"concepts  : {[(r['concept_id'], r['epistemic_status']) for r in concepts]}")

    roots = await db.execute_query(
        "SELECT DISTINCT root_evidence_id FROM unified.concept_evidence "
        "WHERE evidence_id = $1", (envelope["evidence_id"],), fetch_all=True) or []
    own_root = [r["root_evidence_id"] for r in roots] == [envelope["evidence_id"]]

    telemetry = model_telemetry()
    assert_model_free("edu05_execution_evidence")

    passed = bool(moved and concepts and own_root and telemetry["executed"] == 0)
    print(f"\nworld actually changed : {moved}")
    print(f"observation is its own root : {own_root}")
    print(f"model: attempts={telemetry['attempts']} executed={telemetry['executed']} "
          f"policy={telemetry['policy']}")
    print(f"\nEDU-05: {'PASS' if passed else 'FAIL'}")

    manifest = Path(__file__).resolve().parent / "manifest.json"
    manifest.write_text(json.dumps({
        "benchmark": "EDU-05",
        "title": "Executed Action Becomes Root Evidence",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "passed": passed,
        "model_calls": telemetry["executed"],
        "domain": DOMAIN,
        "rule_id": RULE,
        "operator": OPERATOR,
        "oracle": "filesystem listing, independent of the tool's return value",
        "world_before": before_disk,
        "world_after": after_disk,
        "evidence": {
            "evidence_id": envelope["evidence_id"],
            "source_type": envelope["source_type"],
            "producer": envelope["producer"],
            "is_own_root": own_root,
            "observation": observation,
        },
        "concepts_supported": [
            {"concept_id": r["concept_id"], "kind": r["concept_kind"],
             "epistemic_status": r["epistemic_status"]} for r in concepts],
    }, indent=2))
    print(f"manifest -> {manifest}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
