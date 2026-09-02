#!/usr/bin/env python3
"""
Abstraction pipeline connectivity tests
=======================================
Enforces that hierarchical abstraction is *connected*, not merely importable.

A component is only as connected as the loudest thing that breaks when it
isn't. These tests are that loud thing. They assert observable state changes
and downstream consumption rather than that a call returned without raising --
the pipeline previously ran to completion and returned {'schemas_formed': 0}
forever, and nothing noticed.

Also pins the stall incident: cross-domain enrichment is optional, so a model
that is present but slow must not be able to prevent a schema from existing.
The original code only looked healthy when the model was *unavailable* and
therefore failed fast.
"""

import asyncio
import sys
import time
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.reasoning.bayesian_uncertainty import BayesianUncertaintySystem  # noqa: E402
from core.reasoning.hierarchical_abstraction import AbstractionPipeline  # noqa: E402


def make_memory(index, now):
    """One memory in a repeating, cross-session failure pattern."""
    return SimpleNamespace(
        memory_id=f"m{index}",
        content=f"Deploy failed: config file missing on host{index % 9}",
        memory_type="ops",
        session_id=f"s{index % 12}",
        importance_score=0.85,
        similarity_score=0.0,
        tags=["deploy", "config"],
        emotional_context={},
        reasoning_strategy="",
        embeddings=None,
        embedding=None,
        metadata={"domain": "ops", "outcome": "config_missing_failure"},
        created_at=datetime.fromtimestamp(now - index * 5400),
    )


class FakeMemoryAgent:
    """Returns MemoryItem-shaped objects, matching the real agent's contract."""

    def __init__(self, items):
        self.items = list(items)
        self.updates = []

    async def get_recent_memories(self, limit=10, **kwargs):
        return self.items[:limit]

    async def search_memories(self, *args, **kwargs):
        return self.items

    async def get_memory(self, memory_id, **kwargs):
        return next((m for m in self.items if m.memory_id == memory_id), None)

    async def update_memory(self, memory_id, *args, **kwargs):
        self.updates.append(memory_id)
        return True


def build_pipeline(count=30):
    now = time.time()
    items = [make_memory(i, now) for i in range(count)]
    agent = FakeMemoryAgent(items)
    pipeline = AbstractionPipeline(
        memory_agent=agent,
        uncertainty_system=BayesianUncertaintySystem(),
    )
    return pipeline, agent, items


def raw_dicts(items):
    return [
        {
            "memory_id": m.memory_id,
            "content": m.content,
            "memory_type": m.memory_type,
            "session_id": m.session_id,
            "importance_score": m.importance_score,
            "tags": m.tags,
            "created_at": m.created_at.timestamp(),
            "metadata": m.metadata,
        }
        for m in items
    ]


# ------------------------------------------------ criterion 2: observable effect


def test_processing_memories_forms_a_schema():
    """A repeating cross-session pattern must produce a schema.

    Before this suite the pipeline could not form one at all: should_abstract()
    compared an abstraction_score that process_memories never assigned, so no
    pattern of any strength passed the gate.
    """
    pipeline, _, items = build_pipeline()

    before = len(pipeline.active_schemas)
    result = asyncio.run(pipeline.process_memories(raw_dicts(items)))
    after = len(pipeline.active_schemas)

    assert "error" not in result, f"pipeline errored: {result.get('error')}"
    assert result["schemas_formed"] >= 1
    assert after > before, "no observable state change: active_schemas unchanged"


def test_dict_input_is_accepted_as_documented():
    """process_memories is typed for dicts; internals read attributes.

    Passing the documented type used to raise AttributeError, which was caught
    and reported as zero schemas -- identical to a clean run finding nothing.
    """
    pipeline, _, items = build_pipeline()

    result = asyncio.run(pipeline.process_memories(raw_dicts(items)))

    assert "error" not in result


