#!/usr/bin/env python3
"""
Test suite for ALL research tools - REAL LLM USAGE with TestBase
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


class ResearchToolsTests(TestBase):
    """Research tools test suite with LLM execution"""

    def __init__(self):
        super().__init__(
            test_category="tool_execution",
            test_type="research_tools"
        )
        self.llm = None
        self.executor = None

        self.research_tools = [
            "conduct_research",
            "search_academic",
            "search_data",
            "search_news",
            "analyze_research_paper",
            "generate_citation",
            "synthesize_literature",
            "extract_paper_metadata",
            "analyze_research_data",
            "fetch_paper_by_doi",
            "fetch_paper_by_arxiv",
            "validate_bibliography",
            "export_bibliography_csl",
            "link_claim_to_evidence",
            "generate_artifact_manifest"
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
        """Run all research tool tests"""
        await self.setup_llm()

        try:
            for idx, tool_name in enumerate(self.research_tools, 1):
                # Generate prompt for this tool
                if "conduct_research" in tool_name:
                    prompt = f"Use {tool_name} to research 'machine learning optimization'"
                elif "search_academic" in tool_name:
                    prompt = f"Use {tool_name} to search academic papers about 'neural networks'"
                elif "search_data" in tool_name:
                    prompt = f"Use {tool_name} to search datasets about 'climate data'"
                elif "search_news" in tool_name:
                    prompt = f"Use {tool_name} to search news about 'AI research'"
                elif "analyze_research_paper" in tool_name:
                    prompt = f"Use {tool_name} to analyze a research paper at /Users/stefan/Dominion Labs/TorinAI/data/paper.pdf"
                elif "generate_citation" in tool_name:
                    prompt = f"Use {tool_name} to generate citation for paper titled 'Attention Is All You Need'"
                elif "synthesize_literature" in tool_name:
                    prompt = f"Use {tool_name} to synthesize literature on 'transformer models'"
                elif "extract_paper_metadata" in tool_name:
                    prompt = f"Use {tool_name} to extract metadata from paper at /Users/stefan/Dominion Labs/TorinAI/data/paper.pdf"
                elif "analyze_research_data" in tool_name:
                    prompt = f"Use {tool_name} to analyze research data at /Users/stefan/Dominion Labs/TorinAI/data/research_data.csv"
                elif "fetch_paper_by_doi" in tool_name:
                    prompt = f"Use {tool_name} to fetch paper with DOI '10.1000/xyz123'"
                elif "fetch_paper_by_arxiv" in tool_name:
                    prompt = f"Use {tool_name} to fetch paper with arXiv ID '2104.09864'"
                elif "validate_bibliography" in tool_name:
                    prompt = f"Use {tool_name} to validate bibliography at /Users/stefan/Dominion Labs/TorinAI/bibliography.json"
                elif "export_bibliography_csl" in tool_name:
                    prompt = f"Use {tool_name} to export bibliography to CSL format from /Users/stefan/Dominion Labs/TorinAI/bibliography.json"
                elif "link_claim_to_evidence" in tool_name:
                    prompt = f"Use {tool_name} to link claim 'AI improves efficiency' to evidence in bibliography"
                elif "generate_artifact_manifest" in tool_name:
                    prompt = f"Use {tool_name} to generate artifact manifest for research project"
                else:
                    prompt = f"Use {tool_name} for research purposes"

                print(f"\n[{idx:3d}/{len(self.research_tools)}] Testing: {tool_name}")
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
                        "category": "research",
                        "tool_name": tool_name,
                        "prompt": prompt
                    }
                )

        finally:
            await self.teardown_llm()


async def main():
    """Main test runner"""
    print("\n" + "=" * 80)
    print("RESEARCH TOOLS TEST WITH LLM (TestBase Integration)")
    print("=" * 80)

    tests = ResearchToolsTests()
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
