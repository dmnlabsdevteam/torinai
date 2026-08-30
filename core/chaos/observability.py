#!/usr/bin/env python3
"""
Chaos Observability
===================

Comprehensive observability for chaos experiments.

Features:
- Real-time metrics collection from target systems
- Hypothesis validation (expected vs actual behavior)
- Experiment report generation with insights
- Metrics aggregation and statistical analysis
- MySQL persistence for metrics and reports
"""

import asyncio
import logging
import statistics
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from .types import (
    ChaosExperiment,
    ExperimentResult,
    MetricsSnapshot,
    Hypothesis,
    SLOThresholds,
)
from .injection_engine import get_injection_engine
from ..database.logging_database import get_logging_db

logger = logging.getLogger(__name__)


class ChaosObservability:
    """
    Chaos Observability

    Provides comprehensive observability for chaos experiments:
    - Metrics collection and aggregation
    - Hypothesis validation
    - Report generation with insights
    - Statistical analysis
    """

    def __init__(self, config: Optional[Dict] = None):
        """
        Initialize chaos observability.

        Args:
            config: Optional configuration dict (from chaos_config.json)
        """
        self.config = config or self._load_default_config()

        # Logging database (PostgreSQL unified schema) for persistence
        self.db = get_logging_db()

        # Metrics collection configuration
        self.collection_interval = self.config.get("observability", {}).get(
            "metrics_collection_interval_seconds", 5
        )
        self.retention_days = self.config.get("observability", {}).get(
            "metrics_retention_days", 30
        )

        # Injection engine for health metrics
        self.injection_engine = get_injection_engine()

        logger.info("ChaosObservability initialized")

    def _load_default_config(self) -> Dict:
        """Load default observability configuration"""
        return {
            "observability": {
                "metrics_collection_interval_seconds": 5,
                "metrics_retention_days": 30,
                "enable_real_time_streaming": True,
                "enable_mysql_logging": True
            }
        }

    async def collect_metrics(
        self,
        target_system: str,
        experiment_id: str,
        duration_seconds: int
    ) -> List[MetricsSnapshot]:
        """
        Collect metrics from target system over duration.

        Args:
            target_system: Target system name
            experiment_id: Experiment ID
            duration_seconds: Collection duration

        Returns:
            List of MetricsSnapshot
        """
        metrics_collected: List[MetricsSnapshot] = []
        start_time = datetime.now()
        end_time = start_time + timedelta(seconds=duration_seconds)

        logger.info(
            f"Starting metrics collection for {target_system} "
            f"(experiment: {experiment_id}, duration: {duration_seconds}s)"
        )

        while datetime.now() < end_time:
            # Get health metrics from target system
            health_metrics = await self.injection_engine.get_system_health(target_system)

            if health_metrics:
                snapshot = MetricsSnapshot(
                    experiment_id=experiment_id,
                    timestamp=datetime.now(),
                    system_metrics={
                        "cpu_percent": health_metrics.get("cpu_percent", 0),
                        "memory_percent": health_metrics.get("memory_percent", 0)
                    },
                    component_metrics={
                        "latency_p95": health_metrics.get("tool_execution_latency_p95", 0),
                        "latency_p99": health_metrics.get("tool_execution_latency_p99", 0),
                        "error_rate": health_metrics.get("tool_error_rate", 0)
                    }
                )
                metrics_collected.append(snapshot)

                # Log to database if enabled
                if self.db and self.config.get("observability", {}).get("enable_mysql_logging", True):
                    await self._persist_metric(experiment_id, snapshot)

            # Wait before next collection
            await asyncio.sleep(self.collection_interval)

        logger.info(
            f"Metrics collection complete: {len(metrics_collected)} snapshots collected"
        )

        return metrics_collected

    async def _persist_metric(self, experiment_id: str, metric: MetricsSnapshot):
        """Persist metric snapshot to unified.chaos_metrics via LoggingDatabase"""
        if not self.db:
            return

        try:
            # Store multiple metrics as separate rows
            metrics_to_store = [
                ("latency_p95", metric.latency_p95),
                ("latency_p99", metric.latency_p99),
                ("error_rate", metric.error_rate),
                ("cpu_percent", metric.cpu_percent),
                ("memory_percent", metric.memory_percent),
            ]

            for metric_name, metric_value in metrics_to_store:
                await self.db.log_chaos_metric(
                    experiment_id=experiment_id,
                    metric_type="system",
                    metric_name=metric_name,
                    metric_value=metric_value,
                    metric_metadata=None,
                )
        except Exception as e:
            logger.error(f"Failed to persist chaos metric: {e}")

    def validate_hypothesis(
        self,
        hypothesis: Hypothesis,
        metrics: List[MetricsSnapshot]
    ) -> Tuple[bool, Dict[str, any]]:
        """
        Validate hypothesis against collected metrics.

        Args:
            hypothesis: Experiment hypothesis
            metrics: Collected metrics

        Returns:
            Tuple of (validated: bool, validation_details: Dict)
        """
        if not metrics:
            return False, {"reason": "No metrics collected"}

        # Extract expected behavior
        expected = hypothesis.expected_behavior

        # Calculate actual metrics
        actual_latency_p95 = statistics.mean(m.latency_p95 for m in metrics)
        actual_latency_p99 = statistics.mean(m.latency_p99 for m in metrics)
        actual_error_rate = statistics.mean(m.error_rate for m in metrics)

        max_latency_p95 = actual_latency_p95
        max_latency_p99 = actual_latency_p99
        max_error_rate = max(m.error_rate for m in metrics)

        # Check against expected thresholds
        expected_latency_p95 = expected.get("max_latency_p95_ms", float('inf'))
        expected_latency_p99 = expected.get("max_latency_p99_ms", float('inf'))
        expected_error_rate = expected.get("max_error_rate", 1.0)

        latency_p95_ok = actual_latency_p95 <= expected_latency_p95
        latency_p99_ok = actual_latency_p99 <= expected_latency_p99
        error_rate_ok = max_error_rate <= expected_error_rate

        validated = latency_p95_ok and latency_p99_ok and error_rate_ok

        validation_details = {
            "validated": validated,
            "checks": {
                "latency_p95": {
                    "passed": latency_p95_ok,
                    "expected": expected_latency_p95,
                    "actual": round(actual_latency_p95, 2),
                    "max": round(max_latency_p95, 2)
                },
                "latency_p99": {
                    "passed": latency_p99_ok,
                    "expected": expected_latency_p99,
                    "actual": round(actual_latency_p99, 2),
                    "max": round(max_latency_p99, 2)
                },
                "error_rate": {
                    "passed": error_rate_ok,
                    "expected": expected_error_rate,
                    "actual": round(actual_error_rate, 4),
                    "max": round(max_error_rate, 4)
                }
            },
            "hypothesis_statement": hypothesis.hypothesis_statement
        }

        logger.info(
            f"Hypothesis validation: {validated} - "
            f"Latency P95: {actual_latency_p95:.1f}ms (expected ≤{expected_latency_p95}ms), "
            f"Error rate: {max_error_rate*100:.2f}% (expected ≤{expected_error_rate*100}%)"
        )

        return validated, validation_details

    def generate_insights(
        self,
        experiment: ChaosExperiment,
        metrics: List[MetricsSnapshot],
        slo_thresholds: Optional[SLOThresholds] = None
    ) -> List[str]:
        """
        Generate insights from experiment metrics.

        Args:
            experiment: Experiment details
            metrics: Collected metrics
            slo_thresholds: Optional SLO thresholds

        Returns:
            List of insight strings
        """
        insights = []

        if not metrics:
            insights.append("No metrics collected - unable to generate insights")
            return insights

        # Calculate statistics
        latency_p95_values = [m.latency_p95 for m in metrics]
        latency_p99_values = [m.latency_p99 for m in metrics]
        error_rate_values = [m.error_rate for m in metrics]

        avg_latency_p95 = statistics.mean(latency_p95_values)
        max_latency_p95 = max(latency_p95_values)
        min_latency_p95 = min(latency_p95_values)
        std_latency_p95 = statistics.stdev(latency_p95_values) if len(latency_p95_values) > 1 else 0

        avg_latency_p99 = statistics.mean(latency_p99_values)
        max_latency_p99 = max(latency_p99_values)

        avg_error_rate = statistics.mean(error_rate_values)
        max_error_rate = max(error_rate_values)

        # Latency insights
        insights.append(
            f"Latency P95: avg={avg_latency_p95:.1f}ms, "
            f"max={max_latency_p95:.1f}ms, min={min_latency_p95:.1f}ms, "
            f"std={std_latency_p95:.1f}ms"
        )

        insights.append(
            f"Latency P99: avg={avg_latency_p99:.1f}ms, max={max_latency_p99:.1f}ms"
        )

        # Error rate insights
        insights.append(
            f"Error rate: avg={avg_error_rate*100:.2f}%, max={max_error_rate*100:.2f}%"
        )

        # SLO compliance check
        if slo_thresholds:
            slo_violations = []

            if avg_latency_p95 > slo_thresholds.latency_p95_ms:
                slo_violations.append(
                    f"Latency P95 exceeded SLO ({avg_latency_p95:.1f}ms > {slo_thresholds.latency_p95_ms}ms)"
                )

            if avg_latency_p99 > slo_thresholds.latency_p99_ms:
                slo_violations.append(
                    f"Latency P99 exceeded SLO ({avg_latency_p99:.1f}ms > {slo_thresholds.latency_p99_ms}ms)"
                )

            if max_error_rate > slo_thresholds.error_rate:
                slo_violations.append(
                    f"Error rate exceeded SLO ({max_error_rate*100:.2f}% > {slo_thresholds.error_rate*100}%)"
                )

            if slo_violations:
                insights.append(f"SLO violations detected: {', '.join(slo_violations)}")
            else:
                insights.append("All SLOs maintained throughout experiment")

        # Variance insights
        if std_latency_p95 > avg_latency_p95 * 0.5:
            insights.append(
                f"High latency variance detected (std={std_latency_p95:.1f}ms) - "
                "system may be unstable or experiencing intermittent issues"
            )

        # Blast radius impact
        insights.append(
            f"Experiment impact: {experiment.blast_radius}% of traffic affected "
            f"on {experiment.target_system}"
        )

        return insights

    def generate_report(
        self,
        experiment: ChaosExperiment,
        result: ExperimentResult,
        slo_thresholds: Optional[SLOThresholds] = None
    ) -> Dict:
        """
        Generate comprehensive experiment report.

        Args:
            experiment: Experiment details
            result: Experiment result
            slo_thresholds: Optional SLO thresholds

        Returns:
            Report dict
        """
        report = {
            "experiment_id": experiment.experiment_id,
            "experiment_name": experiment.name,
            "description": experiment.description,
            "target_system": experiment.target_system,
            "chaos_type": experiment.chaos_type.value,
            "environment": experiment.environment,
            "blast_radius": experiment.blast_radius,
            "status": experiment.status.value,
            "started_at": experiment.started_at.isoformat() if experiment.started_at else None,
            "completed_at": experiment.completed_at.isoformat() if experiment.completed_at else None,
            "duration_seconds": None,
            "success": result.success,
            "rollback_triggered": result.rollback_triggered,
            "metrics_summary": self._generate_metrics_summary(result.metrics_collected),
            "hypothesis_validation": {
                "validated": result.hypothesis_validated,
                "hypothesis": experiment.hypothesis
            } if experiment.hypothesis else None,
            "insights": result.insights,
            "governance": {
                "tier": experiment.governance_tier,
                "decision_id": experiment.governance_decision_id
            } if experiment.governance_tier else None
        }

        # Calculate duration
        if experiment.started_at and experiment.completed_at:
            duration = experiment.completed_at - experiment.started_at
            report["duration_seconds"] = duration.total_seconds()

        # Add SLO compliance
        if slo_thresholds and result.metrics_collected:
            report["slo_compliance"] = self._check_slo_compliance(
                result.metrics_collected,
                slo_thresholds
            )

        logger.info(f"Generated experiment report for {experiment.experiment_id}")

        return report

    def _generate_metrics_summary(self, metrics: List[MetricsSnapshot]) -> Dict:
        """Generate summary statistics from metrics"""
        if not metrics:
            return {
                "metrics_count": 0,
                "collection_period_seconds": 0
            }

        latency_p95_values = [m.latency_p95 for m in metrics]
        latency_p99_values = [m.latency_p99 for m in metrics]
        error_rate_values = [m.error_rate for m in metrics]

        # Calculate time range
        timestamps = [m.timestamp for m in metrics]
        collection_period = (max(timestamps) - min(timestamps)).total_seconds()

        return {
            "metrics_count": len(metrics),
            "collection_period_seconds": collection_period,
            "latency_p95": {
                "avg": round(statistics.mean(latency_p95_values), 2),
                "min": round(min(latency_p95_values), 2),
                "max": round(max(latency_p95_values), 2),
                "std": round(statistics.stdev(latency_p95_values), 2) if len(latency_p95_values) > 1 else 0
            },
            "latency_p99": {
                "avg": round(statistics.mean(latency_p99_values), 2),
                "min": round(min(latency_p99_values), 2),
                "max": round(max(latency_p99_values), 2),
                "std": round(statistics.stdev(latency_p99_values), 2) if len(latency_p99_values) > 1 else 0
            },
            "error_rate": {
                "avg": round(statistics.mean(error_rate_values), 4),
                "min": round(min(error_rate_values), 4),
                "max": round(max(error_rate_values), 4),
                "std": round(statistics.stdev(error_rate_values), 4) if len(error_rate_values) > 1 else 0
            }
        }

    def _check_slo_compliance(
        self,
        metrics: List[MetricsSnapshot],
        slo_thresholds: SLOThresholds
    ) -> Dict:
        """Check SLO compliance across all metrics"""
        if not metrics:
            return {"compliant": False, "reason": "No metrics"}

        latency_p95_values = [m.latency_p95 for m in metrics]
        latency_p99_values = [m.latency_p99 for m in metrics]
        error_rate_values = [m.error_rate for m in metrics]

        avg_latency_p95 = statistics.mean(latency_p95_values)
        avg_latency_p99 = statistics.mean(latency_p99_values)
        max_error_rate = max(error_rate_values)

        latency_p95_ok = avg_latency_p95 <= slo_thresholds.latency_p95_ms
        latency_p99_ok = avg_latency_p99 <= slo_thresholds.latency_p99_ms
        error_rate_ok = max_error_rate <= slo_thresholds.error_rate

        compliant = latency_p95_ok and latency_p99_ok and error_rate_ok

        return {
            "compliant": compliant,
            "checks": {
                "latency_p95": {
                    "passed": latency_p95_ok,
                    "threshold": slo_thresholds.latency_p95_ms,
                    "actual": round(avg_latency_p95, 2)
                },
                "latency_p99": {
                    "passed": latency_p99_ok,
                    "threshold": slo_thresholds.latency_p99_ms,
                    "actual": round(avg_latency_p99, 2)
                },
                "error_rate": {
                    "passed": error_rate_ok,
                    "threshold": slo_thresholds.error_rate,
                    "actual": round(max_error_rate, 4)
                }
            }
        }

    async def cleanup_old_metrics(self, retention_days: Optional[int] = None):
        """
        Clean up old metrics from MySQL.

        Args:
            retention_days: Retention period (defaults to config value)
        """
        if not self.db:
            return

        retention = retention_days or self.retention_days
        cutoff_date = datetime.now() - timedelta(days=retention)

        try:
            result = await self.db.execute_query(
                "DELETE FROM chaos_metrics WHERE timestamp < $1",
                (cutoff_date,)
            )
            logger.info(
                f"Cleaned up metrics older than {retention} days (cutoff: {cutoff_date})"
            )
        except Exception as e:
            logger.error(f"Failed to cleanup old metrics: {e}")

    async def get_experiment_metrics(
        self,
        experiment_id: str
    ) -> List[MetricsSnapshot]:
        """
        Retrieve all metrics for an experiment from PostgreSQL.

        Args:
            experiment_id: Experiment ID

        Returns:
            List of MetricsSnapshot
        """
        if not self.db:
            return []

        try:
            # Get all metrics for this experiment
            rows = await self.db.execute_query(
                """
                SELECT timestamp, metric_type, metric_value
                FROM chaos_metrics
                WHERE experiment_id = $1
                ORDER BY timestamp
                """,
                (experiment_id,),
                fetch_all=True
            )

            # Group by timestamp
            metrics_by_timestamp: Dict[datetime, Dict] = {}

            for row in rows:
                timestamp = row["timestamp"]
                metric_type = row["metric_type"]
                metric_value = row["metric_value"]

                if timestamp not in metrics_by_timestamp:
                    metrics_by_timestamp[timestamp] = {
                        "timestamp": timestamp,
                        "latency_p95": 0,
                        "latency_p99": 0,
                        "error_rate": 0,
                        "cpu_percent": 0,
                        "memory_percent": 0
                    }

                metrics_by_timestamp[timestamp][metric_type] = metric_value

            # Convert to MetricsSnapshot list
            snapshots = [
                MetricsSnapshot(**metrics)
                for metrics in metrics_by_timestamp.values()
            ]

            return sorted(snapshots, key=lambda m: m.timestamp)

        except Exception as e:
            logger.error(f"Failed to retrieve experiment metrics: {e}")
            return []


# Singleton instance
_observability = None


def get_observability(config: Optional[Dict] = None) -> ChaosObservability:
    """Get global observability instance"""
    global _observability
    if _observability is None:
        _observability = ChaosObservability(config)
    return _observability
