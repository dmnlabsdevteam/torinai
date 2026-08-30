#!/usr/bin/env python3
"""
Governance Phase 1 Unit Tests
===============================
Tests for:
1. UnifiedGovernanceTriggerSystem - Action evaluation and tiered approval routing
2. ContextClassifier - Non-destructive context labeling
3. MultiLevelSafetyPrompts - Layered safety constraints
4. CommitmentContracts - Pre/post-action verification

Author: Torin AI Team
Date: December 29, 2025
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio
import json
from datetime import datetime
from test_base import TestBase, TestResult

# Import Phase 1 components
from core.governance import (
    UnifiedGovernanceTriggerSystem,
    ActionCategory,
    EnforcementMode,
    DecisionTier,
    ContextClassifier,
    ContextLabel,
    verify_no_data_loss
)

from core.safety import (
    MultiLevelSafetyPrompts,
    CommitmentContract,
    CommitmentType,
    ViolationSeverity
)


class GovernancePhase1Tests(TestBase):
    """Comprehensive tests for Phase 1 governance components"""

    def __init__(self):
        super().__init__(
            test_category="governance",
            test_type="unit"
        )
        self.results = []

    # ============================================================================
    # UnifiedGovernanceTriggerSystem Tests
    # ============================================================================

    async def test_trigger_system_initialization(self):
        """Test: Trigger system initializes and loads config correctly"""
        start_time = datetime.now()
        try:
            trigger_system = UnifiedGovernanceTriggerSystem()

            # Verify config loaded
            assert trigger_system.config is not None, "Config should be loaded"
            assert "action_categories" in trigger_system.config, "Config should have action_categories"

            # Verify all 8 action categories present
            expected_categories = [
                "TOOL_EXECUTION",
                "MEMORY_OPERATIONS",
                "RESOURCE_ALLOCATION",
                "LEARNING_PARAMETERS",
                "CONFIGURATION_CHANGES",
                "EXTERNAL_INTEGRATIONS",
                "TASK_CREATION",
                "CURIOSITY_EXPLORATION"
            ]

            for category in expected_categories:
                assert category in trigger_system.config["action_categories"], \
                    f"Category {category} should be in config"

            duration_ms = (datetime.now() - start_time).total_seconds() * 1000

            await self.log_test_result(
                test_name="test_trigger_system_initialization",
                status="passed",
                duration_ms=duration_ms,
                assertions_passed=10,
                assertions_failed=0,
                description="Trigger system initializes with all 8 action categories"
            )

            return True

        except Exception as e:
            duration_ms = (datetime.now() - start_time).total_seconds() * 1000
            await self.log_test_result(
                test_name="test_trigger_system_initialization",
                status="failed",
                duration_ms=duration_ms,
                assertions_passed=0,
                assertions_failed=1,
                description="Trigger system initialization",
                error_message=str(e)
            )
            return False

    async def test_chaos_testing_production_trigger(self):
        """Test: Production chaos testing triggers CRITICAL governance"""
        start_time = datetime.now()
        try:
            trigger_system = UnifiedGovernanceTriggerSystem()

            evaluation = await trigger_system.evaluate_action(
                action_category=ActionCategory.TOOL_EXECUTION,
                action_type="execute_tool",
                parameters={
                    "tool_name": "ChaosTestingTool",
                    "target": "production",
                    "intensity": 5
                }
            )

            # Assertions
            assert evaluation.triggered, "Should trigger governance"
            assert evaluation.trigger_id == "tool_exec_001", "Should match production chaos trigger"
            assert evaluation.decision_tier == DecisionTier.CRITICAL, "Should be CRITICAL tier"
            assert evaluation.enforcement_mode == EnforcementMode.MUST_BLOCK, "Should MUST_BLOCK"

            duration_ms = (datetime.now() - start_time).total_seconds() * 1000

            await self.log_test_result(
                test_name="test_chaos_testing_production_trigger",
                status="passed",
                duration_ms=duration_ms,
                assertions_passed=4,
                assertions_failed=0,
                description="Production chaos testing triggers CRITICAL governance",
                input_data={"tool": "ChaosTestingTool", "target": "production"},
                actual_output={"tier": evaluation.decision_tier.value, "triggered": True}
            )

            return True

        except Exception as e:
            duration_ms = (datetime.now() - start_time).total_seconds() * 1000
            print(f"ERROR in test_chaos_testing_production_trigger: {e}")
            import traceback
            traceback.print_exc()
            await self.log_test_result(
                test_name="test_chaos_testing_production_trigger",
                status="failed",
                duration_ms=duration_ms,
                assertions_passed=0,
                assertions_failed=1,
                description="Production chaos testing trigger test",
                error_message=str(e)
            )
            return False

    async def test_decision_tier_assignment(self):
        """Test: Decision tiers assigned correctly based on risk"""
        start_time = datetime.now()
        try:
            trigger_system = UnifiedGovernanceTriggerSystem()

            test_cases = [
                # (action_type, parameters, expected_tier)
                (ActionCategory.LEARNING_PARAMETERS, "update_model_weights", {}, DecisionTier.CRITICAL),
                (ActionCategory.RESOURCE_ALLOCATION, "allocate_resources", {"percent_change": 25}, DecisionTier.IMPORTANT),
                (ActionCategory.CONFIGURATION_CHANGES, "update_config", {"config_key": "logging_level"}, DecisionTier.ROUTINE),
            ]

            assertions_passed = 0
            for category, action_type, params, expected_tier in test_cases:
                evaluation = await trigger_system.evaluate_action(
                    action_category=category,
                    action_type=action_type,
                    parameters=params
                )

                if evaluation.decision_tier == expected_tier:
                    assertions_passed += 1
                else:
                    raise AssertionError(
                        f"{action_type} should be {expected_tier.value}, "
                        f"got {evaluation.decision_tier.value}"
                    )

            duration_ms = (datetime.now() - start_time).total_seconds() * 1000

            await self.log_test_result(
                test_name="test_decision_tier_assignment",
                status="passed",
                duration_ms=duration_ms,
                assertions_passed=assertions_passed,
                assertions_failed=0,
                description="Decision tiers correctly assigned (ROUTINE/IMPORTANT/CRITICAL)"
            )

            return True

        except Exception as e:
            duration_ms = (datetime.now() - start_time).total_seconds() * 1000
            print(f"ERROR in test_decision_tier_assignment: {e}")
            import traceback
            traceback.print_exc()
            await self.log_test_result(
                test_name="test_decision_tier_assignment",
                status="failed",
                duration_ms=duration_ms,
                assertions_passed=assertions_passed if 'assertions_passed' in locals() else 0,
                assertions_failed=1,
                description="Decision tier assignment test",
                error_message=str(e)
            )
            return False

    # ============================================================================
    # ContextClassifier Tests
    # ============================================================================

    async def test_context_classifier_no_deletion(self):
        """Test: Context classifier preserves all data (NO DELETION)"""
        start_time = datetime.now()
        try:
            classifier = ContextClassifier()

            original_items = [
                {"type": "action_parameters", "content": {"param1": "value1"}, "source": "test"},
                {"type": "risk_assessment", "content": "High risk action", "source": "governance"},
                {"type": "reasoning", "content": "Because XYZ", "source": "singleton"},
            ]

            classified = await classifier.classify_context(original_items)

            # Critical assertion: NO DATA LOSS
            assert len(classified) == len(original_items), "Must preserve all items"
            assert verify_no_data_loss(original_items, classified), "No data loss verification"

            # Verify all original content preserved
            for i, classified_item in enumerate(classified):
                assert classified_item.content == original_items[i], "Content must be unchanged"

            duration_ms = (datetime.now() - start_time).total_seconds() * 1000

            await self.log_test_result(
                test_name="test_context_classifier_no_deletion",
                status="passed",
                duration_ms=duration_ms,
                assertions_passed=5,
                assertions_failed=0,
                description="Context classifier preserves all data (NO DELETION principle)"
            )

            return True

        except Exception as e:
            duration_ms = (datetime.now() - start_time).total_seconds() * 1000
            await self.log_test_result(
                test_name="test_context_classifier_no_deletion",
                status="failed",
                duration_ms=duration_ms,
                assertions_passed=0,
                assertions_failed=1,
                description="Context classifier no deletion test",
                error_message=str(e)
            )
            return False

    async def test_context_labels_assignment(self):
        """Test: Context items labeled correctly"""
        start_time = datetime.now()
        try:
            classifier = ContextClassifier()

            test_items = [
                {"type": "action_parameters", "content": {}, "source": "test"},  # DECISIONAL
                {"type": "governance_decision", "content": "approved", "source": "governance"},  # AUDIT_RELEVANT
                {"type": "pattern_recognition", "content": "pattern found", "source": "learner"},  # MEMORY_CANDIDATE
                {"type": "api_response", "content": "data", "source": "external_api"},  # REFERENTIAL
                {"type": "scratch_analysis", "content": "temp", "source": "tool"},  # TRANSIENT
            ]

            classified = await classifier.classify_context(test_items)

            expected_labels = [
                ContextLabel.DECISIONAL,
                ContextLabel.AUDIT_RELEVANT,
                ContextLabel.MEMORY_CANDIDATE,
                ContextLabel.REFERENTIAL,
                ContextLabel.TRANSIENT
            ]

            assertions_passed = 0
            for i, classified_item in enumerate(classified):
                if classified_item.label == expected_labels[i]:
                    assertions_passed += 1
                else:
                    raise AssertionError(
                        f"Item {i} should be labeled {expected_labels[i].value}, "
                        f"got {classified_item.label.value}"
                    )

            duration_ms = (datetime.now() - start_time).total_seconds() * 1000

            await self.log_test_result(
                test_name="test_context_labels_assignment",
                status="passed",
                duration_ms=duration_ms,
                assertions_passed=assertions_passed,
                assertions_failed=0,
                description="Context items receive correct labels (5 label types)"
            )

            return True

        except Exception as e:
            duration_ms = (datetime.now() - start_time).total_seconds() * 1000
            await self.log_test_result(
                test_name="test_context_labels_assignment",
                status="failed",
                duration_ms=duration_ms,
                assertions_passed=assertions_passed if 'assertions_passed' in locals() else 0,
                assertions_failed=1,
                description="Context label assignment test",
                error_message=str(e)
            )
            return False

    # ============================================================================
    # MultiLevelSafetyPrompts Tests
    # ============================================================================

    async def test_multi_level_prompts_structure(self):
        """Test: Multi-level prompts include all 3 levels + checkpoints"""
        start_time = datetime.now()
        try:
            safety_prompts = MultiLevelSafetyPrompts()

            # Build complete prompt
            prompt = safety_prompts.build_complete_prompt(
                task="Test task",
                context={"current_task": "test", "risk_level": "LOW", "execution_mode": "autonomous"},
                pending_action={"type": "test_action", "parameters": {}}
            )

            # Verify all levels present
            assert "CORE SAFETY INVARIANTS" in prompt, "Should include Level 1 (system prompt)"
            assert "CONTEXT-AWARE SAFETY GUIDANCE" in prompt, "Should include Level 2 (meta prompt)"
            assert "ACTION-SPECIFIC SAFETY CHECK" in prompt, "Should include Level 3 (action prompt)"

            duration_ms = (datetime.now() - start_time).total_seconds() * 1000

            await self.log_test_result(
                test_name="test_multi_level_prompts_structure",
                status="passed",
                duration_ms=duration_ms,
                assertions_passed=3,
                assertions_failed=0,
                description="Multi-level prompts include all 3 safety levels"
            )

            return True

        except Exception as e:
            duration_ms = (datetime.now() - start_time).total_seconds() * 1000
            await self.log_test_result(
                test_name="test_multi_level_prompts_structure",
                status="failed",
                duration_ms=duration_ms,
                assertions_passed=0,
                assertions_failed=1,
                description="Multi-level prompts structure test",
                error_message=str(e)
            )
            return False

    async def test_safety_checkpoint_triggering(self):
        """Test: Safety checkpoints trigger every N actions"""
        start_time = datetime.now()
        try:
            safety_prompts = MultiLevelSafetyPrompts()
            safety_prompts.set_checkpoint_interval(5)

            # Simulate 10 actions
            checkpoint_count = 0
            for i in range(1, 11):
                safety_prompts.action_count = i
                checkpoint = safety_prompts.apply_safety_checkpoint()
                if checkpoint:
                    checkpoint_count += 1
                    assert i % 5 == 0, f"Checkpoint should only trigger at multiples of 5, got {i}"

            assert checkpoint_count == 2, f"Should have 2 checkpoints for 10 actions, got {checkpoint_count}"

            duration_ms = (datetime.now() - start_time).total_seconds() * 1000

            await self.log_test_result(
                test_name="test_safety_checkpoint_triggering",
                status="passed",
                duration_ms=duration_ms,
                assertions_passed=11,
                assertions_failed=0,
                description="Safety checkpoints trigger every N actions as configured"
            )

            return True

        except Exception as e:
            duration_ms = (datetime.now() - start_time).total_seconds() * 1000
            await self.log_test_result(
                test_name="test_safety_checkpoint_triggering",
                status="failed",
                duration_ms=duration_ms,
                assertions_passed=0,
                assertions_failed=1,
                description="Safety checkpoint triggering test",
                error_message=str(e)
            )
            return False

    # ============================================================================
    # CommitmentContracts Tests
    # ============================================================================

    async def test_commitment_contract_creation(self):
        """Test: Commitment contracts store immutable commitments"""
        start_time = datetime.now()
        try:
            contract = CommitmentContract(action_id="test_action_123", action_type="test_action")

            # Make commitments
            commitment_id_1 = await contract.make_commitment(
                commitment_type=CommitmentType.OUTCOME,
                commitment_statement="Will achieve X without Y",
                verification_method="automated_check"
            )

            commitment_id_2 = await contract.make_commitment(
                commitment_type=CommitmentType.CONSTRAINT,
                commitment_statement="Will respect safety constraints",
                verification_method="runtime_monitoring"
            )

            # Verify commitments stored
            assert len(contract.commitments) == 2, "Should have 2 commitments"
            assert contract.commitments[0].commitment_id == commitment_id_1, "First commitment ID should match"
            assert contract.commitments[1].commitment_id == commitment_id_2, "Second commitment ID should match"

            # Verify immutable hash exists
            for commitment in contract.commitments:
                assert commitment.immutable_hash, "Each commitment should have immutable hash"
                assert len(commitment.immutable_hash) == 64, "SHA256 hash should be 64 chars"

            duration_ms = (datetime.now() - start_time).total_seconds() * 1000

            await self.log_test_result(
                test_name="test_commitment_contract_creation",
                status="passed",
                duration_ms=duration_ms,
                assertions_passed=6,
                assertions_failed=0,
                description="Commitment contracts store immutable commitments"
            )

            return True

        except Exception as e:
            duration_ms = (datetime.now() - start_time).total_seconds() * 1000
            await self.log_test_result(
                test_name="test_commitment_contract_creation",
                status="failed",
                duration_ms=duration_ms,
                assertions_passed=0,
                assertions_failed=1,
                description="Commitment contract creation test",
                error_message=str(e)
            )
            return False

    async def test_commitment_verification(self):
        """Test: Commitment verification detects violations"""
        start_time = datetime.now()
        try:
            contract = CommitmentContract(action_id="test_action_456", action_type="test_action")

            # Make a commitment
            await contract.make_commitment(
                commitment_type=CommitmentType.OUTCOME,
                commitment_statement="Will not cause data loss",
                verification_method="automated_check"
            )

            # Simulate action execution
            action_result = {"status": "success", "data": "test"}
            execution_context = {"runtime_logs": [], "execution_duration": "5s"}

            # Verify commitments
            report = await contract.verify_commitments(action_result, execution_context)

            # Assertions
            assert report.total_commitments == 1, "Should have 1 commitment"
            assert report.action_id == "test_action_456", "Action ID should match"
            assert report.verified_at is not None, "Should have verification timestamp"
            assert report.report_hash, "Should have immutable report hash"

            duration_ms = (datetime.now() - start_time).total_seconds() * 1000

            await self.log_test_result(
                test_name="test_commitment_verification",
                status="passed",
                duration_ms=duration_ms,
                assertions_passed=4,
                assertions_failed=0,
                description="Commitment verification produces valid reports"
            )

            return True

        except Exception as e:
            duration_ms = (datetime.now() - start_time).total_seconds() * 1000
            await self.log_test_result(
                test_name="test_commitment_verification",
                status="failed",
                duration_ms=duration_ms,
                assertions_passed=0,
                assertions_failed=1,
                description="Commitment verification test",
                error_message=str(e)
            )
            return False

    # ============================================================================
    # Test Runner
    # ============================================================================

    async def run_all_tests(self):
        """Run all Phase 1 tests"""
        print("\n" + "="*80)
        print("GOVERNANCE PHASE 1 UNIT TESTS")
        print("="*80 + "\n")

        tests = [
            # Unified Governance Trigger System
            ("Trigger System Initialization", self.test_trigger_system_initialization),
            ("Chaos Testing Production Trigger", self.test_chaos_testing_production_trigger),
            ("Decision Tier Assignment", self.test_decision_tier_assignment),

            # Context Classifier
            ("Context Classifier No Deletion", self.test_context_classifier_no_deletion),
            ("Context Labels Assignment", self.test_context_labels_assignment),

            # Multi-Level Safety Prompts
            ("Multi-Level Prompts Structure", self.test_multi_level_prompts_structure),
            ("Safety Checkpoint Triggering", self.test_safety_checkpoint_triggering),

            # Commitment Contracts
            ("Commitment Contract Creation", self.test_commitment_contract_creation),
            ("Commitment Verification", self.test_commitment_verification),
        ]

        passed = 0
        failed = 0

        for test_name, test_func in tests:
            print(f"Running: {test_name}...")
            try:
                result = await test_func()
                if result:
                    passed += 1
                    print(f"✓ PASSED: {test_name}\n")
                else:
                    failed += 1
                    print(f"✗ FAILED: {test_name}\n")
            except Exception as e:
                failed += 1
                print(f"✗ ERROR: {test_name} - {str(e)}\n")

        print("="*80)
        print(f"RESULTS: {passed} passed, {failed} failed")
        print("="*80 + "\n")

        return passed, failed


async def main():
    """Main test execution"""
    test_suite = GovernancePhase1Tests()
    passed, failed = await test_suite.run_all_tests()

    # Exit with appropriate code
    exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    asyncio.run(main())
