#!/usr/bin/env python3
"""
Phase 5A: Task Creation Governance Tests
Using TestBase for MySQL logging
"""

import pytest
import asyncio
import sys
from pathlib import Path

# Add project root and tests directory to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "tests"))

from test_base import TestBase
from core.agents.autonomous.task_queue import TaskQueue
from core.agents.autonomous.shared_types import Task, TaskType, TaskSource, Priority


class TestPhase5ATaskGovernance(TestBase):
    """Phase 5A: Task Creation Governance - MySQL Logged Tests"""

    def __init__(self):
        super().__init__(
            test_category="governance_phase5a",
            test_type="integration"
        )
        self.queue = None

    @pytest.mark.asyncio
    async def test_1_normal_task_creation(self):
        """Single autonomous task should not trigger governance"""
        self.queue = TaskQueue()

        task = Task(
            id="task_1",
            type=TaskType.ANALYSIS,
            source=TaskSource.AUTONOMOUS,
            description="Analyze system metrics"
        )

        result = await self.queue.add_task(task)

        assert result is True, "Task should be added"
        assert self.queue.get_queue_length() == 1, "Queue should have 1 task"
        assert self.queue.governance_triggered_count == 0, "Governance should not trigger for 1 task"

    @pytest.mark.asyncio
    async def test_2_user_defined_tasks_exempt(self):
        """100 user tasks should not trigger governance"""
        self.queue = TaskQueue()

        # Add 100 user tasks
        for i in range(100):
            source = [TaskSource.API, TaskSource.MANUAL, TaskSource.API][i % 3]
            task = Task(
                id=f"user_task_{i}",
                type=TaskType.ANALYSIS,
                source=source,
                description=f"User task {i}"
            )
            result = await self.queue.add_task(task)
            assert result is True, f"User task {i} should be added"

        assert self.queue.get_queue_length() == 100, "Should have 100 tasks"
        assert self.queue.governance_triggered_count == 0, "User tasks never trigger governance"
        assert self.queue.user_tasks_exempt_count == 100, "All 100 should be exempt"

    @pytest.mark.asyncio
    async def test_3_bulk_autonomous_triggers_governance(self):
        """20+ autonomous tasks should trigger governance"""
        self.queue = TaskQueue()

        # Add 19 tasks - should all succeed
        for i in range(19):
            task = Task(
                id=f"auto_{i}",
                type=TaskType.ANALYSIS,
                source=TaskSource.AUTONOMOUS,
                description=f"Auto task {i}"
            )
            result = await self.queue.add_task(task)
            assert result is True, f"Task {i} should be added (below threshold)"

        assert self.queue.governance_triggered_count == 0, "No governance yet"

        # Add 20th task - triggers governance
        task_20 = Task(
            id="auto_19",
            type=TaskType.ANALYSIS,
            source=TaskSource.AUTONOMOUS,
            description="20th task"
        )
        await self.queue.add_task(task_20)

        # Governance should have been triggered
        assert self.queue.governance_triggered_count >= 1, "Governance should trigger on 20th task"

    @pytest.mark.asyncio
    async def test_4_mixed_source_only_counts_autonomous(self):
        """User + autonomous mix should only count autonomous toward threshold"""
        # Backpressure limits raised so they do not decide this test. The
        # default soft_limit is 25, and the 50 user tasks below push the queue
        # into soft pressure, at which point discretionary AUTONOMOUS work is
        # correctly deferred -- so the 10 autonomous tasks never entered the
        # queue and the count came to 55. That is backpressure working, not the
        # governance exemption this test is about, and the two must not be
        # measured through each other.
        self.queue = TaskQueue({"soft_limit": 500, "hard_limit": 1000})

        # 50 user tasks
        for i in range(50):
            task = Task(
                id=f"user_{i}",
                type=TaskType.ANALYSIS,
                source=TaskSource.MANUAL,
                description=f"User {i}"
            )
            await self.queue.add_task(task)

        # 10 autonomous tasks
        for i in range(10):
            task = Task(
                id=f"auto_{i}",
                type=TaskType.ANALYSIS,
                source=TaskSource.AUTONOMOUS,
                description=f"Auto {i}"
            )
            await self.queue.add_task(task)

        # 5 more user tasks
        for i in range(5):
            task = Task(
                id=f"api_{i}",
                type=TaskType.ANALYSIS,
                source=TaskSource.API,
                description=f"API {i}"
            )
            await self.queue.add_task(task)

        assert self.queue.get_queue_length() == 65, "Should have 65 total tasks"
        assert self.queue.user_tasks_exempt_count == 55, "55 user tasks exempt"
        assert len(self.queue.autonomous_task_window) == 10, "Only 10 autonomous tracked"
        assert self.queue.governance_triggered_count == 0, "Below 20 threshold"

    @pytest.mark.asyncio
    async def test_5_window_cleanup(self):
        """Task window should cleanup old entries"""
        self.queue = TaskQueue()

        # Add 10 tasks
        for i in range(10):
            task = Task(
                id=f"task_{i}",
                type=TaskType.ANALYSIS,
                source=TaskSource.AUTONOMOUS,
                description=f"Task {i}"
            )
            await self.queue.add_task(task)

        assert len(self.queue.autonomous_task_window) == 10, "Should have 10 in window"

        # Force window expiry
        import datetime
        self.queue.task_window_duration = datetime.timedelta(seconds=0)

        # Add new task - should cleanup old ones
        task = Task(
            id="new_task",
            type=TaskType.ANALYSIS,
            source=TaskSource.AUTONOMOUS,
            description="New task"
        )
        await self.queue.add_task(task)

        assert len(self.queue.autonomous_task_window) == 1, "Old entries should be removed"

    async def run_all_tests(self):
        """Run all Phase 5A tests"""
        await self.start_session()

        await self.run_test(
            "test_1_normal_task_creation",
            self.test_1_normal_task_creation,
            metadata={
                "description": "Single autonomous task should not trigger governance",
                "expected_behavior": "Task added to queue without governance trigger",
                "governance_threshold": 20,
                "tasks_added": 1
            }
        )

        await self.run_test(
            "test_2_user_defined_tasks_exempt",
            self.test_2_user_defined_tasks_exempt,
            metadata={
                "description": "100 user tasks should not trigger governance",
                "expected_behavior": "All user tasks exempt from governance",
                "governance_threshold": 20,
                "tasks_added": 100,
                "task_sources": ["API", "MANUAL"]
            }
        )

        await self.run_test(
            "test_3_bulk_autonomous_triggers_governance",
            self.test_3_bulk_autonomous_triggers_governance,
            metadata={
                "description": "20+ autonomous tasks should trigger governance",
                "expected_behavior": "Governance triggered on 20th autonomous task",
                "governance_threshold": 20,
                "tasks_added": 20,
                "task_source": "AUTONOMOUS"
            }
        )

        await self.run_test(
            "test_4_mixed_source_only_counts_autonomous",
            self.test_4_mixed_source_only_counts_autonomous,
            metadata={
                "description": "User + autonomous mix should only count autonomous toward threshold",
                "expected_behavior": "Only autonomous tasks counted, user tasks exempt",
                "governance_threshold": 20,
                "user_tasks": 55,
                "autonomous_tasks": 10,
                "total_tasks": 65
            }
        )

        await self.run_test(
            "test_5_window_cleanup",
            self.test_5_window_cleanup,
            metadata={
                "description": "Task window should cleanup old entries",
                "expected_behavior": "Expired tasks removed from tracking window",
                "window_duration": "5 minutes (forced to 0 for test)",
                "tasks_added": 11
            }
        )

        await self.end_session()
        self.print_summary()


async def main():
    """Run Phase 5A tests"""
    tests = TestPhase5ATaskGovernance()
    await tests.run_all_tests()

    # Return exit code
    return 0 if tests.failed_tests == 0 else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
