"""A lesson is worth teaching only if it separates hypotheses that survive.

Pinned from the EDU-06 mistake: a negative was built with the item already in
the DESTINATION, so every viable hypothesis predicted the same outcome, the
lesson contradicted nothing, and induction learned an operator missing a
precondition. It looked like a good counterexample.
"""
import json

import pytest

from core.learning.rule_induction import (
    CandidateRule, Fact, RuleEffects, TrainingExample)
from core.learning.teacher_policy import (
    TeacherPolicy, choose_lesson, predicts, score_lesson)

F = Fact.parse


def rule(body, add, delete, action):
    return CandidateRule(
        body=frozenset(F(b) for b in body),
        effects=RuleEffects(add=frozenset(F(a) for a in add),
                            delete=frozenset(F(d) for d in delete)),
        action=F(action))


#: The two hypotheses KITE was actually torn between.
WITHOUT_SOURCE = rule(["MOVE(?X,?A,?B)", "PATH(?A,?B)", "OPEN(?B)"],
                      ["AT(?X,?B)"], ["AT(?X,?A)"], "MOVE(?X,?A,?B)")
WITH_SOURCE = rule(["MOVE(?X,?A,?B)", "AT(?X,?A)", "PATH(?A,?B)", "OPEN(?B)"],
                   ["AT(?X,?B)"], ["AT(?X,?A)"], "MOVE(?X,?A,?B)")
VERSION_SPACE = [WITHOUT_SOURCE, WITH_SOURCE]


def lesson(before, evidence_id, positive=False):
    facts = tuple(F(f) for f in before)
    return TrainingExample(before=facts, action=F("MOVE(z,HALL,LAB)"),
                           after=facts, positive=positive, evidence_id=evidence_id)


def test_the_object_elsewhere_separates_the_hypotheses():
    """z is in a THIRD room: the broad rule fires, the narrow one does not."""
    score = score_lesson(VERSION_SPACE,
                         lesson(["AT(z,VAULT)", "PATH(HALL,LAB)", "OPEN(LAB)"], "good"))
    assert score.predictions == (True, False)
    assert score.separated == 1
    assert score.is_worth_teaching and score.is_decisive


def test_the_object_already_at_the_destination_separates_nothing():
    """The EDU-06 mistake. Both hypotheses agree, so the lesson settles nothing
    however much it looks like a counterexample."""
    score = score_lesson(VERSION_SPACE,
                         lesson(["AT(z,LAB)", "PATH(HALL,LAB)", "OPEN(LAB)"], "useless"))
    assert score.separated == 0
    assert not score.is_worth_teaching
    assert "same outcome" in score.reason


def test_the_policy_refuses_a_lesson_that_settles_nothing():
    policy = TeacherPolicy()
    admitted, score = policy.review(
        VERSION_SPACE,
        lesson(["AT(z,LAB)", "PATH(HALL,LAB)", "OPEN(LAB)"], "useless"),
        proposer="some_llm")
    assert admitted is False
    assert policy.statistics()["rejected"] == 1


def test_a_confident_proposer_gets_no_extra_weight():
    """A model may propose; the policy decides. The only input is what the
    lesson separates, so the same lesson from any source gets the same answer."""
    policy = TeacherPolicy()
    useless = lesson(["AT(z,LAB)", "PATH(HALL,LAB)", "OPEN(LAB)"], "useless")
    for proposer in ("qwen", "human_curriculum", "random_generator"):
        admitted, _ = policy.review(VERSION_SPACE, useless, proposer=proposer)
        assert admitted is False, f"{proposer} must not be able to force a null lesson"


def test_choose_lesson_returns_nothing_rather_than_the_least_bad():
    """Teaching a lesson that settles nothing spends a real observation and
    reports movement that did not happen."""
    useless = [lesson(["AT(z,LAB)", "PATH(HALL,LAB)", "OPEN(LAB)"], "u1"),
               lesson(["AT(z,LAB)", "PATH(HALL,LAB)", "OPEN(LAB)"], "u2")]
    chosen, score = choose_lesson(VERSION_SPACE, useless)
    assert chosen is None
    assert score.separated == 0


def test_choose_lesson_prefers_the_separating_candidate():
    useful = lesson(["AT(z,VAULT)", "PATH(HALL,LAB)", "OPEN(LAB)"], "useful")
    useless = lesson(["AT(z,LAB)", "PATH(HALL,LAB)", "OPEN(LAB)"], "useless")
    chosen, score = choose_lesson(VERSION_SPACE, [useless, useful])
    assert chosen is useful
    assert score.separated == 1


def test_one_hypothesis_cannot_be_separated():
    score = score_lesson([WITH_SOURCE],
                         lesson(["AT(z,VAULT)", "PATH(HALL,LAB)", "OPEN(LAB)"], "x"))
    assert score.separated == 0
    assert "fewer than two" in score.reason


# ---------------------------------------------------------------------------
# A plug-in model may propose. It may not decide.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_a_model_cannot_teach_a_lesson_that_separates_nothing():
    """The proposer is irrelevant to the verdict; only separation counts."""
    from core.learning.llm_teacher import LLMTeacher

    class _Model:
        async def extract_structured(self, **_):
            return {"content": json.dumps({"lessons": [
                # Confident, well-formed, and worthless: the object is already
                # at the destination, so both hypotheses predict the same world.
                {"id": "llm_useless", "before": ["AT(z,LAB)", "PATH(HALL,LAB)", "OPEN(LAB)"],
                 "action": "MOVE(z,HALL,LAB)", "after": ["AT(z,LAB)", "PATH(HALL,LAB)", "OPEN(LAB)"]},
                # Genuinely discriminating.
                {"id": "llm_useful", "before": ["AT(z,VAULT)", "PATH(HALL,LAB)", "OPEN(LAB)"],
                 "action": "MOVE(z,HALL,LAB)", "after": ["AT(z,VAULT)", "PATH(HALL,LAB)", "OPEN(LAB)"]},
            ]})}

    teacher = LLMTeacher(llm_service=_Model())
    session = await teacher.propose(VERSION_SPACE, ["AT", "PATH", "OPEN", "MOVE"],
                                    ["z", "HALL", "LAB", "VAULT"])
    admitted = [lesson.evidence_id for lesson in session.admitted]
    assert admitted == ["llm_useful"], f"policy admitted {admitted}"
    assert session.summary()["refused_as_non_separating"] == 1


@pytest.mark.asyncio
async def test_malformed_model_output_is_declined_not_repaired():
    from core.learning.llm_teacher import LLMTeacher

    class _Model:
        async def extract_structured(self, **_):
            return {"content": json.dumps({"lessons": [
                {"id": "no_before", "action": "MOVE(z,HALL,LAB)", "after": []},
                {"before": ["AT(z,HALL)"], "action": "MOVE(z,HALL,LAB)", "after": []},
                {"id": "bad_fact", "before": ["this is not a fact"],
                 "action": "MOVE(z,HALL,LAB)", "after": []},
            ]})}

    session = await LLMTeacher(llm_service=_Model()).propose(
        VERSION_SPACE, ["AT"], ["z"])
    assert session.summary()["unparseable"] == 3
    assert session.admitted == []


@pytest.mark.asyncio
async def test_an_unavailable_model_proposes_nothing_rather_than_inventing():
    from core.learning.llm_teacher import LLMTeacher

    class _Broken:
        async def extract_structured(self, **_):
            raise RuntimeError("model is down")

    session = await LLMTeacher(llm_service=_Broken()).propose(VERSION_SPACE, ["AT"], ["z"])
    assert session.proposed == 0 and session.admitted == []
