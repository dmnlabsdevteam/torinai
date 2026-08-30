#!/usr/bin/env python3
"""Deriving how to read a sentence, and putting it where reading happens.

`ReadingRegistry` exists so a DERIVED reading can be consulted before any model,
and `DerivedReadingFormalizer` already asks it on every formalization. Nothing
ever registered one. The registry was empty in every process that ever ran, the
formalizer returned nothing every time, and the conversation path fell through
to positional guessing plus a model asked to find the seams in the sentence.

That fallback is what produced the junk: `which_lines_belong_to_which_block` and
`you` admitted as entities, `write --a function count_o--> threshold` admitted
as a relation. Nothing was wrong with the ingress -- it faithfully admitted
whatever it was handed, and it was handed guesses.

    THE CONSTRUCTOR ALREADY EXISTS. `procedure_synthesis.derive_procedure`
    builds a procedure out of operators the substrate has already learned,
    accepting a candidate only when it produces the required answer on EVERY
    example. This supplies it the evidence and registers what comes back.

EDU-13 derived exactly this and proved it on seven held-out sentences whose
content words never appeared in the evidence, with zero model calls. It then
threw it away when the process exited. The only thing this module adds is that
the result survives into the running system.

NO MODEL IS INVOLVED AT ANY POINT.
"""

from __future__ import annotations

import logging
import threading
from typing import List, Optional, Tuple

from core.semantics.sentence_machine import (AFFIRMS, COPULAS, DENIES,
                                             DETERMINERS, FLAGS, INSTRUCTIONS,
                                             NEGATORS, SentenceMachine,
                                             tokenize)

logger = logging.getLogger(__name__)

#: Demonstrations of each instruction: (sentence, instructions run first).
#: EVIDENCE, NOT A GRAMMAR. Each row is the machine being shown one step, and
#: what the step is for is induced from the state change it causes.
DEMONSTRATIONS = {
    "BIND_SUBJECT": [("robin is a bird", []), ("vault holds gold", []),
                     ("the cat sees a dog", ["SKIP"])],
    "BIND_OBJECT": [("robin is a bird", ["BIND_SUBJECT", "SKIP", "SKIP"]),
                    ("vault holds gold", ["BIND_SUBJECT", "SKIP"]),
                    ("the cat sees a dog", ["SKIP", "BIND_SUBJECT", "SKIP", "SKIP"])],
    "MARK_NEGATIVE": [("robin is not a mammal", ["BIND_SUBJECT", "SKIP"]),
                      ("gold is not cheap", ["BIND_SUBJECT", "SKIP"]),
                      ("the cat is not a dog", ["SKIP", "BIND_SUBJECT", "SKIP"])],
    "EXTEND_SUBJECT": [("the smoke alarm is red", ["SKIP", "BIND_SUBJECT"]),
                       ("the fire alarm is loud", ["SKIP", "BIND_SUBJECT"])],
    "EXTEND_OBJECT": [("the alarm is a smoke detector",
                       ["SKIP", "BIND_SUBJECT", "SKIP", "SKIP", "BIND_OBJECT"]),
                      ("the pump is a fluid mover",
                       ["SKIP", "BIND_SUBJECT", "SKIP", "SKIP", "BIND_OBJECT"])],
    "SKIP": [("robin is a bird", ["BIND_SUBJECT"]),
             ("vault holds gold", ["BIND_SUBJECT"]),
             ("the cat sees a dog", [])],
    "EMIT": [("robin is a bird", ["BIND_SUBJECT", "SKIP", "SKIP", "BIND_OBJECT"]),
             ("vault holds gold", ["BIND_SUBJECT", "SKIP", "BIND_OBJECT"]),
             ("the cat is not a dog",
              ["SKIP", "BIND_SUBJECT", "SKIP", "MARK_NEGATIVE", "SKIP", "BIND_OBJECT"])],
}

