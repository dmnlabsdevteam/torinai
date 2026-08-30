#!/usr/bin/env python3
"""Transactional ownership of a tool-selection learning episode.

The algorithms were never the missing piece. Three real modules already exist:

    adaptive_tool_learning.IntentClassifier      task text -> intent
    adaptive_tool_learning.ToolAffinityScorer    history  -> multipliers
    adaptive_tool_learning.ToolUsageRecorder     outcome  -> tool_usage_history
    tool_selection_feedback.ToolSelectionFeedback  rank position -> selection score

What was missing is an OWNER, and the consequence was not merely a dead writer.

    selection time:  classify intent -> affinities -> rank -> choose
    feedback  time:  classify intent AGAIN -> rank AGAIN -> assign credit

Torin was not learning from the decision it made. It was learning from a
RECONSTRUCTION of that decision. Both reconstructions are deterministic today,
so the defect is latent rather than active — but a change to keyword weights, to
the tool registry, to capability metadata or to accumulated affinity silently
rewrites history, and credit lands on a decision that was never taken.

So `AdaptiveSelection` is the unit of work: the decision is captured once, in
full, including the ranking snapshot the ranker actually produced at the moment
of choosing. The write side consumes that object verbatim and never recomputes.

    executor
        -> AdaptiveToolLearning.select()      -> AdaptiveSelection D
        -> runs under D
        -> AdaptiveToolLearning.observe(D, outcome)
             credit gate -> feedback evaluator -> recorder
        -> tool_usage_history

Two questions stay separate, because they are separate:

    Was the selection measurable?     -> SelectionOutcome / selection_score
    Should this outcome teach?        -> credit_eligible / credit_reason

`OutcomeClass` supplies causal context but is deliberately NOT reused wholesale.
Meta-learning asks "was this strategy a good choice"; this learner asks the
narrower counterfactual "did the outcome tell us anything about the quality of
this TOOL-SELECTION decision". Those admit different evidence.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from .adaptive_tool_learning import (
    IntentClassifier,
    IntentType,
    ToolAffinityScorer,
    ToolUsageRecorder,
)
from .tool_selection_feedback import SelectionOutcome, get_tool_selection_feedback

logger = logging.getLogger(__name__)


# ── learner state ───────────────────────────────────────────────────────────
#
# "No historical data yet - using base scores" was printed on every task for
# months and meant two irreconcilable things: a legitimate cold start, and a
# writer that had been disconnected the entire time. A substrate must be able to
# tell "I have not learned yet" from "my learning loop is broken".

COLD_START = "COLD_START"                    # nothing observed yet — legitimate
LEARNING = "LEARNING"                        # observations accruing, affinities measured
INSUFFICIENT_SUPPORT = "INSUFFICIENT_SUPPORT"  # observations exist, none past the support floor
PERSISTENCE_DEGRADED = "PERSISTENCE_DEGRADED"  # episodes observed but writes are not landing
STALE = "STALE"                              # nothing written recently despite activity


@dataclass(frozen=True)
class AffinityEstimate:
    """A multiplier and whether it is actually MEASURED.

    `multiplier=1.0, measured=False` (no evidence) and `multiplier=1.0,
    measured=True` (measured as exactly neutral) are different facts. The numeric
    consumer may treat both as 1.0; the substrate must not confuse them.
    """

    multiplier: float
    measured: bool
    observations: int
    reason: str


@dataclass(frozen=True)
class AdaptiveSelection:
    """The tool-selection decision, captured once, at the moment it was made.

    Carries the ranking snapshot so feedback scores against the ranking that
    ACTUALLY informed the choice, not against whatever the ranker would say
    later. This is the object that makes the loop causally closed rather than
    merely correlated.
    """

    selection_id: str
    task_id: str

    intent: IntentType
    intent_confidence: float

    base_category_scores: Dict[str, float]
    affinity_multipliers: Dict[str, float]
    final_category_scores: Dict[str, float]
    affinity_support: Dict[str, int]

    selected_categories: Tuple[str, ...] = ()
    # (tool_name, score) exactly as the ranker returned it at selection time.
    ranked_tools: Tuple[Tuple[str, float], ...] = ()

    created_at: datetime = field(default_factory=datetime.now)

    def rank_of(self, tool_name: str) -> Optional[int]:
        """1-based position in the SNAPSHOT, or None if absent."""
        for i, (name, _) in enumerate(self.ranked_tools, start=1):
            if name == tool_name:
                return i
        return None


@dataclass(frozen=True)
class ToolSelectionLearningOutcome:
    """What the episode is allowed to teach, and why."""

    selection_id: str
    outcome_class: str
    credit_eligible: bool
    credit_reason: str

    task_success: Optional[bool] = None
    selection_outcome: Optional[SelectionOutcome] = None
    selection_score: Optional[float] = None
    evidence_id: str = ""


# Does this outcome carry evidence about TOOL-SELECTION quality?
#
# Narrower than meta-learning's credit table on purpose. A task can fail for
# reasons that say nothing about which tool categories were chosen — and
# recording those teaches a false causal relation: "(debugging, filesystem)
# failed" when what actually happened was an LLM timeout.
_CREDIT_ELIGIBLE = {
    "success": (True, "task succeeded under this selection"),
    "strategy_failure": (True, "failure attributable to how the task was approached"),
    "execution_failure": (True, "the chosen tools ran and did not achieve the goal"),
    # Everything below is real, and says nothing about the selection.
    "infrastructure_failure": (False, "machinery failed; selection untested"),
    "safety_blocked": (False, "action refused by policy; selection untested"),
    "invalid_task": (False, "task was malformed; selection untested"),
    "external_failure": (False, "external dependency failed; selection untested"),
    "insufficient_evidence": (False, "outcome undetermined"),
    "indeterminate": (False, "outcome undetermined"),
}


class AdaptiveToolLearning:
    """One owner for the tool-selection learning episode.

    Holds ONE persistence authority and hands it to both the reader and the
    writer. Previously the executor constructed a scorer and a recorder
    independently, each resolving its own database — and the writer sat behind
    `if self.db_manager:`, an attribute the executor never assigned, so the read
    path recovered via its own fallback while the write path was gated off
    entirely. Two constructors happening to choose the same database is not one
    persistence authority.
    """

    def __init__(self, db_manager: Any = None):
        # Explicit injection in production. The sub-components keep their own
        # fallbacks for standalone use, but the owner does not rely on them.
        self.db = db_manager
        self.classifier = IntentClassifier()
        self.scorer = ToolAffinityScorer(db_manager=db_manager)
        self.recorder = ToolUsageRecorder(db_manager=db_manager)
        self.feedback = get_tool_selection_feedback()

        self._episodes_observed = 0
        self._writes_confirmed = 0
        self._last_write_at: Optional[datetime] = None
        self._last_write_error: Optional[str] = None

    # ── selection ───────────────────────────────────────────────────────────

    async def select(
        self,
        task_id: str,
        task_description: str,
        base_category_scores: Dict[str, float],
        ranked_tools: Optional[List[Tuple[str, float]]] = None,
    ) -> AdaptiveSelection:
        """Classify, weight by learned affinity, and CAPTURE the decision."""
        intent, confidence = self.classifier.classify(task_description)

        multipliers: Dict[str, float] = {}
        support: Dict[str, int] = {}
        final: Dict[str, float] = {}

        for category, base in (base_category_scores or {}).items():
            est = await self.estimate_affinity(intent, category)
            multipliers[category] = est.multiplier
            support[category] = est.observations
            final[category] = base * est.multiplier

        selection = AdaptiveSelection(
            selection_id=str(uuid.uuid4()),
            task_id=task_id,
            intent=intent,
            intent_confidence=confidence,
            base_category_scores=dict(base_category_scores or {}),
            affinity_multipliers=multipliers,
            final_category_scores=final,
            affinity_support=support,
            selected_categories=tuple(
                c for c, _ in sorted(final.items(), key=lambda kv: kv[1], reverse=True)
            ),
            ranked_tools=tuple(ranked_tools or ()),
        )
        logger.info(
            f"[ADAPTIVE] selection {selection.selection_id[:8]} intent={intent.value} "
            f"({confidence:.2f}) measured={sum(1 for v in support.values() if v >= 3)}"
            f"/{len(support)} categories"
        )
        return selection

    async def estimate_affinity(self, intent: IntentType, category: str) -> AffinityEstimate:
        """Multiplier plus whether it rests on evidence."""
        multiplier = await self.scorer.get_affinity_multiplier(intent, category)
        observations = 0
        try:
            observations = int(
                self.scorer._affinity_support.get((intent.value, category), 0)
            ) if hasattr(self.scorer, "_affinity_support") else 0
        except Exception:
            observations = 0

        measured = (intent.value, category) in getattr(self.scorer, "_affinity_cache", {})
        return AffinityEstimate(
            multiplier=multiplier,
            measured=measured,
            observations=observations,
            reason="measured" if measured else "insufficient_support",
        )

    # ── observation ─────────────────────────────────────────────────────────

    async def observe(
        self,
        selection: AdaptiveSelection,
        outcome_class: str,
        task_success: Optional[bool],
        tool_names_used: List[str],
        tool_categories_used: Optional[List[str]] = None,
        primary_tool: Optional[str] = None,
        tool_exists: bool = True,
        execution_time_seconds: Optional[int] = None,
        iterations_count: Optional[int] = None,
        failure_reason: Optional[str] = None,
        outcome_quality: Optional[float] = None,
    ) -> ToolSelectionLearningOutcome:
        """Assign credit to THIS decision, using THIS decision's snapshot."""
        self._episodes_observed += 1

        oc = (outcome_class or "indeterminate").lower()
        eligible, reason = _CREDIT_ELIGIBLE.get(oc, (False, f"unknown outcome class '{oc}'"))

        sel_outcome: Optional[SelectionOutcome] = None
        sel_score: Optional[float] = None

        if eligible and primary_tool:
            # Scored against the snapshot, NOT a fresh discover_tools() call.
            # Re-ranking here would let registry changes, capability edits or
            # accumulated affinity rewrite what the decision looked like.
            sel_score, sel_outcome = self.score_against_snapshot(
                selection, primary_tool, bool(task_success), tool_exists
            )

        outcome = ToolSelectionLearningOutcome(
            selection_id=selection.selection_id,
            outcome_class=oc,
            credit_eligible=eligible,
            credit_reason=reason,
            task_success=task_success,
            selection_outcome=sel_outcome,
            selection_score=sel_score,
            evidence_id=str(uuid.uuid4()),
        )

        if not eligible:
            logger.info(
                f"[ADAPTIVE] selection {selection.selection_id[:8]} NOT credited "
                f"({oc}: {reason}) — affinity unchanged"
            )
            return outcome

        try:
            await self.recorder.record_usage(
                task_id=selection.task_id,
                task_description="",  # the decision, not the prose, is the record
                intent_type=selection.intent,      # from the DECISION, never re-classified
                tool_categories_used=list(
                    tool_categories_used or selection.selected_categories
                ),
                tool_names_used=list(tool_names_used or ()),
                success=bool(task_success),
                # HOW WELL IT WENT and HOW WELL IT WAS CHOSEN are two questions.
                # `sel_score` used to be written into `outcome_quality` because
                # `record_usage` had no parameter for it — so the dedicated
                # column stayed NULL and the one field that was populated
                # answered neither question cleanly. A task can succeed on a
                # badly-chosen tool and fail on a well-chosen one; a learner
                # that cannot separate those learns the wrong thing.
                outcome_quality=outcome_quality,
                selection_score=sel_score,
                selection_reason=(sel_outcome.value if sel_outcome else None),
                confidence=selection.intent_confidence,
                execution_time_seconds=execution_time_seconds,
                iterations_count=iterations_count,
                failure_reason=failure_reason,
            )
            self._writes_confirmed += 1
            self._last_write_at = datetime.now()
            self._last_write_error = None
            # Invalidate only what this episode could have changed, so the next
            # decision sees it — waiting out a 300s TTL would mean the substrate
            # cannot act on what it just learned.
            self._invalidate(selection.intent, tool_categories_used or selection.selected_categories)
        except Exception as e:
            self._last_write_error = str(e)
            logger.error(f"[ADAPTIVE] observation NOT persisted: {e}", exc_info=True)

        return outcome

    def score_against_snapshot(
        self,
        selection: AdaptiveSelection,
        tool_name: str,
        succeeded: bool,
        tool_exists: bool = True,
    ) -> Tuple[Optional[float], SelectionOutcome]:
        """Selection quality judged by the ranking that informed the choice.

        Mirrors ToolSelectionFeedback.score_selection's bands, but reads the
        snapshot instead of calling discover_tools() again. UNRANKED keeps its
        precise meaning: the ranker produced nothing usable AT SELECTION TIME —
        it is not a bucket for infrastructure failures, which never reach here
        because the credit gate refuses them first.
        """
        from .tool_selection_feedback import (
            OUTCOME_SCORE, ACCEPTABLE_RANK, MARGINAL_RANK,
        )

        if not tool_exists:
            return OUTCOME_SCORE[SelectionOutcome.NOT_FOUND], SelectionOutcome.NOT_FOUND
        if not succeeded:
            return OUTCOME_SCORE[SelectionOutcome.FAILED], SelectionOutcome.FAILED
        if not selection.ranked_tools:
            return None, SelectionOutcome.UNRANKED

        position = selection.rank_of(tool_name)
        if position is None:
            return OUTCOME_SCORE[SelectionOutcome.MISRANKED], SelectionOutcome.MISRANKED
        if position <= ACCEPTABLE_RANK:
            return round(1.0 - (position - 1) * 0.1, 4), SelectionOutcome.ACCEPTABLE
        if position <= MARGINAL_RANK:
            return 0.6, SelectionOutcome.ACCEPTABLE
        return OUTCOME_SCORE[SelectionOutcome.MISRANKED], SelectionOutcome.MISRANKED

    # ── state ───────────────────────────────────────────────────────────────

    def _invalidate(self, intent: IntentType, categories) -> None:
        cache = getattr(self.scorer, "_affinity_cache", None)
        if cache is None:
            return
        for c in categories or ():
            cache.pop((intent.value, c), None)

    async def status(self) -> Dict[str, Any]:
        """Cold start and broken must not look the same."""
        rows = None
        try:
            if self.db:
                r = await self.db.execute_query(
                    "SELECT count(*) AS n FROM tool_usage_history", fetch_all=True
                )
                rows = int((r or [{}])[0].get("n", 0))
        except Exception as e:
            self._last_write_error = str(e)

        measured = len(getattr(self.scorer, "_affinity_cache", {}) or {})

        if rows is None:
            mode = PERSISTENCE_DEGRADED
        elif self._episodes_observed > 0 and self._writes_confirmed == 0:
            # The decisive case: episodes happened and nothing landed. Under the
            # old code this was indistinguishable from a cold start.
            mode = PERSISTENCE_DEGRADED
        elif rows == 0:
            mode = COLD_START
        elif measured == 0:
            mode = INSUFFICIENT_SUPPORT
        else:
            mode = LEARNING

        return {
            "mode": mode,
            "history_rows": rows,
            "measured_affinities": measured,
            "episodes_observed": self._episodes_observed,
            "writes_confirmed": self._writes_confirmed,
            "last_write_at": self._last_write_at.isoformat() if self._last_write_at else None,
            "last_write_error": self._last_write_error,
        }


