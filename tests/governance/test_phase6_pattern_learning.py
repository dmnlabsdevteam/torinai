#!/usr/bin/env python3
"""Governance pattern learning, against the approval gate.

REWRITTEN FOR THE GATE THAT EXISTS. The previous version fed
`record_decision({... "voter_type": ...})` into an in-memory list and asserted
on aggregates of a multi-judge governance session -- `make_decision`, the AI
judge panel and the approval queue -- all of which were retired. It also
exercised `propose_config_change` and `validate_learner_approval`, which
belonged to that model.

Governance is now one gate: a person answers a request in
`unified.pending_approvals`. These tests put REAL requests through
`core.governance.approval_requests`, decide them, and check that the learner
reads the record correctly -- including that it cannot decide anything itself.

Every row created here is namespaced `test6:` and removed at the end.
"""

import asyncio
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "tests"))

from core.governance import approval_requests as gate            # noqa: E402
from core.learning.governance_pattern_learner import (           # noqa: E402
    GovernancePatternLearner, MIN_DECISIONS_FOR_PATTERN)


ACTION = "test6_deployment"
PREFIX = "test6:"


async def _clean(db):
    await db.execute_query(
        "DELETE FROM unified.pending_approvals WHERE action_id LIKE $1",
        (f"{PREFIX}%",), commit=True)
    await db.execute_query(
        "DELETE FROM unified.governance_patterns WHERE action_type = $1",
        (ACTION,), commit=True)


async def _decide(db, index: int, approved: bool, tier: str = "MAJOR",
                  authenticated: bool = False):
    """One real request through the real gate, answered by a person."""
    request = await gate.request(
        action_id=f"{PREFIX}{tier}:{index}", action_type=ACTION, tier=tier,
        scope=tier.lower(), requester="test_suite",
        summary=f"test request {index}", db_manager=db)
    await gate.decide(request.approval_id, approved=approved,
                      decided_by="test_operator", authenticated=authenticated,
                      db_manager=db)


async def test_learns_approval_rate_from_real_decisions(db, learner):
    """A pattern is the gate's own history, not something reported to it."""
    for i in range(1, 5):
        await _decide(db, i, approved=(i == 4), authenticated=(i == 4))

    patterns = [p for p in await learner.learn(min_decisions=MIN_DECISIONS_FOR_PATTERN)
                if p.action_type == ACTION]
    assert patterns, "no pattern learned from four decided requests"
    pattern = patterns[0]
    assert pattern.decided == 4, f"expected 4 decided, got {pattern.decided}"
    assert pattern.approved == 1 and pattern.declined == 3
    assert abs(pattern.approval_rate - 0.25) < 1e-9, pattern.approval_rate
    assert abs(pattern.authenticated_rate - 0.25) < 1e-9, pattern.authenticated_rate
    return "learned 1/4 approved from the real approval table"


async def test_nothing_reported_the_decisions(db):
    """The learner is never told; it reads. A fresh instance sees the same."""
    fresh = GovernancePatternLearner(db_manager=db)
    guidance = await fresh.guidance_for(ACTION, "MAJOR")
    assert guidance["known"] is True, guidance
    assert abs(guidance["approval_rate"] - 0.25) < 1e-9
    return "a fresh instance with no memory reads the same history"


async def test_below_threshold_is_not_a_pattern(db, learner):
    """Two decisions is noise. A rate needs enough of them to mean anything."""
    for i in range(1, 3):
        await _decide(db, i, approved=True, tier="MINOR")
    patterns = [p for p in await learner.learn(min_decisions=MIN_DECISIONS_FOR_PATTERN,
                                               persist=False)
                if p.action_type == ACTION and p.tier == "MINOR"]
    assert not patterns, f"2 decisions should not form a pattern, got {patterns}"
    return f"{MIN_DECISIONS_FOR_PATTERN} decisions required before a rate is reported"