def test_failure_is_distinguishable_from_finding_nothing():
    """A crashed run must not look like an idle one."""
    pipeline, _, _ = build_pipeline()

    result = asyncio.run(pipeline.process_memories([{"bad": object()}]))

    assert result["schemas_formed"] == 0
    # Either it cleanly found nothing, or it reports why. It must never crash
    # and present the crash as an empty result.
    assert "error" in result or result["patterns_formed"] == 0


# -------------------------------------------- criterion 3: downstream consumption


def test_schema_formation_creates_a_belief_and_a_concept():
    """The schema must be consumed downstream, not merely stored.

    Belief creation, abstraction effects and hierarchy insertion all sat behind
    a cross-domain enrichment call that never returned, so none of them ran.
    """
    pipeline, _, items = build_pipeline()

    beliefs_before = len(pipeline.beliefs.beliefs)
    nodes_before = len(pipeline.concept_hierarchy.nodes)

    asyncio.run(pipeline.process_memories(raw_dicts(items)))

    assert len(pipeline.beliefs.beliefs) > beliefs_before, "no Bayesian belief created"
    assert len(pipeline.concept_hierarchy.nodes) > nodes_before, "not added to hierarchy"


def test_belief_can_be_created_with_initial_evidence():
    """create_belief() updated before registering, so evidence always raised."""
    system = BayesianUncertaintySystem()

    belief = system.create_belief(
        claim="schema holds",
        domain="ops",
        prior=0.6,
        evidence={"strength": 0.8, "reliability": 0.9},
    )

    assert belief.belief_id in system.beliefs
    assert belief.update_count >= 1


# ------------------------------- the incident: optional work cannot block validity


def test_enrichment_failure_does_not_invalidate_a_schema():
    """Enrichment can improve a schema; it cannot decide whether it exists."""
    pipeline, _, items = build_pipeline()

    async def exploding_enrichment(schema):
        raise RuntimeError("enrichment backend down")

    pipeline._enrich_schema_with_cross_domain_mappings = exploding_enrichment

    result = asyncio.run(pipeline.process_memories(raw_dicts(items)))

    assert result["schemas_formed"] >= 1
    assert len(pipeline.beliefs.beliefs) >= 1, "belief creation must precede enrichment"


def test_a_slow_model_cannot_stall_schema_formation():
    """The stall regression.

    Cross-domain enrichment reached the Universal Domain Master, which issued
    one model inference per target domain, sequentially, on a single-slot
    server -- roughly half an hour before the schema could finish applying.
    The code looked healthy only because the model was usually unavailable and
    therefore failed instantly.

    Here the model is *available and deliberately slow*, which is the condition
    that used to stall the system.
    """
    pipeline, _, items = build_pipeline()

    async def glacial_enrichment(schema):
        await asyncio.sleep(300)

    pipeline._enrich_schema_with_cross_domain_mappings = glacial_enrichment

    async def run_bounded():
        # Schema formation must finish well inside the enrichment's runtime.
        return await asyncio.wait_for(
            pipeline.process_memories(raw_dicts(items)), timeout=45
        )

    started = time.time()
    try:
        asyncio.run(run_bounded())
    except asyncio.TimeoutError:
        pytest.fail(
            "slow enrichment stalled schema formation: optional work is on the "
            "critical path again"
        )
    elapsed = time.time() - started

    # The schema, its belief and its hierarchy node must all exist despite
    # enrichment never having completed.
    assert len(pipeline.active_schemas) >= 1
    assert len(pipeline.beliefs.beliefs) >= 1
    assert len(pipeline.concept_hierarchy.nodes) >= 1
    assert elapsed < 45


def test_model_enrichment_is_bounded_and_capped():
    """Escalation must be time-bounded and must not enumerate every domain."""
    pipeline, _, _ = build_pipeline()

    assert pipeline.ENRICHMENT_MODEL_TIMEOUT <= 60
    assert pipeline.ENRICHMENT_MAX_DOMAINS <= 5
    assert 0.0 < pipeline.ENRICHMENT_MIN_VALUE <= 1.0


