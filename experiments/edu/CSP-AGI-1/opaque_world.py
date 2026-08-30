#!/usr/bin/env python3
"""Worlds whose vocabulary and laws are invented after the architecture froze.

`K17` means whatever this generator decided it means, behind a seed the subject
never sees. No pretrained prior can help, and no module was written for it.

THE SPACE IS WIDER THAN THE SUBJECT. Six families of hidden law, three the
substrate's rule language can express and three it cannot -- a negative
condition, a disjunctive one, and a value produced by arithmetic outside the
value authority's catalogue. The subject is not told which it is looking at,
which is the whole point: a system that answers everything and a system that
refuses everything both fail, and only one that can tell them apart passes.

The generator supplies DISCRIMINATING evidence -- values varied so the
arithmetic is determined, counter-demonstrations for every law, an irrelevant
property that varies independently, and a demonstration that nothing happens
without acting. That is the teacher's job and it is stated rather than hidden.
What remains the subject's job is finding the law, and knowing when there isn't
one it can hold.

THE FIRST VERSION OF THIS FILE FAILED AT THAT, and the subject caught it. The
irrelevant property was present in every positive, so it was perfectly
correlated with the real condition and no evidence could separate them; and no
demonstration ever withheld the action, so nothing forced the action into the
rule. Induction returned MULTIPLE_HYPOTHESES -- two rules, one using the
distractor -- which was the correct answer to the evidence supplied. The
teacher was wrong, not the learner.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

from core.learning.rule_induction import Fact, TrainingExample

#: Representable by the substrate's rule language, and not.
REPRESENTABLE = ("conjunctive", "relational", "computed")
UNREPRESENTABLE = ("negated", "disjunctive", "uncatalogued")
FAMILIES = REPRESENTABLE + UNREPRESENTABLE

_CONSONANTS = "BDFGKLMNPRSTVXZ"
_VOWELS = "AEIOU"


def _token(rng: random.Random, used: set) -> str:
    while True:
        token = (rng.choice(_CONSONANTS) + rng.choice(_VOWELS)
                 + rng.choice(_CONSONANTS) + rng.choice("0123456789"))
        if token not in used:
            used.add(token)
            return token


@dataclass(frozen=True)
class Vocabulary:
    """Opaque names. Nothing about them says what they do."""

    action: str
    p: str
    q: str
    r: str
    distractor: str
    left: str
    right: str

    @classmethod
    def invent(cls, rng: random.Random) -> "Vocabulary":
        used: set = set()
        return cls(*(_token(rng, used) for _ in range(7)))


@dataclass
class OpaqueWorld:
    """One hidden law over one invented vocabulary."""

    family: str
    vocabulary: Vocabulary
    function: Optional[str]
    seed: int

    def _object(self, rng: random.Random) -> str:
        return "o" + str(rng.randrange(1000, 9999))

    # ---- one demonstration ----------------------------------------------

    def demonstrate(self, rng: random.Random, fires: bool, evidence_id: str,
                    acted: bool = True, branch: int = 0) -> TrainingExample:
        v = self.vocabulary
        subject = self._object(rng)
        # Present or absent independently of everything else, so nothing can
        # mistake it for part of the law.
        irrelevant = (Fact(v.distractor, (subject,)),) if rng.random() < 0.5 else ()

        if self.family in ("computed", "uncatalogued"):
            a, b = self._operands(rng)
            before = (Fact(v.p, (subject, str(a))), Fact(v.q, (subject, str(b)))
                      ) + irrelevant
            action = Fact(v.action, (subject,))
            if not acted:
                return TrainingExample(before=before, action=None, after=before,
                                       positive=False, evidence_id=evidence_id)
            if not fires:
                # The law needs both readings; with one absent nothing happens.
                before = (Fact(v.p, (subject, str(a))),) + irrelevant
                return TrainingExample(before=before + (action,), action=action,
                                       after=before + (action,), positive=False,
                                       evidence_id=evidence_id)
            value = (a + b if self.function == "add" else
                     a * b if self.function == "multiply" else
                     a - b if self.function == "subtract" else min(a, b))
            after = before + (Fact(v.r, (subject, str(value))),)
            return TrainingExample(before=before + (action,), action=action,
                                   after=after + (action,), positive=True,
                                   evidence_id=evidence_id)

        if self.family == "relational":
            other = self._object(rng)
            action = Fact(v.action, (subject, other))
            held = Fact(v.left, (subject, other))
            marked = Fact(v.q, (other,))
            if fires:
                before = (held, marked) + irrelevant
                after = (marked,) + irrelevant + (Fact(v.right, (subject, other)),)
            else:
                before = (held,) + irrelevant   # the second object is unmarked
                after = before
            if not acted:
                return TrainingExample(before=(held, marked) + irrelevant, action=None,
                                       after=(held, marked) + irrelevant,
                                       positive=False, evidence_id=evidence_id)
            return TrainingExample(before=before + (action,), action=action,
                                   after=after + (action,),
                                   positive=fires, evidence_id=evidence_id)

        # unary families
        action = Fact(v.action, (subject,))
        p, q = Fact(v.p, (subject,)), Fact(v.q, (subject,))
        produced = Fact(v.r, (subject,))

        if self.family == "conjunctive":
            if not acted:
                return TrainingExample(before=(p, q) + irrelevant, action=None,
                                       after=(p, q) + irrelevant, positive=False,
                                       evidence_id=evidence_id)
            # BOTH ways of failing, deterministically. Leaving it to a coin
            # flip let two counter-demonstrations land on the same condition,
            # so the other was never refuted and a rule missing it survived as
            # the more general one.
            before = ((p, q) if fires else
                      ((q,) if branch % 2 else (p,))) + irrelevant
            after = ((q,) + irrelevant + (produced,)) if fires else before
        elif self.family == "negated":
            # Fires only where the second property is ABSENT.
            if not acted:
                return TrainingExample(before=(p,) + irrelevant, action=None,
                                       after=(p,) + irrelevant, positive=False,
                                       evidence_id=evidence_id)
            before = ((p,) if fires else (p, q)) + irrelevant
            after = before + (produced,) if fires else before
        else:  # disjunctive
            if not acted:
                return TrainingExample(before=(p,) + irrelevant, action=None,
                                       after=(p,) + irrelevant, positive=False,
                                       evidence_id=evidence_id)
            if fires:
                before = ((p,) if branch % 2 else (q,)) + irrelevant
                after = before + (produced,)
            else:
                before = irrelevant or (Fact(v.left, (subject, subject)),)
                after = before
        return TrainingExample(before=before + (action,), action=action,
                               after=after + (action,), positive=fires,
                               evidence_id=evidence_id)

    def _operands(self, rng: random.Random) -> Tuple[int, int]:
        """Values that determine the arithmetic rather than allowing several.

        For `uncatalogued` the smaller operand alternates sides, so `the first
        reading` never explains the result either -- otherwise the law would be
        representable after all and the world would be testing nothing.
        """
        while True:
            a, b = rng.randrange(2, 40), rng.randrange(2, 40)
            if a == b or a in (0, 1) or b in (0, 1):
                continue
            value = (a + b if self.function == "add" else
                     a * b if self.function == "multiply" else
                     a - b if self.function == "subtract" else min(a, b))
            if value in (a, b) and self.function != "min":
                continue
            return a, b

    @property
    def produced(self) -> str:
        """The predicate the law asserts. Not the same field in every family --
        the relational law relates two objects and asserts a relation."""
        return (self.vocabulary.right if self.family == "relational"
                else self.vocabulary.r)


def invent(seed: int, family: str) -> OpaqueWorld:
    rng = random.Random(seed)
    function = None
    if family == "computed":
        function = rng.choice(("add", "multiply", "subtract"))
    elif family == "uncatalogued":
        function = "min"
    return OpaqueWorld(family=family, vocabulary=Vocabulary.invent(rng),
                       function=function, seed=seed)


def evidence(world: OpaqueWorld, seed: int, positives: int, negatives: int,
             tag: str) -> List[TrainingExample]:
    """Positives, counter-demonstrations, and -- as one of the counters -- a
    state where the law's conditions hold and nobody acts. Without that last
    one nothing forces the action into the rule, and `P ∧ Q -> R` fits every
    demonstration of `ACT ∧ P ∧ Q -> R`."""
    rng = random.Random(seed)
    examples = [world.demonstrate(rng, True, f"{tag}_p{index}", branch=index)
                for index in range(positives)]
    for index in range(negatives):
        examples.append(world.demonstrate(
            rng, False, f"{tag}_n{index}", acted=index % 2 == 0, branch=index // 2))
    return examples


__all__ = ["FAMILIES", "REPRESENTABLE", "UNREPRESENTABLE", "OpaqueWorld",
           "Vocabulary", "invent", "evidence"]
