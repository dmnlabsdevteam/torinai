#!/usr/bin/env python3
"""
Perception Manager - Simplified sensory input processing
Consolidates all perception functionality from the monolithic controller
"""

import asyncio
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime
from collections import deque

from .shared_types import PerceptionData, Task, TaskType, TaskStatus, Priority
from core.database import TorinUnifiedDatabase

logger = logging.getLogger(__name__)


#: The perceptions table had NO definition anywhere in the codebase. Both the
#: writer and the reader named an unqualified `perceptions`, so every write
#: since this module was authored failed with `relation "perceptions" does not
#: exist`, was caught, logged, and counted as processed anyway. The substrate
#: has never retained a single perception.
#:
#: Schema-qualified, because the rest of the store is: an unqualified name
#: resolves through search_path, which differs between the pooled connection
#: and a psql session, so "the table exists" stops being a fact about the
#: database and becomes a fact about who is asking.
PERCEPTIONS_DDL = """
CREATE TABLE IF NOT EXISTS unified.perceptions (
    id          VARCHAR PRIMARY KEY,
    source      VARCHAR NOT NULL,
    data_type   VARCHAR NOT NULL,
    content     JSONB   NOT NULL,
    confidence  DOUBLE PRECISION NOT NULL,
    timestamp   DOUBLE PRECISION NOT NULL,
    metadata    JSONB   NOT NULL DEFAULT '{}'::jsonb,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS perceptions_source_idx    ON unified.perceptions (source);
CREATE INDEX IF NOT EXISTS perceptions_timestamp_idx ON unified.perceptions (timestamp DESC);
"""


