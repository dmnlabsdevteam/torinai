#!/usr/bin/env python3
"""
Chaos Orchestrator Tests
=========================

Comprehensive tests for ChaosOrchestrator including:
- Experiment lifecycle management
- Governance integration
- Progressive rollout
- Automatic rollback
- SLO monitoring
"""

import pytest
import asyncio
from datetime import datetime
from unittest.mock import Mock, AsyncMock, patch, MagicMock

from core.chaos.orchestrator import ChaosOrchestrator, get_orchestrator
from core.chaos.types import (
    ChaosType, ExperimentStatus, InjectionConfig,
    ChaosExperiment, ExperimentResult, SLOViolation
)


@pytest.fixture
def orchestrator():
    """Create test orchestrator instance"""
    config = {"observability": {"enable_mysql_logging": False}}
    return ChaosOrchestrator(config=config)


@pytest.fixture
def sample_injection_config():
    """Sample injection configuration"""
    return InjectionConfig(
        component="tool_registry",
        injection_point="get_tool",
        chaos_type=ChaosType.LATENCY,
        delay_ms=500,
        jitter_ms=100,
        error_type="TestError",
        error_rate=0.1,
        resource_type="cpu",
        limit_value=80.0
    )


class TestOrchestratorInitialization:
    """Test orchestrator initialization and setup"""

    def test_orchestrator_singleton(self):
        """Test that get_orchestrator returns singleton instance"""
        orch1 = get_orchestrator()
        orch2 = get_orchestrator()
        assert orch1 is orch2

    def test_orchestrator_components_initialized(self, orchestrator):
        """Test that all components are initialized"""
        assert orchestrator.experiment_manager is not None
        assert orchestrator.injection_engine is not None
        assert orchestrator.safety_controller is not None

    def test_orchestrator_config_loaded(self, orchestrator):
        """Test that configuration is loaded"""
        assert orchestrator.config is not None
        assert "safety_controls" in orchestrator.config
        assert "progressive_rollout" in orchestrator.config


class TestExperimentCreation:
    """Test experiment creation with governance integration"""

    @pytest.mark.asyncio
    async def test_create_experiment_basic(self, orchestrator, sample_injection_config):
        """Test basic experiment creation"""
        experiment = await orchestrator.create_experiment(
            name="Test Experiment",
            description="Test description",
            target_system="tool_system",
            chaos_type=ChaosType.LATENCY,
            environment="dev",
            injection_config=sample_injection_config,
            blast_radius=10
        )

        assert experiment is not None
        assert experiment.name == "Test Experiment"
        assert experiment.target_system == "tool_system"
        assert experiment.chaos_type == ChaosType.LATENCY
        assert experiment.blast_radius == 10
        assert experiment.status == ExperimentStatus.PENDING

    @pytest.mark.asyncio
    async def test_create_experiment_with_hypothesis(self, orchestrator, sample_injection_config):
        """Test experiment creation with hypothesis"""
        hypothesis = {
            "hypothesis_statement": "System should handle latency gracefully",
            "expected_behavior": {
                "max_latency_p95_ms": 700,
                "max_error_rate": 0.01
            }
        }

        experiment = await orchestrator.create_experiment(
            name="Test with Hypothesis",
            description="Test description",
            target_system="tool_system",
            chaos_type=ChaosType.LATENCY,
            environment="dev",
            injection_config=sample_injection_config,
            blast_radius=10,
            hypothesis=hypothesis
        )

        assert experiment.hypothesis is not None
        assert "hypothesis_statement" in experiment.hypothesis

    @pytest.mark.asyncio
    async def test_create_experiment_governance_required(self, orchestrator, sample_injection_config):
        """Test that production experiments require governance"""
        with patch.object(orchestrator, '_request_governance_approval', new_callable=AsyncMock) as mock_gov:
            mock_gov.return_value = True

            experiment = await orchestrator.create_experiment(
                name="Production Test",
                description="Test description",
                target_system="tool_system",
                chaos_type=ChaosType.LATENCY,
                environment="production",
                injection_config=sample_injection_config,
                blast_radius=50,
                requires_governance=True
            )

            assert experiment.governance_tier in ["ROUTINE", "IMPORTANT", "CRITICAL"]
            # Governance approval should have been requested
            mock_gov.assert_called_once()


