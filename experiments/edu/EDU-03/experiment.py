"""EDU-03 — Level 4: does learned structure carry into a different representation?

Same abstract structure as MOVE, renamed throughout:
    AT   -> LOCATED      PATH -> LINK
    MOVE -> SEND         OPEN -> UP
Nothing is taught in the new domain. Two questions, asked separately:
  A. does the learned rule apply directly?      (predicate-name transfer)
  B. can the substrate ground the STRUCTURE?    (analogy transfer)
"""
import asyncio, sys
sys.path.insert(0, '/Users/stefan/Dominion Labs/TorinAI')
from core.database.unified_database_postgres import get_unified_database
from core.learning.rule_store import get_rule_store
from core.learning.rule_grounding import ground_for_problem
from core.learning.rule_induction import Fact
from core.reasoning.temporal_reasoning import TemporalReasoningSystem
from core.domain.cross_domain_grounding import (
    CrossDomainGrounder, StructuralObservation, GroundingOutcome)

ROUTING_WORLD = ["LOCATED(pkt,N1)", "LINK(N1,N2)", "UP(N2)", "LINK(N2,N3)", "UP(N3)"]
ROUTING_GOAL  = ["LOCATED(pkt,N3)"]

async def main():
    db = await get_unified_database(); await db.initialize()
    store = get_rule_store()
    rules = await store.executable_rules(domain_id="kite17")
    print("learned rules available:", [r.rule_id for r in rules])

    print("\nA. DIRECT TRANSFER — learned rule against the renamed domain")
    sf = [Fact.parse(f) for f in ROUTING_WORLD]
    gf = [Fact.parse(f) for f in ROUTING_GOAL]
    g = ground_for_problem(rules, sf, gf)
    print("   operators grounded:", len(g.operators))
    res = TemporalReasoningSystem().plan_for_state_goal(
        [f.to_formula() for f in gf], {"conditions": [f.to_formula() for f in sf]}, g.to_actions())
    print("   planning:", res.status.name, "steps:", len(res.steps))
    print("   -> direct transfer:", "WORKS" if res.steps else "DOES NOT OCCUR")

    print("\nB. STRUCTURAL TRANSFER — same shape, opaque element labels")
    # Roles only. Naming them 'node' or 'packet' would hand over the answer.
    obs = StructuralObservation(
        observation_id="edu03_routing",
        elements=("e1", "e2", "e3", "e4"),
        relations=(("e1", "situated_in", "e2"),
                   ("e2", "connects_to", "e3"),
                   ("e3", "admits", "e1"),
                   ("e2", "connects_to", "e4")),
        description="an entity situated in a place, places connected, places admitting entities")
    print("   searchable:", obs.is_searchable, f"({len(obs.relations)} relations)")
    grounder = CrossDomainGrounder(db)
    result = await grounder.ground(obs)
    print("   outcome           :", result.outcome.name)
    # A @property since cross_domain_grounding was last changed; calling it
    # raised TypeError: 'bool' object is not callable.
    print("   usable for transfer:", result.is_usable_for_transfer)
    print("   correspondences   :", len(getattr(result, "correspondences", []) or []))
    for c in (getattr(result, "correspondences", []) or [])[:4]:
        print("      ", c)
    if getattr(result, "note", ""):
        print("   note:", result.note[:150])
    gaps = getattr(result, "epistemic_gaps", None) or []
    for gp in gaps[:3]:
        print("   gap :", str(gp)[:120])
asyncio.run(main())
