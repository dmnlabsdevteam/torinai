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
