#!/usr/bin/env python3
"""
Test suite for ALL testing tools - REAL LLM USAGE with TestBase
"""

import pytest
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


class TestingToolsTests(TestBase):
    """Testing tools test suite with TestBase integration"""

    def __init__(self):
        super().__init__(
            test_category="tool_execution",
            test_type="testing_tools"
        )

        # Initialize LLM and executor
        self.llm = None
        self.executor = None

        # Test directory
        self.test_dir = Path("/Users/stefan/Dominion Labs/TorinAI")

        # Testing tools to test
        self.testing_tools = [
            "run_pytest",
            "run_unittest",
            "check_syntax",
            "validate_json",
            "validate_yaml",
            "lint_python",
            "type_check",
            "benchmark_code",
            "fuzz_testing",
            "mutation_testing",
            "static_security_analysis",
            "golden_test_harness",
            "chaos_testing"
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
        test_dir = self.test_dir

        if "pytest" in tool_name:
            return f"Use {tool_name} to run pytest tests in {test_dir}/tests"
        elif "unittest" in tool_name:
            return f"Use {tool_name} to run unittest tests in {test_dir}/tests"
        elif "check_syntax" in tool_name:
            return f"Use {tool_name} to check syntax of Python file"
        elif "validate_json" in tool_name:
            return f"Use {tool_name} to validate JSON file"
        elif "validate_yaml" in tool_name:
            return f"Use {tool_name} to validate YAML configuration file"
        elif "lint_python" in tool_name:
            return f"Use {tool_name} to lint Python code for style issues"
        elif "type_check" in tool_name:
            return f"Use {tool_name} to type check {test_dir}/core/tools/tool_registry.py"
        elif "benchmark" in tool_name:
            return f"Use {tool_name} to benchmark code performance"
        elif "fuzz" in tool_name:
            return f"Use {tool_name} to fuzz test a function with random inputs"
        elif "mutation" in tool_name:
            return f"Use {tool_name} to run mutation testing on code"
        elif "static_security" in tool_name:
            return f"Use {tool_name} to run static security analysis on {test_dir}/core"
        elif "golden_test" in tool_name:
            return f"Use {tool_name} to create golden test harness"
        elif "chaos_testing" in tool_name:
            return f"Use {tool_name} to run chaos testing on the system"
        else:
            return f"Use {tool_name} to test code"

    @pytest.mark.asyncio
    async def test_tool_execution(self, tool_name: str):
        """Test a single testing tool with LLM"""
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
                    output_str = str(tc.get('output'))
                    print(f"    Output: {output_str[:200]}")
                if tc.get('error'):
                    print(f"    Error: {tc.get('error')}")

        # Assertions
        assert used_correct, f"LLM chose wrong tool(s): {tools_used}, expected {tool_name}"
        assert success, f"Task failed - {result.get('error', 'Unknown error')}"

    async def run_all_tests(self):
        """Run all testing tool tests"""
        # Setup LLM once for all tests
        await self.setup_llm()

        try:
            for idx, tool_name in enumerate(self.testing_tools, 1):
                print(f"\n{'='*80}")
                print(f"[{idx:3d}/{len(self.testing_tools)}] Testing: {tool_name}")
                print(f"{'='*80}")

                await self.run_test(
                    test_name=f"test_{tool_name}",
                    test_func=lambda tn=tool_name: self.test_tool_execution(tn),
                    metadata={
                        "description": f"Test {tool_name} tool via LLM execution",
                        "category": "testing",
                        "tool_name": tool_name,
                        "test_type": "llm_tool_execution",
                        "component": "testing_tools"
                    }
                )

        finally:
            # Cleanup LLM
            await self.teardown_llm()


async def main():
    """Main test runner"""
    print("\n" + "=" * 80)
    print("TESTING TOOLS TEST WITH LLM (TestBase Integration)")
    print("=" * 80)

    # Create test suite
    tests = TestingToolsTests()

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
