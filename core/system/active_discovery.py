#!/usr/bin/env python3
"""
Active Discovery Layer
======================
Generic, adaptive service discovery through active probing.

Methods:
- Port scanning (dynamic range detection)
- Service fingerprinting (HTTP, protocol detection)
- Health endpoint probing (adaptive)
- Response profiling

Cross-platform: Windows, Linux, macOS

Author: Dominion Labs
Research: Based on network topology discovery (Katz et al.)
"""

import asyncio
import socket
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Set, Optional, List, Tuple
from enum import Enum

try:
    import httpx
except ImportError:
    httpx = None

logger = logging.getLogger(__name__)


class ObservationStatus(Enum):
    """What THIS scan actually established about a port.

    Distinct from the fingerprint itself: a port can be open now while the
    fingerprint that named it came from a previous scan. Conflating those lets
    yesterday's identity masquerade as today's observation.
    """
    OBSERVED_IDENTIFIED = "observed_identified"      # open now, fingerprinted now
    OBSERVED_UNIDENTIFIED = "observed_unidentified"  # open now, fingerprint FAILED now
    NOT_OBSERVED = "not_observed"                    # scanned, not open


class ServiceProtocol(Enum):
    """Detected service protocol"""
    HTTP = "http"
    HTTPS = "https"
    DATABASE = "database"
    REDIS = "redis"
    UNKNOWN = "unknown"


@dataclass
class DiscoveredService:
    """A dynamically discovered service"""
    port: int
    protocol: ServiceProtocol
    name: Optional[str] = None  # Inferred from fingerprinting
    health_endpoint: Optional[str] = None
    response_time_ms: Optional[float] = None
    server_header: Optional[str] = None
    is_healthy: bool = False
    last_seen: datetime = field(default_factory=datetime.now)
    fingerprint: Dict = field(default_factory=dict)

    observation_status: 'ObservationStatus' = ObservationStatus.OBSERVED_IDENTIFIED
    last_fingerprinted: Optional[datetime] = None
    # Identity from an EARLIER successful scan, kept as history only. It must
    # never be read as current identity — that is the whole point of the split.
    previous_identity: Optional[str] = None


