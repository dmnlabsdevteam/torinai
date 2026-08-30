# TorinAI Reasoning, Simulation, and Optimization Stack

This document summarizes the new industrial-grade reasoning and numerical
capabilities added to TorinAI and how to use them from code and tools.

## Components

### Formal Proof Engine (AdvancedProofEngine)

- Module: `core.reasoning.advanced_proof_engine`
- Key types:
  - `Theorem`: theorem_id, statement, premises, logic_type.
  - `LogicType`: `PROPOSITIONAL`, `FIRST_ORDER`, etc.
  - `Proof`: proved flag, method, confidence, steps.
- Backend:
  - Uses Z3 when available for propositional / QF-FOL (`ProofMethod.SMT`).
  - Falls back to simpler strategies for other logic types.

**Example (direct Python):**

```python
from core.reasoning.advanced_proof_engine import Theorem, LogicType, get_proof_engine

engine = get_proof_engine()

theorem = Theorem(
    theorem_id="mp_1",
    statement="Q",
    premises=["P -> Q", "P"],
    logic_type=LogicType.PROPOSITIONAL,
)

proof = await engine.prove_theorem(theorem)
print(proof.proved, proof.method, proof.confidence)
```

**Tool interface:** `prove_theorem`

- Category: `reasoning`
- Parameters:
  - `statement: str`
  - `premises: list[str]`
  - `logic_type: str` (e.g. `"propositional"`)
  - `theorem_id?: str`
  - `max_steps?: int`
  - `timeout?: float`
- Returns: JSON-serializable proof object (proved/method/confidence/steps).

---

### CSP/SMT Constraint Solver

- Module: `core.reasoning.constraint_solver`
- Backend: Z3 (`z3-solver`), with graceful failure if unavailable.
- Key types:
  - `ConstraintVariable` (name, vtype, lower/upper).
  - `ConstraintProblem` (variables, constraints).
  - `ConstraintSolution` (satisfiable, model, raw_status).

**Example (direct Python):**

```python
from z3 import Int, And
from core.reasoning.constraint_solver import get_constraint_solver

solver = get_constraint_solver()
problem = solver.create_problem()
solver.add_variable(problem, "x", vtype="int", lower=0, upper=10)
solver.add_variable(problem, "y", vtype="int", lower=0, upper=10)

x = Int("x")
y = Int("y")
solver.add_constraint(problem, And(x + y == 7, x >= 2))

solution = solver.solve(problem)
print(solution.satisfiable, solution.model)
```

**Tool interface:** `solve_constraints`

- Parameters:
  - `variables: list[{name, vtype, lower?, upper?}]`
  - `constraints: list[expr]` where `expr` is a JSON AST with nodes:
    - `{ "type": "var", "name": "x" }`
    - `{ "type": "const", "value": 5 }`
    - `{ "type": "op", "op": "+"|"-"|"*"|"/"|"and"|"or"|"not"|"<="|">="|"<"|">"|"==", "args": [...] }`
- Returns: `{satisfiable, model, raw_status, error}`.

---

### Linear / MILP Optimization

- Module: `core.optimization.optimizers`
- Backend: PuLP (`pulp`) for LP/MILP; SciPy is used separately for black-box.
- Key types:
  - `LinearObjective` (coefficients, sense).
  - `LinearConstraint` (coefficients, sense, rhs).
  - `LinearProblem`, `LinearSolution`.

**Example (direct Python):**

```python
from core.optimization.optimizers import (
    LinearObjective, LinearConstraint, LinearProblem, solve_linear_problem
)

objective = LinearObjective(coefficients={"x": 1.0, "y": 1.0}, sense="min")
constraints = [
    LinearConstraint(coefficients={"x": 1.0, "y": 2.0}, sense=">=", rhs=4.0),
]

problem = LinearProblem(
    objective=objective,
    constraints=constraints,
    var_bounds={"x": (0.0, None), "y": (0.0, None)},
    var_categories={"x": "continuous", "y": "continuous"},
)

solution = solve_linear_problem(problem)
print(solution.status, solution.objective_value, solution.variables)
```

**Tool interface:** `solve_linear_optimization`

- Parameters:
  - `objective: {sense: 'min'|'max', coefficients: {var: coef}}`
  - `constraints?: [{coefficients, sense, rhs}]`
  - `var_bounds?: {var: [lower, upper]}`
  - `var_categories?: {var: 'continuous'|'integer'|'binary'}`
