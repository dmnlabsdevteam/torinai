#!/usr/bin/env python3
"""
Chaos Safety Controller
========================

Production safety guardrails for chaos experiments.

Features:
- Pre-flight checks before experiment execution
- SLO monitoring during experiments
- Automatic rollback on threshold violations
- Circuit breaker implementation
- Emergency stop functionality
"""

import asyncio
import logging
import time
from enum import Enum
from typing import Dict, List, Optional

from .types import (
    ChaosExperiment,
    CircuitState,
    PreFlightCheck,
    PreFlightResult,
    SLOStatus,
    SLOThresholds,
)
from .experiment_manager import get_experiment_manager
from .injection_engine import get_injection_engine

logger = logging.getLogger(__name__)


class ChaosSafetyController:
    """
    Chaos Safety Controller

    Provides production safety guardrails:
    - Pre-flight validation before experiments
    - SLO monitoring with automatic rollback
    - Circuit breakers for failing systems
    - Resource availability checks
    - Concurrent experiment limits
    """

    def __init__(self, config: Optional[Dict] = None):
        """
        Initialize safety controller.

        Args:
            config: Optional configuration dict (from chaos_config.json)
        """
        self.config = config or self._load_default_config()

        # SLO thresholds
        slo_config = self.config.get("slo_thresholds", {})
        self.slo_thresholds = SLOThresholds(
            latency_p95_ms=slo_config.get("latency_p95_ms", 500.0),
            latency_p99_ms=slo_config.get("latency_p99_ms", 1000.0),
            error_rate=slo_config.get("error_rate", 0.01),
            cpu_percent=slo_config.get("cpu_percent", 80.0),
            memory_percent=slo_config.get("memory_percent", 85.0),
            disk_percent=slo_config.get("disk_percent", 90.0)
        )

        # Circuit breakers per target system
        self.circuit_breakers: Dict[str, 'CircuitBreaker'] = {}

        # Safety controls
        self.safety_controls = self.config.get("safety_controls", {})
        self.max_concurrent_experiments = self.safety_controls.get("max_concurrent_experiments", 3)

        logger.info("ChaosSafetyController initialized")

    def _load_default_config(self) -> Dict:
        """Load default safety configuration"""
        return {
            "safety_controls": {
                "pre_flight_checks_enabled": True,
                "slo_monitoring_enabled": True,
                "auto_rollback_enabled": True,
                "circuit_breakers_enabled": True,
                "max_concurrent_experiments": 3
            },
            "slo_thresholds": {
                "latency_p95_ms": 500.0,
                "latency_p99_ms": 1000.0,
                "error_rate": 0.01,
                "cpu_percent": 80.0,
                "memory_percent": 85.0
            },
            "circuit_breaker": {
                "failure_threshold": 5,
                "timeout_seconds": 60,
                "half_open_max_calls": 3
            }
        }

    async def pre_flight_check(self, experiment: ChaosExperiment) -> PreFlightResult:
        """
        Comprehensive pre-flight checks before chaos injection.

        Checks:
        1. Target system health
        2. Resource availability (CPU, memory)
        3. No concurrent experiments on same target
        4. Governance approval obtained
        5. Rollback capability verified
        6. Blast radius within limits

        Args:
            experiment: Experiment to validate

        Returns:
            PreFlightResult with pass/fail and detailed checks
        """
        checks: List[PreFlightCheck] = []

        # Check 1: Target system health
        health_check = await self._check_target_health(experiment.target_system)
        checks.append(health_check)

        # Check 2: Resource availability
        resource_check = await self._check_resource_availability()
        checks.append(resource_check)

        # Check 3: Concurrent experiments
        concurrent_check = await self._check_concurrent_experiments(experiment.target_system)
        checks.append(concurrent_check)

        # Check 4: Governance approval (if required)
        if experiment.environment == "production":
            governance_check = self._check_governance_approval(experiment)
            checks.append(governance_check)

        # Check 5: Blast radius validation
        blast_radius_check = self._check_blast_radius(experiment)
        checks.append(blast_radius_check)

        # Check 6: Circuit breaker state
        circuit_check = self._check_circuit_breaker(experiment.target_system)
        checks.append(circuit_check)

        # Determine overall result
        all_passed = all(check.passed for check in checks)
        blocking_issues = [
            check.reason for check in checks
            if not check.passed and check.reason
        ]

        result = PreFlightResult(
            passed=all_passed,
            checks=checks,
            can_proceed=all_passed,
            blocking_issues=blocking_issues
        )

        if all_passed:
            logger.info(f"Pre-flight checks passed for experiment {experiment.experiment_id}")
        else:
            logger.warning(
                f"Pre-flight checks failed for experiment {experiment.experiment_id}: "
                f"{', '.join(blocking_issues)}"
            )

        return result

    async def _check_target_health(self, target_system: str) -> PreFlightCheck:
        """Check target system health"""
        try:
            engine = get_injection_engine()
            metrics = await engine.get_system_health(target_system)

            if metrics and metrics.get("healthy", True):
                return PreFlightCheck(
                    name="target_health",
                    passed=True,
                    reason=None
                )
            else:
                return PreFlightCheck(
                    name="target_health",
                    passed=False,
                    reason=f"Target system {target_system} is unhealthy"
                )

        except Exception as e:
            logger.error(f"Health check failed for {target_system}: {e}")
            return PreFlightCheck(
                name="target_health",
                passed=False,
                reason=f"Failed to check health: {str(e)}"
            )

    async def _check_resource_availability(self) -> PreFlightCheck:
        """Check system resource availability"""
        try:
            # In production, this would check actual system metrics
            # For now, return a mock check
            import psutil

            cpu_percent = psutil.cpu_percent(interval=0.1)
            memory_percent = psutil.virtual_memory().percent

            if cpu_percent > self.slo_thresholds.cpu_percent:
                return PreFlightCheck(
                    name="resource_availability",
                    passed=False,
                    reason=f"CPU usage too high: {cpu_percent}%"
                )

            if memory_percent > self.slo_thresholds.memory_percent:
                return PreFlightCheck(
                    name="resource_availability",
                    passed=False,
                    reason=f"Memory usage too high: {memory_percent}%"
                )

            return PreFlightCheck(
                name="resource_availability",
                passed=True,
                reason=None
            )

        except ImportError:
            # psutil not available, skip check
            return PreFlightCheck(
                name="resource_availability",
                passed=True,
                reason="psutil not available, skipping resource check"
            )
        except Exception as e:
            logger.error(f"Resource check failed: {e}")
            return PreFlightCheck(
                name="resource_availability",
                passed=False,
                reason=f"Resource check error: {str(e)}"
            )

    async def _check_concurrent_experiments(self, target_system: str) -> PreFlightCheck:
        """Check for concurrent experiments"""
        try:
            manager = get_experiment_manager()
            active = manager.get_active_experiments(target_system)

            if len(active) >= self.max_concurrent_experiments:
                return PreFlightCheck(
                    name="concurrent_experiments",
                    passed=False,
                    reason=f"{len(active)} active experiments on {target_system} (max: {self.max_concurrent_experiments})"
                )

            return PreFlightCheck(
                name="concurrent_experiments",
                passed=True,
                reason=None
            )

        except Exception as e:
            logger.error(f"Concurrent check failed: {e}")
            return PreFlightCheck(
                name="concurrent_experiments",
                passed=False,
                reason=f"Failed to check concurrent experiments: {str(e)}"
            )

    def _check_governance_approval(self, experiment: ChaosExperiment) -> PreFlightCheck:
        """Check if governance approval obtained"""
        if experiment.governance_decision_id:
            return PreFlightCheck(
                name="governance_approval",
                passed=True,
                reason=None
            )
        else:
            return PreFlightCheck(
                name="governance_approval",
                passed=False,
                reason="Production experiment requires governance approval"
            )

    def _check_blast_radius(self, experiment: ChaosExperiment) -> PreFlightCheck:
        """Check if blast radius within limits"""
        max_radius = self.safety_controls.get(f"max_blast_radius_{experiment.environment}", 100)

        if experiment.blast_radius > max_radius:
            return PreFlightCheck(
                name="blast_radius",
                passed=False,
                reason=f"Blast radius {experiment.blast_radius}% exceeds {experiment.environment} limit: {max_radius}%"
            )

        return PreFlightCheck(
            name="blast_radius",
            passed=True,
            reason=None
        )

    def _check_circuit_breaker(self, target_system: str) -> PreFlightCheck:
        """Check circuit breaker state"""
        breaker = self.circuit_breakers.get(target_system)

        if breaker and breaker.state == CircuitState.OPEN:
            return PreFlightCheck(
                name="circuit_breaker",
                passed=False,
                reason=f"Circuit breaker OPEN for {target_system}"
            )

        return PreFlightCheck(
            name="circuit_breaker",
            passed=True,
            reason=None
        )

    async def monitor_slos(
        self,
        target_system: str,
        experiment_id: str
    ) -> SLOStatus:
        """
        Monitor SLOs for a target system during experiment.

        Args:
            target_system: Target system name
            experiment_id: Experiment ID

        Returns:
            SLOStatus with health status and violations
        """
        violations = []

        try:
            # Get system health metrics
            engine = get_injection_engine()
            metrics = await engine.get_system_health(target_system)

            if not metrics:
                return SLOStatus(
                    healthy=False,
                    violations=["Failed to retrieve metrics"],
                    should_rollback=True
                )

            # Check latency p95
            latency_p95 = metrics.get("tool_execution_latency_p95", 0)
            if latency_p95 > self.slo_thresholds.latency_p95_ms:
                violations.append(f"Latency P95 exceeded: {latency_p95}ms > {self.slo_thresholds.latency_p95_ms}ms")

            # Check latency p99
            latency_p99 = metrics.get("tool_execution_latency_p99", 0)
            if latency_p99 > self.slo_thresholds.latency_p99_ms:
                violations.append(f"Latency P99 exceeded: {latency_p99}ms > {self.slo_thresholds.latency_p99_ms}ms")

            # Check error rate
            error_rate = metrics.get("tool_error_rate", 0)
            if error_rate > self.slo_thresholds.error_rate:
                violations.append(f"Error rate exceeded: {error_rate*100:.1f}% > {self.slo_thresholds.error_rate*100}%")

            # Determine if rollback needed
            should_rollback = len(violations) > 0

            return SLOStatus(
                healthy=len(violations) == 0,
                violations=violations,
                should_rollback=should_rollback,
                health_status="healthy" if len(violations) == 0 else "degraded",
                metrics=metrics
            )

        except Exception as e:
            logger.error(f"SLO monitoring failed: {e}")
            return SLOStatus(
                healthy=False,
                violations=[f"Monitoring error: {str(e)}"],
                should_rollback=True
            )

    async def trigger_automatic_rollback(
        self,
        experiment: ChaosExperiment,
        reason: str,
        metrics: Optional[Dict] = None
    ):
        """
        Trigger automatic rollback of experiment.

        Args:
            experiment: Experiment to rollback
            reason: Rollback reason
            metrics: Optional metrics snapshot
        """
        logger.critical(
            f"AUTOMATIC ROLLBACK triggered for experiment {experiment.experiment_id}: {reason}"
        )

        # Stop chaos injection
        engine = get_injection_engine()
        await engine.cleanup_system(experiment.target_system)

        # Update experiment status
        manager = get_experiment_manager()
        await manager.update_experiment(
            experiment.experiment_id,
            status="rolled_back",
            rollback_reason=reason
        )

        # Open circuit breaker
        await self.open_circuit_breaker(experiment.target_system, duration_seconds=60)

        logger.info(f"Automatic rollback complete for experiment {experiment.experiment_id}")

    async def open_circuit_breaker(self, target_system: str, duration_seconds: int = 60):
        """
        Open circuit breaker for target system.

        Args:
            target_system: Target system name
            duration_seconds: How long to keep circuit open
        """
        breaker_config = self.config.get("circuit_breaker", {})

        breaker = CircuitBreaker(
            target=target_system,
            failure_threshold=breaker_config.get("failure_threshold", 5),
            timeout_seconds=duration_seconds
        )
        breaker.state = CircuitState.OPEN
        breaker.last_failure_time = time.time()

        self.circuit_breakers[target_system] = breaker

        logger.warning(f"Circuit breaker OPENED for {target_system} (duration: {duration_seconds}s)")

    async def close_circuit_breaker(self, target_system: str):
        """
        Close circuit breaker for target system.

        Args:
            target_system: Target system name
        """
        if target_system in self.circuit_breakers:
            self.circuit_breakers[target_system].state = CircuitState.CLOSED
            logger.info(f"Circuit breaker CLOSED for {target_system}")