class ActiveDiscovery:
    """
    Active Discovery Layer

    Discovers services through:
    1. Port scanning - Find what's listening
    2. Protocol detection - Identify service type
    3. Fingerprinting - Extract service info
    4. Health probing - Test common endpoints

    Pure discovery - no hardcoded knowledge.
    Adapts to any environment.

    Usage:
        discovery = ActiveDiscovery()
        services = await discovery.scan()
        # Returns: {8080: DiscoveredService(...), ...}
    """

    def __init__(self, port_range: Tuple[int, int] = (1, 65535)):
        """
        Initialize Active Discovery

        Args:
            port_range: Port range to scan (start, end)
        """
        # Discovered services
        self.services: Dict[int, DiscoveredService] = {}

        # Configuration
        self.port_range = port_range
        self.common_ports = self._get_common_ports()
        self.health_endpoints = [
            '/health', '/healthz', '/status', '/api/health',
            '/ping', '/_health', '/actuator/health'
        ]

        # Statistics
        self.scan_history: List[datetime] = []
        self.total_scans = 0
        self._last_quick = True   # what the most recent scan actually covered

    def _get_common_ports(self) -> Set[int]:
        """Get common service ports for faster scanning"""
        return {
            # Web services
            80, 443, 8000, 8080, 8443, 8888, 3000, 3001, 5000,
            # Databases. 5433 is TorinAI's own PostgreSQL instance; without it
            # discovery scanned the shared 5432 and reported not finding the
            # database this system actually runs on.
            3306, 5432, 5433, 6379, 27017, 9200, 9300,
            # Application servers
            8081, 8082, 8083, 8084, 8085, 8086, 8087, 8088, 8089,
            8090, 8100, 8101, 8102, 8103, 8104, 8105, 8106, 8107,
            8200, 8201, 8202, 8300, 8400, 8401, 8500,
            # Monitoring
            9090, 9091, 9100, 3000, 16686,
            # API services
            9001, 9002, 9003, 9080,
        }

    async def scan(self, quick: bool = True) -> Dict[int, DiscoveredService]:
        """
        Scan for services

        Args:
            quick: If True, only scan common ports. If False, full range.

        Returns:
            Dict mapping port to DiscoveredService
        """
        self.total_scans += 1
        self._last_quick = quick
        self.scan_history.append(datetime.now())

        # Determine ports to scan
        if quick:
            ports_to_scan = self.common_ports
        else:
            ports_to_scan = range(self.port_range[0], self.port_range[1] + 1)

        # Scan ports in parallel (batched for performance)
        open_ports = await self._scan_ports(ports_to_scan)

        # Fingerprint each open port. PER-PORT failure boundary: one service that
        # disconnects rudely (httpx.RemoteProtocolError from a non-HTTP listener
        # on an HTTP probe) used to abort the ENTIRE scan, leaving self.services
        # empty. That made Torin's self-knowledge silently absent — and the
        # security audit, which asks "is this port mine?", then classified its own
        # services as unidentified public listeners. A scan that learns about 45
        # of 49 ports is vastly better than one that learns nothing.
        failed_ports = []
        for port in open_ports:
            try:
                svc = await self._fingerprint_service(port)
                svc.observation_status = ObservationStatus.OBSERVED_IDENTIFIED
                svc.last_fingerprinted = datetime.now()
                self.services[port] = svc
            except Exception as e:
                failed_ports.append(port)
                # DO NOT leave the previous fingerprint in place. The port is
                # open but we could not identify it THIS scan; retaining the old
                # DiscoveredService would let consumers read a stale identity as
                # current while the log says "unidentified" — the observation
                # authority contradicting itself.
                prior = self.services.get(port)
                self.services[port] = DiscoveredService(
                    port=port,
                    protocol=ServiceProtocol.UNKNOWN,
                    observation_status=ObservationStatus.OBSERVED_UNIDENTIFIED,
                    last_fingerprinted=(prior.last_fingerprinted if prior else None),
                    previous_identity=(prior.name if prior else None),
                )
                logger.debug("Fingerprint failed for port %s (%s: %s) — marked "
                             "OBSERVED_UNIDENTIFIED", port, type(e).__name__, e)

        if failed_ports:
            logger.warning(
                "Active discovery: %d/%d port(s) could not be fingerprinted: %s. "
                "They are OPEN but unidentified — absence from the service "
                "inventory does NOT mean absence from the host.",
                len(failed_ports), len(open_ports), sorted(failed_ports)
            )

        # Remove ports that are no longer open. A port we merely failed to
        # fingerprint is still open, so it must not be forgotten here.
        closed_ports = set(self.services.keys()) - open_ports
        for port in closed_ports:
            del self.services[port]

        logger.info(
            f"Active discovery: {len(self.services)} services found"
            + (f" ({len(failed_ports)} unidentified)" if failed_ports else "")
        )
        return self.services

    async def _scan_ports(self, ports: Set[int], batch_size: int = 100) -> Set[int]:
        """
        Scan ports for listeners

        Args:
            ports: Ports to scan
            batch_size: Parallel scan batch size

        Returns:
            Set of open ports
        """
        open_ports = set()
        ports_list = list(ports)

        # Scan in batches to avoid overwhelming the system
        for i in range(0, len(ports_list), batch_size):
            batch = ports_list[i:i + batch_size]
            results = await asyncio.gather(
                *[self._check_port(port) for port in batch],
                return_exceptions=True
            )

            for port, is_open in zip(batch, results):
                if isinstance(is_open, bool) and is_open:
                    open_ports.add(port)

        return open_ports

    async def _check_port(self, port: int, host: str = 'localhost', timeout: float = 0.5) -> bool:
        """Check if a port is open"""
        try:
            _, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port),
                timeout=timeout
            )
            writer.close()
            await writer.wait_closed()
            return True
        except (asyncio.TimeoutError, ConnectionRefusedError, OSError):
            return False

    async def _fingerprint_service(self, port: int) -> DiscoveredService:
        """
        Fingerprint a service on a port

        Attempts:
        1. HTTP probe
        2. Protocol detection
        3. Health endpoint discovery
        """
        service = DiscoveredService(
            port=port,
            protocol=ServiceProtocol.UNKNOWN
        )

        # Try HTTP/HTTPS
        http_result = await self._probe_http(port)
        if http_result:
            service.protocol = ServiceProtocol.HTTP
            service.server_header = http_result.get('server')
            service.name = http_result.get('inferred_name')
            service.health_endpoint = http_result.get('health_endpoint')
            service.response_time_ms = http_result.get('response_time_ms')
            service.is_healthy = http_result.get('is_healthy', False)
            service.fingerprint = http_result

        # Try database protocols
        elif await self._probe_database(port):
            service.protocol = ServiceProtocol.DATABASE
            service.name = self._infer_database_type(port)

        return service

    async def _probe_http(self, port: int) -> Optional[Dict]:
        """Probe HTTP service"""
        if not httpx:
            return None

        url = f"http://localhost:{port}"

        try:
            start = datetime.now()
            async with httpx.AsyncClient(timeout=2.0) as client:
                # Try root endpoint
                try:
                    resp = await client.get(url)
                    response_time = (datetime.now() - start).total_seconds() * 1000

                    result = {
                        'server': resp.headers.get('server'),
                        'response_time_ms': response_time,
                        'status_code': resp.status_code,
                        'is_healthy': resp.status_code < 500
                    }

                    # Try to infer service name from headers or content
                    result['inferred_name'] = self._infer_name_from_http(resp)

                    # Try health endpoints
                    health_endpoint = await self._find_health_endpoint(port, client)
                    if health_endpoint:
                        result['health_endpoint'] = health_endpoint
                        result['is_healthy'] = True

                    return result

                except httpx.HTTPStatusError:
                    # Service responded but with error - still HTTP
                    return {
                        'server': None,
                        'response_time_ms': None,
                        'is_healthy': False
                    }

        except (httpx.ConnectError, httpx.TimeoutException):
            return None

    async def _find_health_endpoint(self, port: int, client: httpx.AsyncClient) -> Optional[str]:
        """Try common health endpoints"""
        for endpoint in self.health_endpoints:
            try:
                url = f"http://localhost:{port}{endpoint}"
                resp = await client.get(url, timeout=1.0)
                if resp.status_code == 200:
                    return endpoint
            except:
                continue
        return None

    def _infer_name_from_http(self, resp: 'httpx.Response') -> Optional[str]:
        """Infer service name from HTTP response"""
        # Check Server header
        server = resp.headers.get('server', '').lower()
        if 'uvicorn' in server or 'fastapi' in server:
            return 'fastapi-service'
        elif 'nginx' in server:
            return 'nginx'
        elif 'apache' in server:
            return 'apache'

        # Check X-Powered-By
        powered_by = resp.headers.get('x-powered-by', '').lower()
        if 'express' in powered_by:
            return 'express'
        elif 'next.js' in powered_by:
            return 'nextjs'

        # Check for common patterns in response
        try:
            text = resp.text[:500].lower()
            if 'prometheus' in text:
                return 'prometheus'
            elif 'grafana' in text:
                return 'grafana'
        except:
            pass

        return None

    async def _probe_database(self, port: int) -> bool:
        """Check if port is a database"""
        # Try connecting with socket to see if it's a database protocol
        # Database ports typically send a greeting on connect
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection('localhost', port),
                timeout=1.0
            )

            # Read initial bytes (database greeting)
            try:
                data = await asyncio.wait_for(reader.read(100), timeout=0.5)
                writer.close()
                await writer.wait_closed()
                return len(data) > 0  # Databases typically send greeting
            except asyncio.TimeoutException:
                writer.close()
                await writer.wait_closed()
                return False

        except (ConnectionRefusedError, OSError):
            return False

    def _infer_database_type(self, port: int) -> str:
        """Infer database type from port"""
        db_ports = {
            3306: 'mysql',
            5432: 'postgresql',
            5433: 'postgresql',
            6379: 'redis',
            27017: 'mongodb',
            9200: 'elasticsearch',
        }
        return db_ports.get(port, 'database')

    def get_service_summary(self) -> Dict:
        """Get summary of discovered services"""
        protocol_counts = {}
        for service in self.services.values():
            proto = service.protocol.value
            protocol_counts[proto] = protocol_counts.get(proto, 0) + 1

        healthy_count = sum(1 for s in self.services.values() if s.is_healthy)

        identified = sorted(
            p for p, sv in self.services.items()
            if sv.observation_status == ObservationStatus.OBSERVED_IDENTIFIED
        )
        unidentified = sorted(
            p for p, sv in self.services.items()
            if sv.observation_status == ObservationStatus.OBSERVED_UNIDENTIFIED
        )
        return {
            'total_services': len(self.services),
            'healthy_services': healthy_count,
            'by_protocol': protocol_counts,
            # 'ports' = every port OBSERVED OPEN, identified or not. Consumers
            # deciding anything about ownership must use 'identified_ports':
            # an open port we failed to fingerprint is the LEAST safe thing to
            # assume is ours.
            'ports': sorted(self.services.keys()),
            'identified_ports': identified,
            'unidentified_ports': unidentified,
            'scan_coverage': self.get_coverage(),
            'total_scans': self.total_scans
        }

    def get_coverage(self) -> Dict:
        """What this inventory actually measured.

        quick=True probes a fixed common-port set, so absence from the inventory
        means NOT OBSERVED IN THE PROBED SET — never NOT PRESENT ON HOST. A
        consumer asking "is port 12345 mine?" about a port that was never scanned
        must get UNMEASURED, not False.
        """
        return {
            'ports_scanned': sorted(self.common_ports) if self._last_quick else 'full_range',
            'scan_mode': 'quick' if self._last_quick else 'full',
            'scanned_count': len(self.common_ports) if self._last_quick else (
                self.port_range[1] - self.port_range[0] + 1),
            'has_scanned': self.total_scans > 0,
        }

    def observation_for(self, port: int) -> str:
        """Three-valued answer about a port. Never a bare bool.

        KNOWN_SERVICE          identified this scan
        KNOWN_OPEN_UNIDENTIFIED  open, fingerprint failed
        KNOWN_CLOSED           scanned, not open
        UNMEASURED             never probed — the honest answer for anything
                               outside the quick-mode port set
        """
        if self.total_scans == 0:
            return 'UNMEASURED'
        sv = self.services.get(port)
        if sv is not None:
            return ('KNOWN_SERVICE'
                    if sv.observation_status == ObservationStatus.OBSERVED_IDENTIFIED
                    else 'KNOWN_OPEN_UNIDENTIFIED')
        scanned = self.common_ports if self._last_quick else range(
            self.port_range[0], self.port_range[1] + 1)
        return 'KNOWN_CLOSED' if port in scanned else 'UNMEASURED'


# Module-level singleton. Without an accessor, the only ActiveDiscovery instance
# lived on the coordinator, so peers that needed Torin's self-knowledge (e.g. the
# security audit deciding whether a listening port is OUR OWN service) had no way
# to reach it and re-derived the answer — or, in the audit's case, could not, and
# reported its own services as unidentified public listeners.
_active_discovery: Optional['ActiveDiscovery'] = None


def get_active_discovery() -> 'ActiveDiscovery':
    """Shared ActiveDiscovery — one authority for what is OBSERVED on this host.

    NOT an authority on ownership. This layer establishes port/protocol/header/
    health only; it knows nothing about PID, executable, binary hash, process
    owner, launch ancestry, deployment manifest membership or trust domain.
    "Observed on localhost" must never be read as "mine" — an IdentityResolver
    consuming process provenance and a signed deployment manifest is what can
    answer SELF / SIBLING / EXTERNAL / UNKNOWN.
    """
    global _active_discovery
    if _active_discovery is None:
        _active_discovery = ActiveDiscovery()
    return _active_discovery


def register_active_discovery(instance: 'ActiveDiscovery') -> None:
    """Publish an already-built instance (the coordinator owns the live one)."""
    global _active_discovery
    _active_discovery = instance
