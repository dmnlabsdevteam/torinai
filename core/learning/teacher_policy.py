#!/usr/bin/env python3
"""Which lesson to teach next, decided by measurement rather than intuition.

    A prospective counterexample has discriminating value only if competing
    hypotheses make different predictions for it.

That sentence is the whole module, and it was learned by getting it wrong. In
EDU-06 a negative was constructed with the item already sitting in the
DESTINATION. Every surviving hypothesis predicted the same observable outcome
there, so the lesson contradicted nothing, and induction happily learned an
operator with no source precondition at all -- the identical defect KITE had
before mv_no_AT_SOURCE. The example LOOKED like a good negative. It taught
nothing.

So the teacher does not judge a lesson by whether it is a negative, by whether
it feels instructive, or by whether a model says it is. It computes what the
lesson would separate.

WHY THIS BINDS A MODEL TOO. Torin is meant to accept plug-in LLM teachers.
A model is free to PROPOSE lessons -- proposing is what models are good at --
but a proposal is scored here before it is taught, and a lesson that separates
nothing is rejected no matter how confident or well-argued its proposer was.
The policy is the authority; the model is a source of candidates. That is the
same division the substrate applies everywhere else: the model expands the
hypothesis space, the substrate decides what is admissible.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from core.learning.rule_induction import CandidateRule, Fact, TrainingExample

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LessonScore:
    """What one prospective lesson would actually settle."""
    discrimination: float
    viable_hypotheses: int
    separated: int
    #: whether each hypothesis FIRES, for readability. Separation is
    #: computed on predicted STATE, which is what an observer could see.
    predictions: Tuple[bool, ...] = ()
    reason: str = ""

    @property
    def is_worth_teaching(self) -> bool:
        """A lesson every hypothesis answers identically settles nothing."""
        return self.separated > 0

    @property
    def is_decisive(self) -> bool:
        """Splits the version space as evenly as it can be split."""
        return self.discrimination >= 0.5


def _bindings(rule: CandidateRule, example: TrainingExample) -> Optional[Dict[str, str]]:
    """Variable bindings if the rule's action matches the one taken, else None."""
    if rule.action is None or example.action is None:
        return None
    if rule.action.predicate != example.action.predicate:
        return None
    if rule.action.arity != example.action.arity:
        return None
    bindings: Dict[str, str] = {}
    for slot, value in zip(rule.action.args, example.action.args):
        if slot.startswith("?"):
            if bindings.setdefault(slot, value) != value:
                return None
        elif slot != value:
            return None
    return bindings


def fires(rule: CandidateRule, example: TrainingExample) -> bool:
    """Would this rule's preconditions all hold in this situation?"""
    bindings = _bindings(rule, example)
    if bindings is None:
        return False
    for condition in rule.preconditions:
        grounded = condition.substitute(bindings)
        if not grounded.is_ground or grounded not in example.before:
            return False
    return True


def predicts(rule: CandidateRule, example: TrainingExample) -> frozenset:
    """The WORLD STATE this rule predicts after the lesson -- not whether it fires.

    THE DISTINCTION IS THE WHOLE POINT, and getting it wrong is what produced
    the EDU-06 defect. Two hypotheses can disagree about whether a rule applies
    and still predict the SAME observable outcome, because the effect it would
    have added was already true. Nothing separates them: the world looks
    identical either way, so the lesson eliminates neither.

    Scoring on `fires` calls such a lesson decisive. Scoring on the predicted
    STATE calls it what it is -- worthless -- which is the answer that would
    have prevented the missing precondition.
    """
    if not fires(rule, example):
        return frozenset(example.before)
    bindings = _bindings(rule, example) or {}
    state = set(example.before)
    for fact in rule.effects.delete:
        state.discard(fact.substitute(bindings))
    for fact in rule.effects.add:
        state.add(fact.substitute(bindings))
    return frozenset(state)


def score_lesson(hypotheses: Sequence[CandidateRule],
                 lesson: TrainingExample) -> LessonScore:
    """How much of the version space would this lesson collapse?

    `discrimination` is the fraction of hypothesis PAIRS the lesson separates,
    which peaks at an even split. A lesson every hypothesis agrees on scores 0
    however dramatic it looks.
    """
    if len(hypotheses) < 2:
        return LessonScore(0.0, len(hypotheses), 0, (),
                           "fewer than two viable hypotheses: nothing to separate")

    states = [predicts(h, lesson) for h in hypotheses]
    separated = sum(1 for i in range(len(states))
                    for j in range(i + 1, len(states))
                    if states[i] != states[j])
    total_pairs = len(states) * (len(states) - 1) // 2
    discrimination = (separated / total_pairs) if total_pairs else 0.0

    distinct = len({tuple(sorted(str(f) for f in state)) for state in states})
    if separated == 0:
        reason = ("every viable hypothesis predicts the same outcome here; this "
                  "lesson cannot eliminate any of them")
    else:
        reason = (f"{len(states)} hypotheses predict {distinct} distinct "
                  f"outcomes; {separated} pair(s) separated")
    return LessonScore(round(discrimination, 4), len(hypotheses), separated,
                       tuple(fires(h, lesson) for h in hypotheses), reason)


