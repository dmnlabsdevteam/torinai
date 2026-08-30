#!/usr/bin/env python3
"""Security has one authority, and nothing may fabricate its verdict.

`safety_framework.evaluate_action` is the authority: it composes the security
controller, runtime capacity, and the governance rule engine, and every
evaluation is persisted. Unlike learning before its authority existed, this one
was real -- the defect was callers going around it.

`memory_agent.validate_governance_compliance` called
`governance.check_compliance(action=..., context=...)`, WHICH DOES NOT EXIST on
the trigger system. Every call raised AttributeError, a broad handler swallowed
it, and the function returned `True, "Operation complies with governance"`.
Every memory-agent operation was approved unconditionally while reporting a
governance check had passed -- a fabricated authorization, which is worse than
no check at all: a missing check is visible, an invented one is not.
"""

import pytest


def test_the_method_that_was_being_called_still_does_not_exist():
    """Pins the diagnosis. If a `check_compliance` is ever added to the trigger
    system, this test should be revisited deliberately rather than silently
    making the old call look correct."""
    from core.governance.unified_governance_trigger_system import get_governance_system
    assert not hasattr(get_governance_system(), "check_compliance")


def test_memory_agent_no_longer_calls_the_governance_system_for_authorization():
    """It must route to the authority, not to a system that cannot answer."""
    import ast
    import inspect
    import textwrap

    from core.agents.memory_agent import MemoryAgent
    source = textwrap.dedent(inspect.getsource(MemoryAgent.validate_governance_compliance))

    # PARSED, not string-matched. The fix documents the old call verbatim so the
    # defect stays legible, and a substring check cannot tell a comment from
    # code -- it would fail on its own explanation.
    tree = ast.parse(source)
    called = {node.func.attr for node in ast.walk(tree)
              if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
    assert "check_compliance" not in called, "still calls a method that does not exist"
    assert "evaluate_action" in called, "does not route to the authority"
    assert "get_safety_framework" in source


@pytest.mark.asyncio
async def test_an_ordinary_operation_is_evaluated_not_merely_approved():
    from core.agents.memory_agent import MemoryAgent

    agent = object.__new__(MemoryAgent)
    approved, reason = await MemoryAgent.validate_governance_compliance(
        agent, "store_memory", {})
    assert approved is True
    # The claim must describe what actually happened.
    assert "Evaluated by safety framework" in reason
    assert "complies with governance" not in reason


@pytest.mark.asyncio
async def test_a_protected_operation_still_requires_its_token():
    from core.agents.memory_agent import MemoryAgent

    agent = object.__new__(MemoryAgent)
    approved, reason = await MemoryAgent.validate_governance_compliance(
        agent, "delete_all_memories", {})
    assert approved is False
    assert "capability token" in reason


@pytest.mark.asyncio
async def test_an_unavailable_evaluator_does_not_report_compliance(monkeypatch):
    """Governance does not gate ordinary execution, so an unavailable evaluator
    does not stop the operation -- but it must never be reported as a passed
    check. The claim is the defect, not the allow."""
    import core.security.safety_framework as framework
    from core.agents.memory_agent import MemoryAgent

    def unavailable():
        raise RuntimeError("evaluator down")

    monkeypatch.setattr(framework, "get_safety_framework", unavailable)

    agent = object.__new__(MemoryAgent)
    approved, reason = await MemoryAgent.validate_governance_compliance(
        agent, "store_memory", {})
    assert approved is True, "governance must not block ordinary execution"
    assert "unavailable" in reason and "not evaluated" in reason
    assert "complies" not in reason


def test_the_audit_worker_hook_does_not_claim_an_integration_it_lacks():
    """The setter is fed the real authority now, but nothing reads it. The
    docstring and log must say so rather than implying a live integration."""
    import inspect

    from core.security.security_audit_worker import SecurityAuditWorker
    source = inspect.getsource(SecurityAuditWorker.set_safety_framework)
    assert "no consumer reads it yet" in source


# ---- system security: enforcement mode must not be decided by accident ----

@pytest.fixture
def clean_security():
    from core.security import reset_integrated_security_system
    reset_integrated_security_system()
    yield
    reset_integrated_security_system()


def test_observing_security_never_creates_it(clean_security):
    """The getter used to CREATE the process-wide singleton hardcoded to
    test_mode=True -- dry-run, no real firewall rules. Its only callers are
    read-only observers, so merely looking at security could fix the whole
    process into dry-run, after which the production initialisation in
    core/main.py hit the singleton early-return and had its test_mode=False and
    its API keys discarded, while logging "Firewall PRODUCTION MODE"."""
    from core.security import get_integrated_security_system
    assert get_integrated_security_system() is None


@pytest.mark.asyncio
async def test_enforcement_cannot_be_silently_downgraded(clean_security):
    """A caller asking for real enforcement must not be handed a dry-run system."""
    from core.security import (create_integrated_security_system,
                               get_integrated_security_system)

    create_integrated_security_system(test_mode=True, use_singleton=True)
    assert get_integrated_security_system()["test_mode"] is True

    with pytest.raises(RuntimeError, match="dry-run"):
        create_integrated_security_system(test_mode=False, use_singleton=True)


@pytest.mark.asyncio
async def test_requesting_dry_run_against_an_enforcing_system_is_allowed_but_warned(
        clean_security, caplog):
    """The safe direction: you asked for less protection and got more."""
    from core.security import create_integrated_security_system

    create_integrated_security_system(test_mode=False, use_singleton=True)
    system = create_integrated_security_system(test_mode=True, use_singleton=True)
    assert system["test_mode"] is False


@pytest.mark.asyncio
async def test_the_observers_report_absence_rather_than_crashing(clean_security):
    """They call `.get(...)` on the result, so a None must be handled where it
    is received rather than becoming an AttributeError somewhere else."""
    import inspect

    from core.health.health_monitor import HealthMonitor
    source = inspect.getsource(HealthMonitor)
    assert source.count("if sec_sys is None:") >= 2
