#!/usr/bin/env python3
"""
Motivation integration tests — REAL IntrinsicMotivationSystem, no stub
======================================================================
The coordinator called five methods on the motivation system that did not
exist anywhere: calculate_competence_reward, calculate_curiosity_reward,
calculate_novelty_reward, calculate_autonomy_reward, get_top_exploration_targets.

Every call raised AttributeError. _learning_phase applied its priority boost
and then died before its rewards and memory write; generate_curiosity_driven_goals
returned [] on every call and read as a stable system.

The unit tests could not catch this: they stub intrinsic_motivation with fake
reward methods, so the real collaborator was never exercised. These tests use
the real object.
"""

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.agents.autonomous.intrinsic_motivation import (  # noqa: E402
    IntrinsicMotivationSystem,
    MotivationDimension,
)

REWARD_METHODS = [
    "calculate_competence_reward",
    "calculate_curiosity_reward",
    "calculate_novelty_reward",
    "calculate_autonomy_reward",
]
TARGET_METHODS = ["get_top_exploration_targets", "mark_target_explored"]


def motivation():
    return IntrinsicMotivationSystem()


# ------------------------------------------------- the API actually exists


@pytest.mark.parametrize("name", REWARD_METHODS + TARGET_METHODS)
def test_coordinator_facing_method_exists(name):
    """Each of these was called in production and defined nowhere."""
    assert hasattr(motivation(), name), f"{name} does not exist"


# ------------------------------------------------- rewards are not drives


def test_competence_reward_is_not_the_competence_drive():
    """The drive is an inverted-U — a success rate above 0.8 drops it to 0.4
    because there is no room to grow. A reward aliased to it would pay least
    exactly when the system performs best, inverting the reinforcement signal.
    """
    system = motivation()

    async def scenario():
        # Establish a low baseline, then improve on it.
        await system.calculate_competence_reward("deploy", performance=0.2, success=True)
        await system.calculate_competence_reward("deploy", performance=0.2, success=True)
        return await system.calculate_competence_reward("deploy", performance=0.9, success=True)

    reward = asyncio.run(scenario())

    assert reward.reward_value > 0, "improving performance must be rewarded"
    assert reward.dimension == MotivationDimension.COMPETENCE


def test_competence_reward_decays_as_a_skill_saturates():
    """Learning progress, not absolute performance: a mastered skill stops
    paying, which is what the inverted-U drive expresses."""
    system = motivation()

    async def scenario():
        first = await system.calculate_competence_reward("x", performance=0.9, success=True)
        for _ in range(6):
            await system.calculate_competence_reward("x", performance=0.9, success=True)
        return first, await system.calculate_competence_reward("x", performance=0.9, success=True)

    first, saturated = asyncio.run(scenario())

    assert first.reward_value > saturated.reward_value
    assert saturated.reward_value == pytest.approx(0.0, abs=0.05)


def test_regression_produces_a_negative_competence_reward():
    system = motivation()

    async def scenario():
        for _ in range(3):
            await system.calculate_competence_reward("y", performance=0.9, success=True)
        return await system.calculate_competence_reward("y", performance=0.2, success=False)

    assert asyncio.run(scenario()).reward_value < 0


def test_unanswered_complexity_earns_no_curiosity_credit():
    """A hard question left unanswered is curiosity aroused, not satisfied."""
    system = motivation()

    async def scenario():
        unanswered = await system.calculate_curiosity_reward(
            {"information_gain": 0.0, "uncertainty_reduction": 0.0,
             "question_complexity": 1.0, "answer_depth": 0.0}
        )
        answered = await system.calculate_curiosity_reward(
            {"information_gain": 0.0, "uncertainty_reduction": 0.0,
             "question_complexity": 1.0, "answer_depth": 1.0}
        )
        return unanswered, answered

    unanswered, answered = asyncio.run(scenario())

    assert unanswered.reward_value == 0.0
    assert answered.reward_value > 0.0


def test_repeating_an_experience_is_less_novel_than_a_new_one():
    system = motivation()

    async def scenario():
        base = {"active_goals": 3, "active_tasks": 2, "cycle_count": 10}
        await system.calculate_novelty_reward(base)
        repeat = await system.calculate_novelty_reward(dict(base))
        different = await system.calculate_novelty_reward(
            {"active_goals": 90, "active_tasks": 80, "cycle_count": 900}
        )
        return repeat, different

    repeat, different = asyncio.run(scenario())

    assert repeat.reward_value < different.reward_value