#: How far a learned affinity may move the ranker.
#:
#: The multiplier lives in [0.5, 1.5], and applying it raw would let history
#: overrule relevance outright -- a tool that has never been tried for this
#: intent would sit permanently below one that has, which is how a bandit stops
#: exploring and never discovers it was wrong. Damped to a nudge: it reorders
#: near-ties, and cannot lift an irrelevant tool over a relevant one.
AFFINITY_WEIGHT = 0.25

#: Below this many observations the rate is noise, not a measurement. The SQL
#: already refuses to aggregate under three; this refuses to ACT under six.
AFFINITY_MIN_SUPPORT = 6


def apply_learned_affinity(task_description: str,
                           scored: "list",
                           category_of) -> "list":
    """Re-rank `(name, score)` pairs by what history says about this intent.

    THE LAST LINK. Everything upstream of this was already built: intents are
    classified, outcomes recorded to `tool_usage_history`, success rates
    aggregated into multipliers. Nothing read them -- `get_affinity_multiplier`
    had no caller on the ranking path, so the system measured which tools work
    for which kind of task and then chose as though it had not.

    Synchronous and cache-only. Ranking runs on the hot path of every task and
    cannot await a database read; a stale cache schedules a refresh and answers
    neutrally in the meantime, which is honest rather than blocking.

    `category_of` maps a tool name to its category string. Passed in because
    this module must not depend on the registry that calls it.
    """
    if not scored:
        return scored
    try:
        owner = get_adaptive_tool_learning()
        scorer = owner.scorer
    except Exception as error:
        logger.debug("affinity unavailable (%s); ranking unchanged", error)
        return scored

    if scorer.cache_is_stale():
        _schedule_affinity_refresh(scorer)

    try:
        intent, _confidence = IntentClassifier().classify(task_description)
    except Exception as error:
        logger.debug("intent unclassified (%s); ranking unchanged", error)
        return scored

    adjusted = []
    moved = 0
    for name, score in scored:
        category = ""
        try:
            category = category_of(name) or ""
        except Exception:
            category = ""
        multiplier = 1.0
        if category and scorer.support_now(intent, category) >= AFFINITY_MIN_SUPPORT:
            multiplier = scorer.multiplier_now(intent, category)
        if multiplier != 1.0:
            moved += 1
        damped = 1.0 + (multiplier - 1.0) * AFFINITY_WEIGHT
        adjusted.append((name, float(score) * damped))

    if moved:
        logger.debug("affinity adjusted %d of %d candidates for intent %s",
                     moved, len(scored), intent.value)
    # Stable: equal scores keep the ranker's order, so affinity breaks ties
    # rather than inventing one.
    adjusted.sort(key=lambda pair: pair[1], reverse=True)
    return adjusted


