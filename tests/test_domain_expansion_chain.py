#!/usr/bin/env python3
"""Oracles for the task-outcome -> domain-knowledge chain (Priority 4).

Every component of this chain existed and none of them were joined:

  producer  AutonomousCoordinator._store_task_outcome_meta_memory writes a
            TaskOutcomeRecord as a META memory tagged "task_outcome", with the
            domain from _infer_domain_from_task
  bridge    DomainRegistry.resolve_domain_reference turns that CATEGORY
            ("scientific") into the populated FIELDS beneath it
  consumer  UnifiedLearningSystem.learn_with_domain_context, the only method
            that puts a domain onto learn_from_example
  tier      _idle_domain_expansion_work, documented at TORINAI_REFERENCE.md:3114
            and never registered

Four defects found while joining them are locked here. Each returned a
plausible value while doing nothing, which is why none of them surfaced:

  1. `metadata = metadata || $1::jsonb` on a NULL column yields NULL. The row
     updated, so rows_affected was 1 and update_memory returned True while
     storing nothing.
  2. learn_with_domain_context returned learn_from_example's CREDIT flag as its
     own `success`, so an outcome that was learned from -- cross-domain transfer
     included -- came back success=False with no error and no error_class.
  3. The structured record lives in thinking_state["raw_event"]; `content` is a
     rendered narrative. Reading `content` yields prose and every field of the
     TaskOutcomeRecord reads as absent.
  4. 15 of 18 populated fields were absent from _FIELD_TO_DOMAIN_TYPE and fell
     to the ABSTRACT fallback, so the producer's categories resolved past the
     concepts they should have found.

test_chain_end_to_end is the oracle that matters: the five component tests can
all pass while the chain remains broken at a joint none of them crosses.
"""

import asyncio
from pathlib import Path

import pytest

TAG = "task_outcome"
MARK = "domain_expanded_at"


def _load_env():
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[1] / ".env.production", override=True)


async def _storage():
    from core.agents.memory_agent import get_memory_agent
    agent = await get_memory_agent()
    # get_memory_agent() returns an UNINITIALIZED agent by its own docstring;
    # postgres_storage is None until initialize() runs.
    await agent.initialize()
    assert agent.postgres_storage is not None, "memory agent exposes no storage"
    return agent.postgres_storage


async def _coordinator():
    """A coordinator carrying only what this chain needs, wired to the real systems."""
    from core.agents.autonomous.autonomous_coordinator import AutonomousCoordinator
    from core.agents.memory_agent import get_memory_agent
    from core.learning.unified_learning_system import get_learning_authority

    coord = AutonomousCoordinator.__new__(AutonomousCoordinator)
    coord.config = {}
    coord.memory = await get_memory_agent()
    await coord.memory.initialize()
    # ONE learning attribute now: `coord.learning` (the coordinator's methods
    # read self.learning; `unified_learning` was a second name for the same
    # singleton and is gone). get_learning_authority() == get_unified_learning_system().
    coord.learning = get_learning_authority()
    await coord.learning.start()
    return coord


def _task(description, task_type="analysis", task_id="oracle_task"):
    from types import SimpleNamespace
    return SimpleNamespace(
        id=task_id,
        description=description,
        type=SimpleNamespace(value=task_type),
        source=SimpleNamespace(value="autonomous"),
    )


# ---------------------------------------------------------------- component 1

