#!/usr/bin/env python3
"""
Circuit Breaker for External Module Resilience
Prevents cascading failures from unreliable external dependencies
"""

import asyncio
import logging
import time
from typing import Dict, Any, Optional, Callable, Awaitable
from dataclasses import dataclass, field
from datetime import datetime

from core.chaos.types import CircuitState

logger = logging.getLogger(__name__)


@dataclass
class CircuitBreakerStats:
    """Statistics for circuit breaker"""
    total_calls: int = 0
    successful_calls: int = 0
    failed_calls: int = 0
    rejected_calls: int = 0
    last_failure_time: Optional[float] = None
    last_success_time: Optional[float] = None
    state_transitions: int = 0


class CircuitBreaker:
    """
    Circuit breaker for external module calls

    States:
    - CLOSED: Normal operation, calls go through
    - OPEN: Too many failures, block all calls
    - HALF_OPEN: Testing recovery, allow limited calls

    Uses CircuitState from chaos/types.py for consistency
    """

    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        success_threshold: int = 2,
        timeout_seconds: float = 60.0,
        half_open_timeout: float = 30.0
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.success_threshold = success_threshold
        self.timeout_seconds = timeout_seconds
        self.half_open_timeout = half_open_timeout

        # State management
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.success_count = 0
        self.last_failure_time: Optional[float] = None
        self.opened_at: Optional[float] = None

        # Statistics
        self.stats = CircuitBreakerStats()

        # Lock for thread safety
        self._lock = asyncio.Lock()

        logger.info(
            f"Circuit breaker '{name}' initialized: "
            f"failure_threshold={failure_threshold}, "
            f"timeout={timeout_seconds}s"
        )

    async def call(
        self,
        func: Callable[..., Awaitable[Any]],
        *args,
        **kwargs
    ) -> Any:
        """
        Execute function through circuit breaker

        Args:
            func: Async function to execute
            *args: Positional arguments
            **kwargs: Keyword arguments

        Returns:
            Result from function

        Raises:
            RuntimeError: If circuit is open
            Exception: Original exception from function
        """
        async with self._lock:
            current_state = self.state

            # Check if we should transition from OPEN to HALF_OPEN
            if current_state == CircuitState.OPEN:
                if self.opened_at and (time.time() - self.opened_at) >= self.timeout_seconds:
                    await self._transition_to_half_open()
                    current_state = CircuitState.HALF_OPEN
                else:
                    self.stats.rejected_calls += 1
                    raise RuntimeError(
                        f"Circuit breaker '{self.name}' is OPEN. "
                        f"Opened {time.time() - self.opened_at:.1f}s ago. "
                        f"Will retry in {self.timeout_seconds - (time.time() - self.opened_at):.1f}s."
                    )

            # HALF_OPEN: Allow call but monitor closely
            if current_state == CircuitState.HALF_OPEN:
                logger.info(f"Circuit breaker '{self.name}' testing recovery (HALF_OPEN)")

        # Execute function outside lock to avoid blocking
        self.stats.total_calls += 1
        start_time = time.time()

        try:
            # Execute with timeout for HALF_OPEN state
            if current_state == CircuitState.HALF_OPEN:
                result = await asyncio.wait_for(
                    func(*args, **kwargs),
                    timeout=self.half_open_timeout
                )
            else:
                result = await func(*args, **kwargs)

            # Success - update state
            async with self._lock:
                await self._on_success()

            return result

        except Exception as e:
            # Failure - update state
            async with self._lock:
                await self._on_failure(e)

            raise

    async def _on_success(self):
        """Handle successful call"""
        self.stats.successful_calls += 1
        self.stats.last_success_time = time.time()
        self.failure_count = 0

        if self.state == CircuitState.HALF_OPEN:
            self.success_count += 1
            logger.info(
                f"Circuit breaker '{self.name}' recovery test successful "
                f"({self.success_count}/{self.success_threshold})"
            )

            if self.success_count >= self.success_threshold:
                await self._transition_to_closed()

        elif self.state == CircuitState.CLOSED:
            self.success_count += 1

    async def _on_failure(self, error: Exception):
        """Handle failed call"""
        self.stats.failed_calls += 1
        self.stats.last_failure_time = time.time()
        self.last_failure_time = time.time()
        self.success_count = 0

        if self.state == CircuitState.HALF_OPEN:
            logger.warning(
                f"Circuit breaker '{self.name}' recovery failed: {error}. "
                "Reopening circuit."
            )
            await self._transition_to_open()

        elif self.state == CircuitState.CLOSED:
            self.failure_count += 1
            logger.warning(
                f"Circuit breaker '{self.name}' failure {self.failure_count}/{self.failure_threshold}: {error}"
            )

            if self.failure_count >= self.failure_threshold:
                await self._transition_to_open()

    async def _transition_to_open(self):
        """Transition to OPEN state"""
        if self.state != CircuitState.OPEN:
            self.state = CircuitState.OPEN
            self.opened_at = time.time()
            self.stats.state_transitions += 1
            logger.error(
                f"Circuit breaker '{self.name}' OPENED. "
                f"Blocking calls for {self.timeout_seconds}s. "
                f"Failures: {self.failure_count}"
            )

    async def _transition_to_half_open(self):
        """Transition to HALF_OPEN state"""
        if self.state != CircuitState.HALF_OPEN:
            self.state = CircuitState.HALF_OPEN
            self.failure_count = 0
            self.success_count = 0
            self.stats.state_transitions += 1
            logger.info(
                f"Circuit breaker '{self.name}' HALF_OPEN. "
                "Testing recovery..."
            )

    async def _transition_to_closed(self):
        """Transition to CLOSED state"""
        if self.state != CircuitState.CLOSED:
            self.state = CircuitState.CLOSED
            self.failure_count = 0
            self.success_count = 0
            self.opened_at = None
            self.stats.state_transitions += 1
            logger.info(
                f"Circuit breaker '{self.name}' CLOSED. "
                "Normal operation restored."
            )

    async def reset(self):
        """Manually reset circuit breaker to CLOSED"""
        async with self._lock:
            await self._transition_to_closed()
            logger.info(f"Circuit breaker '{self.name}' manually reset")

    def get_stats(self) -> Dict[str, Any]:
        """Get circuit breaker statistics"""
        return {
            "name": self.name,
            "state": self.state.value,
            "failure_count": self.failure_count,
            "success_count": self.success_count,
            "total_calls": self.stats.total_calls,
            "successful_calls": self.stats.successful_calls,
            "failed_calls": self.stats.failed_calls,
            "rejected_calls": self.stats.rejected_calls,
            "success_rate": (
                self.stats.successful_calls / self.stats.total_calls
                if self.stats.total_calls > 0 else 0.0
            ),
            "state_transitions": self.stats.state_transitions,
            "opened_at": datetime.fromtimestamp(self.opened_at).isoformat() if self.opened_at else None,
            "last_failure_time": (
                datetime.fromtimestamp(self.stats.last_failure_time).isoformat()
                if self.stats.last_failure_time else None
            ),
            "last_success_time": (
                datetime.fromtimestamp(self.stats.last_success_time).isoformat()
                if self.stats.last_success_time else None
            )
        }


