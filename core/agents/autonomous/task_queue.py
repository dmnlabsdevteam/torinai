#!/usr/bin/env python3
"""Compatibility shim — the task queue is now the QUEUE AUTHORITY.

`queue_authority.py` (`QueueAuthority`) is the one authority for the substrate's
work jobs, await jobs, and scheduling. This module re-exports it under the old
names so existing imports keep working during migration; new code should import
from `queue_authority` directly. This shim will be removed once every call site
has moved and the coordinator draws from the singleton authority.
"""

from .queue_authority import (  # noqa: F401
    QueueAuthority,
    TaskQueue,          # alias of QueueAuthority
    QueuedTask,
    TaskPriority,
    get_queue_authority,
)
from .shared_types import Task  # re-exported here before; kept for back-compat

__all__ = [
    "QueueAuthority", "TaskQueue", "QueuedTask", "TaskPriority",
    "get_queue_authority", "Task",
]
