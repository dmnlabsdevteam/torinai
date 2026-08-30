"""Oracles for the health evaluator's evidence rules.

Every test here corresponds to a verdict the evaluator actually returned in
production. They are written against the failure, not around it: each one
passes on the old code only if the fabrication is still present.
"""
import ast
import inspect
import textwrap

import pytest

from core.health.health_monitor import HealthMonitor, HealthStatus


@pytest.fixture
def hm():
    # __new__ skips __init__, which is what we want (no monitoring loop, no DB),
    # but the declared-metric channel the checks write through must still exist.
    monitor = HealthMonitor.__new__(HealthMonitor)
    monitor._declared_metrics = {}
    return monitor


def test_no_signals_produces_no_score(hm):
    """A score is a summary of measurements. With none, there is nothing to
    summarise -- `sum(...) if signals else 1.0` invented a perfect one."""
    r = hm.evaluate("tools", {"total_tools": 384}, [])
    assert r["score"] is None
    assert r["status"] is HealthStatus.UNKNOWN
    assert r["coverage"] == 0.0


def test_issues_without_signals_are_not_a_passing_grade(hm):
    """The production reading: tools, one issue, zero measurable signals,
    graded HEALTHY 0.9 -- 1.0 fabricated, then decremented by one issue."""
    r = hm.evaluate("tools", {"total_tools": 384},
                    ["Tool outcomes are recorded asymmetrically"])
    assert r["status"] is not HealthStatus.HEALTHY
    assert r["status"] is HealthStatus.DEGRADED
    assert r["score"] is None, "unmeasured severity must not be quantified"


def test_severity_is_not_a_function_of_issue_count(hm):
    """Eleven issues and no signals graded UNHEALTHY 0.0; one graded HEALTHY
    0.9. Both numbers came from the same invented baseline, so the count alone
    decided severity -- the rule the weighted evaluator was meant to replace."""
    few = hm.evaluate("tools", {"n": 1}, ["a"])
    many = hm.evaluate("tools", {"n": 1}, [f"issue-{i}" for i in range(11)])
    assert few["status"] is many["status"], (
        "with no measurements, eleven issues are not gradably worse than one"
    )
    assert few["score"] is None and many["score"] is None


def test_high_score_on_partial_evidence_is_not_healthy(hm):
    """reasoning read HEALTHY 1.0 at coverage 0.25: one signal true, three
    metrics returned None. evaluate_declared already blocked this."""
    r = hm.evaluate("reasoning",
                    {"neural_bridge_initialized": True,
                     "bayesian_engine": None, "causal_engine": None,
                     "symbolic_engine": None},
                    [])
    assert r["coverage"] == 0.25
    assert r["status"] is HealthStatus.DEGRADED
    assert r["score"] == 1.0, "the score is real; the confidence in it is not"


def test_full_evidence_still_reaches_healthy(hm):
    """The coverage rule must not make HEALTHY unreachable."""
    r = hm.evaluate("reasoning",
                    {"neural_bridge_initialized": True, "engine_loaded": True},
                    [])
    assert r["coverage"] == 1.0
    assert r["status"] is HealthStatus.HEALTHY
    assert r["score"] == 1.0


def test_critical_gate_still_dominates(hm):
    """Gates outrank both rules above."""
    r = hm.evaluate("database", {"accessible": False, "query_rate": 1.0}, [])
    assert r["status"] is HealthStatus.CRITICAL
    assert r["gate_failures"] == ["accessible"]


def test_both_paths_apply_the_same_coverage_rule(hm):
    """The declared and inferred paths disagreed: one demoted a confident score
    computed without its required evidence, the other did not."""
    from core.health.health_monitor import HealthMetric
    declared = hm.evaluate_declared(
        "x",
        [HealthMetric(name="a", raw_value=True, normalized=1.0, required=True),
         HealthMetric(name="b", raw_value=None, normalized=None, required=True)],
        [],
    )
    inferred = hm.evaluate("x", {"a_initialized": True, "b": None}, [])
    assert declared["status"] is inferred["status"] is HealthStatus.DEGRADED


