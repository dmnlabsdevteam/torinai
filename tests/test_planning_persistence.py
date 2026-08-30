"""Deliberative state must survive the process, and must fail loudly when it can't.

Goals and plans had never persisted -- not "not recently", never. PlanningEngine
declared its own table types (`priority VARCHAR`, epoch `DOUBLE PRECISION`,
`tasks TEXT`) while the deployed `unified` schema had INTEGER, TIMESTAMP and
JSONB. Because the tables already existed, CREATE TABLE IF NOT EXISTS was a
permanent no-op, every INSERT failed on type, and four separate
`except -> logger.error` handlers turned that into a success: initialize()
returned True, generate_plan() returned a Plan, and `plans_generated` counted up.

The persistence bug and the honesty bug are equally load-bearing. A store that
silently drops writes is survivable if someone notices; one that reports success
while dropping them cannot be noticed at all.
"""
import uuid
from datetime import datetime

import pytest
import pytest_asyncio

from core.agents.autonomous.planning_engine import PlanningEngine
from core.agents.autonomous.shared_types import (
    PRIORITY_ORDINAL, Priority, priority_from_ordinal,
)

PROBE = "PLANNING_PERSISTENCE_TEST"


@pytest_asyncio.fixture
async def engine():
    pe = PlanningEngine({})
    assert await pe.initialize() is True
    yield pe
    await pe.connection.execute_query(
        "DELETE FROM plans WHERE goal_id IN (SELECT id FROM goals WHERE description LIKE $1)",
        params=(f"{PROBE}%",), commit=True)
    await pe.connection.execute_query(
        "DELETE FROM goals WHERE description LIKE $1", params=(f"{PROBE}%",), commit=True)


# ------------------------------------------------------------------- ordinals

def test_priority_has_one_ordinal_authority():
    """Storage needs an integer; get_next_tasks needed an ordering. Two
    independent answers about whether HIGH outranks MEDIUM is a defect waiting."""
    assert PRIORITY_ORDINAL[Priority.LOW] < PRIORITY_ORDINAL[Priority.MEDIUM]
    assert PRIORITY_ORDINAL[Priority.MEDIUM] < PRIORITY_ORDINAL[Priority.HIGH]
    assert PRIORITY_ORDINAL[Priority.HIGH] < PRIORITY_ORDINAL[Priority.CRITICAL]
    for priority, ordinal in PRIORITY_ORDINAL.items():
        assert priority_from_ordinal(ordinal) is priority


def test_an_unknown_ordinal_raises_rather_than_defaulting():
    """Defaulting a corrupt row to MEDIUM would make the corruption invisible."""
    with pytest.raises(ValueError):
        priority_from_ordinal(99)
    with pytest.raises(ValueError):
        priority_from_ordinal(None)


# ---------------------------------------------------------------- persistence

@pytest.mark.asyncio
async def test_a_goal_reaches_the_database(engine):
    goal = await engine.create_goal(f"{PROBE} reach the store", Priority.HIGH)
    row = await engine.connection.execute_query(
        "SELECT id, priority, created_at FROM goals WHERE id = $1",
        params=(goal.id,), fetch_all=True)

    assert row, "create_goal reported success but wrote nothing"
    assert row[0]["priority"] == PRIORITY_ORDINAL[Priority.HIGH]
    assert isinstance(row[0]["created_at"], datetime), (
        "created_at must be a timestamp, not an epoch float"
    )


@pytest.mark.asyncio
async def test_a_plan_reaches_the_database_with_the_columns_types_it_declares(engine):
    goal = await engine.create_goal(f"{PROBE} plan storage", Priority.MEDIUM)
    plan = await engine.generate_plan(goal.id, {})

    row = (await engine.connection.execute_query(
        "SELECT estimated_duration, confidence, created_at, tasks FROM plans WHERE id = $1",
        params=(plan.id,), fetch_all=True))[0]

    assert isinstance(row["estimated_duration"], int)
    assert isinstance(row["created_at"], datetime)
    assert row["tasks"], "tasks is NOT NULL jsonb"


@pytest.mark.asyncio
async def test_deliberative_state_survives_a_new_engine(engine):
    """The boundary that matters: a plan proved and then lost at persistence is
    not a plan the system owns."""
    goal = await engine.create_goal(f"{PROBE} survive restart", Priority.CRITICAL)
    plan = await engine.generate_plan(goal.id, {})

    reloaded = PlanningEngine({})
    assert await reloaded.initialize() is True

    assert goal.id in reloaded.current_goals, "goal did not reload"
    assert plan.id in reloaded.active_plans, "plan did not reload"
    assert reloaded.current_goals[goal.id].priority is Priority.CRITICAL
    assert len(reloaded.active_plans[plan.id].tasks) == len(plan.tasks)


@pytest.mark.asyncio
async def test_reloaded_tasks_keep_their_dependency_chain(engine):
    """get_next_tasks enforces ordering through dependencies, so a chain lost in
    the round trip would let steps run out of order."""
    goal = await engine.create_goal(f"{PROBE} dependency chain", Priority.MEDIUM)
    plan = await engine.generate_plan(goal.id, {})

    reloaded = PlanningEngine({})
    await reloaded.initialize()
    before = {t.id: list(t.dependencies or []) for t in plan.tasks}
    after = {t.id: list(t.dependencies or []) for t in reloaded.active_plans[plan.id].tasks}
    assert before == after


# -------------------------------------------------------------------- honesty

@pytest.mark.asyncio
async def test_a_store_with_no_connection_raises_instead_of_returning():
    """`if not self.connection: return` made a missing store indistinguishable
    from a completed write."""
    pe = PlanningEngine({})
    pe.connection = None
    with pytest.raises(RuntimeError):
        await pe._create_tables()
    with pytest.raises(RuntimeError):
        await pe._store_goal(object())


@pytest.mark.asyncio
async def test_initialize_cannot_report_success_when_its_database_work_failed():
    """The defect that hid the other one for the lifetime of the module."""
    pe = PlanningEngine({})

    async def failing_tables():
        raise RuntimeError("pool down")

    pe._create_tables = failing_tables
    assert await pe.initialize() is False
    assert pe.active is False


@pytest.mark.asyncio
async def test_an_inactive_engine_produces_no_phantom_plans():
    """active=False must stop planning, not merely stop persisting it."""
    pe = PlanningEngine({})
    assert pe.active is False
    assert await pe.create_goal("never", Priority.LOW) is None
    assert await pe.generate_plan("nonexistent", {}) is None


@pytest.mark.asyncio
async def test_memory_does_not_hold_a_goal_the_store_rejected(engine):
    """Registering in memory before the write left the caller told 'None' while
    the engine believed the goal existed -- until restart dropped it."""
    async def failing_store(_goal):
        raise RuntimeError("write rejected")

    engine._store_goal = failing_store
    before = dict(engine.current_goals)
    result = await engine.create_goal(f"{PROBE} rejected", Priority.LOW)

    assert result is None
    assert engine.current_goals == before, "a rejected goal stayed in memory"
