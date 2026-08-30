#!/usr/bin/env python3
"""Recognising a linear equation in text, so the solver can be reached without a model.

The substrate ships a working Z3 backend (`core/reasoning/constraint_solver.py`)
that answers `4x + 8 = 32` correctly, including negative roots. It was
UNREACHABLE without a language model: the only route to it ran through
`_neuro_symbolic_reasoning`, whose first phase is "NEURAL PROPOSES" -- so Z3
could check a model's answer but never produce one. "Torin can do algebra" was
therefore a model-dependent claim, and severing Z3 would have changed nothing
because the model was doing the work.

This is the missing reading stage, and it is the same shape as genericity:
classify the surface form deterministically, then let the owner of that
capability answer. It does not solve anything itself.

THE GRAMMAR IS DELIBERATELY NARROW -- single variable, integer coefficients,
one occurrence of the variable. Anything else returns None and the request
continues to the ordinary path. A reader that guesses at an equation is worse
than one that declines, because a misread equation produces a confident wrong
number rather than a gap.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional

#: `[label:] [a]x [+|- b] = c`, with optional whitespace and an optional
#: leading instruction such as "Solve for x:".
_EQUATION = re.compile(
    r"^\s*(?:[^:]*:)?\s*"
    r"(?P<coefficient>[+-]?\d+)?\s*\*?\s*(?P<variable>[a-z])\s*"
    r"(?:(?P<sign>[+-])\s*(?P<constant>\d+)\s*)?"
    r"=\s*(?P<target>[+-]?\d+)\s*$",
    re.IGNORECASE,
)


#: A question naming a run of numbers, e.g. "Next term in the sequence 5, 9, 13".
#: Deliberately requires an explicit cue word: a sentence that merely contains
#: several numbers is not a sequence question, and reading it as one would
#: answer questions nobody asked.
_SEQUENCE_CUE = re.compile(r"\b(sequence|series|next term|comes next)\b", re.IGNORECASE)
_NUMBERS = re.compile(r"-?\d+(?:\.\d+)?")
#: Below this many terms a rule cannot be evidenced -- one step is consistent
#: with infinitely many rules.
MINIMUM_SEQUENCE_TERMS = 3


@dataclass(frozen=True)
class SequenceQuestion:
    """A run of observed terms, and the request for what follows."""

    terms: List[float]
    surface: str

    def as_text(self) -> str:
        return ", ".join(str(int(t) if float(t).is_integer() else t) for t in self.terms)


@dataclass(frozen=True)
class LinearEquation:
    """`coefficient * variable + constant = target`."""

    variable: str
    coefficient: int
    constant: int
    target: int
    surface: str

    def as_text(self) -> str:
        sign = "+" if self.constant >= 0 else "-"
        return (f"{self.coefficient}{self.variable} {sign} {abs(self.constant)} "
                f"= {self.target}")


def read(text: str) -> Optional[LinearEquation]:
    """Read a linear equation, or None if the text is not one.

    None means "not an equation", never "an equation I could not solve" --
    solving is the constraint solver's job and its failures are its own.
    """
    if not text or "=" not in text:
        return None
    match = _EQUATION.match(str(text).strip().rstrip("?."))
    if not match:
        return None

    raw_coefficient = match.group("coefficient")
    coefficient = int(raw_coefficient) if raw_coefficient not in (None, "", "+") else 1
    if raw_coefficient == "-":
        coefficient = -1
    if coefficient == 0:
        return None

    constant = int(match.group("constant") or 0)
    if match.group("sign") == "-":
        constant = -constant

    return LinearEquation(
        variable=match.group("variable").lower(),
        coefficient=coefficient,
        constant=constant,
        target=int(match.group("target")),
        surface=str(text).strip(),
    )


def read_sequence(text: str) -> Optional[SequenceQuestion]:
    """Read a sequence question, or None if the text is not one.

    None means "not a sequence question", never "a sequence I could not
    extend" -- extending is the learning authority's job, and inducing nothing
    from three terms is a real answer it is entitled to give.
    """
    if not text or not _SEQUENCE_CUE.search(str(text)):
        return None
    terms = [float(n) for n in _NUMBERS.findall(str(text))]
    if len(terms) < MINIMUM_SEQUENCE_TERMS:
        return None
    return SequenceQuestion(terms=terms, surface=str(text).strip())


__all__ = ["LinearEquation", "SequenceQuestion", "read", "read_sequence",
           "MINIMUM_SEQUENCE_TERMS"]
