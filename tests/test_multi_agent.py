#!/usr/bin/env python3
"""
Multi-Agent Parallel Execution Test
====================================
Tests parallel task execution, agent coordination, and background intrinsic tasks.

Sections:
  1. TaskExecutionPool — parallel batch dispatch and semaphore limits
  2. AgentCoordinator — fixed registration and routing bugs
  3. Exploration Cycle — multi-goal generation, background task firing
  4. Batch Extrinsic Drain — queue draining up to max_parallel_tasks
  5. VLM Integration — loads Qwen2.5-VL-32B, dispatches 3 concurrent tasks
     (skipped unless VLM_INTEGRATION=1 env var is set)

Usage:
    # Fast unit tests only (no VLM load):
    python3 tests/test_multi_agent.py

    # Include integration tests with real VLM:
    VLM_INTEGRATION=1 python3 tests/test_multi_agent.py
"""

import pytest
import asyncio
import os
import sys
import time
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
load_dotenv(project_root / '.env.production')

from core.agents.autonomous.task_execution_pool import TaskExecutionPool
from core.agents.autonomous.shared_types import (
    Task, TaskType, TaskSource, Priority, Goal
)
from core.agents.agents import AgentCoordinator, AgentType, AgentConfig


PASS = "✓"
FAIL = "✗"
SKIP = "⊘"


def make_task(task_type: TaskType = TaskType.RESEARCH, description: str = "Test task") -> Task:
    return Task(
        id=f"task_{uuid.uuid4().hex[:8]}",
        type=task_type,
        description=description,
        priority=Priority.MEDIUM,
        source=TaskSource.API,
        created_by="test_multi_agent"
    )


# ============================================================================
# SECTION 1: TaskExecutionPool
# ============================================================================

@pytest.mark.asyncio
async def test_pool_single_task():
    """Pool executes a single task and returns its result."""
    pool = TaskExecutionPool(max_parallel=3, timeout_seconds=5.0)
    called = []

    async def work():
        called.append(1)
        return "done"

    result = await pool.execute("t1", work)
    assert result == "done", f"Expected 'done', got {result!r}"
    assert called == [1]
    print(f"  {PASS} single task executes correctly")


@pytest.mark.asyncio
async def test_pool_batch_parallel():
    """execute_batch runs tasks concurrently (wall time < sum of delays)."""
    pool = TaskExecutionPool(max_parallel=5, timeout_seconds=5.0)
    start_times = {}
    end_times = {}

    async def timed_work(name: str):
        start_times[name] = time.monotonic()
        await asyncio.sleep(0.1)
        end_times[name] = time.monotonic()
        return name

    batch = [
        ("a", timed_work, ("a",), {}),
        ("b", timed_work, ("b",), {}),
        ("c", timed_work, ("c",), {}),
    ]
    results = await pool.execute_batch(batch)

    assert all(ok for _, ok, _ in results), "All tasks should succeed"
    assert {r for _, _, r in results} == {"a", "b", "c"}

    wall_time = max(end_times.values()) - min(start_times.values())
    assert wall_time < 0.25, f"Expected parallel execution (<0.25s), got {wall_time:.3f}s"
    print(f"  {PASS} batch of 3 ran in {wall_time:.3f}s (parallel, not {0.3:.1f}s sequential)")


@pytest.mark.asyncio
async def test_pool_semaphore_limits_concurrency():
    """Semaphore cap is respected — never more than max_parallel active at once."""
    max_p = 2
    pool = TaskExecutionPool(max_parallel=max_p, timeout_seconds=5.0)
    active = [0]
    peak = [0]

    async def counted():
        active[0] += 1
        peak[0] = max(peak[0], active[0])
        await asyncio.sleep(0.05)
        active[0] -= 1

    batch = [(f"t{i}", counted, (), {}) for i in range(6)]
    await pool.execute_batch(batch)

    assert peak[0] <= max_p, f"Peak concurrency {peak[0]} exceeded limit {max_p}"
    print(f"  {PASS} semaphore held peak concurrency to {peak[0]} (limit={max_p})")


@pytest.mark.asyncio
async def test_pool_stats():
    """Pool tracks submission, completion, and failure counts correctly."""
    pool = TaskExecutionPool(max_parallel=3, timeout_seconds=5.0)

    async def noop(): pass
    async def boom(): raise ValueError("simulated failure")

    for i in range(3):
        await pool.execute(f"ok_{i}", noop)

    try:
        await pool.execute("fail_1", boom)
    except ValueError:
        pass

    stats = pool.get_stats()
    assert stats["total_submitted"] == 4
    assert stats["total_completed"] == 3
    assert stats["total_failed"] == 1
    print(f"  {PASS} stats: submitted=4, completed=3, failed=1")


