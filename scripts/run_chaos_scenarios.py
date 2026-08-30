#!/usr/bin/env python3
"""
Run Chaos Scenarios
===================

Execute chaos scenarios and verify logging/observability.
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path (script is in scripts/, so go up 1 level)
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.chaos.orchestrator import ChaosOrchestrator
from core.chaos.experiment_manager import get_experiment_manager
from core.chaos.scenarios import list_all_scenarios


async def run_scenario(scenario_id: str, system_name: str):
    """Run a single chaos scenario."""
    print(f"\n{'='*80}")
    print(f"Running Scenario: {scenario_id}")
    print(f"Target System: {system_name}")
    print(f"{'='*80}")

    try:
        # Create orchestrator with MySQL logging enabled
        config = {
            "observability": {
                "enable_mysql_logging": True
            }
        }
        orchestrator = ChaosOrchestrator(config=config)

        # Create experiment from scenario
        experiment_manager = get_experiment_manager()
        experiment = await experiment_manager.create_experiment_from_scenario(
            scenario_id=scenario_id,
            environment="dev",
            blast_radius=1  # Small blast radius for safety
        )

        if not experiment:
            print(f"❌ Failed to create experiment from scenario: {scenario_id}")
            return False

        print(f"✅ Experiment created: {experiment.experiment_id}")
        print(f"   Name: {experiment.name}")
        print(f"   Target: {experiment.target_system}")
        print(f"   Chaos Type: {experiment.chaos_type.value}")
        print(f"   Blast Radius: {experiment.blast_radius}%")

        # Execute the experiment with a short duration
        print(f"🔄 Executing experiment (duration: 0.1 minutes)...")
        result = await orchestrator.run_experiment(
            experiment_id=experiment.experiment_id,
            progressive_rollout=False,  # Direct execution for testing
            duration_minutes=0.1  # Very short duration for safety
        )

        if result and result.success:
            print(f"✅ Experiment executed successfully")
            print(f"   Status: {result.status.value}")
            print(f"   Metrics collected: {len(result.metrics_collected)}")
            print(f"   Rollback triggered: {result.rollback_triggered}")
            if result.insights:
                print(f"   Insights: {result.insights[0][:100]}...")
            return True
        else:
            print(f"❌ Experiment execution failed")
            if result and result.insights:
                print(f"   Reason: {result.insights[0]}")
            return False

    except Exception as e:
        print(f"❌ Error running scenario {scenario_id}: {e}")
        import traceback
        print("\nFull traceback:")
        traceback.print_exc()
        return False


async def main():
    """Run chaos scenarios for all systems."""
    print("="*80)
    print("CHAOS SCENARIO EXECUTION")
    print("="*80)

    # Get all scenarios
    all_scenarios = list_all_scenarios()

    print(f"\nFound {sum(len(scenarios) for scenarios in all_scenarios.values())} scenarios across {len(all_scenarios)} systems")

    results = {}
    total_scenarios = 0
    successful_scenarios = 0

    # Run one scenario per system to verify functionality
    for system_name, scenarios in all_scenarios.items():
        if not scenarios:
            continue

        # Run the first scenario for each system
        scenario_id = scenarios[0]
        total_scenarios += 1

        success = await run_scenario(scenario_id, system_name)
        results[system_name] = success

        if success:
            successful_scenarios += 1

        # Small delay between scenarios
        await asyncio.sleep(0.5)

    # Summary
    print("\n" + "="*80)
    print("EXECUTION SUMMARY")
    print("="*80)

    for system_name, success in results.items():
        status = "✅ SUCCESS" if success else "❌ FAILED"
        print(f"  {system_name:25} {status}")

    print(f"\nTotal: {successful_scenarios}/{total_scenarios} scenarios executed successfully")

    if successful_scenarios == total_scenarios:
        print("\n🎉 ALL SCENARIOS EXECUTED SUCCESSFULLY!")
        print("📊 Check MySQL logs for experiment persistence")
        return 0
    else:
        print(f"\n⚠️  {total_scenarios - successful_scenarios} scenario(s) failed")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
