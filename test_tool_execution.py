#!/usr/bin/env python3
"""
Comprehensive Tool Execution Test
Tests the entire tool-calling chain to find failures
"""

import asyncio
import sys
import json
from pathlib import Path

# Add TorinAI to path
sys.path.insert(0, str(Path(__file__).parent))

async def test_tool_execution():
    """Test tool execution end-to-end"""

    print("=" * 80)
    print("TORIN AI TOOL EXECUTION DIAGNOSTIC TEST")
    print("=" * 80)

    results = {
        "tests": [],
        "passed": 0,
        "failed": 0
    }

    # Test 1: Import tool registry
    print("\n[TEST 1] Importing tool registry...")
    try:
        from core.tools.tool_registry import get_tool_registry
        tool_registry = get_tool_registry()
        tools = tool_registry.list_tools()
        results["tests"].append({
            "name": "Import tool registry",
            "status": "PASS",
            "details": f"Found {len(tools)} tools"
        })
        results["passed"] += 1
        print(f"✓ PASS: {len(tools)} tools available")
    except Exception as e:
        results["tests"].append({
            "name": "Import tool registry",
            "status": "FAIL",
            "error": str(e)
        })
        results["failed"] += 1
        print(f"✗ FAIL: {e}")
        return results

    # Test 2: Import LLM service
    print("\n[TEST 2] Importing LLM service...")
    try:
        from core.services.unified_llm import get_llm_service
        llm = get_llm_service()
        results["tests"].append({
            "name": "Import LLM service",
            "status": "PASS",
            "details": f"LLM service: {type(llm)}"
        })
        results["passed"] += 1
        print(f"✓ PASS: LLM service available")
    except Exception as e:
        results["tests"].append({
            "name": "Import LLM service",
            "status": "FAIL",
            "error": str(e)
        })
        results["failed"] += 1
        print(f"✗ FAIL: {e}")
        return results

    # Test 3: Initialize LLM
    print("\n[TEST 3] Initializing LLM...")
    try:
        if hasattr(llm, 'initialize') and not getattr(llm, 'model_loaded', False):
            await llm.initialize()
        results["tests"].append({
            "name": "Initialize LLM",
            "status": "PASS",
            "details": f"Model loaded: {getattr(llm, 'model_loaded', 'Unknown')}"
        })
        results["passed"] += 1
        print(f"✓ PASS: LLM initialized")
    except Exception as e:
        results["tests"].append({
            "name": "Initialize LLM",
            "status": "FAIL",
            "error": str(e)
        })
        results["failed"] += 1
        print(f"✗ FAIL: {e}")
        return results

    # Test 4: Simple LLM generation (no tools)
    print("\n[TEST 4] Testing simple LLM generation...")
    try:
        response = await llm.generate(
            "Respond with exactly: TEST_SUCCESS",
            max_tokens=50,
            temperature=0.0
        )
        content = response.get('content', response.get('text', ''))
        success = 'TEST_SUCCESS' in content
        results["tests"].append({
            "name": "Simple LLM generation",
            "status": "PASS" if success else "WARN",
            "details": f"Response: {content[:100]}"
        })
        if success:
            results["passed"] += 1
        else:
            results["failed"] += 1
        print(f"{'✓ PASS' if success else '⚠ WARN'}: LLM responded: {content[:50]}")
    except Exception as e:
        results["tests"].append({
            "name": "Simple LLM generation",
            "status": "FAIL",
            "error": str(e)
        })
        results["failed"] += 1
        print(f"✗ FAIL: {e}")
        return results

    # Test 5: Test JSON parsing from LLM
    print("\n[TEST 5] Testing LLM JSON generation...")
    try:
        prompt = """Respond with ONLY this JSON (no other text):
{"test": "success", "value": 123}"""
        response = await llm.generate(prompt, max_tokens=100, temperature=0.0)
        content = response.get('content', response.get('text', ''))

        # Try to parse JSON from response
        if '```json' in content:
            json_str = content.split('```json')[1].split('```')[0].strip()
        elif '```' in content:
            json_str = content.split('```')[1].split('```')[0].strip()
        elif '{' in content and '}' in content:
            start = content.find('{')
            end = content.rfind('}') + 1
            json_str = content[start:end]
        else:
            json_str = content

        parsed = json.loads(json_str)
        success = parsed.get('test') == 'success'
        results["tests"].append({
            "name": "LLM JSON generation",
            "status": "PASS" if success else "WARN",
            "details": f"Parsed: {parsed}"
        })
        if success:
            results["passed"] += 1
        else:
            results["failed"] += 1
        print(f"{'✓ PASS' if success else '⚠ WARN'}: Parsed JSON: {parsed}")
    except Exception as e:
        results["tests"].append({
            "name": "LLM JSON generation",
            "status": "FAIL",
            "error": str(e),
            "raw_response": content[:200]
        })
        results["failed"] += 1
        print(f"✗ FAIL: {e}")
        print(f"   Raw response: {content[:200]}")

    # Test 6: Test tool format generation
    print("\n[TEST 6] Testing tool format generation...")
    try:
        # Get first 10 tools
        sample_tools = tools[:10]
        tool_list = "\n".join([f"- {t.name}: {t.description}" for t in sample_tools])

        prompt = f"""You have access to these tools:
{tool_list}

To use a tool, respond with JSON:
{{"tool_calls": [{{"tool": "tool_name", "parameters": {{"param": "value"}}}}]}}

Task: List all files in the current directory.
Choose the appropriate tool and respond with the JSON format."""

        response = await llm.generate(prompt, max_tokens=200, temperature=0.0)
        content = response.get('content', response.get('text', ''))

        # Check if response contains tool_calls
        has_tool_calls = 'tool_calls' in content
        has_json = '{' in content and '}' in content

        results["tests"].append({
            "name": "Tool format generation",
            "status": "PASS" if (has_tool_calls and has_json) else "FAIL",
            "details": f"Has tool_calls: {has_tool_calls}, Has JSON: {has_json}",
            "raw_response": content[:300]
        })
        if has_tool_calls and has_json:
            results["passed"] += 1
            print(f"✓ PASS: LLM generated tool call format")
        else:
            results["failed"] += 1
            print(f"✗ FAIL: LLM did not generate proper tool call")
        print(f"   Response preview: {content[:150]}...")
    except Exception as e:
        results["tests"].append({
            "name": "Tool format generation",
            "status": "FAIL",
            "error": str(e)
        })
        results["failed"] += 1
        print(f"✗ FAIL: {e}")

    # Test 7: Test actual tool execution via tool_registry
    print("\n[TEST 7] Testing actual tool execution via tool_registry...")
    try:
        # Use a simple tool with known parameters - WriteFile
        test_file_path = "/Users/stefan/Dominion Labs/TorinAI/data/test_tool_exec.txt"
        test_params = {
            "file_path": test_file_path,
            "content": "Tool execution test"
        }

        print(f"   Attempting to execute: write_file")
        result = await tool_registry.execute_tool("write_file", test_params)

        if result.success:
            results["tests"].append({
                "name": "Tool execution",
                "status": "PASS",
                "details": f"write_file executed successfully"
            })
            results["passed"] += 1
            print(f"✓ PASS: Tool executed successfully")
            # Clean up test file
            import os
            if os.path.exists(test_file_path):
                os.remove(test_file_path)
        else:
            results["tests"].append({
                "name": "Tool execution",
                "status": "FAIL",
                "details": f"Tool failed: {result.error}"
            })
            results["failed"] += 1
            print(f"✗ FAIL: Tool execution failed - {result.error}")
    except Exception as e:
        results["tests"].append({
            "name": "Tool execution",
            "status": "FAIL",
            "error": str(e)
        })
        results["failed"] += 1
        print(f"✗ FAIL: {e}")

    # Test 8: Test Task object creation
    print("\n[TEST 8] Testing Task object creation...")
    try:
        from core.agents.autonomous.shared_types import Task, TaskType, TaskStatus, Priority, TaskSource

        task = Task(
            id="test_task_001",
            type=TaskType.EXECUTION,
            description="Test task for diagnostic",
            priority=Priority.HIGH,
            status=TaskStatus.PENDING,
            source=TaskSource.MANUAL
        )

        # Check metadata attribute
        has_metadata = hasattr(task, 'metadata')
        metadata_type = type(task.metadata) if has_metadata else None

        results["tests"].append({
            "name": "Task object creation",
            "status": "PASS" if has_metadata else "FAIL",
            "details": f"Has metadata: {has_metadata}, Type: {metadata_type}"
        })
        if has_metadata:
            results["passed"] += 1
            print(f"✓ PASS: Task object has metadata attribute ({metadata_type})")
        else:
            results["failed"] += 1
            print(f"✗ FAIL: Task object missing metadata attribute")
    except Exception as e:
        results["tests"].append({
            "name": "Task object creation",
            "status": "FAIL",
            "error": str(e)
        })
        results["failed"] += 1
        print(f"✗ FAIL: {e}")

    # Test 9: Test general_purpose_executor import
    print("\n[TEST 9] Testing GeneralPurposeExecutor import...")
    try:
        from core.agents.autonomous.general_purpose_executor import GeneralPurposeExecutor
        executor = GeneralPurposeExecutor(torin_brain=llm)
        await executor.initialize()

        executor_active = getattr(executor, 'active', getattr(executor, 'initialized', 'Unknown'))
        results["tests"].append({
            "name": "GeneralPurposeExecutor import",
            "status": "PASS",
            "details": f"Executor status: {executor_active}"
        })
        results["passed"] += 1
        print(f"✓ PASS: Executor initialized (status: {executor_active})")
    except Exception as e:
        results["tests"].append({
            "name": "GeneralPurposeExecutor import",
            "status": "FAIL",
            "error": str(e)
        })
        results["failed"] += 1
        print(f"✗ FAIL: {e}")
        return results

    # Test 10: Test executor with simple task
    print("\n[TEST 10] Testing executor with simple task...")
    try:
        simple_task = Task(
            id="diagnostic_simple_task",
            type=TaskType.EXECUTION,
            description="Create a file at /Users/stefan/Dominion Labs/TorinAI/data/test_output.txt with content 'DIAGNOSTIC_TEST_SUCCESS'",
            priority=Priority.HIGH
        )

        print(f"   Executing task: {simple_task.description[:80]}...")

        # Enable debug logging
        import logging
        logging.getLogger('core.agents.autonomous.general_purpose_executor').setLevel(logging.INFO)

        result = await executor.execute_task(simple_task)

        success = result.get('success', False)
        error = result.get('error', 'No error')
        tool_results = result.get('tool_results', [])

        print(f"   Result: Success={success}, Tools executed={len(tool_results)}")
        if not tool_results:
            print(f"   ⚠️  WARNING: No tools were executed!")

        results["tests"].append({
            "name": "Executor simple task",
            "status": "PASS" if success else "FAIL",
            "details": f"Success: {success}, Error: {error}",
            "result": result
        })
        if success:
            results["passed"] += 1
            print(f"✓ PASS: Task executed successfully")
        else:
            results["failed"] += 1
            print(f"✗ FAIL: Task failed - {error}")
        print(f"   Full result: {json.dumps(result, indent=2, default=str)[:500]}")
    except Exception as e:
        results["tests"].append({
            "name": "Executor simple task",
            "status": "FAIL",
            "error": str(e)
        })
        results["failed"] += 1
        print(f"✗ FAIL: {e}")

    # Cleanup LLM to prevent event loop errors
    print("\n[CLEANUP] Shutting down LLM service...")
    try:
        if llm and hasattr(llm, 'shutdown'):
            await llm.shutdown()
            print("[CLEANUP] ✓ LLM shutdown complete")
    except Exception as e:
        print(f"[CLEANUP] ⚠ Shutdown error (non-critical): {e}")

    return results


async def main():
    results = await test_tool_execution()

    print("\n" + "=" * 80)
    print("DIAGNOSTIC RESULTS")
    print("=" * 80)
    print(f"Tests Passed: {results['passed']}")
    print(f"Tests Failed: {results['failed']}")
    print(f"Total Tests:  {results['passed'] + results['failed']}")
    print(f"Success Rate: {(results['passed'] / max(1, results['passed'] + results['failed']) * 100):.1f}%")

    # Save results to file
    output_file = Path("/Users/stefan/Dominion Labs/TorinAI/data/diagnostic_results.json")
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with open(output_file, 'w') as f:
        json.dump(results, f, indent=2, default=str)

    print(f"\n✓ Results saved to: {output_file}")
    print("=" * 80)

    return results['failed'] == 0


if __name__ == "__main__":
    try:
        success = asyncio.run(main())
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\nTest interrupted by user")
        sys.exit(1)
