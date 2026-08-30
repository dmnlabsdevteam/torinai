"""Learned rules must survive a restart, and must not validate themselves.

Persistence is what turns "it induced a rule" into "the competence is owned by
the substrate". These oracles pin the two things that would make that claim
false without looking false: a rule promoted to executable on the evidence that
produced it, and a refuted rule quietly disappearing so the store only ever
reports successes.
"""
import json

import pytest
import pytest_asyncio

from core.learning.rule_induction import (
    Fact, RuleEffects, TrainingExample, get_rule_inducer,
)
from core.learning.rule_store import (
    EpistemicStatus, EvidenceRole, INDUCTION_ROLES, ProvenanceViolation,
    RuleStore, SCHEMA_VERSION, from_json, to_json,
)
from core.model_policy import (
    ModelPolicy, assert_model_free, reset_model_telemetry, set_model_policy,
)

F = Fact.parse
DOMAIN = "test_rule_store"


@pytest.fixture(autouse=True)
def strict():
    previous = set_model_policy(ModelPolicy.STRICT_MODEL_FREE)
    reset_model_telemetry()
    yield
    assert_model_free("rule store")
    set_model_policy(previous)
    reset_model_telemetry()


def positive(x, y, evidence_id):
    before = (F(f"NAL({x})"), F(f"VEX({x},{y})"), F(f"TOR({y})"))
    return TrainingExample(before=before, action=F(f"KEM({x},{y})"),
                           after=before + (F(f"ZOR({x},{y})"),), evidence_id=evidence_id)


def negative(before, action, evidence_id):
    return TrainingExample(before=before, action=action, after=before,
                           positive=False, evidence_id=evidence_id)


TEACHING = [
    positive("a", "b", "d1"), positive("c", "d", "d2"),
    negative((F("VEX(e,f)"), F("TOR(f)")), F("KEM(e,f)"), "no_NAL"),
    negative((F("NAL(g)"), F("TOR(h)")), F("KEM(g,h)"), "no_VEX"),
    negative((F("NAL(i)"), F("VEX(i,j)")), F("KEM(i,j)"), "no_TOR"),
    negative((F("NAL(k)"), F("VEX(k,l)"), F("TOR(l)")), None, "no_KEM"),
]
HELD_OUT = [positive("m", "n", "h1"), positive("p", "q", "h2")]


@pytest_asyncio.fixture
async def store():
    s = RuleStore()
    await s.ensure_schema()
    yield s
    await s.db().execute_query(
        "DELETE FROM unified.rule_authority_events WHERE rule_id IN"
        " (SELECT rule_id FROM unified.learned_rules WHERE domain_id = $1)", (DOMAIN,))
    await s.db().execute_query(
        "DELETE FROM unified.learned_rule_evidence WHERE rule_id IN"
        " (SELECT rule_id FROM unified.learned_rules WHERE domain_id = $1)", (DOMAIN,))
    await s.db().execute_query(
        "UPDATE unified.learned_rules SET supersedes_rule_id = NULL WHERE domain_id = $1",
        (DOMAIN,))
    await s.db().execute_query(
        "DELETE FROM unified.learned_rules WHERE domain_id = $1", (DOMAIN,))


@pytest_asyncio.fixture
async def candidate(store):
    result = get_rule_inducer().induce(TEACHING)
    stored = await store.record_induction(result, TEACHING, domain_id=DOMAIN)
    return stored[0]


# ------------------------------------------------------------- representation

def test_the_canonical_form_is_structure_not_a_rendered_string():
    """A formula string would trap learned cognition in a textual encoding the
    moment negation, typing or arithmetic arrive."""
    rule = get_rule_inducer().induce(TEACHING).rule
    payload = to_json(rule)

    assert isinstance(payload["body"], list)
    assert all(set(entry) == {"predicate", "args"} for entry in payload["body"])
    assert "delete_effects" in payload, "delete effects present before they are used"
    assert from_json(payload) == rule, "structure must round-trip exactly"


def test_an_unreadable_schema_version_is_refused_not_guessed_at():
    payload = to_json(get_rule_inducer().induce(TEACHING).rule)
    payload["schema_version"] = SCHEMA_VERSION + 1
    with pytest.raises(ValueError):
        from_json(payload)


# ------------------------------------------------------------------- statuses

@pytest.mark.asyncio
async def test_induction_produces_a_candidate_that_may_not_execute(candidate):
    assert candidate.status is EpistemicStatus.CANDIDATE
    assert candidate.is_executable is False


@pytest.mark.asyncio
async def test_independent_evidence_promotes_to_validated(store, candidate):
    outcome = await store.validate(candidate, HELD_OUT)

    assert outcome.status is EpistemicStatus.VALIDATED
    assert outcome.confirmed == len(HELD_OUT)
    assert candidate.is_executable is True
    assert candidate.validated_at is not None


