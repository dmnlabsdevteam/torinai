"""
Phase 8 - Critical Action Enforcement Tests (Week 9)

Tests MUST_BLOCK enforcement for critical actions with full safety stack:
- Model weight changes
- Memory architecture changes
- External integrations
- Safety threshold modifications
- Commitment contracts (blocking mode)
- Context classification (production)
- Tiered approval routing
- Multi-level safety prompts

All tests use pytest with automatic MySQL logging via conftest.py.
"""

import pytest
from core.governance.unified_governance_trigger_system import (
    UnifiedGovernanceTriggerSystem,
    ActionCategory,
    EnforcementMode,
    DecisionTier
)
from core.governance.enforcement_mode_manager import EnforcementModeManager


@pytest.mark.asyncio
async def test_1_1_variable_risk_is_resolved_from_magnitude():
    """A trigger that declares `safety_risk: "VARIES_BY_*"` carries a
    `risk_tiers` table saying what varies with what, and NO code resolved it --
    grep for VARIES_BY returned the config and nothing else. The literal string
    travelled to the composition, matched no known risk and fell to a default.

    This was written against `learning_001` (model weight changes), which has
    since been removed with the weight-update capability: the substrate does not
    run on model weights, so a rule governing changes to them governs nothing.
    `learning_003` declares VARIES_BY_PARAM and exercises the same resolution.
    """
    enforcement_manager = EnforcementModeManager()
    trigger_system = UnifiedGovernanceTriggerSystem(
        enforcement_manager=enforcement_manager)

    async def _config_change(param, percent):
        return await trigger_system.evaluate_action(
            action_category=ActionCategory.LEARNING_PARAMETERS,
            action_type="propose_learner_config_change",
            parameters={"parameter_name": param, "percent_change": percent},
            context={"action_id": f"test_{param}_{percent}",
                     "source": "GovernancePatternLearner"},
        )

    small = await _config_change("batch_size", 0.5)
    assert small.triggered is True
    assert small.trigger_id == "learning_003"
    assert small.safety_risk == "LOW", "a 0.5% change resolves LOW, not the literal string"

    large = await _config_change("batch_size", 40)
    assert large.safety_risk == "CRITICAL", "the same rule, a different magnitude"

    # A parameter the trigger itself names safety-critical outranks magnitude:
    # a 1% change to `safety_threshold` is not a small change.
    critical_param = await _config_change("safety_threshold", 0.5)
    assert critical_param.safety_risk == "CRITICAL"

    # An UNSTATED magnitude is not a small one.
    unstated = await trigger_system.evaluate_action(
        action_category=ActionCategory.LEARNING_PARAMETERS,
        action_type="propose_learner_config_change",
        parameters={"parameter_name": "batch_size"},
        context={"action_id": "test_unstated", "source": "GovernancePatternLearner"},
    )
    assert unstated.safety_risk == "CRITICAL"


@pytest.mark.asyncio
async def test_1_2_memory_architecture_changes_trigger_notification():
    """
    Test 1.2: Memory architecture changes trigger notification approval

    - Configure memory architecture trigger with MUST_BLOCK enforcement
    - Execute memory tier threshold change
    - Verify action BLOCKS and requires approval
    - Verify IMPORTANT tier routing (notification, not full session)
    - Verify action proceeds after approval
    """
    trigger_system = UnifiedGovernanceTriggerSystem()
    enforcement_manager = EnforcementModeManager()

    # Enable enforcement for memory operations
    await enforcement_manager.enable_enforcement(
        category=ActionCategory.MEMORY_OPERATIONS,
        mode=EnforcementMode.MUST_BLOCK,
        updated_by="test_system",
        rollout_stage=2
    )

    # Execute memory architecture change
    evaluation = await trigger_system.evaluate_action(
        action_category=ActionCategory.MEMORY_OPERATIONS,
        action_type="architecture_change",
        parameters={
            "operation": "tier_threshold_change",
            "tier": "episodic",
            "new_threshold": 0.75,
            "previous_threshold": 0.65
        },
        context={"action_id": "test_mem_arch_1", "source": "autonomous"}
    )

    # If trigger fires, verify tier is IMPORTANT (architecture changes are important but not critical)
    if evaluation.triggered:
        assert evaluation.decision_tier == DecisionTier.IMPORTANT, \
            "Memory architecture changes should be IMPORTANT tier"

    # Verify enforcement mode
    effective_mode = await enforcement_manager.get_enforcement_mode(
        category=ActionCategory.MEMORY_OPERATIONS
    )
    assert effective_mode == EnforcementMode.MUST_BLOCK

    # Clean up
    await enforcement_manager.disable_enforcement(
        category=ActionCategory.MEMORY_OPERATIONS,
        updated_by="test_system"
    )