class TestExperimentExecution:
    """Test experiment execution with safety controls"""

    @pytest.mark.asyncio
    async def test_run_experiment_success(self, orchestrator, sample_injection_config):
        """Test successful experiment execution"""
        # Create experiment
        experiment = await orchestrator.create_experiment(
            name="Success Test",
            description="Test description",
            target_system="tool_system",
            chaos_type=ChaosType.LATENCY,
            environment="dev",
            injection_config=sample_injection_config,
            blast_radius=5
        )

        # Mock safety controller to pass pre-flight checks
        from core.chaos.types import PreFlightResult, SLOStatus

        async def mock_preflight(*args, **kwargs):
            return PreFlightResult(passed=True, checks=[])

        async def mock_slo(*args, **kwargs):
            return SLOStatus(healthy=True, violations=[], should_rollback=False, metrics={})

        with patch.object(orchestrator.safety_controller, 'pre_flight_check', side_effect=mock_preflight):
            # Mock SLO checks to pass
            with patch.object(orchestrator.safety_controller, 'monitor_slos', side_effect=mock_slo):

                # Mock injection engine
                with patch.object(orchestrator.injection_engine, 'inject_chaos', new_callable=AsyncMock) as mock_inject:
                    mock_inject.return_value = Mock(injection_id="test_injection")

                    # Mock asyncio.sleep to skip waiting
                    async def mock_sleep(*args, **kwargs):
                        pass

                    with patch('asyncio.sleep', side_effect=mock_sleep):
                        # Mock time to skip waiting - return value increases each call
                        with patch('time.time') as mock_time:
                            call_count = [0]
                            def time_mock():
                                call_count[0] += 1
                                if call_count[0] <= 2:
                                    return 0  # Start time
                                else:
                                    return 1000  # End time - way past duration
                            mock_time.side_effect = time_mock

                            # Run experiment (short duration for test)
                            result = await orchestrator.run_experiment(
                                experiment_id=experiment.experiment_id,
                                progressive_rollout=False,
                                duration_minutes=0.01
                            )

                            assert result is not None
                            assert result.success is True
                            assert len(result.metrics_collected) >= 0

    @pytest.mark.asyncio
    async def test_run_experiment_preflight_failure(self, orchestrator, sample_injection_config):
        """Test that pre-flight check failures block execution"""
        experiment = await orchestrator.create_experiment(
            name="Preflight Fail Test",
            description="Test description",
            target_system="tool_system",
            chaos_type=ChaosType.LATENCY,
            environment="dev",
            injection_config=sample_injection_config,
            blast_radius=5
        )

        # Mock safety controller to fail pre-flight checks
        with patch.object(orchestrator.safety_controller, 'pre_flight_check', new_callable=AsyncMock) as mock_preflight:
            from core.chaos.types import PreFlightResult, PreFlightCheck
            mock_preflight.return_value = PreFlightResult(
                passed=False,
                can_proceed=False,
                blocking_issues=["Target system unhealthy"],
                checks=[PreFlightCheck(name="target_health", passed=False, reason="Target system unhealthy")]
            )

            result = await orchestrator.run_experiment(
                experiment_id=experiment.experiment_id,
                progressive_rollout=False
            )

            # Should return failed result
            assert result is not None
            assert result.success is False
            assert result.status == ExperimentStatus.FAILED
            assert "Pre-flight check failed" in result.insights[0]

    @pytest.mark.asyncio
    async def test_run_experiment_auto_rollback_on_slo_violation(self, orchestrator, sample_injection_config):
        """Test automatic rollback on SLO violation"""
        experiment = await orchestrator.create_experiment(
            name="SLO Violation Test",
            description="Test description",
            target_system="tool_system",
            chaos_type=ChaosType.LATENCY,
            environment="dev",
            injection_config=sample_injection_config,
            blast_radius=5
        )

        # Mock pre-flight checks to pass
        with patch.object(orchestrator.safety_controller, 'pre_flight_check', new_callable=AsyncMock) as mock_preflight:
            from core.chaos.types import PreFlightResult
            mock_preflight.return_value = PreFlightResult(passed=True, checks=[])

            # Mock SLO check to fail
            with patch.object(orchestrator.safety_controller, 'monitor_slos', new_callable=AsyncMock) as mock_slo:
                from core.chaos.types import SLOStatus
                mock_slo.return_value = SLOStatus(
                    healthy=False,
                    violations=["latency_p95_ms: 1200 > 500"],
                    should_rollback=True,
                    metrics={}
                )

                # Mock injection engine
                with patch.object(orchestrator.injection_engine, 'inject_chaos', new_callable=AsyncMock) as mock_inject:
                    mock_inject.return_value = Mock(injection_id="test_injection")

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

                        # Run experiment
                        result = await orchestrator.run_experiment(
                            experiment_id=experiment.experiment_id,
                            progressive_rollout=False,
                            duration_minutes=0.01
                        )

                        # Should trigger rollback
                        assert result.rollback_triggered is True


