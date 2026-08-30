#!/usr/bin/env python3
"""A machine that supplies instructions, not answers.

`data_world` supplies LENGTH, SUM, MEAN and MAXIMUM as observations -- the way
a language supplies `len`, `sum` and `max`. Composing them is real work, but it
is not derivation: the fold is already written. This machine removes them.

WHAT IT SUPPLIES. A cursor over a list, two registers, a comparator, an adder,
and six instructions. That is the level a CPU actually offers:

    AT(p) SUCC(p,q) HEAD(v)      where the cursor is and what is under it
    A(a) B(b) A_UNSET B_UNSET    two registers and their validity bits
    GT_A LE_A GT_B LE_B          comparator flags, set only when comparable
    A_PLUS_HEAD(s) A_PLUS_ONE(s) the adder's output for the operands actually
                                 in the registers -- not an arithmetic table
    DONE RESULT(r)               the cursor is past the end; what was emitted

WHAT IT DOES NOT SUPPLY. No LENGTH, no SUM, no MEAN, no MAXIMUM, no count of
anything. Nothing in `observe()` is a fold. Every one of those has to be built
out of the six instructions and the flags, and whether the substrate can build
them is the measurement.

WHY THE ADDER IS AN OUTPUT, NOT A TABLE. `A_PLUS_HEAD(s)` states what the adder
returns for the two values currently in the registers, and nothing else -- one
literal per state, not an enumeration. A learned rule stays a function-free
Horn clause, the same discipline `arithmetic_background` follows in the
induction owner.

It carries the RESULT alone rather than `PLUS(a, v, s)` because restating the
operands makes the observation ambiguous: with the operands repeated, "A := the
value under the cursor" and "A := the adder's second operand" are the same
value in every state the machine can reach, and induction correctly reported
MULTIPLE_HYPOTHESES for TAKE and EMIT -- three and two rules, unseparable by
any demonstration. Measured before the change. An adder that publishes its
output is also the more faithful machine: operands live in registers, and the
ALU result is one more register.

Comparison is a FLAG rather than a relation for the same reason a processor
sets a status bit: it is a fact about the current operands, so it costs one
literal and carries no arguments to generalize over.

The acting half and the reporting half stay separate, as in `e2e_world` and
`data_world`: an instruction mutates the machine and returns whether it ran;
`observe()` recomputes everything from the machine's own state. A rule is never
confirmed by the invocation that produced it.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, FrozenSet, List, Optional, Sequence

from core.execution.operator_binding import OperatorBinding, get_binding_registry
from core.learning.rule_induction import Fact, canonical_term

#: The instruction set. Every instruction that reads the cell under the cursor
#: also advances past it -- auto-increment addressing, and the reason a program
#: over this machine terminates: no instruction can consume the same cell twice.
INSTRUCTIONS = ("TAKE", "PASS", "ACCUM", "TALLY", "CLEAR", "EMIT")

#: Zero-arity observations. A guard in a derived procedure is one of these, so
#: the vocabulary a procedure may branch on is fixed here and is visibly free
#: of anything task-specific.
FLAGS = ("DONE", "A_UNSET", "B_UNSET", "GT_A", "LE_A", "GT_B", "LE_B")


def _n(value: Any) -> str:
    return canonical_term(str(value))


class ListMachine:
    """A cursor, two registers, a comparator, an adder."""

    def __init__(self, values: Sequence[Any], b: Optional[Any] = None):
        self.values: List[float] = [float(v) for v in values]
        self.cursor = 0
        self.a = 0.0
        self.a_valid = False
        self.b = float(b) if b is not None else 0.0
        self.b_valid = b is not None
        self.result: Optional[float] = None
        self.performed: List[str] = []

    # ---- the world -------------------------------------------------------

    @staticmethod
    def position(index: int) -> str:
        return f"p{index}"

    @property
    def head(self) -> Optional[float]:
        return self.values[self.cursor] if self.cursor < len(self.values) else None

    def observe(self) -> Optional[FrozenSet[Fact]]:
        """Read the machine. Never a fold, never an answer."""
        facts = {
            Fact("AT", (self.position(self.cursor),)),
            Fact("A", (_n(self.a),)),
            Fact("B", (_n(self.b),)),
        }
        head = self.head
        if head is None:
            facts.add(Fact("DONE", ()))
        else:
            facts.add(Fact("HEAD", (_n(head),)))
            facts.add(Fact("SUCC", (self.position(self.cursor),
                                    self.position(self.cursor + 1))))
        if not self.a_valid:
            facts.add(Fact("A_UNSET", ()))
        if not self.b_valid:
            facts.add(Fact("B_UNSET", ()))
        if head is not None and self.a_valid:
            facts.add(Fact("GT_A" if head > self.a else "LE_A", ()))
            facts.add(Fact("A_PLUS_HEAD", (_n(self.a + head),)))
        if head is not None and self.b_valid:
            facts.add(Fact("GT_B" if head > self.b else "LE_B", ()))
        if self.a_valid:
            facts.add(Fact("A_PLUS_ONE", (_n(self.a + 1),)))
        if self.result is not None:
            facts.add(Fact("RESULT", (_n(self.result),)))
        return frozenset(facts)

    # ---- the instructions ------------------------------------------------

    def take(self) -> bool:
        """A := head, advance."""
        if self.head is None:
            return False
        self.a, self.a_valid = self.head, True
        self.cursor += 1
        return True

    def advance(self) -> bool:
        """Advance, touching no register."""
        if self.head is None:
            return False
        self.cursor += 1
        return True

    def accumulate(self) -> bool:
        """A := A + head, advance."""
        if self.head is None or not self.a_valid:
            return False
        self.a += self.head
        self.cursor += 1
        return True

    def tally(self) -> bool:
        """A := A + 1, advance."""
        if self.head is None or not self.a_valid:
            return False
        self.a += 1.0
        self.cursor += 1
        return True

    def clear(self) -> bool:
        """Make A valid, holding zero."""
        if self.a_valid:
            return False
        self.a, self.a_valid = 0.0, True
        return True

    def emit(self) -> bool:
        """RESULT := A."""
        if not self.a_valid:
            return False
        self.result = self.a
        return True

    def operations(self) -> Dict[str, Callable[[], bool]]:
        return {
            "TAKE": self.take,
            "PASS": self.advance,
            "ACCUM": self.accumulate,
            "TALLY": self.tally,
            "CLEAR": self.clear,
            "EMIT": self.emit,
        }

    def perform(self, action: Fact) -> bool:
        """Run one instruction. Returns whether the machine accepted it.

        Refusal is reported, never silently absorbed: a procedure proposing an
        instruction the machine will not run is a disagreement between the
        learned model and the world, and the interpreter has to be able to see
        it.
        """
        operation = self.operations().get(action.predicate)
        if operation is None:
            return False
        ran = operation()
        if ran:
            self.performed.append(action.predicate)
        return ran

    # ---- binding ---------------------------------------------------------

    def binding(self, predicate: str) -> OperatorBinding:
        return OperatorBinding(
            predicate=predicate,
            tool_name=f"list_machine.{predicate.lower()}",
            parameters=lambda args: {},
            observe=self.observe,
            description="a cursor over a list, two registers, a comparator, an adder",
        )

    def register(self, domain_id: str) -> "ListMachine":
        for predicate in INSTRUCTIONS:
            get_binding_registry().register(domain_id, self.binding(predicate))
        return self


__all__ = ["ListMachine", "INSTRUCTIONS", "FLAGS"]
