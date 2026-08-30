#!/usr/bin/env python3
"""
Comprehensive Cross-Domain Reasoning Diagnostic
Finds the exact failure point in the cross-domain reasoning pipeline
"""
import asyncio
import sys
from pathlib import Path

# Add TorinAI to path
sys.path.insert(0, str(Path(__file__).parent.parent))

async def test_domain_registry():
    """Test 1: Domain Registry"""
    print("\n" + "="*80)
    print("TEST 1: Domain Registry")
    print("="*80)

    from core.domain.domain_registry import get_domain_registry

    registry = get_domain_registry()
    print(f"\n1. Registry DB path: {registry.db_path}")
    print(f"2. Initialized: {registry.initialized}")
    print(f"3. Domains loaded: {len(registry.domains)}")

    if not registry.initialized:
        print("\n➤ Initializing...")
        await registry.initialize()
        print(f"✓ After init: {len(registry.domains)} domains loaded")

    print(f"\n4. Available domain IDs:")
    for domain_id in list(registry.domains.keys())[:20]:
        domain = registry.domains[domain_id]
        print(f"   - {domain_id}: {domain.name} ({domain.domain_type.value})")
        print(f"     Concepts: {len(domain.concepts)}, Relations: {len(domain.relations)}")

    return registry


async def test_domain_retrieval(registry):
    """Test 2: Domain Retrieval"""
    print("\n" + "="*80)
    print("TEST 2: Domain Retrieval")
    print("="*80)

    domain_ids = list(registry.domains.keys())
    if len(domain_ids) < 2:
        print("❌ Not enough domains to test")
        return None, None

    source_id = domain_ids[0]
    target_id = domain_ids[1]

    print(f"\n1. Testing retrieval of: {source_id}")
    source = await registry.get_domain(source_id)
    print(f"   Result: {'✓ Found' if source else '❌ None'}")
    if source:
        print(f"   Name: {source.name}")
        print(f"   Type: {source.domain_type.value}")
        print(f"   Concepts: {len(source.concepts)}")
        print(f"   Relations: {len(source.relations)}")

    print(f"\n2. Testing retrieval of: {target_id}")
    target = await registry.get_domain(target_id)
    print(f"   Result: {'✓ Found' if target else '❌ None'}")
    if target:
        print(f"   Name: {target.name}")
        print(f"   Type: {target.domain_type.value}")
        print(f"   Concepts: {len(target.concepts)}")
        print(f"   Relations: {len(target.relations)}")

    return source_id, target_id, source, target