def test_persistence_never_substitutes_a_bucket_for_a_missing_score():
    """_persist_assessment fell back to _STATUS_SCORE[status] -- writing a
    fabricated 75.0 for a component whose score was None precisely because
    nothing could be measured. Asserted on the source: the behaviour needs a
    live database, but the substitution is a syntactic property."""
    src = textwrap.dedent(inspect.getsource(HealthMonitor._persist_assessment))
    tree = ast.parse(src)
    names = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    assert "_STATUS_SCORE" not in names
    assert not hasattr(HealthMonitor, "_STATUS_SCORE"), (
        "the bucket table is the fabrication source; it should not be reachable"
    )


def test_unmeasurable_component_still_writes_a_row():
    """Returning early left the component's PREVIOUS row in place, so the store
    kept serving a stale `healthy` for something no longer measurable."""
    src = inspect.getsource(HealthMonitor._persist_assessment)
    body = src.split("score =", 1)[1]
    assert "return False" not in body.split("INSERT")[0], (
        "no early return may precede the write; unmeasured is a row with NULL"
    )


class _FakeResp:
    status_code = 200


class _FakeRemoteClient:
    async def get(self, url, timeout=None):
        return _FakeResp()


class _FakeLLM:
    """Remote-mode service: no in-process worker, by design."""
    remote_url = "http://127.0.0.1:8099"
    _remote_client = _FakeRemoteClient()

    def get_statistics(self):
        return {"model_loaded": True, "total_requests": 0, "successful_requests": 0,
                "failed_requests": 0, "total_tokens": 0, "avg_processing_time": 0.0,
                "worker_alive": False, "inference_queue_size": 0}


@pytest.mark.asyncio
async def test_remote_llm_is_not_critical_for_lacking_a_local_worker(monkeypatch, hm):
    """`worker_alive` reads `_worker_task`, created only on the local
    model-loading path to serialise an in-process Llama object. Production runs
    remote, where no such object exists -- so this graded CRITICAL ('requests
    cannot be served') while requests were being served successfully."""
    import core.services.unified_llm as u
    monkeypatch.setattr(u, "get_llm_service", lambda: _FakeLLM())

    metrics, issues = await hm._check_llm_health()

    assert metrics["llm_mode"] == "remote"
    assert "llm_queue_worker_alive" not in metrics, (
        "a signal inapplicable to the running mode must not be reported at all"
    )
    assert metrics["llm_remote_endpoint_connected"] is True
    r = hm.evaluate("llm", metrics, issues)
    assert r["gate_failures"] == []
    assert r["status"] is HealthStatus.HEALTHY


@pytest.mark.asyncio
async def test_idle_service_reaches_full_coverage(monkeypatch, hm):
    """A failure rate over zero requests is undefined by arithmetic, not by a
    failed reading. Counting it as missing evidence capped an idle-but-working
    service below full coverage forever, so it could never grade HEALTHY."""
    import core.services.unified_llm as u
    monkeypatch.setattr(u, "get_llm_service", lambda: _FakeLLM())

    metrics, issues = await hm._check_llm_health()
    assert metrics["llm_failure_rate"] is None
    assert "llm_failure_rate" in metrics["_not_applicable"]

    r = hm.evaluate("llm", metrics, issues)
    assert r["coverage"] == 1.0
    assert r["status"] is HealthStatus.HEALTHY


def test_declared_not_applicable_is_neither_signal_nor_gap(hm):
    """The distinction has to hold generally, not just for the llm check."""
    base = hm.evaluate("x", {"a_initialized": True, "b_rate": None}, [])
    na = hm.evaluate("x", {"a_initialized": True, "b_rate": None,
                           "_not_applicable": ["b_rate"]}, [])
    assert base["coverage"] < 1.0 and na["coverage"] == 1.0
    assert na["signals_measured"] == base["signals_measured"], (
        "not-applicable must not be counted as a passing measurement either"
    )


@pytest.mark.asyncio
async def test_storage_failure_does_not_erase_a_computed_verdict(monkeypatch):
    """Persistence sat inside the outer handler, so a failed write replaced an
    already-computed verdict with UNKNOWN -- and would have erased a CRITICAL
    one the same way, hiding the failure instead of the outage."""
    from core.health.health_monitor import get_health_monitor
    monitor = get_health_monitor()

    async def boom(_record):
        raise RuntimeError("Database not initialized")

    monkeypatch.setattr(monitor, "_persist_assessment", boom)
    health = await monitor.check_component_health("storage")

    assert health.status is not HealthStatus.UNKNOWN, (
        "an unwritable store is a storage fact, not an unmeasurable component"
    )
    assert health.metrics.get("_persisted") is False
    assert any("not recorded" in i for i in health.issues)


