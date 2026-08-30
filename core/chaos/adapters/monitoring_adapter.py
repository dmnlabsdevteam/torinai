#!/usr/bin/env python3
"""
Monitoring System Chaos Adapter
================================

Chaos injection for monitoring system components:
- Prometheus Exporter
- Resource Monitoring
- Metric Collection
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


class MonitoringSystemAdapter(TargetSystemAdapter):
    """
    Adapter for chaos injection into monitoring system.

    Targets:
    - Prometheus Exporter (metrics export, scraping endpoint)
    - Resource Monitoring (CPU, memory, disk monitoring)
    - Metric Collection (metric aggregation, publishing)

    Components:
    - prometheus_exporter: Metrics export to Prometheus
    - resource_monitor: System resource monitoring
    - metric_collector: Metric collection and aggregation
    - metric_publisher: Metric publishing to external systems
    """

    def __init__(self):
        super().__init__("monitoring_system")
        self._original_methods: Dict[str, Any] = {}
        self._chaos_active = False
        self.db = None  # Database for persistence (call initialize_db() to enable)

        # Monitoring-specific metrics
        self._export_latencies: list = []
        self._export_errors: int = 0
        self._metric_collection_errors: int = 0
        self._scrape_failures: int = 0

    async def inject_latency(
        self,
        target_id: str,
        component: str,
        injection_point: str,
        delay_ms: int,
        jitter_ms: int = 0
    ) -> InjectionHandle:
        """
        Inject latency into monitoring system operations.

        Injection points:
        - metrics_export: Delay in Prometheus metrics export
        - resource_monitoring: Delay in resource metric collection
        - metric_aggregation: Delay in metric aggregation
        - scrape_endpoint: Delay in /metrics endpoint response
        """
        self._chaos_active = True

        injection_id = f"monitoring_latency_{uuid.uuid4().hex[:8]}"

        logger.info(
            f"[MonitoringAdapter] Injecting {delay_ms}ms latency "
            f"at {component}:{injection_point} (experiment: {target_id})"
        )

        if injection_point == "metrics_export":
            # Inject latency into Prometheus export
            await self._inject_export_latency(delay_ms, jitter_ms)

        elif injection_point == "resource_monitoring":
            # Inject latency into resource monitoring
            await self._inject_resource_monitor_latency(delay_ms, jitter_ms)

        elif injection_point == "metric_aggregation":
            # Inject latency into metric aggregation
            await self._inject_aggregation_latency(delay_ms, jitter_ms)

        elif injection_point == "scrape_endpoint":
            # Inject latency into scrape endpoint response
            await self._inject_scrape_latency(delay_ms, jitter_ms)

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
        Inject errors into monitoring system operations.

        Error types:
        - MetricExportError: Failed to export metrics
        - ResourceMonitorError: Resource monitoring failures
        - MetricCollectionError: Metric collection failures
        - ScrapeTimeoutError: Scrape endpoint timeout
        - MetricPublishError: Failed to publish metrics
        """
        self._chaos_active = True

        injection_id = f"monitoring_error_{uuid.uuid4().hex[:8]}"

        logger.info(
            f"[MonitoringAdapter] Injecting {error_rate*100}% error rate "
            f"at {component}:{injection_point} ({error_type}, experiment: {target_id})"
        )

        if injection_point == "metrics_export":
            # Inject metrics export errors
            await self._inject_export_errors(error_rate, error_type)

        elif injection_point == "resource_monitoring":
            # Inject resource monitoring errors
            await self._inject_resource_monitor_errors(error_rate, error_type)

        elif injection_point == "metric_collection":
            # Inject metric collection errors
            await self._inject_collection_errors(error_rate, error_type)

        elif injection_point == "scrape_endpoint":
            # Inject scrape endpoint failures
            await self._inject_scrape_errors(error_rate, error_type)

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
        Inject resource exhaustion into monitoring system.

        Resource types:
        - cpu: High CPU usage during metric collection
        - memory: Memory exhaustion in metric aggregation
        - metric_buffer: Metric buffer overflow
        - export_queue: Export queue exhaustion
        """
        self._chaos_active = True

        injection_id = f"monitoring_resource_{uuid.uuid4().hex[:8]}"

        logger.info(
            f"[MonitoringAdapter] Injecting {resource_type} exhaustion "
            f"at {component} (experiment: {target_id})"
        )

        if resource_type == "cpu":
            # Simulate high CPU usage during metric collection
            await self._exhaust_collection_cpu()

        elif resource_type == "memory":
            # Simulate memory exhaustion in metric aggregation
            await self._exhaust_aggregation_memory()

        elif resource_type == "metric_buffer":
            # Simulate metric buffer overflow
            await self._exhaust_metric_buffer()

        elif resource_type == "export_queue":
            # Simulate export queue exhaustion
            await self._exhaust_export_queue()

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
        Get current health metrics of monitoring system.

        Metrics:
        - export_latency_p95: 95th percentile metrics export latency
        - export_error_rate: Metrics export error rate
        - collection_error_rate: Metric collection error rate
        - scrape_failure_rate: Scrape endpoint failure rate
        - metric_throughput: Metrics processed per second
        - buffer_utilization: Metric buffer utilization percentage
        """
        metrics = {}

        # Calculate latency metrics
        if self._export_latencies:
            sorted_latencies = sorted(self._export_latencies)
            p95_idx = int(len(sorted_latencies) * 0.95)
            p99_idx = int(len(sorted_latencies) * 0.99)

            metrics["export_latency_p95"] = sorted_latencies[p95_idx] if sorted_latencies else 0
            metrics["export_latency_p99"] = sorted_latencies[p99_idx] if sorted_latencies else 0
        else:
            metrics["export_latency_p95"] = 0
            metrics["export_latency_p99"] = 0

        # Calculate error rates
        total_operations = 1000  # Simulated total operations
        metrics["export_error_rate"] = self._export_errors / total_operations
        metrics["collection_error_rate"] = self._metric_collection_errors / total_operations
        metrics["scrape_failure_rate"] = self._scrape_failures / total_operations

        # Throughput metrics
        metrics["metric_throughput"] = random.uniform(100, 500) if not self._chaos_active else random.uniform(20, 100)

        # Buffer utilization
        metrics["buffer_utilization"] = random.uniform(20, 50) if not self._chaos_active else random.uniform(70, 95)

        # Resource metrics (simulated)
        metrics["cpu_percent"] = random.uniform(10, 40) if not self._chaos_active else random.uniform(60, 90)
        metrics["memory_percent"] = random.uniform(20, 50) if not self._chaos_active else random.uniform(65, 85)

        # Active injections
        metrics["active_chaos_injections"] = len(self.active_injections)

        # Health status
        metrics["healthy"] = True

        # Mark as unhealthy if latency is very high
        if metrics["export_latency_p95"] > 500:
            metrics["healthy"] = False

        # Mark as unhealthy if error rates are high
        if (metrics["export_error_rate"] > 0.05 or
            metrics["collection_error_rate"] > 0.05 or
            metrics["scrape_failure_rate"] > 0.1):
            metrics["healthy"] = False

        # Mark as unhealthy if buffer is nearly full
        if metrics["buffer_utilization"] > 90:
            metrics["healthy"] = False

        # Mark as unhealthy if resource utilization is critical
        if metrics["cpu_percent"] > 85 or metrics["memory_percent"] > 80:
            metrics["healthy"] = False

        return metrics

    async def cleanup(self) -> None:
        """Clean up all active chaos injections for monitoring system."""
        logger.info(f"Cleaning up {len(self.active_injections)} monitoring system injections")

        # Stop all active injections
        for handle in list(self.active_injections.values()):
            handle.stop()

        # Clear all injections
        self.active_injections.clear()

        # Reset chaos state
        self._chaos_active = False
        self._original_methods.clear()
        self._export_latencies.clear()
        self._export_errors = 0
        self._metric_collection_errors = 0
        self._scrape_failures = 0

        logger.info("Monitoring system chaos cleanup complete")

    # Private helper methods

    async def _inject_export_latency(self, delay_ms: int, jitter_ms: int):
        """Inject latency into metrics export."""
        actual_delay = delay_ms + random.randint(-jitter_ms, jitter_ms)
        await asyncio.sleep(actual_delay / 1000.0)
        self._export_latencies.append(actual_delay)

    async def _inject_resource_monitor_latency(self, delay_ms: int, jitter_ms: int):
        """Inject latency into resource monitoring."""
        actual_delay = delay_ms + random.randint(-jitter_ms, jitter_ms)
        await asyncio.sleep(actual_delay / 1000.0)

    async def _inject_aggregation_latency(self, delay_ms: int, jitter_ms: int):
        """Inject latency into metric aggregation."""
        actual_delay = delay_ms + random.randint(-jitter_ms, jitter_ms)
        await asyncio.sleep(actual_delay / 1000.0)

    async def _inject_scrape_latency(self, delay_ms: int, jitter_ms: int):
        """Inject latency into scrape endpoint."""
        actual_delay = delay_ms + random.randint(-jitter_ms, jitter_ms)
        await asyncio.sleep(actual_delay / 1000.0)

    async def _inject_export_errors(self, error_rate: float, error_type: str):
        """Inject metrics export errors."""
        if random.random() < error_rate:
            self._export_errors += 1
            logger.warning(f"[MonitoringAdapter] Injected export error: {error_type}")

    async def _inject_resource_monitor_errors(self, error_rate: float, error_type: str):
        """Inject resource monitoring errors."""
        if random.random() < error_rate:
            logger.warning(f"[MonitoringAdapter] Injected resource monitor error: {error_type}")

    async def _inject_collection_errors(self, error_rate: float, error_type: str):
        """Inject metric collection errors."""
        if random.random() < error_rate:
            self._metric_collection_errors += 1
            logger.warning(f"[MonitoringAdapter] Injected collection error: {error_type}")

    async def _inject_scrape_errors(self, error_rate: float, error_type: str):
        """Inject scrape endpoint errors."""
        if random.random() < error_rate:
            self._scrape_failures += 1
            logger.warning(f"[MonitoringAdapter] Injected scrape error: {error_type}")

    async def _exhaust_collection_cpu(self):
        """Simulate high CPU usage during metric collection."""
        # Simulate CPU-intensive metric collection
        start = asyncio.get_event_loop().time()
        while asyncio.get_event_loop().time() - start < 0.1:  # 100ms of busy work
            _ = [i ** 2 for i in range(1000)]

    async def _exhaust_aggregation_memory(self):
        """Simulate memory exhaustion in metric aggregation."""
        # Simulate large metric aggregation buffer
        _ = [0] * (20 * 1024 * 1024)  # 20MB allocation

    async def _exhaust_metric_buffer(self):
        """Simulate metric buffer overflow."""
        # Simulate buffer overflow by allocating large buffer
        _ = [0] * (50 * 1024 * 1024)  # 50MB allocation

    async def _exhaust_export_queue(self):
        """Simulate export queue exhaustion."""
        # Simulate queue overflow
        _ = [[0] * 1000 for _ in range(10000)]  # Large queue
