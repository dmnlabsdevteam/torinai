#!/usr/bin/env python3
"""Reasoning, Simulation, and Optimization Tools
================================================

High-level tools that expose Torin's industrial-grade reasoning engines
to agents in a robust, JSON-friendly way.

These tools are thin, fully implemented adapters over the underlying
engines in:
- core.reasoning.advanced_proof_engine (SMT-backed proving)
- core.reasoning.constraint_solver (Z3-based CSP/SMT)
- core.simulation.numerical_simulation (PDE/Monte Carlo)
- core.simulation.system_dynamics (state-space simulation)
- core.optimization.optimizers (LP/MILP and black-box optimization)

They do not reduce functionality; they validate inputs, handle
dependency availability, and return structured results suitable for
agent consumption.
"""

from __future__ import annotations

import logging
from dataclasses import asdict
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from .tool_registry import Tool, ToolParameter, ToolResult, ToolCategory, ToolSafety
from .capabilities import (
    ToolCapabilityProfile, CapabilityMetadata, Capability, RiskLevel
)

from core.reasoning.advanced_proof_engine import (
    Theorem,
    LogicType,
    get_proof_engine,
)
from core.reasoning.constraint_solver import (
    get_constraint_solver,
)
from core.simulation.numerical_simulation import (
    PDE1DConfig,
    simulate_pde_1d,
    MonteCarloConfig,
    run_monte_carlo,
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

try:  # Optional Z3 import for structured constraint expressions
    from z3 import Int, Real, Bool, And, Or, Not  # type: ignore

    _Z3_AVAILABLE = True
except Exception:  # pragma: no cover - optional dependency
    Int = Real = Bool = And = Or = Not = None  # type: ignore
    _Z3_AVAILABLE = False


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# PROOF ENGINE TOOL
# ---------------------------------------------------------------------------


class ProveTheoremTool(Tool):
    """Invoke the Advanced Proof Engine on a theorem.

    Uses the SMT-backed path when available and falls back to other
    proof strategies as implemented by AdvancedProofEngine.
    """

    def __init__(self) -> None:
        super().__init__()
        self.name = "prove_theorem"
        self.description = (
            "Prove a logical theorem given premises using Torin's Advanced "
            "Proof Engine (SMT-backed when available)."
        )
        self.category = ToolCategory.REASONING
        self.safety_level = ToolSafety.SAFE
        self.parameters = [
            ToolParameter(
                name="statement",
                type="string",
                description="The theorem statement to prove (e.g., 'Q').",
                required=True,
            ),
            ToolParameter(
                name="premises",
                type="array",
                description=(
                    "List of premise strings (e.g., ['P -> Q', 'P']). "
                    "Current SMT backend supports &, |, ~, -> over atoms."
                ),
                required=True,
            ),
            ToolParameter(
                name="logic_type",
                type="string",
                description=(
                    "Logic type: 'propositional' or 'first_order'. This "
                    "guides proof method selection."
                ),
                required=False,
                default="propositional",
                enum=[lt.value for lt in LogicType],
            ),
            ToolParameter(
                name="theorem_id",
                type="string",
                description=(
                    "Optional theorem identifier. If omitted, a synthetic "
                    "ID is generated."
                ),
                required=False,
            ),
            ToolParameter(
                name="max_steps",
                type="number",
                description="Maximum proof steps to attempt.",
                required=False,
                default=100,
                min_value=1,
            ),
            ToolParameter(
                name="timeout",
                type="number",
                description="Timeout in seconds for the proof attempt.",
                required=False,
                default=30.0,
                min_value=0.1,
            ),
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="prove_theorem",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.DEDUCTIVE_REASONING,
                    description="Prove logical theorems using deductive reasoning with SMT-backed verification",
                    input_types=["theorem_statement", "premises", "logic_type"],
                    output_types=["proof_steps", "proof_result"],
                    latency="medium",
                    cost="medium",
                    reliability="high",
                    risk_level=RiskLevel.LOW,
                    priority=9
                ),
                CapabilityMetadata(
                    capability=Capability.EXPLAIN_REASONING,
                    description="Generate step-by-step proof explanations with justifications",
                    input_types=["theorem", "premises"],
                    output_types=["proof_trace"],
                    latency="medium",
                    cost="medium",
                    reliability="high",
                    risk_level=RiskLevel.LOW,
                    priority=8
                ),
                CapabilityMetadata(
                    capability=Capability.VALIDATE_CLAIM,
                    description="Validate logical claims against premises using formal methods",
                    input_types=["statement", "premises"],
                    output_types=["validity_result"],
                    latency="medium",
                    cost="medium",
                    reliability="high",
                    risk_level=RiskLevel.LOW,
                    priority=8
                ),
                CapabilityMetadata(
                    capability=Capability.ABDUCTIVE_REASONING,
                    description="Reason backward from observations to best explanation",
                    input_types=["observations"],
                    output_types=["explanation"],
                    latency="medium",
                    cost="medium",
                    reliability="high",
                    risk_level=RiskLevel.LOW,
                    priority=8
                )
            ],
            requires_filesystem=False,
            requires_network=False,
            requires_database=False,
            is_idempotent=True
        )

    async def execute(
        self,
        statement: str,
        premises: Sequence[str],
        logic_type: str = "propositional",
        theorem_id: Optional[str] = None,
        max_steps: int = 100,
        timeout: float = 30.0,
    ) -> ToolResult:
        try:
            if not theorem_id:
                import uuid
                theorem_id = f"tool_theorem_{uuid.uuid4().hex[:8]}"

            # THROUGH THE REASONING AUTHORITY, NOT AROUND IT. Proving a theorem
            # is reasoning, and there is ONE reasoning authority:
            # NeuralSymbolicBridge.reason(). This used to call get_proof_engine()
            # directly -- the same prover the logical kind uses -- so a proof
            # obtained through this tool was unverified, unrecorded, and off the
            # one path the architecture is built around. Now the goal and its
            # premises are submitted to the authority with the LOGICAL kind, and
            # the authority's own verdict is reported. logic_type/max_steps/
            # timeout are accepted for compatibility; the authority selects the
            # proof strategy.
            from core.reasoning.neural_bridge import get_neural_bridge, ReasoningRequest
            from core.reasoning.reasoning_interfaces import ReasoningType

            bridge = get_neural_bridge()
            if hasattr(bridge, "initialize"):
                await bridge.initialize()

            result = await bridge.reason(ReasoningRequest(
                query=statement,
                context=list(premises),
                kinds=[ReasoningType.LOGICAL],
            ))
            md = getattr(result, "metadata", {}) or {}
            answer = str(getattr(result, "answer", "") or "")
            proved = bool(md.get("proved")) or answer.lower().startswith("proved")

            output = {
                "theorem_id": theorem_id,
                "proved": proved,
                "verified": bool(md.get("verified")),
                # Which reasoning path settled it (logical kind, or substrate
                # proof as fallback), so the tool result is traceable to the
                # authority rather than to a private engine call.
                "method": md.get("kind") or md.get("reason"),
                "route": md.get("route"),
                "confidence": float(getattr(result, "confidence", 0.0) or 0.0),
                "answer": answer,
                "steps": list(getattr(result, "reasoning_steps", ()) or ()),
                "error": None if proved or md.get("verified") else md.get("reason"),
            }
            return ToolResult(success=True, output=output)

        except Exception as e:  # Robust error surface
            logger.error("ProveTheoremTool error: %s", e, exc_info=True)
            return ToolResult(success=False, output=None, error=str(e))


