#!/usr/bin/env python3
"""
Chaos Injection Engine
======================

Central engine for managing chaos injection across all target systems.
Coordinates adapters and provides unified injection interface.
"""

import logging
from typing import Dict, Optional, Type

from .types import InjectionHandle, InjectionConfig, ChaosType
from .adapters.base_adapter import TargetSystemAdapter
from .adapters.tool_adapter import ToolSystemAdapter
from .adapters.learning_adapter import LearningSystemAdapter
from .adapters.security_adapter import SecuritySystemAdapter
from .adapters.reasoning_adapter import ReasoningSystemAdapter
from .adapters.agent_adapter import AgentSystemAdapter
from .adapters.domain_adapter import DomainSystemAdapter
from .adapters.memory_adapter import MemorySystemAdapter
from .adapters.intelligence_adapter import IntelligenceSystemAdapter
from .adapters.monitoring_adapter import MonitoringSystemAdapter
from .adapters.services_adapter import ServicesSystemAdapter

logger = logging.getLogger(__name__)


class ChaosInjectionEngine:
    """
    Chaos Injection Engine

    Central coordinator for chaos injection across all target systems.
    Uses adapter pattern to support different target systems.

    Responsibilities:
    - Manage target system adapters
    - Route injection requests to appropriate adapters
    - Track active injections across all systems
    - Coordinate injection lifecycle
    """

    def __init__(self):
        """Initialize chaos injection engine"""
        # Registry of target system adapters
        self.adapters: Dict[str, TargetSystemAdapter] = {}

        # Register default adapters
        self._register_default_adapters()

        logger.info("ChaosInjectionEngine initialized")

    def _register_default_adapters(self):
        """Register default target system adapters"""
        # Register all 10 target system adapters
        self.register_adapter("tool_system", ToolSystemAdapter())
        self.register_adapter("learning_system", LearningSystemAdapter())
        self.register_adapter("security_system", SecuritySystemAdapter())
        self.register_adapter("reasoning_system", ReasoningSystemAdapter())
        self.register_adapter("autonomous_agents", AgentSystemAdapter())
        self.register_adapter("domain_system", DomainSystemAdapter())
        self.register_adapter("memory_system", MemorySystemAdapter())
        self.register_adapter("intelligence_system", IntelligenceSystemAdapter())
        self.register_adapter("monitoring_system", MonitoringSystemAdapter())
        self.register_adapter("services_system", ServicesSystemAdapter())

        logger.info(f"Registered {len(self.adapters)} target system adapters")

    def register_adapter(self, system_name: str, adapter: TargetSystemAdapter):
        """
        Register a target system adapter.

        Args:
            system_name: Name of target system
            adapter: Adapter instance
        """
        if system_name in self.adapters:
            logger.warning(f"Overwriting existing adapter for {system_name}")

        self.adapters[system_name] = adapter
        logger.info(f"Registered adapter: {system_name} ({adapter.__class__.__name__})")

    def get_adapter(self, system_name: str) -> Optional[TargetSystemAdapter]:
        """
        Get adapter for target system.

        Args:
            system_name: Name of target system

        Returns:
            Adapter instance or None if not found
        """
        return self.adapters.get(system_name)

    async def inject_chaos(
        self,
        target_system: str,
        config: InjectionConfig,
        experiment_id: str
    ) -> Optional[InjectionHandle]:
        """
        Inject chaos into target system.

        Args:
            target_system: Target system name (e.g., "tool_system")
            config: Injection configuration
            experiment_id: Associated experiment ID

        Returns:
            InjectionHandle or None if injection failed
        """
        # Get adapter for target system
        adapter = self.get_adapter(target_system)
        if not adapter:
            logger.error(f"No adapter found for target system: {target_system}")
            return None

        try:
            # Route to appropriate injection method based on chaos type
            if config.chaos_type == ChaosType.LATENCY:
                return await adapter.inject_latency(
                    target_id=experiment_id,
                    component=config.component,
                    injection_point=config.injection_point,
                    delay_ms=config.delay_ms or 100,
                    jitter_ms=config.jitter_ms or 0
                )

            elif config.chaos_type == ChaosType.ERROR:
                return await adapter.inject_error(
                    target_id=experiment_id,
                    component=config.component,
                    injection_point=config.injection_point,
                    error_type=config.error_type or "Exception",
                    error_rate=config.error_rate or 0.1
                )

            elif config.chaos_type == ChaosType.RESOURCE_EXHAUSTION:
                return await adapter.inject_resource_exhaustion(
                    target_id=experiment_id,
                    component=config.component,
                    resource_type=config.resource_type or "memory",
                    limit_value=config.limit_value
                )

            elif config.chaos_type == ChaosType.PARTIAL_FAILURE:
                return await adapter.inject_partial_failure(
                    target_id=experiment_id,
                    component=config.component,
                    injection_point=config.injection_point,
                    failure_rate=config.error_rate or 0.5
                )

            elif config.chaos_type == ChaosType.TIMEOUT:
                return await adapter.inject_timeout(
                    target_id=experiment_id,
                    component=config.component,
                    injection_point=config.injection_point,
                    timeout_ms=config.delay_ms or 1000
                )

            else:
                logger.error(f"Unsupported chaos type: {config.chaos_type}")
                return None

        except Exception as e:
            logger.error(f"Chaos injection failed: {e}")
            return None

    async def stop_injection(
        self,
        target_system: str,
        injection_id: str
    ) -> bool:
        """
        Stop a specific chaos injection.

        Args:
            target_system: Target system name
            injection_id: Injection identifier

        Returns:
            True if stopped successfully
        """
        adapter = self.get_adapter(target_system)
        if not adapter:
            logger.error(f"No adapter found for target system: {target_system}")
            return False

        return await adapter.stop_injection(injection_id)

    async def cleanup_system(self, target_system: str) -> bool:
        """
        Clean up all injections for a target system.

        Args:
            target_system: Target system name

        Returns:
            True if cleaned up successfully
        """
        adapter = self.get_adapter(target_system)
        if not adapter:
            logger.error(f"No adapter found for target system: {target_system}")
            return False

        await adapter.cleanup()
        return True

    async def cleanup_all(self):
        """Clean up all active chaos injections across all systems"""
        logger.info("Cleaning up all chaos injections across all systems")

        for system_name, adapter in self.adapters.items():
            try:
                await adapter.cleanup()
                logger.info(f"Cleaned up {system_name}")
            except Exception as e:
                logger.error(f"Cleanup failed for {system_name}: {e}")

        logger.info("Global chaos cleanup complete")

    async def get_system_health(self, target_system: str) -> Optional[Dict]:
        """
        Get health metrics for a target system.

        Args:
            target_system: Target system name

        Returns:
            Health metrics dict or None if system not found
        """
        adapter = self.get_adapter(target_system)
        if not adapter:
            logger.error(f"No adapter found for target system: {target_system}")
            return None

        return await adapter.get_health_metrics()

    def get_active_injection_count(self, target_system: Optional[str] = None) -> int:
        """
        Get count of active injections.

        Args:
            target_system: Optional filter by target system

        Returns:
            Count of active injections
        """
        if target_system:
            adapter = self.get_adapter(target_system)
            return adapter.get_active_injection_count() if adapter else 0

        # Count across all systems
        return sum(
            adapter.get_active_injection_count()
            for adapter in self.adapters.values()
        )

    def get_registered_systems(self) -> list[str]:
        """
        Get list of registered target systems.

        Returns:
            List of system names
        """
        return list(self.adapters.keys())

    def is_system_registered(self, system_name: str) -> bool:
        """
        Check if a target system is registered.

        Args:
            system_name: System name to check

        Returns:
            True if registered
        """
        return system_name in self.adapters

    async def get_all_health_metrics(self) -> Dict[str, Dict]:
        """
        Get health metrics for all registered systems.

        Returns:
            Dict mapping system names to health metrics
        """
        metrics = {}

        for system_name, adapter in self.adapters.items():
            try:
                metrics[system_name] = await adapter.get_health_metrics()
            except Exception as e:
                logger.error(f"Failed to get health metrics for {system_name}: {e}")
                metrics[system_name] = {"error": str(e), "healthy": False}

        return metrics


# Singleton instance
_injection_engine = None


def get_injection_engine() -> ChaosInjectionEngine:
    """Get global injection engine instance"""
    global _injection_engine
    if _injection_engine is None:
        _injection_engine = ChaosInjectionEngine()
    return _injection_engine
