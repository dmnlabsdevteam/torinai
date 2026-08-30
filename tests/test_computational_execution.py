#!/usr/bin/env python3
"""Executing a program whose intermediate values do not exist until it runs.

Planning over dataflow was established elsewhere. This is the claim that
matters: the substrate PLANS a chain whose values it cannot know, RUNS it
against a real world through real tools, and each step binds what the previous
one actually produced -- not what anything predicted it would produce.

    source file (contents unseen)
        READ          copy_file    -> whatever the file held
        PARSE_NUMBER  copy_file    -> a number, if it is one
        MULTIPLY      run_python   -> that number times the factor
        WRITE         copy_file    -> a real file on disk

Every rule below is INDUCED from demonstrations in this world. Every action is
a registered tool invoked through the tool registry. Every observation is a
read of the filesystem afterwards, so a prediction can be contradicted -- and
the negative control is where it is: a file holding `hello` must not become a
number, and the multiply that would have consumed it must never run.
"""

import json
import shutil
import tempfile
from pathlib import Path
from uuid import uuid4

import pytest
import pytest_asyncio

from core.agents.autonomous.execution_plan_adapter import state_plan_to_tasks
from core.agents.autonomous.general_purpose_executor import GeneralPurposeExecutor
from core.agents.autonomous.shared_types import Goal, Priority, Task, TaskType
from core.execution.effect_verification import RuntimeOutcome
from core.execution.operator_binding import get_binding_registry
from core.learning.rule_grounding import ground_for_problem
from core.learning.rule_induction import (BindingOrigin, Fact, TrainingExample,
                                          get_rule_inducer)
from core.learning.rule_store import RuleStore
from core.model_policy import (ModelPolicy, assert_model_free,
                               reset_model_telemetry, set_model_policy)
from core.reasoning.temporal_reasoning import (PlanGuarantee, PlanOutcome,
                                               PlanningStatus,
                                               TemporalReasoningSystem)
from core.tools import get_tool_registry
from experiments.computation_world import ComputationWorld

DOMAIN = "test_computational_execution"


@pytest.fixture(autouse=True)
def strict():
    previous = set_model_policy(ModelPolicy.STRICT_MODEL_FREE)
    reset_model_telemetry()
    yield
    assert_model_free("computational execution")
    set_model_policy(previous)
    reset_model_telemetry()


async def act(world, predicate, args=()):
    """Run one action for real and report what the world then holds."""
    binding = world.binding(predicate)
    before = tuple(sorted(world.observe()))
    result = await get_tool_registry().execute_tool(
        binding.tool_name, binding.parameters(args))
    assert getattr(result, "success", False), (predicate, getattr(result, "error", None))
    return before, tuple(sorted(world.observe()))


async def demonstrate(root, predicate, args, setup, evidence_id):
    """One demonstration, taken by acting in a world of its own."""
    world = ComputationWorld(Path(tempfile.mkdtemp(dir=root)))
    setup(world)
    before, after = await act(world, predicate, args)
    action = Fact(predicate, tuple(args))
    return [
        TrainingExample(before=before + (action,), action=action,
                        after=after + (action,), positive=True,
                        evidence_id=evidence_id),
        TrainingExample(before=before, action=None, after=before, positive=False,
                        evidence_id=f"{evidence_id}_still"),
    ]


def source(name, contents, factor=2):
    return lambda w: w.put_source(name, contents).put_factor(factor)


def register(number=None, product=None, factor=2):
    def setup(world):
        world.put_source("source", "unused").put_factor(factor)
        if number is not None:
            (world.root / world.NUMBER).write_text(str(number))
        if product is not None:
            (world.root / world.PRODUCT).write_text(str(product))
    return setup


def text(value, factor=2):
    def setup(world):
        world.put_source("source", value).put_factor(factor)
        (world.root / world.TEXT).write_text(str(value))
    return setup


