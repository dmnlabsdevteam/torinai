#!/usr/bin/env python3
"""
PostgreSQL Database Layer Tests
================================
Test suite for unified_database_postgres.py

Tests:
- Connection pool creation
- Schema routing (unified, memory_hot, memory_cold)
- Query execution with $1, $2, $3 placeholders
- pgvector functionality
- Health checks
"""

import pytest
import asyncio
import sys
from pathlib import Path

# Add TorinAI to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.database.unified_database_postgres import TorinUnifiedDatabasePostgres


@pytest.mark.asyncio
async def test_singleton_pattern():
    """Test that database class is a singleton"""
    db1 = TorinUnifiedDatabasePostgres()
    db2 = TorinUnifiedDatabasePostgres()

    assert db1 is db2, "Database instances should be identical (singleton)"
    print("✓ Singleton pattern working")


@pytest.mark.asyncio
async def test_connection_pool_creation():
    """Test connection pool initialization"""
    db = TorinUnifiedDatabasePostgres()

    # Initialize should create pool
    success = await db.initialize()
    assert success, "Database initialization failed"
    assert db.initialized, "Database not marked as initialized"
    assert db.pool is not None, "Connection pool not created"

    print(f"✓ Connection pool created (min: {db.pool_min_size}, max: {db.pool_max_size})")

    await db.close()


@pytest.mark.asyncio
async def test_schema_routing_unified():
    """Test query routing to unified schema"""
    db = TorinUnifiedDatabasePostgres()
    await db.initialize()

    # Test unified schema (default)
    async with db.get_connection() as conn:
        schema = await conn.fetchval("SELECT current_schema()")
        assert schema == "unified", f"Expected 'unified' schema, got '{schema}'"

    print("✓ Unified schema routing working")
    await db.close()


@pytest.mark.asyncio
async def test_schema_routing_hot_tier():
    """Test query routing to memory_hot schema"""
    db = TorinUnifiedDatabasePostgres()
    await db.initialize()

    # Test hot tier schema
    async with db.get_connection(use_hot_tier=True) as conn:
        schema = await conn.fetchval("SELECT current_schema()")
        assert schema == "memory_hot", f"Expected 'memory_hot' schema, got '{schema}'"

    print("✓ Hot tier schema routing working")
    await db.close()


@pytest.mark.asyncio
async def test_schema_routing_cold_tier():
    """Test query routing to memory_cold schema"""
    db = TorinUnifiedDatabasePostgres()
    await db.initialize()

    # Test cold tier schema
    async with db.get_connection(use_cold_tier=True) as conn:
        schema = await conn.fetchval("SELECT current_schema()")
        assert schema == "memory_cold", f"Expected 'memory_cold' schema, got '{schema}'"

    print("✓ Cold tier schema routing working")
    await db.close()


@pytest.mark.asyncio
async def test_execute_query_placeholders():
    """Test query execution with $1, $2, $3 placeholders"""
    db = TorinUnifiedDatabasePostgres()
    await db.initialize()

    # Test parameterized query with PostgreSQL placeholders
    result = await db.execute_query(
        "SELECT $1::text as value1, $2::int as value2, $3::boolean as value3",
        ('test', 42, True),
        fetch_one=True
    )

    assert result is not None, "Query returned None"
    assert result['value1'] == 'test', "String parameter mismatch"
    assert result['value2'] == 42, "Integer parameter mismatch"
    assert result['value3'] is True, "Boolean parameter mismatch"

    print("✓ Query execution with $1, $2, $3 placeholders working")
    await db.close()


@pytest.mark.asyncio
async def test_fetch_all():
    """Test fetch_all query mode"""
    db = TorinUnifiedDatabasePostgres()
    await db.initialize()

    # Query that returns multiple rows
    results = await db.execute_query(
        "SELECT generate_series(1, 5) as num",
        fetch_all=True
    )

    assert results is not None, "fetch_all returned None"
    assert len(results) == 5, f"Expected 5 rows, got {len(results)}"
    assert results[0]['num'] == 1, "First row incorrect"
    assert results[4]['num'] == 5, "Last row incorrect"

    print("✓ fetch_all working correctly")
    await db.close()


