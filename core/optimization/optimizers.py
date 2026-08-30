#!/usr/bin/env python3
"""Optimization Engine
=====================

Provides optimization utilities for:
- Linear and mixed-integer linear programs (LP/MILP) via PuLP
- Black-box optimization via SciPy's optimize module
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np

logger = logging.getLogger(__name__)

try:  # PuLP for LP/MILP
    import pulp  # type: ignore

    _PULP_AVAILABLE = True
except Exception:  # pragma: no cover - optional dependency
    pulp = None  # type: ignore
    _PULP_AVAILABLE = False

try:  # SciPy for black-box optimization
    from scipy import optimize  # type: ignore

    _SCIPY_AVAILABLE = True
except Exception:  # pragma: no cover - optional dependency
    optimize = None  # type: ignore
    _SCIPY_AVAILABLE = False


# ---------------------------------------------------------------------------
# LP / MILP OPTIMIZATION (PuLP)
# ---------------------------------------------------------------------------


@dataclass
class LinearConstraint:
    """Linear constraint of the form sum(a_i x_i) (<=, >=, ==) b."""

    coefficients: Dict[str, float]
    sense: str  # "<=", ">=", "=="
    rhs: float


@dataclass
class LinearObjective:
    """Linear objective function."""

    coefficients: Dict[str, float]
    sense: str = "min"  # "min" or "max"


@dataclass
class LinearProblem:
    """Linear or mixed-integer optimization problem."""

    objective: LinearObjective
    constraints: List[LinearConstraint] = field(default_factory=list)
    var_bounds: Dict[str, Tuple[Optional[float], Optional[float]]] = field(default_factory=dict)
    var_categories: Dict[str, str] = field(default_factory=dict)  # "continuous", "integer", "binary"


@dataclass
class LinearSolution:
    """Solution to an LP/MILP problem."""

    status: str
    objective_value: Optional[float]
    variables: Dict[str, float]
    solver_status: Optional[str] = None
    error: Optional[str] = None


def solve_linear_problem(problem: LinearProblem) -> LinearSolution:
    """Solve a linear or mixed-integer optimization problem using PuLP.

    Raises RuntimeError if PuLP is not available.
    """
    if not _PULP_AVAILABLE:
        raise RuntimeError("PuLP is required for linear optimization but is not available")

    sense = problem.objective.sense.lower()
    if sense == "min":
        lp = pulp.LpProblem("torin_lp", pulp.LpMinimize)
    elif sense == "max":
        lp = pulp.LpProblem("torin_lp", pulp.LpMaximize)
    else:
        raise ValueError("Objective sense must be 'min' or 'max'")

    # Variables
    lp_vars: Dict[str, Any] = {}
    for name in set(list(problem.objective.coefficients.keys()) + [k for c in problem.constraints for k in c.coefficients.keys()]):
        low, up = problem.var_bounds.get(name, (None, None))
        cat_str = problem.var_categories.get(name, "continuous").lower()
        if cat_str == "continuous":
            cat = pulp.LpContinuous
        elif cat_str == "integer":
            cat = pulp.LpInteger
        elif cat_str == "binary":
            cat = pulp.LpBinary
        else:
            raise ValueError(f"Unknown variable category: {cat_str}")
        lp_vars[name] = pulp.LpVariable(name, lowBound=low, upBound=up, cat=cat)

    # Objective
    lp += pulp.lpSum(coef * lp_vars[name] for name, coef in problem.objective.coefficients.items())

    # Constraints
    for c in problem.constraints:
        expr = pulp.lpSum(coef * lp_vars[name] for name, coef in c.coefficients.items())
        if c.sense == "<=":
            lp += (expr <= c.rhs)
        elif c.sense == ">=":
            lp += (expr >= c.rhs)
        elif c.sense == "==":
            lp += (expr == c.rhs)
        else:
            raise ValueError(f"Unsupported constraint sense: {c.sense}")

    # Solve
    status_code = lp.solve()
    status_str = pulp.LpStatus[status_code]

    if status_str not in ("Optimal", "Feasible"):
        logger.warning("Linear solver did not find optimal/feasible solution: %s", status_str)

    if status_str == "Infeasible":
        return LinearSolution(
            status="infeasible",
            objective_value=None,
            variables={},
            solver_status=status_str,
        )

    solution_vars = {name: float(v.value()) for name, v in lp_vars.items() if v.value() is not None}

    return LinearSolution(
        status="optimal" if status_str == "Optimal" else "feasible",
        objective_value=float(pulp.value(lp.objective)) if solution_vars else None,
        variables=solution_vars,
        solver_status=status_str,
    )


# ---------------------------------------------------------------------------
# BLACK-BOX OPTIMIZATION (SciPy)
# ---------------------------------------------------------------------------


BlackBoxFunction = Callable[[np.ndarray, Dict[str, Any]], float]


@dataclass
class BlackBoxConfig:
    """Configuration for black-box optimization."""

    method: str = "Nelder-Mead"  # Any method supported by scipy.optimize.minimize
    max_iter: Optional[int] = None
    tol: Optional[float] = None


@dataclass
class BlackBoxResult:
    """Result of black-box optimization."""

    x_opt: np.ndarray
    f_opt: float
    success: bool
    message: str
    n_iter: int


def optimize_black_box(
    fn: BlackBoxFunction,
    x0: Sequence[float],
    bounds: Optional[Sequence[Tuple[float, float]]] = None,
    config: Optional[BlackBoxConfig] = None,
    params: Optional[Dict[str, Any]] = None,
) -> BlackBoxResult:
    """Optimize a black-box objective function using SciPy's minimize.

    Raises RuntimeError if SciPy is not available.
    """
    if not _SCIPY_AVAILABLE:
        raise RuntimeError("SciPy is required for black-box optimization but is not available")

    config = config or BlackBoxConfig()
    params = params or {}

    x0_arr = np.asarray(x0, dtype=float)

    def wrapped(x: np.ndarray) -> float:
        return float(fn(x, params))

    # Convert bounds
    scipy_bounds = None
    if bounds is not None:
        scipy_bounds = [(float(lo), float(hi)) for lo, hi in bounds]

    options: Dict[str, Any] = {}
    if config.max_iter is not None:
        options["maxiter"] = int(config.max_iter)
    if config.tol is not None:
        options["xatol"] = float(config.tol)

    res = optimize.minimize(
        wrapped,
        x0_arr,
        method=config.method,
        bounds=scipy_bounds,
        options=options if options else None,
    )

    return BlackBoxResult(
        x_opt=np.asarray(res.x, dtype=float),
        f_opt=float(res.fun),
        success=bool(res.success),
        message=str(res.message),
        n_iter=int(res.nit) if hasattr(res, "nit") else -1,
    )
