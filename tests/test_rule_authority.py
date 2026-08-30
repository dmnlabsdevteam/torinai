"""The edge from a refuted rule to a withdrawn plan.

The chain under test, end to end:

    runtime contradiction, attributable to the rule
      -> rule loses VALIDATED status                        (rule store)
      -> RuleAuthorityChanged written durably               (rule store)
      -> plans standing on that rule are invalidated        (planning engine)
      -> their queued steps stop being dispatched           (get_next_tasks)
      -> the goal is re-planned over what is still validated (coordinator)

Each link is checked on its own AND the chain is checked whole, because a
chain that only works when driven by hand is not wired. The two properties
that matter most are negative:

  * a contradiction the credit invariant refuses to charge to the rule must
    produce NO authority event, or infrastructure failure silently rewrites
    learned knowledge;
  * invalidation must not spread to plans built on other rules.
"""
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import pytest
import pytest_asyncio

from core.agents.autonomous.general_purpose_executor import GeneralPurposeExecutor
from core.agents.autonomous.planning_engine import PlanningEngine
from core.agents.autonomous.shared_types import (
    Plan, Priority, Task, TaskStatus, TaskType, SystemState,
)
from core.execution.effect_verification import (
    Attribution, EffectVerdict, EffectVerification, Polarity, RuntimeEvidence,
    RuntimeOutcome, outcome_class_for,
)
from core.execution.operator_binding import get_binding_registry
from core.learning.rule_authority import (
    AuthorityCause, RuleAuthorityChanged, authority_history, mark_consumed,
    pending_authority_changes, record_authority_change,
)
from core.learning.rule_induction import Fact, get_rule_inducer
from core.learning.rule_store import (
    EpistemicStatus, RuleStore, confers_execution_authority,
)
from core.model_policy import (
    ModelPolicy, assert_model_free, reset_model_telemetry, set_model_policy,
)

from tests.test_substrate_execution import (
    DOMAIN, HELD_OUT, LockedWorld, TEACHING, World, task_for,
)

PROBE = "authority_probe"


@pytest.fixture(autouse=True)
def strict():
    previous = set_model_policy(ModelPolicy.STRICT_MODEL_FREE)
    reset_model_telemetry()
    yield
    assert_model_free("rule authority")
    set_model_policy(previous)
    reset_model_telemetry()


async def _purge(store, engine=None):
    if engine is not None and engine.connection:
        await engine.connection.execute_query(
            "DELETE FROM plans WHERE goal_id IN"
            " (SELECT id FROM goals WHERE description LIKE $1)",
            params=(f"{PROBE}%",), commit=True)
        await engine.connection.execute_query(
            "DELETE FROM goals WHERE description LIKE $1",
            params=(f"{PROBE}%",), commit=True)
    for table in ("unified.rule_authority_events", "unified.learned_rule_evidence"):
        await store.db().execute_query(
            f"DELETE FROM {table} WHERE rule_id IN"
            " (SELECT rule_id FROM unified.learned_rules WHERE domain_id = $1)",
            (DOMAIN,))
    await store.db().execute_query(
        "DELETE FROM unified.learned_rules WHERE domain_id = $1", (DOMAIN,))


@pytest_asyncio.fixture
async def locked():
    """A world where MOVE into LAB silently does nothing: the rule predicts the
    move, the filesystem disagrees, and the disagreement is the rule's."""
    root = Path(tempfile.mkdtemp(prefix="torin_authority_"))
    world = LockedWorld(root, ["HALL", "LAB"], [("HALL", "LAB")], locked={"LAB"})
    world.place("z", "HALL")
    get_binding_registry().register(DOMAIN, world.binding())

    store = RuleStore()
    await store.ensure_schema()
    stored = (await store.record_induction(
        get_rule_inducer().induce(TEACHING), TEACHING,
        domain_id=DOMAIN, rule_kind="move"))[0]
    await store.validate(stored, HELD_OUT)

    yield world, store, stored

    get_binding_registry().clear(DOMAIN)
    shutil.rmtree(root, ignore_errors=True)
    await _purge(store)


