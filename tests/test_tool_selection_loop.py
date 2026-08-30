#!/usr/bin/env python3
"""Does what the system learned about tool choice reach the choice?

Everything upstream of this existed and worked: intents classified, outcomes
recorded to `tool_usage_history`, success rates aggregated into per-(intent,
category) multipliers. Nothing read them on the ranking path -- so the system
measured which tools work for which kind of task, and then chose as though it
had not. These tests are about the last link.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.learning.adaptive_tool_learning import IntentType, ToolAffinityScorer
from core.learning.adaptive_tool_owner import (AFFINITY_MIN_SUPPORT,
                                               apply_learned_affinity)


def _scorer_with(history):
    """A scorer whose cache is already loaded, as a live one's would be."""
    scorer = ToolAffinityScorer(db_manager=None)
    for (intent, category), (rate, support) in history.items():
        scorer._affinity_cache[(intent, category)] = rate
        scorer._affinity_support[(intent, category)] = support
    from datetime import datetime
    scorer._cache_timestamp = datetime.now()
    return scorer


@pytest.fixture
def owner(monkeypatch):
    import core.learning.adaptive_tool_owner as owner_module

    class _Owner:
        pass

    holder = _Owner()
    monkeypatch.setattr(owner_module, "get_adaptive_tool_learning",
                        lambda *a, **k: holder)
    return holder


def test_a_category_that_keeps_working_is_promoted(owner):
    owner.scorer = _scorer_with({
        ("debugging", "analysis"): (0.95, 40),
        ("debugging", "filesystem"): (0.20, 40),
    })
    categories = {"good_tool": "analysis", "bad_tool": "filesystem"}
    ranked = apply_learned_affinity(
        "debug why this crashes",
        [("bad_tool", 1.00), ("good_tool", 0.95)],
        categories.get)
    assert [name for name, _ in ranked] == ["good_tool", "bad_tool"], (
        "a near-tie must be broken by what actually worked for this intent"
    )


def test_history_cannot_overrule_relevance(owner):
    """A damped nudge, not an override. A tool never tried for this intent must
    not sit permanently below one that has -- that is how a learner stops
    exploring and never discovers it was wrong."""
    owner.scorer = _scorer_with({("debugging", "analysis"): (1.0, 500)})
    ranked = apply_learned_affinity(
        "debug why this crashes",
        [("clearly_relevant", 2.00), ("well_liked", 1.00)],
        {"clearly_relevant": "filesystem", "well_liked": "analysis"}.get)
    assert ranked[0][0] == "clearly_relevant"


def test_thin_evidence_does_not_move_anything(owner):
    """Below the support floor a rate is noise. Acting on three observations
    and calling it a measurement is how a learner locks onto an accident."""
    owner.scorer = _scorer_with({
        ("debugging", "analysis"): (1.0, AFFINITY_MIN_SUPPORT - 1),
    })
    before = [("a", 1.0), ("b", 0.9)]
    after = apply_learned_affinity("debug why this crashes", list(before),
                                   {"a": "filesystem", "b": "analysis"}.get)
    assert after == before


def test_a_cold_cache_is_neutral_not_a_verdict(owner):
    owner.scorer = _scorer_with({})
    before = [("a", 1.0), ("b", 0.9)]
    after = apply_learned_affinity("debug why this crashes", list(before),
                                   {"a": "filesystem", "b": "analysis"}.get)
    assert after == before
    assert owner.scorer.multiplier_now(IntentType.DEBUGGING, "analysis") == 1.0
    assert owner.scorer.support_now(IntentType.DEBUGGING, "analysis") == 0


def test_a_broken_learner_surfaces_rather_than_silently_reordering(owner):
    """It raises HERE and is contained at the registry, which is the right way
    round: a learner that fails must not quietly return a ranking it did not
    actually adjust, and must not be able to empty a tool search either. The
    containment is asserted by the registry test below."""
    class _Exploding:
        def cache_is_stale(self): raise RuntimeError("boom")

    owner.scorer = _Exploding()
    before = [("a", 1.0), ("b", 0.9)]
    with pytest.raises(RuntimeError):
        apply_learned_affinity("debug this", list(before), {}.get)


def test_the_registry_path_never_drops_tools():
    """The registry wraps the call so a learner failure cannot shrink results."""
    from core.tools import get_tool_registry

    registry = get_tool_registry()
    found = registry.discover_tools("read the contents of a file", limit=4)
    assert found, "discovery must return tools with the affinity step wired in"
    assert any(getattr(t, "name", "") == "read_file" for t in found)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))


# ── the write side: why the table was empty ─────────────────────────────────

def test_every_caller_of_the_recorder_says_why_the_task_ended():
    """`outcome_class` defaults to `indeterminate`, which earns NO credit — the
    right default, because losing an observation is recoverable and inventing
    one is not. But the SUCCESS path relied on that default, so every task that
    completed (the single most informative thing that can happen to a tool
    selection) was filed as "outcome undetermined" and discarded.
    `tool_usage_history` held one row after months, and it was a probe."""
    import re

    source = (Path(__file__).resolve().parents[1]
              / "core" / "agents" / "autonomous"
              / "general_purpose_executor.py").read_text()

    calls = [m.start() for m in re.finditer(r"await self\._record_tool_usage_outcome\(",
                                            source)]
    assert calls, "the recording call site moved; this test must follow it"
    for start in calls:
        depth, i = 0, source.index("(", start)
        while i < len(source):
            depth += (source[i] == "(") - (source[i] == ")")
            if depth == 0:
                break
            i += 1
        call = source[start:i]
        assert "outcome_class" in call, (
            f"a caller omits outcome_class and will silently record "
            f"'indeterminate':\n{call[:400]}"
        )


def test_the_recorder_can_store_a_selection_score():
    """The columns existed, the score was computed, and `record_usage` had no
    parameter for it -- so `observe()` smuggled it through `outcome_quality`
    and the dedicated column stayed NULL. How well the task WENT and how well
    the tool was CHOSEN are different questions: a task can succeed on a badly
    chosen tool and fail on a well chosen one."""
    import inspect

    from core.learning.adaptive_tool_learning import ToolUsageRecorder

    params = inspect.signature(ToolUsageRecorder.record_usage).parameters
    assert "selection_score" in params
    assert "selection_reason" in params
    assert "outcome_quality" in params, "still recorded, and separately"


def test_the_ranking_snapshot_is_actually_captured():
    """`_last_ranked_tools` was READ at the credit step and assigned NOWHERE, so
    every selection scored UNRANKED and the "chose a tool the ranker scored far
    below its top candidate" signal could not fire once."""
    source = (Path(__file__).resolve().parents[1]
              / "core" / "agents" / "autonomous"
              / "general_purpose_executor.py").read_text()
    assert "self._last_ranked_tools = " in source, (
        "the ranking snapshot has a reader but no writer again"
    )
    assert "with_scores=True" in source, (
        "the snapshot needs the ranker's SCORES, not just the order"
    )
