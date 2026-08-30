#!/usr/bin/env python3
"""
Test ALL Tools with LLM
Loads LLM once, then tests every single tool
"""

import asyncio
import sys
import json
import logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))


def generate_prompt_for_tool(tool_name: str, tool) -> str:
    """Generate a prompt that will make the LLM use this specific tool"""

    # Get tool description
    desc = tool.description if hasattr(tool, 'description') else ""
    desc_lower = desc.lower()
    name_lower = tool_name.lower()

    # File operations
    if "read" in name_lower and "file" in name_lower:
        return f"Read the file /Users/stefan/Dominion Labs/TorinAI/test_tool_execution.py"
    if "write" in name_lower and "file" in name_lower:
        return f"Write 'test content' to /Users/stefan/Dominion Labs/TorinAI/data/test_{tool_name}.txt"
    if "append" in name_lower:
        return f"Append 'new line' to /Users/stefan/Dominion Labs/TorinAI/data/test_{tool_name}.txt"
    if "delete" in name_lower and "file" in name_lower:
        return f"Delete /Users/stefan/Dominion Labs/TorinAI/data/test_delete.txt (set confirm to false)"
    if "move" in name_lower or "rename" in name_lower:
        return f"Move /Users/stefan/Dominion Labs/TorinAI/data/src.txt to /Users/stefan/Dominion Labs/TorinAI/data/dst.txt"
    if "copy" in name_lower:
        return f"Copy /Users/stefan/Dominion Labs/TorinAI/data/src.txt to /Users/stefan/Dominion Labs/TorinAI/data/copy.txt"

    # Directory operations
    if "list" in name_lower and "dir" in name_lower:
        return f"List all files in /Users/stefan/Dominion Labs/TorinAI/data"
    if "create" in name_lower and "dir" in name_lower:
        return f"Create directory /Users/stefan/Dominion Labs/TorinAI/data/test_dir_{tool_name}"
    if "delete" in name_lower and "dir" in name_lower:
        return f"Delete directory /Users/stefan/Dominion Labs/TorinAI/data/test_del (set confirm to false)"

    # Search operations
    if "search" in name_lower or "find" in name_lower:
        return f"Search for .py files in /Users/stefan/Dominion Labs/TorinAI"
    if "grep" in name_lower:
        return f"Search for 'test' in files in /Users/stefan/Dominion Labs/TorinAI"

    # Path operations
    if "validate" in name_lower and "path" in name_lower:
        return f"Validate the path /Users/stefan/Dominion Labs/TorinAI/data"
    if "check" in name_lower and "exist" in name_lower:
        return f"Check if /Users/stefan/Dominion Labs/TorinAI exists"
    if "info" in name_lower or "stat" in name_lower:
        return f"Get information about /Users/stefan/Dominion Labs/TorinAI/test_tool_execution.py"

    # JSON operations
    if "json" in name_lower:
        if "read" in name_lower or "parse" in name_lower:
            return f"Read JSON from /Users/stefan/Dominion Labs/TorinAI/data/diagnostic_results.json"
        if "write" in name_lower:
            return f"Write {{\"test\": \"data\"}} to /Users/stefan/Dominion Labs/TorinAI/data/test_{tool_name}.json"

    # Compression
    if "compress" in name_lower or "zip" in name_lower or "archive" in name_lower:
        return f"Create a zip archive of /Users/stefan/Dominion Labs/TorinAI/data at /Users/stefan/Dominion Labs/TorinAI/data/test.zip"
    if "decompress" in name_lower or "extract" in name_lower or "unzip" in name_lower:
        return f"Extract /Users/stefan/Dominion Labs/TorinAI/data/test.zip to /Users/stefan/Dominion Labs/TorinAI/data/extracted"

    # Checksum/hash
    if "checksum" in name_lower or "hash" in name_lower or "sha" in name_lower or "md5" in name_lower:
        return f"Calculate checksum of /Users/stefan/Dominion Labs/TorinAI/test_tool_execution.py"

    # Duplicate detection
    if "duplicate" in name_lower:
        return f"Find duplicate files in /Users/stefan/Dominion Labs/TorinAI/data"

    # Sync
    if "sync" in name_lower:
        return f"Sync /Users/stefan/Dominion Labs/TorinAI/data to /Users/stefan/Dominion Labs/TorinAI/data_backup"

    # Network/HTTP
    if "http" in name_lower or "request" in name_lower or "fetch" in name_lower or "download" in name_lower:
        return f"Fetch data from https://example.com using {tool_name}"
    if "url" in name_lower:
        return f"Process URL https://example.com with {tool_name}"

    # Database
    if "database" in name_lower or "db" in name_lower or "sql" in name_lower or "query" in name_lower:
        return f"Use {tool_name} to query test database"

    # Execution
    if "execute" in name_lower or "run" in name_lower or "shell" in name_lower or "command" in name_lower:
        return f"Use {tool_name} to run command 'echo test'"
    if "python" in name_lower:
        return f"Use {tool_name} to execute python code: print('test')"

    # Communication
    if "email" in name_lower or "mail" in name_lower:
        return f"Use {tool_name} to send test email"
    if "slack" in name_lower or "message" in name_lower or "notify" in name_lower:
        return f"Use {tool_name} to send test message"

    # System
    if "system" in name_lower or "process" in name_lower:
        return f"Use {tool_name} to check system status"
    if "memory" in name_lower:
        return f"Use {tool_name} to check memory usage"
    if "cpu" in name_lower:
        return f"Use {tool_name} to check CPU usage"

    # macOS specific
    if "macos" in name_lower or "mac" in name_lower or "osx" in name_lower:
        return f"Use {tool_name} on macOS system"
    if "spotlight" in name_lower:
        return f"Use {tool_name} to search Spotlight"
    if "notification" in name_lower:
        return f"Use {tool_name} to show notification"

    # AI/ML
    if "model" in name_lower or "llm" in name_lower or "ai" in name_lower:
        return f"Use {tool_name} with test input"

    # Generic fallback - use description
    if desc:
        return f"Use {tool_name}: {desc[:100]}"

    # Final fallback
    return f"Use the {tool_name} tool with appropriate test parameters"


