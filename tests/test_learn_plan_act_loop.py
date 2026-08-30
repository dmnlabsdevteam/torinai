"""The whole loop, on the production path, with no model involved.

    persistent learned rule -> state goal -> PlanningEngine -> grounding ->
    state search -> ordered task chain -> durable plan -> restart ->
    only step A runnable -> A completes -> B becomes runnable

Each severance below removes exactly one link and asserts the loop stops in the
way that link's absence should cause -- so a pass is evidence the link carries
the capability rather than merely accompanying it.
"""
import pytest
import pytest_asyncio

from core.agents.autonomous.execution_plan_adapter import (
    PlanValidationError, validate_task_chain,
)
from core.agents.autonomous.planning_engine import PlanningEngine
from core.agents.autonomous.shared_types import (
    GoalType, Priority, SystemState, Task, TaskStatus, TaskType,
)
from core.learning.rule_induction import Fact, TrainingExample, get_rule_inducer
from core.learning.rule_store import EpistemicStatus, RuleStore
from core.model_policy import (
    ModelPolicy, assert_model_free, reset_model_telemetry, set_model_policy,
)
from core.reasoning.temporal_reasoning import PlanningStatus

F = Fact.parse
DOMAIN = "test_learn_plan_act"
PROBE = "LEARN_PLAN_ACT_TEST"

WORLD = ["AT(z, HALL)", "PATH(HALL, LAB)", "OPEN(LAB)",
         "PATH(LAB, VAULT)", "OPEN(VAULT)"]
GOAL_CONDITIONS = ["AT(z, VAULT)"]


@pytest.fixture(autouse=True)
def strict():
    previous = set_model_policy(ModelPolicy.STRICT_MODEL_FREE)
    reset_model_telemetry()
    yield
    assert_model_free("learn-plan-act loop")
    set_model_policy(previous)
    reset_model_telemetry()


def move(who, a, b, evidence_id, opened=True, path=True, acted=True, at=True):
    before = []
    if at:
        before.append(F(f"AT({who},{a})"))
    if path:
        before.append(F(f"PATH({a},{b})"))
    if opened:
        before.append(F(f"OPEN({b})"))
    before = tuple(before)
    ok = opened and path and acted and at
    after = (tuple(f for f in before if f != F(f"AT({who},{a})"))
             + (F(f"AT({who},{b})"),)) if ok else before
    return TrainingExample(
        before=before, action=F(f"MOVE({who},{a},{b})") if acted else None,
        after=after, positive=ok, evidence_id=evidence_id)


TEACHING = [
    move("a", "R1", "R2", "t1"), move("b", "R3", "R4", "t2"),
    move("c", "R5", "R6", "n1", opened=False),
    move("d", "R7", "R8", "n2", path=False),
    move("e", "R9", "R10", "n3", acted=False),
    move("h", "R15", "R16", "n4", at=False),
]
HELD_OUT = [move("f", "R11", "R12", "h1"), move("g", "R13", "R14", "h2")]


@pytest_asyncio.fixture
async def substrate():
    """A validated, persisted learned rule and an initialized engine."""
    store = RuleStore()
    await store.ensure_schema()
    stored = (await store.record_induction(
        get_rule_inducer().induce(TEACHING), TEACHING,
        domain_id=DOMAIN, rule_kind="move"))[0]
    await store.validate(stored, HELD_OUT)

    engine = PlanningEngine({})
    assert await engine.initialize() is True

    yield engine, store, stored

    await engine.connection.execute_query(
        "DELETE FROM plans WHERE goal_id IN (SELECT id FROM goals WHERE description LIKE $1)",
        params=(f"{PROBE}%",), commit=True)
    await engine.connection.execute_query(
        "DELETE FROM goals WHERE description LIKE $1", params=(f"{PROBE}%",), commit=True)
    await store.db().execute_query(
        "DELETE FROM unified.rule_authority_events WHERE rule_id IN"
        " (SELECT rule_id FROM unified.learned_rules WHERE domain_id = $1)", (DOMAIN,))
    await store.db().execute_query(
        "DELETE FROM unified.learned_rule_evidence WHERE rule_id IN"
        " (SELECT rule_id FROM unified.learned_rules WHERE domain_id = $1)", (DOMAIN,))
    await store.db().execute_query(
        "DELETE FROM unified.learned_rules WHERE domain_id = $1", (DOMAIN,))