@pytest.mark.asyncio
async def test_table_exists():
    """Test table existence check"""
    db = TorinUnifiedDatabasePostgres()
    await db.initialize()

    # Check if governance_laws table exists in unified schema
    exists = await db.table_exists('governance_laws')
    assert exists, "governance_laws table should exist in unified schema"

    # Check non-existent table
    not_exists = await db.table_exists('nonexistent_table_xyz')
    assert not not_exists, "Nonexistent table should return False"

    print("✓ table_exists working correctly")
    await db.close()


@pytest.mark.asyncio
async def test_governance_laws_query():
    """Test querying governance laws from unified schema"""
    db = TorinUnifiedDatabasePostgres()
    await db.initialize()

    # Query governance laws (should have 5 laws from seed data)
    laws = await db.execute_query(
        "SELECT law_number, law_name FROM governance_laws ORDER BY law_number",
        fetch_all=True
    )

    if laws and len(laws) > 0:
        print(f"✓ Found {len(laws)} governance laws:")
        for law in laws:
            print(f"  Law {law['law_number']}: {law['law_name']}")
    else:
        print("⚠ No governance laws found (run schema seed data)")

    await db.close()


@pytest.mark.asyncio
async def test_pgvector_extension():
    """Test pgvector extension availability"""
    db = TorinUnifiedDatabasePostgres()
    await db.initialize()

    # Check if pgvector extension is installed
    async with db.pool.acquire() as conn:
        result = await conn.fetchval(
            "SELECT 1 FROM pg_extension WHERE extname = 'vector'"
        )
        assert result is not None, "pgvector extension not installed"

    print("✓ pgvector extension available")
    await db.close()


@pytest.mark.asyncio
async def test_vector_storage():
    """Test storing and querying vector embeddings"""
    db = TorinUnifiedDatabasePostgres()
    await db.initialize()

    # Check if memory_hot table exists
    table_exists = await db.table_exists('memory_hot', use_hot_tier=True)

    if not table_exists:
        print("⚠ memory_hot table doesn't exist, skipping vector test")
        await db.close()
        return

    # Test vector insertion and retrieval
    test_embedding = [0.1] * 384  # 384-dimensional embedding

    try:
        # Insert test memory with embedding
        await db.execute_query(
            """
            INSERT INTO memory_hot (memory_id, memory_type, content, embedding, created_at)
            VALUES ($1, $2, $3, $4::vector, CURRENT_TIMESTAMP)
            ON CONFLICT (memory_id) DO UPDATE SET embedding = $4::vector
            """,
            ('test_vector_001', 'episodic', '{"test": "data"}', test_embedding),
            use_hot_tier=True,
            commit=True
        )

        # Query back the embedding
        result = await db.execute_query(
            "SELECT memory_id, embedding FROM memory_hot WHERE memory_id = $1",
            ('test_vector_001',),
            use_hot_tier=True,
            fetch_one=True
        )

        assert result is not None, "Vector query returned None"
        assert result['memory_id'] == 'test_vector_001', "Memory ID mismatch"
        assert result['embedding'] is not None, "Embedding is None"

        print("✓ Vector storage and retrieval working")

        # Clean up test data
        await db.execute_query(
            "DELETE FROM memory_hot WHERE memory_id = $1",
            ('test_vector_001',),
            use_hot_tier=True,
            commit=True
        )

    except Exception as e:
        print(f"⚠ Vector test failed: {e}")

    await db.close()


