#!/usr/bin/env python3
"""
Critical Test: Can the LLM generate tool calls in the expected format?
This is the core issue causing task failures.
"""

import asyncio
import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

async def main():
    print("=" * 80)
    print("CRITICAL TEST: LLM Tool Calling Format")
    print("=" * 80)

    # Import and get LLM
    from core.services.unified_llm import get_llm_service
    from core.tools.tool_registry import get_tool_registry

    llm = get_llm_service()
    tool_registry = get_tool_registry()
    tools = tool_registry.list_tools()

    print(f"\n✓ LLM Service loaded")
    print(f"✓ Tool Registry loaded ({len(tools)} tools)")

    # Initialize if needed
    if hasattr(llm, 'initialize'):
        try:
            await llm.initialize()
            print(f"✓ LLM initialized")
        except Exception as e:
            print(f"⚠ LLM init error (continuing anyway): {e}")

    # Create tool list for first 20 tools
    sample_tools = tools[:20]
    tool_descriptions = []
    for tool in sample_tools:
        desc = f"- {tool.name}: {tool.description if hasattr(tool, 'description') else 'No description'}"
        tool_descriptions.append(desc)
    tool_list = "\n".join(tool_descriptions)

    # Test 1: Can LLM follow JSON format instructions?
    print("\n" + "=" * 80)
    print("TEST 1: Basic JSON Format Following")
    print("=" * 80)

    basic_prompt = """Respond with ONLY this JSON (no other text, no markdown):
{"status": "understood", "test": "pass"}"""

    print(f"\nPrompt: {basic_prompt}")
    response = await llm.generate(basic_prompt, max_tokens=100, temperature=0.0)
    content = response.get('content', response.get('text', ''))
    print(f"\nResponse:\n{content}\n")

    try:
        # Try to extract JSON
        if '```json' in content:
            json_str = content.split('```json')[1].split('```')[0].strip()
        elif '```' in content:
            json_str = content.split('```')[1].split('```')[0].strip()
        elif '{' in content:
            start = content.find('{')
            end = content.rfind('}') + 1
            json_str = content[start:end]
        else:
            json_str = content

        parsed = json.loads(json_str)
        print(f"✓ JSON parsed successfully: {parsed}")
        if parsed.get('status') == 'understood':
            print("✓ TEST 1 PASSED: LLM can follow JSON format")
        else:
            print("✗ TEST 1 FAILED: Wrong JSON content")
    except Exception as e:
        print(f"✗ TEST 1 FAILED: Cannot parse JSON - {e}")

    # Test 2: Can LLM generate tool_calls format?
    print("\n" + "=" * 80)
    print("TEST 2: Tool Call Format Generation")
    print("=" * 80)

    tool_prompt = f"""You are an autonomous AI agent. You have access to these tools:

AVAILABLE TOOLS:
{tool_list}

TASK: List all files in the /Users/stefan/Dominion Labs/TorinAI/data directory

To use a tool, respond with JSON in EXACTLY this format (no other text):
{{
    "reasoning": "why you need this tool",
    "tool_calls": [
        {{"tool": "tool_name", "parameters": {{"param_name": "param_value"}}}}
    ]
}}

Respond now with the tool call:"""

    print(f"\nPrompt sent to LLM (showing first 500 chars):")
    print(tool_prompt[:500] + "...")

    response = await llm.generate(tool_prompt, max_tokens=500, temperature=0.0)
    content = response.get('content', response.get('text', ''))

    print(f"\nFull LLM Response:")
    print("-" * 80)
    print(content)
    print("-" * 80)

    # Analyze response
    has_tool_calls = 'tool_calls' in content
    has_json_braces = '{' in content and '}' in content
    has_reasoning = 'reasoning' in content

    print(f"\nAnalysis:")
    print(f"  - Contains 'tool_calls': {has_tool_calls}")
    print(f"  - Contains JSON braces: {has_json_braces}")
    print(f"  - Contains 'reasoning': {has_reasoning}")

    # Try to parse
    try:
        if '```json' in content:
            json_str = content.split('```json')[1].split('```')[0].strip()
        elif '```' in content:
            json_str = content.split('```')[1].split('```')[0].strip()
        elif '{' in content:
            start = content.find('{')
            end = content.rfind('}') + 1
            json_str = content[start:end]
        else:
            raise ValueError("No JSON found in response")

        parsed = json.loads(json_str)
        print(f"\n✓ Parsed JSON:")
        print(json.dumps(parsed, indent=2))

        if 'tool_calls' in parsed and isinstance(parsed['tool_calls'], list) and len(parsed['tool_calls']) > 0:
            print(f"\n✓✓ TEST 2 PASSED: LLM generated proper tool_calls format!")
            print(f"   Tool requested: {parsed['tool_calls'][0].get('tool')}")
            print(f"   Reasoning: {parsed.get('reasoning', 'N/A')}")
        else:
            print(f"\n✗ TEST 2 FAILED: JSON parsed but no valid tool_calls array")
    except Exception as e:
        print(f"\n✗ TEST 2 FAILED: Cannot parse response as JSON - {e}")
        print(f"   This is the ROOT CAUSE of task failures!")
        print(f"   The LLM is generating text instead of JSON tool calls.")

    # Test 3: Try with more explicit instructions
    print("\n" + "=" * 80)
    print("TEST 3: Tool Call Format (Very Explicit Instructions)")
    print("=" * 80)

    explicit_prompt = """SYSTEM: You are an AI agent that MUST respond in JSON format.

AVAILABLE TOOLS:
- ListDirectoryTool: List files in a directory
- ReadFileTool: Read file contents
- WriteFileTool: Write content to a file

TASK: List files in /Users/stefan/Dominion Labs/TorinAI/data

CRITICAL INSTRUCTION: You MUST respond with ONLY valid JSON. No other text. No markdown. Just JSON.

REQUIRED JSON FORMAT:
{
    "reasoning": "I need to list files in the directory",
    "tool_calls": [
        {"tool": "ListDirectoryTool", "parameters": {"path": "/Users/stefan/Dominion Labs/TorinAI/data"}}
    ]
}

YOUR RESPONSE (JSON only):"""

    print("\nSending explicit prompt...")
    response = await llm.generate(explicit_prompt, max_tokens=300, temperature=0.0)
    content = response.get('content', response.get('text', ''))

    print(f"\nLLM Response:")
    print("-" * 80)
    print(content)
    print("-" * 80)

    # Try to parse
    try:
        if '```json' in content:
            json_str = content.split('```json')[1].split('```')[0].strip()
        elif '```' in content:
            json_str = content.split('```')[1].split('```')[0].strip()
        elif '{' in content:
            start = content.find('{')
            end = content.rfind('}') + 1
            json_str = content[start:end]
        else:
            json_str = content.strip()

        parsed = json.loads(json_str)
        print(f"\n✓ Parsed JSON successfully")

        if 'tool_calls' in parsed:
            print(f"✓✓ TEST 3 PASSED: Explicit instructions worked!")
        else:
            print(f"✗ TEST 3 FAILED: Still no tool_calls in response")
    except Exception as e:
        print(f"✗ TEST 3 FAILED: {e}")

    print("\n" + "=" * 80)
    print("DIAGNOSIS COMPLETE")
    print("=" * 80)

    return 0

if __name__ == "__main__":
    asyncio.run(main())
