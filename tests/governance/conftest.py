#!/usr/bin/env python3
"""
Pytest Configuration for Governance Tests
==========================================
MySQL logging removed.

This suite previously logged results to a MySQL schema. TorinAI no longer uses
MySQL, so we keep a lightweight session id and emit concise results to stdout.
"""

import pytest
import asyncio
from pathlib import Path
from datetime import datetime
import sys
import os
import json
import uuid

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

# Test session tracking
_test_session_id = None
_test_start_times = {}

# Pytest hooks (stdout logging)
def pytest_sessionstart(session):
    """Called at the start of the test session"""
    global _test_session_id
    _test_session_id = f"governance-{uuid.uuid4()}"
    print(f"[governance] session start: {_test_session_id}", flush=True)


def pytest_sessionfinish(session):
    """Called at the end of the test session"""
    global _test_session_id

    if not _test_session_id:
        return

    passed = session.testscollected - session.testsfailed
    failed = session.testsfailed
    print(
        f"[governance] session end: {_test_session_id} | "
        f"total={session.testscollected} passed={passed} failed={failed}",
        flush=True,
    )


def pytest_runtest_logstart(nodeid, location):
    """Called at the start of a test"""
    global _test_start_times
    _test_start_times[nodeid] = datetime.now()


def pytest_runtest_logreport(report):
    """Called after each test phase (setup, call, teardown)"""
    global _test_session_id, _test_start_times

    # Only log the actual test call, not setup/teardown
    if report.when != "call":
        return

    if _test_session_id is None:
        return

    # Extract test details
    test_name = report.nodeid.split("::")[-1]
    test_file = report.nodeid.split("::")[0]

    # Determine status and error
    if report.passed:
        status = "passed"
        has_error = False
    elif report.failed:
        status = "failed"
        has_error = True
    elif report.skipped:
        status = "skipped"
        has_error = False
    else:
        status = "unknown"
        has_error = False

    # Calculate duration in seconds
    elapsed_time = report.duration if hasattr(report, 'duration') else 0.0

    # Prepare metadata
    metadata = {
        "test_file": test_file,
        "nodeid": report.nodeid,
        "outcome": report.outcome,
        "longrepr": str(report.longrepr) if report.longrepr else None,
        "keywords": list(report.keywords)
    }

    line = {
        "session_id": _test_session_id,
        "timestamp": datetime.now().isoformat(),
        "category": "governance_phase8",
        "test_name": test_name,
        "test_file": test_file,
        "status": status,
        "elapsed_time": elapsed_time,
        "has_error": has_error,
        "metadata": metadata,
    }
    print(f"[governance] {json.dumps(line, default=str)}", flush=True)


# Session-level fixtures
@pytest.fixture(scope="session")
def event_loop():
    """Create event loop for async tests"""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()
