#!/usr/bin/env python3
"""
Agent Factory & Coordinator
Factory pattern for creating and managing TorinAI agents.
Provides centralized agent lifecycle, monitoring, and coordination.
"""

import logging
import asyncio
import uuid
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional, Set
from datetime import datetime
from enum import Enum

# Agent implementations
from core.memory import MemoryAgent, get_memory_agent
from core.agents.logical.logical_integration import LogicalIntegrationSystem as LogicalAgent
from core.agents.research.agent import ResearchAgent

logger = logging.getLogger(__name__)


class AgentType(Enum):
    """Available agent types"""
    MEMORY = "memory"
    RESEARCH = "research"
    LOGICAL = "logical"
    GENERIC = "generic"


@dataclass
class AgentConfig:
    """Agent configuration"""
    agent_id: str
    agent_type: AgentType
    name: str
    capabilities: List[str]
    max_concurrent_tasks: int = 5
    created_at: datetime = field(default_factory=datetime.now)
    last_active: datetime = field(default_factory=datetime.now)
    is_active: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)


class AgentCoordinator:
    """
    Agent Coordinator - Factory & Lifecycle Manager

    Creates, manages, and coordinates TorinAI agents.
    Provides centralized agent registry, health monitoring, and task coordination.
    """

    def __init__(self, enable_monitoring: bool = True, enable_safety: bool = True):
        """Initialize agent coordinator"""
        self.enable_monitoring: bool = enable_monitoring
        self.enable_safety: bool = enable_safety
        self.agents: Dict[str, Any] = {}  # agent_id → agent instance
        self.agent_configs: Dict[str, AgentConfig] = {  # agent_id → config
            agent_id: config for agent_id, config in {}
        }
        self.agent_tasks: Dict[str, List[str]] = {}  # agent_id → list of task_ids
        self.initialized: bool = False

        # Safety framework integration
        if self.enable_safety:
            self.safety_framework = None  # Initialized in initialize()
            self.commitment_manager = None  # Initialized in initialize()

        # Monitoring
        self.metrics = {
            "agents_created": 0,
            "agents_active": 0,
            "tasks_executed": 0,
            "errors_encountered": 0
        }

        self.coordinator_id: str = f"coordinator_{uuid.uuid4().hex}"

    async def initialize(self) -> bool:
        """Initialize agent coordinator"""
        try:
            logger.info("Initializing AgentCoordinator...")

            # Initialize safety framework (if enabled)
            if self.enable_safety:
                from core.security.safety_framework import get_safety_framework
                # get_safety_framework is a SYNC factory. `await`-ing it raised
                # "object SafetyFramework can't be used in 'await' expression",
                # which initialize() swallowed -> returned False -> the
                # coordinator was handed back empty with zero agents.
                self.safety_framework = get_safety_framework()

            # Initialize memory agent (core agent, always needed)
            memory_agent = await get_memory_agent()
            await memory_agent.initialize()

            # Register memory agent in coordinator
            agent_id = getattr(memory_agent, 'agent_id', f"memory_{uuid.uuid4().hex}")
            await self.register_agent(
                agent=memory_agent,
                config=AgentConfig(
                    agent_id=agent_id,
                    agent_type=AgentType.MEMORY,
                    name="Memory Agent",
                    capabilities=["memory_storage", "memory_retrieval", "semantic_search"]
                ),
                agent_id=agent_id,
                capabilities=["memory_storage", "memory_retrieval", "semantic_search"]
            )

            # Create the specialist agents. create_research_agent() and
            # create_logical_agent() were defined but NEVER CALLED from
            # initialize(), so the coordinator only ever held the memory agent
            # -- and delegate_task("...", "research") found no suitable agent
            # and returned None for every research request.
            for factory in (self.create_research_agent, self.create_logical_agent):
                try:
                    await factory()
                except Exception as e:
                    # One specialist failing must not sink the coordinator, but
                    # it must be visible -- this is exactly the class of silent
                    # failure that hid the whole subsystem.
                    logger.error(f"{factory.__name__} failed: {e}", exc_info=True)

            self.initialized = True
            logger.info(f"AgentCoordinator initialized with {len(self.agents)} agents")
            return True

        except Exception as e:
            logger.error(f"AgentCoordinator initialization failed: {e}")
            return False

    async def create_memory_agent(self):
        """Create memory agent"""
        try:
            # Get memory agent (singleton)
            agent = await get_memory_agent(
                enable_monitoring=True
            )

            # Initialize agent
            if hasattr(agent, 'initialize'):
                await agent.initialize()
            else:
                logger.warning("MemoryAgent missing initialize()")

            # Create agent config (for registry)
            agent_id = getattr(agent, 'agent_id', f"memory_{uuid.uuid4().hex}")

            # Register agent
            await self.register_agent(
                agent=agent,
                config=AgentConfig(
                    agent_id=agent_id,
                    agent_type=AgentType.MEMORY,
                    name="Memory Agent",
                    capabilities=[
                        "memory_storage",
                        "memory_retrieval",
                        "semantic_search"
                    ]
                ),
                agent_id=agent_id,
                capabilities=[
                    "memory_storage",
                    "memory_retrieval",
                    "semantic_search"
                ]
            )

            logger.info("Memory agent created successfully")

        except Exception as e:
            logger.error(f"Failed to create memory agent: {e}")

    async def create_research_agent(self):
        """Create research agent"""
        try:
            agent = ResearchAgent()
            await agent.initialize()
            # ONE id for both the config and the registry key. These were two
            # independent uuid4() calls, so config.agent_id never matched the
            # key the agent was stored under -- breaking per-agent attribution.
            _agent_id_suffix = uuid.uuid4().hex
            _agent_id = f"research_{_agent_id_suffix}"

            await self.register_agent(
                agent=agent,
                config=AgentConfig(
                    agent_id=f"research_{_agent_id_suffix}",
                    agent_type=AgentType.RESEARCH,
                    name="Research Agent",
                    capabilities=[
                        "research",
                        "analysis",
                        "web_search",
                        "synthesis"
                    ]
                ),
                agent_id=_agent_id,
                capabilities=["research", "web_search", "synthesis"]
            )

            logger.info("Research agent created successfully")

        except Exception as e:
            logger.error(f"Failed to create research agent: {e}")

    async def create_logical_agent(self):
        """Create logical reasoning agent"""
        try:
            agent = LogicalAgent()
            if hasattr(agent, "initialize"):
                await agent.initialize()
            _agent_id_suffix = uuid.uuid4().hex
            _agent_id = f"logical_{_agent_id_suffix}"

            await self.register_agent(
                agent=agent,
                config=AgentConfig(
                    agent_id=f"logical_{_agent_id_suffix}",
                    agent_type=AgentType.LOGICAL,
                    name="Logical Agent",
                    capabilities=[
                        "formal_reasoning",
                        "theorem_proving",
                        "logic_verification"
                    ]
                ),
                agent_id=_agent_id,
                capabilities=["formal_reasoning", "theorem_proving", "logic_verification"]
            )

            logger.info("Logical agent created successfully")

        except Exception as e:
            logger.error(f"Failed to create logical agent: {e}")

    async def register_agent(
        self,
        agent: Any,
        config: AgentConfig,
        agent_id: str,
        capabilities: List[str]
    ) -> bool:
        """Register agent in coordinator"""
        try:
            # Store agent instance
            self.agents[agent_id] = agent
            self.agent_configs[agent_id] = config

            # Initialize task list
            if agent_id not in self.agent_tasks:
                self.agent_tasks[agent_id] = []

            # Update metrics
            self.metrics["agents_created"] = len(self.agents)

            logger.info(f"Agent {agent_id} ({config.agent_type.value}) registered with {len(capabilities)} capabilities")
            return True

        except Exception as e:
            logger.error(f"Failed to register agent {agent_id}: {e}")
            return False

    async def get_agent(self, agent_id: str) -> Optional[Any]:
        """Get agent by ID"""
        return self.agents.get(agent_id, None)

    async def get_agents_by_type(self, agent_type: AgentType) -> List[Any]:
        """Get all agents of specific type"""
        return [self.agents[agent_id] for agent_id in self.agents if self.agent_configs[agent_id].agent_type == agent_type]

    async def execute_task(
        self,
        agent_id: str,
        task: str,
        parameters: Dict[str, Any]
    ) -> Optional[Any]:
        """Execute task on agent"""
        try:
            if agent_id not in self.agents:
                logger.warning(f"Agent {agent_id} not found")
                return None
        except Exception:
            pass

        try:
            # Get agent
            agent = self.agents[agent_id]

            # Generate task ID
            task_id = f"task_{uuid.uuid4().hex}"
            task_timestamp = datetime.now()

            # Add task to agent's task list
            if agent_id not in self.agent_tasks:
                self.agent_tasks[agent_id] = []

            # Execute task based on agent type
            result = await agent.execute(task, parameters)

            # Update metrics
            self.metrics["tasks_executed"] = self.metrics.get("tasks_executed", 0) + 1

            return result

        except Exception as e:
            logger.error(f"Task execution failed for agent {agent_id}: {e}")
            self.metrics["errors_encountered"] = self.metrics.get("errors_encountered", 0) + 1
            return None

    async def get_agent_status(self, agent_id: str, include_tasks: bool) -> Optional[Dict[str, Any]]:
        """Get agent status"""
        # Check agent exists
        if agent_id not in self.agents or agent_id not in self.agent_configs:
            return None

        # Get config
        config = self.agent_configs[agent_id]
        agent = self.agents[agent_id]

        # Get agent health (if available)
        health_status = None
        if hasattr(agent, 'get_health'):
            health_status = await agent.get_health()

        # Get agent metrics (if available)
        agent_metrics = None
        if hasattr(agent, 'get_metrics'):
            agent_metrics = agent.get_metrics()

        return {
            "agent_id": agent_id,
            "agent_type": config.agent_type.value,
            "name": config.name,
            "is_active": config.is_active,
            "capabilities": config.capabilities,
            "health": health_status,
            "metrics": agent_metrics
        }

    async def shutdown_agent(self, agent_id: str, reason: str) -> bool:
        """Shutdown agent"""
        try:
            if agent_id not in self.agents:
                logger.warning(f"Agent {agent_id} not found")
                return False

            # Get agent
            agent = self.agents[agent_id]

            # Call shutdown if available
            if hasattr(agent, 'shutdown'):
                await agent.shutdown(reason)

            # Mark as inactive
            if agent_id in self.agent_configs:
                self.agent_configs[agent_id].is_active = False

            logger.info(f"Agent {agent_id} shutdown: {reason}")
            return True

        except Exception as e:
            logger.error(f"Failed to shutdown agent {agent_id}: {e}")
            return False

    async def remove_agent(self, agent_id: str, force: bool = False) -> bool:
        """Remove agent from coordinator"""
        try:
            # Shutdown agent first
            if not force:
                await self.shutdown_agent(agent_id, "removal")

            # Remove from registry
            if agent_id in self.agents:
                del self.agents[agent_id]

            if agent_id in self.agent_configs:
                del self.agent_configs[agent_id]

            # Clear tasks
            if agent_id in self.agent_tasks:
                del self.agent_tasks[agent_id]

            logger.info(f"Agent {agent_id} removed")
            return True

        except Exception as e:
            logger.error(f"Failed to remove agent {agent_id}: {e}")
            return False

    async def health_check(self):
        """Perform health check on all agents"""
        logger.info("Performing agent health check...")

        # Check each agent
        for agent_id in list(self.agents.keys()):
            try:
                agent = self.agents[agent_id]

                # Check if agent has health check method
                if hasattr(agent, 'health_check'):
                    is_healthy = await agent.health_check()

                    if not is_healthy:
                        logger.warning(f"Agent {agent_id} health check failed")
                else:
                    # Basic health check - verify agent is still in registry
                    is_healthy = agent_id in self.agents
                    if is_healthy:
                        logger.debug(f"Agent {agent_id} basic health check passed")
                    # If unhealthy, log warning
                    if not is_healthy:
                        logger.warning(f"Agent {agent_id} missing from registry")

            except Exception as e:
                logger.error(f"Health check error for {agent_id}: {e}")
                # Mark agent as unhealthy
                if agent_id in self.agent_configs:
                    self.agent_configs[agent_id].is_active = False

        logger.info("Agent health check complete")

    async def cleanup_inactive_agents(self, max_age_hours: int = 24):
        """Clean up inactive agents"""
        try:
            current_time = datetime.now()
            agents_removed = 0

            # Find inactive agents
            for agent_id in list(self.agents.keys()):
                config = self.agent_configs.get(agent_id)
                if config:
                    # Calculate age
                    age = (current_time - config.last_active).total_seconds() / 3600

                    if not config.is_active and age > max_age_hours:
                        # Remove inactive agent
                        await self.remove_agent(
                            agent_id=agent_id,
                            force=True
                        )
                        agents_removed += 1

            logger.info(f"Cleaned up {agents_removed} inactive agents")

        except Exception as e:
            logger.error(f"Cleanup error: {e}")

    async def delegate_task(
        self,
        task: str,
        task_type: str,
        parameters: Dict[str, Any],
        preferred_agent_id: str = ""
    ) -> Optional[Any]:
        """Delegate task to appropriate agent"""
        try:
            # If preferred agent specified, use it
            if preferred_agent_id and preferred_agent_id in self.agents:
                logger.info(f"Delegating task to preferred agent: {preferred_agent_id}")
                return await self.execute_task(
                    agent_id=preferred_agent_id,
                    task=task,
                    parameters=parameters
                )

            # Find suitable agent based on task type
            suitable_agent_id = None

            # Route based on task type
            task_type_lower = task_type.lower()
            if "memory" in task_type_lower:
                target_type = AgentType.MEMORY
            elif "research" in task_type_lower:
                target_type = AgentType.RESEARCH
            elif "logical" in task_type_lower:
                target_type = AgentType.LOGICAL
            else:
                target_type = None

            if target_type is not None:
                suitable_agent_id = next(
                    (aid for aid, cfg in self.agent_configs.items()
                     if cfg.agent_type == target_type and cfg.is_active),
                    None
                )

            if suitable_agent_id:
                logger.info(f"Delegating {task_type} task to agent: {suitable_agent_id}")
                return await self.execute_task(
                    agent_id=suitable_agent_id,
                    task=task,
                    parameters=parameters
                )
            else:
                logger.warning(f"No suitable agent found for task type: {task_type}")
                return None

        except Exception as e:
            logger.error(f"Task delegation failed: {e}")
            return None

    async def broadcast_message(
        self,
        message: str,
        agent_types: List[AgentType],
        metadata: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """Broadcast message to agents"""
        try:
            results = {}
            errors = []

            # Send to each agent type
            for agent_type in agent_types:
                agents = await self.get_agents_by_type(agent_type)

                for agent in agents:
                    try:
                        # Find agent ID
                        agent_id = [aid for aid, a in self.agents.items() if a == agent][0]

                        # Send message (if agent has message handler)
                        if hasattr(agent, 'handle_message'):
                            result = await agent.handle_message(
                                message=message,
                                metadata=metadata or {}
                            )
                            results[agent_id] = {
                                "status": "success",
                                "result": result
                            }
                    except Exception as e:
                        errors.append(str(e))

            logger.info(f"Broadcast message to {len(results)} agents")
            return {
                "message": message,
                "recipients": len(results),
                "results": results,
                "errors": errors if len(errors) > 0 else None
            }

        except Exception as e:
            logger.error(f"Broadcast failed: {e}")
            return {"error": str(e), "results": {}}

    async def get_statistics(self):
        """Get coordinator statistics"""
        try:
            agent_count = len(self.agents)
            active_agents = {}
            inactive_agents = {}

            for agent_id in self.agents.keys():
                # Get agent type
                agent_type = self.agent_configs.get(agent_id, '').agent_type.value if agent_id in self.agent_configs else 'unknown'
                active_agents[agent_type] = active_agents.get(agent_type, 0) + 1

                # Get agent status
                if agent_id in self.agent_configs:
                    config = self.agent_configs[agent_id]
                    if not config.is_active:
                        inactive_count = inactive_agents.get(agent_type, 0) if agent_type else 0
                        inactive_agents[agent_type] = inactive_count + 1

            return {
                "coordinator_id": self.coordinator_id,
                "total_agents": agent_count,
                "active_by_type": active_agents,
                "inactive_by_type": inactive_agents,
                "initialized": self.initialized
            }

        except Exception as e:
            logger.error(f"Statistics error: {e}")
            return {
                "coordinator_id": self.coordinator_id,
                "total_agents": {},
                "active_by_type": {},
                "inactive_by_type": {},
                "initialized": False
            }

    async def shutdown(self):
        """Shutdown coordinator and all agents"""
        logger.info("Shutting down AgentCoordinator...")

        # Shutdown all agents
        for agent_id in list(self.agents.keys()):
            try:
                await self.shutdown_agent(agent_id, "coordinator_shutdown")
            except Exception as e:
                logger.error(f"Error shutting down agent {agent_id}: {e}")

        # Clear registries
        self.agents.clear()
        for agent_id, config in self.agent_configs.items():
            try:
                # Mark agents as inactive
                config.is_active = False
                if hasattr(config, 'shutdown'):
                    await config.shutdown()
                # Clear agent tasks
                if agent_id in self.agent_tasks:
                    self.agent_tasks[agent_id].clear()
            except Exception as e:
                logger.error(f"Error during cleanup: {e}")


        logger.info("AgentCoordinator shutdown complete")


async def create_agent_coordinator(
    enable_monitoring: bool = True,
    enable_safety: bool = True
) -> AgentCoordinator:
    """Create and initialize agent coordinator"""
    coordinator = AgentCoordinator(enable_monitoring, enable_safety)
    await coordinator.initialize()
    return coordinator


# ---------------------------------------------------------------------------
# Singleton accessor
#
# There must be exactly ONE AgentCoordinator in the process. main.py and the
# delegate_task tool both need it, and two instances would split the agent
# registry the same way two SecurityAuditWorker instances split the findings
# store (252 vs 0) and two meta-learners split the posteriors. Same defect,
# same cost: authoritative state that silently disagrees with itself.
# ---------------------------------------------------------------------------

_agent_coordinator: Optional[AgentCoordinator] = None


async def get_agent_coordinator(
    enable_monitoring: bool = False,
    enable_safety: bool = True,
) -> AgentCoordinator:
    """Get the shared AgentCoordinator, initializing it on first use."""
    global _agent_coordinator
    if _agent_coordinator is None:
        _agent_coordinator = AgentCoordinator(enable_monitoring, enable_safety)
        if not await _agent_coordinator.initialize():
            # Do not hand back a half-built coordinator. initialize() used to
            # return False silently (the awaited-sync-factory bug) and callers
            # received an empty object with zero agents.
            raise RuntimeError("AgentCoordinator failed to initialize")
    return _agent_coordinator
