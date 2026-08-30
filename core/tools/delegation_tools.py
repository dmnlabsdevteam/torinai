#!/usr/bin/env python3
"""Agent delegation, exposed as a tool.

Deliberately a TOOL and not a new pipeline.

TorinAI already has exactly one validated execution path, and everything it
needs is on it:

  tool_registry.execute_tool
      -> safety_framework.evaluate_action        (the single safety gate)
      -> tool execution
      -> _record_safety_outcome_async            (closes the assessment)
      -> _record_tool_usage_outcome              (tool_usage_history)
      -> _fire_reward_signals                    (reward / cooldown)

Writing a second safety+credit path inside AgentCoordinator.execute_task would
have produced a parallel universe with its own gate and its own posteriors --
the same defect as the two SecurityAuditWorker instances (252 findings vs 0) and
the two meta-learning systems (_strategy_outcomes vs MetaLearner). Every one of
those cost real correctness.

As a tool, delegation gets the gate, the outcome record, the usage history and
the reward signal for free, and it is discoverable through the capability
system -- which also gives DELEGATE_TASK / COORDINATE_AGENTS a provider that
actually delegates, instead of TriggerSelfImprovementTool which runs an ASI
cycle when asked to delegate.
"""

import logging
from typing import Any, Dict, List, Optional

from core.tools.tool_registry import (
    Tool, ToolResult, ToolParameter, ToolCategory, ToolSafety,
)
from core.tools.capabilities import (
    Capability, CapabilityMetadata, ToolCapabilityProfile, RiskLevel,
)
from core.capability import CapabilityUnavailable

logger = logging.getLogger(__name__)

async def _get_coordinator():
    """The shared AgentCoordinator.

    Uses the module singleton rather than create_agent_coordinator(), which
    mints a NEW coordinator each call -- this tool and main.py would otherwise
    hold different agent registries.
    """
    from core.agents.agents import get_agent_coordinator
    return await get_agent_coordinator()


class DelegateTaskTool(Tool):
    """Delegate a task to the specialist agent best suited to it."""

    def __init__(self):
        super().__init__()
        self.name = "delegate_task"
        self.description = (
            "Delegate a task to a specialist agent (research, logical, memory). "
            "Use for work that benefits from a dedicated agent: literature/web "
            "research, formal proof, or memory retrieval."
        )
        self.category = ToolCategory.SYSTEM
        self.safety_level = ToolSafety.SAFE
        # DELEGATE_TASK and COORDINATE_AGENTS were declared ONLY by
        # TriggerSelfImprovementTool, whose execute() runs an ASI improvement
        # cycle -- so a planner searching for "delegate this" found a provider,
        # succeeded, and got self-improvement. Those false claims are removed;
        # the capability now belongs to the tool that actually delegates.
        self.capability_profile = ToolCapabilityProfile(
            tool_name="delegate_task",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.DELEGATE_TASK,
                    description="Delegate a subtask to the specialist agent suited to it",
                    input_types=["task", "task_type"],
                    output_types=["agent_result"],
                    latency="medium",
                    cost="medium",
                    reliability="high",
                    risk_level=RiskLevel.LOW,
                    priority=8,
                ),
                CapabilityMetadata(
                    capability=Capability.COORDINATE_AGENTS,
                    description="Route work across research, logical and memory agents",
                    input_types=["task", "task_type"],
                    output_types=["agent_result"],
                    latency="medium",
                    cost="medium",
                    reliability="high",
                    risk_level=RiskLevel.LOW,
                    priority=7,
                ),
            ],
        )
        self.parameters = [
            ToolParameter(
                name="task",
                type="string",
                description="What the agent should do, stated plainly.",
                required=True,
            ),
            ToolParameter(
                name="task_type",
                type="string",
                description=(
                    "Which specialist to use: 'research' (web/literature), "
                    "'logical' (formal proof), or 'memory' (recall)."
                ),
                required=True,
            ),
            ToolParameter(
                name="parameters",
                type="object",
                description="Optional parameters passed to the agent.",
                required=False,
            ),
        ]

    async def execute(
        self,
        task: str,
        task_type: str,
        parameters: Optional[Dict[str, Any]] = None,
    ) -> ToolResult:
        try:
            coordinator = await _get_coordinator()
            result = await coordinator.delegate_task(
                task=task,
                task_type=task_type,
                parameters=parameters or {},
            )

            if result is None:
                # Honest failure. delegate_task returns None both when no agent
                # matches and when the agent itself failed; either way no work
                # was done, so this must not report success.
                return ToolResult(
                    success=False,
                    output=None,
                    error=(
                        f"delegation failed: no result from a '{task_type}' agent. "
                        f"Available types: research, logical, memory."
                    ),
                    tool_name=self.name,
                    parameters={"task": task, "task_type": task_type},
                )

            return ToolResult(
                success=True,
                output=result,
                error=None,
                tool_name=self.name,
                parameters={"task": task, "task_type": task_type},
            )

        except CapabilityUnavailable as e:
            # An unimplemented agent capability is broken machinery, not a bad
            # delegation choice. Surfaced distinctly so the credit layer can
            # classify it as INFRASTRUCTURE_FAILURE rather than charging it.
            return ToolResult(
                success=False,
                output=None,
                error=f"capability_unavailable: {e}",
                tool_name=self.name,
                parameters={"task": task, "task_type": task_type},
            )
        except Exception as e:
            logger.error(f"delegate_task failed: {e}", exc_info=True)
            return ToolResult(
                success=False,
                output=None,
                error=f"delegation error: {e}",
                tool_name=self.name,
                parameters={"task": task, "task_type": task_type},
            )


def register_delegation_tools():
    """Register delegation tools (same shape as register_learning_tools)."""
    from core.tools import get_tool_registry

    registry = get_tool_registry()
    tools = [DelegateTaskTool()]
    for tool in tools:
        registry.register(tool)
        logger.info(f"✅ Registered delegation tool: {tool.name}")
    logger.info(f"✅ Registered {len(tools)} delegation tool(s)")
    return len(tools)


__all__ = ["DelegateTaskTool", "register_delegation_tools"]