@pytest.mark.asyncio
async def test_metadata_merge_is_a_merge_and_survives_a_null_column():
    """Both halves of `COALESCE(metadata,'{}') || $1`: NULL-safe AND merging."""
    _load_env()
    from core.database import get_database_manager
    from core.memory.utils.interfaces import MemoryItem, MemoryType

    storage = await _storage()
    db = get_database_manager()
    mid = "test_merge_semantics"

    await storage.store_memory(MemoryItem(
        memory_id=mid, memory_type=MemoryType.META,
        content={"event": "test", "purpose": "metadata merge oracle"},
        tags={"test_merge_oracle"}))

    async def metadata():
        rows = await db.execute_query(
            "SELECT metadata FROM memory_hot.memory_hot WHERE memory_id = $1",
            (mid,), fetch_all=True)
        import json
        raw = rows[0]["metadata"]
        return json.loads(raw) if isinstance(raw, str) else raw

    try:
        # (a) NULL column. `NULL || jsonb` is NULL, and UPDATE still reports one
        # row affected -- so the write returns True and stores nothing.
        await db.execute_query(
            "UPDATE memory_hot.memory_hot SET metadata = NULL WHERE memory_id = $1",
            (mid,), commit=True)
        assert await storage.update_memory(
            mid, {"metadata": {"first": "a"}, "metadata.merge": True}) is True
        stored = await metadata()
        assert isinstance(stored, dict), f"metadata is {type(stored).__name__}, not an object"
        assert stored.get("first") == "a", (
            f"merge into a NULL metadata column stored {stored!r} while "
            f"update_memory returned True; anything using this to mark an item "
            f"processed will reprocess it forever")

        # (b) MERGE, not replace. A marker written over existing metadata must
        # not discard what was already there.
        assert await storage.update_memory(
            mid, {"metadata": {"second": "b"}, "metadata.merge": True}) is True
        stored = await metadata()
        assert stored == {"first": "a", "second": "b"}, (
            f"expected a merge, got {stored!r}; the pre-existing key was "
            f"discarded, so marking an item processed would erase its other "
            f"metadata")
    finally:
        await db.execute_query(
            "DELETE FROM memory_hot.memory_hot WHERE memory_id = $1", (mid,), commit=True)


# ---------------------------------------------------------------- component 2

@pytest.mark.asyncio
async def test_learning_recorded_and_credit_earned_are_separately_representable():
    """The interface must express (recorded=True, credit=False)."""
    _load_env()
    from core.learning.unified_learning_system import get_unified_learning_system
    from core.learning.learning_interfaces import LearningExample

    learning = get_unified_learning_system()
    await learning.start()

    # A domain known to hold learned concepts, and an example that states no
    # accuracy -- so the strategy cannot earn credit while the example is still
    # learned from. This is precisely the state the old interface collapsed.
    result = await learning.learn_with_domain_context(
        LearningExample(
            example_id="test_recorded_vs_credit",
            inputs={"task_description": "verify pressure loss across a fitting"},
            domain="practical",
        ),
        "practical",
    )
    meta = result.metadata or {}

    assert "learning_recorded" in meta, (
        "learn_with_domain_context does not report whether the example was "
        "learned from; without it a caller can only read `success`, which used "
        "to carry the credit flag")
    assert "strategy_earned_credit" in meta, (
        "credit must be reported separately from whether the example was "
        "learned from")
    assert result.success is meta["learning_recorded"], (
        f"success={result.success!r} but learning_recorded={meta['learning_recorded']!r}; "
        f"`success` must mean 'learned from' and nothing else")

    assert meta["learning_recorded"] is True, (
        f"an example in a populated domain was not recorded as learned "
        f"(error={result.error!r}, class={meta.get('error_class')!r})")

    # The regression case, stated as a state rather than a hope: recorded
    # without credit must be expressible and must read as success.
    if meta["strategy_earned_credit"] is False:
        assert result.success is True, (
            "an example that was learned from but earned no strategy credit "
            "reported success=False -- the exact conflation that made the idle "
            "tier discard working expansions and reprocess them forever")

    # A negative must always be explained, on every path.
    if not result.success:
        assert result.error or meta.get("error_class"), (
            "unexplained negative: indistinguishable from a strategy that "
            "simply earned no credit")


# ---------------------------------------------------------------- component 3

