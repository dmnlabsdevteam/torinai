#!/usr/bin/env python3
"""A language model may PROPOSE lessons. TeacherPolicy decides which are taught.

Torin is meant to accept plug-in models as helpers and teachers, and this is the
shape that makes that safe: the model is a source of candidates, never an
authority over the curriculum. Every proposal is parsed deterministically,
scored for what it would actually separate, and admitted or refused on that
alone. A confident proposal that settles nothing is refused exactly as fast as
a diffident one.

THE MODEL CANNOT REACH THE LEARNER. It returns text. This module turns text
into candidate TrainingExamples and hands them to the policy; nothing here
writes to the rule store, and a proposal that cannot be parsed is DECLINED
rather than repaired into something plausible. Guessing at malformed output is
how a model's mistake becomes the substrate's belief.

What a model is genuinely useful for here is coverage: enumerating situations a
fixed generator would not think to try. What it must never do is decide whether
one of them is worth teaching, because that question has an answer that can be
computed and does not need an opinion.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from core.learning.rule_induction import CandidateRule, Fact, TrainingExample
from core.learning.teacher_policy import LessonScore, TeacherPolicy

logger = logging.getLogger(__name__)


@dataclass
class ProposalOutcome:
    """What happened to one model-proposed lesson."""
    raw: str
    parsed: Optional[TrainingExample] = None
    admitted: bool = False
    score: Optional[LessonScore] = None
    declined_reason: str = ""


@dataclass
class TeachingSession:
    proposed: int = 0
    unparseable: int = 0
    admitted: List[TrainingExample] = field(default_factory=list)
    outcomes: List[ProposalOutcome] = field(default_factory=list)

    @property
    def refused(self) -> int:
        return self.proposed - len(self.admitted) - self.unparseable

    def summary(self) -> Dict[str, Any]:
        return {
            "proposed": self.proposed,
            "admitted": len(self.admitted),
            "refused_as_non_separating": self.refused,
            "unparseable": self.unparseable,
        }


class LLMTeacher:
    """Asks a model for lessons; lets the policy decide which are taught."""

    #: Asks for FACTS, not prose. A lesson is a state, an action and a state;
    #: anything the model cannot express that way is not a lesson.
    PROMPT = (
        "You are proposing test situations for a learner that is trying to work "
        "out the preconditions of an action.\n\n"
        "The learner is considering these competing rules:\n{hypotheses}\n\n"
        "Propose {count} situations that would help decide between them. A good "
        "situation is one where the rules DISAGREE about what the world looks "
        "like afterwards.\n\n"
        "THE STATE IS CLOSED-WORLD. List only facts that are TRUE. Anything you "
        "do not list is false. To test what happens when a condition is "
        "missing, simply LEAVE IT OUT -- do not write a negation, and do not "
        "use `!`, `not`, or `-`. `PRED(a,b)` is the only accepted form.\n\n"
        "Return JSON only:\n"
        '{{"lessons":[{{"id":"...","before":["PRED(a,b)", ...],'
        '"action":"ACT(a,b,c)","after":["PRED(a,b)", ...]}}]}}\n\n'
        "Use only these predicates: {predicates}\n"
        "Use only these constants: {constants}\n"
    )

    def __init__(self, llm_service=None, policy: Optional[TeacherPolicy] = None):
        self._llm = llm_service
        self.policy = policy or TeacherPolicy()

    def _service(self):
        if self._llm is None:
            from core.services.unified_llm import get_llm_service
            self._llm = get_llm_service()
        return self._llm

    @staticmethod
    def _parse_lesson(item: Dict[str, Any]) -> Tuple[Optional[TrainingExample], str]:
        """One proposal -> a TrainingExample, or a reason it is not one.

        DECLINED, never repaired. A half-understood lesson taught anyway is the
        model's error entering the learner's evidence with a teacher's
        authority.
        """
        try:
            before = tuple(Fact.parse(f) for f in (item.get("before") or []))
            after = tuple(Fact.parse(f) for f in (item.get("after") or []))
            raw_action = item.get("action")
            action = Fact.parse(raw_action) if raw_action else None
        except (ValueError, TypeError, AttributeError) as e:
            return None, f"not parseable as facts: {e}"
        if not before:
            return None, "no before-state: a lesson must describe a situation"
        identifier = str(item.get("id") or "").strip()
        if not identifier:
            return None, "no id: a lesson must be citable as evidence"
        # The label is what the WORLD does, so it is derived from the states the
        # proposal reports rather than taken from any 'positive' field.
        return TrainingExample(before=before, action=action, after=after,
                               positive=frozenset(after) != frozenset(before),
                               evidence_id=identifier), ""

    async def propose(
        self,
        hypotheses: Sequence[CandidateRule],
        predicates: Sequence[str],
        constants: Sequence[str],
        count: int = 4,
    ) -> TeachingSession:
        """Ask for lessons, parse them, and let the policy rule on each."""
        session = TeachingSession()
        prompt = self.PROMPT.format(
            hypotheses="\n".join(f"  R{i}: {h.to_formula()}"
                                 for i, h in enumerate(hypotheses)),
            count=count,
            predicates=", ".join(predicates),
            constants=", ".join(constants),
        )

        try:
            # STRUCTURED INTERPRETATION, not generation. A reasoning model
            # spends its budget deliberating before answering: measured here,
            # `generate()` returned 1200 tokens of prose cut off mid-sentence
            # and zero parseable lessons. `extract_structured` sets
            # chat_template_kwargs={"enable_thinking": false}, which is the only
            # lever that actually suppresses it -- reasoning_effort and a
            # /no_think prefix both failed.
            raw = await self._service().extract_structured(
                prompt=prompt, max_tokens=1600, temperature=0.4)
        except Exception as e:
            # No fabricated lessons. A teacher that invents a curriculum when
            # its proposer is unavailable is not a fallback, it is a different
            # teacher wearing the same name.
            logger.error("LLM teacher unavailable: %s; proposing nothing", e)
            return session

        payload = raw.get("content") if isinstance(raw, dict) else str(raw)
        payload = payload or ""
        start, end = payload.find("{"), payload.rfind("}")
        if start < 0 or end <= start:
            logger.warning("LLM teacher returned no JSON object")
            return session
        try:
            parsed = json.loads(payload[start:end + 1])
        except json.JSONDecodeError as e:
            logger.warning("LLM teacher output was not valid JSON: %s", e)
            return session

        for item in (parsed.get("lessons") or []):
            session.proposed += 1
            outcome = ProposalOutcome(raw=json.dumps(item, separators=(",", ":")))
            if not isinstance(item, dict):
                session.unparseable += 1
                outcome.declined_reason = "proposal is not an object"
                session.outcomes.append(outcome)
                continue
            lesson, why = self._parse_lesson(item)
            if lesson is None:
                session.unparseable += 1
                outcome.declined_reason = why
                session.outcomes.append(outcome)
                continue
            outcome.parsed = lesson
            admitted, score = self.policy.review(hypotheses, lesson, proposer="llm")
            outcome.admitted, outcome.score = admitted, score
            if admitted:
                session.admitted.append(lesson)
            session.outcomes.append(outcome)

        logger.info("LLM teacher: %s", session.summary())
        return session


def model_can_serve(llm_service: Any) -> bool:
    """Whether the teacher's model is actually able to serve a request right now.

    The service object first, then the backend — the presence of a service is not
    enough: the remote backend only marks the device REMOTE once the shared
    llama-server answers, and the in-process backend only sets .model after a
    successful load. Asking whether a model COULD serve is a routing question.
    """
    if llm_service is None:
        return False
    if getattr(llm_service, "model", None) is not None:
        return True
    device = getattr(llm_service, "device", None)
    return getattr(device, "value", device) == "remote"


def teacher_reachable() -> bool:
    """Whether the teacher — the one consultable model — can serve right now.

    The teacher OWNS the model access. Callers that want to know whether they
    could escalate to a teacher ask HERE rather than holding their own model
    handle. Never forces a load: it reports on the existing service singleton, so
    it is a routing/reachability question and consulting no model at all is not
    recorded as model use. Honest on failure — an unreachable teacher is False,
    not an exception.
    """
    try:
        from core.services.unified_llm import get_llm_service
        return model_can_serve(get_llm_service())
    except Exception:
        return False


__all__ = ["LLMTeacher", "TeachingSession", "ProposalOutcome",
           "model_can_serve", "teacher_reachable"]
