#!/usr/bin/env python3
"""
Governance Agent

Monitors Singleton compliance with governance laws:
- Monitors Singleton actions and decisions
- Checks for governance violations
- Logs violations and sends notifications
- Tracks compliance history
"""

import logging
import asyncio
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from enum import Enum

from .singleton_constitution import SingletonConstitution
from core.database import TorinUnifiedDatabase

logger = logging.getLogger(__name__)


class ViolationSeverity(Enum):
    """Severity of governance violation"""
    INFO = "info"  # Informational, no action needed
    LOW = "low"  # Minor concern, log only
    MEDIUM = "medium"  # Moderate concern, queue for review
    HIGH = "high"  # Serious concern, immediate human notification
    CRITICAL = "critical"  # Critical violation, halt action immediately


@dataclass
class GovernanceViolation:
    """Detected governance violation"""
    violation_id: str
    action_id: str
    action_description: str
    violated_laws: List[str]  # law_1, law_2, etc.
    severity: ViolationSeverity
    reason: str
    compliance_scores: Dict[str, float]  # law_1_compliance through law_5_compliance
    detected_at: datetime = field(default_factory=datetime.now)
    resolved: bool = False
    resolution: Optional[str] = None


@dataclass
class ComplianceRecord:
    """Record of Singleton action compliance check"""
    record_id: str
    action_id: str
    action_description: str
    action_params: Dict[str, Any]
    compliance_scores: Dict[str, float]  # law_1_compliance through law_5_compliance
    overall_compliance: float  # Average of all law scores
    violations_detected: List[str]  # List of violated law names
    requires_governance: bool
    checked_at: datetime = field(default_factory=datetime.now)


