#!/usr/bin/env python3
"""
Reasoning System Chaos Adapter
===============================

Chaos injection for the reasoning system.

Targets:
- Hypothesis testing
- Bayesian uncertainty estimation
- Abstract reasoning engine
- Causal inference
- Logical reasoning
"""

import logging
import uuid
from datetime import datetime
from typing import Dict, Any, Optional

from .base_adapter import TargetSystemAdapter
from ..types import InjectionHandle, ChaosType
from ..context_managers import ChaosContext

logger = logging.getLogger(__name__)


class ReasoningSystemAdapter(TargetSystemAdapter):
    """
    Chaos adapter for the reasoning system.

    Injection Points:
    - hypothesis_testing.test: Hypothesis testing timeouts
    - bayesian_uncertainty.estimate: Bayesian computation failures
    - abstract_reasoning_engine.reason: Reasoning errors
    - causal_inference.infer: Causal inference failures
    """

    def __init__(self):
        super().__init__("reasoning_system")
        self.injection_points = {
            "hypothesis_test": "hypothesis_testing",
            "bayesian_estimate": "bayesian_uncertainty",
            "abstract_reason": "abstract_reasoning_engine",
            "causal_infer": "causal_inference"
        }

    async def inject_latency(
        self,
        target_id: str,
        component: str,
        injection_point: str,
        delay_ms: int,
        jitter_ms: int = 0
    ) -> InjectionHandle:
        """
        Inject latency into reasoning system operations.

        Examples:
        - component="hypothesis_testing", injection_point="test_execution"
        - component="bayesian_uncertainty", injection_point="monte_carlo_sampling"
        """
        injection_id = f"reasoning_latency_{uuid.uuid4().hex[:8]}"

        # Enable chaos via context
        await ChaosContext.enable_chaos(component, injection_point, target_id)

        # Create injection handle
        handle = InjectionHandle(
            injection_id=injection_id,
            experiment_id=target_id,
            target=self.system_name,
            chaos_type=ChaosType.LATENCY,
            started_at=datetime.now(),
            active=True
        )

        self.active_injections[injection_id] = handle

        logger.info(
            f"Reasoning latency injection: {component}.{injection_point} "
            f"({delay_ms}ms ± {jitter_ms}ms, experiment: {target_id})"
        )

        return handle

    async def inject_error(
        self,
        target_id: str,
        component: str,
        injection_point: str,
        error_type: str,
        error_rate: float
    ) -> InjectionHandle:
        """
        Inject errors into reasoning system operations.

        Examples:
        - component="bayesian_uncertainty", error_type="NumericOverflow"
        - component="abstract_reasoning_engine", error_type="ReasoningTimeout"
        """
        injection_id = f"reasoning_error_{uuid.uuid4().hex[:8]}"

        # Enable chaos via context
        await ChaosContext.enable_chaos(component, injection_point, target_id)

        # Create injection handle
        handle = InjectionHandle(
            injection_id=injection_id,
            experiment_id=target_id,
            target=self.system_name,
            chaos_type=ChaosType.ERROR,
            started_at=datetime.now(),
            active=True
        )

        self.active_injections[injection_id] = handle

        logger.info(
            f"Reasoning error injection: {component}.{injection_point} "
            f"({error_type} at {error_rate*100}% rate, experiment: {target_id})"
        )

        return handle

    async def inject_resource_exhaustion(
        self,
        target_id: str,
        component: str,
        resource_type: str,
        limit_value: Optional[float] = None
    ) -> InjectionHandle:
        """
        Inject resource exhaustion into reasoning system.

        Examples:
        - resource_type="computation_budget" (reasoning computation limits)
        - resource_type="memory_budget" (reasoning memory limits)
        """
        injection_id = f"reasoning_resource_{uuid.uuid4().hex[:8]}"

        # Enable chaos via context
        injection_point = f"{resource_type}_exhaustion"
        await ChaosContext.enable_chaos(component, injection_point, target_id)

        # Create injection handle
        handle = InjectionHandle(
            injection_id=injection_id,
            experiment_id=target_id,
            target=self.system_name,
            chaos_type=ChaosType.RESOURCE_EXHAUSTION,
            started_at=datetime.now(),
            active=True
        )

        self.active_injections[injection_id] = handle

        logger.info(
            f"Reasoning resource exhaustion: {component}.{resource_type} "
            f"(experiment: {target_id})"
        )

        return handle

    async def get_health_metrics(self) -> Dict[str, Any]:
        """
        Get health metrics for reasoning system.

        Metrics:
        - hypothesis_test_latency_p95: Hypothesis testing latency
        - bayesian_estimation_success_rate: Bayesian estimation success rate
        - reasoning_accuracy: Reasoning accuracy
        - inference_error_rate: Causal inference error rate
        """
        # In production, these would come from actual monitoring
        metrics = {
            "hypothesis_test_latency_p95": 300.0,  # ms
            "hypothesis_test_latency_p99": 600.0,  # ms
            "bayesian_estimation_success_rate": 0.97,  # 97%
            "reasoning_accuracy": 0.92,  # 92%
            "inference_error_rate": 0.05,  # 5%
            "active_reasoning_tasks": len(self.active_injections),
            "healthy": True
        }

        # Mark as unhealthy if accuracy is low or latency is high
        if metrics["reasoning_accuracy"] < 0.85 or metrics["hypothesis_test_latency_p95"] > 1000:
            metrics["healthy"] = False

        return metrics

    async def cleanup(self):
        """
        Clean up all active chaos injections for reasoning system.
        """
        logger.info(f"Cleaning up {len(self.active_injections)} reasoning system injections")

        # Disable all chaos contexts
        for injection_id, handle in list(self.active_injections.items()):
            handle.stop()

        # Clear all injections
        self.active_injections.clear()

        # Disable all chaos for reasoning system components
        await ChaosContext.disable_all()

        logger.info("Reasoning system chaos cleanup complete")


# Singleton instance
_reasoning_adapter = None


def get_reasoning_adapter() -> ReasoningSystemAdapter:
    """Get global reasoning system adapter instance"""
    global _reasoning_adapter
    if _reasoning_adapter is None:
        _reasoning_adapter = ReasoningSystemAdapter()
    return _reasoning_adapter
