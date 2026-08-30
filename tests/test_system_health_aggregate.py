"""Oracles for the aggregate that gates ASI self-improvement.

`update_model_weights` refuses to run unless `SystemImprovementState` says the
system is healthy: it blocks below an overall score of 80, and blocks again on
any component in a critical state. Both readings came out of
`ImprovementMonitor.get_system_state`, and both were wrong -- in opposite
directions.

The score averaged every row in `component_health`, including six whose names
are metric keys (`overall_status`, `active_alerts`, ...) written before
intrinsic_motivation was corrected to the 0-100 scale, so they hold 0.8-1.0 in
a 0-100 column. Nothing rewrites them -- the upsert is keyed on component_name
and no writer emits those names any more -- so they permanently dragged 29 real
measurements from 91.5 to 76.0 and held the gate shut on residue.

The critical count asked for the string `critical`. The enum behind every row
in the table is `health_monitor.HealthStatus`, which spells that state
`unhealthy`. So the check read 0 forever and never fired.

Each test passes on the old code only if the defect is still present.
"""
import inspect
import re

import pytest

from core.learning.improvement_monitor import ImprovementMonitor


class _FakeDB:
    """Answers whatever `get_system_state` asks, and remembers the questions."""

    def __init__(self, health_rows, avg, detail_rows=()):
        self.health_rows = health_rows
        self.avg = avg
        self.detail_rows = list(detail_rows)
        self.queries = []

    async def execute_query(self, query, params=None, **kwargs):
        self.queries.append(query)
        if "improvement_metrics" in query:
            return {"total_metrics": 0, "degradations": 0}
        if "COUNT(*) as count" in query:
            return self.health_rows
        if "avg_health" in query:
            return {"avg_health": self.avg}
        return self.detail_rows


def _monitor(db):
    monitor = ImprovementMonitor.__new__(ImprovementMonitor)
    monitor.db = db
    monitor.metrics = {}
    monitor.component_metrics = {}
    return monitor


@pytest.mark.asyncio
async def test_unhealthy_counts_as_impaired_but_is_not_called_critical():
    """The production reading: learning 45.1, security 50.0, agents 56.7, all
    written as `unhealthy` -- and originally reported as zero of everything, so
    the gate that exists to catch exactly this could never close.

    The first fix counted `unhealthy` as CRITICAL, which closed the gate but
    made the field lie: the ASI gate then refused with "components in CRITICAL
    state" about components that were running, merely impaired. Both properties
    are needed and they are different claims, so both are counted -- under the
    name that is true of each.
    """
    db = _FakeDB(
        health_rows=[{"status": "healthy", "count": 65},
                     {"status": "degraded", "count": 8},
                     {"status": "unhealthy", "count": 3}],
        avg=91.5,
    )
    state = await _monitor(db).get_system_state()

    assert state.critical_components == 0, (
        "`unhealthy` means running impaired; calling it critical makes every "
        "gate message about it false"
    )
    assert state.degraded_components == 11, (
        "degraded + unhealthy are both impaired and must not be lost"
    )
    assert state.impaired_components == 11, (
        "the gate needs one number for 'not healthy', and it must not be "
        "spelled by overloading `critical`"
    )
    assert state.healthy_components == 65
    assert state.total_components == 76


@pytest.mark.asyncio
async def test_offline_also_counts_as_critical():
    db = _FakeDB(health_rows=[{"status": "offline", "count": 2}], avg=91.5)
    state = await _monitor(db).get_system_state()
    assert state.critical_components == 2


@pytest.mark.asyncio
async def test_this_modules_own_spelling_still_counts():
    """Widening the vocabulary must not drop the word it already accepted."""
    db = _FakeDB(health_rows=[{"status": "critical", "count": 1}], avg=91.5)
    state = await _monitor(db).get_system_state()
    assert state.critical_components == 1


@pytest.mark.asyncio
async def test_unmeasured_health_is_none_not_a_passing_score():
    """AVG over no measured row is NULL. Substituting a number there opens the
    gate on no evidence; the deployment gate turns None into a refusal."""
    db = _FakeDB(health_rows=[], avg=None)
    state = await _monitor(db).get_system_state()
    assert state.overall_health_score is None


@pytest.mark.asyncio
async def test_zero_is_preserved_rather_than_read_as_absent():
    """Every component critical and nothing measured are opposite states; a
    falsy check made both read as perfect health."""
    db = _FakeDB(health_rows=[], avg=0.0)
    state = await _monitor(db).get_system_state()
    assert state.overall_health_score == 0.0


@pytest.mark.asyncio
async def test_every_component_health_read_is_constrained_to_the_registry():
    """A component is something DECLARED, not anything that once wrote a row.

    unified.components is the authority -- `_get_all_components` already joins
    to it for this reason. Applying that authority at target selection but not
    at the aggregate is what let six metric-key rows decide whether the
    substrate was allowed to improve itself.
    """
    db = _FakeDB(health_rows=[], avg=91.5)
    await _monitor(db).get_system_state()

    reads = [q for q in db.queries if "component_health" in q]
    assert reads, "get_system_state issued no read against component_health"
    for query in reads:
        assert "unified.components" in query, (
            f"unconstrained read -- any row in component_health counts as a "
            f"component:\n{query}"
        )


def test_the_registry_join_is_not_left_or_outer():
    """A LEFT JOIN would re-admit every unregistered row it exists to exclude."""
    source = inspect.getsource(ImprovementMonitor.get_system_state)
    for join in re.findall(r"(\w+)\s+JOIN\s+unified\.components", source, re.I):
        assert join.upper() not in {"LEFT", "RIGHT", "FULL", "OUTER"}, (
            f"{join} JOIN re-admits unregistered rows"
        )