async def test_structural_similarities(reasoner, source, target):
    """Test 3: Structural Similarity Finding"""
    print("\n" + "="*80)
    print("TEST 3: Structural Similarity Finding")
    print("="*80)

    if not source or not target:
        print("❌ Cannot test - domains not loaded")
        return []

    print(f"\n1. Source domain concepts:")
    for concept_id, concept in list(source.concepts.items())[:5]:
        print(f"   - {concept_id}: {concept.name} ({concept.concept_type.value})")

    print(f"\n2. Target domain concepts:")
    for concept_id, concept in list(target.concepts.items())[:5]:
        print(f"   - {concept_id}: {concept.name} ({concept.concept_type.value})")

    print(f"\n3. Finding structural similarities...")
    try:
        mappings = await reasoner._find_structural_similarities(source, target)
        print(f"   ✓ Found {len(mappings)} structural mappings")

        for i, mapping in enumerate(mappings[:5]):
            print(f"\n   Mapping {i+1}:")
            print(f"     Source: {mapping['source_concept']}")
            print(f"     Target: {mapping['target_concept']}")
            print(f"     Similarity: {mapping['similarity']:.3f}")

        return mappings
    except Exception as e:
        print(f"   ❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return []


async def test_analogical_reasoning(reasoner, source_id, target_id):
    """Test 4: Full Analogical Reasoning"""
    print("\n" + "="*80)
    print("TEST 4: Full Analogical Reasoning Pipeline")
    print("="*80)

    from core.domain.cross_domain_reasoner import ReasoningContext, ReasoningStrategy

    context = ReasoningContext(
        source_domain_id=source_id,
        target_domain_id=target_id,
        reasoning_goal="Diagnostic test",
        strategy=ReasoningStrategy.ANALOGICAL,
        confidence_threshold=0.0  # Accept any result
    )

    print(f"\n1. Testing analogical reasoning...")
    print(f"   Source: {source_id}")
    print(f"   Target: {target_id}")

    try:
        result = await reasoner._analogical_reasoning(context)

        print(f"\n2. Results:")
        print(f"   Success: {result.success}")
        print(f"   Confidence: {result.confidence:.3f}")
        print(f"   Mappings generated: {len(result.generated_mappings)}")
        print(f"   Insights generated: {len(result.new_insights)}")
        print(f"   Reasoning steps: {len(result.reasoning_steps)}")

        if result.reasoning_steps:
            print(f"\n3. Reasoning steps:")
            for i, step in enumerate(result.reasoning_steps):
                print(f"   Step {i+1}: {step}")

        if result.new_insights:
            print(f"\n4. Insights:")
            for i, insight in enumerate(result.new_insights[:5]):
                print(f"   {i+1}. {insight}")

        return result

    except Exception as e:
        print(f"   ❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return None


async def test_memory_storage(result, source_id, target_id):
    """Test 5: Memory Storage"""
    print("\n" + "="*80)
    print("TEST 5: Memory Storage")
    print("="*80)

    if not result:
        print("❌ Cannot test - no result from reasoning")
        return False

    print(f"\n1. Checking if result meets storage criteria:")
    print(f"   result.success: {result.success}")
    print(f"   result.confidence: {result.confidence:.3f}")
    print(f"   Meets threshold (success AND confidence > 0.5): {result.success and result.confidence > 0.5}")

    if not (result.success and result.confidence > 0.5):
        print("\n❌ Result does NOT meet storage criteria")
        print("   Memory storage code will not execute")
        return False

    print("\n2. Testing memory storage...")
    try:
        from core.memory import get_memory_agent
        from core.memory.utils.interfaces import MemoryType

        memory_agent = await get_memory_agent()

        thinking_state = {
            "reasoning_id": result.reasoning_id,
            "source_domain": source_id,
            "target_domain": target_id,
            "strategy": "analogical",
            "justification": {
                "store_reason": ["cross_domain_test"],
                "decision_summary": "Test cross-domain reasoning memory storage"
            },
            "outcome": {
                "action_type": "cross_domain_reasoning",
                "confidence": result.confidence
            }
        }

        success, memory_id = await memory_agent.store_memory(
            memory_type=MemoryType.SEMANTIC,
            content=f"Cross-domain test: {len(result.new_insights)} insights, {len(result.generated_mappings)} mappings",
            importance_score=result.confidence,
            confidence_score=result.confidence,
            tags=["cross_domain_test", source_id, target_id],
            thinking_state=thinking_state
        )

        if success:
            print(f"   ✓ Memory stored successfully: {memory_id}")
            return True
        else:
            print("   ❌ Memory storage failed")
            return False

    except Exception as e:
        print(f"   ❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False


async def main():
    """Main diagnostic runner"""
    print("="*80)
    print("Cross-Domain Reasoning Comprehensive Diagnostic")
    print("="*80)

    try:
        # Test 1: Domain Registry
        registry = await test_domain_registry()

        # Test 2: Domain Retrieval
        source_id, target_id, source, target = await test_domain_retrieval(registry)

        if not source or not target:
            print("\n" + "="*80)
            print("❌ CRITICAL: Domains not loaded - cannot continue")
            print("="*80)
            return

        # Get reasoner
        from core.domain.cross_domain_reasoner import get_cross_domain_reasoner
        reasoner = get_cross_domain_reasoner()

        # Test 3: Structural Similarities
        mappings = await test_structural_similarities(reasoner, source, target)

        # Test 4: Analogical Reasoning
        result = await test_analogical_reasoning(reasoner, source_id, target_id)

        # Test 5: Memory Storage
        if result:
            stored = await test_memory_storage(result, source_id, target_id)

        # Summary
        print("\n" + "="*80)
        print("DIAGNOSTIC SUMMARY")
        print("="*80)
        print(f"✓ Domains loaded: {len(registry.domains)}")
        print(f"✓ Source domain: {'Found' if source else 'Missing'}")
        print(f"✓ Target domain: {'Found' if target else 'Missing'}")
        print(f"✓ Structural mappings: {len(mappings) if mappings else 0}")
        if result:
            print(f"✓ Reasoning success: {result.success}")
            print(f"✓ Confidence: {result.confidence:.3f}")
            print(f"✓ Final mappings: {len(result.generated_mappings)}")
            print(f"✓ Insights: {len(result.new_insights)}")
        else:
            print("❌ Reasoning failed")

        print("="*80)

    except Exception as e:
        print(f"\n❌ FATAL ERROR: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
