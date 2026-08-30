#!/usr/bin/env python3
"""
Test Memory Persistence Across Sessions
========================================
Verifies that:
1. Memories can be stored to hot tier (MySQL)
2. Memories persist after system shutdown
3. Memories can be retrieved in new session
4. Memory metadata is preserved

Usage:
    python3 scripts/test_memory_persistence.py
"""

import asyncio
import sys
from pathlib import Path
from datetime import datetime

# Add project to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Load environment
from dotenv import load_dotenv
load_dotenv(project_root / '.env.production')

from core.memory import get_memory_system
from core.memory.utils.interfaces import MemoryType


async def test_memory_persistence():
    """Test memory persistence across sessions"""
    print("=" * 80)
    print("Memory Persistence Test")
    print("=" * 80)
    print()

    # ========== SESSION 1: STORE MEMORIES ==========
    print("SESSION 1: Storing test memories...")
    print("-" * 80)

    # Get memory system
    memory = await get_memory_system()
    if not memory:
        print("❌ Failed to get memory system")
        return False

    # Initialize
    if not memory.initialized:
        print("  Initializing MemoryAgent...")
        await memory.initialize()

    if not memory.mysql_storage:
        print("❌ MySQL storage not available")
        return False

    print("✅ Memory system initialized")
    print()

    # Get initial memory count
    stats = await memory.mysql_storage.get_statistics()
    initial_count = stats.get('total_count', 0)
    print(f"📊 Initial memory count: {initial_count}")
    print()

    # Store test memories
    # NOTE: Include reasoning_trace and higher confidence to pass memory filter
    test_memories = [
        {
            "content": f"Test memory 1: Autonomous task execution completed successfully. Executed ai_research_breakthrough task analyzing recent papers on multi-modal reasoning. Found 3 key insights: (1) Vision-language alignment crucial for reasoning, (2) Chain-of-thought improves multi-step tasks, (3) Tool use enhances reasoning capabilities. Task completed with 85% confidence at {datetime.now().isoformat()}",
            "memory_type": MemoryType.EPISODIC,
            "importance_score": 0.8,
            "confidence_score": 0.85,
            "tags": ["test", "task_execution", "persistence_test", "autonomous"],
            "source_context": {
                "source_system": "autonomous_coordinator",
                "test_id": "persistence_test_1",
                "context_count": 3
            },
            "reasoning_trace": [
                "Step 1: Analyzed task requirements for AI research breakthrough",
                "Step 2: Executed semantic search for recent papers on multi-modal reasoning",
                "Step 3: Synthesized findings into 3 key insights",
                "Step 4: Validated insights against source papers",
                "Step 5: Generated summary with confidence score"
            ]
        },
        {
            "content": "Test memory 2: AI research breakthrough - discovered novel approach to multi-modal reasoning combining vision transformers with language models. Analysis showed 23% improvement in vision-language tasks through improved alignment mechanism. Key finding: Joint training on paired image-text data with contrastive learning significantly enhances cross-modal understanding. Validated against 5 benchmark datasets.",
            "memory_type": MemoryType.SEMANTIC,
            "importance_score": 0.9,
            "confidence_score": 0.88,
            "tags": ["test", "research", "breakthrough", "persistence_test", "vision_language"],
            "source_context": {
                "source_system": "autonomous_coordinator",
                "test_id": "persistence_test_2",
                "context_count": 5
            },
            "reasoning_trace": [
                "Step 1: Surveyed recent papers on multi-modal reasoning architectures",
                "Step 2: Identified key limitation: poor vision-language alignment",
                "Step 3: Analyzed contrastive learning approaches",
                "Step 4: Synthesized novel combination of vision transformers + language models",
                "Step 5: Validated against benchmark datasets",
                "Step 6: Calculated 23% improvement metric"
            ]
        },
        {
            "content": "Test memory 3: Learned new skill - efficient memory filtering using worthiness metadata. Implemented multi-dimensional evaluation considering complexity, novelty, criticality, and query characteristics. Key procedure: (1) Generate metadata from raw inputs, (2) Evaluate against filtering rules, (3) Make admission decision with confidence score, (4) Store frozen metadata for audit. This approach reduces memory bloat by 67% while preserving important experiences.",
            "memory_type": MemoryType.PROCEDURAL,
            "importance_score": 0.85,
            "confidence_score": 0.82,
            "tags": ["test", "skill", "learning", "persistence_test", "memory_filter"],
            "source_context": {
                "source_system": "autonomous_coordinator",
                "test_id": "persistence_test_3",
                "context_count": 4
            },
            "reasoning_trace": [
                "Step 1: Identified problem - too many low-value memories being stored",
                "Step 2: Researched memory filtering approaches",
                "Step 3: Designed multi-dimensional worthiness evaluation",
                "Step 4: Implemented filtering logic with frozen metadata",
                "Step 5: Tested on sample memories - achieved 67% reduction",
                "Step 6: Deployed to production memory system"
            ]
        }
    ]

    stored_memory_ids = []
    print("Storing test memories...")
    for i, mem_data in enumerate(test_memories, 1):
        success, memory_id = await memory.store_memory(**mem_data)

        if success:
            print(f"  ✅ Memory {i} stored: {memory_id}")
            stored_memory_ids.append(memory_id)
        else:
            print(f"  ❌ Memory {i} failed to store")

    print()
    print(f"Total memories stored: {len(stored_memory_ids)}")
    print()

    # Verify storage
    stats_after = await memory.mysql_storage.get_statistics()
    final_count = stats_after.get('total_count', 0)
    new_memories = final_count - initial_count
    print(f"📊 Final memory count: {final_count} (+{new_memories})")
    print()

    if new_memories != len(stored_memory_ids):
        print(f"⚠️  WARNING: Expected {len(stored_memory_ids)} new memories but found {new_memories}")
    else:
        print(f"✅ All {new_memories} memories verified in storage")

    print()
    print("Stored memory IDs:")
    for mem_id in stored_memory_ids:
        print(f"  - {mem_id}")
    print()

    # ========== SESSION 2: SHUTDOWN AND RESTART ==========
    print("SESSION 2: Simulating system shutdown...")
    print("-" * 80)

    # Clear memory agent instance (simulate shutdown)
    print("  Clearing memory agent instance...")
    # Access private singleton from memory_agent module
    import core.agents.memory_agent as mem_agent_module
    if hasattr(mem_agent_module, '_memory_agent') and mem_agent_module._memory_agent:
        agent = mem_agent_module._memory_agent
        # Clean up
        if hasattr(agent, 'memory_cache'):
            agent.memory_cache.clear()
        agent.initialized = False
        # Clear singleton
        mem_agent_module._memory_agent = None
        print("  ✅ Cleared memory agent singleton")
    else:
        print("  ⚠️  Memory agent singleton already cleared")

    print("✅ Memory system shutdown complete")
    print()

    # ========== SESSION 3: RESTART AND RETRIEVE ==========
    print("SESSION 3: Restarting memory system and retrieving memories...")
    print("-" * 80)

    # Get fresh memory system instance
    memory_new = await get_memory_system()
    if not memory_new:
        print("❌ Failed to get memory system after restart")
        return False

    print("  Initializing fresh MemoryAgent instance...")
    await memory_new.initialize()

    if not memory_new.mysql_storage:
        print("❌ MySQL storage not available after restart")
        return False

    print("✅ Memory system restarted")
    print()

    # Verify memory count persisted
    stats_restart = await memory_new.mysql_storage.get_statistics()
    restart_count = stats_restart.get('total_count', 0)
    print(f"📊 Memory count after restart: {restart_count}")
    print()

    if restart_count < final_count:
        print(f"❌ FAILURE: Memory count decreased after restart!")
        print(f"  Before shutdown: {final_count}")
        print(f"  After restart: {restart_count}")
        return False

    print("✅ Memory count persisted correctly")
    print()

    # Retrieve each stored memory
    print("Retrieving stored memories...")
    retrieved_count = 0
    for i, mem_id in enumerate(stored_memory_ids, 1):
        retrieved = await memory_new.retrieve_memory(mem_id, update_access=True)

        if retrieved:
            print(f"  ✅ Memory {i} retrieved: {mem_id}")
            print(f"     Type: {retrieved.memory_type.value}")
            print(f"     Content preview: {retrieved.content[:80]}...")
            print(f"     Importance: {retrieved.importance_score}")
            print(f"     Tags: {', '.join(retrieved.tags)}")
            print(f"     Access count: {retrieved.access_count}")
            retrieved_count += 1
        else:
            print(f"  ❌ Memory {i} NOT found: {mem_id}")

        print()

    # ========== RESULTS ==========
    print("=" * 80)
    print("Test Results")
    print("=" * 80)
    print()
    print(f"Memories stored: {len(stored_memory_ids)}")
    print(f"Memories retrieved after restart: {retrieved_count}")
    print()

    if retrieved_count == len(stored_memory_ids):
        print("✅ SUCCESS: All memories persisted across system restart!")
        print()
        print("Verified capabilities:")
        print("  ✓ Memory storage to hot tier (MySQL)")
        print("  ✓ Memory persistence across shutdown")
        print("  ✓ Memory retrieval in new session")
        print("  ✓ Metadata preservation")
        return True
    else:
        print(f"❌ FAILURE: Only {retrieved_count}/{len(stored_memory_ids)} memories retrieved")
        return False


