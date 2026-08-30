#!/usr/bin/env python3
"""
Chaos Engineering Tools
=======================

Tools for chaos engineering experiments.
Exposes the chaos framework through the tool system.
"""

import asyncio
import logging
from typing import Dict, List, Optional

from .tool_registry import Tool, ToolResult
from .capabilities import (
    Capability,
    CapabilityMetadata,
    ToolCapabilityProfile,
    RiskLevel
)
from ..chaos.orchestrator import get_orchestrator
from ..chaos.experiment_manager import get_experiment_manager
from ..chaos.types import ChaosType, InjectionConfig, Hypothesis
from ..chaos.scenarios import get_scenario, list_all_scenarios, get_scenarios_by_system

logger = logging.getLogger(__name__)


class CreateChaosExperimentTool(Tool):
    """
    Create a chaos experiment with safety controls.

    This tool creates a chaos experiment that will go through governance approval
    before execution. All experiments require pre-flight checks and SLO monitoring.
    """

    name = "create_chaos_experiment"
    description = "Create a chaos experiment for testing system resilience"

    def __init__(self):
        super().__init__()

        # Capability declarations
        self.capability_profile = ToolCapabilityProfile(
            tool_name="create_chaos_experiment",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.DESIGN_EXPERIMENT,
                    description="Design chaos experiments to test hypotheses",
                    input_types=["experiment_spec"],
                    output_types=["experiment_id"],
                    latency="low",
                    cost="low",
                    reliability="high",
                    risk_level=RiskLevel.MEDIUM,  # Creating experiments requires approval
                    priority=9
                ),
                CapabilityMetadata(
                    capability=Capability.TEST_RESILIENCE,
                    description="Test system resilience through chaos engineering",
                    input_types=["experiment_spec"],
                    output_types=["experiment_id"],
                    latency="low",
                    cost="low",
                    reliability="high",
                    risk_level=RiskLevel.MEDIUM,
                    priority=8
                )
            ],
            requires_filesystem=False,
            requires_network=False,
            requires_database=True,
            is_idempotent=False  # Creating experiments has side effects
        )

    parameters = {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Experiment name"
            },
            "description": {
                "type": "string",
                "description": "Detailed experiment description"
            },
            "target_system": {
                "type": "string",
                "enum": [
                    "tool_system",
                    "learning_system",
                    "security_system",
                    "reasoning_system",
                    "autonomous_agents",
                    "domain_system",
                    "memory_system",
                    "intelligence_system",
                    "monitoring_system",
                    "services_system"
                ],
                "description": "Target system to inject chaos into"
            },
            "chaos_type": {
                "type": "string",
                "enum": [
                    "LATENCY",
                    "ERROR",
                    "RESOURCE_EXHAUSTION",
                    "PARTIAL_FAILURE",
                    "NETWORK_PARTITION",
                    "TIMEOUT",
                    "RATE_LIMIT",
                    "DATA_CORRUPTION"
                ],
                "description": "Type of chaos to inject"
            },
            "component": {
                "type": "string",
                "description": "Component within target system"
            },
            "injection_point": {
                "type": "string",
                "description": "Specific injection point"
            },
            "environment": {
                "type": "string",
                "enum": ["dev", "staging", "production"],
                "description": "Environment to run experiment in"
            },
            "blast_radius": {
                "type": "integer",
                "minimum": 1,
                "maximum": 100,
                "description": "Percentage of traffic to affect (1-100)"
            },
            "duration_seconds": {
                "type": "integer",
                "minimum": 60,
                "maximum": 3600,
                "description": "Experiment duration in seconds"
            },
            "delay_ms": {
                "type": "integer",
                "description": "Latency delay in milliseconds (for LATENCY type)"
            },
            "error_rate": {
                "type": "number",
                "minimum": 0,
                "maximum": 1,
                "description": "Error rate 0-1 (for ERROR type)"
            },
            "hypothesis": {
                "type": "object",
                "description": "Optional hypothesis to validate",
                "properties": {
                    "statement": {"type": "string"},
                    "max_latency_p95_ms": {"type": "number"},
                    "max_error_rate": {"type": "number"}
                }
            }
        },
        "required": [
            "name",
            "description",
            "target_system",
            "chaos_type",
            "component",
            "injection_point",
            "environment",
            "blast_radius",
            "duration_seconds"
        ]
    }

    async def execute(self, **kwargs) -> Dict:
        """Execute the tool"""
        try:
            orchestrator = get_orchestrator()

            # Build injection config
            chaos_type = ChaosType[kwargs["chaos_type"]]
            injection_config = InjectionConfig(
                component=kwargs["component"],
                injection_point=kwargs["injection_point"],
                chaos_type=chaos_type,
                delay_ms=kwargs.get("delay_ms", 0),
                jitter_ms=kwargs.get("jitter_ms", 0),
                error_type=kwargs.get("error_type", "GenericError"),
                error_rate=kwargs.get("error_rate", 0.1),
                resource_type=kwargs.get("resource_type", "cpu"),
                limit_value=kwargs.get("limit_value")
            )

            # Build hypothesis if provided
            hypothesis = None
            if "hypothesis" in kwargs:
                h = kwargs["hypothesis"]
                hypothesis = {
                    "hypothesis_statement": h.get("statement", ""),
                    "expected_behavior": {
                        "max_latency_p95_ms": h.get("max_latency_p95_ms", 500),
                        "max_error_rate": h.get("max_error_rate", 0.01)
                    }
                }

            # Create experiment
            experiment = await orchestrator.create_experiment(
                name=kwargs["name"],
                description=kwargs["description"],
                target_system=kwargs["target_system"],
                chaos_type=chaos_type,
                environment=kwargs["environment"],
                injection_config=injection_config,
                blast_radius=kwargs["blast_radius"],
                hypothesis=hypothesis,
                requires_governance=True
            )

            return ToolResult(
                success=True,
                output={
                    "experiment_id": experiment.experiment_id,
                    "name": experiment.name,
                    "status": experiment.status.value,
                    "governance_tier": experiment.governance_tier,
                    "message": f"Chaos experiment created: {experiment.experiment_id}. "
                              f"Requires {experiment.governance_tier} governance approval before execution."
                }
            )

        except Exception as e:
            logger.error(f"Failed to create chaos experiment: {e}")
            return ToolResult(
                success=False,
                output=None,
                error=str(e)
            )


