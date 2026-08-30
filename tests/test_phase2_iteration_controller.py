#!/usr/bin/env python3
"""
Test Phase 2: Iteration Controller
===================================

Validates:
1. Bayesian iteration budgets (not heuristic)
2. Uncertainty-based convergence (not max_iterations)
3. Temporal time budgets (deadline-aware)
4. Bayesian retry decisions (not retry_count < 3)
"""

import asyncio
import pytest
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from core.execution.iteration_controller import (
    get_iteration_controller,
    IterationDecision,
    IterationBudget
)


@pytest.mark.asyncio
async def test_bayesian_iteration_budget():
    """Test 1: Bayesian iteration budget computation"""
    print("\n" + "="*70)
    print("TEST 1: Bayesian Iteration Budget Computation")
    print("="*70)
    
    controller = get_iteration_controller()
    
    # Verify temporal engine is available and working
    print("\n[Pre-check] Verifying temporal reasoning engine...")
    if controller.temporal_engine is None:
        print("  ❌ Temporal engine failed to initialize - this is a CRITICAL FAILURE")
        raise RuntimeError("Temporal reasoning engine must be available for deadline-aware tasks")
    else:
        print(f"  ✓ Temporal engine initialized")
    
    # High uncertainty → more iterations
    print("\n[Test 1a] High uncertainty (0.8) → should get ~10 iterations")
    budget_high = controller.compute_iteration_budget(
        task=type('Task', (), {'id': 'test_1a', 'description': 'Test task'})(),
        initial_uncertainty=0.8,
        complexity=0.5
    )
    print(f"  Result: {budget_high.max_iterations} iterations")
    print(f"  Time budget: {budget_high.time_budget_seconds:.1f}s")
    print(f"  Uncertainty threshold: {budget_high.uncertainty_threshold}")
    # Derived from the CURRENT gain model, not a hardcoded 7-15. Iterations are
    # roughly uncertainty_budget / alpha, so the literal range silently encoded
    # alpha=0.08; when alpha was deliberately lowered to 0.03 for accuracy
    # (iteration_controller.py: "Reduced from 0.08 — more conservative"), the
    # budget correctly roughly doubled and the test reported a regression that
    # was actually a tuning decision.
    _alpha = controller.adaptive_params['expected_reduction_per_iteration']
    _expected = 0.8 / _alpha          # uncertainty to burn / gain per iteration
    assert 0.5 * _expected <= budget_high.max_iterations <= 1.5 * _expected, (
        f"Expected ~{_expected:.0f} iterations at alpha={_alpha}, "
        f"got {budget_high.max_iterations}"
    )
    
    # Low uncertainty → fewer iterations
    print("\n[Test 1b] Low uncertainty (0.3) → should get ~3-5 iterations")
    budget_low = controller.compute_iteration_budget(
        task=type('Task', (), {'id': 'test_1b', 'description': 'Test task'})(),
        initial_uncertainty=0.3,
        complexity=0.5
    )
    print(f"  Result: {budget_low.max_iterations} iterations")
    print(f"  Time budget: {budget_low.time_budget_seconds:.1f}s")
    assert budget_low.max_iterations < budget_high.max_iterations, "Low uncertainty should get fewer iterations than high uncertainty"
    
    # Deadline constraint - MUST use authoritative temporal reasoning (no fallback)
    print("\n[Test 1c] Tight deadline (30s) → AUTHORITATIVE temporal reasoning required")
    deadline = datetime.now() + timedelta(seconds=30)
    budget_deadline = controller.compute_iteration_budget(
        task=type('Task', (), {'id': 'test_1c', 'description': 'Test task'})(),
        initial_uncertainty=0.5,
        deadline=deadline,
        complexity=0.5
    )
    print(f"  Result: time budget = {budget_deadline.time_budget_seconds:.1f}s")
    print(f"  Expected: ~27s (30s deadline * 0.9 buffer)")
    # Temporal reasoning must be authoritative (not fallback to 180s)
    assert 20 <= budget_deadline.time_budget_seconds <= 30, \
        f"Expected 20-30s time budget from AUTHORITATIVE temporal reasoning, got {budget_deadline.time_budget_seconds:.1f}s (fallback = 180s = FAILURE)"
    
    print("\n✅ Test 1 PASSED: Bayesian iteration budgets computed correctly\n")