@pytest.mark.asyncio
async def test_producer_vocabulary_is_a_subset_of_what_the_resolver_accepts():
    """The producer's category space and the registry's must be ONE vocabulary."""
    _load_env()
    import inspect
    import re
    from core.agents.autonomous.autonomous_coordinator import AutonomousCoordinator
    from core.domain.domain_registry import DomainRegistry, UnresolvedDomainReference
    from core.domain.domain_types import DomainType

    # (a) ONE enum, not two vocabularies that happen to agree. universal_domain_master
    # re-exports the registry's DomainType; a shadow copy would compare unequal
    # by identity and every category would silently miss.
    from core.integration.universal_domain_master import DomainType as ProducerDomainType
    assert ProducerDomainType is DomainType, (
        "the producer and the registry use different DomainType objects; "
        "identity-based Enum equality means their values can never match")

    # (b) Every literal the producer can return comes FROM that enum. A branch
    # returning a hand-typed string is how the two vocabularies drift apart.
    source = inspect.getsource(AutonomousCoordinator._infer_domain_from_task)
    literals = set(re.findall(r'return\s+"([^"]+)"', source))
    unknown = sorted(lit for lit in literals if lit not in {d.value for d in DomainType})
    assert not unknown, (
        f"_infer_domain_from_task can return {unknown}, which are not DomainType "
        f"values; the registry resolves against DomainType and would never match")

    # (c) Every category the producer can emit is ACCEPTED by the resolver --
    # either resolving to fields or raising the explicit unresolved error. What
    # must never happen is a crash or a silent empty for a category the producer
    # routinely emits.
    registry = DomainRegistry()
    await registry.initialize()
    for dt in DomainType:
        try:
            registry.resolve_domain_reference(dt.value, require_concepts=True)
        except UnresolvedDomainReference:
            pytest.fail(
                f"producer category {dt.value!r} is unresolvable; the producer "
                f"can classify a task into it and the outcome could never reach "
                f"any domain")

    # (d) And every populated field is reachable from its own category, or a
    # task classified there resolves past the concepts it should have found.
    populated = {d.domain_id for d in registry.domains.values() if d.concepts}
    assert populated, "registry loaded no populated domain"
    reachable = set()
    for domain in registry.domains.values():
        if domain.concepts:
            reachable.update(
                r.domain_id for r in registry.resolve_domain_reference(
                    domain.domain_type.value, require_concepts=True))
    assert not sorted(populated - reachable), (
        f"populated field(s) {sorted(populated - reachable)} cannot be reached "
        f"from their own DomainType category")


# ---------------------------------------------------------------- component 4

@pytest.mark.asyncio
async def test_universal_projection_is_derived_not_persisted():
    """domain_abstract carries the ontology's universal level, by projection."""
    _load_env()
    from core.database import get_database_manager
    from core.domain.domain_registry import DomainRegistry

    registry = DomainRegistry()
    await registry.initialize()
    abstract = registry.domains[DomainRegistry.UNIVERSAL_DOMAIN_ID]

    projected = {cid: c for cid, c in abstract.concepts.items()
                 if (c.properties or {}).get("source") == "universal_ontology"}
    assert projected, (
        "domain_abstract holds no projected universal concepts; the ABSTRACT "
        "category resolves to nothing while UniversalOntology holds them one "
        "module away")

    # Authority is encoded by PROVENANCE, not by forbidding the abstract domain
    # to hold anything. Torin may legitimately learn a concept that belongs to
    # the abstract level later; what must never happen is the ONTOLOGY's
    # concepts being copied into unified.concepts, which would give the
    # universal level two owners that can disagree.
    db = get_database_manager()
    rows = await db.execute_query(
        "SELECT concept_id FROM unified.concepts WHERE concept_id = ANY($1::text[])",
        (list(projected),), fetch_all=True) or []
    assert not rows, (
        f"projected universal concept(s) {[r['concept_id'] for r in rows]} were "
        f"persisted to unified.concepts; the projection must stay derived so "
        f"UniversalOntology remains their single authority")

    # Stable identity across reload, or structure compared between restarts
    # looks changed when nothing changed.
    again = DomainRegistry()
    await again.initialize()
    assert set(abstract.relations) == set(
        again.domains[DomainRegistry.UNIVERSAL_DOMAIN_ID].relations), (
        "projected relation ids differ between loads")


