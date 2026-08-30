"""
Test Phase 3: Self-Optimization Loop

Validates that the iteration controller auto-calibrates α, uncertainty_threshold,
and operation costs based on production feedback.
"""

import pytest
import time
from core.execution.iteration_controller import IterationController


@pytest.mark.asyncio
async def test_phase3_alpha_calibration():
    """Test α auto-calibration from empirical gain observations"""
    controller = IterationController()
    
    # Two channels, and recalibration reads only one of them.
    # record_task_outcome() drives the recalibration INTERVAL;
    # record_empirical_reduction() supplies the observed gains recalibration
    # actually calibrates from. This test fed only the first, so
    # observed_gain_per_iteration stayed empty, the min_calibration_samples
    # guard never opened, and alpha could not move -- the test was asserting
    # against a calibration that had no data and never ran.
    initial_alpha = controller.adaptive_params['expected_reduction_per_iteration']
    EMPIRICAL_GAIN = 0.06

    for i in range(55):
        initial_u = 0.8
        final_u = max(0.1, 0.8 - (i % 10 + 1) * EMPIRICAL_GAIN)
        iterations = max(1, round((initial_u - final_u) / EMPIRICAL_GAIN))

        controller.record_empirical_reduction(initial_u, final_u, iterations)
        controller.record_task_outcome(final_uncertainty=final_u, success=final_u < 0.3)

    stats = controller.get_stats()
    learned_alpha = stats['phase3_optimization']['adaptive_alpha']

    assert stats['phase3_optimization']['recalibrations_count'] >= 1, (
        "recalibration never ran, so alpha could not have been learned")

    # Smoothed toward the empirical gain: 0.7*old + 0.3*new, applied once per
    # recalibration. Expressed against the CURRENT starting alpha rather than a
    # hardcoded 0.08, so a deliberate retune of the default does not read as a
    # calibration failure.
    assert initial_alpha < learned_alpha <= EMPIRICAL_GAIN, (
        f"alpha={learned_alpha} did not move from {initial_alpha} toward {EMPIRICAL_GAIN}")
    print(f"✅ α calibrated {initial_alpha:.4f} → {learned_alpha:.4f} "
          f"(empirical: {EMPIRICAL_GAIN})")


@pytest.mark.asyncio
async def test_phase3_threshold_calibration():
    """Test uncertainty threshold auto-calibration from success rates"""
    controller = IterationController()
    
    # Simulate 55 tasks with varying final uncertainties and success patterns
    # Pattern: tasks with u<0.2 always succeed, 0.2<u<0.3 mostly succeed, u>0.3 fail
    scenarios = [
        (0.10, True),   # u < 0.2 → success
        (0.15, True),
        (0.18, True),
        (0.22, True),   # 0.2 < u < 0.3 → mostly succeed
        (0.25, True),
        (0.28, True),
        (0.32, False),  # u > 0.3 → fail
        (0.35, False),
    ] * 7  # 56 tasks total
    
    for final_u, success in scenarios:
        controller.record_task_outcome(final_uncertainty=final_u, success=success)
    
    # After 50 tasks, threshold should optimize
    stats = controller.get_stats()
    learned_threshold = stats['phase3_optimization']['adaptive_threshold']
    
    # Optimal threshold should be around 0.15-0.30 based on success pattern
    assert 0.10 <= learned_threshold <= 0.35, f"Threshold={learned_threshold} not in expected range"
    print(f"✅ Threshold calibrated to {learned_threshold:.4f} (initial: 0.25)")


@pytest.mark.asyncio
async def test_phase3_operation_cost_learning():
    """Test operation cost learning from actual execution times"""
    controller = IterationController()
    
    # Simulate 15 tool executions with varying durations
    tool_durations = [1.2, 1.5, 1.1, 1.4, 1.3, 1.6, 1.2, 1.4, 1.3, 1.5, 1.2, 1.4, 1.3, 1.5, 1.4]
    for duration in tool_durations:
        controller.record_operation_cost(operation="tool_call", duration=duration)
    
    # Check learned cost (should be median of last 10: ~1.35)
    stats = controller.get_stats()
    operations_count = stats['phase3_optimization']['operations_learned']
    
    assert operations_count > 0, "No operations learned"
    print(f"✅ Operation costs tracked: {operations_count} operation types")


