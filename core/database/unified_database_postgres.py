#!/usr/bin/env python3
"""
TorinAI Unified PostgreSQL Database
====================================
Production PostgreSQL database implementation with schema-based tier architecture.

Architecture:
- Single PostgreSQL database (torinai_db) with 3 logical schemas
- Hot Tier: memory_hot schema for last 60 days
- Unified: unified schema with directives, governance, metrics
- Cold Tier: memory_cold schema for 60+ day old memories

Connection Pooling:
- Uses asyncpg for async PostgreSQL operations
- Single connection pool with schema routing via search_path
- pgvector integration for 100x faster semantic search
- Configuration from .env.postgres environment variables

Schemas:
- unified: Main schema (directives, governance, metrics, alerts, etc.)
- memory_hot: Hot tier for recent memories (last 60 days) with pgvector
- memory_cold: Cold tier for archived memories (60+ days old) with pgvector
"""

import logging

from .postgres_config import DEFAULT_PORT
import os
import json
import asyncio
import time
from typing import Dict, Any, List, Optional, Tuple, Union
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

try:
    import asyncpg
    from pgvector.asyncpg import register_vector
    ASYNCPG_AVAILABLE = True
except ImportError:
    ASYNCPG_AVAILABLE = False
    logging.warning("asyncpg or pgvector not available - database operations will fail")

from dotenv import load_dotenv

from core.database.postgres_config import DatabaseIdentityError, PostgresConfig

logger = logging.getLogger(__name__)


