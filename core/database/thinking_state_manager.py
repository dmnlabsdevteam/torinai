#!/usr/bin/env python3
"""
Thinking State Manager for Torin ASI
====================================
Production-ready system for managing AI thinking states, reasoning chains, and cognitive traces.

Features:
- Persistent storage of thinking states in PostgreSQL
- Async singleton pattern with proper locking
- Reasoning chain tracking and retrieval
- Cognitive state snapshots
- Performance metrics and analytics
- Automatic cleanup and archival
"""

from core.capability import raise_if_structural
import logging
import asyncio
import json
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, Optional, List
from dataclasses import dataclass
from enum import Enum

from . import TorinUnifiedDatabase

logger = logging.getLogger(__name__)


class ThinkingStateType(Enum):
    """Types of thinking states"""
    REASONING = "reasoning"
    PLANNING = "planning"
    PROBLEM_SOLVING = "problem_solving"
    LEARNING = "learning"
    DECISION_MAKING = "decision_making"
    REFLECTION = "reflection"
    ANALYSIS = "analysis"
    SYNTHESIS = "synthesis"


class ThinkingStateStatus(Enum):
    """Status of thinking states"""
    ACTIVE = "active"
    COMPLETED = "completed"
    SUSPENDED = "suspended"
    FAILED = "failed"
    ARCHIVED = "archived"


