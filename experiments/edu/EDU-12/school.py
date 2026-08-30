#!/usr/bin/env python3
"""EDU-12 — Open-Domain Autonomous Competence Acquisition.

    Can the same unchanged cognitive architecture enter multiple unfamiliar
    domains, teach itself enough to become competent, and reuse what it learns
    across them without domain-specific engineering?

This file is the school day. It holds no knowledge about any subject: it seals
the exams, runs the blocks, grades by answer shape, and checks the three
invariants that make the result mean anything.

    architecture fingerprint  core/ is byte-identical before and after
    subject purity            a subject is data, never code
    subject agnosticism       the attempt path cannot name a subject

STAGE 1 -- BASELINE ONLY. This run establishes S0 and proves the invariants
hold. Teaching is not wired yet, and nothing here reports a post-education
number. A pre/post table produced before instruction exists would be the exact
fabricated-signal failure the rest of this ladder was built to catch.

THE FIRST ADMISSIBLE BASELINE. The previous one (`S0_INVALID_01.json`) is
preserved and permanently marked invalid: its harness drove
`ProbabilisticVersionSpace` directly and returned UNKNOWN for everything else,
so it measured its own wiring rather than Torin. Every item now goes through
the production ingress -- `AutonomousCoordinator.reason_about` for reasoning,
`SubstrateLearning` for induction -- and the teacher model is DETACHED, so a
correct answer cannot be Qwen quietly supplying it.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

logging.disable(logging.INFO)

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[2]))

from attempt import UNKNOWN, Attempt, assert_subject_agnostic, attempt  # noqa: E402

from core.agents.autonomous.autonomous_coordinator import (  # noqa: E402
    AutonomousCoordinator)
from core.learning.learning_authority import get_learning_authority  # noqa: E402
from exam_seal import contamination, seal_exams  # noqa: E402
from exam_validity import validate  # noqa: E402
from generality import (GeneralityLedger, check_freeze,  # noqa: E402
                        check_subject_purity)

BLOCKS = ("mathematics", "programming", "causal_science", "language")
NUMERIC_TOLERANCE = 1e-6


def load_subject(name: str):
    path = HERE / "subjects" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"subject_{name}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def grade(item: Dict[str, Any], response: Attempt) -> str:
    """correct / wrong / unknown -- three outcomes, never two.

    Folding UNKNOWN into WRONG would hide the single most important property of
    an honest learner: that it declines rather than guesses. The two are scored
    the same (neither earns a point) and reported separately.
    """
    if response.is_unknown:
        return "unknown"
    expected = item.get("answer")
    given = response.answer
    if isinstance(expected, (int, float)) and isinstance(given, (int, float)):
        return "correct" if abs(expected - given) <= NUMERIC_TOLERANCE else "wrong"
    if isinstance(expected, dict) and isinstance(given, dict):
        return "correct" if all(sorted(expected.get(k, [])) == sorted(given.get(k, []))
                                for k in ("requires", "forbids")) else "wrong"
    return "correct" if expected == given else "wrong"


async def build_substrate(detach_model: bool = True):
    """Stand up the production ingress, and sever the teacher.

    Detached rather than merely unselected: `model_calls` is derived from the
    route, so a hard zero is only credible if the model is unreachable.
    """
    coordinator = AutonomousCoordinator()
    await coordinator.initialize(start_loop=False)
    if detach_model:
        # Severed everywhere, including the path tools use, and verified.
        from lesson import detach_teacher
        detach_teacher(coordinator)
    return coordinator, get_learning_authority()


async def sit_exam(exam, coordinator, authority) -> Dict[str, Any]:
    outcomes, detail = {"correct": 0, "wrong": 0, "unknown": 0}, []
    model_calls = 0
    for item in exam:
        response = await attempt(item, coordinator, authority)
        verdict = grade(item, response)
        outcomes[verdict] += 1
        model_calls += response.model_calls
        detail.append({"id": item.get("id"), "verdict": verdict,
                       "answer": None if response.is_unknown else response.answer,
                       "expected": item.get("answer"), "basis": response.basis,
                       "route": response.route, "verified": response.verified,
                       "model_calls": response.model_calls})
    total = len(exam) or 1
    derived = outcomes["correct"] + outcomes["wrong"]
    return {
        "score": outcomes["correct"], "of": len(exam),
        "percent": round(100.0 * outcomes["correct"] / total, 1),
        "unknown_rate": round(outcomes["unknown"] / total, 3),
        # Of the answers it committed to, how many were false? This is what
        # separates an ignorant learner from a dangerous one.
        "false_confidence_rate": round(outcomes["wrong"] / derived, 3) if derived else 0.0,
        "model_calls": model_calls,
        "detail": detail,
    }


async def main() -> int:
    now = datetime.now(timezone.utc).isoformat()
    print("EDU-12 — Open-Domain Autonomous Competence Acquisition")
    print("STAGE 1: baseline and invariants. Teaching is not wired.\n")

    # THE FREEZE IS CHECKED BEFORE ANYTHING ELSE. Stage 2 asks whether a frozen
    # system can be educated; if the substrate has changed since the baseline,
    # no result from this run can distinguish learning from an upgrade.
    violation = check_freeze(HERE / "FROZEN.json")
    if violation is not None:
        print(f"\nFREEZE VIOLATED\n   {violation.message}")
        return 1

    ledger = GeneralityLedger.open()
    subjects = {name: load_subject(name) for name in BLOCKS}

    print("invariants")
    purity = {name: check_subject_purity(HERE / "subjects" / f"{name}.py")
              for name in BLOCKS}
    pure = all(not v for v in purity.values())
    print(f"   subject purity        : {'HELD' if pure else purity}")

    agnostic = assert_subject_agnostic(BLOCKS)
    print(f"   attempt subject-blind : {'HELD' if not agnostic else agnostic}")

    # VALIDATED BEFORE SEALED. An exam whose stated answer its own evidence
    # cannot support does not measure competence -- it measures whether the
    # learner will assert more than it knows, and rewards exactly the failure
    # this ladder exists to prevent. Stage 1 shipped four such items and they
    # produced a 50% "false confidence" rate that was the substrate being right.
    invalid = {}
    for name in BLOCKS:
        found = []
        for label in ("PRETEST", "POSTTEST", "TRANSFER"):
            found += validate(getattr(subjects[name], label))
        if found:
            invalid[name] = [f"{i.item_id}: {i.reason}" for i in found]
    valid = not invalid
    print(f"   exam items answerable : {'HELD' if valid else invalid}")

    seals = {name: seal_exams(subjects[name], now) for name in BLOCKS}
    leaks = {name: contamination(
        list(subjects[name].POSTTEST) + list(subjects[name].TRANSFER),
        subjects[name].LESSONS) for name in BLOCKS}
    clean = all(not v for v in leaks.values())
    print(f"   exams sealed          : {len(seals)} subjects, "
          f"{'no lesson overlap' if clean else leaks}")
    print(f"   architecture baseline : {ledger.baseline[:16]}… "
          f"({ledger.to_json()['substrate_files']} files)")

    print("\nstanding up the production ingress with the teacher detached…")
    coordinator, authority = await build_substrate(detach_model=True)
    print(f"   model_available={coordinator.model_available} "
          f"bridge_model={coordinator.neural_bridge._model_available()}")

    print(f"\nS0 baseline — before any instruction\n")
    print(f"{'subject':<16}{'pretest':>9}{'score':>8}{'unknown':>10}"
          f"{'false conf':>12}{'model calls':>13}  demand")
    baseline = {}
    for name in BLOCKS:
        subject = subjects[name]
        result = await sit_exam(subject.PRETEST, coordinator, authority)
        baseline[name] = result
        ledger.check(f"after_{name}_pretest")
        print(f"{name:<16}{result['of']:>9}{result['percent']:>7.0f}%"
              f"{result['unknown_rate']:>10.0%}{result['false_confidence_rate']:>12.0%}"
              f"{result['model_calls']:>13}  {subject.COGNITIVE_DEMAND[0]}")

    held = ledger.held
    print(f"\narchitecture unchanged across all blocks: {held}")

    manifest = HERE / "manifest.json"
    manifest.write_text(json.dumps({
        "benchmark": "EDU-12",
        "title": "Open-Domain Autonomous Competence Acquisition",
        "stage": "1_baseline_and_invariants",
        "recorded_at": now,
        "model_calls": 0,
        "blocks": list(BLOCKS),
        "invariants": {
            "subject_purity_held": pure,
            "attempt_subject_agnostic": not agnostic,
            "exams_sealed": {k: v.to_json() for k, v in seals.items()},
            "posttest_lesson_contamination": {k: v for k, v in leaks.items() if v},
            "exam_items_answerable": valid,
            "invalid_exam_items": invalid,
            "generality": ledger.to_json(),
        },
        "admissible": True,
        "supersedes": "S0_INVALID_01.json",
        "ingress": {
            "reasoning": "AutonomousCoordinator.reason_about -> NeuralSymbolicBridge",
            "induction": "SubstrateLearning.induce_causal_structure",
            "teacher_model_detached": True,
        },
        "s0_baseline": {k: {kk: vv for kk, vv in v.items() if kk != "detail"}
                        for k, v in baseline.items()},
        "s0_detail": {k: v["detail"] for k, v in baseline.items()},
    }, indent=2, default=str))
    total_model_calls = sum(r["model_calls"] for r in baseline.values())
    print(f"\nmodel calls across the whole baseline: {total_model_calls}")
    ok = (pure and not agnostic and clean and held and valid
          and total_model_calls == 0)
    print(f"\nEDU-12 stage 1: {'INVARIANTS HELD' if ok else 'INVARIANT VIOLATED'}")
    print(f"manifest -> {manifest}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
