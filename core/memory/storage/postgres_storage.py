#!/usr/bin/env python3
"""
PostgreSQL Hot and Cold Tier Storage with pgvector

Stores memories in PostgreSQL with hot/cold tier architecture and native vector embeddings:
- Hot tier (memory_hot schema): Last 60 days for fast access with pgvector semantic search
- Cold tier (memory_cold schema): 60+ days for long-term archival with pgvector semantic search

Schema:
- memory_hot.memory_hot: Hot tier memory storage with cognitive state tracking + vector(384) embeddings
- memory_cold.memory_cold: Cold tier archived memories + vector(384) embeddings
- memory_hot.archive_log: Tracks archival operations

Architecture:
- Single PostgreSQL database (torinai_db) with 3 logical schemas
- Hot tier: memory_hot schema for last 60 days (fast access, HNSW indexes)
- Cold tier: memory_cold schema for 60+ day old memories (archival, long-term storage)
- pgvector: 100x faster semantic search via native vector operations

Performance:
- Semantic similarity search: 5,000ms (MySQL Python loop) → 50ms (pgvector HNSW index)
"""

from core.capability import raise_if_structural
import logging
import json
import uuid
from typing import Dict, Any, List, Optional, Set, Tuple
from datetime import datetime, timedelta
from dataclasses import asdict

from core.database.unified_database_postgres import TorinUnifiedDatabasePostgres
from core.memory.utils.interfaces import (
    MemoryItem,
    MemoryType,
    MemoryStatus,
    MemoryPriority
)

logger = logging.getLogger(__name__)



def _vector_literal(embeddings):
    """Render an embedding as a pgvector literal, or None when there is none.

    Two hazards, both of which broke hot->cold migration outright:
      - `if embeddings` on a numpy array raises "truth value of an array with
        more than one element is ambiguous", and the handler turned that into a
        bare False, so migration failed for every memory carrying an embedding.
      - str() of an array of numpy scalars yields "[np.float32(-0.066), ...]",
        which pgvector rejects as invalid vector syntax.

    Coerced to plain floats so the literal is valid whatever the source type.
    """
    if embeddings is None:
        return None
    try:
        if len(embeddings) == 0:
            return None
        return "[" + ",".join(repr(float(x)) for x in embeddings) + "]"
    except (TypeError, ValueError):
        return None


def _json_field(row, key):
    """Read an optional JSONB column that may arrive as str, dict or absent."""
    import json as _json
    try:
        v = row[key]
    except (KeyError, TypeError, IndexError):
        return None
    if v is None:
        return None
    if isinstance(v, str):
        try:
            return _json.loads(v)
        except ValueError:
            return None
    return v

