#!/usr/bin/env python3
"""
Causal Feedback Analyzer

Analyzes feedback from deployments, actions, and experiments
to understand cause-and-effect relationships

Features:
- Causal relationship detection
- Feedback loop analysis
- Impact assessment
- Counterfactual reasoning ("what if we hadn't...")
- Action-outcome correlation
- LLM-based causal reasoning

Purpose:
Understanding WHY changes worked or failed is critical for improvement.
This analyzer goes beyond correlation to establish causal links between
actions and outcomes.

Example:
    "Deployment X caused 15% latency increase due to inefficient DB query"
    NOT just "Deployment X happened, latency increased 15%"

    Identifies:
    - Root cause (inefficient query)
    - Causal chain (deployment → query change → DB load → latency)
    - Confidence level (87% confident this is the cause)
"""

import asyncio
import logging
import re
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Tuple, Set
from collections import defaultdict
from enum import Enum

# Optional: Statistical libraries for correlation analysis
try:
    import numpy as np
    NUMPY_AVAILABLE = True
except ImportError:
    NUMPY_AVAILABLE = False

logger = logging.getLogger(__name__)


@dataclass
class CausalEvent:
    """Represents a single event that may have causal relationships"""
    event_id: str
    event_type: str  # "deployment", "config_change", "incident"
    description: str
    timestamp: datetime

    # Observables
    metrics_before: Dict[str, float] = field(default_factory=dict)
    metrics_after: Dict[str, float] = field(default_factory=dict)

    # Context
    context: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CausalLink:
    """Represents a causal relationship between action and outcome"""
    cause_event_id: str
    effect_description: str
    confidence: float  # 0.0 to 1.0

    # Evidence
    correlation_score: float = 0.0
    temporal_proximity: float = 0.0  # How close in time
    mechanism: str = ""  # Explanation of HOW it caused the effect

    # Supporting data
    evidence: List[str] = field(default_factory=list)
    counterfactual_support: float = 0.0  # Evidence from "what if" analysis

    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)

    # The names this class was originally built with, and which its consumers
    # and the database still speak.
    #
    # `store_analysis` serialises `link.cause_event / effect_event / strength`,
    # and `_counterfactual_analysis` reads the same. The dataclass was later
    # given richer names (cause_event_id / effect_description / confidence) and
    # neither consumer was updated, so every call raised AttributeError into a
    # broad handler. Aliases rather than a rewrite: the fields are the same
    # facts under two names, and renaming the consumers would leave the JSONB
    # already written under the old keys unreadable.
    @property
    def cause_event(self) -> str:
        return self.cause_event_id

    @property
    def effect_event(self) -> str:
        return self.effect_description

    @property
    def strength(self) -> float:
        return self.confidence


@dataclass
class FeedbackAnalysis:
    """Complete analysis of feedback and causal relationships"""
    analysis_id: str
    event_analyzed: CausalEvent

    # Findings
    causal_links: List[CausalLink]
    primary_cause: Optional[CausalLink]
    contributing_factors: List[CausalLink]

    # Insights
    lessons_learned: List[str]
    recommendations: List[str]

    # Confidence
    overall_confidence: float

    # Metadata
    analyzed_at: datetime = field(default_factory=datetime.now)
    analysis_method: str = "hybrid"  # "statistical", "llm", "hybrid"
    metadata: Dict[str, Any] = field(default_factory=dict)

    # `unified.causal_feedback_analyses` has columns `trigger_event`, `outcome`,
    # `timestamp` and `metadata`. `store_analysis` writes exactly those from
    # `analysis.trigger_event / .outcome / .timestamp / .metadata`, and
    # `_counterfactual_analysis` reads `trigger_event` / `outcome` back off the
    # history. The dataclass had none of them, so the writer raised on every
    # call and `causal_feedback_analyses` has been empty since it was created.
    #
    # The schema is the contract here — it predates the dataclass rename and is
    # what any already-persisted row conforms to — so these expose the same
    # facts under the names the table uses instead of migrating the table.
    @property
    def trigger_event(self) -> str:
        """What was analysed — the event that may have caused the outcome."""
        ev = self.event_analyzed
        return getattr(ev, "description", None) or getattr(ev, "event_id", "") or ""

    @property
    def outcome(self) -> str:
        """What actually followed, as established by the primary cause."""
        if self.primary_cause is not None:
            return self.primary_cause.effect_description
        if self.causal_links:
            return self.causal_links[0].effect_description
        return ""

    @property
    def timestamp(self) -> datetime:
        return self.analyzed_at


