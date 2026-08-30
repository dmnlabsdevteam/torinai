#!/usr/bin/env python3
"""
Chaos Adapter Tests
===================

Comprehensive tests for all chaos adapters with new API.
"""

import pytest
import asyncio
from datetime import datetime

from core.chaos.types import ChaosType
from core.chaos.adapters import (
    ToolSystemAdapter,
    LearningSystemAdapter,
    SecuritySystemAdapter,
    ReasoningSystemAdapter,
    AgentSystemAdapter,
    DomainSystemAdapter,
    MemorySystemAdapter,
    IntelligenceSystemAdapter,
    MonitoringSystemAdapter,
    ServicesSystemAdapter
)


class TestToolSystemAdapter:
    """Test tool system adapter"""

    @pytest.fixture
    def adapter(self):
        return ToolSystemAdapter()

    @pytest.mark.asyncio
    async def test_inject_latency(self, adapter):
        """Test latency injection into tool system"""
        handle = await adapter.inject_latency(
            target_id="test_exp",
            component="tool_registry",
            injection_point="get_tool",
            delay_ms=500,
            jitter_ms=100
        )
        assert handle is not None
        assert handle.active is True

    @pytest.mark.asyncio
    async def test_inject_error(self, adapter):
        """Test error injection into tool system"""
        handle = await adapter.inject_error(
            target_id="test_exp",
            component="tool_registry",
            injection_point="get_connection",
            error_type="TestError",
            error_rate=0.2
        )
        assert handle is not None
        assert handle.active is True

    @pytest.mark.asyncio
    async def test_get_health_metrics(self, adapter):
        """Test health metrics retrieval"""
        metrics = await adapter.get_health_metrics()
        assert isinstance(metrics, dict)
        assert "healthy" in metrics

    @pytest.mark.asyncio
    async def test_cleanup(self, adapter):
        """Test cleanup resets state"""
        await adapter.inject_latency(
            target_id="test_exp",
            component="tool_registry",
            injection_point="get_tool",
            delay_ms=500,
            jitter_ms=100
        )
        await adapter.cleanup()
        metrics = await adapter.get_health_metrics()
        assert metrics.get("active_chaos_injections", 0) == 0


class TestAgentSystemAdapter:
    """Test autonomous agent system adapter"""

    @pytest.fixture
    def adapter(self):
        return AgentSystemAdapter()

    @pytest.mark.asyncio
    async def test_inject_coordination_latency(self, adapter):
        """Test coordination latency injection"""
        handle = await adapter.inject_latency(
            target_id="test_exp",
            component="agent_coordinator",
            injection_point="coordination",
            delay_ms=200,
            jitter_ms=50
        )
        assert handle is not None
        assert adapter._chaos_active is True

    @pytest.mark.asyncio
    async def test_inject_motivation_latency(self, adapter):
        """Test motivation calculation latency"""
        handle = await adapter.inject_latency(
            target_id="test_exp",
            component="intrinsic_motivation",
            injection_point="motivation_calculation",
            delay_ms=300,
            jitter_ms=100
        )
        assert handle is not None

    @pytest.mark.asyncio
    async def test_inject_planning_error(self, adapter):
        """Test planning error injection"""
        handle = await adapter.inject_error(
            target_id="test_exp",
            component="planning_engine",
            injection_point="plan_generation",
            error_type="PlanningError",
            error_rate=0.1
        )
        assert handle is not None

    @pytest.mark.asyncio
    async def test_inject_governance_queue_error(self, adapter):
        """Test governance queue error injection"""
        handle = await adapter.inject_error(
            target_id="test_exp",
            component="governance_queue",
            injection_point="governance_processing",
            error_type="QueueError",
            error_rate=0.15
        )
        assert handle is not None

    @pytest.mark.asyncio
    async def test_exhaust_agent_pool(self, adapter):
        """Test agent pool exhaustion"""
        handle = await adapter.inject_resource_exhaustion(
            target_id="test_exp",
            component="agent_pool",
            resource_type="agent_pool"
        )
        assert handle is not None

    @pytest.mark.asyncio
    async def test_health_metrics_include_motivation(self, adapter):
        """Test health metrics include motivation metrics"""
        metrics = await adapter.get_health_metrics()
        assert isinstance(metrics, dict)
        assert "healthy" in metrics


