#!/usr/bin/env python3
"""A real data environment for substrate execution: values are held, operations
compute, and `observe()` reads back what is actually there.

The same discipline as `e2e_world`: the thing that ACTS is separate from the
thing that REPORTS. An operation stores its result in the environment; the
observer recomputes what it sees from the stored values and never from what an
operation claimed. If the world were reported by the code that changed it, a
rule would be confirmed by its own invocation returning cleanly.

WHAT THIS SUPPLIES AND WHAT IT DOES NOT. It supplies PRIMITIVE observations --
length, sum, mean, maximum, how many values exceed a threshold -- the way a
programming language supplies `len`, `sum` and `max`. It does NOT supply the
answer to any composed question. Discovering which primitive answers which
goal, and in what order, is what induction and planning have to do, and that is
the part being measured.

Stated plainly because the line matters: the substrate here COMPOSES primitives
it can observe. It does not re-derive them from first principles, any more than
a programmer reimplements `max` before using it.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, FrozenSet, List, Optional, Tuple

from core.execution.operator_binding import OperatorBinding, get_binding_registry
from core.learning.rule_induction import Fact, canonical_term


def _n(value: Any) -> str:
    return canonical_term(str(value))


class DataWorld:
    """Named collections and the values computed from them."""

    def __init__(self) -> None:
        self.collections: Dict[str, List[float]] = {}
        #: Values produced by operations, in the order they were produced.
        self.derived: List[float] = []
        #: Results produced by terminal operations.
        self.results: List[float] = []

    # ---- the world -------------------------------------------------------

    def put(self, name: str, values) -> "DataWorld":
        self.collections[name] = [float(v) for v in values]
        return self

    def reset_working(self) -> "DataWorld":
        """Clear what operations produced, keeping the data itself."""
        self.derived, self.results = [], []
        return self

    def observe(self) -> Optional[FrozenSet[Fact]]:
        """Read the environment. None when there is nothing to read at all,
        which is a different fact from an environment holding nothing."""
        if not self.collections:
            return None

        facts = set()
        for name, values in self.collections.items():
            if not values:
                continue
            total, length = sum(values), len(values)
            mean = total / length
            facts.add(Fact("LIST", (name,)))
            facts.add(Fact("LENGTH", (name, _n(length))))
            facts.add(Fact("SUM", (name, _n(total))))
            facts.add(Fact("MEAN", (name, _n(mean))))
            facts.add(Fact("MAXIMUM", (name, _n(max(values)))))
            # Bounded: only thresholds the environment already exposes, so the
            # observation set stays finite and does not enumerate arithmetic.
            for threshold in {mean, max(values)}:
                exceeding = len([v for v in values if v > threshold])
                facts.add(Fact("EXCEEDING", (name, _n(threshold), _n(exceeding))))

        for value in self.derived:
            facts.add(Fact("VALUE", (_n(value),)))
        for value in self.results:
            facts.add(Fact("RESULT", (_n(value),)))
        return frozenset(facts)

    # ---- the operations --------------------------------------------------

    def mean_of(self, name: str) -> Optional[float]:
        values = self.collections.get(name)
        if not values:
            return None
        mean = sum(values) / len(values)
        self.derived.append(mean)
        return mean

    def maximum_of(self, name: str) -> Optional[float]:
        values = self.collections.get(name)
        if not values:
            return None
        self.derived.append(max(values))
        return max(values)

    def count_exceeding(self, name: str) -> Optional[float]:
        """Count values above a threshold ALREADY PRODUCED by an earlier step.

        Takes no threshold argument on purpose: it consumes what a previous
        operation put into the environment, which is what makes a two-step
        composition necessary rather than a convenience.
        """
        values = self.collections.get(name)
        if not values or not self.derived:
            return None
        threshold = self.derived[-1]
        count = float(len([v for v in values if v > threshold]))
        self.results.append(count)
        return count

    def operations(self) -> Dict[str, Callable[[Tuple[str, ...]], Optional[float]]]:
        return {
            "MEAN_OF": lambda args: self.mean_of(args[0]),
            "MAXIMUM_OF": lambda args: self.maximum_of(args[0]),
            "COUNT_EXCEEDING": lambda args: self.count_exceeding(args[0]),
        }

    # ---- binding ---------------------------------------------------------

    def binding(self, predicate: str) -> OperatorBinding:
        return OperatorBinding(
            predicate=predicate,
            tool_name=f"data_world.{predicate.lower()}",
            parameters=lambda args: {"collection": args[0] if args else None},
            observe=self.observe,
            description="values are held in a data environment; operations compute over them",
        )

    def register(self, domain_id: str) -> "DataWorld":
        for predicate in self.operations():
            get_binding_registry().register(domain_id, self.binding(predicate))
        return self


__all__ = ["DataWorld"]