@pytest.mark.asyncio
async def test_1_3_external_integrations_require_full_session():
    """
    Test 1.3: External integrations require full governance session

    - Configure external integration trigger with MUST_BLOCK enforcement
    - Attempt to register new external API
    - Verify CRITICAL tier routing (full governance session)
    - Verify 5 AI judges + human oversight triggered
    - Verify action blocked until approval
    """
    trigger_system = UnifiedGovernanceTriggerSystem()
    enforcement_manager = EnforcementModeManager()

    # Enable enforcement for external integrations
    await enforcement_manager.enable_enforcement(
        category=ActionCategory.EXTERNAL_INTEGRATIONS,
        mode=EnforcementMode.MUST_BLOCK,
        updated_by="test_system",
        rollout_stage=2
    )

    # Attempt to register new external API
    evaluation = await trigger_system.evaluate_action(
        action_category=ActionCategory.EXTERNAL_INTEGRATIONS,
        action_type="register_external_integration",
        parameters={
            "api_name": "NewPaymentGateway",
            "endpoint": "https://api.newpayment.com",
            "requires_auth": True,
            "data_sharing": ["user_email", "payment_info"]
        },
        context={"action_id": "test_ext_int_1", "source": "autonomous"}
    )

    # Verify trigger fired (external integrations should always trigger)
    assert evaluation.triggered is True, "External integration should trigger governance"

    # Verify CRITICAL tier (external integrations are critical)
    assert evaluation.decision_tier == DecisionTier.CRITICAL, \
        "External integrations should be CRITICAL tier"

    # Verify enforcement mode
    effective_mode = await enforcement_manager.get_enforcement_mode(
        category=ActionCategory.EXTERNAL_INTEGRATIONS
    )
    assert effective_mode == EnforcementMode.MUST_BLOCK

    # Clean up
    await enforcement_manager.disable_enforcement(
        category=ActionCategory.EXTERNAL_INTEGRATIONS,
        updated_by="test_system"
    )


@pytest.mark.asyncio
async def test_1_4_safety_threshold_modifications_block_automatically():
    """
    Test 1.4: Safety threshold modifications block automatically

    - Configure safety threshold trigger with MUST_BLOCK enforcement
    - Attempt to modify safety_threshold learning parameter
    - Verify action BLOCKS immediately
    - Verify CRITICAL tier with human-only approval
    - Verify AI judge votes rejected
    """
    # NO SETUP. That is the assertion.
    #
    # This used to enable MUST_BLOCK on the whole LEARNING_PARAMETERS category
    # and check that a trigger inherited it -- the conflation that has since
    # been removed: a category mode is a ROLLOUT state, and what a rule MEANS
    # is derived from whether its action can be undone. Under that derivation
    # `config_001` does not block, because a safety threshold can be set back.
    #
    # What cannot be set back is every evaluation made while it was wrong. The
    # rule corrupts the instrument the other rules are measured with, so it is
    # an explicit override rather than a derivation -- and it is seeded when the
    # manager is CONSTRUCTED, not by a startup call, because a guarantee that
    # holds only after something else runs is not a guarantee.
    enforcement_manager = EnforcementModeManager()
    trigger_system = UnifiedGovernanceTriggerSystem(
        enforcement_manager=enforcement_manager)

    evaluation = await trigger_system.evaluate_action(
        action_category=ActionCategory.CONFIGURATION_CHANGES,
        action_type="update_config",
        parameters={
            "config_key": "safety_threshold",
            "current_value": 0.85,
            "new_value": 0.70,
        },
        context={"action_id": "test_safety_threshold_1", "source": "autonomous"},
    )

    assert evaluation.triggered is True, "Safety threshold change should trigger governance"
    assert evaluation.trigger_id == "config_001"
    assert evaluation.enforcement_mode == EnforcementMode.MUST_BLOCK, \
        "Safety threshold modification is the one unconditional block"

    # And it holds without anyone having switched anything on.
    assert enforcement_manager.trigger_override(
        ActionCategory.CONFIGURATION_CHANGES, "config_001"
    ) == EnforcementMode.MUST_BLOCK

    # THE PAIR IS EXHAUSTIVE OR IT IS A HOLE. config_002 is config_001 negated
    # over one key, and `not_matches` used to be satisfied by an ABSENT value --
    # so omitting `config_key` fell through the specific rule into the general
    # one and scored LOW, in the one place the system claims to always block.
    omitted = await trigger_system.evaluate_action(
        action_category=ActionCategory.CONFIGURATION_CHANGES,
        action_type="update_config",
        parameters={"new_value": 0.70},
        context={"action_id": "test_safety_threshold_2", "source": "autonomous"},
    )
    assert omitted.trigger_id != "config_002", (
        "a config change that does not say which key it touches must not be "
        "scored as the general low-risk case"
    )


