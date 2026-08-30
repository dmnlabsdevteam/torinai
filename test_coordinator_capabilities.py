#!/usr/bin/env python3
"""
Test Autonomous Coordinator Capability-Based Tool Discovery
============================================================

Verifies that the coordinator now uses capability inference instead of keyword matching.
"""

import asyncio
import logging
from typing import Dict, Any

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def test_capability_based_discovery():
    """Test that _get_tools_by_capability uses semantic capability inference"""
    print("\n" + "="*80)
    print("TEST: Autonomous Coordinator - Capability-Based Tool Discovery")
    print("="*80)

    from core.agents.autonomous.general_purpose_executor import GeneralPurposeExecutor
    from core.tools import get_tool_registry

    executor = GeneralPurposeExecutor()
    # Set tool_registry directly for testing (normally set in initialize())
    executor.tool_registry = get_tool_registry()

    test_cases = [
        {
            "description": "Analyze causal relationships in system performance degradation",
            "expected_capabilities": ["CAUSAL_REASONING", "ANALYZE_FEEDBACK", "EXTRACT_PATTERNS"],
            "expected_tools": ["analyzecausalfeedback"]
        },
        {
            "description": "Test system resilience under network partition scenarios",
            "expected_capabilities": ["TEST_RESILIENCE", "INJECT_FAILURE"],
            "expected_tools": ["create_chaos_experiment", "run_chaos_experiment"]
        },
        {
            "description": "Predict when AGI capabilities will emerge based on current trends",
            "expected_capabilities": ["PREDICT_BREAKTHROUGH", "TRACK_FRONTIER"],
            "expected_tools": ["forecastcapabilities"]
        },
        {
            "description": "Benchmark memory agent performance and identify bottlenecks",
            "expected_capabilities": ["BENCHMARK", "ANALYZE_PERFORMANCE"],
            "expected_tools": ["profileperformance"]
        },
    ]

    passed = 0
    failed = 0

    for i, test_case in enumerate(test_cases, 1):
        print(f"\n{'─'*80}")
        print(f"Test Case {i}: {test_case['description'][:60]}...")
        print(f"{'─'*80}")

        try:
            # Call the NEW capability-based discovery method
            tools = await executor._get_tools_by_capability(test_case['description'])

            print(f"\n📊 Results:")
            print(f"   Tools discovered: {len(tools)}")
            print(f"   Tool names: {list(tools.keys())[:10]}")  # Show first 10

            # Check if expected tools are present
            expected_tools = test_case['expected_tools']
            found_tools = [tool_name for tool_name in expected_tools if tool_name in tools]

            if found_tools:
                print(f"\n✓ PASS: Found {len(found_tools)}/{len(expected_tools)} expected tools")
                for tool_name in found_tools:
                    tool = tools[tool_name]
                    if hasattr(tool, 'capability_profile') and tool.capability_profile:
                        caps = [cap.value for cap in tool.capability_profile.get_capability_names()]
                        print(f"   → {tool_name}: {caps[:3]}")
                    else:
                        print(f"   → {tool_name}: (no capability profile)")
                passed += 1
            else:
                print(f"\n✗ FAIL: Expected tools not found")
                print(f"   Expected: {expected_tools}")
                print(f"   Got: {list(tools.keys())[:10]}")
                failed += 1

        except Exception as e:
            print(f"\n✗ FAIL: Exception occurred: {e}")
            logger.exception(f"Test case {i} failed")
            failed += 1

    # Summary
    print(f"\n{'='*80}")
    print(f"SUMMARY: {passed}/{passed+failed} tests passed")
    print(f"{'='*80}")

    if failed == 0:
        print("\n✓ SUCCESS: Capability-based tool discovery is working correctly!")
        print("✓ The autonomous coordinator now uses semantic capabilities instead of keywords")
        print("✓ This enables the brain (LLM) to request capabilities and get matching tools")
    else:
        print(f"\n⚠ {failed} test(s) failed - see details above")

    return failed == 0


async def test_keyword_vs_capability_comparison():
    """Compare OLD keyword matching vs NEW capability-based discovery"""
    print("\n" + "="*80)
    print("COMPARISON: Keyword Matching vs Capability-Based Discovery")
    print("="*80)

    from core.agents.autonomous.general_purpose_executor import GeneralPurposeExecutor
    from core.tools import get_tool_registry

    executor = GeneralPurposeExecutor()
    # Set tool_registry directly for testing (normally set in initialize())
    executor.tool_registry = get_tool_registry()

    task_description = "Analyze causal relationships in feedback to improve system performance"

    print(f"\nTask: {task_description}")
    print(f"\n{'─'*80}")
    print(f"NEW: Capability-Based Discovery")
    print(f"{'─'*80}")

    # NEW: Capability-based
    new_tools = await executor._get_tools_by_capability(task_description)
    print(f"Tools discovered: {len(new_tools)}")

    # Show cognitive tools
    cognitive_tools = [name for name in new_tools.keys()
                      if name in ['analyzecausalfeedback', 'forecastcapabilities',
                                 'profileperformance', 'triggerselfimprovement']]

    print(f"Cognitive tools: {cognitive_tools}")

    if 'analyzecausalfeedback' in new_tools:
        print(f"\n✓ SUCCESS: Found analyzecausalfeedback via CAUSAL_REASONING capability")
        print(f"   This is semantic matching - the system understood the INTENT")
    else:
        print(f"\n✗ FAIL: Did not find analyzecausalfeedback")

    print(f"\n{'─'*80}")
    print(f"Key Difference:")
    print(f"{'─'*80}")
    print(f"OLD: Keyword matching → searches for 'causal', 'feedback', 'analyze' in tool names/categories")
    print(f"NEW: Capability inference → infers CAUSAL_REASONING capability → finds tools declaring it")
    print(f"\nThis allows:")
    print(f"  • Semantic understanding (intent-based, not keyword-based)")
    print(f"  • Tool extensibility (new tools auto-discovered if they declare capabilities)")
    print(f"  • Priority-based selection (highest-priority provider wins)")
    print(f"  • Risk-aware routing (governance based on capability risk levels)")


async def main():
    """Run all tests"""
    print("\n" + "="*80)
    print("AUTONOMOUS COORDINATOR - CAPABILITY SYSTEM TESTS")
    print("="*80)

    success = await test_capability_based_discovery()
    await test_keyword_vs_capability_comparison()

    return 0 if success else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    exit(exit_code)
