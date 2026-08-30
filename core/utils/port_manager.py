#!/usr/bin/env python3
"""
Port Manager
============
Manage port allocations for services
"""

import asyncio
import logging
import socket
from typing import Dict, Any, List, Optional, Tuple
from pathlib import Path
import json

logger = logging.getLogger(__name__)


class PortManager:
    """
    Port Manager

    Purpose:
    - Allocate ports for services
    - Track port usage
    - Avoid port conflicts
    """

    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}
        self.config_file = Path(self.config.get("config_file", "data/ports.json"))
        self.ports: Dict[str, int] = {}
        self.allocated_ports: List[int] = []
        self.lock = asyncio.Lock()

        # Default port ranges for services
        self.default_ports = {
            'database': (3306, 3316),      # MySQL
            'backend': (8000, 8010),       # Backend API
            'frontend': (3000, 3010),      # Frontend
            'websocket': (8080, 8090),     # WebSocket
            'monitoring': (9090, 9100)     # Monitoring services
        }

        # Load existing port assignments
        self._load_ports()

    def _load_ports(self):
        """Load port assignments from config"""
        try:
            if self.config_file.exists():
                with open(self.config_file, 'r') as f:
                    data = json.load(f)
                    self.ports = data.get('ports', {})
                    self.allocated_ports = list(self.ports.values())
                logger.info(f"Loaded {len(self.ports)} port assignments")
        except Exception as e:
            logger.error(f"Failed to load ports: {e}")
            self.ports = {}
            self.allocated_ports = []

    def _save_ports(self):
        """Save port assignments to config"""
        try:
            data = {
                'ports': self.ports,
                'allocated': self.allocated_ports
            }
            self.config_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.config_file, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save ports: {e}")

    def get_port(self, service: str) -> Optional[int]:
        """Get assigned port for a service"""
        return self.ports.get(service)

    def allocate_port(
        self,
        service: str,
        preferred_port: int = None,
        port_range: Tuple[int, int] = None
    ) -> Optional[int]:
        """
        Allocate a port for a service

        Args:
            service: Service name
            preferred_port: Preferred port number
            port_range: Range of ports to try (min, max)

        Returns:
            Allocated port or None if failed
        """
        try:
            # Return existing port if already allocated
            if service in self.ports:
                return self.ports[service]

            # Try preferred port first
            if preferred_port and self._is_port_available(preferred_port):
                self.ports[service] = preferred_port
                self.allocated_ports.append(preferred_port)
                self._save_ports()
                logger.info(f"Allocated port {preferred_port} to {service}")
                return preferred_port

            # Determine port range
            if not port_range:
                port_range = self.default_ports.get(service, (8000, 9000))

            # Find available port in range
            for port in range(port_range[0], port_range[1]):
                if self._is_port_available(port) and port not in self.allocated_ports:
                    self.ports[service] = port
                    self.allocated_ports.append(port)
                    self._save_ports()
                    logger.info(f"Allocated port {port} to {service}")
                    return port

            logger.error(f"No available ports for {service}")
            return None

        except Exception as e:
            logger.error(f"Failed to allocate port for {service}: {e}")
            return None

    def _is_port_available(self, port: int) -> bool:
        """Check if a port is available"""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(('', port))
                return True
        except OSError:
            return False

    def release_port(self, service: str) -> bool:
        """Release a port allocation"""
        try:
            if service in self.ports:
                port = self.ports[service]
                del self.ports[service]
                if port in self.allocated_ports:
                    self.allocated_ports.remove(port)
                self._save_ports()
                logger.info(f"Released port {port} from {service}")
                return True
            return False
        except Exception as e:
            logger.error(f"Failed to release port for {service}: {e}")
            return False

    def get_all_ports(self) -> Dict[str, int]:
        """Get all port assignments"""
        return self.ports.copy()

    def is_port_allocated(self, port: int) -> bool:
        """Check if a port is allocated"""
        return port in self.allocated_ports

    def find_available_port(
        self,
        start_port: int = 8000,
        end_port: int = 9000
    ) -> Optional[int]:
        """Find an available port in range"""
        for port in range(start_port, end_port):
            if self._is_port_available(port) and port not in self.allocated_ports:
                return port
        return None

    def get_service_for_port(self, port: int) -> Optional[str]:
        """Get service name for a port"""
        for service, service_port in self.ports.items():
            if service_port == port:
                return service
        return None

    def clear_all_ports(self):
        """Clear all port allocations"""
        logger.warning("Clearing all port allocations")
        self.ports.clear()
        self.allocated_ports.clear()
        self._save_ports()


# Singleton instance
_port_manager = None


def get_port_manager() -> PortManager:
    """Get global port manager instance"""
    global _port_manager
    if _port_manager is None:
        _port_manager = PortManager()
    return _port_manager


# CLI test
def main():
    """Test port manager"""
    logging.basicConfig(level=logging.INFO)

    manager = get_port_manager()

    print("\n=== Port Manager Test ===")

    # Allocate ports
    db_port = manager.allocate_port("database", preferred_port=3306)
    print(f"Database port: {db_port}")

    backend_port = manager.allocate_port("backend")
    print(f"Backend port: {backend_port}")

    # Get all ports
    all_ports = manager.get_all_ports()
    print(f"All ports: {all_ports}")

    # Find available port
    available = manager.find_available_port(8000, 8100)
    print(f"Available port: {available}")


if __name__ == "__main__":
    main()