class CausalFeedbackAnalyzer:
    """
    Analyzes feedback to establish causal relationships

    Approach:
    1. Collect events and their outcomes
    2. Detect temporal relationships
    3. Analyze correlations
    4. Use LLM for causal reasoning
    5. Perform counterfactual analysis
    6. Establish confidence levels
    """

    def __init__(self):
        # Model-free: causal reasoning is the substrate's (neural bridge, CAUSAL);
        # correlation is statistical. No llm_service (retired 2026-08-28).
        self.event_history = []

        # Statistical thresholds
        self.correlation_threshold = 0.7  # Strong correlation
        self.temporal_window_seconds = 300  # 5 minutes

        # Causal patterns learned from experience
        self.known_patterns = {
            "database_query": {
                "indicators": {"query", "database", "db"},
                "effects": {"latency", "slow"},
                "confidence_boost": 0.15
            },
            "memory_leak": {
                "indicators": {"memory", "leak", "oom"},
                "effects": {"crash", "restart"},
                "confidence_boost": 0.20
            },
            "config_error": {
                "indicators": {"config", "setting"},
                "effects": {"error", "fail"},
                "confidence_boost": 0.10
            }
        }

    async def analyze_feedback(
        self,
        event: CausalEvent,
        outcomes: List[Dict[str, Any]],
        context: Dict[str, Any] = None
    ) -> FeedbackAnalysis:
        """
        Analyze feedback to understand causal relationships

        Args:
            event: The action/change that occurred
            outcomes: Observed outcomes after the event
            context: Additional context

        Returns:
            FeedbackAnalysis with causal insights
        """
        logger.info(f"Analyzing feedback for event: {event.event_id}")

        # Step 1: Temporal analysis
        temporal_links = await self._analyze_temporal_relationships(event, outcomes)

        # Step 2: Statistical correlation
        statistical_links = await self._analyze_statistical_correlations(event, outcomes)

        # Step 3: Pattern matching against known causes
        pattern_links = await self._match_known_patterns(
            event,
            outcomes,
            context
        )

        # Step 4: substrate causal reasoning (reads/traces ASSERTED causation; no model)
        substrate_causal_links = await self._substrate_causal_reasoning(event, outcomes)

        # Step 5: Synthesize all evidence
        all_links = (
            temporal_links +
            statistical_links +
            pattern_links +
            substrate_causal_links
        )

        # Step 6: Counterfactual filter — drop links whose effect has often
        # occurred WITHOUT that cause.
        #
        # This ran BEFORE synthesis and its result was concatenated in, as
        # though it produced links; its body and docstring have always
        # described a filter over `all_links`. Producing links from a
        # counterfactual is not meaningful — the counterfactual is what
        # separates the correlations already found from the causes among them,
        # which is the distinction this module exists to draw.
        all_links = await self._counterfactual_analysis(all_links)

        # Merge and deduplicate
        merged_links = await self._merge_causal_links(all_links)

        # Identify primary cause
        primary_cause = self._identify_primary_cause(merged_links)

        # Separate contributing factors
        contributing_factors = [
            link for link in merged_links
            if link != primary_cause and link.confidence > 0.5
        ]

        # Generate insights
        lessons_learned = await self._extract_lessons_learned(
            event, merged_links, outcomes
        )
        recommendations = await self._generate_recommendations(
            merged_links, lessons_learned
        )

        # Calculate overall confidence
        overall_confidence = self._calculate_overall_confidence(merged_links)

        analysis = FeedbackAnalysis(
            analysis_id=f"analysis_{event.event_id}",
            event_analyzed=event,
            causal_links=merged_links,
            primary_cause=primary_cause,
            contributing_factors=contributing_factors,
            lessons_learned=lessons_learned,
            recommendations=recommendations,
            overall_confidence=overall_confidence,
            analyzed_at=datetime.now(),
            analysis_method="hybrid"
        )

        # Store in history
        self.event_history.append(analysis)

        # Log findings
        if primary_cause:
            logger.info(
                f"Primary cause identified: {primary_cause.effect_description} "
                f"(confidence: {primary_cause.confidence:.2%})"
            )

        return analysis

    async def _analyze_temporal_relationships(
        self,
        event: CausalEvent,
        outcomes: List[Dict[str, Any]]
    ) -> List[CausalLink]:
        """Analyze temporal proximity between event and outcomes"""
        links = []

        for outcome in outcomes:
            outcome_time = outcome.get("timestamp", None)
            outcome_desc = outcome.get("description", "")

            if not outcome_time:
                continue

            # Calculate time difference
            if isinstance(outcome_time, str):
                outcome_time = datetime.fromisoformat(outcome_time)

            time_diff = abs((outcome_time - event.timestamp).total_seconds())

            # Strong temporal proximity if within window
            temporal_proximity = max(0, 1.0 - (time_diff / self.temporal_window_seconds))

            # Check if outcome type suggests causation
            outcome_type = outcome.get("type", "")
            causal_keywords = ["error", "failure", "degradation", "improvement", "success"]
            has_causal_indicator = any(kw in outcome_desc.lower() for kw in causal_keywords)

            # Calculate confidence based on temporal proximity
            confidence = temporal_proximity * 0.6  # Max 60% from temporal alone
            if has_causal_indicator:
                confidence += 0.2

            if confidence > 0.3:  # Threshold for considering
                link = CausalLink(
                    cause_event_id=event.event_id,
                    effect_description=outcome_desc,
                    confidence=confidence,
                    temporal_proximity=temporal_proximity,
                    mechanism="temporal_correlation",
                    evidence=[f"Occurred {time_diff:.0f}s after event"],
                    metadata={"time_diff_seconds": time_diff}
                )
                links.append(link)

        return links

    async def _analyze_statistical_correlations(
        self,
        event: CausalEvent,
        outcomes: List[Dict[str, Any]]
    ) -> List[CausalLink]:
        """Analyze statistical correlations between metrics"""
        links = []

        if not NUMPY_AVAILABLE or not event.metrics_after:
            return links

        # Compare metrics before/after
        for metric_name, after_value in event.metrics_after.items():
            before_value = event.metrics_before.get(metric_name, after_value)

            if before_value == after_value:
                continue

            # Calculate percentage change
            if before_value != 0:
                pct_change = ((after_value - before_value) / abs(before_value)) * 100
            else:
                pct_change = 0

            # Significant change threshold
            if abs(pct_change) > 5:  # >5% change
                # Determine if positive or negative
                direction = "increase" if pct_change > 0 else "decrease"

                link = CausalLink(
                    cause_event_id=event.event_id,
                    effect_description=f"{metric_name} {direction} of {abs(pct_change):.1f}%",
                    confidence=min(0.8, abs(pct_change) / 100),  # Higher % change = higher confidence
                    correlation_score=abs(pct_change) / 100,
                    mechanism="metric_correlation",
                    evidence=[
                        f"Before: {before_value}",
                        f"After: {after_value}",
                        f"Change: {pct_change:+.1f}%"
                    ]
                )
                links.append(link)

        return links

    async def _match_known_patterns(
        self,
        event: CausalEvent,
        outcomes: List[Dict[str, Any]],
        context: Dict[str, Any]
    ) -> List[CausalLink]:
        """Match against known causal patterns"""
        links = []

        event_text = (event.description + " " + str(context)).lower()

        for pattern_name, pattern_data in self.known_patterns.items():
            # Check if event contains pattern indicators
            indicators = pattern_data["indicators"]
            effects = pattern_data["effects"]

            has_indicator = any(ind in event_text for ind in indicators)

            if has_indicator:
                # Check if outcomes match expected effects
                for outcome in outcomes:
                    outcome_text = outcome.get("description", "").lower()
                    has_effect = any(eff in outcome_text for eff in effects)

                    if has_effect:
                        link = CausalLink(
                            cause_event_id=event.event_id,
                            effect_description=outcome.get("description", ""),
                            confidence=0.5 + pattern_data.get("confidence_boost", 0),
                            mechanism=f"known_pattern: {pattern_name}",
                            evidence=[f"Matches known pattern: {pattern_name}"]
                        )
                        links.append(link)

        return links

    async def _substrate_causal_reasoning(
        self,
        event: CausalEvent,
        outcomes: List[Dict[str, Any]]
    ) -> List[CausalLink]:
        """Establish causal links via the SUBSTRATE's causal reasoning — no model.

        Routes the event and its outcomes, as premises, through the neural bridge's
        CAUSAL kind, which reads causal relations ASSERTED in the descriptions
        ("X causes Y", "Y due to X") and traces chains through the temporal-reasoning
        engine that owns causality. It does NOT fabricate a mechanism from mere
        correlation the way the model did: correlation is reported by
        `_analyze_statistical_correlations`, and where causation is not asserted,
        nothing is claimed. Only a VERIFIED derivation becomes a link.
        """
        links: List[CausalLink] = []
        try:
            from core.reasoning.neural_bridge import get_neural_bridge, ReasoningRequest
            from core.reasoning.reasoning_interfaces import ReasoningType

            premises = [event.description] + [
                str(o.get("description", "")).strip()
                for o in outcomes if str(o.get("description", "")).strip()
            ]
            bridge = get_neural_bridge()
            await bridge.initialize()
            result = await bridge.reason(ReasoningRequest(
                query=f"What did this event cause? Event: {event.description}",
                context=premises,
                kinds=[ReasoningType.CAUSAL],
                cached_memories=[],  # reasoning is over these premises, not memory
            ))

            # Admit a causal link ONLY when the substrate VERIFIED the derivation.
            # An unverified reasoning result is not a fabricated mechanism.
            if result.metadata.get("verified") and result.answer:
                links.append(CausalLink(
                    cause_event_id=event.event_id,
                    effect_description=result.answer,
                    confidence=float(result.confidence),
                    mechanism="; ".join(result.reasoning_steps[:4]),
                    evidence=list(result.reasoning_steps),
                    metadata={
                        "substrate_causal": True,
                        "kind": result.metadata.get("kind"),
                        "conclusions": result.metadata.get("conclusions"),
                    },
                ))
                logger.info("Substrate causal reasoning established %d link(s)", len(links))
        except Exception as e:
            # Visible, not silent: a reasoning error is logged (not conflated with
            # "no causal relation asserted"); the deterministic paths still stand.
            logger.warning("Substrate causal reasoning unavailable: %s", e)

        return links


    async def _counterfactual_analysis(
        self,
        links: List[CausalLink]
    ) -> List[CausalLink]:
        """Drop links whose effect has often occurred WITHOUT that cause.

        This is the step that separates causation from correlation, and it is
        the reason the module exists: "Deployment X CAUSED the latency" rather
        than "X happened and latency rose".

        Three things were wrong and each alone made it raise:

          * it read `all_links`, which is neither a parameter nor in scope —
            NameError on every call, swallowed by the caller's
            `except Exception: logger.warning("Could not perform causal
            analysis")`, so it read as an intermittent hiccup rather than a
            function that had never once completed.
          * it used `link.cause_event` / `link.effect_event`; the fields are
            `cause_event_id` / `effect_description`.
          * it read `event.trigger_event` / `event.outcome` over
            `self.event_history`, which holds FeedbackAnalysis objects, not
            events, and neither attribute exists on either type.

        It was also WIRED as a producer — its result was concatenated into
        `all_links` — while its body and docstring describe a filter. It is now
        applied to the synthesised links, which is what it was always trying to
        do.
        """
        if not links:
            return []

        # With no prior analyses there is nothing to refute a link WITH. That is
        # absence of evidence, not evidence of spuriousness, so nothing is
        # dropped — the alternative silently discards every finding on a cold
        # start.
        if not self.event_history:
            return links

        kept: List[CausalLink] = []
        for link in links:
            # Times the SAME effect was attributed to a DIFFERENT cause.
            occurrences_without_this_cause = [
                prior_link
                for prior in self.event_history
                for prior_link in (getattr(prior, "causal_links", None) or [])
                if prior_link.effect_description == link.effect_description
                and prior_link.cause_event_id != link.cause_event_id
            ]

            spurious_rate = len(occurrences_without_this_cause) / max(len(self.event_history), 1)

            if spurious_rate < 0.3:
                kept.append(link)
            else:
                logger.debug(
                    "Filtered spurious correlation: %s -> %s (effect seen without "
                    "this cause in %.0f%% of prior analyses)",
                    link.cause_event_id, link.effect_description, spurious_rate * 100,
                )

        return kept

    async def _merge_causal_links(
        self,
        all_links: List[CausalLink]
    ) -> List[CausalLink]:
        """Merge duplicate causal links and boost confidence with multiple evidence"""
        if not all_links:
            return []

        # Group by effect description (case-insensitive)
        groups = defaultdict(list)
        for link in all_links:
            key = link.effect_description.lower().strip()
            groups[key].append(link)

        merged = []
        for effect_desc, link_group in groups.items():
            if len(link_group) == 1:
                merged.append(link_group[0])
            else:
                # Merge multiple links for same effect
                # Take highest confidence and combine evidence
                best_link = max(link_group, key=lambda l: l.confidence)

                # Boost confidence if multiple sources agree
                evidence_boost = min(0.2, (len(link_group) - 1) * 0.05)
                best_link.confidence = min(1.0, best_link.confidence + evidence_boost)

                # Combine all evidence
                all_evidence = []
                for link in link_group:
                    all_evidence.extend(link.evidence)
                best_link.evidence = list(set(all_evidence))  # Deduplicate

                merged.append(best_link)

        # Sort by confidence
        merged.sort(key=lambda l: l.confidence, reverse=True)

        return merged

    def _identify_primary_cause(
        self,
        links: List[CausalLink]
    ) -> Optional[CausalLink]:
        """Identify the primary cause from all causal links"""
        if not links:
            return None

        # Primary cause is highest confidence link
        return max(links, key=lambda l: l.confidence)

    async def _extract_lessons_learned(
        self,
        event: CausalEvent,
        causal_links: List[CausalLink],
        outcomes: List[Dict[str, Any]]
    ) -> List[str]:
        """Extract actionable lessons from causal analysis"""
        lessons = []

        # Lesson from primary cause
        if causal_links:
            primary = causal_links[0]
            if primary.confidence > 0.7:
                lessons.append(
                    f"High confidence: {event.event_type} actions "
                    f"can cause {primary.effect_description}"
                )
            elif primary.confidence > 0.5:
                lessons.append(
                    f"Likely relationship: {event.event_type} actions "
                    f"may cause {primary.effect_description}"
                )

        # Lesson from metric changes
        if event.metrics_after:
            for metric, value_after in event.metrics_after.items():
                value_before = event.metrics_before.get(metric, value_after)
                if abs(value_after - value_before) / max(abs(value_before), 1) > 0.1:
                    direction = "increased" if value_after > value_before else "decreased"
                    lessons.append(
                        f"Metric monitoring: {metric} {direction} significantly after {event.event_type}"
                    )

        # Lesson from multiple contributing factors
        contributing = [l for l in causal_links if l.confidence > 0.5]
        if len(contributing) > 2:
            lessons.append(
                f"Complex causation: Multiple factors contributed to outcomes "
                f"(consider interactions between {len(contributing)} factors)"
            )

        return lessons

    async def _generate_recommendations(
        self,
        causal_links: List[CausalLink],
        lessons_learned: List[str]
    ) -> List[str]:
        """Generate actionable recommendations"""
        recommendations = []

        # Recommendation from high-confidence negative effects
        for link in causal_links:
            if link.confidence > 0.7:
                negative_keywords = ["error", "fail", "slow", "crash", "degrade"]
                is_negative = any(kw in link.effect_description.lower() for kw in negative_keywords)

                if is_negative:
                    recommendations.append(
                        f"Avoid: Actions similar to event {link.cause_event_id} "
                        f"tend to cause {link.effect_description}"
                    )
                else:
                    recommendations.append(
                        f"Replicate: Actions similar to event {link.cause_event_id} "
                        f"successfully caused {link.effect_description}"
                    )

        # Recommendation from patterns
        if len(causal_links) > 3:
            recommendations.append(
                "Monitor: This type of event has multiple causal effects. "
                "Implement additional monitoring."
            )

        return recommendations

    def _calculate_overall_confidence(
        self,
        causal_links: List[CausalLink]
    ) -> float:
        """Calculate overall confidence in causal analysis"""
        if not causal_links:
            return 0.0

        # Weighted average of top links
        top_links = causal_links[:3]  # Top 3
        weights = [1.0, 0.6, 0.3]  # Decreasing weights

        total_weight = 0
        weighted_sum = 0

        for link, weight in zip(top_links, weights):
            weighted_sum += link.confidence * weight
            total_weight += weight

        return weighted_sum / total_weight if total_weight > 0 else 0.0

    async def get_analysis_summary(
        self,
        analysis: FeedbackAnalysis
    ) -> Dict[str, Any]:
        """Get human-readable summary of analysis"""
        summary = {
            "analysis_id": analysis.analysis_id,
            "event": analysis.event_analyzed.description,
            "timestamp": analysis.analyzed_at.isoformat(),
            "confidence": f"{analysis.overall_confidence:.0%}",
            "primary_cause": None,
            "contributing_factors": [],
            "lessons_learned": analysis.lessons_learned,
            "recommendations": analysis.recommendations
        }

        if analysis.primary_cause:
            summary["primary_cause"] = {
                "effect": analysis.primary_cause.effect_description,
                "mechanism": analysis.primary_cause.mechanism,
                "confidence": f"{analysis.primary_cause.confidence:.0%}"
            }

        for factor in analysis.contributing_factors:
            summary["contributing_factors"].append({
                "effect": factor.effect_description,
                "confidence": f"{factor.confidence:.0%}"
            })

        return summary

    async def store_analysis(
        self,
        analysis: FeedbackAnalysis,
        database_config: Dict[str, Any] = None
    ):
        """Store analysis in database for future reference"""
        try:
            from core.database import get_database_manager
            db = get_database_manager()

            await db.execute_query(
                """
                INSERT INTO causal_feedback_analyses
                   (analysis_id, trigger_event, outcome, causal_links, overall_confidence, timestamp, metadata)
                   VALUES ($1, $2, $3, $4, $5, $6, $7)
                """,
                params=(
                    analysis.analysis_id,
                    str(analysis.trigger_event),
                    str(analysis.outcome),
                    str([
                        {"cause": link.cause_event, "effect": link.effect_event, "strength": link.strength}
                        for link in analysis.causal_links
                    ]),
                    analysis.overall_confidence,
                    analysis.timestamp,
                    str(analysis.metadata),
                ),
                commit=True,
            )
            logger.info(f"Analysis stored to database: {analysis.analysis_id}")
        except Exception as e:
            logger.error(f"Failed to store analysis in database: {e}")
            self.event_history.append(analysis)

    def get_statistics(self) -> Dict[str, Any]:
        """Get analyzer statistics"""
        return {
            "total_analyses": len(self.event_history),
            "avg_confidence": sum(a.overall_confidence for a in self.event_history) / len(self.event_history)
                if self.event_history else 0,
            "high_confidence_analyses": sum(
                1 for a in self.event_history
                if a.overall_confidence > 0.7
            ),
            "patterns_known": len(self.known_patterns)
        }


# Global instance
_causal_analyzer: Optional[CausalFeedbackAnalyzer] = None


def get_causal_analyzer() -> CausalFeedbackAnalyzer:
    """Get or create global causal analyzer"""
    global _causal_analyzer
    if _causal_analyzer is None:
        _causal_analyzer = CausalFeedbackAnalyzer()
    return _causal_analyzer