# ---------------------------------------------------------------------------
# CONSTRAINT SOLVER TOOL (Z3-BASED CSP/SMT)
# ---------------------------------------------------------------------------


def _build_z3_expr(node: Any, z3_vars: Dict[str, Any]) -> Any:
    """Build a Z3 expression from a structured JSON-like node.

    Supported node forms:
        {"type": "var", "name": "x"}
        {"type": "const", "value": 5}
        {"type": "op", "op": "+", "args": [ ... ]}
        {"type": "op", "op": "-", "args": [ ... ]}
        {"type": "op", "op": "*", "args": [ ... ]}
        {"type": "op", "op": "/", "args": [ ... ]}
        {"type": "op", "op": "and", "args": [ ... ]}
        {"type": "op", "op": "or", "args": [ ... ]}
        {"type": "op", "op": "not", "args": [ ... ]}
        {"type": "op", "op": "<=", "args": [left, right]}
        (similarly for ">=", "<", ">", "==")
    """

    if not _Z3_AVAILABLE:
        raise RuntimeError("Z3 is required for constraint solving but is not available")

    if not isinstance(node, dict):
        raise ValueError(f"Constraint expression node must be object, got {type(node)}")

    node_type = node.get("type")

    if node_type == "var":
        name = node.get("name")
        if name not in z3_vars:
            raise KeyError(f"Unknown variable in constraint expression: {name}")
        return z3_vars[name]

    if node_type == "const":
        return node.get("value")

    if node_type == "op":
        op = node.get("op")
        args = node.get("args", [])
        if not isinstance(args, list):
            raise ValueError("'args' for op node must be a list")

        built_args = [_build_z3_expr(a, z3_vars) for a in args]

        if op == "+":
            if not built_args:
                raise ValueError("'+' op requires at least one argument")
            expr = built_args[0]
            for a in built_args[1:]:
                expr = expr + a
            return expr
        if op == "-":
            if len(built_args) == 1:
                return -built_args[0]
            if len(built_args) != 2:
                raise ValueError("'-' op requires 1 or 2 args")
            return built_args[0] - built_args[1]
        if op == "*":
            if not built_args:
                raise ValueError("'*' op requires at least one argument")
            expr = built_args[0]
            for a in built_args[1:]:
                expr = expr * a
            return expr
        if op == "/":
            if len(built_args) != 2:
                raise ValueError("'/' op requires exactly 2 args")
            return built_args[0] / built_args[1]
        if op == "and":
            return And(*built_args)
        if op == "or":
            return Or(*built_args)
        if op == "not":
            if len(built_args) != 1:
                raise ValueError("'not' op requires exactly 1 arg")
            return Not(built_args[0])
        if op in {"<=", ">=", "<", ">", "=="}:
            if len(built_args) != 2:
                raise ValueError(f"'{op}' comparison requires exactly 2 args")
            left, right = built_args
            if op == "<=":
                return left <= right
            if op == ">=":
                return left >= right
            if op == "<":
                return left < right
            if op == ">":
                return left > right
            return left == right

        raise ValueError(f"Unsupported operator in constraint expression: {op}")

    raise ValueError(f"Unsupported node type in constraint expression: {node_type}")


