#!/usr/bin/env python3
"""Severance: proving a capability CAUSALLY OWNS the answer it appears to give.

"Torin got the right answer" is a much weaker claim than "this mechanism
produced the right answer". The difference is only visible when the mechanism
is removed: if the answer survives, something else was doing the work.

This is not hypothetical here. The Z3 constraint solver answered `4x + 8 = 32`
correctly the whole time while being UNREACHABLE without a language model --
the only route to it ran through an orchestration path whose first phase is
"NEURAL PROPOSES", so Z3 could check a model's answer but never produce one.
Severing Z3 would have changed nothing, because the model was doing the work.

Each test severs one capability and asserts the system reports a FAULT rather
than an answer from somewhere else.
"""

import pytest

from core.reasoning.arithmetic_reading import read as read_equation
from core.reasoning.constraint_solver import get_constraint_solver


@pytest.fixture
def bridge_class():
    from core.reasoning.neural_bridge import NeuralSymbolicBridge
    return NeuralSymbolicBridge


def test_arithmetic_is_answered_by_the_solver_when_it_is_present(bridge_class):
    equation = read_equation("4x + 8 = 32")
    assert equation is not None
    result = bridge_class._solve_equation(object.__new__(bridge_class), equation)
    assert result.answer == "x = 6"
    assert (result.metadata or {})["verified"] is True
    assert (result.metadata or {})["route"] == ["arithmetic_reading", "constraint_solver"]


def test_severing_z3_produces_a_capability_fault_not_a_fallback_answer(
        bridge_class, monkeypatch):
    """THE DECISIVE ONE. With the solver gone the same question must NOT come
    back as x=6 from anywhere else."""
    from core.reasoning.neural_bridge import REASON_CAPABILITY_UNAVAILABLE

    solver = get_constraint_solver()
    monkeypatch.setattr(solver, "_available", False)
    assert not solver.available

    equation = read_equation("4x + 8 = 32")
    result = bridge_class._solve_equation(object.__new__(bridge_class), equation)

    metadata = result.metadata or {}
    assert metadata["reason"] == REASON_CAPABILITY_UNAVAILABLE
    assert metadata["capability"] == "constraint_solver"
    assert metadata["verified"] is False
    assert result.answer == "", f"an answer appeared without the solver: {result.answer!r}"
    assert "6" not in str(result.answer)
    # And it must not have asked for a model to cover the gap: the reading
    # succeeded, so this is a missing capability, not missing coverage.
    assert metadata.get("model_required") is False


def test_a_severed_solver_still_reports_through_its_own_typed_api():
    """`solve_linear` must not raise or silently return a wrong model."""
    solver = get_constraint_solver()
    original = solver._available
    try:
        solver._available = False
        solution = solver.solve_linear("x", 4, 8, 32)
        assert solution.satisfiable is False
        assert solution.raw_status == "no_solver"
        assert solution.model == {}
    finally:
        solver._available = original


@pytest.mark.asyncio
async def test_severing_unification_disables_variable_deduction(monkeypatch):
    """Sever the owner of variable binding; the deduction that depends on it
    must stop, not be rescued."""
    import core.reasoning.abstract_reasoning_engine as engine
    from core.reasoning.abstract_reasoning_engine import (DeductiveReasoningStrategy,
                                                          ReasoningContext,
                                                          ReasoningPremise,
                                                          ReasoningType)

    strategy = DeductiveReasoningStrategy()
    context = ReasoningContext(
        context_id="severance", domain="logic", problem_type="deduction",
        premises=[ReasoningPremise(premise_id="p1", statement="HUMAN(socrates)",
                                   confidence=1.0)],
        rules=["HUMAN(?X) -> MORTAL(?X)"],
        allowed_reasoning_types=[ReasoningType.DEDUCTIVE])

    intact = await strategy.reason(context)
    assert any(c.statement == "MORTAL(socrates)" for c in intact), \
        "the oracle did not hold before severance, so the test proves nothing"

    def severed(*_args, **_kwargs):
        raise RuntimeError("unification capability severed")

    monkeypatch.setattr(engine, "match_body", severed)
    after = await strategy.reason(context)
    assert not any(c.statement == "MORTAL(socrates)" for c in after), (
        "variable deduction survived the removal of the unifier, so something "
        "else produced the conclusion")


def test_the_reading_stage_is_separable_from_the_solving_stage():
    """Reading an equation and solving it are different capabilities, and the
    reader must not answer anything by itself."""
    equation = read_equation("2x + 19 = 7")
    assert equation.coefficient == 2 and equation.constant == 19 and equation.target == 7
    assert not hasattr(equation, "solution")
    assert read_equation("Is a robin an animal?") is None