def test_autonomy_rewards_self_direction_with_a_real_choice():
    system = motivation()

    async def scenario():
        directed = await system.calculate_autonomy_reward(
            {"self_initiated": False, "choice_made": False, "exploration_ratio": 0.5}
        )
        autonomous = await system.calculate_autonomy_reward(
            {"self_initiated": True, "choice_made": True, "exploration_ratio": 0.5}
        )
        return directed, autonomous

    directed, autonomous = asyncio.run(scenario())

    assert autonomous.reward_value > directed.reward_value


def test_rewards_stay_in_range():
    system = motivation()

    async def scenario():
        return [
            await system.calculate_curiosity_reward(
                {"information_gain": 99, "uncertainty_reduction": 99,
                 "question_complexity": 99, "answer_depth": 99}
            ),
            await system.calculate_autonomy_reward(
                {"self_initiated": True, "choice_made": True, "exploration_ratio": 99}
            ),
            await system.calculate_competence_reward("z", performance=99, success=True),
        ]

    for reward in asyncio.run(scenario()):
        assert -1.0 <= reward.reward_value <= 1.0


# ------------------------------------------- exploration targets: exposure


def test_exploration_targets_come_from_the_epistemic_engine():
    """Not a manufactured ranking: EpistemicEngine.get_unstable_regions()
    already returns high-entropy beliefs and stalled hypotheses, sorted by
    entropy descending."""
    from core.reasoning.epistemic_engine import EpistemicTarget

    system = motivation()
    made = [
        EpistemicTarget(target_id=f"b{i}", target_type="belief", entropy=0.9 - i * 0.1,
                        description=f"resolve {i}", domain="d")
        for i in range(4)
    ]

    class Engine:
        def get_unstable_regions(self):
            return made

    import core.reasoning.epistemic_engine as ee
    original = ee.get_epistemic_engine
    ee.get_epistemic_engine = lambda: Engine()
    try:
        targets = asyncio.run(system.get_top_exploration_targets(limit=2))
    finally:
        ee.get_epistemic_engine = original

    assert [t.target_id for t in targets] == ["b0", "b1"], "must preserve entropy order"


def test_a_broken_epistemic_engine_is_not_reported_as_no_targets():
    """The defect this whole fix is about: [] must not mean 'broken'."""
    system = motivation()

    import core.reasoning.epistemic_engine as ee
    original = ee.get_epistemic_engine

    def boom():
        raise RuntimeError("engine down")

    ee.get_epistemic_engine = boom
    try:
        with pytest.raises(RuntimeError):
            asyncio.run(system.get_top_exploration_targets(limit=3))
    finally:
        ee.get_epistemic_engine = original


# --------------------------------- the coordinator against the REAL system


def _coordinator_with_real_motivation():
    from core.agents.autonomous.autonomous_coordinator import AutonomousCoordinator
    from core.agents.autonomous.learning_adapter import LearningAdapter
    from core.agents.autonomous.shared_types import Priority, TaskType

    async def noop(*a, **k):
        return None

    async def perception_stats(*a, **k):
        return {"novel_patterns": 2}

    adapter = LearningAdapter()
    adapter.active = True

    coordinator = object.__new__(AutonomousCoordinator)
    coordinator.learning = adapter
    coordinator.intrinsic_motivation = IntrinsicMotivationSystem()   # REAL
    coordinator.stats = {"cycles_completed": 3}
    task = SimpleNamespace(type=TaskType.RESEARCH, priority=Priority.LOW, description="survey")
    coordinator.planning = SimpleNamespace(
        active_plans={"p": SimpleNamespace(tasks=[task])},
        current_goals={},
        _store_plan=noop,
        _store_goal=noop,
    )
    coordinator.system_state = SimpleNamespace(
        mode=SimpleNamespace(value="autonomous"),
        active_goals=[], active_tasks=[], resource_usage=0.3, resources={},
    )
    coordinator.perception = SimpleNamespace(get_statistics=perception_stats)
    coordinator.store_memory = noop
    return coordinator, task


def test_learning_phase_completes_against_the_real_motivation_system():
    """This is the test that would have caught the phantom methods: it runs
    _learning_phase with the real IntrinsicMotivationSystem and requires the
    phase to reach its terminal write, not merely boost a priority and die."""
    from core.agents.autonomous.shared_types import Priority

    coordinator, task = _coordinator_with_real_motivation()

    async def scenario():
        for _ in range(5):
            await coordinator._record_experience_outcome(
                SimpleNamespace(id="t", metadata={}), "research", True, "success"
            )
        await coordinator._learning_phase()

    asyncio.run(scenario())

    assert task.priority == Priority.MEDIUM, "priority boost did not happen"
    assert coordinator._learning_phase_status == "COMPLETED", (
        f"phase did not reach its terminal write "
        f"(status={coordinator._learning_phase_status})"
    )


