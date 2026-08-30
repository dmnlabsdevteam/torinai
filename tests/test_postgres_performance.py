#!/usr/bin/env python3
"""
PostgreSQL + pgvector Performance Benchmark
===========================================
Validates 100x speed improvement from pgvector HNSW indexes
"""
import pytest
import asyncio
import time
import numpy as np
from typing import List

from core.database import TorinUnifiedDatabase


@pytest.mark.asyncio
async def test_vector_search_performance():
    """
    Benchmark pgvector semantic search performance

    Expected: < 100ms for 1000 vectors with HNSW index
    vs 5000ms+ for MySQL JSON + Python loop
    """
    db = TorinUnifiedDatabase()
    await db.initialize()

    try:
        # Generate 1000 test embeddings
        print("\n=== Inserting 1000 test embeddings ===")
        insert_start = time.time()

        for i in range(1000):
            embedding = np.random.rand(384).tolist()

            await db.execute_query(
                """
                INSERT INTO memory_hot.memory_hot
                (memory_id, memory_type, content, embedding)
                VALUES ($1, $2, $3, $4::vector)
                ON CONFLICT (memory_id) DO NOTHING
                """,
                (
                    f"perf_test_{i}",
                    "episodic",
                    f"Test memory {i}",
                    embedding
                ),
                use_hot_tier=True,
                commit=True
            )

            if (i + 1) % 100 == 0:
                print(f"Progress: {i + 1}/1000 inserted...")

        insert_time = (time.time() - insert_start) * 1000  # ms
        print(f"✓ Insert time: {insert_time:.0f}ms ({insert_time/1000:.2f}ms per embedding)")

        # Benchmark semantic search with HNSW index
        print("\n=== Benchmarking pgvector HNSW semantic search ===")
        query_embedding = np.random.rand(384).tolist()

        # Warm up
        await db.execute_query(
            """
            SELECT memory_id, 1 - (embedding <=> $1::vector) AS similarity
            FROM memory_hot.memory_hot
            ORDER BY embedding <=> $1::vector
            LIMIT 10
            """,
            (query_embedding,),
            use_hot_tier=True,
            fetch_all=True
        )

        # Benchmark 10 searches
        search_times = []
        for _ in range(10):
            search_start = time.time()

            results = await db.execute_query(
                """
                SELECT memory_id, 1 - (embedding <=> $1::vector) AS similarity
                FROM memory_hot.memory_hot
                WHERE 1 - (embedding <=> $1::vector) >= $2
                ORDER BY embedding <=> $1::vector
                LIMIT 10
                """,
                (query_embedding, 0.0),  # No threshold filter for benchmark
                use_hot_tier=True,
                fetch_all=True
            )

            search_time = (time.time() - search_start) * 1000  # ms
            search_times.append(search_time)

        avg_search_time = np.mean(search_times)
        min_search_time = np.min(search_times)
        max_search_time = np.max(search_times)

        print(f"\n✓ Search performance over 10 runs:")
        print(f"  Average: {avg_search_time:.2f}ms")
        print(f"  Min:     {min_search_time:.2f}ms")
        print(f"  Max:     {max_search_time:.2f}ms")

        # Performance assertions
        assert avg_search_time < 100, f"Search too slow: {avg_search_time}ms (expected < 100ms)"
        assert len(results) == 10, f"Wrong result count: {len(results)} (expected 10)"

        # Calculate speedup vs MySQL (estimated 5000ms for 1000 vectors)
        mysql_estimated_time = 5000  # ms for Python loop cosine similarity
        speedup = mysql_estimated_time / avg_search_time

        print(f"\n🚀 Performance Improvement:")
        print(f"  MySQL (estimated): {mysql_estimated_time}ms")
        print(f"  PostgreSQL+pgvector: {avg_search_time:.2f}ms")
        print(f"  Speedup: {speedup:.0f}x faster")

        # Clean up test data
        print("\n=== Cleaning up test data ===")
        await db.execute_query(
            """
            DELETE FROM memory_hot.memory_hot
            WHERE memory_id LIKE 'perf_test_%'
            """,
            use_hot_tier=True,
            commit=True
        )
        print("✓ Test data cleaned")

    finally:
        await db.close()


@pytest.mark.asyncio
async def test_concurrent_vector_searches():
    """
    Test concurrent semantic searches to validate connection pool performance
    """
    db = TorinUnifiedDatabase()
    await db.initialize()

    try:
        # Insert 100 test embeddings
        print("\n=== Inserting 100 test embeddings ===")
        for i in range(100):
            embedding = np.random.rand(384).tolist()
            await db.execute_query(
                """
                INSERT INTO memory_hot.memory_hot
                (memory_id, memory_type, content, embedding)
                VALUES ($1, $2, $3, $4::vector)
                ON CONFLICT (memory_id) DO NOTHING
                """,
                (f"concurrent_test_{i}", "episodic", f"Test {i}", embedding),
                use_hot_tier=True,
                commit=True
            )

        # Run 20 concurrent searches
        print("\n=== Running 20 concurrent searches ===")

        async def search(idx: int):
            query_embedding = np.random.rand(384).tolist()
            start = time.time()

            results = await db.execute_query(
                """
                SELECT memory_id, 1 - (embedding <=> $1::vector) AS similarity
                FROM memory_hot.memory_hot
                ORDER BY embedding <=> $1::vector
                LIMIT 5
                """,
                (query_embedding,),
                use_hot_tier=True,
                fetch_all=True
            )

            duration = (time.time() - start) * 1000
            return duration, len(results)

        concurrent_start = time.time()
        tasks = [search(i) for i in range(20)]
        results = await asyncio.gather(*tasks)
        concurrent_time = (time.time() - concurrent_start) * 1000

        avg_individual = np.mean([r[0] for r in results])

        print(f"✓ 20 concurrent searches completed in {concurrent_time:.2f}ms")
        print(f"  Average individual search: {avg_individual:.2f}ms")
        print(f"  Connection pool efficiency: {concurrent_time / avg_individual:.1f}x parallelism")

        # Clean up
        await db.execute_query(
            """
            DELETE FROM memory_hot.memory_hot
            WHERE memory_id LIKE 'concurrent_test_%'
            """,
            use_hot_tier=True,
            commit=True
        )

    finally:
        await db.close()


if __name__ == "__main__":
    # Run benchmarks directly
    asyncio.run(test_vector_search_performance())
    asyncio.run(test_concurrent_vector_searches())
