"""
System State Management
=======================
Multi-layer adaptive system awareness framework.

Layers:
1. AgentState - Cognitive state (tasks, goals, metrics) [existing]
2. Active Discovery - Generic service discovery through probing
3. Behavioral Analysis - Dependency inference from observation
4. EnvironmentState - Unified system awareness (services, resources, capabilities)
5. InfrastructureTopology - Structural model (dependencies, critical paths)

Research Foundation:
- Active Discovery: Network topology discovery (Katz et al.)
- Behavioral Analysis: Causality in distributed systems (Lamport)
- Infrastructure Topology: Graph theory and critical path analysis
"""

from .active_discovery import (
    ActiveDiscovery,
    DiscoveredService,
    ServiceProtocol
)

from .behavioral_analysis import (
    BehavioralAnalysis,
    NetworkFlow,
    ServiceDependency,
    DependencyType,
    FailureEvent
)

from .environment_state import (
    EnvironmentState,
    ServiceStatus,
    ServiceInfo,
    ResourceMetrics,
    HealthStatus
)

from .infrastructure_topology import (
    InfrastructureTopology,
    ServiceNode,
    ServiceTier
)

__all__ = [
    # Active Discovery
    'ActiveDiscovery',
    'DiscoveredService',
    'ServiceProtocol',
    # Behavioral Analysis
    'BehavioralAnalysis',
    'NetworkFlow',
    'ServiceDependency',
    'DependencyType',
    'FailureEvent',
    # Environment State
    'EnvironmentState',
    'ServiceStatus',
    'ServiceInfo',
    'ResourceMetrics',
    'HealthStatus',
    # Infrastructure Topology
    'InfrastructureTopology',
    'ServiceNode',
    'ServiceTier'
]
