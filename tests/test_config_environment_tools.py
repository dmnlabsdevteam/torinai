#!/usr/bin/env python3
"""
Test suite for ALL config/environment tools - REAL LLM USAGE with TestBase
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


class ConfigEnvironmentToolsTests(TestBase):
    """Config/environment tools test suite with LLM execution"""

    def __init__(self):
        super().__init__(
            test_category="tool_execution",
            test_type="config_environment_tools"
        )
        self.llm = None
        self.executor = None

        self.config_env_tools = [
            "set_environment_variable",
            "get_environment_variable",
            "modify_config_file",
            "reload_config",
            "check_dependencies",
            "update_system",
            "manage_docker"
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
        """Run all config/environment tool tests"""
        await self.setup_llm()

        try:
            for idx, tool_name in enumerate(self.config_env_tools, 1):
                # Generate prompt for this tool
                if "set_environment" in tool_name:
                    prompt = f"Use {tool_name} to set environment variable TEST_VAR to 'test_value'"
                elif "get_environment" in tool_name:
                    prompt = f"Use {tool_name} to get value of PATH environment variable"
                elif "modify_config" in tool_name:
                    prompt = f"Use {tool_name} to modify config file at /Users/stefan/Dominion Labs/TorinAI/config.yaml, set the key 'llm.model_name' to 'test-model'"
                elif "reload_config" in tool_name:
                    prompt = f"Use {tool_name} to reload the TorinAI configuration. The tool takes no parameters, just call it once and return the result."
                elif "check_dependencies" in tool_name:
                    prompt = f"Use {tool_name} to check project dependencies"
                elif "update_system" in tool_name:
                    prompt = f"Use {tool_name} to update system packages"
                elif "manage_docker" in tool_name:
                    prompt = f"Use {tool_name} to list docker containers"
                else:
                    prompt = f"Use {tool_name} for config/environment operation"

                print(f"\n[{idx:3d}/{len(self.config_env_tools)}] Testing: {tool_name}")
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
                        "category": "config_environment",
                        "tool_name": tool_name,
                        "prompt": prompt
                    }
                )

        finally:
            await self.teardown_llm()


async def main():
    """Main test runner"""
    print("\n" + "=" * 80)
    print("CONFIG/ENVIRONMENT TOOLS TEST WITH LLM (TestBase Integration)")
    print("=" * 80)

    tests = ConfigEnvironmentToolsTests()
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
