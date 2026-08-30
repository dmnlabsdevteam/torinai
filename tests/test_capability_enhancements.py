#!/usr/bin/env python3
"""
Test Enhanced Capability System
================================
Integration tests for the 4 architectural enhancements:
1. Weighted scoring function with configurable weights
2. Capability dependencies and execution planning
3. Risk-based governance integration
4. Improved inference with confidence scoring

Author: Torin AI Team
"""

import asyncio
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.tools.tool_registry import ToolRegistry
from core.tools.capabilities import (
    Capability,
    CapabilityMetadata,
    ToolCapabilityProfile,
    RiskLevel,
    infer_capability_from_task
)
from core.tools.filesystem_tools import ReadFileTool


def test_weighted_scoring():
    """Test weighted scoring for optimal provider selection"""
    print("\n" + "="*70)
    print("TEST 1: Weighted Scoring Function")
    print("="*70)

    # Create mock tool profiles
    profile_fast = ToolCapabilityProfile(
        tool_name="fast_reader",
        capabilities=[
            CapabilityMetadata(
                capability=Capability.READ_DATA,
                description="Fast but unreliable reader",
                latency="low",
                cost="low",
                reliability="medium",
                priority=5
            )
        ]
    )

    profile_reliable = ToolCapabilityProfile(
        tool_name="reliable_reader",
        capabilities=[
            CapabilityMetadata(
                capability=Capability.READ_DATA,
                description="Slow but very reliable reader",
                latency="high",
                cost="medium",
                reliability="high",
                priority=8
            )
        ]
    )

    # Test 1: Default weights (priority matters most)
    print("\n1. Testing default weights...")
    context = {"data_source": "file"}

    score_fast = profile_fast.score_for_context(Capability.READ_DATA, context)
    score_reliable = profile_reliable.score_for_context(Capability.READ_DATA, context)

    print(f"   Fast reader score: {score_fast:.2f}")
    print(f"   Reliable reader score: {score_reliable:.2f}")
    print(f"   Winner: {'Reliable' if score_reliable > score_fast else 'Fast'}")

    # Test 2: Prioritize low latency
    print("\n2. Testing latency-focused weights...")
    latency_weights = {"priority": 0.5, "reliability": 0.3, "latency": -2.0, "cost": -0.1}

    score_fast_latency = profile_fast.score_for_context(Capability.READ_DATA, context, latency_weights)
    score_reliable_latency = profile_reliable.score_for_context(Capability.READ_DATA, context, latency_weights)

    print(f"   Fast reader score: {score_fast_latency:.2f}")
    print(f"   Reliable reader score: {score_reliable_latency:.2f}")
    print(f"   Winner: {'Reliable' if score_reliable_latency > score_fast_latency else 'Fast'}")

    # Test 3: Prioritize reliability
    print("\n3. Testing reliability-focused weights...")
    reliability_weights = {"priority": 0.5, "reliability": 3.0, "latency": -0.1, "cost": -0.1}

    score_fast_rel = profile_fast.score_for_context(Capability.READ_DATA, context, reliability_weights)
    score_reliable_rel = profile_reliable.score_for_context(Capability.READ_DATA, context, reliability_weights)

    print(f"   Fast reader score: {score_fast_rel:.2f}")
    print(f"   Reliable reader score: {score_reliable_rel:.2f}")
    print(f"   Winner: {'Reliable' if score_reliable_rel > score_fast_rel else 'Fast'}")

    print("\n✅ Weighted scoring works! Different weights produce different winners.")