class RunChaosExperimentTool(Tool):
    """
    Run an approved chaos experiment.

    This tool executes a chaos experiment that has been approved by governance.
    It includes pre-flight checks, SLO monitoring, and automatic rollback.
    """

    name = "run_chaos_experiment"
    description = "Execute an approved chaos experiment with safety controls"

    def __init__(self):
        super().__init__()

        # Capability declarations
        self.capability_profile = ToolCapabilityProfile(
            tool_name="run_chaos_experiment",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.RUN_EXPERIMENT,
                    description="Execute chaos experiments",
                    input_types=["experiment_id"],
                    output_types=["experiment_results"],
                    latency="high",
                    cost="medium",
                    reliability="high",
                    risk_level=RiskLevel.HIGH,  # Running experiments affects production
                    approval_level="team_lead",
                    priority=10
                ),
                CapabilityMetadata(
                    capability=Capability.INJECT_FAILURE,
                    description="Inject failures for resilience testing",
                    input_types=["experiment_id"],
                    output_types=["experiment_results"],
                    latency="high",
                    cost="medium",
                    reliability="high",
                    risk_level=RiskLevel.HIGH,
                    approval_level="team_lead",
                    priority=9
                ),
                CapabilityMetadata(
                    capability=Capability.COLLECT_EVIDENCE,
                    description="Collect evidence from experiments",
                    input_types=["experiment_id"],
                    output_types=["metrics", "evidence"],
                    latency="medium",
                    cost="low",
                    reliability="high",
                    risk_level=RiskLevel.LOW,
                    priority=7
                )
            ],
            requires_filesystem=False,
            requires_network=False,
            requires_database=True,
            is_idempotent=False  # Running experiments is NOT idempotent
        )

    parameters = {
        "type": "object",
        "properties": {
            "experiment_id": {
                "type": "string",
                "description": "Experiment ID to run"
            },
            "progressive_rollout": {
                "type": "boolean",
                "description": "Use progressive rollout (canary → gradual → full)",
                "default": True
            }
        },
        "required": ["experiment_id"]
    }

    async def execute(self, **kwargs) -> Dict:
        """Execute the tool"""
        try:
            orchestrator = get_orchestrator()
            experiment_id = kwargs["experiment_id"]
            progressive_rollout = kwargs.get("progressive_rollout", True)

            # Run experiment
            result = await orchestrator.run_experiment(
                experiment_id=experiment_id,
                progressive_rollout=progressive_rollout
            )

            return ToolResult(
                success=result.success,
                output={
                    "experiment_id": experiment_id,
                    "metrics_collected": len(result.metrics_collected),
                    "hypothesis_validated": result.hypothesis_validated,
                    "rollback_triggered": result.rollback_triggered,
                    "insights": result.insights,
                    "message": f"Experiment {'completed successfully' if result.success else 'failed or rolled back'}"
                }
            )

        except Exception as e:
            logger.error(f"Failed to run chaos experiment: {e}")
            return ToolResult(
                success=False,
                output=None,
                error=str(e)
            )


