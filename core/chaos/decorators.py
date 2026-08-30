#!/usr/bin/env python3
"""
Chaos Injection Decorators
===========================

Non-invasive chaos injection via function decorators.

Decorators can be applied to any async or sync function to inject
chaos transparently without modifying the core logic.
"""

import asyncio
import functools
import logging
import random
import time
from typing import Callable, Optional, Type

from .context_managers import ChaosContext

logger = logging.getLogger(__name__)


class ChaosDecorators:
    """
    Non-invasive chaos injection decorators.

    These decorators allow transparent chaos injection into
    existing functions without modifying their core logic.
    """

    @staticmethod
    def inject_latency(
        component: str,
        injection_point: str,
        delay_ms: int = 100,
        jitter_ms: int = 50,
        enabled: bool = True
    ):
        """
        Decorator to inject latency into a function.

        Args:
            component: Component name (e.g., "continuous_learning_pipeline")
            injection_point: Injection point (e.g., "data_loading")
            delay_ms: Base delay in milliseconds
            jitter_ms: Random jitter in milliseconds
            enabled: Whether to enable this decorator (for testing)

        Usage:
            @ChaosDecorators.inject_latency("my_component", "my_function", delay_ms=500)
            async def my_function():
                pass
        """
        def decorator(func: Callable):
            @functools.wraps(func)
            async def async_wrapper(*args, **kwargs):
                if enabled and ChaosContext.is_chaos_enabled(component, injection_point):
                    # Calculate delay with jitter
                    delay = delay_ms + random.randint(-jitter_ms, jitter_ms)
                    delay_seconds = max(0, delay / 1000.0)

                    experiment_id = ChaosContext.get_active_experiment_id(component, injection_point)
                    logger.debug(
                        f"Chaos latency injection: {component}.{injection_point} "
                        f"({delay}ms delay, experiment: {experiment_id})"
                    )

                    await asyncio.sleep(delay_seconds)

                return await func(*args, **kwargs)

            @functools.wraps(func)
            def sync_wrapper(*args, **kwargs):
                if enabled and ChaosContext.is_chaos_enabled(component, injection_point):
                    # Calculate delay with jitter
                    delay = delay_ms + random.randint(-jitter_ms, jitter_ms)
                    delay_seconds = max(0, delay / 1000.0)

                    experiment_id = ChaosContext.get_active_experiment_id(component, injection_point)
                    logger.debug(
                        f"Chaos latency injection: {component}.{injection_point} "
                        f"({delay}ms delay, experiment: {experiment_id})"
                    )

                    time.sleep(delay_seconds)

                return func(*args, **kwargs)

            # Return appropriate wrapper based on function type
            if asyncio.iscoroutinefunction(func):
                return async_wrapper
            else:
                return sync_wrapper

        return decorator

    @staticmethod
    def inject_error(
        component: str,
        injection_point: str,
        error_type: Type[Exception] = Exception,
        error_rate: float = 0.1,
        error_message: str = "Chaos-injected error"
    ):
        """
        Decorator to inject errors into a function.

        Args:
            component: Component name
            injection_point: Injection point
            error_type: Exception type to raise
            error_rate: Probability of raising error (0.0-1.0)
            error_message: Error message

        Usage:
            @ChaosDecorators.inject_error("my_component", "my_function",
                                           error_type=IOError, error_rate=0.3)
            async def my_function():
                pass
        """
        def decorator(func: Callable):
            @functools.wraps(func)
            async def async_wrapper(*args, **kwargs):
                if ChaosContext.is_chaos_enabled(component, injection_point):
                    if random.random() < error_rate:
                        experiment_id = ChaosContext.get_active_experiment_id(component, injection_point)
                        logger.warning(
                            f"Chaos error injection: {component}.{injection_point} "
                            f"(raising {error_type.__name__}, experiment: {experiment_id})"
                        )
                        raise error_type(error_message)

                return await func(*args, **kwargs)

            @functools.wraps(func)
            def sync_wrapper(*args, **kwargs):
                if ChaosContext.is_chaos_enabled(component, injection_point):
                    if random.random() < error_rate:
                        experiment_id = ChaosContext.get_active_experiment_id(component, injection_point)
                        logger.warning(
                            f"Chaos error injection: {component}.{injection_point} "
                            f"(raising {error_type.__name__}, experiment: {experiment_id})"
                        )
                        raise error_type(error_message)

                return func(*args, **kwargs)

            if asyncio.iscoroutinefunction(func):
                return async_wrapper
            else:
                return sync_wrapper

        return decorator

    @staticmethod
    def inject_timeout(
        component: str,
        injection_point: str,
        timeout_ms: int = 1000
    ):
        """
        Decorator to inject timeout errors into async functions.

        Args:
            component: Component name
            injection_point: Injection point
            timeout_ms: Timeout in milliseconds

        Usage:
            @ChaosDecorators.inject_timeout("my_component", "my_function", timeout_ms=500)
            async def my_function():
                pass
        """
        def decorator(func: Callable):
            if not asyncio.iscoroutinefunction(func):
                raise ValueError("inject_timeout can only be used with async functions")

            @functools.wraps(func)
            async def wrapper(*args, **kwargs):
                if ChaosContext.is_chaos_enabled(component, injection_point):
                    timeout_seconds = timeout_ms / 1000.0
                    experiment_id = ChaosContext.get_active_experiment_id(component, injection_point)

                    logger.debug(
                        f"Chaos timeout injection: {component}.{injection_point} "
                        f"({timeout_ms}ms timeout, experiment: {experiment_id})"
                    )

                    try:
                        return await asyncio.wait_for(func(*args, **kwargs), timeout=timeout_seconds)
                    except asyncio.TimeoutError:
                        logger.warning(
                            f"Chaos timeout triggered: {component}.{injection_point} "
                            f"(experiment: {experiment_id})"
                        )
                        raise

                return await func(*args, **kwargs)

            return wrapper

        return decorator

    @staticmethod
    def inject_partial_failure(
        component: str,
        injection_point: str,
        failure_rate: float = 0.5,
        fallback_value: Optional[any] = None
    ):
        """
        Decorator to inject partial failures (returns fallback instead of raising).

        Args:
            component: Component name
            injection_point: Injection point
            failure_rate: Probability of partial failure (0.0-1.0)
            fallback_value: Value to return on partial failure

        Usage:
            @ChaosDecorators.inject_partial_failure("my_component", "my_function",
                                                     failure_rate=0.5, fallback_value=None)
            async def my_function():
                pass
        """
        def decorator(func: Callable):
            @functools.wraps(func)
            async def async_wrapper(*args, **kwargs):
                if ChaosContext.is_chaos_enabled(component, injection_point):
                    if random.random() < failure_rate:
                        experiment_id = ChaosContext.get_active_experiment_id(component, injection_point)
                        logger.warning(
                            f"Chaos partial failure injection: {component}.{injection_point} "
                            f"(returning fallback, experiment: {experiment_id})"
                        )
                        return fallback_value

                return await func(*args, **kwargs)

            @functools.wraps(func)
            def sync_wrapper(*args, **kwargs):
                if ChaosContext.is_chaos_enabled(component, injection_point):
                    if random.random() < failure_rate:
                        experiment_id = ChaosContext.get_active_experiment_id(component, injection_point)
                        logger.warning(
                            f"Chaos partial failure injection: {component}.{injection_point} "
                            f"(returning fallback, experiment: {experiment_id})"
                        )
                        return fallback_value

                return func(*args, **kwargs)

            if asyncio.iscoroutinefunction(func):
                return async_wrapper
            else:
                return sync_wrapper

        return decorator

    @staticmethod
    def inject_resource_exhaustion(
        component: str,
        injection_point: str,
        resource_type: str = "memory",
        exhaustion_rate: float = 0.1
    ):
        """
        Decorator to simulate resource exhaustion.

        Args:
            component: Component name
            injection_point: Injection point
            resource_type: Resource type (memory, cpu, disk)
            exhaustion_rate: Probability of exhaustion (0.0-1.0)

        Usage:
            @ChaosDecorators.inject_resource_exhaustion("my_component", "my_function")
            async def my_function():
                pass
        """
        def decorator(func: Callable):
            @functools.wraps(func)
            async def async_wrapper(*args, **kwargs):
                if ChaosContext.is_chaos_enabled(component, injection_point):
                    if random.random() < exhaustion_rate:
                        experiment_id = ChaosContext.get_active_experiment_id(component, injection_point)
                        logger.error(
                            f"Chaos resource exhaustion: {component}.{injection_point} "
                            f"({resource_type}, experiment: {experiment_id})"
                        )

                        # Raise appropriate error based on resource type
                        if resource_type == "memory":
                            raise MemoryError(f"Chaos: {resource_type} exhausted")
                        elif resource_type == "disk":
                            raise OSError(f"Chaos: {resource_type} exhausted")
                        else:
                            raise RuntimeError(f"Chaos: {resource_type} exhausted")

                return await func(*args, **kwargs)

            @functools.wraps(func)
            def sync_wrapper(*args, **kwargs):
                if ChaosContext.is_chaos_enabled(component, injection_point):
                    if random.random() < exhaustion_rate:
                        experiment_id = ChaosContext.get_active_experiment_id(component, injection_point)
                        logger.error(
                            f"Chaos resource exhaustion: {component}.{injection_point} "
                            f"({resource_type}, experiment: {experiment_id})"
                        )

                        # Raise appropriate error based on resource type
                        if resource_type == "memory":
                            raise MemoryError(f"Chaos: {resource_type} exhausted")
                        elif resource_type == "disk":
                            raise OSError(f"Chaos: {resource_type} exhausted")
                        else:
                            raise RuntimeError(f"Chaos: {resource_type} exhausted")

                return func(*args, **kwargs)

            if asyncio.iscoroutinefunction(func):
                return async_wrapper
            else:
                return sync_wrapper

        return decorator


# Convenience aliases
inject_latency = ChaosDecorators.inject_latency
inject_error = ChaosDecorators.inject_error
inject_timeout = ChaosDecorators.inject_timeout
inject_partial_failure = ChaosDecorators.inject_partial_failure
inject_resource_exhaustion = ChaosDecorators.inject_resource_exhaustion
