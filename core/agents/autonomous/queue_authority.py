#!/usr/bin/env python3
"""Queue Authority — the one owner of the substrate's queued, awaited, and
scheduled work.

The self (the autonomous coordinator — the sheriff, Torin, the substrate) is a
WORKER: it pulls work and does it. It does NOT own the queue, the execution
pool, or the scheduler. Those are this authority's, so there is one place that
knows what work exists, what is running, and what is due.

Three kinds of job, one authority:
  1. WORK jobs   — ad-hoc tasks pushed on, pulled off by priority, run under a
                   concurrency limit. Admission control (backpressure) is the
                   queue's own metabolism: it refuses discretionary work when the
                   backlog grows so the substrate cannot invent work faster than
                   it can metabolise it.
  2. AWAIT jobs  — submit a coroutine and await THIS result (a future), or come
                   back and collect it later. What the agent factory needs.
  3. SCHEDULED   — recurring interval jobs (e.g. periodic maintenance/learning)
     jobs           and one-shot timed jobs. Nothing schedules timed work on its
                   own; it registers here.

GOVERNANCE IS NOT HERE. Governance is a blanket authority over the whole self —
internal affairs over the sheriff's office — not a call reached up into from
inside a sub-component. The old queue embedded a bulk-task-creation governance
trigger; that has been removed. What stays is admission control, which is about
the QUEUE'S capacity, not about whether an action is permitted — a different
question, owned above.
"""

import asyncio
import inspect
import logging
import time
from enum import Enum
from typing import Dict, Any, Optional, List, Tuple, Callable, Awaitable
from datetime import datetime, timedelta
from asyncio import PriorityQueue
from dataclasses import dataclass, field

from .shared_types import Task, TaskStatus, Priority, TaskSource, TaskType

logger = logging.getLogger(__name__)


# A job's time budget, owned by the queue authority (see `timeout_for`). The
# formula and two of its three factors live here:
#   * TASK TYPE base — how long that kind of work reasonably takes (below);
#   * SEVERITY — important/urgent work gets more room (below).
# The third factor, REASONING difficulty, is NOT declared here: it is the
# reasoning authority's MEASURED signal (NeuralSymbolicBridge.reasoning_difficulty),
# which the queue reads. The queue owns the algorithm; the reasoning authority
# owns how hard the thinking is. Keyed by TaskType/Priority value; unknown ->
# default.
_TASK_TYPE_BASE_S: Dict[str, float] = {
    "communication": 60.0,
    "research": 120.0, "validation": 180.0, "analysis": 180.0, "synthesis": 180.0,
    "planning": 300.0,
    "execution": 600.0, "learning": 600.0, "optimization": 600.0,
    "security_remediation": 600.0,
    "self_improvement": 1800.0,
}
_DEFAULT_TASK_BASE_S = 300.0

_SEVERITY_FACTOR: Dict[str, float] = {
    "critical": 1.5, "high": 1.25, "medium": 1.0, "low": 0.75,
}
_DEFAULT_SEVERITY_FACTOR = 1.0


class TaskPriority(Enum):
    """Heap-key priority (int-valued)."""
    CRITICAL = 4
    HIGH = 3
    MEDIUM = 2
    LOW = 1


@dataclass
class QueuedTask:
    """A work job on the queue, with its lifecycle and timing."""
    task: Task
    priority: TaskPriority
    added_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    execution_duration: float = 0.0
    times_requeued: int = 0
    status: TaskStatus = TaskStatus.PENDING
    error_message: Optional[str] = None
    wait_time: float = 0.0
    retry_count: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            'task_id': self.task.id,
            'task_type': self.task.type.value,
            'task_description': self.task.description,
            'priority': self.priority.value,
            'status': self.status.value,
            'added_at': self.added_at.isoformat(),
            'started_at': self.started_at.isoformat() if self.started_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
            'wait_time': self.wait_time,
            'times_requeued': self.times_requeued,
            'retry_count': self.retry_count,
            'error_message': self.error_message,
        }


@dataclass
class _PoolStats:
    total_submitted: int = 0
    total_completed: int = 0
    total_failed: int = 0
    total_timeout: int = 0
    active: int = 0
    peak_active: int = 0
    total_wait_time_sec: float = 0.0
    total_execution_time_sec: float = 0.0


@dataclass
class _ScheduledJob:
    """A recurring or one-shot job the authority owns the cadence of."""
    name: str
    call: Callable[[], Awaitable[Any]]
    #: Recurring: seconds between runs. One-shot: None.
    interval_s: Optional[float]
    #: Next monotonic time this is due.
    next_due: float
    recurring: bool
    priority: str = "medium"
    last_run: Optional[float] = None
    runs: int = 0
    errors: int = 0
    last_error: Optional[str] = None