@pytest_asyncio.fixture
async def engine():
    e = PlanningEngine()
    assert await e.initialize() is True
    yield e
    await _purge(RuleStore(), e)


# ─────────────────────────────────────────────────── the event itself

@pytest.mark.asyncio
async def test_a_runtime_contradiction_writes_a_durable_authority_event(locked):
    """The whole point: the status change leaves a record something else can
    find, without the executor telling anyone."""
    world, store, stored = locked
    task = task_for(stored.rule_id, "MOVE(z, HALL, LAB)")
    task.provenance["plan_id"] = "plan_probe"
    task.provenance["goal_id"] = "goal_probe"

    await GeneralPurposeExecutor().execute_task(task)

    events = await authority_history(store.db(), stored.rule_id)
    withdrawal = [e for e in events if e.lost_authority]
    assert len(withdrawal) == 1, f"expected exactly one withdrawal, got {events}"
    e = withdrawal[0]
    assert e.old_status is EpistemicStatus.VALIDATED
    assert e.new_status is EpistemicStatus.REFUTED
    assert e.cause is AuthorityCause.RUNTIME_CONTRADICTION
    assert e.task_id == task.id
    assert e.plan_id == "plan_probe"
    assert e.goal_id == "goal_probe"
    assert e.observation_id, "the event does not say which observation refuted it"


@pytest.mark.asyncio
async def test_validation_is_recorded_as_a_gain_not_a_loss(locked):
    """CANDIDATE -> VALIDATED is an authority change too, and reading it as a
    loss would invalidate plans every time a rule was learned."""
    _, store, stored = locked
    events = await authority_history(store.db(), stored.rule_id)
    promotion = [e for e in events if e.cause is AuthorityCause.VALIDATION]
    assert promotion, "validation emitted no authority event"
    assert promotion[0].gained_authority
    assert not promotion[0].lost_authority
    assert not confers_execution_authority(promotion[0].old_status)


@pytest.mark.asyncio
async def test_a_gain_is_not_offered_to_the_planning_layer(locked):
    """`lost_only` is what keeps a newly learned rule from causing churn."""
    _, store, _ = locked
    pending = await pending_authority_changes(store.db(), lost_only=True)
    assert all(e.lost_authority for e in pending)
    everything = await pending_authority_changes(store.db(), lost_only=False)
    assert len(everything) > len(pending), "the gain was never recorded at all"


@pytest.mark.asyncio
async def test_a_transition_to_the_same_status_is_not_an_event(locked):
    _, store, stored = locked
    with pytest.raises(ValueError):
        await record_authority_change(store.db(), RuleAuthorityChanged(
            rule_id=stored.rule_id,
            old_status=EpistemicStatus.VALIDATED,
            new_status=EpistemicStatus.VALIDATED,
            cause=AuthorityCause.VALIDATION,
        ))


@pytest.mark.asyncio
async def test_draining_is_once_only(locked):
    """Two consumers must not both act on the same withdrawal."""
    _, store, stored = locked
    await GeneralPurposeExecutor().execute_task(
        task_for(stored.rule_id, "MOVE(z, HALL, LAB)"))

    pending = await pending_authority_changes(store.db())
    ids = [e.event_id for e in pending]
    assert ids

    assert await mark_consumed(store.db(), ids, "first") == len(ids)
    assert await mark_consumed(store.db(), ids, "second") == 0
    assert not [e for e in await pending_authority_changes(store.db())
                if e.event_id in ids]


