#!/usr/bin/env python3
"""Unit tests for the coordinator's self-event dispatch (Phase 0a).

Exercises the event core in isolation — a bare coordinator with only the
reaction state set — so the dispatch semantics are proven without booting the
whole system: sync ordering, reaction isolation, the reactive drain worker,
the one-owner guard, and the reentrancy depth demotion.
"""
import asyncio
from collections import deque

import pytest

from core.agents.autonomous.autonomous_coordinator import (
    AutonomousCoordinator, SelfEvent, SelfEventType,
)


def _bare_coord() -> AutonomousCoordinator:
    """A coordinator with just the reaction state — no subsystem wiring."""
    c = AutonomousCoordinator.__new__(AutonomousCoordinator)
    c._reactions = {}
    c._reactive_queue = deque()
    c._work_ready = asyncio.Event()
    c._reactive_worker = None
    c._emit_depth = 0
    c._max_emit_depth = 8
    c.active = True
    return c


@pytest.mark.asyncio
async def test_sync_reactions_run_in_priority_order():
    c = _bare_coord()
    order = []

    async def hi(e):
        order.append("high")

    async def lo(e):
        order.append("low")

    # register low first, then high — priority (not registration order) decides
    c.on(SelfEventType.TASK_COMPLETED, lo, name="low", mode="sync", priority=1)
    c.on(SelfEventType.TASK_COMPLETED, hi, name="high", mode="sync", priority=90)
    await c.emit(SelfEvent(SelfEventType.TASK_COMPLETED))
    assert order == ["high", "low"], order


@pytest.mark.asyncio
async def test_failing_reaction_is_isolated():
    c = _bare_coord()
    ran = []

    async def boom(e):
        raise RuntimeError("intended")

    async def ok(e):
        ran.append("ok")

    c.on(SelfEventType.TASK_COMPLETED, boom, name="boom", mode="sync", priority=90)
    c.on(SelfEventType.TASK_COMPLETED, ok, name="ok", mode="sync", priority=1)
    # emit must not raise; the good reaction must still run
    await c.emit(SelfEvent(SelfEventType.TASK_COMPLETED))
    assert ran == ["ok"], ran


@pytest.mark.asyncio
async def test_deferred_reaction_drains_when_woken():
    c = _bare_coord()
    drained = []

    async def slow(e):
        drained.append(e.payload.get("n"))

    c.on(SelfEventType.TASK_COMPLETED, slow, name="slow", mode="deferred")
    worker = asyncio.create_task(c._reactive_drain_worker())
    try:
        await c.emit(SelfEvent(SelfEventType.TASK_COMPLETED, {"n": 1}))
        await c.emit(SelfEvent(SelfEventType.TASK_COMPLETED, {"n": 2}))
        # give the worker a couple of loop turns to drain
        for _ in range(50):
            if drained == [1, 2]:
                break
            await asyncio.sleep(0.01)
        assert drained == [1, 2], drained
    finally:
        c.active = False
        worker.cancel()
        try:
            await worker
        except asyncio.CancelledError:
            pass


@pytest.mark.asyncio
async def test_duplicate_owner_rejected():
    c = _bare_coord()

    async def h(e):
        pass

    c.on(SelfEventType.TASK_COMPLETED, h, name="dup", mode="sync")
    with pytest.raises(ValueError):
        c.on(SelfEventType.TASK_COMPLETED, h, name="dup", mode="sync")


@pytest.mark.asyncio
async def test_bad_mode_rejected():
    c = _bare_coord()

    async def h(e):
        pass

    with pytest.raises(ValueError):
        c.on(SelfEventType.TASK_COMPLETED, h, name="x", mode="nonsense")


@pytest.mark.asyncio
async def test_depth_guard_demotes_sync_to_deferred():
    c = _bare_coord()
    ran_inline = []

    async def h(e):
        ran_inline.append(True)

    c.on(SelfEventType.TASK_COMPLETED, h, name="h", mode="sync")
    # simulate being already at max emit depth: the sync reaction must be
    # enqueued (deferred) rather than run inline, and nothing dropped.
    c._emit_depth = c._max_emit_depth
    await c.emit(SelfEvent(SelfEventType.TASK_COMPLETED))
    assert ran_inline == [], "sync reaction should have been demoted, not run inline"
    assert len(c._reactive_queue) == 1, "demoted reaction must be enqueued, not dropped"
    assert c._work_ready.is_set()


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
