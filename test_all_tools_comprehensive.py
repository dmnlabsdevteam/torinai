#!/usr/bin/env python3
"""
COMPREHENSIVE TOOL TEST - NO STUBS, NO SKIPPING
Tests ALL 228 tools with proper parameters
"""

import asyncio
import sys
import json
import os
from pathlib import Path
from typing import Dict, Any, List

# Add TorinAI to path
sys.path.insert(0, str(Path(__file__).parent))


async def test_all_tools_comprehensive():
    """Test EVERY SINGLE tool in the registry with real parameters"""

    print("=" * 80)
    print("COMPREHENSIVE TOOL TEST - ALL 228 TOOLS")
    print("=" * 80)

    results = {
        "total_tools": 0,
        "tested": 0,
        "passed": 0,
        "failed": 0,
        "parameter_errors": 0,
        "execution_errors": 0,
        "failures": [],
        "successes": []
    }

    # Import tool registry
    print("\n[SETUP] Importing tool registry...")
    try:
        from core.tools.tool_registry import get_tool_registry
        tool_registry = get_tool_registry()
        tools = tool_registry.list_tools()
        results["total_tools"] = len(tools)
        print(f"✓ Found {len(tools)} tools")
    except Exception as e:
        print(f"✗ FATAL: Failed to import tool registry: {e}")
        return results

    # Test data directory
    test_dir = Path("/Users/stefan/Dominion Labs/TorinAI/data/tool_tests")
    test_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n[INFO] Testing ALL {len(tools)} tools with real parameters...")
    print(f"[INFO] Test directory: {test_dir}")
    print("=" * 80)

    # Test each tool
    for idx, tool in enumerate(tools, 1):
        tool_name = tool.name

        # Progress indicator every 20 tools
        if idx % 20 == 0:
            print(f"\n[PROGRESS] Tested {idx}/{len(tools)} tools ({results['passed']} passed, {results['failed']} failed)...")

        # Generate test parameters based on tool definition
        try:
            test_params = generate_test_parameters(tool, test_dir)
        except Exception as e:
            results["tested"] += 1
            results["failed"] += 1
            results["parameter_errors"] += 1
            results["failures"].append({
                "tool": tool_name,
                "error_type": "parameter_generation",
                "error": str(e)
            })
            print(f"  [{idx:3d}] ✗ FAIL: {tool_name:40s} - Param gen: {str(e)[:40]}")
            continue

        # Execute the tool
        try:
            result = await tool_registry.execute_tool(tool_name, test_params)

            results["tested"] += 1

            if result.success:
                results["passed"] += 1
                results["successes"].append({
                    "tool": tool_name,
                    "parameters": test_params,
                    "output_preview": str(result.output)[:100] if result.output else "None"
                })
                print(f"  [{idx:3d}] ✓ PASS: {tool_name:40s}")
            else:
                results["failed"] += 1

                # Categorize the error
                error_msg = result.error or "No error message"
                if "validation failed" in error_msg.lower():
                    results["parameter_errors"] += 1
                    error_type = "parameter_validation"
                else:
                    results["execution_errors"] += 1
                    error_type = "execution"

                results["failures"].append({
                    "tool": tool_name,
                    "error_type": error_type,
                    "parameters": test_params,
                    "error": error_msg,
                    "output": str(result.output) if result.output else "None"
                })
                print(f"  [{idx:3d}] ✗ FAIL: {tool_name:40s} - {error_msg[:40]}")

        except Exception as e:
            results["tested"] += 1
            results["failed"] += 1
            results["execution_errors"] += 1
            results["failures"].append({
                "tool": tool_name,
                "error_type": "exception",
                "parameters": test_params,
                "error": str(e),
                "exception_type": type(e).__name__
            })
            print(f"  [{idx:3d}] ✗ FAIL: {tool_name:40s} - Exception: {str(e)[:40]}")

    return results