@pytest.mark.asyncio
async def test_the_event_outlives_the_object_that_wrote_it(locked):
    """Durability is the reason this is an event and not a method call: a
    consumer that was not running at the time must still find it."""
    _, store, stored = locked
    await GeneralPurposeExecutor().execute_task(
        task_for(stored.rule_id, "MOVE(z, HALL, LAB)"))

    fresh = RuleStore()
    await fresh.ensure_schema()
    found = await pending_authority_changes(fresh.db())
    assert [e.rule_id for e in found] == [stored.rule_id]


# ─────────────────────────────────────────── the credit invariant holds

@pytest.mark.asyncio
async def test_an_unattributable_contradiction_changes_no_authority(locked):
    """A mismatch the credit invariant refuses to charge to the rule must not
    reach the authority log either. Otherwise a misbound tool rewrites what the
    substrate believes it knows."""
    from core.learning.rule_store import record_runtime_evidence

    _, store, stored = locked
    evidence = RuntimeEvidence(
        outcome=RuntimeOutcome.CONTRADICTION,
        rule_id=stored.rule_id, operator="MOVE(z, HALL, LAB)",
        observation_id="obs_infra",
        verifications=[EffectVerification(
            predicted_effect=Fact("AT", ("z", "LAB")), polarity=Polarity.ADD,
            verdict=EffectVerdict.CONTRADICTED, observation_id="obs_infra")],
        detail="tool was misbound",
    )
    status = await record_runtime_evidence(
        store, evidence, Attribution.EXECUTION_FAILURE, "wrong tool")

    assert status is None
    reloaded = next(r for r in await store.load(domain_id=DOMAIN)
                    if r.rule_id == stored.rule_id)
    assert reloaded.status is EpistemicStatus.VALIDATED
    assert not [e for e in await authority_history(store.db(), stored.rule_id)
                if e.cause is AuthorityCause.RUNTIME_CONTRADICTION]


@pytest.mark.parametrize("attribution,outcome,expected", [
    (Attribution.RULE_EVIDENCE, RuntimeOutcome.CONTRADICTION, "strategy_failure"),
    (Attribution.RULE_EVIDENCE, RuntimeOutcome.CONFIRMATION, "success"),
    (Attribution.EXECUTION_FAILURE, RuntimeOutcome.CONTRADICTION, "execution_failure"),
    (Attribution.EXTERNAL_FAILURE, RuntimeOutcome.CONTRADICTION, "external_failure"),
    (Attribution.INDETERMINATE, RuntimeOutcome.INDETERMINATE, "indeterminate"),
])
def test_only_rule_evidence_reaches_the_strategy(attribution, outcome, expected):
    """The translation into credit vocabulary must never let an infrastructure
    failure arrive as a strategy failure — that is what would produce replan
    pressure against a rule that was right."""
    evidence = RuntimeEvidence(outcome=outcome, rule_id="r", operator="MOVE",
                               observation_id="o")
    assert outcome_class_for(evidence, attribution).value == expected


# ────────────────────────────────────────── the planning layer consumes it

async def _plan_on(engine, rule_id, label, *, completed_first=True):
    """A two-step plan: step one done, step two queued behind it."""
    goal = await engine.create_goal(f"{PROBE} {label}", Priority.MEDIUM)
    goal_id = goal.id

    def step(index, status):
        return Task(
            id=f"{PROBE}_{goal_id}_{index}", type=TaskType.EXECUTION,
            description=f"MOVE(z, R{index}, R{index + 1})",
            priority=Priority.MEDIUM, status=status, created_at=datetime.now(),
            dependencies=[f"{PROBE}_{goal_id}_0"] if index else [],
            provenance={"learned_rule_id": rule_id, "plan_id": goal_id,
                        "grounded_operator": f"MOVE(z, R{index}, R{index + 1})"},
        )

    plan = Plan(
        id=f"plan_{uuid4().hex[:8]}", goal_id=goal_id,
        tasks=[step(0, TaskStatus.COMPLETED if completed_first else TaskStatus.PENDING),
               step(1, TaskStatus.PENDING)],
        status="active",
    )
    engine.active_plans[plan.id] = plan
    await engine._store_plan(plan)
    return plan


