#!/usr/bin/env python3
"""
Test vision → THE BRAIN → memory pipeline with COMPLEX query that deserves storage
"""
import pytest
import asyncio
import sys
from pathlib import Path

# Add TorinAI to path
sys.path.insert(0, str(Path(__file__).parent))

from core.reasoning.neural_bridge import NeuralSymbolicBridge, ReasoningRequest, ReasoningMode


@pytest.mark.asyncio
async def test_complex_vision_memory():
    print("=" * 80)
    print("Testing Vision → THE BRAIN → Memory (Complex Query)")
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

    # Test with complex vision query requiring synthesis and reasoning
    print("\n" + "=" * 80)
    print("COMPLEX QUERY: Requires vision analysis + multi-step reasoning + synthesis")
    print("=" * 80)

    test_image = "/Users/stefan/Dominion Labs/TorinAI/test_data/vision_test.png"

    request = ReasoningRequest(
        query="""Analyze this test image and provide a comprehensive evaluation:
1. What visual elements are present and what do they test?
2. What vision capabilities would this image effectively evaluate?
3. What improvements would make this a better test pattern?
4. How would you design a test suite using this as a foundation?

Provide detailed reasoning for each point.""",
        mode=ReasoningMode.NEURAL,
        image=test_image
    )

    print(f"\nQuery: {request.query[:100]}...")
    print(f"Image: {test_image}")
    print(f"Mode: {request.mode}")

    result = await bridge.reason(request)

    print(f"\n{'='*80}")
    print("RESULT:")
    print(f"{'='*80}")
    print(f"Answer: {result.answer[:300]}...")
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
            print(f"  Content: {new_memory.content[:300]}...")
            print(f"  Importance: {new_memory.importance_score}")
            print(f"  Tags: {new_memory.tags}")
            if hasattr(new_memory, 'thinking_state') and new_memory.thinking_state:
                vision_inputs = new_memory.thinking_state.get('vision_inputs', {})
                print(f"  Vision inputs: {vision_inputs}")
        else:
            print("\n✗ MEMORY STORAGE FAILED - Complex query still rejected")
            print("This indicates a deeper issue with the memory storage system")
    else:
        print("\n✗ No memory agent available")


if __name__ == "__main__":
    asyncio.run(test_complex_vision_memory())