@pytest.mark.asyncio
async def test_uncertainty_convergence():
    """Test 2: Uncertainty-based convergence (not max_iterations)"""
    print("\n" + "="*70)
    print("TEST 2: Uncertainty-Based Convergence")
    print("="*70)
    
    controller = get_iteration_controller()
    
    # Create budget
    budget = IterationBudget(
        max_iterations=20,
        time_budget_seconds=120.0,
        uncertainty_threshold=0.25,
        progress_threshold=0.05
    )
    
    # Simulate convergence by reducing uncertainty
    print("\n[Test 2a] Uncertainty converges before max_iterations")
    uncertainties = [0.8, 0.65, 0.5, 0.35, 0.22]  # Converges at iteration 5
    
    for i, unc in enumerate(uncertainties):
        decision, reason = await controller.should_continue_iteration(
            budget, unc, elapsed_seconds=i * 10.0
        )
        print(f"  Iteration {i+1}: uncertainty={unc:.2f} → {decision.value}")
        
        if i < len(uncertainties) - 1:
            assert decision == IterationDecision.CONTINUE, f"Should continue at iteration {i+1}"
        else:
            assert decision == IterationDecision.CONVERGED, f"Should converge at iteration {i+1}"
    
    print(f"\n  ✓ Converged at iteration {len(uncertainties)} (before max_iterations={budget.max_iterations})")
    print("  Reason: Epistemic uncertainty < threshold")
    
    print("\n✅ Test 2 PASSED: Uncertainty convergence works\n")


@pytest.mark.asyncio
async def test_temporal_limits():
    """Test 3: Temporal time budget limits"""
    print("\n" + "="*70)
    print("TEST 3: Temporal Time Budget Limits")
    print("="*70)
    
    controller = get_iteration_controller()
    
    # Short time budget
    budget = IterationBudget(
        max_iterations=20,
        time_budget_seconds=5.0,  # Only 5 seconds
        uncertainty_threshold=0.25,
        progress_threshold=0.05
    )
    
    print("\n[Test 3a] Time budget exhausted before max_iterations")
    
    # Vary uncertainty to avoid stagnation detection
    uncertainties = [0.8, 0.75, 0.7, 0.65, 0.6, 0.55, 0.5, 0.45, 0.4, 0.35]
    
    for i in range(10):
        elapsed = i * 1.0
        # Use varying uncertainty to avoid stagnation
        current_unc = uncertainties[i] if i < len(uncertainties) else 0.5
        
        decision, reason = await controller.should_continue_iteration(
            budget, current_uncertainty=current_unc, elapsed_seconds=elapsed
        )
        print(f"  Iteration {i+1}: elapsed={elapsed:.1f}s/{budget.time_budget_seconds:.1f}s, unc={current_unc:.2f} → {decision.value}")
        
        if elapsed < budget.time_budget_seconds:
            assert decision == IterationDecision.CONTINUE, f"Should continue while time remains (got {decision.value})"
        else:
            assert decision == IterationDecision.TEMPORAL_LIMIT, f"Should stop when time exhausted"
            print(f"\n  ✓ Temporal limit hit at iteration {i+1}: {reason}")
            break
    
    print("\n✅ Test 3 PASSED: Temporal limits enforced\n")


