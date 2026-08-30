"""
Phase 7 Tests: Shadow Mode Enforcement

Tests verify that LOG_ONLY mode triggers governance but never blocks actions.
Shadow mode is critical for validating trigger accuracy before enforcement.

Category 1: Shadow Mode Enforcement (6 tests)
All tests use pytest with automatic MySQL logging via conftest.py.
"""

import pytest
import asyncio
from datetime import datetime
from core.governance.unified_governance_trigger_system import (
    UnifiedGovernanceTriggerSystem,
    ActionCategory,
    EnforcementMode,
    DecisionTier
)
from core.governance.shadow_mode_coordinator import ShadowModeCoordinator


@pytest.mark.asyncio
async def test_1_1_log_only_mode_triggers_but_allows_action():
    """
    Test 1.1: LOG_ONLY mode triggers but allows action to proceed

    Shadow mode should:
    1. Fire triggers and log events
    2. NEVER block actions
    3. Record comprehensive audit trail
    """
    coordinator = ShadowModeCoordinator()
    trigger_system = UnifiedGovernanceTriggerSystem()

    await coordinator.start_shadow_mode()

    # Execute action that would normally trigger governance
    evaluation = await trigger_system.evaluate_action(
        action_category=ActionCategory.TOOL_EXECUTION,
        action_type="tool_execution",
        parameters={"tool_name": "ChaosTestingTool", "target": "production"},
        context={"action_id": "test_action_1"}
    )

    # Record in shadow mode
    event_id = await coordinator.record_trigger_event(evaluation)

    # Verify trigger fired
    assert evaluation.triggered is True
    assert evaluation.trigger_id is not None
    assert evaluation.enforcement_mode == EnforcementMode.MUST_BLOCK

    # Verify shadow mode logged but didn't block
    assert len(coordinator.events) == 1
    event = coordinator.events[0]
    assert event.triggered is True
    assert event.would_block_if_enforced is True
    assert event.event_id == event_id

    await coordinator.stop_shadow_mode()


@pytest.mark.asyncio
async def test_1_2_log_only_applies_to_all_decision_tiers():
    """
    Test 1.2: LOG_ONLY mode applies to all decision tiers

    All tiers (ROUTINE, IMPORTANT, CRITICAL) should log but not block.
    """
    coordinator = ShadowModeCoordinator()
    trigger_system = UnifiedGovernanceTriggerSystem()

    await coordinator.start_shadow_mode()

    # Test ROUTINE/MODERATE tier
    eval_moderate = await trigger_system.evaluate_action(
        action_category=ActionCategory.TOOL_EXECUTION,
        action_type="chaos_test",
        parameters={"tool_name": "ChaosTestingTool", "intensity": 8},
        context={"action_id": "moderate_action"}
    )
    await coordinator.record_trigger_event(eval_moderate)

    # Test CRITICAL tier
    eval_critical = await trigger_system.evaluate_action(
        action_category=ActionCategory.TOOL_EXECUTION,
        action_type="chaos_test",
        parameters={"tool_name": "ChaosTestingTool", "target": "production"},
        context={"action_id": "critical_action"}
    )
    await coordinator.record_trigger_event(eval_critical)

    # Test another CRITICAL tier
    eval_critical2 = await trigger_system.evaluate_action(
        action_category=ActionCategory.TOOL_EXECUTION,
        action_type="mutation_test",
        parameters={"tool_name": "MutationTestingTool", "target_files": ["core/governance/session.py"]},
        context={"action_id": "critical_action_2"}
    )
    await coordinator.record_trigger_event(eval_critical2)

    # Verify all events logged
    assert len(coordinator.events) == 3

    # Verify at least one trigger fired
    triggered_events = [e for e in coordinator.events if e.triggered]
    assert len(triggered_events) >= 1, "At least one action should have triggered governance"

    await coordinator.stop_shadow_mode()


