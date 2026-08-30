#!/usr/bin/env python3
"""
Phase 1: Core Infrastructure Tests
===================================

Tests for Phase 1 governance trigger system with database logging.

Tests:
1. Configuration loading (2 tests)
2. Tool execution matching (5 tests)
3. Decision tier assignment (2 tests)
4. Cross-category evaluation (1 test)

Total: 10 tests

Author: Torin AI Team
Date: January 1, 2026
"""

import sys
import os
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

# Add tests directory to path for test_base
tests_dir = Path(__file__).parent.parent
sys.path.insert(0, str(tests_dir))

import asyncio
import json
from test_base import TestBase, TestResult

from core.governance.unified_governance_trigger_system import (
    UnifiedGovernanceTriggerSystem,
    GovernanceTriggerEvaluation,
    DecisionTier,
    ActionCategory,
)
from core.governance.context_classifier import (
    ContextClassifier,
    ContextLabel,
    verify_no_data_loss
)


class GovernancePhase1Tests(TestBase):
    """Phase 1 governance tests with database logging"""

    def __init__(self):
        super().__init__(
            test_category="governance",
            test_type="phase1"
        )

        # Initialize governance system
        config_path = project_root / "config" / "governance_triggers.json"
        self.gov = UnifiedGovernanceTriggerSystem(config_path=str(config_path))
        self.config_path = config_path

        # Initialize context classifier
        self.classifier = ContextClassifier()

    # ===== Configuration Loading Tests =====

    def test_load_governance_triggers(self):
        """Test that governance_triggers.json loads successfully"""
        assert self.config_path.exists(), f"Config file not found: {self.config_path}"

        with open(self.config_path, 'r') as f:
            config = json.load(f)

        assert "action_categories" in config, "Missing action_categories in config"
        assert "schema_version" in config, "Missing schema_version in config"

    def test_all_8_categories_present(self):
        """Test that all 8 action categories are defined"""
        with open(self.config_path, 'r') as f:
            config = json.load(f)

        expected_categories = [
            "TOOL_EXECUTION",
            "MEMORY_OPERATIONS",
            "RESOURCE_ALLOCATION",
            "LEARNING_PARAMETERS",
            "CONFIGURATION_CHANGES",
            "TASK_CREATION",
            "EXTERNAL_INTEGRATIONS",
            "CURIOSITY_EXPLORATION"
        ]

        action_categories = config["action_categories"]
        for category in expected_categories:
            assert category in action_categories, f"Missing category: {category}"

    # ===== Tool Execution Matching Tests =====

    async def test_production_chaos_testing(self):
        """Test production chaos testing triggers CRITICAL"""
        result = await self.gov.evaluate_action(
            action_category=ActionCategory.TOOL_EXECUTION,
            action_type="execute_tool",
            parameters={"tool_name": "ChaosTestingTool", "target": "production"}
        )

        assert result.triggered == True, "Should trigger on production chaos testing"
        assert result.trigger_id == "tool_exec_001", f"Wrong trigger_id: {result.trigger_id}"
        assert result.decision_tier == DecisionTier.CRITICAL, f"Wrong tier: {result.decision_tier}"

    async def test_prod_regex_match(self):
        """Test regex pattern matching for prod servers"""
        result = await self.gov.evaluate_action(
            action_category=ActionCategory.TOOL_EXECUTION,
            action_type="execute_tool",
            parameters={"tool_name": "ChaosTestingTool", "target": "prod-server-01"}
        )

        assert result.triggered == True, "Should trigger on prod-server-01 (regex match)"
        assert result.trigger_id == "tool_exec_001", f"Wrong trigger_id: {result.trigger_id}"

    async def test_high_intensity_chaos(self):
        """Test numeric comparison for intensity"""
        result = await self.gov.evaluate_action(
            action_category=ActionCategory.TOOL_EXECUTION,
            action_type="execute_tool",
            parameters={"tool_name": "ChaosTestingTool", "target": "staging", "intensity": 8}
        )

        assert result.triggered == True, "Should trigger on high intensity (>=7)"
        assert result.trigger_id == "tool_exec_002", f"Wrong trigger_id: {result.trigger_id}"

    async def test_mutation_critical_files(self):
        """Test contains_any matching"""
        result = await self.gov.evaluate_action(
            action_category=ActionCategory.TOOL_EXECUTION,
            action_type="execute_tool",
            parameters={
                "tool_name": "MutationTestingTool",
                "target_files": ["core/governance", "other.py"]
            }
        )

        assert result.triggered == True, "Should trigger on critical file mutation"
        assert result.trigger_id == "tool_exec_003", f"Wrong trigger_id: {result.trigger_id}"

    async def test_no_match_safe_tool(self):
        """Test safe tool has no triggers"""
        result = await self.gov.evaluate_action(
            action_category=ActionCategory.TOOL_EXECUTION,
            action_type="execute_tool",
            parameters={"tool_name": "SafeReadTool", "file": "readme.txt"}
        )

        assert result.triggered == False, "Safe tool should not trigger"
        assert result.decision_tier == DecisionTier.ROUTINE, f"Wrong tier: {result.decision_tier}"

    # ===== Decision Tier Tests =====

    async def test_critical_tier(self):
        """MUST_BLOCK enforcement → CRITICAL tier"""
        result = await self.gov.evaluate_action(
            action_category=ActionCategory.TOOL_EXECUTION,
            action_type="execute_tool",
            parameters={"tool_name": "ChaosTestingTool", "target": "production"}
        )

        assert result.decision_tier == DecisionTier.CRITICAL, f"Wrong tier: {result.decision_tier}"
        assert result.enforcement_mode.value == "MUST_BLOCK", f"Wrong enforcement: {result.enforcement_mode.value}"

    async def test_routine_tier(self):
        """No trigger → ROUTINE tier"""
        result = await self.gov.evaluate_action(
            action_category=ActionCategory.TOOL_EXECUTION,
            action_type="execute_tool",
            parameters={"tool_name": "AnalyzeCodeTool", "file": "test.py"}
        )

        assert result.decision_tier == DecisionTier.ROUTINE, f"Wrong tier: {result.decision_tier}"

    # ===== Cross-Category Tests =====

    async def test_all_categories_work(self):
        """Verify evaluate_action works for all 8 categories"""
        test_cases = [
            (ActionCategory.TOOL_EXECUTION, "execute", {}),
            (ActionCategory.MEMORY_OPERATIONS, "operation", {}),
            (ActionCategory.RESOURCE_ALLOCATION, "allocate", {}),
            (ActionCategory.LEARNING_PARAMETERS, "update", {}),
            (ActionCategory.CONFIGURATION_CHANGES, "change", {}),
            (ActionCategory.TASK_CREATION, "create", {}),
            (ActionCategory.EXTERNAL_INTEGRATIONS, "integrate", {}),
            (ActionCategory.CURIOSITY_EXPLORATION, "explore", {}),
        ]

        for category, action_type, params in test_cases:
            result = await self.gov.evaluate_action(
                action_category=category,
                action_type=action_type,
                parameters=params
            )
            assert isinstance(result, GovernanceTriggerEvaluation), \
                f"Wrong return type for {category}: {type(result)}"
            assert result.action_category == category, \
                f"Wrong category in result: {result.action_category}"

    # ===== Context Classifier Tests =====

    async def test_audit_relevant_classification(self):
        """Test AUDIT_RELEVANT label for governance decisions"""
        context_items = [{
            "type": "governance_decision",
            "content": "Critical action requires human approval",
            "action_id": "act_001"
        }]

        classified = await self.classifier.classify_context(context_items)

        assert len(classified) == 1, "Should preserve all items"
        assert classified[0].label == ContextLabel.AUDIT_RELEVANT, f"Wrong label: {classified[0].label}"
        assert classified[0].confidence >= 0.9, "Should have high confidence"
        assert verify_no_data_loss(context_items, classified), "Data loss detected!"

    async def test_decisional_classification(self):
        """Test DECISIONAL label for action parameters"""
        context_items = [{
            "type": "action_parameters",
            "content": {"tool_name": "TestTool", "target": "production"},
            "source": "evaluate_action"
        }]

        classified = await self.classifier.classify_context(context_items)

        assert len(classified) == 1
        assert classified[0].label == ContextLabel.DECISIONAL
        assert verify_no_data_loss(context_items, classified)

    async def test_memory_candidate_classification(self):
        """Test MEMORY_CANDIDATE label for insights"""
        context_items = [{
            "type": "pattern_recognition",
            "content": "Discovered correlation between deployment time and failure rate",
            "source": "analysis_engine"
        }]

        classified = await self.classifier.classify_context(context_items)

        assert len(classified) == 1
        assert classified[0].label == ContextLabel.MEMORY_CANDIDATE
        assert verify_no_data_loss(context_items, classified)

    async def test_referential_classification(self):
        """Test REFERENTIAL label for external docs"""
        context_items = [{
            "type": "external_documentation",
            "content": "API documentation from https://example.com/api/docs",
            "source": "external_api"
        }]

        classified = await self.classifier.classify_context(context_items)

        assert len(classified) == 1
        assert classified[0].label == ContextLabel.REFERENTIAL
        assert verify_no_data_loss(context_items, classified)

    async def test_transient_classification(self):
        """Test TRANSIENT label for temporary outputs"""
        context_items = [{
            "type": "tool_output",
            "content": "Temporary analysis result: 42",
            "source": "scratch_analysis"
        }]

        classified = await self.classifier.classify_context(context_items)

        assert len(classified) == 1
        assert classified[0].label == ContextLabel.TRANSIENT
        assert verify_no_data_loss(context_items, classified)

    async def test_no_data_loss_multiple_items(self):
        """Test that classifier preserves all items with mixed types"""
        context_items = [
            {"type": "governance_decision", "content": "Audit item"},
            {"type": "action_parameters", "content": "Decision item"},
            {"type": "pattern_recognition", "content": "Memory item"},
            {"type": "external_documentation", "content": "Reference item"},
            {"type": "tool_output", "content": "Transient item"}
        ]

        classified = await self.classifier.classify_context(context_items)

        assert len(classified) == 5, f"Expected 5 items, got {len(classified)}"
        assert verify_no_data_loss(context_items, classified), "Data loss detected!"

        # Verify all labels are assigned
        labels = {c.label for c in classified}
        assert ContextLabel.AUDIT_RELEVANT in labels
        assert ContextLabel.DECISIONAL in labels
        assert ContextLabel.MEMORY_CANDIDATE in labels
        assert ContextLabel.REFERENTIAL in labels
        assert ContextLabel.TRANSIENT in labels

    def test_format_for_judges(self):
        """Test formatted output for human/AI review"""
        # Create sample classified context
        from core.governance.context_classifier import ClassifiedContext
        from datetime import datetime

        classified = [
            ClassifiedContext(
                content={"type": "governance_decision", "content": "Test decision"},
                label=ContextLabel.AUDIT_RELEVANT,
                confidence=0.95,
                classification_reason="Contains governance decision",
                classified_at=datetime.now(),
                metadata={"item_type": "governance_decision"}
            )
        ]

        formatted = self.classifier.format_context_for_judges(classified)

        assert "AUDIT_RELEVANT" in formatted, "Should include label"
        assert "Contains governance decision" in formatted, "Should include reason"
        assert "0.95" in formatted, "Should include confidence"
        assert "All context is preserved" in formatted, "Should include no-deletion note"

    # ===== Test Runner =====

    async def run_all_tests(self):
        """Run all Phase 1 tests"""
        # Configuration tests (sync)
        await self.run_test(
            "test_load_governance_triggers",
            self.test_load_governance_triggers,
            metadata={
                "description": "Verify governance_triggers.json loads and has required schema fields",
                "phase": "1",
                "component": "configuration",
                "category": "config_validation"
            }
        )
        await self.run_test(
            "test_all_8_categories_present",
            self.test_all_8_categories_present,
            metadata={
                "description": "Verify all 8 action categories exist in config",
                "phase": "1",
                "component": "configuration",
                "category": "config_validation",
                "expected_categories": 8
            }
        )

        # Tool execution matching tests (async)
        await self.run_test(
            "test_production_chaos_testing",
            self.test_production_chaos_testing,
            metadata={
                "description": "Verify production chaos testing triggers CRITICAL decision tier",
                "phase": "1",
                "component": "trigger_matching",
                "category": "TOOL_EXECUTION",
                "expected_trigger": "tool_exec_001",
                "expected_tier": "CRITICAL"
            }
        )
        await self.run_test(
            "test_prod_regex_match",
            self.test_prod_regex_match,
            metadata={
                "description": "Verify regex pattern matching for prod-* servers",
                "phase": "1",
                "component": "trigger_matching",
                "category": "TOOL_EXECUTION",
                "match_type": "regex",
                "pattern": "prod-.*"
            }
        )
        await self.run_test(
            "test_high_intensity_chaos",
            self.test_high_intensity_chaos,
            metadata={
                "description": "Verify numeric comparison for intensity >= 7",
                "phase": "1",
                "component": "trigger_matching",
                "category": "TOOL_EXECUTION",
                "match_type": "numeric_comparison",
                "operator": ">=",
                "threshold": 7
            }
        )
        await self.run_test(
            "test_mutation_critical_files",
            self.test_mutation_critical_files,
            metadata={
                "description": "Verify contains_any matching for critical file paths",
                "phase": "1",
                "component": "trigger_matching",
                "category": "TOOL_EXECUTION",
                "match_type": "contains_any"
            }
        )
        await self.run_test(
            "test_no_match_safe_tool",
            self.test_no_match_safe_tool,
            metadata={
                "description": "Verify safe tools don't trigger governance",
                "phase": "1",
                "component": "trigger_matching",
                "category": "TOOL_EXECUTION",
                "expected_triggered": False,
                "expected_tier": "ROUTINE"
            }
        )

        # Decision tier tests (async)
        await self.run_test(
            "test_critical_tier",
            self.test_critical_tier,
            metadata={
                "description": "Verify MUST_BLOCK enforcement maps to CRITICAL tier",
                "phase": "1",
                "component": "decision_tier",
                "enforcement_mode": "MUST_BLOCK",
                "expected_tier": "CRITICAL"
            }
        )
        await self.run_test(
            "test_routine_tier",
            self.test_routine_tier,
            metadata={
                "description": "Verify no trigger results in ROUTINE tier",
                "phase": "1",
                "component": "decision_tier",
                "expected_triggered": False,
                "expected_tier": "ROUTINE"
            }
        )

        # Cross-category tests (async)
        await self.run_test(
            "test_all_categories_work",
            self.test_all_categories_work,
            metadata={
                "description": "Verify evaluate_action works for all 8 action categories",
                "phase": "1",
                "component": "cross_category",
                "categories_tested": 8,
                "validates": "API compatibility across all categories"
            }
        )

        # Context Classifier tests (async)
        await self.run_test(
            "test_audit_relevant_classification",
            self.test_audit_relevant_classification,
            metadata={
                "description": "Verify AUDIT_RELEVANT label for governance decisions",
                "phase": "1",
                "component": "context_classifier",
                "label": "AUDIT_RELEVANT",
                "validates": "Critical principle: NO DELETION"
            }
        )
        await self.run_test(
            "test_decisional_classification",
            self.test_decisional_classification,
            metadata={
                "description": "Verify DECISIONAL label for action parameters",
                "phase": "1",
                "component": "context_classifier",
                "label": "DECISIONAL"
            }
        )
        await self.run_test(
            "test_memory_candidate_classification",
            self.test_memory_candidate_classification,
            metadata={
                "description": "Verify MEMORY_CANDIDATE label for insights and patterns",
                "phase": "1",
                "component": "context_classifier",
                "label": "MEMORY_CANDIDATE"
            }
        )
        await self.run_test(
            "test_referential_classification",
            self.test_referential_classification,
            metadata={
                "description": "Verify REFERENTIAL label for external documentation",
                "phase": "1",
                "component": "context_classifier",
                "label": "REFERENTIAL"
            }
        )
        await self.run_test(
            "test_transient_classification",
            self.test_transient_classification,
            metadata={
                "description": "Verify TRANSIENT label for temporary tool outputs",
                "phase": "1",
                "component": "context_classifier",
                "label": "TRANSIENT"
            }
        )
        await self.run_test(
            "test_no_data_loss_multiple_items",
            self.test_no_data_loss_multiple_items,
            metadata={
                "description": "Verify NO DELETION principle with mixed context types",
                "phase": "1",
                "component": "context_classifier",
                "validates": "Data preservation across all 5 label types",
                "items_tested": 5
            }
        )
        await self.run_test(
            "test_format_for_judges",
            self.test_format_for_judges,
            metadata={
                "description": "Verify formatted output for human/AI judge review",
                "phase": "1",
                "component": "context_classifier",
                "validates": "Readability and completeness of judge presentation"
            }
        )


async def main():
    """Main test runner"""
    print("\n" + "=" * 60)
    print("Phase 1: Core Infrastructure Tests")
    print("=" * 60)

    # Create test suite
    tests = GovernancePhase1Tests()

    # Start session
    await tests.start_session()

    # Run all tests
    await tests.run_all_tests()

    # End session
    await tests.end_session()

    # Print summary
    tests.print_summary()

    # Return exit code
    return 0 if tests.failed_tests == 0 else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
