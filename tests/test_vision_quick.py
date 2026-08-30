#!/usr/bin/env python3
"""
Quick test - just verify simple vision query is fast
"""
import pytest
import asyncio
import sys
from pathlib import Path
import time

# Add TorinAI to path
sys.path.insert(0, str(Path(__file__).parent))

from core.reasoning.neural_bridge import NeuralSymbolicBridge, ReasoningRequest, ReasoningMode


@pytest.mark.asyncio
async def test_quick():
    print("Testing simple vision query...")

    bridge = NeuralSymbolicBridge()
    await bridge.initialize()

    test_image = "/Users/stefan/Dominion Labs/TorinAI/test_data/vision_test.png"

    start = time.time()

    request = ReasoningRequest(
        query="What color is the circle?",  # Simple
        mode=ReasoningMode.NEURAL,
        image=test_image
    )

    result = await bridge.reason(request)
    elapsed = time.time() - start

    print(f"\nQuery: {request.query}")
    print(f"Answer: {result.answer}")
    print(f"Time: {elapsed:.2f}s")

    if elapsed < 15:
        print(f"\n✓ FAST ({elapsed:.2f}s) - Vision-only pipeline working!")
    else:
        print(f"\n✗ SLOW ({elapsed:.2f}s) - THE MAIN AGENT may have been used")

    # Check system prompt
    if hasattr(result, 'metadata') and result.metadata:
        print(f"\nMetadata: {result.metadata}")


if __name__ == "__main__":
    asyncio.run(test_quick())
