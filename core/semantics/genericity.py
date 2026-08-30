#!/usr/bin/env python3
"""What proposition a copular sentence expresses. SEMANTICS OWNS THIS.

MOVED OUT OF `core/reasoning/neural_bridge.py` on 2026-08-24. Genericity is a
fact about language -- whether a sentence speaks of a kind, an individual, or
some unnamed thing -- and belongs with the faculty that reads sentences, not
with the one that reasons over what they say.

THE RISK IT GUARDS. "A robin is a bird" needs to become a rule about kinds, and
the cheap way there is to read the article `a` as a quantifier. That turns
"A robin is in the yard" into a law about all robins: an overgeneralization
machine that proves things nobody said.

So classification is its OWN STAGE, kept apart from reading and from
formalizing. A reader says what a sentence relates. This says whether the formal
grammar can carry that relation -- and for EXISTENTIAL and AMBIGUOUS readings it
cannot, because the grammar has no existential quantifier and nothing here may
resolve an ambiguity the sentence left open.

Applied to BOTH readers. The hand-written patterns and the derived reading each
skipped it once, and each produced `robin_yard` -- reading `robin` as a named
individual when the sentence says SOME robin.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


#: Locative prepositions and adverbs. A copula that LOCATES is not classifying,
#: so an indefinite subject with one of these is existential, never generic.
_LOCATIVE_PREPOSITIONS = (
    "in", "on", "at", "near", "inside", "outside", "under", "underneath",
    "over", "above", "below", "beside", "behind", "within", "beyond", "by",
    "next", "across", "between", "among", "around",
)
_LOCATIVE_ADVERBS = (
    "here", "there", "nearby", "upstairs", "downstairs", "outside", "inside",
    "abroad", "away", "home",
)

_INDEFINITE = ("a", "an")
_DEFINITE = ("the",)

#: A complement denoting a kind: an indefinite article and a single common noun.
_KIND_COMPLEMENT = re.compile(r"^(?:a|an)\s+([a-z][\w'-]*)$", re.IGNORECASE)
_BARE_WORD = re.compile(r"^[\w'-]+$")


class Genericity(Enum):
    """The proposition type a copular sentence expresses."""

    GENERIC_KIND = "generic_kind"
    INSTANCE = "instance"
    EXISTENTIAL = "existential"
    AMBIGUOUS = "ambiguous"

    @property
    def is_representable(self) -> bool:
        """Whether the current formal language can express this at all.

        EXISTENTIAL is understood and NOT representable -- there is no
        existential quantifier in the propositional grammar the solver takes.
        Those are different failures and must not share an answer: rendering
        "A robin is in the yard" as an atom like `robin_in_yard` would keep the
        pipeline running while quietly discarding the quantifier.
        """
        return self in (Genericity.GENERIC_KIND, Genericity.INSTANCE)


@dataclass(frozen=True)
class GenericityReading:
    """A classification, with the cue that produced it kept for provenance."""

    genericity: Genericity
    subject: str
    complement: str
    #: Why this reading was chosen. Cognition-bearing: a proof that rests on a
    #: universal rule should be able to say why that rule existed.
    cue: str
    determiner: Optional[str] = None
    transformations: Tuple[str, ...] = field(default_factory=tuple)

    @property
    def is_representable(self) -> bool:
        return self.genericity.is_representable


def _leading_word(text: str) -> str:
    stripped = text.strip()
    return stripped.split()[0].lower() if stripped else ""


def _is_locative(complement: str) -> bool:
    head = _leading_word(complement)
    if head in _LOCATIVE_PREPOSITIONS:
        return True
    return head in _LOCATIVE_ADVERBS and _BARE_WORD.match(complement.strip() or "x") is not None


def unrepresentable_reason(genericity: "Genericity") -> str:
    """The stable name for WHY a reading cannot be represented.

    A caller must be able to test which limit it hit, so these are markers, not
    prose. They were written at one decline site and a second site later grew
    its own wording -- at which point the same refusal had two names and only
    one of them was greppable.
    """
    return ("existential_quantification_not_supported"
            if genericity is Genericity.EXISTENTIAL
            else "ambiguous_quantification_not_resolved")


def classify_genericity(subject: str, complement: str,
             determiner: Optional[str] = None) -> GenericityReading:
    """Classify one copular sentence: `<determiner> <subject> is <complement>`.

    `determiner` is whatever preceded the subject, or None for a bare subject.
    """
    subject = (subject or "").strip()
    complement = (complement or "").strip().rstrip(".?!")
    determiner_key = (determiner or "").strip().lower() or None
    transformations = ()

    if not subject or not complement:
        return GenericityReading(Genericity.AMBIGUOUS, subject, complement,
                                 "empty subject or complement", determiner_key)

    # A proper noun names an individual, so the sentence is about that
    # individual whatever the complement says. Detected AFTER the determiner is
    # separated, so sentence-initial capitalisation of "A" cannot be mistaken
    # for a proper noun.
    if subject[0].isupper():
        return GenericityReading(Genericity.INSTANCE, subject, complement,
                                 "subject is a proper noun", determiner_key,
                                 transformations)

    if determiner_key in _DEFINITE:
        return GenericityReading(Genericity.INSTANCE, subject, complement,
                                 "definite subject denotes a particular individual",
                                 determiner_key, transformations)

    if determiner_key in _INDEFINITE:
        # Order matters: locative first, because "in a yard" also contains an
        # indefinite article and would otherwise read as a kind.
        if _is_locative(complement):
            return GenericityReading(Genericity.EXISTENTIAL, subject, complement,
                                     "copula locates rather than classifies",
                                     determiner_key, transformations)
        if _KIND_COMPLEMENT.match(complement):
            return GenericityReading(
                Genericity.GENERIC_KIND, subject, complement,
                "both sides denote kinds and the copula classifies",
                determiner_key, transformations + ("generic_class_interpretation",))
        # A bare adjective is genuinely undecidable: "A robin is small" is
        # generic, "A doctor is available" is existential, and nothing in the
        # surface form separates them. Declining preserves the ambiguity.
        return GenericityReading(Genericity.AMBIGUOUS, subject, complement,
                                 "indefinite subject with a non-classifying "
                                 "complement; generic and existential readings "
                                 "are both available",
                                 determiner_key, transformations)

    # No determiner. A bare common noun subject with a classifying complement
    # is the "Socrates is human" shape without the capital -- an individual.
    return GenericityReading(Genericity.INSTANCE, subject, complement,
                             "bare subject read as an individual",
                             determiner_key, transformations)


def _subject_and_complement(sentence: str,
                           subject: str) -> Tuple[Optional[str], str]:
    """The article framing the subject, and the complement AS WRITTEN.

    Genericity is decided on the complement in the form the sentence used, not
    on the bare term a reading returned. `("robin", "a bird")` classifies as a
    kind; `("robin", "bird")` classifies as AMBIGUOUS and refuses. Passing the
    bare object therefore rejected "a robin is a bird" -- a perfectly
    representable statement about kinds -- for want of the article.

    No pattern is written here. The subject is located in the sentence, the text
    after it is the complement, and a leading copula or negator is dropped using
    the vocabulary the semantics layer already owns.
    """
    from core.semantics.sentence_machine import COPULAS, DETERMINERS, NEGATORS

    words = (sentence or "").strip().split()
    lowered = [w.lower().strip(".,?!") for w in words]
    target = str(subject).lower().strip()

    try:
        at = lowered.index(target)
    except ValueError:
        at = 0

    determiner = (words[at - 1] if at > 0 and lowered[at - 1] in DETERMINERS
                  else None)

    rest = words[at + 1:]
    while rest and rest[0].lower().strip(".,?!") in (COPULAS | NEGATORS):
        rest = rest[1:]
    return determiner, " ".join(rest).strip(".,?!")


def _word_class(word: str) -> Optional[str]:
    """The word's class: recorded first, else derived by rule. Never guesses.

    A recorded class is an observation -- something the world confirmed. When
    there is none, a rule INDUCED from the recorded words is applied, which is
    what lets a word never seen before be read at all. Without this the reader
    was a lookup table: teaching nine words left every unseen word unreadable,
    however well the rule separating them had been learned.

    The rule answers None when nothing applies and None when two rules apply,
    so an unseparated word stays unknown rather than being assigned a class the
    evidence does not support.
    """
    try:
        from core.semantics.lexicon import get_lexicon

        lexicon = get_lexicon()
        recorded = lexicon.class_of(word)
        if recorded:
            return recorded

        # No spelling-based fallback. It was measured classifying every plural
        # noun as a verb, so a word with no recorded class stays unknown and
        # the sentence containing it does not read -- which is the honest
        # outcome for a word the substrate has never seen used.
        return None
    except Exception:                      # a missing lexicon is not a verb
        return None
