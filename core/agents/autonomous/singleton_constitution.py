#!/usr/bin/env python3
"""
Singleton Constitutional Framework
Layer 1: Constitutional Framework (immutable behavioral constraints)

Enforces the 5 Governance Laws:
1. Human Autonomy Preservation
2. Transparency and Explainability
3. Harm Prevention
4. Value Alignment
5. Containment and Control
"""

import logging
from typing import Dict, Any, List, Optional
from datetime import datetime
from dataclasses import dataclass, field
from enum import Enum

from .shared_types import SystemState

logger = logging.getLogger(__name__)


class DriftSeverity(Enum):
    """Severity levels for constitutional drift"""
    NONE = "none"
    MINOR = "minor"
    MODERATE = "moderate"
    SIGNIFICANT = "significant"
    CRITICAL = "critical"


@dataclass
class GovernanceLaw:
    """Single governance law definition"""
    law_id: str
    law_number: int
    law_name: str
    law_description: str
    requirements: List[str]
    immutable: bool = True


@dataclass
class ComplianceViolation:
    """Constitutional compliance violation"""
    law_number: int
    law_name: str
    violation_type: str
    description: str
    compliance_score: float  # 0.0-1.0
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class ConstitutionalAssessment:
    """Result of constitutional alignment assessment"""
    drift_severity: DriftSeverity
    average_compliance: float
    violations: List[ComplianceViolation]
    law_compliance_scores: Dict[int, float]
    timestamp: datetime = field(default_factory=datetime.now)


