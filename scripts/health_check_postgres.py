#!/usr/bin/env python3
"""PostgreSQL Health Check"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.database import TorinUnifiedDatabase

async def health_check():
    """Perform comprehensive health check"""
    db = TorinUnifiedDatabase()

    try:
        await db.initialize()
        print("✓ PostgreSQL connection successful")

        # Check governance laws
        laws = await db.execute_query(
            "SELECT COUNT(*) as count FROM unified.governance_laws",
            fetch_one=True
        )
        print(f"✓ Governance laws: {laws['count']}")

        # Check memory with embeddings
        memories = await db.execute_query(
            "SELECT COUNT(*) as count FROM memory_hot.memory_hot WHERE embedding IS NOT NULL",
            use_hot_tier=True,
            fetch_one=True
        )
        print(f"✓ Memories with embeddings: {memories['count']}")

        # Test vector search
        import numpy as np
        test_embedding = np.random.rand(384).tolist()
        results = await db.execute_query(
            """
            SELECT memory_id, 1 - (embedding <=> $1::vector) AS similarity
            FROM memory_hot.memory_hot
            ORDER BY embedding <=> $1::vector
            LIMIT 1
            """,
            (test_embedding,),
            use_hot_tier=True,
            fetch_all=True
        )
        print(f"✓ Vector search functional (found {len(results)} results)")

        await db.close()
        print("\n✅ All health checks passed!")
        return True

    except Exception as e:
        print(f"\n❌ Health check failed: {e}")
        await db.close()
        return False

if __name__ == "__main__":
    result = asyncio.run(health_check())
    sys.exit(0 if result else 1)
