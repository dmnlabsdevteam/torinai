#!/usr/bin/env python3
"""What a computation returns, asked rather than known.

An action can create a value that existed nowhere before it ran: dividing a
total by a count produces a number no fact in the pre-state named. Something
has to be able to say what that value IS, and the wrong answers are for the
planner to know, or for each rule to carry its own arithmetic.

So it is asked. `evaluate("divide", ("20", "4"))` returns "5"; the planner is
handed a value and stays domain-neutral, and induction searches this catalogue
rather than a list of special cases someone wrote for one experiment.

BELOW BOTH OWNERS, LIKE UNIFICATION. Learning asks it to explain how an output
relates to the inputs; grounding asks it to compute that output; the planner
asks it so a value produced mid-plan can be carried forward. One
implementation, because two would let the learner and the planner disagree
about what a computation returns -- and the plan would then be built on
arithmetic the rule did not mean.

WHAT IT WILL NOT DO. It returns None rather than a value whenever the answer is
not determined: a division by zero, a non-numeric argument, a function it does
not have. None is a refusal, not a zero, and a caller that treats it as a value
will produce a plan resting on arithmetic that never happened.

THE CATALOGUE IS DELIBERATELY SMALL. Induction searches it: every additional
function is another hypothesis that might explain a demonstration by accident,
so the price of a function nobody needs is a version space that fails to
collapse. Four is what the arithmetic of folds requires. A function is added
when evidence needs it, not in case it is wanted.
"""

from __future__ import annotations

import logging
from typing import Callable, Dict, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)


def _divide(numerator: float, denominator: float) -> Optional[float]:
    return None if denominator == 0 else numerator / denominator


#: name -> (arity, commutative, computation). Every computation returns None
#: where the result is undefined, so undefinedness travels as a refusal rather
#: than as a number that happens to be wrong.
#:
#: COMMUTATIVITY IS DECLARED HERE because it is a property of the function, and
#: a searcher that does not know it manufactures an ambiguity no evidence can
#: ever settle: `add(?a, ?b)` and `add(?b, ?a)` are one hypothesis written
#: twice, and reporting them as two rivals leaves addition permanently
#: unlearnable. Measured -- multiply survived three separating demonstrations
#: and still came back MULTIPLE_HYPOTHESES against its own mirror image.
_FUNCTIONS: Dict[str, Tuple[int, bool, Callable[..., Optional[float]]]] = {
    "add": (2, True, lambda a, b: a + b),
    "subtract": (2, False, lambda a, b: a - b),
    "multiply": (2, True, lambda a, b: a * b),
    "divide": (2, False, _divide),
}


def catalogue() -> Tuple[str, ...]:
    """Every function that can be asked for, in a stable order."""
    return tuple(sorted(_FUNCTIONS))


def arity(function: str) -> Optional[int]:
    entry = _FUNCTIONS.get(function)
    return entry[0] if entry else None


def is_commutative(function: str) -> bool:
    """Whether the order of this function's arguments changes its answer."""
    entry = _FUNCTIONS.get(function)
    return bool(entry and entry[1])


def is_known(function: str) -> bool:
    return function in _FUNCTIONS


def evaluate(function: str, inputs: Sequence[str]) -> Optional[str]:
    """The value this function returns for these terms, as a canonical term.

    None whenever the answer is not determined -- an unknown function, the
    wrong number of arguments, a term that is not a number, or a computation
    undefined on them.
    """
    from core.learning.rule_induction import canonical_term, is_number

    entry = _FUNCTIONS.get(function)
    if entry is None:
        return None
    expected, _, compute = entry
    if len(inputs) != expected:
        return None
    if not all(is_number(str(term)) for term in inputs):
        return None
    result = compute(*(float(term) for term in inputs))
    return None if result is None else canonical_term(str(result))


__all__ = ["arity", "catalogue", "evaluate", "is_commutative", "is_known"]
