#!/usr/bin/env python3
"""
Intelligence System Chaos Adapter
==================================

Chaos injection for intelligence system components:
- NLP Optimizer
- Predictive Intelligence System
"""

import asyncio
import logging
import random
import uuid
from typing import Dict, Any, Optional
from datetime import datetime

from .base_adapter import TargetSystemAdapter
from ..types import ChaosType, InjectionHandle

logger = logging.getLogger(__name__)


class IntelligenceSystemAdapter(TargetSystemAdapter):
    """
    Adapter for chaos injection into intelligence system.

    Targets:
    - NLP Optimizer (text processing, lemmatization, tokenization)
    - Predictive Intelligence System (predictions, forecasting)

    Components:
    - nlp_processor: NLP text processing pipeline
    - predictive_system: Predictive intelligence and forecasting
    - prediction_cache: Prediction caching layer
    - model_inference: Model inference engine
    """

    def __init__(self):
        super().__init__("intelligence_system")
        self._original_methods: Dict[str, Any] = {}
        self._chaos_active = False
        self.db = None  # Database for persistence (call initialize_db() to enable)

        # Intelligence-specific metrics
        self._prediction_latencies: list = []
        self._nlp_processing_errors: int = 0
        self._prediction_errors: int = 0
        self._cache_misses: int = 0

    async def inject_latency(
        self,
        target_id: str,
        component: str,
        injection_point: str,
        delay_ms: int,
        jitter_ms: int = 0
    ) -> InjectionHandle:
        """
        Inject latency into intelligence system operations.

        Injection points:
        - nlp_processing: Delay in text processing pipeline
        - prediction_inference: Delay in prediction generation
        - model_loading: Delay in model initialization
        - cache_lookup: Delay in cache operations
        """
        self._chaos_active = True

        injection_id = f"intelligence_latency_{uuid.uuid4().hex[:8]}"

        logger.info(
            f"[IntelligenceAdapter] Injecting {delay_ms}ms latency "
            f"at {component}:{injection_point} (experiment: {target_id})"
        )

        if injection_point == "nlp_processing":
            # Inject latency into NLP text processing
            await self._inject_nlp_latency(delay_ms, jitter_ms)

        elif injection_point == "prediction_inference":
            # Inject latency into prediction generation
            await self._inject_prediction_latency(delay_ms, jitter_ms)

        elif injection_point == "model_loading":
            # Inject latency into model initialization
            await self._inject_model_load_latency(delay_ms, jitter_ms)

        elif injection_point == "cache_lookup":
            # Inject latency into cache operations
            await self._inject_cache_latency(delay_ms, jitter_ms)
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
        Inject errors into intelligence system operations.

        Error types:
        - NLPProcessingError: Text processing failures
        - PredictionError: Prediction generation failures
        - ModelLoadError: Model loading failures
        - CacheMissError: Forced cache misses
        - InferenceError: Model inference failures
        """
        self._chaos_active = True

        
        injection_id = f"intelligence_error_{uuid.uuid4().hex[:8]}"

        logger.info(
            f"[IntelligenceAdapter] Injecting {error_rate*100}% error rate "
            f"at {component}:{injection_point} ({error_type}, experiment: {target_id})"
        )

        if injection_point == "nlp_processing":
            # Inject NLP processing errors
            await self._inject_nlp_errors(error_rate, error_type)

        elif injection_point == "prediction_inference":
            # Inject prediction errors
            await self._inject_prediction_errors(error_rate, error_type)

        elif injection_point == "model_loading":
            # Inject model loading errors
            await self._inject_model_load_errors(error_rate, error_type)

        elif injection_point == "cache_operations":
            # Inject cache operation errors (forced misses)
            await self._inject_cache_errors(error_rate)
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

        return handle

    async def inject_resource_exhaustion(
        self,
        target_id: str,
        component: str,
        resource_type: str,
        limit_value: Optional[float] = None
    ) -> InjectionHandle:
        """
        Inject resource exhaustion into intelligence system.

        Resource types:
        - cpu: High CPU usage during NLP processing
        - memory: Memory exhaustion in prediction models
        - cache: Cache capacity exhaustion
        - model_memory: Model memory overflow
        """
        self._chaos_active = True

        
        injection_id = f"intelligence_resource_{uuid.uuid4().hex[:8]}"

        logger.info(
            f"[IntelligenceAdapter] Injecting {resource_type} exhaustion "
            f"at {component}"
        )

        if resource_type == "cpu":
            # Simulate high CPU usage during NLP processing
            await self._exhaust_nlp_cpu()

        elif resource_type == "memory":
            # Simulate memory exhaustion in prediction models
            await self._exhaust_prediction_memory()

        elif resource_type == "cache":
            # Simulate cache capacity exhaustion
            await self._exhaust_cache_capacity()

        elif resource_type == "model_memory":
            # Simulate model memory overflow
            await self._exhaust_model_memory()
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

        return handle

    async def get_health_metrics(self) -> Dict[str, Any]:
        """
        Get current health metrics of intelligence system.

        Metrics:
        - nlp_processing_latency_p95: 95th percentile NLP processing latency
        - prediction_latency_p95: 95th percentile prediction latency
        - nlp_error_rate: NLP processing error rate
        - prediction_error_rate: Prediction error rate
        - cache_hit_rate: Prediction cache hit rate
        - active_predictions: Number of active predictions
        """
        metrics = {}

        # Calculate latency metrics
        if self._prediction_latencies:
            sorted_latencies = sorted(self._prediction_latencies)
            p95_idx = int(len(sorted_latencies) * 0.95)
            p99_idx = int(len(sorted_latencies) * 0.99)

            metrics["latency_p95_ms"] = sorted_latencies[p95_idx] if sorted_latencies else 0
            metrics["latency_p99_ms"] = sorted_latencies[p99_idx] if sorted_latencies else 0
        else:
            metrics["latency_p95_ms"] = 0
            metrics["latency_p99_ms"] = 0

        # Calculate error rates
        total_operations = 1000  # Simulated total operations
        metrics["nlp_error_rate"] = self._nlp_processing_errors / total_operations
        metrics["prediction_error_rate"] = self._prediction_errors / total_operations

        # Cache metrics
        total_cache_ops = 500
        metrics["cache_hit_rate"] = (total_cache_ops - self._cache_misses) / total_cache_ops

        # Resource metrics (simulated)
        metrics["cpu_percent"] = random.uniform(20, 70) if not self._chaos_active else random.uniform(60, 95)
        metrics["memory_percent"] = random.uniform(30, 60) if not self._chaos_active else random.uniform(70, 90)

        # Active injections
        metrics["active_chaos_injections"] = len(self.active_injections)

        # Health status
        metrics["healthy"] = True

        # Mark as unhealthy if latency is very high or error rates are high
        if max(metrics.get("latency_p95_ms", 0), metrics.get("prediction_latency_p95", 0), metrics.get("export_latency_p95", 0)) > 500:
            metrics["healthy"] = False

        if any(v > 0.05 for k, v in metrics.items() if "error_rate" in k):
            metrics["healthy"] = False

        return metrics

    async def cleanup(self) -> None:
        """Clean up all active chaos injections for intelligence system."""
        logger.info(f"Cleaning up {len(self.active_injections)} intelligence system injections")

        # Stop all active injections
        for handle in list(self.active_injections.values()):
            handle.stop()

        # Clear all injections
        self.active_injections.clear()

        # Reset chaos state
        self._chaos_active = False
        self._original_methods.clear()
        self._prediction_latencies.clear()
        self._nlp_processing_errors = 0
        self._prediction_errors = 0
        self._cache_misses = 0

        logger.info("[IntelligenceAdapter] Chaos injection cleaned up")

    # Private helper methods

    async def _inject_nlp_latency(self, delay_ms: int, jitter_ms: int):
        """Inject latency into NLP processing."""
        actual_delay = delay_ms + random.randint(-jitter_ms, jitter_ms)
        await asyncio.sleep(actual_delay / 1000.0)
        self._prediction_latencies.append(actual_delay)

    async def _inject_prediction_latency(self, delay_ms: int, jitter_ms: int):
        """Inject latency into prediction generation."""
        actual_delay = delay_ms + random.randint(-jitter_ms, jitter_ms)
        await asyncio.sleep(actual_delay / 1000.0)
        self._prediction_latencies.append(actual_delay)

    async def _inject_model_load_latency(self, delay_ms: int, jitter_ms: int):
        """Inject latency into model loading."""
        actual_delay = delay_ms + random.randint(-jitter_ms, jitter_ms)
        await asyncio.sleep(actual_delay / 1000.0)

    async def _inject_cache_latency(self, delay_ms: int, jitter_ms: int):
        """Inject latency into cache operations."""
        actual_delay = delay_ms + random.randint(-jitter_ms, jitter_ms)
        await asyncio.sleep(actual_delay / 1000.0)

    async def _inject_nlp_errors(self, error_rate: float, error_type: str):
        """Inject NLP processing errors."""
        if random.random() < error_rate:
            self._nlp_processing_errors += 1
            logger.warning(f"[IntelligenceAdapter] Injected NLP error: {error_type}")

    async def _inject_prediction_errors(self, error_rate: float, error_type: str):
        """Inject prediction generation errors."""
        if random.random() < error_rate:
            self._prediction_errors += 1
            logger.warning(f"[IntelligenceAdapter] Injected prediction error: {error_type}")

    async def _inject_model_load_errors(self, error_rate: float, error_type: str):
        """Inject model loading errors."""
        if random.random() < error_rate:
            logger.warning(f"[IntelligenceAdapter] Injected model load error: {error_type}")
            raise Exception(f"Model load failed: {error_type}")

    async def _inject_cache_errors(self, error_rate: float):
        """Inject cache operation errors (forced misses)."""
        if random.random() < error_rate:
            self._cache_misses += 1

    async def _exhaust_nlp_cpu(self):
        """Simulate high CPU usage during NLP processing."""
        # Simulate CPU-intensive NLP operations
        start = asyncio.get_event_loop().time()
        while asyncio.get_event_loop().time() - start < 0.1:  # 100ms of busy work
            _ = [i ** 2 for i in range(1000)]

    async def _exhaust_prediction_memory(self):
        """Simulate memory exhaustion in prediction models."""
        # Simulate large prediction model in memory
        _ = [0] * (10 * 1024 * 1024)  # 10MB allocation

    async def _exhaust_cache_capacity(self):
        """Simulate cache capacity exhaustion."""
        # Force cache misses
        for _ in range(100):
            self._cache_misses += 1

    async def _exhaust_model_memory(self):
        """Simulate model memory overflow."""
        # Simulate large model allocation
        _ = [0] * (50 * 1024 * 1024)  # 50MB allocation
