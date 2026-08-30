#!/usr/bin/env python3
"""A cursor over words, so a reading can be derived instead of hand-written.

The deterministic formalizer is six regular expressions. Every sentence form
beyond them is a person writing a seventh, which is not the substrate learning
to read -- it is the substrate being read TO. `Formalization.requires_model`
exists to measure "substrate-native vs model-formalized ... as the
deterministic extractor grows", and it never grew.

A READING IS A PROGRAM OVER A SEQUENCE, which is the thing `list_machine`
established the substrate can derive from input/output pairs alone. So the same
shape: a cursor, registers, flags, four instructions.

    BIND_SUBJECT   subject := the word here, advance
    BIND_OBJECT    object  := the word here, advance
    MARK_NEGATIVE  polarity := denies, advance
    SKIP           advance, touching no register
    EMIT           assert the reading, with its polarity

WHAT IS SUPPLIED, STATED PLAINLY. The machine holds a LEXICON -- five words
marked as copulas or determiners -- and publishes `COPULA` / `DETERMINER` /
`CONTENT` for the word under the cursor. That is data the world holds, like
`SMALLER` in a tower puzzle or `FACTOR` in an arithmetic one, and it is the
honest boundary of this block: word CLASS is given, and everything about which
class matters where, in what order, and what to do about it is derived.

Learning the classes themselves from distribution is a different and much
larger problem, and pretending otherwise here would hide the one place a person
is still writing the grammar down.
"""

from __future__ import annotations

import re
from typing import Any, Callable, Dict, FrozenSet, List, Optional, Sequence

from core.execution.operator_binding import OperatorBinding, get_binding_registry
from core.learning.rule_induction import Fact

INSTRUCTIONS = ("BIND_SUBJECT", "BIND_OBJECT", "EXTEND_SUBJECT",
                "EXTEND_OBJECT", "MARK_NEGATIVE", "SKIP", "EMIT")

#: Zero-arity observations a derived reading may branch on.
FLAGS = ("DONE", "SUBJECT_UNSET", "OBJECT_UNSET", "COPULA", "DETERMINER",
         "NEGATOR", "CONTENT", "HAS_COPULA", "COPULA_SEEN",
         "CONTENT_AHEAD")

#: The whole supplied lexicon. Six words.
COPULAS = frozenset({"is", "are"})
DETERMINERS = frozenset({"a", "an", "the"})
NEGATORS = frozenset({"not"})

AFFIRMS, DENIES = "affirms", "denies"

#: Stands in a register that holds nothing yet, so writing to a register is one
#: kind of change rather than two -- the same reason `list_machine` keeps A
#: present and carries a validity flag beside it.
EMPTY = "nothing"

_WORD = re.compile(r"[A-Za-z][A-Za-z0-9_']*")


def tokenize(sentence: str) -> List[str]:
    """Words, lowercased. No parsing: this decides where words END, nothing more."""
    return [w.lower().replace("'", "_") for w in _WORD.findall(sentence)]


class SentenceMachine:
    """A cursor over the words of one sentence, and two registers."""

    def __init__(self, sentence: str):
        self.words: List[str] = tokenize(sentence)
        self.cursor = 0
        self.subject, self.subject_set = EMPTY, False
        self.object, self.object_set = EMPTY, False
        self.polarity = AFFIRMS
        self.reading: Optional[Fact] = None
        self.performed: List[str] = []

    @staticmethod
    def position(index: int) -> str:
        return f"w{index}"

    @property
    def head(self) -> Optional[str]:
        return self.words[self.cursor] if self.cursor < len(self.words) else None

    # ---- the world -------------------------------------------------------

    def observe(self) -> Optional[FrozenSet[Fact]]:
        facts = {
            Fact("AT", (self.position(self.cursor),)),
            Fact("SUBJECT", (self.subject,)),
            Fact("OBJECT", (self.object,)),
            Fact("POLARITY", (self.polarity,)),
        }
        head = self.head
        if head is None:
            facts.add(Fact("DONE", ()))
        else:
            facts.add(Fact("WORD", (head,)))
            facts.add(Fact("SUCC", (self.position(self.cursor),
                                    self.position(self.cursor + 1))))
            facts.add(Fact("COPULA" if head in COPULAS else
                           "DETERMINER" if head in DETERMINERS else
                           "NEGATOR" if head in NEGATORS else "CONTENT", ()))
        if any(w in COPULAS for w in self.words):
            facts.add(Fact("HAS_COPULA", ()))
        if any(w in COPULAS for w in self.words[:self.cursor]):
            facts.add(Fact("COPULA_SEEN", ()))
        # A content word still ahead of the head separates a relation verb from
        # the object in an S-V-O sentence with no copula to mark the boundary.
        ahead = self.words[self.cursor + 1:] if self.cursor < len(self.words) else []
        if any(w not in COPULAS and w not in DETERMINERS and w not in NEGATORS
               for w in ahead):
            facts.add(Fact("CONTENT_AHEAD", ()))
        if not self.subject_set:
            facts.add(Fact("SUBJECT_UNSET", ()))
        if not self.object_set:
            facts.add(Fact("OBJECT_UNSET", ()))
        if self.reading is not None:
            facts.add(self.reading)
        return frozenset(facts)

    # ---- the instructions ------------------------------------------------

    def bind_subject(self) -> bool:
        if self.head is None:
            return False
        self.subject, self.subject_set = self.head, True
        self.cursor += 1
        return True

    def bind_object(self) -> bool:
        if self.head is None:
            return False
        self.object, self.object_set = self.head, True
        self.cursor += 1
        return True

    def extend_subject(self) -> bool:
        if self.head is None or not self.subject_set:
            return False
        self.subject = f"{self.subject}_{self.head}"
        self.cursor += 1
        return True

    def extend_object(self) -> bool:
        if self.head is None or not self.object_set:
            return False
        self.object = f"{self.object}_{self.head}"
        self.cursor += 1
        return True

    def mark_negative(self) -> bool:
        if self.head is None:
            return False
        self.polarity = DENIES
        self.cursor += 1
        return True

    def skip(self) -> bool:
        if self.head is None:
            return False
        self.cursor += 1
        return True

    def emit(self) -> bool:
        if not (self.subject_set and self.object_set):
            return False
        self.reading = Fact("READING", (self.subject, self.object, self.polarity))
        return True

    def operations(self) -> Dict[str, Callable[[], bool]]:
        return {"BIND_SUBJECT": self.bind_subject, "BIND_OBJECT": self.bind_object,
                "EXTEND_SUBJECT": self.extend_subject,
                "EXTEND_OBJECT": self.extend_object,
                "MARK_NEGATIVE": self.mark_negative, "SKIP": self.skip,
                "EMIT": self.emit}

    def perform(self, action: Fact) -> bool:
        operation = self.operations().get(action.predicate)
        if operation is None:
            return False
        ran = operation()
        if ran:
            self.performed.append(action.predicate)
        return ran

    # ---- binding ---------------------------------------------------------

    def binding(self, predicate: str) -> OperatorBinding:
        return OperatorBinding(
            predicate=predicate, tool_name=f"sentence_machine.{predicate.lower()}",
            parameters=lambda args: {}, observe=self.observe,
            description="a cursor over the words of a sentence, and two registers")

    def register(self, domain_id: str) -> "SentenceMachine":
        for predicate in INSTRUCTIONS:
            get_binding_registry().register(domain_id, self.binding(predicate))
        return self


__all__ = ["SentenceMachine", "INSTRUCTIONS", "FLAGS", "tokenize", "EMPTY",
           "AFFIRMS", "DENIES"]