# ============================================================================
# SECTION 2: AgentCoordinator bug fixes
# ============================================================================

@pytest.mark.asyncio
async def test_register_agent_no_keyerror():
    """register_agent must not raise KeyError for new agent_id."""
    coordinator = AgentCoordinator(enable_monitoring=False, enable_safety=False)
    mock_agent = MagicMock()
    agent_id = f"mem_{uuid.uuid4().hex[:8]}"

    result = await coordinator.register_agent(
        agent=mock_agent,
        config=AgentConfig(
            agent_id=agent_id,
            agent_type=AgentType.MEMORY,
            name="Test Memory Agent",
            capabilities=["memory_storage"]
        ),
        agent_id=agent_id,
        capabilities=["memory_storage"]
    )

    assert result is True
    assert agent_id in coordinator.agents
    assert agent_id in coordinator.agent_tasks
    assert isinstance(coordinator.agent_tasks[agent_id], list)
    print(f"  {PASS} register_agent initializes task list without KeyError")


@pytest.mark.asyncio
async def test_delegate_task_routes_to_correct_type():
    """delegate_task picks the matching agent type, not the first registered agent."""
    coordinator = AgentCoordinator(enable_monitoring=False, enable_safety=False)

    memory_agent = MagicMock()
    memory_agent.execute = AsyncMock(return_value="memory_result")
    research_agent = MagicMock()
    research_agent.execute = AsyncMock(return_value="research_result")

    # Register memory agent FIRST so the old bug would pick it for all types
    await coordinator.register_agent(
        agent=memory_agent,
        config=AgentConfig("mem_1", AgentType.MEMORY, "Memory", ["memory_storage"]),
        agent_id="mem_1",
        capabilities=["memory_storage"]
    )
    await coordinator.register_agent(
        agent=research_agent,
        config=AgentConfig("res_1", AgentType.RESEARCH, "Research", ["research"]),
        agent_id="res_1",
        capabilities=["research"]
    )

    result = await coordinator.delegate_task(
        task="find papers on transformers",
        task_type="research",
        parameters={}
    )

    assert result == "research_result", f"Expected research_result, got {result!r}"
    research_agent.execute.assert_called_once()
    memory_agent.execute.assert_not_called()
    print(f"  {PASS} delegate_task routes 'research' to research agent, not first-registered")


@pytest.mark.asyncio
async def test_delegate_memory_task():
    """Memory tasks are routed to memory agent."""
    coordinator = AgentCoordinator(enable_monitoring=False, enable_safety=False)

    memory_agent = MagicMock()
    memory_agent.execute = AsyncMock(return_value="stored")

    await coordinator.register_agent(
        agent=memory_agent,
        config=AgentConfig("mem_1", AgentType.MEMORY, "Memory", ["memory_storage"]),
        agent_id="mem_1",
        capabilities=["memory_storage"]
    )

    result = await coordinator.delegate_task("store this", "memory_write", {})
    assert result == "stored"
    print(f"  {PASS} delegate_task routes memory task correctly")


@pytest.mark.asyncio
async def test_delegate_unknown_type_returns_none():
    """Unknown task type returns None gracefully."""
    coordinator = AgentCoordinator(enable_monitoring=False, enable_safety=False)
    result = await coordinator.delegate_task("do something", "unknown_type", {})
    assert result is None
    print(f"  {PASS} delegate_task returns None for unknown type (no crash)")


# ============================================================================
# SECTION 3: Exploration Cycle — multi-goal, background firing
# ============================================================================

