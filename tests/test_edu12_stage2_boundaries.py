#!/usr/bin/env python3
"""Stage 2's boundaries, checked rather than intended.

Stage 2 asks whether a FROZEN system can be educated. Three separations make
the answer meaningful, and each one, if breached, produces a number that looks
like learning and is not:

    the teacher may not answer the exam
    the teacher may not write knowledge
    Torin commits before it is told

Every test here tries to breach one and asserts it is caught.
"""

import json
import sys
from pathlib import Path

import pytest

EDU12 = Path(__file__).resolve().parents[1] / "experiments" / "edu" / "EDU-12"
sys.path.insert(0, str(EDU12))

from lesson import (LearningKind, Phase, classify_learning,  # noqa: E402
                    run_phase, teach)


class _Response:
    def __init__(self, model_calls=0, route=None):
        self.answer = "x"
        self.derived = True
        self.basis = "stub"
        self.route = route or ["reason_about", "neural_bridge"]
        self.model_calls = model_calls
        self.verified = True
        self.is_unknown = False


class _Coordinator:
    def __init__(self, model_available=False):
        self.model_available = model_available


# ---- the teacher may not answer the exam --------------------------------

@pytest.mark.parametrize("phase", [Phase.COLD_RETRIEVAL, Phase.EXAMINATION,
                                   Phase.TRANSFER])
def test_the_exam_phases_require_a_detached_teacher(phase):
    assert phase.teacher_must_be_detached


def test_instruction_and_guided_practice_may_use_the_teacher():
    assert not Phase.INSTRUCTION.teacher_must_be_detached
    assert not Phase.GUIDED.teacher_must_be_detached


@pytest.mark.asyncio
async def test_a_model_call_during_the_examination_breaches_the_lesson(monkeypatch):
    """An improvement whose route ends in 'teacher -> answer' is not a
    capability, so the lesson is discarded rather than scored."""
    import lesson

    async def answered_by_the_model(item, coordinator, authority):
        return _Response(model_calls=1, route=["reason_about", "neural_bridge",
                                               "ReasoningMode.NEURAL"])

    monkeypatch.setattr(lesson, "attempt", answered_by_the_model)

    result = await run_phase(Phase.EXAMINATION, [{"id": "q1", "answer": "x"}],
                             _Coordinator(), None, lambda i, r: "correct")
    assert result.breaches, "a model-answered exam item was accepted"
    assert "on its route" in result.breaches[0]
    assert result.model_calls == 1


@pytest.mark.asyncio
async def test_an_attached_teacher_breaches_before_a_single_item_is_sat(monkeypatch):
    import lesson

    async def substrate_only(item, coordinator, authority):
        return _Response(model_calls=0)

    monkeypatch.setattr(lesson, "attempt", substrate_only)

    result = await run_phase(Phase.EXAMINATION, [{"id": "q1", "answer": "x"}],
                             _Coordinator(model_available=True), None,
                             lambda i, r: "correct")
    assert any("still attached" in b for b in result.breaches)


@pytest.mark.asyncio
async def test_a_clean_examination_records_no_breach(monkeypatch):
    """The guard must also stay quiet when nothing is wrong, or it is noise."""
    import lesson

    async def substrate_only(item, coordinator, authority):
        return _Response(model_calls=0)

    monkeypatch.setattr(lesson, "attempt", substrate_only)

    result = await run_phase(Phase.EXAMINATION, [{"id": "q1", "answer": "x"}],
                             _Coordinator(model_available=False), None,
                             lambda i, r: "correct")
    assert not result.breaches
    assert result.score == 1 and result.of == 1


# ---- the teacher may not write knowledge --------------------------------

@pytest.mark.asyncio
async def test_taught_material_never_becomes_knowledge():
    """"25% means 25 out of 100" is not evidence because a teacher said it."""
    from core.learning.learning_authority import SubstrateLearning

    authority = SubstrateLearning()
    authority.register_contributor("qwen", "teacher")

    admitted = await teach(authority, "qwen",
                           [{"id": "l1", "concept": "percentage",
                             "content": "25% means 25 out of 100"}],
                           domain_id="mathematics")
    assert admitted[0]["accepted"] is True
    assert admitted[0]["became_knowledge"] is False

    metrics = await authority.metrics()
    assert metrics["contributions_promoted_to_knowledge"] == 0


@pytest.mark.asyncio
async def test_an_unregistered_teacher_cannot_teach():
    from core.learning.learning_authority import SubstrateLearning

    authority = SubstrateLearning()
    admitted = await teach(authority, "stranger", [{"id": "l1"}], domain_id="x")
    assert admitted[0]["accepted"] is False


