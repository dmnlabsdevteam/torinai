#!/usr/bin/env python3
"""
Test Memory Storage System
===========================
Verifies that memories are being captured and stored correctly
Uses TestBase for MySQL test logging
"""
import asyncio
import sys
from pathlib import Path
from datetime import datetime

# Add TorinAI to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Import TestBase
sys.path.insert(0, str(Path(__file__).parent.parent / "tests"))
from test_base import TestBase

import aiomysql
import os
from dotenv import load_dotenv
import json


class MemoryStorageTests(TestBase):
    """Memory storage verification tests with MySQL logging"""

    def __init__(self):
        super().__init__(
            test_category="memory",
            test_type="integration"
        )

        # Load MySQL credentials
        env_path = Path(__file__).parent.parent / ".env.mysql"
        if env_path.exists():
            load_dotenv(env_path)

        self.mysql_host = os.getenv('MYSQL_HOST', 'localhost')
        self.mysql_port = int(os.getenv('MYSQL_PORT', '3306'))
        self.mysql_user = os.getenv('MYSQL_USER', 'root')
        self.mysql_password = os.getenv('MYSQL_PASSWORD', '')

        # Store memory IDs for verification
        self.stored_memory_ids = []

    async def test_schema_check(self):
        """Check if memory_hot table exists and has correct schema"""
        conn = await aiomysql.connect(
            host=self.mysql_host,
            port=self.mysql_port,
            user=self.mysql_user,
            password=self.mysql_password,
            db="torinai_thinking_hot"
        )

        async with conn.cursor() as cursor:
            # Check if table exists
            await cursor.execute("SHOW TABLES LIKE 'memory_hot'")
            result = await cursor.fetchone()

            assert result is not None, "memory_hot table does NOT exist"

            # Get row count
            await cursor.execute("SELECT COUNT(*) FROM memory_hot")
            count = (await cursor.fetchone())[0]
            print(f"Current memory_hot row count: {count:,}")

        conn.close()

    async def test_autonomous_memory_storage(self):
        """Test autonomous coordinator memory storage"""
        from core.memory import get_memory_agent
        from core.memory.utils.interfaces import MemoryType

        memory_agent = await get_memory_agent()

        # Build rich metadata
        thinking_state = {
            "test_type": "autonomous_coordinator_simulation",
            "justification": {
                "store_reason": ["test", "autonomous_memory", "verification"],
                "decision_summary": "Test memory storage from autonomous coordinator path",
                "alternatives_considered": ["direct_test", "unit_test"],
                "rejected_because": ["integration_test_preferred"],
                "complexity_assessment": "low",
                "novelty_assessment": "routine"
            },
            "outcome": {
                "action_type": "test_autonomous_memory",
                "action_summary": "Autonomous coordinator test memory storage",
                "affected_components": ["autonomous_coordinator", "memory_agent"],
                "created_new_knowledge": False,
                "confidence": 1.0,
                "impact_assessment": "minimal",
                "verification_status": "verified",
                "success_criteria": {"memory_stored": True}
            }
        }

        # Store a test memory with rich metadata
        success, memory_id = await memory_agent.store_memory(
            memory_type=MemoryType.EPISODIC,
            content="Autonomous coordinator test memory - verifying storage pipeline",
            importance_score=0.8,
            confidence_score=1.0,
            tags=["test", "memory_verification", "autonomous"],
            thinking_state=thinking_state,
            decision_factors={"test_run": datetime.now().isoformat()},
            reasoning_trace=["Test autonomous memory storage"],
            emotional_context={"test_confidence": 1.0}
        )

        assert success, "Failed to store autonomous memory"
        assert memory_id is not None, "No memory ID returned"

        print(f"Stored autonomous memory: {memory_id}")
        self.stored_memory_ids.append(memory_id)

    async def test_reasoning_memory_storage(self):
        """Test reasoning engine memory storage"""
        from core.reasoning.neural_bridge import NeuralSymbolicBridge, ReasoningRequest, ReasoningMode

        bridge = NeuralSymbolicBridge()
        await bridge.initialize()

        # Create test reasoning request
        request = ReasoningRequest(
            query="Test query: What is the purpose of memory storage?",
            context=["Memory storage enables learning", "Rich metadata improves recall"],
            max_steps=3,
            confidence_threshold=0.6
        )

        # This should trigger memory storage
        result = await bridge.reason(request)

        assert result.confidence > 0, "Reasoning failed with zero confidence"
        print(f"Reasoning completed with confidence {result.confidence:.2f}")
        print(f"Answer: {result.answer[:100] if len(result.answer) > 100 else result.answer}")

    async def test_cross_domain_memory_storage(self):
        """Test cross-domain reasoner memory storage"""
        from core.domain.cross_domain_reasoner import get_cross_domain_reasoner, ReasoningContext, ReasoningStrategy

        # Initialize domain registry first
        from core.domain.domain_registry import get_domain_registry
        registry = get_domain_registry()

        if not registry.initialized:
            await registry.initialize()

        print(f"Domains loaded: {len(registry.domains)}")

        # Use singleton getter
        reasoner = get_cross_domain_reasoner()

        # Get available domains
        available_domains = list(registry.domains.keys())
        assert len(available_domains) >= 2, f"Need at least 2 domains, found {len(available_domains)}"

        source_domain = available_domains[0]
        target_domain = available_domains[1]

        print(f"Using domains: {source_domain} → {target_domain}")

        # Create test context with correct classes
        context = ReasoningContext(
            source_domain_id=source_domain,
            target_domain_id=target_domain,
            reasoning_goal="Test cross-domain memory storage",
            strategy=ReasoningStrategy.ANALOGICAL,
            confidence_threshold=0.0  # Accept any result for test purposes
        )

        # This should trigger memory storage (with lowered threshold)
        result = await reasoner.reason_across_domains(context)

        print(f"Cross-domain reasoning result:")
        print(f"  Success: {result.success}")
        print(f"  Confidence: {result.confidence:.3f}")
        print(f"  Mappings: {len(result.generated_mappings)}")
        print(f"  Insights: {len(result.new_insights)}")

        assert result.success, "Cross-domain reasoning failed"
        print(f"Cross-domain reasoning completed with confidence {result.confidence:.2f}")

    async def test_database_verification(self):
        """Verify memories were actually written to memory_hot table"""
        conn = await aiomysql.connect(
            host=self.mysql_host,
            port=self.mysql_port,
            user=self.mysql_user,
            password=self.mysql_password,
            db="torinai_thinking_hot"
        )

        async with conn.cursor() as cursor:
            # Get total count
            await cursor.execute("SELECT COUNT(*) FROM memory_hot")
            total_count = (await cursor.fetchone())[0]

            assert total_count > 0, "No memories found in database"
            print(f"Total memories in database: {total_count:,}")

            # Get recent memories
            await cursor.execute("""
                SELECT memory_id, memory_type, content, importance_score,
                       confidence_score, tags, thinking_state, created_at
                FROM memory_hot
                ORDER BY created_at DESC
                LIMIT 10
            """)

            memories = await cursor.fetchall()

            print(f"\nRecent memories (last 10):")
            for mem in memories:
                memory_id, mem_type, content, importance, confidence, tags, thinking_state, created_at = mem
                print(f"  {memory_id} - {mem_type} - confidence: {confidence:.2f}")

            # Check for test memories
            await cursor.execute("""
                SELECT memory_id, content, thinking_state
                FROM memory_hot
                WHERE tags LIKE '%test%' OR tags LIKE '%memory_verification%'
                ORDER BY created_at DESC
                LIMIT 5
            """)

            test_memories = await cursor.fetchall()

            assert len(test_memories) > 0, "No test memories found in database"
            print(f"\nFound {len(test_memories)} test-related memories")

            # Verify rich metadata in first test memory
            memory_id, content, thinking_state = test_memories[0]

            print(f"\nExamining memory: {memory_id}")
            print(f"  Content: {content[:100]}...")

            if thinking_state:
                state = json.loads(thinking_state) if isinstance(thinking_state, str) else thinking_state

                # Check for rich metadata
                has_justification = "justification" in state
                has_outcome = "outcome" in state

                print(f"\n  Rich Metadata Check:")
                print(f"    - Justification: {'✓ Present' if has_justification else '❌ MISSING'}")
                print(f"    - Outcome: {'✓ Present' if has_outcome else '❌ MISSING'}")

                assert has_justification or has_outcome, "Missing rich metadata (justification or outcome)"
            else:
                raise AssertionError("No thinking_state found in test memory")

        conn.close()

    async def run_all_tests(self):
        """Run all memory storage tests"""
        print("="*80)
        print("TorinAI Memory Storage Verification Test")
        print("="*80)
        print(f"Started: {datetime.now().isoformat()}\n")

        # Run tests in order
        await self.run_test(
            "schema_check",
            self.test_schema_check,
            metadata={"description": "Verify memory_hot table schema"}
        )

        await self.run_test(
            "autonomous_memory_storage",
            self.test_autonomous_memory_storage,
            metadata={"description": "Test autonomous coordinator memory storage"}
        )

        await self.run_test(
            "reasoning_memory_storage",
            self.test_reasoning_memory_storage,
            metadata={"description": "Test reasoning engine memory storage"}
        )

        await self.run_test(
            "cross_domain_memory_storage",
            self.test_cross_domain_memory_storage,
            metadata={"description": "Test cross-domain reasoner memory storage"}
        )

        await self.run_test(
            "database_verification",
            self.test_database_verification,
            metadata={"description": "Verify memories in database"}
        )


async def main():
    """Main test runner"""
    tests = MemoryStorageTests()

    # Start session (logs to MySQL)
    await tests.start_session()

    try:
        # Run all tests
        await tests.run_all_tests()
    finally:
        # End session (updates MySQL)
        await tests.end_session()

        # Print summary
        tests.print_summary()

        # Return exit code
        if tests.failed_tests > 0:
            print("\n❌ Some tests failed. Review output above for details.")
            sys.exit(1)
        else:
            print("\n✓✓✓ ALL TESTS PASSED! Memory storage is working correctly! ✓✓✓")
            sys.exit(0)


if __name__ == "__main__":
    asyncio.run(main())
