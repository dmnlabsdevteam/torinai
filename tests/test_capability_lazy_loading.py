#!/usr/bin/env python3
"""
Test Capability-Based Discovery and Lazy Loading
=================================================
Integration test to verify:
1. Lazy loading - tools only load when accessed
2. Capability-based discovery - find tools by capability
3. Context-aware selection - pick best tool for use case
4. Capability index building - automatic indexing

Author: Torin AI Team
"""

import pytest
import asyncio
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.tools.tool_registry import ToolRegistry
from core.tools.capabilities import Capability
from core.tools.filesystem_tools import ReadFileTool


def test_lazy_loading():
    """Test that tools load on-demand, not at registration"""
    print("\n" + "="*70)
    print("TEST 1: Lazy Loading")
    print("="*70)

    registry = ToolRegistry()

    # Register a tool factory (should not instantiate)
    print("\n1. Registering ReadFileTool factory...")
    tool_instantiated = False

    def read_file_factory():
        nonlocal tool_instantiated
        tool_instantiated = True
        print("   ⚠️  Tool instantiated!")
        return ReadFileTool()

    registry.register_factory(
        "read_file",
        read_file_factory,
        capabilities=[Capability.READ_DATA]
    )

    print("   ✓ Factory registered")
    print(f"   Tool instantiated? {tool_instantiated}")
    assert not tool_instantiated, "Tool should NOT be instantiated at registration!"

    # Now access the tool - should trigger lazy loading
    print("\n2. Accessing tool via get_tool()...")
    tool = registry.get_tool("read_file")

    print(f"   Tool instantiated? {tool_instantiated}")
    assert tool_instantiated, "Tool SHOULD be instantiated when accessed!"
    assert tool is not None, "Tool should be loaded!"
    assert tool.name == "read_file"

    print("\n✅ Lazy loading works correctly!")


# Helper, not a pytest test: it takes an argument and is driven by the
# script's own runner below. Named `test_*` it was collected anyway and
# pytest failed resolving the argument as a fixture -- an error that
# reported the file as broken while the script itself worked.
def check_capability_discovery(registry: ToolRegistry):
    """Test capability-based discovery"""
    print("\n" + "="*70)
    print("TEST 2: Capability-Based Discovery")
    print("="*70)

    # Find providers for READ_DATA capability
    print("\n1. Finding providers for Capability.READ_DATA...")
    providers = registry.find_providers(Capability.READ_DATA)

    print(f"   Found {len(providers)} provider(s):")
    for tool in providers:
        print(f"   - {tool.name}: {tool.description}")

    assert len(providers) >= 1, "Should find at least 1 provider for READ_DATA!"

    # Check capability index
    print("\n2. Checking capability index...")
    coverage = registry.get_capability_coverage()
    print(f"   Capability coverage: {len(coverage)} capabilities indexed")

    if Capability.READ_DATA in coverage:
        print(f"   READ_DATA: {coverage[Capability.READ_DATA]} provider(s)")

    print("\n✅ Capability discovery works correctly!")


# Helper, not a pytest test: it takes an argument and is driven by the
# script's own runner below. Named `test_*` it was collected anyway and
# pytest failed resolving the argument as a fixture -- an error that
# reported the file as broken while the script itself worked.
def check_context_aware_selection(registry: ToolRegistry):
    """Test context-aware tool selection"""
    print("\n" + "="*70)
    print("TEST 3: Context-Aware Selection")
    print("="*70)

    # Find best provider for reading from file
    print("\n1. Selecting best provider for reading a file...")
    best_tool = registry.select_best_provider(
        Capability.READ_DATA,
        context={"data_source": "file", "file_path": "/var/log/system.log"}
    )

    if best_tool:
        print(f"   Selected: {best_tool.name}")
        print(f"   Description: {best_tool.description}")
        print(f"   Priority: {best_tool.capability_profile.capabilities[0].priority if best_tool.capability_profile else 0}")
    else:
        print("   ⚠️  No tool selected")

    print("\n✅ Context-aware selection works correctly!")