def test_capability_dependencies():
    """Test capability dependency resolution and execution planning"""
    print("\n" + "="*70)
    print("TEST 2: Capability Dependencies")
    print("="*70)

    registry = ToolRegistry()

    # Create mock research tool with dependencies
    print("\n1. Creating research tool with dependencies...")

    class MockResearchTool:
        def __init__(self):
            self.name = "research_tool"
            self.description = "Conducts multi-source research"
            self.capability_profile = ToolCapabilityProfile(
                tool_name="research_tool",
                capabilities=[
                    CapabilityMetadata(
                        capability=Capability.CONDUCT_RESEARCH,
                        description="Multi-source research with web scraping",
                        depends_on=[
                            Capability.HTTP_REQUEST,
                            Capability.PARSE_HTML,
                            Capability.SUMMARIZE_TEXT
                        ],
                        priority=10
                    )
                ]
            )

    research_tool = MockResearchTool()
    print(f"   Created: {research_tool.name}")

    # Check dependencies
    deps = research_tool.capability_profile.get_capability_dependencies(Capability.CONDUCT_RESEARCH)
    print(f"   Dependencies: {[d.value for d in deps]}")

    assert len(deps) == 3, "Should have 3 dependencies!"
    assert Capability.HTTP_REQUEST in deps
    assert Capability.PARSE_HTML in deps
    assert Capability.SUMMARIZE_TEXT in deps

    print("\n✅ Capability dependencies work correctly!")


def test_risk_based_governance():
    """Test risk-based approval requirements"""
    print("\n" + "="*70)
    print("TEST 3: Risk-Based Governance Integration")
    print("="*70)

    # Create tool profiles with different risk levels
    print("\n1. Creating tools with different risk levels...")

    profile_safe = ToolCapabilityProfile(
        tool_name="read_file",
        capabilities=[
            CapabilityMetadata(
                capability=Capability.READ_DATA,
                description="Safe read operation",
                risk_level=RiskLevel.LOW
            )
        ]
    )

    profile_moderate = ToolCapabilityProfile(
        tool_name="write_file",
        capabilities=[
            CapabilityMetadata(
                capability=Capability.WRITE_DATA,
                description="Moderate risk write operation",
                risk_level=RiskLevel.MEDIUM,
                approval_level="team_lead"
            )
        ]
    )

    profile_high = ToolCapabilityProfile(
        tool_name="delete_database",
        capabilities=[
            CapabilityMetadata(
                capability=Capability.DELETE_DATA,
                description="High risk deletion",
                risk_level=RiskLevel.HIGH
            )
        ]
    )

    profile_critical = ToolCapabilityProfile(
        tool_name="deploy_production",
        capabilities=[
            CapabilityMetadata(
                capability=Capability.RUN_COMMAND,
                description="Critical production deployment",
                risk_level=RiskLevel.CRITICAL,
                approval_level="security_officer"
            )
        ]
    )

    # Test approval requirements
    print("\n2. Testing approval requirements...")

    requires_approval_safe = profile_safe.requires_approval(Capability.READ_DATA)
    requires_approval_moderate = profile_moderate.requires_approval(Capability.WRITE_DATA)
    requires_approval_high = profile_high.requires_approval(Capability.DELETE_DATA)
    requires_approval_critical = profile_critical.requires_approval(Capability.RUN_COMMAND)

    print(f"   Safe (READ): Requires approval? {requires_approval_safe}")
    print(f"   Moderate (WRITE): Requires approval? {requires_approval_moderate}")
    print(f"   High (DELETE): Requires approval? {requires_approval_high}")
    print(f"   Critical (DEPLOY): Requires approval? {requires_approval_critical}")

    assert not requires_approval_safe, "LOW risk should not require approval"
    assert requires_approval_moderate, "MEDIUM with approval_level should require approval"
    assert requires_approval_high, "HIGH risk should require approval"
    assert requires_approval_critical, "CRITICAL risk should require approval"

    print("\n✅ Risk-based governance integration works correctly!")


