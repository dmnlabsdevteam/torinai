#!/usr/bin/env python3
"""
Test Memory Capture - Version 2
Simpler test to verify reasoning steps extraction
"""
import asyncio
import sys
from pathlib import Path

project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
load_dotenv(project_root / ".env")

from core.services.unified_llm import get_llm_service
from core.reasoning.neural_bridge import get_neural_bridge, ReasoningRequest, ReasoningMode
from core.memory import get_memory_agent

async def main():
    print("=" * 80)
    print("MEMORY CAPTURE TEST V2 - Reasoning Steps Extraction")
    print("=" * 80)

    # Initialize services
    print("\n[INIT] Loading LLM service...")
    llm = get_llm_service()
    await llm.initialize()
    print("✓ LLM initialized")

    print("\n[INIT] Loading neural bridge...")
    neural_bridge = get_neural_bridge()
    await neural_bridge.initialize()
    print("✓ Neural bridge initialized")

    print("\n[INIT] Loading memory agent...")
    memory_agent = await get_memory_agent()
    await memory_agent.initialize()
    print("✓ Memory agent initialized")

    # Query BEFORE test
    print("\n[MEMORY CHECK] Querying memories BEFORE test...")
    before_count = await memory_agent.query_by_tags(["neural"], limit=100)
    print(f"Memories before test: {len(before_count)}")

    # Test reasoning task with explicit multi-step thinking
    print("\n[TEST] Running reasoning task...")
    request = ReasoningRequest(
        query="Analyze this problem: What are the 3 main benefits of modular software architecture? List them clearly with explanations.",
        context=["Focus on software engineering principles", "Provide concrete examples"],
        mode=ReasoningMode.NEURAL
    )

    result = await neural_bridge.reason(request)

    print(f"\n[RESULT] Answer: {result.answer[:200]}...")
    print(f"[RESULT] Confidence: {result.confidence}")
    print(f"[RESULT] Reasoning steps extracted: {len(result.reasoning_steps)}")
    for i, step in enumerate(result.reasoning_steps, 1):
        print(f"  Step {i}: {step[:100]}...")

    # Small delay for memory to be stored
    await asyncio.sleep(2)

    # Query AFTER test
    print("\n[MEMORY CHECK] Querying memories AFTER test...")
    after_count = await memory_agent.query_by_tags(["neural"], limit=100)
    print(f"Memories after test: {len(after_count)}")

    # Show new memories
    new_memories = len(after_count) - len(before_count)
    print(f"\n[SUMMARY] New memories captured: {new_memories}")

    if new_memories > 0:
        print("\n✓ SUCCESS: Memory captured!")
        latest = after_count[0] if after_count else None
        if latest:
            print(f"  Memory ID: {latest.get('memory_id', 'N/A')}")
            print(f"  Content: {str(latest.get('content', 'N/A'))[:200]}...")
            print(f"  Tags: {latest.get('tags', [])}")
    else:
        print("\n✗ FAILURE: No memories captured")

    # Cleanup
    if llm and hasattr(llm, 'shutdown'):
        await llm.shutdown()

    print("\n" + "=" * 80)

if __name__ == "__main__":
    asyncio.run(main())
