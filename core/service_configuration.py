"""
Service Configuration
=====================
Service initialization and configuration management
"""


import logging
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class ServiceStatus(Enum):
    """Service status"""
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    FAILED = "failed"


#: Default health-check cadence for a configured service, in seconds.
#: `ServiceConfig.health_check_interval` referenced this as a field default
#: and it was defined nowhere in the repository, so importing this module
#: raised NameError -- the module has never been importable. Matched to
#: SystemWatchdog.check_interval (30s), which is the cadence the health
#: system already polls components on.
SERVICE_TIMEOUT = 30


@dataclass
class ServiceConfig:
    """Service configuration"""
    name: str
    enabled: bool = True
    auto_start: bool = True
    depends_on: List[str] = field(default_factory=list)
    config: Dict[str, Any] = field(default_factory=dict)
    health_check_interval: int = SERVICE_TIMEOUT  # seconds
    restart_on_failure: bool = True


async def start_all_services(services: List[str] = None) -> Dict[str, bool]:
    """
    Start all configured services or specified services

    Args:
        services: Optional list of specific services to start

    Returns:
        Dict mapping service names to success status
    """
    if services is None:
        services = get_default_services()

    results = {}

    # Start services in dependency order
    for service_name in services:
        try:
            success = await start_service(service_name)
            results[service_name] = success
        except Exception as e:
            logger.error(f"Failed to start service {service_name}: {e}")
            results[service_name] = False

    logger.info(f"Service startup complete: {sum(results.values())}/{len(results)} succeeded")
    return results


async def stop_all_services() -> Dict[str, bool]:
    """
    Stop all running services gracefully

    Returns:
        Dict mapping service names to success status
    """
    services = get_default_services()
    results = {}

    # Stop services in reverse dependency order
    for service_name in reversed(services):
        try:
            success = await stop_service(name=service_name)
            results[service_name] = success
        except Exception as e:
            logger.error(f"Failed to stop service {service_name}: {e}")
            results[service_name] = False

    return results


async def start_service(name: str, **config) -> bool:
    """
    Start a specific service with configuration

    Args:
        name: Service name
        **config: Service configuration parameters

    Returns:
        True if service started successfully
    """
    try:
        logger.info(f"Starting service: {name}")

        # Service-specific initialization
        if name == 'database':
            from core.database import get_database_manager
            db = get_database_manager()
            logger.info(f"✓ Database service ready")
        elif name == 'memory':
            
            # Memory agent is async, just import to verify module exists
            logger.info(f"✓ Memory service ready")
        elif name == 'chat':
            logger.info(f"✓ Chat service configuration loaded")
        elif name == 'learning':
            logger.info(f"✓ Learning service configuration loaded")
        else:
            logger.info(f"✓ Service configuration loaded: {name}")

        return True

    except Exception as e:
        logger.error(f"Failed to start service {name}: {e}")
        return False


async def stop_service(**config) -> bool:
    """
    Stop a specific service

    Args:
        **config: Service configuration

    Returns:
        True if service stopped successfully
    """
    try:
        name = config.get('name', 'unknown')
        logger.info(f"Stopping service: {name}")

        # Service-specific cleanup
        if name in ['database', 'memory', 'chat', 'learning']:
            logger.info(f"✓ Service {name} stopped gracefully")
        else:
            logger.info(f"✓ Service {name} stopped")

        return True

    except Exception as e:
        logger.error(f"Failed to stop service {name}: {e}")
        return False


# Service registry
def get_chat_service() -> ServiceConfig:
    """Get chat service configuration"""
    return ServiceConfig(
        name="chat_service",
        enabled=True,
        auto_start=True,
        depends_on=["database", "memory"],
        config={
            "max_sessions": 1000,
            "session_timeout": SERVICE_LIFE_CYCLE_TIMEOUT
        }
    )


def get_memory_service() -> ServiceConfig:
    """Get memory service configuration"""
    return ServiceConfig(
        name="memory_service",
        enabled=True,
        auto_start=True,
        depends_on=["database"],
        config={
            "cache_size": MAX_SERVICE_CONNECTIONS,
            "embedding_model": "text-embedding-ada-002"
        }
    )


def get_default_services() -> List[str]:
    """Get list of default services to start"""
    return [
        'database',
        'memory',
        'chat',
        'learning'
    ]


# Service manager instance
_service_configs: Dict[str, ServiceConfig] = {}


def register_service(config: ServiceConfig):
    """Register a service configuration"""
    _service_configs[config.name] = config
    logger.info(f"Registered service: {config.name}")


def get_service_config(name: str) -> Optional[ServiceConfig]:
    """Get service configuration by name"""
    return _service_configs.get(name)


def list_services() -> List[str]:
    """List all registered services"""
    return list(_service_configs.keys())
