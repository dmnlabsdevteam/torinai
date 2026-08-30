#!/usr/bin/env python3
"""
Domain Knowledge System Chaos Adapter
======================================

Chaos injection for the domain knowledge system.

Targets:
- Cross-domain reasoner
- Universal ontology
- Domain registry
- Knowledge graph
- Domain-specific reasoning
"""

import logging
import uuid
from datetime import datetime
from typing import Dict, Any, Optional

from .base_adapter import TargetSystemAdapter
from ..types import InjectionHandle, ChaosType
from ..context_managers import ChaosContext

logger = logging.getLogger(__name__)


class DomainSystemAdapter(TargetSystemAdapter):
    """
    Chaos adapter for the domain knowledge system.

    Injection Points:
    - cross_domain_reasoner.reason: Cross-domain reasoning failures
    - universal_ontology.query: Ontology query timeouts
    - domain_registry.lookup: Domain lookup errors
    - knowledge_graph.traverse: Graph traversal failures
    """

    def __init__(self):
        super().__init__("domain_system")
        self.injection_points = {
            "cross_domain_reasoning": "cross_domain_reasoner",
            "ontology_query": "universal_ontology",
            "domain_lookup": "domain_registry",
            "graph_traversal": "knowledge_graph"
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
        Inject latency into domain system operations.

        Examples:
        - component="cross_domain_reasoner", injection_point="domain_mapping"
        - component="universal_ontology", injection_point="concept_lookup"
        """
        injection_id = f"domain_latency_{uuid.uuid4().hex[:8]}"

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
            f"Domain latency injection: {component}.{injection_point} "
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
        Inject errors into domain system operations.

        Examples:
        - component="universal_ontology", error_type="OntologyQueryTimeout"
        - component="domain_registry", error_type="DomainNotFound"
        """
        injection_id = f"domain_error_{uuid.uuid4().hex[:8]}"

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
            f"Domain error injection: {component}.{injection_point} "
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
        Inject resource exhaustion into domain system.

        Examples:
        - resource_type="ontology_cache" (ontology cache exhaustion)
        - resource_type="graph_memory" (knowledge graph memory limits)
        """
        injection_id = f"domain_resource_{uuid.uuid4().hex[:8]}"

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
            f"Domain resource exhaustion: {component}.{resource_type} "
            f"(experiment: {target_id})"
        )

        return handle

    async def get_health_metrics(self) -> Dict[str, Any]:
        """
        Get health metrics for domain system.

        Metrics:
        - reasoning_latency_p95: Cross-domain reasoning latency
        - ontology_query_success_rate: Ontology query success rate
        - domain_lookup_error_rate: Domain lookup error rate
        - knowledge_graph_size: Size of knowledge graph
        """
        # In production, these would come from actual monitoring
        metrics = {
            "reasoning_latency_p95": 150.0,  # ms
            "reasoning_latency_p99": 400.0,  # ms
            "ontology_query_success_rate": 0.98,  # 98%
            "domain_lookup_error_rate": 0.01,  # 1%
            "knowledge_graph_size": 50000,  # nodes
            "active_reasoning_tasks": len(self.active_injections),
            "healthy": True
        }

        # Mark as unhealthy if success rate is low or latency is high
        if metrics["ontology_query_success_rate"] < 0.9 or metrics["reasoning_latency_p95"] > 500:
            metrics["healthy"] = False

        return metrics

    async def cleanup(self):
        """
        Clean up all active chaos injections for domain system.
        """
        logger.info(f"Cleaning up {len(self.active_injections)} domain system injections")

        # Disable all chaos contexts
        for injection_id, handle in list(self.active_injections.items()):
            handle.stop()

        # Clear all injections
        self.active_injections.clear()

        # Disable all chaos for domain system components
        await ChaosContext.disable_all()

        logger.info("Domain system chaos cleanup complete")


# Singleton instance
_domain_adapter = None


def get_domain_adapter() -> DomainSystemAdapter:
    """Get global domain system adapter instance"""
    global _domain_adapter
    if _domain_adapter is None:
        _domain_adapter = DomainSystemAdapter()
    return _domain_adapter