class PerceptionManager:
    """Manages sensory input processing and environmental awareness"""
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.active = False
        
        # Perception data storage
        self.perception_queue: deque = deque(maxlen=1000)
        self.processed_perceptions: Dict[str, PerceptionData] = {}
        
        # Use unified database instead of separate perception.db
        self.unified_db = TorinUnifiedDatabase()
        self.connection = None  # For backwards compatibility
        
        # Processing statistics
        self.stats = {
            "total_processed": 0,
            "total_retained": 0,
            "processing_time_avg": 0.0,
            "confidence_avg": 0.0,
            "queue_length": 0
        }
    
    async def initialize(self) -> bool:
        """Initialize the perception system"""
        try:
            await self.unified_db.initialize()
            # TorinUnifiedDatabase uses connection pools, not direct connection
            self.connection = self.unified_db  # Store database instance for queries

            # The table this module writes to is created HERE, by the module
            # that owns it. Nothing else defined it, which is why every write
            # failed.
            for statement in [s for s in PERCEPTIONS_DDL.split(";") if s.strip()]:
                await self.unified_db.execute_query(statement, commit=True)

            self.active = True
            logger.info("Perception manager initialized successfully")
            return True

        except Exception as e:
            logger.error(f"Failed to initialize perception manager: {e}")
            return False
    
    async def process_input(self, source: str, data_type: str, content: Dict[str, Any]) -> Optional[PerceptionData]:
        """Process new sensory input"""
        if not self.active:
            return None
        
        try:
            start_time = datetime.now().timestamp()
            
            # Create perception data
            perception = PerceptionData(
                source=source,
                data_type=data_type,
                content=content,
                confidence=self._calculate_confidence(content),
                timestamp=start_time
            )
            
            # Process the perception
            processed_perception = await self._analyze_perception(perception)
            
            # Store in queue and database
            perception_id = f"perc_{start_time}_{source}"
            self.perception_queue.append(processed_perception)
            self.processed_perceptions[perception_id] = processed_perception
            
            # Retention is reported, never assumed. The write used to fail on
            # every call and be absorbed, so `total_processed` counted
            # perceptions that no longer existed a moment later.
            try:
                await self._store_perception(perception_id, processed_perception)
                processed_perception.metadata["retained"] = True
            except Exception as e:
                processed_perception.metadata["retained"] = False
                logger.error(
                    "perception %s from %s was analysed but NOT retained: %s",
                    perception_id, source, e)

            # A perception is an OBSERVATION of something the substrate can
            # name, and PerceptionManager was its only consumer -- perceptions
            # were stored, counted, and never became knowledge of anything.
            # Health monitoring, the live producer, supplies a component and a
            # condition in typed fields, so nothing has to read the message
            # text to know what was observed.
            await self._observe_semantically(source, data_type, content)

            # Update statistics
            processing_time = datetime.now().timestamp() - start_time
            self._update_stats(processing_time, processed_perception.confidence,
                               retained=processed_perception.metadata.get("retained", False))
            
            logger.debug(f"Processed perception from {source}: {data_type}")
            return processed_perception
            
        except Exception as e:
            logger.error(f"Error processing perception input: {e}")
            return None
    
    async def _observe_semantically(self, source, data_type, content) -> None:
        """Submit a perception as evidence. Never fails perception itself."""
        try:
            from core.domain.evidence_producers import submit_perception

            await submit_perception(source, data_type, content or {})
        except Exception as e:
            logger.error(
                "perception from %s could not be recorded as evidence: %s: %s",
                source, type(e).__name__, e)

    async def get_recent_perceptions(self, limit: int = 10) -> List[PerceptionData]:
        """Get most recent perception data"""
        return list(self.perception_queue)[-limit:]
    
    async def search_perceptions(self, query: Dict[str, Any]) -> List[PerceptionData]:
        """Search retained perceptions.

        Rewritten because every part of the previous query was wrong for the
        database it runs against: `?` and `%s` placeholders (SQLite and
        psycopg2) against an asyncpg pool that takes `$1`, an unqualified table
        that does not exist, and positional row indexing against a manager that
        returns mapping rows. It could not have returned a result under any
        input, and the `except` around it reported that as "no perceptions
        found".
        """
        if not self.connection:
            raise RuntimeError(
                "perception manager has no database connection; initialize() "
                "must run before perceptions can be searched")

        conditions, params = [], []
        for key, column, operator in (("source", "source", "="),
                                      ("data_type", "data_type", "="),
                                      ("min_confidence", "confidence", ">=")):
            if key in query:
                params.append(query[key])
                conditions.append(f"{column} {operator} ${len(params)}")

        params.append(int(query.get("limit", 50)))
        where = " AND ".join(conditions) if conditions else "TRUE"
        rows = await self.connection.execute_query(
            f"""SELECT id, source, data_type, content, confidence, timestamp, metadata
                FROM unified.perceptions
                WHERE {where}
                ORDER BY timestamp DESC
                LIMIT ${len(params)}""",
            tuple(params), fetch_all=True) or []

        import json

        def _obj(value):
            return json.loads(value) if isinstance(value, str) else (value or {})

        return [PerceptionData(
            source=row["source"],
            data_type=row["data_type"],
            content=_obj(row["content"]),
            confidence=row["confidence"],
            timestamp=row["timestamp"],
            metadata=_obj(row["metadata"]),
        ) for row in rows]

    async def get_statistics(self) -> Dict[str, Any]:
        """Get perception processing statistics"""
        self.stats["queue_length"] = len(self.perception_queue)
        return self.stats.copy()
    
    async def _analyze_perception(self, perception: PerceptionData) -> PerceptionData:
        """Analyze and enhance perception data"""
        # Simple analysis - can be enhanced as needed
        analysis_metadata = {
            "processed_at": datetime.now().timestamp(),
            "analysis_version": "1.0"
        }
        
        # Add pattern recognition, feature extraction, etc. here
        if perception.data_type == "text":
            analysis_metadata["word_count"] = len(perception.content.get("text", "").split())
        elif perception.data_type == "image":
            analysis_metadata["image_size"] = perception.content.get("dimensions", "unknown")
        
        perception.metadata.update(analysis_metadata)
        return perception
    
    def _calculate_confidence(self, content: Dict[str, Any]) -> float:
        """Calculate confidence score for perception data"""
        # Simple confidence calculation - can be enhanced
        base_confidence = 0.8
        
        # Adjust based on data completeness
        if "text" in content and len(content["text"]) > 0:
            base_confidence += 0.1
        if "metadata" in content:
            base_confidence += 0.1
        
        return min(1.0, base_confidence)
    
    async def _store_perception(self, perception_id: str, perception: PerceptionData) -> bool:
        """Store perception in the database. Raises when the write fails."""
        if not self.connection:
            raise RuntimeError(
                "perception manager has no database connection; initialize() "
                "must run before a perception can be retained")

        try:
            import json
            sql_query = """
                INSERT INTO unified.perceptions
                (id, source, data_type, content, confidence, timestamp, metadata)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                ON CONFLICT (id) DO UPDATE SET
                    source = EXCLUDED.source,
                    data_type = EXCLUDED.data_type,
                    content = EXCLUDED.content,
                    confidence = EXCLUDED.confidence,
                    timestamp = EXCLUDED.timestamp,
                    metadata = EXCLUDED.metadata
            """

            await self.connection.execute_query(
                sql_query,
                params=(
                    perception_id,
                    perception.source,
                    perception.data_type,
                    json.dumps(perception.content),
                    perception.confidence,
                    perception.timestamp,
                    json.dumps(perception.metadata)
                ),
                commit=True,
            )

            return True

        except Exception as e:
            # Raised to the caller rather than absorbed. A perception that was
            # analysed but not retained is not a processed perception, and
            # counting it as one is how this subsystem reported four years of
            # activity while persisting nothing.
            logger.error("Error storing perception %s: %s", perception_id, e)
            raise

    def _update_stats(self, processing_time: float, confidence: float,
                      retained: bool = True):
        """Update processing statistics.

        `total_retained` is tracked apart from `total_processed` so the gap
        between "analysed" and "still exists" is visible in the statistics
        rather than only in a log line.
        """
        self.stats["total_processed"] += 1
        if retained:
            self.stats["total_retained"] += 1
        
        # Update averages
        total = self.stats["total_processed"]
        self.stats["processing_time_avg"] = (
            (self.stats["processing_time_avg"] * (total - 1) + processing_time) / total
        )
        self.stats["confidence_avg"] = (
            (self.stats["confidence_avg"] * (total - 1) + confidence) / total
        )
    
    async def shutdown(self):
        """Shutdown the perception manager"""
        self.active = False
        # Database cleanup is handled by the unified database itself
        self.connection = None
        logger.info("Perception manager shutdown completed")