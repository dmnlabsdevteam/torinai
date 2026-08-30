#!/usr/bin/env python3
"""
Prometheus Metrics Exporter
============================
Exports TorinAI system metrics in Prometheus format

Purpose:
- Export system metrics (CPU, memory, disk)
- Export LLM request metrics (requests, tokens, latency)
- Export agent metrics (by type and status)
- Export database metrics (connections, queries)
- Support /metrics endpoint for Prometheus scraping
"""

import asyncio
import logging
import os
import psutil
import platform
from typing import Dict, Any, List, Optional
from datetime import datetime

# Prometheus client
try:
    from prometheus_client import (
        Counter, Gauge, Histogram, Info,
        CollectorRegistry, generate_latest, REGISTRY
    )
    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False
    logging.warning("prometheus_client not available - metrics export disabled")

logger = logging.getLogger(__name__)


class PrometheusMetrics:
    """Prometheus metrics exporter for TorinAI"""

    def __init__(self):
        if not PROMETHEUS_AVAILABLE:
            logger.warning("Prometheus client not available - metrics disabled")
            return

        # System metrics (Gauges - current values)
        self.cpu_usage = Gauge('torin_cpu_usage_percent', 'CPU usage percentage')
        self.memory_usage = Gauge('torin_memory_usage_mb', 'Memory usage in MB')
        self.disk_usage = Gauge('torin_disk_usage_percent', 'Disk usage percentage')
        self.gpu_memory_usage = Gauge('torin_gpu_memory_mb', 'GPU memory usage in MB')
        self.process_memory = Gauge('torin_process_memory_mb', 'Process memory usage in MB')

        # LLM metrics (Counters and Histograms)
        self.llm_requests = Counter('torin_llm_requests_total', 'Total LLM requests', ['agent_type', 'model', 'status'])
        self.llm_tokens = Counter('torin_llm_tokens_total', 'Total LLM tokens used', ['agent_type', 'model'])
        self.llm_latency = Histogram('torin_llm_latency_seconds', 'LLM request latency', ['agent_type', 'model'])
        self.llm_errors = Counter('torin_llm_errors_total', 'Total LLM errors', ['agent_type', 'error_type'])
        self.llm_queue_size = Gauge('torin_llm_queue_size', 'LLM request queue size')
        self.llm_active_requests = Gauge('torin_llm_active_requests', 'Active LLM requests')
        self.llm_cache_hits = Counter('torin_llm_cache_hits', 'LLM cache hits', ['type'])

        # Agent metrics (Counters)
        self.agent_tasks = Counter('torin_agent_tasks_total', 'Total agent tasks', ['agent_type'])
        self.agent_errors = Counter('torin_agent_errors_total', 'Total agent errors', ['agent_type', 'error'])

        # Memory system metrics
        self.memory_operations = Counter('torin_memory_operations_total', 'Memory operations', ['operation'])
        self.memory_size = Gauge('torin_memory_size_bytes', 'Memory system size in bytes')

        # Database metrics
        self.db_connections = Gauge('torin_db_connections', 'Database connections', ['pool'])
        self.db_queries = Counter('torin_db_queries_total', 'Database queries', ['table', 'operation'])
        self.db_query_latency = Histogram('torin_db_query_latency_seconds', 'Database query latency')

        # Learning metrics
        self.learning_cycles = Counter('torin_learning_cycles_total', 'Learning cycles completed')
        self.learning_improvements = Counter('torin_learning_improvements_total', 'Improvements deployed')
        self.learning_safety_blocks = Counter('torin_learning_safety_blocks_total', 'Safety blocks')

        # System info (metadata)
        self.system_info = Info('torin_system', 'System information')

        logger.info("Prometheus metrics initialized")

    def export_metrics(self) -> bytes:
        """Export metrics in Prometheus format"""
        if not PROMETHEUS_AVAILABLE:
            return b""

        try:
            # Update system metrics before export
            self.update_system_metrics()

            # Generate Prometheus format
            metrics_output = generate_latest(REGISTRY)
            return metrics_output

        except Exception as e:
            logger.error(f"Failed to export metrics: {e}")
            return b""

    def update_system_metrics(self):
        """Update system metrics (CPU, memory, disk)"""
        if not PROMETHEUS_AVAILABLE:
            return

        try:
            # CPU usage
            cpu_percent = psutil.cpu_percent(interval=0.1)
            self.cpu_usage.set(cpu_percent)

            # Memory usage
            memory = psutil.virtual_memory()
            self.memory_usage.set(memory.used / (1024 * 1024))  # MB

            # Disk usage
            disk = psutil.disk_usage('/')
            self.disk_usage.set(disk.percent)

        except Exception as e:
            logger.error(f"Failed to update system metrics: {e}")

    def record_llm_request(
        self,
        agent_type: str,
        model: str,
        status: str,
        tokens: int,
        latency: float
    ):
        """Record LLM request metrics"""
        if not PROMETHEUS_AVAILABLE:
            return

        try:
            self.llm_requests.labels(agent_type=agent_type, model=model, status=status).inc()
            self.llm_tokens.labels(agent_type=agent_type, model=model).inc(tokens)
            self.llm_latency.labels(agent_type=agent_type, model=model).observe(latency)
        except Exception as e:
            logger.error(f"Failed to record LLM metrics: {e}")

    def record_agent_task(
        self,
        agent_type: str,
        success: bool,
        error: str = None
    ):
        """Record agent task metrics"""
        if not PROMETHEUS_AVAILABLE:
            return

        try:
            self.agent_tasks.labels(agent_type=agent_type).inc()
            if not success and error:
                self.agent_errors.labels(agent_type=agent_type, error=error).inc()
        except Exception as e:
            logger.error(f"Failed to record agent metrics: {e}")


# Singleton instance
_metrics_instance = None


def get_prometheus_metrics() -> PrometheusMetrics:
    """Get global Prometheus metrics instance"""
    global _metrics_instance
    if _metrics_instance is None:
        _metrics_instance = PrometheusMetrics()
    return _metrics_instance


# FastAPI endpoint helper
def create_metrics_endpoint(app):
    """Create FastAPI metrics endpoint (for integration)"""
    if not PROMETHEUS_AVAILABLE:
        logger.warning("Prometheus not available - endpoint disabled")
        return None

    from fastapi import Response

    @app.get("/metrics")
    async def metrics():
        """Prometheus metrics endpoint"""
        # Update metrics before serving
        metrics = get_prometheus_metrics()
        output = metrics.export_metrics()

        return Response(
            content=output,
            media_type="text/plain"
        )

    logger.info("Metrics endpoint created at /metrics")


# CLI test
async def main():
    """Test metrics export"""
    logging.basicConfig(level=logging.INFO)

    if not PROMETHEUS_AVAILABLE:
        logger.error("Prometheus client not installed")
        return

    try:
        # Create metrics instance
        metrics = get_prometheus_metrics()

        # Update system metrics
        logger.info("Updating system metrics")
        metrics.update_system_metrics()

        # Simulate LLM request
        logger.info("Recording test LLM request")
        metrics.record_llm_request(
            agent_type="test",
            model="qwen-32b",
            status="success",
            tokens=150,
            latency=1.5
        )

        # Export metrics
        logger.info("Exporting metrics")
        output = metrics.export_metrics()

        print("\n=== Prometheus Metrics ===")
        print(output.decode('utf-8'))

    except Exception as e:
        logger.error(f"Test failed: {e}")


if __name__ == "__main__":
    asyncio.run(main())
