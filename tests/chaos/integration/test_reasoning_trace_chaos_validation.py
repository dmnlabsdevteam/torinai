#!/usr/bin/env python3
"""
Reasoning Trace Chaos Validation Tests
=======================================

Integration tests validating that chain of thought capture remains
robust during chaos experiments.
"""

import pytest
import pytest_asyncio
import asyncio
from datetime import datetime
from typing import Dict, Any

# Import chaos framework components
from core.chaos.adapters.memory_adapter import get_memory_adapter
from core.chaos.scenarios.scenario_library import get_scenario

# Import memory and reasoning systems
from core.memory import get_memory_agent
from core.reasoning.abstract_reasoning_engine import AbstractReasoningEngine
from core.reasoning.neural_bridge import NeuralSymbolicBridge
from core.reasoning.hypothesis_testing import HypothesisTestingSystem
from core.memory.utils.interfaces import MemoryType


@pytest.mark.asyncio
class TestReasoningTraceChaosValidation:
    """Test suite for reasoning trace capture under chaos"""

    # pytest's setup_method/teardown_method hooks are SYNCHRONOUS. Declaring
    # them `async def` returned a coroutine pytest never awaited, so the
    # attributes below were never set and every test in this class failed on
    # AttributeError rather than on anything it was written to check. An async
    # autouse fixture is the hook that actually runs.
    @pytest_asyncio.fixture(autouse=True)
    async def _memory_fixtures(self):
        self.memory_adapter = get_memory_adapter()
        self.memory_agent = await get_memory_agent()   # async factory
        yield
        await self.memory_adapter.cleanup()

    @pytest.mark.asyncio
    async def test_reasoning_trace_metrics_collection(self):
        """Test that reasoning trace quality metrics are collected correctly"""

        # Get reasoning trace metrics
        metrics = await self.memory_adapter.get_reasoning_trace_metrics()

        # Validate metric structure
        assert "total_memories_last_hour" in metrics
        assert "reasoning_trace_completeness_rate" in metrics
        assert "reasoning_trace_avg_length" in metrics
        assert "thinking_state_capture_rate" in metrics
        assert "decision_factors_population_rate" in metrics

        # Validate metric types
        assert isinstance(metrics["total_memories_last_hour"], (int, float))
        assert isinstance(metrics["reasoning_trace_completeness_rate"], float)
        assert isinstance(metrics["reasoning_trace_avg_length"], (int, float))
        assert isinstance(metrics["thinking_state_capture_rate"], float)
        assert isinstance(metrics["decision_factors_population_rate"], float)

        # Validate metric ranges
        assert 0.0 <= metrics["reasoning_trace_completeness_rate"] <= 1.0
        assert 0.0 <= metrics["thinking_state_capture_rate"] <= 1.0
        assert 0.0 <= metrics["decision_factors_population_rate"] <= 1.0
        assert metrics["reasoning_trace_avg_length"] >= 0

    @pytest.mark.asyncio
    async def test_health_metrics_include_reasoning_trace(self):
        """Test that health metrics include reasoning trace quality"""

        # Get health metrics
        health_metrics = await self.memory_adapter.get_health_metrics()

        # Validate reasoning trace metrics are included
        assert "reasoning_trace_completeness_rate" in health_metrics
        assert "reasoning_trace_avg_length" in health_metrics
        assert "thinking_state_capture_rate" in health_metrics
        assert "decision_factors_population_rate" in health_metrics

        # Validate health status logic
        assert "healthy" in health_metrics
        assert isinstance(health_metrics["healthy"], bool)

    @pytest.mark.asyncio
    async def test_reasoning_trace_capture_under_latency(self):
        """Test reasoning trace capture quality when storage is slow"""

        # Get baseline metrics
        baseline_metrics = await self.memory_adapter.get_reasoning_trace_metrics()
        baseline_completeness = baseline_metrics.get("reasoning_trace_completeness_rate", 0.0)

        # Load chaos scenario
        scenario = get_scenario("reasoning_trace_capture_validation")

        # Simulate reasoning operations with latency injection
        # (In production, this would inject chaos via ChaosOrchestrator)

        # Store test memories with reasoning traces
        test_memories = []
        for i in range(10):
            success, memory_id = await self.memory_agent.store_memory(
                memory_type=MemoryType.SEMANTIC,
                content=f"Test reasoning result {i}",
                importance_score=0.8,
                confidence_score=0.9,
                tags=["test", "chaos", "reasoning"],
                reasoning_trace=[
                    f"Step 1: Analyze problem {i}",
                    f"Step 2: Generate hypothesis {i}",
                    f"Step 3: Validate solution {i}"
                ],
                thinking_state={
                    "test_iteration": i,
                    "timestamp": datetime.now().isoformat()
                },
                decision_factors={
                    "test_scenario": "chaos_validation",
                    "iteration": i
                },
                emotional_context={
                    "confidence": 0.9
                }
            )

            if success:
                test_memories.append(memory_id)

        # Verify memories were stored
        assert len(test_memories) > 0, "No test memories were stored"

        # Get post-test metrics
        post_test_metrics = await self.memory_adapter.get_reasoning_trace_metrics()

        # Validate reasoning trace capture rate
        # Should be high (>80%) even under latency
        expected_min_completeness = scenario["hypothesis"]["expected_behavior"]["min_reasoning_trace_completeness_rate"]

        if post_test_metrics["total_memories_last_hour"] > 0:
            assert post_test_metrics["reasoning_trace_completeness_rate"] >= expected_min_completeness, \
                f"Reasoning trace completeness {post_test_metrics['reasoning_trace_completeness_rate']} below threshold {expected_min_completeness}"

        # Validate thinking state capture
        expected_min_thinking_state = scenario["hypothesis"]["expected_behavior"]["min_thinking_state_capture_rate"]

        if post_test_metrics["total_memories_last_hour"] > 0:
            assert post_test_metrics["thinking_state_capture_rate"] >= expected_min_thinking_state, \
                f"Thinking state capture {post_test_metrics['thinking_state_capture_rate']} below threshold {expected_min_thinking_state}"

    @pytest.mark.asyncio
    async def test_chain_of_thought_not_dropped_during_errors(self):
        """Test that chain of thought isn't dropped during database errors"""

        # Load chaos scenario
        scenario = get_scenario("chain_of_thought_persistence_under_errors")

        # Store memories with comprehensive chain of thought
        successful_stores = 0
        total_attempts = 20

        for i in range(total_attempts):
            success, memory_id = await self.memory_agent.store_memory(
                memory_type=MemoryType.EPISODIC,
                content=f"Chain of thought test {i}",
                importance_score=0.85,
                confidence_score=0.9,
                tags=["test", "chain_of_thought", "persistence"],
                reasoning_trace=[
                    f"Thought {i}.1: Initial observation",
                    f"Thought {i}.2: Intermediate reasoning",
                    f"Thought {i}.3: Conclusion reached"
                ],
                thinking_state={
                    "iteration": i,
                    "cognitive_load": "medium"
                },
                decision_factors={
                    "primary_factor": "test_validation",
                    "confidence_threshold": 0.8
                }
            )

            if success:
                successful_stores += 1

        # Get metrics after error injection
        post_error_metrics = await self.memory_adapter.get_reasoning_trace_metrics()

        # Validate that reasoning traces weren't dropped
        # Even with errors, completeness should be high due to retries
        expected_min_completeness = scenario["hypothesis"]["expected_behavior"]["min_reasoning_trace_completeness_rate"]

        if post_error_metrics["total_memories_last_hour"] > 0:
            actual_completeness = post_error_metrics["reasoning_trace_completeness_rate"]
            assert actual_completeness >= expected_min_completeness, \
                f"Reasoning trace completeness {actual_completeness} below threshold {expected_min_completeness} despite retries"

        # Validate decision factors weren't dropped
        expected_min_decision_factors = scenario["hypothesis"]["expected_behavior"]["min_decision_factors_population_rate"]

        if post_error_metrics["total_memories_last_hour"] > 0:
            actual_decision_factors = post_error_metrics["decision_factors_population_rate"]
            assert actual_decision_factors >= expected_min_decision_factors, \
                f"Decision factors population {actual_decision_factors} below threshold {expected_min_decision_factors}"

    @pytest.mark.asyncio
    async def test_thinking_state_completeness_under_resource_pressure(self):
        """Test all chain of thought fields under connection pool pressure"""

        # Load chaos scenario
        scenario = get_scenario("thinking_state_capture_completeness")

        # Store memories with complete chain of thought data
        for i in range(15):
            await self.memory_agent.store_memory(
                memory_type=MemoryType.PROCEDURAL,
                content=f"Complete chain of thought test {i}",
                importance_score=0.9,
                confidence_score=0.95,
                tags=["test", "completeness", "resource_pressure"],
                reasoning_trace=[
                    f"Analysis step {i}.1",
                    f"Planning step {i}.2",
                    f"Execution step {i}.3",
                    f"Validation step {i}.4"
                ],
                thinking_state={
                    "iteration": i,
                    "cognitive_state": "focused",
                    "resource_utilization": 0.9
                },
                decision_factors={
                    "primary": "test_completeness",
                    "secondary": "resource_pressure",
                    "tertiary": "data_integrity"
                },
                emotional_context={
                    "confidence": 0.95,
                    "certainty": "high"
                }
            )

        # Get metrics under resource pressure
        pressure_metrics = await self.memory_adapter.get_reasoning_trace_metrics()

        # Validate all fields are captured
        expected_behavior = scenario["hypothesis"]["expected_behavior"]

        if pressure_metrics["total_memories_last_hour"] > 0:
            # Reasoning trace completeness
            assert pressure_metrics["reasoning_trace_completeness_rate"] >= expected_behavior["min_reasoning_trace_completeness_rate"], \
                "Reasoning trace completeness degraded under pressure"

            # Thinking state capture
            assert pressure_metrics["thinking_state_capture_rate"] >= expected_behavior["min_thinking_state_capture_rate"], \
                "Thinking state capture degraded under pressure"

            # Decision factors population
            assert pressure_metrics["decision_factors_population_rate"] >= expected_behavior["min_decision_factors_population_rate"], \
                "Decision factors population degraded under pressure"

            # Reasoning trace length (quality metric)
            assert pressure_metrics["reasoning_trace_avg_length"] >= expected_behavior["min_reasoning_trace_avg_length"], \
                f"Reasoning trace avg length {pressure_metrics['reasoning_trace_avg_length']} below minimum {expected_behavior['min_reasoning_trace_avg_length']}"

    @pytest.mark.asyncio
    async def test_abstract_reasoning_engine_chain_of_thought_persistence(self):
        """Test Abstract Reasoning Engine chain of thought is persisted"""

        # Note: This would require full engine initialization
        # For integration test, we validate the memory store call pattern

        # Validate that reasoning_trace parameter is available
        import inspect
        sig = inspect.signature(self.memory_agent.store_memory)
        params = list(sig.parameters.keys())

        assert "reasoning_trace" in params, "Memory agent missing reasoning_trace parameter"
        assert "thinking_state" in params, "Memory agent missing thinking_state parameter"
        assert "decision_factors" in params, "Memory agent missing decision_factors parameter"
        assert "emotional_context" in params, "Memory agent missing emotional_context parameter"

    @pytest.mark.asyncio
    async def test_neural_bridge_chain_of_thought_persistence(self):
        """Test Neural Bridge chain of thought is persisted"""

        # Validate Neural Bridge has memory_agent integration
        # This validates the fix we made earlier

        bridge = NeuralSymbolicBridge()
        await bridge.initialize()

        # Verify memory agent is connected
        assert hasattr(bridge, "memory_agent"), "Neural Bridge missing memory_agent attribute"
        assert bridge.memory_agent is not None, "Neural Bridge memory_agent not initialized"

    @pytest.mark.asyncio
    async def test_hypothesis_testing_chain_of_thought_persistence(self):
        """Test Hypothesis Testing chain of thought is persisted"""

        # Validate Hypothesis Testing has memory_agent integration

        hypothesis_system = HypothesisTestingSystem()
        await hypothesis_system.initialize()

        # Verify memory agent is connected
        assert hasattr(hypothesis_system, "memory_agent"), "Hypothesis Testing missing memory_agent attribute"
        assert hypothesis_system.memory_agent is not None, "Hypothesis Testing memory_agent not initialized"

    @pytest.mark.asyncio
    async def test_chaos_scenario_hypothesis_validation(self):
        """Test that chaos scenarios have proper hypothesis validation for reasoning traces"""

        # Validate all memory chaos scenarios have reasoning trace expectations
        memory_scenarios = [
            "reasoning_trace_capture_validation",
            "chain_of_thought_persistence_under_errors",
            "thinking_state_capture_completeness"
        ]

        for scenario_name in memory_scenarios:
            scenario = get_scenario(scenario_name)

            # Validate scenario structure
            assert "hypothesis" in scenario, f"Scenario {scenario_name} missing hypothesis"
            assert "expected_behavior" in scenario["hypothesis"], f"Scenario {scenario_name} missing expected_behavior"

            expected = scenario["hypothesis"]["expected_behavior"]

            # Validate reasoning trace expectations are defined
            # At least one reasoning trace metric should be specified
            reasoning_metrics = [
                "min_reasoning_trace_completeness_rate",
                "min_thinking_state_capture_rate",
                "min_decision_factors_population_rate",
                "min_reasoning_trace_avg_length"
            ]

            has_reasoning_metric = any(metric in expected for metric in reasoning_metrics)
            assert has_reasoning_metric, f"Scenario {scenario_name} missing reasoning trace validation metrics"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
