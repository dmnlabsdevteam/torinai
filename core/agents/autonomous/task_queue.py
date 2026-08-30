#!/usr/bin/env python3
"""
Task Queue

Priority-based task queue management:
- Task prioritization (CRITICAL > HIGH > MEDIUM > LOW)
- Queue metrics tracking
- Task lifecycle management
"""

import asyncio
import logging
from enum import Enum
from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from asyncio import PriorityQueue

# Reuse shared types
from .shared_types import Task, TaskStatus, Priority, TaskSource, TaskType

logger = logging.getLogger(__name__)


class TaskPriority(Enum):
    """Task priority levels"""
    CRITICAL = 4
    HIGH = 3
    MEDIUM = 2
    LOW = 1


class QueueStatus(Enum):
    """Queue operational status"""
    READY = "ready"
    PAUSED = "paused"
    STOPPED = "stopped"
    ERROR = "error"
    FULL = "full"


class QueueMetrics(Enum):
    """Queue performance metrics"""
    TASKS_ADDED = "tasks_added"  # Total tasks added
    TASKS_COMPLETED = "tasks_completed"  # Total completed
    TASKS_FAILED = "tasks_failed"  # Total failed
    AVG_WAIT_TIME = "avg_wait_time"  # Average wait time
    AVG_EXECUTION_TIME = "avg_execution_time"  # Average execution
    QUEUE_LENGTH = "queue_length"  # Current queue size


@dataclass
class QueuedTask:
    """
    Queued task with priority and metadata
    """
    task: Task
    priority: TaskPriority
    added_at: datetime

    # Execution metadata
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    execution_duration: float = 0.0  # seconds

    # Queue position
    queue_position: int = 0  # Position when added
    times_requeued: int = 0  # How many times requeued

    # Status tracking
    status: TaskStatus = TaskStatus.PENDING
    error_message: Optional[str] = None

    # Metrics
    wait_time: float = 0.0  # Time waiting in queue (seconds)
    retry_count: int = 0  # Number of retries

    # Timestamps for tracking
    last_status_change: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
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
            'execution_duration': self.execution_duration,
            'queue_position': self.queue_position,
            'times_requeued': self.times_requeued,
            'retry_count': self.retry_count,
            'error_message': self.error_message
        }


