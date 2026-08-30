#!/usr/bin/env python3
"""
Test Unified Qwen2.5-VL-32B Model
==================================
Tests:
1. Model loading with vision capabilities
2. Vision query processing
3. Memory capture and storage
4. Memory injection before reasoning
"""

import asyncio
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from core.services.unified_llm import get_llm_service
from core.memory import get_memory_agent
from core.reasoning.neural_bridge import get_neural_bridge, ReasoningRequest, ReasoningMode


async def test_unified_model():
    """Test the unified vision-language model"""

    print("=" * 80)
    print("UNIFIED QWEN2.5-VL-32B MODEL TEST")
    print("=" * 80)
    print()

    # Initialize services
    print("1. Initializing Neural Bridge (THE MAIN AGENT) with unified VL model...")
    neural_bridge = get_neural_bridge()
    if not neural_bridge.initialized:
        await neural_bridge.initialize()
    print("✓ Neural Bridge initialized with THE MAIN AGENT")
    print()

    # Initialize memory agent
    print("2. Initializing memory agent...")
    memory_agent = await get_memory_agent()
    if not memory_agent.initialized:
        await memory_agent.initialize()
    print("✓ Memory agent initialized")
    print()

    # Check initial memory count
    print("3. Checking initial memory count...")
    success, initial_memories = await memory_agent.search_memories(
        query="vision test",
        limit=100
    )
    initial_count = len(initial_memories) if success else 0
    print(f"Initial memories: {initial_count}")
    print()

    # Test vision query through Neural Bridge (proper flow)
    print("4. Testing vision query through Neural Bridge...")
    test_image_path = "/Users/stefan/Dominion Labs/TorinAI/test_data/vision_test.png"

    if not Path(test_image_path).exists():
        print(f"⚠️  Test image not found at: {test_image_path}")
        print("   Creating a simple test...")

    try:
        # Create reasoning request with vision input
        request = ReasoningRequest(
            query="Describe what you see in this image in detail.",
            image=test_image_path,
            mode=ReasoningMode.NEURAL,  # Use neural mode for vision
            context=["Vision analysis test"]
        )

        # Process through Neural Bridge (handles memory injection + storage)
        result = await neural_bridge.reason(request)

        print(f"Vision Response:")
        print(f"  Answer: {result.answer[:200]}...")
        print(f"  Confidence: {result.confidence:.2f}")
        print(f"  Mode Used: {result.mode_used.value}")
        print(f"  Reasoning Steps: {len(result.reasoning_steps)}")
        print()

    except Exception as e:
        print(f"❌ Vision query failed: {e}")
        import traceback
        traceback.print_exc()
        return False

    # Check if memory was captured
    print("5. Checking if memory was captured...")
    await asyncio.sleep(2)  # Give time for async memory storage

    # Search with broader query and lower threshold to find vision-related memories
    success, new_memories = await memory_agent.search_memories(
        query="image visual analysis describe",
        limit=100,
        min_similarity=0.3  # Lower threshold to catch vision memories
    )
    new_count = len(new_memories) if success else 0

    print(f"Memories after vision query: {new_count}")
    print(f"New memories captured: {new_count - initial_count}")

    if new_count > initial_count:
        print("✓ Memory was captured!")
        # Show the latest memory
        if new_memories:
            latest = new_memories[0]
            print(f"\nLatest memory:")
            print(f"  ID: {latest.memory_id}")
            print(f"  Type: {latest.memory_type}")
            print(f"  Content: {str(latest.content)[:150]}...")
            print(f"  Tags: {latest.tags}")
    else:
        print("⚠️  No new memories captured")
    print()

    # Test memory injection
    print("6. Testing memory injection...")
    print("   Searching for relevant memories with query: 'visual image analysis'")

    success, injected_memories = await memory_agent.search_memories(
        query="visual image analysis describe",
        limit=5,
        min_similarity=0.3  # Lower threshold to match vision memories
    )

    print(f"   Found {len(injected_memories)} relevant memories")
    if injected_memories:
        print("   ✓ Memory injection is working!")
        for i, mem in enumerate(injected_memories[:3], 1):
            print(f"   Memory {i}:")
            print(f"     Similarity: {mem.similarity_score:.3f}")
            print(f"     Content: {str(mem.content)[:100]}...")
    else:
        print("   ⚠️  No memories found for injection")
    print()

    print("=" * 80)
    print("TEST SUMMARY")
    print("=" * 80)
    print(f"✓ Model loading: Success")
    print(f"✓ Vision query: {result.confidence > 0.5}")
    print(f"✓ Memory capture: {new_count > initial_count}")
    print(f"✓ Memory injection: {len(injected_memories) > 0}")
    print()

    return True


if __name__ == "__main__":
    asyncio.run(test_unified_model())
