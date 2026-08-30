#!/usr/bin/env python3
"""Every ERROR and CRITICAL in the process, onto the canonical failure record.

There are 1,113 `except` blocks across 295 files in `core/` that log at
error, critical or exception level. Each one is the code itself declaring that
what just happened was a failure -- and each one was a line in a log file that
no subsystem could query.

Wiring them by hand means 1,113 edits across 20 folders, and the ones that get
missed are invisible: a site nobody edited looks exactly like a site with
nothing to report. So the capture happens where every one of them already
converges -- the logging system.

    THE CODE'S OWN SEVERITY IS THE CRITERION. If a module chose to log
    something at ERROR, that module is asserting a failure. This does not
    second-guess it, and it cannot miss a site.

Explicit `failure_record.report(...)` calls remain the better way to record a
failure, because they carry structured metadata a log message cannot. This is
the floor beneath them, not a replacement: a site with both produces one row
from the explicit call and a duplicate-suppressed one from here.

WHAT THIS DELIBERATELY DOES NOT DO. It does not block the caller. Logging is
called from inside failure paths, often while holding locks, and a handler
that awaited a database write would turn every error into a stall. Records go
onto a bounded queue and a background task drains it; when the queue is full
or no event loop is running, the record is DROPPED and counted, and the count
is readable -- silent loss and no loss must not look the same.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from collections import deque
from typing import Any, Deque, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

#: Loggers whose own errors must never be captured, or reporting a failure
#: that failed would report itself failing, forever.
_EXCLUDED_PREFIXES = (
    "core.observability.failure_record",
    "core.observability.failure_capture",
    "asyncio",
    "aiohttp",
    "urllib3",
)

#: How many pending records may wait to be written. Past this, the system is
#: producing errors faster than they can be recorded and the newest are
#: dropped -- a bound is what keeps a failure storm from becoming a memory leak.
MAX_QUEUE = 2000

#: The same message from the same logger inside this window is one failure,
#: not many. A retry loop logging the same error 200 times is one fault.
DEDUPE_WINDOW_SEC = 60.0

#: Log level -> canonical severity. WARNING is not captured: the codebase uses
#: it for conditions it has already decided to continue through.
_SEVERITY = {logging.ERROR: "high", logging.CRITICAL: "critical"}


def _component_of(logger_name: str) -> str:
    """The component a logger belongs to.

    `core.agents.autonomous.autonomous_coordinator` -> `agents.autonomous_coordinator`,
    matching the shape the component registry and `component_health` use, so a
    failure captured here lines up with the component it is about.
    """
    name = str(logger_name or "unknown")
    parts = [p for p in name.split(".") if p]
    if parts and parts[0] == "core":
        parts = parts[1:]
    if not parts:
        return "unknown"
    if len(parts) == 1:
        return parts[0]
    return f"{parts[0]}.{parts[-1]}"


class FailureCaptureHandler(logging.Handler):
    """Turns ERROR/CRITICAL log records into canonical failure rows."""

    def __init__(self) -> None:
        super().__init__(level=logging.ERROR)
        self._queue: Deque[Dict[str, Any]] = deque()
        self._seen: Dict[Tuple[str, str], float] = {}
        self._lock = threading.Lock()
        self._local = threading.local()
        self._drain_task: Optional[asyncio.Task] = None
        self.stats = {"captured": 0, "deduped": 0, "dropped_full": 0,
                      "dropped_no_loop": 0, "written": 0, "write_failed": 0}

    # ---- the logging side (synchronous, must be cheap) -------------------

    def emit(self, record: logging.LogRecord) -> None:
        try:
            if getattr(self._local, "inside", False):
                return                                  # re-entrancy guard
            if record.levelno not in _SEVERITY:
                return
            if any(record.name.startswith(p) for p in _EXCLUDED_PREFIXES):
                return

            self._local.inside = True
            try:
                message = record.getMessage()
            finally:
                self._local.inside = False

            # Dedupe on the FORMAT string, not the formatted message: a retry
            # loop logging "connection to %s failed" for fifty hosts is fifty
            # facts, while the same host fifty times is one.
            key = (record.name, str(record.msg)[:200])
            now = record.created

            with self._lock:
                last = self._seen.get(key)
                if last is not None and (now - last) < DEDUPE_WINDOW_SEC:
                    self.stats["deduped"] += 1
                    return
                self._seen[key] = now
                if len(self._seen) > 4096:              # bounded
                    for stale in [k for k, t in self._seen.items()
                                  if now - t > DEDUPE_WINDOW_SEC][:2048]:
                        self._seen.pop(stale, None)

                if len(self._queue) >= MAX_QUEUE:
                    self.stats["dropped_full"] += 1
                    return

                exception_name = None
                if record.exc_info and record.exc_info[0] is not None:
                    exception_name = record.exc_info[0].__name__

                self._queue.append({
                    "component": _component_of(record.name),
                    "failure_type": "logged_error",
                    "description": message[:4000],
                    "severity": _SEVERITY[record.levelno],
                    "exception_type": exception_name,
                    "metadata": {"logger": record.name,
                                 "module": record.module,
                                 "line": record.lineno,
                                 "level": record.levelname},
                })
                self.stats["captured"] += 1

            self._ensure_draining()

        except Exception:
            # A capture handler that raises breaks logging for the whole
            # process. There is nowhere safe to report this to.
            pass

    def _ensure_draining(self) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # Logged outside an event loop. The record stays queued and is
            # written by whichever loop drains next; if none ever does, it is
            # counted below rather than silently forgotten.
            with self._lock:
                self.stats["dropped_no_loop"] += 1
            return
        if self._drain_task is None or self._drain_task.done():
            self._drain_task = loop.create_task(self._drain())

    # ---- the writing side (async) ---------------------------------------

    async def _drain(self) -> None:
        from core.observability import failure_record

        while True:
            with self._lock:
                if not self._queue:
                    return
                pending = self._queue.popleft()
            try:
                written = await failure_record.report(
                    component=pending["component"],
                    failure_type=pending["failure_type"],
                    description=pending["description"],
                    source_system="log_capture",
                    severity=pending["severity"],
                    exception_type=pending["exception_type"],
                    metadata=pending["metadata"])
                with self._lock:
                    if written:
                        self.stats["written"] += 1
                    else:
                        self.stats["write_failed"] += 1
            except Exception:
                with self._lock:
                    self.stats["write_failed"] += 1
            await asyncio.sleep(0)          # yield; never monopolise the loop

    def snapshot(self) -> Dict[str, Any]:
        """What this handler has done. Dropped counts are part of the answer."""
        with self._lock:
            return {**self.stats, "queued": len(self._queue)}


_handler: Optional[FailureCaptureHandler] = None


def install() -> FailureCaptureHandler:
    """Attach the capture handler to the root logger. Idempotent."""
    global _handler
    if _handler is None:
        _handler = FailureCaptureHandler()
        logging.getLogger().addHandler(_handler)
        logger.info("Failure capture installed: ERROR and CRITICAL records now "
                    "reach unified.failure_events")
    return _handler


def uninstall() -> None:
    global _handler
    if _handler is not None:
        logging.getLogger().removeHandler(_handler)
        _handler = None


def get_handler() -> Optional[FailureCaptureHandler]:
    return _handler


__all__ = ["FailureCaptureHandler", "install", "uninstall", "get_handler"]
