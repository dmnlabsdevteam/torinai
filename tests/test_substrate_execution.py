"""Acting on a real world and checking the learned model against it.

THE INVARIANT these exist to protect:

    Predictions may define WHAT to test, but may never construct the
    observation used to confirm themselves.

The observation is produced by reading the actual filesystem, never by applying
the rule's own add/delete effects to a symbolic state. The contradiction test is
the proof: if observations were built from predictions, a contradiction could
not occur.

`runtime_confirmation` must also not be the generic success branch. A tool that
returns cleanly while the world does not move is INDETERMINATE, and a world
that moves the wrong way is CONTRADICTION.
"""
import asyncio
import shutil
import tempfile
from pathlib import Path

import pytest
import pytest_asyncio

from core.agents.autonomous.general_purpose_executor import GeneralPurposeExecutor
from core.agents.autonomous.shared_types import Task, TaskType
from core.execution.effect_verification import (
    EffectVerdict, Polarity, RuntimeOutcome, ToolObservation, verify_effects,
)
from core.execution.operator_binding import OperatorBinding, get_binding_registry
from core.learning.rule_induction import Fact, RuleEffects, TrainingExample, get_rule_inducer
from core.learning.rule_store import EpistemicStatus, RuleStore
from core.model_policy import (
    ModelPolicy, assert_model_free, reset_model_telemetry, set_model_policy,
)

F = Fact.parse
DOMAIN = "test_substrate_exec"


@pytest.fixture(autouse=True)
def strict():
    previous = set_model_policy(ModelPolicy.STRICT_MODEL_FREE)
    reset_model_telemetry()
    yield
    assert_model_free("substrate execution")
    set_model_policy(previous)
    reset_model_telemetry()


class World:
    """Rooms are directories, the agent is a file, MOVE is the move_file tool."""

    def __init__(self, root, rooms, paths):
        self.root, self.rooms, self.paths = root, list(rooms), list(paths)
        self.readable = True
        for r in self.rooms:
            (self.root / r).mkdir(parents=True, exist_ok=True)

    def place(self, agent, room):
        (self.root / room / agent).write_text("")

    def observe(self):
        """Reads the FILESYSTEM. Never consults a rule or a prediction."""
        if not self.readable or not self.root.exists():
            return None
        facts = set()
        for room in self.rooms:
            d = self.root / room
            if not d.is_dir():
                continue
            facts.add(Fact("SBOPEN", (room,)))
            for entry in d.iterdir():
                if entry.is_file():
                    facts.add(Fact("SBAT", (entry.name, room)))
        for a, b in self.paths:
            facts.add(Fact("SBPATH", (a, b)))
        return frozenset(facts)

    def binding(self, destination_override=None):
        def parameters(args):
            agent, origin, destination = args
            return {
                "source_path": str(self.root / origin / agent),
                "destination_path": str(
                    self.root / (destination_override or destination) / agent),
                "create_dirs": False,
            }

        return OperatorBinding(predicate="SBMOVE", tool_name="move_file",
                               parameters=parameters, observe=self.observe)


