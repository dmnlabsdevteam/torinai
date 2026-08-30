"""EDU-01 — Discriminating Evidence -> Compositional Capability Gain.

One counterexample (the item is not at the source) is the entire teaching event.
Everything measured here is planning from learned rules over a stated world:
no memory injection, no memory retrieval, no model call.

Maps are held out from teaching, which used rooms R1..R16 and single-hop
demonstrations only.
"""
import asyncio, json, sys
from datetime import datetime, timezone
sys.path.insert(0, '/Users/stefan/Dominion Labs/TorinAI')

from core.database.unified_database_postgres import get_unified_database
from core.learning.rule_store import get_rule_store
from core.learning.rule_grounding import ground_for_problem
from core.learning.rule_induction import Fact
from core.reasoning.temporal_reasoning import TemporalReasoningSystem

PRE_LESSON_RULE  = "rule_dccaff4cba0f"   # no AT(X,A) precondition
POST_LESSON_RULE = "rule_edbe5a8b4ad8"   # after mv_no_AT_SOURCE

def chain(item, rooms):
    w = [f"AT({item},{rooms[0]})"]
    for a, b in zip(rooms, rooms[1:]):
        w += [f"PATH({a},{b})", f"OPEN({b})"]
    return w, [f"AT({item},{rooms[-1]})"], len(rooms) - 1

MAPS = [
    ("2-hop",          *chain("z", ["HALL","LAB","VAULT"])),
    ("3-hop",          *chain("k", ["A1","B1","C1","D1"])),
    ("4-hop",          *chain("m", ["P","Q","R","S","T"])),
    ("5-hop",          *chain("n", ["N0","N1","N2","N3","N4","N5"])),
    ("6-hop",          *chain("p", ["S0","S1","S2","S3","S4","S5","S6"])),
    # branched: two routes, shorter one is legal -> optimal is 2
    ("branched",       ["AT(b,J0)","PATH(J0,J1)","OPEN(J1)","PATH(J1,J4)","OPEN(J4)",
                        "PATH(J0,J2)","OPEN(J2)","PATH(J2,J3)","OPEN(J3)","PATH(J3,J4)"],
                       ["AT(b,J4)"], 2),
    # dead end: the only long branch terminates; real route is the other one
    ("dead-end",       ["AT(d,K0)","PATH(K0,K1)","OPEN(K1)","PATH(K1,K2)","OPEN(K2)",
                        "PATH(K0,K9)","OPEN(K9)"],
                       ["AT(d,K2)"], 2),
    # negative controls
    ("no path",        ["AT(v,M1)","OPEN(N1)"], ["AT(v,N1)"], None),
    ("closed door",    ["AT(u,G1)","PATH(G1,H1)"], ["AT(u,H1)"], None),
]

def valid(steps, world):
    at = {}
    for f in world:
        if f.startswith("AT("):
            a, b = f[3:-1].split(",")
            at[a.strip()] = b.strip()
    for s in steps:
        act = s["action"]
        item, src, dst = [x.strip() for x in act[act.index("(")+1:act.rindex(")")].split(",")]
        if at.get(item) != src:
            return False
        at[item] = dst
    return True

def run(rules, world, goal):
    sf = [Fact.parse(f) for f in world]
    gf = [Fact.parse(f) for f in goal]
    g = ground_for_problem(rules, sf, gf)
    res = TemporalReasoningSystem().plan_for_state_goal(
        [f.to_formula() for f in gf],
        {"conditions": [f.to_formula() for f in sf]},
        g.to_actions())
    return res.steps, res.status

async def score(rules, label):
    rows, ok = [], 0
    for name, world, goal, expect in MAPS:
        steps, status = run(rules, world, goal)
        n = len(steps)
        if expect is None:
            good = (n == 0)
            note = status.name
        else:
            good = (n == expect and valid(steps, world))
            note = "valid" if (n and valid(steps, world)) else ("INVALID" if n else status.name)
        ok += good
        rows.append({"map": name, "steps": n, "expected": expect,
                     "correct": good, "note": note})
        print(f"   {'OK ' if good else 'XX '}{name:<12} steps={n} expected={expect}  {note}")
    print(f"   {label}: {ok}/{len(MAPS)}")
    return ok, rows

async def main():
    db = await get_unified_database(); await db.initialize()
    store = get_rule_store()
    allr = {r.rule_id: r for r in await store.load(domain_id="kite17")}
    pre, post = allr[PRE_LESSON_RULE], allr[POST_LESSON_RULE]

    print("PRE-LESSON RULE :", pre.rendered_formula if hasattr(pre,'rendered_formula') else pre.rule_id)
    print("POST-LESSON RULE:", post.rule_id)

    print("\nBEFORE the lesson")
    pre_ok, pre_rows = await score([pre], "pre")
    print("\nAFTER the lesson")
    post_ok, post_rows = await score([post], "post")

    print("\nABLATION — remove the AT-bearing rule entirely")
    abl_ok, abl_rows = await score([], "ablated")

    total = len(MAPS)
    report = {
        "benchmark": "EDU-01",
        "title": "Discriminating Evidence -> Compositional Capability Gain",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "teaching": {
            "positives": "single-hop MOVE demonstrations (mv_d1, mv_d2)",
            "counterexample": "mv_no_AT_SOURCE — item not at the source",
            "held_out": ["mv_h1", "mv_h2"],
        },
        "memory_retrieval": "none",
        "model_calls": 0,
        "pre_lesson_rule": {"rule_id": PRE_LESSON_RULE,
                            "body": sorted(str(f) for f in pre.rule.body),
                            "action": str(pre.rule.action)},
        "post_lesson_rule": {"rule_id": POST_LESSON_RULE,
                             "body": sorted(str(f) for f in post.rule.body),
                             "action": str(post.rule.action)},
        "results": {"pre": {"score": pre_ok, "of": total, "detail": pre_rows},
                    "post": {"score": post_ok, "of": total, "detail": post_rows},
                    "ablated": {"score": abl_ok, "of": total, "detail": abl_rows}},
        "delta_pp": round(100.0 * (post_ok - pre_ok) / total, 1),
    }
    out = "/Users/stefan/Dominion Labs/TorinAI/experiments/edu/EDU-01_T0.json"
    json.dump(report, open(out, "w"), indent=2)
    print(f"\nΔ competence: {pre_ok}/{total} -> {post_ok}/{total}  "
          f"(+{report['delta_pp']} percentage points)")
    print("frozen:", out)

if __name__ == "__main__":
    # Guarded so the retention probe can reuse MAPS, run(), score() and valid()
    # instead of copying them. A second copy of the exam would be a second
    # authority on what EDU-01 measures, and the two would drift.
    asyncio.run(main())
