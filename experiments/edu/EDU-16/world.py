#!/usr/bin/env python3
"""What decides a word's class: the slots it fits, not the teacher's label.

The teacher may say "tank is a noun". That is a proposal with no evidence
behind it. This module supplies the evidence, by putting the word into frames
the substrate can already read and seeing which ones produce a reading.

    the __ is heavy     -> a NOUN fits here
    the vault is __     -> an ADJECTIVE fits here
    the pump __ water   -> a VERB fits here

A word that reads in the noun frame and not the others is a noun BY BEHAVIOUR.
That is a fact the substrate established, not a claim it accepted.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


@dataclass
class ClassVerdict:
    """What the frames said about one word."""

    word: str
    fitted: Tuple[str, ...] = ()
    verdict: Optional[str] = None      # None when the frames do not separate it
    readings: Dict[str, str] = field(default_factory=dict)

    @property
    def decided(self) -> bool:
        return self.verdict is not None


async def _reads(sentence: str, talk) -> Optional[str]:
    """Does the substrate produce a reading for this sentence?"""
    try:
        reading, _source = await talk.read(sentence)
    except Exception:
        return None
    if not reading:
        return None
    return reading[0] if isinstance(reading, tuple) else str(reading)


async def classify(word: str, frames, talk, induction=None,
                   observations=None) -> ClassVerdict:
    """Decide a word's class by which frames accept it.

    UNDECIDED IS A REAL ANSWER. A word that fits every frame, or none, has not
    been separated -- and reporting that is the difference between a measured
    class and a guess. The whole point of teaching is to move words out of
    UNDECIDED, so it must be visible when they have not moved.
    """
    verdict = ClassVerdict(word=word)
    fitted: List[str] = []
    for frame in frames:
        sentence = frame.template.replace("__", word)
        reading = await _reads(sentence, talk)
        if reading:
            fitted.append(frame.accepts)
            verdict.readings[sentence] = reading

    verdict.fitted = tuple(sorted(set(fitted)))
    if len(verdict.fitted) == 1:
        verdict.verdict = verdict.fitted[0]
        return verdict

    # THE FRAMES CANNOT BOOTSTRAP THE FIRST CLASSIFICATION.
    #
    # A frame only discriminates once a word's class is known -- that is what
    # makes "the cold is heavy" fail -- so an entirely unknown word fits every
    # frame and the frames say nothing. That circularity is why teaching nine
    # words classified none of nine held-out ones.
    #
    # An INDUCED RULE breaks it: derived from the words already established,
    # applied to a word never seen. It answers None when no rule applies and
    # None when two do, so an unseparated word stays UNDECIDED.
    # OBSERVATION FIRST. Where a word was seen standing in a sentence it was
    # GIVEN beats any rule about how it is spelled -- `-s` marks a
    # third-person verb and a plural noun alike, so spelling called `valves` a
    # verb, while one sighting of it as a subject settles it.
    if observations:
        from core.semantics.class_induction import class_from_observations

        seen = class_from_observations(word, observations)
        if seen:
            verdict.verdict = seen
            verdict.readings["observed_in"] = seen
            return verdict

    if induction is not None:
        from core.semantics.class_induction import classify as by_rule

        ruled = by_rule(word, induction)
        if ruled:
            verdict.verdict = ruled
            verdict.readings["induced_rule"] = ruled
    return verdict


async def read_sentence(sentence: str, expected, talk) -> Tuple[bool, Optional[str]]:
    """Whether a held-out sentence reads, and whether it reads CORRECTLY.

    Graded on the derived reading, not on whether the teacher said the sentence
    was well formed.
    """
    got = await _reads(sentence, talk)
    if got is None:
        return False, None
    return got in expected, got