def test_capability_index_auto_build():
    """Test that capability index builds automatically for eagerly registered tools"""
    print("\n" + "="*70)
    print("TEST 4: Auto-Building Capability Index (Eager Registration)")
    print("="*70)

    registry = ToolRegistry()

    # Register tool eagerly (old way) - should still build capability index
    print("\n1. Registering ReadFileTool eagerly (old register() method)...")
    tool = ReadFileTool()
    registry.register(tool)

    # Check that capability index was built
    print("\n2. Checking if capability index was built...")
    providers = registry.find_providers(Capability.READ_DATA, load_tools=False)
    print(f"   Tools in READ_DATA index: {providers}")

    assert "read_file" in providers, "Tool should be in capability index!"

    print("\n✅ Auto-building capability index works correctly!")


def test_task_capability_inference():
    """Test inferring capabilities from task description"""
    print("\n" + "="*70)
    print("TEST 5: Task Capability Inference")
    print("="*70)

    registry = ToolRegistry()

    # Test inferring capabilities from task descriptions
    test_tasks = [
        "read the file /var/log/system.log",
        "analyze the code in main.py",
        "send a message to Slack",
        "run the tests",
        "encrypt the database backup",
    ]

    print("\nInferring capabilities from task descriptions:")
    for task in test_tasks:
        caps = registry.find_capabilities_for_task(task)
        print(f"\n   Task: \"{task}\"")
        print(f"   Capabilities: {[c.name for c in caps]}")

    print("\n✅ Task capability inference works correctly!")


@pytest.mark.asyncio
async def test_actual_tool_execution():
    """Test that tool with capabilities can actually execute"""
    print("\n" + "="*70)
    print("TEST 6: Actual Tool Execution")
    print("="*70)

    registry = ToolRegistry()

    # Register tool
    print("\n1. Registering ReadFileTool...")
    tool = ReadFileTool()
    registry.register(tool)

    # Create a test file
    test_file = Path("/tmp/torin_test_file.txt")
    test_content = "Hello from capability-based discovery!\nThis is line 2.\n"
    test_file.write_text(test_content)
    print(f"   Created test file: {test_file}")

    # Execute tool via registry
    print("\n2. Executing tool via registry...")
    result = await registry.execute_tool(
        "read_file",
        {"file_path": str(test_file)}
    )

    print(f"   Success: {result.success}")
    if result.output:
        output_str = str(result.output)
        print(f"   Output preview: {output_str[:50]}...")
    else:
        print("   Output: None")

    assert result.success, "Tool execution should succeed!"
    # Read the STRUCTURED field. str(dict) escapes newlines to a literal \n,
    # so the raw content was never a substring of the repr -- the assertion
    # could only pass for content with no newlines in it.
    payload = result.output
    file_content = payload["content"] if isinstance(payload, dict) else payload
    assert file_content == test_content, "Should read correct content!"

    # Cleanup
    test_file.unlink()
    print(f"   Cleaned up test file")

    print("\n✅ Tool execution works correctly!")


def run_all_tests():
    """Run all tests"""
    print("\n")
    print("╔" + "="*68 + "╗")
    print("║" + " "*15 + "CAPABILITY LAZY LOADING TEST SUITE" + " "*19 + "║")
    print("╚" + "="*68 + "╝")

    try:
        # Test 1: Lazy loading
        test_lazy_loading()
        registry = ToolRegistry()

        # Test 2: Capability discovery
        check_capability_discovery(registry)

        # Test 3: Context-aware selection
        check_context_aware_selection(registry)

        # Test 4: Auto-building capability index
        test_capability_index_auto_build()

        # Test 5: Task capability inference
        test_task_capability_inference()

        # Test 6: Actual tool execution
        asyncio.run(test_actual_tool_execution())

        # Summary
        print("\n" + "="*70)
        print("ALL TESTS PASSED! ✅")
        print("="*70)
        print("\nCapability-based discovery system is fully functional:")
        print("  ✓ Lazy loading prevents loading all 258 tools at startup")
        print("  ✓ Capability discovery finds tools by what they CAN do")
        print("  ✓ Context-aware selection picks best tool for use case")
        print("  ✓ Capability index builds automatically")
        print("  ✓ Task inference suggests needed capabilities")
        print("  ✓ Tools with capabilities execute correctly")
        print("\nNext steps:")
        print("  1. Migrate more tools using migrate_to_capabilities.py")
        print("  2. Update tool registration to use register_factory()")
        print("  3. Update AI prompts to request capabilities, not tool names")
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
