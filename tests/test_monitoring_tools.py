#!/usr/bin/env python3
"""
Test suite for ALL monitoring tools - REAL LLM USAGE
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


async def main():
    print("=" * 80)
    print("MONITORING TOOLS TEST WITH LLM")
    print("=" * 80)

    print("\n[SETUP] Loading LLM...")
    from core.services.unified_llm import get_llm_service
    from core.tools.tool_registry import get_tool_registry
    from core.agents.autonomous.general_purpose_executor import GeneralPurposeExecutor
    from core.agents.autonomous.shared_types import Task, TaskType, Priority

    llm = get_llm_service()
    await llm.initialize()
    tool_registry = get_tool_registry()
    executor = GeneralPurposeExecutor(torin_brain=llm)
    await executor.initialize()
    print("✓ LLM loaded and executor initialized")

    monitoring_tools = [
        "get_cpu_usage",
        "get_memory_usage",
        "get_disk_usage",
        "get_network_stats",
        "check_mysql_health",
        "get_service_status",
        "parse_logs",
        "query_metrics",
        "create_alert",
        "get_performance_profile",
        "distributed_tracing",
        "slo_sli_tooling",
        "anomaly_detection",
        "dashboard_generator"
    ]

    results = {
        "total": len(monitoring_tools),
        "passed": 0,
        "failed": 0,
        "details": []
    }

    print(f"\n[INFO] Testing {len(monitoring_tools)} monitoring tools")
    print("=" * 80)

    for idx, tool_name in enumerate(monitoring_tools, 1):
        # Generate prompt for this tool
        if "cpu_usage" in tool_name:
            prompt = f"Use {tool_name} to get current CPU usage"
        elif "memory_usage" in tool_name:
            prompt = f"Use {tool_name} to get current memory usage"
        elif "disk_usage" in tool_name:
            prompt = f"Use {tool_name} to get disk usage for /"
        elif "network_stats" in tool_name:
            prompt = f"Use {tool_name} to get network statistics"
        elif "mysql_health" in tool_name:
            prompt = f"Use {tool_name} to check MySQL database health"
        elif "service_status" in tool_name:
            prompt = f"Use {tool_name} to get status of all services"
        elif "parse_logs" in tool_name:
            prompt = f"Use {tool_name} to parse logs from /var/log/system.log"
        elif "query_metrics" in tool_name:
            prompt = f"Use {tool_name} to query metrics for last hour"
        elif "create_alert" in tool_name:
            prompt = f"Use {tool_name} to create alert when CPU exceeds 80%"
        elif "performance_profile" in tool_name:
            prompt = f"Use {tool_name} to get performance profile of system"
        elif "distributed_tracing" in tool_name:
            prompt = f"Use {tool_name} to trace distributed request flow"
        elif "slo_sli_tooling" in tool_name:
            prompt = f"Use {tool_name} to calculate SLO and SLI metrics"
        elif "anomaly_detection" in tool_name:
            prompt = f"Use {tool_name} to detect anomalies in metrics"
        elif "dashboard_generator" in tool_name:
            prompt = f"Use {tool_name} to generate monitoring dashboard"
        else:
            prompt = f"Use {tool_name} to monitor system"

        task = Task(
            id=f"test_{tool_name}",
            type=TaskType.EXECUTION,
            description=prompt,
            priority=Priority.HIGH
        )

        try:
            print(f"\n{'='*80}")
            print(f"[{idx:3d}/{len(monitoring_tools)}] Testing: {tool_name}")
            print(f"PROMPT: {prompt}")
            print(f"{'-'*80}")
            
            result = await executor.execute_task(task)
            
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

            print(f"  [{idx:3d}] {status}: {tool_name}")

        except Exception as e:
            results["failed"] += 1
            results["details"].append({
                "tool": tool_name,
                "error": str(e)
            })
            print(f"  [{idx:3d}] ✗ ERR: {tool_name} - {str(e)[:40]}")

    if hasattr(llm, 'shutdown'):
        await llm.shutdown()

    print("\n" + "=" * 80)
    print(f"RESULTS: {results['passed']} passed, {results['failed']} failed")
    print("=" * 80)

    return results["failed"] == 0


if __name__ == "__main__":
    try:
        success = asyncio.run(main())
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\nInterrupted")
        sys.exit(1)
