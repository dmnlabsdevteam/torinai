#!/usr/bin/env python3
"""
Phase 6: Safety Systems Tests
Using TestBase for MySQL logging

Tests multi-level safety prompt system:
- System-level prompts (constitutional principles)
- Meta-level prompts (context-aware)
- Action-level prompts (task-specific)
- Complete prompt generation
- Safety validation
"""

import pytest
import asyncio
import sys
from pathlib import Path

# Add project root and tests directory to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "tests"))

from test_base import TestBase
from core.safety.multi_level_prompts import (
    MultiLevelSafetyPrompts,
    SafetyPromptIntegration,
    SafetyLevel,
    verify_safety_prompt_compliance,
    validate_prompt_safety
)


class TestPhase6SafetySystems(TestBase):
    """Phase 6: Safety Systems - MySQL Logged Tests"""

    def __init__(self):
        super().__init__(
            test_category="governance_phase6_safety",
            test_type="integration"
        )
        self.prompts = None
        self.integration = None

    @pytest.mark.asyncio
    async def test_1_system_level_prompt_active(self):
        """System-level safety prompts active"""
        self.prompts = MultiLevelSafetyPrompts()

        system_prompt = self.prompts.get_system_prompt()

        assert system_prompt is not None, "System prompt should not be None"
        assert "CONSTITUTIONAL" in system_prompt, "Should contain constitutional principles"
        assert "SAFETY" in system_prompt, "Should contain safety keywords"
        assert "Transparency" in system_prompt, "Should include transparency principle"
        assert "Reversibility" in system_prompt, "Should include reversibility principle"
        assert "Human oversight" in system_prompt, "Should include human oversight"

    @pytest.mark.asyncio
    async def test_2_meta_level_prompt_autonomous_mode(self):
        """Meta-level prompts for autonomous mode"""
        self.prompts = MultiLevelSafetyPrompts()

        context = {
            "execution_mode": "autonomous",
            "risk_level": "HIGH",
            "task_type": "system_modification",
            "safety_constraints": ["no_unauthorized_access", "governance_required"]
        }

        meta_prompt = self.prompts.build_meta_level_prompt(context)

        assert "AUTONOMOUS MODE" in meta_prompt, "Should indicate autonomous mode"
        assert "HIGH" in meta_prompt, "Should include risk level"
        assert "Escalate" in meta_prompt or "escalate" in meta_prompt, "Should mention escalation"
        assert "governance approval" in meta_prompt or "approval" in meta_prompt, "Should mention governance"

    @pytest.mark.asyncio
    async def test_3_meta_level_prompt_supervised_mode(self):
        """Meta-level prompts for supervised mode"""
        self.prompts = MultiLevelSafetyPrompts()

        context = {
            "execution_mode": "supervised",
            "risk_level": "MODERATE",
            "task_type": "analysis",
            "safety_constraints": []
        }

        meta_prompt = self.prompts.build_meta_level_prompt(context)

        assert "SUPERVISED MODE" in meta_prompt, "Should indicate supervised mode"
        assert "MODERATE" in meta_prompt, "Should include risk level"
        assert "Human oversight" in meta_prompt or "oversight" in meta_prompt, "Should mention oversight"

    @pytest.mark.asyncio
    async def test_4_action_level_prompt_with_checks(self):
        """Action-level prompts with safety checks"""
        self.prompts = MultiLevelSafetyPrompts()

        action_type = "update_model_weights"
        parameters = {"layer": "layer_5", "delta": 0.05}
        safety_checks = [
            "Validate weight delta magnitude",
            "Check governance approval",
            "Verify rollback plan exists"
        ]

        action_prompt = self.prompts.build_action_level_prompt(
            action_type=action_type,
            parameters=parameters,
            safety_checks=safety_checks
        )

        assert action_type in action_prompt, "Should include action type"
        assert "Validate weight delta magnitude" in action_prompt, "Should include first check"
        assert "Check governance approval" in action_prompt, "Should include second check"
        assert "Verify rollback plan exists" in action_prompt, "Should include third check"
        assert "Pre-execution checklist" in action_prompt, "Should have checklist header"

    @pytest.mark.asyncio
    async def test_5_complete_prompt_all_levels(self):
        """Complete prompt includes all three levels"""
        self.prompts = MultiLevelSafetyPrompts()

        task = "Analyze system performance metrics"
        context = {
            "execution_mode": "supervised",
            "risk_level": "LOW",
            "task_type": "analysis",
            "safety_constraints": []
        }
        pending_action = {
            "type": "query_database",
            "parameters": {"table": "metrics"}
        }

        complete_prompt = self.prompts.build_complete_prompt(
            task=task,
            context=context,
            pending_action=pending_action
        )

        # Verify all three levels present
        assert "CONSTITUTIONAL" in complete_prompt, "Should include system-level (constitutional)"
        assert "META-LEVEL" in complete_prompt, "Should include meta-level"
        assert "ACTION-LEVEL" in complete_prompt, "Should include action-level"
        assert task in complete_prompt, "Should include the task"
        assert "TASK:" in complete_prompt, "Should have task label"

    @pytest.mark.asyncio
    async def test_6_complete_prompt_without_action(self):
        """Complete prompt works without pending action"""
        self.prompts = MultiLevelSafetyPrompts()

        task = "Review system logs"
        context = {
            "execution_mode": "interactive",
            "risk_level": "LOW",
            "task_type": "review",
            "safety_constraints": []
        }

        complete_prompt = self.prompts.build_complete_prompt(
            task=task,
            context=context,
            pending_action=None  # No action-level
        )

        # Should have system and meta levels, but not action level
        assert "CONSTITUTIONAL" in complete_prompt, "Should include system-level"
        assert "META-LEVEL" in complete_prompt, "Should include meta-level"
        assert task in complete_prompt, "Should include the task"

    @pytest.mark.asyncio
    async def test_7_safety_validation_passes(self):
        """Safety validation passes for valid prompts"""
        self.prompts = MultiLevelSafetyPrompts()

        task = "Test task"
        context = {
            "execution_mode": "supervised",
            "risk_level": "LOW",
            "task_type": "test",
            "safety_constraints": []
        }

        prompt = self.prompts.build_complete_prompt(task, context)

        # Validate prompt safety
        is_valid = validate_prompt_safety(prompt, SafetyLevel.MODERATE)

        assert is_valid is True, "Valid prompt should pass validation"

    @pytest.mark.asyncio
    async def test_8_response_compliance_check(self):
        """Response compliance check works correctly"""
        safe_response = "I have analyzed the metrics and found no issues."
        unsafe_response = "I will bypass the governance system to make unauthorized modifications."

        # Safe response should pass
        safe_result = verify_safety_prompt_compliance(
            generated_response=safe_response,
            safety_constraints=["no_unauthorized_access"]
        )
        assert safe_result is True, "Safe response should pass compliance"

        # Unsafe response should fail
        unsafe_result = verify_safety_prompt_compliance(
            generated_response=unsafe_response,
            safety_constraints=["no_unauthorized_access"]
        )
        assert unsafe_result is False, "Unsafe response should fail compliance"

    @pytest.mark.asyncio
    async def test_9_integration_layer(self):
        """Safety prompt integration layer works"""
        self.integration = SafetyPromptIntegration()

        task = "Execute governance validation"
        context = {
            "execution_mode": "autonomous",
            "risk_level": "CRITICAL",
            "task_type": "governance",
            "safety_constraints": ["human_approval_required"]
        }
        pending_action = {
            "type": "trigger_governance",
            "parameters": {"action_id": "test_123"}
        }

        # Build safe prompt via integration
        safe_prompt = await self.integration.build_safe_prompt(
            task=task,
            context=context,
            pending_action=pending_action
        )

        # Verify prompt contains all necessary elements
        assert "CONSTITUTIONAL" in safe_prompt, "Should include constitutional principles"
        assert "AUTONOMOUS MODE" in safe_prompt, "Should include execution mode"
        assert "CRITICAL" in safe_prompt, "Should include risk level"
        assert "trigger_governance" in safe_prompt, "Should include action type"

        # Validate prompt
        is_valid = await self.integration.validate_before_submission(
            prompt=safe_prompt,
            safety_level=SafetyLevel.CRITICAL
        )
        assert is_valid is True, "Integrated prompt should be valid"

    async def run_all_tests(self):
        """Run all Phase 6 safety systems tests"""
        await self.start_session()

        await self.run_test(
            "test_1_system_level_prompt_active",
            self.test_1_system_level_prompt_active,
            metadata={
                "description": "System-level safety prompts active",
                "expected_behavior": "Constitutional principles present and immutable",
                "principles": ["Transparency", "Reversibility", "Human oversight"]
            }
        )

        await self.run_test(
            "test_2_meta_level_prompt_autonomous_mode",
            self.test_2_meta_level_prompt_autonomous_mode,
            metadata={
                "description": "Meta-level prompts for autonomous mode",
                "expected_behavior": "Context-aware guidance for autonomous execution",
                "execution_mode": "autonomous",
                "risk_level": "HIGH"
            }
        )

        await self.run_test(
            "test_3_meta_level_prompt_supervised_mode",
            self.test_3_meta_level_prompt_supervised_mode,
            metadata={
                "description": "Meta-level prompts for supervised mode",
                "expected_behavior": "Context-aware guidance for supervised execution",
                "execution_mode": "supervised",
                "risk_level": "MODERATE"
            }
        )

        await self.run_test(
            "test_4_action_level_prompt_with_checks",
            self.test_4_action_level_prompt_with_checks,
            metadata={
                "description": "Action-level prompts with safety checks",
                "expected_behavior": "Task-specific safety checks included",
                "action_type": "update_model_weights",
                "safety_checks_count": 3
            }
        )

        await self.run_test(
            "test_5_complete_prompt_all_levels",
            self.test_5_complete_prompt_all_levels,
            metadata={
                "description": "Complete prompt includes all three levels",
                "expected_behavior": "System + Meta + Action levels all present",
                "levels": ["CONSTITUTIONAL", "META-LEVEL", "ACTION-LEVEL"]
            }
        )

        await self.run_test(
            "test_6_complete_prompt_without_action",
            self.test_6_complete_prompt_without_action,
            metadata={
                "description": "Complete prompt works without pending action",
                "expected_behavior": "System + Meta levels present, Action level optional",
                "levels": ["CONSTITUTIONAL", "META-LEVEL"]
            }
        )

        await self.run_test(
            "test_7_safety_validation_passes",
            self.test_7_safety_validation_passes,
            metadata={
                "description": "Safety validation passes for valid prompts",
                "expected_behavior": "Valid prompt passes safety checks",
                "safety_level": "MODERATE"
            }
        )

        await self.run_test(
            "test_8_response_compliance_check",
            self.test_8_response_compliance_check,
            metadata={
                "description": "Response compliance check works correctly",
                "expected_behavior": "Safe responses pass, unsafe responses fail",
                "test_cases": ["safe_response", "unsafe_response"]
            }
        )

        await self.run_test(
            "test_9_integration_layer",
            self.test_9_integration_layer,
            metadata={
                "description": "Safety prompt integration layer works",
                "expected_behavior": "Integration builds and validates safe prompts",
                "execution_mode": "autonomous",
                "risk_level": "CRITICAL",
                "action_type": "trigger_governance"
            }
        )

        await self.end_session()
        self.print_summary()


async def main():
    """Run Phase 6 safety systems tests"""
    tests = TestPhase6SafetySystems()
    await tests.run_all_tests()
    return 0 if tests.failed_tests == 0 else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