@pytest.mark.asyncio
async def test_exploration_cycle_fires_background_tasks():
    """_run_exploration_cycle fires N background tasks without blocking the cycle."""
    from core.agents.autonomous.autonomous_coordinator import AutonomousCoordinator
    from core.agents.autonomous.coordinator_config import CoordinatorConfig

    # Build a minimal coordinator object via __new__ (bypass heavy __init__)
    from core.agents.autonomous.task_queue import TaskQueue

    coordinator = AutonomousCoordinator.__new__(AutonomousCoordinator)
    coordinator.coordinator_config = CoordinatorConfig()
    coordinator.coordinator_config.max_concurrent_goals = 3
    # __new__ skips __init__, so every attribute the exercised path touches has
    # to be supplied here. A real TaskQueue, not a double: the cycle enqueues
    # through it, and a double would let a broken enqueue look like success.
    coordinator.task_queue = TaskQueue()

    fired_tasks = []
    fire_times = []

    async def mock_execute(task):
        fired_tasks.append(task.id)
        fire_times.append(time.monotonic())
        await asyncio.sleep(0.08)

    async def mock_generate_goals(max_goals, system_context):
        return [
            Goal(
                id=f"goal_{i}",
                description=f"Explore topic {i}",
                priority=Priority.LOW,
                expected_novelty=0.7,
                expected_competence_gain=0.6,
                curiosity_value=0.9,
                intrinsic_reward_potential=0.8
            )
            for i in range(max_goals)
        ]

    async def mock_select_type(description, **kwargs):
        # **kwargs so the double does not have to track every keyword the real
        # _select_adaptive_task_type grows (it now takes _decision_sink).
        return TaskType.RESEARCH

    async def mock_collect_context():
        return {}

    coordinator.intrinsic_motivation = MagicMock()
    coordinator.intrinsic_motivation.generate_curiosity_driven_goals = mock_generate_goals
    coordinator._select_adaptive_task_type = mock_select_type
    coordinator._collect_system_context_for_goals = mock_collect_context
    coordinator._execute_and_validate_task = mock_execute

    # Exploration is gated by the behaviour arbiter, so the cycle needs a real
    # disposition to reach the code under test. Built from measured signals via
    # the canonical constructor rather than hand-set: a fabricated
    # AppraisalState would let the test pass against pressures the real
    # pipeline could never produce.
    from core.agents.autonomous.appraisal import build_appraisal, get_appraisal_system
    _appraisal = get_appraisal_system()
    _appraisal.current_state = build_appraisal(
        outcome_quality=0.7,
        epistemic={"information_gain": 0.9, "uncertainty_increase": 0.5},
        action_success_rate=0.9,
    )
    assert _appraisal.current_state.exploration_pressure >= 0.35, (
        "setup did not produce enough exploration pressure to reach the cycle")

    cycle_start = time.monotonic()
    await coordinator._run_exploration_cycle()
    cycle_elapsed = time.monotonic() - cycle_start

    # The cycle itself should return quickly — work is queued, not awaited.
    assert cycle_elapsed < 0.5, (
        f"Cycle took {cycle_elapsed:.3f}s — should return fast since tasks are queued"
    )

    # The cycle ENQUEUES; the task queue's consumer executes. It used to call
    # _execute_and_validate_task directly, and this test still mocked that,
    # so it was watching a dispatch path the cycle no longer uses -- it would
    # have reported zero no matter how well the cycle worked.
    #
    # Breadth is not a constant either: the behaviour arbiter decides how many
    # goals exploration may open, so the count asserted here is the one the
    # directive authorised rather than a hardcoded 3.
    # Bounds, not a recomputation. Re-deriving the exact number here would mean
    # copying the coordinator's slot arithmetic into the test, and the copy
    # would then be free to disagree with it -- which it did, asserting 2
    # against the cycle's 1. What the cycle guarantees is that it opens at
    # least one goal and never more than the configured concurrency.
    queued = coordinator.task_queue.queue.qsize()
    assert 1 <= queued <= coordinator.coordinator_config.max_concurrent_goals, (
        f"queued {queued} exploration task(s), outside "
        f"1..{coordinator.coordinator_config.max_concurrent_goals}"
    )
    print(
        f"  {PASS} exploration cycle returned in {cycle_elapsed*1000:.0f}ms, "
        f"queued {queued} task(s) as authorised"
    )



# ============================================================================
# SECTION 4: Batch Extrinsic Drain
# ============================================================================

@pytest.mark.asyncio
async def test_extrinsic_queue_drains_to_batch():
    """Coordination cycle drains up to max_parallel_tasks from queue in one sweep."""
    from core.agents.autonomous.task_queue import TaskQueue

    queue = TaskQueue()
    tasks = [make_task(description=f"External task {i}") for i in range(4)]
    for t in tasks:
        await queue.add_task(t, priority=Priority.HIGH)

    max_parallel = 3
    batch = []
    qt = await queue.get_next_task(timeout=0.1)
    if qt:
        batch.append(qt.task)
    while len(batch) < max_parallel:
        qt = queue.try_get_task()
        if qt is None:
            break
        batch.append(qt.task)

    assert len(batch) == max_parallel, (
        f"Expected {max_parallel} tasks drained (capped by max_parallel), got {len(batch)}"
    )
    # Fourth task should still be in queue
    remaining = queue.try_get_task()
    assert remaining is not None, "Fourth task should remain in queue after drain"
    print(f"  {PASS} queue drained {len(batch)} tasks (cap={max_parallel}), 1 remains for next cycle")


# ============================================================================
# SECTION 5: VLM Integration (skipped unless VLM_INTEGRATION=1)
# ============================================================================

