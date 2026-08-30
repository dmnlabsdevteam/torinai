"""
Shadow Mode Coordinator

Manages shadow mode deployment where governance triggers fire and log events
but never block actions. Collects comprehensive metrics for threshold tuning
and rigorous error analysis.

Shadow mode is critical for:
1. Validating trigger accuracy before enforcement
2. Collecting baseline metrics
3. Detecting all error types: FP, FN, tier errors, trigger attribution errors
4. Tuning thresholds based on comprehensive ground truth
5. Identifying high-risk action categories

Error Types Tracked:
- False Positives (FP): Triggered but should not have
- False Negatives (FN): NOT triggered but should have (MOST DANGEROUS)
- Tier Errors: Triggered at wrong tier (over/under escalation)
- Trigger Attribution Errors: Wrong trigger matched the action
"""

import json
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, asdict
from collections import defaultdict
from pathlib import Path

from core.governance.unified_governance_trigger_system import (
    ActionCategory,
    EnforcementMode,
    DecisionTier,
    GovernanceTriggerEvaluation,
    IrreversibilityClass
)

logger = logging.getLogger(__name__)


@dataclass
class GroundTruthLabel:
    """
    Ground truth labeling for an action (for rigorous error analysis).

    This is the "truth object" that allows computing:
    - False Positive Rate (FPR): triggered but expected_triggered=False
    - False Negative Rate (FNR): not triggered but expected_triggered=True (MOST DANGEROUS)
    - Tier Error Rate: triggered with wrong tier (over/under escalation)
    - Trigger Attribution Error: wrong trigger_id matched
    """
    action_id: str
    expected_triggered: bool  # Should this action trigger governance?
    expected_trigger_ids: Optional[List[str]]  # Which triggers should match (if any)
    expected_tier: Optional[DecisionTier]  # Expected decision tier if triggered
    reviewer_id: str  # Who labeled this (human identifier)
    review_timestamp: datetime
    rationale: str  # Short explanation of the labeling decision


@dataclass
class ShadowModeEvent:
    """A single shadow mode trigger event"""
    event_id: str
    timestamp: datetime
    action_id: str
    action_category: ActionCategory
    action_type: str
    triggered: bool
    trigger_id: Optional[str]
    trigger_name: Optional[str]
    decision_tier: DecisionTier
    enforcement_mode: EnforcementMode
    escalation_category: Optional[str]
    irreversibility_class: IrreversibilityClass
    impact_level: str
    safety_risk: str
    would_block_if_enforced: bool  # True if MUST_BLOCK in production
    processing_latency_ms: float


@dataclass
class ShadowModePeriod:
    """Time period for shadow mode deployment"""
    start_time: datetime
    end_time: Optional[datetime]
    duration_hours: Optional[float]


@dataclass
class ErrorAnalysis:
    """
    Comprehensive error analysis from shadow mode.

    Tracks all four error types for rigorous validation:
    1. False Positives (FP): Triggered but shouldn't have
    2. False Negatives (FN): NOT triggered but should have (MOST DANGEROUS)
    3. Tier Errors: Wrong decision tier assigned
    4. Trigger Attribution Errors: Wrong trigger matched
    """
    total_labeled_actions: int  # Total actions with ground truth labels

    # False Positives (triggered but expected_triggered=False)
    false_positives: int
    false_positive_rate: float

    # False Negatives (NOT triggered but expected_triggered=True) - MOST DANGEROUS
    false_negatives: int
    false_negative_rate: float

    # Tier Errors (triggered at wrong tier)
    tier_errors: int  # Count of tier mismatches
    tier_error_rate: float  # tier_errors / triggered_actions
    over_escalation_count: int  # Escalated too high (e.g., ROUTINE -> IMPORTANT)
    under_escalation_count: int  # Escalated too low (e.g., CRITICAL -> IMPORTANT)

    # Trigger Attribution Errors (wrong trigger matched)
    attribution_errors: int  # Wrong trigger_id matched
    attribution_error_rate: float  # attribution_errors / triggered_actions

    # Overall accuracy
    true_positives: int  # Triggered and should have
    true_negatives: int  # Not triggered and shouldn't have
    accuracy: float  # (TP + TN) / total_labeled_actions
    precision: float  # TP / (TP + FP)
    recall: float  # TP / (TP + FN)
    f1_score: float  # 2 * (precision * recall) / (precision + recall)