class SolveConstraintsTool(Tool):
    """Solve a constraint satisfaction problem using the Z3-based solver.

    This exposes core.reasoning.constraint_solver through a structured,
    JSON-based constraint language. It is fully implemented and expects
    well-formed variable and constraint specifications.
    """

    def __init__(self) -> None:
        super().__init__()
        self.name = "solve_constraints"
        self.description = (
            "Solve numeric/boolean constraints over named variables using a "
            "Z3-backed CSP/SMT solver and return a satisfying assignment if "
            "one exists."
        )
        self.category = ToolCategory.REASONING
        self.safety_level = ToolSafety.SAFE
        self.parameters = [
            ToolParameter(
                name="variables",
                type="array",
                description=(
                    "List of variable specs: {name, vtype: 'int'|'real'|'bool', "
                    "lower?, upper?}."
                ),
                required=True,
            ),
            ToolParameter(
                name="constraints",
                type="array",
                description=(
                    "List of structured constraint expressions using nodes of "
                    "form {type: 'var'|'const'|'op', ...}. See tool docs for "
                    "the exact mini-language."
                ),
                required=True,
            ),
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="solve_constraints",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.CONSTRAINT_REASONING,
                    description="Solve constraint satisfaction problems using Z3 SMT solver",
                    input_types=["variables", "constraints"],
                    output_types=["constraint_solution"],
                    latency="medium",
                    cost="medium",
                    reliability="high",
                    risk_level=RiskLevel.LOW,
                    priority=9
                ),
                CapabilityMetadata(
                    capability=Capability.DEDUCTIVE_REASONING,
                    description="Find solutions satisfying logical and arithmetic constraints",
                    input_types=["constraint_specification"],
                    output_types=["satisfying_assignment"],
                    latency="medium",
                    cost="medium",
                    reliability="high",
                    risk_level=RiskLevel.LOW,
                    priority=8
                ),
                CapabilityMetadata(
                    capability=Capability.VALIDATE_CLAIM,
                    description="Verify if constraint solutions satisfy all requirements",
                    input_types=["variables", "constraints"],
                    output_types=["validation_result"],
                    latency="medium",
                    cost="medium",
                    reliability="high",
                    risk_level=RiskLevel.LOW,
                    priority=7
                ),
                CapabilityMetadata(
                    capability=Capability.RESOLVE_CONTRADICTION,
                    description="Resolve contradictions through constraint solving",
                    input_types=["constraints", "contradiction"],
                    output_types=["resolution"],
                    latency="medium",
                    cost="medium",
                    reliability="high",
                    risk_level=RiskLevel.MEDIUM,
                    priority=7
                )
            ],
            requires_filesystem=False,
            requires_network=False,
            requires_database=False,
            is_idempotent=True
        )

    async def execute(
        self,
        variables: Sequence[Dict[str, Any]],
        constraints: Sequence[Dict[str, Any]],
    ) -> ToolResult:
        try:
            solver = get_constraint_solver()
            if not solver.available:
                return ToolResult(
                    success=False,
                    output=None,
                    error="Z3 solver not available in this environment",
                )

            if not _Z3_AVAILABLE:
                return ToolResult(
                    success=False,
                    output=None,
                    error="Z3 Python bindings are not available",
                )

            problem = solver.create_problem()

            # Register variables
            z3_vars: Dict[str, Any] = {}
            for var in variables:
                name = var.get("name")
                vtype = var.get("vtype", "int")
                lower = var.get("lower")
                upper = var.get("upper")

                if not name or not isinstance(name, str):
                    raise ValueError("Each variable must have a non-empty string 'name'")
                if vtype not in {"int", "real", "bool"}:
                    raise ValueError(f"Unsupported variable type: {vtype}")

                solver.add_variable(problem, name=name, vtype=vtype, lower=lower, upper=upper)

                if vtype == "int":
                    z3_vars[name] = Int(name)
                elif vtype == "real":
                    z3_vars[name] = Real(name)
                else:
                    z3_vars[name] = Bool(name)

            # Build and add constraints
            for node in constraints:
                expr = _build_z3_expr(node, z3_vars)
                solver.add_constraint(problem, expr)

            solution = solver.solve(problem)

            output = {
                "satisfiable": solution.satisfiable,
                "model": dict(solution.model),
                "raw_status": solution.raw_status,
                "error": solution.error,
            }

            return ToolResult(success=solution.satisfiable, output=output)

        except Exception as e:
            logger.error("SolveConstraintsTool error: %s", e, exc_info=True)
            return ToolResult(success=False, output=None, error=str(e))