# ---------------------------------------------------------------- component 5

@pytest.mark.asyncio
async def test_idle_tier_registers_at_runtime_and_is_dispatchable():
    """Registration is proven by RUNNING it, not by reading the source."""
    _load_env()
    coord = await _coordinator()

    # Source text can contain a registration that never executes, and a
    # reformatting of the list would break a regex oracle without changing
    # behaviour. Invoke the real registration path and inspect what it built.
    coord._register_idle_subsystems()

    assert "idle_domain_expansion" in coord.registered_capabilities, (
        "the lifecycle did not register a domain-expansion tier; "
        "TORINAI_REFERENCE.md:3114 specifies one, and without it the "
        "task-outcome producer has no reader")

    entry = coord.registered_capabilities["idle_domain_expansion"]
    callback = getattr(entry["instance"], entry["method"], None)
    assert callable(callback), (
        f"idle_domain_expansion registers {entry['method']!r}, which is not "
        f"callable on the registered instance; the tier would fail on every "
        f"idle cycle")
    assert asyncio.iscoroutinefunction(callback), (
        f"{entry['method']!r} is not awaitable; the idle loop awaits its "
        f"capabilities")
    assert entry["status"] == "active" and entry["interval"] > 0


# ---------------------------------------------------------------- component 6

@pytest.mark.asyncio
async def test_tier_reads_the_structured_record_not_the_narrative():
    """store_memory keeps the record and the rendering apart; the tier must
    read the record.

    `content` is a narrative built from the event dict -- "Task success in
    domain 'scientific' at ...". The TaskOutcomeRecord fields are not
    recoverable from it without parsing English, and store_memory preserves the
    original dict verbatim at thinking_state["raw_event"] for exactly that
    reason. A tier reading `content` finds no `domain` on any outcome and
    classifies every one of them as unusable -- which is indistinguishable from
    having nothing to learn from, and is why this is asserted on the tier's own
    skip reasons rather than only through the full chain.
    """
    _load_env()
    from core.database import get_database_manager
    from core.memory.utils.interfaces import MemoryType

    coord = await _coordinator()
    storage = await _storage()
    db = get_database_manager()

    task = _task("test and verify pressure loss across the pipe fitting installation",
                 task_id="oracle_record_vs_narrative")
    memory_id = await coord._store_task_outcome_meta_memory(
        task=task, outcome="success", confidence=0.8,
        result_summary="verified against the minor-loss coefficient")
    try:
        found = await storage.search_memories(
            memory_type=MemoryType.META, tags={TAG}, limit=500)
        item = next(m for m in found if m.memory_id == memory_id)

        # The two are DIFFERENT representations, and only one is the record.
        raw = (item.thinking_state or {}).get("raw_event")
        assert isinstance(raw, dict) and raw.get("domain"), (
            "the structured record did not survive storage")
        assert not (isinstance(item.content, dict) and item.content.get("domain")), (
            "content now carries the structured fields too; if that is "
            "intentional the record has two representations and they can "
            "disagree")

        await coord._idle_domain_expansion_work()
        counts = coord._domain_expansion_counts
        assert counts["skipped"].get("no_domain", 0) == 0, (
            f"the tier classified {counts['skipped']['no_domain']} outcome(s) as "
            f"having no domain while the stored records all carry one -- it is "
            f"reading the narrative instead of thinking_state['raw_event']")
        assert counts["expanded"] > 0, (
            f"the tier considered {counts['considered']} outcome(s) and expanded "
            f"none: {counts['skipped']}")
    finally:
        await db.execute_query(
            "DELETE FROM memory_hot.memory_hot WHERE memory_id = $1",
            (memory_id,), commit=True)


# ------------------------------------------------------- the return direction

