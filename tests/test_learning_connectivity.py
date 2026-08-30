#!/usr/bin/env python3
"""
Learning pipeline connectivity tests
====================================
Guards the learning-path repairs that were previously verified only by
throwaway scripts.

Everything here was confirmed once by hand and would have silently regressed,
which is precisely how the defects it covers accumulated in the first place.

Each test names the defect it pins down.
"""

import asyncio
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.agents.autonomous.learning_adapter import (  # noqa: E402
    LearningAdapter,
    LearningData,
)


def experience(action="retry", success=True, confidence=0.9, context=None):
    return LearningData(
        context=context or {"task": "deploy"},
        action=action,
        outcome={"ok": success},
        success=success,
        confidence=confidence,
        timestamp=datetime.now(),
        metadata={},
    )


def active_adapter():
    adapter = LearningAdapter()
    adapter.active = True
    return adapter


# ------------------------------------------------------- LearningAdapter repairs


def test_missing_methods_are_defined():
    """_update_average_confidence and _discover_patterns were called by
    integrate_experience but never defined, so every call raised."""
    assert hasattr(LearningAdapter, "_update_average_confidence")
    assert hasattr(LearningAdapter, "_discover_patterns")


def test_integrating_an_experience_succeeds():
    """integrate_experience returned False on every call, for every input."""
    adapter = active_adapter()

    assert asyncio.run(adapter.integrate_experience(experience())) is True


def test_metrics_agree_with_the_return_value():
    """The worst symptom: successful_integrations incremented while the
    function returned False, so counters and callers disagreed."""
    adapter = active_adapter()

    result = asyncio.run(adapter.integrate_experience(experience()))

    assert result is True
    assert adapter.metrics.successful_integrations == 1
    assert adapter.metrics.failed_integrations == 0
    assert adapter.metrics.experiences_processed == 1


def test_string_action_does_not_raise():
    """LearningData.action is typed str, but was read as a dict via
    .get("type"), raising 'str' object has no attribute 'get'."""
    adapter = active_adapter()

    assert asyncio.run(adapter.integrate_experience(experience(action="retry"))) is True
    assert adapter.patterns, "no pattern recorded from a string action"


def test_dict_action_still_supported():
    """The fix must not break structured actions."""
    adapter = active_adapter()

    data = experience()
    data.action = {"type": "rollback"}

    assert asyncio.run(adapter.integrate_experience(data)) is True
    assert any(p.get("action_type") == "rollback" for p in adapter.patterns.values())


def test_average_confidence_is_computed():
    adapter = active_adapter()

    async def scenario():
        for _ in range(4):
            await adapter.integrate_experience(experience(confidence=0.8))

    asyncio.run(scenario())

    assert adapter.metrics.average_confidence == pytest.approx(0.8, abs=1e-6)


def test_experience_produces_a_consumable_recommendation():
    """get_recommendations read self.patterns, which only integrate_experience
    fills -- and that always failed, so it could only ever return []."""
    adapter = active_adapter()

    async def scenario():
        for _ in range(4):
            await adapter.integrate_experience(experience())
        return await adapter.get_recommendations({"task": "deploy"})

    recommendations = asyncio.run(scenario())

    assert recommendations, "pattern store produced no recommendation"


# --------------------------------------------------------------- the wiring


def test_coordinator_feeds_the_experience_learner():
    """LearningAdapter was constructed at startup and never fed, so its
    pattern store stayed empty no matter how many tasks completed."""
    from core.agents.autonomous.autonomous_coordinator import AutonomousCoordinator

    coordinator = object.__new__(AutonomousCoordinator)
    coordinator.learning = active_adapter()
    task = SimpleNamespace(id="t1", metadata={})

    async def scenario():
        for _ in range(4):
            await coordinator._record_experience_outcome(
                task, "code_generation", True, "success"
            )

    asyncio.run(scenario())

    assert coordinator.learning.metrics.experiences_processed == 4
    assert coordinator.learning.patterns


