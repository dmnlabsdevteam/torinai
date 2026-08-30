#!/usr/bin/env python3
"""Debug script to test governance evaluation"""

import sys
import asyncio
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from core.governance.unified_governance_trigger_system import (
    UnifiedGovernanceTriggerSystem,
    ActionCategory,
    DecisionTier
)
from core.tools.tool_registry import get_tool_registry


async def debug_governance():
    """Test governance evaluation directly"""

    print("=" * 60)
    print("DEBUG: Governance Evaluation Test")
    print("=" * 60)
    print()

    # Test 1: Direct governance evaluation
    print("Test 1: Direct governance evaluation")
    print("-" * 60)

    governance = UnifiedGovernanceTriggerSystem()

    # Test chaos_testing with production target
    evaluation = await governance.evaluate_action(
        action_category=ActionCategory.TOOL_EXECUTION,
        action_type="execute_tool",
        parameters={
            "tool_name": "chaos_testing",
            "target": "production",
            "duration": 60
        }
    )

    print(f"Action: chaos_testing(target='production', duration=60)")
    print(f"Triggered: {evaluation.triggered}")
    print(f"Trigger ID: {evaluation.trigger_id}")
    print(f"Decision Tier: {evaluation.decision_tier}")
    print(f"Enforcement Mode: {evaluation.enforcement_mode}")
    print(f"Safety Risk: {evaluation.safety_risk}")
    print()

    # Test 2: Via tool registry
    print("Test 2: Via tool registry execute_tool()")
    print("-" * 60)

    registry = get_tool_registry()
    result = await registry.execute_tool(
        tool_name="chaos_testing",
        parameters={"target": "production", "duration": 60}
    )

    print(f"Success: {result.success}")
    print(f"Requires Approval: {result.requires_approval}")
    print(f"Approval Message: {result.approval_message}")
    print(f"Error: {result.error}")
    print()

    # Test 3: Safe tool (read_file)
    print("Test 3: Safe tool (read_file)")
    print("-" * 60)

    evaluation2 = await governance.evaluate_action(
        action_category=ActionCategory.TOOL_EXECUTION,
        action_type="execute_tool",
        parameters={
            "tool_name": "read_file",
            "file_path": "/tmp/test.txt"
        }
    )

    print(f"Action: read_file(file_path='/tmp/test.txt')")
    print(f"Triggered: {evaluation2.triggered}")
    print(f"Decision Tier: {evaluation2.decision_tier}")
    print(f"Expected: ROUTINE (no trigger)")
    print()


if __name__ == "__main__":
    asyncio.run(debug_governance())