#: One induction per register an instruction writes: a rule may only conclude
#: about terms its body binds.
TARGETS = {
    "BIND_SUBJECT": ["SUBJECT", "AT"], "BIND_OBJECT": ["OBJECT", "AT"],
    "EXTEND_SUBJECT": ["SUBJECT", "AT"], "EXTEND_OBJECT": ["OBJECT", "AT"],
    "MARK_NEGATIVE": ["POLARITY", "AT"], "SKIP": ["AT"], "EMIT": ["READING"],
}

#: Sentence, and what it means. Chosen to force the reading rather than flatter
#: it: a bare subject and one behind a determiner, an affirmative and a
#: negation, so no policy that ignores word class fits them all.
TAUGHT: List[Tuple[str, Tuple[str, str, str]]] = [
    ("robin is a bird", ("robin", "bird", AFFIRMS)),
    ("the vault is locked", ("vault", "locked", AFFIRMS)),
    ("a dog is an animal", ("dog", "animal", AFFIRMS)),
    ("robin is not a mammal", ("robin", "mammal", DENIES)),
    ("the engine is not cold", ("engine", "cold", DENIES)),

    # QUESTIONS. A question makes the same claim a statement does -- "is the
    # vault locked?" and "the vault is locked" relate the same two things -- and
    # differ only in what the asker wants done with it. Which is the query and
    # which the premise is decided by POSITION at formalization, not by grammar,
    # so a reading need not mark the form.
    #
    # It could not read one before, and the reason was teaching rather than
    # capability: every taught sentence put the subject first, so no procedure
    # covering them had to handle a sentence OPENING with a copula. The machine
    # could always express it -- SKIP(is), SKIP(the), BIND_SUBJECT, BIND_OBJECT,
    # EMIT -- nothing was ever asked to.
    #
    # Measured before: the derived reading settled 0 of 2 question cases while
    # the hand-written patterns settled both.
    ("is the vault locked", ("vault", "locked", AFFIRMS)),
    ("is robin a bird", ("robin", "bird", AFFIRMS)),
    ("is the engine not cold", ("engine", "cold", DENIES)),
    ("the smoke alarm is red", ("smoke_alarm", "red", AFFIRMS)),
    ("the fire alarm is loud", ("fire_alarm", "loud", AFFIRMS)),
    ("the alarm is a smoke detector", ("alarm", "smoke_detector", AFFIRMS)),

    # SUBJECT-VERB-OBJECT, no copula. The verb has content AHEAD of it (the
    # object); the object does not. That is the signal the reading learns.
    ("the heart pumps blood", ("heart", "blood", AFFIRMS)),
    ("vault holds gold", ("vault", "gold", AFFIRMS)),
]

MAX_RULES = 12

class _Unanimous:
    """Every procedure that fit the evidence, answering together.

    Exposes the `run` a `DerivedReading` expects, so the registry and the
    formalizer are unaware there is more than one candidate -- what they get is
    a reading the evidence determines, or nothing.
    """

    __slots__ = ("procedures",)

    def __init__(self, procedures):
        self.procedures = tuple(procedures)

    def run(self, machine, max_steps: int):
        # The machine handed in is consumed by the first run, so each candidate
        # gets its own built from the same words.
        sentence = " ".join(machine.words)
        answers, outcomes = set(), []
        for procedure in self.procedures:
            outcome = procedure.run(SentenceMachine(sentence), max_steps)
            outcomes.append(outcome)
            answers.add(tuple(outcome.answer.args)
                        if outcome.produced_answer else None)
        if len(answers) == 1 and None not in answers:
            return outcomes[0]
        if len(answers) > 1:
            logger.info("sentence %r separates the %d surviving readings %s; "
                        "it is the discriminating example that would decide them",
                        sentence, len(self.procedures), sorted(map(str, answers)))
        return outcomes[0] if not outcomes[0].produced_answer else _NoAnswer()


class _NoAnswer:
    """A run that produced nothing, because the candidates did not agree."""

    produced_answer = False
    answer = None
    status = None


_lock = threading.Lock()
_state: dict = {"derived": False, "reading": None, "why": ""}


def budget(sentence: str) -> int:
    """Steps the procedure may take. Two per word plus room to emit."""
    return 2 * len(SentenceMachine(sentence).words) + 6