async def test_unknown_is_not_permission(learner):
    """No history predicts neither approval nor refusal."""
    guidance = await learner.guidance_for("never_requested_anything", "MAJOR")
    assert guidance["known"] is False
    assert "approval_rate" not in guidance, (
        "an unknown action must not carry a rate a caller could act on")
    return "an unseen action returns known=False with a reason"


async def test_guidance_carries_no_verdict(learner):
    """Guidance must not contain a field a caller could mistake for a decision.

    This is the whole safety property of the module: it learns what tends to
    happen and has no way to make it happen.
    """
    guidance = await learner.guidance_for(ACTION, "MAJOR")
    forbidden = {"approved_decision", "allow", "permitted", "auto_approve",
                 "decision", "grant"}
    present = forbidden.intersection(guidance.keys())
    assert not present, f"guidance exposes a verdict field: {present}"
    assert isinstance(guidance.get("note"), str)
    return "guidance is history only; no verdict field is exposed"


async def test_learner_cannot_approve(db, learner):
    """The learner has no path to settle a request, by construction."""
    request = await gate.request(
        action_id=f"{PREFIX}unapprovable", action_type=ACTION, tier="MAJOR",
        scope="major", requester="test_suite",
        summary="must remain pending", db_manager=db)

    for name in dir(learner):
        assert "approve" not in name.lower() or name.startswith("_"), (
            f"learner exposes {name!r}, which looks like an approval path")

    await learner.learn(min_decisions=1)
    still = await gate.find(f"{PREFIX}unapprovable", db_manager=db)
    assert still.status == "pending", (
        f"learning changed a request's status to {still.status}")
    assert await gate.decision_for(f"{PREFIX}unapprovable", db_manager=db) is None
    return "learning left the pending request untouched"


async def test_stale_requests_are_visible(db, learner):
    """A question nobody answered blocks everything behind it."""
    stale = await learner.stale_requests(older_than_minutes=0)
    ours = [s for s in stale if str(s["action_id"]).startswith(PREFIX)] \
        if stale and "action_id" in (stale[0] or {}) else stale
    assert stale, "the pending request should be reported as waiting"
    return f"{len(stale)} pending request(s) surfaced as unanswered"


async def test_statistics_come_from_the_record(learner):
    """Counts are read from the gate, not accumulated in memory."""
    stats = await learner.get_statistics()
    assert stats["available"] is True
    assert stats["total_requests"] >= 5
    assert stats["approval_rate"] is None or 0.0 <= stats["approval_rate"] <= 1.0
    return (f"{stats['total_requests']} requests, {stats['pending']} pending, "
            f"rate={stats['approval_rate']}")


async def main() -> int:
    from core.database import get_database_manager

    db = get_database_manager()
    await db.initialize()
    learner = GovernancePatternLearner(db_manager=db)

    await _clean(db)
    results, failures = [], 0
    try:
        for label, coro in [
            ("learns approval rate from real decisions",
             test_learns_approval_rate_from_real_decisions(db, learner)),
            ("nothing reported the decisions", test_nothing_reported_the_decisions(db)),
            ("below threshold is not a pattern",
             test_below_threshold_is_not_a_pattern(db, learner)),
            ("unknown is not permission", test_unknown_is_not_permission(learner)),
            ("guidance carries no verdict", test_guidance_carries_no_verdict(learner)),
            ("learner cannot approve", test_learner_cannot_approve(db, learner)),
            ("stale requests are visible", test_stale_requests_are_visible(db, learner)),
            ("statistics come from the record",
             test_statistics_come_from_the_record(learner)),
        ]:
            try:
                detail = await coro
                results.append(f"  PASS  {label:44} {detail}")
            except AssertionError as failure:
                failures += 1
                results.append(f"  FAIL  {label:44} {failure}")
            except Exception as error:
                failures += 1
                results.append(f"  ERROR {label:44} {type(error).__name__}: {error}")
    finally:
        await _clean(db)

    print("\n".join(results))
    print(f"\n  {len(results) - failures}/{len(results)} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
