#!/usr/bin/env python3
"""
Iteration Controller — Phase 2: Uncertainty & Temporal Layer
                       Phase 3: Self-Optimization Loop
=============================================================

Phase 2: Mathematically justified iteration and retry logic using:
- bayesian_uncertainty.py — quantify uncertainty, decide when to retry
- temporal_reasoning.py — time budgets, deadline-aware iteration limits

Phase 3: Self-optimization and automatic calibration:
- Auto-calibrate expected_reduction_per_iteration from production data
- Adjust uncertainty_threshold based on success rate
- Learn operation costs from actual execution times

Architecture:
    Before: max_iterations = 30 (heuristic)
    After:  max_iterations = uncertainty_budget / expected_progress_rate (Bayesian)
    
    Before: retry if tool_failed (heuristic)
    After:  retry if epistemic_uncertainty > threshold (Bayesian proof)
    
    Before: timeout = 30s (arbitrary)
    After:  timeout = temporal_constraint_solver(deadline, complexity) (formal)

Design Principle:
    No heuristic iteration limits. Every retry is Bayesian-justified.
    Every timeout is temporally-reasoned.
    All parameters self-calibrate from production data.
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timedelta
from enum import Enum

logger = logging.getLogger(__name__)


class IterationDecision(Enum):
    """Iteration control decisions"""
    CONTINUE = "continue"              # Continue iterating (uncertainty high)
    CONVERGED = "converged"            # Stop - converged (uncertainty low)
    TEMPORAL_LIMIT = "temporal_limit"  # Stop - time budget exceeded
    STAGNANT = "stagnant"              # Stop - no progress being made
    MAX_BUDGET = "max_budget"          # Stop - uncertainty budget exhausted


@dataclass
class IterationBudget:
    """Mathematically derived iteration budget"""
    max_iterations: int                # Derived from uncertainty budget
    time_budget_seconds: float         # Derived from temporal constraints
    uncertainty_threshold: float       # Stop when uncertainty drops below this
    progress_threshold: float          # Stop if progress < threshold for N iterations
    
    # Derived parameters
    expected_uncertainty_reduction: float = 0.1  # Expected Δuncertainty per iteration
    stagnation_window: int = 3                   # Iterations to check for stagnation
    # How long a task may run producing NO epistemic signal before that silence
    # is treated as the answer. Long enough for the first tool results to come
    # back and form a belief; short enough that an unresolvable finding costs
    # minutes rather than the full 200-iteration budget.
    no_signal_grace_iterations: int = 8
    
    # Runtime tracking
    current_iteration: int = 0
    elapsed_seconds: float = 0.0
    uncertainty_history: List[float] = field(default_factory=list)
    
    def is_exhausted(self) -> bool:
        """Check if budget is exhausted"""
        return (
            self.current_iteration >= self.max_iterations or
            self.elapsed_seconds >= self.time_budget_seconds
        )
    
    def is_stagnant(self) -> bool:
        """Check if progress has stagnated.
        
        Uses smoothed uncertainty (rolling average) to handle measurement noise.
        If epistemic estimation has noise ±0.03, raw values might oscillate:
            0.50 → 0.51 → 0.50 (false stagnation)
        Smoothing prevents false positives.
        """
        if len(self.uncertainty_history) < self.stagnation_window:
            return False
        
        recent = self.uncertainty_history[-self.stagnation_window:]
        
        # Apply exponential smoothing to handle measurement noise
        # α = 0.5 (light smoothing - responsive but handles ±0.03 noise)
        smoothed = [recent[0]]  # First value unsmoothed
        for i in range(1, len(recent)):
            smoothed_val = 0.5 * recent[i] + 0.5 * smoothed[i-1]
            smoothed.append(smoothed_val)
        
        # Check if smoothed uncertainty shows no progress
        # Use MORE strict threshold for smoothed values (0.03 instead of 0.05)
        # This compensates for smoothing dampening the delta
        delta = max(smoothed) - min(smoothed)
        smoothed_threshold = self.progress_threshold * 0.6  # 0.05 * 0.6 = 0.03

        # Uncertainty pinned at maximum means the epistemic engine has produced
        # NO beliefs. That was previously an exemption — "no measurements is not
        # the same as stuck, keep running" — and the diagnosis was right while
        # the conclusion was backwards.
        #
        # Early on it is correct: beliefs cannot form before the first tool
        # results come back, so a grace period is genuine. After that, a
        # pinned 1.000 is not an absence of information about progress, it IS
        # the information: this task is generating no observations, and another
        # 195 iterations will generate none either.
        #
        # Observed cost of the exemption: `auth_missing_env_POSTGRES_PASSWORD`
        # — a finding no agent can remediate — ran with uncertainty=1.000 and a
        # 200-iteration / 36000s budget, stagnation detection disabled the whole
        # way. Every unresolvable finding burned hours.
        #
        # STAGNANT is the honest verdict: the executor answers it by asking for
        # one final propose_completion rather than killing the task, so a task
        # that genuinely has something to say still gets to say it.
        if min(smoothed) >= 0.99:
            grace = max(self.stagnation_window, self.no_signal_grace_iterations)
            if len(self.uncertainty_history) < grace:
                return False
            return True

        return delta < smoothed_threshold


@dataclass
class RetryDecision:
    """Bayesian-justified retry decision"""
    should_retry: bool
    reason: str
    
    # Bayesian evidence
    current_uncertainty: float
    uncertainty_threshold: float
    expected_gain: float               # Expected uncertainty reduction from retry
    
    # Temporal constraints
    time_remaining: float
    estimated_retry_cost: float        # Expected time for retry
    
    # Metadata
    retry_count: int
    max_retries: int


class IterationController:
    """
    Mathematically justified iteration and retry control
    
    Uses:
    - Bayesian uncertainty for iteration budgets
    - Temporal reasoning for time budgets
    - Epistemic evidence for retry decisions
    """

    # Security/critical work gets a FLOOR (we are willing to keep going) and a
    # CEILING (a policy limit, not a default). The adaptive result survives in
    # between — importance must not delete the measurement.
    SECURITY_ITERATION_FLOOR: int = 40
    SECURITY_ITERATION_CEILING: int = 200


    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}
        
        # Lazy-load reasoning engines
        self._uncertainty_sys = None
        self._temporal_engine = None
        
        # Statistics
        self.stats = {
            'total_budgets_created': 0,
            'bayesian_iterations': 0,
            'heuristic_fallbacks': 0,
            'temporal_limits_hit': 0,
            'uncertainty_converged': 0,
        }
        
        # Empirical calibration data (for validating gain model)
        self.empirical_data = {
            'uncertainty_reductions': [],  # [(initial_unc, final_unc, iterations)]
            'observed_gain_per_iteration': [],  # [actual_reduction]
        }
        
        # Phase 3: Self-optimization tracking
        self.optimization_data = {
            'task_outcomes': [],  # [(uncertainty_threshold, success)]
            'operation_costs': {},  # {operation: [actual_durations]}
            'threshold_success_rate': {},  # {threshold: success_rate}
            'recalibrations_count': 0,
            # Risk 1: Uncertainty calibration
            'uncertainty_predictions': [],  # [(predicted_convergence, actual_success, posterior_error)]
            # Risk 2: Performance profiling
            'iteration_costs': [],  # [duration_seconds]
            'proof_solve_times': [],  # [z3_duration_seconds]
            'convergence_check_times': [],  # [convergence_gate_duration]
        }
        
        # Phase 3: Adaptive parameters (start with defaults, auto-calibrate)
        self.adaptive_params = {
            'expected_reduction_per_iteration': 0.03,  # Reduced from 0.08 — more conservative progress per iteration for accuracy
            'uncertainty_threshold': 0.2,  # Will be calibrated
            'min_calibration_samples': 20,  # Need 20+ samples before auto-adjust
            'recalibration_interval': 50,  # Recalibrate every 50 tasks
        }
        
        logger.info("IterationController initialized (Phase 2: Uncertainty & Temporal Layer)")
    
    # ─────────────────────────────────────────────────────────────────────────
    # Lazy Engine Initialization
    # ─────────────────────────────────────────────────────────────────────────
    
    @property
    def uncertainty_sys(self):
        """Lazy-load Bayesian uncertainty system"""
        if self._uncertainty_sys is None:
            try:
                from core.reasoning.bayesian_uncertainty import get_uncertainty_system
                self._uncertainty_sys = get_uncertainty_system()
            except Exception as e:
                logger.warning(f"Bayesian uncertainty not available: {e}")
        return self._uncertainty_sys
    
    @property
    def temporal_engine(self):
        """Lazy-load temporal reasoning engine"""
        if self._temporal_engine is None:
            try:
                from core.reasoning.temporal_reasoning import TemporalReasoningSystem
                # Pass explicit db_path to avoid initialization errors
                self._temporal_engine = TemporalReasoningSystem(db_path="data/temporal_reasoning.db")
                logger.info("✓ Temporal reasoning engine initialized")
            except Exception as e:
                # Log full exception for debugging
                logger.error(f"Temporal reasoning initialization failed: {e}", exc_info=True)
                # DO NOT silently suppress - return None to indicate failure
                self._temporal_engine = None
        return self._temporal_engine
    
    # ─────────────────────────────────────────────────────────────────────────
    # Bayesian Iteration Budget
    # ─────────────────────────────────────────────────────────────────────────
    
    def compute_iteration_budget(
        self,
        task: Any,
        initial_uncertainty: Optional[float] = None,
        deadline: Optional[datetime] = None,
        complexity: Optional[float] = None
    ) -> IterationBudget:
        """Compute mathematically justified iteration budget.
        
        Formula:
            max_iterations = uncertainty_budget / expected_uncertainty_reduction
            time_budget = temporal_constraint_solver(deadline, complexity)
        
        Args:
            task: Task being executed
            initial_uncertainty: Current epistemic uncertainty (0-1)
            deadline: Task deadline (if any)
            complexity: Task complexity estimate (0-1)
        
        Returns:
            IterationBudget with Bayesian-derived limits
        """
        self.stats['total_budgets_created'] += 1
        
        # ── Bayesian Iteration Limit ──
        if self.uncertainty_sys and initial_uncertainty is not None:
            # ═══════════════════════════════════════════════════════════════════
            # GAIN MODEL: Linear uncertainty reduction per iteration
            # ═══════════════════════════════════════════════════════════════════
            # 
            # Assumption: uncertainty reduces linearly per iteration
            #     u(n+1) = u(n) - α  where α = expected_reduction_per_iteration
            # 
            # Convergence:
            #     u(0) = initial_uncertainty (e.g., 0.8)
            #     u(n) = 0.2 (target threshold)
            #     
            #     Solving: 0.2 = 0.8 - n*α
            #     n = (0.8 - 0.2) / α = 0.6 / 0.08 = 7.5 ≈ 7 iterations
            # 
            # CRITICAL: α = 0.08 is ASSUMED (heuristic), not empirically validated
            # 
            # Empirical validation:
            #     - Track actual uncertainty reductions per iteration
            #     - Compute observed α_empirical = Σ(Δu) / Σ(iterations)
            #     - If |α_assumed - α_empirical| > 0.02, recalibrate
            # 
            # Alternative models (future work):
            #     - Exponential decay: u(n+1) = u(n) * β  (entropy-based)
            #     - Logarithmic: u(n) = u(0) - α*log(n+1)  (information-theoretic)
            # ═══════════════════════════════════════════════════════════════════
            
            uncertainty_budget = initial_uncertainty - 0.2  # Target: reduce to 0.2
            
            # Phase 3: Use adaptive expected reduction (auto-calibrated)
            expected_reduction_per_iteration = self.adaptive_params['expected_reduction_per_iteration']
            
            # Check if we have empirical data to validate
            if len(self.empirical_data['observed_gain_per_iteration']) > 10:
                observed_mean = sum(self.empirical_data['observed_gain_per_iteration'][-10:]) / 10
                drift = abs(expected_reduction_per_iteration - observed_mean)
                
                if drift > 0.02:
                    logger.warning(
                        f"⚠️ Gain model drift detected: assumed={expected_reduction_per_iteration:.3f}, "
                        f"observed={observed_mean:.3f}, drift={drift:.3f}. "
                        f"Auto-recalibration will trigger at next interval."
                    )
            
            bayesian_max_iterations = max(
                10,  # Minimum — formula gives 5 when uncertainty already below target
                min(
                    100,  # Maximum — relaxed from 30 to prioritize accuracy over speed
                    int(uncertainty_budget / expected_reduction_per_iteration)
                )
            )
            
            # ── Task-Aware Scaling: SECURITY & CRITICAL tasks bypass normal caps ──
            from core.agents.autonomous.shared_types import TaskType
            task_type = getattr(task, 'type', None)
            task_criticality = getattr(task, 'criticality', 'normal')
            
            if task_type == TaskType.SECURITY_REMEDIATION or task_criticality == 'CRITICAL':
                # Security raises WILLINGNESS to keep working; it does not delete
                # the measurement of how much work is warranted.
                #
                # This was `bayesian_max_iterations = 200` — an assignment, so the
                # adaptive result was computed and thrown away. Every security
                # task got 200 iterations regardless of what the evidence implied,
                # which combined with a 36000s time budget authorised ten-hour
                # runs on findings no agent could resolve.
                #
                # A floor is the correct shape, and the complexity branch below
                # already used it. The ceiling remains available for genuinely
                # hard security work — it is now a limit, not a default.
                _computed = bayesian_max_iterations
                bayesian_max_iterations = max(
                    min(_computed, self.SECURITY_ITERATION_CEILING),
                    self.SECURITY_ITERATION_FLOOR,
                )
                if bayesian_max_iterations != _computed:
                    logger.info(
                        f"🔒 Security/Critical floor applied: {_computed} → "
                        f"{bayesian_max_iterations} "
                        f"(floor={self.SECURITY_ITERATION_FLOOR}, "
                        f"ceiling={self.SECURITY_ITERATION_CEILING}, "
                        f"task_type={task_type}, criticality={task_criticality})"
                    )
                else:
                    logger.info(
                        f"🔒 Security/Critical task: adaptive budget {_computed} "
                        f"already within [{self.SECURITY_ITERATION_FLOOR}, "
                        f"{self.SECURITY_ITERATION_CEILING}] — kept"
                    )
            elif complexity is not None and complexity > 0.4:
                # Multi-phase tasks (EXECUTION, SELF_IMPROVEMENT, etc.) often need more
                # iterations than the Bayesian formula predicts when initial uncertainty
                # is already low.  Apply a complexity-derived floor so the model has
                # enough turns to complete all phases without hitting the hard cap.
                # A BACKSTOP, not the policy. This was `int(15 + complexity*15)`
                # -- 22 at mid complexity -- set when alpha was 0.08 and the
                # Bayesian formula granted only ~7 iterations. Alpha was later
                # lowered to 0.03 for accuracy, which raised the formula to ~20,
                # but the floor was never revisited. Two compensations for the
                # same problem then stacked, and since the floor exceeded the
                # formula's output at EVERY uncertainty (its whole range is
                # 10..26), the floor became the answer: max_iterations came back
                # 22 for uncertainty 0.1 and 0.8 alike, and "high uncertainty
                # gets more iterations" -- the point of the model -- could not
                # happen. Sized below the formula's range so it backstops
                # multi-phase work without replacing the uncertainty signal.
                complexity_floor = max(8, min(15, int(5 + complexity * 10)))
                if bayesian_max_iterations < complexity_floor:
                    logger.info(
                        f"📈 Complexity floor applied: {bayesian_max_iterations} → {complexity_floor} "
                        f"(complexity={complexity:.2f}, task_type={task_type})"
                    )
                    bayesian_max_iterations = complexity_floor
            
            self.stats['bayesian_iterations'] += 1
            logger.info(
                f"📊 Bayesian iteration budget: {bayesian_max_iterations} iterations "
                f"(uncertainty={initial_uncertainty:.3f}, target=0.001, "
                f"expected_reduction={expected_reduction_per_iteration:.3f}/iter, model=LINEAR)"
            )
        else:
            # Fallback: complexity-based heuristic
            if complexity is not None:
                bayesian_max_iterations = max(10, min(30, int(15 + complexity * 15)))
            else:
                bayesian_max_iterations = 20
            
            self.stats['heuristic_fallbacks'] += 1
            logger.warning(
                f"⚠️  Falling back to heuristic iteration limit: {bayesian_max_iterations} "
                f"(Bayesian uncertainty unavailable)"
            )
        
        # ── Temporal Time Budget ──
        if deadline:
            # CRITICAL: Temporal reasoning is REQUIRED when deadline is present
            # No silent fallback allowed - deadline-aware tasks need authoritative temporal reasoning
            if not self.temporal_engine:
                error_msg = (
                    "Temporal reasoning REQUIRED for deadline-aware task but engine unavailable. "
                    "Cannot compute authoritative time budget. This is a HARD FAILURE."
                )
                logger.error(f"❌ {error_msg}")
                raise RuntimeError(error_msg)
            
            # Compute time remaining until deadline (authoritative)
            time_remaining = (deadline - datetime.now()).total_seconds()

            # Reserve buffer for completion verification (10%)
            time_budget = time_remaining * 0.9

            # Back-derive a sane max_iterations from the actual time budget.
            # The Bayesian formula caps at 30 but a long-running task with a
            # generous deadline should get proportionally more iterations.
            # 180s/iter is the conservative floor used in the no-deadline path.
            time_derived_iters = max(10, int(time_budget / 180.0))
            if time_derived_iters > bayesian_max_iterations:
                logger.info(
                    f"📈 Deadline-derived iteration budget: {bayesian_max_iterations} "
                    f"→ {time_derived_iters} "
                    f"(time_budget={time_budget:.0f}s / 180s per iter)"
                )
                bayesian_max_iterations = time_derived_iters

            logger.info(
                f"⏱️  Temporal time budget: {time_budget:.1f}s "
                f"(deadline={deadline.isoformat()}, remaining={time_remaining:.1f}s, "
                f"computed with authoritative temporal reasoning)"
            )
        else:
            # No deadline: Temporal reasoning is OPTIONAL
            # Fallback to complexity-based estimate is acceptable
            if complexity is not None:
                time_budget = 60.0 + (complexity * 240.0)  # 60s-300s
            else:
                time_budget = 180.0  # Default 3 minutes

            # FLOOR: large models (e.g. Qwen 32B Q4) need ~90s per inference call.
            # The complexity-based estimate (60-300s) was designed for fast models.
            # Enforce a minimum so every iteration can actually complete at least once.
            # Conservative: 180s/iteration × max_iterations (increased from 90s to allow careful reasoning)
            min_budget_floor = bayesian_max_iterations * 180.0
            if time_budget < min_budget_floor:
                logger.info(
                    f"⏱️  Time budget floor applied: {time_budget:.1f}s → {min_budget_floor:.1f}s "
                    f"(complexity estimate too tight for {bayesian_max_iterations} iterations × 180s/iter)"
                )
                time_budget = min_budget_floor

            logger.info(
                f"⏱️  Estimated time budget: {time_budget:.1f}s "
                f"(no deadline, using complexity-based estimate)"
            )
        
        # ── Uncertainty Threshold ──
        uncertainty_threshold = self.config.get('uncertainty_threshold', 0.20)  # 80% confidence — 0.001 was so strict uncertainty never reached it
        progress_threshold = self.config.get('progress_threshold', 0.05)
        
        budget = IterationBudget(
            max_iterations=bayesian_max_iterations,
            time_budget_seconds=time_budget,
            uncertainty_threshold=uncertainty_threshold,
            progress_threshold=progress_threshold
        )
        
        return budget
    
    # ─────────────────────────────────────────────────────────────────────────
    # Iteration Decision
    # ─────────────────────────────────────────────────────────────────────────
    
    async def should_continue_iteration(
        self,
        budget: IterationBudget,
        current_uncertainty: float,
        elapsed_seconds: float
    ) -> Tuple[IterationDecision, str]:
        """Decide whether to continue iterating.
        
        Bayesian decision:
        - Continue if uncertainty > threshold AND budget remaining
        - Stop if uncertainty converged (< threshold)
        - Stop if temporal limit exceeded
        - Stop if stagnant (no progress)
        
        Args:
            budget: Current iteration budget
            current_uncertainty: Current epistemic uncertainty
            elapsed_seconds: Time elapsed so far
        
        Returns:
            (decision, reason) tuple
        """
        # Update budget state
        budget.current_iteration += 1
        budget.elapsed_seconds = elapsed_seconds
        budget.uncertainty_history.append(current_uncertainty)
        
        # Check convergence (Bayesian criterion)
        if current_uncertainty < budget.uncertainty_threshold:
            self.stats['uncertainty_converged'] += 1
            return (
                IterationDecision.CONVERGED,
                f"Epistemic uncertainty converged: {current_uncertainty:.3f} < {budget.uncertainty_threshold}"
            )
        
        # Check temporal limits
        if budget.elapsed_seconds >= budget.time_budget_seconds:
            self.stats['temporal_limits_hit'] += 1
            return (
                IterationDecision.TEMPORAL_LIMIT,
                f"Temporal budget exhausted: {budget.elapsed_seconds:.1f}s >= {budget.time_budget_seconds:.1f}s"
            )
        
        # Check iteration budget
        if budget.current_iteration >= budget.max_iterations:
            return (
                IterationDecision.MAX_BUDGET,
                f"Iteration budget exhausted: {budget.current_iteration} >= {budget.max_iterations}"
            )
        
        # Check stagnation
        if budget.is_stagnant():
            return (
                IterationDecision.STAGNANT,
                f"Progress stagnant: uncertainty delta < {budget.progress_threshold} "
                f"over last {budget.stagnation_window} iterations"
            )
        
        # Continue iterating
        return (
            IterationDecision.CONTINUE,
            f"Continuing: uncertainty={current_uncertainty:.3f}, "
            f"iter={budget.current_iteration}/{budget.max_iterations}, "
            f"time={budget.elapsed_seconds:.1f}s/{budget.time_budget_seconds:.1f}s"
        )
    
    # ─────────────────────────────────────────────────────────────────────────
    # Bayesian Retry Logic
    # ─────────────────────────────────────────────────────────────────────────
    
    async def should_retry_operation(
        self,
        operation: str,
        failure_reason: str,
        current_uncertainty: float,
        retry_count: int,
        time_remaining: float
    ) -> RetryDecision:
        """Decide whether to retry a failed operation using Bayesian evidence.
        
        Bayesian criterion:
        - Retry if expected uncertainty reduction > cost
        - Don't retry if uncertainty already low (failure is deterministic)
        - Don't retry if no time remaining
        
        Args:
            operation: Operation that failed (e.g., "tool_call", "llm_inference")
            failure_reason: Why it failed
            current_uncertainty: Current epistemic uncertainty
            retry_count: How many retries so far
            time_remaining: Time budget remaining
        
        Returns:
            RetryDecision with Bayesian justification
        """
        uncertainty_threshold = 0.3
        max_retries = 3
        
        # Check if retry budget exhausted
        if retry_count >= max_retries:
            return RetryDecision(
                should_retry=False,
                reason=f"Max retries reached: {retry_count} >= {max_retries}",
                current_uncertainty=current_uncertainty,
                uncertainty_threshold=uncertainty_threshold,
                expected_gain=0.0,
                time_remaining=time_remaining,
                estimated_retry_cost=0.0,
                retry_count=retry_count,
                max_retries=max_retries
            )
        
        # Phase 3: Use learned operation costs (auto-calibrated from production data)
        if operation in self.optimization_data['operation_costs'] and \
           len(self.optimization_data['operation_costs'][operation]) >= 5:
            # Use median of last 10 observations (robust to outliers)
            recent_costs = self.optimization_data['operation_costs'][operation][-10:]
            estimated_cost = sorted(recent_costs)[len(recent_costs) // 2]
            logger.debug(f"Using learned cost for {operation}: {estimated_cost:.1f}s (from {len(recent_costs)} samples)")
        else:
            # Fallback to defaults until we have enough data
            operation_costs = {
                'tool_call': 5.0,
                'llm_inference': 30.0,
                'memory_search': 2.0,
                'file_operation': 1.0,
            }
            estimated_cost = operation_costs.get(operation, 10.0)
        
        # Check temporal feasibility
        if time_remaining < estimated_cost:
            return RetryDecision(
                should_retry=False,
                reason=f"Insufficient time: {time_remaining:.1f}s < {estimated_cost:.1f}s",
                current_uncertainty=current_uncertainty,
                uncertainty_threshold=uncertainty_threshold,
                expected_gain=0.0,
                time_remaining=time_remaining,
                estimated_retry_cost=estimated_cost,
                retry_count=retry_count,
                max_retries=max_retries
            )
        
        # Bayesian decision: retry if uncertainty is high
        if current_uncertainty > uncertainty_threshold:
            # High uncertainty → failure might be non-deterministic → retry could succeed
            expected_gain = 0.15  # Expected uncertainty reduction from retry
            
            return RetryDecision(
                should_retry=True,
                reason=(
                    f"uncertainty={current_uncertainty:.3f} > "
                    f"threshold={uncertainty_threshold}, expected_gain={expected_gain:.3f}"
                ),
                current_uncertainty=current_uncertainty,
                uncertainty_threshold=uncertainty_threshold,
                expected_gain=expected_gain,
                time_remaining=time_remaining,
                estimated_retry_cost=estimated_cost,
                retry_count=retry_count,
                max_retries=max_retries
            )
        else:
            # Low uncertainty → failure is deterministic → retry won't help
            return RetryDecision(
                should_retry=False,
                reason=(
                    f"uncertainty={current_uncertainty:.3f} < "
                    f"threshold={uncertainty_threshold} (deterministic failure)"
                ),
                current_uncertainty=current_uncertainty,
                uncertainty_threshold=uncertainty_threshold,
                expected_gain=0.0,
                time_remaining=time_remaining,
                estimated_retry_cost=estimated_cost,
                retry_count=retry_count,
                max_retries=max_retries
            )
    
    def get_operation_timeout(
        self,
        budget: "IterationBudget",
        elapsed_seconds: float,
        operation: str = "tool_call",
        floor_seconds: float = 60.0,
        ceiling_seconds: float = 900.0,
    ) -> float:
        """Return the max seconds a single operation should be allowed to run.

        Ensures no single tool call can silently exhaust the remaining task
        budget between iteration-boundary time checks.

        Uses Phase-3 learned operation costs when enough samples exist;
        falls back to a simple fraction of remaining budget.

        Args:
            budget:           Current IterationBudget (owns time_budget_seconds).
            elapsed_seconds:  Seconds already elapsed since task start.
            operation:        Operation key for learned-cost lookup (e.g. 'tool_call').
            floor_seconds:    Minimum timeout returned (never starve a fast op).
            ceiling_seconds:  Hard cap (matches LLM inference ceiling).

        Returns:
            Timeout in seconds to pass to asyncio.wait_for.
        """
        remaining = budget.time_budget_seconds - elapsed_seconds
        if remaining <= 0:
            return floor_seconds

        # Base: allow at most 80 % of remaining budget for one operation,
        # leaving 20 % headroom for remaining iterations and completion.
        base_timeout = remaining * 0.8

        # If Phase-3 has enough samples, use P95 * 3 as an evidence-based cap.
        learned_costs = self.optimization_data["operation_costs"].get(operation, [])
        if len(learned_costs) >= 5:
            sorted_costs = sorted(learned_costs)
            p95_idx = min(int(len(sorted_costs) * 0.95), len(sorted_costs) - 1)
            p95_cost = sorted_costs[p95_idx]
            # 3× P95 handles legitimate outliers without blocking runaway ops.
            evidence_cap = min(p95_cost * 3.0, base_timeout)
            timeout = max(floor_seconds, min(evidence_cap, ceiling_seconds))
        else:
            timeout = max(floor_seconds, min(base_timeout, ceiling_seconds))

        return timeout

    def get_stats(self) -> Dict[str, Any]:
        """Get iteration controller statistics including Phase 3 optimization data"""
        stats = {
            **self.stats,
            'bayesian_rate': (
                self.stats['bayesian_iterations'] / self.stats['total_budgets_created']
                if self.stats['total_budgets_created'] > 0 else 0.0
            )
        }
        
        # Add empirical gain model validation
        if self.empirical_data['observed_gain_per_iteration']:
            observed_gains = self.empirical_data['observed_gain_per_iteration']
            stats['empirical_gain_mean'] = sum(observed_gains) / len(observed_gains)
            stats['empirical_gain_samples'] = len(observed_gains)
            stats['assumed_gain'] = self.adaptive_params['expected_reduction_per_iteration']
            stats['gain_model_drift'] = abs(stats['empirical_gain_mean'] - stats['assumed_gain'])
        
        # Phase 3: Add optimization stats
        stats['phase3_optimization'] = {
            'adaptive_alpha': self.adaptive_params['expected_reduction_per_iteration'],
            'adaptive_threshold': self.adaptive_params['uncertainty_threshold'],
            'task_outcomes_tracked': len(self.optimization_data['task_outcomes']),
            'operations_learned': len(self.optimization_data['operation_costs']),
            'threshold_success_rates': self.optimization_data['threshold_success_rate'],
            'recalibrations_count': self.optimization_data['recalibrations_count'],
        }
        
        # Risk monitoring
        if self.optimization_data['uncertainty_predictions']:
            recent_predictions = self.optimization_data['uncertainty_predictions'][-20:]
            avg_error = sum(p[2] for p in recent_predictions) / len(recent_predictions)
            stats['uncertainty_calibration_error'] = avg_error
        
        if self.optimization_data['iteration_costs']:
            recent_costs = self.optimization_data['iteration_costs'][-10:]
            stats['avg_iteration_cost'] = sum(recent_costs) / len(recent_costs)
            stats['max_iteration_cost'] = max(recent_costs)
        
        if self.optimization_data['proof_solve_times']:
            recent_proofs = self.optimization_data['proof_solve_times'][-10:]
            stats['avg_proof_time'] = sum(recent_proofs) / len(recent_proofs)
            stats['max_proof_time'] = max(recent_proofs)
        
        return stats
    
    def record_empirical_reduction(self, initial_unc: float, final_unc: float, iterations: int):
        """Record empirical uncertainty reduction for gain model calibration.
        
        Args:
            initial_unc: Initial uncertainty at task start
            final_unc: Final uncertainty at task end
            iterations: Number of iterations taken
        """
        self.empirical_data['uncertainty_reductions'].append((
            initial_unc, final_unc, iterations
        ))
        
        # Compute observed gain per iteration
        if iterations > 0:
            observed_gain = (initial_unc - final_unc) / iterations
            self.empirical_data['observed_gain_per_iteration'].append(observed_gain)
            
            logger.debug(
                f"Recorded empirical reduction: {initial_unc:.3f} → {final_unc:.3f} "
                f"over {iterations} iterations (gain={observed_gain:.3f}/iter)"
            )
    
    # ─────────────────────────────────────────────────────────────────────────
    # Phase 3: Self-Optimization Methods
    # ─────────────────────────────────────────────────────────────────────────
    
    def record_task_outcome(self, final_uncertainty: float, success: bool):
        """Record task outcome for uncertainty threshold calibration.
        
        Args:
            final_uncertainty: Final uncertainty when task completed
            success: Whether task completed successfully
        """
        self.optimization_data['task_outcomes'].append((final_uncertainty, success))
        
        # Check if we should recalibrate
        if len(self.optimization_data['task_outcomes']) % self.adaptive_params['recalibration_interval'] == 0:
            self._recalibrate_all()
    
    def record_uncertainty_prediction(
        self, 
        predicted_convergence: float, 
        actual_success: bool,
        predicted_uncertainty: float,
        actual_uncertainty: float
    ):
        """Risk 1: Track uncertainty calibration accuracy."""
        posterior_error = abs(predicted_uncertainty - actual_uncertainty)
        self.optimization_data['uncertainty_predictions'].append((
            predicted_convergence,
            actual_success,
            posterior_error
        ))
        
        # Alert if calibration drift detected
        if len(self.optimization_data['uncertainty_predictions']) >= 20:
            recent = self.optimization_data['uncertainty_predictions'][-20:]
            avg_error = sum(p[2] for p in recent) / len(recent)
            if avg_error > 0.15:
                logger.warning(
                    f"⚠️ RISK 1: Uncertainty miscalibration detected. "
                    f"Avg posterior error: {avg_error:.3f} (threshold: 0.15)"
                )
    
    def record_operation_cost(self, operation: str, duration: float):
        """Record actual operation duration for cost learning.
        
        Args:
            operation: Operation type (e.g., 'tool_call', 'llm_inference')
            duration: Actual duration in seconds
        """
        if operation not in self.optimization_data['operation_costs']:
            self.optimization_data['operation_costs'][operation] = []
        
        self.optimization_data['operation_costs'][operation].append(duration)
        
        # Keep only last 50 samples (sliding window)
        if len(self.optimization_data['operation_costs'][operation]) > 50:
            self.optimization_data['operation_costs'][operation].pop(0)
    
    def record_iteration_cost(self, duration: float):
        """Risk 2: Track iteration cost for performance monitoring."""
        self.optimization_data['iteration_costs'].append(duration)
        if len(self.optimization_data['iteration_costs']) > 100:
            self.optimization_data['iteration_costs'].pop(0)
        
        # Alert if cost explosion detected
        if len(self.optimization_data['iteration_costs']) >= 10:
            recent = self.optimization_data['iteration_costs'][-10:]
            avg_cost = sum(recent) / len(recent)
            max_cost = max(recent)
            if avg_cost > 5.0 or max_cost > 15.0:
                logger.warning(
                    f"⚠️ RISK 2: Iteration cost explosion. "
                    f"Avg: {avg_cost:.2f}s, Max: {max_cost:.2f}s"
                )
    
    def record_proof_solve_time(self, duration: float):
        """Risk 2: Track Z3 proof solver performance."""
        self.optimization_data['proof_solve_times'].append(duration)
        if len(self.optimization_data['proof_solve_times']) > 50:
            self.optimization_data['proof_solve_times'].pop(0)
        
        if duration > 2.0:
            logger.warning(f"⚠️ RISK 2: Slow proof solve: {duration:.2f}s")
    
    def record_convergence_check_time(self, duration: float):
        """Risk 2: Track convergence gate overhead."""
        self.optimization_data['convergence_check_times'].append(duration)
        if len(self.optimization_data['convergence_check_times']) > 50:
            self.optimization_data['convergence_check_times'].pop(0)
    
    def _recalibrate_all(self):
        """Phase 3: Auto-recalibrate all adaptive parameters."""
        logger.info("🔄 Phase 3: Starting self-optimization recalibration...")
        
        # Increment recalibration counter
        self.optimization_data['recalibrations_count'] += 1
        
        # 1. Recalibrate expected_reduction_per_iteration (α)
        if len(self.empirical_data['observed_gain_per_iteration']) >= self.adaptive_params['min_calibration_samples']:
            old_alpha = self.adaptive_params['expected_reduction_per_iteration']
            
            # Use median (robust to outliers)
            gains = sorted(self.empirical_data['observed_gain_per_iteration'])
            new_alpha = gains[len(gains) // 2]
            
            # Smooth update (moving average with weight 0.3 for new data)
            self.adaptive_params['expected_reduction_per_iteration'] = 0.7 * old_alpha + 0.3 * new_alpha
            
            logger.info(
                f"  ✓ Calibrated α: {old_alpha:.3f} → {self.adaptive_params['expected_reduction_per_iteration']:.3f} "
                f"(observed median: {new_alpha:.3f}, samples: {len(gains)})"
            )
        
        # 2. Recalibrate uncertainty_threshold based on success rate
        if len(self.optimization_data['task_outcomes']) >= self.adaptive_params['min_calibration_samples']:
            # Compute success rate at different uncertainty thresholds
            thresholds = [0.15, 0.2, 0.25, 0.3, 0.35]
            best_threshold = self.adaptive_params['uncertainty_threshold']
            best_score = 0.0
            
            for threshold in thresholds:
                # Filter outcomes where task stopped at this threshold
                relevant = [(u, s) for u, s in self.optimization_data['task_outcomes'] 
                           if abs(u - threshold) < 0.05]
                
                if len(relevant) >= 5:
                    success_rate = sum(1 for _, s in relevant if s) / len(relevant)
                    
                    # Score = success_rate - penalty for high threshold (want low uncertainty)
                    # Higher threshold = more iterations = higher cost
                    penalty = (threshold - 0.15) * 0.5  # Prefer lower thresholds
                    score = success_rate - penalty
                    
                    self.optimization_data['threshold_success_rate'][threshold] = success_rate
                    
                    if score > best_score:
                        best_score = score
                        best_threshold = threshold
            
            old_threshold = self.adaptive_params['uncertainty_threshold']
            # Smooth update
            self.adaptive_params['uncertainty_threshold'] = 0.7 * old_threshold + 0.3 * best_threshold
            
            logger.info(
                f"  ✓ Calibrated uncertainty_threshold: {old_threshold:.3f} → "
                f"{self.adaptive_params['uncertainty_threshold']:.3f} "
                f"(optimal: {best_threshold:.3f}, score: {best_score:.3f})"
            )
        
        # 3. Log learned operation costs
        if self.optimization_data['operation_costs']:
            logger.info("  ✓ Learned operation costs:")
            for op, durations in self.optimization_data['operation_costs'].items():
                if durations:
                    median = sorted(durations)[len(durations) // 2]
                    logger.info(f"      {op}: {median:.1f}s (median of {len(durations)} samples)")
        
        logger.info("🎯 Phase 3: Self-optimization recalibration complete")


# ─────────────────────────────────────────────────────────────────────────────
# Global singleton
# ─────────────────────────────────────────────────────────────────────────────

_controller_instance: Optional[IterationController] = None


def get_iteration_controller() -> IterationController:
    """Get or create the global IterationController singleton"""
    global _controller_instance
    if _controller_instance is None:
        _controller_instance = IterationController()
    return _controller_instance