# ---------------------------------------------------------------------------
# LINEAR OPTIMIZATION TOOL (LP/MILP VIA PULP)
# ---------------------------------------------------------------------------


class SolveLinearOptimizationTool(Tool):
    """Solve LP/MILP problems via PuLP.

    Accepts an objective and linear constraints in coefficient form and
    returns the optimal (or feasible) solution if found.
    """

    def __init__(self) -> None:
        super().__init__()
        self.name = "solve_linear_optimization"
        self.description = (
            "Solve linear or mixed-integer optimization problems using PuLP "
            "(LP/MILP)."
        )
        self.category = ToolCategory.REASONING
        self.safety_level = ToolSafety.SAFE
        self.parameters = [
            ToolParameter(
                name="objective",
                type="object",
                description=(
                    "Objective spec: {sense: 'min'|'max', coefficients: {var: coef, ...}}."
                ),
                required=True,
            ),
            ToolParameter(
                name="constraints",
                type="array",
                description=(
                    "List of constraints: {coefficients: {var: coef, ...}, "
                    "sense: '<='|'>='|'==', rhs: number}."
                ),
                required=False,
                default=[],
            ),
            ToolParameter(
                name="var_bounds",
                type="object",
                description=(
                    "Variable bounds: {var: [lower, upper]} (either may be null)."
                ),
                required=False,
                default={},
            ),
            ToolParameter(
                name="var_categories",
                type="object",
                description=(
                    "Variable categories: {var: 'continuous'|'integer'|'binary'}."
                ),
                required=False,
                default={},
            ),
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="solve_linear_optimization",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.CONSTRAINT_REASONING,
                    description="Optimize linear objectives subject to linear constraints using LP/MILP",
                    input_types=["objective", "constraints", "variable_bounds"],
                    output_types=["optimal_solution"],
                    latency="medium",
                    cost="medium",
                    reliability="high",
                    risk_level=RiskLevel.LOW,
                    priority=9
                ),
                CapabilityMetadata(
                    capability=Capability.DEDUCTIVE_REASONING,
                    description="Find optimal solutions satisfying all constraints",
                    input_types=["linear_problem"],
                    output_types=["optimization_result"],
                    latency="medium",
                    cost="medium",
                    reliability="high",
                    risk_level=RiskLevel.LOW,
                    priority=8
                ),
                CapabilityMetadata(
                    capability=Capability.ALLOCATE_RESOURCES,
                    description="Optimize resource allocation given constraints and objectives",
                    input_types=["objective", "resource_constraints"],
                    output_types=["allocation_plan"],
                    latency="medium",
                    cost="medium",
                    reliability="high",
                    risk_level=RiskLevel.MEDIUM,
                    priority=8
                )
            ],
            requires_filesystem=False,
            requires_network=False,
            requires_database=False,
            is_idempotent=True
        )

    async def execute(
        self,
        objective: Dict[str, Any],
        constraints: Optional[Sequence[Dict[str, Any]]] = None,
        var_bounds: Optional[Dict[str, Sequence[Optional[float]]]] = None,
        var_categories: Optional[Dict[str, str]] = None,
    ) -> ToolResult:
        constraints = list(constraints or [])
        var_bounds = var_bounds or {}
        var_categories = var_categories or {}

        try:
            obj_sense = str(objective.get("sense", "min")).lower()
            coeffs = objective.get("coefficients", {})
            if not isinstance(coeffs, dict) or not coeffs:
                raise ValueError("Objective.coefficients must be a non-empty object")

            lin_obj = LinearObjective(coefficients={str(k): float(v) for k, v in coeffs.items()}, sense=obj_sense)

            lin_constraints: List[LinearConstraint] = []
            for c in constraints:
                c_coeffs = c.get("coefficients", {})
                sense = c.get("sense")
                rhs = c.get("rhs")
                if sense not in {"<=", ">=", "=="}:
                    raise ValueError(f"Unsupported constraint sense: {sense}")
                if not isinstance(c_coeffs, dict):
                    raise ValueError("Constraint.coefficients must be an object")
                lin_constraints.append(
                    LinearConstraint(
                        coefficients={str(k): float(v) for k, v in c_coeffs.items()},
                        sense=sense,
                        rhs=float(rhs),
                    )
                )

            bounds: Dict[str, Tuple[Optional[float], Optional[float]]] = {}
            for name, pair in var_bounds.items():
                if not isinstance(pair, (list, tuple)) or len(pair) != 2:
                    raise ValueError("Each var_bounds entry must be [lower, upper]")
                lower, upper = pair
                bounds[str(name)] = (
                    float(lower) if lower is not None else None,
                    float(upper) if upper is not None else None,
                )

            categories = {str(k): str(v).lower() for k, v in var_categories.items()}

            problem = LinearProblem(
                objective=lin_obj,
                constraints=lin_constraints,
                var_bounds=bounds,
                var_categories=categories,
            )

            solution = solve_linear_problem(problem)

            output = asdict(solution)
            return ToolResult(success=solution.status in {"optimal", "feasible"}, output=output)

        except Exception as e:
            logger.error("SolveLinearOptimizationTool error: %s", e, exc_info=True)
            return ToolResult(success=False, output=None, error=str(e))


