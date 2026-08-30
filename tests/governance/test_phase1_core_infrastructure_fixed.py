#!/usr/bin/env python3
"""
Phase 1: Core Infrastructure Tests (CORRECTED API USAGE)
"""

import pytest

pytest.skip(
    "Same retired governance-session machinery as test_phase1_core_infrastructure.py; GovernanceDecision no longer exists.",
    allow_module_level=True,
)


import pytest
import json
from pathlib import Path
import sys

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from core.governance.unified_governance_trigger_system import (
    UnifiedGovernanceTriggerSystem,
    GovernanceDecision,
    DecisionTier,
    ActionCategory,
)


class TestConditionMatching:
    """Test condition matching logic with correct API"""

    @pytest.fixture
    def governance_system(self):
        """Create governance system instance"""
        config_path = project_root / "config" / "governance_triggers.json"
        return UnifiedGovernanceTriggerSystem(config_path=str(config_path))

    @pytest.mark.asyncio
    async def test_tool_execution_exact_match(self, governance_system):
        """Test exact string match for tool execution"""
        decision = await governance_system.evaluate_action(
            action_category=ActionCategory.TOOL_EXECUTION,
            action_type="ChaosTestingTool",
            parameters={"target": "production"}
        )

        assert decision.matched_trigger_id == "tool_exec_001"
        assert decision.decision_tier == DecisionTier.CRITICAL
        assert decision.escalation_category == "CHAOS_TESTING_PRODUCTION"

    @pytest.mark.asyncio
    async def test_tool_execution_regex_match(self, governance_system):
        """Test regex pattern match for tool execution"""
        decision = await governance_system.evaluate_action(
            action_category=ActionCategory.TOOL_EXECUTION,
            action_type="ChaosTestingTool",
            parameters={"target": "prod-server-01"}
        )

        assert decision.matched_trigger_id == "tool_exec_001"
        assert decision.decision_tier == DecisionTier.CRITICAL


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
