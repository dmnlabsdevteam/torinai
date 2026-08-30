"""Oracles for semantic rule identity.

Rule ids used to be `rule_{uuid4()}`, so the same hypothesis induced twice was
two rules. At education scale that turns a repeated lesson into thousands of
"new" rules and every support count, validation history and competence estimate
computed over them counts copies.

Identity is now a SHA-256 over the rule's meaning. These oracles pin what
"meaning" includes and, just as importantly, what it excludes.
"""
import pytest

from core.learning.rule_identity import canonical_form, semantic_fingerprint
from core.learning.rule_induction import CandidateRule, Fact, RuleEffects

F = Fact.parse


def rule(body, add=(), delete=(), action=None):
    return CandidateRule(
        body=frozenset(F(b) for b in body),
        effects=RuleEffects(add=frozenset(F(a) for a in add),
                            delete=frozenset(F(d) for d in delete)),
        action=F(action) if action else None,
    )


MOVE = rule(["MOVE(?X0,?X2,?X1)", "AT(?X0,?X2)", "OPEN(?X1)", "PATH(?X2,?X1)"],
            add=["AT(?X0,?X1)"], delete=["AT(?X0,?X2)"], action="MOVE(?X0,?X2,?X1)")


def test_reordering_the_body_is_the_same_hypothesis():
    """Conjunction is commutative; an identity that depended on literal order
    would split a rule from itself."""
    shuffled = rule(["PATH(?X2,?X1)", "OPEN(?X1)", "AT(?X0,?X2)", "MOVE(?X0,?X2,?X1)"],
                    add=["AT(?X0,?X1)"], delete=["AT(?X0,?X2)"], action="MOVE(?X0,?X2,?X1)")
    assert semantic_fingerprint(MOVE) == semantic_fingerprint(shuffled)


def test_alpha_renaming_is_the_same_hypothesis():
    """Otherwise UUID duplication is simply replaced by variable-name duplication."""
    renamed = rule(["MOVE(?A,?C,?B)", "AT(?A,?C)", "OPEN(?B)", "PATH(?C,?B)"],
                   add=["AT(?A,?B)"], delete=["AT(?A,?C)"], action="MOVE(?A,?C,?B)")
    assert semantic_fingerprint(MOVE) == semantic_fingerprint(renamed)


def test_adding_a_real_precondition_is_a_different_hypothesis():
    """R1 -> R2 must get its own identity: that is the revision history."""
    without_at = rule(["MOVE(?X0,?X2,?X1)", "OPEN(?X1)", "PATH(?X2,?X1)"],
                      add=["AT(?X0,?X1)"], delete=["AT(?X0,?X2)"],
                      action="MOVE(?X0,?X2,?X1)")
    assert semantic_fingerprint(MOVE) != semantic_fingerprint(without_at)


def test_changing_the_action_is_a_different_hypothesis():
    same_body = rule(["MOVE(?X0,?X2,?X1)", "AT(?X0,?X2)", "OPEN(?X1)", "PATH(?X2,?X1)"],
                     add=["AT(?X0,?X1)"], delete=["AT(?X0,?X2)"], action="OPEN(?X1)")
    assert semantic_fingerprint(MOVE) != semantic_fingerprint(same_body)


def test_an_unknown_action_is_a_different_hypothesis_from_a_known_one():
    """A v1 rule genuinely does not record which literal was the action, so it
    is usable for inference and NOT admissible as a planning operator. Two rules
    that differ on that differ in what may be done with them.

    This is not hypothetical: unified.learned_rules holds exactly such a pair
    for kite17/move, and collapsing them would have granted planning authority
    to a rule that never recorded an action.
    """
    unknown = rule(["MOVE(?X0,?X2,?X1)", "AT(?X0,?X2)", "OPEN(?X1)", "PATH(?X2,?X1)"],
                   add=["AT(?X0,?X1)"], delete=["AT(?X0,?X2)"], action=None)
    assert semantic_fingerprint(MOVE) != semantic_fingerprint(unknown)


def test_changing_effects_is_a_different_hypothesis():
    no_delete = rule(["MOVE(?X0,?X2,?X1)", "AT(?X0,?X2)", "OPEN(?X1)", "PATH(?X2,?X1)"],
                     add=["AT(?X0,?X1)"], action="MOVE(?X0,?X2,?X1)")
    assert semantic_fingerprint(MOVE) != semantic_fingerprint(no_delete)
    swapped = rule(["MOVE(?X0,?X2,?X1)", "AT(?X0,?X2)", "OPEN(?X1)", "PATH(?X2,?X1)"],
                   add=["AT(?X0,?X2)"], delete=["AT(?X0,?X1)"], action="MOVE(?X0,?X2,?X1)")
    assert semantic_fingerprint(MOVE) != semantic_fingerprint(swapped)


def test_domain_and_kind_scope_identity():
    assert (semantic_fingerprint(MOVE, domain_id="kite17")
            != semantic_fingerprint(MOVE, domain_id="routing"))
    assert (semantic_fingerprint(MOVE, rule_kind="move")
            != semantic_fingerprint(MOVE, rule_kind="reasoning_pattern"))


def test_history_is_not_part_of_meaning():
    """The canonical form must contain nothing about where the rule came from:
    status, evidence, timestamps, confidence, supersession, usage."""
    form = canonical_form(MOVE, domain_id="kite17", rule_kind="move")
    rendered = repr(form).lower()
    for forbidden in ("rule_id", "status", "created", "validated", "evidence",
                      "confidence", "supersed", "usage", "count"):
        assert forbidden not in rendered, f"{forbidden!r} leaked into rule identity"