def test_learning_phase_reports_abort_rather_than_appearing_successful():
    """A phase that dies partway must be distinguishable from one that ran."""
    coordinator, _ = _coordinator_with_real_motivation()

    async def explode(*a, **k):
        raise RuntimeError("motivation down")

    coordinator.intrinsic_motivation.calculate_novelty_reward = explode

    async def scenario():
        for _ in range(5):
            await coordinator._record_experience_outcome(
                SimpleNamespace(id="t", metadata={}), "research", True, "success"
            )
        await coordinator._learning_phase()

    asyncio.run(scenario())

    assert coordinator._learning_phase_status == "ABORTED"


def test_curiosity_goals_are_generated_from_real_targets():
    """generate_curiosity_driven_goals returned [] on every call because its
    first statement called a method that did not exist. With a controlled
    non-empty target fixture it must now produce goals and report
    TARGETS_AVAILABLE rather than the SYSTEM_FAILURE it was silently in."""
    from core.agents.autonomous.autonomous_coordinator import AutonomousCoordinator
    from core.reasoning.epistemic_engine import EpistemicTarget
    import core.reasoning.epistemic_engine as ee

    coordinator = object.__new__(AutonomousCoordinator)
    coordinator.intrinsic_motivation = IntrinsicMotivationSystem()   # REAL
    coordinator.coordinator_config = SimpleNamespace(
        max_goals_curiosity=2, expected_competence_gain=0.5,
        novelty_weight=0.4, uncertainty_weight=0.4, competence_weight=0.2,
    )
    coordinator.slack_notifier = None
    created = []

    async def set_goal(description, priority=None, intrinsic_values=None):
        created.append((description, intrinsic_values))
        return f"goal_{len(created)}"

    coordinator.set_goal = set_goal

    targets = [
        EpistemicTarget(target_id=f"b{i}", target_type="belief", entropy=0.9,
                        description=f"resolve claim {i}", domain="d")
        for i in range(2)
    ]

    class Engine:
        def get_unstable_regions(self):
            return targets

    original = ee.get_epistemic_engine
    ee.get_epistemic_engine = lambda: Engine()
    try:
        goal_ids = asyncio.run(coordinator.generate_curiosity_driven_goals())
    finally:
        ee.get_epistemic_engine = original

    assert goal_ids, "no goals generated from a non-empty target fixture"
    assert coordinator._exploration_status == "TARGETS_AVAILABLE"
    assert all(v["intrinsic_reward_potential"] > 0 for _, v in created)


def test_zero_targets_is_distinguishable_from_a_broken_subsystem():
    from core.agents.autonomous.autonomous_coordinator import AutonomousCoordinator
    import core.reasoning.epistemic_engine as ee

    coordinator = object.__new__(AutonomousCoordinator)
    coordinator.intrinsic_motivation = IntrinsicMotivationSystem()
    coordinator.coordinator_config = SimpleNamespace(max_goals_curiosity=2)

    class Empty:
        def get_unstable_regions(self):
            return []

    def boom():
        raise RuntimeError("engine down")

    original = ee.get_epistemic_engine
    try:
        ee.get_epistemic_engine = lambda: Empty()
        assert asyncio.run(coordinator.generate_curiosity_driven_goals()) == []
        empty_status = coordinator._exploration_status

        ee.get_epistemic_engine = boom
        assert asyncio.run(coordinator.generate_curiosity_driven_goals()) == []
        broken_status = coordinator._exploration_status
    finally:
        ee.get_epistemic_engine = original

    assert empty_status == "NO_EXPLORATION_TARGETS"
    assert broken_status == "SYSTEM_FAILURE"
    assert empty_status != broken_status