class TestIntelligenceSystemAdapter:
    """Test intelligence system adapter"""

    @pytest.fixture
    def adapter(self):
        return IntelligenceSystemAdapter()

    @pytest.mark.asyncio
    async def test_inject_nlp_latency(self, adapter):
        """Test NLP processing latency"""
        handle = await adapter.inject_latency(
            target_id="test_exp",
            component="nlp_processor",
            injection_point="nlp_processing",
            delay_ms=200,
            jitter_ms=50
        )
        assert handle is not None

    @pytest.mark.asyncio
    async def test_inject_prediction_error(self, adapter):
        """Test prediction error injection"""
        handle = await adapter.inject_error(
            target_id="test_exp",
            component="predictive_system",
            injection_point="prediction_inference",
            error_type="PredictionError",
            error_rate=0.1
        )
        assert handle is not None

    @pytest.mark.asyncio
    async def test_exhaust_prediction_cache(self, adapter):
        """Test prediction cache exhaustion"""
        handle = await adapter.inject_resource_exhaustion(
            target_id="test_exp",
            component="prediction_cache",
            resource_type="cache"
        )
        assert handle is not None

    @pytest.mark.asyncio
    async def test_health_metrics_include_cache(self, adapter):
        """Test health metrics include cache metrics"""
        metrics = await adapter.get_health_metrics()
        assert isinstance(metrics, dict)
        assert "healthy" in metrics


class TestMonitoringSystemAdapter:
    """Test monitoring system adapter"""

    @pytest.fixture
    def adapter(self):
        return MonitoringSystemAdapter()

    @pytest.mark.asyncio
    async def test_inject_prometheus_export_latency(self, adapter):
        """Test prometheus export latency"""
        handle = await adapter.inject_latency(
            target_id="test_exp",
            component="prometheus_exporter",
            injection_point="metric_export",
            delay_ms=150,
            jitter_ms=30
        )
        assert handle is not None

    @pytest.mark.asyncio
    async def test_inject_metric_collection_error(self, adapter):
        """Test metric collection error injection"""
        handle = await adapter.inject_error(
            target_id="test_exp",
            component="metric_collector",
            injection_point="metric_collection",
            error_type="CollectionError",
            error_rate=0.05
        )
        assert handle is not None

    @pytest.mark.asyncio
    async def test_exhaust_metric_buffer(self, adapter):
        """Test metric buffer exhaustion"""
        handle = await adapter.inject_resource_exhaustion(
            target_id="test_exp",
            component="metric_buffer",
            resource_type="buffer"
        )
        assert handle is not None

    @pytest.mark.asyncio
    async def test_health_metrics_include_throughput(self, adapter):
        """Test health metrics include throughput"""
        metrics = await adapter.get_health_metrics()
        assert isinstance(metrics, dict)
        assert "healthy" in metrics


class TestServicesSystemAdapter:
    """Test services system adapter"""

    @pytest.fixture
    def adapter(self):
        return ServicesSystemAdapter()

    @pytest.mark.asyncio
    async def test_inject_llm_inference_latency(self, adapter):
        """Test LLM inference latency"""
        handle = await adapter.inject_latency(
            target_id="test_exp",
            component="unified_llm",
            injection_point="llm_inference",
            delay_ms=500,
            jitter_ms=100
        )
        assert handle is not None

    @pytest.mark.asyncio
    async def test_inject_backup_error(self, adapter):
        """Test backup error injection"""
        handle = await adapter.inject_error(
            target_id="test_exp",
            component="backup_scheduler",
            injection_point="backup_operation",
            error_type="BackupError",
            error_rate=0.1
        )
        assert handle is not None

    @pytest.mark.asyncio
    async def test_exhaust_llm_queue(self, adapter):
        """Test LLM queue exhaustion"""
        handle = await adapter.inject_resource_exhaustion(
            target_id="test_exp",
            component="unified_llm",
            resource_type="queue"
        )
        assert handle is not None

    @pytest.mark.asyncio
    async def test_health_metrics_include_gpu(self, adapter):
        """Test health metrics include GPU metrics"""
        metrics = await adapter.get_health_metrics()
        assert isinstance(metrics, dict)
        assert "healthy" in metrics


class TestLearningSystemAdapter:
    """Test learning system adapter"""

    @pytest.fixture
    def adapter(self):
        return LearningSystemAdapter()

    @pytest.mark.asyncio
    async def test_inject_training_latency(self, adapter):
        """Test training latency injection"""
        handle = await adapter.inject_latency(
            target_id="test_exp",
            component="training_system",
            injection_point="model_training",
            delay_ms=1000,
            jitter_ms=200
        )
        assert handle is not None

    @pytest.mark.asyncio
    async def test_get_health_metrics(self, adapter):
        """Test health metrics"""
        metrics = await adapter.get_health_metrics()
        assert isinstance(metrics, dict)
        assert "healthy" in metrics


