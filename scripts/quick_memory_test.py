#!/usr/bin/env python3
"""
Quick Memory Test
==================
Quick test to verify memory agent can store and retrieve memories
"""
import asyncio
import sys
from pathlib import Path
from datetime import datetime

# Add TorinAI to path
sys.path.insert(0, str(Path(__file__).parent.parent))


async def test_memory_agent():
    """Test memory agent store/retrieve"""
    print("="*80)
    print("Quick Memory Agent Test")
    print("="*80)

    try:
        from core.memory import get_memory_agent
        from core.memory.utils.interfaces import MemoryType

        print("\n1. Getting memory agent...")
        memory_agent = await get_memory_agent()
        print("   ✓ Memory agent initialized")

        print("\n2. Storing test memory with RICH METADATA...")

        # Build rich metadata
        thinking_state = {
            "test_run": datetime.now().isoformat(),
            "test_type": "quick_verification",
            # RICH METADATA: Justification
            "justification": {
                "store_reason": [
                    "memory_system_test",
                    "verification",
                    "quick_test"
                ],
                "decision_summary": "Quick test to verify memory storage pipeline is working",
                "alternatives_considered": [
                    "unit_test",
                    "integration_test",
                    "manual_testing"
                ],
                "rejected_because": [
                    "quick_verification_needed",
                    "end_to_end_test_preferred"
                ],
                "complexity_assessment": "low",
                "novelty_assessment": "routine"
            },
            # RICH METADATA: Outcome
            "outcome": {
                "action_type": "memory_system_test",
                "action_summary": "Quick verification that memory storage works end-to-end",
                "affected_components": ["memory_agent", "mysql_storage", "memory_hot_table"],
                "created_new_knowledge": False,
                "confidence": 1.0,
                "impact_assessment": "minimal",
                "verification_status": "verified",
                "success_criteria": {
                    "memory_stored": True,
                    "rich_metadata_included": True
                }
            }
        }

        decision_factors = {
            "test_metadata": {
                "timestamp": datetime.now().isoformat(),
                "purpose": "verification"
            }
        }

        success, memory_id = await memory_agent.store_memory(
            memory_type=MemoryType.EPISODIC,
            content="Quick test memory - verifying storage pipeline works correctly",
            importance_score=0.7,
            confidence_score=1.0,
            tags=["test", "quick_verification", "memory_pipeline"],
            thinking_state=thinking_state,
            decision_factors=decision_factors,
            reasoning_trace=[
                "Test initiated",
                "Memory agent obtained",
                "Rich metadata generated",
                "Storage attempted"
            ],
            emotional_context={"test_confidence": 1.0}
        )

        if success and memory_id:
            print(f"   ✓ Memory stored successfully!")
            print(f"   Memory ID: {memory_id}")

            print("\n3. Retrieving stored memory...")
            # Try to retrieve it
            memories = await memory_agent.retrieve_memories(
                query="quick verification test",
                limit=1
            )

            if memories:
                print(f"   ✓ Memory retrieved successfully!")
                print(f"   Retrieved {len(memories)} memory/memories")

                mem = memories[0]
                print(f"\n   Memory Details:")
                print(f"     - ID: {mem.memory_id}")
                print(f"     - Type: {mem.memory_type.value}")
                print(f"     - Content: {mem.content[:80]}...")
                print(f"     - Importance: {mem.importance_score:.2f}")
                print(f"     - Confidence: {mem.confidence_score:.2f}")
                print(f"     - Tags: {', '.join(mem.tags[:5])}")

                # Check for rich metadata
                if mem.thinking_state:
                    has_justification = "justification" in mem.thinking_state
                    has_outcome = "outcome" in mem.thinking_state

                    print(f"\n   Rich Metadata Check:")
                    print(f"     - Justification: {'✓ Present' if has_justification else '❌ MISSING'}")
                    print(f"     - Outcome: {'✓ Present' if has_outcome else '❌ MISSING'}")

                    if has_justification and has_outcome:
                        print("\n   ✓✓✓ FULL RICH METADATA CONFIRMED! ✓✓✓")
                    else:
                        print("\n   ⚠️  Rich metadata incomplete")
                else:
                    print("\n   ❌ No thinking_state found!")

                print("\n" + "="*80)
                print("TEST RESULT: ✓ SUCCESS - Memory pipeline working correctly!")
                print("="*80)

                return True

            else:
                print("   ❌ Failed to retrieve memory")
                return False

        else:
            print(f"   ❌ Failed to store memory")
            print(f"   Success: {success}, Memory ID: {memory_id}")
            return False

    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False


async def main():
    """Main entry point"""
    result = await test_memory_agent()

    if not result:
        print("\n❌ Test failed!")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