class TorinUnifiedDatabasePostgres:
    """
    Unified PostgreSQL Database for TorinAI (Singleton)

    All instantiations return the same shared instance with shared connection
    pool, preventing connection exhaustion from multiple components each
    creating their own pools.

    Provides async connection pooling and database operations for:
    - Directive system (governance_laws, internal_directives, etc.)
    - Unified metrics and alerts
    - Component tracking
    - Hot tier memory storage (0-60 days) with pgvector semantic search
    - Cold tier memory archival (60+ days) with pgvector semantic search
    - Learning and adaptation data

    Usage:
        db = TorinUnifiedDatabasePostgres()
        await db.initialize()

        # Execute query with automatic schema routing
        results = await db.execute_query(
            "SELECT * FROM internal_directives WHERE status = $1",
            ('ACTIVE',),
            fetch_all=True
        )

        # Use hot tier schema
        memories = await db.execute_query(
            "SELECT * FROM memory_hot WHERE timestamp > $1",
            (cutoff_time,),
            use_hot_tier=True,
            fetch_all=True
        )

        await db.close()
    """

    # Singleton: all instantiations share the same object and connection pool
    _instance = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(
        self,
        host: Optional[str] = None,
        port: Optional[int] = None,
        user: Optional[str] = None,
        password: Optional[str] = None,
        database: Optional[str] = None,
        pool_min_size: Optional[int] = None,
        pool_max_size: Optional[int] = None
    ):
        """
        Initialize database connection manager

        Args:
            host: PostgreSQL host (from env if None)
            port: PostgreSQL port (from env if None)
            user: PostgreSQL user (from env if None)
            password: PostgreSQL password (from env if None)
            database: Database name (from env if None)
            pool_min_size: Min pool size (from env if None, default 5)
            pool_max_size: Max pool size (from env if None, default 20)
        """
        # Skip re-initialization if singleton already configured
        if hasattr(self, '_singleton_configured'):
            return
        self._singleton_configured = True

        # Set ALL instance attributes to safe defaults BEFORE any code that can raise.
        # This ensures the singleton is always in a usable (non-crashing) state even
        # if initialization fails partway through.
        self.initialized = False
        self.pool = None
        #: The event loop self.pool was created on. asyncpg pools are not
        #: portable across loops; see _pool_matches_running_loop.
        self._pool_loop = None
        #: Identifies each pool generation server-side, so backends stranded by
        #: a dead loop can be found and closed. See _reap_stale_pools.
        self._pool_generation = 0
        self._pool_tag: Optional[str] = None
        self._stale_pool_tags: set = set()
        self.host = 'localhost'
        # 5433 is TorinAI's own instance; 5432 is the shared one holding
        # agentso's tenant databases. See postgres_config.DEFAULT_PORT.
        self.port = DEFAULT_PORT
        self.user = 'postgres'
        self.password = ''
        self.database = 'torinai_db'
        self.pool_min_size = 5
        self.pool_max_size = 20
        self._boot_time = time.time()
        self._error_counts: Dict[str, int] = {}
        self._error_grace_seconds = 60
        self._error_retry_threshold = 3
        self.metrics = {
            'total_queries': 0,
            'failed_queries': 0,
            'total_connections': 0,
            'pool_errors': 0,
            'hot_tier_queries': 0,
            'cold_tier_queries': 0,
            'unified_queries': 0
        }

        if not ASYNCPG_AVAILABLE:
            raise ImportError(
                "asyncpg and pgvector are required for PostgreSQL database operations. "
                "Install with: pip install asyncpg pgvector"
            )

        # Configuration is resolved, not imposed. This previously called
        # load_dotenv(override=True) and then read os.getenv on the next line,
        # so the file overwrote the process environment and an externally
        # supplied POSTGRES_DATABASE could never take effect -- a subprocess
        # asked for one database and silently connected to another.
        self.config = PostgresConfig.resolve(
            host=host, port=port, user=user, password=password, database=database,
            pool_min_size=pool_min_size, pool_max_size=pool_max_size,
        )
        self.host = self.config.host
        self.port = self.config.port
        self.user = self.config.user
        self.password = self.config.password
        self.database = self.config.database
        self.pool_min_size = self.config.pool_min_size
        self.pool_max_size = self.config.pool_max_size
        self._error_grace_seconds = int(os.getenv("DB_ERROR_GRACE_SECONDS", "60"))
        self._error_retry_threshold = int(os.getenv("DB_ERROR_MAX_INITIAL_RETRIES", "3"))

        logger.info(
            f"TorinUnifiedDatabasePostgres singleton configured "
            f"(host: {self.host}:{self.port}, database: {self.database}, "
            f"pool: {self.pool_min_size}-{self.pool_max_size}, "
            f"database_source: {self.config.provenance.get('database')})"
        )

    async def assert_database_identity(self, expected: str) -> str:
        """Verify against the live connection which database this actually is.

        Asks the server rather than trusting configuration, so a mismatch is
        caught whether it came from resolution, a pooled connection or a
        singleton constructed earlier by something else. Required before any
        mutation-capable experiment: a process that believes it is operating on
        a clone while writing to production is not merely misconfigured.
        """
        if not self.initialized:
            # The result is CHECKED. Discarding it meant a failed initialize was
            # followed by the work it was meant to enable, and the real failure
            # resurfaced later disguised as something else.
            if await self.initialize() is False:
                raise RuntimeError(
                    type(self).__name__ + ' could not initialize; refusing to '
                    'continue as though it had')

        actual = await self.execute_query("SELECT current_database()")
        if isinstance(actual, list) and actual:
            actual = actual[0]
        if hasattr(actual, "values"):
            actual = list(actual.values())[0]
        actual = str(actual)

        if actual != expected:
            raise DatabaseIdentityError(
                f"connected to {actual!r} while operating as {expected!r} "
                f"(configured from {self.config.provenance.get('database')})"
            )
        return actual

    def _should_notify_error(self, operation: str) -> bool:
        """Decide whether to send a database error notification.

        Applies a startup grace window and per-operation retry threshold so
        transient errors during boot don't spam Slack.
        """
        # Track how many times we've seen this operation fail
        current_count = self._error_counts.get(operation, 0) + 1
        self._error_counts[operation] = current_count

        # Within the grace window, suppress the first N failures per operation
        if self._error_grace_seconds > 0:
            since_boot = time.time() - self._boot_time
            if since_boot < self._error_grace_seconds and current_count <= self._error_retry_threshold:
                logger.warning(
                    "Suppressing %s database error (attempt %d within grace window %ds)",
                    operation,
                    current_count,
                    self._error_grace_seconds,
                )
                return False

        # Outside grace window or beyond retry threshold: notify
        return True

    async def _ensure_pool_for_running_loop(self) -> None:
        """Guarantee a usable pool before any query.

        Replaces a bare `if not self.initialized: raise`. That guard checked a
        boolean, not whether the pool could actually serve the CURRENT loop, so
        a manager initialized on one loop passed it and then failed inside
        asyncpg with a message about the query rather than the lifecycle.

        Re-initializing here is safe: initialize() is idempotent when the pool
        already matches the running loop.
        """
        if self.initialized and self._pool_matches_running_loop():
            return
        if not self.initialized and self.pool is None and self._pool_loop is None:
            # Never initialized at all — that is a caller error, not a loop one.
            raise RuntimeError(
                "Database not initialized. Call await db.initialize() at startup before using."
            )
        await self.initialize()

    def _pool_matches_running_loop(self) -> bool:
        """True when self.pool can actually be used from the current loop.

        asyncpg binds a pool and every connection in it to the loop that
        created them. Using one from another loop does not raise a clear error
        — it fails inside the protocol with "another operation is in progress",
        naming a query that is entirely valid, which reads as a database fault
        rather than a lifecycle one.
        """
        if self.pool is None:
            return False
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            return False
        if self._pool_loop is None:
            return True          # created before this tracking existed
        return self._pool_loop is running and not self._pool_loop.is_closed()

    async def _register_connection_codecs(self, conn) -> None:
        """Give one pooled connection the pgvector codec.

        Best-effort per connection: a database without the vector extension is
        still perfectly usable for everything that is not an embedding query, so
        a missing extension must not stop the pool from being created at all.
        Raising here would take out the whole pool -- and did, for any database
        created without pgvector.
        """
        try:
            await register_vector(conn)
        except Exception as e:
            logger.debug("pgvector codec unavailable on this connection: %s", e)

    async def _discard_pool(self) -> None:
        """Drop a pool that belongs to a dead or foreign loop, releasing its
        sockets rather than abandoning them.

        `await pool.close()` is a graceful shutdown that has to run on the loop
        that owns the pool, so it is unavailable here by definition — this is
        called precisely when that loop is gone. Dropping the reference and
        waiting for the collector was the previous behaviour, and it leaks:
        every loop switch strands up to `pool_max_size` server connections
        until GC happens to run. A process that switches loops often — a worker
        thread with its own loop, repeated asyncio.run(), a test session where
        each test gets a fresh loop — walks that leak straight into
        `max_connections` and then fails to build ANY pool, which surfaces as a
        database outage in whatever unrelated component asked next.

        `terminate()` is asyncpg's synchronous, non-graceful release: it aborts
        the transports directly instead of negotiating shutdown, so it does not
        need the owning loop to still be alive. In-flight queries on that pool
        are already lost — the loop running them is dead — so there is nothing
        graceful left to preserve.
        """
        # Asked BEFORE the fields are cleared. _pool_matches_running_loop reads
        # self.pool, so consulting it afterwards always answered False and the
        # graceful branch below could never be reached — every discard, even one
        # on the pool's own live loop, fell through to abandonment.
        owns_loop = self._pool_matches_running_loop()
        stale_tag = self._pool_tag

        old = self.pool
        self.pool = None
        self._pool_loop = None
        self.initialized = False
        if old is None:
            return

        if owns_loop:
            try:
                await old.close()
                return
            except Exception as e:
                logger.debug("Graceful close of old pool failed: %s", e)

        try:
            old.terminate()
            return
        except Exception as e:
            # Expected when the owning loop is gone: terminate() aborts the
            # transports, and aborting needs the loop. Nothing in this process
            # can release those sockets now, so the backends are handed to the
            # server-side reaper instead of being abandoned.
            logger.debug("Cannot terminate a pool from a dead loop (%s)", e)

        if stale_tag:
            self._stale_pool_tags.add(stale_tag)

    async def _reap_stale_pools(self) -> int:
        """Close the server-side backends left by pools this process abandoned.

        Terminates by `application_name`, which is stamped per pool generation,
        so this can only ever reach connections THIS process opened and never
        the current pool. Anything else sharing the server -- another service,
        another instance -- is untouched by construction.

        Without this, each event-loop switch strands up to `pool_max_size`
        backends until the collector happens to run, and a process that
        switches loops faster than that walks into `max_connections`. The
        failure then surfaces as "cannot create pool" in whichever component
        asked next, which is never the one that caused it.
        """
        if not self._stale_pool_tags or self.pool is None:
            return 0

        tags = sorted(self._stale_pool_tags - {self._pool_tag})
        if not tags:
            return 0

        try:
            rows = await self.pool.fetch(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity"
                " WHERE application_name = ANY($1::text[])"
                "   AND pid <> pg_backend_pid()",
                tags,
            )
        except Exception as e:
            # Reaping is hygiene, not correctness for THIS query. A failure
            # here must not stop the pool that was just built from being used.
            logger.warning("Could not reap abandoned database backends: %s", e)
            return 0

        self._stale_pool_tags -= set(tags)
        if rows:
            logger.info(
                "Reaped %d abandoned database backend(s) from %d dead pool(s)",
                len(rows), len(tags),
            )
        return len(rows)

    async def initialize(self) -> bool:
        """
        Initialize database connection pool

        Creates single connection pool for all schemas:
        - unified (main tables - directives, governance, logs)
        - memory_hot (hot tier with pgvector)
        - memory_cold (cold tier with pgvector)

        Returns:
            True if successful
        """
        if self.initialized and self._pool_matches_running_loop():
            logger.debug("Database already initialized")
            return True

        if self.initialized:
            # The pool belongs to a different event loop. asyncpg binds a pool
            # and its connections to the loop that created them, so reusing it
            # here fails deep inside the protocol with
            #   InterfaceError: cannot perform operation: another operation is
            #   in progress
            # naming a query that is perfectly valid. This manager is a process
            # singleton, so any caller that runs asyncio.run() twice, starts a
            # worker thread with its own loop, or restarts the loop after a
            # crash inherits a pool from a dead one. Rebuild instead.
            logger.warning(
                "Connection pool belongs to a different event loop; rebuilding "
                "for the running loop"
            )
            await self._discard_pool()

        try:
            # Every pool generation is tagged so its server-side backends can be
            # identified later BY NAME. A pool abandoned with its dead loop
            # cannot be closed from Python -- asyncpg needs the owning loop to
            # abort the transports -- but the backends it left behind can be
            # reaped through ordinary SQL from the new one.
            self._pool_generation += 1
            self._pool_tag = f"torinai_{os.getpid()}_{self._pool_generation}"

            # Create single PostgreSQL connection pool
            self.pool = await asyncpg.create_pool(
                host=self.host,
                port=self.port,
                user=self.user,
                password=self.password,
                database=self.database,
                min_size=self.pool_min_size,
                max_size=self.pool_max_size,
                command_timeout=60,
                server_settings={'application_name': self._pool_tag},
                # EVERY pooled connection gets the pgvector codec, via asyncpg's
                # init hook. This function existed and was never passed anywhere;
                # registration was done once on a single acquired connection
                # instead, so exactly one connection in the pool could adapt a
                # Python list to `vector`. A lone query happened to get that
                # connection and worked, which is why this looked fine -- but
                # concurrent embedding queries fan out across the pool and the
                # rest failed with "expected str, got list".
                init=self._register_connection_codecs,
            )

            # The new pool is the first thing able to reach the server since
            # the old one died, so this is the earliest point the backends it
            # stranded can be closed.
            await self._reap_stale_pools()

            logger.info(
                f"PostgreSQL database pool created "
                f"(database: {self.database}, pool: {self.pool_min_size}-{self.pool_max_size})"
            )

            # Verify schemas exist
            try:
                async with self.pool.acquire() as conn:
                    schemas = await conn.fetch(
                        "SELECT schema_name FROM information_schema.schemata WHERE schema_name IN ('unified', 'memory_hot', 'memory_cold')"
                    )
                    schema_names = [row['schema_name'] for row in schemas]

                    if 'unified' in schema_names:
                        logger.info("✓ unified schema available")
                    if 'memory_hot' in schema_names:
                        logger.info("✓ memory_hot schema available")
                    if 'memory_cold' in schema_names:
                        logger.info("✓ memory_cold schema available")

                    if len(schema_names) == 0:
                        logger.warning(
                            "No schemas found! Run postgres_schemas.sql to create database structure."
                        )
            except Exception as e:
                logger.warning(f"Schema verification warning: {e}")

            self.initialized = True
            self._pool_loop = asyncio.get_running_loop()
            logger.info("PostgreSQL database initialization complete")
            return True

        except Exception as e:
            logger.error(f"Database initialization failed: {e}")
            self.metrics['pool_errors'] += 1

            # Send notification for database initialization failure (respect grace window)
            if self._should_notify_error("initialization"):
                try:
                    from core.utils.notification_helpers import notify_database_error
                    asyncio.create_task(notify_database_error(
                        operation="initialization",
                        error=e,
                        database="PostgreSQL Unified Database",
                        context={"host": self.host, "database": self.database}
                    ))
                except Exception as notify_error:
                    logger.warning(f"Failed to send database error notification: {notify_error}")

            return False

    @asynccontextmanager
    async def get_connection(self, use_hot_tier: bool = False, use_cold_tier: bool = False):
        """
        Get database connection from pool with schema routing (context manager)

        Args:
            use_hot_tier: Set search_path to memory_hot schema
            use_cold_tier: Set search_path to memory_cold schema

        Usage:
            # Unified schema (default)
            async with db.get_connection() as conn:
                result = await conn.fetch("SELECT * FROM internal_directives")

            # Hot tier schema
            async with db.get_connection(use_hot_tier=True) as conn:
                result = await conn.fetch("SELECT * FROM memory_hot")

        Yields:
            asyncpg.Connection with search_path set to appropriate schema
        """
        await self._ensure_pool_for_running_loop()

        if not self.pool:
            raise RuntimeError("Database pool not available")

        # Determine schema based on tier flags (priority: cold > hot > unified)
        if use_cold_tier:
            schema = 'memory_cold'
            tier_name = 'cold tier'
        elif use_hot_tier:
            schema = 'memory_hot'
            tier_name = 'hot tier'
        else:
            schema = 'unified'
            tier_name = 'unified'

        # Acquire connection from pool
        async with self.pool.acquire() as conn:
            self.metrics['total_connections'] += 1

            # Set search_path to route queries to appropriate schema
            # Include 'public' as fallback for extension types (vector, etc.)
            await conn.execute(f"SET search_path TO {schema}, public")

            try:
                yield conn
            finally:
                # Reset search_path to default after use
                await conn.execute("SET search_path TO public")

    async def execute_query(
        self,
        query: str,
        params: Optional[Union[Tuple, List]] = None,
        use_hot_tier: bool = False,
        use_cold_tier: bool = False,
        fetch_one: bool = False,
        fetch_all: bool = False,
        commit: bool = False
    ) -> Optional[Any]:
        """
        Execute SQL query with optional fetch/commit

        Args:
            query: SQL query to execute (use $1, $2, $3 placeholders)
            params: Query parameters (tuple or list)
            use_hot_tier: Use memory_hot schema
            use_cold_tier: Use memory_cold schema
            fetch_one: Fetch single row
            fetch_all: Fetch all rows
            commit: Commit transaction (asyncpg auto-commits by default)

        Returns:
            Query results if fetch_one/fetch_all, None otherwise

        Note:
            PostgreSQL uses $1, $2, $3 placeholders instead of MySQL's %s.
            asyncpg returns asyncpg.Record objects which behave like dicts.
        """
        await self._ensure_pool_for_running_loop()

        # Safety/ergonomics: if a caller issues a SELECT-like query without
        # fetch_one/fetch_all, automatically fetch_all to avoid returning None.
        # This prevents a common class of "NoneType is not iterable" bugs.
        try:
            autofetch = os.getenv("TORINAI_DB_AUTOFETCH_SELECT", "true").strip().lower() not in {"0", "false", "no", "off"}
            if autofetch and not fetch_one and not fetch_all:
                q = (query or "").lstrip().lower()
                if q.startswith("select") or q.startswith("with") or q.startswith("show") or q.startswith("explain"):
                    fetch_all = True
        except Exception:
            pass

        try:
            async with self.get_connection(use_hot_tier=use_hot_tier, use_cold_tier=use_cold_tier) as conn:
                # Execute query with asyncpg
                # asyncpg uses positional parameters: $1, $2, $3
                if params:
                    # Convert params to list if tuple
                    params_list = list(params) if isinstance(params, tuple) else params
                else:
                    params_list = []

                self.metrics['total_queries'] += 1
                if use_cold_tier:
                    self.metrics['cold_tier_queries'] += 1
                elif use_hot_tier:
                    self.metrics['hot_tier_queries'] += 1
                else:
                    self.metrics['unified_queries'] += 1

                # Fetch results based on mode
                result = None
                if fetch_one:
                    # fetchrow returns single Record or None
                    result = await conn.fetchrow(query, *params_list)
                    # Convert Record to dict for compatibility with MySQL version
                    if result:
                        result = dict(result)
                elif fetch_all:
                    # fetch returns list of Records
                    result = await conn.fetch(query, *params_list)
                    # Convert Records to dicts for compatibility
                    result = [dict(row) for row in result]
                else:
                    # asyncpg's execute() returns a status string such as
                    # "UPDATE 3" / "INSERT 0 1". It was being DISCARDED, so every
                    # write in the substrate returned None and no caller could
                    # tell a write that changed 3 rows from one that changed
                    # none. Capturing it is what lets update_memory() report an
                    # honest False when a row does not exist in the tier.
                    result = await conn.execute(query, *params_list)

                # Note: asyncpg auto-commits by default for non-transactional queries
                # commit parameter kept for API compatibility but is a no-op

                return result

        except Exception as e:
            logger.error(f"Query execution failed: {e}")
            logger.error(f"Query: {query}")
            logger.error(f"Params: {params}")
            self.metrics['failed_queries'] += 1

            # Send notification for query failure (respect grace window)
            if self._should_notify_error("query"):
                try:
                    from core.utils.notification_helpers import notify_database_error
                    asyncio.create_task(notify_database_error(
                        operation="query",
                        error=e,
                        database="PostgreSQL",
                        context={
                            "query": query[:200] if len(query) > 200 else query,
                            "tier": "cold" if use_cold_tier else ("hot" if use_hot_tier else "unified")
                        }
                    ))
                except Exception as notify_error:
                    logger.warning(f"Failed to send query error notification: {notify_error}")

            raise

    async def query(
        self,
        query: str,
        params: Optional[Tuple] = None,
        use_hot_tier: bool = False
    ) -> List[Dict[str, Any]]:
        """
        Execute SQL query and return all results as list of dicts

        This is a convenience method that wraps execute_query with fetch_all=True.
        Used by security tools and other components that need simple query access.

        Args:
            query: SQL query to execute (use $1, $2, $3 placeholders)
            params: Query parameters (tuple)
            use_hot_tier: Use memory_hot schema

        Returns:
            List of result rows as dictionaries
        """
        result = await self.execute_query(query, params, use_hot_tier=use_hot_tier, fetch_all=True)
        return result if result is not None else []

    async def execute_many(
        self,
        query: str,
        params_list: List[Tuple],
        use_hot_tier: bool = False,
        use_cold_tier: bool = False,
        commit: bool = True
    ) -> int:
        """
        Execute query with multiple parameter sets

        Args:
            query: SQL query to execute (use $1, $2, $3 placeholders)
            params_list: List of parameter tuples
            use_hot_tier: Use memory_hot schema
            use_cold_tier: Use memory_cold schema
            commit: Commit transaction (kept for API compatibility)

        Returns:
            Number of rows affected
        """
        await self._ensure_pool_for_running_loop()

        try:
            async with self.get_connection(use_hot_tier=use_hot_tier, use_cold_tier=use_cold_tier) as conn:
                # asyncpg executemany
                result = await conn.executemany(query, params_list)

                self.metrics['total_queries'] += len(params_list)
                if use_cold_tier:
                    self.metrics['cold_tier_queries'] += len(params_list)
                elif use_hot_tier:
                    self.metrics['hot_tier_queries'] += len(params_list)
                else:
                    self.metrics['unified_queries'] += len(params_list)

                # Return number of affected rows (executemany returns status string)
                return len(params_list)

        except Exception as e:
            logger.error(f"Execute many failed: {e}")
            logger.error(f"Query: {query}")
            self.metrics['failed_queries'] += 1

            # Send notification for execute many failure (respect grace window)
            if self._should_notify_error("execute_many"):
                try:
                    from core.utils.notification_helpers import notify_database_error
                    asyncio.create_task(notify_database_error(
                        operation="execute_many",
                        error=e,
                        database="PostgreSQL",
                        context={
                            "query": query[:200] if len(query) > 200 else query,
                            "batch_size": len(params_list),
                            "tier": "cold" if use_cold_tier else ("hot" if use_hot_tier else "unified")
                        }
                    ))
                except Exception as notify_error:
                    logger.warning(f"Failed to send execute many error notification: {notify_error}")

            raise

    async def table_exists(self, table_name: str, use_hot_tier: bool = False, use_cold_tier: bool = False) -> bool:
        """
        Check if table exists in schema

        Args:
            table_name: Table name to check
            use_hot_tier: Check in memory_hot schema
            use_cold_tier: Check in memory_cold schema

        Returns:
            True if table exists
        """
        # Determine schema name
        if use_cold_tier:
            schema = 'memory_cold'
        elif use_hot_tier:
            schema = 'memory_hot'
        else:
            schema = 'unified'

        result = await self.execute_query(
            """
            SELECT COUNT(*) as count
            FROM information_schema.tables
            WHERE table_schema = $1 AND table_name = $2
            """,
            params=(schema, table_name),
            fetch_one=True
        )

        return result['count'] > 0 if result else False

    async def create_database_if_not_exists(
        self,
        database_name: str
    ) -> bool:
        """
        Create database if it doesn't exist

        Args:
            database_name: Database name to create

        Returns:
            True if successful
        """
        try:
            # Connect to postgres default database to create new database
            temp_pool = await asyncpg.create_pool(
                host=self.host,
                port=self.port,
                user=self.user,
                password=self.password,
                database='postgres',  # Connect to default database
                min_size=1,
                max_size=1
            )

            async with temp_pool.acquire() as conn:
                # Check if database exists
                exists = await conn.fetchval(
                    "SELECT 1 FROM pg_database WHERE datname = $1",
                    database_name
                )

                if not exists:
                    # CREATE DATABASE cannot run in transaction, use execute directly
                    await conn.execute(f'CREATE DATABASE {database_name}')
                    logger.info(f"Database {database_name} created")
                else:
                    logger.info(f"Database {database_name} already exists")

            await temp_pool.close()
            return True

        except Exception as e:
            logger.error(f"Failed to create database {database_name}: {e}")
            return False

    async def execute_schema_file(
        self,
        schema_file: Path,
        use_hot_tier: bool = False
    ) -> bool:
        """
        Execute SQL schema file

        Args:
            schema_file: Path to SQL schema file
            use_hot_tier: Execute on memory_hot schema (kept for API compatibility)

        Returns:
            True if successful
        """
        if not schema_file.exists():
            logger.error(f"Schema file not found: {schema_file}")
            return False

        try:
            # Read schema file
            with open(schema_file, 'r', encoding='utf-8') as f:
                schema_sql = f.read()

            # Execute entire schema (PostgreSQL handles multi-statement execution)
            async with self.pool.acquire() as conn:
                await conn.execute(schema_sql)

            logger.info(f"Schema file executed: {schema_file.name}")
            return True

        except Exception as e:
            logger.error(f"Failed to execute schema file {schema_file}: {e}")
            return False

    async def get_metrics(self) -> Dict[str, Any]:
        """
        Get database metrics

        Returns:
            Dict with database metrics
        """
        pool_metrics = {}

        if self.pool:
            pool_metrics['unified'] = {
                'size': self.pool.get_size(),
                'min_size': self.pool.get_min_size(),
                'max_size': self.pool.get_max_size()
            }

        return {
            'initialized': self.initialized,
            'host': self.host,
            'port': self.port,
            'database': self.database,
            'pool_metrics': pool_metrics,
            'query_metrics': self.metrics.copy()
        }

    async def health_check(self) -> Dict[str, Any]:
        """
        Check database health

        Returns:
            Dict with health status
        """
        health = {
            'initialized': self.initialized,
            'pool_available': self.pool is not None,
            'unified_connection_ok': False,
            'hot_connection_ok': False,
            'cold_connection_ok': False,
            'pgvector_available': False,
            'errors': []
        }

        # Test unified schema connection
        if self.pool:
            try:
                result = await self.execute_query(
                    "SELECT 1 as test",
                    fetch_one=True
                )
                health['unified_connection_ok'] = result is not None
            except Exception as e:
                health['errors'].append(f"Unified connection test failed: {e}")

        # Test hot tier schema connection
        if self.pool:
            try:
                result = await self.execute_query(
                    "SELECT 1 as test",
                    use_hot_tier=True,
                    fetch_one=True
                )
                health['hot_connection_ok'] = result is not None
            except Exception as e:
                health['errors'].append(f"Hot tier connection test failed: {e}")

        # Test cold tier schema connection
        if self.pool:
            try:
                result = await self.execute_query(
                    "SELECT 1 as test",
                    use_cold_tier=True,
                    fetch_one=True
                )
                health['cold_connection_ok'] = result is not None
            except Exception as e:
                health['errors'].append(f"Cold tier connection test failed: {e}")

        # Test pgvector extension
        if self.pool:
            try:
                async with self.pool.acquire() as conn:
                    result = await conn.fetchval(
                        "SELECT 1 FROM pg_extension WHERE extname = 'vector'"
                    )
                    health['pgvector_available'] = result is not None
            except Exception as e:
                health['errors'].append(f"pgvector test failed: {e}")

        health['healthy'] = (
            health['unified_connection_ok'] and
            health['hot_connection_ok'] and
            health['cold_connection_ok'] and
            health['pgvector_available'] and
            len(health['errors']) == 0
        )

        return health

    async def close(self) -> None:
        """
        Close database connection pool

        Closes the single connection pool and releases all connections.
        """
        if self.pool:
            await self.pool.close()
            logger.info("PostgreSQL database pool closed")

        self.initialized = False
        logger.info("Database connections closed")

    async def __aenter__(self):
        """Async context manager entry"""
        await self._ensure_pool_for_running_loop()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        await self.close()


# Convenience alias
TorinUnifiedDatabase = TorinUnifiedDatabasePostgres

async def get_unified_database() -> TorinUnifiedDatabasePostgres:
    """
    Get singleton instance of unified database.

    NOTE: This does NOT auto-initialize. The database must be initialized
    separately at startup via main.py or service initialization.

    The class itself is a singleton via __new__.

    Returns:
        TorinUnifiedDatabasePostgres singleton instance (may not be initialized)
    """
    return TorinUnifiedDatabasePostgres()


# Alias for shorter name
get_unified_db = get_unified_database
