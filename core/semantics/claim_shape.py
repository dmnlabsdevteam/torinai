#!/usr/bin/env python3
"""What a sentence CLAIMS, kept apart from how it is worded.

Measured on the substrate's own embedding model:

    0.948   `the vault is locked`  vs  `the vault is not locked`
    0.484   `the vault is locked`  vs  `the safe is secured`

A statement and its negation score nearly identical; two ways of saying the
same thing score half that. The vector is a measure of how alike the WORDS are,
and polarity is one token that reverses the claim without moving the words. No
threshold recovers it, and a bigger embedding model does not fix it -- it makes
the neighbourhood tighter around a distinction that was never encoded.

So it is not recovered at read time. It is READ WHEN THE MEMORY IS WRITTEN and
stored beside it, where it can be compared exactly instead of approximately.
The same argument covers tense: whether something IS or WAS the case is a fact
about the claim, not a flavour of its wording.

    the vault is locked        affirms, present
    the vault is not locked    denies,  present
    the vault was locked       affirms, past
    the vault wasn't locked    denies,  past

DELIBERATELY A SMALL CLOSED LIST. Six negators and a handful of past-tense
copulas, all visible in one place. This is not an attempt at understanding
English -- it is the one distinction the vector provably cannot make, taken out
of the vector's hands. Everything it cannot decide it reports as unknown rather
than guessing, because a claim recorded with the wrong polarity is worse than
one recorded with none: it will be retrieved as agreement.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

AFFIRMS, DENIES = "affirms", "denies"
PRESENT, PAST = "present", "past"

#: Every way the closed list knows of reversing a claim.
NEGATORS = frozenset({"not", "no", "never", "cannot", "isn_t", "wasn_t", "aren_t",
                      "weren_t", "doesn_t", "didn_t", "won_t", "don_t"})

#: Contractions arrive from `tokenize` with the apostrophe already folded.
PAST_MARKERS = frozenset({"was", "were", "had", "used", "wasn_t", "weren_t",
                          "didn_t", "formerly", "previously", "originally"})

PRESENT_MARKERS = frozenset({"is", "are", "now", "currently", "isn_t", "aren_t"})

_WORD = re.compile(r"[A-Za-z][A-Za-z0-9_']*")

#: Words that NAME something, as opposed to describing it.
#:
#: `unusual behaviour in data` and `anomaly detection` are the same question in
#: different words, and the vector is right to score them close. `the capital of
#: Mongolia` and `the capital of France` are DIFFERENT questions in nearly the
#: same words, and the vector scores those close too -- it measures wording, and
#: only one token differs. Measured on the live store, that memory came back as
#: the answer to the Mongolia question.
#:
#: This is the polarity problem again, in a second place. A proper noun and a
#: number are rigid: `anomaly` paraphrases to `unusual behaviour`, and nothing
#: paraphrases `Mongolia` or `1998`. So a memory that never mentions what the
#: question named is not about it, whatever it scores -- an exact test, taken
#: out of the vector's hands, like polarity.
#:
#: STATED LIMIT: a name in the first position is not recognised, because
#: capitalisation there is grammatical rather than referential and this cannot
#: tell `Mongolia is in Asia` from `What is a load balancer`. It declines
#: instead of guessing, which costs a discrimination it could have made and
#: never invents one it could not.
_NAMED = re.compile(r"\b[A-Z][A-Za-z]{2,}\b|\b\d[\d,.]*\b")

#: A question asserts nothing, so it has no polarity to record. Without this
#: `what is a load balancer` read as an affirmative claim about load balancers,
#: and every question filed in memory carried a polarity it never had.
ASKING = frozenset({"what", "which", "who", "whose", "where", "when", "why",
                    "how", "is", "are", "was", "were", "does", "do", "did",
                    "can", "could", "will", "would", "should"})


@dataclass(frozen=True)
class ClaimShape:
    """The shape of what is being claimed, apart from its wording."""

    polarity: Optional[str] = None
    tense: Optional[str] = None

    @property
    def known(self) -> bool:
        return self.polarity is not None

    def agrees_with(self, other: "ClaimShape") -> Optional[bool]:
        """True/False where both polarities are known, None where either is not.

        None is not a soft no. A memory whose polarity could not be read must
        not be reported as agreeing OR disagreeing, because both are claims
        about it that nothing established.
        """
        if not (self.known and other.known):
            return None
        return self.polarity == other.polarity

    def as_tags(self) -> list:
        return [t for t in (self.polarity, self.tense) if t]


def names_in(text: str) -> frozenset:
    """The rigid designators a sentence uses -- proper nouns and numbers."""
    stripped = (text or "").strip()
    if not stripped:
        return frozenset()
    # The first word is skipped whole: its capital says where the sentence
    # starts, not that it names anything.
    head, _, rest = stripped.partition(" ")
    found = {m.group(0).lower().rstrip(".,") for m in _NAMED.finditer(rest)}
    # A number leading the sentence is still a number; only capitals are
    # ambiguous at position 0.
    if head and head[0].isdigit():
        found.update(m.group(0).lower().rstrip(".,") for m in _NAMED.finditer(head))
    return frozenset(w for w in found if w)


def about_the_same_thing(question: str, memory: str) -> Optional[bool]:
    """False where the question NAMES something the memory never mentions.

    None where the question names nothing, which is most questions -- and the
    difference matters: None means this test had nothing to say, not that the
    memory passed it. True where every name in the question appears.
    """
    named = names_in(question)
    if not named:
        return None
    words = {w.lower() for w in _WORD.findall(memory or "")}
    words |= {m.group(0).lower().rstrip(".,") for m in _NAMED.finditer(memory or "")}
    return all(name in words for name in named)


def read_claim(text: str) -> ClaimShape:
    """The polarity and tense of a sentence, or nothing where it is not plain."""
    stripped = (text or "").strip()
    words = [w.lower().replace("'", "_") for w in _WORD.findall(stripped)]
    if not words:
        return ClaimShape()
    if stripped.endswith("?") or words[0] in ASKING:
        return ClaimShape()

    negated = any(w in NEGATORS for w in words)
    past = any(w in PAST_MARKERS for w in words)
    present = any(w in PRESENT_MARKERS for w in words)

    # A sentence with no copula and no negator is not making a claim this can
    # read -- a question, a fragment, a command. Reported as unknown.
    if not (negated or past or present):
        return ClaimShape()

    return ClaimShape(
        polarity=DENIES if negated else AFFIRMS,
        # Both markers present ("it was locked and is now open") is a change
        # being described, which this cannot place in time, so it declines.
        tense=None if (past and present) else PAST if past else PRESENT,
    )


__all__ = ["ClaimShape", "read_claim", "names_in", "about_the_same_thing",
           "AFFIRMS", "DENIES", "PRESENT", "PAST",
           "NEGATORS", "PAST_MARKERS", "PRESENT_MARKERS"]