def generate_test_parameters(tool, test_dir: Path) -> Dict[str, Any]:
    """
    Generate valid test parameters for a tool based on its parameter definitions.
    NO STUBS - real parameters only!
    """
    params = {}

    for param in tool.parameters:
        param_name = param.name
        param_type = param.type
        required = param.required
        default = param.default
        enum = param.enum

        # Use default if available
        if not required and default is not None:
            params[param_name] = default
            continue

        # Generate based on type and name
        if param_type == "string":
            if enum:
                params[param_name] = enum[0]  # Use first enum value
            elif "path" in param_name.lower() or "file" in param_name.lower():
                if "directory" in param_name.lower():
                    params[param_name] = str(test_dir / f"test_{tool.name}_dir")
                else:
                    params[param_name] = str(test_dir / f"test_{tool.name}.txt")
            elif "url" in param_name.lower():
                params[param_name] = "https://example.com/test"
            elif "email" in param_name.lower():
                params[param_name] = "test@example.com"
            elif "command" in param_name.lower():
                params[param_name] = "echo test"
            elif "query" in param_name.lower() or "search" in param_name.lower():
                params[param_name] = "test query"
            elif "content" in param_name.lower() or "text" in param_name.lower():
                params[param_name] = "Test content for tool execution"
            elif "message" in param_name.lower():
                params[param_name] = "Test message"
            elif "name" in param_name.lower():
                params[param_name] = "test_name"
            elif "pattern" in param_name.lower():
                params[param_name] = "*.txt"
            elif "mode" in param_name.lower():
                params[param_name] = "write" if enum and "write" in enum else default or "w"
            elif "encoding" in param_name.lower():
                params[param_name] = "utf-8"
            elif "algorithm" in param_name.lower():
                params[param_name] = "sha256"
            elif "format" in param_name.lower():
                params[param_name] = enum[0] if enum else "json"
            elif "key" in param_name.lower():
                params[param_name] = "test_key"
            elif "value" in param_name.lower():
                params[param_name] = "test_value"
            elif "address" in param_name.lower():
                params[param_name] = "0x0000000000000000000000000000000000000000"
            elif "description" in param_name.lower():
                params[param_name] = "Test description"
            else:
                params[param_name] = "test_value"

        elif param_type == "number":
            if "port" in param_name.lower():
                params[param_name] = 8080
            elif "timeout" in param_name.lower():
                params[param_name] = 30
            elif "max" in param_name.lower() or "limit" in param_name.lower():
                params[param_name] = 100
            elif "chunk" in param_name.lower():
                params[param_name] = 65536
            elif "line" in param_name.lower():
                params[param_name] = 1
            elif param.min_value is not None:
                params[param_name] = param.min_value
            else:
                params[param_name] = 10

        elif param_type == "boolean":
            if "create" in param_name.lower() or "parents" in param_name.lower():
                params[param_name] = True
            elif "recursive" in param_name.lower():
                params[param_name] = False
            elif "delete" in param_name.lower() or "confirm" in param_name.lower():
                params[param_name] = False  # Safety first
            elif "allow" in param_name.lower() or "enable" in param_name.lower():
                params[param_name] = True
            elif "preserve" in param_name.lower():
                params[param_name] = True
            elif "must_exist" in param_name.lower():
                params[param_name] = False
            else:
                params[param_name] = False

        elif param_type == "array":
            if "roots" in param_name.lower():
                params[param_name] = ["/Users"]
            elif "files" in param_name.lower() or "paths" in param_name.lower():
                params[param_name] = [str(test_dir / "test1.txt"), str(test_dir / "test2.txt")]
            elif "tags" in param_name.lower():
                params[param_name] = ["test", "sample"]
            elif "headers" in param_name.lower():
                params[param_name] = []
            else:
                params[param_name] = []

        elif param_type == "object":
            if "metadata" in param_name.lower():
                params[param_name] = {"test": "value"}
            elif "headers" in param_name.lower():
                params[param_name] = {"Content-Type": "application/json"}
            elif "data" in param_name.lower():
                params[param_name] = {"key": "value"}
            elif "config" in param_name.lower():
                params[param_name] = {}
            else:
                params[param_name] = {}

    return params


async def main():
    results = await test_all_tools_comprehensive()

    print("\n" + "=" * 80)
    print("COMPREHENSIVE TEST RESULTS")
    print("=" * 80)
    print(f"Total Tools:       {results['total_tools']}")
    print(f"Tools Tested:      {results['tested']}")
    print(f"✓ Passed:          {results['passed']}")
    print(f"✗ Failed:          {results['failed']}")
    print(f"  ↳ Param Errors:  {results['parameter_errors']}")
    print(f"  ↳ Exec Errors:   {results['execution_errors']}")

    if results['tested'] > 0:
        pass_rate = (results['passed'] / results['tested']) * 100
        print(f"\nPass Rate:         {pass_rate:.1f}%")

    # Show parameter validation failures
    param_failures = [f for f in results['failures'] if f['error_type'] == 'parameter_validation']
    if param_failures:
        print("\n" + "=" * 80)
        print(f"PARAMETER VALIDATION FAILURES ({len(param_failures)} tools)")
        print("=" * 80)
        for failure in param_failures[:30]:  # Show first 30
            print(f"\n✗ {failure['tool']}")
            print(f"  Parameters: {failure['parameters']}")
            print(f"  Error: {failure['error']}")

    # Show execution failures
    exec_failures = [f for f in results['failures'] if f['error_type'] in ['execution', 'exception']]
    if exec_failures:
        print("\n" + "=" * 80)
        print(f"EXECUTION FAILURES ({len(exec_failures)} tools)")
        print("=" * 80)
        for failure in exec_failures[:30]:  # Show first 30
            print(f"\n✗ {failure['tool']}")
            print(f"  Parameters: {failure['parameters']}")
            print(f"  Error: {failure['error']}")

    # Save detailed results
    output_file = Path("/Users/stefan/Dominion Labs/TorinAI/data/comprehensive_tool_test_results.json")
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with open(output_file, 'w') as f:
        json.dump(results, f, indent=2, default=str)

    print(f"\n✓ Detailed results saved to: {output_file}")
    print("=" * 80)

    return results['failed'] == 0


if __name__ == "__main__":
    try:
        success = asyncio.run(main())
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\nTest interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\nFATAL ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