@dataclass
class ThinkingState:
    """Represents a cognitive thinking state"""
    state_id: str
    state_type: ThinkingStateType
    status: ThinkingStateStatus
    context: Dict[str, Any]
    reasoning_chain: List[Dict[str, Any]]
    metadata: Dict[str, Any]
    created_at: datetime
    updated_at: datetime
    completed_at: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage"""
        return {
            'state_id': self.state_id,
            'state_type': self.state_type.value,
            'status': self.status.value,
            'context': json.dumps(self.context),
            'reasoning_chain': json.dumps(self.reasoning_chain),
            'metadata': json.dumps(self.metadata),
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat(),
            'completed_at': self.completed_at.isoformat() if self.completed_at else None
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ThinkingState':
        """Create from dictionary"""
        return cls(
            state_id=data['state_id'],
            state_type=ThinkingStateType(data['state_type']),
            status=ThinkingStateStatus(data['status']),
            context=json.loads(data['context']) if isinstance(data['context'], str) else data['context'],
            reasoning_chain=json.loads(data['reasoning_chain']) if isinstance(data['reasoning_chain'], str) else data['reasoning_chain'],
            metadata=json.loads(data['metadata']) if isinstance(data['metadata'], str) else data['metadata'],
            created_at=datetime.fromisoformat(data['created_at']) if isinstance(data['created_at'], str) else data['created_at'],
            updated_at=datetime.fromisoformat(data['updated_at']) if isinstance(data['updated_at'], str) else data['updated_at'],
            completed_at=datetime.fromisoformat(data['completed_at']) if data.get('completed_at') and isinstance(data['completed_at'], str) else data.get('completed_at')
        )


class ThinkingStateManager:
    """
    Production-ready thinking state manager for Torin ASI

    Manages cognitive states, reasoning chains, and thinking processes
    with persistent storage in PostgreSQL and async access patterns.
    """

    def __init__(self):
        """Initialize thinking state manager"""
        self.db = TorinUnifiedDatabase()
        self.initialized = False
        self._init_lock = asyncio.Lock()
        self._active_states: Dict[str, ThinkingState] = {}
        self._state_cache: Dict[str, ThinkingState] = {}
        self._cache_size = 1000

        logger.info("ThinkingStateManager instance created")

    async def initialize(self) -> bool:
        """
        Initialize the thinking state manager

        Returns:
            bool: True if initialization successful
        """
        async with self._init_lock:
            if self.initialized:
                logger.debug("ThinkingStateManager already initialized")
                return True

            try:
                # Initialize unified PostgreSQL database
                await self.db.initialize()

                # Verify tables exist (from postgres_schemas.sql)
                thinking_states_exists = await self.db.table_exists('thinking_states')
                reasoning_chains_exists = await self.db.table_exists('reasoning_chains')

                if not thinking_states_exists:
                    logger.warning("thinking_states table doesn't exist - run postgres_schemas.sql")
                if not reasoning_chains_exists:
                    logger.warning("reasoning_chains table doesn't exist - run postgres_schemas.sql")

                # Load active states into memory
                await self._load_active_states()

                self.initialized = True
                logger.info("✅ ThinkingStateManager initialized successfully (PostgreSQL)")
                return True

            except Exception as e:
                logger.error(f"Failed to initialize ThinkingStateManager: {e}")
                return False

    async def _load_active_states(self):
        """Load active states from database into memory"""
        try:
            query = """
            SELECT * FROM thinking_states
            WHERE status IN ('active', 'suspended')
            ORDER BY updated_at DESC
            LIMIT 100
            """

            rows = await self.db.execute_query(query, fetch_all=True) or []

            for row in rows:
                state = ThinkingState.from_dict(dict(row))
                self._active_states[state.state_id] = state

            logger.info(f"Loaded {len(self._active_states)} active thinking states")

        except Exception as e:
            logger.warning(f"Error loading active states: {e}")

    async def create_state(
        self,
        state_id: str,
        state_type: ThinkingStateType,
        context: Dict[str, Any],
        metadata: Optional[Dict[str, Any]] = None
    ) -> ThinkingState:
        """
        Create a new thinking state

        Args:
            state_id: Unique identifier for the state
            state_type: Type of thinking state
            context: Context information
            metadata: Additional metadata

        Returns:
            ThinkingState: Created state
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
            now = datetime.now(timezone.utc)

            state = ThinkingState(
                state_id=state_id,
                state_type=state_type,
                status=ThinkingStateStatus.ACTIVE,
                context=context or {},
                reasoning_chain=[],
                metadata=metadata or {},
                created_at=now,
                updated_at=now
            )

            # Store in database
            insert_sql = """
            INSERT INTO thinking_states
            (state_id, state_type, status, context, reasoning_chain, metadata, created_at, updated_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            """

            state_dict = state.to_dict()
            await self.db.execute_query(
                insert_sql,
                params=(
                    state_dict['state_id'],
                    state_dict['state_type'],
                    state_dict['status'],
                    state_dict['context'],
                    state_dict['reasoning_chain'],
                    state_dict['metadata'],
                    state_dict['created_at'],
                    state_dict['updated_at']
                ),
                commit=True
            )

            # Cache in memory
            self._active_states[state_id] = state
            self._cache_state(state)

            logger.debug(f"Created thinking state: {state_id} ({state_type.value})")
            return state

        except Exception as e:
            logger.error(f"Error creating thinking state {state_id}: {e}")
            raise

    async def update_state(
        self,
        state_id: str,
        context: Optional[Dict[str, Any]] = None,
        reasoning_step: Optional[Dict[str, Any]] = None,
        status: Optional[ThinkingStateStatus] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Optional[ThinkingState]:
        """
        Update an existing thinking state

        Args:
            state_id: State identifier
            context: Updated context
            reasoning_step: New reasoning step to append
            status: New status
            metadata: Updated metadata

        Returns:
            Updated ThinkingState or None if not found
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
            # Get current state
            state = await self.get_state(state_id)
            if not state:
                logger.warning(f"State {state_id} not found for update")
                return None

            # Update fields
            if context is not None:
                state.context = context
            if reasoning_step is not None:
                state.reasoning_chain.append(reasoning_step)
            if status is not None:
                state.status = status
            if metadata is not None:
                state.metadata.update(metadata)

            state.updated_at = datetime.now(timezone.utc)

            if status == ThinkingStateStatus.COMPLETED:
                state.completed_at = state.updated_at

            # Update in database
            update_sql = """
            UPDATE thinking_states
            SET context = $1, reasoning_chain = $2, status = $3,
                metadata = $4, updated_at = $5, completed_at = $6
            WHERE state_id = $7
            """

            state_dict = state.to_dict()
            await self.db.execute_query(
                update_sql,
                params=(
                    state_dict['context'],
                    state_dict['reasoning_chain'],
                    state_dict['status'],
                    state_dict['metadata'],
                    state_dict['updated_at'],
                    state_dict['completed_at'],
                    state_id
                ),
                commit=True
            )

            # Update cache
            self._active_states[state_id] = state
            self._cache_state(state)

            logger.debug(f"Updated thinking state: {state_id}")
            return state

        except Exception as e:
            logger.error(f"Error updating thinking state {state_id}: {e}")
            return None

    async def get_state(self, state_id: str) -> Optional[ThinkingState]:
        """
        Get a thinking state by ID

        Args:
            state_id: State identifier

        Returns:
            ThinkingState or None if not found
        """
        if not self.initialized:
            # The result is CHECKED. Discarding it meant a failed initialize was
            # followed by the work it was meant to enable, and the real failure
            # resurfaced later disguised as something else.
            if await self.initialize() is False:
                raise RuntimeError(
                    type(self).__name__ + ' could not initialize; refusing to '
                    'continue as though it had')

        # Check cache first
        if state_id in self._state_cache:
            return self._state_cache[state_id]

        # Query database
        try:
            query = "SELECT * FROM thinking_states WHERE state_id = $1"
            row = await self.db.execute_query(query, params=(state_id,), fetch_one=True)

            if row:
                state = ThinkingState.from_dict(dict(row))
                self._cache_state(state)
                return state

            return None

        except Exception as e:
            logger.error(f"Error getting thinking state {state_id}: {e}")
            return None

    async def get_active_states(
        self,
        state_type: Optional[ThinkingStateType] = None
    ) -> List[ThinkingState]:
        """
        Get all active thinking states

        Args:
            state_type: Optional filter by state type

        Returns:
            List of active ThinkingState objects
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
            if state_type:
                query = """
                SELECT * FROM thinking_states
                WHERE status = 'active' AND state_type = $1
                ORDER BY updated_at DESC
                """
                rows = await self.db.execute_query(query, params=(state_type.value,), fetch_all=True) or []
            else:
                query = """
                SELECT * FROM thinking_states
                WHERE status = 'active'
                ORDER BY updated_at DESC
                """
                rows = await self.db.execute_query(query, fetch_all=True) or []

            states = [ThinkingState.from_dict(dict(row)) for row in rows]
            return states

        except Exception as e:
            # `except` must not turn a wiring defect into an empty result.
            raise_if_structural(e, 'thinking_state_manager.get_active_states')
            logger.error(f"Error getting active states: {e}")
            return []

    async def complete_state(
        self,
        state_id: str,
        final_metadata: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Mark a thinking state as completed

        Args:
            state_id: State identifier
            final_metadata: Optional final metadata

        Returns:
            bool: True if successful
        """
        metadata = final_metadata or {}
        metadata['completed_at'] = datetime.now(timezone.utc).isoformat()

        state = await self.update_state(
            state_id,
            status=ThinkingStateStatus.COMPLETED,
            metadata=metadata
        )

        if state:
            # Remove from active states
            self._active_states.pop(state_id, None)
            return True

        return False

    async def archive_old_states(self, older_than_days: int = 30) -> int:
        """
        Archive completed states older than specified days

        Args:
            older_than_days: Archive states older than this many days

        Returns:
            Number of states archived
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
            cutoff_date = datetime.now(timezone.utc) - timedelta(days=older_than_days)

            update_sql = """
            UPDATE thinking_states
            SET status = 'archived'
            WHERE status = 'completed'
            AND completed_at < $1
            """

            await self.db.execute_query(update_sql, params=(cutoff_date.isoformat(),), commit=True)

            logger.info(f"Archived thinking states older than {older_than_days} days")
            return 0  # PostgreSQL doesn't return affected rows easily without RETURNING clause

        except Exception as e:
            logger.error(f"Error archiving old states: {e}")
            return 0

    async def get_state_statistics(self) -> Dict[str, Any]:
        """
        Get statistics about thinking states

        Returns:
            Dictionary with statistics
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
            stats_query = """
            SELECT
                status,
                state_type,
                COUNT(*) as count,
                AVG(EXTRACT(EPOCH FROM (completed_at - created_at))) as avg_duration_seconds
            FROM thinking_states
            WHERE created_at > CURRENT_TIMESTAMP - INTERVAL '7 days'
            GROUP BY status, state_type
            ORDER BY count DESC
            """

            rows = await self.db.execute_query(stats_query, fetch_all=True) or []

            stats = {
                'total_states': len(self._state_cache),
                'active_states': len(self._active_states),
                'by_status_and_type': []
            }

            for row in rows:
                stats['by_status_and_type'].append({
                    'status': row['status'],
                    'state_type': row['state_type'],
                    'count': row['count'],
                    'avg_duration_seconds': float(row['avg_duration_seconds']) if row['avg_duration_seconds'] else None
                })

            return stats

        except Exception as e:
            logger.error(f"Error getting state statistics: {e}")
            return {
                'total_states': len(self._state_cache),
                'active_states': len(self._active_states),
                'error': str(e)
            }

    def _cache_state(self, state: ThinkingState):
        """Add state to cache with LRU eviction"""
        self._state_cache[state.state_id] = state

        # Simple LRU: remove oldest if cache is full
        if len(self._state_cache) > self._cache_size:
            # Remove oldest (first key)
            oldest_key = next(iter(self._state_cache))
            del self._state_cache[oldest_key]

    async def close(self):
        """Close database connection"""
        if self.db:
            await self.db.close()
