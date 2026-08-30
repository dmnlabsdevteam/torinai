#!/usr/bin/env python3
"""Numerical Simulation Engine
===========================

Provides numerical simulation utilities for:
- Ordinary differential equations (ODEs)
- Simple 1D parabolic PDEs (e.g., heat equation)
- Monte Carlo simulations

This module is designed for production use and integrates with SciPy when
available, with clear error messages if required backends are missing.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np

logger = logging.getLogger(__name__)

try:  # SciPy is required for ODE integration
    from scipy.integrate import solve_ivp  # type: ignore

    _SCIPY_AVAILABLE = True
except Exception:  # pragma: no cover - optional dependency
    solve_ivp = None  # type: ignore
    _SCIPY_AVAILABLE = False


# ---------------------------------------------------------------------------
# ODE SIMULATION
# ---------------------------------------------------------------------------


RHSFunction = Callable[[float, np.ndarray, Dict[str, Any]], np.ndarray]


@dataclass
class ODESystem:
    """Represents an ODE system dy/dt = f(t, y, params)."""

    rhs: RHSFunction
    params: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ODESimulationConfig:
    """Configuration for an ODE simulation."""

    t0: float
    t_end: float
    y0: Sequence[float]
    method: str = "RK45"
    max_step: Optional[float] = None
    atol: float = 1e-6
    rtol: float = 1e-3
    t_eval: Optional[Sequence[float]] = None
    dense_output: bool = False


@dataclass
class ODESimulationResult:
    """Result of an ODE simulation."""

    t: np.ndarray
    y: np.ndarray
    success: bool
    message: str


def simulate_ode(system: ODESystem, config: ODESimulationConfig) -> ODESimulationResult:
    """Simulate an ODE system using SciPy's solve_ivp.

    Raises RuntimeError if SciPy is not available.
    """
    if not _SCIPY_AVAILABLE:
        raise RuntimeError("SciPy is required for ODE simulation but is not available")

    y0 = np.asarray(config.y0, dtype=float)

    def _wrapped_rhs(t: float, y: np.ndarray) -> np.ndarray:
        return system.rhs(t, y, system.params)

    sol = solve_ivp(
        _wrapped_rhs,
        (config.t0, config.t_end),
        y0,
        method=config.method,
        t_eval=np.asarray(config.t_eval, dtype=float) if config.t_eval is not None else None,
        max_step=config.max_step,
        atol=config.atol,
        rtol=config.rtol,
        dense_output=config.dense_output,
    )

    if not sol.success:
        logger.warning("ODE simulation failed: %s", sol.message)

    return ODESimulationResult(
        t=sol.t,
        y=sol.y,
        success=bool(sol.success),
        message=str(sol.message),
    )


# ---------------------------------------------------------------------------
# SIMPLE 1D PARABOLIC PDE (HEAT EQUATION STYLE)
# ---------------------------------------------------------------------------


@dataclass
class PDE1DConfig:
    """Configuration for a simple 1D parabolic PDE using finite differences.

    We solve a PDE of the form:

        du/dt = alpha * d^2 u / dx^2

    on x in [0, L] with either fixed (Dirichlet) or insulated (Neumann)
    boundary conditions.
    """

    length: float
    nx: int
    dt: float
    t_steps: int
    alpha: float
    bc_type: str = "dirichlet"  # "dirichlet" or "neumann"
    u0: Optional[Sequence[float]] = None


@dataclass
class PDE1DResult:
    """Result of 1D PDE simulation."""

    x: np.ndarray
    t: np.ndarray
    u: np.ndarray  # shape (t_steps+1, nx)


def simulate_pde_1d(config: PDE1DConfig) -> PDE1DResult:
    """Simulate a simple 1D parabolic PDE using explicit Euler FD.

    This is intended for moderate grid sizes and stable dt satisfying the
    standard CFL-like condition for the heat equation.
    """
    nx = config.nx
    L = config.length
    dx = L / (nx - 1)
    dt = config.dt
    alpha = config.alpha

    r = alpha * dt / (dx * dx)
    if r > 0.5:
        logger.warning(
            "PDE scheme may be unstable: alpha*dt/dx^2 = %.3f > 0.5", r
        )

    x = np.linspace(0.0, L, nx)
    t = np.linspace(0.0, dt * config.t_steps, config.t_steps + 1)

    if config.u0 is not None:
        u0 = np.asarray(config.u0, dtype=float)
        if u0.shape[0] != nx:
            raise ValueError("Initial condition length does not match nx")
    else:
        u0 = np.zeros(nx, dtype=float)

    u = np.zeros((config.t_steps + 1, nx), dtype=float)
    u[0, :] = u0

    for n in range(config.t_steps):
        u_n = u[n, :].copy()
        u_np1 = u_n.copy()

        # Interior points
        u_np1[1:-1] = u_n[1:-1] + r * (u_n[2:] - 2.0 * u_n[1:-1] + u_n[:-2])

        if config.bc_type == "dirichlet":
            # Boundaries fixed at initial values
            u_np1[0] = u0[0]
            u_np1[-1] = u0[-1]
        elif config.bc_type == "neumann":
            # Zero-flux (insulated) boundaries
            u_np1[0] = u_np1[1]
            u_np1[-1] = u_np1[-2]
        else:
            raise ValueError(f"Unsupported bc_type: {config.bc_type}")

        u[n + 1, :] = u_np1

    return PDE1DResult(x=x, t=t, u=u)


# ---------------------------------------------------------------------------
# MONTE CARLO SIMULATION
# ---------------------------------------------------------------------------


MCFunction = Callable[[np.random.Generator, Dict[str, Any]], Any]


@dataclass
class MonteCarloConfig:
    """Configuration for Monte Carlo simulations."""

    n_samples: int
    seed: Optional[int] = None
    batch_size: int = 0  # 0 or 1 -> no explicit batching


@dataclass
class MonteCarloResult:
    """Monte Carlo simulation result."""

    samples: np.ndarray
    mean: float
    std: float


def run_monte_carlo(
    fn: MCFunction,
    config: MonteCarloConfig,
    params: Optional[Dict[str, Any]] = None,
) -> MonteCarloResult:
    """Run a Monte Carlo simulation.

    The user-provided function ``fn`` should accept a NumPy Generator and a
    params dict, and return a scalar or 1D array. Outputs are flattened into a
    1D array of samples.
    """
    params = params or {}
    rng = np.random.default_rng(config.seed)

    results: List[float] = []
    n = config.n_samples
    batch = max(int(config.batch_size), 0)

    remaining = n
    while remaining > 0:
        current_batch = remaining if batch in (0, 1) else min(batch, remaining)
        for _ in range(current_batch):
            value = fn(rng, params)
            arr = np.asarray(value, dtype=float).ravel()
            results.extend(arr.tolist())
        remaining -= current_batch

    samples = np.asarray(results, dtype=float)
    return MonteCarloResult(
        samples=samples,
        mean=float(samples.mean()) if samples.size > 0 else float("nan"),
        std=float(samples.std(ddof=1)) if samples.size > 1 else float("nan"),
    )
