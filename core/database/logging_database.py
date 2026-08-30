#!/usr/bin/env python3
"""
Logging Database for TorinAI
Logs all test results, test sessions, and system operations to PostgreSQL.

Integration:
- pytest conftest.py: Automatic test logging
- Test framework: Logs all test execution to PostgreSQL
- System operations: General operation logging

Tables (from postgres_schemas.sql):
- test_sessions: Test run sessions
- test_results: Individual test results
- operation_logs: System operation logs (partitioned)
- chaos_experiments: Chaos engineering experiments
- chaos_metrics: Chaos experiment metrics (partitioned)
- chaos_events: Chaos experiment events (partitioned)
"""

import logging

# A LIBRARY MODULE DOES NOT CONFIGURE LOGGING, AND DOES NOT OPEN FILES AT
# IMPORT.
#
# This called `logging.basicConfig(handlers=[FileHandler('operation_logs.log'),
# StreamHandler()])` at import time, which did three things it had no business
# doing:
#
#   1. Reconfigured the ROOT logger for the whole process. Any program that
#      imported `core.database` -- which `core/__init__.py` pulls in
#      transitively, so effectively everything -- had its logging replaced by
#      this module's choice. Which module won was decided by import order.
#   2. Opened a file as a side effect of importing, at a RELATIVE path, so the
#      log landed wherever the process happened to start. It had grown to 32MB
#      in the repository root.
#   3. Made the package unimportable on a read-only filesystem, which is how
#      the sandbox found it: every candidate change failed with
#      `OSError: [Errno 30] Read-only file system: '/repo/operation_logs.log'`
#      before a single line of the change was reached.
#
# `core/main.py` configures logging for the application, which is the correct
# owner. A library asks for its logger and says nothing about where output goes.
logger = logging.getLogger(__name__)
import json
from typing import Dict, Any, List, Optional
from datetime import datetime

from .unified_database_postgres import TorinUnifiedDatabasePostgres as TorinUnifiedDatabase


