#!/usr/bin/env python3
"""
Memory Filtering Engine
========================

Deterministic O(1) filtering logic for intelligent memory storage.
Uses namespaced metadata and enum-based rules for fast decisions.
"""

import logging
import json
import random
from pathlib import Path
from typing import Dict, Any, Tuple, Optional
from dataclasses import dataclass, field
from datetime import datetime

from .memory_worthiness import (
    MemoryWorthinessMetadata,
    DecisionType,
    ConsequenceLevel,
    PatternType,
    QueryType,
    ReusabilityLevel
)

logger = logging.getLogger(__name__)


@dataclass
class FilterDecision:
    """Result of memory filtering decision"""
    should_store: bool
    rule_matched: str
    decision_type: str  # "hard_store", "hard_reject", "soft_threshold"
    confidence: float = 1.0
    rationale: str = ""


@dataclass
class FilterMetrics:
    """Metrics for filter performance"""
    total_evaluated: int = 0
    total_stored: int = 0
    total_rejected: int = 0

    # By decision type
    hard_store_count: int = 0
    hard_reject_count: int = 0
    soft_threshold_count: int = 0

    # By rule
    rejection_reasons: Dict[str, int] = field(default_factory=dict)
    storage_reasons: Dict[str, int] = field(default_factory=dict)

    # Calibration
    calibration_checks: int = 0
    calibration_mismatches: int = 0