def test_deterministic_enrichment_is_preferred_over_the_model():
    """Analogy discovery is primary; the model is escalation, not fallback."""
    pipeline, _, _ = build_pipeline()

    escalated = {"called": False}

    async def record_escalation(schema):
        escalated["called"] = True

    async def deterministic_hit(schema):
        return [{"target_domain": "biology", "source_concept": "config",
                 "target_concept": "cell", "similarity": 0.7,
                 "strategy": "analogical", "source": "analogy_discovery"}]

    pipeline._find_analogical_mappings = deterministic_hit
    pipeline._escalate_enrichment_to_model = record_escalation

    schema = SimpleNamespace(
        schema_id="s1", condition={"domain": "ops"}, outcome="failure",
        metadata={"domain": "ops"}, context_diversity_score=1.0,
        stress_test_score=0.9, calculate_probability=lambda: 0.9,
    )

    asyncio.run(pipeline._enrich_schema_with_cross_domain_mappings(schema))

    assert schema.metadata["enrichment_source"] == "analogy_discovery"
    assert escalated["called"] is False, "model was consulted despite a deterministic hit"


def test_low_value_schema_does_not_escalate_to_the_model():
    """A deterministic miss legitimately means 'no mapping known'."""
    pipeline, _, _ = build_pipeline()

    escalated = {"called": False}

    async def no_mappings(schema):
        return []

    async def record_escalation(schema):
        escalated["called"] = True

    pipeline._find_analogical_mappings = no_mappings
    pipeline._escalate_enrichment_to_model = record_escalation

    schema = SimpleNamespace(
        schema_id="s2", condition={"domain": "ops"}, outcome="failure",
        metadata={"domain": "ops"}, context_diversity_score=1.0,
        stress_test_score=0.1, calculate_probability=lambda: 0.2,
    )

    asyncio.run(pipeline._enrich_schema_with_cross_domain_mappings(schema))

    assert escalated["called"] is False
    assert schema.metadata["enrichment_source"] == "none"


# ------------------------------ detached must mean non-blocking, not unobservable


def test_enrichment_tasks_are_registered_and_drainable():
    """Detached work must remain observable and cancellable at shutdown."""
    pipeline, _, _ = build_pipeline()

    started = asyncio.Event()

    async def slow_enrichment(schema):
        started.set()
        await asyncio.sleep(300)

    pipeline._enrich_schema_with_cross_domain_mappings = slow_enrichment

    schema = SimpleNamespace(schema_id="s_registry", metadata={},
                             context_diversity_score=1.0)

    async def scenario():
        pipeline._schedule_enrichment(schema)
        await started.wait()

        # Observable while in flight, keyed by schema_id.
        assert "s_registry" in pipeline.enrichment_tasks

        # Drains rather than orphaning.
        outcome = await pipeline.drain_enrichment(timeout=0.2)
        assert outcome["cancelled"] == 1
        assert not pipeline.enrichment_tasks

    asyncio.run(scenario())


def test_enrichment_is_not_scheduled_twice_for_one_schema():
    pipeline, _, _ = build_pipeline()

    async def slow_enrichment(schema):
        await asyncio.sleep(300)

    pipeline._enrich_schema_with_cross_domain_mappings = slow_enrichment
    schema = SimpleNamespace(schema_id="s_dup", metadata={}, context_diversity_score=1.0)

    async def scenario():
        pipeline._schedule_enrichment(schema)
        pipeline._schedule_enrichment(schema)
        assert len(pipeline.enrichment_tasks) == 1
        await pipeline.drain_enrichment(timeout=0.1)

    asyncio.run(scenario())


def test_significance_boost_is_idempotent():
    """The boost is multiplicative; a retried enrichment must not compound it."""
    pipeline, _, _ = build_pipeline()
    schema = SimpleNamespace(schema_id="s_idem", metadata={}, context_diversity_score=1.0)

    pipeline._mark_cross_domain_significance(schema)
    once = schema.context_diversity_score

    pipeline._mark_cross_domain_significance(schema)
    pipeline._mark_cross_domain_significance(schema)

    assert schema.context_diversity_score == once