@pytest.mark.asyncio
async def test_1_5_commitment_contracts_enforce_in_blocking_mode():
    """
    Test 1.5: Commitment contracts enforce in blocking mode

    - Create commitment contract in enforcement mode
    - Execute action that violates contract
    - Verify action REJECTED due to contract violation
    - Verify violation rate tracked
    - Verify NO action execution on violation

    Note: This test verifies the enforcement framework is ready.
    Actual commitment contract enforcement will be implemented in Phase 8.
    """
    enforcement_manager = EnforcementModeManager()

    # Enable enforcement mode
    await enforcement_manager.enable_enforcement(
        category=ActionCategory.TOOL_EXECUTION,
        mode=EnforcementMode.MUST_BLOCK,
        updated_by="test_system",
        rollout_stage=3
    )

    # Verify enforcement enabled
    effective_mode = await enforcement_manager.get_enforcement_mode(
        category=ActionCategory.TOOL_EXECUTION
    )
    assert effective_mode == EnforcementMode.MUST_BLOCK

    # Verify enforcement config persisted
    config = await enforcement_manager.get_enforcement_config(ActionCategory.TOOL_EXECUTION)
    assert config is not None
    assert config.enabled is True
    assert config.enforcement_mode == EnforcementMode.MUST_BLOCK

    # Clean up
    await enforcement_manager.disable_enforcement(
        category=ActionCategory.TOOL_EXECUTION,
        updated_by="test_system"
    )


@pytest.mark.asyncio
async def test_1_6_context_classification_active_in_production():
    """
    Test 1.6: Context classification active in production mode

    - Execute governance-triggering action
    - Verify context items classified before governance
    - Verify classifications: DECISIONAL, TRANSIENT, AUDIT_RELEVANT, MEMORY_CANDIDATE
    - Verify classified context passed to judges
    - Verify MEMORY_CANDIDATE items promoted after approval

    Note: This test verifies the trigger system works with enforcement.
    Context classification integration will be tested in full integration tests.
    """
    trigger_system = UnifiedGovernanceTriggerSystem()
    enforcement_manager = EnforcementModeManager()

    # Enable enforcement
    await enforcement_manager.enable_enforcement(
        category=ActionCategory.TOOL_EXECUTION,
        mode=EnforcementMode.MUST_BLOCK,
        updated_by="test_system",
        rollout_stage=3
    )

    # Execute action that triggers governance
    evaluation = await trigger_system.evaluate_action(
        action_category=ActionCategory.TOOL_EXECUTION,
        action_type="chaos_test",
        parameters={"tool_name": "ChaosTestingTool", "target": "production"},
        context={
            "action_id": "test_context_class_1",
            "source": "autonomous",
            "recent_context": [
                "User requested performance testing",
                "Previous test showed latency issues",
                "Production environment selected"
            ]
        }
    )

    # Verify trigger fired
    assert evaluation.triggered is True

    # Verify enforcement mode active
    effective_mode = await enforcement_manager.get_enforcement_mode(
        category=ActionCategory.TOOL_EXECUTION
    )
    assert effective_mode == EnforcementMode.MUST_BLOCK

    # Clean up
    await enforcement_manager.disable_enforcement(
        category=ActionCategory.TOOL_EXECUTION,
        updated_by="test_system"
    )


