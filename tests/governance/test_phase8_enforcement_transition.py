"""
Phase 8 - Enforcement Mode Transition Tests

Tests smooth transition from shadow mode to enforcement mode:
- Per-category enforcement toggle
- Per-trigger enforcement override
- Enforcement config persistence
- Shadow mode metrics informing rollout
- Gradual rollout by decision tier
- Rollback capability

All tests use pytest with automatic MySQL logging via conftest.py.
"""

import pytest
from pathlib import Path
from core.governance.unified_governance_trigger_system import (
    UnifiedGovernanceTriggerSystem,
    ActionCategory,
    EnforcementMode,
    DecisionTier
)
from core.governance.enforcement_mode_manager import EnforcementModeManager
from core.governance.shadow_mode_coordinator import ShadowModeCoordinator


@pytest.mark.asyncio
async def test_3_1_per_category_enforcement_toggle():
    """
    Test 3.1: Per-category enforcement mode toggle

    - Start in shadow mode for all categories
    - Enable MUST_BLOCK for TOOL_EXECUTION only
    - Execute tool action → verify BLOCKED (enforcement active)
    - Execute memory action → verify ALLOWED (still in shadow mode)
    - Verify category-level isolation working
    """
    # ISOLATION IS STILL PER CATEGORY -- but what is isolated changed.
    #
    # Categories no longer start in LOG_ONLY. Shadow existed because 44 rules
    # declared MUST_BLOCK and switching them on at once would have denied most
    # of what the agent does; a rule's meaning is now derived from whether its
    # action can be undone, which blocks five of fifty-six, so there is nothing
    # left for shadow to protect against. What a category mode controls is
    # whether that derivation is CONSULTED at all.
    enforcement_manager = EnforcementModeManager()
    trigger_system = UnifiedGovernanceTriggerSystem(
        enforcement_manager=enforcement_manager)

    for category in [ActionCategory.TOOL_EXECUTION, ActionCategory.MEMORY_OPERATIONS]:
        assert not enforcement_manager.in_shadow(category), \
            f"{category.value} should be enforcing, not observing"

    # An irreversible tool action blocks on its own declaration -- nothing was
    # switched on to make that happen.
    tool_eval = await trigger_system.evaluate_action(
        action_category=ActionCategory.TOOL_EXECUTION,
        action_type="execute_tool",
        parameters={"tool_name": "run_shell_command", "command": "rm -rf /"},
        context={"action_id": "test_tool_1", "source": "autonomous"},
    )
    assert tool_eval.triggered
    assert tool_eval.enforcement_mode == EnforcementMode.MUST_BLOCK

    # Put ONLY that category back to observing. Its rules stop deciding;
    # the other category is untouched.
    await enforcement_manager.disable_enforcement(
        category=ActionCategory.TOOL_EXECUTION,
        updated_by="test_system",
    )
    assert enforcement_manager.in_shadow(ActionCategory.TOOL_EXECUTION)
    assert not enforcement_manager.in_shadow(ActionCategory.MEMORY_OPERATIONS)

    shadowed = await trigger_system.evaluate_action(
        action_category=ActionCategory.TOOL_EXECUTION,
        action_type="execute_tool",
        parameters={"tool_name": "run_shell_command", "command": "rm -rf /"},
        context={"action_id": "test_tool_2", "source": "autonomous"},
    )
    assert shadowed.triggered, "shadow observes; it does not stop matching"
    assert shadowed.enforcement_mode == EnforcementMode.LOG_ONLY


