#!/usr/bin/env python3
"""Unit tests for Torin's reasoning / simulation / optimization stack.

These tests exercise the new engines and tools directly (no LLM), to
ensure they behave correctly and are wired into the ToolRegistry.

Run with:
    python -m pytest tests/test_reasoning_simulation_stack.py
"""

import asyncio
from pathlib import Path

import numpy as np

# Ensure project root on path
import sys
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from core.reasoning.advanced_proof_engine import Theorem, LogicType, get_proof_engine
from core.reasoning.constraint_solver import get_constraint_solver
from core.simulation.numerical_simulation import (
    PDE1DConfig,
    simulate_pde_1d,
)
from core.simulation.system_dynamics import (
    StateSpaceModel,
    StateSpaceConfig,
    simulate_state_space,
)
from core.optimization.optimizers import (
    LinearObjective,
    LinearConstraint,
    LinearProblem,
    solve_linear_problem,
)
from core.tools.tool_registry import get_tool_registry


def test_smt_proof_simple_modus_ponens():
    """Prove a simple propositional theorem via SMT: P -> Q, P ⊢ Q."""
    engine = get_proof_engine()

    theorem = Theorem(
        theorem_id="test_modus_ponens",
        statement="Q",
        premises=["P -> Q", "P"],
        logic_type=LogicType.PROPOSITIONAL,
    )

    proof = asyncio.run(engine.prove_theorem(theorem))

    assert proof is not None
    assert proof.proved is True
    assert proof.method.value in {"smt", "resolution", "direct"}
    assert any(step.statement == "Q" or "Q" in step.statement for step in proof.steps)


def test_constraint_solver_basic_linear_system():
    """Solve a small linear CSP: x in [0,10], y in [0,10], x + y = 7, x >= 2."""
    from z3 import Int, And  # type: ignore

    solver = get_constraint_solver()
    assert solver.available, "Z3 solver must be available for this test"

    problem = solver.create_problem()
    solver.add_variable(problem, "x", vtype="int", lower=0, upper=10)
    solver.add_variable(problem, "y", vtype="int", lower=0, upper=10)

    x = Int("x")
    y = Int("y")
    solver.add_constraint(problem, And(x + y == 7, x >= 2))

    solution = solver.solve(problem)
    assert solution.satisfiable is True
    assert solution.model["x"] >= 2
    assert solution.model["x"] + solution.model["y"] == 7


def test_linear_optimization_min_cost():
    """Solve a simple LP: minimize x + y s.t. x + 2y >= 4, x,y >= 0."""
    objective = LinearObjective(coefficients={"x": 1.0, "y": 1.0}, sense="min")
    constraints = [
        LinearConstraint(coefficients={"x": 1.0, "y": 2.0}, sense=">=", rhs=4.0),
    ]
    bounds = {"x": (0.0, None), "y": (0.0, None)}

    problem = LinearProblem(
        objective=objective,
        constraints=constraints,
        var_bounds=bounds,
        var_categories={"x": "continuous", "y": "continuous"},
    )

    solution = solve_linear_problem(problem)
    assert solution.status in {"optimal", "feasible"}
    assert solution.objective_value is not None
    assert solution.variables["x"] >= 0.0
    assert solution.variables["y"] >= 0.0
    assert solution.variables["x"] + 2 * solution.variables["y"] >= 4.0 - 1e-6


def test_pde_1d_heat_diffusion():
    """Run a small 1D heat-equation simulation and check basic properties."""
    nx = 11
    u0 = np.zeros(nx, dtype=float)
    u0[nx // 2] = 1.0  # central spike

    config = PDE1DConfig(
        length=1.0,
        nx=nx,
        dt=0.0005,
        t_steps=100,
        alpha=0.1,
        bc_type="dirichlet",
        u0=u0,
    )

    result = simulate_pde_1d(config)

    assert result.u.shape == (config.t_steps + 1, nx)
    # Total heat should be approximately conserved for small dt (Dirichlet fixed at 0)
    initial_sum = float(result.u[0].sum())
    final_sum = float(result.u[-1].sum())
    assert abs(final_sum) <= initial_sum + 1e-2


def test_state_space_stable_system():
    """Simulate a simple stable 1D system dx/dt = -x with zero input."""
    A = np.array([[-1.0]])
    B = np.array([[0.0]])
    C = np.array([[1.0]])
    D = np.array([[0.0]])

    model = StateSpaceModel(A=A, B=B, C=C, D=D, input_dim=1, output_dim=1)
    config = StateSpaceConfig(t0=0.0, t_end=1.0, x0=[1.0])

    result = simulate_state_space(model, config)

    assert result.success is True
    assert result.x.shape[0] == 1
    # State should decay toward zero
    assert abs(result.x[:, -1][0]) < 1.0


def test_tool_registry_reasoning_tools_available():
    """Smoke-test that new tools are registered and callable via ToolRegistry."""
    registry = get_tool_registry()

    # ProveTheoremTool via execute_tool
    proof_result = asyncio.run(
        registry.execute_tool(
            "prove_theorem",
            {
                "statement": "Q",
                "premises": ["P -> Q", "P"],
                "logic_type": "propositional",
            },
        )
    )
    assert proof_result.success is True
    assert proof_result.output["proved"] is True

    # SolveConstraintsTool via execute_tool
    constraints_result = asyncio.run(
        registry.execute_tool(
            "solve_constraints",
            {
                "variables": [
                    {"name": "x", "vtype": "int", "lower": 0, "upper": 10},
                    {"name": "y", "vtype": "int", "lower": 0, "upper": 10},
                ],
                "constraints": [
                    {
                        "type": "op",
                        "op": "and",
                        "args": [
                            {
                                "type": "op",
                                "op": "==",
                                "args": [
                                    {"type": "op", "op": "+", "args": [
                                        {"type": "var", "name": "x"},
                                        {"type": "var", "name": "y"},
                                    ]},
                                    {"type": "const", "value": 7},
                                ],
                            },
                            {
                                "type": "op",
                                "op": ">=",
                                "args": [
                                    {"type": "var", "name": "x"},
                                    {"type": "const", "value": 2},
                                ],
                            },
                        ],
                    }
                ],
            },
        )
    )
    assert constraints_result.success is True
    assert constraints_result.output["satisfiable"] is True

    # SolveLinearOptimizationTool via execute_tool
    lp_result = asyncio.run(
        registry.execute_tool(
            "solve_linear_optimization",
            {
                "objective": {"sense": "min", "coefficients": {"x": 1.0, "y": 1.0}},
                "constraints": [
                    {
                        "coefficients": {"x": 1.0, "y": 2.0},
                        "sense": ">=",
                        "rhs": 4.0,
                    }
                ],
                "var_bounds": {"x": [0.0, None], "y": [0.0, None]},
                "var_categories": {"x": "continuous", "y": "continuous"},
            },
        )
    )
    assert lp_result.success is True
    assert lp_result.output["status"] in {"optimal", "feasible"}


if __name__ == "__main__":
    # Allow running directly for quick local sanity check
    import pytest

    raise SystemExit(pytest.main([__file__]))