# ------------------------------------- criterion 1: admission-controlled invocation


class _StubBridge:
    """Stands in for the reasoning authority: owns the abstraction pipeline and
    exposes the bridge API the memory agent now asks (abstract_over_memories)."""

    def __init__(self, pipeline):
        self.abstraction = pipeline

    async def abstract_over_memories(self, batch):
        if self.abstraction is None:
            raise RuntimeError("no abstraction subsystem")
        return await self.abstraction.process_memories(batch)


class _StubAgent:
    """Memory agent exposing only what the admission gate needs. Abstraction is
    the reasoning authority's now, so the agent holds a (stub) bridge and ASKS
    it — mirroring the real memory_agent._reasoning_authority()."""

    ABSTRACTION_MIN_NEW_MEMORIES = 15
    ABSTRACTION_COOLDOWN_S = 900.0
    ABSTRACTION_BATCH_SIZE = 200

    def __init__(self, items, pipeline):
        self._items = items
        self._bridge = _StubBridge(pipeline)
        self.abstraction_state = {
            'last_abstraction_run': None, 'last_processed_created_at': None,
            'memories_since_abstraction': 0, 'abstraction_backlog': 0,
            'schemas_formed_last_run': 0, 'runs': 0, 'last_skip_reason': None,
        }
        self._abstraction_running = False

    def _reasoning_authority(self):
        return self._bridge

    async def get_recent_memories(self, limit=10, **kwargs):
        return self._items[:limit]

    form_abstractions_if_due = None  # bound below


def _make_agent(count=30):
    from core.agents.memory_agent import MemoryAgent
    pipeline, _, items = build_pipeline(count)
    agent = _StubAgent(items, pipeline)
    agent.form_abstractions_if_due = MemoryAgent.form_abstractions_if_due.__get__(agent)
    return agent


def test_abstraction_runs_when_there_is_new_work():
    agent = _make_agent()
    report = asyncio.run(agent.form_abstractions_if_due())

    assert report["ran"] is True, report
    assert report["schemas_formed"] >= 1
    assert agent.abstraction_state["last_processed_created_at"] is not None


def test_cooldown_prevents_immediate_rerun():
    agent = _make_agent()
    asyncio.run(agent.form_abstractions_if_due())

    report = asyncio.run(agent.form_abstractions_if_due())
    assert report["ran"] is False
    assert report["reason"] == "cooldown"


def test_watermark_prevents_reclustering_the_same_memories():
    """Without this, every idle cycle re-derives the schemas it already has."""
    from datetime import datetime, timedelta

    agent = _make_agent()
    asyncio.run(agent.form_abstractions_if_due())

    # Skip the cooldown; there is still no new material.
    agent.abstraction_state["last_abstraction_run"] = datetime.now() - timedelta(seconds=10_000)

    report = asyncio.run(agent.form_abstractions_if_due())
    assert report["ran"] is False
    assert report["reason"] == "insufficient_new_memories"
    assert report["new_memories"] == 0


def test_concurrent_abstraction_is_refused():
    agent = _make_agent()
    agent._abstraction_running = True

    report = asyncio.run(agent.form_abstractions_if_due(force=True))
    assert report["ran"] is False
    assert report["reason"] == "already_running"


def test_declining_records_a_reason():
    """A tier that never runs must be visible, not silently idle. With the
    reasoning authority owning abstraction, "no owner" is the decline reason."""
    agent = _make_agent()
    agent._bridge.abstraction = None  # authority has no abstraction subsystem

    report = asyncio.run(agent.form_abstractions_if_due())
    assert report["ran"] is False
    assert agent.abstraction_state["last_skip_reason"] == "no_reasoning_authority"


