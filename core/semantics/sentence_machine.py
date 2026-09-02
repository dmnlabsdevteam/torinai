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
         "CONTENT_AHEAD",
         # supplied closed-class function words (finite, given -- like COPULA)
         "PREPOSITION",
         # TAUGHT open-class content classes of the head word, from the lexicon.
         # A content word the substrate has been taught the class of publishes
         # it here so the reading can tell a noun-phrase word (extend) from the
         # verb that ends it (skip). Absent when the word has not been taught.
         "HEAD_NOUN", "HEAD_ADJECTIVE", "HEAD_VERB",
         # a taught VERB has already been passed -- the subject noun phrase is
         # closed and what follows the verb is the object side.
         "VERB_SEEN",
         # the head sits inside a trailing prepositional phrase (a preposition
         # has been passed since the object was set) -- an adjunct to drop, not
         # more of the object.
         "IN_ADJUNCT")

#: The whole supplied FUNCTION lexicon: closed classes, finite, given -- the same
#: honest boundary the module names (word CLASS of a function word is supplied;
#: open-class content is taught). Prepositions/pronouns/etc. are added here
#: rather than left to be mistaken for content the way "on"/"by" were.
COPULAS = frozenset({"is", "are"})
DETERMINERS = frozenset({"a", "an", "the"})
NEGATORS = frozenset({"not"})
#: Prepositions that head a phrase. A preposition is either the relation itself
#: ("the vault is IN the room") or the marker of an adjunct to drop ("sells
#: shells BY the sea"); which one is decided by position (before vs. after the
#: object), not by the word.
PREPOSITIONS = frozenset({"in", "on", "at", "by", "over", "under", "with",
                          "into", "onto", "from", "to", "of", "near",
                          "beside", "inside", "through", "across", "above",
                          "below", "between", "around"})
#: Personal pronouns -- a closed class that stands where a noun phrase stands,
#: so a sentence may open with one instead of "the NOUN".
PRONOUNS = frozenset({"i", "you", "he", "she", "it", "we", "they",
                      "me", "him", "her", "us", "them"})
#: Coordinators. A sentence joined by one makes more than one claim; the reader
#: that handles that emits more than one reading (not yet -- see multi-emit).
CONJUNCTIONS = frozenset({"and", "or", "but"})
#: Auxiliary/do-support verbs that OPEN a question ("DOES a kestrel eat mice?")
#: or carry tense without being the relation. They are function words: the
#: relation is the main verb that follows, so the auxiliary is skipped.
AUXILIARIES = frozenset({"do", "does", "did"})
#: Wh-openers that ask for the OBJECT of a relation ("WHAT does a kestrel eat?").
#: The reading yields (subject, relation, <unknown>) -- the object is what is
#: being asked, which is exactly the fact a knowledge-gap check looks for.
WH_OBJECT_OPENERS = frozenset({"what", "which", "who", "whom"})

AFFIRMS, DENIES = "affirms", "denies"

#: Stands in a register that holds nothing yet, so writing to a register is one
#: kind of change rather than two -- the same reason `list_machine` keeps A
#: present and carries a validity flag beside it.
EMPTY = "nothing"

_WORD = re.compile(r"[A-Za-z][A-Za-z0-9_']*")


def tokenize(sentence: str) -> List[str]:
    """Words, lowercased. No parsing: this decides where words END, nothing more."""
    return [w.lower().replace("'", "_") for w in _WORD.findall(sentence)]


#: A bare VERDICT on what was just said -- affirming or denying a PRIOR claim,
#: not asserting a new one. Closed-class and GIVEN, like PRONOUNS: this is the
#: primitive the conversation reads to tell "no, that's wrong" (a verdict on the
#: last turn) from "no man is an island" (a proposition about the world). It
#: carries polarity, never content.
VERDICT_AFFIRMS = frozenset({"yes", "yep", "yeah", "correct", "right",
                             "exactly", "true", "agreed", "affirmative"})
VERDICT_DENIES = frozenset({"no", "nope", "wrong", "incorrect", "false",
                            "untrue", "mistaken", "negative"})
#: Deictic subjects that point BACK at the thing just said rather than naming a
#: new one. Contractions tokenize with a trailing "_s" ("that's" -> "that_s").
DEICTIC = frozenset({"that", "it", "this", "that_s", "it_s", "this_s"})