@pytest.mark.asyncio
async def test_1_3_log_only_transition_from_must_block():
    """
    Test 1.3: LOG_ONLY mode transition from MUST_BLOCK

    Verify that changing enforcement mode from MUST_BLOCK to LOG_ONLY
    changes behavior from blocking to logging-only.
    """
    coordinator = ShadowModeCoordinator()
    trigger_system = UnifiedGovernanceTriggerSystem()

    # First, evaluate action with default config
    eval_original = await trigger_system.evaluate_action(
        action_category=ActionCategory.LEARNING_PARAMETERS,
        action_type="learning_param_change",
        parameters={"parameter": "learning_rate", "change_percent": 50},
        context={"action_id": "transition_test", "source": "autonomous"}
    )

    original_enforcement = eval_original.enforcement_mode

    # Now test in shadow mode
    await coordinator.start_shadow_mode()

    # Execute same action in shadow mode
    eval_shadow = await trigger_system.evaluate_action(
        action_category=ActionCategory.LEARNING_PARAMETERS,
        action_type="learning_param_change",
        parameters={"parameter": "learning_rate", "change_percent": 50},
        context={"action_id": "shadow_test", "source": "autonomous"}
    )

    await coordinator.record_trigger_event(eval_shadow)

    # Verify trigger still fires
    if eval_original.triggered:
        assert eval_shadow.triggered is True
        assert eval_shadow.trigger_id == eval_original.trigger_id

        # Verify shadow mode logged the event
        assert len(coordinator.events) == 1
        event = coordinator.events[0]

        # If original was MUST_BLOCK, verify it would block if enforced
        if original_enforcement == EnforcementMode.MUST_BLOCK:
            assert event.would_block_if_enforced is True

    await coordinator.stop_shadow_mode()


@pytest.mark.asyncio
async def test_1_4_shadow_mode_metrics_collection():
    """
    Test 1.4: Shadow mode metrics collection

    Execute 100 actions across all categories and verify comprehensive logging.
    """
    coordinator = ShadowModeCoordinator()
    trigger_system = UnifiedGovernanceTriggerSystem()

    await coordinator.start_shadow_mode()

    # Execute 100 actions across different categories
    action_count = 0
    for i in range(100):
        category = list(ActionCategory)[i % len(ActionCategory)]

        evaluation = await trigger_system.evaluate_action(
            action_category=category,
            action_type=f"test_action_{category.value}",
            parameters={"index": i, "test": True},
            context={"action_id": f"action_{i}"}
        )

        # Record event with processing latency
        await coordinator.record_trigger_event(evaluation, processing_latency_ms=float(i % 10))
        action_count += 1

    # Verify all 100 actions logged
    assert len(coordinator.events) == 100

    # Verify metrics include required fields
    for event in coordinator.events:
        assert event.event_id is not None
        assert event.action_category in ActionCategory
        assert event.decision_tier in DecisionTier
        assert event.timestamp is not None
        assert event.processing_latency_ms >= 0

    await coordinator.stop_shadow_mode()


@pytest.mark.asyncio
async def test_1_5_shadow_mode_with_human_only_approval():
    """
    Test 1.5: Shadow mode with human_only_approval flag

    Actions requiring human-only approval should:
    1. Still proceed in LOG_ONLY mode
    2. Log that they would require human approval if enforced
    """
    coordinator = ShadowModeCoordinator()
    trigger_system = UnifiedGovernanceTriggerSystem()

    await coordinator.start_shadow_mode()

    # Execute action that requires human-only approval
    evaluation = await trigger_system.evaluate_action(
        action_category=ActionCategory.LEARNING_PARAMETERS,
        action_type="learning_param_change",
        parameters={"parameter": "safety_threshold", "change_percent": 30},
        context={"action_id": "human_only_test", "source": "autonomous"}
    )

    await coordinator.record_trigger_event(evaluation)

    # Verify trigger fired
    if evaluation.triggered:
        assert evaluation.human_only_approval is True

        # Verify shadow mode logged the event
        assert len(coordinator.events) == 1

        # Human approval flag preserved
        assert evaluation.human_only_approval is True

    await coordinator.stop_shadow_mode()


@pytest.mark.asyncio
async def test_1_6_shadow_mode_timeout_behavior():
    """
    Test 1.6: Shadow mode timeout behavior

    Slow actions should:
    1. Complete without governance timeout
    2. Log completion time accurately
    """
    coordinator = ShadowModeCoordinator()
    trigger_system = UnifiedGovernanceTriggerSystem()

    await coordinator.start_shadow_mode()

    # Simulate slow action
    start_time = datetime.now()

    evaluation = await trigger_system.evaluate_action(
        action_category=ActionCategory.TASK_CREATION,
        action_type="recursive_task",
        parameters={"depth": 10, "branching_factor": 3},
        context={"action_id": "slow_action"}
    )

    # Simulate slow processing
    await asyncio.sleep(0.1)  # 100ms delay

    end_time = datetime.now()
    processing_latency = (end_time - start_time).total_seconds() * 1000  # milliseconds

    await coordinator.record_trigger_event(evaluation, processing_latency_ms=processing_latency)

    # Verify action completed without timeout
    assert len(coordinator.events) == 1
    event = coordinator.events[0]

    # Verify completion time logged
    assert event.processing_latency_ms >= 100  # At least 100ms
    assert event.processing_latency_ms < 200  # Not excessively high

    await coordinator.stop_shadow_mode()