@pytest.mark.asyncio
async def test_applying_a_mapping_counts_as_using_it():
    """usage_count separates a relied-upon correspondence from a one-off."""
    _load_env()
    from core.database import get_database_manager
    from core.learning.unified_learning_system import get_unified_learning_system

    learning = get_unified_learning_system()
    await learning.start()
    db = get_database_manager()

    async def events_for(task_ids):
        rows = await db.execute_query(
            "SELECT count(*) AS n FROM unified.mapping_usage_events "
            "WHERE task_id = ANY($1::text[])", (list(task_ids),), fetch_all=True)
        return rows[0]["n"]

    # DISTINCT identities per run. Usage events are idempotent on
    # (mapping, task, stage), so reusing fixed task ids makes the second run of
    # this test record nothing -- correct behaviour that would read here as the
    # accumulation defect it is meant to catch.
    import uuid as _uuid
    run = _uuid.uuid4().hex[:8]
    task_a, task_b = f"oracle_usage_{run}_a", f"oracle_usage_{run}_b"

    before = await events_for([task_a, task_b])
    result = await learning.transfer_learning_across_domains(
        "domain_plumbing", "domain_fluid_mechanics",
        {"trigger": "usage oracle 1", "task_id": task_a})
    if not result.get("success"):
        pytest.skip(f"no validated mapping to apply: {result.get('error')}")
    once = await events_for([task_a, task_b])

    assert once > before, (
        "a transfer was created from validated mappings and no mapping's "
        "usage_count moved; usage_count is serialised, persisted and read back "
        "but nothing increments it, so every mapping reads as equally untried "
        "forever")

    # ACCUMULATION across DISTINCT applications. suggest_cross_domain_mappings
    # mints a fresh CrossDomainMapping per call with usage_count=0, so storing
    # the candidate wholesale reset the running total and every application
    # landed on 1 again. A single-application assertion passes against that bug.
    await learning.transfer_learning_across_domains(
        "domain_plumbing", "domain_fluid_mechanics",
        {"trigger": "usage oracle 2", "task_id": task_b})
    twice = await events_for([task_a, task_b])
    assert twice > once, (
        f"usage went {before} -> {once} -> {twice}: a second application on a "
        f"different task did not accumulate. A re-derived mapping is "
        f"overwriting the stored count, so a correspondence relied on fifty "
        f"times is indistinguishable from one used once")

    # And the count is state, not a session artefact.
    # usage_count is a PROJECTION: after a restart it must equal the number of
    # events, not a separately-maintained number that happens to look right.
    from core.domain.domain_registry import DomainRegistry
    fresh = DomainRegistry()
    await fresh.initialize()
    truth = {r["mapping_id"]: r["n"] for r in (await db.execute_query(
        "SELECT mapping_id, count(*) AS n FROM unified.mapping_usage_events "
        "GROUP BY mapping_id", fetch_all=True) or [])}
    drifted = [(mid, m.usage_count, truth.get(mid, 0))
               for mid, m in fresh.cross_domain_mappings.items()
               if m.usage_count != truth.get(mid, 0)]
    assert not drifted, (
        f"usage_count disagrees with the usage events after reload: {drifted[:3]}; "
        f"the count is maintained independently of the record it summarises and "
        f"can survive with no events to justify it")
    assert max(truth.values(), default=0) >= 1, "no usage event survived reload"

    await db.execute_query(
        "DELETE FROM unified.mapping_usage_events WHERE task_id = ANY($1::text[])",
        ([task_a, task_b],), commit=True)


