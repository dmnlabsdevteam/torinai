#!/usr/bin/env python3
"""
Reasoning Systems Latency Benchmark
===================================
This is a BENCHMARK, not a correctness suite. It measures latency and records
metrics; TestBase marks a case "passed" whenever the call completes without
raising, and the cases here assert nothing. A run can therefore report
"Success: 100.0%" while every proof in it came back proved=False.

Renamed from test_reasoning_systems.py so it is not mistaken for a test.
Correctness is covered by tests/test_reasoning_substrate.py, which asserts
outcomes and fails when an answer is wrong.

Note also that the theorems below are stated in natural language and in
first-order form ("For all n: n + 0 = n"). The SMT backend is propositional,
so those are expected to come back unproved with an explicit error naming the
reason -- that is correct behaviour, not a regression.

Measures:
- Abstract Reasoning Engine (Deductive, Inductive, Analogical, Causal, Temporal)
- Advanced Proof Engine (Theorem proving, verification, logical inference)
- Neural Bridge (Natural language ↔ Formal logic translation)

Loads VLM ONCE and reuses across all tests.
Logs all metrics to MySQL via TestBase.

Usage:
    python3 tests/test_reasoning_systems.py

Author: Torin AI Team
Date: January 14, 2026
"""

import asyncio
import sys
import time
from pathlib import Path
from datetime import datetime
from typing import Dict, Any

# Add project to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Load environment
from dotenv import load_dotenv
load_dotenv(project_root / '.env.production')

# Import test base
sys.path.insert(0, str(project_root / 'tests'))
from test_base import TestBase