@pytest.mark.asyncio
async def test_a_plan_standing_on_a_refuted_rule_is_withdrawn(locked, engine):
    _, store, stored = locked
    plan = await _plan_on(engine, stored.rule_id, "goal_a")

    await GeneralPurposeExecutor().execute_task(
        task_for(stored.rule_id, "MOVE(z, HALL, LAB)"))
    report = await engine.consume_rule_authority_changes()

    assert plan.id in report["plans_invalidated"]
    assert plan.status == "invalidated"
    assert plan.tasks[1].status is TaskStatus.BLOCKED
    assert plan.tasks[1].result["blocked_reason"] == \
        "learned_rule_lost_execution_authority"


@pytest.mark.asyncio
async def test_completed_work_is_not_retracted(locked, engine):
    """The step already taken happened, under a rule that was validated at the
    time. That is history, not something to undo."""
    _, store, stored = locked
    plan = await _plan_on(engine, stored.rule_id, "goal_b")

    await GeneralPurposeExecutor().execute_task(
        task_for(stored.rule_id, "MOVE(z, HALL, LAB)"))
    await engine.consume_rule_authority_changes()

    assert plan.tasks[0].status is TaskStatus.COMPLETED


@pytest.mark.asyncio
async def test_a_queued_step_does_not_run_because_its_predecessor_finished(locked, engine):
    """The invariant the dependency chain does NOT provide: ordering is not
    continued authorization."""
    _, store, stored = locked
    plan = await _plan_on(engine, stored.rule_id, "goal_c")

    runnable_before = await engine.get_next_tasks(SystemState())
    assert plan.tasks[1].id in {t.id for t in runnable_before}, \
        "step two should be dispatchable while the rule is validated"

    await GeneralPurposeExecutor().execute_task(
        task_for(stored.rule_id, "MOVE(z, HALL, LAB)"))

    runnable_after = await engine.get_next_tasks(SystemState())
    assert plan.tasks[1].id not in {t.id for t in runnable_after}, \
        "a step authorised by a refuted rule was still dispatched"


@pytest.mark.asyncio
async def test_invalidation_does_not_spread_to_other_rules(locked, engine):
    """Over-broad invalidation would make one bad rule stop unrelated work."""
    _, store, stored = locked
    affected = await _plan_on(engine, stored.rule_id, "goal_d")
    unrelated = await _plan_on(engine, "rule_someone_else", "goal_e")

    await GeneralPurposeExecutor().execute_task(
        task_for(stored.rule_id, "MOVE(z, HALL, LAB)"))
    report = await engine.consume_rule_authority_changes()

    assert affected.id in report["plans_invalidated"]
    assert unrelated.id not in report["plans_invalidated"]
    assert unrelated.status == "active"
    assert unrelated.tasks[1].status is TaskStatus.PENDING


@pytest.mark.asyncio
async def test_a_second_pass_finds_nothing_left_to_do(locked, engine):
    """Drained events must not be re-applied every cycle."""
    _, store, stored = locked
    await _plan_on(engine, stored.rule_id, "goal_f")

    await GeneralPurposeExecutor().execute_task(
        task_for(stored.rule_id, "MOVE(z, HALL, LAB)"))
    first = await engine.consume_rule_authority_changes()
    second = await engine.consume_rule_authority_changes()

    assert first["events"] >= 1 and first["plans_invalidated"]
    assert second["events"] == 0 and second["plans_invalidated"] == []


@pytest.mark.asyncio
async def test_dispatch_stops_when_authority_cannot_be_checked(engine):
    """Fail closed: dispatching on unknown authority is the failure the drain
    exists to prevent."""
    class Broken:
        async def execute_query(self, *a, **k):
            raise RuntimeError("authority log unreachable")

    plan = await _plan_on(engine, "rule_x", "goal_g", completed_first=False)
    working = engine.connection
    engine.connection = Broken()
    try:
        assert await engine.get_next_tasks(SystemState()) == []
    finally:
        engine.connection = working
    assert plan.tasks[0].status is TaskStatus.PENDING