@pytest.mark.asyncio
async def test_a_retried_application_is_not_a_second_use():
    """usage is EVENTS keyed by (mapping, task, stage) -- retries count once."""
    _load_env()
    from core.database import get_database_manager
    from core.learning.unified_learning_system import get_unified_learning_system

    learning = get_unified_learning_system()
    await learning.start()
    db = get_database_manager()

    import uuid as _uuid
    run = _uuid.uuid4().hex[:8]
    task, other = f"oracle_retry_{run}", f"oracle_retry_{run}_other"

    async def events():
        rows = await db.execute_query(
            "SELECT count(*) AS n FROM unified.mapping_usage_events WHERE task_id = ANY($1::text[])",
            ([task, other],), fetch_all=True)
        return rows[0]["n"]

    try:
        r = await learning.transfer_learning_across_domains(
            "domain_plumbing", "domain_fluid_mechanics",
            {"trigger": "retry oracle", "task_id": task})
        if not r.get("success"):
            pytest.skip(f"no validated mapping to apply: {r.get('error')}")
        first = await events()
        assert first > 0, "the application recorded no usage event"

        # Autonomous execution retries. The SAME logical application must not
        # become additional evidence -- a count inflated by retries would make a
        # mapping applied once look like one relied on repeatedly.
        await learning.transfer_learning_across_domains(
            "domain_plumbing", "domain_fluid_mechanics",
            {"trigger": "retry oracle", "task_id": task})
        assert await events() == first, (
            f"a retried application added usage events ({first} -> {await events()}); "
            f"usage_id must be derived from (mapping_id, task_id, stage) so the "
            f"same application is idempotent")

        # A genuinely different task IS a second use.
        await learning.transfer_learning_across_domains(
            "domain_plumbing", "domain_fluid_mechanics",
            {"trigger": "retry oracle", "task_id": other})
        assert await events() > first, (
            "a different task did not register as a distinct use; idempotency "
            "is keyed too coarsely and real applications are being discarded")
    finally:
        await db.execute_query(
            "DELETE FROM unified.mapping_usage_events WHERE task_id = ANY($1::text[])",
            ([task, other],), commit=True)


@pytest.mark.asyncio
async def test_transfer_verdict_states_how_it_was_inferred():
    """An attributed verdict and a correlational one must not read the same.

    "The domain improved after the transfer" is not "the transfer improved the
    domain". When usage events identify which tasks a mapping actually
    participated in, the comparison is applied-vs-unapplied within the same
    window; when they do not, it falls back to before-vs-after, which is
    confounded with everything else that changed. Both can be legitimate, but a
    reader must be able to tell which one produced a TRUE.
    """
    _load_env()
    import inspect
    from core.agents.autonomous.autonomous_coordinator import AutonomousCoordinator

    source = inspect.getsource(AutonomousCoordinator._resolve_transfer_outcomes)
    assert '"attributed"' in source and '"observational"' in source, (
        "the evaluator does not distinguish an attributed verdict from a "
        "correlational one; a before/after TRUE would be reported as though it "
        "established that the transfer helped")
    assert "tasks_using_mappings" in source, (
        "the evaluator never asks which tasks the mapping participated in, so "
        "every post-transfer outcome is credited to it regardless of whether "
        "it was involved")

    # And the verdict carries its inference, not just its answer.
    coord = await _coordinator()
    await coord._resolve_transfer_outcomes()
    assert coord._transfer_resolution_status in {"COMPLETED", "NOTHING_PENDING"}