class CreateChaosExperimentFromScenarioTool(Tool):
    """
    Create a chaos experiment from a pre-defined scenario.

    This tool creates experiments from the scenario library, which contains
    battle-tested chaos scenarios for all 7 target systems.
    """

    name = "create_chaos_experiment_from_scenario"
    description = "Create a chaos experiment from a pre-defined scenario template"

    def __init__(self):
        super().__init__()

        # Capability declarations
        self.capability_profile = ToolCapabilityProfile(
            tool_name="create_chaos_experiment_from_scenario",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.DESIGN_EXPERIMENT,
                    description="Design experiments from pre-defined scenarios",
                    input_types=["scenario_name"],
                    output_types=["experiment_id"],
                    latency="low",
                    cost="low",
                    reliability="high",
                    risk_level=RiskLevel.MEDIUM,
                    priority=8
                ),
                CapabilityMetadata(
                    capability=Capability.TEST_RESILIENCE,
                    description="Test resilience using battle-tested scenarios",
                    input_types=["scenario_name"],
                    output_types=["experiment_id"],
                    latency="low",
                    cost="low",
                    reliability="high",
                    risk_level=RiskLevel.MEDIUM,
                    priority=9  # Prefer scenarios over custom experiments
                )
            ],
            requires_filesystem=False,
            requires_network=False,
            requires_database=True,
            is_idempotent=False
        )

    parameters = {
        "type": "object",
        "properties": {
            "scenario_name": {
                "type": "string",
                "description": "Scenario identifier (e.g., 'tool_registry_latency')"
            },
            "environment": {
                "type": "string",
                "enum": ["dev", "staging", "production"],
                "description": "Environment override (optional)"
            },
            "blast_radius": {
                "type": "integer",
                "minimum": 1,
                "maximum": 100,
                "description": "Blast radius override (optional)"
            }
        },
        "required": ["scenario_name"]
    }

    async def execute(self, **kwargs) -> Dict:
        """Execute the tool"""
        try:
            experiment_manager = get_experiment_manager()
            scenario_name = kwargs["scenario_name"]

            # Get scenario
            scenario = get_scenario(scenario_name)

            # Apply overrides
            if "environment" in kwargs:
                scenario["environment"] = kwargs["environment"]
            if "blast_radius" in kwargs:
                scenario["blast_radius"] = kwargs["blast_radius"]

            # Create experiment from scenario
            experiment = await experiment_manager.create_experiment_from_scenario(
                scenario_id=scenario_name,
                environment=scenario.get("environment"),
                blast_radius=scenario.get("blast_radius")
            )

            return ToolResult(
                success=True,
                output={
                    "experiment_id": experiment.experiment_id,
                    "name": experiment.name,
                    "scenario": scenario_name,
                    "target_system": experiment.target_system,
                    "status": experiment.status.value,
                    "governance_tier": experiment.governance_tier,
                    "message": f"Chaos experiment created from scenario '{scenario_name}': {experiment.experiment_id}"
                }
            )

        except KeyError as e:
            scenario_name_str = kwargs.get("scenario_name", "unknown")
            return ToolResult(
                success=False,
                output=None,
                error=f"Scenario not found: {scenario_name_str}"
            )
        except Exception as e:
            logger.error(f"Failed to create experiment from scenario: {e}")
            return ToolResult(
                success=False,
                output=None,
                error=str(e)
            )


