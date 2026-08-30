#!/usr/bin/env python3
"""EDU-15: a teacher-led programming lesson, with the world as the examiner.

    Qwen may explain programming and propose candidate code.
    It may not attest that any of it is correct.
    Execution establishes behaviour; that is what the substrate learns from.

Four competences are measured SEPARATELY, because they are different claims:

    PRETEST    what the substrate could construct before any teaching
    ASSISTED   what it could construct while the teacher was reachable
    SUBSTRATE  what it could construct with the teacher BLOCKED
    TRANSFER   what it could construct that was never shown

The third is the only one that is evidence of learning, and it is the one that
is easiest to fake -- so during the exam the model policy is set to
STRICT_MODEL_FREE. A reach for the teacher is then BLOCKED and COUNTED rather
than trusted not to happen: "zero model calls during the exam" becomes a
measurement instead of an assurance.
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import curriculum
import student
import world


@dataclass
class Telemetry:
    """Everything the run is allowed to claim afterwards."""

    model_calls_instruction: int = 0
    model_calls_exam: int = 0
    model_calls_exam_blocked: int = 0
    program_executions: int = 0
    sandbox_confirmations: int = 0
    sandbox_contradictions: int = 0
    unknown_responses: int = 0
    lessons_ingested: int = 0
    ingestion_failures: int = 0
    pretest: str = ""
    assisted: str = ""
    substrate: str = ""
    transfer: str = ""
    false_confidence: int = 0        # produced code that was wrong
    per_task: Dict[str, Any] = field(default_factory=dict)
    limits: List[str] = field(default_factory=list)


class Teacher:
    """The model, under contract. Everything it says is a proposal."""

    def __init__(self, telemetry: Telemetry):
        self.telemetry = telemetry
        self._service = None

    async def _svc(self):
        if self._service is None:
            from core.services.unified_llm import get_llm_service
            svc = get_llm_service()
            if hasattr(svc, "__await__"):
                svc = await svc
            await svc.initialize()
            self._service = svc
        return self._service

    async def say(self, prompt: str, max_tokens: int = 320,
                  timeout: float = 300.0) -> str:
        svc = await self._svc()
        self.telemetry.model_calls_instruction += 1
        try:
            reply = await asyncio.wait_for(
                svc.generate(prompt=prompt,
                             system_prompt=curriculum.TEACHER_CONTRACT,
                             max_tokens=max_tokens, temperature=0.3,
                             enable_thinking=False),
                timeout=timeout)
        except asyncio.TimeoutError:
            return ""
        text = str((reply or {}).get("content") or "")
        # Qwen3.6 emits chain-of-thought; the lesson is what follows it.
        if "</think>" in text:
            text = text.split("</think>", 1)[1]
        return text.strip()


async def ingest_lesson(text: str, telemetry: Telemetry) -> None:
    """Put the teacher's lesson into the substrate as a CONTRIBUTION.

    It enters as a candidate with no evidence roots, which is the standing rule
    for anything a model produces: it may propose, and only the world can make
    it evidence.
    """
    from core.semantics.conversation import Conversation

    talk = Conversation()
    for line in [l.strip() for l in text.splitlines() if l.strip()][:6]:
        if len(line) < 12 or line.startswith(("#", ">", "-", "*", "```")):
            continue
        try:
            await talk.teach(line)
            telemetry.lessons_ingested += 1
        except Exception:
            telemetry.ingestion_failures += 1


async def attempt(task, telemetry: Telemetry, phase: str) -> Optional[world.Grade]:
    """One task: the substrate constructs, the sandbox judges."""
    tried = await student.ask_substrate(task)
    if tried.said_unknown and not tried.source:
        telemetry.unknown_responses += 1
    if not tried.source:
        telemetry.per_task[f"{phase}:{task.task_id}"] = "no code produced"
        return None

    graded = world.grade(task, tried.source)
    telemetry.program_executions += 1
    if graded.passed:
        telemetry.sandbox_confirmations += 1
    else:
        telemetry.sandbox_contradictions += 1
        telemetry.false_confidence += 1        # it produced code and was wrong
    telemetry.per_task[f"{phase}:{task.task_id}"] = graded.summary
    return graded


async def run(quick: bool = False) -> Telemetry:
    from core.database import get_database_manager
    from core.model_policy import (ModelPolicy, model_telemetry,
                                   reset_model_telemetry, set_model_policy)

    db = get_database_manager()
    await db.initialize()

    telemetry = Telemetry()
    ok, why = world.available()
    if not ok:
        telemetry.limits.append(f"sandbox unavailable: {why}")
        return telemetry

    reset_model_telemetry()
    teacher = Teacher(telemetry)

    # ── 0. COLD PRE-TEST, teacher detached ──────────────────────────────────
    print("\n── COLD PRE-TEST (teacher detached) " + "─" * 34)
    passed = 0
    for task in curriculum.PRETEST:
        graded = await attempt(task, telemetry, "pretest")
        passed += bool(graded and graded.passed)
        print(f"   {task.task_id:18} {graded.summary if graded else 'no code':>7}")
    telemetry.pretest = f"{passed}/{len(curriculum.PRETEST)}"
    print(f"   PRETEST COMPETENCE: {telemetry.pretest}")

    # ── 1-4. LESSONS ────────────────────────────────────────────────────────
    lessons = curriculum.LESSONS[:1] if quick else curriculum.LESSONS
    for name, description in lessons:
        print(f"\n── LESSON: {name} " + "─" * 46)
        lesson = await teacher.say(
            f"Teach the concept {name}: {description}. "
            f"Give a short explanation, two contrasting examples as Python code, "
            f"and one counterexample that a beginner would get wrong.")
        if not lesson:
            telemetry.limits.append(f"teacher produced no lesson for {name}")
            continue
        print("   teacher:", lesson.replace("\n", " ")[:150])

        # The world checks the teacher's own examples. It may claim an output;
        # only running it establishes one.
        for snippet in _code_blocks(lesson)[:2]:
            run_result = world.execute(snippet)
            telemetry.program_executions += 1
            if run_result.ran and run_result.exit_code == 0:
                telemetry.sandbox_confirmations += 1
            else:
                telemetry.sandbox_contradictions += 1
                print(f"   world CONTRADICTS the teacher's example: "
                      f"{(run_result.stderr or run_result.error or '').strip()[:80]}")

        await ingest_lesson(lesson, telemetry)

    # ── ASSISTED competence, teacher still reachable ────────────────────────
    print("\n── ASSISTED (teacher reachable) " + "─" * 38)
    passed = 0
    for task in curriculum.EXAM[:2] if quick else curriculum.EXAM:
        graded = await attempt(task, telemetry, "assisted")
        passed += bool(graded and graded.passed)
        print(f"   {task.task_id:22} {graded.summary if graded else 'no code':>7}")
    telemetry.assisted = f"{passed}/{len(curriculum.EXAM[:2] if quick else curriculum.EXAM)}"

    instruction_calls = telemetry.model_calls_instruction

    # ── TEACHER-OFF EXAM, enforced ──────────────────────────────────────────
    print("\n── TEACHER-OFF EXAM (model policy STRICT) " + "─" * 28)
    before = _llm_counts(model_telemetry())
    previous = set_model_policy(ModelPolicy.STRICT_MODEL_FREE)
    try:
        passed = 0
        for task in curriculum.EXAM:
            graded = await attempt(task, telemetry, "exam")
            passed += bool(graded and graded.passed)
            print(f"   {task.task_id:22} {graded.summary if graded else 'no code':>7}")
        telemetry.substrate = f"{passed}/{len(curriculum.EXAM)}"
    finally:
        set_model_policy(previous)

    after = _llm_counts(model_telemetry())
    telemetry.model_calls_exam = after["executed"] - before["executed"]
    telemetry.model_calls_exam_blocked = after["blocked"] - before["blocked"]
    telemetry.model_calls_instruction = instruction_calls

    # TRANSFER: the composition task nothing demonstrated.
    transfer = telemetry.per_task.get("exam:exam_c_total_above_ten", "no code produced")
    telemetry.transfer = transfer
    return telemetry


def _code_blocks(text: str) -> List[str]:
    """Code from a markdown reply, with its own indentation preserved.

    `.strip()` alone removed the leading newline but not the common indent that
    markdown puts on a fenced block inside a list item, so every extracted
    snippet began mid-indent and failed with `IndentationError: unexpected
    indent`. That was recorded as the world CONTRADICTING the teacher -- a
    fabricated contradiction produced by the harness, which is worse than no
    check at all: it would have taught the substrate that correct examples
    were wrong.
    """
    import re
    import textwrap

    blocks = re.findall(r"```(?:python)?[ \t]*\r?\n(.*?)```", text, re.S | re.I)
    cleaned = []
    for block in blocks:
        body = textwrap.dedent(block.rstrip())
        # A block may still carry a uniform indent that dedent cannot see
        # because the first line is blank.
        body = "\n".join(body.splitlines())
        if body.strip():
            cleaned.append(body)
    return cleaned


def _llm_counts(snapshot: Dict[str, Any]) -> Dict[str, int]:
    blob = json.loads(json.dumps(snapshot, default=str))

    def find(node):
        if isinstance(node, dict):
            if "llm" in node and isinstance(node["llm"], dict) and "attempts" in node["llm"]:
                return node["llm"]
            for value in node.values():
                found = find(value)
                if found:
                    return found
        return None

    llm = find(blob) or {}
    return {"attempts": int(llm.get("attempts", 0)),
            "executed": int(llm.get("executed", 0)),
            "blocked": int(llm.get("blocked", 0))}


if __name__ == "__main__":
    quick = "--quick" in sys.argv
    result = asyncio.run(run(quick=quick))
    print("\n" + "=" * 70)
    print("PRETEST   (before teaching)      :", result.pretest)
    print("ASSISTED  (teacher reachable)    :", result.assisted)
    print("SUBSTRATE (teacher BLOCKED)      :", result.substrate)
    print("TRANSFER  (composition task)     :", result.transfer)
    print("-" * 70)
    print("model calls during instruction   :", result.model_calls_instruction)
    print("model calls during exam          :", result.model_calls_exam, "(must be 0)")
    print("model reaches BLOCKED during exam:", result.model_calls_exam_blocked)
    print("program executions               :", result.program_executions)
    print("sandbox confirmations            :", result.sandbox_confirmations)
    print("sandbox contradictions           :", result.sandbox_contradictions)
    print("lessons ingested / failed        :", result.lessons_ingested, "/", result.ingestion_failures)
    print("UNKNOWN responses                :", result.unknown_responses)
    print("false confidence (wrong code)    :", result.false_confidence)
    if result.limits:
        print("LIMITS RECORDED                  :")
        for limit in result.limits:
            print("   -", limit)
    print("=" * 70)
