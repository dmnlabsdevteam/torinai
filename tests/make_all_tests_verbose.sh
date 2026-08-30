#!/bin/bash

# Make all test files verbose

cd "$(dirname "$0")"

for file in test_*_tools.py; do
    if [ "$file" = "test_filesystem_tools.py" ]; then
        echo "Skipping $file (already updated)"
        continue
    fi

    if [ ! -f "$file" ]; then
        continue
    fi

    echo "Updating $file..."

    # Create Python script to do the replacement
    python3 << 'PYTHON_SCRIPT'
import sys
import re

file = sys.argv[1]

with open(file, 'r') as f:
    content = f.content()

# Find the tool list variable name
tool_list_match = re.search(r'(\w+_tools)\s*=\s*\[', content)
if not tool_list_match:
    print(f"  ✗ Could not find tool list in {file}")
    sys.exit(1)

tool_list_name = tool_list_match.group(1)

# Pattern to match the old try-except block
old_pattern = re.compile(
    r'(\s+)try:\n'
    r'\1    result = await executor\.execute_task\(task\)\n'
    r'(.*?)'
    r'\1except Exception as e:\n'
    r'\1    results\["failed"\] \+= 1\n'
    r'(.*?)'
    r'\1    print\(f"  \[\{idx:3d\}\] ✗ ERR:.*?\n',
    re.DOTALL
)

new_block = f'''        try:
            print(f"\\n{{'='*80}}")
            print(f"[{{idx:3d}}/{{len({tool_list_name})}}] Testing: {{tool_name}}")
            print(f"{{'='*80}}")
            print(f"PROMPT: {{prompt}}")
            print(f"{{'-'*80}}")

            result = await executor.execute_task(task)

            success = result.get('success', False)
            summary = result.get('summary', 'No summary')
            tool_calls = result.get('tool_results', [])
            tools_used = [tc['tool'] for tc in tool_calls]
            used_correct = tool_name in tools_used

            print(f"LLM SUMMARY: {{summary}}")
            print(f"\\nTOOLS CALLED: {{tools_used}}")
            print(f"EXPECTED TOOL: {{tool_name}}")
            print(f"CORRECT TOOL USED: {{used_correct}}")

            if tool_calls:
                print(f"\\nTOOL EXECUTION DETAILS:")
                for tc in tool_calls:
                    print(f"  - Tool: {{tc.get('tool', 'unknown')}}")
                    print(f"    Params: {{tc.get('parameters', {{}})}}")
                    print(f"    Success: {{tc.get('success', False)}}")
                    if tc.get('output'):
                        print(f"    Output: {{str(tc.get('output'))[:200]}}")
                    if tc.get('error'):
                        print(f"    Error: {{tc.get('error')}}")

            if used_correct and success:
                results["passed"] += 1
                status = "✓ PASS"
                print(f"\\n{{status}}")
            else:
                results["failed"] += 1
                status = "✗ FAIL"
                print(f"\\n{{status}}")
                if not used_correct:
                    print(f"REASON: LLM chose wrong tool(s): {{tools_used}}")
                if not success:
                    print(f"REASON: Task failed - {{result.get('error', 'Unknown error')}}")

            results["details"].append({{
                "tool": tool_name,
                "prompt": prompt,
                "used_correct": used_correct,
                "success": success,
                "tools_used": tools_used,
                "summary": summary
            }})

        except Exception as e:
            results["failed"] += 1
            print(f"\\n✗ EXCEPTION: {{str(e)}}")
            import traceback
            traceback.print_exc()
            results["details"].append({{
                "tool": tool_name,
                "error": str(e)
            }})
'''

content = old_pattern.sub(new_block, content)

with open(file, 'w') as f:
    f.write(content)

print(f"  ✓ Updated {file}")
PYTHON_SCRIPT
 "$file"

done

echo "Done!"