class ListChaosScenariosTool(Tool):
    """
    List all available chaos scenarios.

    This tool lists all pre-defined chaos scenarios organized by target system.
    """

    name = "list_chaos_scenarios"
    description = "List all available chaos experiment scenarios"

    def __init__(self):
        super().__init__()

        # Capability declarations
        self.capability_profile = ToolCapabilityProfile(
            tool_name="list_chaos_scenarios",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.QUERY_KNOWLEDGE,
                    description="Query available chaos scenarios",
                    input_types=["target_system"],
                    output_types=["scenario_list"],
                    latency="low",
                    cost="low",
                    reliability="high",
                    risk_level=RiskLevel.LOW,
                    priority=7
                )
            ],
            requires_filesystem=False,
            requires_network=False,
            requires_database=False,
            is_idempotent=True
        )

    parameters = {
        "type": "object",
        "properties": {
            "target_system": {
                "type": "string",
                "enum": [
                    "tool_system",
                    "learning_system",
                    "security_system",
                    "reasoning_system",
                    "autonomous_agents",
                    "domain_system",
                    "memory_system",
                    "intelligence_system",
                    "monitoring_system",
                    "services_system"
                ],
                "description": "Filter by target system (optional)"
            }
        },
        "required": []
    }

    async def execute(self, **kwargs) -> Dict:
        """Execute the tool"""
        try:
            target_system = kwargs.get("target_system")

            if target_system:
                # Get scenarios for specific system
                scenarios = get_scenarios_by_system(target_system)
                scenario_list = [
                    {
                        "name": s["name"],
                        "description": s["description"],
                        "chaos_type": s["chaos_type"].value,
                        "blast_radius": s["blast_radius"],
                        "environment": s["environment"]
                    }
                    for s in scenarios
                ]

                return ToolResult(
                    success=True,
                    output={
                        "target_system": target_system,
                        "scenario_count": len(scenario_list),
                        "scenarios": scenario_list
                    }
                )
            else:
                # Get all scenarios grouped by system
                all_scenarios = list_all_scenarios()

                return ToolResult(
                    success=True,
                    output={
                        "total_scenarios": sum(len(v) for v in all_scenarios.values()),
                        "scenarios_by_system": {
                            system: {
                                "count": len(scenarios),
                                "scenario_names": scenarios
                            }
                            for system, scenarios in all_scenarios.items()
                        }
                    }
                )

        except Exception as e:
            logger.error(f"Failed to list chaos scenarios: {e}")
            return ToolResult(
                success=False,
                output=None,
                error=str(e)
            )