def _learn_instructions(authority):
    """Induce what each instruction does, from being shown it act."""
    from core.execution.procedure import Operator
    from core.learning.rule_induction import Fact, TrainingExample

    operators = []
    for instruction in INSTRUCTIONS:
        examples = []
        for sentence, prefix in DEMONSTRATIONS[instruction]:
            machine = SentenceMachine(sentence)
            for earlier in prefix:
                if not machine.perform(Fact(earlier, ())):
                    return None, f"{instruction}: setup {earlier} refused on {sentence!r}"
            before = tuple(sorted(machine.observe()))
            action = Fact(instruction, ())
            if not machine.perform(action):
                return None, f"{instruction} refused on {sentence!r} after {prefix}"
            after = tuple(sorted(machine.observe()))
            examples.append(TrainingExample(before=before + (action,), action=action,
                                            after=after + (action,), positive=True))
            # Nothing happens without acting. Without this the induction can
            # explain the state change with a rule that has no action in it.
            examples.append(TrainingExample(before=before, action=None,
                                            after=before, positive=False))

        rules = []
        for target in TARGETS[instruction]:
            result = authority.induce(examples, target_predicate=target)
            if result.rule is None:
                return None, (f"{instruction} explaining {target}: "
                              f"{result.status.value}")
            rules.append(result.rule)
        operators.append(Operator(action=Fact(instruction, ()), rules=tuple(rules)))
    return operators, ""


def derive() -> Tuple[Optional[object], str]:
    """Derive the reading procedure. Once per process, then cached.

    Returns (DerivedReading, "") or (None, why). A failure is REPORTED, never
    swallowed into a silent fallback -- if this cannot be derived, the caller
    must know it is reading by guess.
    """
    with _lock:
        if _state["derived"]:
            return _state["reading"], _state["why"]

        from core.learning.learning_authority import get_learning_authority
        from core.learning.procedure_synthesis import IOExample, SynthesisStatus
        from core.learning.rule_induction import Fact
        from core.semantics.reading_registry import DerivedReading

        authority = get_learning_authority()
        try:
            operators, why = _learn_instructions(authority)
            if operators is None:
                _state.update(derived=True, reading=None, why=why)
                logger.warning("reading not derived: %s", why)
                return None, why

            guards = tuple(Fact(flag, ()) for flag in FLAGS)
            examples = [IOExample(label=s,
                                  build=lambda t=s: SentenceMachine(t),
                                  expected=m, max_steps=budget(s))
                        for s, m in TAUGHT]
            result = authority.derive_procedure(
                operators, guards, examples, terminal="READING",
                max_rules=MAX_RULES)
        except Exception as error:
            why = f"derivation raised {type(error).__name__}: {error}"
            _state.update(derived=True, reading=None, why=why)
            logger.warning("reading not derived: %s", why)
            return None, why

        if result.status not in (SynthesisStatus.PROCEDURE_DERIVED,
                                 SynthesisStatus.MULTIPLE_PROCEDURES):
            why = f"synthesis returned {result.status.value}: {result.detail}"
            _state.update(derived=True, reading=None, why=why)
            logger.warning("reading not derived: %s", why)
            return None, why

        # MULTIPLE_PROCEDURES is underdetermination and it is the normal
        # outcome here: five sentences do not pin down the route through six
        # guards. Four procedures fit, and they differ only in how they get
        # there. Picking one would be choosing a reading the evidence does not
        # choose -- so ALL of them read every sentence and they must AGREE.
        # Where they disagree the sentence is exactly the input the synthesis
        # said "would decide", and the honest answer is that this reading does
        # not determine it.
        procedures = tuple(result.procedures)

        reading = DerivedReading(
            name="subject_object_polarity",
            procedure=_Unanimous(procedures),
            machine=SentenceMachine,
            budget=budget,
            provenance=(f"derived from {len(TAUGHT)} sentence/meaning pairs via "
                        f"procedure_synthesis over {len(INSTRUCTIONS)} induced "
                        f"instructions; {len(procedures)} procedure(s) fit and "
                        f"must agree; no model"),
        )
        _state.update(derived=True, reading=reading, why="")
        return reading, ""