def test_experience_wiring_survives_a_missing_adapter():
    """The outcome path must not fail when no adapter is attached."""
    from core.agents.autonomous.autonomous_coordinator import AutonomousCoordinator

    coordinator = object.__new__(AutonomousCoordinator)
    coordinator.learning = None

    asyncio.run(
        coordinator._record_experience_outcome(
            SimpleNamespace(id="t1", metadata={}), "x", True, "success"
        )
    )


# -------------------------------------- experience -> applied behaviour change


async def _noop(*args, **kwargs):
    return None


async def _reward(*args, **kwargs):
    return SimpleNamespace(reward_value=0.1)


async def _perception_stats(*args, **kwargs):
    return {"novel_patterns": 0}


async def _no_targets(*args, **kwargs):
    return []


def _coordinator_with_plan(tasks, goals=None):
    """A coordinator carrying just enough real state to run _learning_phase.

    The tasks hold real TaskType/Priority enums on purpose: the defect this
    guards was an enum-vs-string comparison.
    """
    from core.agents.autonomous.autonomous_coordinator import AutonomousCoordinator

    coordinator = object.__new__(AutonomousCoordinator)
    coordinator.learning = active_adapter()
    coordinator.stats = {"cycles_completed": 1}
    coordinator.planning = SimpleNamespace(
        active_plans={"p1": SimpleNamespace(tasks=list(tasks))},
        current_goals=dict(goals or {}),
        _store_plan=_noop,
        _store_goal=_noop,
    )
    coordinator.system_state = SimpleNamespace(
        mode=SimpleNamespace(value="autonomous"),
        active_goals=[],
        active_tasks=[],
        resource_usage=0.2,
        resources={},
    )
    coordinator.intrinsic_motivation = SimpleNamespace(
        calculate_competence_reward=_reward,
        calculate_curiosity_reward=_reward,
        calculate_novelty_reward=_reward,
        calculate_autonomy_reward=_reward,
        get_top_exploration_targets=_no_targets,
    )
    coordinator.perception = SimpleNamespace(get_statistics=_perception_stats)
    coordinator.store_memory = _noop
    return coordinator


def _feed(coordinator, action, success, times):
    async def scenario():
        for _ in range(times):
            await coordinator._record_experience_outcome(
                SimpleNamespace(id="t", metadata={}),
                action,
                success,
                "success" if success else "failure",
            )
        await coordinator._learning_phase()

    asyncio.run(scenario())


def test_experience_raises_the_priority_of_a_proven_task_type():
    """The whole chain, end to end: outcomes -> patterns -> recommendation ->
    applier -> a real task's priority changes.

    Every link existed and none were joined. _learning_phase was never called
    by the AI-driven cycle; the adapter emitted the bare action name as the
    verb, which matched no applier branch; and that branch compared
    str(TaskType.RESEARCH) against "research", so it could not have matched a
    task even if it had been reached.
    """
    from core.agents.autonomous.shared_types import Priority, TaskType

    task = SimpleNamespace(
        type=TaskType.RESEARCH, priority=Priority.LOW, description="survey the field"
    )
    coordinator = _coordinator_with_plan([task])

    _feed(coordinator, "research", success=True, times=5)

    assert task.priority == Priority.MEDIUM, "a proven task type was not boosted"


def test_a_failing_task_type_is_not_boosted():
    """Prioritising a task type that mostly fails amplifies the failure."""
    from core.agents.autonomous.shared_types import Priority, TaskType

    task = SimpleNamespace(
        type=TaskType.ANALYSIS, priority=Priority.LOW, description="analyse"
    )
    coordinator = _coordinator_with_plan([task])

    _feed(coordinator, "analysis", success=False, times=5)

    assert task.priority == Priority.LOW


def test_failures_reach_the_pattern_store():
    """_record_experience_outcome scored failures confidence=0.0, below the
    adapter's min_confidence of 0.3, so every failure was dropped at the door
    and the store only ever accumulated successes."""
    coordinator = _coordinator_with_plan([])

    async def scenario():
        for _ in range(4):
            await coordinator._record_experience_outcome(
                SimpleNamespace(id="t", metadata={}), "deploy", False, "failure"
            )

    asyncio.run(scenario())

    failures = sum(p["failures"] for p in coordinator.learning.patterns.values())
    assert failures == 4, "failures never reached the pattern store"