async def _state_goal(engine, description=f"{PROBE} reach the vault"):
    goal = await engine.create_goal(description, Priority.HIGH)
    goal.state_conditions = list(GOAL_CONDITIONS)
    return goal


def _context():
    return {"world_state": list(WORLD), "domain_id": DOMAIN}


# ------------------------------------------------------------------ the loop

@pytest.mark.asyncio
async def test_a_state_goal_is_planned_by_search_not_templates(substrate):
    engine, _, _ = substrate
    goal = await _state_goal(engine)
    assert goal.goal_type is GoalType.STATE

    outcome = await engine.plan_for_goal(goal.id, _context())

    assert outcome.status is PlanningStatus.PLAN_FOUND
    assert outcome.planning_mode == "state"
    assert [t.description for t in outcome.plan.tasks] == [
        "MOVE(z, HALL, LAB)", "MOVE(z, LAB, VAULT)"]


@pytest.mark.asyncio
async def test_the_task_chain_preserves_the_proof_order(substrate):
    engine, _, _ = substrate
    goal = await _state_goal(engine)
    tasks = (await engine.plan_for_goal(goal.id, _context())).plan.tasks

    assert tasks[0].dependencies == []
    assert tasks[1].dependencies == [tasks[0].id]


@pytest.mark.asyncio
async def test_only_the_first_step_is_runnable_until_it_completes(substrate):
    """get_next_tasks sorts by priority and returns several at once, so without
    the chain both moves would be offered together and run out of order."""
    engine, _, _ = substrate
    goal = await _state_goal(engine)
    tasks = (await engine.plan_for_goal(goal.id, _context())).plan.tasks
    state = SystemState()

    # SCOPED TO THIS PLAN. get_next_tasks offers runnable work across every
    # active plan, and the store holds real ones, so asserting on the whole
    # result made this a claim about the queue rather than about the dependency
    # chain -- and it failed the moment any other plan was live.
    mine = {t.id for t in tasks}

    runnable = [t.id for t in await engine.get_next_tasks(state) if t.id in mine]
    assert runnable == [tasks[0].id]

    tasks[0].status = TaskStatus.COMPLETED
    runnable = [t.id for t in await engine.get_next_tasks(state) if t.id in mine]
    assert runnable == [tasks[1].id]


@pytest.mark.asyncio
async def test_the_plan_and_its_order_survive_a_restart(substrate):
    engine, _, _ = substrate
    goal = await _state_goal(engine)
    plan = (await engine.plan_for_goal(goal.id, _context())).plan

    reloaded = PlanningEngine({})
    assert await reloaded.initialize() is True
    recovered = reloaded.active_plans[plan.id]

    assert [t.description for t in recovered.tasks] == [
        "MOVE(z, HALL, LAB)", "MOVE(z, LAB, VAULT)"]
    assert recovered.tasks[1].dependencies == [recovered.tasks[0].id]

    mine = {t.id for t in recovered.tasks}
    runnable = [t.id for t in await reloaded.get_next_tasks(SystemState())
                if t.id in mine]
    assert runnable == [recovered.tasks[0].id], (
        "after a restart only the first step may be runnable"
    )


@pytest.mark.asyncio
async def test_provenance_traces_a_task_to_the_learned_rule(substrate):
    """Not only what Torin did, but which acquired experience authorised it."""
    engine, _, stored = substrate
    goal = await _state_goal(engine)
    plan = (await engine.plan_for_goal(goal.id, _context())).plan

    reloaded = PlanningEngine({})
    await reloaded.initialize()
    provenance = reloaded.active_plans[plan.id].tasks[1].provenance

    assert provenance["learned_rule_id"] == stored.rule_id
    assert provenance["planning_mode"] == "state"
    assert provenance["goal_id"] == goal.id
    assert provenance["predecessor_task_id"] == plan.tasks[0].id
    assert provenance["grounding_complete"] is True


# ------------------------------------------------------------------ severance

@pytest.mark.asyncio
async def test_demoting_the_rule_removes_the_capability(substrate):
    """The execution gate the ablation proved causal, reached through planning."""
    engine, store, stored = substrate
    await store.db().execute_query(
        "UPDATE unified.learned_rules SET epistemic_status = $1 WHERE rule_id = $2",
        (EpistemicStatus.SUPPORTED.value, stored.rule_id))

    goal = await _state_goal(engine)
    outcome = await engine.plan_for_goal(goal.id, _context())

    assert outcome.status is not PlanningStatus.PLAN_FOUND
    assert outcome.operators_considered == 0