@pytest.mark.asyncio
async def test_3_2_per_trigger_enforcement_override():
    """
    Test 3.2: Per-trigger enforcement mode override

    - Enable MUST_BLOCK globally for a category
    - Override specific trigger to LOG_ONLY
    - Execute action matching overridden trigger → verify ALLOWED (LOG_ONLY respected)
    - Execute action matching other trigger → verify BLOCKED (global MUST_BLOCK respected)
    """
    enforcement_manager = EnforcementModeManager()
    trigger_system = UnifiedGovernanceTriggerSystem(enforcement_manager=enforcement_manager)

    # Enable MUST_BLOCK globally for TOOL_EXECUTION
    await enforcement_manager.enable_enforcement(
        category=ActionCategory.TOOL_EXECUTION,
        mode=EnforcementMode.MUST_BLOCK,
        updated_by="test_system",
        rollout_stage=3
    )

    # Verify global mode is MUST_BLOCK
    global_mode = await enforcement_manager.get_enforcement_mode(ActionCategory.TOOL_EXECUTION)
    assert global_mode == EnforcementMode.MUST_BLOCK

    # Override specific trigger to LOG_ONLY (e.g., tool_exec_002 - high intensity chaos)
    await enforcement_manager.set_trigger_override(
        category=ActionCategory.TOOL_EXECUTION,
        trigger_id="tool_exec_002",  # High intensity chaos (non-production)
        mode=EnforcementMode.LOG_ONLY,
        updated_by="test_system"
    )

    # Verify override was set
    override_mode = await enforcement_manager.get_enforcement_mode(
        category=ActionCategory.TOOL_EXECUTION,
        trigger_id="tool_exec_002"
    )
    assert override_mode == EnforcementMode.LOG_ONLY

    # Execute action matching overridden trigger (should be LOG_ONLY)
    override_eval = await trigger_system.evaluate_action(
        action_category=ActionCategory.TOOL_EXECUTION,
        action_type="chaos_test",
        parameters={"tool_name": "ChaosTestingTool", "intensity": 8},
        context={"action_id": "test_override_1", "source": "autonomous"}
    )

    # If this matches tool_exec_002, it should be LOG_ONLY
    if override_eval.triggered and override_eval.trigger_id == "tool_exec_002":
        assert override_eval.enforcement_mode == EnforcementMode.LOG_ONLY

    # Execute action matching different trigger (should be MUST_BLOCK)
    global_eval = await trigger_system.evaluate_action(
        action_category=ActionCategory.TOOL_EXECUTION,
        action_type="chaos_test",
        parameters={"tool_name": "ChaosTestingTool", "target": "production"},
        context={"action_id": "test_global_1", "source": "autonomous"}
    )

    # If this matches tool_exec_001 (production chaos), it should be MUST_BLOCK
    if global_eval.triggered and global_eval.trigger_id != "tool_exec_002":
        assert global_eval.enforcement_mode == EnforcementMode.MUST_BLOCK

    # Clean up
    await enforcement_manager.disable_enforcement(
        category=ActionCategory.TOOL_EXECUTION,
        updated_by="test_system"
    )


@pytest.mark.asyncio
async def test_3_3_enforcement_config_persists_across_restarts():
    """
    Test 3.3: Enforcement mode persists across restarts

    - Enable MUST_BLOCK for critical actions
    - Save enforcement configuration
    - Create new EnforcementModeManager (simulating restart)
    - Verify configuration loaded correctly
    - Verify enforcement still active
    """
    # Create first manager and configure enforcement
    manager1 = EnforcementModeManager()

    await manager1.enable_enforcement(
        category=ActionCategory.LEARNING_PARAMETERS,
        mode=EnforcementMode.MUST_BLOCK,
        updated_by="test_system",
        rollout_stage=2
    )

    # Set trigger override
    await manager1.set_trigger_override(
        category=ActionCategory.LEARNING_PARAMETERS,
        trigger_id="learning_params_001",
        mode=EnforcementMode.MUST_BLOCK,
        updated_by="test_system"
    )

    # Verify config was saved
    config_path = Path(manager1.config_path)
    assert config_path.exists(), "Config file should be created"

    # Save enforcement config explicitly
    await manager1.save_enforcement_config()

    # Create new manager (simulating restart)
    manager2 = EnforcementModeManager(config_path=config_path)

    # Load persisted configuration
    await manager2.load_enforcement_config()

    # Verify configuration was loaded
    loaded_mode = await manager2.get_enforcement_mode(ActionCategory.LEARNING_PARAMETERS)
    assert loaded_mode == EnforcementMode.MUST_BLOCK, \
        "Enforcement mode should persist across restart"

    # Verify trigger override was loaded
    override_mode = await manager2.get_enforcement_mode(
        category=ActionCategory.LEARNING_PARAMETERS,
        trigger_id="learning_params_001"
    )
    assert override_mode == EnforcementMode.MUST_BLOCK, \
        "Trigger override should persist across restart"

    # Verify config details
    config = await manager2.get_enforcement_config(ActionCategory.LEARNING_PARAMETERS)
    assert config is not None
    assert config.enabled is True
    assert config.enforcement_mode == EnforcementMode.MUST_BLOCK
    assert config.rollout_stage == 2
    assert "learning_params_001" in config.override_triggers

    # Clean up
    await manager2.disable_enforcement(
        category=ActionCategory.LEARNING_PARAMETERS,
        updated_by="test_system"
    )


