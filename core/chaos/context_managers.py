#!/usr/bin/env python3
"""
Chaos Context Managers
======================

Global chaos state management and context managers for chaos experiments.
"""

import asyncio
import logging
from typing import Dict, Optional
from .types import ChaosExperiment

logger = logging.getLogger(__name__)


class ChaosContext:
    """
    Global chaos context for enabling/disabling chaos per request.

    This class maintains global state for chaos injection, allowing
    non-invasive activation/deactivation of chaos for specific
    components and injection points.

    Thread-safe for concurrent experiment execution.
    """

    _chaos_enabled: Dict[str, bool] = {}
    _active_experiments: Dict[str, str] = {}
    _lock = asyncio.Lock()

    @classmethod
    async def enable_chaos(cls, component: str, injection_point: str, experiment_id: str):
        """
        Enable chaos for specific component/injection point.

        Args:
            component: Component name (e.g., "continuous_learning_pipeline")
            injection_point: Injection point (e.g., "data_loading")
            experiment_id: Associated experiment ID
        """
        async with cls._lock:
            key = f"{component}:{injection_point}"
            cls._chaos_enabled[key] = True
            cls._active_experiments[key] = experiment_id
            logger.info(f"Chaos enabled: {key} (experiment: {experiment_id})")

    @classmethod
    async def disable_chaos(cls, component: str, injection_point: str):
        """
        Disable chaos for specific component/injection point.

        Args:
            component: Component name
            injection_point: Injection point
        """
        async with cls._lock:
            key = f"{component}:{injection_point}"
            cls._chaos_enabled[key] = False

            if key in cls._active_experiments:
                experiment_id = cls._active_experiments[key]
                del cls._active_experiments[key]
                logger.info(f"Chaos disabled: {key} (was experiment: {experiment_id})")

    @classmethod
    def is_chaos_enabled(cls, component: str, injection_point: str) -> bool:
        """
        Check if chaos is enabled for component/injection point.

        Args:
            component: Component name
            injection_point: Injection point (use "*" for wildcard)

        Returns:
            True if chaos is enabled
        """
        # Check exact match
        key = f"{component}:{injection_point}"
        if key in cls._chaos_enabled:
            return cls._chaos_enabled[key]

        # Check wildcard match for component
        if injection_point == "*":
            return any(
                enabled
                for k, enabled in cls._chaos_enabled.items()
                if k.startswith(f"{component}:")
            )

        return False

    @classmethod
    def get_active_experiment_id(cls, component: str, injection_point: str) -> Optional[str]:
        """
        Get the active experiment ID for a component/injection point.

        Args:
            component: Component name
            injection_point: Injection point

        Returns:
            Experiment ID if chaos is active, None otherwise
        """
        key = f"{component}:{injection_point}"
        return cls._active_experiments.get(key)

    @classmethod
    async def disable_all(cls):
        """Disable all active chaos injections"""
        async with cls._lock:
            logger.warning("Disabling all active chaos injections")
            cls._chaos_enabled.clear()
            cls._active_experiments.clear()

    @classmethod
    def get_active_injections(cls) -> Dict[str, str]:
        """
        Get all active chaos injections.

        Returns:
            Dict mapping injection keys to experiment IDs
        """
        return dict(cls._active_experiments)


class chaos_experiment:
    """
    Context manager for chaos experiments.

    Enables chaos for the experiment duration, automatically
    disables on exit (even on exceptions).

    Usage:
        async with chaos_experiment(experiment) as ctx:
            # Chaos is enabled during this block
            await run_workload()
        # Chaos is automatically disabled after block
    """

    def __init__(self, experiment: ChaosExperiment):
        """
        Initialize chaos experiment context.

        Args:
            experiment: ChaosExperiment instance
        """
        self.experiment = experiment
        self.component = experiment.injection_config.component
        self.injection_point = experiment.injection_config.injection_point

    async def __aenter__(self):
        """Enable chaos on context entry"""
        await ChaosContext.enable_chaos(
            self.component,
            self.injection_point,
            self.experiment.experiment_id
        )
        logger.info(f"Chaos experiment context entered: {self.experiment.experiment_id}")
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Disable chaos on context exit"""
        await ChaosContext.disable_chaos(
            self.component,
            self.injection_point
        )

        if exc_type is not None:
            logger.error(
                f"Chaos experiment context exited with exception: {exc_type.__name__}: {exc_val}"
            )
        else:
            logger.info(f"Chaos experiment context exited: {self.experiment.experiment_id}")

        # Don't suppress exceptions
        return False


class temporary_chaos:
    """
    Temporary chaos context for testing.

    Enables chaos without requiring a full ChaosExperiment object.
    Useful for unit tests and quick experiments.

    Usage:
        async with temporary_chaos("my_component", "my_injection_point"):
            # Chaos is enabled
            await test_function()
        # Chaos is disabled
    """

    def __init__(self, component: str, injection_point: str, experiment_id: str = "temp"):
        """
        Initialize temporary chaos context.

        Args:
            component: Component name
            injection_point: Injection point
            experiment_id: Optional experiment ID (default: "temp")
        """
        self.component = component
        self.injection_point = injection_point
        self.experiment_id = experiment_id

    async def __aenter__(self):
        """Enable chaos on context entry"""
        await ChaosContext.enable_chaos(
            self.component,
            self.injection_point,
            self.experiment_id
        )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Disable chaos on context exit"""
        await ChaosContext.disable_chaos(
            self.component,
            self.injection_point
        )
        return False


class chaos_scope:
    """
    Chaos scope for managing multiple injections.

    Enables/disables multiple chaos injections as a single unit.
    Useful for complex experiments with multiple failure points.

    Usage:
        async with chaos_scope() as scope:
            await scope.enable("component1", "point1", "exp1")
            await scope.enable("component2", "point2", "exp1")
            # Both injections active
            await run_workload()
        # All injections automatically disabled
    """

    def __init__(self):
        """Initialize chaos scope"""
        self.enabled_injections = []

    async def enable(self, component: str, injection_point: str, experiment_id: str):
        """
        Enable a chaos injection within this scope.

        Args:
            component: Component name
            injection_point: Injection point
            experiment_id: Experiment ID
        """
        await ChaosContext.enable_chaos(component, injection_point, experiment_id)
        self.enabled_injections.append((component, injection_point))

    async def __aenter__(self):
        """Enter scope"""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Exit scope and disable all injections"""
        for component, injection_point in self.enabled_injections:
            await ChaosContext.disable_chaos(component, injection_point)
        return False