class PostgresStorage:
    """
    PostgreSQL Hot and Cold Tier Storage for Memories with pgvector

    Stores memories in PostgreSQL with hot/cold tier architecture.
    Hot tier: last 60 days (memory_hot schema) with pgvector HNSW indexes
    Cold tier: 60+ days (memory_cold schema) with pgvector HNSW indexes

    Provides cognitive state tracking and 100x faster semantic search.

    Integration:
    - Automatically archives 60+ day old memories to cold tier
    - Stores embeddings as native vector(384) for fast similarity search
    - Uses pgvector <=> operator for cosine distance (IN DATABASE, not Python!)
    - Tags for categorical retrieval
    """

    def __init__(
        self,
        db: Optional[TorinUnifiedDatabasePostgres] = None,
        retention_days: int = 60
    ):
        """
        Initialize PostgreSQL storage

        Args:
            db: Database instance (creates new if None)
            retention_days: Days to retain in hot tier (default 60)
        """
        self.db = db or TorinUnifiedDatabasePostgres()
        self.retention_days = retention_days
        self.initialized = False

        # Metrics
        self.metrics = {
            'memories_stored': 0,
            'memories_retrieved': 0,
            'memories_deleted': 0,
            'memories_archived': 0,
            'failed_operations': 0,
            'total_size_bytes': 0
        }

        logger.info(
            f"PostgresStorage initialized "
            f"(retention: {retention_days} days)"
        )

    async def initialize(self) -> bool:
        """
        Initialize database and verify tables exist

        Returns:
            True if successful
        """
        if self.initialized:
            return True

        try:
            await self.db.initialize()

            # Verify tables exist (they should from postgres_schemas.sql)
            hot_exists = await self.db.table_exists('memory_hot', use_hot_tier=True)
            cold_exists = await self.db.table_exists('memory_cold', use_cold_tier=True)
            archive_log_exists = await self.db.table_exists('archive_log', use_hot_tier=True)

            if not hot_exists:
                logger.warning("memory_hot table doesn't exist - run postgres_schemas.sql")
            if not cold_exists:
                logger.warning("memory_cold table doesn't exist - run postgres_schemas.sql")
            if not archive_log_exists:
                logger.warning("archive_log table doesn't exist - run postgres_schemas.sql")

            self.initialized = True
            logger.info("PostgresStorage initialized successfully")
            return True

        except Exception as e:
            logger.error(f"PostgresStorage initialization failed: {e}")
            self.metrics['failed_operations'] += 1
            return False

    async def store_memory(self, memory: MemoryItem) -> bool:
        """
        Store memory in hot tier with pgvector embedding

        Args:
            memory: MemoryItem to store

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
            # Serialize complex fields to JSONB
            content_json = json.dumps(memory.content)
            thinking_state_json = json.dumps(memory.thinking_state) if memory.thinking_state else None
            system_state_json = json.dumps(memory.system_state) if memory.system_state else None
            emotional_context_json = json.dumps(memory.emotional_context) if memory.emotional_context else None
            reasoning_trace_json = json.dumps(memory.reasoning_trace) if memory.reasoning_trace else None
            decision_factors_json = json.dumps(memory.decision_factors) if memory.decision_factors else None
            metadata_json = json.dumps(memory.metadata) if memory.metadata else None
            related_memories_json = json.dumps(memory.related_memories) if memory.related_memories else None

            # Same numpy truthiness hazard as the cold-tier insert: a stored
            # memory read back carries an array, and `if array` raises.
            embeddings = _vector_literal(memory.embeddings)

            # Tags as JSONB array
            tags_json = json.dumps(list(memory.tags)) if memory.tags else None
            memory_admission_json = (json.dumps(memory.memory_admission)
                                     if getattr(memory, 'memory_admission', None) else None)
            appraisal_snapshot_json = (json.dumps(memory.appraisal_snapshot)
                                       if getattr(memory, 'appraisal_snapshot', None) else None)

            # Convert timestamps
            created_at = datetime.fromtimestamp(memory.created_at) if isinstance(memory.created_at, (int, float)) else memory.created_at
            last_accessed = None
            if memory.last_accessed:
                last_accessed = datetime.fromtimestamp(memory.last_accessed) if isinstance(memory.last_accessed, (int, float)) else memory.last_accessed

            # Insert or update using PostgreSQL ON CONFLICT
            await self.db.execute_query(
                """
                INSERT INTO memory_hot (
                    memory_id,
                    memory_type,
                    content,
                    created_at,
                    last_accessed,
                    importance_score,
                    confidence_score,
                    status,
                    thinking_state,
                    system_state,
                    emotional_context,
                    reasoning_trace,
                    decision_factors,
                    memory_admission,
                    appraisal_snapshot,
                    embedding,
                    metadata,
                    related_memories,
                    tags,
                    access_count,
                    user_id,
                    session_id
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16::text::vector, $17, $18, $19, $20, $21, $22)
                ON CONFLICT (memory_id) DO UPDATE SET
                    content = EXCLUDED.content,
                    last_accessed = EXCLUDED.last_accessed,
                    importance_score = EXCLUDED.importance_score,
                    confidence_score = EXCLUDED.confidence_score,
                    status = EXCLUDED.status,
                    thinking_state = EXCLUDED.thinking_state,
                    system_state = EXCLUDED.system_state,
                    emotional_context = EXCLUDED.emotional_context,
                    reasoning_trace = EXCLUDED.reasoning_trace,
                    decision_factors = EXCLUDED.decision_factors,
                    memory_admission = EXCLUDED.memory_admission,
                    appraisal_snapshot = EXCLUDED.appraisal_snapshot,
                    embedding = EXCLUDED.embedding,
                    metadata = EXCLUDED.metadata,
                    related_memories = EXCLUDED.related_memories,
                    tags = EXCLUDED.tags,
                    access_count = memory_hot.access_count + 1
                """,
                (
                    memory.memory_id,
                    memory.memory_type.value,
                    content_json,
                    created_at,
                    last_accessed,
                    memory.importance_score,
                    memory.confidence_score,
                    memory.status.value,
                    thinking_state_json,
                    system_state_json,
                    emotional_context_json,
                    reasoning_trace_json,
                    decision_factors_json,
                    memory_admission_json,
                    appraisal_snapshot_json,
                    embeddings,  # pgvector handles list → vector conversion
                    metadata_json,
                    related_memories_json,
                    tags_json,
                    memory.access_count,
                    memory.user_id if hasattr(memory, 'user_id') else None,
                    memory.session_id if hasattr(memory, 'session_id') else None
                ),
                use_hot_tier=True,
                commit=True
            )

            self.metrics['memories_stored'] += 1
            self.metrics['total_size_bytes'] += len(content_json)

            logger.debug(f"Stored memory: {memory.memory_id} ({memory.memory_type.value})")
            return True

        except Exception as e:
            logger.error(f"Failed to store memory: {e}")
            self.metrics['failed_operations'] += 1

            # Send notification for memory storage failure
            try:
                from core.utils.notification_helpers import notify_memory_event
                import asyncio
                asyncio.create_task(notify_memory_event(
                    event_type="storage_error",
                    details=f"**Failed to store memory**\n\n**Error:** {str(e)}\n**Memory Type:** {memory.memory_type if hasattr(memory, 'memory_type') else 'unknown'}",
                    severity="error"
                ))
            except Exception as notify_error:
                logger.warning(f"Failed to send memory storage error notification: {notify_error}")

            return False

    async def get_memory(self, memory_id: str) -> Optional[MemoryItem]:
        """
        Retrieve memory by ID

        Args:
            memory_id: Memory identifier

        Returns:
            MemoryItem or None if not found
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
            # Get memory from memory_hot table
            row = await self.db.execute_query(
                "SELECT * FROM memory_hot WHERE memory_id = $1",
                (memory_id,),
                use_hot_tier=True,
                fetch_one=True
            )

            if not row:
                return None

            # Update access count and last_accessed
            await self.db.execute_query(
                """
                UPDATE memory_hot
                SET access_count = access_count + 1,
                    last_accessed = CURRENT_TIMESTAMP
                WHERE memory_id = $1
                """,
                (memory_id,),
                use_hot_tier=True,
                commit=True
            )

            # Parse row into MemoryItem
            memory = self._row_to_memory_item(row)

            self.metrics['memories_retrieved'] += 1
            return memory

        except Exception as e:
            logger.error(f"Failed to get memory: {e}")
            self.metrics['failed_operations'] += 1

            # Send notification for memory retrieval failure
            try:
                from core.utils.notification_helpers import notify_memory_event
                import asyncio
                asyncio.create_task(notify_memory_event(
                    event_type="retrieval_error",
                    details=f"**Failed to retrieve memory**\n\n**Error:** {str(e)}\n**Memory ID:** {memory_id}",
                    severity="error"
                ))
            except Exception as notify_error:
                logger.warning(f"Failed to send memory retrieval error notification: {notify_error}")

            return None

    async def update_memory(
        self,
        memory_id: str,
        updates: Dict[str, Any],
        tier: Optional[str] = None
    ) -> bool:
        """
        Update memory fields in PostgreSQL

        Args:
            memory_id: Memory identifier
            updates: Dictionary of fields to update
            tier: Tier hint (ignored, always updates hot tier)

        Returns:
            True if successful, False otherwise
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
            # Build UPDATE query dynamically
            set_clauses = []
            params = []
            param_idx = 1

            for key, value in updates.items():
                if key == "access_count":
                    set_clauses.append(f"access_count = access_count + ${param_idx}")
                    params.append(value)
                    param_idx += 1
                elif key == "last_accessed":
                    set_clauses.append(f"last_accessed = ${param_idx}")
                    params.append(value)
                    param_idx += 1
                elif key == "importance_score":
                    set_clauses.append(f"importance_score = ${param_idx}")
                    params.append(value)
                    param_idx += 1
                elif key == "tags":
                    set_clauses.append(f"tags = ${param_idx}::jsonb")
                    params.append(json.dumps(list(value)) if isinstance(value, (list, set)) else value)
                    param_idx += 1
                elif key == "metadata":
                    # PostgreSQL has JSONB merge operator ||
                    if updates.get("metadata.merge", False):
                        # COALESCE is load-bearing: `NULL || '{...}'::jsonb` is
                        # NULL, not the right-hand side. Most rows are written
                        # with metadata NULL, so a merge into one silently
                        # erased the update while UPDATE still reported one row
                        # affected -- the write returned True and stored
                        # nothing, which is indistinguishable from a merge that
                        # worked until something later reads the key back.
                        set_clauses.append(
                            f"metadata = COALESCE(metadata, '{{}}'::jsonb) || ${param_idx}::jsonb")
                    else:
                        set_clauses.append(f"metadata = ${param_idx}::jsonb")
                    params.append(json.dumps(value) if isinstance(value, dict) else value)
                    param_idx += 1
                elif key == "related_memories":
                    set_clauses.append(f"related_memories = ${param_idx}::jsonb")
                    params.append(json.dumps(value) if isinstance(value, list) else value)
                    param_idx += 1

            if not set_clauses:
                return True  # No updates

            params.append(memory_id)  # WHERE clause parameter

            query = f"UPDATE memory_hot SET {', '.join(set_clauses)} WHERE memory_id = ${param_idx}"

            # Writes used to target memory_hot ONLY and return True
            # unconditionally. Retrieval now spans both tiers, so a caller can
            # legitimately hold a COLD MemoryItem — and updating it matched zero
            # rows while reporting success. A write that changes nothing must
            # never report that it did.
            status = await self.db.execute_query(
                query,
                tuple(params),
                use_hot_tier=True,
                commit=True
            )
            if self._rows_affected(status) > 0:
                return True

            # Not in hot — try the cold tier before declaring failure.
            cold_query = query.replace("UPDATE memory_hot SET", "UPDATE memory_cold SET", 1)
            status = await self.db.execute_query(
                cold_query,
                tuple(params),
                use_cold_tier=True,
                commit=True
            )
            if self._rows_affected(status) > 0:
                return True

            logger.warning(
                "update_memory(%s): matched 0 rows in either tier — no field was "
                "written", memory_id
            )
            return False

        except Exception as e:
            logger.error(f"Failed to update memory {memory_id}: {e}")
            self.metrics['failed_operations'] += 1
            return False

    async def store_batch(
        self,
        memories: List[MemoryItem],
        batch_size: int = 100
    ) -> bool:
        """
        Batch store memories efficiently

        Args:
            memories: List of MemoryItem objects
            batch_size: Number of memories per batch

        Returns:
            True if all succeeded, False otherwise
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
            # Process in batches
            for i in range(0, len(memories), batch_size):
                batch = memories[i:i + batch_size]

                # Store each memory individually (could optimize with execute_many)
                for memory in batch:
                    success = await self.store_memory(memory)
                    if not success:
                        return False

            return True

        except Exception as e:
            logger.error(f"Failed to store batch: {e}")
            self.metrics['failed_operations'] += 1
            return False

    async def search_by_content(
        self,
        content: str,
        exact_match: bool = False,
        limit: int = 10
    ) -> List[MemoryItem]:
        """
        Search memories by content string

        Args:
            content: Content to search for
            exact_match: Use exact matching (default: LIKE fuzzy match)
            limit: Maximum results

        Returns:
            List of matching MemoryItem objects
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
            if exact_match:
                rows = await self.db.execute_query(
                    "SELECT * FROM memory_hot WHERE content = $1 LIMIT $2",
                    (content, limit),
                    use_hot_tier=True,
                    fetch_all=True
                )
            else:
                rows = await self.db.execute_query(
                    "SELECT * FROM memory_hot WHERE content LIKE $1 LIMIT $2",
                    (f"%{content}%", limit),
                    use_hot_tier=True,
                    fetch_all=True
                )

            return [self._row_to_memory_item(row) for row in rows]

        except Exception as e:
            # `except` must not turn a wiring defect into an empty result.
            raise_if_structural(e, 'postgres_storage.search_by_content')
            logger.error(f"Failed to search by content: {e}")
            self.metrics['failed_operations'] += 1
            return []

    async def update_metadata(
        self,
        key: str,
        value: Any,
        metadata: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Update system configuration metadata

        Args:
            key: Configuration key
            value: Configuration value
            metadata: Additional metadata

        Returns:
            True if successful
        """
        # Store in a config table (would need to create)
        logger.warning(f"update_metadata not fully implemented - key: {key}, value: {value}")
        return True

    # A hot-tier hit gets a small ranking nudge to reflect recency/latency.
    # It is a PRIOR, never an eligibility gate: a relevant cold memory must be
    # able to outrank an irrelevant hot one.
    HOT_TIER_RANKING_PRIOR = 0.02

    def _scope_tables(self, scope: 'RetrievalScope') -> List[Tuple[str, float]]:
        """Resolve a scope into (fully-qualified table, tier prior) pairs.

        Callers name what they need to remember; the storage layer decides which
        tiers that implies. No consumer should have to know a schema name.
        """
        from ..utils.interfaces import RetrievalScope

        hot = ('memory_hot.memory_hot', self.HOT_TIER_RANKING_PRIOR)
        cold = ('memory_cold.memory_cold', 0.0)

        if scope == RetrievalScope.RECENT:
            return [hot]
        return [hot, cold]  # HISTORICAL and ALL

    async def search_memories(
        self,
        memory_type: Optional[MemoryType] = None,
        tags: Optional[Set[str]] = None,
        time_window_start: Optional[float] = None,
        time_window_end: Optional[float] = None,
        min_importance: Optional[float] = None,
        status: Optional[MemoryStatus] = None,
        limit: int = 100,
        scope: Optional['RetrievalScope'] = None,
    ) -> List[MemoryItem]:
        """
        Search memories with filters

        Args:
            memory_type: Filter by memory type
            tags: Filter by tags (any match)
            time_window_start: Start timestamp
            time_window_end: End timestamp
            min_importance: Minimum importance score
            status: Filter by status
            limit: Maximum results

        Returns:
            List of MemoryItem objects
        """
        if not self.initialized:
            # The result is CHECKED. Discarding it meant a failed initialize was
            # followed by the work it was meant to enable, and the real failure
            # resurfaced later disguised as something else.
            if await self.initialize() is False:
                raise RuntimeError(
                    type(self).__name__ + ' could not initialize; refusing to '
                    'continue as though it had')

        from ..utils.interfaces import RetrievalScope
        if scope is None:
            scope = RetrievalScope.HISTORICAL

        try:
            # Build the shared predicate once, then apply it to every table the
            # scope resolves to. Tables are fully qualified so the result does
            # not depend on the connection's search_path.
            predicate = ""
            params = []
            param_idx = 1

            if memory_type:
                predicate += f" AND memory_type = ${param_idx}"
                params.append(memory_type.value)
                param_idx += 1

            # Search tags using JSONB @> operator (contains)
            if tags:
                for tag in tags:
                    predicate += f" AND tags @> ${param_idx}::jsonb"
                    params.append(json.dumps([tag]))
                    param_idx += 1

            if time_window_start:
                predicate += f" AND created_at >= to_timestamp(${param_idx})"
                params.append(time_window_start)
                param_idx += 1

            if time_window_end:
                predicate += f" AND created_at <= to_timestamp(${param_idx})"
                params.append(time_window_end)
                param_idx += 1

            if min_importance:
                predicate += f" AND importance_score >= ${param_idx}"
                params.append(min_importance)
                param_idx += 1

            if status:
                predicate += f" AND status = ${param_idx}"
                params.append(status.value)
                param_idx += 1

            branches = [
                f"SELECT *, {prior}::float8 AS tier_prior "
                f"FROM {table} WHERE 1=1{predicate}"
                for table, prior in self._scope_tables(scope)
            ]

            # DISTINCT ON collapses a memory that exists in both tiers to a
            # single row, preferring the hot copy (higher tier_prior).
            query = (
                "WITH candidates AS (" + " UNION ALL ".join(branches) + "), "
                "deduped AS ("
                "  SELECT DISTINCT ON (memory_id) * FROM candidates"
                "  ORDER BY memory_id, tier_prior DESC"
                ") "
                f"SELECT * FROM deduped ORDER BY created_at DESC LIMIT ${param_idx}"
            )
            params.append(limit)

            rows = await self.db.execute_query(
                query,
                tuple(params),
                fetch_all=True
            )

            # Parse rows into MemoryItems
            memories = []
            for row in rows:
                memory = self._row_to_memory_item(row)
                if memory:
                    memories.append(memory)

            self.metrics['memories_retrieved'] += len(memories)
            return memories

        except Exception as e:
            # `except` must not turn a wiring defect into an empty result.
            raise_if_structural(e, 'postgres_storage.search_memories')
            logger.error(f"Failed to search memories: {e}")
            self.metrics['failed_operations'] += 1
            return []

    async def semantic_search(
        self,
        query_embedding: List[float],
        memory_type: Optional[MemoryType] = None,
        min_similarity: float = 0.7,
        limit: int = 10,
        scope: Optional['RetrievalScope'] = None,
        actor: Optional[str] = None,
    ) -> List[MemoryItem]:
        """
        Semantic similarity search using pgvector (100x faster than MySQL!)

        Args:
            query_embedding: Query embedding vector
            memory_type: Filter by memory type
            min_similarity: Minimum similarity threshold (0.0-1.0)
            limit: Maximum results

        Returns:
            List of MemoryItem objects sorted by similarity
        """
        if not self.initialized:
            # The result is CHECKED. Discarding it meant a failed initialize was
            # followed by the work it was meant to enable, and the real failure
            # resurfaced later disguised as something else.
            if await self.initialize() is False:
                raise RuntimeError(
                    type(self).__name__ + ' could not initialize; refusing to '
                    'continue as though it had')

        from ..utils.interfaces import RetrievalScope
        if scope is None:
            scope = RetrievalScope.HISTORICAL

        try:
            # pgvector cosine distance operator (<=>): 0 = identical, 2 = opposite.
            # Cosine similarity = 1 - distance.
            #
            # Candidates are drawn from every tier in scope and ranked together.
            # Eligibility depends ONLY on similarity; the tier prior can reorder
            # near-ties but can never exclude a memory for being old.
            params = [str(query_embedding)]
            param_idx = 2

            predicate = ""
            if memory_type:
                predicate += f" AND memory_type = ${param_idx}"
                params.append(memory_type.value)
                param_idx += 1

            # WHOSE MEMORIES MAY ENTER THIS COGNITION.
            #
            # `actor` is the task's owner. A task acting FOR A USER may see that
            # user's memories and the substrate's own shared knowledge -- never
            # another user's. A task that is the SUBSTRATE'S OWN work (actor
            # None or the substrate id) sees only the substrate's memories:
            # health, security and idle-loop cognition must not be coloured by
            # whoever happened to be connected.
            #
            # Rows written before actors existed carry NULL/'' and are the
            # substrate's by default -- 908 such rows today -- so they surface
            # for the substrate and for no user. The columns exist; this is the
            # first code to read them.
            from core.agents.autonomous.shared_types import (SUBSTRATE_ACTOR,
                                                             is_substrate_actor)
            if is_substrate_actor(actor):
                predicate += (f" AND (user_id IS NULL OR user_id = '' "
                              f"OR user_id = ${param_idx})")
                params.append(SUBSTRATE_ACTOR)
                param_idx += 1
            else:
                predicate += (f" AND (user_id = ${param_idx} "
                              f"OR user_id IS NULL OR user_id = '' "
                              f"OR user_id = ${param_idx + 1})")
                params.append(actor)
                params.append(SUBSTRATE_ACTOR)
                param_idx += 2

            sim = "1 - (embedding <=> $1::text::vector)"
            branches = [
                f"SELECT *, {sim} AS similarity, {prior}::float8 AS tier_prior "
                f"FROM {table} WHERE embedding IS NOT NULL{predicate}"
                for table, prior in self._scope_tables(scope)
            ]

            query = (
                "WITH candidates AS (" + " UNION ALL ".join(branches) + "), "
                "deduped AS ("
                "  SELECT DISTINCT ON (memory_id) * FROM candidates"
                "  ORDER BY memory_id, tier_prior DESC"
                ") "
                f"SELECT * FROM deduped WHERE similarity >= ${param_idx} "
                f"ORDER BY (similarity + tier_prior) DESC LIMIT ${param_idx + 1}"
            )
            params.append(min_similarity)
            params.append(limit)

            rows = await self.db.execute_query(
                query,
                tuple(params),
                fetch_all=True
            )

            # Parse rows into MemoryItems with similarity scores
            results = []
            for row in rows:
                memory = self._row_to_memory_item(row)
                if memory:
                    # Add similarity score from query result
                    memory.similarity_score = row['similarity']
                    results.append(memory)

            logger.info(f"pgvector semantic search found {len(results)} results (similarity >= {min_similarity})")
            return results

        except Exception as e:
            logger.error(f"pgvector semantic search failed: {e}")
            self.metrics['failed_operations'] += 1
            return []

    async def delete_memory(self, memory_id: str) -> bool:
        """
        Delete memory from hot tier

        Args:
            memory_id: Memory identifier

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
                "DELETE FROM memory_hot WHERE memory_id = $1",
                (memory_id,),
                use_hot_tier=True,
                commit=True
            )

            self.metrics['memories_deleted'] += 1
            logger.debug(f"Deleted memory: {memory_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to delete memory: {e}")
            self.metrics['failed_operations'] += 1
            return False

    async def get_old_memories(
        self,
        older_than_days: Optional[int] = None
    ) -> List[str]:
        """
        Get memory IDs older than specified days (for archival)

        Args:
            older_than_days: Age threshold (uses self.retention_days if None)

        Returns:
            List of memory IDs
        """
        if not self.initialized:
            # The result is CHECKED. Discarding it meant a failed initialize was
            # followed by the work it was meant to enable, and the real failure
            # resurfaced later disguised as something else.
            if await self.initialize() is False:
                raise RuntimeError(
                    type(self).__name__ + ' could not initialize; refusing to '
                    'continue as though it had')

        age_threshold = older_than_days or self.retention_days

        try:
            cutoff_date = datetime.now() - timedelta(days=age_threshold)

            rows = await self.db.execute_query(
                """
                SELECT memory_id FROM memory_hot
                WHERE created_at < $1
                ORDER BY created_at ASC
                """,
                (cutoff_date,),
                use_hot_tier=True,
                fetch_all=True
            )

            return [row['memory_id'] for row in rows]

        except Exception as e:
            # `except` must not turn a wiring defect into an empty result.
            raise_if_structural(e, 'postgres_storage.get_old_memories')
            logger.error(f"Failed to get old memories: {e}")
            return []

    async def get_memory_from_cold(self, memory_id: str) -> Optional[MemoryItem]:
        """
        Retrieve memory from cold tier

        Args:
            memory_id: Memory identifier

        Returns:
            MemoryItem or None if not found
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
            row = await self.db.execute_query(
                "SELECT * FROM memory_cold WHERE memory_id = $1",
                (memory_id,),
                use_cold_tier=True,
                fetch_one=True
            )

            if not row:
                return None

            memory = self._row_to_memory_item(row)
            self.metrics['memories_retrieved'] += 1
            return memory

        except Exception as e:
            logger.error(f"Failed to get memory from cold tier: {e}")
            self.metrics['failed_operations'] += 1
            return None

    async def migrate_to_cold(self, memory_id: str) -> bool:
        """
        Migrate memory from hot tier to cold tier

        Args:
            memory_id: Memory identifier

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
            # Get memory from hot tier
            memory = await self.get_memory(memory_id)
            if not memory:
                logger.warning(f"Memory {memory_id} not found in hot tier")
                return False

            # Prepare data for cold tier
            created_at = datetime.fromtimestamp(memory.created_at) if isinstance(memory.created_at, (int, float)) else memory.created_at
            last_accessed = None
            if memory.last_accessed:
                last_accessed = datetime.fromtimestamp(memory.last_accessed) if isinstance(memory.last_accessed, (int, float)) else memory.last_accessed

            # Store to cold tier with pgvector embedding
            await self.db.execute_query(
                """
                INSERT INTO memory_cold (
                    memory_id, memory_type, content, embedding,
                    created_at, last_accessed, importance_score,
                    confidence_score, status, access_count,
                    thinking_state, emotional_context, reasoning_trace,
                    decision_factors, tags, related_memories, metadata,
                    user_id, session_id, system_state, memory_admission,
                    appraisal_snapshot
                ) VALUES (
                    $1, $2, $3, $4::text::vector, $5, $6, $7, $8, $9, $10,
                    $11, $12, $13, $14, $15, $16, $17, $18, $19, $20, $21, $22
                )
                """,
                (
                    memory.memory_id,
                    memory.memory_type.value if memory.memory_type else None,
                    json.dumps(memory.content),
                    # `if memory.embeddings` on a numpy array raises
                    # "truth value of an array ... is ambiguous", and the
                    # handler turned that into a bare False -- so hot->cold
                    # migration failed for every memory carrying an
                    # embedding, which is all of them. Length-tested instead.
                    _vector_literal(memory.embeddings),
                    created_at,
                    last_accessed,
                    memory.importance_score,
                    memory.confidence_score,
                    memory.status.value if memory.status else None,
                    memory.access_count,
                    json.dumps(memory.thinking_state) if memory.thinking_state else None,
                    json.dumps(memory.emotional_context) if memory.emotional_context else None,
                    json.dumps(memory.reasoning_trace) if memory.reasoning_trace else None,
                    json.dumps(memory.decision_factors) if memory.decision_factors else None,
                    json.dumps(list(memory.tags)) if memory.tags else None,
                    json.dumps(memory.related_memories) if memory.related_memories else None,
                    json.dumps(memory.metadata) if memory.metadata else None,
                    memory.user_id,
                    memory.session_id,
                    json.dumps(memory.system_state) if memory.system_state else None,
                    (json.dumps(memory.memory_admission)
                     if getattr(memory, 'memory_admission', None) else None),
                    (json.dumps(memory.appraisal_snapshot)
                     if getattr(memory, 'appraisal_snapshot', None) else None)
                ),
                use_cold_tier=True,
                commit=True
            )

            # Delete from hot tier
            await self.delete_memory(memory_id)

            self.metrics['memories_archived'] += 1
            logger.info(f"Migrated memory {memory_id} to cold tier")
            return True

        except Exception as e:
            logger.error(f"Failed to migrate memory to cold tier: {e}")
            self.metrics['failed_operations'] += 1
            return False

    async def restore_from_cold(self, memory_id: str) -> bool:
        """
        Restore memory from cold tier to hot tier

        Args:
            memory_id: Memory identifier

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
            # Get memory from cold tier
            memory = await self.get_memory_from_cold(memory_id)
            if not memory:
                logger.warning(f"Memory {memory_id} not found in cold tier")
                return False

            # Store to hot tier
            success = await self.store_memory(memory)
            if not success:
                return False

            # Delete from cold tier
            await self.db.execute_query(
                "DELETE FROM memory_cold WHERE memory_id = $1",
                (memory_id,),
                use_cold_tier=True,
                commit=True
            )

            logger.info(f"Restored memory {memory_id} from cold tier")
            return True

        except Exception as e:
            logger.error(f"Failed to restore memory from cold tier: {e}")
            self.metrics['failed_operations'] += 1
            return False

    async def log_archive(
        self,
        memory_id: str,
        size_bytes: int
    ) -> bool:
        """
        Log memory archival to cold tier

        Args:
            memory_id: Memory identifier
            size_bytes: Memory size in bytes

        Returns:
            True if successful
        """
        try:
            await self.db.execute_query(
                """
                INSERT INTO archive_log (memory_id, archived_at, size_bytes)
                VALUES ($1, CURRENT_TIMESTAMP, $2)
                """,
                (memory_id, size_bytes),
                use_hot_tier=True,
                commit=True
            )
            return True

        except Exception as e:
            logger.error(f"Failed to log archive: {e}")
            return False

    async def get_statistics(self) -> Dict[str, Any]:
        """
        Get storage statistics

        Returns:
            Dict with storage statistics
        """
        try:
            # Total memories
            total_result = await self.db.execute_query(
                "SELECT COUNT(*) as count FROM memory_hot",
                use_hot_tier=True,
                fetch_one=True
            )
            total_count = total_result['count'] if total_result else 0

            # Memories by type
            type_rows = await self.db.execute_query(
                """
                SELECT memory_type, COUNT(*) as count
                FROM memory_hot
                GROUP BY memory_type
                """,
                use_hot_tier=True,
                fetch_all=True
            )
            by_type = {row['memory_type']: row['count'] for row in type_rows}

            # Memories by status
            status_rows = await self.db.execute_query(
                """
                SELECT status, COUNT(*) as count
                FROM memory_hot
                GROUP BY status
                """,
                use_hot_tier=True,
                fetch_all=True
            )
            by_status = {row['status']: row['count'] for row in status_rows}

            # Average importance
            avg_result = await self.db.execute_query(
                "SELECT AVG(importance_score) as avg_importance FROM memory_hot",
                use_hot_tier=True,
                fetch_one=True
            )
            avg_importance = float(avg_result['avg_importance']) if avg_result and avg_result['avg_importance'] else 0.0

            # Oldest memory
            oldest_result = await self.db.execute_query(
                "SELECT MIN(created_at) as oldest_memory FROM memory_hot",
                use_hot_tier=True,
                fetch_one=True
            )
            oldest_memory = oldest_result['oldest_memory'] if oldest_result else None

            return {
                'total_memories': total_count,
                'by_type': by_type,
                'by_status': by_status,
                'avg_importance': avg_importance,
                'oldest_memory': oldest_memory.isoformat() if oldest_memory else None,
                'retention_days': self.retention_days,
                'metrics': self.metrics.copy()
            }

        except Exception as e:
            logger.error(f"Failed to get statistics: {e}")
            return {'error': str(e), 'metrics': self.metrics.copy()}

    @staticmethod
    def _rows_affected(status) -> int:
        """Rows touched by an UPDATE. asyncpg returns a status like 'UPDATE 3'.

        Returning 0 on an unparsable status is deliberate: an unknown result is
        not evidence the write landed.
        """
        try:
            if isinstance(status, str) and status.upper().startswith("UPDATE"):
                return int(status.split()[-1])
        except (ValueError, IndexError):
            pass
        return 0

    def _row_to_memory_item(
        self,
        row: Dict[str, Any]
    ) -> Optional[MemoryItem]:
        """
        Convert database row (dict from asyncpg) to MemoryItem

        Args:
            row: Database row dict from memory_hot table

        Returns:
            MemoryItem object
        """
        try:
            # asyncpg returns dict-like Record objects
            # Parse JSON fields
            content = json.loads(row['content']) if row['content'] else {}
            embeddings = row['embedding']  # pgvector returns as list automatically
            thinking_state = json.loads(row['thinking_state']) if row['thinking_state'] else None
            emotional_context = json.loads(row['emotional_context']) if row['emotional_context'] else None
            reasoning_trace = json.loads(row['reasoning_trace']) if row['reasoning_trace'] else None
            decision_factors = json.loads(row['decision_factors']) if row['decision_factors'] else None
            tags_list = json.loads(row['tags']) if row['tags'] else []
            related_memories = json.loads(row['related_memories']) if row['related_memories'] else []
            metadata = json.loads(row['metadata']) if row['metadata'] else {}

            # Convert timestamps to float (Unix timestamps)
            created_at = row['created_at'].timestamp() if row['created_at'] else datetime.now().timestamp()
            last_accessed = row['last_accessed'].timestamp() if row['last_accessed'] else None

            return MemoryItem(
                memory_id=row['memory_id'],
                memory_type=MemoryType(row['memory_type']),
                content=content,
                created_at=created_at,
                last_accessed=last_accessed,
                importance_score=float(row['importance_score']),
                confidence_score=float(row['confidence_score']),
                status=MemoryStatus(row['status']),
                thinking_state=thinking_state,
                emotional_context=emotional_context,
                reasoning_trace=reasoning_trace,
                decision_factors=decision_factors,
                embeddings=embeddings,
                metadata=metadata,
                related_memories=related_memories,
                tags=set(tags_list),
                access_count=row['access_count'],
                user_id=row.get('user_id', ''),
                session_id=row.get('session_id', ''),
                # WRITTEN, NEVER READ BACK. system_state has been persisted on
                # 95.6% of memories and was absent from this mapping, so every
                # retrieved MemoryItem reported None for it -- and because
                # hot->cold migration reads through here, the value was then
                # dropped on the way to the archive. memory_admission would have
                # inherited the same fate.
                system_state=_json_field(row, 'system_state'),
                memory_admission=_json_field(row, 'memory_admission'),
                appraisal_snapshot=_json_field(row, 'appraisal_snapshot')
            )

        except Exception as e:
            logger.error(f"Failed to parse memory row: {e}")
            import traceback
            traceback.print_exc()
            return None

    async def migrate_to_cold_tier(self, cutoff_date: datetime) -> int:
        """
        Migrate old memories from hot tier to cold tier (batch operation)

        Args:
            cutoff_date: Memories older than this date will be migrated

        Returns:
            Number of memories migrated
        """
        try:
            if not self.db:
                logger.error("Database not initialized")
                return 0

            migrated_count = 0

            # Get memories older than cutoff from hot tier
            rows = await self.db.execute_query(
                """
                SELECT memory_id
                FROM memory_hot
                WHERE created_at < $1
                AND status IN ('raw', 'processed')
                """,
                (cutoff_date,),
                use_hot_tier=True,
                fetch_all=True
            )

            memory_ids = [row['memory_id'] for row in rows]

            # Migrate each memory using existing migrate_to_cold method
            for memory_id in memory_ids:
                success = await self.migrate_to_cold(memory_id)
                if success:
                    migrated_count += 1

            logger.info(f"Migrated {migrated_count} memories to cold tier (cutoff: {cutoff_date})")
            return migrated_count

        except Exception as e:
            logger.error(f"Failed to batch migrate to cold tier: {e}")
            return 0

    async def cleanup_low_importance_memories(
        self,
        cutoff_date: datetime,
        importance_threshold: float
    ) -> int:
        """
        Clean up low-importance expired memories from hot tier

        Args:
            cutoff_date: Delete memories older than this
            importance_threshold: Delete memories with importance below this

        Returns:
            Number of memories deleted
        """
        try:
            if not self.db:
                logger.error("Database not initialized")
                return 0

            # Delete and count for real via RETURNING — a caller must be able to
            # tell "cleaned 12" from "cleaned none". Returning a hardcoded 0 made
            # every cleanup look like a no-op even when it deleted rows.
            rows = await self.db.execute_query(
                """
                DELETE FROM memory_hot
                WHERE created_at < $1
                AND importance_score < $2
                AND status IN ('raw', 'processed')
                RETURNING memory_id
                """,
                (cutoff_date, importance_threshold),
                use_hot_tier=True,
                fetch_all=True
            )
            count = len(rows) if rows else 0
            logger.info(f"Cleaned up {count} low-importance memories")
            return count

        except Exception as e:
            logger.error(f"Failed to cleanup memories: {e}")
            return 0

    async def apply_memory_decay(self) -> bool:
        """
        Apply temporal decay to all memories in hot tier

        Updates importance scores based on age and access patterns
        Formula: importance * exp(-0.01 * age_days)
        """
        try:
            if not self.db:
                logger.error("Database not initialized")
                return False

            # PostgreSQL version of decay formula
            await self.db.execute_query(
                """
                UPDATE memory_hot
                SET importance_score = importance_score * EXP(-0.01 * EXTRACT(DAY FROM (NOW() - created_at)))
                WHERE status IN ('raw', 'processed')
                AND EXTRACT(DAY FROM (NOW() - created_at)) > 1
                """,
                use_hot_tier=True,
                commit=True
            )

            logger.info(f"Applied decay to memories in hot tier")
            return True

        except Exception as e:
            logger.error(f"Failed to apply memory decay: {e}")
            return False

    async def query_memories_by_timerange(
        self,
        start_time: datetime,
        memory_type: Optional[MemoryType] = None,
        limit: int = 1000
    ) -> List[MemoryItem]:
        """
        Query memories within a time range from hot tier

        Args:
            start_time: Get memories after this time
            memory_type: Filter by memory type (optional)
            limit: Maximum number of memories to return

        Returns:
            List of MemoryItem objects
        """
        try:
            if not self.db:
                logger.error("Database not initialized")
                return []

            query = "SELECT * FROM memory_hot WHERE created_at >= $1"
            params = [start_time]
            param_idx = 2

            if memory_type:
                query += f" AND memory_type = ${param_idx}"
                params.append(memory_type.value)
                param_idx += 1

            query += f" ORDER BY created_at ASC LIMIT ${param_idx}"
            params.append(limit)

            rows = await self.db.execute_query(
                query,
                tuple(params),
                use_hot_tier=True,
                fetch_all=True
            )

            memories = []
            for row in rows:
                memory = self._row_to_memory_item(row)
                if memory:
                    memories.append(memory)

            return memories

        except Exception as e:
            logger.error(f"Failed to query memories by timerange: {e}")
            return []

    async def close(self) -> None:
        """Close database connection"""
        if self.db:
            await self.db.close()
            logger.info("PostgresStorage closed")


# Alias for compatibility
PostgreSQLStorage = PostgresStorage
