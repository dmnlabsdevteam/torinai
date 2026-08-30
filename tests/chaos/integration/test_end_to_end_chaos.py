#!/usr/bin/env python3
"""
End-to-End Chaos Integration Tests
===================================

Integration tests that exercise the entire chaos framework:
- Create experiments from scenarios
- Run experiments with all safety controls
- Test progressive rollout
- Verify governance integration
- Test MySQL persistence
- Validate metrics collection and hypothesis testing
"""

import pytest
import asyncio
from datetime import datetime
from unittest.mock import Mock, AsyncMock, patch

from core.chaos.orchestrator import ChaosOrchestrator
from core.chaos.experiment_manager import get_experiment_manager
from core.chaos.injection_engine import ChaosInjectionEngine
from core.chaos.safety_controller import ChaosSafetyController
from core.chaos.observability import ChaosObservability
from core.chaos.types import ChaosType, ExperimentStatus
from core.chaos.scenarios import get_scenario, list_all_scenarios


class TestEndToEndScenarioExecution:
    """Test end-to-end execution of chaos scenarios"""

    @pytest.fixture
    def orchestrator(self):
        """Create test orchestrator"""
        config = {"observability": {"enable_mysql_logging": False}}
        return ChaosOrchestrator(config=config)

    @pytest.mark.asyncio
    async def test_tool_registry_latency_scenario(self, orchestrator):
        """Test tool registry latency scenario end-to-end"""
        # Get scenario from library
        scenario = get_scenario("tool_registry_latency")

        # Create experiment from scenario
        experiment_manager = get_experiment_manager()
        experiment = await experiment_manager.create_experiment_from_scenario(
            scenario_id="tool_registry_latency",
            environment="dev",
            blast_radius=5
        )

        assert experiment is not None
        assert experiment.name == "Tool Registry Latency Spike (dev)"
        assert experiment.target_system == "tool_system"
        assert experiment.chaos_type == ChaosType.LATENCY

    @pytest.mark.asyncio
    async def test_intelligence_nlp_latency_scenario(self, orchestrator):
        """Test intelligence system NLP latency scenario end-to-end"""
        scenario = get_scenario("nlp_processing_latency")

        experiment_manager = get_experiment_manager()
        experiment = await experiment_manager.create_experiment_from_scenario(
            scenario_id="nlp_processing_latency",
            environment="dev",
            blast_radius=5
        )

        assert experiment is not None
        assert experiment.name == "NLP Processing Latency Spike (dev)"
        assert experiment.target_system == "intelligence_system"

    @pytest.mark.asyncio
    async def test_services_llm_inference_scenario(self, orchestrator):
        """Test services system LLM inference scenario end-to-end"""
        scenario = get_scenario("llm_inference_latency")

        experiment_manager = get_experiment_manager()
        experiment = await experiment_manager.create_experiment_from_scenario(
            scenario_id="llm_inference_latency",
            environment="dev",
            blast_radius=5
        )

        assert experiment is not None
        assert experiment.name == "LLM Inference Latency Spike (dev)"
        assert experiment.target_system == "services_system"

    @pytest.mark.asyncio
    async def test_monitoring_prometheus_scenario(self, orchestrator):
        """Test monitoring system Prometheus export scenario end-to-end"""
        scenario = get_scenario("prometheus_export_latency")

        experiment_manager = get_experiment_manager()
        experiment = await experiment_manager.create_experiment_from_scenario(
            scenario_id="prometheus_export_latency",
            environment="dev",
            blast_radius=3
        )

        assert experiment is not None
        assert experiment.name == "Prometheus Metrics Export Latency (dev)"
        assert experiment.target_system == "monitoring_system"


