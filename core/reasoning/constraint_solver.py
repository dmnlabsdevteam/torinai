#!/usr/bin/env python3
"""Generic Constraint Solver
=============================

Industrial-strength CSP/SMT wrapper built on Z3.

This module provides a simple Pythonic interface for defining variables and
constraints, then solving them using the Z3 SMT solver. It is intended to be
used both directly by reasoning components and indirectly via tools.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union

logger = logging.getLogger(__name__)

try:
    from z3 import (
        Solver,
        Optimize,          # selection under constraints is an OPTIMISATION,
                           # not a satisfiability question
        Int, Real, Bool,
        And, Or, Not, Sum, If,
        sat,
    )  # type: ignore

    _Z3_AVAILABLE = True
except Exception:  # pragma: no cover - optional dependency
    Solver = Optimize = None  # type: ignore
    Int = Real = Bool = And = Or = Not = Sum = If = sat = None  # type: ignore
    _Z3_AVAILABLE = False


@dataclass
class ConstraintVariable:
    """Represents a variable in a constraint problem."""

    name: str
    vtype: str = "int"  # "int", "real", "bool"
    lower: Optional[float] = None
    upper: Optional[float] = None


@dataclass
class ConstraintProblem:
    """High-level representation of a constraint satisfaction problem."""

    variables: Dict[str, ConstraintVariable] = field(default_factory=dict)
    constraints: List[Any] = field(default_factory=list)


@dataclass
class ConstraintSolution:
    """Solution to a constraint problem."""

    satisfiable: bool
    model: Dict[str, Any] = field(default_factory=dict)
    raw_status: str = "unknown"
    error: Optional[str] = None


class ConstraintSolver:
    """Generic CSP/SMT solver using Z3 as backend."""

    def __init__(self) -> None:
        if not _Z3_AVAILABLE:
            logger.warning("Z3 is not available; constraint solving will be disabled")
        self._available = _Z3_AVAILABLE

    @property
    def available(self) -> bool:
        return self._available

    def create_problem(self) -> ConstraintProblem:
        """Create a new empty constraint problem."""
        return ConstraintProblem()

    def add_variable(
        self,
        problem: ConstraintProblem,
        name: str,
        vtype: str = "int",
        lower: Optional[float] = None,
        upper: Optional[float] = None,
    ) -> None:
        """Add a variable to the problem."""
        problem.variables[name] = ConstraintVariable(
            name=name,
            vtype=vtype,
            lower=lower,
            upper=upper,
        )

    def add_constraint(self, problem: ConstraintProblem, constraint_expr: Any) -> None:
        """Add a low-level Z3 constraint expression to the problem.

        Higher-level APIs (e.g., string-based constraints) can be layered on top
        later; for now we expect a Z3 BoolRef expression to be passed in.
        """

        problem.constraints.append(constraint_expr)

    def solve(self, problem: ConstraintProblem) -> ConstraintSolution:
        """Solve a constraint problem using Z3.

        Returns a ConstraintSolution indicating satisfiability and model values.
        """
        if not self._available:
            return ConstraintSolution(
                satisfiable=False,
                model={},
                raw_status="no_solver",
                error="Z3 solver not available in this environment",
            )

        solver = Solver()

        # Create Z3 variables
        z3_vars: Dict[str, Any] = {}
        for name, var in problem.variables.items():
            if var.vtype == "int":
                z3_var = Int(name)
            elif var.vtype == "real":
                z3_var = Real(name)
            elif var.vtype == "bool":
                z3_var = Bool(name)
            else:
                raise ValueError(f"Unsupported variable type: {var.vtype}")

            z3_vars[name] = z3_var

            # Apply simple bounds if provided
            if var.lower is not None:
                solver.add(z3_var >= var.lower)
            if var.upper is not None:
                solver.add(z3_var <= var.upper)

        # Add explicit constraints
        for c in problem.constraints:
            solver.add(c)

        status = solver.check()
        raw_status = str(status)

        if status != sat:
            return ConstraintSolution(
                satisfiable=False,
                model={},
                raw_status=raw_status,
            )

        model = solver.model()
        solution_values: Dict[str, Any] = {}
        for name, zvar in z3_vars.items():
            if model.eval(zvar, model_completion=True) is not None:
                val = model[zvar]
                solution_values[name] = val.as_long() if hasattr(val, "as_long") else float(val.as_decimal(10)) if hasattr(val, "as_decimal") else bool(val)

        return ConstraintSolution(
            satisfiable=True,
            model=solution_values,
            raw_status=raw_status,
        )

    def optimize(
        self,
        problem: ConstraintProblem,
        objective: Any,
        maximize: bool = True,
    ) -> ConstraintSolution:
        """Solve for the BEST assignment, not merely a satisfying one.

        `solve()` answers "is there an assignment", which is the wrong question
        for a choice. Choosing which components to improve is a selection under
        constraints -- pick at most k, respect a risk ceiling, prefer the ones
        whose failure affects the most other services -- and that is an
        optimisation, so it needs Z3's Optimize rather than its Solver.

        Without this the only way to express a choice was to hand it to a
        language model as prose, which is why target selection was a chat
        prompt the substrate could not represent.

        `objective` is a Z3 arithmetic expression over the problem's variables.
        """
        if not self._available:
            return ConstraintSolution(
                satisfiable=False, model={}, raw_status="no_solver",
                error="Z3 solver not available in this environment",
            )

        opt = Optimize()

        z3_vars: Dict[str, Any] = {}
        for name, var in problem.variables.items():
            if var.vtype == "int":
                z3_var = Int(name)
            elif var.vtype == "real":
                z3_var = Real(name)
            elif var.vtype == "bool":
                z3_var = Bool(name)
            else:
                raise ValueError(f"Unsupported variable type: {var.vtype}")
            z3_vars[name] = z3_var
            if var.lower is not None:
                opt.add(z3_var >= var.lower)
            if var.upper is not None:
                opt.add(z3_var <= var.upper)

        for c in problem.constraints:
            opt.add(c)

        opt.maximize(objective) if maximize else opt.minimize(objective)

        status = opt.check()
        raw_status = str(status)
        if status != sat:
            return ConstraintSolution(satisfiable=False, model={},
                                      raw_status=raw_status)

        model = opt.model()
        values: Dict[str, Any] = {}
        for name, zvar in z3_vars.items():
            val = model[zvar]
            if val is None:
                continue
            if hasattr(val, "as_long"):
                values[name] = val.as_long()
            elif hasattr(val, "as_decimal"):
                values[name] = float(val.as_decimal(10).rstrip("?"))
            else:
                values[name] = bool(val)

        return ConstraintSolution(satisfiable=True, model=values,
                                  raw_status=raw_status)

    def solve_linear(self, variable: str, coefficient: int, constant: int,
                     target: int) -> ConstraintSolution:
        """Solve `coefficient * variable + constant = target` over the integers.

        Exists so callers do not have to import z3 to ask for the commonest
        case. Keeping the backend confined to this module is what makes
        severing it observable: with Z3 absent this returns `no_solver`, and a
        caller that wanted an answer gets a capability fault rather than a
        number from somewhere else.
        """
        if not self._available:
            return ConstraintSolution(
                satisfiable=False, model={}, raw_status="no_solver",
                error="Z3 solver not available in this environment")

        problem = self.create_problem()
        self.add_variable(problem, variable, "int")
        self.add_constraint(problem, coefficient * Int(variable) + constant == target)
        return self.solve(problem)


# Global helper
_constraint_solver: Optional[ConstraintSolver] = None


def get_constraint_solver() -> ConstraintSolver:
    """Get (or create) a global constraint solver instance."""
    global _constraint_solver
    if _constraint_solver is None:
        _constraint_solver = ConstraintSolver()
    return _constraint_solver
