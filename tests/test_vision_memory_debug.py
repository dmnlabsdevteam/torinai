#!/usr/bin/env python3
"""
Test vision → THE BRAIN → memory pipeline with debug logging
"""
import pytest
import asyncio
import sys
from pathlib import Path

# Add TorinAI to path
sys.path.insert(0, str(Path(__file__).parent))

from core.reasoning.neural_bridge import NeuralSymbolicBridge, ReasoningRequest, ReasoningMode


@pytest.mark.asyncio
async def test_vision_memory():
    print("=" * 80)
    print("Testing Vision → THE BRAIN → Memory Pipeline (with debug logging)")
    print("=" * 80)

    # Initialize bridge
    bridge = NeuralSymbolicBridge()
    await bridge.initialize()

    # Check memory before
    initial_count = 0
    if bridge.memory_agent:
        memories_before = await bridge.memory_agent.search_memories(
            query="",
            limit=1000
        )
        initial_count = len(memories_before)
        print(f"\nInitial memories: {initial_count}")

    # Test with vision
    print("\n" + "=" * 80)
    print("Testing: Vision analysis → THE BRAIN reasoning")
    print("=" * 80)

    test_image = "/Users/stefan/Dominion Labs/TorinAI/test_data/vision_test.png"

    request = ReasoningRequest(
        query="What color is the circle in the image?",
        mode=ReasoningMode.NEURAL,  # Neural mode to use LLM
        image=test_image
    )

    print(f"\nQuery: {request.query}")
    print(f"Image: {test_image}")
    print(f"Mode: {request.mode}")

    result = await bridge.reason(request)

    print(f"\n{'='*80}")
    print("RESULT:")
    print(f"{'='*80}")
    print(f"Answer: {result.answer}")
    print(f"Confidence: {result.confidence}")
    print(f"Mode used: {result.mode_used}")
    print(f"{'='*80}")

    # Check memory after
    if bridge.memory_agent:
        # Small delay to ensure storage completes
        await asyncio.sleep(1)

        memories_after = await bridge.memory_agent.search_memories(
            query="",
            limit=1000
        )
        final_count = len(memories_after)
        new_count = final_count - initial_count

        print(f"\nFinal memories: {final_count}")
        print(f"New memories: {new_count}")

        if new_count > 0:
            print("\n✓ MEMORY STORAGE WORKING!")
            # Show the new memory
            new_memory = memories_after[0]
            print(f"\nLatest memory:")
            print(f"  Content: {new_memory.content[:200]}...")
            print(f"  Importance: {new_memory.importance_score}")
            print(f"  Tags: {new_memory.tags}")
        else:
            print("\n✗ MEMORY STORAGE FAILED - No new memories created")
            print("Check the debug logs above for details")
    else:
        print("\n✗ No memory agent available")


if __name__ == "__main__":
    asyncio.run(test_vision_memory())
