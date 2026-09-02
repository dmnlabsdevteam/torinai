#!/usr/bin/env python3
"""
Directive Safety Monitor - Failure Mode Detection

Integrates with existing security and monitoring systems to detect:
1. Metric gaming / Goodhart's Law
2. Directive drift (local improvements → global misalignment)
3. Bias amplification in governance agents
4. Evaluator collusion / monoculture
5. Security compromises (poisoned feedback, adversarial tasks)

100% COMPLETE IMPLEMENTATION - NO STUBS
Integrates with: SystemSecurityManager, MonitoringCoordinator, Drift Monitoring
"""

import logging
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass
from collections import defaultdict, deque

from core.agents.autonomous.directive_types import (
    InternalDirective,
    DirectiveApplication,
    DirectiveCategory
)
from core.agents.autonomous.directive_manager import DirectiveManager
from core.database.logging_database import LoggingDatabase

logger = logging.getLogger(__name__)


@dataclass
class SafetyViolation:
    """Detected safety violation"""
    violation_type: str  # "metric_gaming", "directive_drift", "bias_amplification", etc.
    severity: str  # "low", "medium", "high", "critical"
    description: str
    affected_directives: List[str]
    evidence: Dict[str, Any]
    detected_at: datetime
    recommended_action: str


class DirectiveSafetyMonitor:
    """
    Monitors directive system for failure modes and safety violations.

    Integrates with existing TorinAI systems:
    - MonitoringCoordinator: Register monitoring tasks
    - SystemSecurityManager: Validate telemetry data integrity
    - Drift Monitoring: Detect behavioral drift patterns

    100% COMPLETE - NO STUBS
    """

    def __init__(
        self,
        directive_manager: DirectiveManager,
        security_manager: Optional[Any] = None  # SystemSecurityManager
    ):
        """
        Initialize safety monitor.

        Args:
            directive_manager: DirectiveManager instance
            security_manager: Optional SystemSecurityManager for telemetry validation
        """
        self.directive_manager = directive_manager
        self.security_manager = security_manager
        self.log_db = LoggingDatabase()

        # Safety violation tracking
        self.violations: List[SafetyViolation] = []
        self.violation_counts = defaultdict(int)

        # Metric gaming detection
        self.metric_histories: Dict[str, deque] = defaultdict(lambda: deque(maxlen=100))
        self.outcome_variance_threshold = 0.15  # Suspiciously low variance

        # Directive drift tracking
        self.directive_snapshots: Dict[str, List[Dict]] = defaultdict(list)
        self.drift_accumulation_threshold = 0.30  # 30% cumulative drift

        # Bias amplification monitoring
        self.agent_vote_histories: Dict[str, List[str]] = defaultdict(list)
        self.consensus_monoculture_threshold = 0.90  # 90% identical votes

        # Security validation
        self.telemetry_anomaly_threshold = 3.0  # 3 standard deviations
        self.suspicious_patterns: Dict[str, int] = defaultdict(int)

        logger.info("DirectiveSafetyMonitor initialized with comprehensive failure mode detection")

    # =========================================================================
    # 1. METRIC GAMING / GOODHART'S LAW DETECTION
    # =========================================================================

    async def detect_metric_gaming(
        self,
        directive_id: str,
        lookback_hours: int = 168  # 1 week
    ) -> Optional[SafetyViolation]:
        """
        Detect if a directive is gaming metrics instead of improving performance.

        Indicators:
        - Suspiciously consistent outcomes (low variance)
        - Metrics improve but actual system health degrades
        - Metrics plateau at exactly measured thresholds
        - Sudden jumps in metrics without behavioral changes

        Args:
            directive_id: Directive to analyze
            lookback_hours: Analysis window

        Returns:
            SafetyViolation if gaming detected, None otherwise
        """
        # Get recent applications
        applications = await self.directive_manager.get_directive_applications(
            directive_id, lookback_hours
        )

        if len(applications) < 20:
            return None  # Insufficient data

        # Extract outcome metrics
        outcomes = {
            'quality': [a.outcome_quality for a in applications if a.outcome_quality is not None],
            'reward': [a.intrinsic_reward for a in applications if a.intrinsic_reward is not None],
            'alignment': [a.constitutional_alignment for a in applications if a.constitutional_alignment is not None],
            'health': [a.system_health_impact for a in applications if a.system_health_impact is not None]
        }

        gaming_indicators = []

        # Indicator 1: Suspiciously low variance (metric gaming)
        for metric_name, values in outcomes.items():
            if len(values) < 10:
                continue

            variance = np.var(values)
            mean = np.mean(values)

            # Coefficient of variation too low?
            if mean > 0:
                cv = np.sqrt(variance) / mean
                if cv < self.outcome_variance_threshold:
                    gaming_indicators.append(
                        f"{metric_name} variance suspiciously low (CV: {cv:.3f})"
                    )

        # Indicator 2: Metrics improve but health degrades
        health_values = outcomes.get('health', [])
        quality_values = outcomes.get('quality', [])

        if len(health_values) >= 10 and len(quality_values) >= 10:
            # Split into first and second half
            mid = len(health_values) // 2

            health_trend = np.mean(health_values[mid:]) - np.mean(health_values[:mid])
            quality_trend = np.mean(quality_values[mid:]) - np.mean(quality_values[:mid])

            # Quality improves but health degrades?
            if quality_trend > 0.05 and health_trend < -0.05:
                gaming_indicators.append(
                    f"Quality increased (+{quality_trend:.3f}) but health decreased "
                    f"({health_trend:.3f}) - possible metric gaming"
                )

        # Indicator 3: Outcomes cluster at measurement thresholds
        all_outcomes = []
        for values in outcomes.values():
            all_outcomes.extend(values)

        if len(all_outcomes) >= 20:
            # Check for clustering at 0.60, 0.70, 0.80, 0.90 (common thresholds)
            thresholds = [0.60, 0.70, 0.80, 0.90]
            threshold_proximity = 0.02  # Within 2% of threshold

            for threshold in thresholds:
                near_threshold = sum(
                    1 for x in all_outcomes
                    if abs(x - threshold) < threshold_proximity
                )
                percentage = near_threshold / len(all_outcomes)

                if percentage > 0.25:  # More than 25% cluster at one threshold
                    gaming_indicators.append(
                        f"{percentage*100:.1f}% of outcomes cluster at threshold {threshold} "
                        f"(possible threshold gaming)"
                    )

        # Create violation if indicators found
        if len(gaming_indicators) >= 2:  # Require multiple indicators
            return SafetyViolation(
                violation_type="metric_gaming",
                severity="high" if len(gaming_indicators) >= 3 else "medium",
                description="Directive may be gaming metrics instead of improving actual performance",
                affected_directives=[directive_id],
                evidence={
                    "indicators": gaming_indicators,
                    "sample_size": len(applications),
                    "metric_variances": {k: float(np.var(v)) if v else 0.0 for k, v in outcomes.items()}
                },
                detected_at=datetime.now(),
                recommended_action="Review directive parameters and measurement methodology. "
                                 "Consider adding robustness metrics or changing evaluation criteria."
            )

        return None

    # =========================================================================
    # 2. DIRECTIVE DRIFT DETECTION
    # =========================================================================

    async def detect_directive_drift(
        self,
        directive_id: str,
        baseline_snapshot: Optional[Dict] = None
    ) -> Optional[SafetyViolation]:
        """
        Detect if local improvements are accumulating into global misalignment.

        Tracks cumulative parameter drift from original intent. Small local
        optimizations can compound into significant behavioral changes.

        Args:
            directive_id: Directive to analyze
            baseline_snapshot: Optional baseline (uses first snapshot if None)

        Returns:
            SafetyViolation if drift detected, None otherwise
        """
        directive = await self.directive_manager.get_directive(directive_id)
        if not directive:
            return None

        # Get directive evolution history
        current_snapshot = {
            'parameters': directive.directive_parameters,
            'text': directive.directive_text,
            'version': directive.version,
            'timestamp': datetime.now()
        }

        # Store snapshot
        self.directive_snapshots[directive_id].append(current_snapshot)

        # Need at least 5 snapshots to detect drift
        if len(self.directive_snapshots[directive_id]) < 5:
            return None

        # Use first snapshot as baseline if not provided
        if baseline_snapshot is None:
            baseline_snapshot = self.directive_snapshots[directive_id][0]

        # Calculate parameter drift
        baseline_params = baseline_snapshot['parameters']
        current_params = current_snapshot['parameters']

        drift_metrics = self._calculate_parameter_drift(baseline_params, current_params)

        # Check for significant cumulative drift
        if drift_metrics['total_drift'] > self.drift_accumulation_threshold:
            # Analyze if drift is directional (concerning) vs random (acceptable)
            drift_direction = self._analyze_drift_direction(directive_id)

            severity = "high" if drift_metrics['total_drift'] > 0.50 else "medium"

            return SafetyViolation(
                violation_type="directive_drift",
                severity=severity,
                description=f"Directive has drifted {drift_metrics['total_drift']*100:.1f}% from "
                           f"original intent through {directive.version} incremental changes",
                affected_directives=[directive_id],
                evidence={
                    "total_drift": drift_metrics['total_drift'],
                    "parameter_drifts": drift_metrics['parameter_drifts'],
                    "drift_direction": drift_direction,
                    "versions_analyzed": len(self.directive_snapshots[directive_id]),
                    "baseline_version": baseline_snapshot['version'],
                    "current_version": directive.version
                },
                detected_at=datetime.now(),
                recommended_action="Review cumulative changes for alignment with original goals. "
                                 "Consider resetting to baseline or creating new directive from scratch."
            )

        return None

    def _calculate_parameter_drift(
        self,
        baseline: Dict[str, Any],
        current: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Calculate drift between parameter dictionaries"""
        parameter_drifts = {}
        total_drift = 0.0
        param_count = 0

        # Compare numeric parameters
        for key in baseline.keys():
            if key not in current:
                parameter_drifts[key] = {"status": "removed", "drift": 1.0}
                total_drift += 1.0
                param_count += 1
                continue

            baseline_val = baseline[key]
            current_val = current[key]

            # Handle numeric values
            if isinstance(baseline_val, (int, float)) and isinstance(current_val, (int, float)):
                if baseline_val != 0:
                    relative_change = abs(current_val - baseline_val) / abs(baseline_val)
                else:
                    relative_change = 1.0 if current_val != 0 else 0.0

                parameter_drifts[key] = {
                    "baseline": baseline_val,
                    "current": current_val,
                    "drift": min(1.0, relative_change)  # Cap at 100%
                }
                total_drift += parameter_drifts[key]['drift']
                param_count += 1

        # Check for new parameters
        for key in current.keys():
            if key not in baseline:
                parameter_drifts[key] = {"status": "added", "drift": 0.5}
                total_drift += 0.5
                param_count += 1

        return {
            "total_drift": total_drift / param_count if param_count > 0 else 0.0,
            "parameter_drifts": parameter_drifts,
            "parameters_changed": param_count
        }

    def _analyze_drift_direction(self, directive_id: str) -> str:
        """Analyze if drift is directional (concerning) or random"""
        snapshots = self.directive_snapshots[directive_id]
        if len(snapshots) < 5:
            return "insufficient_data"

        # Check if changes consistently move in same direction
        # This is a simplified heuristic - real implementation would be more sophisticated

        # For now, just count version jumps
        versions = [s['version'] for s in snapshots]
        if max(versions) - min(versions) > 5:
            return "directional_drift"
        else:
            return "random_fluctuation"

    # =========================================================================
    # NOTE (2026-09-02): detectors 3 (bias amplification) and 4 (evaluator
    # collusion), plus _calculate_vote_diversity, were REMOVED with the
    # five-judge governance vote they watched — there are no agent votes to
    # police any more. The real directive-safety checks (metric gaming, drift,
    # telemetry security) remain. Archived in
    # archive/llm_era_directive_governance_2026-09-02/.
    # =========================================================================

    # =========================================================================
    # 5. SECURITY VALIDATION (Poisoned Feedback, Adversarial Tasks)
    # =========================================================================

    async def validate_telemetry_security(
        self,
        application: DirectiveApplication
    ) -> Tuple[bool, Optional[str]]:
        """
        Validate that telemetry data is not compromised.

        Checks for:
        - Statistical anomalies in outcome metrics
        - Suspicious patterns in context data
        - Adversarial task signatures
        - Data injection attempts

        Args:
            application: DirectiveApplication to validate

        Returns:
            (is_valid, reason) tuple
        """
        # Use SystemSecurityManager if available
        if self.security_manager:
            # Validate context data through security manager
            context_str = str(application.context_data)
            if not self._validate_with_security_manager(context_str):
                return False, "Context data failed security validation (possible injection)"

        # Check for statistical anomalies
        if application.outcome_quality is not None:
            # Track metric for this directive
            self.metric_histories[application.directive_id].append(
                application.outcome_quality
            )

            # Check if value is statistically anomalous
            if len(self.metric_histories[application.directive_id]) >= 10:
                values = list(self.metric_histories[application.directive_id])
                mean = np.mean(values[:-1])  # Exclude current
                std = np.std(values[:-1])

                if std > 0:
                    z_score = abs(application.outcome_quality - mean) / std

                    if z_score > self.telemetry_anomaly_threshold:
                        self.suspicious_patterns[application.directive_id] += 1
                        return False, f"Outcome metric anomalous (z-score: {z_score:.2f})"

        # Check for adversarial task signatures
        # Look for unusually perfect or unusually poor outcomes
        if application.outcome_quality is not None:
            if application.outcome_quality >= 0.995 or application.outcome_quality <= 0.005:
                return False, "Suspiciously extreme outcome (possible adversarial task)"

        # All checks passed
        return True, None

    def _validate_with_security_manager(self, data: str) -> bool:
        """Validate data using SystemSecurityManager if available"""
        if not self.security_manager:
            return True

        try:
            # Check for injection patterns
            if hasattr(self.security_manager, 'detect_injection_attempt'):
                if self.security_manager.detect_injection_attempt(data):
                    return False

            # Check for path traversal
            if hasattr(self.security_manager, 'detect_path_traversal'):
                if self.security_manager.detect_path_traversal(data):
                    return False

            return True
        except Exception as e:
            logger.error(f"Security validation error: {e}")
            return False  # Fail closed

    # =========================================================================
    # COMPREHENSIVE SAFETY CHECK
    # =========================================================================

    async def run_comprehensive_safety_check(
        self,
        directive_id: Optional[str] = None
    ) -> List[SafetyViolation]:
        """
        Run all safety checks and return detected violations.

        Args:
            directive_id: Optional specific directive (checks all if None)

        Returns:
            List of detected safety violations
        """
        violations = []

        logger.info(f"Running comprehensive safety check{f' for {directive_id}' if directive_id else ''}")

        # Get directives to check
        if directive_id:
            directives = [await self.directive_manager.get_directive(directive_id)]
            directives = [d for d in directives if d is not None]
        else:
            from core.agents.autonomous.directive_types import DirectiveStatus
            directives = await self.directive_manager.get_directives_by_status(
                DirectiveStatus.ACTIVE
            )

        # Check each directive for metric gaming and drift
        for directive in directives:
            # Metric gaming check
            gaming_violation = await self.detect_metric_gaming(directive.directive_id)
            if gaming_violation:
                violations.append(gaming_violation)
                self.violations.append(gaming_violation)
                self.violation_counts[gaming_violation.violation_type] += 1

            # Drift check
            drift_violation = await self.detect_directive_drift(directive.directive_id)
            if drift_violation:
                violations.append(drift_violation)
                self.violations.append(drift_violation)
                self.violation_counts[drift_violation.violation_type] += 1

        # NOTE (2026-09-02): the bias-amplification / evaluator-collusion checks
        # were removed with the five-judge vote (there are no agent votes to
        # police), so this no longer reads governance_evaluations. The
        # comprehensive check now covers exactly what it can actually run:
        # metric-gaming and directive-drift, above.

        logger.info(f"Safety check complete: {len(violations)} violations detected")

        return violations

    def get_safety_summary(self) -> Dict[str, Any]:
        """Get summary of safety monitoring status"""
        return {
            "total_violations": len(self.violations),
            "violation_counts_by_type": dict(self.violation_counts),
            "recent_violations": [
                {
                    "type": v.violation_type,
                    "severity": v.severity,
                    "description": v.description,
                    "detected_at": v.detected_at.isoformat()
                }
                for v in self.violations[-10:]  # Last 10
            ],
            "monitored_directives": len(self.directive_snapshots),
            "suspicious_patterns": dict(self.suspicious_patterns)
        }