def test_abstraction_is_event_triggered_not_polled():
    """Criterion 1 (updated): abstraction is REASONING owned by the reasoning
    authority and is driven by an EVENT — episodic-memory accumulation — not by
    a scheduled poll tier. So it must NOT be a registered idle tier, and the
    memory store's episodic path must schedule it via note_episodic_stored."""
    import inspect
    from core.agents.autonomous.autonomous_coordinator import AutonomousCoordinator
    from core.agents.memory_agent import MemoryAgent

    source = inspect.getsource(AutonomousCoordinator._register_idle_subsystems)
    assert "idle_abstraction" not in source, "abstraction should no longer be a poll tier"

    # The event trigger exists and the store path invokes it.
    assert hasattr(MemoryAgent, "note_episodic_stored")
    assert hasattr(MemoryAgent, "_run_abstraction_then_reflect")
    store_src = inspect.getsource(MemoryAgent.store_memory)
    assert "note_episodic_stored" in store_src, "episodic store does not trigger abstraction"
    # The memory agent asks the authority rather than owning a pipeline.
    gate_src = inspect.getsource(MemoryAgent.form_abstractions_if_due)
    assert "_reasoning_authority" in gate_src and "abstract_over_memories" in gate_src


# ----------------------- induced knowledge must enter the belief constraint graph


def _linked_concept(pipeline, beliefs, condition, outcome, probability):
    """Add a schema-derived concept through the real linking path."""
    from core.reasoning.hierarchical_abstraction import AbstractionLevel, ConceptNode

    belief = beliefs.create_belief(
        f"Pattern: {condition} -> {outcome}", "induced_schema", prior=probability
    )
    schema = SimpleNamespace(
        condition=condition, outcome=outcome, probability=probability,
        schema_id=f"s_{len(beliefs.beliefs)}", belief_id=belief.belief_id,
    )
    concept = ConceptNode(
        concept_id=f"c_{len(pipeline.concept_hierarchy.nodes)}",
        level=AbstractionLevel.SCHEMA,
        content=f"{condition} -> {outcome}",
        probability=probability,
        belief_id=belief.belief_id,
        schema_id=schema.schema_id,
    )
    pipeline._link_concept_to_existing(concept, schema)
    pipeline.concept_hierarchy.add_concept(concept)
    pipeline._mirror_relations_to_beliefs(concept)
    return concept, belief


def _relation_fixture():
    from core.reasoning.bayesian_uncertainty import BayesianUncertaintySystem
    from core.reasoning.hierarchical_abstraction import AbstractionPipeline

    class _Agent:
        async def get_recent_memories(self, limit=10, **kwargs):
            return []

        async def get_memory(self, memory_id, **kwargs):
            return None

        async def update_memory(self, memory_id, *args, **kwargs):
            return True

    beliefs = BayesianUncertaintySystem()
    pipeline = AbstractionPipeline(memory_agent=_Agent(), uncertainty_system=beliefs)
    return pipeline, beliefs


def test_more_specific_schema_implies_the_general_one():
    pipeline, beliefs = _relation_fixture()

    general, _ = _linked_concept(pipeline, beliefs, {"tags": "deploy"}, {"result": "failure"}, 0.9)
    specific, _ = _linked_concept(
        pipeline, beliefs, {"tags": "deploy", "host": "web01"}, {"result": "failure"}, 0.85
    )

    assert general.concept_id in specific.implies


def test_same_trigger_with_different_outcome_contradicts():
    pipeline, beliefs = _relation_fixture()

    first, _ = _linked_concept(pipeline, beliefs, {"tags": "deploy"}, {"result": "failure"}, 0.9)
    second, _ = _linked_concept(pipeline, beliefs, {"tags": "deploy"}, {"result": "success"}, 0.8)

    assert first.concept_id in second.contradicts
    assert second.concept_id in first.contradicts, "contradiction must be reciprocal"


