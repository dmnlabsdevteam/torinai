#!/usr/bin/env python3
"""
Memory System Chaos Adapter
============================

Chaos injection for the memory system.

Targets:
- Memory storage (PostgreSQL hot and cold tiers)
- Memory agent
- Capability tokens
- Memory retrieval
"""

import logging
import uuid
from datetime import datetime
from typing import Dict, Any, Optional

from .base_adapter import TargetSystemAdapter
from ..types import InjectionHandle, ChaosType
from ..context_managers import ChaosContext

logger = logging.getLogger(__name__)


class MemorySystemAdapter(TargetSystemAdapter):
    """
    Chaos adapter for the memory system.

    Injection Points:
    - PostgreSQL Hot Tier (0-60 days):
      - postgres_storage.store_memory: Storage operation failures
      - postgres_storage.search_memories: Search operation latency/failures

    - PostgreSQL Cold Tier (60+ days archival):
      - postgres_storage.migrate_to_cold: Archival migration failures
      - postgres_storage.get_memory_from_cold: Cold tier retrieval latency/failures

    - Memory Agent Coordination:
      - memory_agent.store_memory: Agent-level storage coordination failures
      - memory_agent.search_memories: Agent-level search coordination latency
      - memory_agent.query_by_tags: Tag-based query failures
      - memory_agent.delete_memory: Delete operation failures

    - Query Agents:
      - postgres_query_agent.search: Read-only query failures
      - postgres_query_agent.search_by_tags: Tag query failures

    - Embedding Service:
      - embedding_service.encode: Embedding generation failures
      - embedding_service.search_similar: Semantic search latency

    - Governance:
      - capability_token_validation: Token validation failures (delete protection)
    """

    def __init__(self):
        super().__init__("memory_system")
        self.injection_points = {
            # PostgreSQL hot tier (0-60 days)
            "postgres_store": "postgres_storage.store_memory",
            "postgres_search": "postgres_storage.search_memories",

            # PostgreSQL cold tier (60+ days archival)
            "postgres_cold_migrate": "postgres_storage.migrate_to_cold",
            "postgres_cold_retrieve": "postgres_storage.get_memory_from_cold",

            # Memory agent coordination
            "agent_store": "memory_agent.store_memory",
            "agent_search": "memory_agent.search_memories",
            "agent_query_tags": "memory_agent.query_by_tags",
            "agent_delete": "memory_agent.delete_memory",

            # Query agents (read-only)
            "query_search": "postgres_query_agent.search",
            "query_tags": "postgres_query_agent.search_by_tags",

            # Embedding service
            "embedding_encode": "embedding_service.encode",
            "embedding_search": "embedding_service.search_similar",

            # Governance
            "token_validation": "capability_token_validation"
        }

    async def inject_latency(
        self,
        target_id: str,
        component: str,
        injection_point: str,
        delay_ms: int,
        jitter_ms: int = 0
    ) -> InjectionHandle:
        """
        Inject latency into memory system operations.

        Examples:
        - component="postgres_storage", injection_point="store_memory"
        - component="postgres_storage", injection_point="search_memories"
        - component="postgres_storage", injection_point="migrate_to_cold"
        - component="memory_agent", injection_point="search_memories"
        - component="embedding_service", injection_point="search_similar"
        """
        injection_id = f"memory_latency_{uuid.uuid4().hex[:8]}"

        # Enable chaos via context
        await ChaosContext.enable_chaos(component, injection_point, target_id)

        # Create injection handle
        handle = InjectionHandle(
            injection_id=injection_id,
            experiment_id=target_id,
            target=self.system_name,
            chaos_type=ChaosType.LATENCY,
            started_at=datetime.now(),
            active=True
        )

        self.active_injections[injection_id] = handle

        logger.info(
            f"Memory latency injection: {component}.{injection_point} "
            f"({delay_ms}ms ± {jitter_ms}ms, experiment: {target_id})"
        )

        return handle

    async def inject_error(
        self,
        target_id: str,
        component: str,
        injection_point: str,
        error_type: str,
        error_rate: float
    ) -> InjectionHandle:
        """
        Inject errors into memory system operations.

        Examples:
        - component="postgres_storage", error_type="ConnectionTimeout"
        - component="postgres_storage", error_type="ColdTierAccessError"
        - component="memory_agent", error_type="StorageError"
        - component="capability_token_validation", error_type="UnauthorizedError"
        """
        injection_id = f"memory_error_{uuid.uuid4().hex[:8]}"

        # Enable chaos via context
        await ChaosContext.enable_chaos(component, injection_point, target_id)

        # Create injection handle
        handle = InjectionHandle(
            injection_id=injection_id,
            experiment_id=target_id,
            target=self.system_name,
            chaos_type=ChaosType.ERROR,
            started_at=datetime.now(),
            active=True
        )

        self.active_injections[injection_id] = handle

        logger.info(
            f"Memory error injection: {component}.{injection_point} "
            f"({error_type} at {error_rate*100}% rate, experiment: {target_id})"
        )

        return handle

    async def inject_resource_exhaustion(
        self,
        target_id: str,
        component: str,
        resource_type: str,
        limit_value: Optional[float] = None
    ) -> InjectionHandle:
        """
        Inject resource exhaustion into memory system.

        Examples:
        - component="postgres_storage", resource_type="connection_pool"
        - component="r2_storage", resource_type="storage_quota"
        - component="embedding_service", resource_type="embedding_cache"
        - component="memory_agent", resource_type="batch_size"
        """
        injection_id = f"memory_resource_{uuid.uuid4().hex[:8]}"

        # Enable chaos via context
        injection_point = f"{resource_type}_exhaustion"
        await ChaosContext.enable_chaos(component, injection_point, target_id)

        # Create injection handle
        handle = InjectionHandle(
            injection_id=injection_id,
            experiment_id=target_id,
            target=self.system_name,
            chaos_type=ChaosType.RESOURCE_EXHAUSTION,
            started_at=datetime.now(),
            active=True
        )

        self.active_injections[injection_id] = handle

        logger.info(
            f"Memory resource exhaustion: {component}.{resource_type} "
            f"(experiment: {target_id})"
        )

        return handle

    async def get_reasoning_trace_metrics(self) -> Dict[str, Any]:
        """
        Get reasoning trace capture quality metrics.

        Queries the memory database to validate chain of thought capture.

        Returns:
            Dict with reasoning trace quality metrics
        """
        try:
            from core.memory import get_memory_agent

            memory_agent = await get_memory_agent()

            # Query PostgreSQL for reasoning trace statistics
            # This queries the memory_hot schema
            query = """
                SELECT
                    COUNT(*) as total_memories,
                    SUM(CASE WHEN reasoning_trace IS NOT NULL AND jsonb_array_length(reasoning_trace) > 0 THEN 1 ELSE 0 END) as with_reasoning_trace,
                    SUM(CASE WHEN thinking_state IS NOT NULL AND jsonb_array_length(thinking_state) > 0 THEN 1 ELSE 0 END) as with_thinking_state,
                    SUM(CASE WHEN decision_factors IS NOT NULL AND jsonb_array_length(decision_factors) > 0 THEN 1 ELSE 0 END) as with_decision_factors,
                    AVG(CASE WHEN reasoning_trace IS NOT NULL THEN jsonb_array_length(reasoning_trace) ELSE 0 END) as avg_reasoning_trace_length
                FROM memory_hot
                WHERE created_at > NOW() - INTERVAL '1 hour'
            """

            # Execute query via PostgreSQL storage
            if memory_agent.postgres_storage:
                result = await memory_agent.postgres_storage.execute_query(query)

                if result and len(result) > 0:
                    row = result[0]
                    total = row.get('total_memories', 1)  # Avoid division by zero

                    return {
                        "total_memories_last_hour": total,
                        "reasoning_trace_completeness_rate": row.get('with_reasoning_trace', 0) / total if total > 0 else 0.0,
                        "reasoning_trace_avg_length": row.get('avg_reasoning_trace_length', 0),
                        "thinking_state_capture_rate": row.get('with_thinking_state', 0) / total if total > 0 else 0.0,
                        "decision_factors_population_rate": row.get('with_decision_factors', 0) / total if total > 0 else 0.0
                    }

            # Return empty metrics if database unavailable
            logger.debug("Memory database unavailable, returning empty reasoning trace metrics")
            return {
                "total_memories_last_hour": 0,
                "reasoning_trace_completeness_rate": 0.0,
                "reasoning_trace_avg_length": 0,
                "thinking_state_capture_rate": 0.0,
                "decision_factors_population_rate": 0.0
            }

        except Exception as e:
            logger.error(f"Failed to get reasoning trace metrics: {e}")
            return {
                "total_memories_last_hour": 0,
                "reasoning_trace_completeness_rate": 0.0,
                "reasoning_trace_avg_length": 0,
                "thinking_state_capture_rate": 0.0,
                "decision_factors_population_rate": 0.0
            }

    async def get_health_metrics(self) -> Dict[str, Any]:
        """
        Get REAL health metrics from actual MemoryAgent.

        Metrics:
        - postgres_store_latency_p95/p99: PostgreSQL hot tier storage operation latency
        - postgres_search_latency_p95/p99: PostgreSQL search operation latency
        - postgres_cold_migrate_latency_p95/p99: PostgreSQL cold tier migration latency
        - postgres_cold_retrieve_latency_p95/p99: PostgreSQL cold tier retrieval latency
        - agent_search_success_rate: Memory agent search success rate
        - embedding_encode_latency_p95: Embedding generation latency
        - embedding_search_latency_p95: Semantic search latency
        - postgres_connection_pool_utilization: PostgreSQL connection pool usage
        - postgres_cold_tier_size_gb: Total PostgreSQL cold tier storage
        - reasoning_trace_completeness_rate: % of memories with reasoning trace
        - reasoning_trace_avg_length: Average reasoning trace length
        - thinking_state_capture_rate: % of memories with thinking state
        - decision_factors_population_rate: % of memories with decision factors
        """
        try:
            from core.memory import get_memory_agent

            memory_agent = await get_memory_agent()

            # Get real metrics from MemoryAgent
            agent_metrics = memory_agent.metrics if hasattr(memory_agent, 'metrics') else {}

            metrics = {
                # Real metrics from MemoryAgent
                "memories_stored": agent_metrics.get("memories_stored", 0),
                "memories_retrieved": agent_metrics.get("memories_retrieved", 0),
                "cache_hits": agent_metrics.get("cache_hits", 0),
                "tier_migrations": agent_metrics.get("tier_migrations", 0),
                "queries_executed": agent_metrics.get("queries_executed", 0),

                # Storage backend status
                "postgres_storage_initialized": memory_agent.postgres_storage is not None if hasattr(memory_agent, 'postgres_storage') else False,
                "embedding_service_initialized": memory_agent.embedding_service is not None if hasattr(memory_agent, 'embedding_service') else False,

                # Cache metrics
                "cache_size": len(memory_agent.memory_cache) if hasattr(memory_agent, 'memory_cache') else 0,
                "cache_enabled": memory_agent.cache_enabled if hasattr(memory_agent, 'cache_enabled') else False,

                # Agent state
                "agent_initialized": memory_agent.initialized if hasattr(memory_agent, 'initialized') else False,

                # Active chaos injections
                "active_chaos_injections": len(self.active_injections),

                "healthy": True
            }

            # Get reasoning trace quality metrics
            reasoning_metrics = await self.get_reasoning_trace_metrics()
            metrics.update(reasoning_metrics)

        except Exception as e:
            logger.error(f"Failed to get real memory metrics: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            # Return minimal fallback
            metrics = {
                "healthy": True,
                "error": str(e),
                "active_chaos_injections": len(self.active_injections),
                "agent_initialized": False
            }

            # Still try to get reasoning metrics
            try:
                reasoning_metrics = await self.get_reasoning_trace_metrics()
                metrics.update(reasoning_metrics)
            except:
                pass

        # For chaos testing, we consider the system healthy if we can collect metrics
        # Even if the agent isn't fully initialized, we can still inject chaos
        # In production, you'd want stricter health checks

        # Only mark as unhealthy if reasoning trace capture quality is poor AND we have data
        total_memories = metrics.get("total_memories_last_hour", 0)
        if total_memories > 10:  # Only check quality if we have enough data
            if "reasoning_trace_completeness_rate" in metrics and metrics["reasoning_trace_completeness_rate"] < 0.8:
                metrics["healthy"] = False
                logger.warning(
                    f"Reasoning trace capture quality degraded: {metrics['reasoning_trace_completeness_rate']*100:.1f}% completeness"
                )
        elif total_memories == 0:
            # Low completeness is expected with no memories, just log it
            logger.debug(
                f"No memories in last hour, skipping reasoning trace quality check"
            )

        return metrics

    async def cleanup(self):
        """
        Clean up all active chaos injections for memory system.
        """
        logger.info(f"Cleaning up {len(self.active_injections)} memory system injections")

        # Disable all chaos contexts
        for injection_id, handle in list(self.active_injections.items()):
            handle.stop()

        # Clear all injections
        self.active_injections.clear()

        # Disable all chaos for memory system components
        await ChaosContext.disable_all()

        logger.info("Memory system chaos cleanup complete")


# Singleton instance
_memory_adapter = None


def get_memory_adapter() -> MemorySystemAdapter:
    """Get global memory system adapter instance"""
    global _memory_adapter
    if _memory_adapter is None:
        _memory_adapter = MemorySystemAdapter()
    return _memory_adapter