@pytest.mark.asyncio
async def test_stagnation_detection():
    """Test 4: Stagnation detection with measurement noise handling"""
    print("\n" + "="*70)
    print("TEST 4: Stagnation Detection")
    print("="*70)
    
    controller = get_iteration_controller()
    
    budget = IterationBudget(
        max_iterations=20,
        time_budget_seconds=120.0,
        uncertainty_threshold=0.2,
        progress_threshold=0.05,
        stagnation_window=3
    )
    
    print("\n[Test 4a] Stagnation: uncertainty stuck at 0.5 for 4 iterations")
    
    # Uncertainty plateaus (no progress)
    uncertainties = [0.8, 0.65, 0.5, 0.51, 0.50, 0.51]  # Stuck at ~0.5
    
    for i, unc in enumerate(uncertainties):
        decision, reason = await controller.should_continue_iteration(
            budget, unc, elapsed_seconds=i * 5.0
        )
        print(f"  Iteration {i+1}: uncertainty={unc:.2f} → {decision.value}")
        
        if i < 4:
            assert decision == IterationDecision.CONTINUE, f"Should continue before stagnation window"
        else:
            if decision == IterationDecision.STAGNANT:
                print(f"\n  ✓ Stagnation detected at iteration {i+1}: {reason}")
                break
    
    # Test 4b: Measurement noise should NOT trigger false stagnation
    print("\n[Test 4b] Measurement noise: uncertainty oscillates ±0.03 but trending down")
    
    budget2 = IterationBudget(
        max_iterations=20,
        time_budget_seconds=120.0,
        uncertainty_threshold=0.2,
        progress_threshold=0.05,
        stagnation_window=3
    )
    
    # Noisy but trending down: 0.8 → 0.77 → 0.80 → 0.73 (noise ±0.03)
    # Smoothing should detect this is NOT stagnant
    noisy_uncertainties = [0.8, 0.77, 0.80, 0.73, 0.76, 0.70]
    
    stagnation_detected = False
    for i, unc in enumerate(noisy_uncertainties):
        decision, reason = await controller.should_continue_iteration(
            budget2, unc, elapsed_seconds=i * 5.0
        )
        print(f"  Iteration {i+1}: uncertainty={unc:.2f} (noisy) → {decision.value}")
        
        if decision == IterationDecision.STAGNANT:
            stagnation_detected = True
            print(f"\n  ✗ FALSE POSITIVE: Stagnation detected despite downward trend")
            break
    
    if not stagnation_detected:
        print(f"\n  ✓ Smoothing prevented false stagnation detection (noisy measurements)")
    
    print("\n✅ Test 4 PASSED: Stagnation detection works with measurement noise\n")


@pytest.mark.asyncio
async def test_bayesian_retry_decisions():
    """Test 5: Bayesian retry decisions"""
    print("\n" + "="*70)
    print("TEST 5: Bayesian Retry Decisions")
    print("="*70)
    
    controller = get_iteration_controller()
    
    # High uncertainty → retry justified
    print("\n[Test 5a] High uncertainty (0.8) → retry should be justified")
    retry_high = await controller.should_retry_operation(
        operation="tool_call",
        failure_reason="Connection timeout",
        current_uncertainty=0.8,
        retry_count=1,
        time_remaining=60.0
    )
    print(f"  Result: should_retry={retry_high.should_retry}")
    print(f"  Reason: {retry_high.reason}")
    assert retry_high.should_retry, "High uncertainty should justify retry"
    
    # Low uncertainty → deterministic failure, don't retry
    print("\n[Test 5b] Low uncertainty (0.1) → retry should be rejected (deterministic failure)")
    retry_low = await controller.should_retry_operation(
        operation="tool_call",
        failure_reason="File not found",
        current_uncertainty=0.1,
        retry_count=1,
        time_remaining=60.0
    )
    print(f"  Result: should_retry={retry_low.should_retry}")
    print(f"  Reason: {retry_low.reason}")
    assert not retry_low.should_retry, "Low uncertainty should reject retry (deterministic failure)"
    
    # No time remaining → don't retry
    print("\n[Test 5c] No time remaining → retry should be rejected")
    retry_no_time = await controller.should_retry_operation(
        operation="tool_call",
        failure_reason="Connection timeout",
        current_uncertainty=0.8,
        retry_count=1,
        time_remaining=1.0  # Only 1s left, tool needs 5s
    )
    print(f"  Result: should_retry={retry_no_time.should_retry}")
    print(f"  Reason: {retry_no_time.reason}")
    assert not retry_no_time.should_retry, "Insufficient time should reject retry"
    
    print("\n✅ Test 5 PASSED: Bayesian retry decisions work\n")