def test_concept_edges_are_mirrored_onto_the_belief_graph():
    """Relationships were only ever created from LLM output, so schema-derived
    beliefs sat isolated and constraint propagation never reached them."""
    pipeline, beliefs = _relation_fixture()

    _linked_concept(pipeline, beliefs, {"tags": "deploy"}, {"result": "failure"}, 0.9)
    _linked_concept(pipeline, beliefs, {"tags": "deploy"}, {"result": "success"}, 0.8)

    assert len(getattr(beliefs, "relationships", {}) or {}) >= 1


def test_contradicting_induced_beliefs_propagate():
    """The payoff: evidence on one induced belief must move its contradiction."""
    pipeline, beliefs = _relation_fixture()

    _, general = _linked_concept(pipeline, beliefs, {"tags": "deploy"}, {"result": "failure"}, 0.9)
    _, rival = _linked_concept(pipeline, beliefs, {"tags": "deploy"}, {"result": "success"}, 0.8)

    before = beliefs.beliefs[general.belief_id].posterior_probability
    beliefs.update_belief(rival.belief_id, {"strength": 0.9, "reliability": 0.9},
                          evidence_supports=True)
    after = beliefs.beliefs[general.belief_id].posterior_probability

    assert abs(after - before) > 1e-9, "no propagation: induced beliefs are isolated"
    assert after < before, "supporting a contradiction must lower the rival"


def test_consistency_checking_can_now_detect_violations():
    """Both consistency checkers existed and always returned nothing, because
    every concept was inserted with no edges."""
    pipeline, beliefs = _relation_fixture()

    _linked_concept(pipeline, beliefs, {"tags": "deploy"}, {"result": "failure"}, 0.95)
    _linked_concept(pipeline, beliefs, {"tags": "deploy"}, {"result": "success"}, 0.9)

    assert len(pipeline.concept_hierarchy.check_consistency()) >= 1
    assert len(beliefs.check_consistency().get("contradiction_violations", [])) >= 1


def test_unrelated_schemas_are_not_linked():
    """Linking must be driven by the schemas, not applied indiscriminately."""
    pipeline, beliefs = _relation_fixture()

    first, _ = _linked_concept(pipeline, beliefs, {"tags": "deploy"}, {"result": "failure"}, 0.9)
    second, _ = _linked_concept(pipeline, beliefs, {"tags": "backup"}, {"result": "slow"}, 0.8)

    assert first.concept_id not in second.implies
    assert first.concept_id not in second.contradicts


# ------------------------------------ persistence failures must never be silent


def test_dropped_belief_writes_are_counted_not_swallowed():
    """A write discarded because the DB is uninitialized used to be
    indistinguishable from a successful one, so lost epistemic state looked
    like persisted state."""
    from types import SimpleNamespace

    from core.reasoning.bayesian_uncertainty import BayesianUncertaintySystem

    system = BayesianUncertaintySystem()
    # Force the drop condition rather than relying on the ambient database being
    # uninitialized: anything earlier in the same process that initializes it
    # (abduction registering a hypothesis, for one) silently turned this test
    # into a no-op that still passed.
    system.unified_db = SimpleNamespace(initialized=False)

    async def scenario():
        for i in range(3):
            system.create_belief(f"claim {i}", "test", prior=0.5)
        await asyncio.sleep(0.3)

    asyncio.run(scenario())
    stats = system.get_statistics()

    assert stats["persistence_drops"] >= 1
    assert stats["persistence_healthy"] is False


def test_concept_persistence_uses_a_stable_natural_key():
    """Concept has no concept_id field; reading one raised before the query ran,
    so every concept write failed silently."""
    import inspect

    from core.reasoning.analogy_discovery import AnalogyDiscovery

    source = inspect.getsource(AnalogyDiscovery._persist_concept)

    assert "concept.concept_id" not in source, "reads a field Concept does not have"
    assert "unified.concepts" in source, "must write the declared table, not a duplicate"
    assert "_json.dumps" in source, "JSONB columns require JSON, not str() reprs"


