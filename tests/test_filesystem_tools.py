#!/usr/bin/env python3
"""
Test suite for ALL filesystem tools - REAL LLM USAGE with TestBase
"""

import asyncio
import sys
from pathlib import Path
import tarfile

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


class FilesystemToolsTests(TestBase):
    """Filesystem tools test suite with TestBase integration"""

    def __init__(self):
        super().__init__(
            test_category="tool_execution",
            test_type="filesystem_tools"
        )

        # Initialize LLM and executor
        self.llm = None
        self.executor = None

        # Test directory setup
        self.test_dir = Path("/Users/stefan/Dominion Labs/TorinAI/data/tool_tests/filesystem")
        self.test_dir.mkdir(parents=True, exist_ok=True)

        # Filesystem tools to test
        self.filesystem_tools = [
            "read_file",
            "write_file",
            "atomic_write_file",
            "list_directory",
            "create_directory",
            "copy_file",
            "move_file",
            "delete_file",
            "get_file_info",
            "calculate_checksum",
            "validate_path",
            "search_files",
            "compress_file",
            "decompress_file",
            "find_duplicate_files",
            "sync_directory"
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
        test_file = self.test_dir / "test_read.txt"

        if tool_name == "read_file":
            # Prepare test file
            test_file.write_text("Test content for reading")
            return f"Use {tool_name} to read the file {test_file}"

        elif tool_name == "write_file":
            return f"Use {tool_name} to write 'test content' to {self.test_dir}/test_write.txt with mode write"

        elif tool_name == "atomic_write_file":
            return f"Use {tool_name} to atomically write 'atomic test' to {self.test_dir}/atomic.txt"

        elif tool_name == "list_directory":
            return f"Use {tool_name} to list all txt files in {self.test_dir}"

        elif tool_name == "create_directory":
            return f"Use {tool_name} to create directory {self.test_dir}/subdir/nested with parents"

        elif tool_name == "copy_file":
            test_file.write_text("Test content for copying")
            return f"Use {tool_name} to copy {test_file} to {self.test_dir}/copy.txt"

        elif tool_name == "move_file":
            (self.test_dir / "copy.txt").write_text("move me")
            return f"Use {tool_name} to move {self.test_dir}/copy.txt to {self.test_dir}/moved.txt"

        elif tool_name == "delete_file":
            (self.test_dir / "delete_me.txt").write_text("delete")
            return f"Use {tool_name} to delete {self.test_dir}/delete_me.txt with confirm false"

        elif tool_name == "get_file_info":
            test_file.write_text("Test content")
            return f"Use {tool_name} to get information about {test_file}"

        elif tool_name == "calculate_checksum":
            test_file.write_text("Test content")
            return f"Use {tool_name} to calculate sha256 checksum of {test_file}"

        elif tool_name == "validate_path":
            return f"Use {tool_name} to validate path {self.test_dir} with allowed roots /Users"

        elif tool_name == "search_files":
            return f"Use {tool_name} to search for txt files in {self.test_dir} recursively"

        elif tool_name == "compress_file":
            test_file.write_text("Test content")
            return f"Use {tool_name} to compress {test_file} to {self.test_dir}/test.tar.gz with format tar.gz"

        elif tool_name == "decompress_file":
            # Create compressed file
            test_file.write_text("Test content")
            with tarfile.open(self.test_dir / "test.tar.gz", 'w:gz') as tar:
                tar.add(test_file, arcname=test_file.name)
            return f"Use {tool_name} to decompress {self.test_dir}/test.tar.gz to {self.test_dir}/decompressed"

        elif tool_name == "find_duplicate_files":
            return f"Use {tool_name} to find duplicate files in {self.test_dir} recursively"

        elif tool_name == "sync_directory":
            (self.test_dir / "sync_src").mkdir(exist_ok=True)
            (self.test_dir / "sync_src/file.txt").write_text("sync")
            return f"Use {tool_name} to sync {self.test_dir}/sync_src to {self.test_dir}/sync_dst"

        else:
            return f"Use {tool_name} on {self.test_dir}"

    async def test_tool_execution(self, tool_name: str):
        """Test a single filesystem tool with LLM"""
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
        """Run all filesystem tool tests"""
        # Setup LLM once for all tests
        await self.setup_llm()

        try:
            for idx, tool_name in enumerate(self.filesystem_tools, 1):
                print(f"\n{'='*80}")
                print(f"[{idx:3d}/{len(self.filesystem_tools)}] Testing: {tool_name}")
                print(f"{'='*80}")

                await self.run_test(
                    test_name=f"test_{tool_name}",
                    test_func=lambda tn=tool_name: self.test_tool_execution(tn),
                    metadata={
                        "description": f"Test {tool_name} tool via LLM execution",
                        "category": "filesystem",
                        "tool_name": tool_name,
                        "test_type": "llm_tool_execution",
                        "component": "filesystem_tools"
                    }
                )

        finally:
            # Cleanup LLM
            await self.teardown_llm()


async def main():
    """Main test runner"""
    print("\n" + "=" * 80)
    print("FILESYSTEM TOOLS TEST WITH LLM (TestBase Integration)")
    print("=" * 80)

    # Create test suite
    tests = FilesystemToolsTests()

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
