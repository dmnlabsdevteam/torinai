#!/usr/bin/env python3
"""The service locator, and the three defects nothing had ever exercised.

It lived in `core/security/service_abstractions.py` with ZERO consumers and no
security logic in it. The core container was correct; everything around it was
not, and every defect was in a path no caller had ever taken.
"""

import asyncio

import pytest

from core.system.service_locator import (DependencyInjector, ServiceLocator,
                                         get_service_locator,
                                         inject_dependencies)


class Engine:
    def __init__(self):
        self.started = True


class Car:
    def __init__(self, engine: Engine):
        self.engine = engine


def test_the_container_itself_was_always_correct():
    locator = ServiceLocator()
    locator.register_singleton(Engine, Engine)
    assert locator.get_service(Engine) is locator.get_service(Engine)

    locator.register_transient(Car, Engine)   # transient of a concrete type
    assert locator.get_service(Car) is not locator.get_service(Car)


def test_an_unregistered_service_raises_rather_than_returning_none():
    """A silent None here would travel and fail somewhere unrelated."""
    with pytest.raises(ValueError, match="not registered"):
        ServiceLocator().get_service(Engine)


def test_declared_dependencies_are_actually_resolved():
    """`ServiceDescriptor.dependencies` was DECLARED AND NEVER READ -- a caller
    could register a service with dependencies and they were silently
    discarded, constructing the object with no arguments."""
    from core.system.service_locator import ServiceDescriptor, ServiceScope

    locator = ServiceLocator()
    locator.register_singleton(Engine, Engine)
    locator._services[Car] = ServiceDescriptor(
        service_type=Car, implementation_type=Car,
        scope=ServiceScope.TRANSIENT, dependencies=[Engine])

    car = locator.get_service(Car)
    assert isinstance(car.engine, Engine)
    assert car.engine is locator.get_service(Engine)


def test_a_dependency_that_is_not_registered_is_reported_not_skipped():
    from core.system.service_locator import ServiceDescriptor, ServiceScope

    locator = ServiceLocator()
    locator._services[Car] = ServiceDescriptor(
        service_type=Car, implementation_type=Car,
        scope=ServiceScope.TRANSIENT, dependencies=[Engine])

    with pytest.raises(ValueError, match="not registered"):
        locator.get_service(Car)


def test_the_decorator_no_longer_needs_an_event_loop():
    """It ended `__init__` with `asyncio.create_task(...)`, so ANY class built
    outside a running loop raised RuntimeError."""
    get_service_locator().register_singleton(Engine, Engine)

    @inject_dependencies
    class Dashboard:
        engine: Engine

        def __init__(self):
            self.engine = None

    # Constructed with no loop running at all.
    dashboard = Dashboard()
    assert isinstance(dashboard.engine, Engine)


def test_injection_completes_before_the_constructor_returns():
    """The decorator fired a task and returned, so the object was handed to the
    caller with its dependencies still None while the decorator's name promised
    they were set."""
    get_service_locator().register_singleton(Engine, Engine)

    observed = {}

    @inject_dependencies
    class Probe:
        engine: Engine

        def __init__(self):
            self.engine = None

    probe = Probe()
    observed["engine_at_return"] = probe.engine
    assert observed["engine_at_return"] is not None, (
        "dependencies were still unset when __init__ returned")


@pytest.mark.asyncio
async def test_the_async_form_still_works_and_agrees_with_the_sync_one():
    locator = ServiceLocator()
    locator.register_singleton(Engine, Engine)
    injector = DependencyInjector(locator)

    class Panel:
        engine: Engine

        def __init__(self):
            self.engine = None

    panel = Panel()
    await injector.inject_dependencies(panel)
    assert isinstance(panel.engine, Engine)


def test_it_no_longer_lives_in_the_security_package():
    """It contains no security logic; filing it there made it look like part of
    the security subsystem."""
    import importlib

    with pytest.raises(ImportError):
        importlib.import_module("core.security.service_abstractions")
