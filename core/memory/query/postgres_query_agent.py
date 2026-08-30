#!/usr/bin/env python3
"""
PostgreSQL Query Agent

Intelligent query interface for PostgreSQL hot tier memory storage.
Translates natural language queries to structured memory searches.

Capabilities:
- Semantic similarity search with pgvector
- Keyword-based search across content
- Tag-based filtering
- Time-based queries
- Pattern recognition

Integration:
- Uses PostgresStorage for hot tier access
- Optionally delegates to LLM for query understanding
"""

import logging
from typing import Dict, Any, List, Optional, Set, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict

from core.memory.storage.postgres_storage import PostgresStorage
from core.memory.utils.interfaces import (
    MemoryQuery,
    MemorySearchResult,
    MemoryItem,
    MemoryType,
    MemoryOperation
)

logger = logging.getLogger(__name__)


class PostgresQueryAgent:
    """
    PostgreSQL Query Agent for Hot Tier Memory

    Intelligent query interface that translates natural language queries
    to structured memory searches in PostgreSQL hot tier (last 60 days).

    Features:
    - Natural language understanding
    - Tag and keyword extraction
    - Time-based query translation
    - Pattern matching
    - pgvector semantic search
    """

    def __init__(self, storage: Optional[PostgresStorage] = None):
        """Initialize PostgreSQL query agent"""
        self.storage = storage or PostgresStorage()
        self.initialized = False

        # Metrics
        self.metrics = {
            'queries_executed': 0,
            'successful_queries': 0,
            'failed_queries': 0,
            'avg_search_time': 0.0
        }

    async def initialize(self) -> bool:
        """Initialize storage and agent"""
        try:
            # Initialize storage
            await self.storage.initialize()

            self.initialized = True
            logger.info("PostgresQueryAgent initialized successfully")
            return True

        except Exception as e:
            logger.error(f"Failed to initialize PostgresQueryAgent: {e}")
            return False

    async def query(
        self,
        query: MemoryQuery,
        memory_types: Optional[List[MemoryType]] = None,
        tags: Optional[Set[str]] = None,
        time_window_start: Optional[datetime] = None,
        time_window_end: Optional[datetime] = None,
        min_importance: Optional[float] = None,
        limit: int = 10
    ) -> Tuple[bool, MemorySearchResult]:
        """
        Execute memory query against PostgreSQL hot tier

        Args:
            query: MemoryQuery object with search parameters
            memory_types: Filter by memory types (episodic, semantic, procedural, etc.)
            tags: Filter by tags (set of tag strings)
            time_window_start: Start of time window
            time_window_end: End of time window
            min_importance: Minimum importance score (0.0-1.0)
            limit: Maximum results to return

        Returns:
            Tuple of (success, MemorySearchResult)
                - success: True if query executed successfully
                - MemorySearchResult: Search results with metadata
        """
        start_time = datetime.now()
        self.metrics['queries_executed'] += 1

        try:
            # Parse query for additional context
            parsed_query = await self._parse_query(
                query_text=query.content,
                memory_types=memory_types,
                tags=tags,
                time_window_start=time_window_start,
                time_window_end=time_window_end
            )

            # Merge parsed parameters
            final_types = memory_types or parsed_query['memory_types']
            final_tags = tags or parsed_query['tags']
            final_time_start = time_window_start or parsed_query['time_window_start']
            final_time_end = time_window_end or parsed_query['time_window_end']

            # Execute search on PostgreSQL storage
            results = await self.storage.search_memories(
                memory_type=final_types[0] if final_types else None,
                tags=final_tags,
                time_window_start=final_time_start.timestamp() if final_time_start else None,
                time_window_end=final_time_end.timestamp() if final_time_end else None,
                min_importance=min_importance,
                limit=limit
            )

            # Calculate search time
            search_time = (datetime.now() - start_time).total_seconds()

            # Update metrics
            self.metrics['successful_queries'] += 1
            self.metrics['avg_search_time'] = (
                (self.metrics['avg_search_time'] * (self.metrics['successful_queries'] - 1) + search_time) /
                self.metrics['successful_queries']
            )

            logger.info(
                f"Query executed successfully: {len(results)} results "
                f"(query='{query.content[:50]}...', time={search_time:.3f}s), "
                f"filters={self.metrics['successful_queries']}"
            )

            return True, MemorySearchResult(
                query_id=query.query_id,
                memories=results,
                total_matches=len(results),
                search_time=search_time
            )

        except Exception as e:
            logger.error(f"Query execution failed: {e}")
            self.metrics['failed_queries'] += 1
            return False, MemorySearchResult(
                query_id=query.query_id,
                memories=[],
                total_matches=0,
                search_time=0.0
            )

    async def query_by_tags(
        self,
        tags: Set[str],
        memory_types: Optional[List[MemoryType]] = None,
        limit: int = 100
    ) -> Tuple[bool, List[MemoryItem]]:
        """
        Query memories by tags

        Args:
            tags: Set of tags to search for
            memory_types: Optional filter by memory types
            limit: Maximum results

        Returns:
            Tuple of (success, List[MemoryItem])
        """
        results = await self.storage.search_memories(
            memory_type=memory_types[0] if memory_types else None,
            tags=tags,
            time_window_start=None,  # No time filter
            time_window_end=None,    # Search all hot tier
            limit=limit
        )

        # Filter by additional memory types if provided
        if memory_types and len(memory_types) > 1:
            filtered_results = []
            for mem in results:
                mem_type = mem.memory_type if isinstance(mem.memory_type, MemoryType) else MemoryType(mem.memory_type)
                if mem_type in memory_types:
                    filtered_results.append(mem)
            results = filtered_results

        # Group by tag for analysis
        if tags and len(results) > 0:
            tag_counts = {}
            for tag in tags:
                count = sum(1 for mem in results if tag in (mem.metadata.get('tags', []) if mem.metadata else []))
                tag_counts[tag] = count
                logger.info(f"  • Tag '{tag}': {count} memories")

        else:
            logger.info(
                f"No memories found for tags: {', '.join(tags)}"
            )
            tag_counts = {tag: 0 for tag in tags}

        return True, results

    async def query_by_timeframe(
        self,
        days_back: int = 7,
        limit: int = 100
    ) -> Tuple[bool, List[MemoryItem]]:
        """
        Query memories from recent timeframe

        Args:
            days_back: Number of days to look back
            limit: Maximum results

        Returns:
            Tuple of (success, List[MemoryItem])
        """
        try:
            # Calculate time window
            end_time = datetime.now()
            start_time = end_time - timedelta(days=days_back)

            # Search within time window
            results = await self.storage.search_memories(
                memory_type=None,
                tags=None,
                time_window_start=start_time.timestamp(),
                time_window_end=end_time.timestamp(),
                limit=limit
            )

            # Calculate statistics
            total_memories = len(results)
            avg_importance = sum(m.importance_score for m in results) / total_memories if total_memories > 0 else 0

            # Breakdown by memory type (if useful)
            type_counts = {}
            for mem in results:
                mem_type = str(mem.memory_type.value if isinstance(mem.memory_type, MemoryType) else mem.memory_type)
                type_counts[mem_type] = type_counts.get(mem_type, 0) + 1

            logger.info(f"  • Timeframe: last {days_back} days")
            logger.info(f"  • Total memories: {total_memories}")

            # Log top 3 types
            top_types = sorted(type_counts.items(), key=lambda x: x[1], reverse=True)[:3]
            if top_types:
                logger.info("  • Top memory types:")
                for mem_type, count in top_types:
                    logger.info(f"    - {mem_type}: {count}")

            return True, results

        except Exception as e:
            logger.error(f"Timeframe query failed: {e}")
            return False, []

    async def _parse_query(
        self,
        query_text: str,
        memory_types: Optional[List[MemoryType]],
        tags: Optional[Set[str]],
        time_window_start: Optional[datetime],
        time_window_end: Optional[datetime]
    ) -> Dict[str, Any]:
        """
        Parse natural language query to extract parameters

        Args:
            query_text: Natural language query string
            memory_types: Explicit memory types (if provided)
            tags: Explicit tags (if provided)
            time_window_start: Explicit start time
            time_window_end: Explicit end time

        Returns:
            Dictionary with parsed query parameters
        """
        parsed = {
            'memory_types': memory_types or [],
            'tags': tags or set(),
            'time_window_start': time_window_start,
            'time_window_end': time_window_end
        }

        # Extract time-related keywords
        query_lower = query_text.lower()

        # Detect time references
        if 'today' in query_lower or 'recent' in query_lower:
            parsed['time_window_start'] = datetime.now() - timedelta(days=1)
        elif 'yesterday' in query_lower:
            parsed['time_window_start'] = datetime.now() - timedelta(days=2)
            parsed['time_window_end'] = datetime.now() - timedelta(days=1)
        elif 'week' in query_lower or 'last 7' in query_lower:
            parsed['time_window_start'] = datetime.now() - timedelta(days=7)
        elif 'month' in query_lower or 'last 30' in query_lower:
            parsed['time_window_start'] = datetime.now() - timedelta(days=30)

        # Extract memory type keywords
        type_keywords = {
            'episodic': MemoryType.EPISODIC,
            'semantic': MemoryType.SEMANTIC,
            'procedural': MemoryType.PROCEDURAL
        }

        for keyword, mem_type in type_keywords.items():
            if keyword in query_lower:
                parsed['memory_types'].append(mem_type)

        return parsed

    async def analyze_query_patterns(
        self,
        memories: List[Tuple[MemoryItem, str]]
    ) -> Dict[str, Any]:
        """
        Analyze patterns in query results

        Args:
            memories: List of (MemoryItem, extra_info) tuples

        Returns:
            Analysis dictionary
        """
        if not memories:
            return {}

        total_count = len(memories)
        memories_only = [m[0] if isinstance(m, tuple) else m for m in memories]
        avg_importance = sum(m.importance_score for m in memories_only) / total_count if total_count > 0 else 0
        avg_confidence = sum(m.confidence_score for m in memories_only) / total_count if total_count > 0 else 0
        avg_access_count = sum(m.access_count for m in memories_only) / total_count if total_count > 0 else 0

        # Count by type
        type_dist = {}
        for mem in memories_only:
            mem_type_str = str(mem.memory_type.value if isinstance(mem.memory_type, MemoryType) else mem.memory_type)
            type_dist[mem_type_str] = type_dist.get(mem_type_str, 0) + 1

        # Count by tags
        tag_dist = {}
        for mem in memories_only:
            mem_tags = set(mem.metadata.get('tags', []) if mem.metadata else [])
            for tag in mem_tags:
                tag_dist[tag] = tag_dist.get(tag, 0) + 1

        return {
            'total_memories': total_count,
            'avg_importance': avg_importance,
            'avg_confidence': avg_confidence,
            'avg_access_count': avg_access_count,
            'type_distribution': type_dist,
            'tag_distribution': tag_dist
        }

    async def summarize_results(
        self,
        memories: List[Tuple[MemoryItem, str]],
        query_text: str,
        include_content_preview: bool = True,
        preview_length: int = 100
    ) -> List[str]:
        """
        Generate human-readable summary of query results

        Args:
            memories: List of (MemoryItem, extra_info) tuples
            query_text: Original query text
            include_content_preview: Whether to include content previews
            preview_length: Max characters for content preview

        Returns:
            List of summary strings
        """
        if not memories:
            return []

        summary = []
        summary.append(f"Query: \"{query_text}\"")
        summary.append(
            f"Results: {len(memories)} memories (from PostgreSQL hot tier)"
        )

        # Statistics
        avg_importance = sum(m[0].importance_score for m in memories) / len(memories)
        logger.info(f"  • Average importance: {avg_importance:.2%}")

        # Recent vs older
        now = datetime.now()
        recent_count = sum(
            1 for m in memories
            if (now - (datetime.fromtimestamp(m[0].created_at) if isinstance(m[0].created_at, (int, float)) else m[0].created_at)).days <= 7
        )
        logger.info(f"  • Recent (last 7 days): {recent_count}")

        # Top memory types (show top 3)
        type_counts = {}
        for mem, _ in memories:
            mem_type = str(mem.memory_type.value if isinstance(mem.memory_type, MemoryType) else mem.memory_type)
            type_counts[mem_type] = type_counts.get(mem_type, 0) + 1

        if type_counts:
            logger.info("  • Memory types:")
            for mem_type, count in sorted(type_counts.items(), key=lambda x: x[1], reverse=True)[:3]:
                pct = (count / len(memories)) * 100
                logger.info(f"    - {mem_type}: {count} ({pct:.1f}%)")

        return summary

    async def suggest_refinements(
        self,
        memories: List[Tuple[MemoryItem, str]],
        query_text: str
    ) -> List[str]:
        """
        Suggest query refinements based on results

        Args:
            memories: Query result memories
            query_text: Original query

        Returns:
            List of suggested refinements
        """
        suggestions = []

        # Too many results
        if len(memories) > 50:
            suggestions.append(
                f"Consider narrowing search ({len(memories)}% results) - add time filter or tags"
            )

        # Too few results
        if len(memories) < 5:
            suggestions.append(
                "Consider broadening search - remove filters or expand timeframe"
            )

        # Low importance scores
        avg_importance = sum(m[0].importance_score for m in memories) / len(memories) if memories else 0
        if avg_importance < 0.5 * 1.0:  # Less than 50% of max importance
            suggestions.append(
                "Results have low importance - consider filtering by min_importance"
            )

        return suggestions

    async def get_statistics(self) -> Dict[str, Any]:
        """Get query agent statistics"""
        stats = await self.storage.get_statistics()
        stats['agent_metrics'] = self.metrics  # Merge agent metrics
        return stats

    def __del__(self):
        """Cleanup on deletion"""
        # Clean up resources if needed
        logger.debug("PostgresQueryAgent cleanup")


# Global query agent instance
_query_agent = None

async def get_query_agent() -> PostgresQueryAgent:
    """Get global PostgreSQL query agent instance"""
    global _query_agent
    if _query_agent is None:
        _query_agent = PostgresQueryAgent()
        await _query_agent.initialize()
    return _query_agent
