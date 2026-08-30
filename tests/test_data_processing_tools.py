#!/usr/bin/env python3
"""
Test suite for ALL data processing tools - REAL LLM USAGE with TestBase
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


class DataProcessingToolsTests(TestBase):
    """Data processing tools test suite with TestBase integration"""

    def __init__(self):
        super().__init__(
            test_category="tool_execution",
            test_type="data_processing_tools"
        )

        # Initialize LLM and executor
        self.llm = None
        self.executor = None

        # Test directory setup
        self.test_dir = Path("/Users/stefan/Dominion Labs/TorinAI/data")

        # Data processing tools to test
        self.data_processing_tools = [
            "parse_json",
            "parse_yaml",
            "parse_csv",
            "convert_format",
            "transform_data",
            "aggregate_data",
            "merge_datasets",
            "filter_data",
            "sort_data",
            "deduplicate_data",
            "parse_jsonl",
            "schema_inference",
            "pii_scrubbing",
            "dataset_profiling"
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
        if "parse_json" in tool_name and "jsonl" not in tool_name:
            return f"Use {tool_name} to parse JSON from {self.test_dir}/diagnostic_results.json"
        elif "parse_yaml" in tool_name:
            return f"Use {tool_name} to parse YAML from {self.test_dir}/config.yaml"
        elif "parse_csv" in tool_name:
            return f"Use {tool_name} to parse CSV from {self.test_dir}/data.csv"
        elif "convert_format" in tool_name:
            return f"Use {tool_name} to convert JSON to YAML for file {self.test_dir}/diagnostic_results.json"
        elif "transform_data" in tool_name:
            return f"Use {tool_name} to transform data by selecting fields"
        elif "aggregate_data" in tool_name:
            return f"Use {tool_name} to aggregate data by grouping and summing values"
        elif "merge_datasets" in tool_name:
            return f"Use {tool_name} to merge two datasets on common key"
        elif "filter_data" in tool_name:
            return f"Use {tool_name} to filter data where status equals 'PASS'"
        elif "sort_data" in tool_name:
            return f"Use {tool_name} to sort data by timestamp descending"
        elif "deduplicate_data" in tool_name:
            return f"Use {tool_name} to remove duplicate entries from dataset"
        elif "parse_jsonl" in tool_name:
            return f"Use {tool_name} to parse JSONL from {self.test_dir}/logs.jsonl"
        elif "schema_inference" in tool_name:
            return f"Use {tool_name} to infer schema from dataset at {self.test_dir}/data.csv"
        elif "pii_scrubbing" in tool_name:
            return f"Use {tool_name} with file_path parameter to scrub PII (emails and phone numbers) from {self.test_dir}/data.csv"
        elif "dataset_profiling" in tool_name:
            return f"Use {tool_name} to profile dataset at {self.test_dir}/data.csv"
        else:
            return f"Use {tool_name} to process data"

    async def run_tests(self):
        """Run all data processing tool tests"""
        print("=" * 80)
        print("DATA PROCESSING TOOLS TEST WITH LLM")
        print("=" * 80)

        await self.setup_llm()

        results = {
            "total": len(self.data_processing_tools),
            "passed": 0,
            "failed": 0,
            "details": []
        }

        print(f"\n[INFO] Testing {len(self.data_processing_tools)} data processing tools")
        print("=" * 80)

        for idx, tool_name in enumerate(self.data_processing_tools, 1):
            prompt = self._get_tool_prompt(tool_name)

            task = Task(
                id=f"test_{tool_name}",
                type=TaskType.EXECUTION,
                description=prompt,
                priority=Priority.HIGH
            )

            try:
                print(f"\n{'='*80}")
                print(f"[{idx:3d}/{len(self.data_processing_tools)}] Testing: {tool_name}")
                print(f"PROMPT: {prompt}")
                print(f"{'-'*80}")

                result = await self.executor.execute_task(task)

                print(f"LLM SUMMARY: {result.get('summary', 'No summary')}")
                print(f"TOOLS CALLED: {[tc['tool'] for tc in result.get('tool_results', [])]}")
                print(f"SUCCESS: {result.get('success', False)}")
                success = result.get('success', False)
                tool_calls = result.get('tool_results', [])
                tools_used = [tc['tool'] for tc in tool_calls]
                used_correct = tool_name in tools_used

                if used_correct and success:
                    results["passed"] += 1
                    status = "✓ PASS"
                else:
                    results["failed"] += 1
                    status = "✗ FAIL"

                results["details"].append({
                    "tool": tool_name,
                    "prompt": prompt,
                    "used_correct": used_correct,
                    "success": success,
                    "tools_used": tools_used
                })

                # Log result to MySQL via TestBase
                await self.log_test_result(
                    test_name=tool_name,
                    passed=used_correct and success,
                    error_message=None if (used_correct and success) else f"Used: {tools_used}",
                    duration=0.0,
                    test_data={"prompt": prompt, "tools_used": tools_used}
                )

                print(f"  [{idx:3d}] {status}: {tool_name}")

            except Exception as e:
                results["failed"] += 1
                results["details"].append({
                    "tool": tool_name,
                    "error": str(e)
                })

                # Log error to MySQL
                await self.log_test_result(
                    test_name=tool_name,
                    passed=False,
                    error_message=str(e),
                    duration=0.0
                )

                print(f"  [{idx:3d}] ✗ ERR: {tool_name} - {str(e)[:40]}")

        await self.teardown_llm()

        print("\n" + "=" * 80)
        print(f"RESULTS: {results['passed']} passed, {results['failed']} failed")
        pass_rate = (results['passed'] / results['total'] * 100) if results['total'] > 0 else 0
        print(f"PASS RATE: {pass_rate:.1f}%")
        print("=" * 80)

        return results["failed"] == 0


async def main():
    """Main test runner"""
    test_suite = DataProcessingToolsTests()
    await test_suite.start_session()

    try:
        success = await test_suite.run_tests()
        await test_suite.end_session()
        return success
    except Exception as e:
        print(f"Test suite failed: {e}")
        await test_suite.end_session()
        return False


if __name__ == "__main__":
    try:
        success = asyncio.run(main())
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\nInterrupted")
        sys.exit(1)
