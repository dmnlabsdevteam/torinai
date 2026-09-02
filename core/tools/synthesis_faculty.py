"""Self-contained program synthesis owned by the code tools.

Synthesis here is by VERIFICATION: a candidate program is accepted only if it
reproduces EVERY (input, output) example. Nothing is guessed — a program that
does not match all examples is never returned, and when no candidate matches,
the result is an honest gap. This duplicates, in the tool layer, the spirit of
the substrate's example-driven synthesis (propose a program, keep it only if it
verifies) without importing the substrate's engine.

The hypothesis space is a library of common single-argument programs over lists,
numbers, and strings. It widens by adding candidates here.
"""
from __future__ import annotations

import math
from typing import Any, List, Optional, Sequence, Tuple


def _is_num(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _num_seq(x) -> bool:
    return isinstance(x, (list, tuple)) and len(x) > 0 and all(_is_num(v) for v in x)


def _seq(x) -> bool:
    return isinstance(x, (list, tuple))


# (rendered expression over `xs`, callable, applies-to-input predicate)
# Ordered simplest-first so the chosen program is the simplest that verifies.
_CANDIDATES: List[Tuple[str, Any, Any]] = [
    ("xs", lambda xs: xs, lambda x: True),                       # identity
    ("sum(xs)", lambda xs: sum(xs), _num_seq),
    ("len(xs)", lambda xs: len(xs), lambda x: isinstance(x, (list, tuple, str))),
    ("max(xs)", lambda xs: max(xs), _num_seq),
    ("min(xs)", lambda xs: min(xs), _num_seq),
    ("math.prod(xs)", lambda xs: math.prod(xs), _num_seq),
    ("sum(xs) / len(xs)", lambda xs: sum(xs) / len(xs), _num_seq),
    ("xs[0]", lambda xs: xs[0], lambda x: isinstance(x, (list, tuple, str)) and len(x) > 0),
    ("xs[-1]", lambda xs: xs[-1], lambda x: isinstance(x, (list, tuple, str)) and len(x) > 0),
    ("sorted(xs)", lambda xs: sorted(xs), _seq),
    ("sorted(xs, reverse=True)", lambda xs: sorted(xs, reverse=True), _seq),
    ("list(reversed(xs))", lambda xs: list(reversed(xs)), _seq),
    ("list(dict.fromkeys(xs))", lambda xs: list(dict.fromkeys(xs)), _seq),
    ("[x for x in xs if x > 0]", lambda xs: [x for x in xs if x > 0], _num_seq),
    ("[x * x for x in xs]", lambda xs: [x * x for x in xs], _num_seq),
    ("-xs", lambda xs: -xs, _is_num),
    ("abs(xs)", lambda xs: abs(xs), _is_num),
    ("xs * xs", lambda xs: xs * xs, _is_num),
    ("xs + 1", lambda xs: xs + 1, _is_num),
    ("xs - 1", lambda xs: xs - 1, _is_num),
    ("xs * 2", lambda xs: xs * 2, _is_num),
    ("xs.upper()", lambda xs: xs.upper(), lambda x: isinstance(x, str)),
    ("xs.lower()", lambda xs: xs.lower(), lambda x: isinstance(x, str)),
    ("xs[::-1]", lambda xs: xs[::-1], lambda x: isinstance(x, str)),
    ("xs.strip()", lambda xs: xs.strip(), lambda x: isinstance(x, str)),
    ("len(xs.split())", lambda xs: len(xs.split()), lambda x: isinstance(x, str)),
]


def _as_examples(examples: Sequence[Any]) -> Optional[List[Tuple[Any, Any]]]:
    """Coerce to [(input, output)]; None if the shape is not example-like."""
    pairs = []
    for ex in examples:
        if isinstance(ex, dict) and "input" in ex and "output" in ex:
            pairs.append((ex["input"], ex["output"]))
        elif isinstance(ex, (list, tuple)) and len(ex) == 2:
            pairs.append((ex[0], ex[1]))
        else:
            return None
    return pairs or None


def synthesize(examples: Sequence[Any], function_name: str = "synthesized_function") -> Tuple[Optional[dict], str]:
    """Return (result, "") for a program that reproduces every example, else (None, why)."""
    pairs = _as_examples(examples)
    if pairs is None:
        return None, "examples must be [{'input':..., 'output':...}] or [[input, output], ...]"
    if len(pairs) < 2:
        return None, "need at least 2 examples to synthesize by verification"

    first_input = pairs[0][0]
    matches: List[str] = []
    for expr, fn, applies in _CANDIDATES:
        try:
            if not applies(first_input):
                continue
        except Exception:
            continue
        ok = True
        for inp, out in pairs:
            try:
                if fn(inp) != out:
                    ok = False
                    break
            except Exception:
                ok = False
                break
        if ok:
            matches.append(expr)

    if not matches:
        return None, "no candidate program in the hypothesis space reproduces all examples"

    chosen = matches[0]  # simplest-first
    code = f"def {function_name}(xs):\n    return {chosen}\n"
    return {
        "code": code,
        "expression": chosen,
        "verified": True,
        "examples_count": len(pairs),
        "alternatives": matches[1:],
        "model_free": True,
    }, ""