@dataclass
class TriggerRateMetrics:
    """Trigger rate statistics for an action category"""
    total_actions: int
    triggered_actions: int
    trigger_rate: float

    # Error analysis (if ground truth available)
    error_analysis: Optional[ErrorAnalysis] = None


@dataclass
class ShadowModeMetrics:
    """Comprehensive metrics from shadow mode deployment"""
    period: ShadowModePeriod
    trigger_rates: Dict[str, TriggerRateMetrics]  # category -> metrics
    decision_tier_distribution: Dict[str, int]  # tier -> count
    escalation_category_distribution: Dict[str, int]  # category -> count
    enforcement_mode_distribution: Dict[str, int]  # mode -> count
    total_events: int
    total_would_block: int  # Actions that would block if enforced
    context_classifications: Dict[str, int]  # label -> count
    commitment_violations: Dict[str, Any]
    safety_checkpoint_frequency: Dict[str, int]
    average_processing_latency_ms: float


class ShadowModeCoordinator:
    """
    Coordinates shadow mode deployment across all governance components.

    Shadow mode allows governance system to run in observation-only mode:
    - All triggers fire and log events
    - No actions are blocked
    - Comprehensive metrics collected
    - False positives identified
    - Thresholds can be tuned based on data

    Usage:
        coordinator = ShadowModeCoordinator()
        await coordinator.start_shadow_mode()

        # Execute actions...
        await coordinator.record_trigger_event(evaluation)

        # Analyze results
        metrics = await coordinator.calculate_metrics()
        await coordinator.export_metrics("shadow_mode_metrics.json")
    """

    def __init__(self, storage_path: Optional[Path] = None):
        """
        Initialize shadow mode coordinator.

        Args:
            storage_path: Where to store shadow mode events (defaults to logs/shadow_mode/)
        """
        if storage_path is None:
            storage_path = Path(__file__).parent.parent.parent / "logs" / "shadow_mode"

        self.storage_path = storage_path
        self.storage_path.mkdir(parents=True, exist_ok=True)

        self.events: List[ShadowModeEvent] = []
        self.period: Optional[ShadowModePeriod] = None
        self.ground_truth_labels: Dict[str, GroundTruthLabel] = {}  # action_id -> label

        # Metrics caches
        self._metrics_cache: Optional[ShadowModeMetrics] = None
        self._cache_invalidated = True

        logger.info(f"ShadowModeCoordinator initialized, storage: {self.storage_path}")

    async def start_shadow_mode(self) -> None:
        """Begin shadow mode observation period"""
        self.period = ShadowModePeriod(
            start_time=datetime.now(),
            end_time=None,
            duration_hours=None
        )
        self.events = []
        self._cache_invalidated = True

        logger.info(f"Shadow mode started at {self.period.start_time}")

    async def stop_shadow_mode(self) -> None:
        """End shadow mode observation period"""
        if self.period is None:
            raise ValueError("Shadow mode not started")

        self.period.end_time = datetime.now()
        duration = self.period.end_time - self.period.start_time
        self.period.duration_hours = duration.total_seconds() / 3600

        logger.info(
            f"Shadow mode stopped at {self.period.end_time} "
            f"(duration: {self.period.duration_hours:.2f} hours, "
            f"events: {len(self.events)})"
        )

    async def record_trigger_event(
        self,
        evaluation: GovernanceTriggerEvaluation,
        processing_latency_ms: float = 0.0
    ) -> str:
        """
        Record a trigger evaluation event in shadow mode.

        Args:
            evaluation: Result from governance trigger system
            processing_latency_ms: How long evaluation took

        Returns:
            Event ID for this event
        """
        event_id = f"shadow_{datetime.now().timestamp()}_{len(self.events)}"

        # Determine if this would block if enforced
        would_block = (
            evaluation.triggered and
            evaluation.enforcement_mode == EnforcementMode.MUST_BLOCK
        )

        event = ShadowModeEvent(
            event_id=event_id,
            timestamp=datetime.now(),
            action_id=evaluation.action_id,
            action_category=evaluation.action_category,
            action_type=evaluation.action_type,
            triggered=evaluation.triggered,
            trigger_id=evaluation.trigger_id,
            trigger_name=evaluation.trigger_name,
            decision_tier=evaluation.decision_tier,
            enforcement_mode=evaluation.enforcement_mode,
            escalation_category=evaluation.escalation_category,
            irreversibility_class=evaluation.irreversibility_class,
            impact_level=evaluation.impact_level,
            safety_risk=evaluation.safety_risk,
            would_block_if_enforced=would_block,
            processing_latency_ms=processing_latency_ms
        )

        self.events.append(event)
        self._cache_invalidated = True

        logger.debug(
            f"Shadow event recorded: {evaluation.action_type} "
            f"(triggered: {evaluation.triggered}, would_block: {would_block})"
        )

        return event_id

    async def label_action(
        self,
        action_id: str,
        expected_triggered: bool,
        reviewer_id: str,
        rationale: str,
        expected_trigger_ids: Optional[List[str]] = None,
        expected_tier: Optional[DecisionTier] = None
    ) -> None:
        """
        Label an action with ground truth (rigorous labeling protocol).

        This enables comprehensive error analysis:
        - False Positives: triggered but expected_triggered=False
        - False Negatives: NOT triggered but expected_triggered=True
        - Tier Errors: wrong expected_tier
        - Attribution Errors: wrong trigger_id

        Args:
            action_id: Action to label
            expected_triggered: Should this action trigger governance?
            reviewer_id: Human reviewer identifier
            rationale: Why this labeling decision was made
            expected_trigger_ids: Which triggers should match (if any)
            expected_tier: Expected decision tier if triggered
        """
        label = GroundTruthLabel(
            action_id=action_id,
            expected_triggered=expected_triggered,
            expected_trigger_ids=expected_trigger_ids,
            expected_tier=expected_tier,
            reviewer_id=reviewer_id,
            review_timestamp=datetime.now(),
            rationale=rationale
        )

        self.ground_truth_labels[action_id] = label
        self._cache_invalidated = True

        logger.debug(
            f"Ground truth labeled: {action_id} -> "
            f"triggered={expected_triggered}, tier={expected_tier}, "
            f"reviewer={reviewer_id}"
        )

    async def calculate_error_analysis(self) -> ErrorAnalysis:
        """
        Calculate comprehensive error analysis across ALL four error types.

        Requires ground truth labels to be set via label_action().

        Returns:
            ErrorAnalysis with FP, FN, tier errors, and attribution errors
        """
        # Counters for all error types
        true_positives = 0
        true_negatives = 0
        false_positives = 0
        false_negatives = 0
        tier_errors = 0
        over_escalation = 0
        under_escalation = 0
        attribution_errors = 0

        # Map decision tiers to ordinal values for over/under escalation
        tier_order = {
            DecisionTier.ROUTINE: 1,
            DecisionTier.IMPORTANT: 2,
            DecisionTier.CRITICAL: 3
        }

        # Analyze each labeled action
        for action_id, label in self.ground_truth_labels.items():
            # Find corresponding event
            event = next((e for e in self.events if e.action_id == action_id), None)
            if event is None:
                logger.warning(f"No event found for labeled action: {action_id}")
                continue

            # False Positive / False Negative / True Positive / True Negative
            if event.triggered and label.expected_triggered:
                true_positives += 1
            elif event.triggered and not label.expected_triggered:
                false_positives += 1
            elif not event.triggered and label.expected_triggered:
                false_negatives += 1  # MOST DANGEROUS
            elif not event.triggered and not label.expected_triggered:
                true_negatives += 1

            # Tier Errors (only for triggered actions)
            if event.triggered and label.expected_triggered and label.expected_tier:
                if event.decision_tier != label.expected_tier:
                    tier_errors += 1

                    # Over/under escalation
                    actual_order = tier_order.get(event.decision_tier, 0)
                    expected_order = tier_order.get(label.expected_tier, 0)

                    if actual_order > expected_order:
                        over_escalation += 1
                    elif actual_order < expected_order:
                        under_escalation += 1

            # Trigger Attribution Errors (only for triggered actions)
            if event.triggered and label.expected_trigger_ids:
                if event.trigger_id not in label.expected_trigger_ids:
                    attribution_errors += 1

        # Calculate rates and metrics
        total_labeled = len(self.ground_truth_labels)
        triggered_labeled = true_positives + false_positives

        fp_rate = false_positives / total_labeled if total_labeled > 0 else 0.0
        fn_rate = false_negatives / total_labeled if total_labeled > 0 else 0.0
        tier_error_rate = tier_errors / triggered_labeled if triggered_labeled > 0 else 0.0
        attribution_error_rate = attribution_errors / triggered_labeled if triggered_labeled > 0 else 0.0

        accuracy = (true_positives + true_negatives) / total_labeled if total_labeled > 0 else 0.0
        precision = true_positives / (true_positives + false_positives) if (true_positives + false_positives) > 0 else 0.0
        recall = true_positives / (true_positives + false_negatives) if (true_positives + false_negatives) > 0 else 0.0
        f1_score = 2 * (precision * recall) / (precision + recall) if (precision + recall) > 0 else 0.0

        return ErrorAnalysis(
            total_labeled_actions=total_labeled,
            false_positives=false_positives,
            false_positive_rate=fp_rate,
            false_negatives=false_negatives,
            false_negative_rate=fn_rate,
            tier_errors=tier_errors,
            tier_error_rate=tier_error_rate,
            over_escalation_count=over_escalation,
            under_escalation_count=under_escalation,
            attribution_errors=attribution_errors,
            attribution_error_rate=attribution_error_rate,
            true_positives=true_positives,
            true_negatives=true_negatives,
            accuracy=accuracy,
            precision=precision,
            recall=recall,
            f1_score=f1_score
        )

    async def calculate_trigger_rates(self) -> Dict[ActionCategory, TriggerRateMetrics]:
        """
        Calculate trigger rates by action category with comprehensive error analysis.

        Returns:
            Map of category -> trigger rate metrics (includes error analysis if ground truth available)
        """
        category_stats = defaultdict(lambda: {"total": 0, "triggered": 0})

        for event in self.events:
            category = event.action_category
            category_stats[category]["total"] += 1

            if event.triggered:
                category_stats[category]["triggered"] += 1

        # Convert to TriggerRateMetrics
        metrics = {}
        for category, stats in category_stats.items():
            total = stats["total"]
            triggered = stats["triggered"]

            # Calculate error analysis if ground truth available
            error_analysis = None
            if len(self.ground_truth_labels) > 0:
                # Filter labels for this category
                category_events = [e for e in self.events if e.action_category == category]
                category_action_ids = {e.action_id for e in category_events}
                category_labels = {
                    aid: label for aid, label in self.ground_truth_labels.items()
                    if aid in category_action_ids
                }

                if len(category_labels) > 0:
                    # Temporarily swap labels to calculate per-category analysis
                    original_labels = self.ground_truth_labels
                    self.ground_truth_labels = category_labels
                    error_analysis = await self.calculate_error_analysis()
                    self.ground_truth_labels = original_labels

            metrics[category] = TriggerRateMetrics(
                total_actions=total,
                triggered_actions=triggered,
                trigger_rate=triggered / total if total > 0 else 0.0,
                error_analysis=error_analysis
            )

        return metrics

    async def calculate_decision_tier_distribution(self) -> Dict[DecisionTier, int]:
        """Calculate distribution of decision tiers"""
        distribution = defaultdict(int)

        for event in self.events:
            if event.triggered:  # Only count triggered events
                distribution[event.decision_tier] += 1

        return dict(distribution)

    async def calculate_escalation_distribution(self) -> Dict[str, int]:
        """Calculate distribution of escalation categories"""
        distribution = defaultdict(int)

        for event in self.events:
            if event.triggered and event.escalation_category:
                distribution[event.escalation_category] += 1

        return dict(distribution)

    async def identify_false_positives(self) -> List[ShadowModeEvent]:
        """
        Identify false positive triggers based on ground truth.

        False Positive = triggered but expected_triggered=False

        Returns:
            List of events that triggered but shouldn't have
        """
        false_positives = []

        for event in self.events:
            if event.action_id in self.ground_truth_labels:
                label = self.ground_truth_labels[event.action_id]
                if event.triggered and not label.expected_triggered:
                    false_positives.append(event)

        logger.info(
            f"Identified {len(false_positives)} false positives "
            f"out of {len(self.ground_truth_labels)} labeled actions"
        )

        return false_positives

    async def identify_false_negatives(self) -> List[str]:
        """
        Identify false negative misses based on ground truth.

        False Negative = NOT triggered but expected_triggered=True
        These are MOST DANGEROUS as they represent missed safety triggers.

        Returns:
            List of action_ids that should have triggered but didn't
        """
        false_negatives = []

        for event in self.events:
            if event.action_id in self.ground_truth_labels:
                label = self.ground_truth_labels[event.action_id]
                if not event.triggered and label.expected_triggered:
                    false_negatives.append(event.action_id)

        logger.warning(
            f"CRITICAL: Identified {len(false_negatives)} false negatives "
            f"out of {len(self.ground_truth_labels)} labeled actions. "
            f"These represent MISSED safety triggers!"
        )

        return false_negatives

    async def identify_tier_errors(self) -> List[Tuple[str, DecisionTier, DecisionTier]]:
        """
        Identify tier errors (over/under escalation).

        Returns:
            List of (action_id, actual_tier, expected_tier) tuples
        """
        tier_errors = []

        for event in self.events:
            if event.action_id in self.ground_truth_labels:
                label = self.ground_truth_labels[event.action_id]
                if event.triggered and label.expected_tier:
                    if event.decision_tier != label.expected_tier:
                        tier_errors.append((
                            event.action_id,
                            event.decision_tier,
                            label.expected_tier
                        ))

        logger.info(
            f"Identified {len(tier_errors)} tier errors "
            f"(over/under escalation)"
        )

        return tier_errors

    async def identify_attribution_errors(self) -> List[Tuple[str, str, List[str]]]:
        """
        Identify trigger attribution errors (wrong trigger matched).

        Returns:
            List of (action_id, actual_trigger_id, expected_trigger_ids) tuples
        """
        attribution_errors = []

        for event in self.events:
            if event.action_id in self.ground_truth_labels:
                label = self.ground_truth_labels[event.action_id]
                if event.triggered and label.expected_trigger_ids:
                    if event.trigger_id not in label.expected_trigger_ids:
                        attribution_errors.append((
                            event.action_id,
                            event.trigger_id,
                            label.expected_trigger_ids
                        ))

        logger.info(
            f"Identified {len(attribution_errors)} attribution errors "
            f"(wrong trigger matched)"
        )

        return attribution_errors

    async def calculate_metrics(self) -> ShadowModeMetrics:
        """
        Calculate comprehensive shadow mode metrics.

        Returns:
            Complete metrics summary
        """
        if not self._cache_invalidated and self._metrics_cache is not None:
            return self._metrics_cache

        # Trigger rates by category
        trigger_rates = await self.calculate_trigger_rates()
        trigger_rates_dict = {
            cat.value: asdict(metrics)
            for cat, metrics in trigger_rates.items()
        }

        # Decision tier distribution
        tier_dist = await self.calculate_decision_tier_distribution()
        tier_dist_dict = {tier.value: count for tier, count in tier_dist.items()}

        # Escalation category distribution
        escalation_dist = await self.calculate_escalation_distribution()

        # Enforcement mode distribution
        enforcement_dist = defaultdict(int)
        for event in self.events:
            if event.triggered:
                enforcement_dist[event.enforcement_mode.value] += 1

        # Total would-block count
        would_block_count = sum(1 for e in self.events if e.would_block_if_enforced)

        # Average processing latency
        latencies = [e.processing_latency_ms for e in self.events]
        avg_latency = sum(latencies) / len(latencies) if latencies else 0.0

        metrics = ShadowModeMetrics(
            period=self.period or ShadowModePeriod(
                start_time=datetime.now(),
                end_time=None,
                duration_hours=None
            ),
            trigger_rates=trigger_rates_dict,
            decision_tier_distribution=tier_dist_dict,
            escalation_category_distribution=escalation_dist,
            enforcement_mode_distribution=dict(enforcement_dist),
            total_events=len(self.events),
            total_would_block=would_block_count,
            context_classifications={},  # Populated by integration with ContextClassifier
            commitment_violations={},  # Populated by integration with CommitmentContract
            safety_checkpoint_frequency={},  # Populated by integration with SafetyCheckpoints
            average_processing_latency_ms=avg_latency
        )

        self._metrics_cache = metrics
        self._cache_invalidated = False

        return metrics

    async def export_metrics(
        self,
        filename: Optional[str] = None,
        format: str = "json"
    ) -> str:
        """
        Export shadow mode metrics to file.

        Args:
            filename: Output filename (defaults to shadow_mode_metrics_{timestamp}.json)
            format: Export format (only "json" supported currently)

        Returns:
            Path to exported file
        """
        if format != "json":
            raise ValueError(f"Unsupported format: {format}")

        metrics = await self.calculate_metrics()

        if filename is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"shadow_mode_metrics_{timestamp}.json"

        output_path = self.storage_path / filename

        # Convert dataclasses to dicts for JSON serialization
        metrics_dict = self._serialize_metrics(metrics)

        with open(output_path, 'w') as f:
            json.dump(metrics_dict, f, indent=2, default=str)

        logger.info(f"Shadow mode metrics exported to {output_path}")
        return str(output_path)

    def _serialize_metrics(self, metrics: ShadowModeMetrics) -> Dict[str, Any]:
        """Convert ShadowModeMetrics to JSON-serializable dict"""
        return {
            "shadow_mode_period": {
                "start": metrics.period.start_time.isoformat(),
                "end": metrics.period.end_time.isoformat() if metrics.period.end_time else None,
                "duration_hours": metrics.period.duration_hours
            },
            "trigger_rates": metrics.trigger_rates,
            "decision_tier_distribution": metrics.decision_tier_distribution,
            "escalation_category_distribution": metrics.escalation_category_distribution,
            "enforcement_mode_distribution": metrics.enforcement_mode_distribution,
            "summary": {
                "total_events": metrics.total_events,
                "total_would_block_if_enforced": metrics.total_would_block,
                "average_processing_latency_ms": metrics.average_processing_latency_ms
            },
            "context_classifications": metrics.context_classifications,
            "commitment_violations": metrics.commitment_violations,
            "safety_checkpoint_frequency": metrics.safety_checkpoint_frequency
        }

    async def get_events_by_category(
        self,
        category: ActionCategory
    ) -> List[ShadowModeEvent]:
        """Get all events for a specific action category"""
        return [e for e in self.events if e.action_category == category]

    async def get_events_by_trigger(
        self,
        trigger_id: str
    ) -> List[ShadowModeEvent]:
        """Get all events for a specific trigger"""
        return [e for e in self.events if e.trigger_id == trigger_id]

    async def get_high_false_positive_triggers(
        self,
        threshold: float = 0.3
    ) -> List[Tuple[str, float]]:
        """
        Identify triggers with high false positive rates.

        Args:
            threshold: Minimum false positive rate to flag (default 30%)

        Returns:
            List of (trigger_id, false_positive_rate) tuples sorted by FP rate (highest first)
        """
        trigger_stats = defaultdict(lambda: {"triggered": 0, "false_positives": 0})

        for event in self.events:
            if event.triggered and event.trigger_id:
                trigger_stats[event.trigger_id]["triggered"] += 1

                # Check if false positive
                if event.action_id in self.ground_truth_labels:
                    label = self.ground_truth_labels[event.action_id]
                    if not label.expected_triggered:
                        trigger_stats[event.trigger_id]["false_positives"] += 1

        high_fp_triggers = []
        for trigger_id, stats in trigger_stats.items():
            triggered = stats["triggered"]
            false_pos = stats["false_positives"]

            if triggered > 0:
                fp_rate = false_pos / triggered
                if fp_rate >= threshold:
                    high_fp_triggers.append((trigger_id, fp_rate))

        high_fp_triggers.sort(key=lambda x: x[1], reverse=True)

        logger.info(
            f"Found {len(high_fp_triggers)} triggers with FP rate >= {threshold}"
        )

        return high_fp_triggers

    async def get_high_false_negative_triggers(
        self,
        threshold: float = 0.2
    ) -> List[Tuple[str, int]]:
        """
        Identify action patterns with high false negative rates (MOST DANGEROUS).

        False negatives = actions that should have triggered but didn't.

        Args:
            threshold: Minimum FN rate to flag (default 20%)

        Returns:
            List of (action_type, false_negative_count) tuples sorted by FN count (highest first)
        """
        action_type_stats = defaultdict(lambda: {"total_expected": 0, "false_negatives": 0})

        # Analyze labeled actions
        for action_id, label in self.ground_truth_labels.items():
            if label.expected_triggered:
                # Find corresponding event
                event = next((e for e in self.events if e.action_id == action_id), None)
                if event:
                    action_type_stats[event.action_type]["total_expected"] += 1

                    if not event.triggered:
                        action_type_stats[event.action_type]["false_negatives"] += 1

        high_fn_patterns = []
        for action_type, stats in action_type_stats.items():
            total_expected = stats["total_expected"]
            false_negs = stats["false_negatives"]

            if total_expected > 0:
                fn_rate = false_negs / total_expected
                if fn_rate >= threshold:
                    high_fn_patterns.append((action_type, false_negs))

        high_fn_patterns.sort(key=lambda x: x[1], reverse=True)

        if len(high_fn_patterns) > 0:
            logger.warning(
                f"CRITICAL: Found {len(high_fn_patterns)} action patterns with FN rate >= {threshold}. "
                f"These represent MISSED safety triggers!"
            )

        return high_fn_patterns
