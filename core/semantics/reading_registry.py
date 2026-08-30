#!/usr/bin/env python3
"""Readings the substrate derived, offered to the formalizer chain.

`_get_deterministic_formalizer` says the deterministic extractor "registers
here as it grows, which continuously shrinks the set of inputs that need
model-backed coverage". It never grew. Growing it meant a person writing a
seventh regular expression, so the measurable that
`Formalization.requires_model` exists to track could only move by hand.

This is the other way in. A reading DERIVED from sentence/meaning pairs is
registered here, and the chain consults it after the hand-written patterns and
before any model. Coverage then grows by evidence rather than by authorship,
and the share stays measurable because a derived reading needs no model either.

AFTER THE REGEXES, DELIBERATELY. The hand-written patterns are tested and are
the oracle a derived reading is checked against; a derived one that shadowed
them could regress a form that already worked without anything saying so. It
only ever sees input the tested path declined.

THE MACHINE STAYS OUT OF HERE. A reading carries its own way of turning a
sentence into something to run over -- registered by whatever derived it, so
this module never learns what a word is.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable, List, Optional, Tuple

logger = logging.getLogger(__name__)

#: A reading must produce subject, object and polarity, in that order. Declared
#: rather than inferred: a formalizer that guessed at the shape of what it was
#: handed would put an invented premise in front of the solver.
POLARITIES = ("affirms", "denies")
READING_ARITY = 3


@dataclass(frozen=True)
class DerivedReading:
    """One derived way of reading a sentence, and where it came from."""

    name: str
    #: Runs over a sentence and produces READING(subject, object, polarity).
    procedure: Any
    #: sentence -> an actuator the procedure can run against.
    machine: Callable[[str], Any]
    #: sentence -> how many steps it may take.
    budget: Callable[[str], int]
    #: What evidence derived it. A reading with no traceable origin is a
    #: hand-written pattern wearing a different coat.
    provenance: str

    def read(self, sentence: str) -> Optional[Tuple[str, ...]]:
        """The reading, or None where this one does not apply."""
        outcome = self.procedure.run(self.machine(sentence), self.budget(sentence))
        if not outcome.produced_answer:
            return None
        args = tuple(outcome.answer.args)
        if len(args) != READING_ARITY or args[2] not in POLARITIES:
            logger.warning("derived reading %s produced %s, which is not a reading",
                           self.name, args)
            return None
        return args


class ReadingRegistry:
    """The derived readings available, in the order they were registered."""

    def __init__(self):
        self._readings: List[DerivedReading] = []

    def register(self, reading: DerivedReading) -> None:
        self._readings.append(reading)
        logger.info("derived reading registered: %s (%s)", reading.name,
                    reading.provenance)

    def readings(self) -> List[DerivedReading]:
        return list(self._readings)

    def clear(self) -> None:
        self._readings.clear()


_registry: Optional[ReadingRegistry] = None


def get_reading_registry() -> ReadingRegistry:
    global _registry
    if _registry is None:
        _registry = ReadingRegistry()
    return _registry


__all__ = ["DerivedReading", "ReadingRegistry", "get_reading_registry",
           "POLARITIES", "READING_ARITY"]
