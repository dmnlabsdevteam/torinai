#!/usr/bin/env python3
"""
Test suite for ALL code generation tools - REAL USAGE with TestBase
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))

from test_base import TestBase
from core.tools.tool_registry import get_tool_registry


class CodeGenerationToolsTests(TestBase):
    """Code generation tools test suite"""

    def __init__(self):
        super().__init__(
            test_category="tool_execution",
            test_type="code_generation_tools"
        )
        self.registry = get_tool_registry()
        self.test_dir = Path("/Users/stefan/Dominion Labs/TorinAI/data/tool_tests/codegen")
        self.test_dir.mkdir(parents=True, exist_ok=True)

    async def run_all_tests(self):
        """Run all code generation tool tests"""
        tools = [
            ("generate_function", {
                "function_name": "calculate_sum",
                "description": "Calculate sum of two numbers",
                "parameters": ["a: int", "b: int"],
                "return_type": "int",
                "language": "python"
            }),
            ("generate_class", {
                "class_name": "Calculator",
                "description": "A simple calculator class",
                "methods": ["add", "subtract"],
                "language": "python"
            }),
            ("generate_module", {
                "module_name": "math_utils",
                "description": "Math utility functions",
                "functions": ["add", "multiply"],
                "language": "python"
            }),
            ("refactor_code", {
                "code": "def foo():\n    x = 1\n    y = 2\n    return x + y",
                "refactor_type": "extract_variable",
                "language": "python"
            }),
            ("add_docstring", {
                "code": "def add(a, b):\n    return a + b",
                "style": "google",
                "language": "python"
            }),
            ("add_type_hints", {
                "code": "def add(a, b):\n    return a + b",
                "language": "python"
            }),
            ("format_code", {
                "code": "def foo( x,y ):\n  return x+y",
                "formatter": "black",
                "language": "python"
            }),
            ("fix_linting_errors", {
                "code": "import sys\nimport os\ndef foo():\n    x=1\n    return x",
                "linter": "pylint",
                "language": "python"
            }),
            ("generate_test", {
                "code": "def add(a, b):\n    return a + b",
                "test_framework": "pytest",
                "language": "python"
            }),
            ("migrate_code", {
                "code": "def foo():\n    print 'hello'",
                "source_version": "python2",
                "target_version": "python3"
            }),
            ("add_logging", {
                "code": "def process():\n    result = compute()\n    return result",
                "log_level": "INFO",
                "language": "python"
            }),
            ("optimize_code", {
                "code": "def sum_list(lst):\n    total = 0\n    for x in lst:\n        total += x\n    return total",
                "optimization_type": "performance",
                "language": "python"
            }),
            ("convert_to_async", {
                "code": "def fetch_data():\n    return requests.get('https://api.example.com')",
                "language": "python"
            }),
            ("extract_method", {
                "code": "def process():\n    x = 1\n    y = 2\n    z = x + y\n    return z",
                "start_line": 2,
                "end_line": 3,
                "method_name": "calculate"
            }),
            ("inline_variable", {
                "code": "def foo():\n    x = 5\n    return x * 2",
                "variable_name": "x",
                "language": "python"
            }),
            ("rename_symbol", {
                "code": "def old_name():\n    pass",
                "old_name": "old_name",
                "new_name": "new_name",
                "language": "python"
            }),
            ("implement_algorithm", {
                "algorithm_name": "binary_search",
                "description": "Binary search in sorted array",
                "language": "python"
            }),
            ("generate_symbolic_math", {
                "expression": "x^2 + 2*x + 1",
                "operation": "simplify"
            }),
            ("generate_numerical_code", {
                "problem": "Solve linear equation 2x + 3 = 7",
                "language": "python"
            }),
            ("generate_math_proof", {
                "theorem": "Pythagorean theorem",
                "proof_style": "direct"
            }),
            ("generate_design_pattern", {
                "pattern_name": "singleton",
                "language": "python"
            }),
            ("generate_api_client", {
                "api_spec": {"base_url": "https://api.example.com", "endpoints": ["/users"]},
                "language": "python"
            }),
            ("scaffold_application", {
                "app_type": "web",
                "framework": "flask",
                "language": "python"
            }),
            ("synthesize_from_examples", {
                "examples": [
                    {"input": [1, 2], "output": 3},
                    {"input": [2, 3], "output": 5}
                ],
                "language": "python"
            }),
            ("generate_property_test", {
                "function_signature": "def add(a: int, b: int) -> int",
                "language": "python"
            }),
            ("apply_patch", {
                "file_path": str(self.test_dir / "test.py"),
                "patch": "--- a/test.py\n+++ b/test.py\n@@ -1 +1 @@\n-old\n+new"
            }),
            ("compile_typecheck_gate", {
                "code": "def add(a: int, b: int) -> int:\n    return a + b",
                "language": "python"
            }),
            ("repository_refactor", {
                "repository_path": str(self.test_dir),
                "refactor_type": "rename_module",
                "parameters": {"old_name": "old", "new_name": "new"}
            }),
            ("license_attribution_check", {
                "repository_path": str(self.test_dir)
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
                    "category": "code_generation",
                    "tool_name": tool_name
                }
            )


async def main():
    """Main test runner"""
    print("\n" + "=" * 80)
    print("CODE GENERATION TOOLS TEST (TestBase Integration)")
    print("=" * 80)

    tests = CodeGenerationToolsTests()
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