def move(who, a, b, evidence_id, opened=True, path=True, acted=True, at=True):
    before = []
    if at:
        before.append(F(f"SBAT({who},{a})"))
    if path:
        before.append(F(f"SBPATH({a},{b})"))
    if opened:
        before.append(F(f"SBOPEN({b})"))
    before = tuple(before)
    ok = opened and path and acted and at
    after = (tuple(f for f in before if f != F(f"SBAT({who},{a})"))
             + (F(f"SBAT({who},{b})"),)) if ok else before
    return TrainingExample(
        before=before, action=F(f"SBMOVE({who},{a},{b})") if acted else None,
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
async def world_and_rule():
    root = Path(tempfile.mkdtemp(prefix="torin_test_world_"))
    world = World(root, ["HALL", "LAB", "VAULT"], [("HALL", "LAB"), ("LAB", "VAULT")])
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
    await store.db().execute_query(
        "DELETE FROM unified.rule_authority_events WHERE rule_id IN"
        " (SELECT rule_id FROM unified.learned_rules WHERE domain_id = $1)", (DOMAIN,))
    await store.db().execute_query(
        "DELETE FROM unified.learned_rule_evidence WHERE rule_id IN"
        " (SELECT rule_id FROM unified.learned_rules WHERE domain_id = $1)", (DOMAIN,))
    await store.db().execute_query(
        "DELETE FROM unified.learned_rules WHERE domain_id = $1", (DOMAIN,))


def task_for(rule_id, operator):
    return Task(id=f"task_{operator}", type=TaskType.EXECUTION, description=operator,
                provenance={"learned_rule_id": rule_id, "grounded_operator": operator,
                            "domain_id": DOMAIN})


# ------------------------------------------------------------ non-circularity

@pytest.mark.asyncio
async def test_the_observation_comes_from_the_world_not_the_prediction(world_and_rule):
    world, _, stored = world_and_rule
    result = await GeneralPurposeExecutor().execute_task(
        task_for(stored.rule_id, "SBMOVE(z, HALL, LAB)"))

    assert result["runtime_outcome"] == RuntimeOutcome.CONFIRMATION.value
    # The physical check, independent of anything the substrate believes.
    assert (world.root / "LAB" / "z").exists()
    assert not (world.root / "HALL" / "z").exists()
    assert Fact("SBAT", ("z", "LAB")) in world.observe()


@pytest.mark.asyncio
async def test_a_world_that_moves_the_wrong_way_contradicts(world_and_rule):
    """The proof of non-circularity: if the observation were constructed from
    the rule's own effects, this could not fail."""
    world, _, stored = world_and_rule
    # The tool succeeds, but sends the agent somewhere the rule did not predict.
    get_binding_registry().register(DOMAIN, world.binding(destination_override="VAULT"))

    result = await GeneralPurposeExecutor().execute_task(
        task_for(stored.rule_id, "SBMOVE(z, HALL, LAB)"))

    assert result["runtime_outcome"] == RuntimeOutcome.CONTRADICTION.value
    assert result["success"] is False, "a clean tool call is not a confirmed model"
    added = [e for e in result["effects"] if e["polarity"] == "add"][0]
    assert added["verdict"] == EffectVerdict.CONTRADICTED.value
    assert (world.root / "VAULT" / "z").exists()


@pytest.mark.asyncio
async def test_an_unobservable_world_is_indeterminate_not_confirmation(world_and_rule):
    """Execution occurred; whether the model held cannot be established."""
    world, _, stored = world_and_rule
    executor = GeneralPurposeExecutor()

    original = world.observe
    calls = {"n": 0}

    def observe():
        calls["n"] += 1
        return original() if calls["n"] == 1 else None

    get_binding_registry().register(
        DOMAIN, OperatorBinding(predicate="SBMOVE", tool_name="move_file",
                                parameters=world.binding().parameters, observe=observe))

    result = await executor.execute_task(task_for(stored.rule_id, "SBMOVE(z, HALL, LAB)"))
    assert result["runtime_outcome"] == RuntimeOutcome.INDETERMINATE.value
    assert result["success"] is False
    assert all(e["verdict"] == EffectVerdict.UNKNOWN.value for e in result["effects"])


# ---------------------------------------------------------------- refusals

@pytest.mark.asyncio
async def test_absent_preconditions_prevent_any_tool_call(world_and_rule):
    """Authorization is re-checked against the OBSERVED world, and a refusal
    must not touch it."""
    world, _, stored = world_and_rule
    result = await GeneralPurposeExecutor().execute_task(
        task_for(stored.rule_id, "SBMOVE(z, LAB, VAULT)"))  # z is in HALL

    assert result["success"] is False
    # The refusal names the literal that failed rather than the set that did
    # not match: the preconditions are matched against the observed world one
    # at a time, so which one is absent is known and worth saying.
    assert "SBAT(z, LAB)" in result["refused"]
    assert "does not hold in the observed world" in result["refused"]
    assert (world.root / "HALL" / "z").exists(), "the world was touched on a refusal"
    assert not (world.root / "VAULT" / "z").exists()


@pytest.mark.asyncio
async def test_a_rule_demoted_after_planning_does_not_execute(world_and_rule):
    """t0 VALIDATED and planned, t1 demoted, t2 executes. The plan's
    authorization is not an argument at t2."""
    world, store, stored = world_and_rule
    await store.db().execute_query(
        "UPDATE unified.learned_rules SET epistemic_status = $1 WHERE rule_id = $2",
        (EpistemicStatus.SUPPORTED.value, stored.rule_id))

    result = await GeneralPurposeExecutor().execute_task(
        task_for(stored.rule_id, "SBMOVE(z, HALL, LAB)"))

    # It fails CLOSED. Falling through to the model would let a step the
    # substrate refused be carried out by generation instead.
    assert result["success"] is False
    assert "not validated" in result["refused"]
    assert (world.root / "HALL" / "z").exists()


# -------------------------------------------------------------- composition

@pytest.mark.asyncio
async def test_two_steps_compose_through_the_real_world(world_and_rule):
    """Step B must be authorized from the OBSERVED S1, not the planner's
    predicted S1."""
    world, _, stored = world_and_rule
    executor = GeneralPurposeExecutor()

    first = await executor.execute_task(task_for(stored.rule_id, "SBMOVE(z, HALL, LAB)"))
    assert first["runtime_outcome"] == RuntimeOutcome.CONFIRMATION.value
    assert Fact("SBAT", ("z", "LAB")) in world.observe()

    second = await executor.execute_task(task_for(stored.rule_id, "SBMOVE(z, LAB, VAULT)"))
    assert second["runtime_outcome"] == RuntimeOutcome.CONFIRMATION.value

    final = world.observe()
    assert Fact("SBAT", ("z", "VAULT")) in final
    assert Fact("SBAT", ("z", "HALL")) not in final
    assert Fact("SBAT", ("z", "LAB")) not in final
    assert (world.root / "VAULT" / "z").exists()


@pytest.mark.asyncio
async def test_the_second_step_survives_a_restart(world_and_rule):
    """A fresh executor and a fresh rule store between A and B. The authority
    for B is recovered from persistence and re-derived from the world."""
    world, _, stored = world_and_rule

    first = await GeneralPurposeExecutor().execute_task(
        task_for(stored.rule_id, "SBMOVE(z, HALL, LAB)"))
    assert first["runtime_outcome"] == RuntimeOutcome.CONFIRMATION.value

    reloaded = [r for r in await RuleStore().executable_rules(domain_id=DOMAIN)
                if r.rule_id == stored.rule_id]
    assert reloaded, "the rule did not survive to authorize the second step"

    second = await GeneralPurposeExecutor().execute_task(
        task_for(stored.rule_id, "SBMOVE(z, LAB, VAULT)"))
    assert second["runtime_outcome"] == RuntimeOutcome.CONFIRMATION.value
    assert (world.root / "VAULT" / "z").exists()


# ------------------------------------------------------- verification units

def test_a_successful_tool_call_alone_confirms_nothing():
    """The distinction that stops a rule accumulating support from its own
    invocation."""
    observation = ToolObservation(
        observation_id="o1", tool_name="t", invoked=True,
        tool_reported_success=True, observed=False)
    evidence = verify_effects(
        RuleEffects(add={Fact("SBAT", ("z", "LAB"))}), observation)
    assert evidence.outcome is RuntimeOutcome.INDETERMINATE


def test_add_and_delete_are_verified_independently():
    """ADD confirmed / DELETE contradicted is a different fact from either
    alone, and must not flatten to one boolean."""
    observation = ToolObservation(
        observation_id="o2", tool_name="t", invoked=True,
        tool_reported_success=True, observed=True,
        facts=frozenset({Fact("SBAT", ("z", "LAB")), Fact("SBAT", ("z", "HALL"))}))
    evidence = verify_effects(RuleEffects(
        add={Fact("SBAT", ("z", "LAB"))}, delete={Fact("SBAT", ("z", "HALL"))}), observation)

    verdicts = {v.polarity: v.verdict for v in evidence.verifications}
    assert verdicts[Polarity.ADD] is EffectVerdict.CONFIRMED
    assert verdicts[Polarity.DELETE] is EffectVerdict.CONTRADICTED
    assert evidence.outcome is RuntimeOutcome.CONTRADICTION


# ------------------------------------------------- autonomous epistemic loop

class LockedWorld(World):
    """A world with a condition the rule was never taught: locked rooms refuse
    entry, and the actuator reports success anyway."""

    def __init__(self, root, rooms, paths, locked):
        super().__init__(root, rooms, paths)
        self.locked = set(locked)

    def observe(self):
        facts = super().observe()
        if facts is None:
            return None
        return facts | {Fact("LOCKED", (r,)) for r in self.locked
                        if (self.root / r).is_dir()}

    def binding(self, destination_override=None):
        def parameters(args):
            agent, origin, destination = args
            target = origin if destination in self.locked else destination
            return {"source_path": str(self.root / origin / agent),
                    "destination_path": str(self.root / target / agent),
                    "create_dirs": False}
        return OperatorBinding("SBMOVE", "move_file", parameters, self.observe)


@pytest_asyncio.fixture
async def locked_world():
    root = Path(tempfile.mkdtemp(prefix="torin_locked_"))
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
    await store.db().execute_query(
        "DELETE FROM unified.rule_authority_events WHERE rule_id IN"
        " (SELECT rule_id FROM unified.learned_rules WHERE domain_id = $1)", (DOMAIN,))
    await store.db().execute_query(
        "DELETE FROM unified.learned_rule_evidence WHERE rule_id IN"
        " (SELECT rule_id FROM unified.learned_rules WHERE domain_id = $1)", (DOMAIN,))
    await store.db().execute_query(
        "DELETE FROM unified.learned_rules WHERE domain_id = $1", (DOMAIN,))


@pytest.mark.asyncio
async def test_the_executor_itself_closes_the_loop(locked_world):
    """One execute_task call. Nothing else touches evidence or status.

    Reality violates a prediction, the contradiction becomes durable evidence,
    attribution charges it to the rule, and the rule loses execution authority
    -- without anything outside the executor intervening.
    """
    from core.execution.effect_verification import Attribution, RuntimeOutcome
    from core.learning.rule_store import EvidenceRole

    world, store, stored = locked_world
    task = Task(id="t", type=TaskType.EXECUTION, description="SBMOVE(z, HALL, LAB)",
                provenance={"learned_rule_id": stored.rule_id,
                            "grounded_operator": "SBMOVE(z, HALL, LAB)",
                            "domain_id": DOMAIN})

    result = await GeneralPurposeExecutor().execute_task(task)

    assert result["runtime_outcome"] == RuntimeOutcome.CONTRADICTION.value
    assert result["attribution"] == Attribution.RULE_EVIDENCE.value
    assert result["rule_status_after"] == EpistemicStatus.REFUTED.value

    reloaded = [r for r in await store.load(domain_id=DOMAIN)
                if r.rule_id == stored.rule_id][0]
    assert reloaded.status is EpistemicStatus.REFUTED
    roots = await store.evidence_roots(
        stored.rule_id, {EvidenceRole.RUNTIME_CONTRADICTION})
    assert result["observation_id"] in roots, "the contradiction was not persisted"


@pytest.mark.asyncio
async def test_a_refuted_rule_stops_being_operational_knowledge(locked_world):
    """The assertion that matters most: a logged contradiction must not leave
    the same VALIDATED rule executing forever."""
    from core.learning.rule_grounding import ground_for_problem

    world, store, stored = locked_world
    state = world.observe()
    goal = [Fact("SBAT", ("z", "LAB"))]
    task = Task(id="t", type=TaskType.EXECUTION, description="SBMOVE(z, HALL, LAB)",
                provenance={"learned_rule_id": stored.rule_id,
                            "grounded_operator": "SBMOVE(z, HALL, LAB)",
                            "domain_id": DOMAIN})

    before = ground_for_problem(
        await store.executable_rules(domain_id=DOMAIN), state, goal)
    assert before.operators, "the rule should be operational before the contradiction"

    await GeneralPurposeExecutor().execute_task(task)

    after = ground_for_problem(
        await store.executable_rules(domain_id=DOMAIN), state, goal)
    assert after.operators == [], "planning still offers a refuted rule"
    retry = await GeneralPurposeExecutor().execute_task(task)
    assert retry["success"] is False
    assert "refuted" in retry["refused"]


@pytest.mark.asyncio
async def test_torin_does_not_invent_the_condition_it_was_never_taught(locked_world):
    """One contradiction reduces certainty; it does not determine a replacement.

    LOCKED is not even in the rule's vocabulary. Manufacturing `NOT LOCKED(B)`
    here would be contradiction -> invent explanation, which is the failure mode
    the whole attribution path exists to avoid.
    """
    world, store, stored = locked_world
    task = Task(id="t", type=TaskType.EXECUTION, description="SBMOVE(z, HALL, LAB)",
                provenance={"learned_rule_id": stored.rule_id,
                            "grounded_operator": "SBMOVE(z, HALL, LAB)",
                            "domain_id": DOMAIN})
    await GeneralPurposeExecutor().execute_task(task)

    rules = await store.load(domain_id=DOMAIN)
    assert len(rules) == 1, "a replacement hypothesis was invented from one observation"
    assert not any("LOCKED" in str(f) for f in rules[0].rule.body)


def test_a_mismatch_is_not_charged_to_the_rule_unless_everything_held():
    """The credit invariant at runtime: never debit a strategy for an
    infrastructure failure."""
    from core.execution.effect_verification import (
        Attribution, AttributionContext, RuntimeOutcome, ToolObservation,
        attribute, verify_effects,
    )

    observation = ToolObservation(
        observation_id="o", tool_name="t", invoked=True,
        tool_reported_success=True, observed=True, facts=frozenset())
    evidence = verify_effects(
        RuleEffects(add={Fact("SBAT", ("z", "LAB"))}), observation, rule_id="r")
    assert evidence.outcome is RuntimeOutcome.CONTRADICTION

    everything_held = AttributionContext(
        preconditions_observed=True, rule_validated_at_execution=True,
        action_matches_rule=True, arguments_verified=True,
        invocation_occurred=True, observer_available=True,
        post_state_observed=True, external_interference=False)
    assert attribute(evidence, everything_held)[0] is Attribution.RULE_EVIDENCE

    misbound = AttributionContext(**{**vars(everything_held), "action_matches_rule": False})
    assert attribute(evidence, misbound)[0] is Attribution.EXECUTION_FAILURE

    interfered = AttributionContext(**{**vars(everything_held), "external_interference": True})
    assert attribute(evidence, interfered)[0] is Attribution.EXTERNAL_FAILURE
