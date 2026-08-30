#!/usr/bin/env python3
"""
Chaos Framework Data Types
===========================

Data classes and enums for the chaos engineering framework.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional


class ExperimentStatus(Enum):
    """Chaos experiment status"""
    PENDING = "pending"
    APPROVED = "approved"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"


class ChaosType(Enum):
    """Types of chaos injection"""
    LATENCY = "latency"
    ERROR = "error"
    RESOURCE_EXHAUSTION = "resource_exhaustion"
    PARTIAL_FAILURE = "partial_failure"
    NETWORK_PARTITION = "network_partition"
    TIMEOUT = "timeout"
    RATE_LIMIT = "rate_limit"
    DATA_CORRUPTION = "data_corruption"


class CircuitState(Enum):
    """Circuit breaker states"""
    CLOSED = "closed"      # Normal operation
    OPEN = "open"          # Blocking calls
    HALF_OPEN = "half_open"  # Testing recovery


class EventSeverity(Enum):
    """Chaos event severity levels"""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass
class InjectionConfig:
    """Configuration for chaos injection"""
    component: str
    injection_point: str
    chaos_type: ChaosType

    # Latency injection
    delay_ms: Optional[int] = None
    jitter_ms: Optional[int] = None

    # Error injection
    error_rate: Optional[float] = None
    error_type: Optional[str] = None
    error_message: Optional[str] = None

    # Resource exhaustion
    resource_type: Optional[str] = None  # cpu, memory, disk
    limit_value: Optional[float] = None

    # Metadata
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Hypothesis:
    """Experiment hypothesis for validation"""
    description: str
    success_criteria: List[Dict[str, Any]] = field(default_factory=list)
    expected_behavior: Dict[str, Any] = field(default_factory=dict)

    def add_criterion(
        self,
        name: str,
        metric_name: str,
        operator: str,
        expected_value: Any
    ):
        """Add a success criterion to the hypothesis"""
        self.success_criteria.append({
            "name": name,
            "metric_name": metric_name,
            "operator": operator,
            "expected_value": expected_value
        })


@dataclass
class ChaosExperiment:
    """Chaos experiment definition"""
    experiment_id: str
    name: str
    description: str
    target_system: str
    chaos_type: ChaosType
    environment: str  # dev, staging, production

    # Configuration
    injection_config: InjectionConfig
    blast_radius: int = 1  # Percentage of traffic to affect (1-100)

    # Experiment state
    status: ExperimentStatus = ExperimentStatus.PENDING
    created_at: datetime = field(default_factory=datetime.now)
    created_by: str = "torin_ai"

    # Governance
    governance_decision_id: Optional[str] = None
    governance_tier: Optional[str] = None  # ROUTINE, IMPORTANT, CRITICAL

    # Execution tracking
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    duration_seconds: Optional[float] = None

    # Rollback
    rollback_reason: Optional[str] = None

    # Hypothesis
    hypothesis: Optional[Hypothesis] = None

    # Metadata
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization"""
        return {
            "experiment_id": self.experiment_id,
            "name": self.name,
            "description": self.description,
            "target_system": self.target_system,
            "chaos_type": self.chaos_type.value,
            "environment": self.environment,
            "blast_radius": self.blast_radius,
            "status": self.status.value,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "created_by": self.created_by,
            "governance_decision_id": self.governance_decision_id,
            "governance_tier": self.governance_tier,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "ended_at": self.ended_at.isoformat() if self.ended_at else None,
            "duration_seconds": self.duration_seconds,
            "rollback_reason": self.rollback_reason,
            "metadata": self.metadata
        }


@dataclass
class ExperimentResult:
    """Result of a chaos experiment"""
    experiment_id: str
    success: bool
    status: ExperimentStatus

    # Stage progression
    completed_stages: List[str] = field(default_factory=list)
    stage_failed: Optional[str] = None

    # Metrics
    metrics_collected: int = 0
    events_recorded: int = 0

    # Hypothesis validation
    hypothesis_validated: bool = False
    confidence_score: float = 0.0

    # Rollback
    rollback_triggered: bool = False
    rollback_reason: Optional[str] = None

    # Insights
    insights: List[str] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)

    # Metadata
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization"""
        return {
            "experiment_id": self.experiment_id,
            "success": self.success,
            "status": self.status.value,
            "completed_stages": self.completed_stages,
            "stage_failed": self.stage_failed,
            "metrics_collected": self.metrics_collected,
            "events_recorded": self.events_recorded,
            "hypothesis_validated": self.hypothesis_validated,
            "confidence_score": self.confidence_score,
            "rollback_triggered": self.rollback_triggered,
            "rollback_reason": self.rollback_reason,
            "insights": self.insights,
            "recommendations": self.recommendations,
            "metadata": self.metadata
        }


@dataclass
class MetricsSnapshot:
    """Snapshot of metrics during chaos experiment"""
    experiment_id: str
    timestamp: datetime

    # System metrics
    system_metrics: Dict[str, Any] = field(default_factory=dict)

    # Component metrics
    component_metrics: Dict[str, Any] = field(default_factory=dict)

    # Chaos-specific metrics
    chaos_metrics: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization"""
        return {
            "experiment_id": self.experiment_id,
            "timestamp": self.timestamp.isoformat(),
            "system_metrics": self.system_metrics,
            "component_metrics": self.component_metrics,
            "chaos_metrics": self.chaos_metrics
        }