class LoggingDatabase:
    """
    Logging Database for Test Results and System Operations

    Uses unified PostgreSQL database (tables from postgres_schemas.sql).

    Automatically logs:
    - Test sessions (pytest runs)
    - Test results (individual test outcomes)
    - System operations (general logging)
    - Chaos experiments and metrics

    Used by:
    - pytest conftest.py for automatic test logging
    - System components for operation logging
    - Chaos engineering framework
    """

    def __init__(self):
        """Initialize logging database using unified PostgreSQL database"""
        self.db = TorinUnifiedDatabase()
        self.initialized = False

        # Metrics
        self.test_sessions_logged = 0
        self.test_results_logged = 0
        self.operations_logged = 0
        self.failed_logs = 0
        self.passed_tests = 0
        self.failed_tests = 0

    async def initialize(self) -> bool:
        """
        Initialize database connection

        Returns:
            True if successful
        """
        if self.initialized:
            return True

        try:
            # Initialize unified database (tables already exist from postgres_schemas.sql)
            await self.db.initialize()

            # Verify critical tables exist
            test_sessions_exists = await self.db.table_exists('test_sessions')
            test_results_exists = await self.db.table_exists('test_results')
            operation_logs_exists = await self.db.table_exists('operation_logs')

            if not test_sessions_exists:
                logger.warning("test_sessions table doesn't exist - run postgres_schemas.sql")
            if not test_results_exists:
                logger.warning("test_results table doesn't exist - run postgres_schemas.sql")
            if not operation_logs_exists:
                logger.warning("operation_logs table doesn't exist - run postgres_schemas.sql")

            self.initialized = True
            logger.info("LoggingDatabase initialized successfully (PostgreSQL)")
            return True

        except Exception as e:
            logger.error(f"LoggingDatabase initialization failed: {e}")
            return False

    async def log_test_session(
        self,
        session_id: str,
        started_at: Optional[datetime] = None,
        test_file: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Log test session start

        Args:
            session_id: Unique session identifier
            started_at: Session start time (now if None)
            test_file: Test file being run
            metadata: Optional session metadata

        Returns:
            True if successful
        """
        if not self.initialized:
            # The result is CHECKED. Discarding it meant a failed initialize was
            # followed by the work it was meant to enable, and the real failure
            # resurfaced later disguised as something else.
            if await self.initialize() is False:
                raise RuntimeError(
                    type(self).__name__ + ' could not initialize; refusing to '
                    'continue as though it had')

        try:
            started_at = started_at or datetime.now()

            await self.db.execute_query(
                """
                INSERT INTO test_sessions (
                    session_id,
                    started_at,
                    test_file,
                    session_metadata
                ) VALUES ($1, $2, $3, $4)
                """,
                (
                    session_id,
                    started_at,
                    test_file,
                    json.dumps(metadata) if metadata else None
                ),
                commit=True
            )

            self.test_sessions_logged += 1
            logger.debug(f"Logged test session: {session_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to log test session: {e}")
            self.failed_logs += 1
            return False

    async def log_test_result(
        self,
        session_id: str,
        test_name: str,
        status: str,
        duration: Optional[float] = None,
        error_message: Optional[str] = None,
        error_traceback: Optional[str] = None,
        test_output: Optional[str] = None,
        test_file: Optional[str] = None,
        test_class: Optional[str] = None,
        test_function: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Log individual test result

        Args:
            session_id: Session identifier
            test_name: Full test name
            status: Test status (passed, failed, skipped, error)
            duration: Test duration in seconds
            error_message: Error message if failed
            error_traceback: Full traceback if failed
            test_output: Test stdout/stderr
            test_file: Test file path
            test_class: Test class name
            test_function: Test function name
            metadata: Optional test metadata

        Returns:
            True if successful
        """
        if not self.initialized:
            # The result is CHECKED. Discarding it meant a failed initialize was
            # followed by the work it was meant to enable, and the real failure
            # resurfaced later disguised as something else.
            if await self.initialize() is False:
                raise RuntimeError(
                    type(self).__name__ + ' could not initialize; refusing to '
                    'continue as though it had')

        try:
            # Generate result ID
            result_id = f"result_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"

            # Extract test function from test_name if not provided
            if not test_function:
                # test_name format: "test_file.py::TestClass::test_function"
                parts = test_name.split('::')
                test_function = parts[-1] if parts else test_name
                if len(parts) > 1:
                    test_class = parts[-2] if len(parts) > 2 else None

            # Insert test result
            await self.db.execute_query(
                """
                INSERT INTO test_results (
                    result_id,
                    session_id,
                    test_name,
                    test_file,
                    test_class,
                    test_function,
                    status,
                    duration_seconds,
                    error_message,
                    error_traceback,
                    test_output,
                    test_metadata
                ) VALUES ($1, $2, $3, $4, $5, $6, $7::unified.test_status, $8, $9, $10, $11, $12::jsonb)
                """,
                (
                    result_id,
                    session_id,
                    test_name,
                    test_file,
                    test_class,
                    test_function,
                    status,
                    duration,
                    error_message,
                    error_traceback,
                    test_output,
                    json.dumps(metadata) if metadata else None
                ),
                commit=True
            )

            # Update session counters
            if status == 'passed':
                self.passed_tests += 1
                await self.db.execute_query(
                    "UPDATE test_sessions SET passed_tests = passed_tests + 1 WHERE session_id = $1",
                    (session_id,),
                    commit=True
                )
            elif status == 'failed':
                self.failed_tests += 1
                await self.db.execute_query(
                    "UPDATE test_sessions SET failed_tests = failed_tests + 1 WHERE session_id = $1",
                    (session_id,),
                    commit=True
                )
            elif status == 'skipped':
                await self.db.execute_query(
                    "UPDATE test_sessions SET skipped_tests = skipped_tests + 1 WHERE session_id = $1",
                    (session_id,),
                    commit=True
                )

            # Update total tests count
            await self.db.execute_query(
                "UPDATE test_sessions SET total_tests = total_tests + 1 WHERE session_id = $1",
                (session_id,),
                commit=True
            )

            self.test_results_logged += 1
            logger.debug(f"Logged test result: {test_name} ({status})")
            return True

        except Exception as e:
            logger.error(f"Failed to log test result: {e}")
            self.failed_logs += 1
            return False

    async def end_test_session(
        self,
        session_id: str,
        ended_at: Optional[datetime] = None
    ) -> bool:
        """
        Mark test session as ended

        Args:
            session_id: Session identifier
            ended_at: End timestamp (now if None)

        Returns:
            True if successful
        """
        if not self.initialized:
            # The result is CHECKED. Discarding it meant a failed initialize was
            # followed by the work it was meant to enable, and the real failure
            # resurfaced later disguised as something else.
            if await self.initialize() is False:
                raise RuntimeError(
                    type(self).__name__ + ' could not initialize; refusing to '
                    'continue as though it had')

        try:
            ended_at = ended_at or datetime.now()

            # Get session start time to calculate duration
            session = await self.db.execute_query(
                "SELECT started_at FROM test_sessions WHERE session_id = $1",
                (session_id,),
                fetch_one=True
            )

            if session:
                duration = (ended_at - session['started_at']).total_seconds()

                await self.db.execute_query(
                    """
                    UPDATE test_sessions
                    SET ended_at = $1, duration_seconds = $2
                    WHERE session_id = $3
                    """,
                    (ended_at, duration, session_id),
                    commit=True
                )

                logger.debug(f"Ended test session: {session_id} (duration: {duration:.2f}s)")
                return True
            else:
                logger.warning(f"Test session not found: {session_id}")
                return False

        except Exception as e:
            logger.error(f"Failed to end test session: {e}")
            return False

    async def get_test_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """
        Get test session by ID

        Args:
            session_id: Session identifier

        Returns:
            Session data or None
        """
        if not self.initialized:
            # The result is CHECKED. Discarding it meant a failed initialize was
            # followed by the work it was meant to enable, and the real failure
            # resurfaced later disguised as something else.
            if await self.initialize() is False:
                raise RuntimeError(
                    type(self).__name__ + ' could not initialize; refusing to '
                    'continue as though it had')

        try:
            session = await self.db.execute_query(
                "SELECT * FROM test_sessions WHERE session_id = $1",
                (session_id,),
                fetch_one=True
            )
            return session

        except Exception as e:
            logger.error(f"Failed to get test session: {e}")
            return None

    async def get_session_results(self, session_id: str) -> List[Dict[str, Any]]:
        """
        Get all test results for a session

        Args:
            session_id: Session identifier

        Returns:
            List of test result dicts
        """
        if not self.initialized:
            # The result is CHECKED. Discarding it meant a failed initialize was
            # followed by the work it was meant to enable, and the real failure
            # resurfaced later disguised as something else.
            if await self.initialize() is False:
                raise RuntimeError(
                    type(self).__name__ + ' could not initialize; refusing to '
                    'continue as though it had')

        try:
            results = await self.db.execute_query(
                """
                SELECT * FROM test_results
                WHERE session_id = $1
                ORDER BY created_at
                """,
                (session_id,),
                fetch_all=True
            )
            return results if results else []

        except Exception as e:
            logger.error(f"Failed to get session results: {e}")
            return []

    async def log_operation(
        self,
        operation_type: str,
        component: str,
        message: str,
        level: str = 'INFO',
        metadata: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Log system operation

        Args:
            operation_type: Type of operation
            component: Component name
            message: Log message
            level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
            metadata: Optional metadata

        Returns:
            True if successful
        """
        if not self.initialized:
            # The result is CHECKED. Discarding it meant a failed initialize was
            # followed by the work it was meant to enable, and the real failure
            # resurfaced later disguised as something else.
            if await self.initialize() is False:
                raise RuntimeError(
                    type(self).__name__ + ' could not initialize; refusing to '
                    'continue as though it had')

        try:
            await self.db.execute_query(
                """
                INSERT INTO operation_logs (
                    operation_type,
                    component,
                    message,
                    level,
                    metadata,
                    created_at
                ) VALUES ($1, $2, $3, $4::unified.log_level, $5::jsonb, CURRENT_TIMESTAMP)
                """,
                (
                    operation_type,
                    component,
                    message,
                    level.upper(),
                    json.dumps(metadata) if metadata else None
                ),
                commit=True
            )

            self.operations_logged += 1
            return True

        except Exception as e:
            logger.error(f"Failed to log operation: {e}")
            self.failed_logs += 1
            return False

    async def update_chaos_experiment(
        self,
        experiment_id: str,
        **updates: Any,
    ) -> bool:
        """
        Update chaos experiment fields

        Args:
            experiment_id: Experiment identifier
            updates: Fields to update

        Returns:
            True if successful
        """
        if not self.initialized:
            # The result is CHECKED. Discarding it meant a failed initialize was
            # followed by the work it was meant to enable, and the real failure
            # resurfaced later disguised as something else.
            if await self.initialize() is False:
                raise RuntimeError(
                    type(self).__name__ + ' could not initialize; refusing to '
                    'continue as though it had')

        try:
            if not updates:
                return True

            # Build dynamic UPDATE query
            set_clauses = []
            params: List[Any] = []  # type: ignore[name-defined]
            param_idx = 1

            for key, value in updates.items():
                set_clauses.append(f"{key} = ${param_idx}")
                params.append(value)
                param_idx += 1

            params.append(experiment_id)

            query = f"UPDATE chaos_experiments SET {', '.join(set_clauses)} WHERE experiment_id = ${param_idx}"

            await self.db.execute_query(query, tuple(params), commit=True)
            return True

        except Exception as e:
            logger.error(f"Failed to update chaos experiment: {e}")
            return False

    async def get_metrics(self) -> Dict[str, Any]:
        """
        Get logging database metrics

        Returns:
            Dict with metrics
        """
        return {
            'test_sessions_logged': self.test_sessions_logged,
            'test_results_logged': self.test_results_logged,
            'operations_logged': self.operations_logged,
            'failed_logs': self.failed_logs,
            'passed_tests': self.passed_tests,
            'failed_tests': self.failed_tests
        }

    async def close(self):
        """Close database connection"""
        if self.db:
            await self.db.close()

    # ------------------------------------------------------------------
    # Chaos Engineering Helpers (PostgreSQL unified schema)
    # ------------------------------------------------------------------

    async def log_chaos_experiment(
        self,
        *,
        experiment_id: str,
        name: str,
        description: Optional[str],
        target_system: str,
        chaos_type: str,
        environment: Optional[str] = None,
        experiment_config: Optional[Dict[str, Any]] = None,
        blast_radius: Optional[int] = None,
        created_by: Optional[str] = None,
        hypothesis: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        status: str = "pending",
        governance_decision_id: Optional[str] = None,
        governance_tier: Optional[str] = None,
    ) -> bool:
        """Insert or update a chaos experiment in unified.chaos_experiments.

        The unified PostgreSQL schema is slightly different from the original
        MySQL schema. Fields like ``blast_radius`` and ``created_by`` are
        stored inside the ``experiment_config``/``metadata`` JSON payloads.
        """
        if not self.initialized:
            # The result is CHECKED. Discarding it meant a failed initialize was
            # followed by the work it was meant to enable, and the real failure
            # resurfaced later disguised as something else.
            if await self.initialize() is False:
                raise RuntimeError(
                    type(self).__name__ + ' could not initialize; refusing to '
                    'continue as though it had')

        try:
            config_payload: Dict[str, Any] = experiment_config.copy() if experiment_config else {}
            if blast_radius is not None:
                config_payload.setdefault("chaos_parameters", {})["blast_radius"] = blast_radius

            metadata_payload: Dict[str, Any] = metadata.copy() if metadata else {}
            if created_by:
                metadata_payload["created_by"] = created_by

            await self.db.execute_query(
                """
                INSERT INTO chaos_experiments (
                    experiment_id,
                    name,
                    description,
                    target_system,
                    chaos_type,
                    environment,
                    status,
                    governance_decision_id,
                    governance_tier,
                    experiment_config,
                    hypothesis,
                    metadata
                ) VALUES (
                    $1, $2, $3, $4, $5, $6,
                    $7::unified.chaos_status,
                    $8, $9,
                    $10::jsonb,
                    $11::jsonb,
                    $12::jsonb
                )
                ON CONFLICT (experiment_id) DO UPDATE SET
                    description = EXCLUDED.description,
                    target_system = EXCLUDED.target_system,
                    chaos_type = EXCLUDED.chaos_type,
                    environment = EXCLUDED.environment,
                    status = EXCLUDED.status,
                    governance_decision_id = EXCLUDED.governance_decision_id,
                    governance_tier = EXCLUDED.governance_tier,
                    experiment_config = EXCLUDED.experiment_config,
                    hypothesis = EXCLUDED.hypothesis,
                    metadata = EXCLUDED.metadata
                """,
                (
                    experiment_id,
                    name,
                    description,
                    target_system,
                    chaos_type,
                    environment,
                    status,
                    governance_decision_id,
                    governance_tier,
                    json.dumps(config_payload) if config_payload else None,
                    json.dumps(hypothesis) if hypothesis else None,
                    json.dumps(metadata_payload) if metadata_payload else None,
                ),
                commit=True,
            )

            return True

        except Exception as e:
            logger.error(f"Failed to log chaos experiment: {e}")
            return False

    async def get_chaos_experiments(
        self,
        *,
        target_system: Optional[str] = None,
        environment: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 1000,
    ) -> List[Dict[str, Any]]:
        """Fetch chaos experiments with optional filtering."""
        if not self.initialized:
            # The result is CHECKED. Discarding it meant a failed initialize was
            # followed by the work it was meant to enable, and the real failure
            # resurfaced later disguised as something else.
            if await self.initialize() is False:
                raise RuntimeError(
                    type(self).__name__ + ' could not initialize; refusing to '
                    'continue as though it had')

        try:
            conditions: List[str] = []
            params: List[Any] = []  # type: ignore[name-defined]
            idx = 1

            if target_system:
                conditions.append(f"target_system = ${idx}")
                params.append(target_system)
                idx += 1
            if environment:
                conditions.append(f"environment = ${idx}")
                params.append(environment)
                idx += 1
            if status:
                conditions.append(f"status = ${idx}::unified.chaos_status")
                params.append(status)
                idx += 1

            query = "SELECT * FROM chaos_experiments"
            if conditions:
                query += " WHERE " + " AND ".join(conditions)
            query += f" ORDER BY created_at DESC LIMIT ${idx}"
            params.append(limit)

            rows = await self.db.execute_query(
                query,
                tuple(params),
                fetch_all=True,
            )

            return rows or []

        except Exception as e:
            logger.error(f"Failed to fetch chaos experiments: {e}")
            return []

    async def delete_chaos_experiment(self, experiment_id: str) -> bool:
        """Delete a chaos experiment and its related data."""
        if not self.initialized:
            # The result is CHECKED. Discarding it meant a failed initialize was
            # followed by the work it was meant to enable, and the real failure
            # resurfaced later disguised as something else.
            if await self.initialize() is False:
                raise RuntimeError(
                    type(self).__name__ + ' could not initialize; refusing to '
                    'continue as though it had')

        try:
            await self.db.execute_query(
                "DELETE FROM chaos_experiments WHERE experiment_id = $1",
                (experiment_id,),
                commit=True,
            )
            return True
        except Exception as e:
            logger.error(f"Failed to delete chaos experiment {experiment_id}: {e}")
            return False

    async def log_chaos_event(
        self,
        *,
        experiment_id: str,
        event_type: str,
        severity: str = "info",
        event_data: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Log a chaos event to unified.chaos_events."""
        if not self.initialized:
            # The result is CHECKED. Discarding it meant a failed initialize was
            # followed by the work it was meant to enable, and the real failure
            # resurfaced later disguised as something else.
            if await self.initialize() is False:
                raise RuntimeError(
                    type(self).__name__ + ' could not initialize; refusing to '
                    'continue as though it had')

        try:
            await self.db.execute_query(
                """
                INSERT INTO chaos_events (
                    experiment_id,
                    event_type,
                    event_data,
                    severity
                ) VALUES (
                    $1,
                    $2,
                    $3::jsonb,
                    $4::unified.chaos_severity
                )
                """,
                (
                    experiment_id,
                    event_type,
                    json.dumps(event_data) if event_data else None,
                    severity,
                ),
                commit=True,
            )
            return True
        except Exception as e:
            logger.error(f"Failed to log chaos event: {e}")
            return False

    async def log_chaos_metric(
        self,
        *,
        experiment_id: str,
        metric_type: str,
        metric_name: str,
        metric_value: float,
        metric_metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Log a chaos metric to unified.chaos_metrics."""
        if not self.initialized:
            # The result is CHECKED. Discarding it meant a failed initialize was
            # followed by the work it was meant to enable, and the real failure
            # resurfaced later disguised as something else.
            if await self.initialize() is False:
                raise RuntimeError(
                    type(self).__name__ + ' could not initialize; refusing to '
                    'continue as though it had')

        try:
            await self.db.execute_query(
                """
                INSERT INTO chaos_metrics (
                    experiment_id,
                    metric_type,
                    metric_name,
                    metric_value,
                    metric_metadata
                ) VALUES (
                    $1,
                    $2,
                    $3,
                    $4,
                    $5::jsonb
                )
                """,
                (
                    experiment_id,
                    metric_type,
                    metric_name,
                    metric_value,
                    json.dumps(metric_metadata) if metric_metadata else None,
                ),
                commit=True,
            )
            return True
        except Exception as e:
            logger.error(f"Failed to log chaos metric: {e}")
            return False


# Singleton factory for LoggingDatabase
_logging_db_instance: Optional["LoggingDatabase"] = None


def get_logging_db() -> "LoggingDatabase":
    """Return shared LoggingDatabase instance.

    This preserves the original MySQL-era get_logging_db() API so that
    main.py and chaos components can obtain a singleton logging database
    without managing their own instances.
    """
    global _logging_db_instance
    if _logging_db_instance is None:
        _logging_db_instance = LoggingDatabase()
    return _logging_db_instance