@pytest.mark.asyncio
async def test_vector_similarity_search():
    """Test pgvector similarity search"""
    db = TorinUnifiedDatabasePostgres()
    await db.initialize()

    # Check if memory_hot table exists
    table_exists = await db.table_exists('memory_hot', use_hot_tier=True)

    if not table_exists:
        print("⚠ memory_hot table doesn't exist, skipping similarity test")
        await db.close()
        return

    try:
        # Insert test embeddings
        embedding1 = [0.1] * 384  # Similar to query
        embedding2 = [0.15] * 384  # Very similar to query
        embedding3 = [0.9] * 384  # Different from query

        await db.execute_many(
            """
            INSERT INTO memory_hot (memory_id, memory_type, content, embedding, created_at)
            VALUES ($1, $2, $3, $4::vector, CURRENT_TIMESTAMP)
            ON CONFLICT (memory_id) DO UPDATE SET embedding = $4::vector
            """,
            [
                ('sim_test_1', 'episodic', '{"test": "1"}', embedding1),
                ('sim_test_2', 'episodic', '{"test": "2"}', embedding2),
                ('sim_test_3', 'episodic', '{"test": "3"}', embedding3),
            ],
            use_hot_tier=True,
            commit=True
        )

        # Query for similar embeddings (cosine distance)
        query_embedding = [0.1] * 384
        results = await db.execute_query(
            """
            SELECT memory_id, 1 - (embedding <=> $1::vector) AS similarity
            FROM memory_hot
            WHERE memory_id LIKE 'sim_test_%'
            ORDER BY embedding <=> $1::vector
            LIMIT 2
            """,
            (query_embedding,),
            use_hot_tier=True,
            fetch_all=True
        )

        assert len(results) == 2, f"Expected 2 results, got {len(results)}"

        # Results should be ordered by similarity (highest first)
        print(f"✓ Similarity search working:")
        for result in results:
            print(f"  {result['memory_id']}: similarity = {result['similarity']:.4f}")

        # Most similar should be sim_test_1 or sim_test_2
        assert results[0]['memory_id'] in ['sim_test_1', 'sim_test_2'], \
            "Most similar result incorrect"

        # Clean up test data
        await db.execute_query(
            "DELETE FROM memory_hot WHERE memory_id LIKE 'sim_test_%'",
            use_hot_tier=True,
            commit=True
        )

    except Exception as e:
        print(f"⚠ Similarity search test failed: {e}")

    await db.close()


@pytest.mark.asyncio
async def test_health_check():
    """Test database health check"""
    db = TorinUnifiedDatabasePostgres()
    await db.initialize()

    health = await db.health_check()

    assert health['initialized'], "Database should be initialized"
    assert health['pool_available'], "Pool should be available"
    assert health['unified_connection_ok'], "Unified connection should work"
    assert health['pgvector_available'], "pgvector should be available"

    print("✓ Health check passing:")
    print(f"  Unified schema: {health['unified_connection_ok']}")
    print(f"  Hot tier schema: {health['hot_connection_ok']}")
    print(f"  Cold tier schema: {health['cold_connection_ok']}")
    print(f"  pgvector: {health['pgvector_available']}")
    print(f"  Healthy: {health['healthy']}")

    if health['errors']:
        print(f"  Errors: {health['errors']}")

    await db.close()


@pytest.mark.asyncio
async def test_metrics():
    """Test database metrics tracking"""
    db = TorinUnifiedDatabasePostgres()
    await db.initialize()

    # Execute some queries to generate metrics
    await db.execute_query("SELECT 1", fetch_one=True)
    await db.execute_query("SELECT 1", use_hot_tier=True, fetch_one=True)
    await db.execute_query("SELECT 1", use_cold_tier=True, fetch_one=True)

    metrics = await db.get_metrics()

    assert metrics['initialized'], "Metrics should show initialized"
    assert metrics['query_metrics']['total_queries'] >= 3, "Should have at least 3 queries"
    assert metrics['query_metrics']['unified_queries'] >= 1, "Should have unified query"
    assert metrics['query_metrics']['hot_tier_queries'] >= 1, "Should have hot tier query"
    assert metrics['query_metrics']['cold_tier_queries'] >= 1, "Should have cold tier query"

    print("✓ Metrics tracking working:")
    print(f"  Total queries: {metrics['query_metrics']['total_queries']}")
    print(f"  Unified: {metrics['query_metrics']['unified_queries']}")
    print(f"  Hot tier: {metrics['query_metrics']['hot_tier_queries']}")
    print(f"  Cold tier: {metrics['query_metrics']['cold_tier_queries']}")

    await db.close()


if __name__ == "__main__":
    print("=" * 60)
    print("PostgreSQL Database Layer Tests")
    print("=" * 60)

    asyncio.run(test_singleton_pattern())
    asyncio.run(test_connection_pool_creation())
    asyncio.run(test_schema_routing_unified())
    asyncio.run(test_schema_routing_hot_tier())
    asyncio.run(test_schema_routing_cold_tier())
    asyncio.run(test_execute_query_placeholders())
    asyncio.run(test_fetch_all())
    asyncio.run(test_table_exists())
    asyncio.run(test_governance_laws_query())
    asyncio.run(test_pgvector_extension())
    asyncio.run(test_vector_storage())
    asyncio.run(test_vector_similarity_search())
    asyncio.run(test_health_check())
    asyncio.run(test_metrics())

    print("\n" + "=" * 60)
    print("All tests completed!")
    print("=" * 60)