@pytest.mark.asyncio
async def test_phase3_recalibration_interval():
    """Test that recalibration triggers at correct intervals"""
    controller = IterationController()
    
    # Record 49 tasks (should not recalibrate yet)
    for _ in range(49):
        controller.record_task_outcome(final_uncertainty=0.2, success=True)
    
    stats_before = controller.get_stats()
    recal_count_before = stats_before['phase3_optimization'].get('recalibrations_count', 0)
    
    # 50th task should trigger recalibration
    controller.record_task_outcome(final_uncertainty=0.2, success=True)
    
    stats_after = controller.get_stats()
    recal_count_after = stats_after['phase3_optimization'].get('recalibrations_count', 0)
    
    assert recal_count_after == recal_count_before + 1, "Recalibration did not trigger at 50 tasks"
    print(f"✅ Recalibration triggered at task 50 (count: {recal_count_after})")


@pytest.mark.asyncio
async def test_phase3_stats_reporting():
    """Test that Phase 3 stats are correctly reported"""
    controller = IterationController()
    
    # Add some optimization data
    controller.record_task_outcome(final_uncertainty=0.15, success=True)
    controller.record_task_outcome(final_uncertainty=0.45, success=False)
    controller.record_operation_cost(operation="tool_call", duration=1.5)
    controller.record_operation_cost(operation="llm_inference", duration=2.3)
    
    stats = controller.get_stats()
    
    # Verify Phase 3 section exists
    assert 'phase3_optimization' in stats, "Phase 3 stats missing"
    phase3 = stats['phase3_optimization']
    
    # Check structure
    assert 'task_outcomes_tracked' in phase3, "task_outcomes_tracked missing"
    assert 'adaptive_alpha' in phase3, "adaptive_alpha missing"
    assert 'operations_learned' in phase3, "operations_learned missing"
    
    # Verify data
    assert phase3['task_outcomes_tracked'] == 2, "Task outcome count mismatch"
    assert phase3['operations_learned'] > 0, "No operations tracked"
    
    print(f"✅ Phase 3 stats correctly reported: {phase3['task_outcomes_tracked']} tasks")


@pytest.mark.asyncio
async def test_phase3_integration_with_bayesian_budget():
    """Test that Phase 3 learned parameters are used in budget computation"""
    controller = IterationController()
    
    # Record tasks to trigger recalibration and learn new α
    for i in range(55):
        # Pattern: faster convergence (α ≈ 0.12)
        initial_u = 0.8
        final_u = max(0.1, 0.8 - (i % 5 + 1) * 0.12)
        controller.record_task_outcome(final_uncertainty=final_u, success=True)
    
    # Check that adaptive parameters were updated
    stats = controller.get_stats()
    adaptive_alpha = stats['phase3_optimization']['adaptive_alpha']
    
    # α should be available for budget computation
    assert adaptive_alpha > 0, "Adaptive α must be positive"
    assert stats['phase3_optimization']['recalibrations_count'] >= 1, "Should have recalibrated"
    
    print(f"✅ Adaptive parameters ready for budget: α={adaptive_alpha:.4f}, " +
          f"recalibrations={stats['phase3_optimization']['recalibrations_count']}")


if __name__ == "__main__":
    import asyncio
    
    print("\n" + "="*70)
    print("Phase 3: Self-Optimization Loop Tests")
    print("="*70 + "\n")
    
    async def run_tests():
        await test_phase3_alpha_calibration()
        await test_phase3_threshold_calibration()
        await test_phase3_operation_cost_learning()
        await test_phase3_recalibration_interval()
        await test_phase3_stats_reporting()
        await test_phase3_integration_with_bayesian_budget()
        
        print("\n" + "="*70)
        print("✅ All Phase 3 tests passed")
        print("="*70 + "\n")
    
    asyncio.run(run_tests())