class GetChaosExperimentStatusTool(Tool):
    """
    Get the status of a chaos experiment.

    This tool retrieves the current status of a chaos experiment including
    governance approval status, execution progress, and metrics.
    """

    name = "get_chaos_experiment_status"
    description = "Get the current status of a chaos experiment"

    def __init__(self):
        super().__init__()

        # Capability declarations
        self.capability_profile = ToolCapabilityProfile(
            tool_name="get_chaos_experiment_status",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.TRACK_PROGRESS,
                    description="Track experiment progress",
                    input_types=["experiment_id"],
                    output_types=["status_report"],
                    latency="low",
                    cost="low",
                    reliability="high",
                    risk_level=RiskLevel.LOW,
                    priority=8
                ),
                CapabilityMetadata(
                    capability=Capability.MONITOR_METRICS,
                    description="Monitor experiment metrics",
                    input_types=["experiment_id"],
                    output_types=["metrics"],
                    latency="low",
                    cost="low",
                    reliability="high",
                    risk_level=RiskLevel.LOW,
                    priority=7
                )
            ],
            requires_filesystem=False,
            requires_network=False,
            requires_database=True,
            is_idempotent=True
        )

    parameters = {
        "type": "object",
        "properties": {
            "experiment_id": {
                "type": "string",
                "description": "Experiment ID"
            }
        },
        "required": ["experiment_id"]
    }

    async def execute(self, **kwargs) -> Dict:
        """Execute the tool"""
        try:
            orchestrator = get_orchestrator()
            experiment_id = kwargs["experiment_id"]

            status = await orchestrator.get_experiment_status(experiment_id)

            return ToolResult(
                success=True,
                output=status
            )

        except ValueError as e:
            return ToolResult(
                success=False,
                output=None,
                error=str(e)
            )
        except Exception as e:
            logger.error(f"Failed to get experiment status: {e}")
            return ToolResult(
                success=False,
                output=None,
                error=str(e)
            )


class RollbackChaosExperimentTool(Tool):
    """
    Manually rollback a running chaos experiment.

    This tool triggers an immediate rollback of a running experiment,
    stopping all chaos injection and restoring normal operation.
    """

    name = "rollback_chaos_experiment"
    description = "Manually rollback a running chaos experiment"

    def __init__(self):
        super().__init__()

        # Capability declarations
        self.capability_profile = ToolCapabilityProfile(
            tool_name="rollback_chaos_experiment",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.SELF_REPAIR,
                    description="Rollback experiments to restore normal operation",
                    input_types=["experiment_id", "reason"],
                    output_types=["rollback_status"],
                    latency="low",
                    cost="low",
                    reliability="high",
                    risk_level=RiskLevel.HIGH,  # Rollback affects running experiments
                    approval_level="team_lead",
                    priority=10
                ),
                CapabilityMetadata(
                    capability=Capability.CONTINGENCY_PLAN,
                    description="Execute contingency plans (rollback)",
                    input_types=["experiment_id", "reason"],
                    output_types=["rollback_status"],
                    latency="low",
                    cost="low",
                    reliability="high",
                    risk_level=RiskLevel.HIGH,
                    priority=9
                )
            ],
            requires_filesystem=False,
            requires_network=False,
            requires_database=True,
            is_idempotent=True  # Rollback is idempotent
        )

    parameters = {
        "type": "object",
        "properties": {
            "experiment_id": {
                "type": "string",
                "description": "Experiment ID to rollback"
            },
            "reason": {
                "type": "string",
                "description": "Reason for rollback"
            }
        },
        "required": ["experiment_id", "reason"]
    }

    async def execute(self, **kwargs) -> Dict:
        """Execute the tool"""
        try:
            orchestrator = get_orchestrator()
            experiment_id = kwargs["experiment_id"]
            reason = kwargs["reason"]

            await orchestrator.rollback_experiment(experiment_id, reason)

            return ToolResult(
                success=True,
                output={
                    "experiment_id": experiment_id,
                    "message": f"Experiment {experiment_id} rolled back: {reason}"
                }
            )

        except Exception as e:
            logger.error(f"Failed to rollback experiment: {e}")
            return ToolResult(
                success=False,
                output=None,
                error=str(e)
            )


# Tool registry for chaos tools
CHAOS_TOOLS = [
    CreateChaosExperimentTool(),
    RunChaosExperimentTool(),
    CreateChaosExperimentFromScenarioTool(),
    ListChaosScenariosTool(),
    GetChaosExperimentStatusTool(),
    RollbackChaosExperimentTool(),
]