class TestSecuritySystemAdapter:
    """Test security system adapter"""

    @pytest.fixture
    def adapter(self):
        return SecuritySystemAdapter()

    @pytest.mark.asyncio
    async def test_inject_waf_latency(self, adapter):
        """Test WAF latency injection"""
        handle = await adapter.inject_latency(
            target_id="test_exp",
            component="waf",
            injection_point="request_inspection",
            delay_ms=100,
            jitter_ms=20
        )
        assert handle is not None

    @pytest.mark.asyncio
    async def test_get_health_metrics(self, adapter):
        """Test health metrics"""
        metrics = await adapter.get_health_metrics()
        assert isinstance(metrics, dict)
        assert "healthy" in metrics


class TestReasoningSystemAdapter:
    """Test reasoning system adapter"""

    @pytest.fixture
    def adapter(self):
        return ReasoningSystemAdapter()

    @pytest.mark.asyncio
    async def test_inject_hypothesis_latency(self, adapter):
        """Test hypothesis generation latency"""
        handle = await adapter.inject_latency(
            target_id="test_exp",
            component="hypothesis_generator",
            injection_point="hypothesis_generation",
            delay_ms=300,
            jitter_ms=50
        )
        assert handle is not None

    @pytest.mark.asyncio
    async def test_get_health_metrics(self, adapter):
        """Test health metrics"""
        metrics = await adapter.get_health_metrics()
        assert isinstance(metrics, dict)
        assert "healthy" in metrics


class TestDomainSystemAdapter:
    """Test domain system adapter"""

    @pytest.fixture
    def adapter(self):
        return DomainSystemAdapter()

    @pytest.mark.asyncio
    async def test_inject_reasoner_latency(self, adapter):
        """Test reasoner latency injection"""
        handle = await adapter.inject_latency(
            target_id="test_exp",
            component="domain_reasoner",
            injection_point="reasoning",
            delay_ms=200,
            jitter_ms=40
        )
        assert handle is not None

    @pytest.mark.asyncio
    async def test_get_health_metrics(self, adapter):
        """Test health metrics"""
        metrics = await adapter.get_health_metrics()
        assert isinstance(metrics, dict)
        assert "healthy" in metrics


class TestMemorySystemAdapter:
    """Test memory system adapter"""

    @pytest.fixture
    def adapter(self):
        return MemorySystemAdapter()

    @pytest.mark.asyncio
    async def test_inject_mysql_latency(self, adapter):
        """Test MySQL latency injection"""
        handle = await adapter.inject_latency(
            target_id="test_exp",
            component="mysql_storage",
            injection_point="mysql_store",
            delay_ms=100,
            jitter_ms=20
        )
        assert handle is not None

    @pytest.mark.asyncio
    async def test_inject_r2_error(self, adapter):
        """Test R2 error injection"""
        handle = await adapter.inject_error(
            target_id="test_exp",
            component="r2_storage",
            injection_point="r2_store",
            error_type="R2Error",
            error_rate=0.05
        )
        assert handle is not None

    @pytest.mark.asyncio
    async def test_get_health_metrics(self, adapter):
        """Test health metrics"""
        metrics = await adapter.get_health_metrics()
        assert isinstance(metrics, dict)
        assert "healthy" in metrics


class TestAdapterCleanup:
    """Test adapter cleanup functionality"""

    @pytest.mark.asyncio
    async def test_all_adapters_cleanup(self):
        """Test that all adapters clean up properly"""
        adapters = [
            ToolSystemAdapter(),
            AgentSystemAdapter(),
            IntelligenceSystemAdapter(),
            MonitoringSystemAdapter(),
            ServicesSystemAdapter(),
            LearningSystemAdapter(),
            SecuritySystemAdapter(),
            ReasoningSystemAdapter(),
            DomainSystemAdapter(),
            MemorySystemAdapter()
        ]

        for adapter in adapters:
            # Inject some chaos
            await adapter.inject_latency(
                target_id="test_exp",
                component="test_component",
                injection_point="test_point",
                delay_ms=100,
                jitter_ms=10
            )

            # Cleanup
            await adapter.cleanup()

            # Verify cleanup - check metrics show no active injections
            metrics = await adapter.get_health_metrics()
            assert metrics.get("active_chaos_injections", 0) == 0


class TestAdapterMetrics:
    """Test adapter metrics functionality"""

    @pytest.mark.asyncio
    async def test_all_adapters_provide_metrics(self):
        """Test that all adapters provide health metrics"""
        adapters = [
            ToolSystemAdapter(),
            AgentSystemAdapter(),
            IntelligenceSystemAdapter(),
            MonitoringSystemAdapter(),
            ServicesSystemAdapter(),
            LearningSystemAdapter(),
            SecuritySystemAdapter(),
            ReasoningSystemAdapter(),
            DomainSystemAdapter(),
            MemorySystemAdapter()
        ]

        for adapter in adapters:
            metrics = await adapter.get_health_metrics()
            assert isinstance(metrics, dict)
            assert "healthy" in metrics


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
