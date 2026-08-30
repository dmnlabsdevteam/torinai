#!/usr/bin/env python3
"""How a learned operator becomes an actual tool invocation, and how the world
is read back afterwards.

A learned rule says `MOVE(?X,?A,?B)` changes the world. It does not say what
`MOVE` *is* — the KITE experiments proved acquisition precisely because the
predicates carried no meaning. Something has to connect the symbol to an act,
and that connection is declared here rather than inferred: guessing which tool
a predicate denotes would let the substrate take a real action on a resemblance
between strings.

A binding supplies both halves, and both are required:

    execute   the tool and parameters that perform the action
    observe   how the world is read back, independently of what the tool said

The second is what makes verification possible. Without an independent
observation the only available evidence is the tool's own success flag, and a
rule would be confirmed by the fact that its invocation returned cleanly.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable, Dict, FrozenSet, Optional, Sequence, Tuple

from core.learning.rule_induction import Fact

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class OperatorBinding:
    """Binds one action predicate to a tool, and a world to its observer."""

    predicate: str
    tool_name: str
    #: ground action args -> tool parameters
    parameters: Callable[[Tuple[str, ...]], Dict[str, Any]]
    #: reads the world; returns None when it cannot be read, which is different
    #: from returning an empty world
    observe: Callable[[], Optional[FrozenSet[Fact]]]
    description: str = ""


class BindingRegistry:
    """The declared bindings for a domain. Unbound predicates are refused."""

    def __init__(self):
        self._bindings: Dict[Tuple[str, str], OperatorBinding] = {}

    def register(self, domain_id: str, binding: OperatorBinding) -> None:
        self._bindings[(domain_id, binding.predicate)] = binding
        logger.info("bound %s.%s -> %s", domain_id, binding.predicate, binding.tool_name)

    def get(self, domain_id: str, predicate: str) -> Optional[OperatorBinding]:
        return self._bindings.get((domain_id, predicate))

    def bindings_for(self, domain_id: str) -> Sequence[OperatorBinding]:
        """Every binding declared in a domain.

        The world a state goal is planned against is not one predicate's slice
        of it but the union of what every binding in the domain observes. A
        caller reading the whole world reads it through here rather than
        guessing which predicates exist.
        """
        return [b for (d, _), b in self._bindings.items() if d == domain_id]

    def observe_world(self, domain_id: str) -> Optional[FrozenSet[Fact]]:
        """Read the whole observable world of a domain, or None if any part of
        it cannot be read.

        Returning None on an unreadable slice is deliberate: a world assembled
        from the bindings that happened to answer is a different world from the
        real one, and planning against it would authorise a plan on a state
        that was never observed. An empty world (a domain with no facts) is not
        the same as an unreadable one and returns an empty set.
        """
        bindings = self.bindings_for(domain_id)
        if not bindings:
            return None
        facts: set = set()
        for binding in bindings:
            observed = binding.observe()
            if observed is None:
                return None
            facts |= set(observed)
        return frozenset(facts)

    def clear(self, domain_id: Optional[str] = None) -> None:
        if domain_id is None:
            self._bindings.clear()
            return
        for key in [k for k in self._bindings if k[0] == domain_id]:
            del self._bindings[key]


_registry: Optional[BindingRegistry] = None


def get_binding_registry() -> BindingRegistry:
    global _registry
    if _registry is None:
        _registry = BindingRegistry()
    return _registry
