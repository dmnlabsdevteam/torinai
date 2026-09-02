#!/usr/bin/env python3
"""
Directive System Type Definitions

Complete dataclasses for the governance-based directive system.
These types define the structure of directives, evaluations, and governance laws.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Any
import uuid
import numpy as np  # For bounds checking


# ==========================
# ENUMS
# ==========================

class DirectiveCategory(Enum):
    """Categories of internal directives"""
    GOAL_PRIORITIZATION = "goal_prioritization"
    RESOURCE_ALLOCATION = "resource_allocation"
    LEARNING_STRATEGY = "learning_strategy"
    EXPLORATION_BALANCE = "exploration_balance"


class DirectiveStatus(Enum):
    """Status of a directive"""
    DRAFT = "draft"
    ACTIVE = "active"
    TESTING = "testing"
    DEPRECATED = "deprecated"


class ContextType(Enum):
    """Types of decision contexts where directives are applied"""
    GOAL_SELECTION = "goal_selection"
    RESOURCE_DECISION = "resource_decision"
    STRATEGY_CHOICE = "strategy_choice"
    EXPLORATION_DECISION = "exploration_decision"


class EvolutionType(Enum):
    """Types of directive evolution events"""
    CREATED = "created"
    MODIFIED = "modified"
    PROMOTED = "promoted"
    DEPRECATED = "deprecated"
    AB_TEST_STARTED = "ab_test_started"
    AB_TEST_WINNER = "ab_test_winner"


class ABTestStatus(Enum):
    """Status of A/B tests"""
    RUNNING = "running"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    INSUFFICIENT_DATA = "insufficient_data"


# NOTE (2026-09-02): GovernanceAgentType (the five-judge panel:
# neutral/conservative/moderate/progressive/synthesizer) was REMOVED. Directive
# governance is no longer a multi-agent LLM-style vote — a proposed directive is
# validated against the CONSTITUTION (the single, model-free governance authority,
# singleton_constitution) before activation. The removed vote types
# (GovernanceAgentType/GovernanceAgentVote/GovernanceEvaluation) and their dead
# persistence sink are archived in archive/llm_era_directive_governance_2026-09-02/.


# ==========================
# GOVERNANCE LAW
# ==========================

@dataclass
class GovernanceLaw:
    """
    Immutable law for human protection and AI alignment.
    These laws NEVER change and guide all directive evaluations.
    """
    law_id: str
    law_number: int
    law_name: str
    law_description: str
    requirements: List[str]  # List of specific requirements/constraints
    created_at: datetime
    immutable: bool = True  # Always True

    @staticmethod
    def generate_id() -> str:
        """Generate a unique law ID"""
        return f"gov_law_{uuid.uuid4().hex[:8]}"


# ==========================
# DIRECTIVE
# ==========================

@dataclass
class InternalDirective:
    """
    Performance-adaptive internal directive that guides behavior.
    Directives can evolve based on measured outcomes.

    All average performance metrics are normalized [0.0, 1.0] and validated for mathematical integrity.
    """
    directive_id: str
    directive_name: str
    directive_category: DirectiveCategory
    directive_text: str
    directive_parameters: Dict[str, Any]

    # Versioning
    version: int = 1
    parent_directive_id: Optional[str] = None

    # Status
    status: DirectiveStatus = DirectiveStatus.DRAFT
    activation_date: Optional[datetime] = None
    deprecation_date: Optional[datetime] = None

    # Performance metrics (auto-calculated) - ALL NORMALIZED [0.0, 1.0]
    total_applications: int = 0  # Absolute count (not bounded)
    successful_applications: int = 0  # Absolute count (not bounded)
    avg_outcome_quality: float = 0.0  # MUST be [0.0, 1.0]
    avg_intrinsic_reward: float = 0.0  # MUST be [0.0, 1.0]
    avg_constitutional_alignment: float = 0.0  # MUST be [0.0, 1.0]
    avg_system_health_impact: float = 0.0  # MUST be [0.0, 1.0]

    # A/B testing
    test_group: Optional[str] = None
    test_id: Optional[str] = None

    # Governance compliance
    governance_validated: bool = False
    constitutional_validated: bool = False

    # Timestamps
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)

    def __post_init__(self):
        """Validate all average performance metrics are properly bounded [0.0, 1.0]"""
        if not 0.0 <= self.avg_outcome_quality <= 1.0:
            raise ValueError(
                f"avg_outcome_quality must be in [0.0, 1.0], got {self.avg_outcome_quality}. "
                f"This is a critical metric bound violation."
            )

        if not 0.0 <= self.avg_intrinsic_reward <= 1.0:
            raise ValueError(
                f"avg_intrinsic_reward must be in [0.0, 1.0], got {self.avg_intrinsic_reward}. "
                f"This is a critical metric bound violation."
            )

        if not 0.0 <= self.avg_constitutional_alignment <= 1.0:
            raise ValueError(
                f"avg_constitutional_alignment must be in [0.0, 1.0], got {self.avg_constitutional_alignment}. "
                f"This is a critical metric bound violation."
            )

        if not 0.0 <= self.avg_system_health_impact <= 1.0:
            raise ValueError(
                f"avg_system_health_impact must be in [0.0, 1.0], got {self.avg_system_health_impact}. "
                f"This is a critical metric bound violation."
            )

        # Validate counts are non-negative
        if self.total_applications < 0:
            raise ValueError(f"total_applications must be >= 0, got {self.total_applications}")

        if self.successful_applications < 0:
            raise ValueError(f"successful_applications must be >= 0, got {self.successful_applications}")

        if self.version < 1:
            raise ValueError(f"version must be >= 1, got {self.version}")

    @staticmethod
    def generate_id() -> str:
        """Generate a unique directive ID"""
        return f"dir_{uuid.uuid4().hex[:12]}"

    def overall_performance(self) -> float:
        """Calculate overall performance score (0.0-1.0)"""
        if self.total_applications == 0:
            return 0.0

        metrics = [
            self.avg_outcome_quality,
            self.avg_intrinsic_reward,
            self.avg_constitutional_alignment,
            self.avg_system_health_impact
        ]

        return sum(metrics) / len(metrics)

    def success_rate(self) -> float:
        """Calculate success rate (0.0-1.0)"""
        if self.total_applications == 0:
            return 0.0
        return self.successful_applications / self.total_applications


# ==========================
# DIRECTIVE APPLICATION
# ==========================

@dataclass
class DirectiveApplication:
    """
    Log entry for a single directive application with outcome tracking.

    All outcome metrics are normalized scores [0.0, 1.0] and validated for mathematical integrity.
    """
    application_id: str
    directive_id: str

    # Application context
    applied_at: datetime
    context_type: ContextType
    context_data: Dict[str, Any]
    decision_made: str

    # Outcomes (populated after completion) - ALL NORMALIZED [0.0, 1.0]
    outcome_quality: Optional[float] = None  # MUST be [0.0, 1.0] when set
    intrinsic_reward: Optional[float] = None  # MUST be [0.0, 1.0] when set
    constitutional_alignment: Optional[float] = None  # MUST be [0.0, 1.0] when set
    system_health_impact: Optional[float] = None  # MUST be [0.0, 1.0] when set
    success: Optional[bool] = None

    # Result tracking
    completed_at: Optional[datetime] = None
    evaluation_completed: bool = False

    def __post_init__(self):
        """Validate all outcome metrics are properly bounded [0.0, 1.0]"""
        if self.outcome_quality is not None and not 0.0 <= self.outcome_quality <= 1.0:
            raise ValueError(
                f"outcome_quality must be in [0.0, 1.0], got {self.outcome_quality}. "
                f"This is a critical metric bound violation."
            )

        if self.intrinsic_reward is not None and not 0.0 <= self.intrinsic_reward <= 1.0:
            raise ValueError(
                f"intrinsic_reward must be in [0.0, 1.0], got {self.intrinsic_reward}. "
                f"This is a critical metric bound violation."
            )

        if self.constitutional_alignment is not None and not 0.0 <= self.constitutional_alignment <= 1.0:
            raise ValueError(
                f"constitutional_alignment must be in [0.0, 1.0], got {self.constitutional_alignment}. "
                f"This is a critical metric bound violation."
            )

        if self.system_health_impact is not None and not 0.0 <= self.system_health_impact <= 1.0:
            raise ValueError(
                f"system_health_impact must be in [0.0, 1.0], got {self.system_health_impact}. "
                f"This is a critical metric bound violation."
            )

    @staticmethod
    def generate_id() -> str:
        """Generate a unique application ID"""
        return f"app_{uuid.uuid4().hex[:12]}"

    def is_complete(self) -> bool:
        """Check if all outcome metrics are populated"""
        return all([
            self.outcome_quality is not None,
            self.intrinsic_reward is not None,
            self.constitutional_alignment is not None,
            self.system_health_impact is not None,
            self.success is not None
        ])


# ==========================
# DIRECTIVE EVOLUTION
# ==========================

@dataclass
class DirectiveEvolution:
    """
    Evolution history entry tracking directive changes over time.

    Improvement score is normalized [0.0, 1.0] and validated for mathematical integrity.
    """
    evolution_id: str
    directive_id: str
    evolution_type: EvolutionType

    # Version tracking
    previous_version: Optional[int]
    new_version: int

    # Changes made
    changes: Dict[str, Any]
    improvement_score: Optional[float] = None  # MUST be [0.0, 1.0] when set

    # Context
    trigger_reason: str = ""
    performance_metrics: Optional[Dict[str, float]] = None

    # Timestamp
    evolved_at: datetime = field(default_factory=datetime.now)

    def __post_init__(self):
        """Validate improvement score is properly bounded [0.0, 1.0]"""
        if self.improvement_score is not None and not 0.0 <= self.improvement_score <= 1.0:
            raise ValueError(
                f"improvement_score must be in [0.0, 1.0], got {self.improvement_score}. "
                f"This is a critical metric bound violation."
            )

        # Validate version numbers are positive
        if self.new_version < 1:
            raise ValueError(f"new_version must be >= 1, got {self.new_version}")

        if self.previous_version is not None and self.previous_version < 1:
            raise ValueError(f"previous_version must be >= 1, got {self.previous_version}")

    @staticmethod
    def generate_id() -> str:
        """Generate a unique evolution ID"""
        return f"evo_{uuid.uuid4().hex[:12]}"


# ==========================
# DIRECTIVE PROPOSAL
# ==========================

@dataclass
class DirectiveProposal:
    """
    Proposal for a new directive or modification to existing directive.
    Must be validated against the CONSTITUTION (the model-free governance
    authority) before activation — not a multi-agent vote.
    """
    proposal_id: str
    proposed_directive: InternalDirective

    # Proposal context
    proposal_reason: str
    based_on_directive_id: Optional[str] = None  # If modifying existing
    performance_data: Optional[Dict[str, Any]] = None

    # Validation result (populated after the constitution vets the proposal).
    # Shape: {approved: bool, average_compliance: float,
    #         law_compliance: {law_number: score}, violated_laws: [int], ...}
    constitution_validation: Optional[Dict[str, Any]] = None

    # Timestamps
    proposed_at: datetime = field(default_factory=datetime.now)

    @staticmethod
    def generate_id() -> str:
        """Generate a unique proposal ID"""
        return f"prop_{uuid.uuid4().hex[:12]}"

    def is_approved(self) -> bool:
        """Check if the proposal passed constitutional validation."""
        if not self.constitution_validation:
            return False
        return bool(self.constitution_validation.get("approved", False))


# ==========================
# A/B TEST
# ==========================

@dataclass
class DirectiveABTest:
    """
    A/B test comparing directive variants for scientific validation.

    Confidence scores are normalized [0.0, 1.0] and validated for mathematical integrity.
    """
    test_id: str
    test_name: str

    # Test configuration
    control_directive_id: str
    variant_directive_ids: List[str]

    # Test parameters
    duration_hours: int = 168  # 1 week default
    min_applications_per_variant: int = 50
    required_confidence: float = 0.90  # MUST be [0.0, 1.0]

    # Test status
    status: ABTestStatus = ABTestStatus.RUNNING

    # Test results
    winning_variant: Optional[str] = None
    confidence_level: Optional[float] = None  # MUST be [0.0, 1.0] when set
    results_summary: Optional[Dict[str, Any]] = None

    # Statistical metrics
    # Format: {variant_id: {mean, std_dev, sample_size, p_value}}
    statistical_analysis: Optional[Dict[str, Dict[str, float]]] = None

    # Timestamps
    started_at: datetime = field(default_factory=datetime.now)
    ended_at: Optional[datetime] = None

    def __post_init__(self):
        """Validate confidence scores are properly bounded [0.0, 1.0]"""
        if not 0.0 <= self.required_confidence <= 1.0:
            raise ValueError(
                f"required_confidence must be in [0.0, 1.0], got {self.required_confidence}. "
                f"This is a critical metric bound violation."
            )

        if self.confidence_level is not None and not 0.0 <= self.confidence_level <= 1.0:
            raise ValueError(
                f"confidence_level must be in [0.0, 1.0], got {self.confidence_level}. "
                f"This is a critical metric bound violation."
            )

        # Validate duration and min_applications are positive
        if self.duration_hours <= 0:
            raise ValueError(f"duration_hours must be positive, got {self.duration_hours}")

        if self.min_applications_per_variant <= 0:
            raise ValueError(f"min_applications_per_variant must be positive, got {self.min_applications_per_variant}")

    @staticmethod
    def generate_id() -> str:
        """Generate a unique test ID"""
        return f"abtest_{uuid.uuid4().hex[:8]}"

    def is_complete(self) -> bool:
        """Check if test is complete"""
        return self.status == ABTestStatus.COMPLETED

    def all_variant_ids(self) -> List[str]:
        """Get all variant IDs including control"""
        return [self.control_directive_id] + self.variant_directive_ids


# ==========================
# PERFORMANCE REPORT
# ==========================

@dataclass
class DirectivePerformanceReport:
    """
    Performance analysis report for a directive.

    All performance metrics are normalized [0.0, 1.0] and validated for mathematical integrity.
    """
    directive_id: str
    analysis_window_hours: int

    # Performance metrics - ALL NORMALIZED [0.0, 1.0]
    total_applications: int  # Absolute count (not bounded)
    successful_applications: int  # Absolute count (not bounded)
    success_rate: float  # MUST be [0.0, 1.0]

    avg_outcome_quality: float  # MUST be [0.0, 1.0]
    avg_intrinsic_reward: float  # MUST be [0.0, 1.0]
    avg_constitutional_alignment: float  # MUST be [0.0, 1.0]
    avg_system_health_impact: float  # MUST be [0.0, 1.0]
    overall_performance: float  # MUST be [0.0, 1.0]

    # Analysis results
    recommendation: str  # "maintain_current", "needs_improvement", "promote_and_replicate", "constitutional_violation_review"
    confidence: float  # MUST be [0.0, 1.0]

    # Failure patterns (if any)
    failure_patterns: List[Dict[str, Any]] = field(default_factory=list)

    # Timestamp
    analyzed_at: datetime = field(default_factory=datetime.now)

    def __post_init__(self):
        """Validate all performance metrics are properly bounded [0.0, 1.0]"""
        if not 0.0 <= self.success_rate <= 1.0:
            raise ValueError(
                f"success_rate must be in [0.0, 1.0], got {self.success_rate}. "
                f"This is a critical metric bound violation."
            )

        if not 0.0 <= self.avg_outcome_quality <= 1.0:
            raise ValueError(
                f"avg_outcome_quality must be in [0.0, 1.0], got {self.avg_outcome_quality}. "
                f"This is a critical metric bound violation."
            )

        if not 0.0 <= self.avg_intrinsic_reward <= 1.0:
            raise ValueError(
                f"avg_intrinsic_reward must be in [0.0, 1.0], got {self.avg_intrinsic_reward}. "
                f"This is a critical metric bound violation."
            )

        if not 0.0 <= self.avg_constitutional_alignment <= 1.0:
            raise ValueError(
                f"avg_constitutional_alignment must be in [0.0, 1.0], got {self.avg_constitutional_alignment}. "
                f"This is a critical metric bound violation."
            )

        if not 0.0 <= self.avg_system_health_impact <= 1.0:
            raise ValueError(
                f"avg_system_health_impact must be in [0.0, 1.0], got {self.avg_system_health_impact}. "
                f"This is a critical metric bound violation."
            )

        if not 0.0 <= self.overall_performance <= 1.0:
            raise ValueError(
                f"overall_performance must be in [0.0, 1.0], got {self.overall_performance}. "
                f"This is a critical metric bound violation."
            )

        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(
                f"confidence must be in [0.0, 1.0], got {self.confidence}. "
                f"This is a critical metric bound violation."
            )

        # Validate counts are non-negative
        if self.total_applications < 0:
            raise ValueError(f"total_applications must be >= 0, got {self.total_applications}")

        if self.successful_applications < 0:
            raise ValueError(f"successful_applications must be >= 0, got {self.successful_applications}")

        # Validate analysis window is positive
        if self.analysis_window_hours <= 0:
            raise ValueError(f"analysis_window_hours must be positive, got {self.analysis_window_hours}")
