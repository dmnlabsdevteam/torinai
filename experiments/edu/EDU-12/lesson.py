#!/usr/bin/env python3
"""A 90-minute class, with the boundaries enforced rather than intended.

    cold retrieval -> instruction -> guided practice -> examination -> transfer

The experiment only means something if three separations hold, so each is
CHECKED and a lesson that breaches one is marked invalid rather than scored:

    THE TEACHER MAY NOT ANSWER THE EXAM. Cold retrieval, examination and
    transfer run with the model detached, and every answer's route is
    inspected: a single model call in those phases invalidates the lesson. An
    improvement whose route ends in "teacher -> answer" is not a capability.

    THE TEACHER MAY NOT WRITE KNOWLEDGE. Everything it produces enters through
    `SubstrateLearning.contribute()` as a CANDIDATE with zero evidence roots.
    "25% means 25 out of 100" is not evidence because a teacher said it.

    TORIN COMMITS BEFORE IT IS TOLD. In guided practice the answer is recorded
    before feedback is given. The reverse order -- solution, then reproduction,
    then "learned" -- measures copying.

WHAT COUNTS AS LEARNING IS CLASSIFIED, NOT ASSUMED:

    RETRIEVAL       the exam item was taught almost verbatim
    GENERALIZATION  same operation, unseen instance
    COMPOSITION     requires combining taught pieces, no demonstrated solution

Only the third is evidence relevant to generality, so an aggregate score that
does not separate them can hide a lesson that taught nothing but answers.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence

from attempt import attempt


class Phase(Enum):
    COLD_RETRIEVAL = "cold_retrieval"
    INSTRUCTION = "instruction"
    GUIDED = "guided"
    EXAMINATION = "examination"
    TRANSFER = "transfer"

    @property
    def teacher_must_be_detached(self) -> bool:
        return self in (Phase.COLD_RETRIEVAL, Phase.EXAMINATION, Phase.TRANSFER)


class LearningKind(Enum):
    RETRIEVAL = "retrieval"
    GENERALIZATION = "generalization"
    COMPOSITION = "composition"


#: Above this token overlap with taught material, an exam item is retrieval.
RETRIEVAL_OVERLAP = 0.60
_TOKEN = re.compile(r"[a-z0-9]+")


def _tokens(text: Any) -> frozenset:
    return frozenset(_TOKEN.findall(str(text).lower()))


def classify_learning(item: Dict[str, Any],
                      taught: Sequence[Dict[str, Any]]) -> LearningKind:
    """What an answer to this item would demonstrate."""
    if len(item.get("composes") or []) >= 2:
        return LearningKind.COMPOSITION
    item_tokens = _tokens(item.get("prompt", ""))
    for lesson in taught:
        material = _tokens(lesson.get("content", "")) | _tokens(lesson.get("example", ""))
        if material and item_tokens:
            overlap = len(item_tokens & material) / len(item_tokens | material)
            if overlap >= RETRIEVAL_OVERLAP:
                return LearningKind.RETRIEVAL
    return LearningKind.GENERALIZATION


@dataclass
class PhaseResult:
    phase: Phase
    answers: List[Dict[str, Any]] = field(default_factory=list)
    model_calls: int = 0
    breaches: List[str] = field(default_factory=list)

    @property
    def score(self) -> int:
        return sum(1 for a in self.answers if a["verdict"] == "correct")

    @property
    def of(self) -> int:
        return len(self.answers)


@dataclass
class LessonResult:
    subject: str
    concept: str
    phases: Dict[str, PhaseResult] = field(default_factory=dict)
    contributions: List[Dict[str, Any]] = field(default_factory=list)
    breaches: List[str] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        """A lesson that breached a boundary is not scored, it is discarded."""
        return not self.breaches

    def delta(self) -> Optional[int]:
        cold = self.phases.get(Phase.COLD_RETRIEVAL.value)
        exam = self.phases.get(Phase.EXAMINATION.value)
        if cold is None or exam is None or not cold.of or not exam.of:
            return None
        return round(100.0 * exam.score / exam.of) - round(100.0 * cold.score / cold.of)


class TeacherStillReachable(AssertionError):
    """Detachment did not take. Any result gathered now is inadmissible."""


def detach_teacher(coordinator) -> None:
    """Sever the teacher EVERYWHERE, and verify the severance took.

    Clearing the coordinator and the bridge is not enough. Tools fetch the
    model themselves through `get_llm_service()`, so with only those two
    cleared a programming item routed to `generate_function` would be answered
    by the teacher during a held-out exam while the harness reported
    model_calls=0 -- the reasoning route would be clean because the model was
    reached down a different path entirely.

    Verified rather than assumed: severance that is merely attempted is the
    same failure as a capability that is merely claimed.
    """
    import core.services.unified_llm as unified_llm

    coordinator.llm = None
    coordinator.teacher_model = None
    if coordinator.neural_bridge is not None:
        coordinator.neural_bridge.llm_service = None

    if not hasattr(unified_llm, "_edu12_attached_service"):
        unified_llm._edu12_attached_service = unified_llm.get_llm_service

    def severed(*args, **kwargs):
        raise TeacherStillReachable(
            "a detached phase reached for the teacher; the model is severed")

    unified_llm.get_llm_service = severed

    if coordinator.model_available:
        raise TeacherStillReachable("the coordinator still reports a model")


def attach_teacher(coordinator, teacher_model) -> None:
    import core.services.unified_llm as unified_llm

    original = getattr(unified_llm, "_edu12_attached_service", None)
    if original is not None:
        unified_llm.get_llm_service = original

    coordinator.llm = teacher_model
    coordinator.teacher_model = teacher_model
    if coordinator.neural_bridge is not None:
        coordinator.neural_bridge.llm_service = teacher_model


async def run_phase(phase: Phase, items, coordinator, authority,
                    grade) -> PhaseResult:
    """Sit a set of items, and check the phase's boundary held while doing it."""
    result = PhaseResult(phase=phase)

    if phase.teacher_must_be_detached and coordinator.model_available:
        result.breaches.append(
            f"{phase.value}: the teacher was still attached when the phase began")

    for item in items:
        response = await attempt(item, coordinator, authority)
        verdict = grade(item, response)
        result.model_calls += response.model_calls
        result.answers.append({
            "id": item.get("id"), "verdict": verdict,
            "answer": None if response.is_unknown else response.answer,
            "expected": item.get("answer"), "basis": response.basis,
            "route": response.route, "model_calls": response.model_calls,
            "verified": response.verified,
        })
        if phase.teacher_must_be_detached and response.model_calls:
            result.breaches.append(
                f"{phase.value}: item {item.get('id')} was answered with a model "
                f"on its route ({' -> '.join(response.route)})")

    return result


async def teach(authority, teacher_name: str, lessons: Sequence[Dict[str, Any]],
                domain_id: str) -> List[Dict[str, Any]]:
    """Route instructional material through the contribution boundary.

    Nothing here becomes knowledge. Each lesson is admitted as a proposal, and
    the record of what was admitted is kept so a later capability can be traced
    to what was said to Torin -- and, more importantly, so it can be shown that
    what was said never counted as evidence.
    """
    from core.learning.learning_authority import Contribution, ContributionKind

    admitted = []
    for lesson in lessons:
        admission = await authority.contribute(Contribution(
            contributor=teacher_name,
            kind=ContributionKind.LESSON,
            payload=lesson,
            rationale=str(lesson.get("concept", "")),
            domain_id=domain_id,
        ))
        admitted.append({
            "lesson": lesson.get("id"), "concept": lesson.get("concept"),
            "accepted": admission.accepted, "reason": admission.reason,
            "status": admission.status.value if admission.status else None,
            "became_knowledge": admission.is_knowledge,
        })
    return admitted


__all__ = ["Phase", "LearningKind", "PhaseResult", "LessonResult",
           "classify_learning", "run_phase", "teach",
           "detach_teacher", "attach_teacher", "RETRIEVAL_OVERLAP"]