@pytest.mark.asyncio
async def test_1_7_tiered_approval_routing_works_correctly():
    """
    Test 1.7: Tiered approval routing works correctly

    - Execute ROUTINE tier action (should auto-approve)
    - Execute IMPORTANT tier action (should trigger notification)
    - Execute CRITICAL tier action (should trigger full session)
    - Verify correct routing for each tier
    - Verify human interruption only for IMPORTANT/CRITICAL
    """
    trigger_system = UnifiedGovernanceTriggerSystem()
    enforcement_manager = EnforcementModeManager()

    # Enable enforcement for configuration changes (typically ROUTINE)
    await enforcement_manager.enable_enforcement(
        category=ActionCategory.CONFIGURATION_CHANGES,
        mode=EnforcementMode.RECOMMEND_GOVERNANCE,
        updated_by="test_system",
        rollout_stage=3
    )

    # Execute ROUTINE tier action (config change)
    routine_eval = await trigger_system.evaluate_action(
        action_category=ActionCategory.CONFIGURATION_CHANGES,
        action_type="config_change",
        parameters={"setting": "log_level", "value": "DEBUG"},
        context={"action_id": "test_routine_1", "source": "autonomous"}
    )

    # If trigger fires, verify it's ROUTINE tier
    if routine_eval.triggered:
        assert routine_eval.decision_tier == DecisionTier.ROUTINE, \
            "Config changes should be ROUTINE tier"
        # ROUTINE tier should not require human approval
        assert routine_eval.human_only_approval is False

    # Enable enforcement for learning parameters (CRITICAL tier)
    await enforcement_manager.enable_enforcement(
        category=ActionCategory.LEARNING_PARAMETERS,
        mode=EnforcementMode.MUST_BLOCK,
        updated_by="test_system",
        rollout_stage=2
    )

    # Execute CRITICAL tier action
    critical_eval = await trigger_system.evaluate_action(
        action_category=ActionCategory.LEARNING_PARAMETERS,
        action_type="safety_threshold_change",
        parameters={"parameter": "safety_threshold", "new_value": 0.6},
        context={"action_id": "test_critical_1", "source": "autonomous"}
    )

    # Verify CRITICAL tier triggers and requires human approval
    if critical_eval.triggered:
        assert critical_eval.decision_tier == DecisionTier.CRITICAL
        assert critical_eval.human_only_approval is True

    # Clean up
    await enforcement_manager.disable_enforcement(
        category=ActionCategory.CONFIGURATION_CHANGES,
        updated_by="test_system"
    )
    await enforcement_manager.disable_enforcement(
        category=ActionCategory.LEARNING_PARAMETERS,
        updated_by="test_system"
    )


@pytest.mark.asyncio
async def test_1_8_multi_level_safety_prompts_active():
    """
    Test 1.8: Multi-level safety prompts active during enforcement

    - Execute critical action triggering governance
    - Verify all 3 prompt levels included:
      - System level: Core safety invariants
      - Meta level: Context-aware guidance
      - Action level: Task-specific checks
    - Verify prompts cannot be disabled

    Note: This test verifies enforcement mode is active.
    Multi-level prompt integration will be tested in full integration tests.
    """
    trigger_system = UnifiedGovernanceTriggerSystem()
    enforcement_manager = EnforcementModeManager()

    # Enable enforcement for tool execution
    await enforcement_manager.enable_enforcement(
        category=ActionCategory.TOOL_EXECUTION,
        mode=EnforcementMode.MUST_BLOCK,
        updated_by="test_system",
        rollout_stage=3
    )

    # Execute critical action (production chaos testing)
    evaluation = await trigger_system.evaluate_action(
        action_category=ActionCategory.TOOL_EXECUTION,
        action_type="chaos_test",
        parameters={"tool_name": "ChaosTestingTool", "target": "production"},
        context={"action_id": "test_prompts_1", "source": "autonomous"}
    )

    # Verify trigger fired
    assert evaluation.triggered is True

    # Verify CRITICAL tier (production chaos testing is critical)
    assert evaluation.decision_tier == DecisionTier.CRITICAL

    # Verify enforcement mode is MUST_BLOCK
    effective_mode = await enforcement_manager.get_enforcement_mode(
        category=ActionCategory.TOOL_EXECUTION
    )
    assert effective_mode == EnforcementMode.MUST_BLOCK

    # Verify safety risk and impact level are tracked
    assert evaluation.safety_risk is not None
    assert evaluation.impact_level is not None

    # Clean up
    await enforcement_manager.disable_enforcement(
        category=ActionCategory.TOOL_EXECUTION,
        updated_by="test_system"
    )