@pytest_asyncio.fixture
async def taught():
    root = Path(tempfile.mkdtemp(prefix="torin_computation_"))
    store = RuleStore()
    await store.ensure_schema()

    async def learn(predicate, args, setups, held_out, target):
        teaching = [e for index, setup in enumerate(setups)
                    for e in await demonstrate(root, predicate, args, setup,
                                               f"{predicate}_t{index}")]
        result = get_rule_inducer().induce(teaching, target_predicate=target)
        assert result.rule is not None, (predicate, result.status, result.detail)
        stored = (await store.record_induction(
            result, teaching, domain_id=DOMAIN, rule_kind=predicate))[0]
        checks = [e for index, setup in enumerate(held_out)
                  for e in await demonstrate(root, predicate, args, setup,
                                             f"{predicate}_h{index}")]
        await store.validate(stored, checks)
        return stored

    rules = {
        "READ": await learn(
            "READ", ("source",),
            [source("source", "17"), source("source", "23")],
            [source("source", "41")], "TEXT"),
        "PARSE_NUMBER": await learn(
            "PARSE_NUMBER", (), [text("17"), text("23")], [text("41")], "NUMBER"),
        # Never shown with the text register set, so "the text times the factor"
        # and "the number times the factor" are not the same claim; and never
        # with one factor, so doubling and adding to itself are not either.
        "MULTIPLY": await learn(
            "MULTIPLY", (),
            [register(number=17, factor=2), register(number=5, factor=3),
             register(number=4, factor=2)],
            [register(number=6, factor=5)], "PRODUCT"),
        "WRITE": await learn(
            "WRITE", (), [register(product=34), register(product=15)],
            [register(product=8)], "WRITTEN"),
    }

    world = ComputationWorld(root / "run")
    get_binding_registry().register(DOMAIN, world.binding("READ"))
    world.register(DOMAIN)

    yield world, store, rules

    get_binding_registry().clear(DOMAIN)
    shutil.rmtree(root, ignore_errors=True)
    for table in ("rule_authority_events", "learned_rule_evidence"):
        await store.db().execute_query(
            f"DELETE FROM unified.{table} WHERE rule_id IN"
            f" (SELECT rule_id FROM unified.learned_rules WHERE domain_id = $1)",
            (DOMAIN,))
    await store.db().execute_query(
        "DELETE FROM unified.learned_rules WHERE domain_id = $1", (DOMAIN,))


def plan_for(world, rules, goal_fact):
    state = list(world.observe())
    available = [Fact("READ", ("source",)), Fact("PARSE_NUMBER", ()),
                 Fact("MULTIPLY", ()), Fact("WRITE", ())]
    goal = [goal_fact]
    grounding = ground_for_problem(list(rules.values()), state + available, goal)
    result = TemporalReasoningSystem().plan_for_state_goal(
        [f.to_formula() for f in goal],
        {"conditions": [f.to_formula() for f in state + available]},
        grounding.to_actions())
    return grounding, result


def tasks_for(result, goal_fact):
    goal = Goal(id=f"goal_{uuid4().hex[:8]}", description=str(goal_fact),
                priority=Priority.MEDIUM,
                state_conditions=[goal_fact.to_formula()])
    return state_plan_to_tasks(result, goal, f"plan_{uuid4().hex[:8]}",
                               grounding_complete=True, domain_id=DOMAIN)


def learned(rules, name):
    return rules[name].rule


def restarted(task):
    """The task as it survives a process boundary: data, and nothing else."""
    carried = json.loads(json.dumps(
        {"id": task.id, "description": task.description,
         "provenance": task.provenance}))
    return Task(id=carried["id"], type=TaskType.EXECUTION,
                description=carried["description"],
                provenance=carried["provenance"])


@pytest.mark.asyncio
async def test_every_action_was_learned_including_the_one_that_computes(taught):
    _, _, rules = taught
    multiply = learned(rules, "MULTIPLY")
    assert len(multiply.outputs) == 1
    assert multiply.outputs[0].origin is BindingOrigin.DERIVED
    assert multiply.outputs[0].function == "multiply"
    # The read cannot predict what a file holds, and does not claim to.
    read = learned(rules, "READ")
    assert read.outputs[0].origin is BindingOrigin.ACTION_OUTPUT


