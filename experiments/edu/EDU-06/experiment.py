#!/usr/bin/env python3
"""EDU-06 — transfer between two REAL learned domains.

EDU-04 grounded a HAND-AUTHORED observation on a learned structure. That shows
a learned structure can carry an unfamiliar shape, but the shape was written by
the experimenter, so the objection stands: the target was not a domain, and
nothing had been learned about it.

This takes the observation FROM THE STORE. A structure that was learned in one
domain is stripped to opaque element labels and offered to the matcher with its
own domain excluded, so the only structures available to explain it were
learned somewhere else. If it grounds, knowledge acquired in one domain
recognised a situation in another.

TWO EXCLUSIONS, both required:
  * the source domain -- an observation derived from a structure matches that
    structure perfectly, which measures identity, not transfer
  * nothing else. The matcher sees every other domain and has to pick.

The controls are the same shape as EDU-04: a distractor built from relations
nobody uses must NOT ground, and grounding must survive being asked twice.
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
from core.model_policy import assert_model_free, model_telemetry  # noqa: E402


async def structure_of(db, hub: str):
    rows = await db.execute_query(
        "SELECT relation, target_concept_id FROM unified.concept_relations "
        "WHERE source_concept_id = $1 AND target_concept_id IS NOT NULL "
        "ORDER BY relation, target_concept_id", (hub,), fetch_all=True) or []
    # DISTINCT: repeated identical edges are one claim recorded by several
    # observations, not several claims.
    return sorted({(r["relation"], r["target_concept_id"]) for r in rows})


def anonymise(hub: str, edges):
    """Real structure -> opaque observation. Identities are destroyed; only
    the shape survives, which is the only thing that may carry the match."""
    labels, relations = {}, []
    for relation, target in edges:
        label = labels.setdefault(target, f"e{len(labels) + 1}")
        relations.append(("e0", relation, label))
    return StructuralObservation(
        observation_id=f"edu06_from_{hub.replace(':', '_')}",
        elements=("e0",) + tuple(labels.values()),
        relations=tuple(relations),
        description="a structure lifted from the store with its identities removed",
    ), labels


def report(label, result):
    print(f"   {label:<26} {result.outcome.name:<14} "
          f"searched={result.structures_searched:<4} "
          f"support={result.best_support:.2f}/{result.required_support:.2f} "
          f"transferable={result.is_usable_for_transfer}")
    return {
        "observation_id": result.observation_id,
        "outcome": result.outcome.name,
        "structures_searched": result.structures_searched,
        "best_support": round(result.best_support, 4),
        "usable_for_transfer": result.is_usable_for_transfer,
        "note": result.note,
        "correspondences": [
            {"element": c.element, "concept_id": c.concept_id,
             "supporting_edges": [list(e) for e in c.supporting_edges]}
            for c in result.correspondences],
    }


async def main() -> int:
    db = await get_unified_database()
    await db.initialize()
    grounder = CrossDomainGrounder(db)

    # The rule Torin INDUCED from demonstrations, model-free (EDU-01).
    source_hub = "kite17:move"
    source_domain = source_hub.split(":", 1)[0]
    edges = await structure_of(db, source_hub)
    print(f"source structure : {source_hub}")
    for relation, target in edges:
        print(f"   {relation:<10} -> {target}")

    observation, labels = anonymise(source_hub, edges)
    print(f"\nanonymised to    : {len(observation.relations)} relation(s), "
          f"{len(observation.elements)} opaque element(s)")
    print(f"excluded domain  : {source_domain} "
          f"(an observation matches its own source perfectly)")

    print("\nGROUNDING — only structures learned in OTHER domains are available")
    transfer = report("kite17 -> elsewhere",
                      await grounder.ground(observation,
                                            exclude_domains=(source_domain,)))
    for c in (await grounder.ground(observation,
                                    exclude_domains=(source_domain,))).correspondences[:4]:
        print(f"      {c.element} -> {c.concept_id}")

    distractor = StructuralObservation(
        observation_id="edu06_distractor",
        elements=("f0", "f1", "f2", "f3"),
        relations=(("f0", "rhymes_with", "f1"), ("f0", "tastes_like", "f2"),
                   ("f0", "older_than", "f3")),
        description="relations no learned structure uses")
    print("\nCONTROL")
    control = report("unused relations", await grounder.ground(distractor))

    telemetry = model_telemetry()
    assert_model_free("edu06_real_domain_transfer")

    matched = transfer["correspondences"][0]["concept_id"] if transfer["correspondences"] else None
    matched_domain = matched.split(":", 1)[0] if matched else None
    crossed = bool(matched_domain and matched_domain != source_domain)

    passed = (transfer["usable_for_transfer"] and crossed
              and not control["usable_for_transfer"]
              and telemetry["executed"] == 0)
    print(f"\nsource domain    : {source_domain}")
    print(f"matched domain   : {matched_domain}")
    print(f"crossed a domain : {crossed}")
    print(f"model            : attempts={telemetry['attempts']} executed={telemetry['executed']}")
    print(f"\nEDU-06: {'PASS' if passed else 'FAIL'}")

    manifest = Path(__file__).resolve().parent / "manifest.json"
    manifest.write_text(json.dumps({
        "benchmark": "EDU-06",
        "title": "Transfer Between Two Real Learned Domains",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "passed": passed,
        "model_calls": telemetry["executed"],
        "source_hub": source_hub,
        "source_domain": source_domain,
        "source_edges": [list(e) for e in edges],
        "observation_is_derived_from_the_store": True,
        "excluded_domains": [source_domain],
        "matched_domain": matched_domain,
        "crossed_a_domain_boundary": crossed,
        "transfer": transfer,
        "control_unused_relations": control,
    }, indent=2))
    print(f"manifest -> {manifest}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