def expected_remaining_ambiguity(hypotheses: Sequence[CandidateRule],
                                 lesson: TrainingExample) -> Tuple[float, Dict[str, int]]:
    """How much of the version space would SURVIVE this observation, in expectation.

    Pair counting answers "does anything disagree". That is the right question
    for two or three hypotheses and the wrong one for thousands: a lesson that
    peels off a single outlier scores nearly as many pairs as one that halves
    the space, because both are dominated by the size of the larger part.

    What a teacher actually wants to minimise is what remains. Observing the
    world partitions the viable set by predicted outcome; exactly one block
    survives, and without knowing which, the expected survivor count is

        sum(|block|^2) / |space|

    which is minimised by an even split and equals |space| when every
    hypothesis predicts the same thing -- a lesson that teaches nothing.
    """
    if not hypotheses:
        return 0.0, {}
    blocks: Dict[Any, int] = {}
    for rule in hypotheses:
        key = tuple(sorted(str(f) for f in predicts(rule, lesson)))
        blocks[key] = blocks.get(key, 0) + 1
    total = len(hypotheses)
    expected = sum(size * size for size in blocks.values()) / total
    return expected, {"blocks": len(blocks), "largest": max(blocks.values()),
                      "total": total}


def information_gain(hypotheses: Sequence[CandidateRule],
                     lesson: TrainingExample) -> float:
    """Hypotheses eliminated in expectation. Zero when the lesson settles nothing."""
    expected, _ = expected_remaining_ambiguity(hypotheses, lesson)
    return len(hypotheses) - expected


def choose_lesson(hypotheses: Sequence[CandidateRule],
                  candidates: Sequence[TrainingExample],
                  ) -> Tuple[Optional[TrainingExample], LessonScore]:
    """The lesson that separates the most, or (None, why not).

    Returns None rather than the least-bad option: teaching a lesson that
    settles nothing spends a real observation and moves the learner nowhere,
    and reporting it as progress is how a curriculum appears to be working.
    """
    best: Tuple[Optional[TrainingExample], LessonScore] = (
        None, LessonScore(0.0, len(hypotheses), 0, (), "no candidate separates anything"))
    best_gain = 0.0
    for candidate in candidates:
        score = score_lesson(hypotheses, candidate)
        if score.separated == 0:
            continue
        # Ranked by EXPECTED ELIMINATION, not by pairs separated. With a large
        # version space the two disagree: peeling off one outlier separates
        # almost as many pairs as halving the space.
        gain = information_gain(hypotheses, candidate)
        if gain > best_gain:
            best, best_gain = (candidate, score), gain
    return best


@dataclass
class TeacherPolicy:
    """The authority over what may be taught. Models propose; this decides.

    `review()` is the gate every lesson passes through, whatever produced it --
    a hand-written curriculum, a generator, or a language model asked for
    counterexamples. It has no opinion about the source and no way to be
    persuaded: the only input is what the lesson would separate.
    """

    #: Below this a lesson is refused outright.
    MIN_SEPARATION: int = 1

    accepted: List[str] = field(default_factory=list)
    rejected: List[Tuple[str, str]] = field(default_factory=list)

    def review(self, hypotheses: Sequence[CandidateRule],
               lesson: TrainingExample,
               proposer: str = "unknown") -> Tuple[bool, LessonScore]:
        """Admit or refuse one proposed lesson, and say why."""
        score = score_lesson(hypotheses, lesson)
        identifier = lesson.evidence_id or "<unidentified>"
        if score.separated < self.MIN_SEPARATION:
            self.rejected.append((identifier, score.reason))
            logger.info(
                "TeacherPolicy REFUSED lesson %s from %s: %s",
                identifier, proposer, score.reason)
            return False, score
        self.accepted.append(identifier)
        logger.info("TeacherPolicy accepted lesson %s from %s: %s",
                    identifier, proposer, score.reason)
        return True, score

    def statistics(self) -> Dict[str, Any]:
        return {
            "accepted": len(self.accepted),
            "rejected": len(self.rejected),
            "rejection_reasons": [reason for _id, reason in self.rejected],
        }


__all__ = ["LessonScore", "TeacherPolicy", "predicts", "fires",
           "score_lesson", "choose_lesson", "information_gain",
           "expected_remaining_ambiguity"]
