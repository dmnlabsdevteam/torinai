"""Symbolic mathematics faculty — a real CAS the substrate owns.

Deterministic symbolic algebra via SymPy: simplify, expand, factor,
differentiate, integrate, solve, limit, series. Every result here is
COMPUTED by the computer-algebra system, never generated as text by a
model. The faculty also emits the SymPy code that reproduces the
computation, so a caller that asks for code receives a faithful
serialization of a real run rather than a guess.

This is not a solver-of-last-resort: an operation the CAS cannot carry out
returns an honest error, never a fabricated answer.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

import sympy as sp
from sympy.parsing.sympy_parser import (
    parse_expr,
    standard_transformations,
    implicit_multiplication_application,
)

# Allow "2x" to mean 2*x, and "^" is left as XOR by default — callers use ** .
_TRANSFORMS = standard_transformations + (implicit_multiplication_application,)

#: Operations the faculty supports, each backed by a real SymPy call.
OPERATIONS = (
    "simplify", "expand", "factor",
    "differentiate", "integrate",
    "solve", "limit", "series",
)


@dataclass
class SymbolicResult:
    operation: str
    expression: str
    variable: Optional[str]
    result: Optional[str] = None      # symbolic result rendered as a string
    numeric: Optional[str] = None     # numeric value, when the result is a number
    steps: List[str] = field(default_factory=list)
    code: Optional[str] = None        # SymPy code that reproduces the computation
    ok: bool = True
    error: Optional[str] = None

    def as_dict(self) -> dict:
        return {
            "operation": self.operation,
            "expression": self.expression,
            "variable": self.variable,
            "result": self.result,
            "numeric": self.numeric,
            "steps": self.steps,
            "code": self.code,
            "ok": self.ok,
            "error": self.error,
        }


def _parse(expr_str: str):
    return parse_expr(expr_str, transformations=_TRANSFORMS, evaluate=True)


def _resolve_var(expr, variable: Optional[str]):
    """Pick the symbol an operation acts on: given, or the lone free symbol."""
    if variable:
        return sp.Symbol(variable)
    free = sorted(expr.free_symbols, key=lambda s: s.name)
    if len(free) == 1:
        return free[0]
    return None


def _numeric(value) -> Optional[str]:
    """A numeric rendering when the result is a concrete number."""
    try:
        if getattr(value, "is_number", False):
            return str(sp.N(value))
    except Exception:
        return None
    return None


def _symbols_decl(expr) -> str:
    names = sorted({s.name for s in expr.free_symbols})
    if not names:
        return ""
    joined = ", ".join(names)
    return f"{joined} = sp.symbols('{' '.join(names)}')\n"


def compute(expression: str,
            operation: str,
            variable: Optional[str] = None,
            point: Optional[str] = None,
            order: int = 6) -> SymbolicResult:
    """Run one symbolic operation and return the CAS result plus reproducing code."""
    operation = (operation or "").strip().lower()
    res = SymbolicResult(operation=operation, expression=expression, variable=variable)

    if operation not in OPERATIONS:
        res.ok = False
        res.error = f"unsupported operation {operation!r}; supported: {', '.join(OPERATIONS)}"
        return res

    # ----- solve accepts an equation "lhs = rhs" as well as an expression -----
    try:
        if operation == "solve" and "=" in expression:
            lhs_str, rhs_str = expression.split("=", 1)
            lhs, rhs = _parse(lhs_str), _parse(rhs_str)
            target = sp.Eq(lhs, rhs)
            free_expr = lhs - rhs
        else:
            target = _parse(expression)
            free_expr = target
    except Exception as e:
        res.ok = False
        res.error = f"could not parse {expression!r}: {e}"
        return res

    # Operations that need a variable.
    needs_var = operation in ("differentiate", "integrate", "solve", "limit", "series")
    var = _resolve_var(free_expr, variable) if needs_var else None
    if needs_var and var is None:
        res.ok = False
        res.error = ("this operation needs a variable and the expression has "
                     f"{len(free_expr.free_symbols)} symbols; pass `variable`")
        return res
    res.variable = var.name if var is not None else variable

    try:
        if operation == "simplify":
            out = sp.simplify(target)
            call = "sp.simplify(expr)"
        elif operation == "expand":
            out = sp.expand(target)
            call = "sp.expand(expr)"
        elif operation == "factor":
            out = sp.factor(target)
            call = "sp.factor(expr)"
        elif operation == "differentiate":
            out = sp.diff(target, var)
            call = f"sp.diff(expr, {var})"
        elif operation == "integrate":
            out = sp.integrate(target, var)
            call = f"sp.integrate(expr, {var})"
        elif operation == "solve":
            out = sp.solve(target, var)
            call = f"sp.solve(expr, {var})"
        elif operation == "limit":
            pt = _parse(point) if point is not None else sp.oo
            out = sp.limit(target, var, pt)
            call = f"sp.limit(expr, {var}, {sp.srepr(pt) if point is None else point})"
        elif operation == "series":
            pt = _parse(point) if point is not None else sp.Integer(0)
            out = sp.series(target, var, pt, order)
            call = f"sp.series(expr, {var}, {point or 0}, {order})"
        else:  # unreachable given the guard above
            raise RuntimeError(operation)
    except Exception as e:
        res.ok = False
        res.error = f"CAS could not perform {operation}: {e}"
        return res

    res.result = str(out)
    res.numeric = _numeric(out)

    # SymPy code that reproduces the run — a serialization of a real computation.
    decl = _symbols_decl(free_expr)
    if operation == "solve" and "=" in expression:
        lhs_str, rhs_str = expression.split("=", 1)
        expr_line = f"expr = sp.Eq({lhs_str.strip()}, {rhs_str.strip()})\n"
    else:
        expr_line = f"expr = {expression}\n"
    res.code = (
        "import sympy as sp\n"
        + decl
        + expr_line
        + f"result = {call}\n"
        + "print(result)\n"
    )
    res.steps = [f"parsed: {target}", f"{operation} -> {out}"]
    return res


class SymbolicMath:
    """Object handle over the CAS faculty (mirrors the other reasoning faculties)."""

    OPERATIONS = OPERATIONS

    def compute(self, expression: str, operation: str, variable: Optional[str] = None,
                point: Optional[str] = None, order: int = 6) -> SymbolicResult:
        return compute(expression, operation, variable, point, order)


_INSTANCE: Optional[SymbolicMath] = None


def get_symbolic_math() -> SymbolicMath:
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = SymbolicMath()
    return _INSTANCE