@pytest.mark.asyncio
async def test_a_rule_cannot_validate_itself_on_its_induction_evidence(store, candidate):
    """The provenance invariant. Dropping the overlap silently would report a
    pass from a smaller, unstated sample."""
    with pytest.raises(ProvenanceViolation):
        await store.validate(candidate, TEACHING)


@pytest.mark.asyncio
async def test_partial_overlap_is_refused_rather_than_trimmed(store, candidate):
    with pytest.raises(ProvenanceViolation):
        await store.validate(candidate, [HELD_OUT[0], TEACHING[0]])


@pytest.mark.asyncio
async def test_contradicting_evidence_refutes(store, candidate):
    contradiction = [
        TrainingExample(before=(F("NAL(u)"), F("VEX(u,v)"), F("TOR(v)")),
                        action=F("KEM(u,v)"),
                        after=(F("NAL(u)"), F("VEX(u,v)"), F("TOR(v)")),
                        positive=False, evidence_id="counter"),
    ]
    outcome = await store.validate(candidate, contradiction)
    assert outcome.status is EpistemicStatus.REFUTED
    assert outcome.contradicted == 1


@pytest.mark.asyncio
async def test_a_refuted_rule_is_kept_with_its_evidence(store, candidate):
    """REFUTED is not deletion. That a generalization was too broad is itself
    learned knowledge, and a store that erases failures reports only
    survivorship."""
    await store.validate(candidate, [
        TrainingExample(before=(F("NAL(u)"), F("VEX(u,v)"), F("TOR(v)")),
                        action=F("KEM(u,v)"),
                        after=(F("NAL(u)"), F("VEX(u,v)"), F("TOR(v)")),
                        positive=False, evidence_id="counter")])

    refuted = await store.load(EpistemicStatus.REFUTED, domain_id=DOMAIN)
    assert any(r.rule_id == candidate.rule_id for r in refuted)

    roots = await store.evidence_roots(candidate.rule_id)
    assert "counter" in roots, "the refuting observation must be retained"


@pytest.mark.asyncio
async def test_a_narrower_rule_records_what_it_superseded(store, candidate):
    replacement = (await store.record_induction(
        get_rule_inducer().induce(TEACHING), TEACHING, domain_id=DOMAIN))[0]
    await store.supersede(candidate, replacement)

    reloaded = {r.rule_id: r for r in await store.load(domain_id=DOMAIN)}
    assert reloaded[replacement.rule_id].supersedes_rule_id == candidate.rule_id
    assert candidate.rule_id in reloaded, "the superseded rule is not removed"


# ------------------------------------------------------------------ provenance

@pytest.mark.asyncio
async def test_induction_and_validation_evidence_are_separately_roled(store, candidate):
    await store.validate(candidate, HELD_OUT)

    induction = await store.evidence_roots(candidate.rule_id, INDUCTION_ROLES)
    validation = await store.evidence_roots(
        candidate.rule_id, {EvidenceRole.VALIDATION_POSITIVE,
                            EvidenceRole.VALIDATION_NEGATIVE})

    assert induction == {"d1", "d2", "no_NAL", "no_VEX", "no_TOR", "no_KEM"}
    assert validation == {"h1", "h2"}
    assert not (induction & validation), "the two bases must stay disjoint"


@pytest.mark.asyncio
async def test_repeated_root_ids_do_not_inflate_support(store):
    duplicated = [positive("a", "b", "d1")] * 6 + [positive("c", "d", "d2")]
    result = get_rule_inducer().induce(duplicated + TEACHING[2:])
    stored = await store.record_induction(
        result, duplicated + TEACHING[2:], domain_id=DOMAIN)

    assert stored[0].positive_root_count == 2, (
        "ten transformed copies of one demonstration are one root observation"
    )


# ------------------------------------------------------------------ execution

@pytest.mark.asyncio
async def test_only_validated_rules_are_offered_to_execution(store, candidate):
    assert not any(
        r.rule_id == candidate.rule_id
        for r in await store.executable_rules(domain_id=DOMAIN)
    ), "a CANDIDATE must never reach execution"

    await store.validate(candidate, HELD_OUT)
    assert any(
        r.rule_id == candidate.rule_id
        for r in await store.executable_rules(domain_id=DOMAIN)
    )


@pytest.mark.asyncio
async def test_a_reloaded_rule_is_structurally_identical(store, candidate):
    """Test 5's core: what comes back must be the rule that was learned, not a
    lossy rendering of it."""
    await store.validate(candidate, HELD_OUT)
    reloaded = next(
        r for r in await store.executable_rules(domain_id=DOMAIN)
        if r.rule_id == candidate.rule_id
    )
    assert reloaded.rule == candidate.rule
    assert reloaded.rule.effects.add == candidate.rule.effects.add
    assert reloaded.rule.is_range_restricted
