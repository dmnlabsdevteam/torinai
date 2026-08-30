#!/usr/bin/env python3
"""
Improvement Monitor
Tracks system improvements, performance metrics, and learning progress over time

This module:
- Monitors component health and performance
- Tracks improvement metrics and trends
- Detects performance degradation
- Generates improvement reports
- Provides statistical analysis of learning progress
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Tuple
from enum import Enum
import statistics
import json
import os
from pathlib import Path
from dotenv import load_dotenv

from core.database import TorinUnifiedDatabase, get_unified_db
from core.capability import raise_if_structural

# Load environment variables (non-database settings)
env_file = Path(__file__).parent.parent.parent / ".env.production"
if env_file.exists():
    load_dotenv(env_file)

logger = logging.getLogger(__name__)


#: Percentage change beyond which a metric is called improving or degrading
#: rather than stable. Stated once; it was two bare 5s in two methods.
IMPROVEMENT_TREND_PCT = 5.0


class MetricType(Enum):
    """Types of metrics to track"""
    ACCURACY = "accuracy"
    LATENCY = "latency"
    THROUGHPUT = "throughput"
    ERROR_RATE = "error_rate"
    MEMORY_USAGE = "memory_usage"
    CPU_USAGE = "cpu_usage"
    SUCCESS_RATE = "success_rate"
    QUALITY_SCORE = "quality_score"


class HealthStatus(Enum):
    """Component health status"""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    CRITICAL = "critical"
    UNKNOWN = "unknown"


@dataclass
class ImprovementMetric:
    """Represents a single improvement metric"""
    metric_id: str
    component_name: str
    metric_type: MetricType
    metric_name: str  # e.g., "response_time", "accuracy", "error_rate"

    # Values
    baseline_value: float  # Initial/baseline value
    current_value: float  # Current value
    target_value: Optional[float] = None  # Target goal

    # Metadata
    improvement_percentage: float = 0.0  # % improvement from baseline
    measurements: List[Tuple[datetime, float]] = field(default_factory=list)

    timestamp: datetime = field(default_factory=datetime.now)
    trend: str = ""  # "improving", "degrading", "stable"


@dataclass
class ComponentHealth:
    """Health status of a system component"""
    component_name: str
    status: HealthStatus

    # Metrics
    error_count: int = 0
    success_count: int = 0
    avg_latency_ms: float = 0.0

    # Health indicators
    health_score: float = 100.0  # 0-100
    last_error: Optional[str] = None
    last_success: Optional[datetime] = None

    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class SystemImprovementState:
    """Overall system improvement state"""
    total_components: int
    healthy_components: int
    degraded_components: int
    critical_components: int

    @property
    def impaired_components(self) -> int:
        """Components that are not healthy, however they are impaired.

        The one number a gate should ask for. `critical_components` answers a
        narrower question -- is anything DOWN -- and using it to mean "is
        anything wrong" is what made a refusal message name a state no
        component was in.
        """
        return self.degraded_components + self.critical_components

    # Aggregate metrics
    overall_health_score: Optional[float]   # None when nothing has been measured
    total_improvements_tracked: int
    active_degradations: int

    improvements_by_component: Dict[str, List[ImprovementMetric]] = field(default_factory=dict)
    component_health: Dict[str, ComponentHealth] = field(default_factory=dict)

    last_updated: datetime = field(default_factory=datetime.now)


class ImprovementMonitor:
    """
    Monitor and track system improvements over time

    Responsibilities:
    - Track performance metrics across components
    - Detect improvements and degradations
    - Generate improvement reports
    - Maintain historical performance data
    - Alert on performance regressions
    """

    #: A HEALTH READING EXPIRES. Most of these metrics are in-process singleton
    #: state, so a row is only true of the process that wrote it -- and this
    #: table outlives every process. The gate on self-improvement was blocking
    #: on rows left behind by a run that had already exited, then reporting
    #: "3 components in CRITICAL state" about a system nobody had measured
    #: recently. Stale is not unhealthy, and saying so is the difference
    #: between a safety gate and a superstition.
    #:
    #: Generous relative to the monitor's own check interval, so an ordinary
    #: scheduling delay does not expire a component that is being watched.
    HEALTH_FRESHNESS_SEC = 900

    def __init__(self, db_config: Dict[str, Any] = None):
        # db_config is kept for backward API compatibility but ignored;
        # ImprovementMonitor now uses the unified PostgreSQL database manager.
        _ = db_config

        # Unified PostgreSQL database (singleton manager)
        from core.database import get_database_manager
        self.db: TorinUnifiedDatabase = get_database_manager()

        # In-memory state
        self.metrics: Dict[str, ImprovementMetric] = {}

        # Component tracking: component_name -> {metric_type: [values]}
        self.component_metrics: Dict[str, Dict[str, List[float]]] = {}
        # Load recent metrics (fire-and-forget on running event loop)
        try:
            asyncio.create_task(self._load_recent_metrics())
        except RuntimeError:
            # No running loop (e.g., synchronous context); caller can invoke
            # _load_recent_metrics() manually if needed.
            logger.debug("Event loop not running; skipping automatic metric preload")

    async def _load_recent_metrics(self):
        """Load recent metrics from database"""
        try:
            rows = await self.db.execute_query(
                """
                SELECT metric_id, component_name, metric_type, metric_name,
                       baseline_value, current_value, target_value,
                       improvement_percentage, trend, metadata
                FROM improvement_metrics
                WHERE updated_at >= NOW() - INTERVAL '30 days'
                """,
                fetch_all=True,
            )

            for row in rows or []:
                metric = ImprovementMetric(
                    metric_id=str(row["metric_id"]),
                    component_name=row["component_name"],
                    metric_type=MetricType(row["metric_type"]),
                    metric_name=row["metric_name"],
                    baseline_value=row["baseline_value"],
                    current_value=row["current_value"],
                    target_value=row["target_value"],
                    improvement_percentage=row["improvement_percentage"],
                    trend=row["trend"] or ""
                )
                self.metrics[metric.metric_id] = metric

            logger.info(f"Loaded {len(rows or [])} recent improvement metrics from PostgreSQL")

        except Exception as e:
            logger.error(f"Error loading metrics: {e}")

    async def track_improvement(
        self,
        component_name: str,
        metric_type: MetricType,
        metric_name: str,
        baseline_value: float,
        current_value: float,
        target_value: Optional[float] = None,
        metadata: Dict[str, Any] = None
    ) -> Tuple[bool, ImprovementMetric]:
        """
        Track an improvement metric

        Args:
            component_name: Component being tracked
            metric_type: Type of metric (accuracy, latency, etc.)
            metric_name: Specific metric name
            baseline_value: Initial/baseline value
            current_value: Current measured value
            target_value: Optional target value
            metadata: Additional metadata

        Returns:
            Tuple of (success, metric)
        """
        try:
            # Percentage change against the baseline. UNDEFINED, not zero,
            # when the baseline is zero: a percentage of zero has no value, and
            # returning 0.0 made "cannot be expressed as a percentage" identical
            # to "did not change" -- which then resolved to trend="stable" and
            # reported a component as steady on a measurement that never
            # happened.
            improvement_pct = None
            if baseline_value != 0:
                improvement_pct = ((current_value - baseline_value)
                                   / abs(baseline_value)) * 100

            if improvement_pct is None:
                # The direction is still knowable from the raw values even when
                # the ratio is not, so it is read from those rather than left
                # unstated. Only an exactly-equal pair is genuinely stable.
                if current_value > baseline_value:
                    trend = "improving"
                elif current_value < baseline_value:
                    trend = "degrading"
                else:
                    trend = "stable"
            elif improvement_pct > IMPROVEMENT_TREND_PCT:
                trend = "improving"
            elif improvement_pct < -IMPROVEMENT_TREND_PCT:
                trend = "degrading"
            else:
                trend = "stable"

            # Upsert into unified.improvement_metrics (PostgreSQL)
            row = await self.db.execute_query(
                """
                INSERT INTO improvement_metrics
                    (component_name, metric_type, metric_name,
                     baseline_value, current_value, target_value,
                     improvement_percentage, trend, metadata)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                ON CONFLICT (component_name, metric_name) DO UPDATE SET
                    baseline_value = EXCLUDED.baseline_value,
                    current_value = EXCLUDED.current_value,
                    target_value = EXCLUDED.target_value,
                    improvement_percentage = EXCLUDED.improvement_percentage,
                    trend = EXCLUDED.trend,
                    metadata = EXCLUDED.metadata,
                    updated_at = NOW()
                RETURNING metric_id, baseline_value, current_value,
                          target_value, improvement_percentage, trend
                """,
                params=(
                    component_name,
                    metric_type.value,
                    metric_name,
                    baseline_value,
                    current_value,
                    target_value,
                    improvement_pct,
                    trend,
                    # asyncpg registers no dict->jsonb codec on this pool, so a
                    # raw dict raises "invalid input for query argument". Both
                    # writers here had that defect and neither had a caller, so
                    # nothing ever hit it -- the first real publisher did.
                    json.dumps(metadata or {}, default=str),
                ),
                fetch_one=True,
            )

            metric = ImprovementMetric(
                metric_id=str(row["metric_id"]),
                component_name=component_name,
                metric_type=metric_type,
                metric_name=metric_name,
                baseline_value=float(row["baseline_value"]) if row["baseline_value"] is not None else baseline_value,
                current_value=float(row["current_value"]),
                target_value=float(row["target_value"]) if row["target_value"] is not None else target_value,
                improvement_percentage=float(row["improvement_percentage"]) if row["improvement_percentage"] is not None else improvement_pct,
                trend=row["trend"] or trend,
            )

            # Update in-memory cache
            self.metrics[metric.metric_id] = metric

            # Update component metrics tracking
            if component_name not in self.component_metrics:
                self.component_metrics[component_name] = {}
            if metric_name not in self.component_metrics[component_name]:
                self.component_metrics[component_name][metric_name] = []
            self.component_metrics[component_name][metric_name].append(current_value)

            logger.info(
                f"Tracked improvement for '{component_name}.{metric_name}': "
                f"baseline={baseline_value}, current={current_value}, "
                f"improvement="
                f"{'undefined (zero baseline)' if improvement_pct is None else f'{improvement_pct:.1f}%'}"
                f", trend={trend}"
            )

            return True, metric

        except Exception as e:
            logger.error(f"Error tracking improvement: {e}")
            return False, None

    async def record_measurement(
        self,
        metric_id: str,
        value: float,
        metadata: Dict[str, Any] = None
    ) -> bool:
        """
        Record a new measurement for an existing metric

        This allows tracking metrics over time without creating new metric entries
        """
        try:
            # Check if metric exists
            if metric_id not in self.metrics:
                logger.warning(f"Metric not found: {metric_id}")
                return False

            # Get existing metric
            metric = self.metrics[metric_id]

            # Update current value and recalculate improvement
            old_current = metric.current_value
            metric.current_value = value

            # Same rule as track_improvement: undefined against a zero
            # baseline. This branch previously left the PREVIOUS metric's
            # percentage in place when it could not recompute, so a new
            # measurement silently inherited the old one's improvement figure.
            if metric.baseline_value != 0:
                metric.improvement_percentage = (
                    (value - metric.baseline_value) / abs(metric.baseline_value)
                ) * 100
            else:
                metric.improvement_percentage = None

            # Determine new trend based on direction of change
            if value > old_current:
                direction = "up"
                change_pct = ((value - old_current) / abs(old_current)) * 100 if old_current != 0 else 0
            else:
                direction = "down"
                change_pct = ((old_current - value) / abs(old_current)) * 100 if old_current != 0 else 0

            # Update trend
            if metric.improvement_percentage is None:
                metric.trend = ("improving" if value > metric.baseline_value
                                else "degrading" if value < metric.baseline_value
                                else "stable")
            elif metric.improvement_percentage > IMPROVEMENT_TREND_PCT:
                metric.trend = "improving"
            elif metric.improvement_percentage < -IMPROVEMENT_TREND_PCT:
                metric.trend = "degrading"
            else:
                metric.trend = "stable"

            # Store measurement in unified.metric_measurements
            await self.db.execute_query(
                """
                INSERT INTO metric_measurements
                    (metric_id, value, metadata)
                VALUES ($1, $2, $3)
                """,
                params=(
                    int(metric_id),
                    value,
                    # asyncpg registers no dict->jsonb codec on this pool, so a
                    # raw dict raises "invalid input for query argument". Both
                    # writers here had that defect and neither had a caller, so
                    # nothing ever hit it -- the first real publisher did.
                    json.dumps(metadata or {}, default=str),
                ),
            )

            # Update metric in main table
            await self.db.execute_query(
                """
                UPDATE improvement_metrics
                SET current_value = $1,
                    improvement_percentage = $2,
                    trend = $3,
                    updated_at = NOW()
                WHERE metric_id = $4
                """,
                params=(
                    value,
                    metric.improvement_percentage,
                    metric.trend,
                    int(metric_id),
                ),
            )

            logger.debug(f"Recorded measurement for '{metric_id}': {value}")

            return True

        except Exception as e:
            logger.error(f"Error recording measurement: {e}")
            return False

    async def update_component_health(
        self,
        component_name: str,
        success: bool = True,
        latency_ms: Optional[float] = None,
        error_message: Optional[str] = None
    ) -> ComponentHealth:
        """
        Update health status for a component

        Args:
            component_name: Name of component
            success: Whether operation was successful
            latency_ms: Operation latency in milliseconds
            error_message: Error message if failed

        Returns:
            Updated ComponentHealth object
        """
        try:
            # Get or create health record
            row = await self.db.execute_query(
                """
                SELECT component_name, status, error_count, success_count,
                       avg_latency_ms, health_score, last_error
                FROM component_health
                WHERE component_name = $1
                """,
                params=(component_name,),
                fetch_one=True,
            )

            if row:
                # Update existing
                error_count = row["error_count"]
                success_count = row["success_count"]
                avg_latency = row["avg_latency_ms"]
                health_score = row["health_score"]
            else:
                # Create new
                error_count = 0
                success_count = 0
                avg_latency = 0.0
                health_score = 100.0

            # Update counts
            if success:
                success_count += 1
            else:
                error_count += 1

            # Update average latency
            if latency_ms is not None:
                total_operations = error_count + success_count
                avg_latency = ((avg_latency * (total_operations - 1)) + latency_ms) / total_operations

            # Calculate health score
            total_ops = error_count + success_count
            if total_ops > 0:
                success_rate = (success_count / total_ops) * 100

                # Health score weighted: 70% success rate, 30% latency performance
                latency_score = max(0, 100 - (avg_latency / 10))  # Penalty for high latency
                health_score = (success_rate * 0.7) + (latency_score * 0.3)

            # Determine status
            if health_score >= 80:
                status = HealthStatus.HEALTHY
            elif health_score >= 50:
                status = HealthStatus.DEGRADED
            else:
                status = HealthStatus.CRITICAL

            # Prepare health object
            health = ComponentHealth(
                component_name=component_name,
                status=status,
                error_count=error_count,
                success_count=success_count,
                avg_latency_ms=avg_latency,
                health_score=health_score,
                last_error=error_message if not success else (row.get("last_error") if row else None)
            )

            # Store in database (PostgreSQL upsert)
            await self.db.execute_query(
                """
                INSERT INTO component_health
                    (component_name, status, error_count, success_count,
                     avg_latency_ms, health_score, last_error, last_success,
                     last_updated)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, NOW())
                ON CONFLICT (component_name) DO UPDATE SET
                    status = EXCLUDED.status,
                    error_count = EXCLUDED.error_count,
                    success_count = EXCLUDED.success_count,
                    avg_latency_ms = EXCLUDED.avg_latency_ms,
                    health_score = EXCLUDED.health_score,
                    last_error = EXCLUDED.last_error,
                    last_success = EXCLUDED.last_success,
                    last_updated = NOW()
                """,
                params=(
                    component_name,
                    status.value,
                    error_count,
                    success_count,
                    avg_latency,
                    health_score,
                    error_message,
                    datetime.now() if success else None,
                ),
            )

            logger.info(
                f"Updated health for '{component_name}': "
                f"status={status.value}, score={health_score:.1f}, "
                f"success_rate={success_count}/{total_ops}"
            )

            return health

        except Exception as e:
            logger.error(f"Error updating component health: {e}")
            return None

    async def get_component_metrics(
        self,
        component_name: str,
        days: int = 7
    ) -> List[ImprovementMetric]:
        """
        Get all metrics for a component

        Args:
            component_name: Component to retrieve metrics for
            days: Number of days of history to retrieve

        Returns:
            List of ImprovementMetric objects
        """
        try:
            rows = await self.db.execute_query(
                """
                SELECT metric_id, component_name, metric_type, metric_name,
                       baseline_value, current_value, target_value,
                       improvement_percentage, trend
                FROM improvement_metrics
                WHERE component_name = $1
                  AND updated_at >= NOW() - $2 * INTERVAL '1 day'
                ORDER BY updated_at DESC
                """,
                params=(component_name, days),
                fetch_all=True,
            )

            # Convert to ImprovementMetric objects
            metrics = []
            for row in rows or []:
                metric = ImprovementMetric(
                    metric_id=str(row["metric_id"]),
                    component_name=row["component_name"],
                    metric_type=MetricType(row["metric_type"]),
                    metric_name=row["metric_name"],
                    baseline_value=row["baseline_value"],
                    current_value=row["current_value"],
                    target_value=row["target_value"],
                    improvement_percentage=row["improvement_percentage"],
                    trend=row["trend"] or ""
                )
                metrics.append(metric)

            return metrics

        except Exception as e:
            # `except` must not turn a wiring defect into an empty result.
            raise_if_structural(e, 'improvement_monitor.get_component_metrics')
            logger.error(f"Error getting component metrics: {e}")
            return []

    async def detect_degradation(
        self,
        component_name: str,
        threshold_percentage: float = -10.0
    ) -> Tuple[bool, List[ImprovementMetric]]:
        """
        Detect performance degradation for a component

        Args:
            component_name: Component to check
            threshold_percentage: Degradation threshold (negative %)

        Returns:
            Tuple of (has_degradation, degraded_metrics)
        """
        try:
            metrics = await self.get_component_metrics(component_name, days=7)

            degraded_metrics = [
                m for m in metrics
                if m.improvement_percentage < threshold_percentage
            ]

            if degraded_metrics:
                logger.warning(
                    f"Degradation detected for '{component_name}': "
                    f"{len(degraded_metrics)} metrics below threshold "
                    f"({threshold_percentage}%)"
                )
                return True, degraded_metrics

            return False, []

        except Exception as e:
            logger.error(f"Error detecting degradation: {e}")
            return False, []

    async def generate_improvement_report(
        self,
        component_name: str = None,
        days: int = 30
    ) -> Dict[str, Any]:
        """
        Generate comprehensive improvement report

        Args:
            component_name: Specific component (None for all)
            days: Days of history to include

        Returns:
            Report dictionary with statistics and insights
        """
        try:
            if component_name:
                rows = await self.db.execute_query(
                    """
                    SELECT metric_id, component_name, metric_type, metric_name,
                           baseline_value, current_value, improvement_percentage, trend
                    FROM improvement_metrics
                    WHERE component_name = $1
                      AND updated_at >= NOW() - $2 * INTERVAL '1 day'
                    """,
                    params=(component_name, days),
                    fetch_all=True,
                )
            else:
                rows = await self.db.execute_query(
                    """
                    SELECT metric_id, component_name, metric_type, metric_name,
                           baseline_value, current_value, improvement_percentage, trend
                    FROM improvement_metrics
                    WHERE updated_at >= NOW() - $1 * INTERVAL '1 day'
                    """,
                    params=(days,),
                    fetch_all=True,
                )

            if not rows:
                return {
                    "component": component_name or "all",
                    "days": days,
                    "total_metrics": 0,
                    "message": "No metrics found"
                }

            # Aggregate statistics
            improvements = [r["improvement_percentage"] for r in rows if r["improvement_percentage"] > 0]
            degradations = [r["improvement_percentage"] for r in rows if r["improvement_percentage"] < 0]
            stable = [r["improvement_percentage"] for r in rows if -5 <= r["improvement_percentage"] <= 5]

            # Calculate stats
            avg_improvement = statistics.mean(improvements) if improvements else 0
            avg_degradation = statistics.mean(degradations) if degradations else 0

            report = {
                "component": component_name or "all_components",
                "period_days": days,
                "generated_at": datetime.now().isoformat(),
                "summary": {
                    "total_metrics": len(rows),
                    "improving": len(improvements),
                    "degrading": len(degradations),
                    "stable": len(stable),
                    "avg_improvement_pct": round(avg_improvement, 2),
                    "avg_degradation_pct": round(avg_degradation, 2)
                },
                "top_improvements": sorted(
                    [{"metric": r["metric_name"], "component": r["component_name"],
                      "improvement": r["improvement_percentage"]} for r in rows],
                    key=lambda x: x["improvement"],
                    reverse=True
                )[:10],
                "top_degradations": sorted(
                    [{"metric": r["metric_name"], "component": r["component_name"],
                      "degradation": r["improvement_percentage"]} for r in rows],
                    key=lambda x: x["degradation"]
                )[:10],
                "metrics_by_type": {}
            }

            # Group by metric type
            for row in rows:
                mtype = row["metric_type"]
                if mtype not in report["metrics_by_type"]:
                    report["metrics_by_type"][mtype] = []
                report["metrics_by_type"][mtype].append({
                    "component": row["component_name"],
                    "metric": row["metric_name"],
                    "baseline": row["baseline_value"],
                    "current": row["current_value"],
                    "improvement_pct": row["improvement_percentage"]
                })

            # Add frozen capability benchmark results (global capability anchoring)
            try:
                from core.learning.capability_benchmark_suite import get_capability_benchmark_suite

                benchmark_suite = get_capability_benchmark_suite()

                # Query latest capability report from unified.capability_reports
                latest_capability = await self.db.execute_query(
                    """
                    SELECT
                        overall_score,
                        reasoning_score,
                        coding_score,
                        analysis_score,
                        comprehension_score,
                        regression_detected,
                        regression_domains,
                        regression_severity,
                        tests_passed,
                        tests_failed,
                        baseline_delta,
                        timestamp
                    FROM capability_reports
                    ORDER BY timestamp DESC
                    LIMIT 1
                    """,
                    fetch_one=True,
                )

                # Get historical trend (last 10 reports)
                capability_history = await self.db.execute_query(
                    """
                    SELECT overall_score, timestamp
                    FROM capability_reports
                    ORDER BY timestamp DESC
                    LIMIT 10
                    """,
                    fetch_all=True,
                ) or []

                if latest_capability:
                    report["capability_benchmarks"] = {
                        "overall_score": latest_capability["overall_score"],
                        "domain_scores": {
                            "reasoning": latest_capability["reasoning_score"],
                            "coding": latest_capability["coding_score"],
                            "analysis": latest_capability["analysis_score"],
                            "comprehension": latest_capability["comprehension_score"]
                        },
                        "regression_status": {
                            "detected": bool(latest_capability["regression_detected"]),
                            "domains": latest_capability["regression_domains"].split(',') if latest_capability["regression_domains"] else [],
                            "severity": latest_capability["regression_severity"]
                        },
                        "test_results": {
                            "passed": latest_capability["tests_passed"],
                            "failed": latest_capability["tests_failed"],
                            "total": latest_capability["tests_passed"] + latest_capability["tests_failed"]
                        },
                        "baseline_delta": latest_capability["baseline_delta"],
                        "last_updated": latest_capability["timestamp"].isoformat() if latest_capability["timestamp"] else None,
                        "trend": (
                            "improving"
                            if len(capability_history) >= 2 and
                            capability_history[0]["overall_score"] > capability_history[-1]["overall_score"]
                            else "stable"
                        )
                    }

                    logger.info(
                        f"Capability benchmarks included: Overall={latest_capability['overall_score']:.2%}, "
                        f"Regression={'YES' if latest_capability['regression_detected'] else 'NO'}"
                    )
                else:
                    report["capability_benchmarks"] = {
                        "status": "no_data",
                        "message": "No capability benchmark data available yet"
                    }

            except Exception as cap_error:
                logger.warning(f"Could not include capability benchmarks in report: {cap_error}")
                report["capability_benchmarks"] = {
                    "status": "error",
                    "error": str(cap_error)
                }

            logger.info(
                f"Generated improvement report: {len(rows)} metrics, "
                f"{len(improvements)} improving, {len(degradations)} degrading"
            )

            return report

        except Exception as e:
            logger.error(f"Error generating report: {e}")
            return {"error": str(e)}

    async def get_system_state(self) -> SystemImprovementState:
        """
        Get overall system improvement state

        Returns comprehensive view of all component health and metrics
        """
        try:
            # Get component health summary
            # EVERY AGGREGATE BELOW IS OVER DECLARED COMPONENTS.
            #
            # These three queries read component_health bare, so a component was
            # "anything that ever wrote a row here". That is not the authority:
            # unified.components is, and _get_all_components already joins to it
            # for exactly this reason. Applying the authority at target
            # selection but not at the aggregate left the two readers of one
            # table disagreeing about what a component is.
            #
            # What that cost: the table still holds six rows whose names are
            # metric keys (`overall_status`, `active_alerts`, `critical_issues`,
            # `healthy_components`, `total_components`, `unknown`), written
            # before intrinsic_motivation was corrected to the 0-100 scale, so
            # they carry 0.8-1.0 in a column every consumer reads as 0-100.
            # Nothing rewrites them -- the upsert is keyed on component_name and
            # no writer emits those names any more -- so they are permanent.
            # Averaged in, they dragged 29 real measurements from 91.5 to 76.0
            # and held it under the deployment gate's threshold of 80. Three
            # further rows (`production`, `staging`, `prod-server-42`) are
            # environment strings a validation tool passed to
            # check_component_health, which recorded them as components.
            #
            # A component is something DECLARED, not anything that once appeared
            # in a measurement.
            health_rows = await self.db.execute_query(
                """
                SELECT h.status, COUNT(*) as count
                FROM component_health h
                JOIN unified.components c ON c.component_id = h.component_name
                WHERE c.monitoring_enabled IS TRUE
                  AND h.last_updated > NOW() - make_interval(secs => $1)
                GROUP BY h.status
                """,
                (float(self.HEALTH_FRESHNESS_SEC),),
                fetch_all=True,
            ) or []

            health_counts = {row["status"]: row["count"] for row in health_rows}

            # Get improvement counts
            metrics_summary = await self.db.execute_query(
                """
                -- COALESCE: SUM() over ZERO ROWS RETURNS NULL, NOT 0.
                --
                -- With no metrics in the window this returned
                -- degradations=NULL, so SystemImprovementState carried
                -- active_degradations=None. The ASI deployment gate requires
                -- that field and correctly refuses when it is absent -- so an
                -- empty metrics table, which means "no degradations recorded",
                -- read as "system health cannot be confirmed" and blocked every
                -- deployment. COUNT returns 0 over an empty set; SUM does not.
                SELECT COUNT(DISTINCT metric_id) as total_metrics,
                       COALESCE(
                           SUM(CASE WHEN trend = 'degrading' THEN 1 ELSE 0 END),
                           0
                       ) as degradations
                FROM improvement_metrics
                WHERE updated_at >= NOW() - INTERVAL '7 days'
                """,
                fetch_one=True,
            )

            # Calculate overall health
            avg_health_row = await self.db.execute_query(
                """
                SELECT AVG(h.health_score) as avg_health
                FROM component_health h
                JOIN unified.components c ON c.component_id = h.component_name
                WHERE c.monitoring_enabled IS TRUE
                  AND h.last_updated > NOW() - make_interval(secs => $1)
                """,
                (float(self.HEALTH_FRESHNESS_SEC),),
                fetch_one=True,
            )
            # A FALSY CHECK MADE TWO OPPOSITE STATES READ AS PERFECT HEALTH.
            # `... if avg_health_row["avg_health"] else 100.0` substituted 100.0
            # both when AVG returned NULL (no component has a measured score)
            # and when it returned exactly 0.0 (every component critical). The
            # deployment gate blocks below 80, so that default failed OPEN on
            # precisely the two states it exists to catch.
            #
            # AVG already ignores NULL rows, so this is an average over measured
            # components. None means nothing was measured, which _required() in
            # the deployment gate turns into a refusal to deploy.
            raw_avg = avg_health_row["avg_health"] if avg_health_row else None
            avg_health = None if raw_avg is None else float(raw_avg)

            # POPULATE component_health. The field existed and was left empty on
            # every call, so the only per-component consumer
            # (EnhancedASISelfImprovement._get_component_health) found nothing
            # for every component and fell through to a fabricated score. The
            # counts above summarise these same rows; returning the summary
            # without the rows meant no caller could ever ask about one
            # component.
            detail_rows = await self.db.execute_query(
                """
                SELECT h.component_name, h.status, h.health_score, h.error_count,
                       h.success_count, h.avg_latency_ms, h.last_updated, h.metadata
                FROM component_health h
                JOIN unified.components c ON c.component_id = h.component_name
                WHERE c.monitoring_enabled IS TRUE
                  AND h.last_updated > NOW() - make_interval(secs => $1)
                """,
                (float(self.HEALTH_FRESHNESS_SEC),),
                fetch_all=True,
            ) or []
            def _meta(row):
                raw = row["metadata"]
                return (json.loads(raw) if isinstance(raw, str) else (raw or {}))

            component_health = {
                row["component_name"]: {
                    "component_name": row["component_name"],
                    "status": row["status"],
                    # NULL means the component was checked and could not be
                    # measured -- a state the health monitor now records rather
                    # than leaving a stale row behind. float(None) raised here
                    # and the structural-defect guard re-raised it, so a single
                    # unmeasurable component aborted the whole assessment and
                    # the cycle selected zero targets.
                    "health_score": (None if row["health_score"] is None
                                     else float(row["health_score"])),
                    "error_count": row["error_count"],
                    "success_count": row["success_count"],
                    "avg_latency_ms": row["avg_latency_ms"],
                    "last_updated": row["last_updated"],
                    # The CAUSE, not just the score. HealthMonitor records why a
                    # component is degraded; without carrying it here every
                    # consumer sees a number and has to guess the remedy.
                    "issues": _meta(row).get("issues", []),
                    # PROVENANCE. Most of these metrics are in-process singleton
                    # state, so a reading is only true of the process that took
                    # it. Passing it through lets a consumer tell a current
                    # measurement from one written by a process that has exited.
                    "measured_by": _meta(row).get("measured_by"),
                }
                for row in detail_rows
            }

            # COUNT THE VOCABULARY THE WRITER EMITS.
            #
            # health_monitor.HealthStatus -- the enum behind every row in this
            # table -- spells its worst states `unhealthy` and `offline`. This
            # module's own HealthStatus spells it `critical`, and the count
            # asked for that string alone, so three components sitting in the
            # worst state the writer can express were reported as zero critical
            # and counted toward nothing. Five separate HealthStatus enums
            # define this vocabulary across the codebase; until they are one,
            # the reader has to accept what the writer says rather than what
            # its own enum happens to name.
            # CRITICAL AND UNHEALTHY ARE NOT THE SAME CLAIM, and this state
            # feeds a GATE. `critical`/`offline` mean a component is down;
            # `unhealthy` means it is running impaired. Counting the second as
            # the first let one degraded subsystem block self-improvement
            # entirely while the message said "components in CRITICAL state" --
            # a gate firing on a condition it was not describing.
            #
            # Both are still counted, just under the name that is true of them,
            # so a caller that wants "anything not healthy" can add them.
            _CRITICAL_STATES = ("critical", "offline")
            _DEGRADED_STATES = ("degraded", "unhealthy")
            state = SystemImprovementState(
                total_components=sum(health_counts.values()),
                healthy_components=health_counts.get("healthy", 0),
                degraded_components=sum(health_counts.get(s, 0) for s in _DEGRADED_STATES),
                critical_components=sum(health_counts.get(s, 0) for s in _CRITICAL_STATES),
                overall_health_score=avg_health,
                total_improvements_tracked=metrics_summary["total_metrics"] if metrics_summary else 0,
                active_degradations=metrics_summary["degradations"] if metrics_summary else 0,
                component_health=component_health,
            )

            return state

        except Exception as e:
            # A monitor that cannot read its own store must SAY SO. Returning
            # None made "the query failed" and "the system has no state" the
            # same answer, and every consumer read the second.
            raise_if_structural(e, "ImprovementMonitor.get_system_state")
            logger.error(f"Error getting system state: {e}")
            raise

    async def detect_statistical_degradation(
        self,
        component_name: str,
        metric_name: str,
        days: int = 60,
        significance_level: float = 0.05
    ) -> Tuple[bool, Dict[str, Any]]:
        """
        Detect performance degradation using Mann-Kendall statistical trend test

        This replaces threshold-based detection with statistical significance testing,
        providing confidence in trend direction over 30-60 cycle horizons.

        Args:
            component_name: Component to analyze
            metric_name: Specific metric to analyze
            days: Number of days of history (maps to ~days/2 cycles if cycles run daily)
            significance_level: P-value threshold for significance (default 0.05)

        Returns:
            Tuple of (has_degradation, analysis_dict)
            analysis_dict contains: p_value, trend_direction, confidence, magnitude
        """
        try:
            # Get time series data
            rows = await self.db.execute_query(
                """
                SELECT value, measured_at
                FROM metric_measurements mm
                JOIN improvement_metrics im ON mm.metric_id = im.metric_id
                WHERE im.component_name = $1
                  AND im.metric_name = $2
                  AND mm.measured_at >= NOW() - $3 * INTERVAL '1 day'
                ORDER BY mm.measured_at ASC
                """,
                params=(component_name, metric_name, days),
                fetch_all=True,
            ) or []

            if len(rows) < 10:
                return False, {
                    "error": "Insufficient data",
                    "sample_size": len(rows),
                    "required_minimum": 10
                }

            # Extract values
            values = [row["value"] for row in rows]

            # Mann-Kendall trend test implementation
            n = len(values)
            s = 0

            # Calculate S statistic
            for i in range(n - 1):
                for j in range(i + 1, n):
                    s += self._sign(values[j] - values[i])

            # Calculate variance
            var_s = n * (n - 1) * (2 * n + 5) / 18

            # Calculate Z statistic
            if s > 0:
                z = (s - 1) / (var_s ** 0.5)
            elif s < 0:
                z = (s + 1) / (var_s ** 0.5)
            else:
                z = 0

            # Calculate p-value (two-tailed test)
            from scipy import stats
            p_value = 2 * (1 - stats.norm.cdf(abs(z)))

            # Determine trend
            has_degradation = False
            trend_direction = "stable"

            if p_value < significance_level:
                if s < 0:
                    trend_direction = "degrading"
                    has_degradation = True
                elif s > 0:
                    trend_direction = "improving"

            # Calculate magnitude (average change per cycle)
            early_half = values[:len(values)//2]
            late_half = values[len(values)//2:]
            magnitude = (statistics.mean(late_half) - statistics.mean(early_half)) / statistics.mean(early_half) * 100

            analysis = {
                "component": component_name,
                "metric": metric_name,
                "sample_size": n,
                "days_analyzed": days,
                "p_value": round(p_value, 4),
                "z_statistic": round(z, 3),
                "trend_direction": trend_direction,
                "magnitude_pct": round(magnitude, 2),
                "statistically_significant": p_value < significance_level,
                "confidence": round((1 - p_value) * 100, 1),
                "early_period_avg": round(statistics.mean(early_half), 2),
                "late_period_avg": round(statistics.mean(late_half), 2)
            }

            if has_degradation:
                logger.warning(
                    f"Statistical degradation detected for '{component_name}.{metric_name}': "
                    f"p={p_value:.4f}, magnitude={magnitude:.1f}%, confidence={analysis['confidence']}%"
                )

            return has_degradation, analysis

        except ImportError:
            logger.error("scipy not available - cannot perform statistical analysis")
            return False, {"error": "scipy required for statistical testing"}
        except Exception as e:
            logger.error(f"Error in statistical degradation detection: {e}")
            return False, {"error": str(e)}

    def _sign(self, x):
        """Helper for Mann-Kendall test"""
        if x > 0:
            return 1
        elif x < 0:
            return -1
        return 0

    async def track_cross_cycle_capability(
        self,
        component_name: str,
        metric_name: str,
        current_value: float,
        cycle_number: int
    ) -> Dict[str, Any]:
        """
        Track capability across improvement cycles for long-term monitoring

        Unlike track_improvement() which resets daily, this maintains stable baselines
        across 60+ cycles to detect long-horizon degradation or improvement.

        Args:
            component_name: Component being tracked
            metric_name: Capability metric name
            current_value: Current measurement
            cycle_number: Improvement cycle number

        Returns:
            Dict with baseline comparison and trend status
        """
        try:
            # Check if baseline exists
            baseline_row = await self.db.execute_query(
                """
                SELECT baseline_value, cycles_tracked, last_cycle_value, trend_status,
                       statistical_confidence, established_date
                FROM long_term_baselines
                WHERE component_name = $1 AND metric_name = $2
                """,
                params=(component_name, metric_name),
                fetch_one=True,
            )

            if not baseline_row:
                # Create new baseline
                await self.db.execute_query(
                    """
                    INSERT INTO long_term_baselines
                        (component_name, metric_name, baseline_value, established_date,
                         cycles_tracked, last_cycle_value, trend_status, created_at, updated_at)
                    VALUES ($1, $2, $3, CURRENT_DATE, 1, $3, 'baseline_established', NOW(), NOW())
                    """,
                    params=(component_name, metric_name, current_value),
                )

                logger.info(
                    f"Established long-term baseline for '{component_name}.{metric_name}': {current_value}"
                )

                return {
                    "status": "baseline_established",
                    "baseline_value": current_value,
                    "cycles_tracked": 1
                }

            # Update existing baseline
            #
            # float(...) IS THE WHOLE FIX FOR THE REGRESSION PATH. Postgres
            # returns NUMERIC as decimal.Decimal, and `current_value` arrives
            # as a float, so `current_value - baseline_value` raised
            #
            #     unsupported operand type(s) for -: 'float' and 'decimal.Decimal'
            #
            # on EVERY call after the first. The handler below turned that into
            # {"error": ...} and the caller moved on, so this function could
            # establish a baseline and then never once compare against it --
            # `trend_status` never left 'baseline_established' and the
            # `degrading` branch was unreachable in production.
            #
            # That is why self-improvement tracked improvement and never
            # regression: the only symmetric detector in the codebase failed on
            # a type mismatch, silently, every time it was asked to compare.
            baseline_value = float(baseline_row["baseline_value"])
            current_value = float(current_value)
            cycles_tracked = int(baseline_row["cycles_tracked"]) + 1

            # Calculate change from baseline
            # Undefined against a zero baseline rather than 0, which resolved
            # to "stable" and reported a baseline as holding steady on a
            # comparison that could not be made.
            pct_change = (((current_value - baseline_value) / baseline_value) * 100
                          if baseline_value != 0 else None)

            if pct_change is None:
                trend_status = ("improving" if current_value > baseline_value
                                else "degrading" if current_value < baseline_value
                                else "stable")
            elif pct_change > IMPROVEMENT_TREND_PCT:
                trend_status = "improving"
            elif pct_change < -IMPROVEMENT_TREND_PCT:
                trend_status = "degrading"
            else:
                trend_status = "stable"

            # Update database
            await self.db.execute_query(
                """
                UPDATE long_term_baselines
                SET cycles_tracked = $1,
                    last_cycle_value = $2,
                    trend_status = $3,
                    updated_at = NOW()
                WHERE component_name = $4 AND metric_name = $5
                """,
                params=(
                    cycles_tracked,
                    current_value,
                    trend_status,
                    component_name,
                    metric_name,
                ),
            )

            result = {
                "status": "updated",
                "baseline_value": baseline_value,
                "current_value": current_value,
                "pct_change_from_baseline": round(pct_change, 2),
                "trend_status": trend_status,
                "cycles_tracked": cycles_tracked,
                "days_since_baseline": (datetime.now().date() - baseline_row["established_date"]).days
            }

            logger.info(
                f"Cross-cycle tracking for '{component_name}.{metric_name}': "
                f"cycle {cycles_tracked}, {pct_change:+.1f}% from baseline, trend={trend_status}"
            )

            # This monitor is the authority on whether a component is below
            # where it started. It reports that; it does not decide what to do.
            try:
                from core.observability import regression_record

                if trend_status == "degrading":
                    await regression_record.report(
                        subject=component_name, dimension=metric_name,
                        detail=(f"{pct_change:+.1f}% against a baseline of "
                                f"{baseline_value:.3f} held for "
                                f"{cycles_tracked} cycle(s)"),
                        source_system="improvement_monitor",
                        baseline_value=baseline_value, current_value=current_value,
                        metadata={"cycles_tracked": cycles_tracked})
                elif trend_status in ("improving", "stable"):
                    # Back at or above baseline: whatever was open is closed.
                    await regression_record.resolve(component_name, metric_name)
            except Exception as regression_error:
                logger.error("Regression not recorded for %s.%s: %s",
                             component_name, metric_name, regression_error)

            return result

        except Exception as e:
            logger.error(f"Error tracking cross-cycle capability: {e}")
            return {"error": str(e)}

    async def get_capability_regression_report(
        self,
        days: int = 0
    ) -> Dict[str, Any]:
        """
        Generate report showing which capabilities have regressed over long horizon

        This answers: "Did we lose abilities we had 30-60 cycles ago?"

        Args:
            days: Lookback period for regression analysis

        Returns:
            Report dict with regressed capabilities and severity
        """
        try:
            # Get all baselines with trend analysis
            rows = await self.db.execute_query(
                """
                SELECT component_name, metric_name, baseline_value,
                       last_cycle_value, trend_status, cycles_tracked,
                       (CURRENT_DATE - established_date) AS days_tracked
                FROM long_term_baselines
                WHERE trend_status = 'degrading'
                """,
                fetch_all=True,
            ) or []

            # THE FILTER EXCLUDED EVERY RECENT REGRESSION.
            #
            # `days` defaulted to 90 and the test was `days_tracked >= days`,
            # so this reported only capabilities whose baseline was at least
            # ninety days old. A component degrading today was filtered out for
            # its first three months, and since `long_term_baselines` was empty
            # until this path was wired at all, the report would have returned
            # nothing for ninety days after being switched on.
            #
            # `days` is now a MINIMUM TRACKING AGE, defaulting to 0: report
            # every degrading capability and carry `days_tracked` so a consumer
            # can weigh how established the baseline is. A caller that wants
            # only long-standing regressions asks for them explicitly.
            regressions = [
                dict(r) for r in rows
                if r["days_tracked"] is None or int(r["days_tracked"]) >= days
            ]

            # Postgres returns NUMERIC as Decimal. Comparisons and arithmetic
            # below mix these with floats, which is the same mismatch that made
            # `track_cross_cycle_capability` fail on every comparison it was
            # ever asked to make.
            for row in regressions:
                for column in ("baseline_value", "last_cycle_value"):
                    if row.get(column) is not None:
                        row[column] = float(row[column])

            regressions.sort(
                key=lambda r: (
                    ((r["baseline_value"] - r["last_cycle_value"]) / r["baseline_value"])
                    if r["baseline_value"] not in (None, 0) and r["last_cycle_value"] is not None
                    else 0
                ),
                reverse=True,
            )

            # Calculate regression severity
            for regression in regressions:
                baseline = regression["baseline_value"]
                current = regression["last_cycle_value"]
                # A proportion of zero has no meaning, and `else 0` graded
                # exactly that case as LOW -- the mildest severity available,
                # assigned because the loss could not be computed at all.
                pct_lost = (((baseline - current) / baseline) * 100
                            if baseline not in (None, 0) else None)

                if pct_lost is None:
                    severity = "UNKNOWN"
                elif pct_lost > 20:
                    severity = "CRITICAL"
                elif pct_lost > 10:
                    severity = "HIGH"
                elif pct_lost > IMPROVEMENT_TREND_PCT:
                    severity = "MEDIUM"
                else:
                    severity = "LOW"

                regression["pct_capability_lost"] = (
                    None if pct_lost is None else round(pct_lost, 2))
                regression["severity"] = severity

            report = {
                "generated_at": datetime.now().isoformat(),
                "analysis_period_days": days,
                "total_regressions": len(regressions),
                "critical_regressions": len([r for r in regressions if r["severity"] == "CRITICAL"]),
                "regressions": regressions,
                "summary": {
                    "critical": [r for r in regressions if r["severity"] == "CRITICAL"],
                    "high": [r for r in regressions if r["severity"] == "HIGH"],
                    "medium": [r for r in regressions if r["severity"] == "MEDIUM"]
                }
            }

            if report["critical_regressions"] > 0:
                logger.error(
                    f"CAPABILITY REGRESSION: {report['critical_regressions']} critical regressions detected over {days} days"
                )

            return report

        except Exception as e:
            logger.error(f"Error generating capability regression report: {e}")
            return {"error": str(e)}

    async def get_latest_capability_status(self) -> Dict[str, Any]:
        """
        Get latest frozen capability benchmark status

        This provides quick access to global capability health without running new benchmarks.

        Returns:
            Latest capability benchmark results or error dict
        """
        try:
            # Get latest capability report
            latest = await self.db.execute_query(
                """
                SELECT
                    cycle_id,
                    overall_score,
                    reasoning_score,
                    coding_score,
                    analysis_score,
                    comprehension_score,
                    regression_detected,
                    regression_domains,
                    regression_severity,
                    tests_passed,
                    tests_failed,
                    baseline_delta,
                    statistical_significance,
                    timestamp
                FROM capability_reports
                ORDER BY timestamp DESC
                LIMIT 1
                """,
                fetch_one=True,
            )

            if not latest:
                return {
                    "status": "no_data",
                    "message": "No capability benchmark data available yet. Run first improvement cycle to establish baseline."
                }

            # Get historical trend (last 5 cycles)
            history = await self.db.execute_query(
                """
                SELECT overall_score, timestamp, cycle_id
                FROM capability_reports
                ORDER BY timestamp DESC
                LIMIT 5
                """,
                fetch_all=True,
            ) or []

            # Calculate trend
            if len(history) >= 2:
                score_change = history[0]["overall_score"] - history[-1]["overall_score"]
                if score_change > 0.05:
                    trend = "improving"
                elif score_change < -0.05:
                    trend = "degrading"
                else:
                    trend = "stable"
            else:
                trend = "insufficient_data"

            status = {
                "status": "ok",
                "cycle_id": latest["cycle_id"],
                "timestamp": latest["timestamp"].isoformat() if latest["timestamp"] else None,
                "overall_score": round(latest["overall_score"], 4),
                "domain_scores": {
                    "reasoning": round(latest["reasoning_score"], 4),
                    "coding": round(latest["coding_score"], 4),
                    "analysis": round(latest["analysis_score"], 4),
                    "comprehension": round(latest["comprehension_score"], 4)
                },
                "test_summary": {
                    "passed": latest["tests_passed"],
                    "failed": latest["tests_failed"],
                    "total": latest["tests_passed"] + latest["tests_failed"],
                    "pass_rate": latest["tests_passed"] / (latest["tests_passed"] + latest["tests_failed"])
                        if (latest["tests_passed"] + latest["tests_failed"]) > 0 else 0.0
                },
                "regression": {
                    "detected": bool(latest["regression_detected"]),
                    "domains": latest["regression_domains"].split(',') if latest["regression_domains"] else [],
                    "severity": latest["regression_severity"],
                    "baseline_delta": round(latest["baseline_delta"], 4),
                    "statistical_significance": round(latest["statistical_significance"], 4)
                },
                "trend": trend,
                "history": [
                    {
                        "cycle_id": h["cycle_id"],
                        "score": round(h["overall_score"], 4),
                        "timestamp": h["timestamp"].isoformat() if h["timestamp"] else None
                    }
                    for h in history
                ],
                "health_assessment": self._assess_capability_health(
                    latest["overall_score"],
                    latest["regression_detected"],
                    latest["regression_severity"]
                )
            }

            return status

        except Exception as e:
            logger.error(f"Error getting capability status: {e}")
            return {
                "status": "error",
                "error": str(e)
            }

    def _assess_capability_health(
        self,
        overall_score: float,
        regression_detected: bool,
        regression_severity: str
    ) -> str:
        """Assess overall capability health status"""

        if regression_detected:
            if regression_severity == "SEVERE":
                return "CRITICAL"
            elif regression_severity == "MODERATE":
                return "DEGRADED"
            else:
                return "WARNING"

        if overall_score >= 0.85:
            return "EXCELLENT"
        elif overall_score >= 0.75:
            return "GOOD"
        elif overall_score >= 0.65:
            return "FAIR"
        else:
            return "POOR"


# Global singleton
_improvement_monitor: Optional[ImprovementMonitor] = None


def get_improvement_monitor() -> ImprovementMonitor:
    """Get or create the global improvement monitor"""
    global _improvement_monitor
    if _improvement_monitor is None:
        _improvement_monitor = ImprovementMonitor()
    return _improvement_monitor
