"""Planning over world state must find real plans and fail honestly.

`generate_plan_for_goal` had never been called by anything, and did not work
when it was. Three defects, all verified by execution before repair:

  1. shallow `state.copy()` meant "simulating" an action permanently applied it
     and mutated the caller's own state
  2. it emitted plans whose first step was inapplicable in the initial state
  3. `_extract_conditions` returned the whole goal as one atom, making progress
     binary and multi-step planning impossible by construction

The last of these is why the module could sit unused: the live template planner
never fails, so nothing ever demanded a planner that could tell you a goal was
unreachable.
"""
import pytest

from core.reasoning.temporal_reasoning import (
    PlanningStatus, TemporalReasoningSystem,
)

MOVES = [
    {"name": "MOVE(z,HALL,LAB)",
     "preconditions": ["AT(z,HALL)", "PATH(HALL,LAB)", "OPEN(LAB)"],
     "effects": ["AT(z,LAB)"], "deletes": ["AT(z,HALL)"]},
    {"name": "MOVE(z,LAB,VAULT)",
     "preconditions": ["AT(z,LAB)", "PATH(LAB,VAULT)", "OPEN(VAULT)"],
     "effects": ["AT(z,VAULT)"], "deletes": ["AT(z,LAB)"]},
]

OPEN_WORLD = ["AT(z,HALL)", "OPEN(LAB)", "PATH(HALL,LAB)",
              "OPEN(VAULT)", "PATH(LAB,VAULT)"]


@pytest.fixture
def planner():
    return TemporalReasoningSystem()


def test_a_two_step_plan_is_found(planner):
    """The frozen domain. Neither step alone achieves the goal, so a greedy
    planner with a binary heuristic cannot solve it."""
    result = planner.plan_for_state_goal(
        ["AT(z,VAULT)"], {"conditions": list(OPEN_WORLD)}, MOVES)

    assert result.status is PlanningStatus.PLAN_FOUND
    assert [s["action"] for s in result.steps] == [
        "MOVE(z,HALL,LAB)", "MOVE(z,LAB,VAULT)"]


def test_every_step_is_applicable_when_it_is_reached(planner):
    """It previously returned only the second step, whose precondition was
    false at the start -- a plan that could not be executed."""
    result = planner.plan_for_state_goal(
        ["AT(z,VAULT)"], {"conditions": list(OPEN_WORLD)}, MOVES)

    state = {"conditions": list(OPEN_WORLD)}
    for action in result.actions:
        assert planner._action_applicable(action, state), (
            f"{action['name']} is not applicable at the point it is scheduled"
        )
        state = planner._apply_action(action, state)


def test_planning_does_not_mutate_the_callers_state(planner):
    """Shallow copy made the search destroy the world it was exploring."""
    initial = {"conditions": list(OPEN_WORLD)}
    planner.plan_for_state_goal(["AT(z,VAULT)"], initial, MOVES)
    assert initial["conditions"] == OPEN_WORLD


def test_planning_twice_gives_the_same_answer(planner):
    """The aliasing defect made the second call see a state the first had
    already advanced, so identical questions got different answers."""
    initial = {"conditions": list(OPEN_WORLD)}
    first = planner.plan_for_state_goal(["AT(z,VAULT)"], initial, MOVES)
    second = planner.plan_for_state_goal(["AT(z,VAULT)"], initial, MOVES)
    assert [s["action"] for s in first.steps] == [s["action"] for s in second.steps]


def test_an_unreachable_goal_is_proved_not_guessed(planner):
    """With the vault sealed no action sequence arrives. Exhausting the space
    is a proof, and must be reported as one."""
    sealed = {"conditions": ["AT(z,HALL)", "OPEN(LAB)", "PATH(HALL,LAB)",
                             "PATH(LAB,VAULT)"]}
    result = planner.plan_for_state_goal(["AT(z,VAULT)"], sealed, MOVES)

    assert result.status is PlanningStatus.UNREACHABLE
    assert not result.steps
    assert "exhausted" in result.reason


def test_hitting_the_bound_is_not_reported_as_unreachable(planner):
    """'I proved none exists' and 'I gave up' are different cognitive states."""
    result = planner.plan_for_state_goal(
        ["AT(z,VAULT)"], {"conditions": list(OPEN_WORLD)}, MOVES, max_nodes=1)

    assert result.status is PlanningStatus.INDETERMINATE
    assert result.status is not PlanningStatus.UNREACHABLE


def test_an_already_satisfied_goal_needs_no_steps(planner):
    result = planner.plan_for_state_goal(
        ["AT(z,HALL)"], {"conditions": list(OPEN_WORLD)}, MOVES)
    assert result.status is PlanningStatus.PLAN_FOUND
    assert result.steps == []


def test_an_empty_goal_is_invalid_not_trivially_satisfied(planner):
    """Treating 'no conditions' as 'all conditions met' would report success
    for a goal that said nothing."""
    for empty in (None, "", "   ", [], set()):
        result = planner.plan_for_state_goal(
            empty, {"conditions": list(OPEN_WORLD)}, MOVES)
        assert result.status is PlanningStatus.INVALID_GOAL, empty


def test_a_multi_condition_goal_decomposes(planner):
    """_extract_conditions wrapped whatever it got in a single-element list, so
    a conjunctive goal could never be measured partially."""
    assert planner._extract_conditions(["A", "B"]) == ["A", "B"]
    assert planner._extract_conditions({"A"}) == ["A"]
    assert planner._extract_conditions("A") == ["A"]


def test_delete_effects_are_honoured(planner):
    """Without retraction the mover ends up in two rooms and the second step's
    precondition stays satisfied forever."""
    result = planner.plan_for_state_goal(
        ["AT(z,VAULT)"], {"conditions": list(OPEN_WORLD)}, MOVES)

    state = {"conditions": list(OPEN_WORLD)}
    for action in result.actions:
        state = planner._apply_action(action, state)

    assert "AT(z,VAULT)" in state["conditions"]
    assert "AT(z,HALL)" not in state["conditions"]
    assert "AT(z,LAB)" not in state["conditions"]


def test_the_shortest_plan_is_returned(planner):
    """Breadth-first, so a redundant detour must not be preferred."""
    actions = MOVES + [
        {"name": "DETOUR(z,HALL,LAB)",
         "preconditions": ["AT(z,HALL)", "PATH(HALL,LAB)", "OPEN(LAB)"],
         "effects": ["AT(z,LAB)", "TIRED(z)"], "deletes": ["AT(z,HALL)"]},
    ]
    result = planner.plan_for_state_goal(
        ["AT(z,VAULT)"], {"conditions": list(OPEN_WORLD)}, actions)
    assert len(result.steps) == 2


def test_an_unnamed_action_is_refused(planner):
    """A step the executor cannot identify is not a plan."""
    result = planner.plan_for_state_goal(
        ["AT(z,VAULT)"], {"conditions": list(OPEN_WORLD)},
        [{"preconditions": [], "effects": ["AT(z,VAULT)"]}])
    assert result.status is PlanningStatus.INVALID_GOAL
