#!/usr/bin/env python3
"""
Behavioral Analysis Layer
=========================
Infers system behavior through observation of interactions.

Methods:
- Network flow analysis - Track communication patterns
- Dependency inference - Learn service relationships
- Failure propagation - Map cascading failures
- Performance correlation - Understand interdependencies

Research: Based on distributed systems causality (Lamport) and
          network flow analysis (Greenberg et al.)

Author: Dominion Labs
"""

import asyncio
import psutil
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, Set, List, Optional, Tuple
from collections import defaultdict
from enum import Enum

logger = logging.getLogger(__name__)


class DependencyType(Enum):
    """Type of dependency relationship"""
    STRONG = "strong"      # Direct, consistent communication
    WEAK = "weak"          # Occasional communication
    INFERRED = "inferred"  # Inferred from timing patterns


@dataclass
class NetworkFlow:
    """Observed network connection"""
    source_port: int
    dest_port: int
    timestamp: datetime
    bytes_sent: int = 0
    bytes_recv: int = 0
    duration_ms: float = 0


@dataclass
class ServiceDependency:
    """Inferred dependency between services"""
    source_port: int
    target_port: int
    dependency_type: DependencyType
    confidence: float  # 0.0 to 1.0
    observed_flows: int = 0
    last_observed: datetime = field(default_factory=datetime.now)
    avg_response_time_ms: Optional[float] = None


@dataclass
class FailureEvent:
    """Observed service failure"""
    port: int
    timestamp: datetime
    error_type: str
    duration_s: float
    cascaded_to: List[int] = field(default_factory=list)


