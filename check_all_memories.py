#!/usr/bin/env python3
"""Check all recent memories"""
import asyncio
import sys
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).parent))

from core.memory import get_memory_agent


async def main():
    """Check all recent memories"""
    agent = await get_memory_agent()

    # Get all memories from the last hour
    print("\nFetching all recent memories from MySQL...")

    # Direct database query
    if agent.mysql_storage:
        query = """
            SELECT memory_id, memory_type, content, tags, metadata, created_at
            FROM memory_hot
            ORDER BY created_at DESC
            LIMIT 10
        """

        async with agent.mysql_storage.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(query)
                rows = await cursor.fetchall()

                print(f"\nFound {len(rows)} recent memories:")
                print("=" * 100)

                for row in rows:
                    memory_id, memory_type, content, tags, metadata, created_at = row

                    content_preview = content[:100] if content else "No content"
                    tags_str = str(tags) if tags else "[]"
                    metadata_str = str(metadata)[:200] if metadata else "{}"

                    print(f"\nID: {memory_id}")
                    print(f"Type: {memory_type}")
                    print(f"Created: {created_at}")
                    print(f"Tags: {tags_str}")
                    print(f"Metadata: {metadata_str}...")
                    print(f"Content: {content_preview}...")

                print("\n" + "=" * 100)


if __name__ == "__main__":
    asyncio.run(main())
