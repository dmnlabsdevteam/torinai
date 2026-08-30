#!/usr/bin/env python3
"""
Performance Profiler

Profiles system performance to identify bottlenecks and optimization opportunities

Features:
- Function execution profiling (time, memory, CPU)
- Component-level profiling
- Bottleneck identification
- Performance recommendations
- Historical performance tracking
- Integration with improvement monitor
"""

import asyncio
import logging
import time
import psutil
import tracemalloc
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Any, List, Optional, Callable, Tuple
from functools import wraps
from collections import defaultdict
import json

logger = logging.getLogger(__name__)

# Singleton instance
_profiler_instance = None


@dataclass
class PerformanceMetrics:
    """Detailed performance metrics"""
    component_name: str
    operation_name: str

    # Timing
    execution_time_ms: float
    cpu_time_ms: float

    # Memory
    memory_used_mb: float
    peak_memory_mb: float
    memory_delta_mb: float  # Change during execution

    # CPU
    cpu_percent: float

    # Call statistics
    call_count: int = 1

    #: Whether the profiled call completed. Without this, `failed_operations`
    #: could only ever be 0 -- and performance_logs already shows the shape of
    #: that defect: 16,787 rows, none of them a failure, because `success` was
    #: hardcoded True at the only call site.
    success: bool = True
    error_message: Optional[str] = None

    # Metadata
    timestamp: datetime = field(default_factory=datetime.now)
    context: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ProfilerResult:
    """Result from profiling operation"""
    component_name: str
    operation_name: str

    # Summary metrics. Optional because UNMEASURED IS A REAL STATE and it is
    # not zero: a component nobody has profiled reported avg_time_ms=0, which
    # reads as instantaneous -- the best possible number, for a component about
    # which nothing is known. None cannot be mistaken for a measurement.
    total_time_ms: Optional[float]
    avg_time_ms: Optional[float]
    min_time_ms: Optional[float]
    max_time_ms: Optional[float]

    # Memory summary
    avg_memory_mb: Optional[float]
    peak_memory_mb: Optional[float]

    # CPU and call counts. The profiler_results table has columns for all
    # three; the dataclass had none of them, so _store_profiler_result read
    # `result.avg_cpu_percent`, `result.total_operations` and
    # `result.failed_operations` off an object that has never had them. It
    # would have raised AttributeError on its first use -- which never came,
    # because it also had zero callers.
    avg_cpu_percent: Optional[float] = None
    total_operations: int = 0
    failed_operations: int = 0

    # Bottlenecks
    bottlenecks: List[Dict[str, Any]] = field(default_factory=list)

    # Detailed metrics
    metrics_history: List[PerformanceMetrics] = field(default_factory=list)

    # Analysis
    performance_grade: str = "UNKNOWN"  # EXCELLENT, GOOD, FAIR, POOR, CRITICAL
    recommendations: List[str] = field(default_factory=list)

    # Metadata
    profiled_at: datetime = field(default_factory=datetime.now)
    profile_duration_sec: float = 0.0


@dataclass
class Bottleneck:
    """Performance bottleneck"""
    component_name: str
    operation_name: str
    severity: str  # LOW, MEDIUM, HIGH, CRITICAL

    # Issue
    issue_type: str  # "slow_execution", "high_memory", "high_cpu", "frequent_calls"
    description: str

    # Metrics
    current_value: float
    expected_value: float
    impact_score: float  # 0-100

    # Recommendations
    recommendations: List[str] = field(default_factory=list)

    # Metadata
    detected_at: datetime = field(default_factory=datetime.now)


