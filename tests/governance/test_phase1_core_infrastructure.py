#!/usr/bin/env python3
"""
Phase 1: Core Infrastructure Tests

Comprehensive test suite for governance core infrastructure:
- Configuration loading
- Condition matching
- Decision tier assignment
- Escalation category mapping
- Irreversibility classification
"""

import pytest

pytest.skip(
    "GovernanceDecision was removed with the governance-session machinery (human-in-the-loop debate, multi-judge panels, approval queues). It was already unreachable before removal: every construction passed ai_judge_votes, a field the dataclass did not declare, so it raised TypeError on every call -- and make_decision() had zero callers. These tests exercise that retired path.",
    allow_module_level=True,
)


import pytest
import json
from pathlib import Path
import sys

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from core.governance.unified_governance_trigger_system import (
    UnifiedGovernanceTriggerSystem,
    GovernanceDecision,
    DecisionTier,
    ActionCategory,
)


class TestConfigurationLoading:
    """Test configuration loading from governance_triggers.json"""

    def test_load_governance_triggers(self):
        """Test that governance_triggers.json loads successfully"""
        config_path = project_root / "config" / "governance_triggers.json"
        assert config_path.exists(), "governance_triggers.json not found"

        with open(config_path, 'r') as f:
            config = json.load(f)

        assert "action_categories" in config
        assert "schema_version" in config
        assert config["schema_version"] == "1.0.0"

    def test_validate_trigger_structure(self):
        """Test that all triggers have required fields"""
        config_path = project_root / "config" / "governance_triggers.json"
        with open(config_path, 'r') as f:
            config = json.load(f)

        required_fields = [
            "trigger_id", "name", "conditions", "escalation_category",
            "irreversibility_class", "enforcement_mode"
        ]

        action_categories = config["action_categories"]
        assert len(action_categories) == 8, f"Expected 8 action categories, found {len(action_categories)}"

        for category_name, category_data in action_categories.items():
            assert "triggers" in category_data
            for trigger in category_data["triggers"]:
                for field in required_fields:
                    assert field in trigger, f"Trigger {trigger.get('trigger_id', 'unknown')} missing field: {field}"

                # Validate irreversibility_class
                assert trigger["irreversibility_class"] in [
                    "IRREVERSIBLE", "PARTIALLY_REVERSIBLE",
                    "MOSTLY_REVERSIBLE", "MOSTLY_IRREVERSIBLE", "FULLY_REVERSIBLE"
                ]

                # Validate enforcement_mode
                assert trigger["enforcement_mode"] in [
                    "MUST_BLOCK", "RECOMMEND_GOVERNANCE", "LOG_ONLY"
                ]

    def test_all_8_categories_present(self):
        """Test that all 8 action categories are defined"""
        config_path = project_root / "config" / "governance_triggers.json"
        with open(config_path, 'r') as f:
            config = json.load(f)

        expected_categories = [
            "TOOL_EXECUTION",
            "MEMORY_OPERATIONS",
            "RESOURCE_ALLOCATION",
            "LEARNING_PARAMETERS",  # Actual name in config
            "CONFIGURATION_CHANGES",  # Actual name in config
            "TASK_CREATION",
            "EXTERNAL_INTEGRATIONS",
            "CURIOSITY_EXPLORATION"
        ]

        action_categories = config["action_categories"]
        for category in expected_categories:
            assert category in action_categories, f"Missing action category: {category}"


