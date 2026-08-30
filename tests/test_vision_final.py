#!/usr/bin/env python3
"""
Final test of Vision→THE BRAIN→Memory pipeline
Tests:
1. Simple query (fast, vision-only)
2. Complex query worthy of memory storage
"""
import pytest
import asyncio
import sys
from pathlib import Path

# Add TorinAI to path
sys.path.insert(0, str(Path(__file__).parent))

from core.reasoning.neural_bridge import NeuralSymbolicBridge, ReasoningRequest, ReasoningMode


@pytest.mark.asyncio
async def test_final():
    print("=" * 80)
    print("FINAL TEST: Vision Pipeline")
    print("=" * 80)

    # Initialize bridge
    bridge = NeuralSymbolicBridge()
    await bridge.initialize()

    # Check initial memory count
    initial_count = 0
    if bridge.memory_agent:
        memories_before = await bridge.memory_agent.search_memories(query="", limit=1000)
        initial_count = len(memories_before)
        print(f"\nInitial memories: {initial_count}")

    # ========== TEST 1: Simple Query (should be fast) ==========
    print("\n" + "=" * 80)
    print("TEST 1: Simple Vision Query (should skip THE BRAIN)")
    print("=" * 80)

    test_image = "/Users/stefan/Dominion Labs/TorinAI/test_data/vision_test.png"

    import time
    start = time.time()

    request1 = ReasoningRequest(
        query="What shapes are in the image?",  # Simple - should skip THE BRAIN
        mode=ReasoningMode.NEURAL,
        image=test_image
    )

    result1 = await bridge.reason(request1)
    elapsed1 = time.time() - start

    print(f"Query: {request1.query}")
    print(f"Answer: {result1.answer}")
    print(f"Time: {elapsed1:.2f}s")

    if elapsed1 < 15:
        print("✓ FAST (vision-only)")
    else:
        print(f"✗ SLOW ({elapsed1:.2f}s)")

    # Wait a moment for memory
    await asyncio.sleep(1)

    # Check memory count
    if bridge.memory_agent:
        memories_mid = await bridge.memory_agent.search_memories(query="", limit=1000)
        mid_count = len(memories_mid)
        new1 = mid_count - initial_count
        print(f"New memories from simple query: {new1} (expected: 0, trivial query rejected)")

    # ========== TEST 2: Complex Query (memory-worthy) ==========
    print("\n" + "=" * 80)
    print("TEST 2: Complex Vision Query (should store memory)")
    print("=" * 80)

    start = time.time()

    request2 = ReasoningRequest(
        query="Analyze this test image - what visual capabilities does it evaluate and why would these elements be chosen for testing?",  # Complex + long
        mode=ReasoningMode.NEURAL,
        image=test_image
    )

    result2 = await bridge.reason(request2)
    elapsed2 = time.time() - start

    print(f"Query: {request2.query[:80]}...")
    print(f"Answer: {result2.answer[:200]}...")
    print(f"Time: {elapsed2:.2f}s")

    if "analyze" in request2.query.lower() and elapsed2 > 15:
        print("✓ Used THE BRAIN for complex reasoning")
    else:
        print("? May have skipped THE BRAIN")

    # Wait for memory
    await asyncio.sleep(1)

    # Check final memory
    if bridge.memory_agent:
        memories_final = await bridge.memory_agent.search_memories(query="", limit=1000)
        final_count = len(memories_final)
        new2 = final_count - mid_count

        print(f"\n{'='*80}")
        print("MEMORY RESULTS:")
        print(f"{'='*80}")
        print(f"Initial memories: {initial_count}")
        print(f"After simple query: {mid_count} (+{new1})")
        print(f"After complex query: {final_count} (+{new2})")

        if new2 > 0:
            print("\n✓ Complex query stored in memory!")
            latest = memories_final[0]
            print(f"\nLatest memory preview:")
            print(f"  Content: {latest.content[:150]}...")
            print(f"  Importance: {latest.importance_score}")
        else:
            print("\n? Complex query not stored (may need higher complexity)")

    print(f"\n{'='*80}")
    print("FINAL TEST COMPLETE")
    print(f"{'='*80}")


if __name__ == "__main__":
    asyncio.run(test_final())
