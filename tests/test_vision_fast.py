#!/usr/bin/env python3
"""
Test vision pipeline with simple query (should skip THE BRAIN and be fast)
"""
import pytest
import asyncio
import sys
from pathlib import Path

# Add TorinAI to path
sys.path.insert(0, str(Path(__file__).parent))

from core.reasoning.neural_bridge import NeuralSymbolicBridge, ReasoningRequest, ReasoningMode


@pytest.mark.asyncio
async def test_simple_vision():
    print("=" * 80)
    print("Testing Simple Vision Query (should skip THE BRAIN)")
    print("=" * 80)

    # Initialize bridge
    bridge = NeuralSymbolicBridge()
    await bridge.initialize()

    # Test with simple vision query
    test_image = "/Users/stefan/Dominion Labs/TorinAI/test_data/vision_test.png"

    request = ReasoningRequest(
        query="What color is the circle?",  # Simple query - should skip THE BRAIN
        mode=ReasoningMode.NEURAL,
        image=test_image
    )

    print(f"\nQuery: {request.query}")
    print(f"Image: {test_image}")
    print("Expected: Vision analysis only (no THE BRAIN)")

    import time
    start = time.time()
    result = await bridge.reason(request)
    elapsed = time.time() - start

    print(f"\n{'='*80}")
    print("RESULT:")
    print(f"{'='*80}")
    print(f"Answer: {result.answer}")
    print(f"Confidence: {result.confidence}")
    print(f"Time: {elapsed:.2f}s")
    print(f"{'='*80}")

    if elapsed < 10:
        print("\n✓ FAST! Vision-only pipeline working correctly")
    else:
        print(f"\n✗ SLOW ({elapsed:.2f}s) - THE BRAIN may have been used unnecessarily")


@pytest.mark.asyncio
async def test_complex_vision():
    print("\n" + "=" * 80)
    print("Testing Complex Vision Query (should use THE BRAIN)")
    print("=" * 80)

    # Initialize bridge
    bridge = NeuralSymbolicBridge()
    await bridge.initialize()

    test_image = "/Users/stefan/Dominion Labs/TorinAI/test_data/vision_test.png"

    request = ReasoningRequest(
        query="Analyze this image and explain what it tests",  # Complex - should use THE BRAIN
        mode=ReasoningMode.NEURAL,
        image=test_image
    )

    print(f"\nQuery: {request.query}")
    print(f"Image: {test_image}")
    print("Expected: Vision + THE BRAIN (will be slower)")

    import time
    start = time.time()
    result = await bridge.reason(request)
    elapsed = time.time() - start

    print(f"\n{'='*80}")
    print("RESULT:")
    print(f"{'='*80}")
    print(f"Answer: {result.answer[:200]}...")
    print(f"Confidence: {result.confidence}")
    print(f"Time: {elapsed:.2f}s")
    print(f"{'='*80}")

    if "qwen2-vl-2b+qwen:32b" in str(result.metadata).lower() or elapsed > 20:
        print("\n✓ THE BRAIN was used for complex reasoning")
    else:
        print("\n? THE BRAIN may have been skipped")


if __name__ == "__main__":
    asyncio.run(test_simple_vision())
    print("\n\n")
    # Uncomment to test complex query (will be slow):
    # asyncio.run(test_complex_vision())