@pytest.mark.asyncio
async def test_a_sealed_vault_is_unreachable_not_replanned_as_a_template(substrate):
    """The defect this whole design exists to prevent: an honest planning
    failure becoming Research -> Analyze -> Execute."""
    engine, _, _ = substrate
    goal = await _state_goal(engine)
    sealed = [c for c in WORLD if c != "OPEN(VAULT)"]

    outcome = await engine.plan_for_goal(
        goal.id, {"world_state": sealed, "domain_id": DOMAIN})

    assert outcome.status is PlanningStatus.UNREACHABLE
    assert outcome.plan is None
    assert outcome.planning_mode == "state"


@pytest.mark.asyncio
async def test_truncated_grounding_reports_indeterminate_never_unreachable(substrate):
    """Unreached is not unreachable. Claiming impossibility from an operator set
    Torin failed to enumerate would be a false proof about the world."""
    engine, _, _ = substrate
    goal = await _state_goal(engine)

    import core.agents.autonomous.planning_engine as engine_module
    from core.learning import rule_grounding

    real = rule_grounding.ground_for_problem

    def truncated(*args, **kwargs):
        report = real(*args, **kwargs)
        report.operators = []
        report.truncated = True
        return report

    rule_grounding.ground_for_problem = truncated
    try:
        outcome = await engine.plan_for_goal(goal.id, _context())
    finally:
        rule_grounding.ground_for_problem = real

    assert outcome.status is PlanningStatus.INDETERMINATE
    assert outcome.status is not PlanningStatus.UNREACHABLE
    assert "not unreachable" in outcome.reason


@pytest.mark.asyncio
async def test_a_state_goal_is_refused_by_the_template_planner(substrate):
    """Mode is chosen by goal type. The template path must be unreachable for a
    state goal even when called directly."""
    engine, _, _ = substrate
    goal = await _state_goal(engine)
    assert await engine.generate_plan(goal.id, _context()) is None


@pytest.mark.asyncio
async def test_a_descriptive_goal_still_uses_templates(substrate):
    engine, _, _ = substrate
    goal = await engine.create_goal(f"{PROBE} research widgets", Priority.LOW)

    outcome = await engine.plan_for_goal(goal.id, {})
    assert outcome.planning_mode == "template"
    assert outcome.status is PlanningStatus.PLAN_FOUND


@pytest.mark.asyncio
async def test_a_state_goal_without_a_world_is_indeterminate(substrate):
    """Assuming an empty world would make every goal unreachable for a reason
    about the caller rather than the world."""
    engine, _, _ = substrate
    goal = await _state_goal(engine)
    outcome = await engine.plan_for_goal(goal.id, {"domain_id": DOMAIN})
    assert outcome.status is PlanningStatus.INDETERMINATE


# ---------------------------------------------------------- chain integrity

def _chain_task(identifier, dependencies):
    return Task(id=identifier, type=TaskType.EXECUTION, description=identifier,
                dependencies=list(dependencies))


def test_a_malformed_chain_is_refused_before_persistence():
    with pytest.raises(PlanValidationError, match="duplicate"):
        validate_task_chain([_chain_task("a", []), _chain_task("a", [])])

    with pytest.raises(PlanValidationError, match="not in this plan"):
        validate_task_chain([_chain_task("a", ["ghost"])])

    with pytest.raises(PlanValidationError, match="depends on itself"):
        validate_task_chain([_chain_task("a", ["a"])])

    with pytest.raises(PlanValidationError, match="cycle"):
        validate_task_chain([_chain_task("a", ["b"]), _chain_task("b", ["a"])])


def test_a_valid_chain_passes():
    validate_task_chain([_chain_task("a", []), _chain_task("b", ["a"]),
                         _chain_task("c", ["b"])])


@pytest.mark.asyncio
async def test_a_corrupted_dependency_blocks_execution(substrate):
    """The runtime half of the invariant: validation prevents a bad chain being
    created, this refuses to run one that became bad afterwards."""
    engine, _, _ = substrate
    goal = await _state_goal(engine)
    tasks = (await engine.plan_for_goal(goal.id, _context())).plan.tasks

    tasks[0].status = TaskStatus.COMPLETED
    tasks[1].dependencies = ["a-task-that-does-not-exist"]

    runnable = await engine.get_next_tasks(SystemState())
    assert tasks[1].id not in [t.id for t in runnable], (
        "an unresolvable dependency must block, not read as no blocker"
    )
