#!/usr/bin/env python3
"""
Environment State
=================
Real-time system environment awareness for TorinAI.

Tracks:
- Running services and health
- Network ports and connections
- System resources (CPU, memory, disk)
- Tool availability based on system state
- Overall health status

Author: Dominion Labs
"""

import logging
import psutil
import socket
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, Set, Optional, List
from pathlib import Path

try:
    import httpx
except ImportError:
    httpx = None

logger = logging.getLogger(__name__)


class ServiceStatus(Enum):
    """Service health status"""
    RUNNING = "running"
    DEGRADED = "degraded"
    DOWN = "down"
    UNKNOWN = "unknown"


class HealthStatus(Enum):
    """Overall system health"""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    CRITICAL = "critical"
    UNKNOWN = "unknown"


@dataclass
class ServiceInfo:
    """Information about a running service"""
    name: str
    port: int
    status: ServiceStatus
    health_endpoint: Optional[str] = None
    last_check: Optional[datetime] = None
    response_time_ms: Optional[float] = None
    error: Optional[str] = None


@dataclass
class ResourceMetrics:
    """System resource metrics"""
    cpu_percent: float
    memory_percent: float
    disk_percent: float
    load_average: float
    timestamp: datetime


class EnvironmentState:
    """
    System Environment State

    Provides real-time awareness of:
    - What services are running
    - System resource usage
    - Network state
    - Tool/capability availability

    Usage:
        env = EnvironmentState()
        await env.refresh()  # Update all metrics

        if env.is_service_running('agentso', 8107):
            # AgentSO connectors are available

        if env.cpu_percent > 90:
            # Don't spawn parallel tasks
    """

    def __init__(self):
        # Service tracking
        self.running_services: Dict[str, ServiceInfo] = {}

        # Network state
        self.open_ports: Dict[int, str] = {}  # port -> service name
        self.active_connections: int = 0

        # Resource metrics
        self.cpu_percent: float = 0.0
        self.memory_percent: float = 0.0
        self.disk_percent: float = 0.0
        self.load_average: float = 0.0

        # Tool availability (based on running services)
        self.available_capabilities: Set[str] = set()
        self.degraded_capabilities: Set[str] = set()

        # Overall health
        self.overall_health: HealthStatus = HealthStatus.UNKNOWN
        self.last_refresh: Optional[datetime] = None

        # Known Dominion Labs services
        self.known_services = {
            'api-gateway': {'port': 8080, 'health': '/health'},
            'employee-auth': {'port': 8101, 'health': '/health'},
            'employee-email': {'port': 8102, 'health': '/health'},
            'email-webhook': {'port': 8103, 'health': '/health'},
            'email-realtime': {'port': 8104, 'health': '/health'},
            'smtp-sender': {'port': 8105, 'health': '/health'},
            'user-settings': {'port': 8106, 'health': '/health'},
            'agentso': {'port': 8107, 'health': '/health'},
            'agentso-web': {'port': 3010, 'health': None},
            'cloud-storage': {'port': 8401, 'health': '/health'},
            'payment-service': {'port': 8500, 'health': '/health'},
            'torinai-chat': {'port': 9080, 'health': '/health'},
            'torinai-api': {'port': 9001, 'health': '/health'},
            'prometheus': {'port': 9090, 'health': '/-/healthy'},
            'grafana': {'port': 3000, 'health': '/api/health'},
            # TorinAI's instance, not the shared agentso one on 5432.
            'postgresql': {'port': 5433, 'health': None},
            'redis': {'port': 6379, 'health': None},
        }

    async def refresh(self):
        """Refresh all environment metrics"""
        await self._update_resources()
        await self._scan_services()
        await self._update_network_state()
        self._calculate_health()
        self._update_capability_availability()
        self.last_refresh = datetime.now()

    async def _update_resources(self):
        """Update CPU, memory, disk metrics"""
        try:
            self.cpu_percent = psutil.cpu_percent(interval=0.1)
            self.memory_percent = psutil.virtual_memory().percent
            self.disk_percent = psutil.disk_usage('/').percent
            self.load_average = psutil.getloadavg()[0]  # 1-minute load average
        except Exception as e:
            logger.error(f"Error updating resource metrics: {e}")

    async def _scan_services(self):
        """Scan known services for availability and health"""
        for service_name, config in self.known_services.items():
            port = config['port']
            health_endpoint = config.get('health')

            # Check if port is open
            if self._is_port_open(port):
                # Port is open - check health if endpoint available
                if health_endpoint and httpx:
                    status, response_time, error = await self._check_health(port, health_endpoint)
                else:
                    status = ServiceStatus.RUNNING
                    response_time = None
                    error = None

                self.running_services[service_name] = ServiceInfo(
                    name=service_name,
                    port=port,
                    status=status,
                    health_endpoint=health_endpoint,
                    last_check=datetime.now(),
                    response_time_ms=response_time,
                    error=error
                )
                self.open_ports[port] = service_name
            else:
                # Port closed - service not running
                if service_name in self.running_services:
                    del self.running_services[service_name]
                if port in self.open_ports:
                    del self.open_ports[port]

    def _is_port_open(self, port: int, host: str = 'localhost') -> bool:
        """Check if a port is open"""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(0.5)
                result = sock.connect_ex((host, port))
                return result == 0
        except Exception:
            return False

    async def _check_health(self, port: int, endpoint: str) -> tuple:
        """
        Check service health endpoint

        Returns:
            (status, response_time_ms, error)
        """
        if not httpx:
            return ServiceStatus.RUNNING, None, None

        url = f"http://localhost:{port}{endpoint}"
        try:
            start = datetime.now()
            async with httpx.AsyncClient(timeout=2.0) as client:
                resp = await client.get(url)
            response_time = (datetime.now() - start).total_seconds() * 1000

            if resp.status_code == 200:
                return ServiceStatus.RUNNING, response_time, None
            else:
                return ServiceStatus.DEGRADED, response_time, f"HTTP {resp.status_code}"
        except httpx.TimeoutException:
            return ServiceStatus.DEGRADED, None, "Timeout"
        except Exception as e:
            return ServiceStatus.DEGRADED, None, str(e)

    async def _update_network_state(self):
        """Update network connection count"""
        try:
            connections = psutil.net_connections(kind='inet')
            self.active_connections = len([c for c in connections if c.status == 'ESTABLISHED'])
        except psutil.AccessDenied:
            # macOS restricts a system-wide socket enumeration to root. This is
            # a standing privilege limitation, not a per-cycle incident, so it is
            # noted ONCE and the metric falls back to this process's own
            # established connections -- an honest, root-free lower bound rather
            # than a fabricated system-wide figure.
            try:
                own = psutil.Process().net_connections(kind='inet')
                self.active_connections = len(
                    [c for c in own if c.status == 'ESTABLISHED'])
            except Exception:
                self.active_connections = None
            if not getattr(self, '_net_access_denied_logged', False):
                logger.warning(
                    "System-wide network state needs root on macOS; reporting "
                    "this process's own connections only (logged once)")
                self._net_access_denied_logged = True
        except Exception as e:
            logger.error(f"Error updating network state: {e}")

    def _calculate_health(self):
        """Calculate overall system health"""
        # Critical if any critical resources are exhausted
        if self.cpu_percent > 95 or self.memory_percent > 95 or self.disk_percent > 95:
            self.overall_health = HealthStatus.CRITICAL
            return

        # Degraded if resources are high
        if self.cpu_percent > 80 or self.memory_percent > 80 or self.disk_percent > 80:
            self.overall_health = HealthStatus.DEGRADED
            return

        # Check critical services
        critical_services = ['api-gateway', 'torinai-chat', 'postgresql']
        for service in critical_services:
            if service not in self.running_services:
                self.overall_health = HealthStatus.DEGRADED
                return
            if self.running_services[service].status != ServiceStatus.RUNNING:
                self.overall_health = HealthStatus.DEGRADED
                return

        self.overall_health = HealthStatus.HEALTHY

    def _update_capability_availability(self):
        """Update which capabilities are available based on running services"""
        self.available_capabilities.clear()
        self.degraded_capabilities.clear()

        # Base capabilities always available
        self.available_capabilities.update([
            'filesystem', 'execution', 'system', 'monitoring',
            'code_generation', 'ai_ml', 'research'
        ])

        # Database capabilities require PostgreSQL
        if 'postgresql' in self.running_services:
            self.available_capabilities.add('database')
        else:
            self.degraded_capabilities.add('database')

        # Security connector capabilities require AgentSO
        if 'agentso' in self.running_services:
            if self.running_services['agentso'].status == ServiceStatus.RUNNING:
                self.available_capabilities.add('security_connectors')
            else:
                self.degraded_capabilities.add('security_connectors')
        else:
            self.degraded_capabilities.add('security_connectors')

        # Communication capabilities
        if 'api-gateway' in self.running_services:
            self.available_capabilities.add('communication')

        # Network capabilities
        self.available_capabilities.add('network')

    def is_service_running(self, service_name: str, port: Optional[int] = None) -> bool:
        """Check if a service is running"""
        if service_name in self.running_services:
            return self.running_services[service_name].status == ServiceStatus.RUNNING
        if port and port in self.open_ports:
            return True
        return False

    def get_service_status(self, service_name: str) -> Optional[ServiceStatus]:
        """Get status of a specific service"""
        if service_name in self.running_services:
            return self.running_services[service_name].status
        return None

    def can_use_capability(self, capability: str) -> bool:
        """Check if a capability is available"""
        return capability in self.available_capabilities

    def get_state_summary(self) -> Dict:
        """Get summary of environment state"""
        return {
            'health': self.overall_health.value,
            'services': {
                'running': len(self.running_services),
                'degraded': sum(1 for s in self.running_services.values() if s.status == ServiceStatus.DEGRADED)
            },
            'resources': {
                'cpu_percent': self.cpu_percent,
                'memory_percent': self.memory_percent,
                'disk_percent': self.disk_percent,
                'load_average': self.load_average
            },
            'network': {
                'open_ports': len(self.open_ports),
                'active_connections': self.active_connections
            },
            'capabilities': {
                'available': len(self.available_capabilities),
                'degraded': len(self.degraded_capabilities)
            },
            'last_refresh': self.last_refresh.isoformat() if self.last_refresh else None
        }
