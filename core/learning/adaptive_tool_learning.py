"""
Adaptive Tool Learning System

Implements experience-based tool selection through:
1. Intent Classification: Identifies task goal types
2. Tool Affinity Scoring: Learns which tools work for which intents
3. Historical Success Weighting: Adjusts scores based on past outcomes

This replaces static keyword matching with adaptive learning.
"""

import logging
import re
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

logger = logging.getLogger(__name__)


def _default_db_manager():
    """Unified database manager, or None if unavailable (degrades to neutral)."""
    try:
        from core.database import get_database_manager
        return get_database_manager()
    except Exception as e:  # pragma: no cover - import-time safety
        logger.warning(f"Adaptive tool learning has no database: {e}")
        return None


class IntentType(Enum):
    """Task intent categories"""
    EXPLORATION = "exploration"      # Discovering new capabilities/domains
    OPTIMIZATION = "optimization"     # Improving performance/efficiency
    DEBUGGING = "debugging"          # Diagnosing and fixing issues
    IMPLEMENTATION = "implementation" # Building new features
    MAINTENANCE = "maintenance"      # Routine upkeep and monitoring
    RESEARCH = "research"            # Investigating questions/hypotheses
    ANALYSIS = "analysis"            # Understanding system state


@dataclass
class IntentSignals:
    """Weighted keywords for intent classification"""
    intent_type: IntentType
    keywords: List[Tuple[str, float]]  # (keyword, weight)


class IntentClassifier:
    """
    Classifies task descriptions into intent types using weighted keyword matching.

    Intent types guide which tool categories are most likely to be useful.
    For example:
    - EXPLORATION tasks → research, monitoring tools
    - DEBUGGING tasks → analysis, monitoring, logging tools
    - IMPLEMENTATION tasks → code_generation, testing tools
    """

    # Intent classification signals (high weight = strong indicator)
    INTENT_SIGNALS = [
        IntentSignals(
            intent_type=IntentType.EXPLORATION,
            keywords=[
                ('explore', 3.0), ('discover', 3.0), ('identify', 2.5), ('find', 1.5),
                ('new', 2.0), ('novel', 3.0), ('unknown', 2.5), ('frontier', 3.0),
                ('domain', 2.5), ('expansion', 3.0), ('capability', 2.5), ('gap', 2.5),
                ('breakthrough', 3.0), ('innovative', 2.5)
            ]
        ),
        IntentSignals(
            intent_type=IntentType.OPTIMIZATION,
            keywords=[
                ('optimize', 3.0), ('improve', 2.5), ('performance', 2.5), ('efficiency', 3.0),
                ('faster', 2.5), ('reduce', 2.0), ('minimize', 2.5), ('enhance', 2.0),
                ('throughput', 3.0), ('latency', 3.0), ('bottleneck', 3.0)
            ]
        ),
        IntentSignals(
            intent_type=IntentType.DEBUGGING,
            keywords=[
                ('debug', 3.0), ('fix', 2.5), ('error', 2.5), ('bug', 3.0),
                ('issue', 2.0), ('problem', 2.0), ('failed', 2.5), ('broken', 2.5),
                ('diagnose', 3.0), ('troubleshoot', 3.0), ('investigate', 2.0)
            ]
        ),
        IntentSignals(
            intent_type=IntentType.IMPLEMENTATION,
            keywords=[
                ('implement', 3.0), ('build', 2.5), ('create', 2.0), ('develop', 2.5),
                ('add', 2.0), ('feature', 2.5), ('functionality', 2.5), ('construct', 2.5),
                ('refactor', 2.5), ('write', 1.5)
            ]
        ),
        IntentSignals(
            intent_type=IntentType.MAINTENANCE,
            keywords=[
                ('maintain', 3.0), ('monitor', 2.5), ('check', 2.0), ('status', 2.0),
                ('health', 2.5), ('routine', 2.5), ('periodic', 2.5), ('cleanup', 2.5),
                ('update', 1.5), ('verify', 2.0)
            ]
        ),
        IntentSignals(
            intent_type=IntentType.RESEARCH,
            keywords=[
                ('research', 3.0), ('study', 2.5), ('literature', 3.0), ('paper', 2.5),
                ('survey', 2.5), ('review', 2.0), ('state-of-art', 3.0), ('sota', 3.0),
                ('publication', 2.5), ('benchmark', 2.5)
            ]
        ),
        IntentSignals(
            intent_type=IntentType.ANALYSIS,
            keywords=[
                ('analyze', 2.5), ('understand', 2.0), ('examine', 2.5), ('assess', 2.5),
                ('evaluate', 2.5), ('measure', 2.5), ('profile', 3.0), ('inspect', 2.5),
                ('report', 2.0), ('metrics', 2.5)
            ]
        )
    ]

    def classify(self, task_description: str) -> Tuple[IntentType, float]:
        """
        Classify task description into intent type.

        Returns:
            (intent_type, confidence): Best matching intent and confidence score
        """
        task_lower = task_description.lower()

        # Score each intent type
        intent_scores = {}
        for signals in self.INTENT_SIGNALS:
            score = 0.0
            for keyword, weight in signals.keywords:
                # Use word boundary matching to avoid partial matches
                if re.search(r'\b' + re.escape(keyword) + r'\b', task_lower):
                    score += weight
            intent_scores[signals.intent_type] = score

        # Get highest scoring intent
        if not intent_scores:
            return IntentType.ANALYSIS, 0.3  # Default fallback with low confidence

        best_intent = max(intent_scores.items(), key=lambda x: x[1])
        intent_type, raw_score = best_intent

        # Normalize confidence to 0.0-1.0 range
        # Score of 6.0+ = high confidence (0.9)
        # Score of 3.0 = medium confidence (0.6)
        # Score of 0.0 = low confidence (0.3)
        if raw_score >= 6.0:
            confidence = min(0.95, 0.5 + (raw_score * 0.075))
        elif raw_score >= 3.0:
            confidence = 0.5 + (raw_score * 0.05)
        else:
            confidence = 0.3 + (raw_score * 0.1)

        confidence = min(0.95, confidence)  # Cap at 0.95

        logger.debug(f"Intent classification: {intent_type.value} (confidence={confidence:.2f}, score={raw_score:.1f})")

        return intent_type, confidence