@pytest.mark.asyncio
async def test_busy_dependency_is_not_an_unreachable_one(monkeypatch):
    """llama-server serves one request at a time, so /v1/models queues behind an
    in-flight generation and blows the 5s budget whenever the brain is thinking.
    This is a CRITICAL gate: ordinary inference load flipped `network` to
    UNHEALTHY and made system_awareness report critical services down, while
    inference was completing successfully."""
    import asyncio, os
    from core.health.health_monitor import get_health_monitor

    async def stalled(reader, writer):
        await reader.read(1024)      # accept, read the request, never answer
        await asyncio.sleep(60)

    srv = await asyncio.start_server(stalled, "127.0.0.1", 0)
    port = srv.sockets[0].getsockname()[1]
    monkeypatch.setenv("LLM_SERVER_URL", f"http://127.0.0.1:{port}")
    try:
        metrics, issues = await get_health_monitor()._check_network_health()
    finally:
        srv.close()
        await srv.wait_closed()

    assert metrics["path_llm_server_reachable"] is True
    assert metrics["path_llm_server_slow"] is True
    assert not [i for i in issues if "llm_server" in i]


@pytest.mark.asyncio
async def test_dead_dependency_is_still_reported_unreachable(monkeypatch):
    """The discrimination must not swallow a genuine outage."""
    import socket
    from core.health.health_monitor import get_health_monitor

    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()                        # nothing is listening on this port

    monkeypatch.setenv("LLM_SERVER_URL", f"http://127.0.0.1:{port}")
    metrics, issues = await get_health_monitor()._check_network_health()

    assert metrics["path_llm_server_reachable"] is False
    assert any("required_dependency_unreachable:llm_server" in i for i in issues)


def test_record_rate_separates_undefined_from_unread(hm):
    """One None was doing two jobs: a rate over zero observations (arithmetic,
    subsystem fine) and a value that could not be read (missing evidence)."""
    m = {}
    hm._record_rate(m, "idle_rate", 0.0, 0)            # nothing counted yet
    hm._record_rate(m, "broken_rate", "not-a-number", 5)   # reading failed
    hm._record_rate(m, "real_rate", 0.75, 4)

    assert m["idle_rate"] is None and "idle_rate" in m["_not_applicable"]
    assert m["broken_rate"] is None and "broken_rate" not in m["_not_applicable"]
    assert m["real_rate"] == 0.75


class _StubContracts:
    contracts = {}
    violations_by_category = {}

    def get_contract_stats(self):
        return {}                    # the live implementation is a stub


class _StubFramework:
    def __init__(self, blocking=True):
        self.enable_blocking = blocking
        self.contract_manager = _StubContracts()

    def get_statistics(self):
        return {"blocking_enabled": self.enable_blocking, "constraints_count": 0,
                "evaluations_performed": 0, "violations_detected": 0,
                "violation_rate": 0.0, "events_logged": 0}


@pytest.mark.asyncio
async def test_safety_gate_was_impossible_to_satisfy(monkeypatch, hm):
    """The verdict came from `CommitmentContractManager._instance` -- an
    attribute the class never defines and nothing assigns -- so the getattr
    default made it False on every run. On a critical component an
    `_initialized` key is an automatic gate, so `safety` reported CRITICAL
    permanently for a condition no reachable state could satisfy, while the
    manager was live the whole time as SafetyFramework.contract_manager."""
    from core.safety.commitment_contracts import CommitmentContractManager
    assert not hasattr(CommitmentContractManager, "_instance"), (
        "nothing defines or assigns this attribute; reading it is always None"
    )

    import core.security.safety_framework as sf
    monkeypatch.setattr(sf, "_safety_framework", _StubFramework(), raising=False)
    metrics, issues = await hm._check_safety_health()
    assert metrics["safety_contracts_initialized"] is True

    r = hm.evaluate_declared("safety", hm._declared_metrics.pop("safety"), issues)
    assert r["status"] is HealthStatus.HEALTHY
    assert r["gate_failures"] == []


@pytest.mark.asyncio
async def test_safety_measures_the_layer_that_enforces(monkeypatch, hm):
    """An absent SafetyFramework is the condition that actually means actions
    are ungoverned; that is what must gate."""
    import core.security.safety_framework as sf
    monkeypatch.setattr(sf, "_safety_framework", None, raising=False)

    metrics, issues = await hm._check_safety_health()
    r = hm.evaluate_declared("safety", hm._declared_metrics.pop("safety"), issues)

    assert metrics["safety_framework_initialized"] is False
    assert r["status"] is HealthStatus.CRITICAL
    assert r["gate_failures"] == ["safety_framework_initialized"]


