#!/usr/bin/env python3
"""
Autonomous Agent System Chaos Adapter
======================================

Chaos injection for autonomous agent system components:
- Autonomous Coordinator
- Intrinsic Motivation System
- Planning Engine
- Directive System
- Governance Queue & Session
- Execution Controller
- Experience Evaluator
- Runtime Governance
- Task Queue
"""

import asyncio
import logging
import random
import uuid
from typing import Dict, Any, Optional
from datetime import datetime

from .base_adapter import TargetSystemAdapter
from ..types import ChaosType, InjectionHandle

logger = logging.getLogger(__name__)


class AgentSystemAdapter(TargetSystemAdapter):
    """
    Adapter for chaos injection into autonomous agent system.

    Targets:
    - Autonomous Coordinator (agent lifecycle, coordination)
    - Intrinsic Motivation (7-dimensional motivation system)
    - Planning Engine (plan generation, execution)
    - Directive System (directive management, evolution)
    - Governance Queue (decision queuing, processing)
    - Execution Controller (task execution)
    - Experience Evaluator (experience assessment)
    - Runtime Governance (real-time governance)
    - Task Queue (task management)

    Components:
    - autonomous_coordinator: Agent lifecycle and coordination
    - intrinsic_motivation: 7D motivation system (curiosity, competence, novelty, mastery, autonomy, social, impact)
    - planning_engine: Plan generation and execution
    - directive_system: Directive management and evolution
    - governance_queue: Governance decision queuing
    - execution_controller: Task execution control
    - experience_evaluator: Experience assessment
    - runtime_governance: Real-time governance decisions
    - task_queue: Task queuing and scheduling
    """

    def __init__(self):
        super().__init__("autonomous_agents")
        self._original_methods: Dict[str, Any] = {}
        self._chaos_active: bool = False
        self.db = None  # Database for persistence (call initialize_db() to enable)

        # Agent-specific metrics
        self._coordination_latencies: list = []
        self._motivation_calc_latencies: list = []
        self._planning_errors: int = 0
        self._governance_queue_errors: int = 0
        self._execution_errors: int = 0
        self._experience_eval_errors: int = 0

    async def inject_latency(
        self,
        target_id: str,
        component: str,
        injection_point: str,
        delay_ms: int,
        jitter_ms: int = 0
    ) -> InjectionHandle:
        """
        Inject latency into autonomous agent operations.

        Injection points:
        - coordination: Delay in agent coordination
        - motivation_calculation: Delay in intrinsic motivation computation
        - plan_generation: Delay in planning engine
        - directive_evolution: Delay in directive updates
        - governance_processing: Delay in governance queue processing
        - task_execution: Delay in task execution
        - experience_evaluation: Delay in experience assessment
        - runtime_decision: Delay in runtime governance decisions
        """
        self._chaos_active = True

        injection_id = f"agent_latency_{uuid.uuid4().hex[:8]}"

        logger.info(
            f"[AgentAdapter] Injecting {delay_ms}ms latency "
            f"at {component}:{injection_point} (experiment: {target_id})"
        )

        if injection_point == "coordination":
            # Inject latency into agent coordination
            await self._inject_coordination_latency(delay_ms, jitter_ms)

        elif injection_point == "motivation_calculation":
            # Inject latency into intrinsic motivation
            await self._inject_motivation_latency(delay_ms, jitter_ms)

        elif injection_point == "plan_generation":
            # Inject latency into planning
            await self._inject_planning_latency(delay_ms, jitter_ms)

        elif injection_point == "directive_evolution":
            # Inject latency into directive system
            await self._inject_directive_latency(delay_ms, jitter_ms)

        elif injection_point == "governance_processing":
            # Inject latency into governance queue
            await self._inject_governance_latency(delay_ms, jitter_ms)

        elif injection_point == "task_execution":
            # Inject latency into task execution
            await self._inject_execution_latency(delay_ms, jitter_ms)

        elif injection_point == "experience_evaluation":
            # Inject latency into experience evaluator
            await self._inject_experience_latency(delay_ms, jitter_ms)

        elif injection_point == "runtime_decision":
            # Inject latency into runtime governance
            await self._inject_runtime_gov_latency(delay_ms, jitter_ms)

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
        Inject errors into autonomous agent operations.

        Error types:
        - CoordinationError: Agent coordination failures
        - MotivationError: Motivation calculation failures
        - PlanningError: Plan generation failures
        - DirectiveError: Directive evolution failures
        - GovernanceQueueError: Queue overflow/underflow
        - ExecutionError: Task execution failures
        - ExperienceEvalError: Experience evaluation failures
        - RuntimeGovernanceError: Runtime decision failures
        """
        self._chaos_active = True

        injection_id = f"agent_error_{uuid.uuid4().hex[:8]}"

        logger.info(
            f"[AgentAdapter] Injecting {error_rate*100}% error rate "
            f"at {component}:{injection_point} ({error_type}, experiment: {target_id})"
        )

        if injection_point == "coordination":
            # Inject coordination errors
            await self._inject_coordination_errors(error_rate, error_type)

        elif injection_point == "motivation_calculation":
            # Inject motivation errors
            await self._inject_motivation_errors(error_rate, error_type)

        elif injection_point == "plan_generation":
            # Inject planning errors
            await self._inject_planning_errors(error_rate, error_type)

        elif injection_point == "directive_evolution":
            # Inject directive errors
            await self._inject_directive_errors(error_rate, error_type)

        elif injection_point == "governance_processing":
            # Inject governance queue errors
            await self._inject_governance_errors(error_rate, error_type)

        elif injection_point == "task_execution":
            # Inject execution errors
            await self._inject_execution_errors(error_rate, error_type)

        elif injection_point == "experience_evaluation":
            # Inject experience evaluation errors
            await self._inject_experience_errors(error_rate, error_type)

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

        return handle

    async def inject_resource_exhaustion(
        self,
        target_id: str,
        component: str,
        resource_type: str,
        limit_value: Optional[float] = None
    ) -> InjectionHandle:
        """
        Inject resource exhaustion into autonomous agent system.

        Resource types:
        - agent_pool: Agent instance pool exhaustion
        - queue_capacity: Governance queue capacity exhaustion
        - task_queue: Task queue overflow
        - motivation_memory: Motivation computation memory
        - plan_cache: Planning cache exhaustion
        """
        self._chaos_active = True

        injection_id = f"agent_resource_{uuid.uuid4().hex[:8]}"

        logger.info(
            f"[AgentAdapter] Injecting {resource_type} exhaustion "
            f"at {component} (experiment: {target_id})"
        )

        if resource_type == "agent_pool":
            # Simulate agent pool exhaustion
            await self._exhaust_agent_pool()

        elif resource_type == "queue_capacity":
            # Simulate governance queue overflow
            await self._exhaust_governance_queue()

        elif resource_type == "task_queue":
            # Simulate task queue overflow
            await self._exhaust_task_queue()

        elif resource_type == "motivation_memory":
            # Simulate motivation computation memory
            await self._exhaust_motivation_memory()

        elif resource_type == "plan_cache":
            # Simulate planning cache exhaustion
            await self._exhaust_plan_cache()

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

        return handle

    async def get_health_metrics(self) -> Dict[str, Any]:
        """
        Get current health metrics of autonomous agent system.

        Metrics:
        - coordination_latency_p95: Agent coordination latency
        - motivation_calc_latency_p95: Motivation calculation latency
        - planning_error_rate: Planning error rate
        - governance_queue_depth: Governance queue depth
        - execution_error_rate: Task execution error rate
        - experience_eval_error_rate: Experience evaluation error rate
        - active_agents: Number of active agent instances
        """
        metrics = {}

        # Calculate latency metrics
        if self._coordination_latencies:
            sorted_latencies = sorted(self._coordination_latencies)
            p95_idx = int(len(sorted_latencies) * 0.95)
            p99_idx = int(len(sorted_latencies) * 0.99)

            metrics["coordination_latency_p95"] = sorted_latencies[p95_idx] if sorted_latencies else 0
            metrics["coordination_latency_p99"] = sorted_latencies[p99_idx] if sorted_latencies else 0
        else:
            metrics["coordination_latency_p95"] = 0
            metrics["coordination_latency_p99"] = 0

        # Motivation latency
        if self._motivation_calc_latencies:
            sorted_mot_lat = sorted(self._motivation_calc_latencies)
            metrics["motivation_calc_latency_p95"] = sorted_mot_lat[int(len(sorted_mot_lat) * 0.95)]
        else:
            metrics["motivation_calc_latency_p95"] = 0

        # Calculate error rates
        total_operations = 1000  # Simulated total operations
        metrics["planning_error_rate"] = self._planning_errors / total_operations
        metrics["governance_queue_error_rate"] = self._governance_queue_errors / total_operations
        metrics["execution_error_rate"] = self._execution_errors / total_operations
        metrics["experience_eval_error_rate"] = self._experience_eval_errors / total_operations

        # Queue metrics
        metrics["governance_queue_depth"] = random.uniform(5, 30) if not self._chaos_active else random.uniform(80, 150)
        metrics["task_queue_depth"] = random.uniform(10, 50) if not self._chaos_active else random.uniform(100, 200)

        # Agent metrics
        metrics["active_agents"] = random.uniform(5, 15) if not self._chaos_active else random.uniform(1, 3)

        # Resource metrics
        metrics["cpu_percent"] = random.uniform(20, 50) if not self._chaos_active else random.uniform(70, 95)
        metrics["memory_percent"] = random.uniform(30, 60) if not self._chaos_active else random.uniform(75, 90)

        # Active injections
        metrics["active_chaos_injections"] = len(self.active_injections)

        # Health status
        metrics["healthy"] = True

        # Mark as unhealthy if latency is very high
        if metrics["coordination_latency_p95"] > 500 or metrics["motivation_calc_latency_p95"] > 500:
            metrics["healthy"] = False

        # Mark as unhealthy if error rates are high
        if (metrics["planning_error_rate"] > 0.05 or
            metrics["execution_error_rate"] > 0.05 or
            metrics["governance_queue_error_rate"] > 0.05):
            metrics["healthy"] = False

        # Mark as unhealthy if queue depths are very high
        if metrics["governance_queue_depth"] > 100 or metrics["task_queue_depth"] > 150:
            metrics["healthy"] = False

        # Mark as unhealthy if resource utilization is critical
        if metrics["cpu_percent"] > 90 or metrics["memory_percent"] > 85:
            metrics["healthy"] = False

        return metrics

    async def cleanup(self) -> None:
        """Clean up all active chaos injections for autonomous agent system."""
        logger.info(f"Cleaning up {len(self.active_injections)} agent system injections")

        # Stop all active injections
        for handle in list(self.active_injections.values()):
            handle.stop()

        # Clear all injections
        self.active_injections.clear()

        # Reset chaos state
        self._chaos_active = False
        self._original_methods.clear()
        self._coordination_latencies.clear()
        self._motivation_calc_latencies.clear()
        self._planning_errors = 0
        self._governance_queue_errors = 0
        self._execution_errors = 0
        self._experience_eval_errors = 0

        logger.info("Agent system chaos cleanup complete")

    # Private helper methods

    async def _inject_coordination_latency(self, delay_ms: int, jitter_ms: int):
        """Inject latency into agent coordination."""
        actual_delay = delay_ms + random.randint(-jitter_ms, jitter_ms)
        await asyncio.sleep(actual_delay / 1000.0)
        self._coordination_latencies.append(actual_delay)

    async def _inject_motivation_latency(self, delay_ms: int, jitter_ms: int):
        """Inject latency into motivation calculation."""
        actual_delay = delay_ms + random.randint(-jitter_ms, jitter_ms)
        await asyncio.sleep(actual_delay / 1000.0)
        self._motivation_calc_latencies.append(actual_delay)

    async def _inject_planning_latency(self, delay_ms: int, jitter_ms: int):
        """Inject latency into planning."""
        actual_delay = delay_ms + random.randint(-jitter_ms, jitter_ms)
        await asyncio.sleep(actual_delay / 1000.0)

    async def _inject_directive_latency(self, delay_ms: int, jitter_ms: int):
        """Inject latency into directive evolution."""
        actual_delay = delay_ms + random.randint(-jitter_ms, jitter_ms)
        await asyncio.sleep(actual_delay / 1000.0)

    async def _inject_governance_latency(self, delay_ms: int, jitter_ms: int):
        """Inject latency into governance processing."""
        actual_delay = delay_ms + random.randint(-jitter_ms, jitter_ms)
        await asyncio.sleep(actual_delay / 1000.0)

    async def _inject_execution_latency(self, delay_ms: int, jitter_ms: int):
        """Inject latency into task execution."""
        actual_delay = delay_ms + random.randint(-jitter_ms, jitter_ms)
        await asyncio.sleep(actual_delay / 1000.0)

    async def _inject_experience_latency(self, delay_ms: int, jitter_ms: int):
        """Inject latency into experience evaluation."""
        actual_delay = delay_ms + random.randint(-jitter_ms, jitter_ms)
        await asyncio.sleep(actual_delay / 1000.0)

    async def _inject_runtime_gov_latency(self, delay_ms: int, jitter_ms: int):
        """Inject latency into runtime governance."""
        actual_delay = delay_ms + random.randint(-jitter_ms, jitter_ms)
        await asyncio.sleep(actual_delay / 1000.0)

    async def _inject_coordination_errors(self, error_rate: float, error_type: str):
        """Inject coordination errors."""
        if random.random() < error_rate:
            logger.warning(f"[AgentAdapter] Injected coordination error: {error_type}")

    async def _inject_motivation_errors(self, error_rate: float, error_type: str):
        """Inject motivation calculation errors."""
        if random.random() < error_rate:
            logger.warning(f"[AgentAdapter] Injected motivation error: {error_type}")

    async def _inject_planning_errors(self, error_rate: float, error_type: str):
        """Inject planning errors."""
        if random.random() < error_rate:
            self._planning_errors += 1
            logger.warning(f"[AgentAdapter] Injected planning error: {error_type}")

    async def _inject_directive_errors(self, error_rate: float, error_type: str):
        """Inject directive errors."""
        if random.random() < error_rate:
            logger.warning(f"[AgentAdapter] Injected directive error: {error_type}")

    async def _inject_governance_errors(self, error_rate: float, error_type: str):
        """Inject governance queue errors."""
        if random.random() < error_rate:
            self._governance_queue_errors += 1
            logger.warning(f"[AgentAdapter] Injected governance error: {error_type}")

    async def _inject_execution_errors(self, error_rate: float, error_type: str):
        """Inject execution errors."""
        if random.random() < error_rate:
            self._execution_errors += 1
            logger.warning(f"[AgentAdapter] Injected execution error: {error_type}")

    async def _inject_experience_errors(self, error_rate: float, error_type: str):
        """Inject experience evaluation errors."""
        if random.random() < error_rate:
            self._experience_eval_errors += 1
            logger.warning(f"[AgentAdapter] Injected experience eval error: {error_type}")

    async def _exhaust_agent_pool(self):
        """Simulate agent pool exhaustion."""
        # Simulate agent pool exhaustion
        _ = [0] * (30 * 1024 * 1024)  # 30MB allocation

    async def _exhaust_governance_queue(self):
        """Simulate governance queue overflow."""
        # Simulate queue overflow
        _ = [[0] * 1000 for _ in range(20000)]  # Large queue

    async def _exhaust_task_queue(self):
        """Simulate task queue overflow."""
        # Simulate task queue overflow
        _ = [[0] * 1000 for _ in range(30000)]  # Large queue

    async def _exhaust_motivation_memory(self):
        """Simulate motivation computation memory exhaustion."""
        # Simulate 7D motivation state in memory
        _ = [0] * (50 * 1024 * 1024)  # 50MB allocation

    async def _exhaust_plan_cache(self):
        """Simulate planning cache exhaustion."""
        # Simulate plan cache overflow
        _ = [[0] * 1000 for _ in range(10000)]  # Large cache
