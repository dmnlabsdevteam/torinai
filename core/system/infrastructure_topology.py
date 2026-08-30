#!/usr/bin/env python3
"""
Infrastructure Topology
=======================
Structural model of Dominion Labs infrastructure.

Models:
- Service dependency graph
- Critical path analysis
- Cascading failure detection
- Single points of failure

Author: Dominion Labs
"""

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Set, Optional
from enum import Enum

logger = logging.getLogger(__name__)


class ServiceTier(Enum):
    """Service criticality tier"""
    CRITICAL = "critical"      # Core infrastructure (API Gateway, MySQL)
    IMPORTANT = "important"    # Business services (Auth, Email, AgentSO)
    OPTIONAL = "optional"      # Nice-to-have (Grafana, monitoring)


@dataclass
class ServiceNode:
    """Node in the infrastructure graph"""
    name: str
    tier: ServiceTier
    port: int
    depends_on: List[str] = field(default_factory=list)  # Service dependencies
    health_score: float = 1.0  # 0.0 (dead) to 1.0 (healthy)
    is_running: bool = False
    dependents: List[str] = field(default_factory=list)  # Services that depend on this


class InfrastructureTopology:
    """
    Infrastructure Topology Model

    Models the structural relationships between Dominion Labs services.
    Enables:
    - Dependency analysis
    - Critical path identification
    - Cascading failure detection
    - Impact assessment

    Usage:
        topo = InfrastructureTopology()
        topo.update_from_environment(env_state)

        critical_services = topo.get_critical_services()
        if topo.would_cascade_fail('mysql'):
            # MySQL failure would cascade to 15 services!

        impact = topo.assess_failure_impact('api-gateway')
    """

    def __init__(self):
        self.services: Dict[str, ServiceNode] = {}
        self.dependencies: Dict[str, List[str]] = {}  # service -> depends_on
        self.health_graph: Dict[str, float] = {}      # service -> health score

        self._build_topology()

    def _build_topology(self):
        """Build the Dominion Labs service topology"""

        # === CRITICAL TIER ===
        # API Gateway - central routing hub
        self.add_service('api-gateway', ServiceTier.CRITICAL, 8080, depends_on=[])

        # PostgreSQL - TorinAI unified database (memory + system data)
        # INVERTED HERE UNTIL NOW: this declared TorinAI's critical database
        # on 5432 and agentso's on 5433, which is backwards. Everything that
        # reasons about dependencies or health from this topology was
        # pointing at the wrong instance.
        self.add_service('postgresql-torinai', ServiceTier.CRITICAL, 5433, depends_on=[])

        # TorinAI - system operator
        self.add_service('torinai-chat', ServiceTier.CRITICAL, 9080, depends_on=['postgresql-torinai'])
        self.add_service('torinai-api', ServiceTier.CRITICAL, 9001, depends_on=['postgresql-torinai'])

        # === IMPORTANT TIER ===
        # Core services depend on PostgreSQL and route through API Gateway
        self.add_service('employee-auth', ServiceTier.IMPORTANT, 8101, depends_on=['postgresql-torinai'])
        self.add_service('employee-email', ServiceTier.IMPORTANT, 8102, depends_on=['postgresql-torinai'])
        self.add_service('email-webhook', ServiceTier.IMPORTANT, 8103, depends_on=['postgresql-torinai'])
        self.add_service('email-realtime', ServiceTier.IMPORTANT, 8104, depends_on=['postgresql-torinai', 'redis'])
        self.add_service('smtp-sender', ServiceTier.IMPORTANT, 8105, depends_on=[])
        self.add_service('user-settings', ServiceTier.IMPORTANT, 8106, depends_on=['postgresql-torinai'])

        # AgentSO - SOC platform (uses separate PostgreSQL instance)
        self.add_service('postgresql-agentso', ServiceTier.IMPORTANT, 5432, depends_on=[])
        self.add_service('agentso', ServiceTier.IMPORTANT, 8107, depends_on=['postgresql-agentso'])
        self.add_service('agentso-web', ServiceTier.IMPORTANT, 3010, depends_on=['agentso'])

        # Cloud services
        self.add_service('cloud-storage', ServiceTier.IMPORTANT, 8401, depends_on=['postgresql-torinai'])
        self.add_service('payment-service', ServiceTier.IMPORTANT, 8500, depends_on=['postgresql-torinai'])

        # Redis - caching layer
        self.add_service('redis', ServiceTier.IMPORTANT, 6379, depends_on=[])

        # === OPTIONAL TIER ===
        # AI services

        # Monitoring stack
        self.add_service('prometheus', ServiceTier.OPTIONAL, 9090, depends_on=[])
        self.add_service('grafana', ServiceTier.OPTIONAL, 3000, depends_on=['prometheus'])

        # Build reverse dependencies (who depends on me?)
        for service_name, node in self.services.items():
            for dep in node.depends_on:
                if dep in self.services:
                    self.services[dep].dependents.append(service_name)

    def add_service(self, name: str, tier: ServiceTier, port: int, depends_on: List[str]):
        """Add a service node to the topology"""
        self.services[name] = ServiceNode(
            name=name,
            tier=tier,
            port=port,
            depends_on=depends_on,
            dependents=[]
        )
        self.dependencies[name] = depends_on
        self.health_graph[name] = 0.0  # Assume down until proven up

    def update_from_environment(self, env_state):
        """Update topology health from environment state.

        MATCHED BY PORT, NOT BY NAME. The two sides name the same services
        differently: the scanner reports one `postgresql`, while this topology
        models the two logical databases sharing that instance as
        `postgresql-torinai` and `postgresql-agentso`. Neither name could ever
        match, so a running Postgres was recorded as a CRITICAL service down --
        and the health check reported it as such while every database check in
        the system was passing against it.

        The port is the identity both sides actually observe: the scanner finds
        services by opening them, and every node here declares the one it lives
        on. Names remain the fallback for anything the scanner reports without a
        usable port.
        """
        from .environment_state import ServiceStatus

        by_port = {
            info.port: info
            for info in env_state.running_services.values()
            if getattr(info, 'port', None)
        }

        for service_name, node in self.services.items():
            service_info = (by_port.get(node.port)
                            or env_state.running_services.get(service_name))
            if service_info is not None:
                node.is_running = True

                # Calculate health score
                if service_info.status == ServiceStatus.RUNNING:
                    # Factor in response time if available
                    if service_info.response_time_ms:
                        if service_info.response_time_ms < 100:
                            node.health_score = 1.0
                        elif service_info.response_time_ms < 500:
                            node.health_score = 0.8
                        elif service_info.response_time_ms < 1000:
                            node.health_score = 0.6
                        else:
                            node.health_score = 0.4
                    else:
                        node.health_score = 1.0
                elif service_info.status == ServiceStatus.DEGRADED:
                    node.health_score = 0.3
                else:
                    node.health_score = 0.0
            else:
                node.is_running = False
                node.health_score = 0.0

            self.health_graph[service_name] = node.health_score

    def get_critical_services(self) -> List[str]:
        """Get list of critical tier services"""
        return [name for name, node in self.services.items()
                if node.tier == ServiceTier.CRITICAL]

    def get_dependencies(self, service_name: str) -> List[str]:
        """Get services that this service depends on"""
        if service_name in self.services:
            return self.services[service_name].depends_on
        return []

    def get_dependents(self, service_name: str) -> List[str]:
        """Get services that depend on this service"""
        if service_name in self.services:
            return self.services[service_name].dependents
        return []

    def would_cascade_fail(self, service_name: str) -> bool:
        """Check if service failure would cause cascading failures"""
        affected = self._get_cascade_impact(service_name)
        return len(affected) > 0

    def _get_cascade_impact(self, service_name: str, visited: Optional[Set[str]] = None) -> Set[str]:
        """Recursively find all services affected by this service's failure"""
        if visited is None:
            visited = set()

        if service_name in visited:
            return set()

        visited.add(service_name)
        affected = set()

        # All services that directly depend on this one are affected
        if service_name in self.services:
            for dependent in self.services[service_name].dependents:
                affected.add(dependent)
                # Recursively find their dependents
                cascade = self._get_cascade_impact(dependent, visited)
                affected.update(cascade)

        return affected

    def assess_failure_impact(self, service_name: str) -> Dict:
        """Assess the impact of a service failure"""
        affected_services = self._get_cascade_impact(service_name)

        critical_affected = sum(1 for s in affected_services
                               if self.services[s].tier == ServiceTier.CRITICAL)
        important_affected = sum(1 for s in affected_services
                                if self.services[s].tier == ServiceTier.IMPORTANT)

        return {
            'service': service_name,
            'tier': self.services[service_name].tier.value if service_name in self.services else 'unknown',
            'total_affected': len(affected_services),
            'critical_affected': critical_affected,
            'important_affected': important_affected,
            'affected_services': list(affected_services),
            'is_single_point_of_failure': len(affected_services) > 3
        }

    def find_single_points_of_failure(self) -> List[str]:
        """Find services whose failure would impact many others"""
        spofs = []
        for service_name in self.services:
            impact = self.assess_failure_impact(service_name)
            if impact['is_single_point_of_failure']:
                spofs.append(service_name)
        return spofs

    def get_critical_path(self, service_name: str) -> List[str]:
        """Get the critical path of dependencies for a service"""
        path = []
        visited = set()

        def traverse(name):
            if name in visited:
                return
            visited.add(name)

            if name in self.services:
                deps = self.services[name].depends_on
                for dep in deps:
                    traverse(dep)
                    if dep not in path:
                        path.append(dep)

        traverse(service_name)
        path.append(service_name)
        return path

    def get_health_summary(self) -> Dict:
        """Get overall infrastructure health summary"""
        total = len(self.services)
        running = sum(1 for n in self.services.values() if n.is_running)
        healthy = sum(1 for n in self.services.values() if n.health_score > 0.8)
        degraded = sum(1 for n in self.services.values() if 0.3 < n.health_score <= 0.8)
        down = sum(1 for n in self.services.values() if n.health_score <= 0.3)

        critical_down = sum(1 for n in self.services.values()
                           if n.tier == ServiceTier.CRITICAL and not n.is_running)

        return {
            'total_services': total,
            'running': running,
            'healthy': healthy,
            'degraded': degraded,
            'down': down,
            'critical_services_down': critical_down,
            'avg_health_score': sum(self.health_graph.values()) / total if total > 0 else 0.0,
            'single_points_of_failure': self.find_single_points_of_failure()
        }