# ---- what counts as learning is classified ------------------------------

def test_learning_is_classified_not_aggregated():
    taught = [{"content": "Percentage change is the difference divided by the "
                          "original value times one hundred",
               "example": {"original": 40, "new": 50}}]

    verbatim = {"prompt": "Percentage change is the difference divided by the "
                          "original value times one hundred"}
    assert classify_learning(verbatim, taught) is LearningKind.RETRIEVAL

    unseen = {"prompt": "A value rises from 12 to 15. What is the percentage change"}
    assert classify_learning(unseen, taught) is LearningKind.GENERALIZATION

    composed = {"prompt": "anything", "composes": ["ratio", "percentage"]}
    assert classify_learning(composed, taught) is LearningKind.COMPOSITION


# ---- the sealed stage-3 exams -------------------------------------------

def test_the_stage3_exams_are_sealed_with_their_metadata():
    sealed = json.loads((EDU12 / "SEALED_EXAMS.json").read_text())
    assert sealed["exam_id"] == "EDU-12_STAGE3"
    assert sealed["frozen_against"] == "EDU-12_S0_ADMISSIBLE"

    for subject, exam in sealed["exams"].items():
        assert exam["posttest_seal"] and exam["transfer_seal"]
        assert exam["items"], subject
        for item in exam["items"]:
            assert item["item_hash"] and item["target_capability"]
            assert item["required_cognitive_operations"]
            assert item["exam"] in ("posttest", "transfer")


def test_the_sealed_exams_still_match_the_subject_files():
    """If an exam is edited after sealing, this fails -- which is the point."""
    import importlib.util

    from exam_seal import seal

    sealed = json.loads((EDU12 / "SEALED_EXAMS.json").read_text())
    for name, entry in sealed["exams"].items():
        spec = importlib.util.spec_from_file_location(
            name, EDU12 / "subjects" / f"{name}.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        assert seal(module.POSTTEST) == entry["posttest_seal"], f"{name} posttest changed"
        assert seal(module.TRANSFER) == entry["transfer_seal"], f"{name} transfer changed"


def test_teaching_takes_lessons_and_has_no_way_to_receive_exam_items():
    """The teacher is handed instructional material and Torin's declared state,
    never the questions. Enforced by the signature: `teach` accepts lessons."""
    import inspect

    signature = inspect.signature(teach)
    assert "lessons" in signature.parameters
    assert not any(p in signature.parameters
                   for p in ("posttest", "transfer", "exam", "answers"))


# ---- severance must be global, or the exam leaks -------------------------

def test_detaching_the_coordinator_alone_leaves_the_model_reachable():
    """THE HOLE THIS CLOSES.

    Clearing `coordinator.llm` and the bridge's `llm_service` does not detach
    the model from TOOLS: they fetch it themselves via `get_llm_service()`. A
    programming item routed to `generate_function` would therefore have been
    answered by the teacher during a held-out exam while the harness reported
    model_calls=0 -- the reasoning route would look clean because the model was
    reached down an entirely different path.
    """
    import inspect

    from core.tools import code_generation_tools

    source = inspect.getsource(code_generation_tools.GenerateFunctionTool.execute)
    assert "get_llm_service" in source, (
        "if this tool no longer fetches the model itself, revisit whether "
        "global severance is still required")


def test_severance_replaces_the_global_accessor_and_verifies_it_took():
    import core.services.unified_llm as unified_llm
    from lesson import TeacherStillReachable, attach_teacher, detach_teacher

    class _Coordinator:
        llm = object()
        teacher_model = object()
        neural_bridge = None

        @property
        def model_available(self):
            return self.llm is not None

    original = unified_llm.get_llm_service
    coordinator = _Coordinator()
    try:
        detach_teacher(coordinator)
        assert coordinator.llm is None
        # The path tools use must now refuse rather than hand back a model.
        with pytest.raises(TeacherStillReachable):
            unified_llm.get_llm_service()
    finally:
        attach_teacher(coordinator, original and object())
        unified_llm.get_llm_service = original

    assert unified_llm.get_llm_service is original, "severance was not reversed"


def test_reattaching_restores_the_original_accessor():
    import core.services.unified_llm as unified_llm
    from lesson import attach_teacher, detach_teacher

    class _Coordinator:
        llm = object()
        teacher_model = None
        neural_bridge = None

        @property
        def model_available(self):
            return self.llm is not None

    original = unified_llm.get_llm_service
    coordinator = _Coordinator()
    detach_teacher(coordinator)
    attach_teacher(coordinator, "teacher")
    assert unified_llm.get_llm_service is original
    assert coordinator.teacher_model == "teacher"