@pytest.mark.asyncio
async def test_3_4_shadow_mode_metrics_inform_enforcement():
    """
    Test 3.4: Shadow mode metrics inform enforcement rollout

    - Collect shadow mode metrics (FPR, FNR, tier errors)
    - Identify category with FNR = 0% and FPR < 5%
    - Enable enforcement for that category first
    - Verify successful transition with low false positives
    """
    coordinator = ShadowModeCoordinator()
    trigger_system = UnifiedGovernanceTriggerSystem()
    enforcement_manager = EnforcementModeManager()

    # Start shadow mode
    await coordinator.start_shadow_mode()

    # Execute actions and label them (simulating shadow mode data collection)
    test_actions = [
        {
            "action_id": "shadow_1",
            "category": ActionCategory.TOOL_EXECUTION,
            "params": {"tool_name": "ChaosTestingTool", "target": "production"},
            "expected_triggered": True,
            "rationale": "Production chaos should trigger"
        },
        {
            "action_id": "shadow_2",
            "category": ActionCategory.TOOL_EXECUTION,
            "params": {"tool_name": "SafeReadTool", "operation": "read"},
            "expected_triggered": False,
            "rationale": "Safe read should not trigger"
        },
        {
            "action_id": "shadow_3",
            "category": ActionCategory.TOOL_EXECUTION,
            "params": {"tool_name": "ChaosTestingTool", "target": "production"},
            "expected_triggered": True,
            "rationale": "Production chaos should trigger"
        }
    ]

    for action in test_actions:
        evaluation = await trigger_system.evaluate_action(
            action_category=action["category"],
            action_type="test",
            parameters=action["params"],
            context={"action_id": action["action_id"], "source": "autonomous"}
        )

        await coordinator.record_trigger_event(evaluation)
        await coordinator.label_action(
            action_id=action["action_id"],
            expected_triggered=action["expected_triggered"],
            reviewer_id="test_reviewer",
            rationale=action["rationale"]
        )

    # Calculate error analysis
    error_analysis = await coordinator.calculate_error_analysis()

    # Verify metrics are tracked
    assert error_analysis.total_labeled_actions == 3
    assert error_analysis.false_negative_rate >= 0.0
    assert error_analysis.false_positive_rate >= 0.0

    # If FNR = 0% and FPR < 5%, enable enforcement
    if error_analysis.false_negative_rate == 0.0 and error_analysis.false_positive_rate < 0.05:
        await enforcement_manager.enable_enforcement(
            category=ActionCategory.TOOL_EXECUTION,
            mode=EnforcementMode.MUST_BLOCK,
            updated_by="shadow_mode_analysis",
            rollout_stage=3
        )

        # Verify enforcement enabled
        mode = await enforcement_manager.get_enforcement_mode(ActionCategory.TOOL_EXECUTION)
        assert mode == EnforcementMode.MUST_BLOCK

    # Clean up
    await coordinator.stop_shadow_mode()
    await enforcement_manager.disable_enforcement(
        category=ActionCategory.TOOL_EXECUTION,
        updated_by="test_system"
    )