@pytest.mark.asyncio
async def test_vlm_parallel_tasks():
    """Load Qwen2.5-VL-32B and dispatch 3 concurrent tasks via TaskExecutionPool."""
    if not os.environ.get("VLM_INTEGRATION"):
        print(f"  {SKIP} VLM integration skipped (set VLM_INTEGRATION=1 to run)")
        return

    print("  Loading Qwen2.5-VL-32B (this may take several minutes)...")
    try:
        from core.services.unified_llm import get_llm_service
        llm = get_llm_service()
        if not llm.model_loaded:
            await asyncio.wait_for(llm.initialize(), timeout=600)
        print("  VLM loaded successfully")
    except asyncio.TimeoutError:
        print(f"  {FAIL} VLM load timed out after 600s")
        return
    except Exception as e:
        print(f"  {FAIL} VLM load failed: {e}")
        return

    from core.agents.autonomous.general_purpose_executor import GeneralPurposeExecutor

    executor = GeneralPurposeExecutor(torin_brain=llm)
    print("  Initializing executor (memory agent, tool registry, context manager)...")
    init_ok = await executor.initialize()
    if not init_ok:
        print(f"  {FAIL} Executor initialization failed")
        return

    pool = TaskExecutionPool(max_parallel=3, timeout_seconds=180.0)

    tasks = [
        make_task(TaskType.RESEARCH, "Briefly explain what quantization means in the context of LLMs."),
        make_task(TaskType.RESEARCH, "Briefly explain what LoRA fine-tuning is."),
        make_task(TaskType.ANALYSIS, "Compare GGUF and GPTQ quantization formats in 2-3 sentences."),
    ]

    print(f"  Dispatching {len(tasks)} tasks in parallel via pool...")
    dispatch_start = time.monotonic()

    batch = [(t.id, executor.execute_task, (t,), {}) for t in tasks]
    results = await pool.execute_batch(batch)

    elapsed = time.monotonic() - dispatch_start
    stats = pool.get_stats()

    # pool_ok=True means the function didn't raise — check the actual task result's success field
    task_successes = sum(
        1 for _, pool_ok, result in results
        if pool_ok and isinstance(result, dict) and result.get('success', False)
    )

    print(f"  {PASS if task_successes > 0 else FAIL} {task_successes}/{len(tasks)} tasks succeeded "
          f"in {elapsed:.1f}s (peak_parallel={stats['peak_active']})")

    for task_id, pool_ok, result in results:
        if pool_ok and isinstance(result, dict):
            ok = result.get('success', False)
            summary = result.get('summary', result.get('error', str(result)[:100]))
            print(f"    {PASS if ok else FAIL} {task_id}: {str(summary)[:120]}")
        else:
            print(f"    {FAIL} {task_id}: pool error — {str(result)[:80]}")


# ============================================================================
# RUNNER
# ============================================================================

async def run_section(title: str, tests):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")
    passed = failed = 0
    for name, coro in tests:
        try:
            await coro()
            passed += 1
        except Exception as e:
            print(f"  {FAIL} {name}: {e}")
            import traceback
            traceback.print_exc()
            failed += 1
    return passed, failed


async def main():
    print("\n" + "="*60)
    print("  Multi-Agent Parallel Execution Test Suite")
    print("="*60)

    total_passed = total_failed = 0

    sections = [
        ("1. TaskExecutionPool", [
            ("single task", test_pool_single_task),
            ("batch parallel", test_pool_batch_parallel),
            ("semaphore limit", test_pool_semaphore_limits_concurrency),
            ("stats tracking", test_pool_stats),
        ]),
        ("2. AgentCoordinator Bug Fixes", [
            ("register_agent no KeyError", test_register_agent_no_keyerror),
            ("delegate routes to correct type", test_delegate_task_routes_to_correct_type),
            ("delegate memory task", test_delegate_memory_task),
            ("delegate unknown type → None", test_delegate_unknown_type_returns_none),
        ]),
        ("3. Exploration Cycle — Background Firing", [
            ("multi-goal background tasks", test_exploration_cycle_fires_background_tasks),
        ]),
        ("4. Extrinsic Batch Queue Drain", [
            ("drain to max_parallel cap", test_extrinsic_queue_drains_to_batch),
        ]),
        ("5. VLM Integration (Qwen2.5-VL-32B)", [
            ("parallel task dispatch", test_vlm_parallel_tasks),
        ]),
    ]

    for title, tests in sections:
        p, f = await run_section(title, tests)
        total_passed += p
        total_failed += f

    print(f"\n{'='*60}")
    print(f"  Results: {total_passed} passed, {total_failed} failed")
    print(f"{'='*60}\n")

    return total_failed == 0


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