def _schedule_affinity_refresh(scorer) -> None:
    """Load the cache out of band, if there is a loop to do it on.

    A cache that only refreshes when something awaits it, on a path where
    nothing awaits, never refreshes -- and the neutral multiplier it returns
    forever is indistinguishable from a measured one.
    """
    import asyncio

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.debug("no running loop; affinity cache stays cold this call")
        return
    loop.create_task(_refresh_affinity(scorer))


async def _refresh_affinity(scorer) -> None:
    try:
        await scorer._refresh_cache_if_needed()
    except Exception as error:
        logger.debug("affinity refresh failed: %s", error)


_owner: Optional[AdaptiveToolLearning] = None


def get_adaptive_tool_learning(db_manager: Any = None) -> AdaptiveToolLearning:
    """Process-wide owner. Constructed once, in main.py, with the canonical DB."""
    global _owner
    if _owner is None:
        _owner = AdaptiveToolLearning(db_manager=db_manager)
    elif db_manager is not None and _owner.db is None:
        # Bootstrap ordering: an early consumer may have created it before the
        # database existed. Adopt the real one rather than keeping a crippled
        # owner, and tell both sub-components.
        _owner.db = db_manager
        _owner.scorer.db_manager = db_manager
        _owner.recorder.db_manager = db_manager
        logger.info("AdaptiveToolLearning adopted the canonical database")
    return _owner


__all__ = [
    "AdaptiveToolLearning",
    "AdaptiveSelection",
    "AffinityEstimate",
    "ToolSelectionLearningOutcome",
    "get_adaptive_tool_learning",
    "apply_learned_affinity",
    "AFFINITY_WEIGHT", "AFFINITY_MIN_SUPPORT",
    "COLD_START", "LEARNING", "INSUFFICIENT_SUPPORT", "PERSISTENCE_DEGRADED", "STALE",
]