def test_curiosity_goals_are_generated_from_real_targets():
    """generate_curiosity_driven_goals returned [] on every call because its
    first statement called a method that did not exist. With a controlled
    non-empty target fixture it must now produce goals and report
    TARGETS_AVAILABLE rather than the SYSTEM_FAILURE it was silently in."""
    from core.agents.autonomous.autonomous_coordinator import AutonomousCoordinator
    from core.reasoning.epistemic_engine import EpistemicTarget
    import core.reasoning.epistemic_engine as ee

    coordinator = object.__new__(AutonomousCoordinator)
    coordinator.intrinsic_motivation = IntrinsicMotivationSystem()   # REAL
    coordinator.coordinator_config = SimpleNamespace(
        max_goals_curiosity=2, expected_competence_gain=0.5,
        novelty_weight=0.4, uncertainty_weight=0.4, competence_weight=0.2,
    )
    coordinator.slack_notifier = None
    created = []

    async def set_goal(description, priority=None, intrinsic_values=None):
        created.append((description, intrinsic_values))
        return f"goal_{len(created)}"

    coordinator.set_goal = set_goal

    targets = [
        EpistemicTarget(target_id=f"b{i}", target_type="belief", entropy=0.9,
                        description=f"resolve claim {i}", domain="d")
        for i in range(2)
    ]

    class Engine:
        def get_unstable_regions(self):
            return targets

    original = ee.get_epistemic_engine
    ee.get_epistemic_engine = lambda: Engine()
    try:
        goal_ids = asyncio.run(coordinator.generate_curiosity_driven_goals())
    finally:
        ee.get_epistemic_engine = original

    assert goal_ids, "no goals generated from a non-empty target fixture"
    assert coordinator._exploration_status == "TARGETS_AVAILABLE"
    assert all(v["intrinsic_reward_potential"] > 0 for _, v in created)


def test_zero_targets_is_distinguishable_from_a_broken_subsystem():
    from core.agents.autonomous.autonomous_coordinator import AutonomousCoordinator
    import core.reasoning.epistemic_engine as ee

    coordinator = object.__new__(AutonomousCoordinator)
    coordinator.intrinsic_motivation = IntrinsicMotivationSystem()
    coordinator.coordinator_config = SimpleNamespace(max_goals_curiosity=2)

    class Empty:
        def get_unstable_regions(self):
            return []

    def boom():
        raise RuntimeError("engine down")

    original = ee.get_epistemic_engine
    try:
        ee.get_epistemic_engine = lambda: Empty()
        assert asyncio.run(coordinator.generate_curiosity_driven_goals()) == []
        empty_status = coordinator._exploration_status

        ee.get_epistemic_engine = boom
        assert asyncio.run(coordinator.generate_curiosity_driven_goals()) == []
        broken_status = coordinator._exploration_status
    finally:
        ee.get_epistemic_engine = original

    assert empty_status == "NO_EXPLORATION_TARGETS"
    assert broken_status == "SYSTEM_FAILURE"
    assert empty_status != broken_status


# ---------------------------------------- competence-drive signature taxonomy


def test_contrastive_pending_signature_is_not_malformed():
    """A pending signature ("", 0) is the CONTRASTIVE sentinel
    (demonstration_store.CONTRASTIVE) — domain-level contrastive evidence, NOT a
    malformed operator. The competence drive once rejected it as EMPTY_SIGNATURE;
    it must instead yield a DOMAIN-scoped competence goal, mirroring how the drain
    expands a contrastive across the domain.

    This asserts EXACT accounting over a controlled queue so the reason competence
    contributes each goal (or zero) is proven, not inferred:
        4 candidates -> 2 accepted (1 domain_contrastive + 1 per-operator)
                     -> 2 rejected (CORRUPT_DOMAIN, MALFORMED_SIGNATURE)
    """
    import core.learning.demonstration_store as ds
    from core.learning.demonstration_store import DemonstrationStore

    class FakeStore:
        CONTRASTIVE = DemonstrationStore.CONTRASTIVE

        async def pending_signatures(self, *, limit=None):
            rows = [
                ("fs_general_obs1", "", 0),   # CONTRASTIVE  -> domain goal
                ("nav", "move", 2),           # real operator -> per-op goal
                ("", "p", 1),                 # corrupt domain -> reject
                ("d", "", 3),                 # blank pred, arity!=0 -> reject
            ]
            return rows[:limit] if limit is not None else rows

    original = ds.get_demonstration_store
    ds.get_demonstration_store = lambda: FakeStore()
    try:
        goals = asyncio.run(motivation()._competence_goals(budget=4))
    finally:
        ds.get_demonstration_store = original

    assert len(goals) == 2, f"expected 2 accepted goals, got {len(goals)}"
    domain_goals = [g for g in goals if g.metadata.get("scope") == "domain_contrastive"]
    op_goals = [g for g in goals if g.metadata.get("predicate") == "move"]
    assert len(domain_goals) == 1, "contrastive sentinel was not accepted as a domain goal"
    assert domain_goals[0].metadata["domain_id"] == "fs_general_obs1"
    assert "domain_contrastive" == domain_goals[0].metadata["scope"]
    assert len(op_goals) == 1, "real operator did not yield a per-operator goal"
    assert op_goals[0].metadata["arity"] == 2