# ---------------------------------------------------------------------------
# PDE SIMULATION TOOL (1D HEAT-EQUATION STYLE)
# ---------------------------------------------------------------------------


class SimulatePDE1DTool(Tool):
    """Simulate a simple 1D parabolic PDE (heat-equation style).

    This uses an explicit finite-difference scheme and is suitable for
    moderate grid sizes; it directly exposes PDE1DConfig fields.
    """

    def __init__(self) -> None:
        super().__init__()
        self.name = "simulate_pde_1d"
        self.description = (
            "Simulate a 1D parabolic PDE du/dt = alpha * d^2u/dx^2 over a "
            "finite domain using explicit finite differences."
        )
        self.category = ToolCategory.REASONING
        self.safety_level = ToolSafety.SAFE
        self.parameters = [
            ToolParameter(
                name="length",
                type="number",
                description="Domain length L (x in [0, L]).",
                required=True,
                min_value=0.0,
            ),
            ToolParameter(
                name="nx",
                type="number",
                description="Number of spatial grid points.",
                required=True,
                min_value=3,
            ),
            ToolParameter(
                name="dt",
                type="number",
                description="Time step size.",
                required=True,
                min_value=0.0,
            ),
            ToolParameter(
                name="t_steps",
                type="number",
                description="Number of time steps to simulate.",
                required=True,
                min_value=1,
            ),
            ToolParameter(
                name="alpha",
                type="number",
                description="Diffusion coefficient alpha.",
                required=True,
            ),
            ToolParameter(
                name="bc_type",
                type="string",
                description="Boundary condition type: 'dirichlet' or 'neumann'.",
                required=False,
                default="dirichlet",
                enum=["dirichlet", "neumann"],
            ),
            ToolParameter(
                name="u0",
                type="array",
                description=(
                    "Initial condition values at each grid point (length nx). "
                    "If omitted, zeros are used."
                ),
                required=False,
            ),
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="simulate_pde_1d",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.TEMPORAL_REASONING,
                    description="Simulate time-evolution of 1D parabolic PDEs using finite differences",
                    input_types=["pde_config", "initial_conditions", "boundary_conditions"],
                    output_types=["time_series_solution"],
                    latency="high",
                    cost="medium",
                    reliability="high",
                    risk_level=RiskLevel.LOW,
                    priority=8
                ),
                CapabilityMetadata(
                    capability=Capability.SPATIAL_REASONING,
                    description="Model spatial diffusion processes over finite domains",
                    input_types=["domain_config", "diffusion_coefficient"],
                    output_types=["spatial_distribution"],
                    latency="high",
                    cost="medium",
                    reliability="high",
                    risk_level=RiskLevel.LOW,
                    priority=7
                ),
                CapabilityMetadata(
                    capability=Capability.CAUSAL_REASONING,
                    description="Analyze cause-effect relationships in physical diffusion processes",
                    input_types=["pde_parameters"],
                    output_types=["simulation_results"],
                    latency="high",
                    cost="medium",
                    reliability="high",
                    risk_level=RiskLevel.LOW,
                    priority=7
                ),
                CapabilityMetadata(
                    capability=Capability.RUN_EXPERIMENT,
                    description="Execute numerical experiments for PDE-based physical systems",
                    input_types=["experimental_config"],
                    output_types=["experimental_data"],
                    latency="high",
                    cost="medium",
                    reliability="high",
                    risk_level=RiskLevel.LOW,
                    priority=7
                )
            ],
            requires_filesystem=False,
            requires_network=False,
            requires_database=False,
            is_idempotent=True
        )

    async def execute(
        self,
        length: float,
        nx: int,
        dt: float,
        t_steps: int,
        alpha: float,
        bc_type: str = "dirichlet",
        u0: Optional[Sequence[float]] = None,
    ) -> ToolResult:
        try:
            if nx < 3:
                raise ValueError("nx must be at least 3")
            if dt <= 0.0:
                raise ValueError("dt must be positive")
            if t_steps < 1:
                raise ValueError("t_steps must be at least 1")

            config = PDE1DConfig(
                length=float(length),
                nx=int(nx),
                dt=float(dt),
                t_steps=int(t_steps),
                alpha=float(alpha),
                bc_type=str(bc_type),
                u0=list(u0) if u0 is not None else None,
            )

            result = simulate_pde_1d(config)

            output = {
                "x": result.x.tolist(),
                "t": result.t.tolist(),
                "u": result.u.tolist(),
            }

            return ToolResult(success=True, output=output)

        except Exception as e:
            logger.error("SimulatePDE1DTool error: %s", e, exc_info=True)
            return ToolResult(success=False, output=None, error=str(e))