@pytest.mark.asyncio
async def test_a_program_is_planned_and_run_over_values_that_did_not_exist_yet(taught):
    """The milestone: planned blind, executed for real, every step binding what
    the step before it actually produced."""
    world, _, rules = taught
    world.clear_registers().put_source("source", "17").put_factor(2)

    grounding, result = plan_for(world, rules, Fact("WRITTEN", ("34",)))

    # 1 — planned before the value the plan depends on exists anywhere.
    assert result.status is PlanningStatus.PLAN_FOUND, result.reason
    assert result.guarantee is PlanGuarantee.CONDITIONAL
    assert result.outcome is PlanOutcome.NO_PROVED_PLAN_WITHIN_BOUND
    assert [s["action"].split("(")[0] for s in result.steps] == [
        "READ", "PARSE_NUMBER", "MULTIPLY", "WRITE"]
    assert Fact("TEXT", ("17",)) not in world.observe()

    # 7 — and the plan says so: it carries unknowns, not numbers.
    assert result.deferred
    planned = [p["term"] for step in result.trace for p in step["produced"]]
    assert planned and all(term.startswith("pending_") for term in planned)

    tasks = tasks_for(result, Fact("WRITTEN", ("34",)))
    assert len(tasks) == 4

    executed = []
    for index, task in enumerate(tasks):
        # 9 — the plan is put through a restart halfway. Only serialisable data
        # crosses: the remaining tasks are written to JSON and rebuilt, and
        # each step runs on an executor that has never seen the ones before it.
        # Nothing needs carrying, because what the earlier steps produced is in
        # the world and that is where the later steps read it from.
        if index == 2:
            task = restarted(task)
        outcome = await GeneralPurposeExecutor().execute_task(task)
        executed.append(outcome)
        assert outcome["success"] is True, outcome
        assert outcome["runtime_outcome"] == RuntimeOutcome.CONFIRMATION.value
        assert outcome["model_free"] is True

    observed = world.observe()
    # 2, 4 — each runtime output became a concrete term the next step could use.
    assert Fact("TEXT", ("17",)) in observed
    assert Fact("NUMBER", ("17",)) in observed
    # 5, 6 — the product is what the world computed from the observed number,
    # and it is a real file.
    assert Fact("PRODUCT", ("34",)) in observed
    assert Fact("WRITTEN", ("34",)) in observed
    assert (world.root / world.OUTPUT).read_text().strip() == "34"

    # 3, 8 — what the plan carried as an unknown, execution resolved to a
    # number, and the resolution came from the world rather than the plan.
    multiply = executed[2]
    predicted = [e["effect"] for e in multiply["effects"] if e["polarity"] == "add"]
    assert predicted == ["PRODUCT(34)"], predicted
    assert all(not term.startswith("pending_") for term in
               (f.args[0] for f in observed if f.predicate in
                {"TEXT", "NUMBER", "PRODUCT", "WRITTEN"}))


@pytest.mark.asyncio
async def test_a_file_that_is_not_a_number_stops_the_program_rather_than_inventing_one(taught):
    """The negative control. The parse tool runs and returns cleanly; the world
    does not hold a number afterwards; nothing downstream may proceed on a
    value that was never produced."""
    world, _, rules = taught
    world.clear_registers().put_source("source", "hello").put_factor(2)

    _, result = plan_for(world, rules, Fact("WRITTEN", ("34",)))
    tasks = tasks_for(result, Fact("WRITTEN", ("34",)))

    read = await GeneralPurposeExecutor().execute_task(tasks[0])
    assert read["success"] is True
    assert Fact("TEXT", ("hello",)) in world.observe()

    # The rule predicted the number register would hold what the text held.
    # It does not, because `hello` is not a number -- and the substrate finds
    # that out from the world rather than from the tool, which succeeded.
    parse = await GeneralPurposeExecutor().execute_task(tasks[1])
    assert parse["runtime_outcome"] == RuntimeOutcome.CONTRADICTION.value
    assert parse["success"] is False
    assert not [f for f in world.observe() if f.predicate == "NUMBER"]

    # And the step that would have computed with it refuses, naming what is
    # missing rather than proceeding on a value nothing produced.
    multiply = await GeneralPurposeExecutor().execute_task(tasks[2])
    assert multiply["success"] is False
    assert "does not hold in the observed world" in multiply["refused"]
    assert not [f for f in world.observe() if f.predicate == "PRODUCT"]
    assert not (world.root / world.OUTPUT).exists()