class ReasoningSystemsTests(TestBase):
    """
    Comprehensive Reasoning Systems Tests

    Tests:
    1. Abstract Reasoning Engine
       - Deductive reasoning (general → specific)
       - Inductive reasoning (specific → general)
       - Analogical reasoning (similarity-based)
       - Causal reasoning (cause-effect)
       - Temporal reasoning (time-based)

    2. Advanced Proof Engine
       - Propositional logic proofs
       - First-order logic proofs
       - Theorem verification
       - Axiom-based reasoning

    3. Neural Bridge
       - Natural language → Formal logic
       - Hybrid reasoning (neural + symbolic)
       - Multi-modal reasoning (text + vision)
    """

    def __init__(self):
        super().__init__(
            test_category="reasoning_systems",
            test_type="integration"
        )

        # Shared systems (loaded once)
        self.llm = None
        self.abstract_reasoning = None
        self.proof_engine = None
        self.neural_bridge = None

        # Performance tracking
        self.performance_metrics = {
            "abstract_reasoning": [],
            "proof_engine": [],
            "neural_bridge": []
        }

    async def setup_systems(self):
        """Initialize all reasoning systems (run once)"""
        print("=" * 80)
        print("Initializing Reasoning Systems (one-time setup)")
        print("=" * 80)
        print()

        # 1. Load VLM Service (32GB model)
        print("Step 1: Loading VLM Service (Qwen2.5-VL-32B)...")
        start_time = time.time()

        try:
            from core.services.unified_llm import get_llm_service
            self.llm = get_llm_service()
            if not self.llm.model_loaded:
                await self.llm.initialize()

            load_time = time.time() - start_time
            print(f"✅ VLM loaded in {load_time:.2f}s")
            print()
        except Exception as e:
            print(f"❌ Failed to load VLM: {e}")
            return False

        # 2. Initialize Abstract Reasoning Engine
        print("Step 2: Initializing Abstract Reasoning Engine...")
        try:
            from core.reasoning import create_abstract_reasoning_engine
            self.abstract_reasoning = create_abstract_reasoning_engine()

            # Initialize with LLM if it has initialize method
            if hasattr(self.abstract_reasoning, 'initialize'):
                await self.abstract_reasoning.initialize()

            print("✅ Abstract Reasoning Engine initialized")
            print()
        except Exception as e:
            print(f"⚠️  Abstract Reasoning unavailable: {e}")
            self.abstract_reasoning = None

        # 3. Initialize Proof Engine
        print("Step 3: Initializing Advanced Proof Engine...")
        try:
            from core.reasoning import AdvancedProofEngine
            self.proof_engine = AdvancedProofEngine()
            print("✅ Proof Engine initialized")
            print()
        except Exception as e:
            print(f"⚠️  Proof Engine unavailable: {e}")
            self.proof_engine = None

        # 4. Initialize Neural Bridge
        print("Step 4: Initializing Neural Bridge...")
        try:
            from core.reasoning.neural_bridge import NeuralSymbolicBridge
            self.neural_bridge = NeuralSymbolicBridge()
            await self.neural_bridge.initialize()
            print("✅ Neural Bridge initialized")
            print()
        except Exception as e:
            print(f"⚠️  Neural Bridge unavailable: {e}")
            import traceback
            traceback.print_exc()
            self.neural_bridge = None

        print("=" * 80)
        print("✅ All Systems Initialized")
        print("=" * 80)
        print()

        return True

    # ========== ABSTRACT REASONING TESTS ==========

    async def test_deductive_reasoning_classic(self):
        """Test classic deductive reasoning (Socrates syllogism)"""
        if not self.abstract_reasoning:
            print("  ⚠️  Skipped: Abstract Reasoning not available")
            return

        from core.reasoning.abstract_reasoning_engine import (
            ReasoningContext, ReasoningType, ReasoningPremise
        )
        import uuid

        premises = [
            ReasoningPremise(
                premise_id="p1",
                statement="All humans are mortal",
                confidence=1.0,
                predicates=["human", "mortal"]
            ),
            ReasoningPremise(
                premise_id="p2",
                statement="Socrates is a human",
                confidence=1.0,
                predicates=["Socrates", "human"]
            )
        ]

        rules = ["If X is human then X is mortal"]

        context = ReasoningContext(
            context_id=f"deductive_{uuid.uuid4().hex[:8]}",
            domain="logic",
            problem_type="deductive_reasoning",
            premises=premises,
            rules=rules,
            target_conclusions=["Is Socrates mortal?"],
            allowed_reasoning_types=[ReasoningType.DEDUCTIVE],
            confidence_threshold=0.5
        )

        start_time = time.time()
        result = await self.abstract_reasoning.reason(context)
        latency = time.time() - start_time

        self.performance_metrics["abstract_reasoning"].append({
            "test": "deductive_classic",
            "latency_ms": latency * 1000,
            "confidence": result.overall_confidence if result else 0,
            "conclusions_count": len(result.conclusions) if result else 0,
            "success": bool(result and result.conclusions)
        })

        print(f"  Latency: {latency:.3f}s | Confidence: {result.overall_confidence:.2f}")
        if result and result.conclusions:
            print(f"  Conclusion: {result.conclusions[0].statement}")
        else:
            print(f"  No conclusions generated")

    async def test_inductive_reasoning_pattern(self):
        """Test inductive reasoning with number patterns"""
        if not self.abstract_reasoning:
            print("  ⚠️  Skipped: Abstract Reasoning not available")
            return

        from core.reasoning.abstract_reasoning_engine import (
            ReasoningContext, ReasoningType, ReasoningPremise
        )
        import uuid

        # Fibonacci pattern
        premises = [
            ReasoningPremise(premise_id="obs1", statement="First number: 1", confidence=1.0, predicates=["1"]),
            ReasoningPremise(premise_id="obs2", statement="Second number: 1", confidence=1.0, predicates=["1"]),
            ReasoningPremise(premise_id="obs3", statement="Third number: 2", confidence=1.0, predicates=["2"]),
            ReasoningPremise(premise_id="obs4", statement="Fourth number: 3", confidence=1.0, predicates=["3"]),
            ReasoningPremise(premise_id="obs5", statement="Fifth number: 5", confidence=1.0, predicates=["5"])
        ]

        context = ReasoningContext(
            context_id=f"inductive_{uuid.uuid4().hex[:8]}",
            domain="mathematics",
            problem_type="pattern_recognition",
            premises=premises,
            facts=["Sequence: 1, 1, 2, 3, 5"],
            target_conclusions=["What is the pattern and next number?"],
            allowed_reasoning_types=[ReasoningType.INDUCTIVE],
            confidence_threshold=0.5
        )

        start_time = time.time()
        result = await self.abstract_reasoning.reason(context)
        latency = time.time() - start_time

        self.performance_metrics["abstract_reasoning"].append({
            "test": "inductive_pattern",
            "latency_ms": latency * 1000,
            "confidence": result.overall_confidence if result else 0,
            "conclusions_count": len(result.conclusions) if result else 0,
            "success": bool(result and result.conclusions)
        })

        print(f"  Latency: {latency:.3f}s | Confidence: {result.overall_confidence:.2f}")
        if result and result.conclusions:
            print(f"  Pattern: {result.conclusions[0].statement}")
        else:
            print(f"  No pattern identified")

    async def test_analogical_reasoning_transfer(self):
        """Test analogical reasoning with skill transfer"""
        if not self.abstract_reasoning:
            print("  ⚠️  Skipped: Abstract Reasoning not available")
            return

        from core.reasoning.abstract_reasoning_engine import (
            ReasoningContext, ReasoningType, ReasoningPremise
        )
        import uuid

        premises = [
            ReasoningPremise(
                premise_id="case1",
                statement="Learning to play piano requires practice, coordination, and patience",
                confidence=1.0,
                predicates=["learning", "piano", "practice", "coordination", "patience"]
            ),
            ReasoningPremise(
                premise_id="case2",
                statement="Learning to play guitar requires practice, coordination, and patience",
                confidence=1.0,
                predicates=["learning", "guitar", "practice", "coordination", "patience"]
            )
        ]

        context = ReasoningContext(
            context_id=f"analogical_{uuid.uuid4().hex[:8]}",
            domain="skill_learning",
            problem_type="analogical_transfer",
            premises=premises,
            target_conclusions=["What does learning to play drums likely require?"],
            allowed_reasoning_types=[ReasoningType.ANALOGICAL],
            confidence_threshold=0.5
        )

        start_time = time.time()
        result = await self.abstract_reasoning.reason(context)
        latency = time.time() - start_time

        self.performance_metrics["abstract_reasoning"].append({
            "test": "analogical_transfer",
            "latency_ms": latency * 1000,
            "confidence": result.overall_confidence if result else 0,
            "conclusions_count": len(result.conclusions) if result else 0,
            "success": bool(result and result.conclusions)
        })

        print(f"  Latency: {latency:.3f}s | Confidence: {result.overall_confidence:.2f}")
        if result and result.conclusions:
            print(f"  Analogy: {result.conclusions[0].statement}")
        else:
            print(f"  No analogy found")

    # ========== PROOF ENGINE TESTS ==========

    async def test_proof_identity_axiom(self):
        """Test proving identity axiom (a + 0 = a)"""
        if not self.proof_engine:
            print("  ⚠️  Skipped: Proof Engine not available")
            return

        from core.reasoning.advanced_proof_engine import Theorem, LogicType
        import uuid

        theorem = Theorem(
            theorem_id=f"identity_{uuid.uuid4().hex[:8]}",
            statement="For all n: n + 0 = n",
            premises=["Identity axiom: a + 0 = a for all a"],
            logic_type=LogicType.FIRST_ORDER
        )

        start_time = time.time()
        result = await self.proof_engine.prove_theorem(
            theorem=theorem,
            max_steps=50,
            timeout=10.0
        )
        latency = time.time() - start_time

        self.performance_metrics["proof_engine"].append({
            "test": "identity_axiom",
            "latency_ms": latency * 1000,
            "proved": result.proved if result else False,
            "steps_count": len(result.steps) if result else 0,
            "confidence": result.confidence if result else 0
        })

        print(f"  Latency: {latency:.3f}s | Proved: {result.proved if result else False} | Steps: {len(result.steps) if result else 0}")
        if result and result.steps:
            print(f"    First step: {result.steps[0].statement}")

    async def test_proof_commutativity(self):
        """Test proving commutativity (a + b = b + a)"""
        if not self.proof_engine:
            print("  ⚠️  Skipped: Proof Engine not available")
            return

        from core.reasoning.advanced_proof_engine import Theorem, LogicType
        import uuid

        theorem = Theorem(
            theorem_id=f"commutative_{uuid.uuid4().hex[:8]}",
            statement="For all a, b: a + b = b + a",
            premises=["Commutativity axiom of addition"],
            logic_type=LogicType.FIRST_ORDER
        )

        start_time = time.time()
        result = await self.proof_engine.prove_theorem(
            theorem=theorem,
            max_steps=50,
            timeout=10.0
        )
        latency = time.time() - start_time

        self.performance_metrics["proof_engine"].append({
            "test": "commutativity",
            "latency_ms": latency * 1000,
            "proved": result.proved if result else False,
            "steps_count": len(result.steps) if result else 0,
            "confidence": result.confidence if result else 0
        })

        print(f"  Latency: {latency:.3f}s | Proved: {result.proved if result else False} | Steps: {len(result.steps) if result else 0}")

    async def test_proof_propositional_logic(self):
        """Test propositional logic proof (modus ponens)"""
        if not self.proof_engine:
            print("  ⚠️  Skipped: Proof Engine not available")
            return

        from core.reasoning.advanced_proof_engine import Theorem, LogicType
        import uuid

        theorem = Theorem(
            theorem_id=f"modus_ponens_{uuid.uuid4().hex[:8]}",
            statement="If P implies Q, and P is true, then Q is true",
            premises=["P → Q", "P"],
            logic_type=LogicType.PROPOSITIONAL
        )

        start_time = time.time()
        result = await self.proof_engine.prove_theorem(
            theorem=theorem,
            max_steps=50,
            timeout=10.0
        )
        latency = time.time() - start_time

        self.performance_metrics["proof_engine"].append({
            "test": "modus_ponens",
            "latency_ms": latency * 1000,
            "proved": result.proved if result else False,
            "steps_count": len(result.steps) if result else 0,
            "confidence": result.confidence if result else 0
        })

        print(f"  Latency: {latency:.3f}s | Proved: {result.proved if result else False} | Steps: {len(result.steps) if result else 0}")

    # ========== NEURAL BRIDGE TESTS ==========

    async def test_neural_bridge_simple_query(self):
        """Test neural bridge with simple factual query"""
        if not self.neural_bridge:
            print("  ⚠️  Skipped: Neural Bridge not available")
            return

        from core.reasoning.neural_bridge import ReasoningRequest, ReasoningMode

        request = ReasoningRequest(
            query="What is 2 + 2?",
            context=[],
            mode=ReasoningMode.HYBRID
        )

        start_time = time.time()
        result = await self.neural_bridge.reason(request)
        latency = time.time() - start_time

        self.performance_metrics["neural_bridge"].append({
            "test": "simple_query",
            "latency_ms": latency * 1000,
            "confidence": result.confidence if result else 0,
            "mode_used": result.mode_used.value if result else "unknown",
            "success": bool(result and result.answer)
        })

        print(f"  Latency: {latency:.3f}s | Confidence: {result.confidence:.2f}")
        print(f"  Answer: {result.answer}")
        print(f"  Mode: {result.mode_used.value}")

    async def test_neural_bridge_logical_reasoning(self):
        """Test neural bridge with logical reasoning"""
        if not self.neural_bridge:
            print("  ⚠️  Skipped: Neural Bridge not available")
            return

        from core.reasoning.neural_bridge import ReasoningRequest, ReasoningMode

        request = ReasoningRequest(
            query="If all birds can fly, and a penguin is a bird, can a penguin fly?",
            context=["This is a logical reasoning test", "Consider real-world knowledge"],
            mode=ReasoningMode.HYBRID
        )

        start_time = time.time()
        result = await self.neural_bridge.reason(request)
        latency = time.time() - start_time

        self.performance_metrics["neural_bridge"].append({
            "test": "logical_reasoning",
            "latency_ms": latency * 1000,
            "confidence": result.confidence if result else 0,
            "mode_used": result.mode_used.value if result else "unknown",
            "reasoning_steps": len(result.reasoning_steps) if result else 0,
            "success": bool(result and result.answer)
        })

        print(f"  Latency: {latency:.3f}s | Confidence: {result.confidence:.2f}")
        print(f"  Answer: {result.answer}")
        print(f"  Reasoning steps: {len(result.reasoning_steps)}")
        if result.reasoning_steps:
            for i, step in enumerate(result.reasoning_steps[:3], 1):
                print(f"    Step {i}: {step}")

    async def test_neural_bridge_multi_step(self):
        """Test neural bridge with multi-step reasoning"""
        if not self.neural_bridge:
            print("  ⚠️  Skipped: Neural Bridge not available")
            return

        from core.reasoning.neural_bridge import ReasoningRequest, ReasoningMode

        request = ReasoningRequest(
            query="If Alice is taller than Bob, and Bob is taller than Charlie, who is the tallest?",
            context=["Use transitive reasoning", "Consider all relationships"],
            mode=ReasoningMode.HYBRID,
            max_steps=10
        )

        start_time = time.time()
        result = await self.neural_bridge.reason(request)
        latency = time.time() - start_time

        self.performance_metrics["neural_bridge"].append({
            "test": "multi_step_reasoning",
            "latency_ms": latency * 1000,
            "confidence": result.confidence if result else 0,
            "mode_used": result.mode_used.value if result else "unknown",
            "reasoning_steps": len(result.reasoning_steps) if result else 0,
            "success": bool(result and result.answer)
        })

        print(f"  Latency: {latency:.3f}s | Confidence: {result.confidence:.2f}")
        print(f"  Answer: {result.answer}")
        print(f"  Reasoning steps: {len(result.reasoning_steps)}")

    # ========== MAIN TEST RUNNER ==========

    async def run_all_tests(self):
        """Run all reasoning system tests"""
        # Setup (load VLM and systems once)
        setup_success = await self.setup_systems()
        if not setup_success:
            print("❌ System setup failed - aborting tests")
            return

        print("\n" + "=" * 80)
        print("Running Reasoning Systems Test Suite")
        print("=" * 80)
        print()

        # Abstract Reasoning Tests
        print("═" * 80)
        print("ABSTRACT REASONING ENGINE TESTS")
        print("═" * 80)
        await self.run_test("Deductive Reasoning (Classic Syllogism)", self.test_deductive_reasoning_classic)
        await self.run_test("Inductive Reasoning (Pattern Recognition)", self.test_inductive_reasoning_pattern)
        await self.run_test("Analogical Reasoning (Skill Transfer)", self.test_analogical_reasoning_transfer)
        print()

        # Proof Engine Tests
        print("═" * 80)
        print("ADVANCED PROOF ENGINE TESTS")
        print("═" * 80)
        await self.run_test("Identity Axiom Proof", self.test_proof_identity_axiom)
        await self.run_test("Commutativity Proof", self.test_proof_commutativity)
        await self.run_test("Propositional Logic (Modus Ponens)", self.test_proof_propositional_logic)
        print()

        # Neural Bridge Tests
        print("═" * 80)
        print("NEURAL BRIDGE TESTS")
        print("═" * 80)
        await self.run_test("Simple Query", self.test_neural_bridge_simple_query)
        await self.run_test("Logical Reasoning", self.test_neural_bridge_logical_reasoning)
        await self.run_test("Multi-Step Reasoning", self.test_neural_bridge_multi_step)
        print()

        # Print performance summary
        self.print_performance_summary()

    def print_performance_summary(self):
        """Print detailed performance metrics"""
        print("\n" + "=" * 80)
        print("PERFORMANCE METRICS SUMMARY")
        print("=" * 80)
        print()

        for category, metrics in self.performance_metrics.items():
            if not metrics:
                continue

            print(f"📊 {category.replace('_', ' ').title()}")
            print("-" * 80)

            total_latency = 0
            for metric in metrics:
                test_name = metric.get('test', 'unknown')
                latency = metric.get('latency_ms', 0)
                total_latency += latency

                print(f"  {test_name}: {latency:.1f}ms", end="")

                # Print additional metrics
                if 'confidence' in metric:
                    print(f" | confidence: {metric['confidence']:.2f}", end="")
                if 'proved' in metric:
                    print(f" | proved: {metric['proved']}", end="")
                if 'conclusions_count' in metric:
                    print(f" | conclusions: {metric['conclusions_count']}", end="")
                if 'reasoning_steps' in metric:
                    print(f" | steps: {metric['reasoning_steps']}", end="")
                if 'success' in metric:
                    status = "✓" if metric['success'] else "✗"
                    print(f" | {status}", end="")

                print()  # Newline

            # Category average
            if metrics:
                avg_latency = total_latency / len(metrics)
                print(f"  Average: {avg_latency:.1f}ms")
            print()


async def main():
    """Main entry point"""
    tests = ReasoningSystemsTests()

    # Start session
    await tests.start_session()

    try:
        # Run all tests
        await tests.run_all_tests()

    finally:
        # End session and log results
        await tests.end_session()

        # Print summary
        tests.print_summary()


if __name__ == '__main__':
    asyncio.run(main())