@pytest.mark.asyncio
async def test_detected_but_not_blocked_is_critical(monkeypatch, hm):
    """Blocking disabled means violations are found and actions run anyway."""
    import core.security.safety_framework as sf
    monkeypatch.setattr(sf, "_safety_framework", _StubFramework(blocking=False),
                        raising=False)

    metrics, issues = await hm._check_safety_health()
    r = hm.evaluate_declared("safety", hm._declared_metrics.pop("safety"), issues)

    assert r["status"] is HealthStatus.CRITICAL
    assert "safety_blocking_enabled" in r["gate_failures"]


@pytest.mark.asyncio
async def test_vestigial_constraint_count_is_not_a_gate(monkeypatch, hm):
    """SafetyFramework.constraints is assigned [] and nothing appends to it, so
    gating on `> 0` would be permanently unsatisfiable -- the same defect as the
    contract gate, reintroduced."""
    import core.security.safety_framework as sf
    monkeypatch.setattr(sf, "_safety_framework", _StubFramework(), raising=False)

    metrics, issues = await hm._check_safety_health()
    declared = hm._declared_metrics.pop("safety")

    assert metrics["safety_constraints_loaded"] == 0
    assert "safety_constraints_loaded" not in {m.name for m in declared}


@pytest.mark.asyncio
async def test_stubbed_contract_stats_are_not_reported_as_measurements(monkeypatch, hm):
    """get_contract_stats returns {}. Reporting its zeros would claim 'measured:
    no violations' about a subsystem that measured nothing."""
    import core.security.safety_framework as sf
    monkeypatch.setattr(sf, "_safety_framework", _StubFramework(), raising=False)

    metrics, issues = await hm._check_safety_health()
    hm._declared_metrics.pop("safety", None)

    assert metrics["safety_contract_stats_implemented"] is False
    assert metrics["safety_contract_violation_rate"] is None
    assert "safety_contract_violation_rate" in metrics["_not_applicable"]


def test_topology_matches_services_by_port_not_name():
    """The scanner reports one `postgresql`; the topology models the two logical
    databases sharing that instance as postgresql-torinai/-agentso. Neither name
    could ever match, so a running Postgres was recorded as a CRITICAL service
    down -- while every database health check was passing against it."""
    from core.system.infrastructure_topology import InfrastructureTopology, ServiceTier
    from core.system.environment_state import ServiceInfo, ServiceStatus

    class _Env:
        running_services = {
            "postgresql": ServiceInfo(name="postgresql", port=5432,
                                      status=ServiceStatus.RUNNING),
        }

    topo = InfrastructureTopology()
    topo.update_from_environment(_Env())

    assert topo.services["postgresql-torinai"].is_running is True
    assert topo.services["postgresql-torinai"].health_score > 0.0
    crit_down = [k for k, n in topo.services.items()
                 if n.tier is ServiceTier.CRITICAL and not n.is_running]
    assert "postgresql-torinai" not in crit_down


def test_genuinely_absent_service_still_reads_down():
    """Port matching must not turn every node into a running one."""
    from core.system.infrastructure_topology import InfrastructureTopology

    class _Env:
        running_services = {}

    topo = InfrastructureTopology()
    topo.update_from_environment(_Env())
    assert topo.services["postgresql-torinai"].is_running is False
    assert topo.get_health_summary()["critical_services_down"] > 0


@pytest.mark.asyncio
async def test_system_awareness_probes_before_it_reports(hm):
    """Both EnvironmentState and InfrastructureTopology were constructed and read
    immediately, so every number came from their constructors -- topology starts
    every node at is_running=False ('assume down until proven up') and the
    proving never happened. It reported '4 critical service(s) down' on every
    run regardless of what was actually running."""
    import inspect
    src = inspect.getsource(hm._check_system_awareness_health)
    assert "await env_state.refresh()" in src, "the environment must be scanned"
    assert "update_from_environment" in src, "topology must receive the readings"
    assert "InfrastructureTopology().get_health_summary()" not in src, (
        "reading a freshly constructed topology reports its defaults, not the system"
    )