#: "yes" and "no" are the one ambiguity: a verdict ("no, that's wrong") but also
#: an interjection or quantifier before a NEW subject ("no man is an island").
#: They are read as a verdict only standing alone or pointing back at the
#: exchange -- next to a referring word, never quantifying a fresh noun.
_AMBIGUOUS_LEAD = frozenset({"yes", "no"})
#: Words that point at the exchange or its speakers rather than name a new
#: subject -- what legitimately follows a leading "yes"/"no" verdict.
_REFERRING = DEICTIC | frozenset({"i", "you", "we", "they", "he", "she", "it"})


def evaluative_verdict(sentence: str) -> Optional[bool]:
    """Whether this utterance is a bare VERDICT on what was just said, and which
    way: True affirms it, False denies it, None is not a verdict (an ordinary
    proposition). Structural and model-free, like the question test -- it fires
    only on the recognised evaluative shapes (a leading verdict word, or a
    deictic subject followed by one), never because a larger claim merely
    contains "no" or "right" somewhere inside it. The CONTEXT that makes a
    verdict FEEDBACK -- that there is a prior claim to judge -- is the
    conversation's to supply; this only reads the shape."""
    words = tokenize(sentence)
    if not words:
        return None
    first = words[0]
    if first in _AMBIGUOUS_LEAD:
        # A response particle only when it stands alone or points back at the
        # exchange ("no", "no it isn't", "no, that's wrong") -- not when it
        # quantifies or addresses a new subject ("no man is an island").
        if len(words) == 1 or words[1] in _REFERRING \
                or words[1] in VERDICT_DENIES or words[1] in VERDICT_AFFIRMS:
            return first not in VERDICT_DENIES
        return None
    if first in VERDICT_DENIES:
        return False
    if first in VERDICT_AFFIRMS:
        return True
    if first in DEICTIC:
        for w in words[1:]:
            if w in VERDICT_DENIES:
                return False
            if w in VERDICT_AFFIRMS:
                return True
    return None


def _taught_class(word: str) -> Optional[str]:
    """The lexicon's TAUGHT class for a word, or None if it has never been
    taught one. Open-class content only -- the lexicon holds NOUN/ADJECTIVE/VERB;
    function words are the supplied frozensets above, not this. A missing or
    unreadable lexicon is None, never an error: an untaught word simply carries
    no content-class flag and a reading that needs one does not fire on it."""
    try:
        from core.semantics.lexicon import get_lexicon
        return get_lexicon().class_of(word)
    except Exception:
        return None


class SentenceMachine:
    """A cursor over the words of one sentence, and two registers."""

    def __init__(self, sentence: str):
        self.words: List[str] = tokenize(sentence)
        self.cursor = 0
        self.subject, self.subject_set = EMPTY, False
        self.object, self.object_set = EMPTY, False
        #: Cursor position when the object was first bound, so a preposition
        #: standing AFTER it can be seen as opening an adjunct rather than the
        #: relation (which stands before the object).
        self.object_at: Optional[int] = None
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
            # ADDITIVE supplementary classes. A preposition is ALSO left as
            # CONTENT above so every reading derived before these flags existed
            # is unchanged; these only ADD guards a newer reading may branch on.
            if head in PREPOSITIONS:
                facts.add(Fact("PREPOSITION", ()))
            taught = _taught_class(head)
            if taught == "NOUN":
                facts.add(Fact("HEAD_NOUN", ()))
            elif taught == "ADJECTIVE":
                facts.add(Fact("HEAD_ADJECTIVE", ()))
            elif taught == "VERB":
                facts.add(Fact("HEAD_VERB", ()))
        # A taught VERB already passed closes the subject noun phrase.
        if any(_taught_class(w) == "VERB" for w in self.words[:self.cursor]):
            facts.add(Fact("VERB_SEEN", ()))
        # A preposition standing after the object opens an adjunct to drop.
        if self.object_at is not None and any(
                w in PREPOSITIONS for w in self.words[self.object_at + 1:self.cursor + 1]):
            facts.add(Fact("IN_ADJUNCT", ()))
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
        if self.object_at is None:
            self.object_at = self.cursor
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
           "AFFIRMS", "DENIES", "COPULAS", "DETERMINERS", "NEGATORS",
           "PREPOSITIONS", "PRONOUNS", "CONJUNCTIONS", "AUXILIARIES",
           "WH_OBJECT_OPENERS", "_taught_class",
           "VERDICT_AFFIRMS", "VERDICT_DENIES", "DEICTIC", "evaluative_verdict"]