class ToolAffinityScorer:
    """
    Learns which tool categories work best for which intent types
    by analyzing historical success rates.

    Provides dynamic multipliers for tool category scores based on
    past performance: high success rate → boost score, low success rate → penalize score
    """

    def __init__(self, db_manager=None):
        """
        Args:
            db_manager: Database connection. Defaults to the unified manager —
                previously this defaulted to None, so every affinity lookup
                returned the neutral 1.0 forever and no history was ever read.
        """
        self.db_manager = db_manager or _default_db_manager()
        self._affinity_cache = {}  # Cache: (intent, category) -> success_rate
        self._affinity_support = {}  # Cache: (intent, category) -> observation count
        self._cache_timestamp = None
        self._cache_ttl_seconds = 300  # Refresh cache every 5 minutes

    async def get_affinity_multiplier(
        self,
        intent_type: IntentType,
        category_name: str
    ) -> float:
        """
        Get success rate multiplier for (intent_type, category) pair.

        Returns:
            Multiplier in range [0.5, 1.5]:
            - 1.0 = no data or average performance
            - 1.5 = high success rate (>80%)
            - 0.5 = low success rate (<40%)
        """
        # Refresh cache if stale
        await self._refresh_cache_if_needed()

        # Look up affinity in cache
        cache_key = (intent_type.value, category_name)
        if cache_key in self._affinity_cache:
            success_rate = self._affinity_cache[cache_key]
            return self._success_rate_to_multiplier(success_rate)

        # No historical data → neutral multiplier
        return 1.0

    def multiplier_now(self, intent_type: "IntentType", category_name: str) -> float:
        """The multiplier from the CACHE, without awaiting anything.

        Ranking is synchronous and on the hot path of every task, so it cannot
        await a database read. This answers from whatever the last refresh
        loaded and returns the neutral 1.0 when it has nothing -- which is the
        honest answer for a cold cache, not a measured one.

        `cache_is_stale()` tells a caller whether to schedule a refresh; the
        two are kept separate so reading can never block on loading.
        """
        rate = self._affinity_cache.get((intent_type.value, category_name))
        if rate is None:
            return 1.0
        return self._success_rate_to_multiplier(rate)

    def cache_is_stale(self) -> bool:
        """Whether the affinity cache has never loaded or has aged out."""
        if self._cache_timestamp is None:
            return True
        return ((datetime.now() - self._cache_timestamp).total_seconds()
                > self._cache_ttl_seconds)

    def support_now(self, intent_type: "IntentType", category_name: str) -> int:
        """How many observations back the multiplier. Zero means no evidence,
        which must stay distinguishable from evidence that averaged out."""
        return int(self._affinity_support.get((intent_type.value, category_name), 0))

    def _success_rate_to_multiplier(self, success_rate: float) -> float:
        """
        Convert success rate (0.0-1.0) to score multiplier (0.5-1.5).

        Mapping:
        - 1.0 (100% success) → 1.5x multiplier
        - 0.8 (80% success) → 1.3x multiplier
        - 0.6 (60% success) → 1.0x multiplier (neutral)
        - 0.4 (40% success) → 0.7x multiplier
        - 0.0 (0% success) → 0.5x multiplier
        """
        if success_rate >= 0.8:
            return 1.0 + (success_rate - 0.6) * 1.25  # 0.8 → 1.25, 1.0 → 1.5
        elif success_rate >= 0.6:
            return 1.0 + (success_rate - 0.6) * 1.5   # 0.6 → 1.0, 0.8 → 1.3
        else:
            return 0.5 + (success_rate * 0.833)       # 0.0 → 0.5, 0.6 → 1.0

    async def _refresh_cache_if_needed(self):
        """Refresh affinity cache from database if TTL expired"""
        now = datetime.now()

        # Check if cache needs refresh
        if (self._cache_timestamp is None or
            (now - self._cache_timestamp).total_seconds() > self._cache_ttl_seconds):

            await self._load_affinity_data()
            self._cache_timestamp = now

    async def _load_affinity_data(self):
        """Load tool category affinity data from database"""
        if not self.db_manager:
            logger.warning("No database manager configured, using neutral affinities")
            return

        try:
            # Aggregated directly from tool_usage_history rather than through a
            # `tool_category_affinity` view — that view does not exist, so this
            # query previously failed even when a db_manager was supplied.
            query = """
                SELECT intent_type::text AS intent_type,
                       cat                AS category_name,
                       avg(CASE WHEN success THEN 1.0 ELSE 0.0 END) AS success_rate,
                       count(*)           AS total_uses
                FROM tool_usage_history,
                     jsonb_array_elements_text(tool_categories_used) AS cat
                GROUP BY intent_type, cat
                HAVING count(*) >= 3
            """

            rows = await self.db_manager.execute_query(query, fetch_all=True) or []

            # Build cache
            self._affinity_cache = {}
            self._affinity_support = {}
            for row in rows:
                intent_type = row['intent_type']
                category_name = row['category_name']
                success_rate = float(row['success_rate'])
                total_uses = row['total_uses']

                cache_key = (intent_type, category_name)
                self._affinity_cache[cache_key] = success_rate
                # `total_uses` was selected and then discarded, so a caller could
                # not tell "measured as neutral" from "no evidence" — both
                # surfaced as the multiplier 1.0. Retaining it lets the owner
                # report an AffinityEstimate that says which one it is.
                self._affinity_support[cache_key] = int(total_uses)

            logger.info(f"Loaded {len(self._affinity_cache)} tool affinity mappings from history")

        except Exception as e:
            logger.error(f"Failed to load tool affinity data: {e}")
            # Continue with empty cache (neutral multipliers)