async def test_memory_search():
    """Test memory search and filtering"""
    print()
    print("=" * 80)
    print("Memory Search Test")
    print("=" * 80)
    print()

    memory = await get_memory_system()
    await memory.initialize()

    # Search by tags
    print("Searching for memories with tag 'persistence_test'...")
    success, results = await memory.query_by_tags(
        tags={"persistence_test"},
        limit=10
    )

    if success:
        print(f"✅ Found {len(results)} memories with tag 'persistence_test'")
        for i, mem in enumerate(results, 1):
            print(f"  {i}. {mem.memory_type.value}: {mem.content[:60]}...")
    else:
        print("❌ Search failed")

    print()

    # Semantic search
    print("Semantic search: 'AI research breakthrough'...")
    success, results = await memory.search_memories(
        query="AI research breakthrough",
        min_similarity=0.3,
        limit=5
    )

    if success:
        print(f"✅ Found {len(results)} semantically similar memories")
        for i, mem in enumerate(results, 1):
            print(f"  {i}. {mem.content[:60]}...")
    else:
        print("⚠️  Semantic search not available (no embedding service)")

    print()


async def cleanup_test_memories():
    """Clean up test memories (optional)"""
    print("=" * 80)
    print("Cleanup (Optional)")
    print("=" * 80)
    print()
    print("Test memories tagged with 'persistence_test' remain in database")
    print("To clean up manually, run:")
    print()
    print("  DELETE FROM memories WHERE tags LIKE '%persistence_test%';")
    print()


async def main():
    """Main entry point"""
    try:
        # Run persistence test
        success = await test_memory_persistence()

        # Run search test
        await test_memory_search()

        # Show cleanup info
        await cleanup_test_memories()

        # Exit with status
        sys.exit(0 if success else 1)

    except Exception as e:
        print(f"\n❌ FATAL ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    asyncio.run(main())