- Returns: serialized `LinearSolution`.

---

### Numerical Simulation (PDE / Monte Carlo)

- Module: `core.simulation.numerical_simulation`
- Backends: NumPy for arrays; SciPy for ODEs (PDE is implemented via FD).

#### 1D Parabolic PDE (heat-equation style)

- Types: `PDE1DConfig`, `PDE1DResult`.
- Equation: `du/dt = alpha * d^2 u / dx^2` on `[0, L]`.
- BCs: `dirichlet` or `neumann`.

**Example (direct Python):**

```python
from core.simulation.numerical_simulation import PDE1DConfig, simulate_pde_1d

config = PDE1DConfig(
    length=1.0,
    nx=51,
    dt=0.0005,
    t_steps=100,
    alpha=0.1,
    bc_type="dirichlet",
    u0=[0.0]*25 + [1.0] + [0.0]*25,
)

result = simulate_pde_1d(config)
print(result.x.shape, result.t.shape, result.u.shape)
```

**Tool interface:** `simulate_pde_1d`

- Parameters mirror `PDE1DConfig` (`length`, `nx`, `dt`, `t_steps`, `alpha`, `bc_type`, `u0?`).
- Returns arrays `{x, t, u}` as lists.

#### Monte Carlo

- Types: `MonteCarloConfig`, `MonteCarloResult`.
- Generic engine can be used with arbitrary functions in Python.

**Tool interface:** `run_monte_carlo`

- Parameters:
  - `n_samples: int`
  - `distribution: 'normal'|'uniform'|'lognormal'`
  - `params?: {...}` (e.g. `mean`, `std`, `low`, `high`)
  - `seed?: int`
- Returns: `{samples, mean, std}`.

---

### State-Space / System Dynamics

- Module: `core.simulation.system_dynamics`
- Continuous-time linear systems:
  - `dx/dt = A x + B u(t)`
  - `y = C x + D u(t)`
- Types: `StateSpaceModel`, `StateSpaceConfig`, `StateSpaceResult`.
- Backend: SciPy `solve_ivp`, with explicit Euler fallback.

**Example (direct Python):**

```python
import numpy as np
from core.simulation.system_dynamics import (
    StateSpaceModel, StateSpaceConfig, simulate_state_space
)

A = np.array([[-1.0]])
B = np.array([[0.0]])
C = np.array([[1.0]])
D = np.array([[0.0]])

model = StateSpaceModel(A=A, B=B, C=C, D=D, input_dim=1, output_dim=1)
config = StateSpaceConfig(t0=0.0, t_end=1.0, x0=[1.0])

result = simulate_state_space(model, config)
print(result.t.shape, result.x.shape, result.y.shape)
```

**Tool interface:** `simulate_state_space`

- Parameters:
  - `A, B, C, D`: 2D arrays
  - `t0, t_end: float`
  - `x0: array`
  - `max_step?: float`
  - `input_type?: 'none'|'constant'|'schedule'`
  - `u_constant?`, `u_schedule?` (time/value pairs)
- Returns `{t, x, y, success, message}`.

---

## Tool Usage via ToolRegistry

Agents and higher-level systems should access these capabilities via the
`ToolRegistry` when operating in tool mode:

```python
from core.tools.tool_registry import get_tool_registry

registry = get_tool_registry()

result = await registry.execute_tool(
    "prove_theorem",
    {
        "statement": "Q",
        "premises": ["P -> Q", "P"],
        "logic_type": "propositional",
    },
)

if result.success:
    print(result.output["proved"], result.output["method"])
else:
    print("Error", result.error)
```

All new tools return rich `ToolResult` objects with `success`, `output`,
`error`, and metadata suitable for governance and diagnostics.

---

## Testing

Smoke tests and sanity checks for this stack live in:

- `tests/test_reasoning_simulation_stack.py`

They exercise:

- SMT proof of a simple modus ponens theorem.
- Z3 constraint solving for a small linear CSP.
- LP optimization via PuLP.
- 1D heat equation simulation.
- Stable state-space system simulation.
- End-to-end tool calls via `ToolRegistry` for `prove_theorem`,
  `solve_constraints`, and `solve_linear_optimization`.

Use these as references when adding more complex reasoning or
simulation-driven capabilities.