# ──────────────────────────────────────────────── appraisal gets the signal

async def _appraise_one_execution(world, store, stored, operator="MOVE(z, HALL, LAB)"):
    """Run one substrate execution against a FRESH appraisal and return what it
    left behind. Fresh, because appraisal blends with its previous state and a
    disposition carried in from another test would not be this execution's."""
    from core.agents.autonomous.appraisal import AppraisalSystem
    import core.agents.autonomous.appraisal as appraisal_module

    previous = appraisal_module._appraisal_system
    appraisal_module._appraisal_system = AppraisalSystem()
    try:
        result = await GeneralPurposeExecutor().execute_task(
            task_for(stored.rule_id, operator))
        return result, appraisal_module._appraisal_system.current_state
    finally:
        appraisal_module._appraisal_system = previous


@pytest_asyncio.fixture
async def wrong_destination():
    """The tool SUCCEEDS and the world moves — just not where the rule said.

    This is the case the whole design turns on: execution machinery worked
    perfectly and the learned model was wrong. Anything that reads a
    contradiction off tool failure would see nothing here."""
    root = Path(tempfile.mkdtemp(prefix="torin_authority_wrong_"))
    world = World(root, ["HALL", "LAB", "VAULT"], [("HALL", "LAB"), ("LAB", "VAULT")])
    world.place("z", "HALL")
    get_binding_registry().register(DOMAIN, world.binding(destination_override="VAULT"))

    store = RuleStore()
    await store.ensure_schema()
    stored = (await store.record_induction(
        get_rule_inducer().induce(TEACHING), TEACHING,
        domain_id=DOMAIN, rule_kind="move"))[0]
    await store.validate(stored, HELD_OUT)

    yield world, store, stored

    get_binding_registry().clear(DOMAIN)
    shutil.rmtree(root, ignore_errors=True)
    await _purge(store)


@pytest.mark.asyncio
async def test_a_disproved_prediction_raises_replan_pressure(wrong_destination):
    """`should_replan` had no producer on the substrate path at all: acting on
    proved knowledge left disposition untouched, including when the proof was
    wrong.

    The two signals must stay apart here — the tool reported success (we can
    act) while the prediction failed (this route is wrong). That combination is
    exactly what replanning means.
    """
    from core.agents.autonomous.behavior_arbiter import ACT_THRESHOLD, get_behavior_arbiter

    world, store, stored = wrong_destination
    result, state = await _appraise_one_execution(world, store, stored)

    assert result["runtime_outcome"] == "runtime_contradiction"
    assert (world.root / "VAULT" / "z").exists(), "the tool did not actually act"
    assert state is not None, "the substrate path reported nothing to appraisal"
    assert state.attribution == "strategy_failure"
    assert state.controllability == 1.0, "a working tool must not read as no control"

    directive = get_behavior_arbiter().decide(state)
    assert directive.replan >= ACT_THRESHOLD, (
        f"replan pressure {directive.replan:.3f} did not clear {ACT_THRESHOLD}")
    assert directive.should_replan is True
    # Not asserting `mode == "replan"`. With no epistemic measurement on this
    # path, exploration outranks it, and inventing an uncertainty_increase here
    # to change the ranking would fabricate a measurement whose owner is
    # summarize_epistemic_mutations. should_replan is the signal under test.