def ensure_registered() -> Tuple[bool, str]:
    """Derive the reading if needed and put it in the registry.

    Idempotent: the registry is consulted on every formalization, and the same
    reading appearing twice would make one sentence two readings.
    """
    from core.semantics.reading_registry import get_reading_registry

    registry = get_reading_registry()
    if any(r.name == "subject_object_polarity" for r in registry.readings()):
        return True, ""

    reading, why = derive()
    if reading is None:
        return False, why
    registry.register(reading)
    return True, ""


#: Content words a reading may leave unaccounted for. Exactly one: the
#: relation. `vault holds gold` reads as (vault, gold) and `holds` is the word
#: that says how they relate.
MAX_RESIDUE = 1


def _content_words(sentence: str) -> List[str]:
    """Words that are not part of the supplied six-word function lexicon."""
    return [w for w in tokenize(sentence)
            if w not in COPULAS and w not in DETERMINERS and w not in NEGATORS]


def covers(sentence: str, subject: str, obj: str) -> Tuple[bool, int]:
    """Did the reading ACCOUNT FOR the sentence, or pick two words out of it?

    THE MACHINE ALWAYS EMITS. It walks to the end and reports whatever the
    registers hold, so a twelve-word sentence of the wrong shape produces a
    confident-looking reading rather than a refusal: "A function is a reusable
    block of code that encapsulates logic" came back as (function, logic) and
    the five words carrying the actual claim were dropped on the floor.

    A reading that leaves content words behind did not read the sentence. This
    counts them, and the count is the whole test -- there is no threshold tuned
    to make particular sentences pass.
    """
    # Split multi-token constituents on '_': a grouped subject like
    # 'smoke_alarm' accounts for the sentence words 'smoke' and 'alarm',
    # so a correct multi-word reading is not mistaken for residue.
    accounted = set()
    for _term in (subject, obj):
        accounted.update(_term.split('_'))
    residue = [w for w in _content_words(sentence) if w not in accounted]
    # THE RELATION IS THE COPULA WHEN ONE IS PRESENT, A VERB OTHERWISE.
    # "robin IS a bird" relates its two ends through the copula, so NO content
    # word should be left over; "the heart PUMPS blood" has no copula and the
    # one verb is the relation. So a copula sentence allows zero residue and a
    # verbal one allows exactly the verb. Without this split the one-word budget
    # meant for the verb silently absorbed a dropped noun-phrase word: "the
    # smoke alarm is red" read as (smoke, red) and "all dogs are animals" as
    # (all, animals) -- confident misreadings where an honest decline was right.
    has_copula = any(w in COPULAS for w in tokenize(sentence))
    max_residue = 0 if has_copula else MAX_RESIDUE
    return len(residue) <= max_residue, len(residue)


def relation_in(sentence: str, subject: str, obj: str) -> str:
    """The word saying HOW subject and object relate.

    The reading produces the two ends and the polarity; the relation is what is
    left between them. `vault holds gold` leaves `holds`. `robin is a bird`
    leaves nothing, and the copula is the relation -- the sentence says the one
    IS the other.
    """
    accounted = set()
    for _t in (subject, obj):
        accounted.update(_t.split('_'))
    residue = [w for w in _content_words(sentence) if w not in accounted]
    return residue[0] if residue else "is"


def read(sentence: str) -> Optional[Tuple[str, str, str]]:
    """(subject, object, polarity) for a sentence this reading covers.

    None means THIS READING DOES NOT APPLY, which is an answer. It is not a
    licence to guess -- a caller that cannot read a sentence has not been told
    anything by it.
    """
    reading, _ = derive()
    if reading is None:
        return None
    got = reading.read(sentence)
    if not got:
        return None
    accounted, residue = covers(sentence, got[0], got[1])
    if not accounted:
        logger.info("declining %r: the reading (%s, %s) leaves %d content "
                    "word(s) unaccounted for", sentence, got[0], got[1], residue)
        return None
    return (got[0], got[1], got[2])
