#!/usr/bin/env python3
"""DOM-KG-01 — Knowledge-gap vs. competence discrimination in the domain system.

Does the substrate distinguish a DECLARATIVE knowledge gap ("I have little
information about X") from a PROCEDURAL competence deficit ("I lack the operators
to produce X"), within a MATURE domain, keeping the two axes orthogonal?

Two axes under test:
  * declarative knowledge coverage  = Domain.maturity_score  (structural_complexity
    of the taught concept graph) — "how much I KNOW about this subject".
  * operator competence             = the belief "learned the operators of domain X"
    (bayesian_uncertainty) — "what I can DO in this subject".

Four hypotheses (see docs/TR-2026-09_domain_knowledge_gaps.md):
  H1  gap-type discrimination      — CONCEPT_GAP (unrepresented) vs OPERATOR_GAP
                                     (represented, no producer), structurally.
  H2  routing / attribution        — CONCEPT_GAP -> ESCALATE (acquire),
                                     OPERATOR_GAP -> LEARN_OPERATOR (explore).
  H3  axis orthogonality           — teaching raises coverage, NOT operator competence.
  H4  declarative gap detection    — an in-domain unanswerable registers a
                                     KNOWN_UNKNOWN, competence untouched, no false gaps.

Run:  ./venv_torin/bin/python3 experiments/DOM-KG-01/experiment.py
Writes experiments/DOM-KG-01/result.json.
"""
from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import logging
logging.disable(logging.INFO)

RESULTS: dict = {}


def check(tag: str, ok: bool, evidence: str) -> None:
    RESULTS[tag] = {"pass": bool(ok), "evidence": evidence}
    print(f"  [{'PASS' if ok else 'FAIL'}] {tag}: {evidence}", flush=True)


