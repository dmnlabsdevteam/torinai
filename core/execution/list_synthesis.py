#!/usr/bin/env python3
"""Synthesise a fold over a list of integers from input/output examples.

The list counterpart of ``core.semantics.derived_reader``: it induces the
``ListMachine`` instruction set from a handful of demonstrations, then hands the
learner's I/O examples to the ONE ``derive_procedure`` the substrate uses for
every synthesis task. A sum, a count, a maximum -- each is a decision list over
those instructions, discovered from examples, with no model in the loop.

Honesty is the point of the boundary here. This synthesises folds over integer
lists because that is the machine that exists. Examples that are not fold-shaped
get a REPORTED gap, never a guess and never a model fallback: a caller learns
exactly what the substrate can and cannot yet build itself.
"""

import logging
import threading
from typing import Any, Callable, List, Optional, Sequence, Tuple

from core.execution.list_machine import ListMachine
from core.execution.procedure import Operator, Procedure
from core.learning.rule_induction import Fact, TrainingExample

logger = logging.getLogger(__name__)

# Demonstrations from which each instruction's rule is induced. Only the
# RELATIONAL effect is learned -- every accumulating instruction advances the
# cursor (target ``AT``); EMIT makes the ``RESULT``. The numeric difference
# between ADD, TALLY and KEEP_MAX is the machine's own doing and is not induced.
_DEMOS = {
    "ADD":      [([5, 2], []), ([7], []), ([3, 9, 1], ["ADD"])],
    "TALLY":    [([5, 2], []), ([7], []), ([3, 9, 1], ["TALLY"])],
    "KEEP_MAX": [([5, 2], []), ([7], []), ([3, 9, 1], ["KEEP_MAX"])],
    "EMIT":     [([5, 2], ["ADD", "ADD"]), ([7], ["ADD"]), ([3], [])],
}
_TARGETS = {"ADD": ["AT"], "TALLY": ["AT"], "KEEP_MAX": ["AT"], "EMIT": ["RESULT"]}

# DONE is the ONLY guard: it separates the terminal EMIT from the accumulating
# body. FRESH is deliberately NOT a guard -- splitting the first element into its
# own decision point lets ADD and KEEP_MAX coincide there (0+x == max-from-empty),
# which would make a sum and a max ambiguous. One body guard-state forces the
# whole fold through a single operator, so only the right one verifies.
_GUARDS = (Fact("DONE", ()),)
_TERMINAL = "RESULT"
_MAX_RULES = 6

_lock = threading.Lock()
_state: dict = {"operators": None, "why": ""}


def _learn_operators(authority) -> Tuple[Optional[List[Operator]], str]:
    """Induce the instruction set from demonstrations. Reported failure, no guess."""
    operators: List[Operator] = []
    for instruction, demos in _DEMOS.items():
        examples: List[TrainingExample] = []
        for items, prefix in demos:
            machine = ListMachine(items)
            for step in prefix:
                machine.perform(Fact(step, ()))
            before = tuple(sorted(machine.observe(), key=str))
            action = Fact(instruction, ())
            if not machine.perform(action):
                return None, f"{instruction} refused on {items} after {prefix}"
            after = tuple(sorted(machine.observe(), key=str))
            examples.append(TrainingExample(before=before + (action,), action=action,
                                            after=after + (action,), positive=True))
            examples.append(TrainingExample(before=before, action=None,
                                            after=before, positive=False))
        rules = []
        for target in _TARGETS[instruction]:
            result = authority.induce(examples, target_predicate=target)
            if result.rule is None:
                return None, (f"{instruction} explaining {target}: "
                              f"{result.status.value}")
            rules.append(result.rule)
        operators.append(Operator(action=Fact(instruction, ()), rules=tuple(rules)))
    return operators, ""


def _operators() -> Tuple[Optional[List[Operator]], str]:
    with _lock:
        if _state["operators"] is not None or _state["why"]:
            return _state["operators"], _state["why"]
        from core.learning.unified_learning_system import get_learning_authority
        operators, why = _learn_operators(get_learning_authority())
        _state["operators"], _state["why"] = operators, why
        return operators, why


def _as_fold_examples(examples: Sequence[Any]) -> Tuple[Optional[List[Tuple[List[int], int]]], str]:
    """Read the caller's examples as (list-of-ints -> int) pairs, or say why not.

    The gate that keeps the substrate honest: only fold-shaped evidence reaches
    the fold synthesiser. Anything else is reported as out of this machine's
    reach, not forced through it.
    """
    if not examples:
        return None, "no examples given"
    pairs: List[Tuple[List[int], int]] = []
    for ex in examples:
        if not isinstance(ex, dict) or "input" not in ex or "output" not in ex:
            return None, "each example must be an {input, output} pair"
        raw_in, raw_out = ex["input"], ex["output"]
        if not isinstance(raw_in, (list, tuple)):
            return None, f"input {raw_in!r} is not a list"
        try:
            items = [int(x) for x in raw_in]
            out = int(raw_out)
        except (TypeError, ValueError):
            return None, "this machine folds a list of integers to an integer"
        if isinstance(raw_out, bool) or any(isinstance(x, bool) for x in raw_in):
            return None, "this machine folds a list of integers to an integer"
        pairs.append((items, out))
    return pairs, ""


_FOLD_NAME = {"ADD": "sum", "TALLY": "count", "KEEP_MAX": "maximum"}


def _fold_label(procedure: Procedure) -> str:
    for step in procedure.steps:
        if step.operator.name in _FOLD_NAME:
            return _FOLD_NAME[step.operator.name]
    return "fold"


def synthesize_fold(examples: Sequence[Any]) -> Tuple[Optional[dict], str]:
    """Derive a fold from I/O examples, model-free, or REPORT why it cannot.

    Returns ``(result, "")`` on success or ``(None, why)`` on an honest gap --
    an out-of-domain example set, an operator set that would not induce, or
    examples no single fold explains. Never a fallback, never a fabricated
    program: a gap is returned as a gap.

    ``result`` carries the derived program, a rendered description, and ``run``,
    a callable that applies the synthesised procedure to a fresh list.
    """
    pairs, why = _as_fold_examples(examples)
    if pairs is None:
        return None, why

    operators, why = _operators()
    if operators is None:
        return None, f"instruction set unavailable: {why}"

    from core.learning.procedure_synthesis import (IOExample, SynthesisStatus,
                                                   derive_procedure)

    io_examples = [
        IOExample(label=str(items), build=(lambda it=items: ListMachine(it)),
                  expected=(str(out),), max_steps=len(items) + 2)
        for items, out in pairs
    ]

    outcome = derive_procedure(operators, _GUARDS, io_examples,
                               terminal=_TERMINAL, max_rules=_MAX_RULES)
    if outcome.status is not SynthesisStatus.PROCEDURE_DERIVED or outcome.procedure is None:
        return None, f"no single fold explains these examples ({outcome.status.value})"

    procedure = outcome.procedure

    def run(items: Sequence[Any]) -> Optional[int]:
        machine = ListMachine(items)
        result = procedure.run(machine, len(machine.items) + 2)
        if not result.produced_answer:
            return None
        return int(result.answer.args[0])

    label = _fold_label(procedure)
    return {
        "kind": label,
        "steps": [str(step) for step in procedure.steps],
        "description": f"model-free fold over a list of integers: {label}",
        "examples_count": len(pairs),
        "run": run,
        "model_free": True,
    }, ""
