#!/usr/bin/env python3
"""Re-runnable evidence for the evidence-source wiring and the defects it exposed.

Every claim below is produced by executing the real code path, not by reading
it. Writes experiments/WIRING_EVIDENCE.json and prints the same content.
"""
from __future__ import annotations

import asyncio, json, sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.database.unified_database_postgres import get_unified_database  # noqa: E402


async def store_state(db):
    async def rows(sql):
        return [dict(r) for r in (await db.execute_query(sql, fetch_all=True) or [])]
    return {
        "envelopes_by_source": await rows(
            "SELECT source_type, producer, count(*) n FROM unified.evidence_envelopes "
            "GROUP BY 1,2 ORDER BY 1,2"),
        "concepts_by_extractor": await rows(
            "SELECT provenance->>'first_source_type' source_type, "
            "provenance->>'extractor' extractor, count(*) n "
            "FROM unified.concepts GROUP BY 1,2 ORDER BY 3 DESC"),
        "relations_by_extractor": await rows(
            "SELECT extractor, count(*) n FROM unified.concept_relations "
            "GROUP BY 1 ORDER BY 2 DESC"),
        "perceptions": await rows("SELECT count(*) n FROM unified.perceptions"),
        "reasoning_pattern_rules": await rows(
            "SELECT rule_id, rendered_formula, epistemic_status FROM unified.learned_rules "
            "WHERE rule_kind='reasoning_pattern' ORDER BY rule_id"),
    }


async def check_perception():
    from core.agents.autonomous.perception_manager import PerceptionManager
    pm = PerceptionManager({})
    assert await pm.initialize()
    p = await pm.process_input(
        source="health_monitoring", data_type="component_degraded",
        content={"component": "learning_system", "severity": "degraded",
                 "message": "learning subsystem reported degraded health"})
    found = await pm.search_perceptions({"source": "health_monitoring", "limit": 3})
    return {
        "perceived": bool(p),
        "retained": bool(p and p.metadata.get("retained")),
        "readback_rows": len(found),
        "stats": {k: v for k, v in pm.stats.items() if k.startswith("total")},
        "passed": bool(p and p.metadata.get("retained") and found),
    }


async def check_logical_agent():
    from core.agents.logical import ENHANCED_LOGICAL_STATUS, EnhancedLogicalAgent
    agent = EnhancedLogicalAgent()
    await agent.initialize()

    cases = [
        ("provable", ["All men are mortal", "Socrates is a man"], ["Is Socrates mortal?"]),
        ("unprovable", ["All men are mortal", "Socrates is a man"], ["Is Socrates immortal?"]),
        ("no_premises", [], ["Is Socrates mortal?"]),
        ("unformalizable", ["We report a novel synthesis route for LiFePO4"], ["Is LiFePO4 stable?"]),
        ("no_goal", ["All men are mortal", "Socrates is a man"], []),
    ]
    deduction = {}
    for label, premises, goals in cases:
        r = await agent.execute("logical_reasoning", {"input_data": {
            "premises": premises, "mode": "deductive", "goals": goals}})
        deduction[label] = {
            "success": r["success"], "formalized": r.get("formalized"),
            "requires_model": r.get("requires_model"),
            "conclusions": r["conclusions"], "error": r.get("error"),
            "proof_steps": r.get("proof_steps"),
        }
    return {
        "importable": ENHANCED_LOGICAL_STATUS.available,
        "integration": type(agent.logical_integration).__name__,
        "protocol_execute": callable(getattr(agent, "execute", None)),
        "deduction": deduction,
        "stats": dict(agent.reasoning_stats),
        # The control that matters: it must be able to fail.
        "passed": (deduction["provable"]["success"]
                   and not deduction["unprovable"]["success"]
                   and not deduction["no_premises"]["success"]
                   and not deduction["unformalizable"]["success"]
                   and not deduction["no_goal"]["success"]),
    }


async def check_pattern_learning():
    from core.agents.logical import EnhancedLogicalAgent
    agent = EnhancedLogicalAgent()
    await agent.initialize()

    many = await agent.execute("pattern_learning", {"input_data": {"domain": "syllogism_evidence",
        "examples": [
            {"premises": ["Socrates is a man"], "conclusions": ["Socrates is mortal"],
             "evidence_id": "ev_pat_1"},
            {"premises": ["Plato is a man"], "conclusions": ["Plato is mortal"],
             "evidence_id": "ev_pat_2"},
        ]}})
    one = await agent.execute("pattern_learning", {"input_data": {"domain": "syllogism_evidence",
        "examples": [{"premises": ["Rex is a dog"], "conclusions": ["Rex is loud"],
                      "evidence_id": "ev_pat_3"}]}})
    return {
        "two_examples": {"status": many.get("induction_status"),
                         "learned": many["patterns_learned"],
                         "rules": many.get("new_patterns", [])},
        "one_example": {"status": one.get("induction_status"),
                        "learned": one["patterns_learned"]},
        "counter": agent.reasoning_stats["patterns_learned"],
        # A counter that cannot decrease measures nothing.
        "passed": many["patterns_learned"] >= 1 and one["patterns_learned"] == 0,
    }


async def check_tool_projection():
    from core.tools.tool_registry import get_tool_registry
    registry = get_tool_registry()
    result = await registry.execute_tool(
        "list_directory", {"directory_path": str(Path(__file__).resolve().parent)})
    projection = await registry.project_capabilities()
    return {"tool_invocation_succeeded": result.success,
            "projection": projection,
            "passed": result.success and projection["projected"] > 0
                      and projection["failed"] == 0}


async def main() -> int:
    db = await get_unified_database()
    await db.initialize()

    checks = {
        "perception_retention": await check_perception(),
        "logical_agent_deduction": await check_logical_agent(),
        "pattern_learning": await check_pattern_learning(),
        "tool_observation_and_projection": await check_tool_projection(),
    }
    evidence = {
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "checks": checks,
        "store_state": await store_state(db),
        "all_passed": all(c["passed"] for c in checks.values()),
    }

    out = Path(__file__).resolve().parent / "WIRING_EVIDENCE.json"
    out.write_text(json.dumps(evidence, indent=2, default=str))

    for name, check in checks.items():
        print(f"{'PASS' if check['passed'] else 'FAIL'}  {name}")
    print(f"\nALL: {'PASS' if evidence['all_passed'] else 'FAIL'}")
    print(f"evidence -> {out}")
    return 0 if evidence["all_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
