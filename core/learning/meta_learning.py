#!/usr/bin/env python3
"""Meta-Learning System

Learns which learning strategies work best for different task families.

This module implements the core MetaLearner used across TorinAI:
- Tracks strategy outcomes (success/failure, latency, effectiveness)
- Uses a bandit layer (Thompson sampling) for exploration vs exploitation
- Applies an exploration-aware HARD GATE for production safety
- Exposes a singleton accessor ``get_meta_learner``

The design is intentionally self-contained and lightweight so it can be
reused by higher-level systems (autonomous coordinator, interaction
meta-learning, enhanced self-improvement, etc.).
"""

from __future__ import annotations
from core.capability import raise_if_structural

import json
import logging
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from core.learning.learning_interfaces import IStrategySelection

logger = logging.getLogger(__name__)


class TaskFamily(Enum):
    """Families of learning tasks — the axis meta-learning selects strategies on.

    Owned here because this module is what gives the concept meaning: strategies
    are registered and selected per family, ``task_strategy_map`` is keyed by it,
    and persisted rows are reconstructed through ``TaskFamily(r["task_type"])``.
    Members are therefore a persistence contract — renaming one orphans every
    stored strategy carrying the old string.
    """
    CLASSIFICATION = "classification"
    REGRESSION = "regression"
    SEQUENCE = "sequence"
    GENERATION = "generation"
    REINFORCEMENT = "reinforcement"
    REASONING = "reasoning"
    PERCEPTION = "perception"
    CONTROL = "control"


#: Coordinator TaskType -> TaskFamily, keyed by the TaskType's string value.
#:
#: THE ONE AUTHORITY FOR THIS TRANSLATION. It lived inside
#: `AutonomousCoordinator._task_family_for`, reachable only by the coordinator,
#: so `UnifiedLearningSystem` -- which has the task type on every example it
#: learns from -- had no way to ask and fell back to a default instead. It
#: lives next to TaskFamily because this module is what gives the concept
#: meaning; the coordinator now delegates here rather than holding a copy.
#:
#: Three task types are CONTROL work: acting on the system and verifying the
#: effect. Those are the ones the CONTROL arms exist to choose an approach for.
TASK_TYPE_TO_FAMILY = {
    "research":             TaskFamily.REASONING,
    "analysis":             TaskFamily.REASONING,
    "synthesis":            TaskFamily.GENERATION,
    "execution":            TaskFamily.CONTROL,
    "planning":             TaskFamily.CONTROL,
    "validation":           TaskFamily.CLASSIFICATION,
    "communication":        TaskFamily.GENERATION,
    "learning":             TaskFamily.SEQUENCE,
    "optimization":         TaskFamily.REINFORCEMENT,
    "security_remediation": TaskFamily.CONTROL,
    "self_improvement":     TaskFamily.REASONING,
}


def task_family_for_task_type(task_type) -> Optional["TaskFamily"]:
    """The family a coordinator task type belongs to, or None if unknown.

    None, never a default. A task type this does not know is a fact about the
    map, and answering CLASSIFICATION for it is how 10,601 decisions came to be
    filed against classification arms without anything deciding they were
    classification problems.
    """
    if task_type is None:
        return None
    value = getattr(task_type, "value", task_type)
    return TASK_TYPE_TO_FAMILY.get(str(value).lower())



def _json_safe(value: Any) -> Any:
    """Coerce a context snapshot into something json.dumps can handle.

    Decision context comes from live system state and routinely contains enums,
    datetimes and dataclasses. Letting json.dumps raise here would lose the
    whole record, which is the one thing this table exists to prevent.
    """
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    if hasattr(value, "value") and type(value).__name__ != "type":
        return _json_safe(value.value)
    return str(value)


class OutcomeClass(Enum):
    """Why an attempt ended the way it did.

    A bare success/failure boolean cannot distinguish "this strategy was a poor
    choice" from "the machinery needed to try it is broken". Recording the
    second as a strategy failure teaches the substrate a false causal relation:
    the arm is punished for a defect that has nothing to do with its quality,
    and the learner grows confident in a conclusion the evidence never
    supported.
    """

    SUCCESS = "success"
    STRATEGY_FAILURE = "strategy_failure"
    EXECUTION_FAILURE = "execution_failure"
    INFRASTRUCTURE_FAILURE = "infrastructure_failure"
    SAFETY_BLOCKED = "safety_blocked"
    INVALID_TASK = "invalid_task"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    EXTERNAL_FAILURE = "external_failure"
    INDETERMINATE = "indeterminate"


# THE CREDIT INVARIANT. Only these classes may move a posterior. Everything
# else is recorded for analysis and denied credit.
#
# The line between EXECUTION_FAILURE (eligible) and INFRASTRUCTURE_FAILURE
# (not) is: was the work actually attempted through the strategy, or did the
# machinery required to attempt it fail first? A strategy whose executions
# reliably fail is genuinely a worse strategy. A strategy that never got to run
# because a pipeline stage raised ImportError tells us nothing about itself.
#
# SAFETY_BLOCKED is eligible and negative on purpose: repeatedly proposing work
# that safety refuses is a real defect of the *selection* policy, and it is
# tagged distinctly so it can be separated from ordinary failure in analysis.
CREDIT_ELIGIBLE: Dict["OutcomeClass", bool] = {
    OutcomeClass.SUCCESS: True,
    OutcomeClass.STRATEGY_FAILURE: True,
    OutcomeClass.EXECUTION_FAILURE: True,
    OutcomeClass.SAFETY_BLOCKED: True,
    # Denied credit — the failure is not evidence about the strategy:
    OutcomeClass.INFRASTRUCTURE_FAILURE: False,  # broken pipeline / missing symbol / DB down
    OutcomeClass.INVALID_TASK: False,            # the task was malformed to begin with
    OutcomeClass.INSUFFICIENT_EVIDENCE: False,   # ran, but nothing conclusive observed
    OutcomeClass.EXTERNAL_FAILURE: False,        # third party / network outage
    OutcomeClass.INDETERMINATE: False,           # unclassified: conservative default
}


def is_credit_eligible(outcome_class: "OutcomeClass") -> bool:
    """Unknown classes are never eligible. Losing a credit is recoverable;
    recording a false one is not."""
    return CREDIT_ELIGIBLE.get(outcome_class, False)


class LearningStrategyType(str):
    """Lightweight strategy type identifier.

    We keep this as a simple string-based type so that callers can
    supply arbitrary strategy labels ("supervised", "few_shot",
    "transfer", etc.) without requiring a heavy enum dependency.
    """