@pytest.mark.asyncio
async def test_transfer_outcome_resolves_only_on_sufficient_evidence():
    """NULL until the target domain has history on both sides; then TRUE/FALSE."""
    _load_env()
    from core.database import get_database_manager
    from core.memory.utils.interfaces import MemoryItem, MemoryType

    coord = await _coordinator()
    storage = await _storage()
    db = get_database_manager()

    # A field whose category carries NO real task outcomes, so the fixture is
    # the only evidence and the verdict is attributable to it.
    target_field, category = "fluid_mechanics", "physical"
    rich, thin = "test_xfer_rich", "test_xfer_thin"
    made = []

    async def outcome(tag_id, ok, offset_minutes):
        mid = f"test_outcome_{tag_id}"
        await storage.store_memory(MemoryItem(
            memory_id=mid, memory_type=MemoryType.META,
            content={"event": "task_outcome"},
            thinking_state={"raw_event": {"domain": category,
                                          "outcome": "success" if ok else "failure"}},
            tags={TAG, "test_transfer_fixture"}))
        await db.execute_query(
            "UPDATE memory_hot.memory_hot SET created_at = NOW() + ($2 || ' minutes')::interval "
            "WHERE memory_id = $1", (mid, str(offset_minutes)), commit=True)
        made.append(mid)

    async def transfer(tid):
        await db.execute_query(
            """INSERT INTO unified.knowledge_transfers
                 (transfer_id, source_domain, target_domain, concept, concept_type,
                  transfer_method, success, metadata, created_at)
               VALUES ($1,'plumbing',$2,'fixture','entity','structural_analogy',
                       NULL,'{}'::jsonb, NOW())""",
            (tid, target_field), commit=True)

    try:
        # Baseline: 6 failures BEFORE. Post: 6 successes AFTER. A real effect.
        for i in range(6):
            await outcome(f"{rich}_pre_{i}", ok=False, offset_minutes=-120 + i)
        await transfer(rich)
        await transfer(thin)
        for i in range(6):
            await outcome(f"{rich}_post_{i}", ok=True, offset_minutes=60 + i)

        await coord._resolve_transfer_outcomes()

        rows = await db.execute_query(
            "SELECT transfer_id, success, metadata FROM unified.knowledge_transfers "
            "WHERE transfer_id = ANY($1::text[])", ([rich, thin],), fetch_all=True)
        verdicts = {r["transfer_id"]: r["success"] for r in rows}

        assert verdicts[rich] is True, (
            f"a transfer followed by a 0%->100% swing in its target domain "
            f"resolved to {verdicts[rich]!r}; the return leg of the loop is not "
            f"reading the evidence")

        import json
        meta = rows[0]["metadata"] if rows[0]["transfer_id"] == rich else rows[1]["metadata"]
        meta = json.loads(meta) if isinstance(meta, str) else meta
        evidence = meta.get("outcome_evidence") or {}
        assert evidence.get("reference_n", 0) >= 5 and evidence.get("effect_n", 0) >= 5, (
            f"the verdict was stored without the evidence it rests on ({evidence}); "
            f"an opaque boolean cannot be revised when more outcomes arrive")
        # No usage events exist for this fixture transfer, so the only available
        # comparison is before/after. It must SAY so rather than presenting a
        # correlational result as an attributed one.
        assert evidence.get("inference") == "observational", (
            f"a before/after comparison was labelled {evidence.get('inference')!r}; "
            f"with no record of which tasks the mapping participated in, this "
            f"verdict cannot claim the transfer caused the change")

        # The thin transfer shares the same evidence window, so it resolves too.
        # What must never happen is a verdict with too little history -- prove
        # that by asking for more evidence than exists.
        await db.execute_query(
            "UPDATE unified.knowledge_transfers SET success = NULL, metadata = '{}'::jsonb "
            "WHERE transfer_id = ANY($1::text[])", ([rich, thin],), commit=True)
        original = coord.TRANSFER_MIN_EVIDENCE
        try:
            coord.TRANSFER_MIN_EVIDENCE = 500
            await coord._resolve_transfer_outcomes()
        finally:
            coord.TRANSFER_MIN_EVIDENCE = original

        still = await db.execute_query(
            "SELECT transfer_id, success FROM unified.knowledge_transfers "
            "WHERE transfer_id = ANY($1::text[])", ([rich, thin],), fetch_all=True)
        assert all(r["success"] is None for r in still), (
            "a transfer was given a verdict on less evidence than required; "
            "'not enough history to say' must stay NULL and never default to "
            "False, or an unjudged transfer becomes a refuted one")
    finally:
        if made:
            await db.execute_query(
                "DELETE FROM memory_hot.memory_hot WHERE memory_id = ANY($1::text[])",
                (made,), commit=True)
        await db.execute_query(
            "DELETE FROM unified.knowledge_transfers WHERE transfer_id = ANY($1::text[])",
            ([rich, thin],), commit=True)


# ------------------------------------------------------------------ the chain

