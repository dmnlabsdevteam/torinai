#!/usr/bin/env python3
"""
Master test runner - runs ALL tool category tests
"""

import asyncio
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


def run_test(test_file: str) -> tuple[bool, str]:
    """Run a single test file and return success status and output"""
    try:
        result = subprocess.run(
            [sys.executable, str(test_file)],
            capture_output=True,
            text=True,
            timeout=600
        )
        return result.returncode == 0, result.stdout
    except Exception as e:
        return False, str(e)


def main():
    print("=" * 80)
    print("MASTER TOOL TEST RUNNER")
    print("Running ALL tool category tests")
    print("=" * 80)

    tests_dir = Path(__file__).parent
    test_files = [
        "test_filesystem_tools.py",
        "test_execution_tools.py",
        "test_network_tools.py",
        "test_code_analysis_tools.py",
        "test_code_generation_tools.py",
        "test_security_tools.py",
        "test_security_types.py",
        "test_documentation_tools.py",
        "test_testing_tools.py",
        "test_research_tools.py",
        "test_data_processing_tools.py",
        "test_monitoring_tools.py",
        "test_mlai_tools.py",
        "test_system_tools.py",
        "test_communication_tools.py",
        "test_config_environment_tools.py"
    ]

    results = {
        "total": len(test_files),
        "passed": 0,
        "failed": 0,
        "details": []
    }

    for idx, test_file in enumerate(test_files, 1):
        test_path = tests_dir / test_file

        if not test_path.exists():
            print(f"\n[{idx:2d}/{len(test_files)}] SKIP: {test_file} (not found)")
            continue

        print(f"\n[{idx:2d}/{len(test_files)}] Running {test_file}...")
        print("-" * 80)

        success, output = run_test(test_path)

        if success:
            results["passed"] += 1
            print(f"✓ PASSED: {test_file}")
        else:
            results["failed"] += 1
            print(f"✗ FAILED: {test_file}")

        results["details"].append({
            "test": test_file,
            "success": success,
            "output": output
        })

        # Print summary from output
        if "RESULTS:" in output:
            summary_line = [line for line in output.split('\n') if "RESULTS:" in line]
            if summary_line:
                print(f"  {summary_line[0].strip()}")

    # Final summary
    print("\n" + "=" * 80)
    print("FINAL RESULTS")
    print("=" * 80)
    print(f"Total test suites: {results['total']}")
    print(f"✓ Passed:          {results['passed']}")
    print(f"✗ Failed:          {results['failed']}")

    if results["failed"] > 0:
        print("\nFailed test suites:")
        for detail in results["details"]:
            if not detail["success"]:
                print(f"  - {detail['test']}")

    print("=" * 80)

    return 0 if results["failed"] == 0 else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
        sys.exit(1)