# ---------------------------------------------------------------------------
# STATE-SPACE SIMULATION TOOL
# ---------------------------------------------------------------------------


class SimulateStateSpaceTool(Tool):
    """Simulate linear state-space systems dx/dt = A x + B u(t).

    Agents specify A, B, C, D matrices and a simple input description:
    - no input (u(t) = 0)
    - constant input vector
    - piecewise-constant schedule with linear interpolation
    """

    def __init__(self) -> None:
        super().__init__()
        self.name = "simulate_state_space"
        self.description = (
            "Simulate a linear state-space system dx/dt = A x + B u(t), "
            "y = C x + D u(t) using SciPy or an explicit Euler fallback."
        )
        self.category = ToolCategory.REASONING
        self.safety_level = ToolSafety.SAFE
        self.parameters = [
            ToolParameter(
                name="A",
                type="array",
                description="State matrix A (2D array).",
                required=True,
            ),
            ToolParameter(
                name="B",
                type="array",
                description="Input matrix B (2D array).",
                required=True,
            ),
            ToolParameter(
                name="C",
                type="array",
                description="Output matrix C (2D array).",
                required=True,
            ),
            ToolParameter(
                name="D",
                type="array",
                description="Feedthrough matrix D (2D array).",
                required=True,
            ),
            ToolParameter(
                name="t0",
                type="number",
                description="Initial time.",
                required=True,
            ),
            ToolParameter(
                name="t_end",
                type="number",
                description="Final time.",
                required=True,
            ),
            ToolParameter(
                name="x0",
                type="array",
                description="Initial state vector.",
                required=True,
            ),
            ToolParameter(
                name="max_step",
                type="number",
                description="Maximum step size (optional).",
                required=False,
            ),
            ToolParameter(
                name="input_type",
                type="string",
                description=(
                    "Input type: 'none' (u=0), 'constant' (fixed vector), "
                    "or 'schedule' (time/value pairs)."
                ),
                required=False,
                default="none",
                enum=["none", "constant", "schedule"],
            ),
            ToolParameter(
                name="u_constant",
                type="array",
                description="Constant input vector (for input_type='constant').",
                required=False,
            ),
            ToolParameter(
                name="u_schedule",
                type="array",
                description=(
                    "Input schedule for input_type='schedule': list of "
                    "{t: float, u: [..]} entries. Linear interpolation in t."
                ),
                required=False,
            ),
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="simulate_state_space",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.TEMPORAL_REASONING,
                    description="Simulate temporal evolution of linear state-space systems",
                    input_types=["state_matrices", "initial_conditions", "input_schedule"],
                    output_types=["state_trajectory", "output_trajectory"],
                    latency="high",
                    cost="medium",
                    reliability="high",
                    risk_level=RiskLevel.LOW,
                    priority=8
                ),
                CapabilityMetadata(
                    capability=Capability.CAUSAL_REASONING,
                    description="Model cause-effect relationships in dynamical systems",
                    input_types=["system_matrices", "inputs"],
                    output_types=["system_response"],
                    latency="high",
                    cost="medium",
                    reliability="high",
                    risk_level=RiskLevel.LOW,
                    priority=8
                ),
                CapabilityMetadata(
                    capability=Capability.PREDICT_CONSEQUENCES,
                    description="Predict system behavior given initial conditions and inputs",
                    input_types=["system_model", "initial_state", "control_inputs"],
                    output_types=["predicted_trajectory"],
                    latency="high",
                    cost="medium",
                    reliability="high",
                    risk_level=RiskLevel.LOW,
                    priority=7
                ),
                CapabilityMetadata(
                    capability=Capability.RUN_EXPERIMENT,
                    description="Execute controlled experiments on linear dynamical systems",
                    input_types=["experimental_design"],
                    output_types=["experimental_results"],
                    latency="high",
                    cost="medium",
                    reliability="high",
                    risk_level=RiskLevel.LOW,
                    priority=7
                )
            ],
            requires_filesystem=False,
            requires_network=False,
            requires_database=False,
            is_idempotent=True
        )

    async def execute(
        self,
        A: Sequence[Sequence[float]],
        B: Sequence[Sequence[float]],
        C: Sequence[Sequence[float]],
        D: Sequence[Sequence[float]],
        t0: float,
        t_end: float,
        x0: Sequence[float],
        max_step: Optional[float] = None,
        input_type: str = "none",
        u_constant: Optional[Sequence[float]] = None,
        u_schedule: Optional[Sequence[Dict[str, Any]]] = None,
    ) -> ToolResult:
        try:
            A_arr = np.asarray(A, dtype=float)
            B_arr = np.asarray(B, dtype=float)
            C_arr = np.asarray(C, dtype=float)
            D_arr = np.asarray(D, dtype=float)
            x0_arr = np.asarray(x0, dtype=float)

            n = x0_arr.shape[0]
            if A_arr.shape[0] != n or A_arr.shape[1] != n:
                raise ValueError("A must be square with size equal to len(x0)")

            if B_arr.shape[0] != n:
                raise ValueError("B must have the same number of rows as A")

            input_dim = B_arr.shape[1]
            output_dim = C_arr.shape[0]

            if C_arr.shape[1] != n:
                raise ValueError("C must have number of columns equal to len(x0)")
            if D_arr.shape[0] != output_dim or D_arr.shape[1] != input_dim:
                raise ValueError("D must be of shape (output_dim, input_dim)")

            model = StateSpaceModel(
                A=A_arr,
                B=B_arr,
                C=C_arr,
                D=D_arr,
                input_dim=input_dim,
                output_dim=output_dim,
            )

            config = StateSpaceConfig(
                t0=float(t0),
                t_end=float(t_end),
                x0=x0_arr,
                max_step=float(max_step) if max_step is not None else None,
            )

            # Build input function
            input_type = str(input_type)

            if input_type == "none":
                u_fn = None
                u_params: Dict[str, Any] = {}
            elif input_type == "constant":
                if u_constant is None:
                    raise ValueError("u_constant must be provided for input_type='constant'")
                u_vec = np.asarray(u_constant, dtype=float)
                if u_vec.shape[0] != input_dim:
                    raise ValueError("u_constant dimension must equal input_dim")

                def u_fn(t: float, params: Dict[str, Any]) -> np.ndarray:  # type: ignore
                    return u_vec

                u_params = {}
            elif input_type == "schedule":
                if not u_schedule:
                    raise ValueError("u_schedule must be non-empty for input_type='schedule'")

                # Sort schedule by time
                entries = [
                    (float(e["t"]), np.asarray(e["u"], dtype=float)) for e in u_schedule
                ]
                entries.sort(key=lambda x: x[0])

                for _, u_vec in entries:
                    if u_vec.shape[0] != input_dim:
                        raise ValueError("All schedule u vectors must have dimension input_dim")

                times = np.array([e[0] for e in entries], dtype=float)
                values = np.stack([e[1] for e in entries], axis=0)

                def u_fn(t: float, params: Dict[str, Any]) -> np.ndarray:  # type: ignore
                    # Clamp outside range
                    if t <= times[0]:
                        return values[0]
                    if t >= times[-1]:
                        return values[-1]
                    # Linear interpolation in time
                    idx = np.searchsorted(times, t) - 1
                    t0_ = times[idx]
                    t1_ = times[idx + 1]
                    u0_ = values[idx]
                    u1_ = values[idx + 1]
                    w = (t - t0_) / (t1_ - t0_)
                    return (1.0 - w) * u0_ + w * u1_

                u_params = {}
            else:
                raise ValueError(f"Unsupported input_type: {input_type}")

            result = simulate_state_space(
                model=model,
                config=config,
                u_fn=u_fn,
                u_params=u_params,
            )

            output = {
                "t": result.t.tolist(),
                "x": result.x.tolist(),
                "y": result.y.tolist(),
                "success": result.success,
                "message": result.message,
            }

            return ToolResult(success=result.success, output=output, error=None if result.success else result.message)

        except Exception as e:
            logger.error("SimulateStateSpaceTool error: %s", e, exc_info=True)
            return ToolResult(success=False, output=None, error=str(e))