class PerformanceProfiler:
    """
    Profiles system performance

    Purpose:
    - Measure execution time and resource usage
    - Identify performance bottlenecks
    - Track performance over time
    - Provide optimization recommendations

    Integrates with improvement monitor for long-term tracking
    """

    def __init__(self, db_config: Dict[str, Any] = None):
        self.db_config = db_config or {}
        self.metrics_history: Dict[str, List[PerformanceMetrics]] = defaultdict(list)
        self.profiler_results: Dict[str, ProfilerResult] = {}

        # Configuration
        self.enable_memory_profiling = True
        self.enable_cpu_profiling = True
        self.max_history_per_component = 1000

        # Performance thresholds
        self.thresholds = {
            "execution_time_ms": {
                "excellent": 10,
                "good": 50,
                "fair": 200,
                "poor": 1000,
                "critical": 5000
            },
            "memory_mb": {
                "excellent": 10,
                "good": 50,
                "fair": 200,
                "poor": 500,
                "critical": 1000
            },
            "cpu_percent": {
                "excellent": 10,
                "good": 30,
                "fair": 60,
                "poor": 80,
                "critical": 95
            }
        }

        # Process handle
        self.process = psutil.Process()

        #: Metrics that could not be written. Readable, so "nothing was
        #: recorded" and "nothing happened" are distinguishable.
        self._unpersisted = 0
        self._legacy_memory_warned = False

        logger.info("PerformanceProfiler initialized")

    async def profile_function(
        self,
        func: Callable,
        component_name: str,
        operation_name: str = None,
        *args,
        **kwargs
    ) -> Tuple[Any, PerformanceMetrics]:
        """
        Profile a single function execution

        Args:
            func: Function to profile
            component_name: Component name
            operation_name: Optional operation name (defaults to func.__name__)
            *args: Function arguments
            **kwargs: Function keyword arguments

        Returns:
            Tuple of (function result, performance metrics)
        """
        operation_name = operation_name or getattr(func, '__name__', 'unknown')

        logger.debug(f"Profiling {component_name}.{operation_name}")

        # Only start tracing if nobody else is. A nested profile used to call
        # start() and then stop(), tearing down the OUTER profile's tracer.
        owns_tracer = False
        if self.enable_memory_profiling and not tracemalloc.is_tracing():
            tracemalloc.start()
            owns_tracer = True

        # psutil measures CPU as a share of the interval SINCE THE LAST CALL on
        # this handle. The first call on a fresh handle has no interval and
        # always returns 0.0 -- which is why every cpu_percent this profiler
        # recorded in a short-lived process was zero. Priming here makes the
        # reading below cover the function's own execution.
        if self.enable_cpu_profiling:
            self.process.cpu_percent()

        start_time = time.time()
        start_cpu_time = time.process_time()
        mem_before = self.process.memory_info().rss / 1024 / 1024  # MB

        # THE FUNCTION MAY RAISE, AND A FAILURE IS A PERFORMANCE FACT.
        #
        # This had no try/finally: an exception skipped the timing, skipped the
        # recording, and left tracemalloc running for the life of the process.
        # `success=True` was then hardcoded at the one call site, so
        # performance_logs holds 16,787 rows and ZERO failures -- the column
        # exists and could never be False. A slow operation that always fails
        # looked like an operation that was never run.
        result = None
        failure: Optional[BaseException] = None
        try:
            if asyncio.iscoroutinefunction(func):
                result = await func(*args, **kwargs)
            else:
                result = func(*args, **kwargs)
        except BaseException as error:
            failure = error
        finally:
            end_time = time.time()
            end_cpu_time = time.process_time()
            mem_after = self.process.memory_info().rss / 1024 / 1024

            peak_memory = 0.0
            if owns_tracer and tracemalloc.is_tracing():
                _current, peak = tracemalloc.get_traced_memory()
                peak_memory = peak / 1024 / 1024
                tracemalloc.stop()

            cpu_percent = self.process.cpu_percent() if self.enable_cpu_profiling else 0.0

        execution_time_ms = (end_time - start_time) * 1000
        cpu_time_ms = (end_cpu_time - start_cpu_time) * 1000
        memory_delta = mem_after - mem_before

        # Create metrics
        metrics = PerformanceMetrics(
            component_name=component_name,
            operation_name=operation_name,
            execution_time_ms=execution_time_ms,
            cpu_time_ms=cpu_time_ms,
            # THE OPERATION'S OWN COST, not the interpreter's footprint. This
            # was `mem_after` -- total process RSS -- graded against thresholds
            # of 10/50/200/500 MB. Measured at 652 MB RSS, that pinned the
            # memory score at its floor and made EXCELLENT unreachable: a
            # 0.164ms function graded GOOD, and a 100ms one graded POOR purely
            # because the process is large. The grade described the interpreter,
            # not the code being profiled.
            memory_used_mb=max(0.0, memory_delta),
            peak_memory_mb=peak_memory,
            memory_delta_mb=memory_delta,
            cpu_percent=cpu_percent,
            call_count=1,
            success=failure is None,
            error_message=(f"{type(failure).__name__}: {failure}"
                           if failure is not None else None),
            timestamp=datetime.now()
        )

        # Store metrics, capped. metrics_history is a defaultdict(list) that
        # only ever grew; max_history_per_component was configured and never
        # applied, so a long-running process accumulated every measurement.
        key = f"{component_name}.{operation_name}"
        self.metrics_history[key].append(metrics)
        if len(self.metrics_history[key]) > self.max_history_per_component:
            del self.metrics_history[key][:-self.max_history_per_component]

        await self._persist_metrics(
            component_name=component_name,
            operation_name=operation_name,
            metrics=metrics,
            success=failure is None,
            error_message=(f"{type(failure).__name__}: {failure}"
                           if failure is not None else None),
            context={
                "args_count": len(args),
                "kwargs_count": len(kwargs),
                "function_name": operation_name,
                "total_profiles": len(self.metrics_history[key]),
                "timestamp": datetime.now().isoformat(),
            },
            mem_after_rss=mem_after,
        )

        if failure is not None:
            logger.warning(
                "Profiled %s.%s: FAILED after %.2fms with %s",
                component_name, operation_name, execution_time_ms,
                type(failure).__name__)
            # The measurement is recorded and then the exception continues to
            # the caller. Profiling observes; it must not swallow.
            raise failure

        logger.info(
            "Profiled %s.%s: time=%.2fms, memory=%+.3fMB, cpu=%.1f%%",
            component_name, operation_name, execution_time_ms,
            memory_delta, cpu_percent)

        return result, metrics

    async def profile_component(
        self,
        component_name: str,
        operations: List[str] = None
    ) -> ProfilerResult:
        """
        Analyze component performance from historical data

        Args:
            component_name: Component to analyze
            operations: Specific operations to analyze (None = all)

        Returns:
            Profiler result with analysis
        """
        logger.info(f"Analyzing component: {component_name}")

        # Get all metrics for this component
        component_metrics = []
        for key, metrics_list in self.metrics_history.items():
            comp_name, op_name = key.split('.', 1)
            if comp_name == component_name:
                if operations is None or op_name in operations:
                    component_metrics.extend(metrics_list)

        if not component_metrics:
            # THE HISTORY OUTLIVES THE PROCESS; THIS ONLY READ MEMORY.
            #
            # metrics_history is an in-process dict, so a freshly started
            # process had none and every analysis returned the empty result --
            # while performance_logs held 16,787 real measurements. The
            # profiler could not see its own recorded history.
            component_metrics = await self._load_metrics(component_name, operations)

        if not component_metrics:
            # NOT ZERO. Zeros here read as an instantaneous, memory-free
            # component -- the best possible numbers, reported for a component
            # nothing is known about. None means unmeasured, and the grade
            # already says UNKNOWN.
            logger.warning("No metrics for %s (in memory or persisted); "
                           "reporting UNKNOWN rather than zeros", component_name)
            return ProfilerResult(
                component_name=component_name,
                operation_name="all",
                total_time_ms=None,
                avg_time_ms=None,
                min_time_ms=None,
                max_time_ms=None,
                avg_memory_mb=None,
                peak_memory_mb=None,
                performance_grade="UNKNOWN",
                recommendations=[
                    f"No performance data for {component_name}. Profile it with "
                    f"profile_function() before drawing conclusions."],
            )

        # Calculate statistics
        execution_times = [m.execution_time_ms for m in component_metrics]
        memory_usage = [m.memory_used_mb for m in component_metrics]
        peak_memory = max(m.peak_memory_mb for m in component_metrics)

        # Identify bottlenecks
        bottlenecks = await self._identify_bottlenecks(component_name, component_metrics)

        # Grade performance
        avg_time = sum(execution_times) / len(execution_times)
        performance_grade = self._calculate_performance_grade(
            avg_time_ms=avg_time,
            avg_memory_mb=sum(memory_usage) / len(memory_usage),
            peak_memory_mb=peak_memory
        )

        # Generate recommendations
        recommendations = self._generate_recommendations(
            component_metrics, bottlenecks, performance_grade
        )

        cpu_readings = [m.cpu_percent for m in component_metrics
                        if m.cpu_percent is not None]
        failed = sum(1 for m in component_metrics if not m.success)

        result = ProfilerResult(
            component_name=component_name,
            operation_name="all",
            total_time_ms=sum(execution_times),
            avg_time_ms=avg_time,
            min_time_ms=min(execution_times),
            max_time_ms=max(execution_times),
            avg_memory_mb=sum(memory_usage) / len(memory_usage),
            peak_memory_mb=peak_memory,
            # None, not 0.0: no CPU reading is not a component using no CPU.
            avg_cpu_percent=(sum(cpu_readings) / len(cpu_readings)
                             if cpu_readings else None),
            total_operations=len(component_metrics),
            failed_operations=failed,
            bottlenecks=bottlenecks,
            metrics_history=component_metrics,
            performance_grade=performance_grade,
            recommendations=recommendations,
            profiled_at=datetime.now(),
            profile_duration_sec=0  # Not applicable for historical analysis
        )

        # Persist as well as cache. The analysis used to live only in this
        # dict, so `profiler_results` had 0 rows and every restart lost every
        # grade the profiler had ever assigned.
        await self._store_profiler_result(result)

        logger.info(
            f"Component analysis complete: {component_name}, "
            f"grade={performance_grade}, bottlenecks={len(bottlenecks)}"
        )

        return result

    async def _load_metrics(
        self,
        component_name: str,
        operations: List[str] = None,
        limit: int = 1000,
    ) -> List[PerformanceMetrics]:
        """Recover this component's measurements from the persisted log.

        `performance_logs` is what `_persist_metrics` writes, keyed by
        `component.operation` in its `operation` column. Reading it back is
        what makes a profile survive a restart.
        """
        try:
            from core.database import get_database_manager

            db = get_database_manager()
            if not getattr(db, 'initialized', False):
                logger.warning("Cannot load persisted metrics for %s: database "
                               "not initialised", component_name)
                return []
            rows = await db.execute_query(
                """SELECT operation, duration, cpu_usage, memory_usage,
                          success, timestamp, details
                     FROM unified.performance_logs
                    WHERE operation LIKE $1
                    ORDER BY timestamp DESC LIMIT $2""",
                (f"{component_name}.%", int(limit)), fetch_all=True) or []
        except Exception as error:
            logger.error("Persisted metrics unavailable for %s: %s",
                         component_name, error)
            return []

        recovered: List[PerformanceMetrics] = []
        for row in rows:
            operation = str(row["operation"] or "")
            op_name = operation.split(".", 1)[1] if "." in operation else operation
            if operations is not None and op_name not in operations:
                continue
            details = row["details"]
            if isinstance(details, str):
                try:
                    details = json.loads(details)
                except (TypeError, ValueError):
                    details = {}
            details = details or {}
            # A row written before the memory fix holds process RSS in
            # `memory_usage`, which is ~650MB and would trip the 200MB
            # high-memory bottleneck for every operation ever recorded. Only a
            # row that says it holds the operation's own cost is read as such;
            # older rows contribute their timing and report memory as 0.
            operation_memory = 0.0
            if details.get("memory_semantics") == "operation_delta_mb":
                operation_memory = float(row["memory_usage"] or 0.0)
            elif not self._legacy_memory_warned:
                self._legacy_memory_warned = True
                logger.info(
                    "Some persisted rows for %s predate the memory fix and "
                    "hold process RSS rather than operation cost; their memory "
                    "is reported as unmeasured rather than as a bottleneck",
                    component_name)

            recovered.append(PerformanceMetrics(
                component_name=component_name,
                operation_name=op_name,
                execution_time_ms=float(row["duration"] or 0.0),
                cpu_time_ms=float(details.get("cpu_time_ms") or 0.0),
                memory_used_mb=operation_memory,
                peak_memory_mb=float(details.get("peak_memory_mb") or 0.0),
                memory_delta_mb=float(details.get("memory_delta_mb") or 0.0),
                cpu_percent=float(row["cpu_usage"] or 0.0),
                call_count=1,
                success=bool(row["success"]),
                error_message=details.get("error_message"),
                timestamp=row["timestamp"],
            ))
        if recovered:
            logger.info("Recovered %d persisted measurement(s) for %s",
                        len(recovered), component_name)
        return recovered

    async def _identify_bottlenecks(
        self,
        component_name: str,
        metrics: List[PerformanceMetrics]
    ) -> List[Dict[str, Any]]:
        """
        Identify performance bottlenecks

        Looks for:
        - Slow operations (execution time)
        - High memory usage
        - High CPU usage
        - Frequent calls to slow operations
        """
        if not metrics:
            logger.debug(f"No metrics for {component_name}, no bottlenecks")
            return []

        bottlenecks = []

        # Group by operation
        ops_metrics: Dict[str, List[PerformanceMetrics]] = defaultdict(list)
        for m in metrics:
            ops_metrics[m.operation_name].append(m)

        # Analyze each operation
        for op_name, op_metrics in ops_metrics.items():
            avg_time = sum(m.execution_time_ms for m in op_metrics) / len(op_metrics)
            avg_memory = sum(m.memory_used_mb for m in op_metrics) / len(op_metrics)
            avg_cpu = sum(m.cpu_percent for m in op_metrics) / len(op_metrics)

            # Check for slow execution (>200ms average)
            if avg_time > self.thresholds["execution_time_ms"]["fair"]:
                severity = self._calculate_severity(
                    avg_time,
                    self.thresholds["execution_time_ms"]
                )
                bottlenecks.append({
                    "operation": op_name,
                    "type": "slow_execution",
                    "severity": severity,
                    "avg_time_ms": avg_time,
                    "threshold_ms": self.thresholds["execution_time_ms"]["fair"],
                    "impact": "high"
                })

            # Check for high memory (>200MB average)
            if avg_memory > self.thresholds["memory_mb"]["fair"]:
                severity = self._calculate_severity(
                    avg_memory,
                    self.thresholds["memory_mb"]
                )
                bottlenecks.append({
                    "operation": op_name,
                    "type": "high_memory",
                    "severity": severity,
                    "avg_memory_mb": avg_memory,
                    "threshold_mb": self.thresholds["memory_mb"]["fair"],
                    "impact": "medium"
                })

            # Check for high CPU (>60% average)
            if avg_cpu > self.thresholds["cpu_percent"]["fair"]:
                severity = self._calculate_severity(
                    avg_cpu,
                    self.thresholds["cpu_percent"]
                )
                bottlenecks.append({
                    "operation": op_name,
                    "type": "high_cpu",
                    "severity": severity,
                    "avg_cpu_percent": avg_cpu,
                    "threshold_percent": self.thresholds["cpu_percent"]["fair"],
                    "impact": "medium"
                })

        logger.info(f"Identified {len(bottlenecks)} bottlenecks for {component_name}")

        return bottlenecks

    def _calculate_severity(
        self,
        value: float,
        thresholds: Dict[str, float]
    ) -> str:
        """Calculate severity based on thresholds"""
        if value >= thresholds["critical"]:
            return "CRITICAL"
        elif value >= thresholds["poor"]:
            return "HIGH"
        elif value >= thresholds["fair"]:
            return "MEDIUM"
        else:
            return "LOW"

    def _calculate_performance_grade(
        self,
        avg_time_ms: float,
        avg_memory_mb: float,
        peak_memory_mb: float
    ) -> str:
        """
        Calculate overall performance grade

        Based on:
        - Average execution time (70% weight)
        - Average memory usage (20% weight)
        - Peak memory usage (10% weight)

        Returns:
            Performance grade: EXCELLENT, GOOD, FAIR, POOR, CRITICAL
        """
        # Time score (0-100, inverted)
        time_thresholds = self.thresholds["execution_time_ms"]
        if avg_time_ms <= time_thresholds["excellent"]:
            time_score = 100
        elif avg_time_ms <= time_thresholds["good"]:
            time_score = 80
        elif avg_time_ms <= time_thresholds["fair"]:
            time_score = 60
        elif avg_time_ms <= time_thresholds["poor"]:
            time_score = 40
        else:
            time_score = 20

        # Memory score (0-100, inverted)
        mem_thresholds = self.thresholds["memory_mb"]
        if avg_memory_mb <= mem_thresholds["excellent"]:
            mem_score = 100
        elif avg_memory_mb <= mem_thresholds["good"]:
            mem_score = 80
        elif avg_memory_mb <= mem_thresholds["fair"]:
            mem_score = 60
        elif avg_memory_mb <= mem_thresholds["poor"]:
            mem_score = 40
        else:
            mem_score = 20

        # Peak memory score (0-100, inverted)
        if peak_memory_mb <= mem_thresholds["excellent"]:
            peak_score = 100
        elif peak_memory_mb <= mem_thresholds["good"]:
            peak_score = 80
        elif peak_memory_mb <= mem_thresholds["fair"]:
            peak_score = 60
        elif peak_memory_mb <= mem_thresholds["poor"]:
            peak_score = 40
        else:
            peak_score = 20

        # Weighted average
        overall_score = (time_score * 0.7) + (mem_score * 0.2) + (peak_score * 0.1)

        # Convert to grade
        if overall_score >= 90:
            return "EXCELLENT"
        elif overall_score >= 75:
            return "GOOD"
        elif overall_score >= 60:
            return "FAIR"
        elif overall_score >= 40:
            return "POOR"
        else:
            return "CRITICAL"

    def _generate_recommendations(
        self,
        metrics: List[PerformanceMetrics],
        bottlenecks: List[Dict[str, Any]],
        performance_grade: str
    ) -> List[str]:
        """
        Generate performance improvement recommendations

        Based on identified bottlenecks and performance grade
        """
        if not metrics:
            logger.debug("No metrics, no recommendations")
            return []

        recommendations = []

        # Grade-based recommendations
        if performance_grade in ["POOR", "CRITICAL"]:
            recommendations.append("URGENT: Performance is below acceptable levels")
            recommendations.append("Consider profiling individual operations to identify root causes")

        # Bottleneck-specific recommendations
        for bottleneck in bottlenecks:
            bottleneck_type = bottleneck.get("type", "unknown")
            operation = bottleneck.get("operation", "unknown")
            severity = bottleneck.get("severity", "UNKNOWN")

            if bottleneck_type == "slow_execution":
                avg_time = bottleneck.get("avg_time_ms", 0)
                recommendations.append(
                    f"{severity}: Operation '{operation}' is slow ({avg_time:.1f}ms average)"
                )
                recommendations.append(
                    f"  → Consider optimizing algorithm or adding caching for '{operation}'"
                )

            elif bottleneck_type == "high_memory":
                avg_mem = bottleneck.get("avg_memory_mb", 0)
                recommendations.append(
                    f"{severity}: Operation '{operation}' uses high memory ({avg_mem:.1f}MB average)"
                )
                recommendations.append(
                    f"  → Review data structures and consider streaming for '{operation}'"
                )

            elif bottleneck_type == "high_cpu":
                avg_cpu = bottleneck.get("avg_cpu_percent", 0)
                recommendations.append(
                    f"{severity}: Operation '{operation}' uses high CPU ({avg_cpu:.1f}% average)"
                )
                recommendations.append(
                    f"  → Consider async processing or optimization for '{operation}'"
                )

        # General recommendations
        if not bottlenecks and performance_grade in ["GOOD", "EXCELLENT"]:
            recommendations.append("Performance is good - no critical optimizations needed")

        return recommendations

    async def get_statistics(
        self,
        component_name: str = None
    ) -> Dict[str, Any]:
        """
        Get profiler statistics

        Args:
            component_name: Optional component filter

        Returns:
            Statistics dictionary
        """
        if component_name:
            logger.debug(f"Getting statistics for {component_name}")
            result = await self.profile_component(component_name)
            return {
                "component": component_name,
                "total_profiles": len(result.metrics_history),
                "avg_time_ms": result.avg_time_ms,
                "avg_memory_mb": result.avg_memory_mb,
                "performance_grade": result.performance_grade,
                "bottlenecks": len(result.bottlenecks)
            }

        # Overall statistics
        total_profiles = sum(len(metrics) for metrics in self.metrics_history.values())
        components_profiled = len(set(
            key.split('.', 1)[0] for key in self.metrics_history.keys()
        ))

        # Calculate overall performance
        all_metrics = []
        for metrics_list in self.metrics_history.values():
            all_metrics.extend(metrics_list)

        avg_time = 0.0
        avg_memory = 0.0
        if all_metrics:
            avg_time = sum(m.execution_time_ms for m in all_metrics) / len(all_metrics)
            avg_memory = sum(m.memory_used_mb for m in all_metrics) / len(all_metrics)

        return {
            "total_profiles": total_profiles,
            "components_profiled": components_profiled,
            "operations_profiled": len(self.metrics_history),
            "avg_time_ms": round(avg_time, 2),
            "avg_memory_mb": round(avg_memory, 2),
            "profiler_results": len(self.profiler_results)
        }

    async def _persist_metrics(
        self,
        component_name: str,
        operation_name: str,
        metrics: PerformanceMetrics,
        success: bool,
        error_message: Optional[str],
        context: Dict[str, Any] = None,
        mem_after_rss: float = 0.0,
    ):
        """Persist metrics to database (Postgres)"""
        from core.database import get_database_manager
        db = get_database_manager()

        if not getattr(db, 'initialized', False):
            # SILENTLY DROPPED BEFORE. A profile taken before the pool was up
            # returned normally and wrote nothing, so the caller believed the
            # measurement was recorded. Verified: a profile run in an
            # uninitialised process produced 0 rows and no signal at all.
            self._unpersisted += 1
            logger.warning(
                "Performance metric for %s.%s NOT persisted: database not "
                "initialised (%d dropped so far this process)",
                component_name, operation_name, self._unpersisted)
            return

        import json
        try:
            await db.execute_query(
                """
                INSERT INTO performance_logs
                   (timestamp, operation, duration, cpu_usage, memory_usage, success, details)
                   VALUES ($1, $2, $3, $4, $5, $6, $7)
                """,
                params=(
                    datetime.now(),
                    f"{component_name}.{operation_name}",
                    metrics.execution_time_ms,
                    metrics.cpu_percent,
                    metrics.memory_used_mb,
                    success,
                    json.dumps({
                        "component": component_name,
                        "operation": operation_name,
                        "error_message": error_message,
                        # `memory_usage` HOLDS A DIFFERENT QUANTITY IN OLD ROWS.
                        # Before this was fixed the column received total
                        # process RSS (~650MB), not the operation's cost, so
                        # every historical row exceeds the 200MB "high memory"
                        # bottleneck threshold and would be reported as a
                        # bottleneck on replay. New rows carry this marker so
                        # the loader can tell which semantics a row uses.
                        "memory_semantics": "operation_delta_mb",
                        "process_rss_mb": round(mem_after_rss, 2),
                        "memory_delta_mb": round(metrics.memory_delta_mb, 4),
                        "peak_memory_mb": round(metrics.peak_memory_mb, 4),
                        "cpu_time_ms": round(metrics.cpu_time_ms, 4),
                        "context": context,
                    }, default=str),
                ),
                commit=True,
            )
            logger.debug(f"Metrics persisted for {component_name}.{operation_name}")
        except Exception as e:
            # DEBUG HID THIS ENTIRELY. A metric that failed to write left no
            # visible trace at the default log level, so "the component was
            # never profiled" and "every profile failed to save" looked
            # identical from the outside.
            self._unpersisted += 1
            logger.error("Could not persist metrics for %s.%s: %s (%d dropped "
                         "this process)", component_name, operation_name, e,
                         self._unpersisted)

    async def _store_profiler_result(
        self,
        result: ProfilerResult,
        database_config: Dict[str, Any] = None
    ):
        """Store profiler result in database (Postgres)"""
        # Store in results dict
        self.profiler_results[result.component_name] = result

        # Persist. EVERY FIELD BELOW WAS WRONG: this read
        # `avg_execution_time_ms`, `avg_cpu_percent`, `total_operations`,
        # `failed_operations` and two percentiles off a ProfilerResult that has
        # never declared any of them, and inserted into a `timestamp` column
        # the table does not have (it is `created_at`). The method could not
        # have run; it had no callers, so nothing ever found out.
        try:
            from core.database import get_database_manager

            db = get_database_manager()
            if not getattr(db, 'initialized', False):
                self._unpersisted += 1
                logger.warning("Profiler result for %s NOT persisted: database "
                               "not initialised", result.component_name)
                return

            times = sorted(m.execution_time_ms for m in result.metrics_history)

            def _percentile(fraction: float) -> Optional[float]:
                if not times:
                    return None
                index = min(len(times) - 1, int(len(times) * fraction))
                return round(times[index], 3)

            await db.execute_query(
                """
                INSERT INTO profiler_results
                   (component_name, performance_grade, avg_execution_time_ms,
                    avg_memory_mb, avg_cpu_percent, total_operations,
                    failed_operations, bottlenecks, created_at, metadata)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb, NOW(), $9::jsonb)
                """,
                params=(
                    result.component_name,
                    result.performance_grade,
                    result.avg_time_ms,
                    result.avg_memory_mb,
                    result.avg_cpu_percent,
                    result.total_operations,
                    result.failed_operations,
                    json.dumps(result.bottlenecks, default=str),
                    json.dumps({
                        'p50_execution_time_ms': _percentile(0.50),
                        'p95_execution_time_ms': _percentile(0.95),
                        'min_time_ms': result.min_time_ms,
                        'max_time_ms': result.max_time_ms,
                        'peak_memory_mb': result.peak_memory_mb,
                        'recommendations': result.recommendations,
                        'profiled_at': result.profiled_at.isoformat(),
                    }, default=str),
                ),
                commit=True,
            )
            logger.debug("Profiler result stored: %s (grade=%s, %d ops, %d failed)",
                         result.component_name, result.performance_grade,
                         result.total_operations, result.failed_operations)
        except Exception as e:
            # Counted, not just logged: a grade that was computed and never
            # written is indistinguishable from one never computed unless the
            # loss is visible somewhere.
            self._unpersisted += 1
            logger.error("Failed to store profiler result for %s: %s",
                         result.component_name, e)

    async def clear_history(
        self,
        component_name: str = None,
        operations: List[str] = None
    ):
        """Clear profiling history"""
        if component_name:
            # Clear specific component
            keys_to_clear = [
                key for key in self.metrics_history.keys()
                if key.startswith(f"{component_name}.")
            ]
            for key in keys_to_clear:
                if operations:
                    _, op = key.split('.', 1)
                    if op in operations:
                        del self.metrics_history[key]
                else:
                    del self.metrics_history[key]

            logger.info(f"Cleared history for {component_name}")
        else:
            # Clear all
            self.metrics_history.clear()
            self.profiler_results.clear()
            logger.info("Cleared all profiling history")

    def get_component_history(
        self,
        component_name: str,
        operation_name: str = None
    ) -> List[PerformanceMetrics]:
        """Get profiling history for component/operation"""
        if operation_name:
            key = f"{component_name}.{operation_name}"
            return self.metrics_history.get(key, [])

        # Get all metrics for component
        component_metrics = []
        for key, metrics in self.metrics_history.items():
            if key.startswith(f"{component_name}."):
                component_metrics.extend(metrics)

        return component_metrics


# Singleton accessor
def get_performance_profiler() -> PerformanceProfiler:
    """Get global performance profiler instance"""
    global _profiler_instance
    if _profiler_instance is None:
        _profiler_instance = PerformanceProfiler()
    return _profiler_instance


# Decorator for easy profiling
def profile_performance(component_name: str, operation_name: str = None):
    """
    Decorator to automatically profile function performance

    Usage:
        @profile_performance("my_component", "my_operation")
        async def my_function():
            ...
    """
    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            profiler = get_performance_profiler()
            result, metrics = await profiler.profile_function(
                func, component_name, operation_name, *args, **kwargs
            )
            return result
        return wrapper
    return decorator
