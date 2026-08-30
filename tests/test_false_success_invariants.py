"""The audit question, as a standing test.

    Can this function return a value that causes its caller to believe
    something happened that did not actually happen?

These pin the answers found by the 2026-08-19 sweep so they cannot silently
come back. Each is an invariant about REPORTING, not about the feature: a
subsystem is allowed to be unavailable, and is not allowed to say otherwise.
"""
import asyncio

import pytest


@pytest.mark.asyncio
async def test_lazy_initialize_refuses_to_continue_after_failing():
    """`if not self.initialized: await self.initialize()` must check the result.

    Discarding it meant a failed initialize was followed immediately by the
    work it was meant to enable, and the real failure resurfaced somewhere
    unrelated -- observed as "Database not initialized" reaching a caller
    disguised as a model-weight ROLLBACK error.
    """
    from core.database.thinking_state_manager import ThinkingStateManager

    manager = ThinkingStateManager()
    manager.initialized = False

    async def _fails():
        return False

    manager.initialize = _fails

    with pytest.raises(RuntimeError, match="could not initialize"):
        await manager.get_active_states()


@pytest.mark.asyncio
async def test_quantum_availability_requires_an_executable_provider():
    """`quantum_available` must not mean "qiskit imported".

    Importing qiskit lets you CONSTRUCT a circuit; it says nothing about
    whether one can RUN. With no valid API token this reported True to every
    caller while there was no backend to execute on.
    """
    from core.reasoning.unified_quantum_reasoning_system import (
        UnifiedQuantumReasoningSystem)

    system = UnifiedQuantumReasoningSystem()
    assert system.quantum_available is False, (
        "no provider has been initialized, so nothing can execute")

    system.quantum_provider = object()
    assert system.quantum_available is system.qiskit_installed, (
        "availability must be derived from the provider, not asserted")


@pytest.mark.asyncio
async def test_ibm_provider_is_not_initialized_without_a_backend():
    """initialize() set initialized=True and logged "(backend: None)" on the
    same line -- recording the contradiction and acting on neither half."""
    from core.quantum.ibm_quantum_provider import IBMQuantumProvider
    from core.quantum.quantum_factory import create_quantum_config

    provider = IBMQuantumProvider(create_quantum_config())

    async def _selects_nothing():
        provider.backend = None

    provider._select_backend = _selects_nothing
    provider.service = object()

    assert await provider.initialize() is False
    assert provider.initialized is False


def test_a_failed_cost_estimate_is_not_free():
    """`cost_usd: 0.0` on a failed estimate is the one answer that invites a
    caller to proceed."""
    import inspect

    from core.quantum import ibm_quantum_provider

    source = inspect.getsource(ibm_quantum_provider)
    assert "'cost_usd': 0.0, 'error'" not in source, (
        "a failed estimate must not report zero cost")
    assert "'cost_usd': 0.0, 'backend': 'simulator'" in source, (
        "a simulator run genuinely is free -- that zero is a real measurement "
        "and must not be removed along with the fabricated ones")


def test_placeholders_raise_instead_of_returning_invented_metrics():
    """Two placeholders returned fixed accuracy/advantage figures as success."""
    from core.capability import CapabilityUnavailable
    from core.quantum.hybrid_processor import (
        HybridWorkflowManager, QuantumClassicalBridge)

    bridge = QuantumClassicalBridge.__new__(QuantumClassicalBridge)
    manager = HybridWorkflowManager.__new__(HybridWorkflowManager)

    async def _both():
        # returned final_loss 0.1 / accuracy 0.85 / training_time 1.5
        with pytest.raises(CapabilityUnavailable):
            await bridge._classical_ml_training(None, None)
        # returned the fixed string "Enhanced quantum reasoning result"
        with pytest.raises(CapabilityUnavailable):
            await manager._handle_reasoning(None)

    asyncio.run(_both())