# ---------------------------------------------------------------------------
# MONTE CARLO SIMULATION TOOL
# ---------------------------------------------------------------------------


class RunMonteCarloTool(Tool):
    """Run Monte Carlo simulations for basic distributions.

    This exposes the generic Monte Carlo engine for a practical subset of
    use cases where the distribution is specified declaratively. It does
    not execute arbitrary code from input.
    """

    def __init__(self) -> None:
        super().__init__()
        self.name = "run_monte_carlo"
        self.description = (
            "Run Monte Carlo simulations for simple distributions (normal, "
            "uniform, lognormal) using Torin's Monte Carlo engine."
        )
        self.category = ToolCategory.REASONING
        self.safety_level = ToolSafety.SAFE
        self.parameters = [
            ToolParameter(
                name="n_samples",
                type="number",
                description="Number of samples to draw.",
                required=True,
                min_value=1,
            ),
            ToolParameter(
                name="distribution",
                type="string",
                description="Distribution name: 'normal', 'uniform', or 'lognormal'.",
                required=True,
                enum=["normal", "uniform", "lognormal"],
            ),
            ToolParameter(
                name="params",
                type="object",
                description=(
                    "Distribution parameters: for 'normal' use {mean, std}; "
                    "for 'uniform' use {low, high}; for 'lognormal' use "
                    "{mean, sigma}."
                ),
                required=False,
                default={},
            ),
            ToolParameter(
                name="seed",
                type="number",
                description="Random seed (optional).",
                required=False,
            ),
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="run_monte_carlo",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.INDUCTIVE_REASONING,
                    description="Generate statistical insights from random sampling distributions",
                    input_types=["distribution_spec", "sample_size"],
                    output_types=["statistical_summary", "samples"],
                    latency="medium",
                    cost="low",
                    reliability="high",
                    risk_level=RiskLevel.LOW,
                    priority=8
                ),
                CapabilityMetadata(
                    capability=Capability.RUN_EXPERIMENT,
                    description="Execute Monte Carlo simulations for probabilistic analysis",
                    input_types=["distribution", "parameters", "num_samples"],
                    output_types=["simulation_results"],
                    latency="medium",
                    cost="low",
                    reliability="high",
                    risk_level=RiskLevel.LOW,
                    priority=8
                ),
                CapabilityMetadata(
                    capability=Capability.ASSESS_CONFIDENCE,
                    description="Quantify uncertainty through statistical sampling",
                    input_types=["stochastic_model"],
                    output_types=["confidence_intervals", "statistics"],
                    latency="medium",
                    cost="low",
                    reliability="high",
                    risk_level=RiskLevel.LOW,
                    priority=7
                ),
                CapabilityMetadata(
                    capability=Capability.CALIBRATE_UNCERTAINTY,
                    description="Calibrate uncertainty estimates via repeated sampling",
                    input_types=["distribution_parameters"],
                    output_types=["uncertainty_estimates"],
                    latency="medium",
                    cost="low",
                    reliability="high",
                    risk_level=RiskLevel.LOW,
                    priority=7
                ),
                CapabilityMetadata(
                    capability=Capability.COUNTERFACTUAL_REASONING,
                    description="Simulate counterfactual scenarios",
                    input_types=["scenario", "parameters"],
                    output_types=["counterfactual_outcomes"],
                    latency="medium",
                    cost="medium",
                    reliability="high",
                    risk_level=RiskLevel.LOW,
                    priority=8
                )
            ],
            requires_filesystem=False,
            requires_network=False,
            requires_database=False,
            is_idempotent=False  # Random sampling produces different results
        )

    async def execute(
        self,
        n_samples: int,
        distribution: str,
        params: Optional[Dict[str, Any]] = None,
        seed: Optional[int] = None,
    ) -> ToolResult:
        try:
            params = params or {}
            distribution = distribution.lower()

            def mc_fn(rng: np.random.Generator, p: Dict[str, Any]) -> float:
                if distribution == "normal":
                    mean = float(p.get("mean", 0.0))
                    std = float(p.get("std", 1.0))
                    return float(rng.normal(mean, std))
                if distribution == "uniform":
                    low = float(p.get("low", 0.0))
                    high = float(p.get("high", 1.0))
                    return float(rng.uniform(low, high))
                if distribution == "lognormal":
                    mean = float(p.get("mean", 0.0))
                    sigma = float(p.get("sigma", 1.0))
                    return float(rng.lognormal(mean, sigma))
                raise ValueError(f"Unsupported distribution: {distribution}")

            cfg = MonteCarloConfig(n_samples=int(n_samples), seed=int(seed) if seed is not None else None)
            result = run_monte_carlo(mc_fn, cfg, params=params)

            output = {
                "samples": result.samples.tolist(),
                "mean": result.mean,
                "std": result.std,
            }

            return ToolResult(success=True, output=output)

        except Exception as e:
            logger.error("RunMonteCarloTool error: %s", e, exc_info=True)
            return ToolResult(success=False, output=None, error=str(e))


__all__ = [
    "ProveTheoremTool",
    "SolveConstraintsTool",
    "SolveLinearOptimizationTool",
    "SimulatePDE1DTool",
    "SimulateStateSpaceTool",
    "RunMonteCarloTool",
]