class TestConditionMatching:
    """Test condition matching logic"""

    @pytest.fixture
    def governance_system(self):
        """Create governance system instance"""
        config_path = project_root / "config" / "governance_triggers.json"
        return UnifiedGovernanceTriggerSystem(config_path=str(config_path))

    @pytest.mark.asyncio
    async def test_tool_execution_exact_match(self, governance_system):
        """Test exact string match for tool execution"""
        decision = await governance_system.evaluate_action(
            action_category="TOOL_EXECUTION",
            action_data={
                "tool_name": "ChaosTestingTool",
                "parameters": {
                    "target": "production"
                }
            }
        )

        assert decision.matched_trigger_id == "tool_exec_001"
        assert decision.decision_tier == DecisionTier.CRITICAL
        assert decision.escalation_category == "CHAOS_TESTING_PRODUCTION"

    @pytest.mark.asyncio
    async def test_tool_execution_regex_match(self, governance_system):
        """Test regex pattern match for tool execution"""
        decision = await governance_system.evaluate_action(
            action_category="TOOL_EXECUTION",
            action_data={
                "tool_name": "ChaosTestingTool",
                "parameters": {
                    "target": "prod-server-01"
                }
            }
        )

        assert decision.matched_trigger_id == "tool_exec_001"
        assert decision.decision_tier == DecisionTier.CRITICAL

    @pytest.mark.asyncio
    async def test_tool_execution_numeric_comparison(self, governance_system):
        """Test numeric comparison in conditions"""
        decision = await governance_system.evaluate_action(
            action_category="TOOL_EXECUTION",
            action_data={
                "tool_name": "ChaosTestingTool",
                "parameters": {
                    "target": "staging",
                    "intensity": 8
                }
            }
        )

        # Should match tool_exec_002 (intensity >= 7)
        assert decision.matched_trigger_id == "tool_exec_002"
        assert decision.decision_tier in [DecisionTier.IMPORTANT, DecisionTier.CRITICAL]

    @pytest.mark.asyncio
    async def test_tool_execution_contains_match(self, governance_system):
        """Test contains_any match for tool execution"""
        decision = await governance_system.evaluate_action(
            action_category="TOOL_EXECUTION",
            action_data={
                "tool_name": "MutationTestingTool",
                "parameters": {
                    "target_files": ["core/governance/test.py", "tests/unit/test_main.py"]
                }
            }
        )

        assert decision.matched_trigger_id == "tool_exec_003"
        assert decision.decision_tier == DecisionTier.CRITICAL

    @pytest.mark.asyncio
    async def test_tool_execution_no_match(self, governance_system):
        """Test action that doesn't match any triggers"""
        decision = await governance_system.evaluate_action(
            action_category="TOOL_EXECUTION",
            action_data={
                "tool_name": "ChaosTestingTool",
                "parameters": {
                    "target": "staging",
                    "intensity": 3
                }
            }
        )

        # No match should return ROUTINE
        assert decision.decision_tier == DecisionTier.ROUTINE


class TestDecisionTier:
    """Test decision tier assignment logic"""

    @pytest.fixture
    def governance_system(self):
        """Create governance system instance"""
        config_path = project_root / "config" / "governance_triggers.json"
        return UnifiedGovernanceTriggerSystem(config_path=str(config_path))

    @pytest.mark.asyncio
    async def test_critical_tier_assignment(self, governance_system):
        """Test CRITICAL tier assignment"""
        # Production chaos testing should be CRITICAL
        decision = await governance_system.evaluate_action(
            action_category="TOOL_EXECUTION",
            action_data={
                "tool_name": "ChaosTestingTool",
                "parameters": {"target": "production"}
            }
        )

        assert decision.decision_tier == DecisionTier.CRITICAL
        assert decision.enforcement_mode == "MUST_BLOCK"

    @pytest.mark.asyncio
    async def test_important_tier_assignment(self, governance_system):
        """Test IMPORTANT tier assignment"""
        # High intensity chaos testing should be IMPORTANT
        decision = await governance_system.evaluate_action(
            action_category="TOOL_EXECUTION",
            action_data={
                "tool_name": "ChaosTestingTool",
                "parameters": {"target": "staging", "intensity": 8}
            }
        )

        assert decision.decision_tier in [DecisionTier.IMPORTANT, DecisionTier.CRITICAL]

    @pytest.mark.asyncio
    async def test_routine_tier_assignment(self, governance_system):
        """Test ROUTINE tier assignment"""
        # Low risk action should be ROUTINE
        decision = await governance_system.evaluate_action(
            action_category="TOOL_EXECUTION",
            action_data={
                "tool_name": "AnalyzeCodeTool",
                "parameters": {"file": "test.py"}
            }
        )

        assert decision.decision_tier == DecisionTier.ROUTINE


class TestEscalationCategory:
    """Test escalation category mapping"""

    @pytest.fixture
    def governance_system(self):
        """Create governance system instance"""
        config_path = project_root / "config" / "governance_triggers.json"
        return UnifiedGovernanceTriggerSystem(config_path=str(config_path))

    @pytest.mark.asyncio
    async def test_tool_execution_categories(self, governance_system):
        """Test tool execution escalation categories"""
        expected_categories = [
            "CHAOS_TESTING_PRODUCTION",
            "CHAOS_TESTING_HIGH_INTENSITY",
            "MUTATION_TESTING_CRITICAL_FILES",
            "FUZZ_TESTING_CODE_EXEC"
        ]

        # Test at least one category
        decision = await governance_system.evaluate_action(
            action_category="TOOL_EXECUTION",
            action_data={
                "tool_name": "ChaosTestingTool",
                "parameters": {"target": "production"}
            }
        )

        assert decision.escalation_category in expected_categories

    @pytest.mark.asyncio
    async def test_all_categories_have_escalation(self, governance_system):
        """Test that all matched triggers have escalation categories"""
        config_path = project_root / "config" / "governance_triggers.json"
        with open(config_path, 'r') as f:
            config = json.load(f)

        for category_name, category_data in config["action_categories"].items():
            for trigger in category_data["triggers"]:
                assert "escalation_category" in trigger
                assert len(trigger["escalation_category"]) > 0


