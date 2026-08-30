#!/usr/bin/env python3
"""The coordinator's question-answering entry point must be able to succeed.

`reason_about` previously hand-built a ReasoningContext that no reasoning
strategy could accept -- the question went into `facts` while every strategy's
`is_applicable` requires `premises`, and `rules` was never populated. Measured:
all four strategies inapplicable, zero conclusions, under every reasoning type.
It had zero callers repo-wide, so nothing ever surfaced it, and `return None`
on no-conclusion made that total wiring failure look exactly like "no answer".

These tests pin the two properties that failure violated: it must delegate to
the substrate's reasoning entry point rather than reimplementing routing, and a
missing substrate must be reported as a wiring fault rather than as an absence
of knowledge.
"""

import types

import pytest

from core.agents.autonomous.autonomous_coordinator import AutonomousCoordinator


class _Bridge:
    def __init__(self, result):
        self.result = result
        self.seen = None

    async def reason(self, request):
        self.seen = request
        return self.result


def _stub(bridge):
    """A minimal object carrying only what reason_about touches."""
    stored = []

    async def store_memory(memory_type, content, importance=0.0, tags=None):
        stored.append(content)

    stub = types.SimpleNamespace(neural_bridge=bridge, store_memory=store_memory)
    stub.stored = stored
    return stub


@pytest.mark.asyncio
async def test_a_missing_substrate_is_a_wiring_fault_not_a_shrug():
    """The five things that used to collapse into a bare None must stay
    distinguishable: an unwired substrate is a FAULT, not ignorance."""
    from core.reasoning.neural_bridge import REASON_CAPABILITY_UNAVAILABLE

    stub = _stub(None)
    result = await AutonomousCoordinator.reason_about(stub, "Is Socrates mortal?")
    assert result is not None, "an unwired substrate must not look like 'no answer'"
    assert result.metadata["reason"] == REASON_CAPABILITY_UNAVAILABLE
    assert result.metadata["verified"] is False
    assert result.confidence == 0.0


@pytest.mark.asyncio
async def test_a_malformed_request_is_not_the_same_as_a_broken_substrate():
    from core.reasoning.neural_bridge import REASON_INVALID_INPUT

    stub = _stub(_Bridge(None))
    result = await AutonomousCoordinator.reason_about(stub, "   ")
    assert result.metadata["reason"] == REASON_INVALID_INPUT, (
        "a malformed request must be distinguishable from a broken substrate")


@pytest.mark.asyncio
async def test_reaching_no_conclusion_is_a_result_not_a_fault():
    from core.reasoning.neural_bridge import ReasoningMode, ReasoningResult

    bridge = _Bridge(ReasoningResult(
        answer="", confidence=0.0, mode_used=ReasoningMode.SYMBOLIC,
        metadata={"verified": False, "reason": "substrate_refuted"}))
    result = await AutonomousCoordinator.reason_about(_stub(bridge), "Is a whale a fish?")
    assert result.metadata["reason"] == "substrate_refuted"
    assert result.metadata["model_calls"] == 0, "a symbolic refutation had a model on its route"


@pytest.mark.asyncio
async def test_premises_and_rules_reach_the_substrate():
    """The original defect: context was built so that nothing could use it."""
    from core.reasoning.neural_bridge import ReasoningMode, ReasoningResult

    bridge = _Bridge(ReasoningResult(
        answer="Proved: socrates_mortal", confidence=0.98,
        mode_used=ReasoningMode.SYMBOLIC,
        metadata={"verified": True, "reason": "substrate_verified"}))
    stub = _stub(bridge)

    result = await AutonomousCoordinator.reason_about(
        stub, "Is Socrates mortal?",
        context={"premises": ["Socrates is human"], "rules": ["All humans are mortal"]})

    assert bridge.seen is not None, "the substrate was never called"
    assert "Socrates is human" in bridge.seen.context
    assert "All humans are mortal" in bridge.seen.context
    # The default ABSTRACT path -- the eleven kinds of thinking -- not a forced
    # single mode. AUTO was removed with the router; reason_about leaves mode
    # unset, and forcing one specific mode is what answered nothing.
    assert bridge.seen.mode is ReasoningMode.ABSTRACT
    assert result.metadata["verified"] is True
    assert result.metadata["reason"] == "substrate_verified"
    assert result.confidence == pytest.approx(0.98)
    # Provenance: who actually produced this.
    assert result.metadata["model_calls"] == 0
    assert "neural_bridge" in result.metadata["route"]


@pytest.mark.asyncio
async def test_an_unverified_answer_is_not_recorded_as_knowledge():
    """A solver-checked verdict and an unchecked assertion must not be stored
    with the same weight, or the memory becomes uncitable."""
    from core.reasoning.neural_bridge import ReasoningMode, ReasoningResult

    bridge = _Bridge(ReasoningResult(
        answer="probably", confidence=0.9, mode_used=ReasoningMode.NEURAL,
        metadata={"verified": False, "reason": "model_coverage"}))
    stub = _stub(bridge)

    result = await AutonomousCoordinator.reason_about(stub, "Is a whale a fish?")
    assert result.metadata["verified"] is False
    assert result.metadata["reason"] == "model_coverage"
    assert result.metadata["model_calls"] == 1, "a model answer must be visible in the provenance"
    assert stub.stored and stub.stored[0]["verified"] is False
