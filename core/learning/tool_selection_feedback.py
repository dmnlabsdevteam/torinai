#!/usr/bin/env python3
"""
Tool Selection Feedback
=======================
Reward/consequence signal for *choosing* a tool, as distinct from a tool that
fails.

A tool that fails is already penalised by _fire_reward_signals(). Nothing
recorded the case where a tool succeeded but was the wrong choice — reading a
whole file when a grep would do, or naming a tool that does not exist.

Three signals, all deterministic — no LLM:

  1. NOT_FOUND    the model named a tool that does not exist
  2. FAILED       the tool ran and failed
  3. MISRANKED    the tool ran and succeeded, but the model-free ranker
                  (BM25 + local encoder + capability graph) scored it far
                  below its own top candidate for this task

(3) is the interesting one and it is free: `discover_tools()` already ranks every
tool against the task text without a model. If the agent's pick disagrees badly
with that ranking, that is measurable evidence of a poor selection.

Written to `tool_usage_history.selection_score`, which feeds
`ToolAffinityScorer.get_affinity_multiplier()` and, through it, future ranking.
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class SelectionOutcome(Enum):
    """Why a selection scored the way it did."""
    NOT_FOUND = "not_found"      # named tool does not exist
    FAILED = "failed"            # tool ran, returned failure
    MISRANKED = "misranked"      # succeeded, but ranker strongly disagreed
    ACCEPTABLE = "acceptable"    # succeeded, ranker broadly agreed
    UNRANKED = "unranked"        # ranker unavailable — no signal, not a penalty


# Score floors per outcome. Naming a nonexistent tool is the worst selection
# error available: it costs an iteration and produces nothing.
OUTCOME_SCORE = {
    SelectionOutcome.NOT_FOUND: 0.0,
    SelectionOutcome.FAILED: 0.25,
    SelectionOutcome.MISRANKED: 0.40,
    SelectionOutcome.ACCEPTABLE: 1.0,
    SelectionOutcome.UNRANKED: None,   # record nothing rather than guess
}

# Rank position is the primary signal, not score ratio.
#
# The ranker's raw scores are compressed near the top — for "read the file at
# /etc/hosts" they run read_file 0.999, qualys_get_host_list 0.952,
# ping_host 0.912. A relative-score threshold therefore scores an obviously
# wrong tool at 0.95 and calls it acceptable. Position separates them cleanly:
# the ranker put read_file first and the Qualys tool second, and "second" for a
# file read is a weaker endorsement than 0.95 suggests.
ACCEPTABLE_RANK = 3          # top-3 is a defensible choice
MARGINAL_RANK = 10           # 4-10 is weak but not clearly wrong
MISRANK_THRESHOLD = 0.5      # secondary: score share of the top candidate


class ToolSelectionFeedback:
    """Scores a tool choice against the deterministic ranker."""

    def __init__(self):
        self._rank_cache: Dict[str, List[Tuple[str, float]]] = {}

    async def score_selection(
        self,
        task_description: str,
        tool_name: str,
        succeeded: bool,
        tool_exists: bool = True,
    ) -> Tuple[Optional[float], SelectionOutcome]:
        """Score one tool choice.

        Returns (score, outcome). A None score means "no signal available" —
        deliberately distinct from a zero, which is a real penalty.
        """
        if not tool_exists:
            return OUTCOME_SCORE[SelectionOutcome.NOT_FOUND], SelectionOutcome.NOT_FOUND

        if not succeeded:
            return OUTCOME_SCORE[SelectionOutcome.FAILED], SelectionOutcome.FAILED

        ranked = await self._rank(task_description)
        if not ranked:
            return None, SelectionOutcome.UNRANKED

        top_score = ranked[0][1]
        position = next((i for i, (n, _) in enumerate(ranked, start=1) if n == tool_name), None)

        if position is None:
            # The ranker did not surface it at all for this task
            logger.info(
                f"Tool selection disagreement: {tool_name} absent from the top "
                f"{len(ranked)} for task {task_description[:60]!r}"
            )
            return OUTCOME_SCORE[SelectionOutcome.MISRANKED], SelectionOutcome.MISRANKED

        chosen = next(s for n, s in ranked if n == tool_name)
        relative = (chosen / top_score) if top_score > 0 else 0.0

        if position <= ACCEPTABLE_RANK:
            # Linear within the top band: rank 1 -> 1.0, rank 3 -> 0.8
            score = 1.0 - (position - 1) * 0.1
            return round(score, 4), SelectionOutcome.ACCEPTABLE

        if position <= MARGINAL_RANK:
            logger.debug(
                f"Tool selection weak: {tool_name} ranked {position} for "
                f"task {task_description[:60]!r}"
            )
            return 0.6, SelectionOutcome.ACCEPTABLE

        logger.info(
            f"Tool selection disagreement: {tool_name} ranked {position} "
            f"(top: {ranked[0][0]}, relative score {relative:.2f}) for "
            f"task {task_description[:60]!r}"
        )
        return OUTCOME_SCORE[SelectionOutcome.MISRANKED], SelectionOutcome.MISRANKED

    async def _rank(self, task_description: str) -> List[Tuple[str, float]]:
        """Model-free ranking of tools for a task. Cached per task string.

        discover_tools() is synchronous and returns (tool, score) pairs when
        `with_scores` is set. Its own docstring notes the score is uncalibrated
        across queries and should be thresholded relative to the top score —
        which is exactly what score_selection() does.
        """
        if task_description in self._rank_cache:
            return self._rank_cache[task_description]

        ranked: List[Tuple[str, float]] = []
        try:
            from core.tools.tool_registry import get_tool_registry
            results = get_tool_registry().discover_tools(
                task_description, limit=25, with_scores=True
            )
            for item in results or []:
                try:
                    tool, score = item
                except (TypeError, ValueError):
                    continue
                name = getattr(tool, "name", None)
                if name is not None and score is not None:
                    ranked.append((name, float(score)))
        except Exception as e:
            logger.debug(f"Tool ranking unavailable: {e}")
            return []

        self._rank_cache[task_description] = ranked
        return ranked


_feedback: Optional[ToolSelectionFeedback] = None


def get_tool_selection_feedback() -> ToolSelectionFeedback:
    global _feedback
    if _feedback is None:
        _feedback = ToolSelectionFeedback()
    return _feedback


__all__ = [
    "ToolSelectionFeedback",
    "SelectionOutcome",
    "get_tool_selection_feedback",
    "MISRANK_THRESHOLD",
]