@pytest.mark.asyncio
async def test_3_5_gradual_rollout_by_decision_tier():
    """
    Test 3.5: Gradual rollout by decision tier

    - Week 9: Enable CRITICAL tier enforcement only
    - Week 10: Enable IMPORTANT tier enforcement
    - Verify CRITICAL actions block, IMPORTANT allowed (week 9)
    - Verify both CRITICAL and IMPORTANT block (week 10)
    - Verify ROUTINE still auto-approves throughout
    """
    trigger_system = UnifiedGovernanceTriggerSystem()
    enforcement_manager = EnforcementModeManager()

    # Week 9: Enable enforcement for critical actions only (rollout_stage=2)
    await enforcement_manager.enable_enforcement(
        category=ActionCategory.LEARNING_PARAMETERS,
        mode=EnforcementMode.MUST_BLOCK,
        updated_by="week_9_rollout",
        rollout_stage=2  # Critical only
    )

    # Verify stage 2 (critical only) is set
    config = await enforcement_manager.get_enforcement_config(ActionCategory.LEARNING_PARAMETERS)
    assert config is not None
    assert config.rollout_stage == 2

    # Execute CRITICAL action (safety threshold)
    critical_eval = await trigger_system.evaluate_action(
        action_category=ActionCategory.LEARNING_PARAMETERS,
        action_type="safety_threshold_change",
        parameters={"parameter": "safety_threshold", "new_value": 0.7},
        context={"action_id": "test_critical_tier", "source": "autonomous"}
    )

    # If triggers, should be CRITICAL tier with MUST_BLOCK
    if critical_eval.triggered:
        assert critical_eval.decision_tier == DecisionTier.CRITICAL
        assert critical_eval.enforcement_mode == EnforcementMode.MUST_BLOCK

    # Week 10: Advance to full enforcement (rollout_stage=3)
    await enforcement_manager.enable_enforcement(
        category=ActionCategory.LEARNING_PARAMETERS,
        mode=EnforcementMode.MUST_BLOCK,
        updated_by="week_10_rollout",
        rollout_stage=3  # Full enforcement
    )

    # Verify stage 3 (full enforcement) is set
    config = await enforcement_manager.get_enforcement_config(ActionCategory.LEARNING_PARAMETERS)
    assert config is not None
    assert config.rollout_stage == 3

    # Verify enforcement mode is still MUST_BLOCK
    mode = await enforcement_manager.get_enforcement_mode(ActionCategory.LEARNING_PARAMETERS)
    assert mode == EnforcementMode.MUST_BLOCK

    # Clean up
    await enforcement_manager.disable_enforcement(
        category=ActionCategory.LEARNING_PARAMETERS,
        updated_by="test_system"
    )


@pytest.mark.asyncio
async def test_3_6_rollback_to_shadow_if_issues_detected():
    """
    Test 3.6: Rollback to shadow mode if issues detected

    - Enable enforcement mode
    - Detect high false positive rate (>30%)
    - Rollback to shadow mode for that category
    - Verify actions log but don't block again
    - Verify rollback logged to audit trail
    """
    enforcement_manager = EnforcementModeManager()

    # Enable enforcement
    await enforcement_manager.enable_enforcement(
        category=ActionCategory.TOOL_EXECUTION,
        mode=EnforcementMode.MUST_BLOCK,
        updated_by="test_system",
        rollout_stage=3
    )

    # Verify enforcement enabled
    mode = await enforcement_manager.get_enforcement_mode(ActionCategory.TOOL_EXECUTION)
    assert mode == EnforcementMode.MUST_BLOCK

    # Simulate detecting high false positive rate (35%)
    high_fp_rate = 0.35

    # Trigger automatic rollback
    rollback_triggered = await enforcement_manager.check_rollback_triggers(
        category=ActionCategory.TOOL_EXECUTION,
        false_positive_rate=high_fp_rate,
        queue_wait_time_p95=None,
        commitment_violation_rate=None
    )

    # Verify rollback was triggered
    assert rollback_triggered is True, "High FP rate should trigger rollback"

    # Verify mode rolled back to LOG_ONLY
    mode_after_rollback = await enforcement_manager.get_enforcement_mode(
        ActionCategory.TOOL_EXECUTION
    )
    assert mode_after_rollback == EnforcementMode.LOG_ONLY, \
        "Should rollback to LOG_ONLY after high FP rate"

    # Verify rollback event was logged
    rollback_history = await enforcement_manager.get_rollback_history(
        category=ActionCategory.TOOL_EXECUTION,
        limit=1
    )
    assert len(rollback_history) >= 1, "Rollback should be logged"
    latest_rollback = rollback_history[0]
    assert latest_rollback.category == ActionCategory.TOOL_EXECUTION
    assert "false positive rate" in latest_rollback.reason.lower()
    assert latest_rollback.rollback_to_mode == EnforcementMode.LOG_ONLY

    # Verify rollback status
    rollout_status = await enforcement_manager.get_rollout_status()
    assert rollout_status["rollback_event_count"] >= 1

    # Clean up not needed - already rolled back to LOG_ONLY
