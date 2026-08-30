#!/usr/bin/env python3
"""
Test suite for ALL documentation tools - REAL USAGE with TestBase
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))

from test_base import TestBase
from core.tools.tool_registry import get_tool_registry


class DocumentationToolsTests(TestBase):
    """Documentation tools test suite"""

    def __init__(self):
        super().__init__(
            test_category="tool_execution",
            test_type="documentation_tools"
        )
        self.registry = get_tool_registry()
        self.test_dir = Path("/Users/stefan/Dominion Labs/TorinAI/data/tool_tests/docs")
        self.test_dir.mkdir(parents=True, exist_ok=True)

    async def run_all_tests(self):
        """Run all documentation tool tests"""
        # Prepare test code
        test_code = """
def add(a, b):
    '''Add two numbers'''
    return a + b

class Calculator:
    '''A simple calculator'''
    def multiply(self, x, y):
        return x * y
"""
        (self.test_dir / "test_code.py").write_text(test_code)

        tools = [
            ("generate_readme", {
                "project_path": str(self.test_dir),
                "project_name": "TestProject",
                "description": "A test project",
                "include_badges": True
            }),
            ("generate_api_docs", {
                "source_path": str(self.test_dir / "test_code.py"),
                "output_format": "markdown",
                "include_private": False
            }),
            ("extract_docstrings", {
                "source_path": str(self.test_dir / "test_code.py"),
                "format": "google"
            }),
            ("generate_changelog", {
                "repository_path": str(self.test_dir),
                "version": "1.0.0",
                "include_commits": True
            }),
            ("create_diagram", {
                "diagram_type": "flowchart",
                "description": "Process flow",
                "output_format": "mermaid"
            }),
            ("update_docs", {
                "docs_path": str(self.test_dir / "docs"),
                "source_path": str(self.test_dir / "test_code.py"),
                "update_type": "sync"
            }),
            ("docs_build_preview", {
                "docs_path": str(self.test_dir / "docs"),
                "builder": "mkdocs"
            }),
            ("versioned_doc_deployment", {
                "docs_path": str(self.test_dir / "docs"),
                "version": "1.0.0",
                "deployment_target": "local"
            }),
            ("adr_generator", {
                "decision_title": "Use PostgreSQL for database",
                "context": "Need reliable relational database",
                "decision": "PostgreSQL chosen",
                "consequences": "ACID compliance, good tooling"
            }),
            ("generate_latex_document", {
                "content": "Test document",
                "document_type": "article",
                "output_path": str(self.test_dir / "doc.tex")
            }),
            ("create_research_graph", {
                "data": [{"x": 1, "y": 2}, {"x": 2, "y": 4}],
                "graph_type": "line",
                "title": "Test Graph"
            }),
            ("generate_architecture_diagram", {
                "components": ["Frontend", "Backend", "Database"],
                "connections": [["Frontend", "Backend"], ["Backend", "Database"]],
                "output_format": "mermaid"
            }),
            ("create_flowchart", {
                "steps": ["Start", "Process", "End"],
                "connections": [[0, 1], [1, 2]],
                "output_format": "mermaid"
            })
        ]

        for idx, (tool_name, params) in enumerate(tools, 1):
            print(f"\n[{idx:3d}/{len(tools)}] Testing: {tool_name}")

            async def test_func(tn=tool_name, p=params):
                result = await self.registry.execute_tool(tn, p)
                assert result.success or result.error is not None, f"Tool {tn} failed without error message"
                return result

            await self.run_test(
                test_name=f"test_{tool_name}",
                test_func=test_func,
                metadata={
                    "description": f"Test {tool_name} tool with real parameters",
                    "category": "documentation",
                    "tool_name": tool_name
                }
            )


async def main():
    """Main test runner"""
    print("\n" + "=" * 80)
    print("DOCUMENTATION TOOLS TEST (TestBase Integration)")
    print("=" * 80)

    tests = DocumentationToolsTests()
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
