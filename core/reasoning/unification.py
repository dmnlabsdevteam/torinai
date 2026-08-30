#!/usr/bin/env python3
"""The single authority on binding variables to terms.

Deduction was implemented twice in this codebase, and the two did not agree
about what "a rule applies" means:

    core/learning/rule_induction.py   real unification -- binds ?X to every
                                      matching constant, enumerates all
                                      solutions, detects conflicts

    DeductiveReasoningStrategy        `condition in premise.statement.lower()`
                                      -- substring containment, with the
                                      variable name still in the text

Under the second, `"x is human" in "socrates is human"` is False, so **no rule
containing a variable could ever fire**. Its applicability gate used loose word
overlap, so a rule passed the gate and then silently produced nothing. The
coordinator routed to that one.

The fix is not for one implementation to call the other. Unification is a
primitive of reasoning, not of learning, and the reasoning subsystem should not
depend on the learning subsystem merely because the correct implementation
landed there first. So it lives here, and both subsystems depend on this.

STRUCTURAL, NOT NOMINAL. Everything here works on any atom exposing
`predicate` and `args`, so neither subsystem has to adopt the other's classes
to share the algorithm.

Variables are MARKED, never inferred: a convention like "single uppercase
letters are variables" silently reclassifies a constant named X.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import (Any, Dict, Iterable, List, Optional, Protocol, Tuple,
                    runtime_checkable)

#: A term is a variable iff it carries this prefix. See the note above.
VARIABLE_PREFIX = "?"


@runtime_checkable
class AtomLike(Protocol):
    """A relational atom: a predicate and its ordered terms.

    A PROTOCOL, so the learning subsystem's `Fact` and the reasoning
    subsystem's `Atom` share this algorithm without either importing the
    other's classes. That direction matters: reasoning must not depend on
    learning merely because the correct unifier landed there first, and
    learning must not depend on reasoning's concrete types either.
    """
    predicate: str
    args: Tuple[str, ...]


@dataclass(frozen=True)
class Atom:
    """A concrete relational atom for callers that do not already have one."""

    predicate: str
    args: Tuple[str, ...] = ()

    @classmethod
    def parse(cls, text: str) -> "Atom":
        text = text.strip()
        if "(" not in text:
            return cls(text)
        if not text.endswith(")"):
            raise ValueError(f"unbalanced parentheses in {text!r}")
        predicate, _, rest = text.partition("(")
        inner = rest[:-1].strip()
        args = tuple(a.strip() for a in inner.split(",")) if inner else ()
        return cls(predicate.strip(), args)

    @property
    def is_ground(self) -> bool:
        return not any(is_variable(a) for a in self.args)

    def substitute(self, bindings: Dict[str, str]) -> "Atom":
        return Atom(self.predicate, tuple(bindings.get(a, a) for a in self.args))

    def to_formula(self) -> str:
        return f"{self.predicate}({', '.join(self.args)})" if self.args else self.predicate

    def __str__(self) -> str:
        return self.to_formula()


def is_variable(term: str) -> bool:
    return term.startswith(VARIABLE_PREFIX)


def signature(atom: AtomLike) -> Tuple[str, int]:
    return (atom.predicate, len(atom.args))


def variables_in(atom: AtomLike) -> set:
    return {a for a in atom.args if is_variable(a)}


def unify(pattern: AtomLike, ground: AtomLike,
          bindings: Optional[Dict[str, str]] = None) -> Optional[Dict[str, str]]:
    """Extend `bindings` so `pattern` matches `ground`, or None if impossible.

    Returns a NEW mapping; the input is never mutated, because a caller
    enumerating alternatives must be able to abandon one branch without having
    corrupted the others.

    A variable already bound to a different constant is a conflict, not a
    rebinding: `LIKES(?X, ?X)` must not match `LIKES(ann, bob)`.
    """
    if signature(pattern) != signature(ground):
        return None
    extended = dict(bindings or {})
    for slot, value in zip(pattern.args, ground.args):
        if is_variable(slot):
            if extended.setdefault(slot, value) != value:
                return None
        elif slot != value:
            return None
    return extended


def match_literal(pattern: AtomLike, state: Iterable[AtomLike],
                  bindings: Optional[Dict[str, str]] = None) -> List[Dict[str, str]]:
    """Every extension of `bindings` under which `pattern` holds in `state`."""
    solutions = []
    for ground in state:
        extended = unify(pattern, ground, bindings)
        if extended is not None:
            solutions.append(extended)
    return solutions


def match_body(body: Iterable[AtomLike], state: Iterable[AtomLike]) -> List[Dict[str, str]]:
    """Every substitution under which the whole body holds in the state.

    Backtracking rather than a join: bodies here are a handful of literals, and
    an exact enumeration keeps "the rule matched twice" observable instead of
    collapsing to a boolean.

    Most-constrained literal first, so branches die early.
    """
    state = list(state)
    ordered = sorted(body, key=lambda f: (-len(variables_in(f)), f.predicate, f.args))
    solutions: List[Dict[str, str]] = []

    def walk(index: int, bindings: Dict[str, str]) -> None:
        if index == len(ordered):
            solutions.append(bindings)
            return
        for extended in match_literal(ordered[index], state, bindings):
            walk(index + 1, extended)

    walk(0, {})
    return solutions


def apply_substitution(atom: Any, bindings: Dict[str, str]) -> Any:
    """Instantiate an atom under a binding, preserving its concrete class."""
    return atom.__class__(atom.predicate,
                          tuple(bindings.get(a, a) for a in atom.args))


def entails(body: Iterable[AtomLike], state: Iterable[AtomLike]) -> bool:
    """Whether the body holds under at least one substitution."""
    return bool(match_body(body, state))


__all__ = ["VARIABLE_PREFIX", "Atom", "AtomLike", "is_variable", "signature", "variables_in",
           "unify", "match_literal", "match_body", "apply_substitution", "entails"]
