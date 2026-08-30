#!/usr/bin/env python3
"""
Base Target System Adapter
===========================

Abstract base class for all target system adapters.
Defines the interface that all adapters must implement.
"""

import logging
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional

from ..types import InjectionHandle, ChaosType

logger = logging.getLogger(__name__)


class TargetSystemAdapter(ABC):
    """
    Abstract base class for target system chaos adapters.

    Each target system (learning, security, reasoning, etc.) has a
    concrete adapter that implements this interface.

    Responsibilities:
    - Inject chaos into specific system components
    - Provide health metrics for the target system
    - Clean up chaos injections on completion
    """

    def __init__(self, system_name: str):
        """
        Initialize target system adapter.

        Args:
            system_name: Name of the target system (e.g., "learning_system")
        """
        self.system_name = system_name
        self.active_injections: Dict[str, InjectionHandle] = {}
        logger.info(f"Initialized {self.__class__.__name__} for {system_name}")

    @abstractmethod
    async def inject_latency(
        self,
        target_id: str,
        component: str,
        injection_point: str,
        delay_ms: int,
        jitter_ms: int = 0
    ) -> InjectionHandle:
        """
        Inject latency into target system.

        Args:
            target_id: Unique identifier for this injection
            component: Component to inject into
            injection_point: Specific injection point
            delay_ms: Base delay in milliseconds
            jitter_ms: Random jitter in milliseconds

        Returns:
            InjectionHandle for managing the injection
        """
        pass

    @abstractmethod
    async def inject_error(
        self,
        target_id: str,
        component: str,
        injection_point: str,
        error_type: str,
        error_rate: float
    ) -> InjectionHandle:
        """
        Inject errors into target system.

        Args:
            target_id: Unique identifier for this injection
            component: Component to inject into
            injection_point: Specific injection point
            error_type: Type of error to inject
            error_rate: Probability of error (0.0-1.0)

        Returns:
            InjectionHandle for managing the injection
        """
        pass

    @abstractmethod
    async def inject_resource_exhaustion(
        self,
        target_id: str,
        component: str,
        resource_type: str,
        limit_value: Optional[float] = None
    ) -> InjectionHandle:
        """
        Inject resource exhaustion into target system.

        Args:
            target_id: Unique identifier for this injection
            component: Component to inject into
            resource_type: Type of resource (cpu, memory, disk)
            limit_value: Optional limit value

        Returns:
            InjectionHandle for managing the injection
        """
        pass

    @abstractmethod
    async def get_health_metrics(self) -> Dict[str, Any]:
        """
        Get health metrics for the target system.

        Returns:
            Dict containing health metrics (latency, error_rate, etc.)
        """
        pass

    @abstractmethod
    async def cleanup(self):
        """
        Clean up all active chaos injections for this system.

        Should be called when experiment ends or is rolled back.
        """
        pass

    async def stop_injection(self, injection_id: str) -> bool:
        """
        Stop a specific chaos injection.

        Args:
            injection_id: Injection identifier

        Returns:
            True if stopped successfully
        """
        if injection_id in self.active_injections:
            handle = self.active_injections[injection_id]
            handle.stop()
            del self.active_injections[injection_id]
            logger.info(f"Stopped injection {injection_id} on {self.system_name}")
            return True

        logger.warning(f"Injection not found: {injection_id}")
        return False

    def get_active_injection_count(self) -> int:
        """Get number of active injections"""
        return len(self.active_injections)

    def get_active_injections(self) -> Dict[str, InjectionHandle]:
        """Get all active injections"""
        return dict(self.active_injections)

    async def inject_partial_failure(
        self,
        target_id: str,
        component: str,
        injection_point: str,
        failure_rate: float
    ) -> InjectionHandle:
        """
        Inject partial failures (default implementation using error injection).

        Args:
            target_id: Unique identifier for this injection
            component: Component to inject into
            injection_point: Specific injection point
            failure_rate: Probability of partial failure (0.0-1.0)

        Returns:
            InjectionHandle for managing the injection
        """
        # Default: partial failure is implemented as error injection
        return await self.inject_error(
            target_id=target_id,
            component=component,
            injection_point=injection_point,
            error_type="PartialFailure",
            error_rate=failure_rate
        )

    async def inject_timeout(
        self,
        target_id: str,
        component: str,
        injection_point: str,
        timeout_ms: int
    ) -> InjectionHandle:
        """
        Inject timeout (default implementation using latency injection).

        Args:
            target_id: Unique identifier for this injection
            component: Component to inject into
            injection_point: Specific injection point
            timeout_ms: Timeout in milliseconds

        Returns:
            InjectionHandle for managing the injection
        """
        # Default: timeout is implemented as very high latency
        return await self.inject_latency(
            target_id=target_id,
            component=component,
            injection_point=injection_point,
            delay_ms=timeout_ms * 2,  # Delay longer than timeout
            jitter_ms=0
        )

    # =========================================================================
    # DATABASE PERSISTENCE METHODS
    # =========================================================================

    async def _ensure_chaos_adapter_table(self) -> None:
        """Ensure chaos_adapter_state table exists"""
        if not hasattr(self, 'db') or not self.db:
            return

        try:
            await self.db.execute_query(
                """
                CREATE TABLE IF NOT EXISTS chaos_adapter_state (
                    id SERIAL PRIMARY KEY,
                    adapter_name VARCHAR(128) NOT NULL,
                    method_path VARCHAR(255) NOT NULL,
                    original_method_info JSONB NOT NULL,
                    is_injected BOOLEAN DEFAULT FALSE,
                    injection_type VARCHAR(50) NULL,
                    stored_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_used TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    CONSTRAINT uq_chaos_adapter_method UNIQUE (adapter_name, method_path)
                )
                """,
                commit=True
            )

            # Indexes for common queries
            await self.db.execute_query(
                """
                CREATE INDEX IF NOT EXISTS idx_chaos_adapter_name
                    ON chaos_adapter_state(adapter_name);
                """,
                commit=True,
            )

            await self.db.execute_query(
                """
                CREATE INDEX IF NOT EXISTS idx_chaos_injection_state
                    ON chaos_adapter_state(is_injected);
                """,
                commit=True,
            )
        except Exception as e:
            logger.debug(f"Chaos adapter table initialization issue (likely already exists): {e}")

    async def _store_original_method(self, method_path: str, method_info: Dict[str, Any]) -> None:
        """Store original method reference to database"""
        if not hasattr(self, 'db') or not self.db:
            return

        try:
            await self._ensure_chaos_adapter_table()

            import json
            await self.db.execute_query(
                """
                INSERT INTO chaos_adapter_state (
                    adapter_name, method_path, original_method_info, is_injected
                ) VALUES ($1, $2, $3, FALSE)
                ON CONFLICT (adapter_name, method_path) DO UPDATE SET
                    original_method_info = EXCLUDED.original_method_info,
                    last_used = CURRENT_TIMESTAMP
                """,
                params=(
                    self.system_name,
                    method_path,
                    json.dumps(method_info)
                ),
                commit=True
            )

            logger.debug(f"Stored original method to DB: {method_path}")

        except Exception as e:
            logger.error(f"Failed to store original method: {e}")

    async def _load_original_methods_from_db(self) -> Dict[str, Any]:
        """Load original method references from database"""
        if not hasattr(self, 'db') or not self.db:
            return {}

        try:
            import json
            results = await self.db.execute_query(
                """
                SELECT method_path, original_method_info
                FROM chaos_adapter_state
                WHERE adapter_name = $1
                """,
                params=(self.system_name,)
            )

            methods = {}
            for row in results:
                try:
                    method_info = json.loads(row['original_method_info']) if isinstance(row['original_method_info'], str) else row['original_method_info']
                    methods[row['method_path']] = method_info
                except Exception as parse_error:
                    logger.debug(f"Failed to parse method info: {parse_error}")
                    continue

            return methods

        except Exception as e:
            logger.error(f"Failed to load original methods: {e}")
            return {}

    async def initialize_db(self) -> None:
        """Initialize database connection and load persisted state"""
        try:
            from core.database import TorinUnifiedDatabase
            self.db = TorinUnifiedDatabase()
            await self.db.initialize()
            logger.info(f"{self.system_name} chaos adapter database connected")

            # Load persisted original methods if any
            if hasattr(self, '_original_methods'):
                loaded = await self._load_original_methods_from_db()
                if loaded:
                    # Note: Don't directly restore methods as they may be stale
                    # Just log that we have persisted state
                    logger.info(f"Found {len(loaded)} persisted method references")

        except Exception as e:
            logger.warning(f"Chaos adapter database unavailable (non-critical): {e}")
            self.db = None

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}(system={self.system_name}, active_injections={len(self.active_injections)})>"
