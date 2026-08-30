#!/usr/bin/env python3
"""A cursor over a list of integers, and an accumulator register.

The computational analogue of ``SentenceMachine`` (a cursor over the words of a
sentence). The SAME ``derive_procedure`` that composes reading instructions into
a reading program composes these instructions into a FOLD -- sum, count, max --
from input/output examples alone, model-free.

The design that lets one synthesis engine serve both worlds:

* The cursor is exposed RELATIONALLY -- ``AT``/``SUCC``/``DONE`` -- so an
  instruction's *advance* is an inducible rule, exactly as ``BIND_SUBJECT``'s
  advance is in the reading machine. That relational rule is all the synthesiser
  needs to know WHEN an instruction applies.
* The numeric accumulation is the machine's OWN effect, run inside ``perform``,
  the way ``bind_subject`` mutates a string register internally. Arithmetic is a
  primitive the machine supplies; the synthesiser never has to induce it. Two
  instructions that differ only numerically (ADD vs TALLY) therefore share one
  relational rule -- the I/O examples, run through ``perform`` and checked by the
  synthesiser's own verifier, are what separate a sum from a count.

There is no model anywhere in here. A machine is a fixed instruction set over a
readable state; what to DO with those instructions for a given task is what the
substrate learns.
"""

from typing import Callable, Dict, List, Optional

from core.learning.rule_induction import Fact


class ListMachine:
    """A cursor over a list of integers, and one accumulator register."""

    def __init__(self, items):
        self.items: List[int] = [int(x) for x in items]
        self.cursor = 0
        self.acc = 0
        self.started = False
        self.result: Optional[Fact] = None
        self.performed: List[str] = []

    @staticmethod
    def position(index: int) -> str:
        return f"i{index}"

    @property
    def head(self) -> Optional[int]:
        return self.items[self.cursor] if self.cursor < len(self.items) else None

    # ---- the world -------------------------------------------------------

    def observe(self):
        facts = {
            Fact("AT", (self.position(self.cursor),)),
            Fact("ACC", (str(self.acc),)),
        }
        head = self.head
        if head is None:
            facts.add(Fact("DONE", ()))
        else:
            facts.add(Fact("VALUE", (str(head),)))
            facts.add(Fact("SUCC", (self.position(self.cursor),
                                    self.position(self.cursor + 1))))
        if not self.started:
            facts.add(Fact("FRESH", ()))
        if self.result is not None:
            facts.add(self.result)
        return frozenset(facts)

    # ---- the instructions ------------------------------------------------
    # Each advances the cursor (the relational effect the synthesiser reasons
    # over) and folds the head into the accumulator its own way (the numeric
    # effect it supplies as a primitive). All refuse past the end, so an
    # accumulating instruction stops being applicable exactly when EMIT should
    # take over -- which is why a fold needs no explicit terminator guard.

    def add(self) -> bool:
        if self.head is None:
            return False
        self.acc += self.head
        self.started = True
        self.cursor += 1
        return True

    def tally(self) -> bool:
        if self.head is None:
            return False
        self.acc += 1
        self.started = True
        self.cursor += 1
        return True

    def keep_max(self) -> bool:
        if self.head is None:
            return False
        self.acc = self.head if not self.started else max(self.acc, self.head)
        self.started = True
        self.cursor += 1
        return True

    def emit(self) -> bool:
        self.result = Fact("RESULT", (str(self.acc),))
        return True

    def operations(self) -> Dict[str, Callable[[], bool]]:
        return {"ADD": self.add, "TALLY": self.tally,
                "KEEP_MAX": self.keep_max, "EMIT": self.emit}

    def perform(self, action: Fact) -> bool:
        operation = self.operations().get(action.predicate)
        if operation is None:
            return False
        ran = operation()
        if ran:
            self.performed.append(action.predicate)
        return ran
