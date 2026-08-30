#!/usr/bin/env python3
"""
Research Agent
==============
Agent for conducting research tasks, information gathering, and analysis.
"""

import logging
from typing import Dict, Any, List, Optional
from datetime import datetime

from core.capability import CapabilityUnavailable, not_implemented

logger = logging.getLogger(__name__)


class ResearchAgent:
    """
    Research Agent

    Purpose:
    - Conduct research on topics
    - Gather and analyze information
    - Synthesize findings
    """

    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}
        self.agent_id = f"research_{datetime.now().timestamp()}"
        self.initialized = False

        # Research state
        self.active_research: Dict[str, Any] = {}
        self.research_history: List[Dict[str, Any]] = []

        # Metrics
        self.metrics = {
            "total_research_tasks": 0,
            "completed_tasks": 0,
            "failed_tasks": 0
        }

        logger.info(f"ResearchAgent created: {self.agent_id}")

    async def initialize(self) -> bool:
        """Initialize the research agent"""
        try:
            self.initialized = True
            logger.info(f"ResearchAgent {self.agent_id} initialized")
            return True
        except Exception as e:
            logger.error(f"Failed to initialize ResearchAgent: {e}")
            return False

    async def execute(self, task: str, parameters: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Dispatch entry point used by AgentCoordinator.execute_task.

        AgentCoordinator calls `await agent.execute(task, parameters)` -- a
        contract no agent class implemented, so every delegated task raised
        AttributeError, was swallowed, and delegate_task returned None. The
        capability existed; the entry point did not.
        """
        params = parameters or {}
        topic = params.get("topic") or task
        return await self.conduct_research(
            topic=topic,
            depth=params.get("depth", "medium"),
            sources=params.get("sources"),
            max_sources=int(params.get("max_sources", 5)),
        )

    async def conduct_research(
        self,
        topic: str,
        depth: str = "medium",
        sources: Optional[List[str]] = None,
        max_sources: int = 5,
    ) -> Dict[str, Any]:
        """
        Conduct research on a topic

        Args:
            topic: Research topic
            depth: Research depth (shallow, medium, deep)
            sources: Optional list of sources to use

        Returns:
            Research results
        """
        try:
            research_id = f"research_{datetime.now().timestamp()}"

            self.metrics["total_research_tasks"] += 1

            # REAL RESEARCH. This method used to be a placeholder that built
            # {"findings": [], "status": "completed"} and returned it -- no
            # search, no fetch, no network call. It never attempted research,
            # which is why it always "succeeded" with nothing.
            #
            # TorinAI already has the capability: the conduct_research tool
            # queries the structured-source registry, and web_search/web_fetch
            # give unbounded reach to any source on the open web. The agent
            # simply never called any of it.
            from core.tools.tool_registry import get_tool_registry

            registry = get_tool_registry()
            tool = registry.get_tool("conduct_research")
            if tool is None:
                raise not_implemented(
                    "research", "conduct_research tool is not registered"
                )

            tool_result = await tool.execute(topic=topic, max_sources=max_sources)

            if not getattr(tool_result, "success", False):
                # Report the real failure. Never convert it into an empty
                # success -- that is the defect this method used to embody.
                self.metrics["failed_tasks"] += 1
                raise CapabilityUnavailable(
                    "research",
                    reason="research_failed",
                    topic=topic,
                    detail_error=str(getattr(tool_result, "error", "unknown")),
                )

            payload = getattr(tool_result, "output", None) or {}
            findings = payload.get("raw_results") or []
            sources_used = payload.get("apis_used") or []

            if not findings:
                self.metrics["failed_tasks"] += 1
                raise CapabilityUnavailable(
                    "research",
                    reason="no_results",
                    topic=topic,
                    detail_error="research returned zero findings",
                )

            result = {
                "research_id": research_id,
                "topic": topic,
                "depth": depth,
                "findings": findings,
                "sources_used": sources_used,
                "synthesis": payload.get("synthesis"),
                "sources_queried": payload.get("sources_queried"),
                "sources_successful": payload.get("sources_successful"),
                "timestamp": datetime.now().isoformat(),
                "status": "completed",
            }

            # THE PRODUCER AND THE CALLER WERE NEVER JOINED. `payload` is
            # exactly the shape submit_research_result expects -- per-source
            # raw_results plus a synthesis -- and the research agent has been
            # producing it, and discarding it, on every completed task. So
            # research reached memory as prose and never reached the concept
            # layer at all.
            #
            # Ingestion failing must not turn completed research into a failed
            # task: the findings are real and the caller needs them. It is
            # logged at error, never swallowed silently.
            try:
                from core.domain.evidence_producers import submit_research_result

                ingested = await submit_research_result(
                    topic, payload, producer="conduct_research", request_id=research_id)
                result["concepts_accepted"] = sum(r.accepted for r in ingested)
                unread = [f for r in ingested for f in r.extraction_failures]
                if unread:
                    logger.info(
                        "Research %r: %d envelope reading(s) declined: %s",
                        topic, len(unread), unread[:3])
            except Exception as e:
                logger.error(
                    "Research %r completed but could not be ingested as evidence: "
                    "%s: %s", topic, type(e).__name__, e)

            self.research_history.append(result)
            self.metrics["completed_tasks"] += 1
            logger.info(
                f"Research completed: {topic} — {len(findings)} findings "
                f"from {sources_used}"
            )
            return result

        except CapabilityUnavailable:
            # Propagate: the caller must be able to tell "not implemented" from
            # "attempted and failed". Collapsing it into {"status": "failed"}
            # would make an unbuilt capability look like a strategy failure.
            raise
        except Exception as e:
            logger.error(f"Research failed: {e}")
            self.metrics["failed_tasks"] += 1
            return {
                "status": "failed",
                "error": str(e)
            }

    async def shutdown(self):
        """Shutdown the research agent"""
        self.initialized = False
        logger.info(f"ResearchAgent {self.agent_id} shutdown")

    def get_metrics(self) -> Dict[str, Any]:
        """Get research agent metrics"""
        return self.metrics.copy()


# Factory function
def create_research_agent(config: Dict[str, Any] = None) -> ResearchAgent:
    """Create a research agent instance"""
    return ResearchAgent(config)


# Singleton instance
_research_agent = None


def get_research_agent() -> ResearchAgent:
    """Get global research agent instance (singleton)"""
    global _research_agent
    if _research_agent is None:
        _research_agent = ResearchAgent()
    return _research_agent