class TestAllSystemsScenarios:
    """Test that all 10 systems have working scenarios"""

    def test_all_systems_have_scenarios(self):
        """Test that all systems have scenarios defined"""
        all_scenarios = list_all_scenarios()

        expected_systems = [
            "tool_system",
            "learning_system",
            "security_system",
            "reasoning_system",
            "autonomous_agents",
            "domain_system",
            "memory_system",
            "intelligence_system",
            "monitoring_system",
            "services_system"
        ]

        for system in expected_systems:
            assert system in all_scenarios
            assert len(all_scenarios[system]) > 0

    def test_total_scenario_count(self):
        """Test that we have at least 28 scenarios across all systems"""
        all_scenarios = list_all_scenarios()
        total_count = sum(len(scenarios) for scenarios in all_scenarios.values())

        # We have 3 scenarios per old system (7 systems = 21)
        # Plus 3 scenarios per new system (3 systems = 9)
        # Total = 30 scenarios minimum
        assert total_count >= 28


class TestProgressiveRolloutIntegration:
    """Test progressive rollout integration"""

    @pytest.fixture
    def orchestrator(self):
        config = {
            "observability": {"enable_mysql_logging": False},
            "safety_controls": {
                "max_blast_radius_dev": 100,  # Allow high blast radius for progressive rollout test
            }
        }
        return ChaosOrchestrator(config=config)

    @pytest.mark.asyncio
    async def test_progressive_rollout_with_safety_checks(self, orchestrator):
        """Test progressive rollout with safety checks at each stage"""
        # Update config to allow high blast radius for progressive rollout test
        orchestrator.experiment_manager.config.setdefault("safety_controls", {})["max_blast_radius_dev"] = 100
        orchestrator.experiment_manager.config.setdefault("target_systems", {}).setdefault("tool_system", {})["max_blast_radius"] = 100

        experiment = await orchestrator.experiment_manager.create_experiment_from_scenario(
            scenario_id="tool_registry_latency",
            environment="dev",
            blast_radius=100  # Requires progressive rollout
        )

        # Mock pre-flight and SLO checks to pass
        from core.chaos.types import PreFlightResult, SLOStatus

        async def mock_preflight(*args, **kwargs):
            return PreFlightResult(
                passed=True,
                can_proceed=True,
                blocking_issues=[],
                checks={}
            )

        async def mock_slo(*args, **kwargs):
            return SLOStatus(healthy=True, violations=[], should_rollback=False, metrics={})

        with patch.object(orchestrator.safety_controller, 'pre_flight_check', side_effect=mock_preflight):
            with patch.object(orchestrator.safety_controller, 'monitor_slos', side_effect=mock_slo):

                # Mock injection engine
                async def mock_inject(*args, **kwargs):
                    return Mock(injection_id="test_injection")

                with patch.object(orchestrator.injection_engine, 'inject_chaos', side_effect=mock_inject):
                    # Shorten stages and mock sleep for testing
                    # Patch the ATTRIBUTE, not the parser. __init__ already
                    # called _parse_rollout_stages and cached the result in
                    # self.rollout_stages, which is what run_experiment reads --
                    # so patching the method here changed nothing and the real
                    # 5/10/15/30-minute stages stayed in force.
                    from core.chaos.types import RolloutStage
                    short_stages = [
                        RolloutStage(name="canary", blast_radius=1, duration_minutes=0.005,
                                     slo_check_interval_seconds=1),
                        RolloutStage(name="full", blast_radius=100, duration_minutes=0.005,
                                     slo_check_interval_seconds=1),
                    ]
                    with patch.object(orchestrator, 'rollout_stages', short_stages):

                        # Mock asyncio.sleep to skip waiting
                        async def mock_sleep(*args, **kwargs):
                            pass

                        with patch('asyncio.sleep', side_effect=mock_sleep):
                            # An ADVANCING clock, not a constant one. The monitor
                            # loop is `end_time = time.time() + duration` then
                            # `while time.time() < end_time`, so a constant makes
                            # elapsed permanently zero and the loop never exits --
                            # with sleep mocked out, that is a tight infinite spin,
                            # which is exactly how this test used to hang.
                            _clock = [0.0]
                            def _advancing_time():
                                _clock[0] += 600.0     # 10 minutes per reading
                                return _clock[0]

                            with patch('time.time', side_effect=_advancing_time):
                                result = await orchestrator.run_experiment(
                                    experiment_id=experiment.experiment_id,
                                    progressive_rollout=True
                                )

                                assert result.success is True