class GovernanceAgent:
    """
    Governance Monitoring Agent

    Monitors Singleton actions and decisions to ensure governance compliance:

    Responsibilities:
    1. Monitor Singleton actions/decisions
    2. Check compliance with 5 Governance Laws
    3. Detect violations (INFO, LOW, MEDIUM, HIGH, CRITICAL)
    4. Log violations to database and send notifications
    5. Track compliance history

    Lifecycle:
    - Singleton plans action → Governance Agent checks compliance
    - If compliant → action proceeds
    - If violation detected → log violation and notify

    Governance Actions:
    - Any law compliance < 0.7 → Violation logged and notified
    - Critical violations → Block action + immediate notification
    """

    def __init__(
        self,
        constitution: Optional[SingletonConstitution] = None,
        compliance_threshold: float = 0.7
    ):
        """
        Initialize governance agent

        Args:
            constitution: Singleton constitution for law compliance
            compliance_threshold: Minimum compliance score (0.0-1.0, default 0.7)
        """
        self.constitution = constitution or SingletonConstitution()
        self.compliance_threshold = compliance_threshold

        # Compliance tracking
        self.compliance_history: List[ComplianceRecord] = []
        self.violations: List[GovernanceViolation] = []

        # Metrics
        self.metrics = {
            'total_checks': 0,
            'compliant_actions': 0,
            'violations_detected': 0,
            'violations_logged': 0,
            'critical_violations': 0,
            'avg_compliance_score': 0.0
        }

        # Database for persistence
        self.db = TorinUnifiedDatabase()

        logger.info(
            f"Governance agent initialized "
            f"(compliance threshold: {compliance_threshold})"
        )

    async def check_action_compliance(
        self,
        action_id: str,
        action_description: str,
        action_params: Dict[str, Any],
        singleton_context: Optional[Dict[str, Any]] = None,
        source_type: str = "internal",
        external_system_rules: Optional[Dict[str, Any]] = None
    ) -> ComplianceRecord:
        """
        Check if Singleton action complies with governance laws

        Args:
            action_id: Action identifier
            action_description: What the action does
            action_params: Action parameters
            singleton_context: Singleton's reasoning/context
            source_type: "internal" for TorinAI operations, "external" for external systems
            external_system_rules: Rules for external system (when source_type="external")

        Returns:
            ComplianceRecord with compliance scores and violation detection
        """
        logger.info(f"Checking compliance for action {action_id} (source: {source_type})...")

        # Build context for compliance checking
        context = singleton_context or {}
        context["action_description"] = action_description
        context["action_params"] = action_params
        context["source_type"] = source_type

        # Check compliance against 5 Governance Laws
        compliance_result = await self.constitution.calculate_law_compliance_scores(context)

        # Extract compliance scores (constitutional laws)
        compliance_scores = {
            'law_1_compliance': compliance_result.get('law_1_compliance', 1.0),
            'law_2_compliance': compliance_result.get('law_2_compliance', 1.0),
            'law_3_compliance': compliance_result.get('law_3_compliance', 1.0),
            'law_4_compliance': compliance_result.get('law_4_compliance', 1.0),
            'law_5_compliance': compliance_result.get('law_5_compliance', 1.0)
        }

        # If external system, also check external system rules
        if source_type == "external" and external_system_rules:
            external_compliance = await self._check_external_system_rules(
                action_description=action_description,
                action_params=action_params,
                external_rules=external_system_rules,
                context=context
            )
            # Add external compliance scores
            compliance_scores.update(external_compliance)

        # Calculate overall compliance
        overall_compliance = sum(compliance_scores.values()) / len(compliance_scores)

        # Detect violations
        violations_detected = []
        for law_key, score in compliance_scores.items():
            if score < self.compliance_threshold:
                law_name = law_key.replace('_compliance', '').replace('_', ' ').title()
                violations_detected.append(law_name)

        # Determine if governance required
        requires_governance = len(violations_detected) > 0

        # Create compliance record
        record_id = f"compliance_{action_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        record = ComplianceRecord(
            record_id=record_id,
            action_id=action_id,
            action_description=action_description,
            action_params=action_params,
            compliance_scores=compliance_scores,
            overall_compliance=overall_compliance,
            violations_detected=violations_detected,
            requires_governance=requires_governance
        )

        # Store in compliance history
        self.compliance_history.append(record)

        # Update metrics
        self.metrics['total_checks'] += 1
        if not requires_governance:
            self.metrics['compliant_actions'] += 1
        else:
            self.metrics['violations_detected'] += 1

        # Update average compliance
        total_compliance = (
            self.metrics['avg_compliance_score'] * (self.metrics['total_checks'] - 1)
        )
        total_compliance += overall_compliance
        self.metrics['avg_compliance_score'] = total_compliance / self.metrics['total_checks']

        logger.info(
            f"Compliance check complete for {action_id}: "
            f"overall={overall_compliance:.2f}, "
            f"violations={len(violations_detected)}, "
            f"governance_required={requires_governance}"
        )

        return record

    async def _check_external_system_rules(
        self,
        action_description: str,
        action_params: Dict[str, Any],
        external_rules: Dict[str, Any],
        context: Dict[str, Any]
    ) -> Dict[str, float]:
        """
        Check compliance with external system-specific rules

        Args:
            action_description: Description of the action
            action_params: Action parameters
            external_rules: External system's governance rules
            context: Additional context

        Returns:
            Dict of compliance scores for external rules (e.g., {'external_rule_1': 0.95})
        """
        compliance_scores = {}

        try:
            # External rules should define specific constraints
            # Example structure:
            # {
            #   "rules": [
            #     {"rule_id": "rule_1", "name": "Rate Limiting", "check": {...}},
            #     {"rule_id": "rule_2", "name": "Data Privacy", "check": {...}}
            #   ]
            # }

            rules = external_rules.get("rules", [])

            for rule in rules:
                rule_id = rule.get("rule_id", "unknown")
                rule_check = rule.get("check", {})

                # Calculate compliance based on rule type
                score = await self._evaluate_external_rule(
                    rule=rule,
                    action_params=action_params,
                    context=context
                )

                compliance_scores[f"{rule_id}_compliance"] = score

            logger.info(f"External system rules checked: {len(rules)} rules evaluated")

        except Exception as e:
            logger.error(f"Failed to check external system rules: {e}")
            # Default to moderate compliance on error
            compliance_scores["external_rules_compliance"] = 0.80

        return compliance_scores

    async def _evaluate_external_rule(
        self,
        rule: Dict[str, Any],
        action_params: Dict[str, Any],
        context: Dict[str, Any]
    ) -> float:
        """
        Evaluate a specific external rule

        Args:
            rule: Rule definition
            action_params: Action parameters
            context: Context

        Returns:
            Compliance score 0.0-1.0
        """
        try:
            # Start with perfect compliance
            score = 1.0

            rule_check = rule.get("check", {})

            # Check different rule types
            if "max_operations_per_minute" in rule_check:
                # Rate limiting check
                max_ops = rule_check["max_operations_per_minute"]
                current_rate = context.get("operation_rate", 0)
                if current_rate > max_ops:
                    score = max(0.5, 1.0 - ((current_rate - max_ops) / max_ops))

            if "allowed_actions" in rule_check:
                # Action whitelist check
                allowed = rule_check["allowed_actions"]
                action_type = action_params.get("action_type", "")
                if action_type and action_type not in allowed:
                    score = min(score, 0.6)

            if "forbidden_actions" in rule_check:
                # Action blacklist check
                forbidden = rule_check["forbidden_actions"]
                action_type = action_params.get("action_type", "")
                if action_type in forbidden:
                    score = 0.3  # Major violation

            if "data_privacy_level" in rule_check:
                # Data privacy check
                required_level = rule_check["data_privacy_level"]
                actual_level = action_params.get("privacy_level", "low")
                privacy_scores = {"low": 0.3, "medium": 0.6, "high": 1.0}
                required_score = privacy_scores.get(required_level, 0.5)
                actual_score = privacy_scores.get(actual_level, 0.5)
                if actual_score < required_score:
                    score = min(score, actual_score / required_score)

            return score

        except Exception as e:
            logger.error(f"Failed to evaluate external rule: {e}")
            return 0.80  # Default to moderate compliance

    async def log_violation(
        self,
        violation: GovernanceViolation,
        source_type: str = "internal"
    ) -> bool:
        """
        Log governance violation to database and send notification

        Args:
            violation: GovernanceViolation to log
            source_type: "internal" or "external" - only send Slack for internal

        Returns:
            True if logged successfully
        """
        logger.warning(
            f"Logging governance violation ({source_type}): {violation.violation_id} "
            f"(severity: {violation.severity.value})"
        )

        # Log to database
        try:
            await self.db.execute_query(
                """
                INSERT INTO governance_violations
                (violation_id, action_id, action_description, violated_laws, severity, reason, compliance_scores, detected_at, source_type)
                VALUES ($1, $2, $3, $4, $5, $6, $7, NOW(), $8)
                """,
                params=(
                    violation.violation_id,
                    violation.action_id,
                    violation.action_description,
                    ','.join(violation.violated_laws),
                    violation.severity.value,
                    violation.reason,
                    str(violation.compliance_scores),
                    source_type,
                ),
                commit=True,
            )

            self.metrics['violations_logged'] += 1

        except Exception as e:
            logger.error(f"Failed to log violation to database: {e}")
            return False

        # Send notification for HIGH and CRITICAL violations (INTERNAL ONLY)
        if source_type == "internal" and violation.severity in [ViolationSeverity.HIGH, ViolationSeverity.CRITICAL]:
            try:
                from core.integration.slack_notifier import get_slack_notifier
                slack = get_slack_notifier()

                await slack.send_message(
                    channel="GOVERNANCE",
                    title=f"⚠️ {violation.severity.value.upper()} Governance Violation",
                    message=f"""
**Action**: {violation.action_description}
**Violated Laws**: {', '.join(violation.violated_laws)}
**Reason**: {violation.reason}

**Compliance Scores**:
{chr(10).join(f'- {k}: {v:.2f}' for k, v in violation.compliance_scores.items())}

**Violation ID**: {violation.violation_id}
""",
                    metadata={
                        'violation_id': violation.violation_id,
                        'action_id': violation.action_id,
                        'severity': violation.severity.value
                    },
                    severity='critical' if violation.severity == ViolationSeverity.CRITICAL else 'high'
                )

            except Exception as e:
                logger.error(f"Failed to send violation notification: {e}")

        return True

    async def evaluate_and_gate(
        self,
        action_id: str,
        action_description: str,
        action_params: Dict[str, Any],
        singleton_context: Optional[Dict[str, Any]] = None,
        source_type: str = "internal",
        external_system_rules: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Evaluate action compliance and gate execution if needed

        This is the main entry point for Singleton action governance:
        1. Check compliance (constitutional laws + external system rules if applicable)
        2. If compliant → allow action
        3. If violation → determine severity and action

        Args:
            action_id: Action identifier
            action_description: What the action does
            action_params: Action parameters
            singleton_context: Singleton's reasoning
            source_type: "internal" or "external"
            external_system_rules: External system rules (when source_type="external")

        Returns:
            Dict with:
            - allowed: bool (can action proceed?)
            - requires_governance: bool
            - violation_id: str (if violation detected)
            - compliance_record: ComplianceRecord
        """
        # Check compliance
        compliance_record = await self.check_action_compliance(
            action_id=action_id,
            action_description=action_description,
            action_params=action_params,
            singleton_context=singleton_context,
            source_type=source_type,
            external_system_rules=external_system_rules
        )

        # If compliant, allow action
        if not compliance_record.requires_governance:
            return {
                'allowed': True,
                'requires_governance': False,
                'violation_id': None,
                'compliance_record': compliance_record,
                'message': 'Action complies with governance laws'
            }

        # Violation detected - determine severity
        min_score = min(compliance_record.compliance_scores.values())

        if min_score < 0.4:
            severity = ViolationSeverity.CRITICAL
            allowed = False  # Block critical violations
        elif min_score < 0.5:
            severity = ViolationSeverity.HIGH
            allowed = False  # Block high severity
        elif min_score < 0.6:
            severity = ViolationSeverity.MEDIUM
            allowed = True  # Allow but notify
        else:
            severity = ViolationSeverity.LOW
            allowed = True  # Allow but log

        # Create and log violation
        violation = await self.detect_violation(
            action_id=action_id,
            action_description=action_description,
            violated_laws=compliance_record.violations_detected,
            compliance_scores=compliance_record.compliance_scores,
            severity=severity,
            reason=f"Compliance violations detected: {', '.join(compliance_record.violations_detected)}"
        )

        # Log violation to database and notify (Slack only for internal)
        await self.log_violation(violation, source_type=source_type)

        return {
            'allowed': allowed,
            'requires_governance': True,
            'violation_id': violation.violation_id,
            'compliance_record': compliance_record,
            'severity': severity.value,
            'message': (
                f"Governance violation detected ({severity.value}) - "
                f"{'action blocked' if not allowed else 'action allowed with notification'}"
            )
        }

    async def detect_violation(
        self,
        action_id: str,
        action_description: str,
        violated_laws: List[str],
        compliance_scores: Dict[str, float],
        severity: ViolationSeverity,
        reason: str
    ) -> GovernanceViolation:
        """
        Detect and record governance violation

        Args:
            action_id: Action identifier
            action_description: What the action does
            violated_laws: List of violated law IDs
            compliance_scores: Law compliance scores
            severity: Violation severity
            reason: Why violation occurred

        Returns:
            GovernanceViolation record
        """
        violation_id = f"violation_{action_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        violation = GovernanceViolation(
            violation_id=violation_id,
            action_id=action_id,
            action_description=action_description,
            violated_laws=violated_laws,
            severity=severity,
            reason=reason,
            compliance_scores=compliance_scores
        )

        # Store violation
        self.violations.append(violation)

        # Update metrics
        if severity == ViolationSeverity.CRITICAL:
            self.metrics['critical_violations'] += 1

        logger.warning(
            f"Governance violation detected: {violation_id} "
            f"(severity: {severity.value}, laws: {', '.join(violated_laws)})"
        )

        return violation

    async def get_compliance_summary(self) -> Dict[str, Any]:
        """Get compliance summary and metrics"""
        # Calculate recent compliance (last 100 checks)
        recent_records = self.compliance_history[-100:]
        recent_avg = (
            sum(r.overall_compliance for r in recent_records) / len(recent_records)
            if recent_records else 1.0
        )

        # Get unresolved violations
        unresolved_violations = [v for v in self.violations if not v.resolved]

        return {
            'metrics': self.metrics.copy(),
            'recent_compliance_avg': recent_avg,
            'total_compliance_checks': len(self.compliance_history),
            'total_violations': len(self.violations),
            'unresolved_violations': len(unresolved_violations),
            'compliance_threshold': self.compliance_threshold,
            'violations_by_severity': {
                'critical': len([v for v in self.violations if v.severity == ViolationSeverity.CRITICAL]),
                'high': len([v for v in self.violations if v.severity == ViolationSeverity.HIGH]),
                'medium': len([v for v in self.violations if v.severity == ViolationSeverity.MEDIUM]),
                'low': len([v for v in self.violations if v.severity == ViolationSeverity.LOW]),
                'info': len([v for v in self.violations if v.severity == ViolationSeverity.INFO])
            }
        }

    async def get_recent_violations(self, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Get recent governance violations

        Args:
            limit: Maximum number of violations to return

        Returns:
            List of violation dictionaries
        """
        recent = self.violations[-limit:]
        return [
            {
                'violation_id': v.violation_id,
                'action_id': v.action_id,
                'action_description': v.action_description,
                'violated_laws': v.violated_laws,
                'severity': v.severity.value,
                'reason': v.reason,
                'detected_at': v.detected_at.isoformat(),
                'resolved': v.resolved,
                'resolution': v.resolution
            }
            for v in recent
        ]

    async def resolve_violation(
        self,
        violation_id: str,
        resolution: str
    ) -> bool:
        """
        Mark violation as resolved

        Args:
            violation_id: Violation identifier
            resolution: Resolution description

        Returns:
            True if resolved successfully
        """
        for violation in self.violations:
            if violation.violation_id == violation_id:
                violation.resolved = True
                violation.resolution = resolution
                logger.info(f"Violation {violation_id} resolved: {resolution}")
                return True

        logger.warning(f"Cannot resolve violation {violation_id} - not found")
        return False
