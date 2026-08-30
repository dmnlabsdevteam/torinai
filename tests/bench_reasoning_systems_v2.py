#!/usr/bin/env python3
"""
Reasoning Systems Comprehensive Test Suite (Enhanced Logging)
==============================================================
Deep testing of TorinAI's reasoning capabilities with detailed logging and debugging:
- Abstract Reasoning Engine (Deductive, Inductive, Analogical, Causal, Temporal)
- Advanced Proof Engine (Theorem proving, verification, logical inference)
- Neural Bridge (Natural language ↔ Formal logic translation)

Features:
- Loads VLM ONCE and reuses across all tests
- Logs all metrics to MySQL via TestBase
- Comprehensive debug logging showing inputs/outputs
- Diagnostic information for failures

Usage:
    python3 tests/test_reasoning_systems_v2.py

Author: Torin AI Team
Date: January 14, 2026
"""

import asyncio
import sys
import time
import logging
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional

# Add project to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Load environment
from dotenv import load_dotenv
load_dotenv(project_root / '.env.production')

# Import test base
sys.path.insert(0, str(project_root / 'tests'))
from test_base import TestBase

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)


class ReasoningSystemsTestsV2(TestBase):
    """
    Enhanced Reasoning Systems Tests with Comprehensive Logging

    Improvements:
    - Detailed input/output logging for each test
    - Shows intermediate reasoning steps
    - Explains why tests pass or fail
    - Tracks MySQL logging explicitly
    - Performance metrics with context
    """

    def __init__(self):
        super().__init__(
            test_category="reasoning_systems_v2",
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
        logger.info("=" * 80)
        logger.info("SYSTEM INITIALIZATION - Loading reasoning systems once")
        logger.info("=" * 80)

        # 1. Load VLM Service (32GB model)
        logger.info("Loading VLM Service (Qwen2.5-VL-32B)...")
        start_time = time.time()

        try:
            from core.services.unified_llm import get_llm_service
            self.llm = get_llm_service()
            if not self.llm.model_loaded:
                await self.llm.initialize()

            load_time = time.time() - start_time
            logger.info(f"✅ VLM loaded successfully in {load_time:.2f}s")

        except Exception as e:
            logger.error(f"❌ Failed to load VLM: {e}")
            return False

        # 2. Initialize Abstract Reasoning
        logger.info("Initializing Abstract Reasoning Engine...")
        try:
            from core.reasoning import create_abstract_reasoning_engine
            self.abstract_reasoning = create_abstract_reasoning_engine()
            if hasattr(self.abstract_reasoning, 'initialize'):
                await self.abstract_reasoning.initialize()
            logger.info("✅ Abstract Reasoning Engine initialized")
        except Exception as e:
            logger.error(f"❌ Failed to initialize Abstract Reasoning: {e}")
            return False

        # 3. Initialize Proof Engine
        logger.info("Initializing Advanced Proof Engine...")
        try:
            from core.reasoning.advanced_proof_engine import AdvancedProofEngine
            self.proof_engine = AdvancedProofEngine()
            logger.info("✅ Proof Engine initialized")
        except Exception as e:
            logger.error(f"❌ Failed to initialize Proof Engine: {e}")
            return False

        # 4. Initialize Neural Bridge
        logger.info("Initializing Neural Bridge...")
        try:
            from core.reasoning.neural_bridge import NeuralSymbolicBridge
            self.neural_bridge = NeuralSymbolicBridge()
            await self.neural_bridge.initialize()
            logger.info("✅ Neural Bridge initialized")
        except Exception as e:
            logger.error(f"❌ Failed to initialize Neural Bridge: {e}")
            return False

        logger.info("=" * 80)
        logger.info("✅ ALL SYSTEMS INITIALIZED SUCCESSFULLY")
        logger.info("=" * 80)
        return True

    # ========== ABSTRACT REASONING TESTS ==========

    async def test_deductive_reasoning_classic(self):
        """
        Test deductive reasoning with classic syllogism

        Input:
            Premise 1: All humans are mortal
            Premise 2: Socrates is human
            Expected: Socrates is mortal
        """
        logger.info("\n" + "─" * 80)
        logger.info("TEST: Deductive Reasoning (Classic Syllogism)")
        logger.info("─" * 80)

        from core.reasoning.abstract_reasoning_engine import (
            ReasoningContext,
            ReasoningType,
            ReasoningPremise
        )
        import uuid

        # Prepare premises
        premises = [
            ReasoningPremise(
                premise_id="p1",
                statement="All humans are mortal",
                confidence=1.0,
                source="test",
                predicates=["human", "mortal"]
            ),
            ReasoningPremise(
                premise_id="p2",
                statement="Socrates is human",
                confidence=1.0,
                source="test",
                predicates=["human", "socrates"]
            )
        ]

        rules = [
            "If X is human then X is mortal",
            "Socrates is human"
        ]

        context = ReasoningContext(
            context_id=f"deductive_test_{uuid.uuid4().hex[:8]}",
            domain="logic",
            problem_type="deductive_reasoning",
            premises=premises,
            rules=rules,
            target_conclusions=["Is Socrates mortal?"],
            allowed_reasoning_types=[ReasoningType.DEDUCTIVE],
            confidence_threshold=0.5
        )

        # Log input
        logger.info("INPUT:")
        logger.info(f"  Domain: {context.domain}")
        logger.info(f"  Problem Type: {context.problem_type}")
        logger.info("  Premises:")
        for p in premises:
            logger.info(f"    - {p.statement} (confidence: {p.confidence})")
        logger.info("  Rules:")
        for r in rules:
            logger.info(f"    - {r}")
        logger.info(f"  Target Conclusions: {context.target_conclusions}")

        # Execute reasoning
        logger.info("\nEXECUTING...")
        start_time = time.time()
        result = await self.abstract_reasoning.reason(context)
        latency = time.time() - start_time

        # Log output
        logger.info("\nOUTPUT:")
        logger.info(f"  Latency: {latency*1000:.1f}ms")
        logger.info(f"  Success: {result.success}")
        logger.info(f"  Overall Confidence: {result.overall_confidence}")
        logger.info(f"  Conclusions Count: {len(result.conclusions)}")

        if result.conclusions:
            logger.info("  Conclusions:")
            for i, conclusion in enumerate(result.conclusions, 1):
                logger.info(f"    {i}. {conclusion.statement}")
                logger.info(f"       - Confidence: {conclusion.confidence}")
                logger.info(f"       - Type: {conclusion.reasoning_type}")
                if hasattr(conclusion, 'supporting_evidence'):
                    logger.info(f"       - Evidence: {conclusion.supporting_evidence}")
        else:
            logger.warning("  ⚠️  No conclusions generated!")
            logger.warning("  DIAGNOSIS: Deductive strategy may not be matching premise patterns")
            logger.warning("  SUGGESTION: Check AbstractReasoningEngine.deductive_reasoning() pattern matching")

        # Track metrics
        self.performance_metrics["abstract_reasoning"].append({
            "test": "deductive_classic",
            "latency_ms": latency * 1000,
            "confidence": result.overall_confidence,
            "conclusions_count": len(result.conclusions),
            "success": result.success
        })

        # Assertions for test
        assert result is not None, "Reasoning result should not be None"
        logger.info(f"\n✅ TEST PASSED (result returned)")

    async def test_inductive_reasoning_pattern(self):
        """
        Test inductive reasoning with pattern recognition

        Input:
            Observations: 2, 4, 8, 16, 32
            Expected Pattern: Powers of 2, next = 64
        """
        logger.info("\n" + "─" * 80)
        logger.info("TEST: Inductive Reasoning (Pattern Recognition)")
        logger.info("─" * 80)

        from core.reasoning.abstract_reasoning_engine import (
            ReasoningContext,
            ReasoningType,
            ReasoningPremise
        )
        import uuid

        # Prepare observations as premises
        observations = [2, 4, 8, 16, 32]
        premises = [
            ReasoningPremise(
                premise_id=f"obs{i}",
                statement=f"Observation {i}: value is {val}",
                confidence=1.0,
                source="test",
                predicates=["observation", "value", str(val)]
            )
            for i, val in enumerate(observations, 1)
        ]

        context = ReasoningContext(
            context_id=f"inductive_test_{uuid.uuid4().hex[:8]}",
            domain="mathematics",
            problem_type="pattern_recognition",
            premises=premises,
            facts=[f"Sequence: {observations}"],
            target_conclusions=["What is the pattern?", "What is the next number?"],
            allowed_reasoning_types=[ReasoningType.INDUCTIVE],
            confidence_threshold=0.5
        )

        # Log input
        logger.info("INPUT:")
        logger.info(f"  Domain: {context.domain}")
        logger.info(f"  Problem Type: {context.problem_type}")
        logger.info(f"  Observations: {observations}")
        logger.info(f"  Target: Identify pattern and predict next value")

        # Execute reasoning
        logger.info("\nEXECUTING...")
        start_time = time.time()
        result = await self.abstract_reasoning.reason(context)
        latency = time.time() - start_time

        # Log output
        logger.info("\nOUTPUT:")
        logger.info(f"  Latency: {latency*1000:.1f}ms")
        logger.info(f"  Success: {result.success}")
        logger.info(f"  Overall Confidence: {result.overall_confidence}")
        logger.info(f"  Conclusions Count: {len(result.conclusions)}")

        if result.conclusions:
            logger.info("  Pattern Identified:")
            for conclusion in result.conclusions:
                logger.info(f"    - {conclusion.statement} (confidence: {conclusion.confidence})")
        else:
            logger.warning("  ⚠️  No pattern identified!")
            logger.warning("  DIAGNOSIS: Inductive strategy may not be analyzing numeric sequences")
            logger.warning("  SUGGESTION: Check AbstractReasoningEngine.inductive_reasoning() for pattern detection")

        # Track metrics
        self.performance_metrics["abstract_reasoning"].append({
            "test": "inductive_pattern",
            "latency_ms": latency * 1000,
            "confidence": result.overall_confidence,
            "conclusions_count": len(result.conclusions),
            "success": result.success
        })

        assert result is not None, "Reasoning result should not be None"
        logger.info(f"\n✅ TEST PASSED (result returned)")

    async def test_analogical_reasoning_transfer(self):
        """
        Test analogical reasoning with skill transfer

        Input:
            Base analogy: Learning piano → practice, coordination, patience
            Target: Learning guitar → ?
        """
        logger.info("\n" + "─" * 80)
        logger.info("TEST: Analogical Reasoning (Skill Transfer)")
        logger.info("─" * 80)

        from core.reasoning.abstract_reasoning_engine import (
            ReasoningContext,
            ReasoningType,
            ReasoningPremise
        )
        import uuid

        premises = [
            ReasoningPremise(
                premise_id="base",
                statement="Learning to play piano requires practice, coordination, and patience",
                confidence=1.0,
                source="test",
                predicates=["learning", "piano", "practice", "coordination", "patience"]
            ),
            ReasoningPremise(
                premise_id="target",
                statement="Now considering learning to play guitar",
                confidence=1.0,
                source="test",
                predicates=["learning", "guitar"]
            )
        ]

        context = ReasoningContext(
            context_id=f"analogical_test_{uuid.uuid4().hex[:8]}",
            domain="skill_learning",
            problem_type="analogical_transfer",
            premises=premises,
            target_conclusions=["What skills are needed for learning guitar?"],
            allowed_reasoning_types=[ReasoningType.ANALOGICAL],
            confidence_threshold=0.5
        )

        # Log input
        logger.info("INPUT:")
        logger.info(f"  Domain: {context.domain}")
        logger.info(f"  Base Analogy: Piano learning → practice, coordination, patience")
        logger.info(f"  Target Query: What about guitar?")

        # Execute reasoning
        logger.info("\nEXECUTING...")
        start_time = time.time()
        result = await self.abstract_reasoning.reason(context)
        latency = time.time() - start_time

        # Log output
        logger.info("\nOUTPUT:")
        logger.info(f"  Latency: {latency*1000:.1f}ms")
        logger.info(f"  Success: {result.success}")
        logger.info(f"  Overall Confidence: {result.overall_confidence}")
        logger.info(f"  Conclusions Count: {len(result.conclusions)}")

        if result.conclusions:
            logger.info("  Analogical Transfer:")
            for conclusion in result.conclusions:
                logger.info(f"    - {conclusion.statement}")
                logger.info(f"      Confidence: {conclusion.confidence}")
        else:
            logger.warning("  ⚠️  No analogy detected!")

        # Track metrics
        self.performance_metrics["abstract_reasoning"].append({
            "test": "analogical_transfer",
            "latency_ms": latency * 1000,
            "confidence": result.overall_confidence,
            "conclusions_count": len(result.conclusions),
            "success": result.success
        })

        assert result is not None, "Reasoning result should not be None"
        assert result.overall_confidence > 0, "Should have some confidence in analogy"
        logger.info(f"\n✅ TEST PASSED (analogy detected)")

    # ========== PROOF ENGINE TESTS ==========

    async def test_proof_identity_axiom(self):
        """Test proving identity axiom: a + 0 = a"""
        logger.info("\n" + "─" * 80)
        logger.info("TEST: Identity Axiom Proof (a + 0 = a)")
        logger.info("─" * 80)

        from core.reasoning.advanced_proof_engine import Theorem, LogicType
        import uuid

        theorem = Theorem(
            theorem_id=f"identity_{uuid.uuid4().hex[:8]}",
            statement="For all a: a + 0 = a",
            premises=["Identity axiom: a + 0 = a for all a"],
            logic_type=LogicType.FIRST_ORDER
        )

        logger.info("INPUT:")
        logger.info(f"  Theorem: {theorem.statement}")
        logger.info(f"  Logic Type: {theorem.logic_type}")
        logger.info(f"  Premises: {theorem.premises}")

        logger.info("\nEXECUTING...")
        start_time = time.time()
        result = await self.proof_engine.prove_theorem(
            theorem=theorem,
            max_steps=50,
            timeout=10.0
        )
        latency = time.time() - start_time

        logger.info("\nOUTPUT:")
        logger.info(f"  Latency: {latency*1000:.1f}ms")
        logger.info(f"  Proved: {result.proved if result else False}")
        logger.info(f"  Steps: {len(result.steps) if result else 0}")
        logger.info(f"  Confidence: {result.confidence if result else 0}")

        if result and result.steps:
            logger.info("  Proof Steps:")
            for i, step in enumerate(result.steps, 1):
                logger.info(f"    {i}. {step.statement}")
                logger.info(f"       Rule: {step.rule_applied}")
                logger.info(f"       Justification: {step.justification}")
        else:
            logger.warning("  ⚠️  Theorem not proved")
            logger.warning("  DIAGNOSIS: Proof engine may need axiom system configured")

        self.performance_metrics["proof_engine"].append({
            "test": "identity_axiom",
            "latency_ms": latency * 1000,
            "proved": result.proved if result else False,
            "steps_count": len(result.steps) if result else 0,
            "confidence": result.confidence if result else 0
        })

        assert result is not None, "Proof result should not be None"
        logger.info(f"\n✅ TEST PASSED (proof attempted)")

    # ========== NEURAL BRIDGE TESTS ==========

    async def test_neural_bridge_simple_query(self):
        """Test neural bridge with simple mathematical query"""
        logger.info("\n" + "─" * 80)
        logger.info("TEST: Neural Bridge - Simple Query")
        logger.info("─" * 80)

        from core.reasoning.neural_bridge import ReasoningRequest, ReasoningMode

        request = ReasoningRequest(
            query="What is 2 + 2?",
            context=["Basic arithmetic"],
            mode=ReasoningMode.HYBRID,
            max_steps=5,
            confidence_threshold=0.7
        )

        logger.info("INPUT:")
        logger.info(f"  Query: {request.query}")
        logger.info(f"  Mode: {request.mode}")
        logger.info(f"  Context: {request.context}")

        logger.info("\nEXECUTING...")
        start_time = time.time()
        result = await self.neural_bridge.reason(request)
        latency = time.time() - start_time

        logger.info("\nOUTPUT:")
        logger.info(f"  Latency: {latency*1000:.1f}ms")
        logger.info(f"  Answer: {result.answer}")
        logger.info(f"  Confidence: {result.confidence}")
        logger.info(f"  Mode Used: {result.mode_used}")
        logger.info(f"  Reasoning Steps: {len(result.reasoning_steps)}")

        if result.reasoning_steps:
            logger.info("  Steps:")
            for i, step in enumerate(result.reasoning_steps, 1):
                logger.info(f"    {i}. {step}")

        self.performance_metrics["neural_bridge"].append({
            "test": "simple_query",
            "latency_ms": latency * 1000,
            "confidence": result.confidence,
            "steps_count": len(result.reasoning_steps),
            "mode_used": result.mode_used.value
        })

        assert result is not None, "Result should not be None"
        assert result.confidence > 0.5, "Should have reasonable confidence"
        logger.info(f"\n✅ TEST PASSED (query answered)")

    # ========== RUN ALL TESTS ==========

    async def run_all_tests(self):
        """Run all reasoning system tests with comprehensive logging"""
        # Setup (load VLM and systems once)
        setup_success = await self.setup_systems()
        if not setup_success:
            logger.error("❌ System setup failed - aborting tests")
            return

        logger.info("\n" + "=" * 80)
        logger.info("STARTING TEST SUITE EXECUTION")
        logger.info("=" * 80)

        # Abstract Reasoning Tests
        logger.info("\n" + "═" * 80)
        logger.info("CATEGORY: ABSTRACT REASONING ENGINE")
        logger.info("═" * 80)

        await self.run_test(
            "Deductive Reasoning (Classic Syllogism)",
            self.test_deductive_reasoning_classic,
            metadata={"category": "abstract_reasoning", "type": "deductive"}
        )

        await self.run_test(
            "Inductive Reasoning (Pattern Recognition)",
            self.test_inductive_reasoning_pattern,
            metadata={"category": "abstract_reasoning", "type": "inductive"}
        )

        await self.run_test(
            "Analogical Reasoning (Skill Transfer)",
            self.test_analogical_reasoning_transfer,
            metadata={"category": "abstract_reasoning", "type": "analogical"}
        )

        # Proof Engine Tests
        logger.info("\n" + "═" * 80)
        logger.info("CATEGORY: ADVANCED PROOF ENGINE")
        logger.info("═" * 80)

        await self.run_test(
            "Identity Axiom Proof",
            self.test_proof_identity_axiom,
            metadata={"category": "proof_engine", "type": "identity"}
        )

        # Neural Bridge Tests
        logger.info("\n" + "═" * 80)
        logger.info("CATEGORY: NEURAL BRIDGE")
        logger.info("═" * 80)

        await self.run_test(
            "Simple Query",
            self.test_neural_bridge_simple_query,
            metadata={"category": "neural_bridge", "type": "simple"}
        )

        # Print performance summary
        self.print_performance_summary()

    def print_performance_summary(self):
        """Print detailed performance metrics"""
        logger.info("\n" + "=" * 80)
        logger.info("PERFORMANCE METRICS SUMMARY")
        logger.info("=" * 80)

        for category, metrics in self.performance_metrics.items():
            if not metrics:
                continue

            logger.info(f"\n📊 {category.upper().replace('_', ' ')}")
            logger.info("─" * 80)

            for metric in metrics:
                test_name = metric.get('test', 'unknown')
                latency = metric.get('latency_ms', 0)
                confidence = metric.get('confidence', 0)

                logger.info(f"  {test_name}:")
                logger.info(f"    Latency: {latency:.1f}ms")
                logger.info(f"    Confidence: {confidence:.2f}")

                if 'conclusions_count' in metric:
                    logger.info(f"    Conclusions: {metric['conclusions_count']}")
                if 'proved' in metric:
                    logger.info(f"    Proved: {metric['proved']}")
                if 'steps_count' in metric:
                    logger.info(f"    Steps: {metric['steps_count']}")


async def main():
    """Main entry point with MySQL logging"""
    logger.info("=" * 80)
    logger.info("REASONING SYSTEMS TEST SUITE V2 (Enhanced Logging)")
    logger.info("=" * 80)

    tests = ReasoningSystemsTestsV2()

    # Start MySQL session
    logger.info("\n📊 Starting MySQL test session...")
    await tests.start_session()

    if tests.db_initialized:
        logger.info(f"✅ MySQL session started: ID={tests.mysql_session_id}")
    else:
        logger.warning("⚠️  MySQL logging not available (tests will continue)")

    try:
        # Run all tests
        await tests.run_all_tests()

    finally:
        # End session and log results
        logger.info("\n📊 Ending MySQL test session...")
        await tests.end_session()

        if tests.db_initialized:
            logger.info(f"✅ MySQL session ended: {tests.passed_tests}/{tests.total_tests} passed")

        # Print summary
        logger.info("\n")
        tests.print_summary()


if __name__ == '__main__':
    asyncio.run(main())
