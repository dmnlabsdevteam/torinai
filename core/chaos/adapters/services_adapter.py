#!/usr/bin/env python3
"""
Services System Chaos Adapter
==============================

Chaos injection for services system components:
- Unified LLM Service
- Backup Scheduler
- Document Generator
- Adapter Manager
- Lumen Vision
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


class ServicesSystemAdapter(TargetSystemAdapter):
    """
    Adapter for chaos injection into services system.

    Targets:
    - Unified LLM Service (local LLM inference, request queue)
    - Backup Scheduler (backup operations, scheduling)
    - Adapter Manager (adapter lifecycle management)
    - Lumen Vision (vision processing)

    Components:
    - unified_llm: Local Qwen 32B model inference
    - backup_scheduler: Automated backup scheduling
    - adapter_manager: Service adapter management
    - lumen_vision: Vision processing service
    """

    def __init__(self):
        super().__init__("services_system")
        self._original_methods: Dict[str, Any] = {}
        self._chaos_active = False
        self.db = None  # Database for persistence (call initialize_db() to enable)

        # Services-specific metrics
        self._llm_inference_latencies: list = []
        self._llm_errors: int = 0
        self._backup_failures: int = 0
        self._document_generation_errors: int = 0
        self._vision_processing_errors: int = 0

    async def inject_latency(
        self,
        target_id: str,
        component: str,
        injection_point: str,
        delay_ms: int,
        jitter_ms: int = 0
    ) -> InjectionHandle:
        """
        Inject latency into services system operations.

        Injection points:
        - llm_inference: Delay in LLM model inference
        - llm_queue: Delay in request queue processing
        - backup_operation: Delay in backup operations
        - document_generation: Delay in document generation
        - vision_processing: Delay in vision processing
        - adapter_init: Delay in adapter initialization
        """
        self._chaos_active = True

        injection_id = f"services_latency_{uuid.uuid4().hex[:8]}"

        logger.info(
            f"[ServicesAdapter] Injecting {delay_ms}ms latency "
            f"at {component}:{injection_point} (experiment: {target_id})"
        )

        if injection_point == "llm_inference":
            # Inject latency into LLM inference
            await self._inject_llm_inference_latency(delay_ms, jitter_ms)

        elif injection_point == "llm_queue":
            # Inject latency into request queue
            await self._inject_llm_queue_latency(delay_ms, jitter_ms)

        elif injection_point == "backup_operation":
            # Inject latency into backup operations
            await self._inject_backup_latency(delay_ms, jitter_ms)

        elif injection_point == "document_generation":
            # Inject latency into document generation
            await self._inject_document_gen_latency(delay_ms, jitter_ms)

        elif injection_point == "vision_processing":
            # Inject latency into vision processing
            await self._inject_vision_latency(delay_ms, jitter_ms)

        elif injection_point == "adapter_init":
            # Inject latency into adapter initialization
            await self._inject_adapter_init_latency(delay_ms, jitter_ms)
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
        Inject errors into services system operations.

        Error types:
        - LLMInferenceError: LLM model inference failures
        - ModelLoadError: Failed to load LLM model
        - BackupError: Backup operation failures
        - DocumentGenerationError: Document generation failures
        - VisionProcessingError: Vision processing failures
        - AdapterError: Adapter initialization/lifecycle errors
        - QueueTimeoutError: Request queue timeout
        """
        self._chaos_active = True

        
        injection_id = f"services_error_{uuid.uuid4().hex[:8]}"

        logger.info(
            f"[ServicesAdapter] Injecting {error_rate*100}% error rate "
            f"at {component}:{injection_point} ({error_type}, experiment: {target_id})"
        )

        if injection_point == "llm_inference":
            # Inject LLM inference errors
            await self._inject_llm_errors(error_rate, error_type)

        elif injection_point == "llm_queue":
            # Inject request queue errors
            await self._inject_queue_errors(error_rate, error_type)

        elif injection_point == "backup_operation":
            # Inject backup errors
            await self._inject_backup_errors(error_rate, error_type)

        elif injection_point == "document_generation":
            # Inject document generation errors
            await self._inject_document_gen_errors(error_rate, error_type)

        elif injection_point == "vision_processing":
            # Inject vision processing errors
            await self._inject_vision_errors(error_rate, error_type)
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
        Inject resource exhaustion into services system.

        Resource types:
        - gpu: GPU memory exhaustion during LLM inference
        - cpu: High CPU usage during inference
        - memory: Memory exhaustion in model loading
        - disk: Disk space exhaustion during backups
        - queue: Request queue exhaustion
        """
        self._chaos_active = True

        
        injection_id = f"services_resource_{uuid.uuid4().hex[:8]}"

        logger.info(
            f"[ServicesAdapter] Injecting {resource_type} exhaustion "
            f"at {component}"
        )

        if resource_type == "gpu":
            # Simulate GPU memory exhaustion
            await self._exhaust_gpu_memory()

        elif resource_type == "cpu":
            # Simulate high CPU usage during inference
            await self._exhaust_inference_cpu()

        elif resource_type == "memory":
            # Simulate memory exhaustion in model loading
            await self._exhaust_model_memory()

        elif resource_type == "disk":
            # Simulate disk space exhaustion
            await self._exhaust_disk_space()

        elif resource_type == "queue":
            # Simulate request queue exhaustion
            await self._exhaust_request_queue()
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
        Get current health metrics of services system.

        Metrics:
        - llm_inference_latency_p95: 95th percentile LLM inference latency
        - llm_error_rate: LLM inference error rate
        - backup_failure_rate: Backup operation failure rate
        - document_gen_error_rate: Document generation error rate
        - vision_error_rate: Vision processing error rate
        - queue_depth: Request queue depth
        - gpu_utilization: GPU utilization percentage
        """
        metrics = {}

        # Calculate latency metrics
        if self._llm_inference_latencies:
            sorted_latencies = sorted(self._llm_inference_latencies)
            p95_idx = int(len(sorted_latencies) * 0.95)
            p99_idx = int(len(sorted_latencies) * 0.99)

            metrics["latency_p95_ms"] = sorted_latencies[p95_idx] if sorted_latencies else 0
            metrics["latency_p99_ms"] = sorted_latencies[p99_idx] if sorted_latencies else 0
        else:
            metrics["latency_p95_ms"] = 0
            metrics["latency_p99_ms"] = 0

        # Calculate error rates
        total_operations = 1000  # Simulated total operations
        metrics["llm_error_rate"] = self._llm_errors / total_operations
        metrics["backup_failure_rate"] = self._backup_failures / total_operations
        metrics["document_gen_error_rate"] = self._document_generation_errors / total_operations
        metrics["vision_error_rate"] = self._vision_processing_errors / total_operations

        # Queue metrics
        metrics["queue_depth"] = random.uniform(5, 20) if not self._chaos_active else random.uniform(50, 200)

        # GPU metrics
        metrics["gpu_utilization"] = random.uniform(30, 60) if not self._chaos_active else random.uniform(80, 98)

        # Resource metrics (simulated)
        metrics["cpu_percent"] = random.uniform(20, 50) if not self._chaos_active else random.uniform(70, 95)
        metrics["memory_percent"] = random.uniform(40, 70) if not self._chaos_active else random.uniform(80, 95)

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
        """Clean up all active chaos injections for services system."""
        logger.info(f"Cleaning up {len(self.active_injections)} services system injections")

        # Stop all active injections
        for handle in list(self.active_injections.values()):
            handle.stop()

        # Clear all injections
        self.active_injections.clear()

        # Reset chaos state
        self._chaos_active = False
        self._original_methods.clear()
        self._llm_inference_latencies.clear()
        self._llm_errors = 0
        self._backup_failures = 0
        self._document_generation_errors = 0
        self._vision_processing_errors = 0

        logger.info("Services system chaos cleanup complete")

    # Private helper methods

    async def _inject_llm_inference_latency(self, delay_ms: int, jitter_ms: int):
        """Inject latency into LLM inference."""
        actual_delay = delay_ms + random.randint(-jitter_ms, jitter_ms)
        await asyncio.sleep(actual_delay / 1000.0)
        self._llm_inference_latencies.append(actual_delay)

    async def _inject_llm_queue_latency(self, delay_ms: int, jitter_ms: int):
        """Inject latency into request queue."""
        actual_delay = delay_ms + random.randint(-jitter_ms, jitter_ms)
        await asyncio.sleep(actual_delay / 1000.0)

    async def _inject_backup_latency(self, delay_ms: int, jitter_ms: int):
        """Inject latency into backup operations."""
        actual_delay = delay_ms + random.randint(-jitter_ms, jitter_ms)
        await asyncio.sleep(actual_delay / 1000.0)

    async def _inject_document_gen_latency(self, delay_ms: int, jitter_ms: int):
        """Inject latency into document generation."""
        actual_delay = delay_ms + random.randint(-jitter_ms, jitter_ms)
        await asyncio.sleep(actual_delay / 1000.0)

    async def _inject_vision_latency(self, delay_ms: int, jitter_ms: int):
        """Inject latency into vision processing."""
        actual_delay = delay_ms + random.randint(-jitter_ms, jitter_ms)
        await asyncio.sleep(actual_delay / 1000.0)

    async def _inject_adapter_init_latency(self, delay_ms: int, jitter_ms: int):
        """Inject latency into adapter initialization."""
        actual_delay = delay_ms + random.randint(-jitter_ms, jitter_ms)
        await asyncio.sleep(actual_delay / 1000.0)

    async def _inject_llm_errors(self, error_rate: float, error_type: str):
        """Inject LLM inference errors."""
        if random.random() < error_rate:
            self._llm_errors += 1
            logger.warning(f"[ServicesAdapter] Injected LLM error: {error_type}")

    async def _inject_queue_errors(self, error_rate: float, error_type: str):
        """Inject request queue errors."""
        if random.random() < error_rate:
            logger.warning(f"[ServicesAdapter] Injected queue error: {error_type}")

    async def _inject_backup_errors(self, error_rate: float, error_type: str):
        """Inject backup errors."""
        if random.random() < error_rate:
            self._backup_failures += 1
            logger.warning(f"[ServicesAdapter] Injected backup error: {error_type}")

    async def _inject_document_gen_errors(self, error_rate: float, error_type: str):
        """Inject document generation errors."""
        if random.random() < error_rate:
            self._document_generation_errors += 1
            logger.warning(f"[ServicesAdapter] Injected document gen error: {error_type}")

    async def _inject_vision_errors(self, error_rate: float, error_type: str):
        """Inject vision processing errors."""
        if random.random() < error_rate:
            self._vision_processing_errors += 1
            logger.warning(f"[ServicesAdapter] Injected vision error: {error_type}")

    async def _exhaust_gpu_memory(self):
        """Simulate GPU memory exhaustion."""
        # Simulate GPU memory allocation
        _ = [0] * (100 * 1024 * 1024)  # 100MB allocation

    async def _exhaust_inference_cpu(self):
        """Simulate high CPU usage during inference."""
        # Simulate CPU-intensive inference
        start = asyncio.get_event_loop().time()
        while asyncio.get_event_loop().time() - start < 0.15:  # 150ms of busy work
            _ = [i ** 2 for i in range(2000)]

    async def _exhaust_model_memory(self):
        """Simulate memory exhaustion in model loading."""
        # Simulate large model in memory
        _ = [0] * (200 * 1024 * 1024)  # 200MB allocation

    async def _exhaust_disk_space(self):
        """Simulate disk space exhaustion."""
        # Simulate large backup file
        _ = [0] * (500 * 1024 * 1024)  # 500MB allocation

    async def _exhaust_request_queue(self):
        """Simulate request queue exhaustion."""
        # Simulate queue overflow
        _ = [[0] * 1000 for _ in range(50000)]  # Large queue
