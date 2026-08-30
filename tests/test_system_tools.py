#!/usr/bin/env python3
"""
Test suite for ALL system tools - REAL LLM USAGE with TestBase
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))

from test_base import TestBase
from core.services.unified_llm import get_llm_service
from core.agents.autonomous.general_purpose_executor import GeneralPurposeExecutor
from core.agents.autonomous.shared_types import Task, TaskType, Priority


class SystemToolsTests(TestBase):
    """System tools test suite with LLM execution"""

    def __init__(self):
        super().__init__(
            test_category="tool_execution",
            test_type="system_tools"
        )
        self.llm = None
        self.executor = None

        self.system_tools = [
            "clipboard",
            "notification",
            "system_info",
            "file_watcher"
        ]

    async def setup_llm(self):
        """Initialize LLM and executor"""
        print("\n[SETUP] Loading LLM...")
        self.llm = get_llm_service()
        await self.llm.initialize()
        self.executor = GeneralPurposeExecutor(torin_brain=self.llm)
        await self.executor.initialize()
        print("✓ LLM loaded and executor initialized")

    async def teardown_llm(self):
        """Cleanup LLM"""
        if self.llm and hasattr(self.llm, 'shutdown'):
            await self.llm.shutdown()

    async def run_all_tests(self):
        """Run all system tool tests"""
        await self.setup_llm()

        try:
            for idx, tool_name in enumerate(self.system_tools, 1):
                # Generate prompt for this tool
                if "clipboard" in tool_name:
                    prompt = f"Use {tool_name} to copy text 'test clipboard' to system clipboard"
                elif "notification" in tool_name:
                    prompt = f"Use {tool_name} to show notification with title 'Test' and message 'Test notification'"
                elif "system_info" in tool_name:
                    prompt = f"Use {tool_name} to get system information"
                elif "file_watcher" in tool_name:
                    prompt = f"Use {tool_name} to watch directory /Users/stefan/Dominion Labs/TorinAI/data for changes"
                else:
                    prompt = f"Use {tool_name} for system operation"

                print(f"\n[{idx:3d}/{len(self.system_tools)}] Testing: {tool_name}")
                print(f"PROMPT: {prompt}")

                task = Task(
                    id=f"test_{tool_name}",
                    type=TaskType.EXECUTION,
                    description=prompt,
                    priority=Priority.HIGH
                )

                async def test_func(t=task, tn=tool_name):
                    result = await self.executor.execute_task(t)

                    success = result.get('success', False)
                    tool_calls = result.get('tool_results', [])
                    tools_used = [tc['tool'] for tc in tool_calls]
                    used_correct = tn in tools_used

                    print(f"LLM SUMMARY: {result.get('summary', 'No summary')}")
                    print(f"TOOLS CALLED: {tools_used}")
                    print(f"SUCCESS: {success}")

                    assert used_correct, f"LLM chose wrong tool(s): {tools_used}, expected {tn}"
                    assert success, f"Task failed - {result.get('error', 'Unknown error')}"
                    return result

                await self.run_test(
                    test_name=f"test_{tool_name}",
                    test_func=test_func,
                    metadata={
                        "description": f"Test {tool_name} tool via LLM execution",
                        "category": "system",
                        "tool_name": tool_name,
                        "prompt": prompt
                    }
                )

        finally:
            await self.teardown_llm()


async def main():
    """Main test runner"""
    print("\n" + "=" * 80)
    print("SYSTEM TOOLS TEST WITH LLM (TestBase Integration)")
    print("=" * 80)

    tests = SystemToolsTests()
    await tests.start_session()
    await tests.run_all_tests()
    await tests.end_session()
    tests.print_summary()

    return 0 if tests.failed_tests == 0 else 1


if __name__ == "__main__":
    try:
        exit_code = asyncio.run(main())
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\nInterrupted")
        sys.exit(1)