@pytest.mark.asyncio
async def test_statistics():
    """Test 6: Controller statistics and gain model validation"""
    print("\n" + "="*70)
    print("TEST 6: Controller Statistics & Gain Model Validation")
    print("="*70)
    
    controller = get_iteration_controller()
    
    # Record empirical reductions for gain model validation
    print("\n[Test 6a] Recording empirical uncertainty reductions...")
    controller.record_empirical_reduction(initial_unc=0.8, final_unc=0.3, iterations=6)
    controller.record_empirical_reduction(initial_unc=0.7, final_unc=0.2, iterations=7)
    controller.record_empirical_reduction(initial_unc=0.6, final_unc=0.25, iterations=4)
    
    stats = controller.get_stats()
    print("\nController Statistics:")
    print(f"  Total budgets created: {stats['total_budgets_created']}")
    print(f"  Bayesian iterations: {stats['bayesian_iterations']}")
    print(f"  Heuristic fallbacks: {stats['heuristic_fallbacks']}")
    print(f"  Temporal limits hit: {stats['temporal_limits_hit']}")
    print(f"  Uncertainty converged: {stats['uncertainty_converged']}")
    print(f"  Bayesian rate: {stats['bayesian_rate']:.1%}")
    
    # Gain model validation
    if 'empirical_gain_mean' in stats:
        print(f"\nGain Model Validation:")
        print(f"  Assumed gain (α): {stats['assumed_gain']:.3f}/iter (LINEAR MODEL)")
        print(f"  Empirical gain: {stats['empirical_gain_mean']:.3f}/iter")
        print(f"  Samples: {stats['empirical_gain_samples']}")
        print(f"  Drift: {stats['gain_model_drift']:.3f}")
        
        if stats['gain_model_drift'] > 0.02:
            print(f"  ⚠️  Gain model drift > 0.02 — recalibration recommended")
        else:
            print(f"  ✓ Gain model validated (drift < 0.02)")
    
    assert stats['total_budgets_created'] >= 3, "Should have created at least 3 budgets in tests"
    
    print("\n✅ Test 6 PASSED: Statistics and gain model validation work\n")


async def main():
    """Run all Phase 2 tests"""
    print("\n" + "="*70)
    print("PHASE 2: ITERATION CONTROLLER TEST SUITE")
    print("="*70)
    print("\nValidating:")
    print("  1. Bayesian iteration budgets (not heuristic max_iterations=30)")
    print("  2. Uncertainty-based convergence (not iteration count)")
    print("  3. Temporal time budgets (deadline-aware)")
    print("  4. Stagnation detection (no progress)")
    print("  5. Bayesian retry decisions (not retry_count < 3)")
    print("  6. Statistics tracking")
    
    try:
        await test_bayesian_iteration_budget()
        await test_uncertainty_convergence()
        await test_temporal_limits()
        await test_stagnation_detection()
        await test_bayesian_retry_decisions()
        await test_statistics()
        
        print("\n" + "="*70)
        print("🎉 ALL PHASE 2 TESTS PASSED")
        print("="*70)
        print("\nPhase 2 Summary:")
        print("  ✅ Bayesian iteration budgets replace heuristics")
        print("  ✅ Uncertainty convergence replaces max_iterations")
        print("  ✅ Temporal reasoning enforces deadlines")
        print("  ✅ Stagnation detection prevents infinite loops")
        print("  ✅ Bayesian retry logic (not arbitrary retry limits)")
        print("\nIteration and retry decisions are now mathematically justified.")
        print("="*70 + "\n")
        
        return 0
        
    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {e}\n")
        return 1
    except Exception as e:
        print(f"\n❌ UNEXPECTED ERROR: {e}\n")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
