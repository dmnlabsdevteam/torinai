#!/usr/bin/env python3
"""Check memory types in database"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from core.memory import get_memory_agent


async def main():
    """Check memory types"""
    agent = await get_memory_agent()

    # Search for vision-related memories
    success, memories = await agent.search_memories('vision image', limit=10)

    print(f"\nFound {len(memories)} vision-related memories:")
    print("=" * 80)

    for i, mem in enumerate(memories, 1):
        # Get memory type
        mem_type = mem.memory_type.value if hasattr(mem.memory_type, 'value') else str(mem.memory_type)

        # Get content preview
        content_preview = str(mem.content)[:100]

        # Get tags
        tags = list(mem.tags) if mem.tags else []

        print(f"\n{i}. Memory ID: {mem.memory_id}")
        print(f"   Type: {mem_type}")
        print(f"   Similarity: {getattr(mem, 'similarity_score', 'N/A')}")
        print(f"   Tags: {tags}")
        print(f"   Content: {content_preview}...")

        # Check metadata for has_image flag
        if hasattr(mem, 'metadata') and mem.metadata:
            has_image = mem.metadata.get('has_image', False)
            has_video = mem.metadata.get('has_video', False)
            source_system = mem.metadata.get('source_system', 'unknown')
            print(f"   Source: {source_system}, has_image={has_image}, has_video={has_video}")

    print("\n" + "=" * 80)


if __name__ == "__main__":
    asyncio.run(main())