@dataclass
class ChaosEvent:
    """Event during chaos experiment"""
    event_id: str
    experiment_id: str
    timestamp: datetime
    event_type: str
    event_data: Dict[str, Any] = field(default_factory=dict)
    severity: EventSeverity = EventSeverity.INFO

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization"""
        return {
            "event_id": self.event_id,
            "experiment_id": self.experiment_id,
            "timestamp": self.timestamp.isoformat(),
            "event_type": self.event_type,
            "event_data": self.event_data,
            "severity": self.severity.value
        }


@dataclass
class SLOViolation:
    """SLO violation details for rollback decisions"""
    violated: bool
    metric: str
    threshold: float
    actual: float
    severity: str  # info, warning, critical

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            "violated": self.violated,
            "metric": self.metric,
            "threshold": self.threshold,
            "actual": self.actual,
            "severity": self.severity
        }


@dataclass
class SLOThresholds:
    """Service Level Objective thresholds for auto-rollback"""
    latency_p95_ms: float = 500.0
    latency_p99_ms: float = 1000.0
    error_rate: float = 0.01  # 1%
    cpu_percent: float = 80.0
    memory_percent: float = 85.0
    disk_percent: float = 90.0

    def to_dict(self) -> Dict[str, float]:
        """Convert to dictionary"""
        return {
            "latency_p95_ms": self.latency_p95_ms,
            "latency_p99_ms": self.latency_p99_ms,
            "error_rate": self.error_rate,
            "cpu_percent": self.cpu_percent,
            "memory_percent": self.memory_percent,
            "disk_percent": self.disk_percent
        }


@dataclass
class PreFlightCheck:
    """Individual pre-flight check result"""
    name: str
    passed: bool
    reason: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PreFlightResult:
    """Result of pre-flight checks"""
    passed: bool
    checks: List[PreFlightCheck] = field(default_factory=list)
    can_proceed: bool = True
    blocking_issues: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            "passed": self.passed,
            "can_proceed": self.can_proceed,
            "blocking_issues": self.blocking_issues,
            "warnings": self.warnings,
            "checks": [
                {
                    "name": check.name,
                    "passed": check.passed,
                    "reason": check.reason,
                    "metadata": check.metadata
                }
                for check in self.checks
            ]
        }


@dataclass
class SLOStatus:
    """SLO monitoring status"""
    healthy: bool
    violations: List[str] = field(default_factory=list)
    should_rollback: bool = False
    health_status: Optional[str] = None
    metrics: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RolloutStage:
    """Progressive rollout stage definition"""
    name: str
    blast_radius: int  # Percentage (1-100)
    duration_minutes: int
    slo_check_interval_seconds: int = 10

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            "name": self.name,
            "blast_radius": self.blast_radius,
            "duration_minutes": self.duration_minutes,
            "slo_check_interval_seconds": self.slo_check_interval_seconds
        }


@dataclass
class CriterionValidation:
    """Validation of a single hypothesis criterion"""
    criterion_name: str
    metric_name: str
    expected: Any
    actual: Any
    passed: bool
    operator: str

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            "criterion_name": self.criterion_name,
            "metric_name": self.metric_name,
            "expected": self.expected,
            "actual": self.actual,
            "passed": self.passed,
            "operator": self.operator
        }


@dataclass
class ValidationResult:
    """Hypothesis validation result"""
    experiment_id: str
    hypothesis_validated: bool
    validations: List[CriterionValidation] = field(default_factory=list)
    confidence_score: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            "experiment_id": self.experiment_id,
            "hypothesis_validated": self.hypothesis_validated,
            "confidence_score": self.confidence_score,
            "validations": [v.to_dict() for v in self.validations]
        }


@dataclass
class ExperimentReport:
    """Comprehensive experiment report"""
    experiment_id: str
    experiment: ChaosExperiment
    summary: Dict[str, Any] = field(default_factory=dict)
    metrics: List[MetricsSnapshot] = field(default_factory=list)
    events: List[ChaosEvent] = field(default_factory=list)
    hypothesis_result: Optional[ValidationResult] = None
    insights: List[str] = field(default_factory=list)
    generated_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization"""
        return {
            "experiment_id": self.experiment_id,
            "experiment": self.experiment.to_dict(),
            "summary": self.summary,
            "metrics": [m.to_dict() for m in self.metrics],
            "events": [e.to_dict() for e in self.events],
            "hypothesis_result": self.hypothesis_result.to_dict() if self.hypothesis_result else None,
            "insights": self.insights,
            "generated_at": self.generated_at.isoformat()
        }


@dataclass
class InjectionHandle:
    """Handle for managing an active chaos injection"""
    injection_id: str
    experiment_id: str
    target: str
    chaos_type: ChaosType
    started_at: datetime = field(default_factory=datetime.now)
    active: bool = True

    def stop(self):
        """Mark injection as stopped"""
        self.active = False