def test_analogy_persistence_targets_the_declared_table():
    """unified.analogies matches the Analogy dataclass exactly; the old INSERT
    named columns present in neither."""
    import inspect

    from core.reasoning.analogy_discovery import AnalogyDiscovery

    source = inspect.getsource(AnalogyDiscovery._persist_analogy)

    assert "unified.analogies" in source
    for absent in ("source_concept_id", "target_concept_id", "analogy.strength"):
        assert absent not in source, f"{absent} exists on neither table nor dataclass"


def test_module_does_not_recreate_tables_owned_by_the_schema_file():
    """unified.concepts/analogies are declared in postgres_schemas.sql.
    Creating unqualified copies put a divergent set in the default schema."""
    from core.reasoning.analogy_discovery import AnalogyDiscovery

    ddl = " ".join(AnalogyDiscovery._SCHEMA_STATEMENTS)

    assert "CREATE TABLE IF NOT EXISTS concepts" not in ddl
    assert "CREATE TABLE IF NOT EXISTS analogies" not in ddl
    for statement in AnalogyDiscovery._SCHEMA_STATEMENTS:
        assert "unified." in statement, "tables must be schema-qualified"


def test_analogy_resolves_its_database_without_injection():
    """The old resolver searched for core.database.postgresql_manager and
    database.postgresql_manager -- neither exists -- so self.db was always None
    and every write was skipped, while the in-memory base still populated and
    made the system look healthy. A test that injects the DB hides this."""
    import inspect

    from core.reasoning.analogy_discovery import AnalogyDiscovery

    source = inspect.getsource(AnalogyDiscovery._resolve_database)

    assert "get_unified_database" in source
    assert not hasattr(AnalogyDiscovery, "_resolve_postgresql_manager"), (
        "the resolver that searched for nonexistent modules must be gone"
    )
    assert inspect.iscoroutinefunction(AnalogyDiscovery._resolve_database), (
        "resolution must be async; the sync attempt could never obtain the DB"
    )


def test_initialize_restores_concepts_and_seeds_nothing():
    """The concept base is learned, never seeded.

    This asserted only that restore ran BEFORE seeding, which left the seeding
    itself unchallenged: _load_sample_data wrote twelve fixture concepts
    (atom, molecule, cell, market, ...) into unified.concepts on every
    initialize(). Twelve of the store's thirteen rows were those fixtures, so
    every analogy and every domain mapping computed downstream was computed over
    demonstration data. The seeder is gone; this now guards its absence.
    """
    import inspect

    from core.reasoning.analogy_discovery import AnalogyDiscovery

    source = inspect.getsource(AnalogyDiscovery.initialize)
    assert "_load_concepts_from_store" in source, "learned concepts must be restored"

    assert not hasattr(AnalogyDiscovery, "_load_sample_data"), (
        "AnalogyDiscovery must not carry a sample-data seeder; fixture concepts "
        "in the production store are indistinguishable from learned ones"
    )
    assert "_load_sample_data" not in source

    # No method may call the concept writer with literal concept names. Checked
    # against _add_concept call sites rather than the whole module, so the
    # class docstring's illustrative "atom is to molecule as cell is to
    # organism" stays documentation rather than tripping the guard.
    for name, member in inspect.getmembers(AnalogyDiscovery, inspect.isfunction):
        body = inspect.getsource(member)
        assert "_add_concept(" not in body or name == "_add_concept", (
            f"{name} calls _add_concept; concepts must come from a learning "
            f"path, not from literals in the module"
        )


def test_concept_attribute_values_are_not_discarded():
    """_add_concept took Dict[str, str] and kept only the keys, so
    'structure=rotor + blades' and 'structure=nucleus + electrons' became the
    same attribute -- the values are what make an analogy structural."""
    import inspect

    from core.reasoning.analogy_discovery import AnalogyDiscovery, Concept

    assert "attribute_values" in {f.name for f in __import__("dataclasses").fields(Concept)}

    source = inspect.getsource(AnalogyDiscovery._add_concept)
    assert "attribute_values=dict(attributes)" in source