def test_corrupt_pending_signatures_are_rejected_with_distinct_reasons(caplog):
    """A blank DOMAIN is genuinely corrupt (append() forbids it); a blank
    PREDICATE with nonzero arity is not the contrastive sentinel and is malformed.
    Both are rejected loudly with distinct named reasons, never turned into a
    blank-named goal and never silently dropped."""
    import logging
    import core.learning.demonstration_store as ds
    from core.learning.demonstration_store import DemonstrationStore

    class FakeStore:
        CONTRASTIVE = DemonstrationStore.CONTRASTIVE

        async def pending_signatures(self, *, limit=None):
            return [("", "p", 1), ("d", "", 3)]

    original = ds.get_demonstration_store
    ds.get_demonstration_store = lambda: FakeStore()
    try:
        with caplog.at_level(logging.WARNING):
            goals = asyncio.run(motivation()._competence_goals(budget=4))
    finally:
        ds.get_demonstration_store = original

    assert goals == [], "corrupt signatures must not produce goals"
    text = caplog.text
    assert "CORRUPT_DOMAIN" in text
    assert "MALFORMED_SIGNATURE" in text


# ---------------------------------------- drive-goal execution handler


def _drive_shell(learning):
    """A coordinator shell with just what _execute_drive_goal touches."""
    from core.agents.autonomous.autonomous_coordinator import AutonomousCoordinator
    c = object.__new__(AutonomousCoordinator)
    c.learning = learning
    c.universal_domain_master = None      # isolate the learning path
    return c


def _task(**md):
    return SimpleNamespace(metadata=md)


def test_competence_goal_verified_only_when_operator_becomes_executable():
    """A competence goal's outcome is READ from induction, never fabricated:
    verified iff the operator actually became executable."""
    import core.learning.exploration as ex
    from core.agents.autonomous.autonomous_coordinator import AutonomousCoordinator

    async def reinduce(*, domain_id, predicate, arity):
        return {"status": "operator_executable" if predicate == "MOVE" else "operator_candidate",
                "executable": predicate == "MOVE"}

    learning = SimpleNamespace(reinduce_operator=reinduce)
    orig = ex.explorable_domains
    ex.explorable_domains = lambda: []     # non-explorable: no acting, pure induce
    try:
        c = _drive_shell(learning)
        good = asyncio.run(c._execute_drive_goal(
            _task(drive="competence", domain_id="nav", predicate="MOVE", arity=2)))
        weak = asyncio.run(c._execute_drive_goal(
            _task(drive="competence", domain_id="nav", predicate="OPEN", arity=1)))
    finally:
        ex.explorable_domains = orig

    assert good["verification_state"] == "verified" and good["success"] is True
    assert weak["verification_state"] == "failed" and weak["success"] is False
    assert weak["error"] and "operator_candidate" in weak["error"]


def test_confidence_goal_fails_honestly_when_no_new_root_is_gathered():
    """Confidence success is a MEASURED rise in confirming roots. If acting
    gathers nothing new (or the domain cannot be explored), the goal fails with a
    named reason — never a fabricated success."""
    import core.learning.exploration as ex

    async def reinduce(*, domain_id, predicate, arity):
        return {"status": "operator_executable", "executable": True}

    learning = SimpleNamespace(reinduce_operator=reinduce)
    c = _drive_shell(learning)
    # root count never moves
    async def root_count(*, domain_id, predicate, arity):
        return 2
    c._rule_root_count = root_count

    orig = ex.explorable_domains
    ex.explorable_domains = lambda: []     # non-explorable domain
    try:
        res = asyncio.run(c._execute_drive_goal(
            _task(drive="confidence", domain_id="kite17", predicate="MOVE", arity=3,
                  positive_root_count=2)))
    finally:
        ex.explorable_domains = orig

    assert res["verification_state"] == "failed" and res["success"] is False
    assert res["root_count_before"] == 2 and res["root_count_after"] == 2
    # a domain with no proposer is a BINDING_GAP (addressable), not "can't operate"
    assert res.get("binding_gap") is True
    assert "binding_gap" in res["error"]


def test_drive_goal_rejects_missing_signature():
    learning = SimpleNamespace()
    c = _drive_shell(learning)
    res = asyncio.run(c._execute_drive_goal(_task(drive="competence", domain_id="d")))
    assert res["verification_state"] == "failed" and "signature" in res["error"]