async def main():
    print("=" * 80)
    print("TEST ALL TOOLS WITH LLM")
    print("Load LLM once, test every tool")
    print("=" * 80)

    results = {
        "total_tools": 0,
        "tested": 0,
        "llm_chose_correct_tool": 0,
        "tool_succeeded": 0,
        "tool_failed": 0,
        "llm_chose_wrong_tool": 0,
        "details": []
    }

    # LOAD LLM ONCE
    print("\n[SETUP] Loading LLM (ONE TIME ONLY)...")
    try:
        from core.services.unified_llm import get_llm_service
        from core.tools.tool_registry import get_tool_registry
        from core.agents.autonomous.general_purpose_executor import GeneralPurposeExecutor
        from core.agents.autonomous.shared_types import Task, TaskType, Priority

        llm = get_llm_service()
        print("✓ LLM loaded")

        tool_registry = get_tool_registry()
        tools = tool_registry.list_tools()
        results["total_tools"] = len(tools)
        print(f"✓ Found {len(tools)} tools")

        executor = GeneralPurposeExecutor(torin_brain=llm)
        await executor.initialize()
        print("✓ Executor initialized with LLM")

        logging.getLogger('core.agents.autonomous.general_purpose_executor').setLevel(logging.WARNING)

    except Exception as e:
        print(f"✗ FATAL: {e}")
        import traceback
        traceback.print_exc()
        return 1

    print("\n" + "=" * 80)
    print(f"TESTING {len(tools)} TOOLS")
    print("=" * 80)

    # Test each tool
    for idx, tool in enumerate(tools, 1):
        tool_name = tool.name

        if idx % 20 == 0:
            print(f"\n[{idx}/{len(tools)}] Progress...")

        # Generate prompt
        prompt = generate_prompt_for_tool(tool_name)

        # Create task
        task = Task(
            id=f"test_{tool_name}",
            type=TaskType.EXECUTION,
            description=prompt,
            priority=Priority.HIGH
        )

        # Execute
        try:
            result = await executor.execute_task(task)

            success = result.get('success', False)
            tool_calls = result.get('tool_results', [])
            tools_used = [tc['tool'] for tc in tool_calls]

            # Check if correct tool was used
            used_correct = tool_name in tools_used
            tool_worked = False

            if used_correct:
                # Find the specific call for this tool
                for tc in tool_calls:
                    if tc['tool'] == tool_name:
                        tool_worked = tc.get('success', False)
                        break

            # Update counts
            results["tested"] += 1

            if used_correct:
                results["llm_chose_correct_tool"] += 1
                if tool_worked:
                    results["tool_succeeded"] += 1
                    status = "✓ PASS"
                else:
                    results["tool_failed"] += 1
                    status = "✗ FAIL"
            else:
                results["llm_chose_wrong_tool"] += 1
                status = "✗ WRONG"

            results["details"].append({
                "tool": tool_name,
                "prompt": prompt,
                "used_correct_tool": used_correct,
                "tool_succeeded": tool_worked,
                "tools_used": tools_used,
                "task_success": success
            })

            print(f"  [{idx:3d}] {status}: {tool_name:40s}")

        except Exception as e:
            results["tested"] += 1
            results["llm_chose_wrong_tool"] += 1
            results["details"].append({
                "tool": tool_name,
                "prompt": prompt,
                "error": str(e)
            })
            print(f"  [{idx:3d}] ✗ ERR: {tool_name:40s} - {str(e)[:30]}")

    # Cleanup
    print("\n[CLEANUP]...")
    try:
        if hasattr(llm, 'shutdown'):
            await llm.shutdown()
    except:
        pass

    # Results
    print("\n" + "=" * 80)
    print("RESULTS")
    print("=" * 80)
    print(f"Total Tools:        {results['total_tools']}")
    print(f"Tested:             {results['tested']}")
    print(f"LLM Chose Correct:  {results['llm_chose_correct_tool']}")
    print(f"Tool Succeeded:     {results['tool_succeeded']}")
    print(f"Tool Failed:        {results['tool_failed']}")
    print(f"LLM Chose Wrong:    {results['llm_chose_wrong_tool']}")

    if results['tested'] > 0:
        correct_rate = (results['llm_chose_correct_tool'] / results['tested']) * 100
        success_rate = (results['tool_succeeded'] / results['tested']) * 100
        print(f"\nCorrect Tool Rate:  {correct_rate:.1f}%")
        print(f"Success Rate:       {success_rate:.1f}%")

    # Show failures
    failed = [d for d in results['details'] if d.get('used_correct_tool') and not d.get('tool_succeeded')]
    if failed:
        print(f"\n{'=' * 80}")
        print(f"TOOL EXECUTION FAILURES ({len(failed)})")
        print(f"{'=' * 80}")
        for d in failed[:20]:
            print(f"✗ {d['tool']}: {d['prompt']}")

    wrong = [d for d in results['details'] if not d.get('used_correct_tool') and not d.get('error')]
    if wrong:
        print(f"\n{'=' * 80}")
        print(f"WRONG TOOL CHOICES ({len(wrong)})")
        print(f"{'=' * 80}")
        for d in wrong[:20]:
            print(f"✗ {d['tool']}: Used {', '.join(d.get('tools_used', []))}")

    # Save
    output = Path("/Users/stefan/Dominion Labs/TorinAI/data/all_tools_test_results.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    with open(output, 'w') as f:
        json.dump(results, f, indent=2, default=str)

    print(f"\n✓ Saved to: {output}")
    print("=" * 80)

    return 0 if (results['tool_failed'] == 0 and results['llm_chose_wrong_tool'] == 0) else 1


if __name__ == "__main__":
    try:
        exit_code = asyncio.run(main())
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\nInterrupted")
        sys.exit(1)