def test_the_fingerprint_is_a_full_sha256():
    fingerprint = semantic_fingerprint(MOVE)
    assert len(fingerprint) == 64 and set(fingerprint) <= set("0123456789abcdef")


def test_canonicalisation_refuses_rather_than_approximating():
    """Beyond the enumeration bound the form would not be canonical, and a
    fingerprint that is only usually canonical is worse than none."""
    from core.learning.rule_identity import MAX_VARIABLES

    args = ",".join(f"?V{i}" for i in range(MAX_VARIABLES + 1))
    wide = rule([f"WIDE({args})"], add=["DONE(?V0)"])
    with pytest.raises(ValueError, match="canonicalisation"):
        semantic_fingerprint(wide)


# ---------------------------------------------------------------------------
# Persistence oracles. These run against the real store, in their own domain.
# They are idempotent by construction -- which is the property under test, so a
# second run proves it rather than needing cleanup.
# ---------------------------------------------------------------------------

ORACLE_DOMAIN = "identity_oracle"
pytestmark = pytest.mark.asyncio(loop_scope="session")


async def _store():
    from core.database.unified_database_postgres import get_unified_database
    from core.learning.rule_store import get_rule_store

    db = await get_unified_database()
    await db.initialize()
    store = get_rule_store()
    await store.ensure_schema()
    return db, store


def _demo(subject, evidence_id):
    from core.learning.rule_induction import TrainingExample

    before = (F(f"MAN({subject})"),)
    return TrainingExample(before=before, action=None,
                           after=before + (F(f"MORTAL({subject})"),),
                           positive=True, evidence_id=evidence_id)


async def _induce(store, examples):
    from core.learning.rule_induction import get_rule_inducer

    result = get_rule_inducer().induce(examples)
    return await store.record_induction(
        result, examples, domain_id=ORACLE_DOMAIN, rule_kind="identity_oracle")


@pytest.mark.asyncio
async def test_reinducing_the_same_hypothesis_does_not_create_a_second_rule():
    db, store = await _store()
    first = await _induce(store, [_demo("socrates", "io_ev_1"), _demo("plato", "io_ev_2")])
    assert first, "induction produced nothing; the oracle would be vacuous"
    fingerprint = first[0].semantic_fingerprint
    assert fingerprint, "rule was persisted without a semantic fingerprint"

    again = await _induce(store, [_demo("socrates", "io_ev_1"), _demo("plato", "io_ev_2")])
    assert again[0].rule_id == first[0].rule_id, (
        "the same hypothesis from the same evidence minted a second rule")

    rows = await db.execute_query(
        "SELECT count(*) n FROM unified.learned_rules WHERE semantic_fingerprint = $1",
        (fingerprint,), fetch_all=True)
    assert rows[0]["n"] == 1, f"{rows[0]['n']} rows share one meaning"


@pytest.mark.asyncio
async def test_new_independent_evidence_strengthens_the_rule_it_supports():
    """The behaviour duplicates used to hide: more evidence must raise support
    on ONE hypothesis, not spawn another copy of it."""
    db, store = await _store()
    first = await _induce(store, [_demo("socrates", "io_ev_1"), _demo("plato", "io_ev_2")])
    rule_id, fingerprint = first[0].rule_id, first[0].semantic_fingerprint

    extended = await _induce(store, [
        _demo("socrates", "io_ev_1"), _demo("plato", "io_ev_2"),
        _demo("aristotle", "io_ev_3")])
    assert extended[0].rule_id == rule_id

    rows = await db.execute_query(
        "SELECT count(*) n FROM unified.learned_rules WHERE semantic_fingerprint = $1",
        (fingerprint,), fetch_all=True)
    assert rows[0]["n"] == 1

    roots = await store.evidence_roots(rule_id)
    assert {"io_ev_1", "io_ev_2", "io_ev_3"} <= roots, (
        f"new evidence did not attach to the existing rule: {sorted(roots)}")

    reloaded = await store.get(rule_id)
    assert reloaded.positive_root_count == len(
        [r for r in roots if r.startswith("io_ev")]), (
        "support was incremented rather than recounted from the evidence")


@pytest.mark.asyncio
async def test_legacy_rule_ids_still_resolve():
    """Frozen EDU-01/EDU-02 name these ids. Identity moved to a new column
    precisely so historical reproducibility survived the migration."""
    _, store = await _store()
    for legacy in ("rule_dccaff4cba0f", "rule_edbe5a8b4ad8"):
        record = await store.get(legacy)
        assert record is not None, f"{legacy} no longer resolves"
        assert record.semantic_fingerprint, f"{legacy} was not backfilled"


@pytest.mark.asyncio
async def test_every_stored_rule_carries_a_fingerprint():
    db, _ = await _store()
    rows = await db.execute_query(
        "SELECT rule_id FROM unified.learned_rules WHERE semantic_fingerprint IS NULL",
        fetch_all=True) or []
    assert not rows, f"unfingerprinted rules: {[r['rule_id'] for r in rows]}"


@pytest.mark.asyncio
async def test_no_two_rules_share_a_meaning():
    db, _ = await _store()
    rows = await db.execute_query(
        "SELECT semantic_fingerprint, count(*) n FROM unified.learned_rules"
        " WHERE semantic_fingerprint IS NOT NULL"
        " GROUP BY 1 HAVING count(*) > 1", fetch_all=True) or []
    assert not rows, f"duplicate hypotheses: {[dict(r) for r in rows]}"
