#!/usr/bin/env python3
"""
Update all test files to add verbose output
"""
import re
from pathlib import Path

# The verbose try-except block to replace with
VERBOSE_TRY_EXCEPT = '''        try:
            print(f"\\n{'='*80}")
            print(f"[{idx:3d}/{len(TOOLLIST)}] Testing: {tool_name}")
            print(f"{'='*80}")
            print(f"PROMPT: {prompt}")
            print(f"{'-'*80}")

            result = await executor.execute_task(task)

            success = result.get('success', False)
            summary = result.get('summary', 'No summary')
            tool_calls = result.get('tool_results', [])
            tools_used = [tc['tool'] for tc in tool_calls]
            used_correct = tool_name in tools_used

            print(f"LLM SUMMARY: {summary}")
            print(f"\\nTOOLS CALLED: {tools_used}")
            print(f"EXPECTED TOOL: {tool_name}")
            print(f"CORRECT TOOL USED: {used_correct}")

            if tool_calls:
                print(f"\\nTOOL EXECUTION DETAILS:")
                for tc in tool_calls:
                    print(f"  - Tool: {tc.get('tool', 'unknown')}")
                    print(f"    Params: {tc.get('parameters', {})}")
                    print(f"    Success: {tc.get('success', False)}")
                    if tc.get('output'):
                        print(f"    Output: {str(tc.get('output'))[:200]}")
                    if tc.get('error'):
                        print(f"    Error: {tc.get('error')}")

            if used_correct and success:
                results["passed"] += 1
                status = "✓ PASS"
                print(f"\\n{status}")
            else:
                results["failed"] += 1
                status = "✗ FAIL"
                print(f"\\n{status}")
                if not used_correct:
                    print(f"REASON: LLM chose wrong tool(s): {tools_used}")
                if not success:
                    print(f"REASON: Task failed - {result.get('error', 'Unknown error')}")

            results["details"].append({
                "tool": tool_name,
                "prompt": prompt,
                "used_correct": used_correct,
                "success": success,
                "tools_used": tools_used,
                "summary": summary
            })

        except Exception as e:
            results["failed"] += 1
            print(f"\\n✗ EXCEPTION: {str(e)}")
            import traceback
            traceback.print_exc()
            results["details"].append({
                "tool": tool_name,
                "error": str(e)
            })'''

test_files = [
    "test_execution_tools.py",
    "test_network_tools.py",
    "test_code_analysis_tools.py",
    "test_code_generation_tools.py",
    "test_security_tools.py",
    "test_documentation_tools.py",
    "test_testing_tools.py",
    "test_research_tools.py",
    "test_data_processing_tools.py",
    "test_monitoring_tools.py",
    "test_mlai_tools.py",
    "test_system_tools.py",
    "test_communication_tools.py",
    "test_config_environment_tools.py"
]

tests_dir = Path(__file__).parent

for test_file in test_files:
    file_path = tests_dir / test_file
    if not file_path.exists():
        print(f"Skipping {test_file} (not found)")
        continue

    print(f"Updating {test_file}...")

    content = file_path.read_text()

    # Find the tool list variable name
    tool_list_match = re.search(r'(\w+_tools)\s*=\s*\[', content)
    if not tool_list_match:
        print(f"  ✗ Could not find tool list in {test_file}")
        continue

    tool_list_name = tool_list_match.group(1)

    # Replace the try-except block
    pattern = r'        try:\n            result = await executor\.execute_task\(task\).*?except Exception as e:.*?\})\n'

    replacement = VERBOSE_TRY_EXCEPT.replace('TOOLLIST', tool_list_name)

    # Use a more specific pattern to match the entire try-except block
    old_pattern = re.compile(
        r'(        try:\n)'
        r'(            result = await executor\.execute_task\(task\).*?)'
        r'(        except Exception as e:.*?'
        r'            results\["details"\]\.append\(\{.*?\}\))',
        re.DOTALL
    )

    if old_pattern.search(content):
        content = old_pattern.sub(replacement, content)
        file_path.write_text(content)
        print(f"  ✓ Updated {test_file}")
    else:
        print(f"  ✗ Could not match pattern in {test_file}")

print("\nDone!")