async def run() -> dict:
    from core.integration.universal_domain_master import (
        UniversalDomainMaster, DeficitType, EpistemicDeficit, LearningOperation,
        get_universal_domain_master)
    from core.database import get_database_manager
    from core.semantics.conversation import Conversation
    from core.domain.domain_registry import get_domain_registry
    from core.reasoning.bayesian_uncertainty import get_uncertainty_system

    # ── H1: gap-type discrimination (pure structural classifier) ──────────────
    print("H1  gap-type discrimination (procedural)")
    t_op, ev_op = UniversalDomainMaster._classify_deficit(
        "flies", world_predicates={"bird"}, vocabulary={"bird", "flies"},
        actionable=[], executable=[], actable=set(), executable_effect_predicates=set())
    t_con, ev_con = UniversalDomainMaster._classify_deficit(
        "photosynthesizes", world_predicates={"bird"}, vocabulary={"bird", "flies"},
        actionable=[], executable=[], actable=set(), executable_effect_predicates=set())
    check("H1.operator_gap", t_op is DeficitType.OPERATOR_GAP, f"{t_op.value} {ev_op}")
    check("H1.concept_gap", t_con is DeficitType.CONCEPT_GAP, f"{t_con.value} {ev_con}")
    check("H1.distinct", t_op is not t_con, f"{t_op.value} != {t_con.value}")

    # ── H2: routing & attribution separation ──────────────────────────────────
    print("H2  routing / attribution separation")
    d_con = EpistemicDeficit("d", DeficitType.CONCEPT_GAP, target_predicate="x")
    d_op = EpistemicDeficit("d", DeficitType.OPERATOR_GAP, target_predicate="x")
    check("H2.concept_escalates", d_con.operation is LearningOperation.ESCALATE,
          f"CONCEPT_GAP -> {d_con.operation.value} :: {d_con.remedy_reason}")
    check("H2.operator_learns", d_op.operation is LearningOperation.LEARN_OPERATOR,
          f"OPERATOR_GAP -> {d_op.operation.value}")
    check("H2.operations_distinct", d_con.operation is not d_op.operation,
          f"{d_con.operation.value} != {d_op.operation.value}")

    # ── build a MATURE taught domain (fictional, to isolate from wordnet) ─────
    db = get_database_manager(); await db.initialize()
    NAMES = ["glindar", "morphel", "brythe", "quennel", "vornak", "drayle",
             "zephinx", "merlex", "hoblin", "peregor", "vorm"]
    async def scrub():
        await db.execute_query("DELETE FROM unified.concepts WHERE name = ANY($1)", (NAMES,))
        await db.execute_query("DELETE FROM unified.concept_aliases WHERE alias = ANY($1)", (NAMES,))
        for f in NAMES:
            await db.execute_query("DELETE FROM unified.domains WHERE domain_id = $1", (f"domain_{f}",))
    await scrub()
    c = Conversation()
    for s in ["a zephinx is a morphel", "a morphel is a glindar", "a brythe is a glindar",
              "a quennel is a glindar", "a vornak is a glindar", "a drayle is a glindar"]:
        await c.teach(s)
    udm = get_universal_domain_master(); await udm.initialize()
    res = await udm.discover_concept_domains(from_field="conversation")
    dom = next((o for o in res["outcomes"] if o["field"] in NAMES), None)
    domain_id = dom["domain_id"] if dom else None
    RESULTS["_domain"] = {"domain_id": domain_id,
                          "maturity_at_crystallization": dom["maturity"] if dom else None}
    print(f"    built {domain_id} maturity={dom['maturity'] if dom else '?'}")

    reg = get_domain_registry()
    # ── H3: axis orthogonality ────────────────────────────────────────────────
    print("H3  axis orthogonality")
    m1 = reg.domains[domain_id].maturity_score
    c1 = (await udm.ensure_competence_belief(domain_id)).posterior_probability
    for s in ["a merlex is a morphel", "a hoblin is a morphel", "a peregor is a morphel"]:
        await c.teach(s)
    await udm.discover_concept_domains(from_field="conversation")
    await reg.initialize()
    m2 = reg.domains[domain_id].maturity_score
    c2 = (await udm.ensure_competence_belief(domain_id)).posterior_probability
    check("H3.coverage_rose", m2 > m1, f"maturity {round(m1,4)} -> {round(m2,4)}")
    check("H3.competence_unchanged", abs(c2 - c1) < 1e-9,
          f"operator competence {round(c1,4)} -> {round(c2,4)}")

    # ── H4: declarative gap detection ─────────────────────────────────────────
    print("H4  declarative gap detection")
    unc = get_uncertainty_system()
    before = len([u for u in unc.known_unknowns.values() if u.domain == domain_id])
    detect = getattr(udm, "detect_knowledge_gap", None)
    if detect is None:
        check("H4.gap_detected", False, "no detect_knowledge_gap (declarative tracker unwired)")
    else:
        gap = await detect(domain_id, subject="zephinx", relation="eats")
        after = len([u for u in unc.known_unknowns.values() if u.domain == domain_id])
        c3 = (await udm.ensure_competence_belief(domain_id)).posterior_probability
        check("H4.gap_detected", gap is not None and after == before + 1,
              f"known_unknowns[{domain_id}] {before} -> {after}")
        check("H4.competence_untouched", abs(c3 - c2) < 1e-9,
              f"operator competence {round(c2,4)} -> {round(c3,4)}")
        check("H4.gap_resolvable", bool(gap and gap.information_value > 0 and gap.can_be_resolved),
              f"info_value={round(gap.information_value,3)} resolvable={gap.can_be_resolved}")
        oob = await detect(domain_id, subject="not_a_member", relation="eats")
        check("H4.no_false_gap_oob", oob is None, "out-of-domain subject -> no gap")
        await c.teach("a zephinx eats vorm")
        await udm.discover_concept_domains(from_field="conversation")
        present = await detect(domain_id, subject="zephinx", relation="eats")
        check("H4.no_false_gap_present", present is None, "relation present -> no fabricated gap")

    # ── H5: a detected gap is CONSUMED by intrinsic motivation ────────────────
    print("H5  known-unknown consumption (gap -> exploration target -> acquisition goal)")
    from core.reasoning.epistemic_engine import get_epistemic_engine
    ku = unc.register_known_unknown(
        question="what is a glindar made of", domain=domain_id,
        blocking_factors=["unrepresented relation (test)"])
    targets = get_epistemic_engine().get_unstable_regions()
    gap_targets = [t for t in targets if t.target_type == "knowledge_gap"
                   and t.metadata.get("known_unknown_id") == ku.unknown_id]
    check("H5.gap_is_exploration_target", len(gap_targets) == 1,
          f"knowledge_gap targets for this gap: {len(gap_targets)}")
    if gap_targets:
        t = gap_targets[0]
        check("H5.routed_to_acquisition",
              t.metadata.get("requires_acquisition") is True
              and "requires_epistemic_output" not in t.metadata,
              f"requires_acquisition={t.metadata.get('requires_acquisition')}, "
              f"belief_gate={'requires_epistemic_output' in t.metadata}")
    from core.agents.autonomous.intrinsic_motivation import IntrinsicMotivationSystem
    goals = await IntrinsicMotivationSystem()._generate_epistemic_goals(max_goals=8)
    acq = [g for g in goals if g.metadata.get("known_unknown_id") == ku.unknown_id]
    check("H5.becomes_acquisition_goal", len(acq) >= 1,
          f"acquisition goals generated for the gap: {len(acq)}")
    unc.known_unknowns.pop(ku.unknown_id, None)

    await scrub()
    passed = all(v["pass"] for k, v in RESULTS.items() if not k.startswith("_"))
    RESULTS["_summary"] = {"all_pass": passed, "checks": sum(1 for k in RESULTS if not k.startswith("_"))}
    return RESULTS


if __name__ == "__main__":
    out = asyncio.run(run())
    stamp = datetime.now(timezone.utc).isoformat()
    Path(__file__).with_name("result.json").write_text(
        json.dumps({"run_at": stamp, "results": out}, indent=2))
    print("\nALL PASS:", out["_summary"]["all_pass"])