class BehavioralAnalysis:
    """
    Behavioral Analysis Layer

    Learns system behavior through observation:
    1. Network flow tracking
    2. Dependency inference from communication
    3. Failure propagation detection
    4. Performance correlation

    Builds understanding without configuration.

    Usage:
        analyzer = BehavioralAnalysis()
        await analyzer.observe()  # Run continuously

        deps = analyzer.get_dependencies(8080)
        if analyzer.would_impact_cascade(3306):
            # MySQL failure would cascade!
    """

    def __init__(self):
        # Network flow tracking
        self.flows: List[NetworkFlow] = []
        self.flow_history_limit = 10000

        # Inferred dependencies
        self.dependencies: Dict[Tuple[int, int], ServiceDependency] = {}

        # Failure tracking
        self.failures: List[FailureEvent] = []
        self.failure_history_limit = 1000

        # Performance tracking
        self.response_times: Dict[int, List[float]] = defaultdict(list)
        self.response_time_limit = 100  # Keep last 100 samples per service

        # Observation state
        self.last_observation: Optional[datetime] = None
        self.observation_count = 0

        # Connection state tracking
        self.known_connections: Dict[Tuple, datetime] = {}

    async def observe(self, duration_s: float = 5.0):
        """
        Observe system behavior for duration

        Args:
            duration_s: How long to observe (seconds)
        """
        self.observation_count += 1
        self.last_observation = datetime.now()

        # Capture network flows
        await self._capture_network_flows(duration_s)

        # Analyze patterns
        self._infer_dependencies()
        self._detect_failure_patterns()
        self._analyze_performance_correlation()

        # Cleanup old data
        self._cleanup_history()

    async def _capture_network_flows(self, duration_s: float):
        """Capture network connections over time period"""
        start_time = datetime.now()
        snapshots = []

        # Take multiple snapshots
        while (datetime.now() - start_time).total_seconds() < duration_s:
            try:
                connections = psutil.net_connections(kind='inet')
                snapshots.append((datetime.now(), connections))
                await asyncio.sleep(0.5)  # Sample every 500ms
            except (PermissionError, psutil.AccessDenied):
                logger.warning("Insufficient permissions for network monitoring")
                return

        # Analyze connection changes between snapshots
        for i in range(len(snapshots) - 1):
            timestamp, conns = snapshots[i]
            next_timestamp, next_conns = snapshots[i + 1]

            self._analyze_connection_diff(timestamp, conns, next_conns)

    def _analyze_connection_diff(self, timestamp, conns, next_conns):
        """Analyze difference between connection snapshots"""
        # Build connection maps
        current = {(c.laddr.port, c.raddr.port if c.raddr else None): c
                   for c in conns if c.status == 'ESTABLISHED' and c.raddr}

        next_map = {(c.laddr.port, c.raddr.port if c.raddr else None): c
                    for c in next_conns if c.status == 'ESTABLISHED' and c.raddr}

        # Track new flows
        for key, conn in current.items():
            source_port, dest_port = key
            if dest_port and dest_port != source_port:  # Ignore self-connections
                # Create flow record
                flow = NetworkFlow(
                    source_port=source_port,
                    dest_port=dest_port,
                    timestamp=timestamp
                )
                self.flows.append(flow)

                # Track for dependency inference
                self.known_connections[key] = timestamp

    def _infer_dependencies(self):
        """Infer service dependencies from flow patterns"""
        # Analyze recent flows (last 5 minutes)
        recent_window = datetime.now() - timedelta(minutes=5)
        recent_flows = [f for f in self.flows if f.timestamp >= recent_window]

        # Count flows between service pairs
        flow_counts = defaultdict(int)
        for flow in recent_flows:
            key = (flow.source_port, flow.dest_port)
            flow_counts[key] += 1

        # Update dependencies
        for (source, target), count in flow_counts.items():
            key = (source, target)

            # Determine dependency type based on frequency
            if count >= 10:  # Strong dependency
                dep_type = DependencyType.STRONG
                confidence = min(1.0, count / 20)
            elif count >= 3:  # Weak dependency
                dep_type = DependencyType.WEAK
                confidence = min(0.8, count / 10)
            else:  # Inferred
                dep_type = DependencyType.INFERRED
                confidence = min(0.5, count / 5)

            if key in self.dependencies:
                # Update existing
                dep = self.dependencies[key]
                dep.observed_flows += count
                dep.last_observed = datetime.now()
                dep.dependency_type = dep_type
                dep.confidence = confidence
            else:
                # Create new
                self.dependencies[key] = ServiceDependency(
                    source_port=source,
                    target_port=target,
                    dependency_type=dep_type,
                    confidence=confidence,
                    observed_flows=count,
                    last_observed=datetime.now()
                )

    def _detect_failure_patterns(self):
        """Detect failure propagation patterns"""
        # Look for temporal correlation in failures
        # If service A fails, then service B fails shortly after
        # -> B likely depends on A

        recent_failures = [f for f in self.failures
                          if (datetime.now() - f.timestamp).seconds < 300]  # 5 min window

        # Group failures by time windows (10 second buckets)
        time_buckets = defaultdict(list)
        for failure in recent_failures:
            bucket = int(failure.timestamp.timestamp() / 10)
            time_buckets[bucket].append(failure)

        # Detect cascading patterns
        for bucket, failures_in_bucket in time_buckets.items():
            if len(failures_in_bucket) > 1:
                # Multiple failures in same window - potential cascade
                for failure in failures_in_bucket[1:]:
                    # Mark as potentially cascaded
                    first_failure = failures_in_bucket[0]
                    if failure.port not in first_failure.cascaded_to:
                        first_failure.cascaded_to.append(failure.port)

    def _analyze_performance_correlation(self):
        """Analyze performance correlations between services"""
        # If service A slows down, does service B slow down?
        # This suggests B depends on A

        for (source, target), dep in self.dependencies.items():
            if source in self.response_times and target in self.response_times:
                source_times = self.response_times[source][-20:]
                target_times = self.response_times[target][-20:]

                if len(source_times) >= 10 and len(target_times) >= 10:
                    # Calculate correlation (simple version)
                    correlation = self._calculate_correlation(source_times, target_times)

                    # High correlation suggests dependency
                    if correlation > 0.7:
                        dep.confidence = min(1.0, dep.confidence + 0.1)

    def _calculate_correlation(self, x: List[float], y: List[float]) -> float:
        """Simple Pearson correlation"""
        if len(x) != len(y) or len(x) == 0:
            return 0.0

        mean_x = sum(x) / len(x)
        mean_y = sum(y) / len(y)

        numerator = sum((xi - mean_x) * (yi - mean_y) for xi, yi in zip(x, y))
        denominator = (sum((xi - mean_x) ** 2 for xi in x) ** 0.5 *
                      sum((yi - mean_y) ** 2 for yi in y) ** 0.5)

        if denominator == 0:
            return 0.0

        return numerator / denominator

    def _cleanup_history(self):
        """Remove old data to prevent memory growth"""
        # Keep only recent flows
        if len(self.flows) > self.flow_history_limit:
            self.flows = self.flows[-self.flow_history_limit:]

        # Keep only recent failures
        if len(self.failures) > self.failure_history_limit:
            self.failures = self.failures[-self.failure_history_limit:]

        # Clean old dependencies (not seen in 10 minutes)
        cutoff = datetime.now() - timedelta(minutes=10)
        old_deps = [k for k, v in self.dependencies.items() if v.last_observed < cutoff]
        for key in old_deps:
            del self.dependencies[key]

    def record_failure(self, port: int, error_type: str, duration_s: float):
        """Record a service failure"""
        failure = FailureEvent(
            port=port,
            timestamp=datetime.now(),
            error_type=error_type,
            duration_s=duration_s
        )
        self.failures.append(failure)

    def record_response_time(self, port: int, response_time_ms: float):
        """Record service response time"""
        times = self.response_times[port]
        times.append(response_time_ms)

        # Keep only recent samples
        if len(times) > self.response_time_limit:
            self.response_times[port] = times[-self.response_time_limit:]

    def get_dependencies(self, port: int) -> List[ServiceDependency]:
        """Get services that depend on this port"""
        return [dep for key, dep in self.dependencies.items() if key[1] == port]

    def get_dependents(self, port: int) -> List[ServiceDependency]:
        """Get services this port depends on"""
        return [dep for key, dep in self.dependencies.items() if key[0] == port]

    def would_impact_cascade(self, port: int, threshold: float = 0.7) -> bool:
        """Check if failure would likely cascade"""
        deps = self.get_dependencies(port)
        strong_deps = [d for d in deps
                      if d.confidence >= threshold and d.dependency_type == DependencyType.STRONG]
        return len(strong_deps) > 2

    def get_critical_paths(self) -> List[List[int]]:
        """Find critical dependency paths"""
        paths = []

        # Build graph
        graph = defaultdict(list)
        for (source, target), dep in self.dependencies.items():
            if dep.confidence >= 0.7:
                graph[source].append(target)

        # Find longest paths (simple DFS)
        def dfs(node, path):
            if node not in graph or not graph[node]:
                if len(path) > 2:  # Only keep meaningful paths
                    paths.append(path.copy())
                return

            for neighbor in graph[node]:
                if neighbor not in path:  # Avoid cycles
                    path.append(neighbor)
                    dfs(neighbor, path)
                    path.pop()

        # Start DFS from each node
        for source in graph:
            dfs(source, [source])

        # Sort by length
        return sorted(paths, key=len, reverse=True)[:10]

    def get_analysis_summary(self) -> Dict:
        """Get summary of behavioral analysis"""
        strong_deps = sum(1 for d in self.dependencies.values()
                         if d.dependency_type == DependencyType.STRONG)
        weak_deps = sum(1 for d in self.dependencies.values()
                       if d.dependency_type == DependencyType.WEAK)

        recent_failures = [f for f in self.failures
                          if (datetime.now() - f.timestamp).seconds < 300]

        return {
            'total_flows_observed': len(self.flows),
            'dependencies': {
                'total': len(self.dependencies),
                'strong': strong_deps,
                'weak': weak_deps
            },
            'failures': {
                'total': len(self.failures),
                'recent_5min': len(recent_failures)
            },
            'critical_paths': len(self.get_critical_paths()),
            'observations': self.observation_count,
            'last_observation': self.last_observation.isoformat() if self.last_observation else None
        }
