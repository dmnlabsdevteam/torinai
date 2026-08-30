#!/usr/bin/env python3
"""
Test suite for ALL execution tools - REAL LLM USAGE with TestBase
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Add tests directory for test_base
tests_dir = Path(__file__).parent
sys.path.insert(0, str(tests_dir))

from test_base import TestBase
from core.services.unified_llm import get_llm_service
from core.agents.autonomous.general_purpose_executor import GeneralPurposeExecutor
from core.agents.autonomous.shared_types import Task, TaskType, Priority


class ExecutionToolsTests(TestBase):
    """Execution tools test suite with TestBase integration"""

    def __init__(self):
        super().__init__(
            test_category="tool_execution",
            test_type="execution_tools"
        )

        # Initialize LLM and executor
        self.llm = None
        self.executor = None

        # Execution tools to test
        self.execution_tools = [
            "run_python",
            "run_shell_command",
            "execute_sandbox",
            "list_processes",
            "kill_process",
            "start_service",
            "stop_service",
            "restart_service",
            "get_process_info",
            "run_background_task",
            "schedule_cron_job",
            "install_python_package",
            "execute_with_timeout",
            "execute_with_resource_limits",
            "execute_network_isolated",
            "execute_deterministic",
            "execute_with_artifact_capture"
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

    def _get_tool_prompt(self, tool_name: str) -> str:
        """Generate appropriate prompt for each tool"""
        import os
        if "run_python" in tool_name:
            return f"Use {tool_name} to execute python code: print('hello test')"
        elif "run_shell_command" in tool_name:
            return f"Use {tool_name} to run shell command: echo 'test'"
        elif "execute_sandbox" in tool_name:
            return f"Use {tool_name} to execute command in sandbox: ls"
        elif "list_processes" in tool_name:
            return f"Use {tool_name} to list all running processes"
        elif "kill_process" in tool_name:
            return f"Use {tool_name} to kill process with pid 1 (will fail with permission denied, which is expected)"
        elif "start_service" in tool_name:
            return f"Use {tool_name} to start the service named 'com.apple.Finder'"
        elif "stop_service" in tool_name:
            return f"Use {tool_name} to stop service named test_service"
        elif "restart_service" in tool_name:
            return f"Use {tool_name} to restart the service named 'com.apple.Finder'"
        elif "get_process_info" in tool_name:
            return f"Use {tool_name} to get info about process with pid {os.getpid()}"
        elif "run_background_task" in tool_name:
            return f"Use {tool_name} to run command 'sleep 1' in background"
        elif "schedule_cron_job" in tool_name:
            return f"Use {tool_name} to schedule the command 'echo test_cron' with schedule '0 0 * * *' (daily at midnight)"
        elif "install_python_package" in tool_name:
            return f"Use {tool_name} to install package requests"
        elif "execute_with_timeout" in tool_name:
            return f"Use {tool_name} with command 'echo hello' and hard_timeout of 5 seconds"
        elif "execute_with_resource_limits" in tool_name:
            return f"Use {tool_name} to execute the command 'print(\"test\")' with memory limit (max_memory_mb) of 100 and timeout of 60 seconds"
        elif "execute_network_isolated" in tool_name:
            return f"Use {tool_name} to execute command without network access"
        elif "execute_deterministic" in tool_name:
            return f"Use {tool_name} with code 'print(\"deterministic test\")' and seed 42"
        elif "execute_with_artifact_capture" in tool_name:
            return f"Use {tool_name} to execute and capture all artifacts"
        else:
            return f"Use {tool_name} to execute a command"

    async def test_tool_execution(self, tool_name: str):
        """Test a single execution tool with LLM"""
        prompt = self._get_tool_prompt(tool_name)

        print(f"\nPROMPT: {prompt}")
        print(f"{'-'*80}")

        task = Task(
            id=f"test_{tool_name}",
            type=TaskType.EXECUTION,
            description=prompt,
            priority=Priority.HIGH
        )

        result = await self.executor.execute_task(task)

        success = result.get('success', False)
        summary = result.get('summary', 'No summary')
        tool_calls = result.get('tool_results', [])
        tools_used = [tc['tool'] for tc in tool_calls]
        used_correct = tool_name in tools_used

        print(f"LLM SUMMARY: {summary}")
        print(f"TOOLS CALLED: {tools_used}")
        print(f"EXPECTED TOOL: {tool_name}")
        print(f"CORRECT TOOL USED: {used_correct}")
        print(f"SUCCESS: {success}")

        if tool_calls:
            print(f"\nTOOL EXECUTION DETAILS:")
            for tc in tool_calls:
                print(f"  - Tool: {tc.get('tool', 'unknown')}")
                print(f"    Params: {tc.get('parameters', {})}")
                print(f"    Success: {tc.get('success', False)}")
                if tc.get('output'):
                    print(f"    Output: {str(tc.get('output'))[:200]}")
                if tc.get('error'):
                    print(f"    Error: {tc.get('error')}")

        # Assertions
        assert used_correct, f"LLM chose wrong tool(s): {tools_used}, expected {tool_name}"
        assert success, f"Task failed - {result.get('error', 'Unknown error')}"

    async def run_all_tests(self):
        """Run all execution tool tests"""
        # Setup LLM once for all tests
        await self.setup_llm()

        try:
            for idx, tool_name in enumerate(self.execution_tools, 1):
                print(f"\n{'='*80}")
                print(f"[{idx:3d}/{len(self.execution_tools)}] Testing: {tool_name}")
                print(f"{'='*80}")

                await self.run_test(
                    test_name=f"test_{tool_name}",
                    test_func=lambda tn=tool_name: self.test_tool_execution(tn),
                    metadata={
                        "description": f"Test {tool_name} tool via LLM execution",
                        "category": "execution",
                        "tool_name": tool_name,
                        "test_type": "llm_tool_execution",
                        "component": "execution_tools"
                    }
                )

        finally:
            # Cleanup LLM
            await self.teardown_llm()


async def main():
    """Main test runner"""
    print("\n" + "=" * 80)
    print("EXECUTION TOOLS TEST WITH LLM (TestBase Integration)")
    print("=" * 80)

    # Create test suite
    tests = ExecutionToolsTests()

    # Start session (logs to MySQL test_sessions)
    await tests.start_session()

    # Run all tests (logs to MySQL test_results)
    await tests.run_all_tests()

    # End session (updates test_sessions with results)
    await tests.end_session()

    # Print summary
    tests.print_summary()

    # Return exit code
    return 0 if tests.failed_tests == 0 else 1


if __name__ == "__main__":
    try:
        exit_code = asyncio.run(main())
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\nInterrupted")
        sys.exit(1)