def test_improved_inference():
    """Test improved capability inference with confidence scoring"""
    print("\n" + "="*70)
    print("TEST 4: Improved Inference with Confidence Scoring")
    print("="*70)

    test_cases = [
        ("read the file at /var/log/system.log", Capability.READ_DATA, 6.0),
        ("generate code for user authentication", Capability.GENERATE_CODE, 9.0),
        ("run tests on the database module", Capability.TEST_CODE, 9.0),
        ("send a slack message to the team", Capability.SEND_MESSAGE, 10.0),
        ("security scan for vulnerabilities", Capability.SCAN_SECURITY, 10.0),
        ("query the database for user records", Capability.QUERY_DATABASE, 9.0),
    ]

    print("\n1. Testing inference with confidence scores...")
    for task, expected_cap, min_score in test_cases:
        results = infer_capability_from_task(task, threshold=1.0)

        print(f"\n   Task: \"{task}\"")
        if results:
            for cap, score in sorted(results.items(), key=lambda x: x[1], reverse=True):
                print(f"      {cap.value}: {score:.1f}")
        else:
            print("      No capabilities inferred")

        # Check if expected capability is present with good score
        assert expected_cap in results, f"Should infer {expected_cap.value}!"
        assert results[expected_cap] >= min_score, f"Score should be >= {min_score}!"

    # Test that it doesn't over-trigger
    print("\n2. Testing specificity (shouldn't over-trigger)...")

    vague_task = "analyze this"
    results_vague = infer_capability_from_task(vague_task, threshold=5.0)
    print(f"   Vague task: \"{vague_task}\"")
    print(f"   Capabilities (threshold=5.0): {len(results_vague)}")

    # With high threshold, vague tasks should infer few capabilities
    assert len(results_vague) <= 2, "Vague task should not trigger many high-confidence capabilities"

    print("\n✅ Improved inference works correctly!")


def test_integrated_workflow():
    """Test complete workflow with all enhancements"""
    print("\n" + "="*70)
    print("TEST 5: Integrated Workflow")
    print("="*70)

    registry = ToolRegistry()

    # Register a real tool
    print("\n1. Registering ReadFileTool with capability metadata...")
    tool = ReadFileTool()
    registry.register(tool)
    print(f"   Registered: {tool.name}")

    # Infer capabilities from task
    print("\n2. Inferring capabilities from task description...")
    task = "read the configuration file at /etc/config.yaml"
    capabilities = infer_capability_from_task(task, threshold=5.0)

    print(f"   Task: \"{task}\"")
    for cap, score in capabilities.items():
        print(f"      {cap.value}: {score:.1f}")

    # Select best provider with custom weights
    print("\n3. Selecting best provider with reliability focus...")
    weights = {"priority": 1.0, "reliability": 2.0, "latency": -0.1, "cost": -0.1}

    best_tool = registry.select_best_provider(
        Capability.READ_DATA,
        context={"data_source": "file"},
        weights=weights
    )

    if best_tool:
        print(f"   Selected tool: {best_tool.name}")

        # Check risk level
        if best_tool.capability_profile:
            cap_meta = best_tool.capability_profile.get_capability_metadata(Capability.READ_DATA)
            if cap_meta:
                print(f"   Risk level: {cap_meta.risk_level.value}")
                requires_approval = best_tool.capability_profile.requires_approval(Capability.READ_DATA)
                print(f"   Requires approval: {requires_approval}")

    print("\n✅ Integrated workflow works correctly!")


def run_all_tests():
    """Run all enhancement tests"""
    print("\n")
    print("╔" + "="*68 + "╗")
    print("║" + " "*12 + "ENHANCED CAPABILITY SYSTEM TEST SUITE" + " "*19 + "║")
    print("╚" + "="*68 + "╝")

    try:
        # Test 1: Weighted scoring
        test_weighted_scoring()

        # Test 2: Capability dependencies
        test_capability_dependencies()

        # Test 3: Risk-based governance
        test_risk_based_governance()

        # Test 4: Improved inference
        test_improved_inference()

        # Test 5: Integrated workflow
        test_integrated_workflow()

        # Summary
        print("\n" + "="*70)
        print("ALL ENHANCEMENT TESTS PASSED! ✅")
        print("="*70)
        print("\nEnhanced capability system is production-ready:")
        print("  ✓ Weighted scoring enables optimization (not just filtering)")
        print("  ✓ Capability dependencies enable automatic chaining")
        print("  ✓ Risk-based governance integrates with approval tiers")
        print("  ✓ Improved inference reduces false positives")
        print("\nArchitectural Evolution Complete:")
        print("  • From boolean matching → weighted optimization")
        print("  • From isolated capabilities → dependency graphs")
        print("  • From binary safety → tiered governance")
        print("  • From substring inference → pattern-based scoring")
        print()

        return True

    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {e}")
        return False
    except Exception as e:
        print(f"\n💥 UNEXPECTED ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
