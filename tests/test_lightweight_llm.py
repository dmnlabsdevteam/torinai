"""LightweightLLMService accounting: a served request must move the statistics.

This previously passed a plain dict to `process_request`, which takes a
`LightweightRequest` dataclass, so the call died on `request.request_id` before
reaching anything the test asserted. It also never set `model_loaded`, so the
first branch would have returned the not-initialized error regardless.

`_generate_response` is stubbed rather than the model, because loading a real
model is not what these assertions are about -- they are about the service
accounting for a response it served.
"""
import pytest

from core.services.lightweight_llm import (
    LightweightLLMService,
    LightweightRequest,
    LightweightResponse,
)


@pytest.mark.asyncio
async def test_a_served_request_is_counted_in_statistics():
    service = LightweightLLMService()

    served = LightweightResponse(
        text="The capital of France is Paris.",
        tokens_used=100,
        processing_time=0.5,
        success=True,
    )

    async def _fake_generate(request):
        # The service must hand the generator a real request object, not the
        # caller's raw input.
        assert isinstance(request, LightweightRequest)
        assert request.request_id, "the service did not stamp a request id"
        return served

    service.model_loaded = True
    service._generate_response = _fake_generate

    response = await service.process_request(
        LightweightRequest(
            prompt="What is the capital of France?",
            system_prompt="You are a helpful geography assistant.",
            agent_type="safety_classifier",
            max_tokens=50,
            temperature=0.3,
        ),
        bypass_queue=True,
    )

    assert response.success is True
    assert response.tokens_used == 100
    assert response.processing_time == 0.5
    assert response.text == "The capital of France is Paris."

    stats = service.get_statistics()
    assert stats["successful_requests"] == 1
    assert stats["failed_requests"] == 0
    assert stats["total_tokens"] == 100


@pytest.mark.asyncio
async def test_an_unloaded_service_reports_why_rather_than_raising():
    """Absence of a model is a reportable condition, not an exception."""
    service = LightweightLLMService()
    service.model_loaded = False

    async def _fail_init():
        return False

    service.initialize = _fail_init

    response = await service.process_request(
        LightweightRequest(prompt="hello", system_prompt="", agent_type="safety_classifier")
    )

    assert response.success is False
    assert "not initialized" in (response.error or "")
