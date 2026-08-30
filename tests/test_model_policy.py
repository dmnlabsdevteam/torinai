"""The strict lane must be provable, not merely quiet.

`executed == 0` is the weak claim -- it holds equally when the guard blocked
forty attempts. These oracles pin the distinction the experiment rests on:
a subsystem that keeps reaching for a model is still model-dependent, and
`attempts` is the only place that is visible.
"""
import pytest

from core.model_policy import (
    ModelClass, ModelPolicy, ModelUseForbidden,
    assert_model_free, get_model_policy, guard_model_use, model_telemetry,
    model_use, model_use_permitted, record_model_executed,
    reset_model_telemetry, set_model_policy,
)


@pytest.fixture(autouse=True)
def clean_policy():
    previous = get_model_policy()
    reset_model_telemetry()
    yield
    set_model_policy(previous)
    reset_model_telemetry()


def test_normal_is_the_default_so_production_is_unchanged():
    assert get_model_policy() is ModelPolicy.NORMAL


def test_strict_blocks_and_normal_does_not():
    set_model_policy(ModelPolicy.STRICT_MODEL_FREE)
    with pytest.raises(ModelUseForbidden):
        guard_model_use(ModelClass.LLM, "t")

    set_model_policy(ModelPolicy.NORMAL)
    guard_model_use(ModelClass.LLM, "t")  # must not raise


def test_a_blocked_attempt_is_still_an_attempt():
    """The whole point. A guard that works is not the same as a subsystem that
    does not need a model."""
    set_model_policy(ModelPolicy.STRICT_MODEL_FREE)
    for _ in range(3):
        with pytest.raises(ModelUseForbidden):
            guard_model_use(ModelClass.LLM, "reaches_anyway")

    t = model_telemetry()
    assert t["executed"] == 0, "nothing ran"
    assert t["attempts"] == 3, "but the reach must remain visible"
    assert t["blocked"] == 3


def test_assert_model_free_fails_on_attempts_alone():
    set_model_policy(ModelPolicy.STRICT_MODEL_FREE)
    with pytest.raises(ModelUseForbidden):
        guard_model_use(ModelClass.EMBEDDING, "retrieval")

    with pytest.raises(AssertionError) as e:
        assert_model_free("kite")
    assert "retrieval" in str(e.value), "the failure must name the site"


def test_assert_model_free_passes_only_on_true_silence():
    set_model_policy(ModelPolicy.STRICT_MODEL_FREE)
    assert_model_free("untouched")


def test_classes_are_counted_independently():
    """'We called no LLM' is a much weaker claim than 'we called no model' when
    retrieval still runs a sentence encoder."""
    guard_model_use(ModelClass.EMBEDDING, "e")
    record_model_executed(ModelClass.EMBEDDING, "e")

    by_class = model_telemetry()["by_class"]
    assert by_class["embedding"]["executed"] == 1
    assert by_class["llm"]["attempts"] == 0


def test_permitted_reports_instead_of_raising_but_still_counts():
    """The BM25 lane degrades rather than crashing -- and is still on the record."""
    set_model_policy(ModelPolicy.STRICT_MODEL_FREE)
    assert model_use_permitted(ModelClass.ENCODER, "ranking") is False
    assert model_telemetry()["by_class"]["encoder"]["attempts"] == 1

    set_model_policy(ModelPolicy.NORMAL)
    assert model_use_permitted(ModelClass.ENCODER, "ranking") is True


def test_a_call_that_raises_midway_is_not_counted_as_executed():
    """Attempted and completed are different facts."""
    with pytest.raises(ValueError):
        with model_use(ModelClass.LLM, "dies"):
            raise ValueError("transport failed")

    t = model_telemetry()["by_class"]["llm"]
    assert (t["attempts"], t["executed"]) == (1, 0)


def test_reset_returns_the_census_it_cleared():
    """A baseline must not be destroyed by the act of starting the next run."""
    guard_model_use(ModelClass.LLM, "before")
    previous = reset_model_telemetry()
    assert previous["attempts"] == 1
    assert model_telemetry()["attempts"] == 0


def test_sites_are_recorded_so_a_nonzero_count_is_actionable():
    guard_model_use(ModelClass.LLM, "core.a")
    guard_model_use(ModelClass.LLM, "core.a")
    guard_model_use(ModelClass.LLM, "core.b")
    assert model_telemetry()["by_class"]["llm"]["sites"] == {"core.a": 2, "core.b": 1}


def test_an_unknown_env_policy_is_refused_not_defaulted():
    """Silently falling back to NORMAL would run a 'strict' experiment with the
    model live and report it as model-free."""
    import os
    from core.model_policy import _policy_from_env

    os.environ["TORIN_MODEL_POLICY"] = "strictt"
    try:
        with pytest.raises(ValueError):
            _policy_from_env()
    finally:
        del os.environ["TORIN_MODEL_POLICY"]


# ------------------------------------------------------------------ boundaries
# Every path that reaches a learned model must route through the guard. These
# assert on the source, because a boundary added later without a guard is the
# failure that would make every subsequent experiment quietly wrong.

@pytest.mark.parametrize("module,func,expected_site", [
    ("core.services.unified_llm", "_submit_inference_job", "unified_llm._submit_inference_job"),
    ("core.services.unified_llm", "_remote_chat", "unified_llm._remote_chat"),
    ("core.services.unified_llm", "stream_chat", "unified_llm.stream_chat"),
    ("core.memory.utils.embedding_service", "generate_embedding", "embedding_service.generate_embedding"),
    ("core.memory.utils.embedding_service", "batch_embed", "embedding_service.batch_embed"),
    ("core.memory.utils.embedding_service", "initialize", "embedding_service.initialize"),
])
def test_every_model_boundary_declares_itself(module, func, expected_site):
    import importlib, inspect
    mod = importlib.import_module(module)
    owner = next(
        (obj for _, obj in inspect.getmembers(mod, inspect.isclass)
         if func in getattr(obj, "__dict__", {})),
        mod,
    )
    src = inspect.getsource(getattr(owner, func))
    assert expected_site in src, f"{module}.{func} reaches a model without declaring it"


def test_the_remote_lane_is_guarded_separately_from_the_queue():
    """_submit_inference_job is not a common choke point: the remote path
    short-circuits to _remote_chat and never enqueues a job."""
    import inspect
    from core.services.unified_llm import UnifiedLLMService

    src = inspect.getsource(UnifiedLLMService.generate_with_messages)
    assert "_remote_chat" in src and "_submit_inference_job" in src, (
        "both lanes must remain present for this test to mean anything"
    )
    assert "unified_llm._remote_chat" in inspect.getsource(
        UnifiedLLMService._remote_chat
    )