@dataclass
class MetaLearningRecord:
    """Record of a single learning attempt used for meta-learning."""

    record_id: str
    task_type: TaskFamily
    strategy_type: LearningStrategyType
    success: bool
    performance_score: float
    time_ms: float
    iterations: int = 1
    context: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class LearningStrategy:
    """Tracked learning strategy with performance statistics."""

    strategy_id: str
    strategy_type: LearningStrategyType
    task_type: TaskFamily
    parameters: Dict[str, Any] = field(default_factory=dict)

    # Outcome statistics
    trials: int = 0
    successes: int = 0
    failures: int = 0
    success_rate: float = 0.0

    # Timing / efficiency
    avg_time_ms: float = 0.0
    total_time_ms: float = 0.0

    # Aggregate scores
    effectiveness_score: float = 0.0
    confidence: float = 0.0

    # Operational metadata
    last_used: Optional[datetime] = None


# Defaults aligned with APPROVED_DEFAULTS in meta_metrics_monitor
STRATEGY_MIN_TRIALS = 5
ADAPTATION_THRESHOLD = 0.7


class MetaLearner(IStrategySelection):
    """
    DECLARES `IStrategySelection`. It already did all three of these -- select
    an arm for a TaskFamily, record what happened to it, and report the arms'
    measured state -- and nothing said so, so nothing could ask "who selects
    strategies here" and get an answer. `UnifiedLearningSystem` refuses those
    calls and points at this class in prose; the type now says it.

    The contract was drawn from these signatures rather than the other way
    round, so declaring it adds no method and changes no behaviour.
    """
    """Meta-learning core responsible for strategy selection and adaptation."""

    def __init__(self, config: Dict[str, Any] | None = None) -> None:
        self.config: Dict[str, Any] = config or {}
        self.strategies: Dict[str, LearningStrategy] = {}
        self.learning_records: List[MetaLearningRecord] = []
        self.task_strategy_map: Dict[TaskFamily, List[str]] = defaultdict(list)

        # Status
        self.active: bool = False

        # Optional registry for generic meta-learning tasks (used by
        # interaction_meta_learning and other systems that want to
        # register higher-level "meta tasks" for future use).
        self.meta_tasks: List[Dict[str, Any]] = []
        self._table_ready = False
        self._meta_task_table_ready = False
        self._decision_table_ready = False
        self._loaded = False

        # Configuration
        self.min_trials: int = int(
            self.config.get("min_trials", STRATEGY_MIN_TRIALS)
        )
        self.adaptation_threshold: float = float(
            self.config.get("adaptation_threshold", ADAPTATION_THRESHOLD)
        )
        self.enable_adaptation: bool = bool(
            self.config.get("enable_adaptation", True)
        )

        # Initialize with default strategies
        self._initialize_default_strategies()

        logger.info("MetaLearner initialized")

    async def initialize(self) -> bool:
        """Async initialization hook used by higher-level systems.

        Loads persisted strategy statistics. Without this the bandit relearns
        from Beta(1,1) on every process start: trials/successes/failures lived
        only in memory, so a measured (5,4,1) posterior became (0,0,0) after a
        restart. `memory_db_path` was accepted as config and never opened.
        """
        await self._ensure_loaded()
        self.active = True
        return True

    async def _ensure_loaded(self) -> None:
        """Load persisted statistics exactly once, on whichever path arrives first.

        get_meta_learner() hands out the singleton to callers that never call
        initialize() (EnhancedASISelfImprovement.meta_learner is one). Those
        callers would otherwise record outcomes onto zeroed in-memory defaults
        and then upsert them over the real persisted posteriors -- silently
        destroying learning rather than merely failing to load it.
        """
        if self._loaded:
            return
        self._loaded = True
        await self._ensure_table()
        await self.load_strategies()
        await self._persist_unwritten()

    async def _persist_unwritten(self) -> int:
        """Write registered arms that have never recorded an outcome.

        `save_strategy` had exactly one caller -- `track_learning_outcome` --
        so an arm existed in the table only after it had been SELECTED AND
        SCORED at least once. Registration alone wrote nothing.

        No posterior was lost by that (an arm with zero trials has none), but
        it meant the table held the exercised arms rather than the population:
        29 registered, 15 stored. Anything asking the store how many arms exist
        got the answer "however many have been used", and the count changed
        with whatever a given process had loaded.

        It also hid the more interesting fact. The three designed CONTROL arms
        are registered and have never been chosen once, while CONTROL outcomes
        went to runtime-minted arms instead. An arm that is never selected is
        invisible when only selected arms are written down.
        """
        unwritten = [s for s in self.strategies.values() if s.trials == 0]
        written = 0
        for strategy in unwritten:
            if await self.save_strategy(strategy):
                written += 1
        if written:
            logger.info("Persisted %d registered strategies that had no outcomes "
                        "yet (the store now holds the population, not just the "
                        "exercised arms)", written)
        return written

    # ------------------------------------------------------------------
    # Persistence — strategy statistics must outlive the process
    # ------------------------------------------------------------------

    async def _ensure_table(self) -> bool:
        if self._table_ready:
            return True
        try:
            from core.database import get_database_manager
            db = get_database_manager()
            await db.execute_query(
                """
                CREATE TABLE IF NOT EXISTS meta_learning_strategies (
                    strategy_id         VARCHAR(128) PRIMARY KEY,
                    strategy_type       VARCHAR(64)  NOT NULL,
                    task_type           VARCHAR(64)  NOT NULL,
                    parameters          JSONB NOT NULL DEFAULT '{}'::jsonb,
                    trials              INTEGER NOT NULL DEFAULT 0,
                    successes           INTEGER NOT NULL DEFAULT 0,
                    failures            INTEGER NOT NULL DEFAULT 0,
                    success_rate        NUMERIC(6,4) NOT NULL DEFAULT 0,
                    avg_time_ms         NUMERIC(12,3) NOT NULL DEFAULT 0,
                    total_time_ms       NUMERIC(14,3) NOT NULL DEFAULT 0,
                    effectiveness_score NUMERIC(8,3) NOT NULL DEFAULT 0,
                    confidence          NUMERIC(6,4) NOT NULL DEFAULT 0,
                    last_used           TIMESTAMP,
                    updated_at          TIMESTAMP NOT NULL DEFAULT NOW()
                )
                """,
                commit=True,
            )
            self._table_ready = True
            return True
        except Exception as e:
            logger.error("Meta-learning persistence unavailable: %s", e)
            return False

    async def save_strategy(self, strategy: "LearningStrategy") -> bool:
        """Upsert one strategy's statistics."""
        if not await self._ensure_table():
            return False
        try:
            from core.database import get_database_manager
            await get_database_manager().execute_query(
                """
                INSERT INTO meta_learning_strategies (
                    strategy_id, strategy_type, task_type, parameters, trials,
                    successes, failures, success_rate, avg_time_ms, total_time_ms,
                    effectiveness_score, confidence, last_used, updated_at
                ) VALUES ($1,$2,$3,$4::jsonb,$5,$6,$7,$8,$9,$10,$11,$12,$13,NOW())
                ON CONFLICT (strategy_id) DO UPDATE SET
                    trials = EXCLUDED.trials,
                    successes = EXCLUDED.successes,
                    failures = EXCLUDED.failures,
                    success_rate = EXCLUDED.success_rate,
                    avg_time_ms = EXCLUDED.avg_time_ms,
                    total_time_ms = EXCLUDED.total_time_ms,
                    effectiveness_score = EXCLUDED.effectiveness_score,
                    confidence = EXCLUDED.confidence,
                    last_used = EXCLUDED.last_used,
                    updated_at = NOW()
                """,
                (
                    strategy.strategy_id, str(strategy.strategy_type),
                    strategy.task_type.value, json.dumps(strategy.parameters or {}),
                    strategy.trials, strategy.successes, strategy.failures,
                    round(strategy.success_rate, 4), round(strategy.avg_time_ms, 3),
                    round(strategy.total_time_ms, 3), round(strategy.effectiveness_score, 3),
                    round(strategy.confidence, 4), strategy.last_used,
                ),
                commit=True,
            )
            return True
        except Exception as e:
            logger.error("Failed to persist strategy %s: %s", strategy.strategy_id, e)
            return False

    async def load_strategies(self) -> int:
        """Restore persisted statistics onto the registered strategies."""
        if not await self._ensure_table():
            return 0
        try:
            from core.database import get_database_manager
            rows = await get_database_manager().execute_query(
                "SELECT * FROM meta_learning_strategies", fetch_all=True
            ) or []
            restored = 0
            for row in rows:
                r = dict(row)
                s = self.strategies.get(r["strategy_id"])
                if s is None:
                    # Re-register arms that were created dynamically in an
                    # earlier process. _initialize_default_strategies only knows
                    # the built-in families, so every arm minted at runtime by
                    # _find_or_create_strategy (executor choices, task-type
                    # choices, self-improvement scopes) was read from the table
                    # and thrown away -- persisted but unreachable, which looks
                    # exactly like no persistence at all.
                    try:
                        task_type = TaskFamily(r["task_type"])
                    except ValueError:
                        logger.warning(
                            "Skipping persisted strategy %s: unknown task_type %r",
                            r["strategy_id"], r["task_type"],
                        )
                        continue
                    params = r.get("parameters") or {}
                    if isinstance(params, str):
                        params = json.loads(params)
                    self._add_strategy(
                        strategy_type=LearningStrategyType(r["strategy_type"]),
                        task_type=task_type,
                        parameters=params,
                    )
                    s = self.strategies[r["strategy_id"]]
                s.trials = int(r["trials"])
                s.successes = int(r["successes"])
                s.failures = int(r["failures"])
                s.success_rate = float(r["success_rate"])
                s.avg_time_ms = float(r["avg_time_ms"])
                s.total_time_ms = float(r["total_time_ms"])
                s.effectiveness_score = float(r["effectiveness_score"])
                s.confidence = float(r["confidence"])
                s.last_used = r["last_used"]
                restored += 1
            if restored:
                logger.info("Restored statistics for %d strategies", restored)
            return restored
        except Exception as e:
            # `except` must not turn a wiring defect into an empty result.
            raise_if_structural(e, 'meta_learning.load_strategies')
            logger.error("Failed to load strategy statistics: %s", e)
            return 0

    # ------------------------------------------------------------------
    # Strategy registration and tracking
    # ------------------------------------------------------------------

    def _initialize_default_strategies(self) -> None:
        """Initialize with common learning strategies for classification."""

        try:
            # Supervised learning for classification
            self._add_strategy(
                strategy_type=LearningStrategyType("supervised"),
                task_type=TaskFamily.CLASSIFICATION,
                parameters={"requires_labels": True},
            )

            # Few-shot for quick adaptation
            self._add_strategy(
                strategy_type=LearningStrategyType("few_shot"),
                task_type=TaskFamily.CLASSIFICATION,
                parameters={"num_examples": 5},
            )

            # Transfer learning for related tasks
            self._add_strategy(
                strategy_type=LearningStrategyType("transfer"),
                task_type=TaskFamily.CLASSIFICATION,
                parameters={"base_model": "pretrained"},
            )

            # Coverage for the other task families UnifiedLearningSystem maps to.
            # select_strategy() returns None when a family has no registered
            # strategies, and its caller dereferences the result — so a family
            # with no strategies is an AttributeError, not a graceful skip.
            # CONTROL was missing, and CONTROL is the family that matters most:
            # TaskFamily.SECURITY_REMEDIATION maps to it
            # (autonomous_coordinator:5171), so it is the family of essentially
            # every task Torin actually executes. With no strategies registered,
            # evaluate_strategies(CONTROL) returned {'total_strategies': 0} and
            # select_strategy(CONTROL) returned None -- meta-learning had nothing
            # to choose between and nothing to update for the ONLY work being
            # done. GENERATION and REGRESSION were likewise absent.
            for _family, _types in (
                (TaskFamily.PERCEPTION, ("unsupervised", "clustering")),
                (TaskFamily.REINFORCEMENT, ("policy_gradient", "value_iteration")),
                (TaskFamily.SEQUENCE, ("continual", "replay")),
                (TaskFamily.REASONING, ("meta", "few_shot")),
                # Control = act on the system and verify the effect. The arms are
                # genuinely different approaches to a remediation task, so the
                # bandit has a real choice to learn about.
                (TaskFamily.CONTROL, ("direct_remediation", "diagnose_then_act", "verify_first")),
                (TaskFamily.GENERATION, ("draft_then_refine", "single_pass")),
                (TaskFamily.REGRESSION, ("supervised", "transfer")),
            ):
                for _t in _types:
                    self._add_strategy(
                        strategy_type=LearningStrategyType(_t),
                        task_type=_family,
                        parameters={},
                    )

            logger.info(
                "Initialized default learning strategies (total=%d)",
                len(self.strategies),
            )
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.error("Failed to initialize default strategies: %s", exc)

    async def register_strategy(
        self,
        task_type: TaskFamily,
        strategy_type: LearningStrategyType,
        parameters: Dict[str, Any] | None = None,
    ) -> str:
        """Register a strategy for a task family, restoring its persisted stats.

        Public entry point for subsystems that own their own strategy
        vocabulary (the coordinator's TaskFamily set, for example). Without this
        a family with no registered strategies makes select_strategy return
        None, and the caller falls through to its heuristic forever.
        """
        await self._ensure_loaded()
        strategy_id = self._add_strategy(strategy_type, task_type, parameters)
        strategy = self.strategies[strategy_id]
        if strategy.trials == 0:
            await self.load_strategies()
        return strategy_id

    def _add_strategy(
        self,
        strategy_type: LearningStrategyType,
        task_type: TaskFamily,
        parameters: Dict[str, Any] | None = None,
    ) -> str:
        """Add a learning strategy and return its ID."""

        # Deterministic identity. A timestamped id is a fresh primary key on
        # every process start, so persisted statistics could never be matched
        # back to the strategy they belong to. (task family, strategy type) is
        # the natural key -- re-adding the same pair returns the same strategy
        # rather than a duplicate with a zeroed posterior.
        strategy_id = f"{task_type.value}_{strategy_type}"
        existing = self.strategies.get(strategy_id)
        if existing is not None:
            if parameters:
                existing.parameters.update(parameters)
            return strategy_id

        strategy = LearningStrategy(
            strategy_id=strategy_id,
            strategy_type=strategy_type,
            task_type=task_type,
            parameters=parameters or {},
        )

        self.strategies[strategy_id] = strategy
        self.task_strategy_map[task_type].append(strategy_id)

        logger.debug("Added strategy: %s", strategy_id)
        return strategy_id

    async def track_learning_outcome(
        self,
        task_type: TaskFamily,
        strategy_type: LearningStrategyType,
        success: bool,
        performance_score: float,
        time_ms: float,
        iterations: int = 1,
        context: Dict[str, Any] | None = None,
        decision_id: Optional[str] = None,
        outcome_class: Optional["OutcomeClass"] = None,
    ) -> MetaLearningRecord:
        """Track the outcome of a learning attempt.

        Pass ``decision_id`` (from select_strategy's _decision_sink) to join
        this outcome onto the decision that produced it. Without the join the
        decision log records what was chosen but never what came of it, which
        makes it useless for off-policy estimation.
        """

        await self._ensure_loaded()

        # ── THE CREDIT GATE ──────────────────────────────────────────────
        # An unclassified outcome is treated as INDETERMINATE and denied
        # credit. That is deliberate: a caller that forgets to classify should
        # lose a data point loudly, not silently teach the substrate that a
        # strategy failed when the truth is that a pipeline was broken.
        if outcome_class is None:
            outcome_class = OutcomeClass.INDETERMINATE
            logger.warning(
                "track_learning_outcome called without outcome_class for %s/%s "
                "— denied credit as INDETERMINATE",
                task_type.value, strategy_type,
            )
        eligible = is_credit_eligible(outcome_class)

        record_id = f"meta_{task_type.value}_{datetime.now().timestamp()}"

        record = MetaLearningRecord(
            record_id=record_id,
            task_type=task_type,
            strategy_type=strategy_type,
            success=success,
            performance_score=performance_score,
            time_ms=time_ms,
            iterations=iterations,
            context=context or {},
        )

        self.learning_records.append(record)

        strategy_id = await self._find_or_create_strategy(task_type, strategy_type)

        if strategy_id and not eligible:
            # Recorded, analysable, but the posterior does not move. The arm is
            # not answerable for this outcome.
            logger.info(
                "Credit withheld from %s: outcome_class=%s is not evidence about "
                "the strategy (posterior unchanged at %d/%d)",
                strategy_type, outcome_class.value,
                self.strategies[strategy_id].successes,
                self.strategies[strategy_id].trials,
            )
            if decision_id:
                await self._close_decision(
                    decision_id, success, performance_score, time_ms,
                    outcome_class=outcome_class, credit_applied=False,
                )
            return record

        if strategy_id:
            strategy = self.strategies[strategy_id]

            # Update trial counts
            strategy.trials += 1
            if success:
                strategy.successes += 1
            else:
                strategy.failures += 1

            # Success rate
            strategy.success_rate = (
                strategy.successes / strategy.trials if strategy.trials > 0 else 0.0
            )

            # Exponential moving average for latency
            if strategy.trials == 1:
                strategy.avg_time_ms = time_ms
            else:
                alpha = 0.2
                strategy.avg_time_ms = alpha * time_ms + (1 - alpha) * strategy.avg_time_ms

            strategy.total_time_ms += time_ms

            # Effectiveness: 70% success rate, 30% efficiency (inverse time)
            time_score = max(0.0, 100.0 - (strategy.avg_time_ms / 100.0))
            strategy.effectiveness_score = strategy.success_rate * 70.0 + time_score * 0.3

            # Confidence grows with trials up to 2x min_trials
            strategy.confidence = min(1.0, strategy.trials / (self.min_trials * 2.0))
            strategy.last_used = datetime.now()

            logger.info(
                "Updated strategy %s: success_rate=%.1f%%, effectiveness=%.1f",
                strategy.strategy_type,
                strategy.success_rate * 100.0,
                strategy.effectiveness_score,
            )

            # Persist immediately: the posterior is the learning, and losing it
            # on restart is what made this loop reopen every process start.
            await self.save_strategy(strategy)

            if decision_id:
                await self._close_decision(
                    decision_id, success, performance_score, time_ms,
                    outcome_class=outcome_class, credit_applied=True,
                )

        # Periodically adapt strategies
        if self.enable_adaptation and self.learning_records and (
            len(self.learning_records) % 10 == 0
        ):
            await self._adapt_strategies(task_type)

        return record

    async def _find_or_create_strategy(
        self,
        task_type: TaskFamily,
        strategy_type: LearningStrategyType,
    ) -> Optional[str]:
        """Find existing strategy or create a new one."""

        for strategy_id, strategy in self.strategies.items():
            if strategy.task_type == task_type and strategy.strategy_type == strategy_type:
                return strategy_id

        return self._add_strategy(strategy_type, task_type)

    # ------------------------------------------------------------------
    # Safety gating and confidence
    # ------------------------------------------------------------------

    def _calculate_confidence_interval(
        self,
        successes: int,
        trials: int,
        confidence_level: float = 0.95,
    ) -> Tuple[float, float]:
        """Wilson score confidence interval for a Bernoulli success rate."""

        if trials == 0:
            return (0.0, 0.0)

        import math

        p = successes / trials
        z = {0.90: 1.645, 0.95: 1.96, 0.99: 2.576}.get(confidence_level, 1.96)

        denominator = 1.0 + (z**2) / trials
        centre = (p + (z**2) / (2.0 * trials)) / denominator
        margin = (
            z
            * math.sqrt((p * (1.0 - p) + (z**2) / (4.0 * trials)) / trials)
            / denominator
        )

        lower = max(0.0, centre - margin)
        upper = min(1.0, centre + margin)
        return (lower, upper)

    def validate_strategy_for_production(
        self,
        strategy: LearningStrategy,
        exploration_quota_used: float = 0.0,
        exploration_quota_limit: float = 0.10,
    ) -> Tuple[bool, str]:
        """Exploration-aware HARD GATE for production strategy use.

        Balances stability (block unreliable strategies) with exploration
        (allow discovery within a bounded quota).
        """

        # EXPLORATION MODE: allow low-trial strategies while quota remains
        if exploration_quota_used < exploration_quota_limit and strategy.trials < 5:
            logger.info(
                "✓ Strategy %s allowed for EXPLORATION (trials=%d, quota=%.1f/%.1f)",
                strategy.strategy_id,
                strategy.trials,
                exploration_quota_used * 100.0,
                exploration_quota_limit * 100.0,
            )
            return (True, f"exploration_mode_trials_{strategy.trials}")

        # HARD GATE 1: Minimum trials before confidence
        if strategy.trials < 5:
            return (
                False,
                "Insufficient trials "
                f"({strategy.trials}/5) and exploration quota exhausted "
                f"({exploration_quota_used:.1%} ≥ {exploration_quota_limit:.1%})",
            )

        # HARD GATE 2: Progressive success rate threshold
        if strategy.trials < 20:
            min_success_rate = 0.60
        else:
            min_success_rate = 0.70

        lower_ci, upper_ci = self._calculate_confidence_interval(
            strategy.successes,
            strategy.trials,
            confidence_level=0.95,
        )

        # HARD GATE 3: Confidence interval gating
        if lower_ci < min_success_rate:
            return (
                False,
                "Low confidence success rate: 95% CI "
                f"[{lower_ci:.1%}, {upper_ci:.1%}], lower bound < {min_success_rate:.1%} "
                f"(trials={strategy.trials})",
            )

        logger.info(
            "✅ Strategy %s validated: success_rate=%.1f%%, 95%% CI=[%.1f%%, %.1f%%], trials=%d",
            strategy.strategy_id,
            strategy.success_rate * 100.0,
            lower_ci * 100.0,
            upper_ci * 100.0,
            strategy.trials,
        )

        return (True, f"validated_ci_lower_{lower_ci:.2f}")

    # ------------------------------------------------------------------
    # Bandit-based strategy selection
    # ------------------------------------------------------------------

    async def select_strategy(
        self,
        task_type: TaskFamily,
        prefer_fast: bool = False,
        min_confidence: float = 0.5,
        enable_hard_gate: bool = True,
        exploration_quota_used: float = 0.0,
        strategy_prefix: Optional[str] = None,
        exclude_namespaced: bool = False,
        decision_context: Optional[Dict[str, Any]] = None,
        _decision_sink: Optional[Dict[str, Any]] = None,
    ) -> Optional[LearningStrategy]:
        """Select best learning strategy using a bandit layer + HARD GATE.

        - Uses Thompson sampling over observed success/failure outcomes
          (via ``thompson_sample_strategy``)
        - Optionally incorporates latency preferences when ``prefer_fast``
          is True
        - Applies ``validate_strategy_for_production`` to enforce safety

        ``strategy_prefix`` scopes selection to one decision problem within a
        family. Several distinct decisions map onto the same TaskFamily (which
        kind of task to run vs. which executor to run it with); without a scope
        the sampler would mix arms that are not alternatives to each other and
        return an answer to the wrong question.

        ``exclude_namespaced`` is its complement, and scopes to the BASE
        decision problem: the built-in arms that carry no ``ns:`` qualifier.
        Only a positive prefix existed, so a caller asking the base question
        ("how should I learn from this?") had no way to keep the namespaced
        arms out and could be handed e.g. ``executor:research`` -- crediting a
        coordinator executor-choice posterior with a learning outcome, which is
        the same wrong-question error in the other direction.
        """

        from core.learning.bandit_policy import (
            thompson_sample_strategy,
            thompson_sample_with_propensities,
        )

        await self._ensure_loaded()

        strategy_ids = self.task_strategy_map.get(task_type, [])
        if strategy_prefix:
            strategy_ids = [
                sid for sid in strategy_ids
                if str(self.strategies[sid].strategy_type).startswith(strategy_prefix)
            ]
        elif exclude_namespaced:
            # ``ns:`` is the namespace convention used by every scoped caller
            # (EXECUTOR_NS "executor:", ADAPTIVE_TYPE_NS "tasktype:").
            strategy_ids = [
                sid for sid in strategy_ids
                if ":" not in str(self.strategies[sid].strategy_type)
            ]
        if not strategy_ids:
            logger.warning(
                "No strategies for task type: %s%s",
                task_type.value,
                f" (prefix {strategy_prefix!r})" if strategy_prefix else "",
            )
            return None

        # Soft filter by confidence
        candidates: List[LearningStrategy] = [
            self.strategies[sid]
            for sid in strategy_ids
            if self.strategies[sid].confidence >= min_confidence
        ]

        if not candidates:
            candidates = [self.strategies[sid] for sid in strategy_ids]

        if not candidates:
            return None

        # Bandit-based selection (Thompson sampling). The propensity variant
        # additionally reports P(arm chosen | posterior) for every candidate --
        # the quantity off-policy estimation needs and which is unrecoverable
        # after the fact.
        best, propensities = thompson_sample_with_propensities(
            candidates, prefer_fast=prefer_fast
        )
        if not best:
            return None

        # HARD GATE: production validation with exploration awareness
        if enable_hard_gate:
            is_valid, reason = self.validate_strategy_for_production(
                best,
                exploration_quota_used=exploration_quota_used,
                exploration_quota_limit=0.10,
            )

            if not is_valid:
                logger.error(
                    "🛑 MetaLearner HARD GATE: Strategy %s blocked: %s",
                    best.strategy_id,
                    reason,
                )

                remaining = [c for c in candidates if c.strategy_id != best.strategy_id]
                if not remaining:
                    logger.error(
                        "MetaLearner HARD GATE exhausted for %s; returning blocked best strategy %s to avoid failure",
                        task_type.value,
                        best.strategy_id,
                    )
                    return best

                # Try bandit among remaining
                fallback = thompson_sample_strategy(remaining, prefer_fast=prefer_fast)
                if fallback is not None:
                    is_valid, reason = self.validate_strategy_for_production(
                        fallback,
                        exploration_quota_used=exploration_quota_used,
                        exploration_quota_limit=0.10,
                    )
                    if is_valid:
                        best = fallback
                    else:
                        fallback = None

                # As a final fallback, try by effectiveness score
                if fallback is None:
                    for candidate in sorted(
                        remaining,
                        key=lambda s: s.effectiveness_score,
                        reverse=True,
                    ):
                        is_valid, reason = self.validate_strategy_for_production(
                            candidate,
                            exploration_quota_used=exploration_quota_used,
                            exploration_quota_limit=0.10,
                        )
                        if is_valid:
                            best = candidate
                            break
                    else:
                        # Hard gate exhaustion: prefer the most mature strategy to avoid
                        # crashing the learning pipeline.
                        best_effort = max(
                            remaining,
                            key=lambda s: (
                                getattr(s, "trials", 0),
                                getattr(s, "success_rate", 0.0),
                                getattr(s, "effectiveness_score", 0.0),
                            ),
                        )
                        logger.error(
                            "MetaLearner HARD GATE exhausted for %s; returning best-effort blocked strategy %s (quota=%.1f/10%%)",
                            task_type.value,
                            best_effort.strategy_id,
                            exploration_quota_used * 100.0,
                        )
                        best = best_effort
        

        logger.info(
            "Selected strategy for %s: %s (effectiveness=%.1f, success_rate=%.1f%%, trials=%d)",
            task_type.value,
            best.strategy_type,
            best.effectiveness_score,
            best.success_rate * 100.0,
            best.trials,
        )

        decision_id = await self._record_decision(
            task_type=task_type,
            strategy_prefix=strategy_prefix,
            chosen=best,
            propensities=propensities,
            decision_context=decision_context,
        )
        if _decision_sink is not None:
            _decision_sink["decision_id"] = decision_id

        return best

    # ------------------------------------------------------------------
    # Evaluation, adaptation, and diagnostics
    # ------------------------------------------------------------------

    async def evaluate_strategies(
        self,
        task_type: TaskFamily | None = None,
    ) -> Dict[str, Any]:
        """Evaluate all strategies (optionally filtered by task type)."""

        if task_type is not None:
            strategy_ids = self.task_strategy_map.get(task_type, [])
            strategies = [self.strategies[sid] for sid in strategy_ids]
        else:
            strategies = list(self.strategies.values())

        if not strategies:
            return {
                "total_strategies": 0,
                "task_type": task_type.value if task_type else "all",
            }

        total_trials = sum(s.trials for s in strategies)
        total_successes = sum(s.successes for s in strategies)
        avg_success_rate = (
            total_successes / total_trials if total_trials > 0 else 0.0
        )

        best_strategy = max(
            strategies,
            key=lambda s: s.effectiveness_score,
        )

        by_type: Dict[str, List[LearningStrategy]] = defaultdict(list)
        for strategy in strategies:
            by_type[strategy.strategy_type].append(strategy)

        type_performance: Dict[str, Any] = {}
        for strategy_type, strat_list in by_type.items():
            avg_effectiveness = sum(s.effectiveness_score for s in strat_list) / len(
                strat_list
            )
            type_performance[strategy_type] = {
                "count": len(strat_list),
                "avg_effectiveness": avg_effectiveness,
                "total_trials": sum(s.trials for s in strat_list),
            }

        return {
            "total_strategies": len(strategies),
            "total_trials": total_trials,
            "total_successes": total_successes,
            "avg_success_rate": avg_success_rate,
            "best_strategy": {
                "type": best_strategy.strategy_type,
                "effectiveness": best_strategy.effectiveness_score,
                "success_rate": best_strategy.success_rate,
            },
            "by_type": type_performance,
            "task_type": task_type.value if task_type else "all",
        }

    async def adapt_strategies(self, task_type: TaskFamily) -> None:
        """Force a strategy adaptation pass for a task family.

        Public counterpart to the automatic every-10-records adaptation. The
        coordinator's idle meta-learning tier needs to trigger adaptation on
        demand when its statistical gate fires, rather than waiting for the
        record counter to roll over.
        """
        await self._ensure_loaded()
        await self._adapt_strategies(task_type)

    async def _adapt_strategies(self, task_type: TaskFamily) -> None:
        """Adapt strategies based on performance statistics."""

        try:
            strategy_ids = self.task_strategy_map.get(task_type, [])
            if not strategy_ids:
                return

            successful: List[LearningStrategy] = []
            unsuccessful: List[LearningStrategy] = []

            for sid in strategy_ids:
                strategy = self.strategies[sid]
                if strategy.trials >= self.min_trials:
                    if strategy.success_rate >= self.adaptation_threshold:
                        successful.append(strategy)
                    elif strategy.success_rate < 0.30:
                        unsuccessful.append(strategy)

            if successful:
                logger.info("Meta-learning adaptation for %s:", task_type.value)
                for strat in successful:
                    logger.info(
                        "  ✓ Promoting %s (success=%.1f%%)",
                        strat.strategy_type,
                        strat.success_rate * 100.0,
                    )

            if unsuccessful:
                for strat in unsuccessful:
                    logger.info(
                        "  ✗ Deprecating %s (success=%.1f%%)",
                        strat.strategy_type,
                        strat.success_rate * 100.0,
                    )

            if len(successful) >= 2:
                logger.debug("Opportunity for hybrid strategy exploration")
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.error("Strategy adaptation failed: %s", exc)

    def get_best_strategy_for_task(
        self,
        task_type: TaskFamily,
        context: Dict[str, Any] | None = None,
    ) -> Optional[Tuple[LearningStrategy, float]]:
        """Get best strategy for a task along with a confidence score."""

        strategy_ids = self.task_strategy_map.get(task_type, [])
        if not strategy_ids:
            return None

        best_strategy: Optional[LearningStrategy] = None
        best_score = 0.0

        for sid in strategy_ids:
            strategy = self.strategies[sid]

            score = strategy.effectiveness_score
            score *= 0.5 + 0.5 * strategy.confidence

            if context:
                if context.get("require_speed") and strategy.avg_time_ms > 1000.0:
                    score *= 0.5
                if context.get("require_accuracy") and str(strategy.strategy_type) == "supervised":
                    score *= 1.2

            if score > best_score:
                best_score = score
                best_strategy = strategy

        if best_strategy is None:
            return None

        confidence = min(
            1.0,
            best_strategy.confidence * (best_strategy.success_rate + 0.2),
        )
        return best_strategy, confidence

    def get_statistics(self) -> Dict[str, Any]:
        """Return high-level statistics about the meta-learning system."""

        if not self.strategies:
            return {
                "total_strategies": 0,
                "total_records": 0,
                "task_types_covered": 0,
                "strategy_types_used": 0,
            }

        total_trials = sum(s.trials for s in self.strategies.values())
        total_successes = sum(s.successes for s in self.strategies.values())
        task_types_covered = len(self.task_strategy_map)
        strategy_types_used = len({s.strategy_type for s in self.strategies.values()})

        best = max(self.strategies.values(), key=lambda s: s.effectiveness_score)
        best_info = {
            "task_type": best.task_type.value,
            "strategy_type": best.strategy_type,
            "effectiveness": best.effectiveness_score,
            "success_rate": best.success_rate,
        }

        return {
            "total_strategies": len(self.strategies),
            "total_records": len(self.learning_records),
            "total_trials": total_trials,
            "total_successes": total_successes,
            "success_rate": total_successes / total_trials if total_trials > 0 else 0.0,
            "task_types_covered": task_types_covered,
            "strategy_types_used": strategy_types_used,
            "best_strategy": best_info,
        }

    async def create_meta_task(self, task_config: Dict[str, Any]) -> None:
        """Register a meta-learning task and persist it.

        A meta-task is the durable form of an interaction pattern that cleared
        the promotion bar. Its reader is
        ``InteractionMetaLearner.get_pattern_recommendations``, via the
        ``pattern_db`` restore in that class's ``initialize``: a pattern needs
        frequency >= 3 to be recommendable, so with the in-memory list as the
        only store no pattern could ever accumulate enough occurrences across
        process restarts to be read back.
        """

        task_id = task_config.get("task_id")
        if not task_id:
            raise ValueError("create_meta_task requires task_config['task_id']")

        self.meta_tasks = [
            t for t in self.meta_tasks if t["config"].get("task_id") != task_id
        ]
        self.meta_tasks.append({"config": task_config, "created_at": datetime.now()})

        if not await self._ensure_meta_task_table():
            return
        try:
            from core.database import get_database_manager
            await get_database_manager().execute_query(
                """
                INSERT INTO meta_learning_tasks (
                    task_id, task_family, task_type, domain, difficulty,
                    support_set_size, config, updated_at
                ) VALUES ($1,$2,$3,$4,$5,$6,$7::jsonb,NOW())
                ON CONFLICT (task_id) DO UPDATE SET
                    task_family = EXCLUDED.task_family,
                    task_type = EXCLUDED.task_type,
                    domain = EXCLUDED.domain,
                    difficulty = EXCLUDED.difficulty,
                    support_set_size = EXCLUDED.support_set_size,
                    config = EXCLUDED.config,
                    updated_at = NOW()
                """,
                (
                    task_id,
                    str(task_config.get("task_family", "unknown")),
                    str(task_config.get("task_type", "unknown")),
                    str(task_config.get("domain", "")),
                    float(task_config.get("difficulty", 0.0) or 0.0),
                    int(task_config.get("support_set_size", 0) or 0),
                    json.dumps(task_config.get("metadata", {})),
                ),
                commit=True,
            )
            logger.info("Registered meta-learning task: %s", task_id)
        except Exception as exc:
            logger.error("Failed to persist meta-learning task %s: %s", task_id, exc)

    # ------------------------------------------------------------------
    # Decision records — the log that makes counterfactual credit possible
    # ------------------------------------------------------------------

    async def _ensure_decision_table(self) -> bool:
        if self._decision_table_ready:
            return True
        try:
            from core.database import get_database_manager
            await get_database_manager().execute_query(
                """
                CREATE TABLE IF NOT EXISTS meta_decision_records (
                    decision_id       VARCHAR(64) PRIMARY KEY,
                    task_type         VARCHAR(64) NOT NULL,
                    strategy_prefix   VARCHAR(64),
                    chosen_strategy   VARCHAR(128) NOT NULL,
                    chosen_propensity NUMERIC(8,6),
                    candidates        JSONB NOT NULL DEFAULT '[]'::jsonb,
                    context           JSONB NOT NULL DEFAULT '{}'::jsonb,
                    decided_at        TIMESTAMP NOT NULL DEFAULT NOW(),
                    outcome_known     BOOLEAN NOT NULL DEFAULT FALSE,
                    success           BOOLEAN,
                    performance_score NUMERIC(8,4),
                    time_ms           NUMERIC(14,3),
                    outcome_class     VARCHAR(32),
                    credit_applied    BOOLEAN,
                    outcome_at        TIMESTAMP
                )
                """,
                commit=True,
            )
            await get_database_manager().execute_query(
                "CREATE INDEX IF NOT EXISTS idx_meta_decision_open "
                "ON meta_decision_records (task_type, outcome_known, decided_at DESC)",
                commit=True,
            )
            self._decision_table_ready = True
            return True
        except Exception as e:
            logger.error("Decision-record persistence unavailable: %s", e)
            return False

    async def _record_decision(
        self,
        task_type: TaskFamily,
        strategy_prefix: Optional[str],
        chosen: "LearningStrategy",
        propensities: List[Dict[str, Any]],
        decision_context: Optional[Dict[str, Any]],
    ) -> Optional[str]:
        """Log a decision at the moment it is made.

        Three things exist only at decision time and cannot be reconstructed
        afterwards:

        * the propensity of every arm -- required by IPS / doubly-robust
          estimators to answer "would arm B have worked?", and invalid once the
          posterior moves;
        * the context the decision was made in -- required to learn *when* a
          strategy works rather than only *whether* it works on average;
        * which arms were even available.

        The outcome is joined onto this row later by track_learning_outcome.
        """
        if not await self._ensure_decision_table():
            return None

        chosen_p = next(
            (p["propensity"] for p in propensities
             if p["strategy_id"] == chosen.strategy_id),
            None,
        )
        decision_id = f"d_{uuid.uuid4().hex[:20]}"
        try:
            from core.database import get_database_manager
            await get_database_manager().execute_query(
                """
                INSERT INTO meta_decision_records (
                    decision_id, task_type, strategy_prefix, chosen_strategy,
                    chosen_propensity, candidates, context
                ) VALUES ($1,$2,$3,$4,$5,$6::jsonb,$7::jsonb)
                """,
                (
                    decision_id,
                    task_type.value,
                    strategy_prefix,
                    chosen.strategy_id,
                    chosen_p,
                    json.dumps(propensities),
                    json.dumps(_json_safe(decision_context or {})),
                ),
                commit=True,
            )
            return decision_id
        except Exception as e:
            logger.error("Could not record decision: %s", e)
            return None

    async def reap_abandoned_decisions(
        self, older_than_minutes: int = 60
    ) -> int:
        """Close decisions whose outcome will never arrive. Returns how many.

        A decision row is written when an arm is selected and closed when the
        work finishes. If the process dies in between -- a crash, a shutdown, a
        fire-and-forget task that outlived its interpreter -- the row stays open
        forever. 10,618 such rows accumulated between 2026-08-15 and 08-20,
        and every closure-rate metric averages them in permanently.

        They are closed as INDETERMINATE, which is credit-ineligible: the arm
        is neither rewarded nor punished, because nobody observed how it did.
        Recording them as failures would charge a strategy for the process
        exiting, which is precisely what the credit invariant forbids.

        The window is deliberately generous. A long-running task that is still
        legitimately in flight must not be declared abandoned.
        """
        try:
            from core.database import get_database_manager

            rows = await get_database_manager().execute_query(
                f"""UPDATE unified.meta_decision_records
                       SET outcome_known = true,
                           success = false,
                           outcome_class = $1,
                           credit_applied = false,
                           outcome_at = NOW()
                     WHERE outcome_known = false
                       AND decided_at < NOW() - INTERVAL '{int(older_than_minutes)} minutes'
                 RETURNING decision_id""",
                (OutcomeClass.INDETERMINATE.value,), fetch_all=True) or []
        except Exception as error:
            logger.error("Could not reap abandoned decisions: %s", error)
            return 0

        if rows:
            logger.info("Closed %d abandoned decision(s) as INDETERMINATE; no "
                        "arm gained or lost credit from them", len(rows))
        return len(rows)

    async def _close_decision(
        self,
        decision_id: str,
        success: bool,
        performance_score: float,
        time_ms: float,
        outcome_class: Optional["OutcomeClass"] = None,
        credit_applied: bool = True,
    ) -> None:
        """Join the realised outcome onto its decision row.

        ``credit_applied`` is stored so the log distinguishes "this arm lost"
        from "this arm was denied credit because the failure was not its
        fault" -- without it, an audit of the decision log would reach exactly
        the false conclusion the credit gate exists to prevent.
        """
        if not await self._ensure_decision_table():
            return
        try:
            from core.database import get_database_manager
            await get_database_manager().execute_query(
                """
                UPDATE meta_decision_records
                   SET outcome_known = TRUE,
                       success = $2,
                       performance_score = $3,
                       time_ms = $4,
                       outcome_class = $5,
                       credit_applied = $6,
                       outcome_at = NOW()
                 WHERE decision_id = $1
                """,
                (decision_id, bool(success), float(performance_score), float(time_ms),
                 outcome_class.value if outcome_class else None, bool(credit_applied)),
                commit=True,
            )
        except Exception as e:
            logger.error("Could not close decision %s: %s", decision_id, e)

    async def _ensure_meta_task_table(self) -> bool:
        if self._meta_task_table_ready:
            return True
        try:
            from core.database import get_database_manager
            await get_database_manager().execute_query(
                """
                CREATE TABLE IF NOT EXISTS meta_learning_tasks (
                    task_id          VARCHAR(160) PRIMARY KEY,
                    task_family      VARCHAR(64)  NOT NULL,
                    task_type        VARCHAR(64)  NOT NULL,
                    domain           VARCHAR(256) NOT NULL DEFAULT '',
                    difficulty       NUMERIC(6,4) NOT NULL DEFAULT 0,
                    support_set_size INTEGER      NOT NULL DEFAULT 0,
                    config           JSONB        NOT NULL DEFAULT '{}'::jsonb,
                    created_at       TIMESTAMP    NOT NULL DEFAULT NOW(),
                    updated_at       TIMESTAMP    NOT NULL DEFAULT NOW()
                )
                """,
                commit=True,
            )
            self._meta_task_table_ready = True
            return True
        except Exception as e:
            logger.error("Meta-task persistence unavailable: %s", e)
            return False

    async def get_meta_tasks(
        self,
        task_family: Optional[str] = None,
        domain: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Read back registered meta-tasks, most recently updated first."""

        if not await self._ensure_meta_task_table():
            return [t["config"] for t in self.meta_tasks]
        try:
            from core.database import get_database_manager
            clauses, params = [], []
            if task_family:
                params.append(task_family)
                clauses.append(f"task_family = ${len(params)}")
            if domain:
                params.append(domain)
                clauses.append(f"domain = ${len(params)}")
            where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
            rows = await get_database_manager().execute_query(
                f"SELECT * FROM meta_learning_tasks {where} ORDER BY updated_at DESC",
                tuple(params) if params else None,
                fetch_all=True,
            ) or []
            tasks = []
            for row in rows:
                r = dict(row)
                meta = r["config"]
                if isinstance(meta, str):
                    meta = json.loads(meta)
                tasks.append(
                    {
                        "task_id": r["task_id"],
                        "task_family": r["task_family"],
                        "task_type": r["task_type"],
                        "domain": r["domain"],
                        "difficulty": float(r["difficulty"]),
                        "support_set_size": int(r["support_set_size"]),
                        "metadata": meta,
                        "updated_at": r["updated_at"],
                    }
                )
            return tasks
        except Exception as e:
            logger.error("Failed to read meta-learning tasks: %s", e)
            return [t["config"] for t in self.meta_tasks]


class MetaLearningSystem(MetaLearner):
    """Compatibility alias for legacy MetaLearningSystem.

    Prefer MetaLearner/get_meta_learner. This thin wrapper keeps
    older imports working while routing all behavior through
    MetaLearner's implementation.
    """

    def __init__(self, memory_db_path: str = "meta_learning.db", **config: Any) -> None:
        full_config: Dict[str, Any] = dict(config)
        full_config.setdefault("memory_db_path", memory_db_path)

        logger.warning(
            "MetaLearningSystem is deprecated – use MetaLearner or get_meta_learner() "
            "instead. Routing to MetaLearner with config=%s",
            full_config,
        )

        super().__init__(config=full_config)


# ---------------------------------------------------------------------------
# Singleton accessor
# ---------------------------------------------------------------------------

_meta_learner: Optional[MetaLearner] = None


def get_meta_learner(config: Optional[Dict[str, Any]] = None) -> MetaLearner:
    """Get global MetaLearner instance (singleton).

    The first caller may supply a config; subsequent calls ignore
    config overrides and return the existing instance.
    """

    global _meta_learner

    if _meta_learner is None:
        _meta_learner = MetaLearner(config=config or {})
    else:
        if config:
            logger.debug(
                "get_meta_learner called with config after initialization; "
                "ignoring override and returning existing singleton",
            )

    return _meta_learner