class CircuitBreakerRegistry:
    """Registry for managing multiple circuit breakers"""

    def __init__(self):
        self.breakers: Dict[str, CircuitBreaker] = {}
        self._lock = asyncio.Lock()

    async def get_or_create(
        self,
        name: str,
        failure_threshold: int = 5,
        success_threshold: int = 2,
        timeout_seconds: float = 60.0,
        half_open_timeout: float = 30.0
    ) -> CircuitBreaker:
        """Get existing breaker or create new one"""
        async with self._lock:
            if name not in self.breakers:
                self.breakers[name] = CircuitBreaker(
                    name=name,
                    failure_threshold=failure_threshold,
                    success_threshold=success_threshold,
                    timeout_seconds=timeout_seconds,
                    half_open_timeout=half_open_timeout
                )
                logger.info(f"Created circuit breaker: {name}")
            return self.breakers[name]

    async def reset_all(self):
        """Reset all circuit breakers"""
        async with self._lock:
            for breaker in self.breakers.values():
                await breaker.reset()
            logger.info(f"Reset {len(self.breakers)} circuit breakers")

    def get_all_stats(self) -> Dict[str, Any]:
        """Get statistics for all circuit breakers"""
        return {
            name: breaker.get_stats()
            for name, breaker in self.breakers.items()
        }


# Global registry singleton
_registry: Optional[CircuitBreakerRegistry] = None


def get_circuit_breaker_registry() -> CircuitBreakerRegistry:
    """Get global circuit breaker registry"""
    global _registry
    if _registry is None:
        _registry = CircuitBreakerRegistry()
    return _registry
