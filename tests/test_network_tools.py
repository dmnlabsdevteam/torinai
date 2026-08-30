#!/usr/bin/env python3
"""
Test suite for ALL network tools - REAL LLM USAGE with TestBase
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


class NetworkToolsTests(TestBase):
    """Network tools test suite with TestBase integration"""

    def __init__(self):
        super().__init__(
            test_category="tool_execution",
            test_type="network_tools"
        )

        # Initialize LLM and executor
        self.llm = None
        self.executor = None

        # Network tools to test
        self.network_tools = [
            "http_request",
            "download_file",
            "upload_file",
            "parse_html",
            "extract_links",
            "check_url_status",
            "dns_lookup",
            "ping_host",
            "port_scan",
            "websocket_connect",
            "graphql_query",
            "api_call"
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
        if "http_request" in tool_name:
            return f"Use {tool_name} to make GET request to https://example.com"
        elif "download_file" in tool_name:
            return f"Use {tool_name} to download file from https://httpbin.org/robots.txt to destination_path=/tmp/robots.txt"
        elif "upload_file" in tool_name:
            return f"Use {tool_name} to upload a test file to https://httpbin.org/post with file_path=/Users/stefan/Dominion Labs/TorinAI/data/config.yaml"
        elif "parse_html" in tool_name:
            return f"Use {tool_name} to parse HTML from https://example.com"
        elif "extract_links" in tool_name:
            return f"Use {tool_name} to extract links from https://example.com"
        elif "check_url_status" in tool_name:
            return f"Use {tool_name} to check if https://example.com is up"
        elif "dns_lookup" in tool_name:
            return f"Use {tool_name} to lookup DNS for example.com"
        elif "ping_host" in tool_name:
            return f"Use {tool_name} to ping 8.8.8.8"
        elif "port_scan" in tool_name:
            return f"Use {tool_name} to scan ports on localhost"
        elif "websocket_connect" in tool_name:
            return f"Use {tool_name} to connect to wss://echo.websocket.org"
        elif "graphql_query" in tool_name:
            return f'Use {tool_name} to query the GraphQL endpoint at https://countries.trevorblades.com/ with query: {{ country(code: "US") {{ name capital }} }}'
        elif "api_call" in tool_name:
            return f"Use {tool_name} to call API endpoint https://httpbin.org/get"
        else:
            return f"Use {tool_name} for network operation"

    async def test_tool_execution(self, tool_name: str):
        """Test a single network tool with LLM"""
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
        """Run all network tool tests"""
        # Setup LLM once for all tests
        await self.setup_llm()

        try:
            for idx, tool_name in enumerate(self.network_tools, 1):
                print(f"\n{'='*80}")
                print(f"[{idx:3d}/{len(self.network_tools)}] Testing: {tool_name}")
                print(f"{'='*80}")

                await self.run_test(
                    test_name=f"test_{tool_name}",
                    test_func=lambda tn=tool_name: self.test_tool_execution(tn),
                    metadata={
                        "description": f"Test {tool_name} tool via LLM execution",
                        "category": "network",
                        "tool_name": tool_name,
                        "test_type": "llm_tool_execution",
                        "component": "network_tools"
                    }
                )

        finally:
            # Cleanup LLM
            await self.teardown_llm()


async def main():
    """Main test runner"""
    print("\n" + "=" * 80)
    print("NETWORK TOOLS TEST WITH LLM (TestBase Integration)")
    print("=" * 80)

    # Create test suite
    tests = NetworkToolsTests()

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