class TaskQueue:
    """
    Priority-based async task queue

    Features:
    - Priority levels (CRITICAL, HIGH, MEDIUM, LOW)
    - Async task management (add/get/complete)
    - Queue metrics tracking (throughput, wait times)
    - Task lifecycle tracking
    - Configurable max queue size (prevents overflow)
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """`config` overrides the defaults below.

        `self.config` was read in four places -- including the admission
        soft/hard limits, which the comment there describes as tunable -- while
        __init__ took no argument, so there was no way to set any of them. A
        setting that cannot be set is documentation, not configuration.
        """
        self.queue = PriorityQueue()

        # Task tracking (task_id -> QueuedTask)
        self.queued_tasks: Dict[str, QueuedTask] = {
            TaskStatus.PENDING: [],
            TaskStatus.IN_PROGRESS: [],
            TaskStatus.COMPLETED: [],
            TaskStatus.FAILED: []
        }

        # Metrics tracking
        self.metrics: Dict[str, int] = {
            'tasks_completed': 0,
            'tasks_failed': 0,
            'tasks_requeued': 0,
            'tasks_deferred': 0
        }
        self.lock = asyncio.Lock()  # Thread safety lock

        # Configuration
        self.config = {
            'max_queue_size': 1000,
            'enable_metrics': True,
            'enable_requeue': True,
            'max_retries': 1,
            **(config or {}),
        }

        # === Internal state tracking ===
        # We maintain lists for each status (PENDING, IN_PROGRESS, etc)
        # This allows fast lookups and status changes
        self.tasks_by_status: Dict[TaskStatus, List[QueuedTask]] = {}
        self.tasks_by_id: Dict[str, QueuedTask] = {}
        self.total_tasks_added = 0  # Running count
        self.total_tasks_completed = 0  # Tasks that finished

        # Phase 5A: Bulk task detection
        self.autonomous_task_window: List[datetime] = []
        self.bulk_task_threshold = 20
        self.task_window_duration = timedelta(minutes=5)
        self.governance_triggered_count = 0
        self.governance_rejected_count = 0
        self.user_tasks_exempt_count = 0

        # Sequence number for queue tiebreaker
        self._sequence = 0

        # === ADMISSION CONTROL ===
        # Measured on the 2026-08-13 run: 27 tasks queued, 8 executed -- the
        # producer outran the consumer 3.4:1 and queue depth climbed
        # monotonically. That is not a slow drain, it diverges: the system
        # accumulates an ever-growing representation of work it cannot perform.
        #
        # Curiosity must not create work faster than the organism can
        # metabolise it, so discretionary production is gated on queue depth
        # while obligatory work is always admitted.
        self.soft_limit = int(self.config.get('soft_limit', 25))
        self.hard_limit = int(self.config.get('hard_limit', 60))

        # Work that must never be refused, whatever the backlog.
        # API/MANUAL are the user-directed sources (there is no TaskSource.USER);
        # SYSTEM covers error-handler fix tasks; SECURITY_AUDIT covers remediation.
        self.NON_DISCRETIONARY_SOURCES = {
            TaskSource.API, TaskSource.MANUAL,
            TaskSource.SECURITY_AUDIT, TaskSource.SYSTEM,
        }
        self.NON_DISCRETIONARY_TYPES = {
            TaskType.SECURITY_REMEDIATION,
        }

    # ------------------------------------------------------------------
    # Admission control
    # ------------------------------------------------------------------

    def pressure(self) -> str:
        """Current backlog pressure: 'nominal' | 'soft' | 'hard'."""
        depth = self.queue.qsize()
        if depth >= self.hard_limit:
            return "hard"
        if depth >= self.soft_limit:
            return "soft"
        return "nominal"

    def _is_discretionary(self, task: Task, priority: Priority) -> bool:
        """Discretionary = exploration/curiosity work the system chose to invent."""
        if getattr(task, "source", None) in self.NON_DISCRETIONARY_SOURCES:
            return False
        if getattr(task, "type", None) in self.NON_DISCRETIONARY_TYPES:
            return False
        if priority in (Priority.CRITICAL, Priority.HIGH):
            return False
        return True

    def admits(self, task: Task, priority: Priority = Priority.MEDIUM) -> Tuple[bool, str]:
        """Decide whether this task may be added, given current backlog.

        nominal : everything admitted
        soft    : discretionary work refused; obligations still admitted
        hard    : only safety / remediation / user-directed / critical admitted
        """
        level = self.pressure()
        if level == "nominal":
            return True, "nominal"

        discretionary = self._is_discretionary(task, priority)
        if level == "soft":
            if discretionary:
                return False, (
                    f"soft limit ({self.queue.qsize()}/{self.soft_limit}): "
                    "discretionary work deferred"
                )
            return True, "soft: obligation admitted"

        # hard
        if discretionary or priority not in (Priority.CRITICAL, Priority.HIGH):
            if getattr(task, "source", None) not in self.NON_DISCRETIONARY_SOURCES:
                return False, (
                    f"hard limit ({self.queue.qsize()}/{self.hard_limit}): "
                    "only safety, remediation, user-directed and critical work admitted"
                )
        return True, "hard: obligation admitted"

    async def add_task(self, task: Task, priority: Priority = Priority.MEDIUM) -> bool:
        """
        Add a task to the queue (priority-based)

        Args:
            task: Task to add (Task object)
            priority: Priority level (CRITICAL, HIGH, MEDIUM, LOW)

        Returns:
            bool: True if added successfully
                  False if queue full or governance rejected

        Phase 5A Governance:
            - User-defined tasks (API, MANUAL): Always allowed
            - Autonomous tasks: Trigger governance if 20+ tasks in 5-min window
            - Rejected tasks: NOT added to queue (fail-closed)
        """
        try:
            # ADMISSION CONTROL -- before any other work. A queue that accepts
            # faster than it drains converts autonomy into debt generation.
            admitted, why = self.admits(task, priority)
            if not admitted:
                self.metrics['tasks_deferred'] = self.metrics.get('tasks_deferred', 0) + 1
                logger.info(
                    f"[BACKPRESSURE] Refused task {task.id} "
                    f"({getattr(task.type, 'value', '?')}/{getattr(task.source, 'value', '?')}): {why}"
                )
                return False

            # Phase 5A: Check if user-defined task (exempt from governance)
            if task.source in [TaskSource.API, TaskSource.MANUAL]:
                self.user_tasks_exempt_count += 1
                logger.debug(f"User task {task.id} exempt from governance (source={task.source.value})")
                return await self._add_task_to_queue(task, priority)

            # Phase 5A: Track autonomous tasks
            if task.source == TaskSource.AUTONOMOUS:
                # Clean up old entries outside window
                cutoff_time = datetime.now() - self.task_window_duration
                self.autonomous_task_window = [
                    t for t in self.autonomous_task_window if t > cutoff_time
                ]

                # Add current task time
                self.autonomous_task_window.append(datetime.now())

                # Check if bulk threshold reached
                if len(self.autonomous_task_window) >= self.bulk_task_threshold:
                    # Trigger governance
                    governance_result = await self._trigger_bulk_task_governance(
                        task_count=len(self.autonomous_task_window)
                    )

                    if not governance_result["approved"]:
                        # Governance rejected - DO NOT queue task
                        logger.warning(
                            f"Bulk task creation rejected by governance: "
                            f"{governance_result['message']}"
                        )
                        return False

                    # Governance approved - update task
                    task.governance_approved = True
                    task.governance_action_id = governance_result["action_id"]

            # Delegate to internal add method
            return await self._add_task_to_queue(task, priority)

        except Exception as e:
            logger.error(f"Failed to add task {task.id}: {e}")
            return False

    async def _add_task_to_queue(self, task: Task, priority: Priority) -> bool:
        """Internal method to add task to queue (no governance checks)"""
        try:
            # Check queue size (prevent overflow)
            current_size = self.queue.qsize()

            if current_size >= self.config['max_queue_size']:
                logger.warning(
                    f"Queue at capacity: {current_size} tasks. "
                    f"Cannot add task {task.id} (priority={priority.value})"
                )
                return False

            # Add to queue
            task_priority = self._priority_to_task_priority(priority)

            # Create queued task wrapper
            queued_task = QueuedTask(
                task=task,
                priority=task_priority,
                added_at=datetime.now()
            )

            # Actually add to priority queue (with sequence tiebreaker).
            # self.lock was declared at :131 and never acquired. Dequeue is
            # already concurrency-safe (asyncio.PriorityQueue), but _sequence,
            # tasks_by_id and the counters are not -- a lost update here
            # corrupts ordering and metrics the moment there is more than one
            # producer/consumer.
            async with self.lock:
                self._sequence += 1
                await self.queue.put((-task_priority.value, self._sequence, queued_task))
                self.tasks_by_id[task.id] = queued_task
                self.total_tasks_added += 1

            # Log addition
            logger.info(
                f"Adding task {task.id} to queue "
                f"(priority={task_priority.value}, size={current_size+1})"
            )

            return True

        except Exception as e:
            logger.error(f"Failed to add task to queue {task.id}: {e}")
            return False

    async def _trigger_bulk_task_governance(self, task_count: int) -> Dict[str, Any]:
        """Trigger governance for bulk autonomous task creation"""
        from core.governance import get_unified_governance, ActionCategory

        try:
            # Use governance singleton
            governance = get_unified_governance()
            evaluation = await governance.evaluate_action(
                action_category=ActionCategory.TASK_CREATION,
                action_type="bulk_autonomous_task_creation",
                parameters={
                    "task_count": task_count,
                    "window_duration_seconds": self.task_window_duration.total_seconds(),
                    "threshold": self.bulk_task_threshold
                },
                context={
                    "component": "task_queue",
                    "tasks_in_window": len(self.autonomous_task_window)
                }
            )

            self.governance_triggered_count += 1

            approved = (
                evaluation.decision_tier.name not in ["CRITICAL", "IMPORTANT"]
                or evaluation.approved
            )

            if not approved:
                self.governance_rejected_count += 1

            return {
                "approved": approved,
                "trigger_id": evaluation.trigger_id,
                "action_id": evaluation.action_id,
                "message": f"Bulk task governance: {task_count} tasks"
            }

        except Exception as e:
            logger.error(f"Governance system error: {e}")
            # FAIL-CLOSED: Block on governance failure
            return {
                "approved": False,
                "trigger_id": "error",
                "action_id": "error",
                "message": f"Governance system error: {e}"
            }

    def get_queue_length(self) -> int:
        """Get current queue length"""
        return self.queue.qsize()

    def try_get_task(self) -> Optional['QueuedTask']:
        """
        Non-blocking get — returns None immediately if queue is empty.

        Uses get_nowait() so it never suspends and does not depend on
        asyncio.wait_for timeout behavior (which varies across Python versions).
        Use this for batch-drain loops where you want to consume as many
        ready tasks as possible without waiting.
        """
        try:
            _, _, queued_task = self.queue.get_nowait()
            queued_task.status = TaskStatus.IN_PROGRESS
            queued_task.started_at = datetime.now()
            if queued_task.added_at:
                queued_task.wait_time = (queued_task.started_at - queued_task.added_at).total_seconds()
            else:
                queued_task.wait_time = 0.0
            return queued_task
        except asyncio.QueueEmpty:
            return None

    async def get_next_task(self, timeout: float = None) -> Optional[QueuedTask]:
        """
        Get next task from queue (by priority)

        Args:
            timeout: Max wait time (seconds = None for blocking)

        Returns:
            QueuedTask if available, None if timeout/empty
        """
        try:
            # Get next task from priority queue (highest priority first)
            if timeout is not None:
                _, _, queued_task = await asyncio.wait_for(self.queue.get(), timeout=timeout)
            else:
                _, _, queued_task = await self.queue.get()

            # Update task status (PENDING → IN_PROGRESS)
            queued_task.status = TaskStatus.IN_PROGRESS
            queued_task.started_at = datetime.now()

            # Calculate actual wait (started - added)
            if queued_task.added_at:
                wait_time = (queued_task.started_at - queued_task.added_at).total_seconds()
                queued_task.wait_time = wait_time
            else:
                queued_task.wait_time = 0.0

            return queued_task

        except asyncio.TimeoutError:
            logger.debug(f"No tasks available within {timeout}s")
            return None

    async def mark_completed(self, task_id: str, result: Dict[str, Any]) -> bool:
        """Mark task as completed"""
        try:
            if task_id not in self.tasks_by_id:
                logger.warning(f"Task {task_id} not found in queue")
                return False

            async with self.lock:
                queued_task = self.tasks_by_id[task_id]
                queued_task.status = TaskStatus.COMPLETED
                queued_task.completed_at = datetime.now()
                queued_task.task.result = result

                self.metrics['tasks_completed'] += 1

            logger.info(f"Task {task_id} completed")
            return True

        except Exception as e:
            logger.error(f"Failed to mark task {task_id} completed: {e}")
            return False

    async def mark_failed(self, task_id: str, error: str) -> bool:
        """Mark task as failed"""
        try:
            if task_id not in self.tasks_by_id:
                logger.warning(f"Task {task_id} not found in queue")
                return False

            async with self.lock:
                queued_task = self.tasks_by_id[task_id]
                queued_task.status = TaskStatus.FAILED
                queued_task.completed_at = datetime.now()
                queued_task.error_message = error

            self.metrics['tasks_failed'] += 1

            logger.warning(f"Task {task_id} failed: {error}")
            return True

        except Exception as e:
            logger.error(f"Failed to mark task {task_id} failed: {e}")
            return False

    async def requeue_task(self, task_id: str) -> bool:
        """Requeue a task (move back to queue)"""
        try:
            if task_id not in self.tasks_by_id:
                logger.warning(f"Task {task_id} not found in queue")
                return False

            queued_task = self.tasks_by_id[task_id]

            if queued_task.retry_count >= self.config['max_retries']:
                logger.warning(
                    f"Task {task_id} exceeded max retries ({self.config['max_retries']})"
                )
                return False

            async with self.lock:
                queued_task.retry_count += 1
                queued_task.status = TaskStatus.PENDING
                queued_task.started_at = None
                queued_task.times_requeued += 1

                # Add back to queue with proper priority tuple structure
                self._sequence += 1
                await self.queue.put((-queued_task.priority.value, self._sequence, queued_task))
                self.total_tasks_added += 1

                self.metrics['tasks_requeued'] += 1

            logger.info(f"Task {task_id} requeued (retry {queued_task.retry_count}/{self.config['max_retries']})")
            return True

        except Exception as e:
            logger.error(f"Failed to requeue {task_id}: {e}")
            return False

    def get_all_tasks(self, status: TaskStatus) -> List[QueuedTask]:
        """Get all tasks by status"""
        return self.tasks_by_status.get(status, [])

    async def get_failed_tasks(self, limit: int = 10) -> List[Task]:
        """Get recently failed tasks for intrinsic goal context"""
        failed = [
            qt.task
            for qt in self.tasks_by_id.values()
            if qt.status == TaskStatus.FAILED and qt.task is not None
        ]
        # Most recent first
        failed.sort(key=lambda t: t.completed_at if hasattr(t, 'completed_at') and t.completed_at else datetime.min, reverse=True)
        return failed[:limit]

    # A task in one of these states is already going to be worked on. Re-queuing
    # it is pure duplication.
    _ACTIVE_STATUSES = frozenset({
        TaskStatus.PLANNED, TaskStatus.PENDING, TaskStatus.IN_PROGRESS,
        TaskStatus.AWAITING_VERIFICATION, TaskStatus.BLOCKED,
    })

    def has_active_task(self, task_id: str) -> bool:
        """Is a task with this id already queued or in flight?

        Recurring producers (the security audit runs every ~90s) re-derive the
        SAME deterministic id for a condition that is still present. Without this
        check, each cycle appended another copy: the queue grew 29 -> 35 in two
        seconds while three identical remediation tasks ran concurrently.

        Only ACTIVE states block re-queuing. A previously FAILED or COMPLETED
        task must be allowed to re-enter, because a condition that reappears
        after a failed attempt is genuinely new work.
        """
        qt = self.tasks_by_id.get(task_id)
        if qt is None:
            return False
        return getattr(qt, 'status', None) in self._ACTIVE_STATUSES

    def get_queue_size(self) -> int:
        """Get current queue size"""
        return self.queue.qsize() + sum(len(tasks) for tasks in self.tasks_by_status.values())

    async def get_task_status(
        self,
        task_id: str,
        include_details: bool = False,
        include_result: Optional[bool] = False
    ) -> Dict[str, Any]:
        """
        Get task status and optional details

        Args:
            task_id: Task ID to query
            include_details: Include full task details
            include_result: Include task result (if completed)

        Returns:
            Dict with status info, or error message
        """
        try:
            # Find task
            queued_task = self.tasks_by_id.get(task_id)

            # Add details
            if include_details:
                # Build detailed response (task context, metadata)
                if queued_task:
                    logger.debug(f"Returning detailed status for task {task_id}")
                    return {
                        "task_id": task_id,
                        "status": queued_task.status.value,
                        "priority": queued_task.priority.value,
                        "result": queued_task.task.result if include_result else None
                    }

                # Task not found, return minimal error
                logger.warning(f"Task {task_id} not found")
                return {
                    "task_id": task_id,
                    "status": "not_found",
                    "error": "Task not found in queue"
                }

            # Log status query
            logger.info(
                f"Task {task_id} status: {queued_task.status.value if queued_task else 'not_found'}"
            )

            if include_result and queued_task:
                # Return result if requested (only for completed tasks)
                if queued_task.status == TaskStatus.COMPLETED and queued_task.task.result:
                    logger.debug(f"Including result for completed task {task_id}")
                    return {
                        "task_id": task_id,
                        "status": queued_task.status.value,
                        "result": queued_task.task.result,
                        "completed_at": queued_task.completed_at.isoformat() if queued_task.completed_at else None
                    }

                # No result, just status
                logger.debug(f"No result available for task {task_id}")
                return {
                    "task_id": task_id,
                    "status": queued_task.status.value,
                    "result": None,
                    "error": "Task not completed"
                }

            # Return status only
            return {
                "task_id": task_id,
                "status": queued_task.status.value,
                "priority": queued_task.priority.value,
                "added_at": queued_task.added_at.isoformat()
            }

        except Exception as e:
            logger.error(f"Error getting task status {task_id}: {e}")
            return {
                "task_id": task_id,
                "status": "error",
                "error": str(e)
            }

    async def _validate_task(
        self,
        task: Task
    ) -> bool:
        """
        Validate task before adding to queue

        Args:
            task: Task to validate
            priority: Priority level

        Returns:
            bool: True if valid, False otherwise
        """
        try:
            # Check task ID exists
            task_id = task.id or ""  # Default empty string
            task_type = task.type.value if task.type else ""
            task_desc = task.description or ""

            # Validate task ID
            if not task_id or task_id == "":
                logger.error(
                    f"Invalid task: missing task_id, got {task_id}"
                )
                return False

            # Validate task type
            if not task_type or task_type == "":
                logger.warning(f"Task {task_id} missing type")
                return False

            # Validate task description (optional but recommended)
            if not task_desc or task_desc == "":
                logger.debug(f"Task {task_id} has no description")
                return False

            return True

        except Exception as e:
            logger.error(f"Task validation error: {e}")
            return False

    def get_metrics(self) -> Dict[str, Any]:
        """Get queue performance metrics"""
        return {
            'total_tasks_added': self.total_tasks_added,
            'total_tasks_completed': self.total_tasks_completed,
            'current_queue_size': self.get_queue_size(),
            'tasks_by_status': {
                status.value: len(tasks)
                for status, tasks in self.tasks_by_status.items()
            }
        }

    def _priority_to_task_priority(self, priority: Priority) -> TaskPriority:
        """Convert Priority enum to TaskPriority enum.

        Two enums name the same concept: shared_types.Priority (string-valued,
        carried on Task) and TaskPriority (int-valued, used as the heap key).
        Anything that is not a `Priority` member missed the mapping and came
        back as MEDIUM *silently* -- so a caller passing the other enum got its
        priority erased with no error and no log. Normalise by NAME so either
        enum works, and say so out loud when a priority cannot be interpreted
        rather than quietly inventing MEDIUM.
        """
        mapping = {
            Priority.CRITICAL: TaskPriority.CRITICAL,
            Priority.HIGH: TaskPriority.HIGH,
            Priority.MEDIUM: TaskPriority.MEDIUM,
            Priority.LOW: TaskPriority.LOW
        }
        if priority in mapping:
            return mapping[priority]
        name = getattr(priority, "name", None)
        if name and name in TaskPriority.__members__:
            return TaskPriority[name]
        logger.warning(
            f"Unmappable task priority {priority!r} ({type(priority).__name__}) "
            f"-- defaulting to MEDIUM; the caller's intended priority is being lost"
        )
        return TaskPriority.MEDIUM