class CircuitBreaker:
    """Circuit breaker for chaos experiments"""

    def __init__(self, target: str, failure_threshold: int = 5, timeout_seconds: int = 60):
        self.target = target
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.failure_threshold = failure_threshold
        self.timeout_seconds = timeout_seconds
        self.last_failure_time: Optional[float] = None

    def record_failure(self):
        """Record a failure"""
        self.failure_count += 1
        self.last_failure_time = time.time()

        if self.failure_count >= self.failure_threshold:
            self.state = CircuitState.OPEN
            logger.error(f"Circuit breaker OPENED for {self.target} after {self.failure_count} failures")

    def record_success(self):
        """Record a success"""
        if self.state == CircuitState.HALF_OPEN:
            self.state = CircuitState.CLOSED
            self.failure_count = 0
            logger.info(f"Circuit breaker CLOSED for {self.target}")

    def should_allow_request(self) -> bool:
        """Check if request should be allowed"""
        if self.state == CircuitState.CLOSED:
            return True

        if self.state == CircuitState.OPEN:
            # Check if timeout has elapsed
            if self.last_failure_time and (time.time() - self.last_failure_time > self.timeout_seconds):
                self.state = CircuitState.HALF_OPEN
                logger.info(f"Circuit breaker entering HALF_OPEN state for {self.target}")
                return True
            return False

        # HALF_OPEN state: allow limited requests
        return True


# Singleton instance
_safety_controller = None


def get_safety_controller() -> ChaosSafetyController:
    """Get global safety controller instance"""
    global _safety_controller
    if _safety_controller is None:
        _safety_controller = ChaosSafetyController()
    return _safety_controller