class ToolUsageRecorder:
    """
    Records tool usage outcomes to build historical data for adaptive learning.

    This is the feedback loop: after each task completes, record which tools
    were used, what the intent was, and whether it succeeded.
    """

    def __init__(self, db_manager=None):
        # Defaults to the unified manager for the same reason as above: with
        # None, record_usage() silently returned and tool_usage_history stayed
        # empty, which starved the affinity scorer that reads it.
        self.db_manager = db_manager or _default_db_manager()

    async def record_usage(
        self,
        task_id: str,
        task_description: str,
        intent_type: IntentType,
        tool_categories_used: List[str],
        tool_names_used: List[str],
        success: bool,
        outcome_quality: Optional[float] = None,
        confidence: Optional[float] = None,
        execution_time_seconds: Optional[int] = None,
        iterations_count: Optional[int] = None,
        failure_reason: Optional[str] = None,
        selection_score: Optional[float] = None,
        selection_reason: Optional[str] = None
    ):
        """
        Record tool usage outcome to database.

        Args:
            task_id: Task identifier
            task_description: Task description text
            intent_type: Classified intent type
            tool_categories_used: List of tool category names used
            tool_names_used: List of specific tool names used
            success: Whether task completed successfully
            outcome_quality: Quality score 0.0-1.0 (optional)
            confidence: Executor's confidence in result (optional)
            execution_time_seconds: How long task took (optional)
            iterations_count: Number of agentic iterations (optional)
            failure_reason: Why task failed (if applicable)
            selection_score: How well the CHOSEN tool ranked against the
                snapshot the decision was made from — a different question from
                `outcome_quality`, which is how well the task went. A task can
                succeed on a badly-chosen tool and fail on a well-chosen one,
                and a learner that cannot separate those learns the wrong thing.
                The columns existed and nothing wrote them: this parameter did
                not exist, so `observe()` smuggled the score through
                `outcome_quality` and the dedicated column stayed NULL.
            selection_reason: The SelectionOutcome that score came from
                (ACCEPTABLE / MISRANKED / UNRANKED), so a NULL score is
                readable as "no ranking snapshot" rather than "not measured".
        """
        if not self.db_manager:
            logger.warning("No database manager, cannot record tool usage")
            return

        try:
            import uuid
            import json

            usage_id = str(uuid.uuid4())

            # asyncpg uses $N placeholders, not %s, and there is no
            # execute_update() on the unified manager — both were why this
            # never wrote a row.
            query = """
                INSERT INTO tool_usage_history (
                    usage_id, task_id, task_description, intent_type,
                    tool_categories_used, tool_names_used,
                    success, outcome_quality, confidence,
                    execution_time_seconds, iterations_count, failure_reason,
                    selection_score, selection_reason,
                    started_at, completed_at
                ) VALUES (
                    $1, $2, $3, $4::intent_type, $5::jsonb, $6::jsonb,
                    $7, $8, $9, $10, $11, $12, $13, $14, NOW(), NOW()
                )
            """

            params = (
                usage_id,
                task_id,
                task_description,
                intent_type.value,
                json.dumps(tool_categories_used),
                json.dumps(tool_names_used),
                success,
                outcome_quality,
                confidence,
                execution_time_seconds,
                iterations_count or 1,
                failure_reason,
                selection_score,
                selection_reason
            )

            await self.db_manager.execute_query(query, params, commit=True)

            logger.info(
                f"Recorded tool usage: intent={intent_type.value}, "
                f"categories={tool_categories_used}, success={success}"
            )

        except Exception as e:
            logger.error(f"Failed to record tool usage: {e}")
            # Don't raise - recording failures shouldn't block task completion