def test_unproven_task_types_are_not_recommended():
    """Below the trial floor there is no evidence to act on."""
    from core.agents.autonomous.shared_types import Priority, TaskType

    task = SimpleNamespace(
        type=TaskType.PLANNING, priority=Priority.LOW, description="plan"
    )
    coordinator = _coordinator_with_plan([task])

    _feed(coordinator, "planning", success=True, times=2)

    assert task.priority == Priority.LOW


def test_recommendations_speak_the_appliers_vocabulary():
    """The applier understands three verbs and reads action["task_type"]."""
    adapter = active_adapter()

    async def scenario():
        for _ in range(4):
            await adapter.integrate_experience(experience(action="research"))
        return await adapter.get_recommendations({})

    recommendations = asyncio.run(scenario())

    assert recommendations
    for rec in recommendations:
        assert rec["action"]["type"] == "prioritize_task_type"
        assert rec["action"]["task_type"] == "research"


def test_one_recommendation_per_task_type():
    """Patterns are keyed per (action, context). Emitting one recommendation
    each would boost the same task type once per context in a single pass."""
    adapter = active_adapter()

    async def scenario():
        for i in range(6):
            await adapter.integrate_experience(
                experience(action="research", context={"task": f"ctx{i}"})
            )
        return await adapter.get_recommendations({})

    recommendations = asyncio.run(scenario())

    assert len(adapter.patterns) == 6, "expected one pattern per context"
    assert len(recommendations) == 1
    assert recommendations[0]["action"]["successes"] == 6


def test_applier_reports_whether_anything_changed():
    """It returned None on every path, so the caller's `if success:` was never
    true and no application was ever counted or rewarded."""
    from core.agents.autonomous.shared_types import Priority, TaskType

    task = SimpleNamespace(
        type=TaskType.RESEARCH, priority=Priority.LOW, description="d"
    )
    coordinator = _coordinator_with_plan([task])

    def apply(task_type):
        return asyncio.run(
            coordinator._apply_learning_recommendation(
                {"action": {"type": "prioritize_task_type", "task_type": task_type}}
            )
        )

    assert apply("research") is True
    assert apply("no_such_type") is False, "matching nothing is not an application"


def test_unknown_action_type_is_not_reported_as_applied():
    coordinator = _coordinator_with_plan([])

    applied = asyncio.run(
        coordinator._apply_learning_recommendation({"action": {"type": "invented"}})
    )

    assert applied is False


def test_learning_is_registered_as_an_idle_tier():
    """_learning_phase survived the AI-driven rewrite as a defined but
    unreachable method; the idle tier registry is what now drives it."""
    from core.agents.autonomous.autonomous_coordinator import AutonomousCoordinator

    coordinator = object.__new__(AutonomousCoordinator)
    coordinator.config = {}
    coordinator._register_idle_subsystems()

    tier = coordinator.registered_capabilities.get("idle_learning")

    assert tier is not None, "no idle tier drives the learning phase"
    assert hasattr(coordinator, tier["method"])


def test_learning_phase_survives_a_missing_adapter():
    from core.agents.autonomous.autonomous_coordinator import AutonomousCoordinator

    coordinator = object.__new__(AutonomousCoordinator)
    coordinator.learning = None

    asyncio.run(coordinator._learning_phase())


# ------------------------------------------------------- exploration accounting


def _bare_coordinator():
    from core.agents.autonomous.autonomous_coordinator import AutonomousCoordinator

    return object.__new__(AutonomousCoordinator)


def test_exploration_quota_starts_at_zero():
    assert _bare_coordinator()._calculate_exploration_quota() == 0.0


