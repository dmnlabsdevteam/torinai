#!/usr/bin/env python3
"""System Dynamics and State-Space Simulation
===========================================

Provides utilities for simulating linear state-space systems of the form:

    dx/dt = A x + B u(t)
    y     = C x + D u(t)

Both continuous-time simulation (via SciPy) and a simple explicit Euler fallback
are provided.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional, Sequence, Tuple

import numpy as np

logger = logging.getLogger(__name__)

try:
    from scipy.integrate import solve_ivp  # type: ignore

    _SCIPY_AVAILABLE = True
except Exception:  # pragma: no cover - optional dependency
    solve_ivp = None  # type: ignore
    _SCIPY_AVAILABLE = False


InputFunction = Callable[[float, Dict[str, Any]], np.ndarray]


@dataclass
class StateSpaceModel:
    """Linear state-space model."""

    A: np.ndarray
    B: np.ndarray
    C: np.ndarray
    D: np.ndarray
    input_dim: int
    output_dim: int


@dataclass
class StateSpaceConfig:
    """Configuration for state-space simulation."""

    t0: float
    t_end: float
    x0: Sequence[float]
    max_step: Optional[float] = None
    atol: float = 1e-6
    rtol: float = 1e-3


@dataclass
class StateSpaceResult:
    """Result of state-space simulation."""

    t: np.ndarray
    x: np.ndarray
    y: np.ndarray
    success: bool
    message: str


def simulate_state_space(
    model: StateSpaceModel,
    config: StateSpaceConfig,
    u_fn: Optional[InputFunction] = None,
    u_params: Optional[Dict[str, Any]] = None,
) -> StateSpaceResult:
    """Simulate a linear state-space system.

    If SciPy is available, solve_ivp is used; otherwise a fixed-step explicit
    Euler method is used as a fallback.
    """
    A = np.asarray(model.A, dtype=float)
    B = np.asarray(model.B, dtype=float)
    C = np.asarray(model.C, dtype=float)
    D = np.asarray(model.D, dtype=float)

    x0 = np.asarray(config.x0, dtype=float)
    n = x0.shape[0]

    u_params = u_params or {}

    if u_fn is None:
        def u_fn_local(t: float, params: Dict[str, Any]) -> np.ndarray:  # type: ignore
            return np.zeros(model.input_dim, dtype=float)

        u_fn_effective = u_fn_local
    else:
        u_fn_effective = u_fn

    def rhs(t: float, x: np.ndarray) -> np.ndarray:
        u = np.asarray(u_fn_effective(t, u_params), dtype=float)
        if u.shape[0] != model.input_dim:
            raise ValueError("Input function returned vector with wrong dimension")
        return A @ x + B @ u

    if _SCIPY_AVAILABLE:
        # Build solve_ivp arguments, avoiding passing None for max_step
        solve_kwargs = {
            "atol": config.atol,
            "rtol": config.rtol,
        }
        if config.max_step is not None:
            solve_kwargs["max_step"] = config.max_step

        sol = solve_ivp(
            rhs,
            (config.t0, config.t_end),
            x0,
            **solve_kwargs,
        )

        t = sol.t
        x = sol.y
        success = bool(sol.success)
        message = str(sol.message)
    else:
        # Explicit Euler fallback with uniform step
        steps = 1000
        if config.max_step is not None:
            steps = max(1, int((config.t_end - config.t0) / config.max_step))
        t = np.linspace(config.t0, config.t_end, steps + 1)
        dt = float(t[1] - t[0])
        x = np.zeros((n, steps + 1), dtype=float)
        x[:, 0] = x0
        for k in range(steps):
            x[:, k + 1] = x[:, k] + dt * rhs(t[k], x[:, k])
        success = True
        message = "Euler fallback used (SciPy not available)"

    # Compute outputs
    y_list = []
    for k in range(t.shape[0]):
        u = np.asarray(u_fn_effective(float(t[k]), u_params), dtype=float)
        y_k = C @ x[:, k] + D @ u
        y_list.append(y_k)
    y = np.stack(y_list, axis=1)

    return StateSpaceResult(
        t=t,
        x=x,
        y=y,
        success=success,
        message=message,
    )