class TestHypothesisValidation:
    """Test hypothesis validation during experiments"""

    @pytest.fixture
    def orchestrator(self):
        config = {"observability": {"enable_mysql_logging": False}}
        return ChaosOrchestrator(config=config)

    @pytest.mark.asyncio
    async def test_hypothesis_validation_success(self, orchestrator):
        """Test successful hypothesis validation"""
        # Create experiment with hypothesis
        from core.chaos.types import InjectionConfig

        config = InjectionConfig(
            component="tool_registry",
            injection_point="get_tool",
            chaos_type=ChaosType.LATENCY,
            delay_ms=100,
            jitter_ms=10,
            error_type="",
            error_rate=0.0,
            resource_type="",
            limit_value=None
        )

        hypothesis = {
            "hypothesis_statement": "System should handle 100ms latency",
            "expected_behavior": {
                "max_latency_p95_ms": 200,
                "max_error_rate": 0.01
            }
        }

        experiment = await orchestrator.create_experiment(
            name="Hypothesis Test",
            description="Test hypothesis validation",
            target_system="tool_system",
            chaos_type=ChaosType.LATENCY,
            environment="dev",
            injection_config=config,
            blast_radius=5,
            hypothesis=hypothesis
        )

        # Mock safety checks
        from core.chaos.types import PreFlightResult, SLOStatus

        async def mock_preflight(*args, **kwargs):
            return PreFlightResult(
                passed=True,
                can_proceed=True,
                blocking_issues=[],
                checks={}
            )

        async def mock_slo(*args, **kwargs):
            return SLOStatus(healthy=True, violations=[], should_rollback=False, metrics={})

        with patch.object(orchestrator.safety_controller, 'pre_flight_check', side_effect=mock_preflight):
            with patch.object(orchestrator.safety_controller, 'monitor_slos', side_effect=mock_slo):

                async def mock_inject(*args, **kwargs):
                    return Mock(injection_id="test")

                with patch.object(orchestrator.injection_engine, 'inject_chaos', side_effect=mock_inject):
                    # Mock asyncio.sleep to skip waiting
                    async def mock_sleep(*args, **kwargs):
                        pass

                    with patch('asyncio.sleep', side_effect=mock_sleep):
                        # Mock time to skip waiting
                        with patch('time.time') as mock_time:
                            call_count = [0]
                            def time_mock():
                                call_count[0] += 1
                                if call_count[0] <= 2:
                                    return 0
                                else:
                                    return 1000
                            mock_time.side_effect = time_mock

                            result = await orchestrator.run_experiment(
                                experiment_id=experiment.experiment_id,
                                progressive_rollout=False,
                                duration_minutes=0.01
                            )

                            # Should validate hypothesis
                            assert result is not None
                            assert "hypothesis_validated" in dir(result)