def test_exploration_quota_rises_with_low_trial_selections():
    """The method did not exist; its call site guarded on hasattr and passed
    0.0, so `quota_used < quota_limit` was permanently true and the 10%
    exploration cap never bound."""
    coordinator = _bare_coordinator()

    for trials in [0, 1, 2, 3, 9, 9, 9, 9, 9, 9]:
        coordinator._record_exploration_decision(SimpleNamespace(trials=trials))

    quota = coordinator._calculate_exploration_quota()

    assert quota == pytest.approx(0.4)
    assert quota >= 0.10, "cap must be able to bind"


def test_well_tried_selections_do_not_consume_quota():
    coordinator = _bare_coordinator()

    for _ in range(10):
        coordinator._record_exploration_decision(SimpleNamespace(trials=50))

    assert coordinator._calculate_exploration_quota() == 0.0


def test_exploration_history_is_bounded():
    """An unbounded window would make the quota unresponsive over time."""
    coordinator = _bare_coordinator()

    for _ in range(coordinator.EXPLORATION_WINDOW * 3):
        coordinator._record_exploration_decision(SimpleNamespace(trials=0))

    assert len(coordinator._exploration_history) == coordinator.EXPLORATION_WINDOW


def test_strategy_without_trials_is_ignored():
    coordinator = _bare_coordinator()

    coordinator._record_exploration_decision(SimpleNamespace())

    assert coordinator._calculate_exploration_quota() == 0.0


# ------------------------------------------------ the credit invariant itself


def test_outcomes_without_a_class_are_denied_credit():
    """This is the behaviour I misdiagnosed as a broken learning loop.

    track_learning_outcome refuses to credit a strategy when the outcome is
    unclassified. Recording an outcome with no outcome_class must leave the
    strategy statistics untouched -- that is the credit invariant working,
    not a failure to learn.
    """
    from core.learning.meta_learning import (
        LearningStrategyType,
        MetaLearner,
        TaskFamily,
    )

    async def scenario():
        learner = MetaLearner()
        if hasattr(learner, "initialize"):
            await learner.initialize()

        strategy = learner.strategies["classification_transfer"]
        before = strategy.trials

        for _ in range(6):
            await learner.track_learning_outcome(
                task_type=TaskFamily.CLASSIFICATION,
                strategy_type=LearningStrategyType("transfer"),
                success=True,
                performance_score=0.95,
                time_ms=50.0,
                iterations=1,
                context={},
            )
        return before, learner.strategies["classification_transfer"].trials

    before, after = asyncio.run(scenario())
    assert after == before, "unclassified outcomes must not earn credit"


def test_classified_outcomes_do_earn_credit():
    """The other half: with an outcome_class, the loop closes and selection
    sees real evidence."""
    from core.learning.meta_learning import (
        LearningStrategyType,
        MetaLearner,
        OutcomeClass,
        TaskFamily,
    )

    async def scenario():
        learner = MetaLearner()
        if hasattr(learner, "initialize"):
            await learner.initialize()

        # DELTA, not absolute. Posteriors are loaded from the store on init --
        # that persistence is the invariant this suite exists to protect -- so
        # `trials == 6` asserts the store was empty, which is only true until
        # something actually learns. Any real run through
        # learn_from_example records TRANSFER outcomes against this same
        # strategy_id, and the count was then read as a broken loop rather than
        # as evidence the loop had run. The claim under test is that a
        # classified outcome EARNS credit, which is a statement about the
        # change, exactly as the unclassified case above measures it.
        before = learner.strategies["classification_transfer"]
        prior_trials, prior_successes = before.trials, before.successes

        for _ in range(6):
            await learner.track_learning_outcome(
                task_type=TaskFamily.CLASSIFICATION,
                strategy_type=LearningStrategyType("transfer"),
                success=True,
                performance_score=0.95,
                time_ms=50.0,
                iterations=1,
                context={},
                outcome_class=OutcomeClass.SUCCESS,
            )
        return learner.strategies["classification_transfer"], prior_trials, prior_successes

    strategy, prior_trials, prior_successes = asyncio.run(scenario())

    assert strategy.trials - prior_trials == 6
    assert strategy.successes - prior_successes == 6
    assert strategy.success_rate == pytest.approx(
        strategy.successes / strategy.trials)
    assert strategy.confidence > 0.0