class TestProgressiveRollout:
    """Test progressive rollout functionality"""

    @pytest.mark.asyncio
    async def test_progressive_rollout_stages(self, orchestrator, sample_injection_config):
        """Test progressive rollout through all stages"""
        experiment = await orchestrator.create_experiment(
            name="Progressive Rollout Test",
            description="Test description",
            target_system="tool_system",
            chaos_type=ChaosType.LATENCY,
            environment="dev",
            injection_config=sample_injection_config,
            blast_radius=50
        )

        # Mock pre-flight checks
        with patch.object(orchestrator.safety_controller, 'pre_flight_check', new_callable=AsyncMock) as mock_preflight:
            from core.chaos.types import PreFlightResult
            mock_preflight.return_value = PreFlightResult(passed=True, checks=[])

            # Mock SLO checks to pass
            with patch.object(orchestrator.safety_controller, 'monitor_slos', new_callable=AsyncMock) as mock_slo:
                from core.chaos.types import SLOStatus
                mock_slo.return_value = SLOStatus(healthy=True, violations=[], should_rollback=False, metrics={})

                # Mock injection engine
                with patch.object(orchestrator.injection_engine, 'inject_chaos', new_callable=AsyncMock) as mock_inject:
                    mock_inject.return_value = Mock(injection_id="test_injection")

                    # Shorten stage durations for testing
                    # The ATTRIBUTE, not the parser: __init__ already called
                    # _parse_rollout_stages and cached it in self.rollout_stages,
                    # so patching the method had no effect. This test passed
                    # anyway because its advancing clock exits every stage
                    # immediately regardless of duration -- the ineffective patch
                    # was masked rather than harmless.
                    from core.chaos.types import RolloutStage
                    short_stages = [
                        RolloutStage(name="canary", blast_radius=1, duration_minutes=0, slo_check_interval_seconds=1),
                        RolloutStage(name="gradual_10", blast_radius=10, duration_minutes=0, slo_check_interval_seconds=1),
                        RolloutStage(name="full", blast_radius=50, duration_minutes=0, slo_check_interval_seconds=1)
                    ]
                    with patch.object(orchestrator, 'rollout_stages', short_stages):

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
                                    progressive_rollout=True
                                )

                                # Should complete all stages successfully
                                assert result.success is True


class TestRollback:
    """Test rollback functionality"""

    @pytest.mark.asyncio
    async def test_manual_rollback(self, orchestrator, sample_injection_config):
        """Test manual rollback of running experiment"""
        experiment = await orchestrator.create_experiment(
            name="Rollback Test",
            description="Test description",
            target_system="tool_system",
            chaos_type=ChaosType.LATENCY,
            environment="dev",
            injection_config=sample_injection_config,
            blast_radius=5
        )

        # Mock cleanup
        with patch.object(orchestrator.injection_engine, 'cleanup_system', new_callable=AsyncMock) as mock_cleanup:
            await orchestrator.rollback_experiment(
                experiment_id=experiment.experiment_id,
                reason="Manual rollback test"
            )

            # Should call cleanup_system
            mock_cleanup.assert_called_once_with(experiment.target_system)


class TestExperimentStatus:
    """Test experiment status retrieval"""

    @pytest.mark.asyncio
    async def test_get_experiment_status(self, orchestrator, sample_injection_config):
        """Test retrieving experiment status"""
        experiment = await orchestrator.create_experiment(
            name="Status Test",
            description="Test description",
            target_system="tool_system",
            chaos_type=ChaosType.LATENCY,
            environment="dev",
            injection_config=sample_injection_config,
            blast_radius=5
        )

        status = await orchestrator.get_experiment_status(experiment.experiment_id)

        assert status is not None
        assert "experiment_id" in status
        assert "status" in status
        assert "name" in status
        assert status["experiment_id"] == experiment.experiment_id

    @pytest.mark.asyncio
    async def test_get_nonexistent_experiment_status(self, orchestrator):
        """Test getting status of nonexistent experiment raises error"""
        with pytest.raises(ValueError, match="not found"):
            await orchestrator.get_experiment_status("nonexistent_id")


class TestMySQLPersistence:
    """Persistence functionality.

    Named for MySQL and configured by `enable_mysql_logging` for backward
    compatibility; the store is the PostgreSQL unified schema via
    LoggingDatabase.
    """

    @pytest.mark.asyncio
    async def test_experiment_persisted_to_mysql(self):
        """Test that experiments are persisted to MySQL when enabled"""
        config = {"observability": {"enable_mysql_logging": True}}
        orch = ChaosOrchestrator(config=config)

        # Mock database
        mock_db = AsyncMock()
        orch.db = mock_db

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

        experiment = await orch.create_experiment(
            name="MySQL Test",
            description="Test",
            target_system="tool_system",
            chaos_type=ChaosType.LATENCY,
            environment="dev",
            injection_config=config,
            blast_radius=5
        )

        # Persistence goes through LoggingDatabase's typed methods, not a raw
        # execute_query -- asserting the old call meant this test could not have
        # detected persistence working OR failing.
        assert mock_db.update_chaos_experiment.called, "experiment row never written"
        assert mock_db.log_chaos_event.called, "creation event never recorded"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
