#!/usr/bin/env python3
"""
Learning System Chaos Adapter
==============================

Chaos injection for the learning system.

Targets:
- Continuous learning pipeline
- Safe upgrade deployer
- Governance pattern learner
- Model training and validation
- Pattern extraction
"""

import logging
import uuid
from datetime import datetime
from typing import Dict, Any, Optional

from .base_adapter import TargetSystemAdapter
from ..types import InjectionHandle, ChaosType
from ..context_managers import ChaosContext

logger = logging.getLogger(__name__)


class LearningSystemAdapter(TargetSystemAdapter):
    """
    Chaos adapter for the learning system.

    Injection Points:
    - continuous_learning_pipeline.train: Training process failures
    - safe_upgrade_deployer.deploy: Deployment failures
    - governance_pattern_learner.extract_patterns: Pattern extraction errors
    - model_validator.validate: Validation failures
    """

    def __init__(self):
        super().__init__("learning_system")
        self.injection_points = {
            "training": "continuous_learning_pipeline",
            "deployment": "safe_upgrade_deployer",
            "pattern_learning": "governance_pattern_learner",
            "validation": "model_validator"
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
        Inject latency into learning system operations.

        Examples:
        - component="continuous_learning_pipeline", injection_point="data_loading"
        - component="safe_upgrade_deployer", injection_point="model_upload"
        """
        injection_id = f"learning_latency_{uuid.uuid4().hex[:8]}"

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
            f"Learning latency injection: {component}.{injection_point} "
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
        Inject errors into learning system operations.

        Examples:
        - component="continuous_learning_pipeline", error_type="TrainingFailure"
        - component="governance_pattern_learner", error_type="PatternExtractionError"
        """
        injection_id = f"learning_error_{uuid.uuid4().hex[:8]}"

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
            f"Learning error injection: {component}.{injection_point} "
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
        Inject resource exhaustion into learning system.

        Examples:
        - resource_type="training_memory" (model training OOM)
        - resource_type="gpu_utilization" (GPU exhaustion during training)
        """
        injection_id = f"learning_resource_{uuid.uuid4().hex[:8]}"

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
            f"Learning resource exhaustion: {component}.{resource_type} "
            f"(experiment: {target_id})"
        )

        return handle

    async def get_health_metrics(self) -> Dict[str, Any]:
        """
        Get health metrics for learning system.

        Metrics:
        - training_success_rate: Success rate of training runs
        - deployment_success_rate: Success rate of deployments
        - pattern_extraction_latency_p95: Pattern learning latency
        - model_validation_error_rate: Validation error rate
        """
        # In production, these would come from actual monitoring
        metrics = {
            "training_success_rate": 0.95,  # 95% success
            "deployment_success_rate": 0.98,  # 98% success
            "pattern_extraction_latency_p95": 200.0,  # ms
            "pattern_extraction_latency_p99": 500.0,  # ms
            "model_validation_error_rate": 0.02,  # 2%
            "active_training_jobs": len(self.active_injections),
            "healthy": True
        }

        # Mark as unhealthy if success rates are low
        if metrics["training_success_rate"] < 0.8 or metrics["deployment_success_rate"] < 0.9:
            metrics["healthy"] = False

        return metrics

    async def cleanup(self):
        """
        Clean up all active chaos injections for learning system.
        """
        logger.info(f"Cleaning up {len(self.active_injections)} learning system injections")

        # Disable all chaos contexts
        for injection_id, handle in list(self.active_injections.items()):
            handle.stop()

        # Clear all injections
        self.active_injections.clear()

        # Disable all chaos for learning system components
        await ChaosContext.disable_all()

        logger.info("Learning system chaos cleanup complete")


# Singleton instance
_learning_adapter = None


def get_learning_adapter() -> LearningSystemAdapter:
    """Get global learning system adapter instance"""
    global _learning_adapter
    if _learning_adapter is None:
        _learning_adapter = LearningSystemAdapter()
    return _learning_adapter