class TestIrreversibility:
    """Test irreversibility classification"""

    @pytest.fixture
    def governance_system(self):
        """Create governance system instance"""
        config_path = project_root / "config" / "governance_triggers.json"
        return UnifiedGovernanceTriggerSystem(config_path=str(config_path))

    @pytest.mark.asyncio
    async def test_irreversible_classification(self, governance_system):
        """Test IRREVERSIBLE classification"""
        # Production chaos testing is IRREVERSIBLE
        decision = await governance_system.evaluate_action(
            action_category="TOOL_EXECUTION",
            action_data={
                "tool_name": "ChaosTestingTool",
                "parameters": {"target": "production"}
            }
        )

        assert decision.irreversibility_class == "IRREVERSIBLE"

    @pytest.mark.asyncio
    async def test_partially_reversible_classification(self, governance_system):
        """Test PARTIALLY_REVERSIBLE classification"""
        # High intensity chaos testing is PARTIALLY_REVERSIBLE
        decision = await governance_system.evaluate_action(
            action_category="TOOL_EXECUTION",
            action_data={
                "tool_name": "ChaosTestingTool",
                "parameters": {"target": "staging", "intensity": 8}
            }
        )

        assert decision.irreversibility_class == "PARTIALLY_REVERSIBLE"

    @pytest.mark.asyncio
    async def test_mostly_reversible_classification(self, governance_system):
        """Test MOSTLY_REVERSIBLE classification"""
        # Mutation testing on critical files is MOSTLY_REVERSIBLE
        decision = await governance_system.evaluate_action(
            action_category="TOOL_EXECUTION",
            action_data={
                "tool_name": "MutationTestingTool",
                "parameters": {"target_files": ["core/governance/test.py"]}
            }
        )

        assert decision.irreversibility_class == "MOSTLY_REVERSIBLE"

    def test_all_triggers_have_irreversibility_class(self):
        """Test that all triggers have irreversibility classification"""
        config_path = project_root / "config" / "governance_triggers.json"
        with open(config_path, 'r') as f:
            config = json.load(f)

        valid_classes = ["IRREVERSIBLE", "PARTIALLY_REVERSIBLE", "MOSTLY_REVERSIBLE", "FULLY_REVERSIBLE"]

        for category_name, category_data in config["action_categories"].items():
            for trigger in category_data["triggers"]:
                assert "irreversibility_class" in trigger
                assert trigger["irreversibility_class"] in valid_classes


class TestCrossCategory:
    """Test cross-category integration"""

    @pytest.fixture
    def governance_system(self):
        """Create governance system instance"""
        config_path = project_root / "config" / "governance_triggers.json"
        return UnifiedGovernanceTriggerSystem(config_path=str(config_path))

    @pytest.mark.asyncio
    async def test_all_8_action_categories(self, governance_system):
        """Test that evaluate_action works for all 8 categories"""
        test_actions = [
            ("TOOL_EXECUTION", {"tool_name": "TestTool"}),
            ("MEMORY_OPERATIONS", {"action_type": "upgrade_memory_system"}),
            ("RESOURCE_ALLOCATION", {"resource_type": "cpu", "change_percent": 25}),
            ("LEARNING_PARAMETERS", {"change_type": "model_weights"}),
            ("CONFIGURATION_CHANGES", {"config_type": "safety_threshold"}),
            ("TASK_CREATION", {"task_count": 100}),
            ("EXTERNAL_INTEGRATIONS", {"integration_type": "new_api"}),
            ("CURIOSITY_EXPLORATION", {"exploration_type": "code_modification"}),
        ]

        for category, action_data in test_actions:
            decision = await governance_system.evaluate_action(
                action_category=category,
                action_data=action_data
            )

            # Should return a valid decision
            assert isinstance(decision, GovernanceDecision)
            assert decision.action_category == category
            assert decision.decision_tier in [
                DecisionTier.CRITICAL,
                DecisionTier.IMPORTANT,
                DecisionTier.ROUTINE
            ]

    @pytest.mark.asyncio
    async def test_edge_case_no_match(self, governance_system):
        """Test edge case where no triggers match"""
        decision = await governance_system.evaluate_action(
            action_category="TOOL_EXECUTION",
            action_data={
                "tool_name": "SafeReadTool",
                "parameters": {"file": "readme.txt"}
            }
        )

        # No match should return ROUTINE
        assert decision.decision_tier == DecisionTier.ROUTINE
        assert decision.matched_trigger_id is None

    @pytest.mark.asyncio
    async def test_edge_case_invalid_category(self, governance_system):
        """Test edge case with invalid action category"""
        with pytest.raises(Exception):
            await governance_system.evaluate_action(
                action_category="INVALID_CATEGORY",
                action_data={}
            )


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