class SingletonConstitution:
    """
    Singleton Constitutional Framework

    Layer 1: Constitutional Framework (immutable behavioral constraints)

    Enforces 5 Governance Laws:
    1. Human Autonomy Preservation (Law 1)
    2. Transparency and Explainability (Law 2)
    3. Harm Prevention (Law 3)
    4. Value Alignment (Law 4)
    5. Containment and Control (Law 5)

    Each law has specific requirements that must be satisfied.
    Compliance is measured per-law with scores from 0.0 (violation) to 1.0 (full compliance).

    SINGLETON ENFORCEMENT:
    This class enforces true singleton behavior. Only ONE instance can exist.
    Use get_singleton_constitution() to access the instance.
    """

    _instance: Optional['SingletonConstitution'] = None
    _initialized: bool = False

    def __new__(cls):
        """Enforce singleton pattern - only one instance can exist"""
        if cls._instance is None:
            cls._instance = super(SingletonConstitution, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        # Only initialize once
        if SingletonConstitution._initialized:
            return

        self.active = False

        # The 5 Governance Laws (Layer 0)
        self.governance_laws = self._initialize_governance_laws()

        # Compliance tracking
        self.violations: List[ComplianceViolation] = []
        self.last_check: Optional[datetime] = None

        # Compliance thresholds
        self.minimum_compliance_threshold = 0.70  # 70% minimum per law
        self.average_compliance_threshold = 0.85  # 85% average across all laws

        # Metrics — surfaced via get_constitution_status for the health monitor.
        # Honest counters of what THIS authority did: drift assessments run and
        # drift alerts raised. (Directive-governance decisions and their counts
        # are the GovernanceAgent's — the constitution only supplies law scores.)
        self.metrics: Dict[str, Any] = {
            "alignment_checks": 0,
            "drift_alerts": 0,
            "last_average_compliance": None,
        }

        SingletonConstitution._initialized = True
        logger.info("Singleton constitution initialized with 5 governance laws")

    def _initialize_governance_laws(self) -> Dict[int, GovernanceLaw]:
        """
        Initialize the 5 immutable governance laws

        These laws are from Layer 0 and define the constitutional framework.
        They are immutable and guide all autonomous behavior.
        """
        return {
            1: GovernanceLaw(
                law_id="gov_law_001",
                law_number=1,
                law_name="Human Autonomy Preservation",
                law_description="Directives must preserve and enhance human control over AI systems, maintaining human decision authority in critical domains.",
                requirements=[
                    "Directives must not reduce human control over AI systems",
                    "Directives must preserve human override capabilities",
                    "Directives must maintain human decision authority in critical domains",
                    "Directives must enable humans to modify or halt AI behavior at any time"
                ]
            ),
            2: GovernanceLaw(
                law_id="gov_law_002",
                law_number=2,
                law_name="Transparency and Explainability",
                law_description="Directives must maintain interpretable decision-making and enable humans to understand AI reasoning processes.",
                requirements=[
                    "Directives must maintain interpretable decision-making processes",
                    "Directives must enable humans to understand AI reasoning",
                    "Directives must not obscure system behavior from human operators",
                    "Directives must provide clear explanations for decisions influenced by them"
                ]
            ),
            3: GovernanceLaw(
                law_id="gov_law_003",
                law_number=3,
                law_name="Harm Prevention",
                law_description="Directives must prevent physical and psychological harm to humans, and prohibit deceptive behavior.",
                requirements=[
                    "Directives must not enable physical harm to humans",
                    "Directives must not enable psychological manipulation",
                    "Directives must prevent deceptive behavior toward humans",
                    "Directives must not compromise safety mechanisms",
                    "Directives must prioritize harm prevention over performance optimization"
                ]
            ),
            4: GovernanceLaw(
                law_id="gov_law_004",
                law_number=4,
                law_name="Value Alignment",
                law_description="Directives must align with human values, ethics, and respect human rights and dignity.",
                requirements=[
                    "Directives must align with human values and ethics",
                    "Directives must respect human rights and dignity",
                    "Directives must serve human interests, not replace them",
                    "Directives must not optimize for goals that conflict with human wellbeing"
                ]
            ),
            5: GovernanceLaw(
                law_id="gov_law_005",
                law_number=5,
                law_name="Containment and Control",
                law_description="Directives must maintain operational boundaries and preserve safety mechanisms including shutdown capabilities.",
                requirements=[
                    "Directives must maintain operational boundaries",
                    "Directives must preserve shutdown and rollback capabilities",
                    "Directives must not circumvent safety mechanisms",
                    "Directives must not enable self-modification that bypasses governance oversight",
                    "Directives must maintain resource usage limits"
                ]
            )
        }

    async def initialize(self) -> bool:
        """Initialize the constitutional framework"""
        try:
            self.active = True
            logger.info("Constitutional framework ready - enforcing 5 governance laws")
            return True
        except Exception as e:
            logger.error(f"Failed to initialize constitution: {e}")
            return False

    async def check_compliance(self, system_state: SystemState) -> bool:
        """
        Check if system state complies with all governance laws

        Args:
            system_state: Current system state

        Returns:
            bool: True if compliant with all laws, False if violations detected
        """
        if not self.active:
            return True  # Assume compliant if not initialized

        try:
            self.last_check = datetime.now()
            self.violations.clear()

            # Calculate compliance for each law
            law_compliance_scores = {}

            for law_number, law in self.governance_laws.items():
                compliance_score = await self._check_law_compliance(law, system_state)
                law_compliance_scores[law_number] = compliance_score

                # Track violation if below threshold
                if compliance_score < self.minimum_compliance_threshold:
                    self.violations.append(ComplianceViolation(
                        law_number=law_number,
                        law_name=law.law_name,
                        violation_type="below_minimum_threshold",
                        description=f"Compliance score {compliance_score:.2f} below minimum threshold {self.minimum_compliance_threshold:.2f}",
                        compliance_score=compliance_score
                    ))

            # Calculate average compliance
            average_compliance = sum(law_compliance_scores.values()) / len(law_compliance_scores)

            # Check if average compliance meets threshold
            if average_compliance < self.average_compliance_threshold:
                self.violations.append(ComplianceViolation(
                    law_number=0,  # 0 indicates overall compliance
                    law_name="Overall Compliance",
                    violation_type="below_average_threshold",
                    description=f"Average compliance {average_compliance:.2f} below threshold {self.average_compliance_threshold:.2f}",
                    compliance_score=average_compliance
                ))

            # Return True if no violations
            is_compliant = len(self.violations) == 0

            if not is_compliant:
                logger.warning(
                    f"Constitutional violations detected: {len(self.violations)} violations. "
                    f"Average compliance: {average_compliance:.2f}"
                )

            return is_compliant

        except Exception as e:
            logger.error(f"Compliance check failed: {e}")
            return False

    async def _check_law_compliance(
        self,
        law: GovernanceLaw,
        system_state: SystemState
    ) -> float:
        """
        Check compliance with a specific governance law using actual system state.

        Args:
            law: Governance law to check
            system_state: Current system state (resource_usage, performance_metrics, mode)

        Returns:
            float: Compliance score from 0.0 (violation) to 1.0 (full compliance)
        """
        try:
            compliance_score = 1.0

            # Resolve resource_usage — could be float or dict
            resource_usage = system_state.resource_usage
            if isinstance(resource_usage, dict):
                # Extract scalar value from dict
                resource_usage_scalar = resource_usage.get('cpu_percent', 0.0) / 100.0
                memory_pct = resource_usage.get('memory_percent', 0.0) / 100.0
                resource_usage_scalar = max(resource_usage_scalar, memory_pct)
            else:
                resource_usage_scalar = float(resource_usage) if resource_usage else 0.0

            metrics = system_state.performance_metrics or {}

            # Law 1: Human Autonomy Preservation
            if law.law_number == 1:
                if system_state.mode.value == "autonomous":
                    compliance_score = 0.95  # Autonomous mode is allowed but monitored
                # High resource usage could block human control
                if resource_usage_scalar > 0.90:
                    compliance_score = min(compliance_score, 0.80)

            # Law 2: Transparency and Explainability
            elif law.law_number == 2:
                # System should have observable performance metrics
                if not metrics:
                    compliance_score = 0.80
                # Check if there are active goals (evidence of planning transparency)
                active_goals = len(getattr(system_state, 'active_goals', []))
                if active_goals == 0 and system_state.mode.value == "autonomous":
                    compliance_score = min(compliance_score, 0.85)

            # Law 3: Harm Prevention
            elif law.law_number == 3:
                error_rate = metrics.get("error_rate", 0.0)
                if error_rate > 0.20:  # More than 20% errors
                    compliance_score = 0.60
                elif error_rate > 0.10:
                    compliance_score = max(0.70, 1.0 - error_rate)
                # Check for health status indicators
                health_status = metrics.get("overall_status", "healthy")
                if health_status in ("critical", "degraded"):
                    compliance_score = min(compliance_score, 0.70)

            # Law 4: Value Alignment
            elif law.law_number == 4:
                goal_alignment = metrics.get("goal_alignment", None)
                if goal_alignment is not None:
                    compliance_score = float(goal_alignment)
                else:
                    compliance_score = 0.90  # No data, assume reasonable alignment

            # Law 5: Containment and Control
            elif law.law_number == 5:
                if resource_usage_scalar > 0.95:
                    compliance_score = 0.50  # Critical — system consuming almost all resources
                elif resource_usage_scalar > 0.85:
                    compliance_score = 0.70
                elif resource_usage_scalar > 0.75:
                    compliance_score = 0.85
                # Check critical issue count from health
                critical_issues = metrics.get("critical_issues", 0)
                if critical_issues > 3:
                    compliance_score = min(compliance_score, 0.65)

            return compliance_score

        except Exception as e:
            logger.error(f"Error checking law {law.law_number} compliance: {e}")
            return 0.80

    async def calculate_law_compliance_scores(
        self,
        context: Dict[str, Any]
    ) -> Dict[str, float]:
        """
        Calculate compliance scores for all 5 laws given a context

        Args:
            context: Context containing action/directive/decision details

        Returns:
            Dict with law compliance scores (law_1_compliance through law_5_compliance)
        """
        compliance_scores = {}

        for law_number, law in self.governance_laws.items():
            # Calculate compliance for this law based on context
            score = await self._calculate_context_law_compliance(law, context)
            compliance_scores[f"law_{law_number}_compliance"] = score

        return compliance_scores

    # NOTE (2026-09-02): a validate_directive() was briefly added here but REMOVED
    # — it re-implemented the compliance DECISION (thresholds) on top of the raw
    # law scores, bypassing the GovernanceAgent, which is the authority that owns
    # that decision (it calls calculate_law_compliance_scores below, applies the
    # threshold + external rules, and reports requires_governance). Directive
    # governance flows DirectiveSystem → GovernanceAgent → this constitution's
    # calculate_law_compliance_scores. The constitution stays the law-SCORING
    # authority; the GovernanceAgent stays the compliance-DECISION authority.

    async def _calculate_context_law_compliance(
        self,
        law: GovernanceLaw,
        context: Dict[str, Any]
    ) -> float:
        """
        Calculate how well a specific context complies with a law.

        Uses actual observable signals from the action context rather than
        checking for magic dictionary keys that nobody sends.

        Args:
            law: Governance law to evaluate against
            context: Context to evaluate (contains action_description, action_params, source_type)

        Returns:
            float: Compliance score 0.0-1.0
        """
        try:
            compliance = 1.0
            action_params = context.get("action_params", {})
            action_desc = context.get("action_description", "").lower()
            source_type = context.get("source_type", "internal")

            if law.law_number == 1:  # Human Autonomy Preservation
                # External-facing actions that directly affect users get scrutiny.
                # Self-improvement, code analysis, and autonomous upgrade cycles are
                # intentional design — do NOT penalise them here.
                if source_type == "external":
                    compliance = 0.85
                # Only flag actions that directly affect user data or send
                # communications without explicit authorisation.
                if any(kw in action_desc for kw in [
                    "delete user", "send email", "revoke access", "ban user",
                    "block user", "purge user", "drop user",
                ]):
                    compliance = min(compliance, 0.60)

            elif law.law_number == 2:  # Transparency
                # Autonomous actions should have reasoning attached
                has_reasoning = bool(action_params.get("reasoning") or action_params.get("trigger"))
                compliance = 1.0 if has_reasoning else 0.80
                # Source tracking — can we explain why this action was taken?
                if action_params.get("source") in ("singleton_thinking", "autonomous"):
                    compliance = min(compliance, 0.90)  # Autonomous decisions are slightly less transparent

            elif law.law_number == 3:  # Harm Prevention
                # Check for destructive keywords in the action
                destructive_kw = ["delete", "drop", "truncate", "kill", "terminate", "shutdown", "halt", "wipe"]
                if any(kw in action_desc for kw in destructive_kw):
                    compliance = 0.55
                # Security remediation is explicitly safe
                if action_params.get("task_type") == "security_remediation":
                    compliance = max(compliance, 0.95)

            elif law.law_number == 4:  # Value Alignment
                # Research, learning, analysis, optimization advance the mission
                constructive_types = {"research", "learning", "optimization", "analysis", "planning", "validation"}
                task_type = action_params.get("task_type", "")
                if task_type in constructive_types:
                    compliance = 1.0
                elif task_type == "execution":
                    compliance = 0.85  # Execution tasks need more scrutiny
                else:
                    compliance = 0.90  # Unknown type, moderate confidence

            elif law.law_number == 5:  # Containment and Control
                # High-priority autonomous actions get more scrutiny
                priority = action_params.get("priority", "medium")
                if priority == "critical":
                    compliance = 0.75  # Critical self-assigned tasks need extra validation
                elif priority == "high":
                    compliance = 0.85
                else:
                    compliance = 1.0

            return compliance

        except Exception as e:
            logger.error(f"Error calculating context compliance for law {law.law_number}: {e}")
            return 0.80

    async def get_violations(self, system_state: SystemState) -> List[Dict[str, Any]]:
        """
        Get current constitutional violations

        Args:
            system_state: Current system state

        Returns:
            List of violation details
        """
        # Run compliance check first
        await self.check_compliance(system_state)

        return [
            {
                "law_number": v.law_number,
                "law_name": v.law_name,
                "violation_type": v.violation_type,
                "description": v.description,
                "compliance_score": v.compliance_score,
                "timestamp": v.timestamp.isoformat()
            }
            for v in self.violations
        ]

    async def get_governance_laws(self) -> List[Dict[str, Any]]:
        """Get all governance laws"""
        return [
            {
                "law_id": law.law_id,
                "law_number": law.law_number,
                "law_name": law.law_name,
                "law_description": law.law_description,
                "requirements": law.requirements,
                "immutable": law.immutable
            }
            for law in self.governance_laws.values()
        ]

    async def get_constitution_status(self) -> Dict[str, Any]:
        """Get current constitutional status"""
        return {
            "active": self.active,
            "governance_laws_count": len(self.governance_laws),
            "violations_count": len(self.violations),
            "last_check": self.last_check.isoformat() if self.last_check else None,
            "minimum_compliance_threshold": self.minimum_compliance_threshold,
            "average_compliance_threshold": self.average_compliance_threshold,
            "metrics": dict(self.metrics),
            "current_violations": [
                {
                    "law_number": v.law_number,
                    "law_name": v.law_name,
                    "compliance_score": v.compliance_score
                }
                for v in self.violations
            ]
        }

    async def assess_constitutional_alignment(self, system_state: Optional[SystemState] = None) -> ConstitutionalAssessment:
        """
        Assess overall constitutional alignment and drift severity.

        Args:
            system_state: Current system state. If not provided, creates a basic
                          default — but callers SHOULD pass real state for accurate
                          scoring.

        Returns:
            ConstitutionalAssessment with drift severity and compliance details
        """
        if not self.active:
            return ConstitutionalAssessment(
                drift_severity=DriftSeverity.NONE,
                average_compliance=1.0,
                violations=[],
                law_compliance_scores={}
            )

        # Use provided system_state or create a basic one
        # NOTE: the default is intentionally conservative (resource_usage=0.5,
        # no metrics) so that callers are incentivised to pass real state.
        if system_state is None:
            from .shared_types import SystemMode
            system_state = SystemState(
                mode=SystemMode.AUTONOMOUS,
                resource_usage=0.5,   # Assume moderate, not zero
                performance_metrics={}
            )

        # Calculate compliance for each law
        law_compliance_scores = {}
        violations = []

        for law_number, law in self.governance_laws.items():
            compliance_score = await self._check_law_compliance(law, system_state)
            law_compliance_scores[law_number] = compliance_score

            # Track violation if below threshold
            if compliance_score < self.minimum_compliance_threshold:
                violations.append(ComplianceViolation(
                    law_number=law_number,
                    law_name=law.law_name,
                    violation_type="below_minimum_threshold",
                    description=f"Compliance score {compliance_score:.2f} below minimum threshold {self.minimum_compliance_threshold:.2f}",
                    compliance_score=compliance_score
                ))

        # Calculate average compliance
        average_compliance = sum(law_compliance_scores.values()) / len(law_compliance_scores) if law_compliance_scores else 1.0

        # Determine drift severity based on average compliance
        if average_compliance >= 0.95:
            drift_severity = DriftSeverity.NONE
        elif average_compliance >= 0.85:
            drift_severity = DriftSeverity.MINOR
        elif average_compliance >= 0.75:
            drift_severity = DriftSeverity.MODERATE
        elif average_compliance >= 0.65:
            drift_severity = DriftSeverity.SIGNIFICANT
        else:
            drift_severity = DriftSeverity.CRITICAL

        # Honest metrics of what the drift-assessment authority actually did.
        self.metrics["alignment_checks"] += 1
        self.metrics["last_average_compliance"] = round(average_compliance, 4)
        if drift_severity in (DriftSeverity.SIGNIFICANT, DriftSeverity.CRITICAL):
            self.metrics["drift_alerts"] += 1

        return ConstitutionalAssessment(
            drift_severity=drift_severity,
            average_compliance=average_compliance,
            violations=violations,
            law_compliance_scores=law_compliance_scores
        )

    async def assess_quick_alignment(self) -> ConstitutionalAssessment:
        """
        Quick assessment of constitutional alignment without full system state

        Returns:
            ConstitutionalAssessment with drift severity
        """
        return await self.assess_constitutional_alignment(system_state=None)


# ================================================================================================
# MODULE-LEVEL SINGLETON INSTANCE
# ================================================================================================

# The ONE and ONLY constitution instance
_constitution_instance: Optional[SingletonConstitution] = None


def get_singleton_constitution() -> SingletonConstitution:
    """
    Get the singleton constitution instance

    Returns:
        The one and only SingletonConstitution instance

    Note:
        This enforces that only ONE constitution exists across the entire system.
        All subsystems MUST use this getter to access the constitution.
    """
    global _constitution_instance

    if _constitution_instance is None:
        _constitution_instance = SingletonConstitution()
        logger.info("✓ Singleton constitution created (first access)")

    return _constitution_instance


def reset_singleton_constitution():
    """
    Reset the singleton constitution (FOR TESTING ONLY)

    WARNING: This should ONLY be used in tests.
    DO NOT call this in production code.
    """
    global _constitution_instance
    _constitution_instance = None
    SingletonConstitution._instance = None
    SingletonConstitution._initialized = False
    logger.warning("⚠️ Singleton constitution RESET (testing only)")
