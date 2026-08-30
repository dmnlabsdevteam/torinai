#!/usr/bin/env python3
"""
Test suite for ALL code analysis tools - REAL LLM USAGE with TestBase
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


class CodeAnalysisToolsTests(TestBase):
    """Code analysis tools test suite with TestBase integration"""

    def __init__(self):
        super().__init__(
            test_category="tool_execution",
            test_type="code_analysis_tools"
        )

        # Initialize LLM and executor
        self.llm = None
        self.executor = None

        # Test directory
        self.test_dir = Path("/Users/stefan/Dominion Labs/TorinAI")

        # Code analysis tools to test
        self.code_analysis_tools = [
            "semantic_search",
            "grep_search",
            "analyze_code",
            "analyze_code_quality",
            "analyze_dependencies",
            "find_dead_code",
            "security_scan",
            "find_todos",
            "count_lines",
            "analyze_complexity",
            "detect_code_smells",
            "trace_dependencies",
            "find_circular_imports",
            "analyze_test_coverage_report",
            "find_performance_issues",
            "check_code_style_consistency",
            "ast_search",
            "build_dependency_graph",
            "extract_call_graph",
            "search_secrets_pii"
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

        if "semantic" in tool_name:
            return f"Use {tool_name} to search for 'test execution' in {test_dir}"
        elif "grep" in tool_name:
            return f"Use {tool_name} to search for 'async def' in {test_dir}"
        elif "analyze_code" in tool_name and "quality" not in tool_name:
            return f"Use {tool_name} to analyze {test_dir}/test_tool_execution.py"
        elif "quality" in tool_name:
            return f"Use {tool_name} to check code quality of {test_dir}/core/tools/tool_registry.py"
        elif "dependencies" in tool_name and "trace" not in tool_name:
            return f"Use {tool_name} to analyze dependencies in {test_dir}"
        elif "dead_code" in tool_name:
            return f"Use {tool_name} to find dead code in {test_dir}/core"
        elif "security_scan" in tool_name:
            return f"Use {tool_name} to scan {test_dir}/core for security issues"
        elif "find_todos" in tool_name:
            return f"Use {tool_name} to find TODO comments in {test_dir}"
        elif "count_lines" in tool_name:
            return f"Use {tool_name} to count lines of code in {test_dir}/core"
        elif "complexity" in tool_name:
            return f"Use {tool_name} to analyze complexity of {test_dir}/core/agents"
        elif "code_smells" in tool_name:
            return f"Use {tool_name} to detect code smells in {test_dir}/core"
        elif "trace_dependencies" in tool_name:
            return f"Use {tool_name} to trace dependencies from core.tools.tool_registry"
        elif "circular_imports" in tool_name:
            return f"Use {tool_name} to find circular imports in {test_dir}/core"
        elif "test_coverage" in tool_name:
            return f"Use {tool_name} to analyze test coverage report at {test_dir}/coverage.xml"
        elif "performance_issues" in tool_name:
            return f"Use {tool_name} to find performance issues in {test_dir}/core"
        elif "style_consistency" in tool_name:
            return f"Use {tool_name} to check code style consistency in {test_dir}/core"
        elif "ast_search" in tool_name:
            return f"Use {tool_name} to search for function definitions in {test_dir}/core"
        elif "dependency_graph" in tool_name:
            return f"Use {tool_name} to build dependency graph for {test_dir}/core"
        elif "call_graph" in tool_name:
            return f"Use {tool_name} to extract call graph from {test_dir}/core/tools"
        elif "secrets_pii" in tool_name:
            return f"Use {tool_name} to search for secrets and PII in {test_dir}"
        else:
            return f"Use {tool_name} to analyze code in {test_dir}"

    async def test_tool_execution(self, tool_name: str):
        """Test a single code analysis tool with LLM"""
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
        """Run all code analysis tool tests"""
        # Setup LLM once for all tests
        await self.setup_llm()

        try:
            for idx, tool_name in enumerate(self.code_analysis_tools, 1):
                print(f"\n{'='*80}")
                print(f"[{idx:3d}/{len(self.code_analysis_tools)}] Testing: {tool_name}")
                print(f"{'='*80}")

                await self.run_test(
                    test_name=f"test_{tool_name}",
                    test_func=lambda tn=tool_name: self.test_tool_execution(tn),
                    metadata={
                        "description": f"Test {tool_name} tool via LLM execution",
                        "category": "code_analysis",
                        "tool_name": tool_name,
                        "test_type": "llm_tool_execution",
                        "component": "code_analysis_tools"
                    }
                )

        finally:
            # Cleanup LLM
            await self.teardown_llm()


async def main():
    """Main test runner"""
    print("\n" + "=" * 80)
    print("CODE ANALYSIS TOOLS TEST WITH LLM (TestBase Integration)")
    print("=" * 80)

    # Create test suite
    tests = CodeAnalysisToolsTests()

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
