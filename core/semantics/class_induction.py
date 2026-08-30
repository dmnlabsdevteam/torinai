#!/usr/bin/env python3
"""Deriving a rule for a word class from the words already established.

A lexicon is a lookup table, and lookups do not generalise: EDU-16 taught nine
words, confirmed all nine against the world, and classified none of nine
held-out words -- because nothing could be APPLIED to a word never seen.

    A CLASS IS LEARNED WHEN A RULE FOR IT CAN BE APPLIED TO A NEW WORD.

So the evidence already in the lexicon is treated as labelled examples, and a
rule is INDUCED from features of the words themselves. A rule is kept only when
it is right about every confirmed example of its class and wrong about none of
the others -- no majority vote, no threshold. A feature that merely correlates
is not a rule, and acting on one is how a learner acquires a confident mistake.

Where no feature separates two classes, that is reported. `cold` and `tank`
differ in no surface property this can see, and saying so is the honest result:
an unseparated pair stays UNDECIDED rather than being guessed.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence, Set, Tuple

logger = logging.getLogger(__name__)


#: Surface features of a word. Deliberately few and visible: each is something
#: a beginner could be told to look at, and each is checkable on any new word
#: without consulting anything.
FEATURES: Dict[str, Callable[[str], bool]] = {
    "ends_s": lambda w: w.endswith("s") and not w.endswith("ss"),
    "ends_ed": lambda w: w.endswith("ed"),
    "ends_ing": lambda w: w.endswith("ing"),
    "ends_y": lambda w: w.endswith("y"),
    "single_syllable_ish": lambda w: sum(c in "aeiou" for c in w) <= 1,
}


#: WHERE A WORD APPEARED, WHICH IS WHAT ACTUALLY DEFINES ITS CLASS.
#:
#: Spelling does not. `-s` marks a third-person-singular verb AND a plural noun,
#: so a rule induced from spelling called `valves`, `pumps` and `vaults` verbs --
#: it only looked like a separator because the taught sample happened to hold no
#: plural nouns. That is a coincidence of the sample being read as a law.
#:
#: A slot is not ambiguous in the same way. A word standing where the sentence
#: says what the thing IS is an adjective; a word standing as the thing the
#: sentence is about is a noun. One observation of a word in a slot is worth
#: more than any amount of its spelling.
SUBJECT_SLOT, PROPERTY_SLOT, VERB_SLOT = "subject", "property", "verb"

SLOT_CLASS = {
    SUBJECT_SLOT: "NOUN",
    PROPERTY_SLOT: "ADJECTIVE",
    VERB_SLOT: "VERB",
}


@dataclass
class Observation:
    """One sighting of a word in a slot of a sentence that read."""

    word: str
    slot: str
    sentence: str


def observe(sentence: str, reading: str) -> List[Observation]:
    """The slots a readable sentence puts its words in.

    Derived from the sentence's own shape, which is only known because it read.
    An unreadable sentence yields nothing -- there is no structure to observe.
    """
    words = [w for w in sentence.lower().replace(".", "").split() if w]
    seen: List[Observation] = []
    determiners = {"a", "an", "the"}
    copulas = {"is", "are"}
    content = [w for w in words if w not in determiners and w != "not"]

    if any(w in copulas for w in content):
        index = next(i for i, w in enumerate(content) if w in copulas)
        if index > 0:
            seen.append(Observation(content[index - 1], SUBJECT_SLOT, sentence))
        if index + 1 < len(content):
            seen.append(Observation(content[index + 1], PROPERTY_SLOT, sentence))
        return seen

    # No copula: the shape is subject VERB [object].
    if len(content) >= 2:
        seen.append(Observation(content[0], SUBJECT_SLOT, sentence))
        seen.append(Observation(content[1], VERB_SLOT, sentence))
        if len(content) >= 3:
            seen.append(Observation(content[2], SUBJECT_SLOT, sentence))
    return seen


def class_from_observations(word: str,
                            observations: Sequence[Observation]) -> Optional[str]:
    """The class a word's sightings agree on, or None when they disagree.

    Disagreement is not resolved by counting. A word seen in two slots has been
    used two ways, and choosing the commoner one would hide exactly the case
    worth noticing.
    """
    slots = {o.slot for o in observations if o.word == word.lower()}
    if len(slots) != 1:
        return None
    return SLOT_CLASS[next(iter(slots))]


@dataclass
class ClassRule:
    """One induced rule: this feature holds of this class and of nothing else."""

    word_class: str
    feature: str
    positive: bool                     # the feature must hold / must not hold
    supported_by: Tuple[str, ...] = ()
    separates_from: Tuple[str, ...] = ()

    def applies(self, word: str) -> bool:
        test = FEATURES[self.feature]
        return test(word.lower()) is self.positive

    def describe(self) -> str:
        verb = "ends in -s" if self.feature == "ends_s" else self.feature
        shape = verb if self.positive else f"does not {verb}"
        return (f"{self.word_class}: a word that {shape} "
                f"(from {', '.join(self.supported_by)})")


@dataclass
class Induction:
    """What could and could not be separated."""

    rules: List[ClassRule] = field(default_factory=list)
    unseparated: List[Tuple[str, str]] = field(default_factory=list)

    def rule_for(self, word_class: str) -> Optional[ClassRule]:
        return next((r for r in self.rules if r.word_class == word_class), None)


def induce(examples: Dict[str, str]) -> Induction:
    """Induce a rule per class from `{word: class}` examples.

    Kept only when EXACT: true of every example of the class and of no example
    of any other. Anything weaker is a correlation, and this refuses to call a
    correlation a rule.
    """
    induction = Induction()
    classes = sorted(set(examples.values()))

    for word_class in classes:
        mine = [w for w, c in examples.items() if c == word_class]
        others = [w for w, c in examples.items() if c != word_class]
        if not mine or not others:
            continue

        for feature, test in FEATURES.items():
            for positive in (True, False):
                holds_for_mine = all(test(w) is positive for w in mine)
                holds_for_none_other = all(test(w) is not positive for w in others)
                if holds_for_mine and holds_for_none_other:
                    induction.rules.append(ClassRule(
                        word_class=word_class, feature=feature, positive=positive,
                        supported_by=tuple(sorted(mine)),
                        separates_from=tuple(sorted(set(examples[w] for w in others))),
                    ))
                    break
            if induction.rule_for(word_class):
                break

    # Pairs no feature could tell apart. Reported, not glossed over.
    for i, left in enumerate(classes):
        for right in classes[i + 1:]:
            if induction.rule_for(left) or induction.rule_for(right):
                continue
            induction.unseparated.append((left, right))
    return induction


def classify(word: str, induction: Induction) -> Optional[str]:
    """Always None. Spelling does not decide a word's class.

    A morphological rule is still INDUCED and reported, because knowing which
    surface features happen to line up with a class is worth seeing. It is no
    longer allowed to CLASSIFY, because it was measured doing so wrongly:

        valves -> VERB    pumps -> VERB    vaults -> VERB    (all nouns)
        wibbles -> VERB   (a word that does not exist)

    `-s` marks a third-person-singular verb and a plural noun alike. The rule
    looked exact only because the taught vocabulary contained no plural noun --
    a gap in the sample, promoted to a law. Every word it was applied to beyond
    its support was a coin toss reported as knowledge.

    A word's class is where it can stand, so `class_from_observations` decides
    and this does not. An unobserved word is UNDECIDED, which is the true answer
    when a word has never been seen used.
    """
    return None


def morphological_hypothesis(word: str, induction: Induction) -> Optional[str]:
    """What the induced surface rule WOULD say. Reported, never acted on."""
    hits = [r.word_class for r in induction.rules if r.applies(word)]
    return hits[0] if len(hits) == 1 else None
