#!/usr/bin/env python3
"""EDU-04 — Level 4: cross-domain transfer of a self-induced rule, model-free.

WHAT IS BEING CLAIMED. Torin induced an operator from demonstrations in one
domain, projected it into its concept graph as structure, and then recognised
an unfamiliar situation in a different domain as an instance of that structure
-- with the evidence that warrants the correspondence, and without a model.

WHAT IS NOT BEING CLAIMED. The observation and the learned structure share a
ROLE VOCABULARY (`requires` / `adds` / `removes`). CrossDomainGrounder matches
raw relation labels and deliberately does not normalise relation classes, so
this measures transfer across ELEMENTS, not across relation naming. The
observation's elements are opaque (`e1`..`e4`): naming them `router` or `link`
would hand the matcher the answer through its input.

TWO CONTROLS, because GROUNDED alone does not distinguish transfer from a
matcher that grounds anything:

  DISTRACTOR  an observation of the same size with different roles must NOT
              ground. Without it, a permissive matcher passes.
  ABLATION    remove the edges the RULE contributed and the same observation
              must stop grounding. Without it, the demonstrations alone might
              be carrying the result and nothing would have been transferred
              from what was LEARNED.

The ablation is the one that matters. Demonstrations record what was observed
(`adds`, `removes`); only induction produces `requires`, because which facts an
action needed is exactly what generalization decides. If transfer survives the
ablation, it never depended on the rule.

THE ABLATION IS NOW SCOPED TO THE SOURCE DOMAIN, AND IT HAD TO BE.

As originally written the ablation deleted the rule's projected edges and
re-grounded against EVERY learned domain. That tests "does any structure Torin
holds carry this observation", which is not the claim -- and it stopped being a
valid control almost immediately. This benchmark was frozen as passing at
2026-08-19 18:37:48 UTC; the `archive` domain was taught at 19:16:40 UTC, 39
minutes later, and independently produced the same operator shape. From that
moment the ablated search grounded at support 1.00 via `archive:relocate`, so
the control reported failure while nothing about the rule had changed.

The fix is to ask the question the claim actually makes: can KITE17's learned
structure carry this observation, and does that depend on the induced rule.
`restrict_to_domains=(DOMAIN,)` scopes the search, so removing the rule's edges
severs the only support that could answer, and a second domain learning the
same shape can no longer stand in.

The unrestricted grounding is still run and still reported -- as CONTEXT, not
as a control. Redundant grounding across independently learned domains is a
real property worth recording; it just cannot be the thing an ablation tests.
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from core.database.unified_database_postgres import get_unified_database  # noqa: E402
from core.domain.cross_domain_grounding import (  # noqa: E402
    CrossDomainGrounder, StructuralObservation)
from core.domain.evidence_producers import submit_learned_rule  # noqa: E402
from core.learning.rule_store import INDUCTION_ROLES, get_rule_store  # noqa: E402
from core.model_policy import assert_model_free, model_telemetry  # noqa: E402

RULE = "rule_edbe5a8b4ad8"
DOMAIN = "kite17"

#: A routing situation. Elements are opaque; only the shape is given.
TARGET = StructuralObservation(
    observation_id="edu04_routing",
    elements=("e1", "e2", "e3", "e4"),
    relations=(("e1", "requires", "e2"), ("e1", "requires", "e3"),
               ("e1", "adds", "e4"), ("e1", "removes", "e2")),
    description="an operation requiring a location and a connection, "
                "adding one fact and retracting another")

#: Same element count, same relation count, different roles.
DISTRACTOR = StructuralObservation(
    observation_id="edu04_distractor",
    elements=("f1", "f2", "f3", "f4"),
    relations=(("f1", "composed_of", "f2"), ("f1", "part_of", "f3"),
               ("f1", "used_in", "f4"), ("f1", "opposes", "f2")),
    description="a compositional situation with no operator structure")


def _report(label, result):
    print(f"   {label:<12} {result.outcome.name:<14} "
          f"searched={result.structures_searched:<4} "
          f"domains={len(result.searched_domains):<3} "
          f"support={result.best_support:.2f}/{result.required_support:.2f} "
          f"transferable={result.is_usable_for_transfer}")
    return {
        "observation_id": result.observation_id,
        "outcome": result.outcome.name,
        "structures_searched": result.structures_searched,
        "best_support": round(result.best_support, 4),
        "required_support": result.required_support,
        "usable_for_transfer": result.is_usable_for_transfer,
        "searched_domains": list(result.searched_domains),
        "correspondences": [
            {"element": c.element, "concept_id": c.concept_id,
             "supporting_edges": [list(e) for e in c.supporting_edges],
             "evidence_ids": sorted(c.evidence_ids)}
            for c in result.correspondences],
    }


async def main() -> int:
    db = await get_unified_database()
    await db.initialize()
    store = get_rule_store()
    grounder = CrossDomainGrounder(db)

    stored = {r.rule_id: r for r in await store.load(domain_id=DOMAIN)}[RULE]
    roots = await store.evidence_roots(RULE, INDUCTION_ROLES)
    print(f"rule    : {RULE} | {stored.rule}")
    print(f"lineage : {sorted(roots)}")

    ingestion = await submit_learned_rule(stored, roots)
    print(f"projected: {ingestion.candidates} candidate(s), "
          f"{len(ingestion.created)} created, {len(ingestion.reinforced)} reinforced, "
          f"failures={ingestion.extraction_failures}")
    if not ingestion.read_successfully:
        print("ABORT: the rule could not be read as structure")
        return 1

    evidence_id = f"indrule_{ingestion.evidence_id.split('_', 1)[1]}"
    edges = await db.execute_query(
        "SELECT relation, target_concept_id, extractor FROM unified.concept_relations "
        "WHERE evidence_id = $1 ORDER BY relation, target_concept_id",
        (evidence_id,), fetch_all=True) or []
    print(f"\nedges contributed by the rule ({len(edges)}):")
    for e in edges:
        print(f"   {e['relation']:<9} -> {e['target_concept_id']}  [{e['extractor']}]")

    scope = (DOMAIN,)

    print(f"\nGROUNDING — scoped to {DOMAIN}, the domain whose rule is under test")
    transfer = _report("target", await grounder.ground(
        TARGET, restrict_to_domains=scope))
    distractor = _report("distractor", await grounder.ground(
        DISTRACTOR, restrict_to_domains=scope))

    print(f"\nABLATION — rule-derived edges removed, still scoped to {DOMAIN}")
    await db.execute_query(
        "DELETE FROM unified.concept_relations WHERE evidence_id = $1",
        (evidence_id,), commit=True)
    ablated = _report("target", await grounder.ground(
        TARGET, restrict_to_domains=scope))
    await submit_learned_rule(stored, roots)
    restored = _report("restored", await grounder.ground(
        TARGET, restrict_to_domains=scope))

    # CONTEXT, NOT A CONTROL. Reported so the redundancy is visible rather than
    # silently invalidating the ablation as it did before.
    print("\nUNSCOPED (context only — every learned domain)")
    unscoped = _report("target", await grounder.ground(TARGET))
    other_domains = sorted(set(unscoped["searched_domains"]) - {DOMAIN})
    print(f"   domains that could also answer: {other_domains}")

    telemetry = model_telemetry()
    assert_model_free("edu04_transfer")
    print(f"\nmodel: attempts={telemetry['attempts']} "
          f"executed={telemetry['executed']} policy={telemetry['policy']}")

    passed = (transfer["usable_for_transfer"]
              and not distractor["usable_for_transfer"]
              and not ablated["usable_for_transfer"]
              and restored["usable_for_transfer"]
              and telemetry["executed"] == 0)
    print(f"\nEDU-04: {'PASS' if passed else 'FAIL'}")

    manifest = Path(__file__).resolve().parent / "manifest.json"
    manifest.write_text(json.dumps({
        "benchmark": "EDU-04",
        "title": "Cross-Domain Transfer of a Self-Induced Rule",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "passed": passed,
        "memory_retrieval": "none",
        "model_calls": telemetry["executed"],
        "model_attempts": telemetry["attempts"],
        "source_domain": DOMAIN,
        "rule": {"rule_id": RULE, "formula": stored.rule.to_formula(),
                 "status": stored.status.value,
                 "induction_roots": sorted(roots)},
        "projection": {
            "evidence_id": evidence_id,
            "source_type": "induced_rule",
            "derivative": True,
            "extractor": "structured",
            "edges": [[e["relation"], e["target_concept_id"]] for e in edges],
        },
        "transfer": transfer,
        "search_scope": {
            "restricted_to": [DOMAIN],
            "why": ("the ablation must sever the only support that can answer; "
                    "unscoped, a second domain that learned the same shape "
                    "independently stands in and the control silently stops "
                    "testing anything"),
        },
        "controls": {"distractor": distractor,
                     "ablation_rule_edges_removed": ablated,
                     "after_restore": restored},
        "context_not_a_control": {
            "unscoped_grounding": unscoped,
            "note": ("every learned domain searched. GROUNDED here does not "
                     "support the claim -- it records that the substrate holds "
                     "redundant structure."),
        },
        "limits": {
            "shared_relation_vocabulary": True,
            "opaque_elements": True,
            "relation_class_normalisation": "not applied",
        },
    }, indent=2))
    print(f"manifest -> {manifest}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