class TestGovernanceIntegration:
    """Test governance integration"""

    @pytest.fixture
    def orchestrator(self):
        config = {
            "observability": {"enable_mysql_logging": False},
            "safety_controls": {
                "max_blast_radius_production": 100,  # Allow high blast radius for governance tests
            }
        }
        return ChaosOrchestrator(config=config)

    @pytest.mark.asyncio
    async def test_production_experiment_requires_governance(self, orchestrator):
        """Test that production experiments require governance approval"""
        from core.chaos.types import InjectionConfig

        config = InjectionConfig(
            component="tool_registry",
            injection_point="get_tool",
            chaos_type=ChaosType.LATENCY,
            delay_ms=100,
            jitter_ms=10,
            error_type="",
            error_rate=0.0,
            resource_type="",
            limit_value=None
        )

        with patch.object(orchestrator, '_request_governance_approval', new_callable=AsyncMock) as mock_gov:
            mock_gov.return_value = True

            experiment = await orchestrator.create_experiment(
                name="Production Test",
                description="Test",
                target_system="tool_system",
                chaos_type=ChaosType.LATENCY,
                environment="production",
                injection_config=config,
                blast_radius=50,
                requires_governance=True
            )

            # Should have requested governance approval
            mock_gov.assert_called_once()
            assert experiment.governance_tier is not None

    @pytest.mark.asyncio
    async def test_high_blast_radius_requires_governance(self, orchestrator):
        """Test that high blast radius (>50%) requires governance"""
        # Update config to allow high blast radius for governance test
        orchestrator.experiment_manager.config.setdefault("safety_controls", {})["max_blast_radius_production"] = 100
        orchestrator.experiment_manager.config.setdefault("target_systems", {}).setdefault("tool_system", {})["max_blast_radius"] = 100

        from core.chaos.types import InjectionConfig

        config = InjectionConfig(
            component="tool_registry",
            injection_point="get_tool",
            chaos_type=ChaosType.LATENCY,
            delay_ms=100,
            jitter_ms=10,
            error_type="",
            error_rate=0.0,
            resource_type="",
            limit_value=None
        )

        with patch.object(orchestrator, '_request_governance_approval', new_callable=AsyncMock) as mock_gov:
            mock_gov.return_value = True

            experiment = await orchestrator.create_experiment(
                name="High Blast Test",
                description="Test",
                target_system="tool_system",
                chaos_type=ChaosType.LATENCY,
                environment="production",
                injection_config=config,
                blast_radius=75,  # >50%
                requires_governance=True
            )

            # Should require governance for high blast radius
            assert experiment.governance_tier in ["IMPORTANT", "CRITICAL"]


class TestMetricsCollection:
    """Test metrics collection and observability"""

    @pytest.fixture
    def observability(self):
        config = {"observability": {"enable_mysql_logging": False}}
        return ChaosObservability(config=config)

    @pytest.mark.asyncio
    async def test_metrics_collected_during_experiment(self, observability):
        """Test that metrics are collected during experiment"""
        from core.chaos.types import ChaosExperiment, InjectionConfig

        config = InjectionConfig(
            component="tool_registry",
            injection_point="get_tool",
            chaos_type=ChaosType.LATENCY,
            delay_ms=100,
            jitter_ms=10,
            error_type="",
            error_rate=0.0,
            resource_type="",
            limit_value=None
        )

        experiment = ChaosExperiment(
            experiment_id="test_123",
            name="Test",
            description="Test",
            target_system="tool_system",
            chaos_type=ChaosType.LATENCY,
            environment="dev",
            injection_config=config,
            blast_radius=5,
            status=ExperimentStatus.RUNNING
        )

        # Collect metrics
        metrics_list = await observability.collect_metrics(
            target_system="tool_system",
            experiment_id=experiment.experiment_id,
            duration_seconds=1
        )

        assert metrics_list is not None
        assert len(metrics_list) > 0
        assert metrics_list[0].timestamp is not None


class TestAutonomousSystemChaos:
    """Test chaos experiments on autonomous system with intrinsic motivation"""

    @pytest.fixture
    def orchestrator(self):
        config = {"observability": {"enable_mysql_logging": False}}
        return ChaosOrchestrator(config=config)

    @pytest.mark.asyncio
    async def test_intrinsic_motivation_chaos(self, orchestrator):
        """Test chaos injection into intrinsic motivation system"""
        from core.chaos.types import InjectionConfig

        config = InjectionConfig(
            component="intrinsic_motivation",
            injection_point="motivation_calculation",
            chaos_type=ChaosType.LATENCY,
            delay_ms=200,
            jitter_ms=50,
            error_type="",
            error_rate=0.0,
            resource_type="",
            limit_value=None
        )

        experiment = await orchestrator.create_experiment(
            name="Intrinsic Motivation Latency Test",
            description="Test 7D motivation system resilience",
            target_system="autonomous_agents",
            chaos_type=ChaosType.LATENCY,
            environment="dev",
            injection_config=config,
            blast_radius=10
        )

        assert experiment is not None
        assert experiment.target_system == "autonomous_agents"
        assert experiment.injection_config.component == "intrinsic_motivation"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