async def get_adaptive_category_scores(
    task_description: str,
    base_keyword_scores: Dict[str, float],
    db_manager=None
) -> Dict[str, float]:
    """
    Apply adaptive learning to base keyword scores.

    Process:
    1. Classify task intent
    2. Query historical success rates for each category given that intent
    3. Multiply base scores by affinity multipliers

    Args:
        task_description: Task description text
        base_keyword_scores: Static keyword matching scores {category: score}
        db_manager: Database connection for historical data

    Returns:
        Adjusted scores: {category: adapted_score}
    """
    # Step 1: Classify intent
    classifier = IntentClassifier()
    intent_type, intent_confidence = classifier.classify(task_description)

    print(f"[ADAPTIVE] Intent: {intent_type.value} (confidence={intent_confidence:.2f})")
    logger.info(f"Classified task intent: {intent_type.value} (confidence={intent_confidence:.2f})")

    # Step 2: Get affinity multipliers
    scorer = ToolAffinityScorer(db_manager=db_manager)

    adapted_scores = {}
    multipliers_applied = []

    for category, base_score in base_keyword_scores.items():
        # Get historical success multiplier
        multiplier = await scorer.get_affinity_multiplier(intent_type, category)

        # Apply multiplier to base score
        adapted_score = base_score * multiplier
        adapted_scores[category] = adapted_score

        # Track significant changes for logging
        if abs(multiplier - 1.0) > 0.1:  # Only log if multiplier is significant
            multipliers_applied.append(f"{category}×{multiplier:.2f}")

    # Log adaptations
    if multipliers_applied:
        print(f"[ADAPTIVE] Applied multipliers: {', '.join(multipliers_applied)}")
        logger.info(f"Applied affinity multipliers: {multipliers_applied}")
    else:
        print(f"[ADAPTIVE] No historical data yet - using base scores")

    return adapted_scores
