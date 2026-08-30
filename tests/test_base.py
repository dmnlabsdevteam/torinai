#!/usr/bin/env python3
"""Test base class (DB logging removed).

This test harness originally logged to a MySQL schema. TorinAI no longer uses
MySQL, and test logging is now kept in-memory (and standard Python logging).

Usage:
    class MyTests(TestBase):
        def __init__(self):
            super().__init__(
                test_category="governance",
                test_type="unit"
            )
            self.results = []

        async def run_all_tests(self):
            await self.run_test("test_name", self.test_method)

Author: Torin AI Team
Date: January 1, 2026
"""

import asyncio
import logging
import uuid
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Dict, Any, List, Callable
from pathlib import Path
import traceback
import time
import sys
import os

logger = logging.getLogger(__name__)


@dataclass
class TestResult:
    """Individual test result"""
    test_name: str
    status: str  # 'passed', 'failed', 'skipped', 'error'
    duration: float = 0.0
    error_message: Optional[str] = None
    error_traceback: Optional[str] = None
    test_output: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        """Check if test passed"""
        return self.status == 'passed'

    @property
    def failed(self) -> bool:
        """Check if test failed"""
        return self.status in ('failed', 'error')


class TestBase:
    """
    Base class for TorinAI tests.

    Features:
    - Test session management
    - Test result tracking
    - Duration measurement
    - Error handling and logging

    Usage:
        class MyTests(TestBase):
            def __init__(self):
                super().__init__(
                    test_category="governance",
                    test_type="unit"
                )

            async def test_something(self):
                # Your test code
                assert True

            async def run_all_tests(self):
                await self.run_test("test_something", self.test_something)
    """

    def __init__(
        self,
        test_category: str = "general",
        test_type: str = "unit",
        test_file: Optional[str] = None
    ):
        """
        Initialize test base

        Args:
            test_category: Test category (e.g., "governance", "learning", "memory")
            test_type: Test type (e.g., "unit", "integration", "e2e")
            test_file: Test file path (auto-detected if None)
        """
        self.test_category = test_category
        self.test_type = test_type
        self.test_file = test_file or self._detect_test_file()

        # Session management
        self.session_id = f"session_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
        self.session_started_at = None
        self.session_ended_at = None
        self.session_duration = None

        # Test results
        self.results: List[TestResult] = []
        self.total_tests = 0
        self.passed_tests = 0
        self.failed_tests = 0
        self.skipped_tests = 0

        # Metadata
        self.session_metadata = {
            "test_category": test_category,
            "test_type": test_type,
            "python_version": sys.version,
            "platform": sys.platform
        }

    def _detect_test_file(self) -> str:
        """Detect test file from call stack"""
        import inspect
        frame = inspect.currentframe()
        if frame and frame.f_back and frame.f_back.f_back:
            file_path = frame.f_back.f_back.f_code.co_filename
            return str(Path(file_path).relative_to(Path.cwd()))
        return "unknown"

    async def start_session(self):
        """Start a test session."""
        self.session_started_at = datetime.now()
        logger.info(f"Started test session: {self.session_id}")

    async def end_session(self):
        """End a test session."""
        self.session_ended_at = datetime.now()
        if self.session_started_at:
            self.session_duration = (self.session_ended_at - self.session_started_at).total_seconds()
        logger.info(
            f"Ended test session: {self.session_id} | "
            f"{self.passed_tests}/{self.total_tests} passed, "
            f"{self.failed_tests} failed, {self.skipped_tests} skipped"
        )

    async def run_test(
        self,
        test_name: str,
        test_func: Callable,
        metadata: Optional[Dict[str, Any]] = None,
        *args,
        **kwargs
    ) -> TestResult:
        """
        Run a single test.

        Args:
            test_name: Test name
            test_func: Test function to run (can be sync or async)
            metadata: Optional test metadata (description, tags, etc.)
            *args: Test function args
            **kwargs: Test function kwargs

        Returns:
            TestResult object
        """
        self.total_tests += 1
        start_time = time.time()

        # Prepare result with metadata
        result = TestResult(
            test_name=test_name,
            status='pending',
            metadata=metadata or {}
        )

        try:
            # Run test (handle both sync and async functions)
            if asyncio.iscoroutinefunction(test_func):
                await test_func(*args, **kwargs)
            else:
                result_or_coro = test_func(*args, **kwargs)
                # If test_func returned a coroutine, await it
                if asyncio.iscoroutine(result_or_coro):
                    await result_or_coro

            # Test passed
            result.status = 'passed'
            result.duration = time.time() - start_time
            self.passed_tests += 1

        except AssertionError as e:
            # Test failed (assertion error)
            result.status = 'failed'
            result.duration = time.time() - start_time
            result.error_message = str(e)
            result.error_traceback = traceback.format_exc()
            self.failed_tests += 1

        except Exception as e:
            # Test error (unexpected exception)
            result.status = 'error'
            result.duration = time.time() - start_time
            result.error_message = f"{type(e).__name__}: {str(e)}"
            result.error_traceback = traceback.format_exc()
            self.failed_tests += 1

        # Store result
        self.results.append(result)

        # Log result
        if result.passed:
            logger.info(f"✓ {test_name} - PASSED ({result.duration:.3f}s)")
        else:
            logger.error(f"✗ {test_name} - {result.status.upper()} ({result.duration:.3f}s)")
            if result.error_message:
                logger.error(f"  Error: {result.error_message}")

        return result

    async def log_test_result(
        self,
        test_name: str,
        passed: bool,
        error_message: Optional[str] = None,
        duration: float = 0.0,
        test_data: Optional[Dict[str, Any]] = None
    ):
        """
        Log a test result directly (in-memory only).

        Args:
            test_name: Name of the test
            passed: Whether the test passed
            error_message: Error message if failed
            duration: Test duration in seconds
            test_data: Additional test data (prompt, tools_used, etc.)
        """
        self.total_tests += 1
        if passed:
            self.passed_tests += 1
        else:
            self.failed_tests += 1

        return

    async def run_all_tests(self):
        """
        Override this method in subclasses to run all tests

        Example:
            async def run_all_tests(self):
                await self.run_test("test_something", self.test_something)
                await self.run_test("test_another", self.test_another)
        """
        raise NotImplementedError("Subclasses must implement run_all_tests()")

    def get_summary(self) -> Dict[str, Any]:
        """Get test session summary"""
        return {
            "session_id": self.session_id,
            "test_file": self.test_file,
            "test_category": self.test_category,
            "test_type": self.test_type,
            "total_tests": self.total_tests,
            "passed_tests": self.passed_tests,
            "failed_tests": self.failed_tests,
            "skipped_tests": self.skipped_tests,
            "duration": self.session_duration,
            "success_rate": f"{(self.passed_tests / self.total_tests * 100) if self.total_tests > 0 else 0:.1f}%"
        }

    def print_summary(self):
        """Print test session summary"""
        summary = self.get_summary()
        print("\n" + "=" * 60)
        print(f"Test Session: {summary['session_id']}")
        print("=" * 60)
        print(f"File: {summary['test_file']}")
        print(f"Category: {summary['test_category']} | Type: {summary['test_type']}")
        print(f"Duration: {summary['duration']:.3f}s" if summary['duration'] else "Duration: N/A")
        print("-" * 60)
        print(f"Total:   {summary['total_tests']}")
        print(f"Passed:  {summary['passed_tests']}")
        print(f"Failed:  {summary['failed_tests']}")
        print(f"Skipped: {summary['skipped_tests']}")
        print(f"Success: {summary['success_rate']}")
        print("=" * 60)