@pytest.mark.asyncio
async def test_chain_end_to_end():
    """Producer -> memory -> bridge -> consumer -> marker, proven as one path.

    The component tests above each cross a single joint. This crosses all of
    them at once, which is the only way to catch a chain that is broken between
    two individually-correct parts.
    """
    _load_env()
    from core.database import get_database_manager
    from core.domain.domain_registry import DomainRegistry
    from core.memory.utils.interfaces import MemoryType

    coord = await _coordinator()
    storage = await _storage()
    db = get_database_manager()

    # 1. A task the producer classifies into a category that HAS learned fields.
    task = _task("test and verify pressure loss across the pipe fitting installation",
                 task_id="oracle_chain_e2e")
    category = coord._infer_domain_from_task(task)
    resolved = DomainRegistry()
    await resolved.initialize()
    fields = [r.domain_id for r in resolved.resolve_domain_reference(
        category, require_concepts=True)]
    assert fields, (
        f"the producer classified this task as {category!r}, which resolves to "
        f"no populated field; the chain cannot be exercised through it")

    # 2. Store it through the REAL producer.
    memory_id = await coord._store_task_outcome_meta_memory(
        task=task, outcome="success", confidence=0.8,
        result_summary="verified against the minor-loss coefficient")
    assert memory_id, "the producer stored no memory"

    try:
        # 3. Read it back INDEPENDENTLY: the structured record must survive,
        #    not just the narrative rendering.
        found = await storage.search_memories(
            memory_type=MemoryType.META, tags={TAG}, limit=500)
        item = next((m for m in found if m.memory_id == memory_id), None)
        assert item is not None, (
            "the stored outcome is not returned by the structured search the "
            "tier uses to find its work")
        raw = (item.thinking_state or {}).get("raw_event")
        assert isinstance(raw, dict), (
            f"raw_event is {type(raw).__name__}; the structured TaskOutcomeRecord "
            f"did not survive storage and only the prose narrative remains")
        assert raw.get("domain") == category
        assert raw.get("outcome") == "success"

        # 4. Run the tier.
        await coord._idle_domain_expansion_work()
        assert coord._domain_expansion_status == "COMPLETED"

        # 5-8. The outcome is consumed, and the marker is durably written.
        async def mark():
            rows = await db.execute_query(
                f"SELECT metadata->>'{MARK}' AS m FROM memory_hot.memory_hot "
                f"WHERE memory_id = $1", (memory_id,), fetch_all=True)
            return rows[0]["m"] if rows else None

        first_mark = await mark()
        assert first_mark, (
            "the outcome was processed but carries no durable marker; the next "
            "pass would re-learn it and the meta-learner would count one "
            "outcome as several independent trials")

        # 9. EXACTLY ONCE. A second pass must not touch it again.
        await coord._idle_domain_expansion_work()
        assert await mark() == first_mark, (
            "the marker changed on a second pass; the outcome was reprocessed")

        # 10. RESTART PERSISTENCE. Fresh instances, nothing carried in memory:
        #     the processed state must still be processed.
        from core.agents.memory_agent import MemoryAgent
        fresh_storage = MemoryAgent()
        await fresh_storage.initialize()
        reread = await fresh_storage.postgres_storage.search_memories(
            memory_type=MemoryType.META, tags={TAG}, limit=500)
        after_restart = next((m for m in reread if m.memory_id == memory_id), None)
        assert after_restart is not None
        assert (after_restart.metadata or {}).get(MARK) == first_mark, (
            "the processed marker did not survive a fresh read; every restart "
            "would re-expand the entire backlog")

        # And the learned structure itself survives a fresh registry.
        fresh_registry = DomainRegistry()
        await fresh_registry.initialize()
        assert fresh_registry.cross_domain_mappings, (
            "no cross-domain mapping survived a registry restart")
    finally:
        await db.execute_query(
            "DELETE FROM memory_hot.memory_hot WHERE memory_id = $1",
            (memory_id,), commit=True)
