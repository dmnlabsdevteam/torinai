#!/usr/bin/env python3
"""
Chaos Orchestrator
==================

Main controller coordinating the entire chaos framework lifecycle.

Features:
- Experiment lifecycle management (create → approve → execute → monitor → complete)
- Governance integration with UnifiedGovernanceTriggerSystem
- Progressive rollout coordination (canary → gradual → full)
- Automatic rollback on SLO violations
- Circuit breaker management
- Experiment scheduling and concurrency control
"""

import asyncio
import logging
import time
import uuid
from datetime import datetime
from typing import Dict, List, Optional

from .types import (
    ChaosExperiment,
    ChaosType,
    ExperimentStatus,
    ExperimentResult,
    InjectionConfig,
    MetricsSnapshot,
    ChaosEvent,
    RolloutStage,
)
from .experiment_manager import get_experiment_manager
from .injection_engine import get_injection_engine
from .safety_controller import get_safety_controller
from ..database.logging_database import get_logging_db

logger = logging.getLogger(__name__)


class ChaosOrchestrator:
    """
    Chaos Orchestrator

    Main controller coordinating the entire chaos framework lifecycle.

    Responsibilities:
    - Experiment lifecycle management
    - Governance integration
    - Progressive rollout coordination
    - SLO monitoring and automatic rollback
    - Circuit breaker management
    """

    def __init__(self, config: Optional[Dict] = None):
        """
        Initialize chaos orchestrator.

        Args:
            config: Optional configuration dict (from chaos_config.json)
        """
        # Merge user config with defaults
        default_config = self._load_default_config()
        if config:
            # Deep merge user config with defaults
            self.config = {**default_config}
            for key, value in config.items():
                if isinstance(value, dict) and key in self.config:
                    self.config[key] = {**self.config[key], **value}
                else:
                    self.config[key] = value
        else:
            self.config = default_config

        # Component instances
        self.experiment_manager = get_experiment_manager()
        self.injection_engine = get_injection_engine()
        self.safety_controller = get_safety_controller()

        # Progressive rollout configuration
        self.progressive_rollout_config = self.config.get("progressive_rollout", {})
        self.rollout_stages = self._parse_rollout_stages()

        # Running experiments tracking
        self.running_experiments: Dict[str, ChaosExperiment] = {}
        self.experiment_tasks: Dict[str, asyncio.Task] = {}

        # Event tracking
        self.experiment_events: Dict[str, List[ChaosEvent]] = {}

        # Logging database (PostgreSQL unified schema) for persistence
        self.db = get_logging_db()
        # Preserve config key for backward compatibility, but semantics are
        # now "database logging" rather than specifically MySQL.
        self.db_logging_enabled = self.config.get("observability", {}).get(
            "enable_mysql_logging", True
        )

        # Metrics collection
        self.metrics_collection_interval = self.config.get("observability", {}).get(
            "metrics_collection_interval_seconds", 5
        )

        logger.info("ChaosOrchestrator initialized")

    async def _ensure_db_initialized(self):
        """Ensure database connection is initialized"""
        if self.db and not self.db.initialized:
            await self.db.initialize()

    def _load_default_config(self) -> Dict:
        """Load default orchestrator configuration"""
        return {
            "safety_controls": {
                "enable_preflight_checks": True,
                "enable_slo_monitoring": True,
                "enable_auto_rollback": True,
                "slo_check_interval_seconds": 10,
                "max_blast_radius": 100,
                "require_governance_production": True
            },
            "progressive_rollout": {
                "enabled": True,
                "stages": [
                    {"name": "canary", "blast_radius": 1, "duration_minutes": 5},
                    {"name": "gradual_10", "blast_radius": 10, "duration_minutes": 10},
                    {"name": "gradual_50", "blast_radius": 50, "duration_minutes": 15},
                    {"name": "full", "blast_radius": 100, "duration_minutes": 30}
                ]
            },
            "observability": {
                "metrics_collection_interval_seconds": 5
            }
        }

    def _parse_rollout_stages(self) -> List[RolloutStage]:
        """Parse rollout stages from config"""
        stages = []
        for stage_config in self.progressive_rollout_config.get("stages", []):
            stages.append(RolloutStage(
                name=stage_config["name"],
                blast_radius=stage_config["blast_radius"],
                duration_minutes=stage_config["duration_minutes"],
                slo_check_interval_seconds=stage_config.get("slo_check_interval_seconds", 10)
            ))
        return stages

    async def _persist_event_to_db(self, event: ChaosEvent):
        """Persist event to unified.chaos_events via LoggingDatabase"""
        if not self.db_logging_enabled or not self.db:
            return

        await self._ensure_db_initialized()

        try:
            await self.db.log_chaos_event(
                experiment_id=event.experiment_id,
                event_type=event.event_type,
                severity=event.severity,
                event_data=event.event_data,
            )
        except Exception as e:
            logger.error(f"Failed to persist chaos event: {e}")

    async def _persist_metric_to_db(self, experiment_id: str, metric: MetricsSnapshot):
        """Persist metrics to unified.chaos_metrics via LoggingDatabase"""
        if not self.db_logging_enabled or not self.db:
            return

        await self._ensure_db_initialized()

        try:
            # Store multiple metrics as separate rows
            metrics_to_store = [
                ("latency_p95", metric.component_metrics.get("latency_p95", 0)),
                ("latency_p99", metric.component_metrics.get("latency_p99", 0)),
                ("error_rate", metric.component_metrics.get("error_rate", 0)),
                ("cpu_percent", metric.system_metrics.get("cpu_percent", 0)),
                ("memory_percent", metric.system_metrics.get("memory_percent", 0)),
            ]

            for metric_name, metric_value in metrics_to_store:
                await self.db.log_chaos_metric(
                    experiment_id=experiment_id,
                    metric_type="system",
                    metric_name=metric_name,
                    metric_value=metric_value,
                    metric_metadata=None,
                )
        except Exception as e:
            logger.error(f"Failed to persist chaos metrics: {e}")

    async def _update_experiment_in_db(self, experiment: ChaosExperiment):
        """Update experiment status in unified.chaos_experiments"""
        if not self.db_logging_enabled or not self.db:
            return

        await self._ensure_db_initialized()

        try:
            import json

            updates = {
                "status": experiment.status.value,
                "started_at": experiment.started_at,
                "ended_at": experiment.ended_at,
                "governance_decision_id": experiment.governance_decision_id,
                "governance_tier": experiment.governance_tier,
                "metadata": json.dumps(experiment.metadata) if experiment.metadata is not None else None,
            }

            # Filter out None values to avoid overwriting with NULL unintentionally
            updates = {k: v for k, v in updates.items() if v is not None}

            if updates:
                await self.db.update_chaos_experiment(experiment.experiment_id, **updates)
        except Exception as e:
            logger.error(f"Failed to update experiment in logging database: {e}")

    async def _log_event(
        self,
        experiment_id: str,
        event_type: str,
        event_data: Optional[Dict] = None,
        severity: str = "info"
    ):
        """
        Log a chaos event for an experiment.

        Args:
            experiment_id: Experiment ID
            event_type: Type of event
            event_data: Optional event data
            severity: Event severity (info/warning/error/critical)
        """
        event = ChaosEvent(
            event_id=f"event_{uuid.uuid4().hex[:12]}",
            experiment_id=experiment_id,
            timestamp=datetime.now(),
            event_type=event_type,
            event_data=event_data or {},
            severity=severity
        )

        # Track event in memory
        if experiment_id not in self.experiment_events:
            self.experiment_events[experiment_id] = []
        self.experiment_events[experiment_id].append(event)

        # Persist to logging database
        if self.db_logging_enabled and self.db:
            await self._persist_event_to_db(event)

        # Log to logger
        log_level = {
            "info": logging.INFO,
            "warning": logging.WARNING,
            "error": logging.ERROR,
            "critical": logging.CRITICAL
        }.get(severity, logging.INFO)

        logger.log(
            log_level,
            f"[{experiment_id}] {event_type}: {event_data}"
        )

    async def create_experiment(
        self,
        name: str,
        description: str,
        target_system: str,
        chaos_type: ChaosType,
        environment: str,
        injection_config: InjectionConfig,
        blast_radius: int = 1,
        hypothesis: Optional[Dict] = None,
        requires_governance: bool = True
    ) -> ChaosExperiment:
        """
        Create a new chaos experiment.

        Args:
            name: Experiment name
            description: Experiment description
            target_system: Target system name
            chaos_type: Type of chaos to inject
            environment: Environment (dev/staging/production)
            injection_config: Injection configuration
            blast_radius: Percentage of traffic to affect (1-100)
            hypothesis: Optional hypothesis to validate
            requires_governance: Whether governance approval is required

        Returns:
            Created ChaosExperiment
        """
        experiment = await self.experiment_manager.create_experiment(
            name=name,
            description=description,
            target_system=target_system,
            chaos_type=chaos_type,
            environment=environment,
            injection_config=injection_config,
            blast_radius=blast_radius
        )

        # Add hypothesis if provided
        if hypothesis:
            experiment.hypothesis = hypothesis

        # Determine governance tier
        if requires_governance:
            governance_tier = self._determine_governance_tier(experiment)
            experiment.governance_tier = governance_tier
            logger.info(
                f"Experiment {experiment.experiment_id} requires {governance_tier} governance approval"
            )

            # Request governance approval
            await self._request_governance_approval(experiment)

        # Log event
        await self._log_event(
            experiment.experiment_id,
            "experiment_created",
            {
                "name": name,
                "target_system": target_system,
                "chaos_type": chaos_type.value,
                "environment": environment,
                "blast_radius": blast_radius
            },
            severity="info"
        )

        # Persist to MySQL
        if self.db_logging_enabled:
            await self._update_experiment_in_db(experiment)

        logger.info(f"Created chaos experiment: {experiment.experiment_id} ({name})")
        return experiment

    def _determine_governance_tier(self, experiment: ChaosExperiment) -> str:
        """
        Determine governance tier based on experiment properties.

        ROUTINE: Canary tests (≤1% blast radius) in dev/staging
        IMPORTANT: Gradual rollout (≤50%) in staging or low-blast production
        CRITICAL: Full production (>50%) or critical systems
        """
        # Critical systems always require CRITICAL governance
        critical_systems = ["governance", "safety", "security_system"]
        if any(critical in experiment.target_system for critical in critical_systems):
            return "CRITICAL"

        # Production environment with high blast radius
        if experiment.environment == "production":
            if experiment.blast_radius > 50:
                return "CRITICAL"
            elif experiment.blast_radius > 10:
                return "IMPORTANT"
            else:
                return "ROUTINE"

        # Staging environment
        if experiment.environment == "staging":
            if experiment.blast_radius > 50:
                return "IMPORTANT"
            else:
                return "ROUTINE"

        # Dev environment - always ROUTINE
        return "ROUTINE"

    async def _request_governance_approval(self, experiment: ChaosExperiment) -> bool:
        """
        Request governance approval for experiment (private helper).

        Args:
            experiment: Experiment to request approval for

        Returns:
            True if approval request submitted successfully
        """
        await self.submit_for_governance_approval(experiment)
        return True

    async def submit_for_governance_approval(
        self,
        experiment: ChaosExperiment,
        requestor_agent_id: str = "chaos_orchestrator"
    ) -> str:
        """
        Submit experiment for governance approval.

        Args:
            experiment: Experiment to submit
            requestor_agent_id: ID of agent requesting approval

        Returns:
            Governance decision ID
        """
        # This would integrate with UnifiedGovernanceTriggerSystem
        # For now, return a mock decision ID
        governance_decision_id = f"gov_{experiment.experiment_id}"

        experiment.governance_decision_id = governance_decision_id
        experiment.status = ExperimentStatus.PENDING

        # Log event
        await self._log_event(
            experiment.experiment_id,
            "governance_submission",
            {
                "governance_tier": experiment.governance_tier,
                "decision_id": governance_decision_id,
                "requestor": requestor_agent_id
            },
            severity="info"
        )

        logger.info(
            f"Submitted experiment {experiment.experiment_id} for governance approval "
            f"(tier: {experiment.governance_tier}, decision: {governance_decision_id})"
        )

        return governance_decision_id

    async def approve_experiment(self, experiment_id: str):
        """
        Mark experiment as approved (called by governance system).

        Args:
            experiment_id: Experiment to approve
        """
        experiment = await self.experiment_manager.get_experiment(experiment_id)
        if not experiment:
            raise ValueError(f"Experiment not found: {experiment_id}")

        experiment.status = ExperimentStatus.APPROVED

        # Log event
        await self._log_event(
            experiment_id,
            "experiment_approved",
            {"governance_decision_id": experiment.governance_decision_id},
            severity="info"
        )

        # Persist to MySQL
        if self.db_logging_enabled:
            await self._update_experiment_in_db(experiment)

        logger.info(f"Experiment {experiment_id} approved for execution")

    async def run_experiment(
        self,
        experiment_id: str,
        progressive_rollout: bool = True,
        duration_minutes: Optional[int] = None
    ) -> ExperimentResult:
        """
        Execute chaos experiment with safety controls.

        Args:
            experiment_id: Experiment to run
            progressive_rollout: Whether to use progressive rollout

        Returns:
            ExperimentResult with metrics and insights
        """
        experiment = await self.experiment_manager.get_experiment(experiment_id)
        if not experiment:
            raise ValueError(f"Experiment not found: {experiment_id}")

        # Persist experiment to MySQL before execution
        if self.db_logging_enabled:
            await self._update_experiment_in_db(experiment)

        # Pre-flight checks
        preflight_result = await self.safety_controller.pre_flight_check(experiment)
        if not preflight_result.can_proceed:
            # Log event
            await self._log_event(
                experiment_id,
                "preflight_failed",
                {"blocking_issues": preflight_result.blocking_issues},
                severity="error"
            )

            logger.error(
                f"Pre-flight checks failed for {experiment_id}: "
                f"{', '.join(preflight_result.blocking_issues)}"
            )
            experiment.status = ExperimentStatus.FAILED
            return ExperimentResult(
                experiment_id=experiment_id,
                success=False,
                status=ExperimentStatus.FAILED,
                metrics_collected=[],
                hypothesis_validated=False,
                insights=[f"Pre-flight check failed: {', '.join(preflight_result.blocking_issues)}"],
                rollback_triggered=False
            )

        logger.info(f"Pre-flight checks passed for experiment {experiment_id}")

        # Execute with or without progressive rollout
        if progressive_rollout and self.progressive_rollout_config.get("enabled", True):
            return await self._run_progressive_rollout(experiment)
        else:
            return await self._run_single_stage(experiment, experiment.blast_radius, duration_minutes)

    async def _run_progressive_rollout(self, experiment: ChaosExperiment) -> ExperimentResult:
        """
        Execute experiment with progressive rollout (canary → gradual → full).

        Args:
            experiment: Experiment to run

        Returns:
            ExperimentResult
        """
        logger.info(
            f"Starting progressive rollout for experiment {experiment.experiment_id} "
            f"({len(self.rollout_stages)} stages)"
        )

        all_metrics: List[MetricsSnapshot] = []
        current_stage_index = 0
        rollback_triggered = False

        for stage in self.rollout_stages:
            # Only roll out to stages up to target blast radius
            if stage.blast_radius > experiment.blast_radius:
                logger.info(
                    f"Skipping stage {stage.name} (blast_radius {stage.blast_radius}% > "
                    f"target {experiment.blast_radius}%)"
                )
                break

            # Log event
            await self._log_event(
                experiment.experiment_id,
                "stage_started",
                {
                    "stage_name": stage.name,
                    "blast_radius": stage.blast_radius,
                    "duration_minutes": stage.duration_minutes
                },
                severity="info"
            )

            logger.info(
                f"Entering stage {stage.name} (blast_radius: {stage.blast_radius}%, "
                f"duration: {stage.duration_minutes}min)"
            )

            # Update experiment blast radius for this stage
            original_blast_radius = experiment.blast_radius
            experiment.blast_radius = stage.blast_radius

            # Run this stage
            stage_result = await self._run_single_stage(
                experiment,
                stage.blast_radius,
                duration_minutes=stage.duration_minutes,
                slo_check_interval=stage.slo_check_interval_seconds
            )

            # Collect metrics
            all_metrics.extend(stage_result.metrics_collected)

            # Check if rollback was triggered
            if stage_result.rollback_triggered:
                # Log event
                await self._log_event(
                    experiment.experiment_id,
                    "stage_rollback",
                    {
                        "stage_name": stage.name,
                        "reason": "SLO violations detected"
                    },
                    severity="warning"
                )

                logger.warning(
                    f"Stage {stage.name} triggered rollback - stopping progressive rollout"
                )
                rollback_triggered = True
                experiment.blast_radius = original_blast_radius
                break

            # Check if stage failed
            if not stage_result.success:
                logger.error(f"Stage {stage.name} failed - stopping progressive rollout")
                experiment.blast_radius = original_blast_radius
                return stage_result

            # Log event
            await self._log_event(
                experiment.experiment_id,
                "stage_completed",
                {
                    "stage_name": stage.name,
                    "blast_radius": stage.blast_radius,
                    "metrics_count": len(stage_result.metrics_collected)
                },
                severity="info"
            )

            logger.info(f"Stage {stage.name} completed successfully")
            current_stage_index += 1

            # Small pause between stages
            await asyncio.sleep(2)

        # Restore original blast radius
        experiment.blast_radius = original_blast_radius

        # Determine overall success
        success = not rollback_triggered and current_stage_index > 0

        # Generate insights
        insights = self._generate_progressive_rollout_insights(
            all_metrics,
            current_stage_index,
            rollback_triggered
        )

        result = ExperimentResult(
            experiment_id=experiment.experiment_id,
            success=success,
            status=ExperimentStatus.COMPLETED if success else ExperimentStatus.FAILED,
            metrics_collected=all_metrics,
            hypothesis_validated=self._validate_hypothesis(experiment, all_metrics),
            insights=insights,
            rollback_triggered=rollback_triggered
        )

        # Update experiment status
        if success:
            experiment.status = ExperimentStatus.COMPLETED
            experiment.completed_at = datetime.now()
        elif rollback_triggered:
            experiment.status = ExperimentStatus.ROLLED_BACK
            experiment.completed_at = datetime.now()
        else:
            experiment.status = ExperimentStatus.FAILED
            experiment.completed_at = datetime.now()

        # Persist to MySQL
        if self.db_logging_enabled:
            await self._update_experiment_in_db(experiment)

        logger.info(
            f"Progressive rollout completed for {experiment.experiment_id}: "
            f"success={success}, stages_completed={current_stage_index}/{len(self.rollout_stages)}"
        )

        return result

    async def _run_single_stage(
        self,
        experiment: ChaosExperiment,
        blast_radius: int,
        duration_minutes: Optional[int] = None,
        slo_check_interval: int = 10
    ) -> ExperimentResult:
        """
        Run a single stage of chaos injection.

        Args:
            experiment: Experiment to run
            blast_radius: Blast radius for this stage
            duration_minutes: Stage duration (None = use experiment default)
            slo_check_interval: SLO check interval in seconds

        Returns:
            ExperimentResult for this stage
        """
        experiment.status = ExperimentStatus.RUNNING
        experiment.started_at = datetime.now()

        metrics_collected: List[MetricsSnapshot] = []
        rollback_triggered = False

        try:
            # Start chaos injection
            injection_handle = await self.injection_engine.inject_chaos(
                target_system=experiment.target_system,
                config=experiment.injection_config,
                experiment_id=experiment.experiment_id
            )

            if not injection_handle:
                raise Exception(f"Failed to inject chaos for {experiment.target_system}")

            logger.info(
                f"Chaos injection started: {injection_handle.injection_id} "
                f"(experiment: {experiment.experiment_id}, blast_radius: {blast_radius}%)"
            )

            # Log event
            await self._log_event(
                experiment.experiment_id,
                "chaos_injection_started",
                {
                    "injection_id": injection_handle.injection_id,
                    "target_system": experiment.target_system,
                    "blast_radius": blast_radius,
                    "chaos_type": experiment.chaos_type.value
                },
                severity="info"
            )

            # Determine duration
            if duration_minutes is None:
                duration_minutes = 5  # Default 5 minutes

            duration_seconds = duration_minutes * 60
            end_time = time.time() + duration_seconds

            # Monitor SLOs during execution
            while time.time() < end_time:
                # Collect metrics
                slo_status = await self.safety_controller.monitor_slos(
                    experiment.target_system,
                    experiment.experiment_id
                )

                # Store metrics snapshot
                metrics_snapshot = MetricsSnapshot(
                    experiment_id=experiment.experiment_id,
                    timestamp=datetime.now(),
                    system_metrics={
                        "cpu_percent": slo_status.metrics.get("cpu_percent", 0),
                        "memory_percent": slo_status.metrics.get("memory_percent", 0)
                    },
                    component_metrics={
                        "latency_p95": slo_status.metrics.get("tool_execution_latency_p95", 0),
                        "latency_p99": slo_status.metrics.get("tool_execution_latency_p99", 0),
                        "error_rate": slo_status.metrics.get("tool_error_rate", 0)
                    }
                )
                metrics_collected.append(metrics_snapshot)

                # Persist metric to MySQL
                if self.db_logging_enabled:
                    await self._persist_metric_to_db(experiment.experiment_id, metrics_snapshot)

                # Check if rollback needed
                if slo_status.should_rollback:
                    logger.warning(
                        f"SLO violation detected for {experiment.experiment_id}: "
                        f"{', '.join(slo_status.violations)}"
                    )

                    # Log event
                    await self._log_event(
                        experiment.experiment_id,
                        "slo_violation",
                        {
                            "violations": slo_status.violations,
                            "metrics": slo_status.metrics
                        },
                        severity="warning"
                    )

                    # Trigger automatic rollback
                    await self.safety_controller.trigger_automatic_rollback(
                        experiment,
                        reason=f"SLO violations: {', '.join(slo_status.violations)}",
                        metrics=slo_status.metrics
                    )

                    rollback_triggered = True
                    break

                # Wait before next check
                await asyncio.sleep(slo_check_interval)

            # Stop chaos injection
            if not rollback_triggered:
                await self.injection_engine.stop_injection(
                    experiment.target_system,
                    injection_handle.injection_id
                )
                logger.info(f"Chaos injection stopped: {injection_handle.injection_id}")

                # Log event
                await self._log_event(
                    experiment.experiment_id,
                    "chaos_injection_stopped",
                    {
                        "injection_id": injection_handle.injection_id,
                        "metrics_collected": len(metrics_collected)
                    },
                    severity="info"
                )

            # Determine success
            success = not rollback_triggered

            # Generate insights
            insights = self._generate_stage_insights(metrics_collected, rollback_triggered)

            return ExperimentResult(
                experiment_id=experiment.experiment_id,
                success=success,
                status=experiment.status,
                metrics_collected=metrics_collected,
                hypothesis_validated=self._validate_hypothesis(experiment, metrics_collected),
                insights=insights,
                rollback_triggered=rollback_triggered
            )

        except Exception as e:
            logger.error(f"Experiment execution failed: {e}")
            experiment.status = ExperimentStatus.FAILED

            return ExperimentResult(
                experiment_id=experiment.experiment_id,
                success=False,
                status=ExperimentStatus.FAILED,
                metrics_collected=metrics_collected,
                hypothesis_validated=False,
                insights=[f"Execution error: {str(e)}"],
                rollback_triggered=rollback_triggered
            )

    def _validate_hypothesis(
        self,
        experiment: ChaosExperiment,
        metrics: List[MetricsSnapshot]
    ) -> bool:
        """
        Validate experiment hypothesis against collected metrics.

        Args:
            experiment: Experiment with hypothesis
            metrics: Collected metrics

        Returns:
            True if hypothesis validated
        """
        if not experiment.hypothesis or not metrics:
            return False

        # Extract expected behavior from hypothesis
        expected = experiment.hypothesis.expected_behavior if experiment.hypothesis else {}

        # Calculate actual metrics
        if not metrics:
            return False

        avg_latency_p95 = sum(m.component_metrics.get("latency_p95", 0) for m in metrics) / len(metrics)
        avg_error_rate = sum(m.component_metrics.get("error_rate", 0) for m in metrics) / len(metrics)

        # Check against expected values
        latency_threshold = expected.get("max_latency_p95_ms", float('inf'))
        error_threshold = expected.get("max_error_rate", 1.0)

        latency_ok = avg_latency_p95 <= latency_threshold
        error_ok = avg_error_rate <= error_threshold

        validated = latency_ok and error_ok

        logger.info(
            f"Hypothesis validation for {experiment.experiment_id}: "
            f"validated={validated} (latency: {avg_latency_p95:.1f}ms <= {latency_threshold}ms, "
            f"error_rate: {avg_error_rate*100:.2f}% <= {error_threshold*100}%)"
        )

        return validated

    def _generate_stage_insights(
        self,
        metrics: List[MetricsSnapshot],
        rollback_triggered: bool
    ) -> List[str]:
        """Generate insights from single stage execution"""
        insights = []

        if not metrics:
            insights.append("No metrics collected during stage")
            return insights

        # Calculate averages
        avg_latency_p95 = sum(m.component_metrics.get("latency_p95", 0) for m in metrics) / len(metrics)
        avg_latency_p99 = sum(m.component_metrics.get("latency_p99", 0) for m in metrics) / len(metrics)
        avg_error_rate = sum(m.component_metrics.get("error_rate", 0) for m in metrics) / len(metrics)

        insights.append(f"Average latency P95: {avg_latency_p95:.1f}ms")
        insights.append(f"Average latency P99: {avg_latency_p99:.1f}ms")
        insights.append(f"Average error rate: {avg_error_rate*100:.2f}%")

        if rollback_triggered:
            insights.append("Automatic rollback triggered due to SLO violations")
        else:
            insights.append("Stage completed successfully with SLOs maintained")

        return insights

    def _generate_progressive_rollout_insights(
        self,
        all_metrics: List[MetricsSnapshot],
        stages_completed: int,
        rollback_triggered: bool
    ) -> List[str]:
        """Generate insights from progressive rollout"""
        insights = []

        insights.append(f"Completed {stages_completed} of {len(self.rollout_stages)} rollout stages")

        if rollback_triggered:
            insights.append("Progressive rollout halted due to SLO violations")
        elif stages_completed == len(self.rollout_stages):
            insights.append("Full progressive rollout completed successfully")

        if all_metrics:
            avg_latency_p95 = sum(m.component_metrics.get("latency_p95", 0) for m in all_metrics) / len(all_metrics)
            avg_error_rate = sum(m.component_metrics.get("error_rate", 0) for m in all_metrics) / len(all_metrics)

            insights.append(f"Overall average latency P95: {avg_latency_p95:.1f}ms")
            insights.append(f"Overall average error rate: {avg_error_rate*100:.2f}%")

        return insights

    async def rollback_experiment(self, experiment_id: str, reason: str):
        """
        Manually rollback an experiment.

        Args:
            experiment_id: Experiment to rollback
            reason: Rollback reason
        """
        experiment = await self.experiment_manager.get_experiment(experiment_id)
        if not experiment:
            raise ValueError(f"Experiment not found: {experiment_id}")

        logger.info(f"Manual rollback requested for {experiment_id}: {reason}")

        await self.safety_controller.trigger_automatic_rollback(
            experiment,
            reason=f"Manual rollback: {reason}"
        )

    async def emergency_stop_all(self):
        """Emergency stop all running experiments"""
        logger.critical("EMERGENCY STOP: Stopping all running chaos experiments")

        running_experiments = [
            exp for exp in self.experiment_manager.experiments.values()
            if exp.status == ExperimentStatus.RUNNING
        ]

        for experiment in running_experiments:
            await self.safety_controller.trigger_automatic_rollback(
                experiment,
                reason="Emergency stop triggered"
            )

        logger.info(f"Emergency stop complete: {len(running_experiments)} experiments stopped")

    async def get_experiment_status(self, experiment_id: str) -> Dict:
        """
        Get current status of experiment.

        Args:
            experiment_id: Experiment ID

        Returns:
            Status dict with experiment details
        """
        experiment = await self.experiment_manager.get_experiment(experiment_id)
        if not experiment:
            raise ValueError(f"Experiment not found: {experiment_id}")

        return {
            "experiment_id": experiment.experiment_id,
            "name": experiment.name,
            "status": experiment.status.value,
            "target_system": experiment.target_system,
            "chaos_type": experiment.chaos_type.value,
            "blast_radius": experiment.blast_radius,
            "environment": experiment.environment,
            "governance_tier": experiment.governance_tier,
            "started_at": experiment.started_at.isoformat() if experiment.started_at else None,
            "ended_at": experiment.ended_at.isoformat() if experiment.ended_at else None
        }


# Singleton instance
_orchestrator = None


def get_orchestrator(config: Optional[Dict] = None) -> ChaosOrchestrator:
    """Get global orchestrator instance"""
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = ChaosOrchestrator(config)
    return _orchestrator