class QueueAuthority:
    """One authority for the substrate's queued, awaited, and scheduled work."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = {
            'max_queue_size': 1000,
            'max_retries': 1,
            'max_parallel': 5,
            'job_timeout_seconds': 300.0,
            **(config or {}),
        }

        # ── WORK QUEUE ──────────────────────────────────────────────────────
        self.queue: PriorityQueue = PriorityQueue()
        self.tasks_by_id: Dict[str, QueuedTask] = {}
        self.total_tasks_added = 0
        self._sequence = 0
        self.lock = asyncio.Lock()
        self.metrics: Dict[str, int] = {
            'tasks_completed': 0, 'tasks_failed': 0,
            'tasks_requeued': 0, 'tasks_deferred': 0,
        }

        # Admission control (the queue's own metabolism — NOT governance).
        self.soft_limit = int(self.config.get('soft_limit', 25))
        self.hard_limit = int(self.config.get('hard_limit', 60))
        # Work that must never be refused, whatever the backlog. API/MANUAL are
        # user-directed; SYSTEM covers error-handler fixes; SECURITY_AUDIT covers
        # remediation.
        self.NON_DISCRETIONARY_SOURCES = {
            TaskSource.API, TaskSource.MANUAL,
            TaskSource.SECURITY_AUDIT, TaskSource.SYSTEM,
        }
        self.NON_DISCRETIONARY_TYPES = {TaskType.SECURITY_REMEDIATION}

        # ── EXECUTION POOL (folded in) ──────────────────────────────────────
        # TWO budgets, deliberately separate. WORK jobs (the substrate's acting
        # tasks) run under `max_parallel` — the acting cap. AWAIT/SCHEDULED jobs
        # (spawned agents, periodic maintenance/learning) run under a SEPARATE
        # background budget, so background work can never steal an acting slot
        # (the starvation the one-tier-per-cycle rule used to guard against).
        self.max_parallel = int(self.config['max_parallel'])
        self.bg_max_parallel = int(self.config.get('bg_max_parallel', 8))
        self._semaphore = asyncio.Semaphore(self.max_parallel)
        self._bg_semaphore = asyncio.Semaphore(self.bg_max_parallel)
        self._pool_stats = _PoolStats()
        self._pool_lock = asyncio.Lock()
        #: The reasoning authority, consulted (lazily) for the MEASURED
        #: reasoning-difficulty factor in `timeout_for`. The queue owns the
        #: timeout formula; the reasoning authority owns how hard the thinking is.
        self._reasoning: Any = None

        # PER-JOB TIMEOUT is the AUTHORITY'S to decide, and it depends on the job
        # — not a single flat number. How long a job may run is a scheduling
        # question (this authority's), computed from the task's base budget, how
        # hard the reasoning is, and a per-job difficulty. `timeout_for` combines
        # them; `_TIMEOUT_MIN/MAX` bound the result so no computation runs away.
        self._TIMEOUT_MIN = float(self.config.get('timeout_min_s', 30.0))
        self._TIMEOUT_MAX = float(self.config.get('timeout_max_s', 7200.0))

        # ── AWAIT JOBS ──────────────────────────────────────────────────────
        #: job_id -> the running asyncio task, until awaited/collected.
        self._await_jobs: Dict[str, asyncio.Task] = {}
        self._await_meta: Dict[str, Dict[str, Any]] = {}
        #: Metrics the health monitor reads (see get_statistics). Every count is
        #: real: submitted on submit, completed/failed when the job actually ends,
        #: delivered/delivery_failed for push handlers. No optimistic increments.
        self._await_metrics: Dict[str, int] = {
            "submitted": 0, "completed": 0, "failed": 0,
            "delivered": 0, "delivery_failed": 0, "cancelled": 0,
        }

        # ── SCHEDULER ───────────────────────────────────────────────────────
        self._scheduled: Dict[str, _ScheduledJob] = {}
        self._scheduler_task: Optional[asyncio.Task] = None
        self._scheduler_tick_s = float(self.config.get('scheduler_tick_s', 1.0))
        self._running = False
        #: Real counters — a fire is counted when the loop actually dispatches a
        #: due job; an error is counted when that job's coroutine raised. Never
        #: incremented optimistically, so the health monitor reads the truth.
        self._scheduler_metrics = {"fired": 0, "errors": 0}

        # ── PERSISTENCE ─────────────────────────────────────────────────────
        # Accepted-but-unfinished work must survive a restart. Every lifecycle
        # mutation mirrors to `unified.task_queue`; boot rehydrates what was
        # owed. A write failure is logged + counted, never fatal to the live
        # queue (durability degrades VISIBLY, it does not fake success).
        self._persist_enabled = bool(self.config.get('persist', True))
        self._persistence: Any = None
        self._restoring = False
        self._persist_metrics = {"writes": 0, "errors": 0,
                                 "restored": 0, "restarted": 0}

    # ══════════════════════════════════════════════════════════════════════
    # WORK QUEUE — admission, add, pull, lifecycle
    # ══════════════════════════════════════════════════════════════════════

    def pressure(self) -> str:
        """Backlog pressure: 'nominal' | 'soft' | 'hard'."""
        depth = self.queue.qsize()
        if depth >= self.hard_limit:
            return "hard"
        if depth >= self.soft_limit:
            return "soft"
        return "nominal"

    def _is_discretionary(self, task: Task, priority: Priority) -> bool:
        if getattr(task, "source", None) in self.NON_DISCRETIONARY_SOURCES:
            return False
        if getattr(task, "type", None) in self.NON_DISCRETIONARY_TYPES:
            return False
        return priority not in (Priority.CRITICAL, Priority.HIGH)

    def admits(self, task: Task, priority: Priority = Priority.MEDIUM) -> Tuple[bool, str]:
        """Whether the queue can take this now, given the backlog. Capacity, not
        permission: permission is governance's, decided above the queue."""
        level = self.pressure()
        if level == "nominal":
            return True, "nominal"
        discretionary = self._is_discretionary(task, priority)
        if level == "soft":
            if discretionary:
                return False, (f"soft limit ({self.queue.qsize()}/{self.soft_limit}): "
                               "discretionary work deferred")
            return True, "soft: obligation admitted"
        # hard
        if discretionary or priority not in (Priority.CRITICAL, Priority.HIGH):
            if getattr(task, "source", None) not in self.NON_DISCRETIONARY_SOURCES:
                return False, (f"hard limit ({self.queue.qsize()}/{self.hard_limit}): "
                               "only safety, remediation, user-directed and critical admitted")
        return True, "hard: obligation admitted"

    async def add_task(self, task: Task, priority: Priority = Priority.MEDIUM) -> bool:
        """Push a work job. Returns False if admission (backpressure) refused it
        or the queue is at capacity. No governance here — that is a blanket
        authority applied where the substrate DECIDES to create work."""
        admitted, why = self.admits(task, priority)
        if not admitted:
            self.metrics['tasks_deferred'] += 1
            logger.info("[BACKPRESSURE] refused %s (%s/%s): %s", task.id,
                        getattr(task.type, 'value', '?'),
                        getattr(task.source, 'value', '?'), why)
            return False
        if self.queue.qsize() >= self.config['max_queue_size']:
            logger.warning("queue at capacity; refusing %s", task.id)
            return False

        tp = self._priority_to_task_priority(priority)
        queued = QueuedTask(task=task, priority=tp, added_at=datetime.now())
        async with self.lock:
            self._sequence += 1
            await self.queue.put((-tp.value, self._sequence, queued))
            self.tasks_by_id[task.id] = queued
            self.total_tasks_added += 1
        await self._persist_queued(queued)
        logger.info("queued %s (priority=%s, depth=%d)", task.id, tp.value, self.queue.qsize())
        return True

    def try_get_task(self) -> Optional[QueuedTask]:
        """Non-blocking pull; None if empty."""
        try:
            _, _, queued = self.queue.get_nowait()
        except asyncio.QueueEmpty:
            return None
        self._mark_started(queued)
        return queued

    async def get_next_task(self, timeout: float = None) -> Optional[QueuedTask]:
        """Pull the highest-priority work job; None on timeout/empty. This is how
        the WORKER (the coordinator) draws from the authority."""
        try:
            if timeout is not None:
                _, _, queued = await asyncio.wait_for(self.queue.get(), timeout=timeout)
            else:
                _, _, queued = await self.queue.get()
        except asyncio.TimeoutError:
            return None
        self._mark_started(queued)
        await self._persist_queued(queued)
        return queued

    @staticmethod
    def _mark_started(queued: QueuedTask) -> None:
        queued.status = TaskStatus.IN_PROGRESS
        queued.started_at = datetime.now()
        queued.wait_time = ((queued.started_at - queued.added_at).total_seconds()
                            if queued.added_at else 0.0)

    async def mark_completed(self, task_id: str, result: Dict[str, Any]) -> bool:
        queued = self.tasks_by_id.get(task_id)
        if queued is None:
            logger.warning("mark_completed: %s not found", task_id)
            return False
        async with self.lock:
            queued.status = TaskStatus.COMPLETED
            queued.completed_at = datetime.now()
            queued.task.result = result
            self.metrics['tasks_completed'] += 1
        await self._persist_queued(queued)
        return True

    async def mark_failed(self, task_id: str, error: str) -> bool:
        queued = self.tasks_by_id.get(task_id)
        if queued is None:
            logger.warning("mark_failed: %s not found", task_id)
            return False
        async with self.lock:
            queued.status = TaskStatus.FAILED
            queued.completed_at = datetime.now()
            queued.error_message = error
            self.metrics['tasks_failed'] += 1
        await self._persist_queued(queued)
        logger.warning("task %s failed: %s", task_id, error)
        return True

    async def requeue_task(self, task_id: str) -> bool:
        queued = self.tasks_by_id.get(task_id)
        if queued is None:
            return False
        if queued.retry_count >= self.config['max_retries']:
            logger.warning("task %s exceeded max retries", task_id)
            return False
        async with self.lock:
            queued.retry_count += 1
            queued.times_requeued += 1
            queued.status = TaskStatus.PENDING
            queued.started_at = None
            self._sequence += 1
            await self.queue.put((-queued.priority.value, self._sequence, queued))
            self.metrics['tasks_requeued'] += 1
        await self._persist_queued(queued)
        return True

    _ACTIVE_STATUSES = frozenset({
        TaskStatus.PLANNED, TaskStatus.PENDING, TaskStatus.IN_PROGRESS,
        TaskStatus.AWAITING_VERIFICATION, TaskStatus.BLOCKED,
    })

    def has_active_task(self, task_id: str) -> bool:
        """Already queued or in flight? Recurring producers re-derive the same
        deterministic id for a still-present condition; only ACTIVE states block
        re-queue (a FAILED/COMPLETED id may re-enter as genuinely new work)."""
        queued = self.tasks_by_id.get(task_id)
        return queued is not None and queued.status in self._ACTIVE_STATUSES

    def get_queue_length(self) -> int:
        return self.queue.qsize()

    async def get_task_status(self, task_id: str, include_details: bool = False,
                              include_result: bool = False) -> Dict[str, Any]:
        queued = self.tasks_by_id.get(task_id)
        if queued is None:
            return {"task_id": task_id, "status": "not_found",
                    "error": "Task not found"}
        out = {"task_id": task_id, "status": queued.status.value,
               "priority": queued.priority.value, "added_at": queued.added_at.isoformat()}
        if include_result:
            out["result"] = queued.task.result if queued.status == TaskStatus.COMPLETED else None
        return out

    async def get_failed_tasks(self, limit: int = 10) -> List[Task]:
        """Recently failed work jobs, most recent first — context for the
        substrate's intrinsic goal formation (what went wrong lately)."""
        failed = [q.task for q in self.tasks_by_id.values()
                  if q.status == TaskStatus.FAILED and q.task is not None]
        failed.sort(key=lambda t: getattr(t, 'completed_at', None) or datetime.min,
                    reverse=True)
        return failed[:limit]

    def get_metrics(self) -> Dict[str, Any]:
        return {
            'total_tasks_added': self.total_tasks_added,
            'current_queue_size': self.queue.qsize(),
            **self.metrics,
        }

    def _priority_to_task_priority(self, priority: Priority) -> TaskPriority:
        mapping = {
            Priority.CRITICAL: TaskPriority.CRITICAL, Priority.HIGH: TaskPriority.HIGH,
            Priority.MEDIUM: TaskPriority.MEDIUM, Priority.LOW: TaskPriority.LOW,
        }
        if priority in mapping:
            return mapping[priority]
        name = getattr(priority, "name", None)
        if name and name in TaskPriority.__members__:
            return TaskPriority[name]
        logger.warning("unmappable priority %r; defaulting MEDIUM", priority)
        return TaskPriority.MEDIUM

    # ══════════════════════════════════════════════════════════════════════
    # PERSISTENCE — the durable backing (unified.task_queue)
    # ══════════════════════════════════════════════════════════════════════

    def _persistence_or_none(self):
        """The lazy persistence store, or None when persistence is disabled.
        Lazy because the authority singleton is built before the DB is up."""
        if not self._persist_enabled:
            return None
        if self._persistence is None:
            from .queue_persistence import QueuePersistence
            self._persistence = QueuePersistence()
        return self._persistence

    @staticmethod
    def _queued_meta(queued: "QueuedTask") -> Dict[str, Any]:
        """The QueuedTask timing/lifecycle fields, as a JSON-native dict, so a
        rehydrated job keeps its wait/retry history rather than resetting."""
        return {
            "added_at": queued.added_at.isoformat() if queued.added_at else None,
            "started_at": queued.started_at.isoformat() if queued.started_at else None,
            "completed_at": queued.completed_at.isoformat() if queued.completed_at else None,
            "retry_count": queued.retry_count,
            "times_requeued": queued.times_requeued,
            "error_message": queued.error_message,
            "wait_time": queued.wait_time,
            "metadata": queued.metadata,
        }

    async def _persist_queued(self, queued: "QueuedTask") -> None:
        """Mirror one work job's CURRENT full state to the durable row. Non-fatal
        by contract: a DB error is logged with the task id and counted, and the
        in-memory queue is untouched — the substrate keeps working, and the
        durability gap is visible in `persist_errors`, not hidden."""
        p = self._persistence_or_none()
        if p is None or self._restoring:
            return
        try:
            await p.upsert(
                task=queued.task,
                status=queued.status.value,
                priority=queued.priority.value,
                result=queued.task.result,
                error=queued.error_message,
                queued_meta=self._queued_meta(queued),
            )
            self._persist_metrics["writes"] += 1
        except Exception as e:
            self._persist_metrics["errors"] += 1
            logger.error("queue persist failed for %s (%s): %s",
                         queued.task.id, queued.status.value, e)

    async def restore_pending(self) -> Dict[str, int]:
        """Rehydrate accepted-but-unfinished work from the durable store on boot.

        PENDING/PLANNED/BLOCKED/AWAITING_VERIFICATION jobs re-enter the queue as
        they were. IN_PROGRESS jobs were interrupted mid-run by the restart —
        they are reset to PENDING and re-queued (restart the interrupted work),
        and their durable row is corrected to PENDING so a second crash can't
        double-count them. Terminal jobs stay as history and are not restored.
        Idempotent: re-running finds nothing new because restored rows are no
        longer IN_PROGRESS."""
        p = self._persistence_or_none()
        if p is None:
            return {"restored": 0, "restarted": 0}
        self._restoring = True
        restored = restarted = 0
        try:
            rows = await p.load_restorable()
            for r in rows:
                task = r["task"]
                interrupted = (r["status"] == TaskStatus.IN_PROGRESS.value)
                if interrupted:
                    task.status = TaskStatus.PENDING
                # add_task skips its own persist while _restoring is set (the row
                # already exists); admission still applies.
                accepted = await self.add_task(task, priority=task.priority)
                if not accepted:
                    logger.warning("restore: %s not re-admitted (backpressure)", task.id)
                    continue
                restored += 1
                if interrupted:
                    restarted += 1
                    # Correct the durable row so it reflects the re-queue.
                    await p.update_status(task.id, TaskStatus.PENDING.value)
            self._persist_metrics["restored"] = restored
            self._persist_metrics["restarted"] = restarted
            logger.info("queue restore: %d rehydrated (%d interrupted -> restarted)",
                        restored, restarted)
        except Exception as e:
            logger.error("queue restore failed: %s", e)
        finally:
            self._restoring = False
        return {"restored": restored, "restarted": restarted}

    async def prune_history(self, keep_last: int = 500) -> int:
        """Bound the durable history (terminal rows). Delegates to the store."""
        p = self._persistence_or_none()
        if p is None:
            return 0
        try:
            return await p.prune_terminal(keep_last=keep_last)
        except Exception as e:
            logger.error("queue history prune failed: %s", e)
            return 0

    # ══════════════════════════════════════════════════════════════════════
    # EXECUTION POOL (folded in) — concurrency-limited running
    # ══════════════════════════════════════════════════════════════════════

    def _reasoning_difficulty(self, reasoning_type: Any) -> float:
        """The reasoning-difficulty factor — the reasoning authority's MEASURED
        signal (B), not a queue-local table. Sourced lazily; if the reasoning
        authority is unavailable, a neutral 1.0 (never a fabricated number)."""
        if reasoning_type is None:
            return 1.0
        try:
            if self._reasoning is None:
                from core.reasoning.neural_bridge import get_neural_bridge
                self._reasoning = get_neural_bridge()
            return float(self._reasoning.reasoning_difficulty(reasoning_type))
        except Exception:
            return 1.0

    def timeout_for(self, *, reasoning_type: Any = None, task_type: Any = None,
                    severity: Any = None, difficulty: float = 1.0) -> float:
        """This job's time budget, in seconds — the AUTHORITY'S formula:

            base(task_type) × reasoning_difficulty(reasoning_type)
                            × severity(priority) × difficulty        (clamped)

        base and severity are the queue's; reasoning_difficulty is the reasoning
        authority's MEASURED signal (the queue asks for it). A research task with
        simple reasoning finishes fast; a critical self-improvement task doing
        hard causal reasoning gets far longer. No flat number lives here.
        """
        base = _TASK_TYPE_BASE_S.get(
            str(getattr(task_type, "value", task_type) or "").strip().lower(),
            _DEFAULT_TASK_BASE_S)
        reasoning = self._reasoning_difficulty(reasoning_type)
        sev = _SEVERITY_FACTOR.get(
            str(getattr(severity, "value", severity) or "").strip().lower(),
            _DEFAULT_SEVERITY_FACTOR)
        budget = base * reasoning * sev * max(0.1, float(difficulty or 1.0))
        return max(self._TIMEOUT_MIN, min(self._TIMEOUT_MAX, budget))

    async def execute(self, job_id: str, func: Callable[..., Awaitable[Any]],
                      *args, background: bool = False,
                      timeout: Optional[float] = None,
                      reasoning_type: Any = None, task_type: Any = None,
                      severity: Any = None, difficulty: float = 1.0, **kwargs) -> Any:
        """Run `func` under a concurrency limit + a per-job timeout the AUTHORITY
        decides. `background=False` (work jobs) uses the acting-cap budget;
        `background=True` (await/scheduled) uses the separate background budget so
        it can't steal an acting slot. `timeout` may be passed explicitly, else it
        is computed from reasoning/task/severity/difficulty via `timeout_for`. The
        one place concurrent execution is bounded — no private pools."""
        semaphore = self._bg_semaphore if background else self._semaphore
        job_timeout = timeout if timeout is not None else self.timeout_for(
            reasoning_type=reasoning_type, task_type=task_type,
            severity=severity, difficulty=difficulty)
        wait_start = time.time()
        async with semaphore:
            wait = time.time() - wait_start
            async with self._pool_lock:
                self._pool_stats.total_submitted += 1
                self._pool_stats.active += 1
                self._pool_stats.peak_active = max(self._pool_stats.peak_active,
                                                   self._pool_stats.active)
                self._pool_stats.total_wait_time_sec += wait
            exec_start = time.time()
            try:
                # Accept both coroutine functions and plain callables — a
                # scheduled tier or job may be sync (e.g. a cheap prune). Only an
                # awaitable goes through wait_for (the timeout applies to async
                # work); a sync callable has already run by the time it returns.
                call_result = func(*args, **kwargs)
                if inspect.isawaitable(call_result):
                    result = await asyncio.wait_for(call_result, timeout=job_timeout)
                else:
                    result = call_result
                async with self._pool_lock:
                    self._pool_stats.total_completed += 1
                    self._pool_stats.active -= 1
                    self._pool_stats.total_execution_time_sec += time.time() - exec_start
                return result
            except asyncio.TimeoutError:
                async with self._pool_lock:
                    self._pool_stats.total_timeout += 1
                    self._pool_stats.active -= 1
                logger.error("job %s timed out after %.0fs", job_id, job_timeout)
                raise
            except Exception:
                async with self._pool_lock:
                    self._pool_stats.total_failed += 1
                    self._pool_stats.active -= 1
                raise

    async def execute_batch(
        self, jobs: List[tuple]
    ) -> List[tuple]:
        """Run many (job_id, func, args, kwargs) concurrently on this loop,
        bounded by the semaphore. Returns (job_id, ok, result_or_exc) in order."""
        async def _one(job_id, func, args, kwargs):
            try:
                return (job_id, True, await self.execute(job_id, func, *args, **kwargs))
            except Exception as exc:
                return (job_id, False, exc)
        return list(await asyncio.gather(*[
            _one(jid, f, a, k) for jid, f, a, k in jobs]))

    def pool_stats(self) -> Dict[str, Any]:
        s = self._pool_stats
        return {
            "max_parallel": self.max_parallel, "active": s.active,
            "peak_active": s.peak_active, "total_submitted": s.total_submitted,
            "total_completed": s.total_completed, "total_failed": s.total_failed,
            "total_timeout": s.total_timeout,
            "avg_wait_time_sec": (s.total_wait_time_sec / s.total_submitted
                                  if s.total_submitted else 0.0),
            "avg_execution_time_sec": (s.total_execution_time_sec / s.total_completed
                                       if s.total_completed else 0.0),
        }

    # ══════════════════════════════════════════════════════════════════════
    # AWAIT JOBS — submit and await THIS result (or collect later)
    # ══════════════════════════════════════════════════════════════════════

    def submit(self, coro_factory: Callable[[], Awaitable[Any]], *,
               name: str = "", job_id: Optional[str] = None,
               on_complete: Optional[Callable[[Dict[str, Any]], Any]] = None) -> str:
        """Submit a coroutine to run (through the pool, on the BACKGROUND budget)
        and return a job_id.

        TWO ways the result gets back to whoever wanted it — pick one:
          * PULL — no `on_complete`: the owner `await_result(id)`s it, or
            `collect_ready()`s it later. The result stays until taken.
          * PUSH — `on_complete(outcome)`: when the job ends, the authority
            hands the outcome to that handler and RETIRES the job. This is how a
            result is passed back to the substrate without it polling. The
            handler may be sync or async; if it raises, that is logged and
            counted (delivery_failed) — never swallowed into a false success.
        `outcome` is always {job_id, name, result, error}: `error` set means the
        job failed (honest — never reported as a result).
        """
        import uuid
        jid = job_id or f"job_{uuid.uuid4().hex[:12]}"
        self._await_metrics["submitted"] += 1

        if on_complete is None:
            task = asyncio.ensure_future(self.execute(jid, coro_factory, background=True))
        else:
            async def _deliver():
                outcome = {"job_id": jid, "name": name, "result": None, "error": None}
                try:
                    outcome["result"] = await self.execute(jid, coro_factory, background=True)
                    self._await_metrics["completed"] += 1
                except Exception as e:
                    outcome["error"] = str(e)
                    self._await_metrics["failed"] += 1
                    logger.error("await-job %s (%s) failed: %s", jid, name, e)
                try:
                    r = on_complete(outcome)
                    if asyncio.iscoroutine(r):
                        await r
                    self._await_metrics["delivered"] += 1
                except Exception as e:
                    self._await_metrics["delivery_failed"] += 1
                    logger.error("await-job %s completion handler raised: %s", jid, e)
                finally:
                    self._await_jobs.pop(jid, None)
                    self._await_meta.pop(jid, None)
                return outcome
            task = asyncio.ensure_future(_deliver())

        self._await_jobs[jid] = task
        self._await_meta[jid] = {"name": name, "submitted_at": datetime.now(),
                                 "push": on_complete is not None}
        return jid

    async def await_result(self, job_id: str) -> Dict[str, Any]:
        """Block until this PULL job returns; hand back {result} or {error}
        (honest — a failure is never returned as a result). Removes it. An
        unknown id is reported as such, not faked."""
        task = self._await_jobs.get(job_id)
        if task is None:
            return {"job_id": job_id, "name": None, "result": None,
                    "error": "unknown job id (never submitted, already taken, "
                             "or push-delivered)"}
        meta = self._await_meta.get(job_id, {})
        try:
            result = await task
            self._await_metrics["completed"] += 1
            out = {"job_id": job_id, "name": meta.get("name"),
                   "result": result, "error": None}
        except Exception as e:
            self._await_metrics["failed"] += 1
            out = {"job_id": job_id, "name": meta.get("name"),
                   "result": None, "error": str(e)}
        self._await_jobs.pop(job_id, None)
        self._await_meta.pop(job_id, None)
        return out

    def collect_ready(self) -> List[Dict[str, Any]]:
        """Take every PULL job that has returned since the last collect, without
        blocking — so the worker can keep going and reconcile later. Push jobs
        (on_complete) never appear here; they were delivered + retired already."""
        ready: List[Dict[str, Any]] = []
        for jid in [j for j, t in self._await_jobs.items() if t.done()]:
            task = self._await_jobs.pop(jid)
            meta = self._await_meta.pop(jid, {})
            try:
                ready.append({"job_id": jid, "name": meta.get("name"),
                              "result": task.result(), "error": None})
                self._await_metrics["completed"] += 1
            except Exception as e:
                ready.append({"job_id": jid, "name": meta.get("name"),
                              "result": None, "error": str(e)})
                self._await_metrics["failed"] += 1
        return ready

    def await_pending(self) -> List[str]:
        return [j for j, t in self._await_jobs.items() if not t.done()]

    def cancel(self, job_id: str) -> bool:
        """Cancel an await-job and retire it. Returns False for an unknown id
        (never faked). A job already finished is retired without a cancel; one
        still running is cancelled."""
        task = self._await_jobs.pop(job_id, None)
        self._await_meta.pop(job_id, None)
        if task is None:
            return False
        if not task.done():
            task.cancel()
        self._await_metrics["cancelled"] += 1
        logger.info("await-job %s cancelled", job_id)
        return True

    # ══════════════════════════════════════════════════════════════════════
    # SCHEDULER — recurring interval jobs + one-shot timed jobs
    # ══════════════════════════════════════════════════════════════════════

    def schedule_recurring(self, name: str, call: Callable[[], Awaitable[Any]],
                           interval_s: float, priority: str = "medium") -> None:
        """Register a recurring job the authority fires every `interval_s`. This
        is where the substrate's periodic work lives — nothing runs its own
        interval loop. Idempotent by name (re-registering updates the cadence)."""
        now = time.monotonic()
        self._scheduled[name] = _ScheduledJob(
            name=name, call=call, interval_s=interval_s,
            next_due=now + interval_s, recurring=True, priority=priority)
        logger.info("scheduled recurring job %s every %.0fs", name, interval_s)

    def schedule_after(self, call: Callable[[], Awaitable[Any]], delay_s: float,
                       name: str = "") -> str:
        """Register a one-shot job to run once after `delay_s`."""
        import uuid
        jid = name or f"once_{uuid.uuid4().hex[:8]}"
        self._scheduled[jid] = _ScheduledJob(
            name=jid, call=call, interval_s=None,
            next_due=time.monotonic() + delay_s, recurring=False)
        return jid

    def unschedule(self, name: str) -> bool:
        """Remove a scheduled job. False for an unknown name (never faked)."""
        return self._scheduled.pop(name, None) is not None

    def reschedule(self, name: str, interval_s: float) -> bool:
        """Change a RECURRING job's cadence. The substrate can retune how often
        its periodic work runs without unregistering it. False if the name is
        unknown or the job is a one-shot (nothing to re-time)."""
        job = self._scheduled.get(name)
        if job is None or not job.recurring:
            return False
        job.interval_s = float(interval_s)
        job.next_due = time.monotonic() + float(interval_s)
        logger.info("rescheduled %s to every %.0fs", name, interval_s)
        return True

    def run_now(self, name: str) -> bool:
        """Make a scheduled job due on the NEXT tick — the substrate pulling its
        own periodic work forward (e.g. reflect BECAUSE something just failed,
        rather than waiting out the interval). This is the authority-owned form
        of the coordinator's old `_mark_reflection_due`. False if unknown."""
        job = self._scheduled.get(name)
        if job is None:
            return False
        job.next_due = time.monotonic()
        logger.info("scheduled job %s made due now", name)
        return True

    def scheduled_jobs(self) -> List[str]:
        return list(self._scheduled)

    def start(self) -> None:
        """Start the scheduler loop (idempotent). The authority now fires due
        jobs itself; no other component ticks a schedule."""
        self._running = True
        if self._scheduler_task is None or self._scheduler_task.done():
            self._scheduler_task = asyncio.ensure_future(self._scheduler_loop())
            logger.info("queue authority scheduler started")

    async def _fire_scheduled(self, job: _ScheduledJob) -> None:
        """Run one due scheduled job on the background budget and record its real
        outcome on the job itself. Wrapping the dispatch means a tier that raises
        is logged BY NAME and counted (no orphaned-task warning, no silent loss);
        a tier that succeeds bumps its run count. `execute` still owns the timeout
        and the pool counters — this only adds the per-tier truth."""
        try:
            await self.execute(f"scheduled:{job.name}", job.call, background=True)
            job.runs += 1
        except Exception as e:  # includes asyncio.TimeoutError from execute
            job.errors += 1
            job.last_error = f"{type(e).__name__}: {e}"
            self._scheduler_metrics["errors"] += 1
            logger.error("scheduled job %s failed: %s", job.name, job.last_error)

    async def _scheduler_loop(self) -> None:
        while self._running:
            try:
                await asyncio.sleep(self._scheduler_tick_s)
                now = time.monotonic()
                for job in list(self._scheduled.values()):
                    if now < job.next_due:
                        continue
                    # Fire on the BACKGROUND budget: a scheduled job is maintenance
                    # nobody awaits, so it must NOT enter the await-job map (which
                    # only holds results a caller will collect). Bounded by the bg
                    # semaphore; a slow one cannot stall the loop. Dispatched via
                    # the wrapper so its outcome is recorded, not orphaned.
                    asyncio.ensure_future(self._fire_scheduled(job))
                    self._scheduler_metrics["fired"] += 1
                    job.last_run = now
                    if job.recurring and job.interval_s:
                        job.next_due = now + job.interval_s
                    else:
                        self._scheduled.pop(job.name, None)  # one-shot done
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("scheduler loop error: %s", e)

    async def stop(self) -> None:
        self._running = False
        if self._scheduler_task:
            self._scheduler_task.cancel()
            try:
                await self._scheduler_task
            except (asyncio.CancelledError, Exception):
                pass
        for task in list(self._await_jobs.values()):
            if not task.done():
                task.cancel()
        self._await_jobs.clear()

    async def get_statistics(self) -> Dict[str, Any]:
        """FLAT scalar metrics for the health monitor.

        The probe records only int/float/bool/str values (nested dicts are
        dropped, health_monitor.py:1758), so everything here is a scalar and
        every counter is real — incremented when the thing actually happened,
        never optimistically. `pressure` is a string the probe keeps as-is.
        """
        p = self._pool_stats
        return {
            # work queue
            "queue_depth": self.queue.qsize(),
            "pressure": self.pressure(),
            "total_tasks_added": self.total_tasks_added,
            "tasks_completed": self.metrics["tasks_completed"],
            "tasks_failed": self.metrics["tasks_failed"],
            "tasks_requeued": self.metrics["tasks_requeued"],
            "tasks_deferred": self.metrics["tasks_deferred"],
            # execution pool (two budgets)
            "work_max_parallel": self.max_parallel,
            "bg_max_parallel": self.bg_max_parallel,
            "pool_active": p.active,
            "pool_peak_active": p.peak_active,
            "pool_total_submitted": p.total_submitted,
            "pool_total_completed": p.total_completed,
            "pool_total_failed": p.total_failed,
            "pool_total_timeout": p.total_timeout,
            # await jobs
            "await_submitted": self._await_metrics["submitted"],
            "await_completed": self._await_metrics["completed"],
            "await_failed": self._await_metrics["failed"],
            "await_delivered": self._await_metrics["delivered"],
            "await_delivery_failed": self._await_metrics["delivery_failed"],
            "await_cancelled": self._await_metrics["cancelled"],
            "await_pending": len(self.await_pending()),
            # scheduler
            "scheduled_jobs": len(self._scheduled),
            "scheduler_running": self._running,
            "scheduler_fired": self._scheduler_metrics["fired"],
            "scheduler_errors": self._scheduler_metrics["errors"],
            # persistence (durability of the backlog)
            "persist_enabled": self._persist_enabled,
            "persist_writes": self._persist_metrics["writes"],
            "persist_errors": self._persist_metrics["errors"],
            "persist_restored": self._persist_metrics["restored"],
            "persist_restarted": self._persist_metrics["restarted"],
        }

    def scheduled_job_status(self) -> List[Dict[str, Any]]:
        """Per-job diagnostics (name, cadence, runs, errors, last_error) — the
        substrate's window on what its periodic work is actually doing. Not a
        health scalar (the probe drops nested/list values); read on demand."""
        out: List[Dict[str, Any]] = []
        for job in self._scheduled.values():
            out.append({
                "name": job.name,
                "recurring": job.recurring,
                "interval_s": job.interval_s,
                "runs": job.runs,
                "errors": job.errors,
                "last_error": job.last_error,
            })
        return out


# Back-compat alias during migration: existing imports of `TaskQueue` keep
# working while call sites move to QueueAuthority.
TaskQueue = QueueAuthority


# ── singleton ─────────────────────────────────────────────────────────────
_queue_authority: Optional[QueueAuthority] = None


def get_queue_authority(config: Optional[Dict[str, Any]] = None) -> QueueAuthority:
    """The one queue authority for the process."""
    global _queue_authority
    if _queue_authority is None:
        _queue_authority = QueueAuthority(config)
    return _queue_authority
