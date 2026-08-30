"""Service registration writes through to the registry that readers consult.

These tests previously called `register_service(name, dict)` -- a two-argument
form the function has never had -- and the "valid input" case carried a TODO
where its assertions should have been. It therefore could not have passed, and
would not have detected anything if it had: registering without reading back
proves only that a call did not raise.
"""
import pytest

from core.service_configuration import (
    ServiceConfig,
    get_service_config,
    list_services,
    register_service,
    _service_configs,
)

PROBE = "probe_service_configuration"


@pytest.fixture(autouse=True)
def clean_registry():
    """The registry is module-level state; leaving rows in it would let one
    test decide another's result."""
    before = dict(_service_configs)
    yield
    _service_configs.clear()
    _service_configs.update(before)


def test_register_service_is_readable_afterwards():
    config = ServiceConfig(
        name=PROBE,
        enabled=True,
        auto_start=False,
        depends_on=["database"],
        config={"type": "test"},
    )

    register_service(config)

    stored = get_service_config(PROBE)
    assert stored is config, "the registry returned something other than what was stored"
    assert stored.enabled is True
    assert stored.auto_start is False
    assert stored.depends_on == ["database"]
    assert PROBE in list_services()


def test_registering_the_same_name_replaces_rather_than_duplicates():
    """The registry is keyed by name, so a second registration must supersede
    the first -- two live configurations for one service is the ambiguity the
    keying exists to prevent."""
    register_service(ServiceConfig(name=PROBE, enabled=True))
    register_service(ServiceConfig(name=PROBE, enabled=False))

    assert list_services().count(PROBE) == 1
    assert get_service_config(PROBE).enabled is False


def test_an_unregistered_service_reads_as_absent():
    """Absence is a real answer, not an error."""
    assert get_service_config(f"{PROBE}_never_registered") is None


def test_register_service_rejects_a_non_config():
    """A bare string has no `.name`, so registering it must fail rather than
    silently storing something no reader can use."""
    with pytest.raises(AttributeError):
        register_service("invalid_config")