class MemoryFilter:
    """
    Deterministic memory filtering engine.

    Features:
    - O(1) decision time
    - Namespaced metadata evaluation
    - Enum-based deterministic rules
    - Statistical calibration layer
    - Configurable thresholds
    """

    def __init__(self, config_path: Optional[str] = None):
        """Initialize filter with policy configuration"""
        self.config_path = config_path or "/Users/stefan/Dominion Labs/TorinAI/config/memory_filtering_policy.json"
        self.policy = self._load_policy()
        self.metrics = FilterMetrics()

        logger.info(f"MemoryFilter initialized with policy v{self.policy.get('policy_version', '1.0')}")

    def _load_policy(self) -> Dict[str, Any]:
        """Load filtering policy from config"""
        try:
            with open(self.config_path, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load policy from {self.config_path}: {e}")
            # Return default policy
            return {
                "hard_store_conditions": {"rules": []},
                "hard_reject_conditions": {"rules": []},
                "soft_threshold_conditions": {"thresholds": {"min_complexity_score": 0.6}},
                "calibration_settings": {"enabled": False}
            }

    #: Event classes that are RECORDS, not candidates for retention.
    #:
    #: The filter asks "is this novel / consequential / belief-changing enough
    #: to keep?" That is the wrong question for an event whose value is that it
    #: HAPPENED. A task outcome is evidence about performance; a governance
    #: decision is an audit obligation; a mapping verdict is a result other
    #: subsystems read back. None of them become less true for being routine,
    #: and judging them by novelty produces survivorship bias -- failures score
    #: high-consequence and are kept, ordinary successes are discarded, and the
    #: measured success rate can never rise.
    #:
    #: Keyed on tags because that is what the writers already emit; declared
    #: here rather than in the memory agent so retention policy has one home.
    EXEMPT_EVENT_TAGS = {
        "task_outcome": "task outcome",
        "outcome_success": "task outcome",
        "outcome_failure": "task outcome",
        "safety_validation": "safety event",
        "safety_event": "safety event",
        "governance_block": "governance decision",
        "governance_decision": "governance decision",
        "strategy_adaptation": "learning update",
        "learning_update": "learning update",
        "mapping_verdict": "mapping verdict",
        "cross_domain_mapping": "mapping verdict",
        "critical_failure": "critical failure",
    }

    def exemption_for(
        self,
        tags: Optional[list] = None,
        raw_event: Optional[dict] = None,
    ) -> Optional[str]:
        """Why this memory is exempt from worthiness, or None if it is not.

        One place decides exemption, so the memory agent does not carry a second
        copy of the policy that can drift from this one.
        """
        if isinstance(raw_event, dict) and raw_event.get("event"):
            return f"observation event '{raw_event.get('event')}'"
        for tag in (tags or []):
            klass = self.EXEMPT_EVENT_TAGS.get(str(tag))
            if klass:
                return f"{klass} (tag '{tag}')"
        return None

    def evaluate(
        self,
        metadata: MemoryWorthinessMetadata,
        reasoning_trace: Optional[list] = None
    ) -> FilterDecision:
        """
        Evaluate whether memory should be stored.

        Args:
            metadata: Namespaced memory worthiness metadata
            reasoning_trace: Optional reasoning trace for calibration

        Returns:
            FilterDecision with should_store and rationale
        """
        self.metrics.total_evaluated += 1

        # Step 1: Check hard store conditions
        decision = self._check_hard_store(metadata)
        if decision.should_store:
            self.metrics.total_stored += 1
            self.metrics.hard_store_count += 1
            self.metrics.storage_reasons[decision.rule_matched] = \
                self.metrics.storage_reasons.get(decision.rule_matched, 0) + 1

            # Calibration check
            if self.policy.get("calibration_settings", {}).get("enabled", False):
                self._calibration_check(metadata, reasoning_trace)

            return decision

        # Step 2: Check hard reject conditions
        decision = self._check_hard_reject(metadata)
        if not decision.should_store:
            self.metrics.total_rejected += 1
            self.metrics.hard_reject_count += 1
            self.metrics.rejection_reasons[decision.rule_matched] = \
                self.metrics.rejection_reasons.get(decision.rule_matched, 0) + 1
            return decision

        # Step 3: Evaluate soft thresholds
        decision = self._check_soft_threshold(metadata)
        if decision.should_store:
            self.metrics.total_stored += 1
            self.metrics.soft_threshold_count += 1
            self.metrics.storage_reasons[decision.rule_matched] = \
                self.metrics.storage_reasons.get(decision.rule_matched, 0) + 1
        else:
            self.metrics.total_rejected += 1
            self.metrics.rejection_reasons[decision.rule_matched] = \
                self.metrics.rejection_reasons.get(decision.rule_matched, 0) + 1

        return decision

    def _check_hard_store(self, m: MemoryWorthinessMetadata) -> FilterDecision:
        """Check hard store conditions - always store if matched"""

        # Strategic decisions
        if m.criticality.decision_type == DecisionType.STRATEGIC:
            return FilterDecision(
                should_store=True,
                rule_matched="strategic_decisions",
                decision_type="hard_store",
                rationale="Strategic decisions have long-term impact"
            )

        # High consequence
        if m.criticality.consequence_level in [ConsequenceLevel.HIGH, ConsequenceLevel.CRITICAL]:
            return FilterDecision(
                should_store=True,
                rule_matched="high_consequence",
                decision_type="hard_store",
                rationale="High-stakes knowledge must be preserved"
            )

        # Novel knowledge creation
        if m.novelty.is_novel and m.outcome.created_new_knowledge:
            return FilterDecision(
                should_store=True,
                rule_matched="novel_knowledge_creation",
                decision_type="hard_store",
                rationale="Novel insights are valuable learning opportunities"
            )

        # Cross-domain synthesis
        if len(m.novelty.synthesis_of_domains) > 1:
            return FilterDecision(
                should_store=True,
                rule_matched="cross_domain_synthesis",
                decision_type="hard_store",
                rationale="Cross-domain reasoning is cognitively expensive"
            )

        # RETENTION MUST NOT DEPEND ON HOW VERBOSE A CALLER WAS.
        #
        # This was `reasoning_steps >= 5`, and reasoning_steps is
        # len(reasoning_trace) -- a presentation property of the caller, not a
        # property of the cognition. Two identical episodes were graded
        # differently because one writer happened to emit eight strings and
        # another emitted a structured result and no trace. It also gave every
        # caller an incentive to pad, which is a filter measuring its own input
        # format.
        #
        # Replaced with the semantic signals the metadata already carries and
        # this filter never read.

        # Belief revision: the substrate changed its mind, or had to back up.
        if m.novelty.contradicts_existing or m.cognition.required_backtracking:
            return FilterDecision(
                should_store=True,
                rule_matched="belief_revision",
                decision_type="hard_store",
                rationale="A revised or contradicted belief is what learning is made of"
            )

        # Epistemic change: uncertainty was materially resolved.
        if m.cognition.uncertainty_resolved:
            return FilterDecision(
                should_store=True,
                rule_matched="epistemic_change",
                decision_type="hard_store",
                rationale="Resolving uncertainty changes what the substrate believes"
            )

        # Strategy adaptation: more than one approach was tried.
        if m.cognition.used_multiple_strategies:
            return FilterDecision(
                should_store=True,
                rule_matched="strategy_adaptation",
                decision_type="hard_store",
                rationale="Which approaches were tried is needed to choose again"
            )

        # Consequence for future action.
        if m.outcome.actionable or m.outcome.created_new_knowledge:
            return FilterDecision(
                should_store=True,
                rule_matched="behavioral_consequence",
                decision_type="hard_store",
                rationale="Episodes that affect future action must be recoverable"
            )

        # Connecting knowledge that was previously unrelated.
        if m.novelty.connects_disparate_knowledge or m.novelty.first_occurrence:
            return FilterDecision(
                should_store=True,
                rule_matched="novel_connection",
                decision_type="hard_store",
                rationale="First occurrences and new connections are not reproducible later"
            )

        # Emergent patterns
        if m.novelty.pattern_type == PatternType.EMERGENT:
            return FilterDecision(
                should_store=True,
                rule_matched="emergent_patterns",
                decision_type="hard_store",
                rationale="New patterns are valuable discoveries"
            )

        # Substantive analysis - content classified as analysis/synthesis with meaningful complexity
        if (
            m.query.query_type in [QueryType.ANALYSIS, QueryType.SYNTHESIS, QueryType.COMPLEX_REASONING]
            and m.cognition.complexity_score >= 0.3
        ):
            return FilterDecision(
                should_store=True,
                rule_matched="substantive_analysis",
                decision_type="hard_store",
                rationale="Analysis and synthesis with meaningful complexity should be retained"
            )

        # No hard store match
        return FilterDecision(
            should_store=False,
            rule_matched="none",
            decision_type="none",
            rationale=""
        )

    def _check_hard_reject(self, m: MemoryWorthinessMetadata) -> FilterDecision:
        """Check hard reject conditions - never store if matched"""

        # Trivial factual lookup - only reject if content is also low-complexity
        #
        # `reasoning_steps < 2` was dropped from this test. It meant a caller
        # that reported its reasoning as one structured object instead of a list
        # of strings satisfied a REJECTION clause purely on formatting -- which
        # is how the LLM chain-of-thought capture was discarded for a year. The
        # remaining clauses are about the episode itself: a known, low-complexity
        # lookup that changed no belief.
        if (
            m.query.query_type == QueryType.FACTUAL_LOOKUP
            and not m.novelty.is_novel
            and not m.cognition.uncertainty_resolved
            and not m.outcome.actionable
            and m.cognition.complexity_score < 0.3  # Skip if content analysis found substance
        ):
            return FilterDecision(
                should_store=False,
                rule_matched="trivial_factual_lookup",
                decision_type="hard_reject",
                rationale="Simple fact lookups don't need to be remembered"
            )

        # No reusability
        if (
            m.criticality.reusability == ReusabilityLevel.NONE
            and m.criticality.consequence_level in [ConsequenceLevel.NONE, ConsequenceLevel.LOW]
        ):
            return FilterDecision(
                should_store=False,
                rule_matched="no_reusability",
                decision_type="hard_reject",
                rationale="One-time calculations with low impact can be discarded"
            )

        # Simple calculation
        if (
            m.query.query_type == QueryType.SIMPLE_CALCULATION
            and m.cognition.complexity_score < 0.3
        ):
            return FilterDecision(
                should_store=False,
                rule_matched="simple_calculation",
                decision_type="hard_reject",
                rationale="Trivial math doesn't need memory"
            )

        # No hard reject match - allow to continue to soft threshold
        return FilterDecision(
            should_store=True,  # Not rejected, continue evaluation
            rule_matched="none",
            decision_type="none",
            rationale=""
        )

    def _check_soft_threshold(self, m: MemoryWorthinessMetadata) -> FilterDecision:
        """Check soft threshold conditions"""
        thresholds = self.policy.get("soft_threshold_conditions", {}).get("thresholds", {})

        # Complexity score
        min_complexity = thresholds.get("min_complexity_score", 0.6)
        if m.cognition.complexity_score >= min_complexity:
            return FilterDecision(
                should_store=True,
                rule_matched="complexity_threshold",
                decision_type="soft_threshold",
                rationale=f"Complexity score {m.cognition.complexity_score:.2f} >= {min_complexity}"
            )

        # Reuse value, in place of a reasoning-step count.
        #
        # This was `reasoning_steps >= min_steps`, the same verbosity measure as
        # the hard-store rule. What a soft threshold should ask is whether the
        # episode will be worth reading again, which the metadata states
        # directly.
        if (m.criticality.reusability in (ReusabilityLevel.HIGH, ReusabilityLevel.MEDIUM)
                and m.criticality.likely_reference_count > 0):
            return FilterDecision(
                should_store=True,
                rule_matched="recurrence_value",
                decision_type="soft_threshold",
                rationale=(f"Reusability {m.criticality.reusability.value} with "
                           f"{m.criticality.likely_reference_count} expected future reference(s)")
            )

        # Execution time
        min_time = thresholds.get("min_execution_time_ms", 100)
        if m.cognition.execution_time_ms >= min_time:
            return FilterDecision(
                should_store=True,
                rule_matched="execution_time_threshold",
                decision_type="soft_threshold",
                rationale=f"Execution time {m.cognition.execution_time_ms:.1f}ms >= {min_time}ms"
            )

        # Below all thresholds - reject
        return FilterDecision(
            should_store=False,
            rule_matched="below_soft_thresholds",
            decision_type="soft_threshold",
            rationale="Does not meet minimum complexity, reasoning, or time thresholds"
        )

    def _calibration_check(
        self,
        metadata: MemoryWorthinessMetadata,
        reasoning_trace: Optional[list]
    ):
        """Statistical calibration - verify self-reported metadata"""
        calibration_config = self.policy.get("calibration_settings", {})
        sample_rate = calibration_config.get("sample_rate", 0.05)

        # Sample 5% of memories for calibration
        if random.random() > sample_rate:
            return

        self.metrics.calibration_checks += 1

        # Check 1: is a claimed complexity corroborated by anything?
        #
        # This compared `claimed_steps` against len(reasoning_trace) -- two
        # readings of the same number, so it only ever detected a caller
        # disagreeing with itself about a count that no longer means anything.
        # Retargeted rather than deleted: a metric that is knowingly wrong
        # contaminates observability even when it controls nothing, and the
        # calibration FUNCTION (catching self-reported metadata that drifts from
        # the episode) is still worth having.
        #
        # The defensible target is whether a high self-assessed complexity is
        # backed by any semantic property of the episode. Complexity is
        # self-reported; these are not.
        corroborating = [
            metadata.novelty.is_novel,
            metadata.novelty.contradicts_existing,
            metadata.novelty.first_occurrence,
            metadata.novelty.connects_disparate_knowledge,
            bool(metadata.novelty.synthesis_of_domains),
            metadata.cognition.uncertainty_resolved,
            metadata.cognition.required_backtracking,
            metadata.cognition.used_multiple_strategies,
            metadata.outcome.actionable,
            metadata.outcome.created_new_knowledge,
        ]
        signals_present = sum(1 for c in corroborating if c)
        claimed_complexity = metadata.cognition.complexity_score

        if claimed_complexity >= 0.6 and signals_present == 0:
            self.metrics.calibration_mismatches += 1
            logger.warning(
                f"Calibration mismatch: complexity claimed at {claimed_complexity:.2f} "
                f"with no corroborating semantic signal (source: {metadata.source_system})"
            )

        # Additional calibration checks can be added here
        # (e.g., novelty via embedding similarity, synthesis via domain tag analysis)
        #
        # `reasoning_trace` is still accepted as a parameter so callers do not
        # change, but it is no longer read: it is a legacy descriptive field and
        # nothing calibrates against its length.

    def get_metrics(self) -> Dict[str, Any]:
        """Get filter performance metrics"""
        total = max(self.metrics.total_evaluated, 1)

        return {
            "total_evaluated": self.metrics.total_evaluated,
            "total_stored": self.metrics.total_stored,
            "total_rejected": self.metrics.total_rejected,
            "storage_rate": self.metrics.total_stored / total,
            "rejection_rate": self.metrics.total_rejected / total,

            "decision_breakdown": {
                "hard_store": self.metrics.hard_store_count,
                "hard_reject": self.metrics.hard_reject_count,
                "soft_threshold": self.metrics.soft_threshold_count
            },

            "top_rejection_reasons": sorted(
                self.metrics.rejection_reasons.items(),
                key=lambda x: x[1],
                reverse=True
            )[:5],

            "top_storage_reasons": sorted(
                self.metrics.storage_reasons.items(),
                key=lambda x: x[1],
                reverse=True
            )[:5],

            "calibration": {
                "checks_performed": self.metrics.calibration_checks,
                "mismatches_detected": self.metrics.calibration_mismatches,
                "mismatch_rate": self.metrics.calibration_mismatches / max(self.metrics.calibration_checks, 1)
            }
        }


# Global instance
_memory_filter: Optional[MemoryFilter] = None


def get_memory_filter() -> MemoryFilter:
    """Get global memory filter instance"""
    global _memory_filter
    if _memory_filter is None:
        _memory_filter = MemoryFilter()
    return _memory_filter


__all__ = ["MemoryFilter", "FilterDecision", "get_memory_filter"]
