#!/usr/bin/env python3
"""
Parallel Task Execution Pool
Manages concurrent task execution with resource limits
"""

import asyncio
import logging
import time
from typing import Dict, Any, List, Optional, Callable, Awaitable
from dataclasses import dataclass
from datetime import datetime

from .shared_types import Task, TaskStatus

logger = logging.getLogger(__name__)


@dataclass
class PoolStats:
    """Statistics for task execution pool"""
    total_submitted: int = 0
    total_completed: int = 0
    total_failed: int = 0
    total_timeout: int = 0
    active_tasks: int = 0
    peak_active: int = 0
    total_wait_time_sec: float = 0.0
    total_execution_time_sec: float = 0.0


class TaskExecutionPool:
    """
    Lightweight parallel task execution pool using asyncio.Semaphore

    Manages concurrent task execution without heavyweight threading/processing.
    Uses semaphore to limit parallelism and prevent resource exhaustion.
    """

    def __init__(
        self,
        max_parallel: int = 5,
        timeout_seconds: float = 300.0
    ):
        self.max_parallel = max_parallel
        self.timeout_seconds = timeout_seconds

        # Semaphore for limiting parallelism
        self.semaphore = asyncio.Semaphore(max_parallel)

        # Active task tracking
        self.active_tasks: Dict[str, asyncio.Task] = {}
        self.task_start_times: Dict[str, float] = {}

        # Statistics
        self.stats = PoolStats()

        # Lock for thread-safe stats updates
        self._stats_lock = asyncio.Lock()

        logger.info(
            f"Task execution pool initialized: "
            f"max_parallel={max_parallel}, "
            f"timeout={timeout_seconds}s"
        )

    async def execute(
        self,
        task_id: str,
        func: Callable[..., Awaitable[Any]],
        *args,
        **kwargs
    ) -> Any:
        """
        Execute task through pool with parallelism limit

        Args:
            task_id: Unique task identifier
            func: Async function to execute
            *args: Positional arguments
            **kwargs: Keyword arguments

        Returns:
            Result from function

        Raises:
            asyncio.TimeoutError: If task exceeds timeout
            Exception: Original exception from function
        """
        wait_start = time.time()

        # Acquire semaphore (blocks if at max parallelism)
        async with self.semaphore:
            wait_time = time.time() - wait_start

            async with self._stats_lock:
                self.stats.total_submitted += 1
                self.stats.active_tasks += 1
                self.stats.peak_active = max(self.stats.peak_active, self.stats.active_tasks)
                self.stats.total_wait_time_sec += wait_time

            if wait_time > 1.0:
                logger.info(
                    f"Task {task_id} waited {wait_time:.2f}s for pool slot "
                    f"({self.stats.active_tasks}/{self.max_parallel} active)"
                )

            # Track execution
            exec_start = time.time()
            self.task_start_times[task_id] = exec_start

            try:
                # Execute with timeout
                result = await asyncio.wait_for(
                    func(*args, **kwargs),
                    timeout=self.timeout_seconds
                )

                exec_time = time.time() - exec_start

                async with self._stats_lock:
                    self.stats.total_completed += 1
                    self.stats.active_tasks -= 1
                    self.stats.total_execution_time_sec += exec_time

                logger.info(
                    f"Task {task_id} completed in {exec_time:.2f}s "
                    f"(waited {wait_time:.2f}s)"
                )

                return result

            except asyncio.TimeoutError:
                exec_time = time.time() - exec_start

                async with self._stats_lock:
                    self.stats.total_timeout += 1
                    self.stats.active_tasks -= 1

                logger.error(
                    f"Task {task_id} timed out after {exec_time:.2f}s "
                    f"(limit: {self.timeout_seconds}s)"
                )
                raise

            except Exception as e:
                exec_time = time.time() - exec_start

                async with self._stats_lock:
                    self.stats.total_failed += 1
                    self.stats.active_tasks -= 1

                logger.error(
                    f"Task {task_id} failed after {exec_time:.2f}s: {e}"
                )
                raise

            finally:
                self.task_start_times.pop(task_id, None)

    async def execute_batch(
        self,
        tasks: List[tuple[str, Callable[..., Awaitable[Any]], tuple, dict]]
    ) -> List[tuple[str, bool, Any]]:
        """
        Execute multiple tasks concurrently on the coordinator's event loop.

        Uses asyncio.gather() so all agents share the same event loop as the
        coordinator, DB pool, and LLM inference queue — eliminating cross-loop
        errors entirely.  True I/O concurrency is preserved: DB queries, tool
        calls, and memory lookups all interleave cooperatively while waiting.
        Parallelism is bounded by the semaphore inside execute().

        Args:
            tasks: List of (task_id, func, args, kwargs) tuples

        Returns:
            List of (task_id, success, result_or_error) tuples in submission order
        """
        async def _run_one(task_id, func, args, kwargs):
            try:
                result = await self.execute(task_id, func, *args, **kwargs)
                return (task_id, True, result)
            except Exception as exc:
                return (task_id, False, exc)

        return list(await asyncio.gather(*[
            _run_one(tid, f, args, kwargs)
            for tid, f, args, kwargs in tasks
        ]))

    def get_stats(self) -> Dict[str, Any]:
        """Get pool statistics"""
        avg_wait = (
            self.stats.total_wait_time_sec / self.stats.total_submitted
            if self.stats.total_submitted > 0 else 0.0
        )
        avg_exec = (
            self.stats.total_execution_time_sec / self.stats.total_completed
            if self.stats.total_completed > 0 else 0.0
        )

        return {
            "max_parallel": self.max_parallel,
            "timeout_seconds": self.timeout_seconds,
            "active_tasks": self.stats.active_tasks,
            "peak_active": self.stats.peak_active,
            "total_submitted": self.stats.total_submitted,
            "total_completed": self.stats.total_completed,
            "total_failed": self.stats.total_failed,
            "total_timeout": self.stats.total_timeout,
            "success_rate": (
                self.stats.total_completed / self.stats.total_submitted
                if self.stats.total_submitted > 0 else 0.0
            ),
            "avg_wait_time_sec": avg_wait,
            "avg_execution_time_sec": avg_exec,
            "total_wait_time_sec": self.stats.total_wait_time_sec,
            "total_execution_time_sec": self.stats.total_execution_time_sec
        }

    async def cancel_all(self):
        """Cancel all active tasks"""
        if not self.active_tasks:
            return

        logger.warning(f"Cancelling {len(self.active_tasks)} active tasks")

        for task_id, task in self.active_tasks.items():
            task.cancel()
            logger.info(f"Cancelled task: {task_id}")

        self.active_tasks.clear()
        self.task_start_times.clear()

        async with self._stats_lock:
            self.stats.active_tasks = 0


# Global pool singleton
_pool: Optional[TaskExecutionPool] = None


def get_task_execution_pool(
    max_parallel: int = 5,
    timeout_seconds: float = 300.0
) -> TaskExecutionPool:
    """Get global task execution pool"""
    global _pool
    if _pool is None:
        _pool = TaskExecutionPool(
            max_parallel=max_parallel,
            timeout_seconds=timeout_seconds
        )
    return _pool
