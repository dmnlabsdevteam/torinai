"""EDU-02 — Level 5: detect own failure in the world, withdraw the rule's authority.

The substrate plans from a rule it believes, ACTS on that plan against a real
filesystem, observes the act fail, and records the contradiction against the rule
that produced it. Nothing here tells it the rule is wrong; the world does.
"""
import asyncio, json, sys, time
from pathlib import Path as _Path

_ROOT = _Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))
# e2e_common used to be imported from a per-session scratchpad directory. When
# that directory was cleared the experiment died with ModuleNotFoundError and
# could never be re-run; it lives in experiments/ now.
sys.path.insert(0, str(_ROOT / "experiments"))
from e2e_common import reset_world, observe, where_is, WORLD_ROOT, ITEM

from core.database.unified_database_postgres import get_unified_database
from core.learning.rule_store import get_rule_store, record_runtime_evidence
from core.learning.rule_grounding import ground_for_problem
from core.learning.rule_induction import Fact
from core.reasoning.temporal_reasoning import TemporalReasoningSystem
from core.execution.effect_verification import (
    RuntimeEvidence, RuntimeOutcome, Attribution)
from core.tools.tool_registry import get_tool_registry

BROAD = "rule_dccaff4cba0f"     # believes it can move from anywhere

async def main():
    db = await get_unified_database(); await db.initialize()
    store = get_rule_store()
    rule = {r.rule_id: r for r in await store.load(domain_id="kite17")}[BROAD]
    print("1. RULE UNDER TEST:", rule.rule_id, "status:", rule.status.value)
    print("   body:", sorted(str(f) for f in rule.rule.body))

    # THIS DEMONSTRATION IS ONE-WAY AND CANNOT BE REPEATED.
    #
    # What it shows is a rule LOSING authority: validated -> refuted, driven by
    # the world contradicting a prediction. Once that has happened the rule is
    # refuted for good -- it is retained, never deleted -- and a refuted rule
    # correctly no longer grounds into operators. So a second run gets an empty
    # operator set, plans nothing, and used to die on `res.steps[0]` with
    # IndexError, which reads as a broken benchmark rather than as a benchmark
    # whose result is already in the record.
    #
    # Re-running must NOT restore the rule to validated to make the
    # demonstration repeatable. That would edit the epistemic record to suit
    # the test, which is the one thing this whole subsystem exists to prevent.
    # Instead the recorded transition is verified: the evidence that the
    # substrate detected its own failure is the authority event it wrote.
    if not rule.status.value.lower().startswith(("validated", "candidate")):
        print(f"\n   The rule is already {rule.status.value}. This is a one-way "
              f"transition, so the demonstration is verified from the record "
              f"rather than repeated.")
        events = await db.execute_query(
            "SELECT old_status, new_status, lost_authority, cause, observation_id,"
            " detail, occurred_at FROM unified.rule_authority_events"
            " WHERE rule_id=$1 ORDER BY occurred_at", params=(BROAD,),
            fetch_all=True) or []
        print(f"\n2. RECORDED AUTHORITY HISTORY ({len(events)} event(s))")
        for e in events:
            print(f"   {e['occurred_at']}  {e['old_status']} -> {e['new_status']}"
                  f"  lost_authority={e['lost_authority']}  cause={e['cause']}")
            if e["detail"]:
                print(f"      {str(e['detail'])[:130]}")

        withdrawal = [e for e in events
                      if e["lost_authority"] and e["cause"] == "runtime_contradiction"]
        executable = [r.rule_id for r in await store.executable_rules(domain_id="kite17")]

        print("\n3. WHAT THE RECORD HAS TO SHOW")
        checks = {
            "a runtime contradiction withdrew authority": bool(withdrawal),
            "the withdrawal cites a real observation":
                bool(withdrawal) and bool(withdrawal[0]["observation_id"]),
            "the rule is no longer executable": BROAD not in executable,
            "the rule was retained, not deleted": rule is not None,
        }
        for label, ok in checks.items():
            print(f"   {'OK ' if ok else 'XX '} {label}")
        passed = all(checks.values())
        print(f"\nEDU-02: {'PASS (verified from record)' if passed else 'FAIL'}")
        return 0 if passed else 1

    reset_world()
    world = observe()
    print("\n2. WORLD:", where_is(), "|", [f for f in world if f.startswith("AT(")])

    sf = [Fact.parse(f) for f in world]; gf = [Fact.parse("AT(z,VAULT)")]
    g = ground_for_problem([rule], sf, gf)
    res = TemporalReasoningSystem().plan_for_state_goal(
        [f.to_formula() for f in gf], {"conditions": [f.to_formula() for f in sf]}, g.to_actions())
    print("\n3. PLAN IT BELIEVES:", res.status.name, "steps:", len(res.steps))
    for s in res.steps: print("     ", s["action"])

    step = res.steps[0]["action"]
    item, src, dst = [x.strip() for x in step[step.index("(")+1:step.rindex(")")].split(",")]
    print(f"\n4. ACT: {step}  (real tool, real filesystem)")
    tool = get_tool_registry().get_tool("move_file")
    result = await tool.execute(source_path=str(WORLD_ROOT/src/item),
                                destination_path=str(WORLD_ROOT/dst/item))
    print("   tool success:", result.success, "| error:", (result.error or "")[:70])

    print("\n5. OBSERVE:", where_is(), "-> predicted AT(z,VAULT)?",
          f"AT({ITEM},VAULT)" in observe())
    contradicted = not result.success or f"AT({ITEM},VAULT)" not in observe()
    print("   prediction contradicted by the world:", contradicted)
    assert contradicted, "the broad rule unexpectedly succeeded"

    print("\n6. RECORD THE CONTRADICTION AGAINST THE RULE")
    ev = RuntimeEvidence(
        outcome=RuntimeOutcome.CONTRADICTION,
        rule_id=rule.rule_id,
        operator=step,
        observation_id=f"edu02_{int(time.time())}",
        detail=f"executed {step}; predicted AT(z,VAULT); world shows AT(z,{where_is()})")
    status = await record_runtime_evidence(
        store, ev, Attribution.RULE_EVIDENCE, detail=ev.detail)
    print("   new epistemic status:", status)

    print("\n7. AUTHORITY AFTER THE FAILURE")
    again = {r.rule_id: r for r in await store.load(domain_id="kite17")}[BROAD]
    print("   status in PostgreSQL :", again.status.value)
    ex = [r.rule_id for r in await store.executable_rules(domain_id="kite17")]
    print("   still executable     :", BROAD in ex)
    events = await db.execute_query(
        "SELECT cause, previous_status, current_status FROM unified.rule_authority_events"
        " WHERE rule_id=$1 ORDER BY 1 DESC LIMIT 3", params=(BROAD,), fetch_all=True) or []
    print("   authority events     :", [dict(e) for e in events])
asyncio.run(main())