@pytest.mark.asyncio
async def test_an_action_the_world_refuses_escalates_instead_of_replanning(locked):
    """Both are contradictions; they are not the same situation.

    When the world will not carry out the action at all, planning another route
    through the same operator is not the response — the rule still loses its
    authority, but disposition says escalate rather than replan. Collapsing the
    two would make every contradiction demand a replan.
    """
    from core.agents.autonomous.behavior_arbiter import ACT_THRESHOLD, get_behavior_arbiter

    world, store, stored = locked
    result, state = await _appraise_one_execution(world, store, stored)

    assert result["runtime_outcome"] == "runtime_contradiction"
    assert state.attribution == "strategy_failure"
    assert state.controllability == 0.0, "the tool refused; that is no control"

    directive = get_behavior_arbiter().decide(state)
    assert directive.replan < ACT_THRESHOLD
    assert directive.escalation > directive.replan

    # The rule still loses authority. Disposition decides the response; it does
    # not decide what the evidence established.
    assert [e for e in await authority_history(store.db(), stored.rule_id)
            if e.lost_authority]


@pytest.mark.asyncio
async def test_a_confirmed_rule_does_not_ask_for_replanning():
    """The control: a world that moves as predicted must not produce replan
    pressure, or the signal means nothing."""
    from core.agents.autonomous.appraisal import AppraisalSystem
    from core.agents.autonomous.behavior_arbiter import get_behavior_arbiter
    import core.agents.autonomous.appraisal as appraisal_module

    root = Path(tempfile.mkdtemp(prefix="torin_authority_ok_"))
    world = World(root, ["HALL", "LAB"], [("HALL", "LAB")])
    world.place("z", "HALL")
    get_binding_registry().register(DOMAIN, world.binding())
    store = RuleStore()
    await store.ensure_schema()
    stored = (await store.record_induction(
        get_rule_inducer().induce(TEACHING), TEACHING,
        domain_id=DOMAIN, rule_kind="move"))[0]
    await store.validate(stored, HELD_OUT)

    previous = appraisal_module._appraisal_system
    appraisal_module._appraisal_system = AppraisalSystem()
    try:
        result = await GeneralPurposeExecutor().execute_task(
            task_for(stored.rule_id, "MOVE(z, HALL, LAB)"))
        state = appraisal_module._appraisal_system.current_state
    finally:
        appraisal_module._appraisal_system = previous
        get_binding_registry().clear(DOMAIN)
        shutil.rmtree(root, ignore_errors=True)
        await _purge(store)

    assert result["success"] is True
    assert state.attribution == "success"
    assert get_behavior_arbiter().decide(state).should_replan is False


# ────────────────────────────────────────── the goal is re-planned, not stranded

class _CoordinatorStub:
    """Only what _replan_phase touches. The method under test is the real one."""

    def __init__(self, planning):
        self.planning = planning


async def _replan(engine):
    from core.agents.autonomous.autonomous_coordinator import AutonomousCoordinator
    return await AutonomousCoordinator._replan_phase(_CoordinatorStub(engine))


@pytest.mark.asyncio
async def test_a_goal_whose_route_was_withdrawn_is_replanned(locked, engine):
    """The far end of the edge. Without this the refutation is correct and the
    goal is stuck forever, which is a worse failure than the one it fixed."""
    _, store, stored = locked
    plan = await _plan_on(engine, stored.rule_id, "goal_h")
    goal_id = plan.goal_id

    await GeneralPurposeExecutor().execute_task(
        task_for(stored.rule_id, "MOVE(z, HALL, LAB)"))
    await engine.consume_rule_authority_changes()
    assert plan.status == "invalidated"

    report = await _replan(engine)

    assert report["stranded"] >= 1
    assert report["replanned"] + report["unreachable"] >= 1
    assert any(p.goal_id == goal_id and p.status == "active"
               for p in engine.active_plans.values()), \
        "the goal was left with no route at all"


@pytest.mark.asyncio
async def test_a_goal_that_still_has_a_plan_is_not_replanned(locked, engine):
    """Repair must be driven by the absence of a route, not run every cycle."""
    _, store, stored = locked
    await _plan_on(engine, stored.rule_id, "goal_i")

    report = await _replan(engine)

    assert report["stranded"] == 0
    assert report["replanned"] == 0
