#!/usr/bin/env python3
"""A combinatorial world: twelve observable conditions, five of them causal.

Built for EDU-09, where the point is that no teacher may enumerate the
situation space. Twelve binary conditions give 4096 situations before entities
are considered, against a proposal budget of eight per lesson.

The hidden rule the world actually enforces:

    TRANSFER(X, A, B) succeeds iff
        LOCATED(X, A) and ROUTE(A, B) and AVAILABLE(B)
        and POWERED(A) and AUTHORISED(X, B)
        and NOT LOCKED(B)

Six distractors are observable, vary freely, and change nothing:
PAINTED_RED, MONITORED, HIGH_PRIORITY, HAS_LABEL, WEATHER_CLEAR, RECENTLY_USED.
The learner is not told which is which; that is the whole problem.

The world ENFORCES this. A refusal is a real refusal, so a negative
demonstration is an observation rather than a label.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, FrozenSet, Set, Tuple

from core.learning.rule_induction import Fact

#: Conditions that genuinely gate the action.
CAUSAL_POSITIVE = ("LOCATED", "ROUTE", "AVAILABLE", "POWERED", "AUTHORISED")
CAUSAL_NEGATIVE = ("LOCKED",)
#: Observable, freely varying, causally inert.
DISTRACTORS = ("PAINTED_RED", "MONITORED", "HIGH_PRIORITY", "HAS_LABEL",
               "WEATHER_CLEAR", "RECENTLY_USED")
ALL_CONDITIONS = CAUSAL_POSITIVE + CAUSAL_NEGATIVE + DISTRACTORS

#: Which entity each condition is about, given TRANSFER(X, A, B).
ARGUMENT_OF: Dict[str, Tuple[str, ...]] = {
    "LOCATED": ("X", "A"), "ROUTE": ("A", "B"), "AVAILABLE": ("B",),
    "POWERED": ("A",), "AUTHORISED": ("X", "B"), "LOCKED": ("B",),
    "PAINTED_RED": ("B",), "MONITORED": ("A",), "HIGH_PRIORITY": ("X",),
    "HAS_LABEL": ("B",), "WEATHER_CLEAR": (), "RECENTLY_USED": ("A",),
}


@dataclass
class ComplexWarehouse:
    """State is a set of true conditions. Absent means false -- closed world."""
    pallet: str = "p"
    source: str = "DOCK"
    destination: str = "AISLE"
    held: Set[str] = field(default_factory=set)

    def ground(self, condition: str) -> Fact:
        slots = ARGUMENT_OF[condition]
        binding = {"X": self.pallet, "A": self.source, "B": self.destination}
        return Fact(condition, tuple(binding[s] for s in slots))

    def set_conditions(self, conditions) -> None:
        self.held = {c for c in conditions if c in ALL_CONDITIONS}

    def observe(self) -> FrozenSet[Fact]:
        """Every condition that is TRUE. Nothing predicted, nothing inferred."""
        return frozenset(self.ground(c) for c in sorted(self.held))

    def transfer(self) -> bool:
        """Enforced by the world. Distractors cannot affect this."""
        if not all(c in self.held for c in CAUSAL_POSITIVE):
            return False
        if any(c in self.held for c in CAUSAL_NEGATIVE):
            return False
        self.held.discard("LOCATED")
        self.held.add("__ARRIVED__")
        return True

    def after(self) -> FrozenSet[Fact]:
        """The observable state following the attempt."""
        binding = {"X": self.pallet, "A": self.source, "B": self.destination}
        facts = {self.ground(c) for c in sorted(self.held) if c in ALL_CONDITIONS}
        if "__ARRIVED__" in self.held:
            facts.add(Fact("LOCATED", (binding["X"], binding["B"])))
        return frozenset(facts)


def run(conditions, pallet="p", source="DOCK", destination="AISLE"):
    """Set the world up, attempt the transfer, report what actually happened."""
    world = ComplexWarehouse(pallet=pallet, source=source, destination=destination)
    world.set_conditions(conditions)
    before = world.observe()
    moved = world.transfer()
    return before, world.after(), moved


__all__ = ["ComplexWarehouse", "run", "ALL_CONDITIONS", "CAUSAL_POSITIVE",
           "CAUSAL_NEGATIVE", "DISTRACTORS", "ARGUMENT_OF"]
