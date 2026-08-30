"""Acquiring an executable rule from demonstrations, with no model involved.

The capability under test is the one the audit found missing: the substrate
could execute symbolic knowledge at zero model calls and could not acquire any.
Every test here runs under STRICT_MODEL_FREE and asserts the census afterwards,
so a regression that quietly reintroduces a model call fails here rather than
being discovered in an experiment's results.
"""
import pytest

from core.learning.rule_induction import (
    CandidateRule, Fact, InductionStatus, RuleEffects, RuleInducer,
    TrainingExample, applies, generalize, get_rule_inducer, is_variable,
    match_body, successor_state,
)
from core.model_policy import (
    ModelPolicy, assert_model_free, reset_model_telemetry, set_model_policy,
)

F = Fact.parse


@pytest.fixture(autouse=True)
def strict():
    previous = set_model_policy(ModelPolicy.STRICT_MODEL_FREE)
    reset_model_telemetry()
    yield
    assert_model_free("rule induction")
    set_model_policy(previous)
    reset_model_telemetry()


@pytest.fixture
def inducer():
    return RuleInducer()


def kite_positive(x, y, evidence_id):
    before = (F(f"NAL({x})"), F(f"VEX({x},{y})"), F(f"TOR({y})"))
    return TrainingExample(
        before=before, action=F(f"KEM({x},{y})"),
        after=before + (F(f"ZOR({x},{y})"),), evidence_id=evidence_id,
    )


def kite_negative(before, action, evidence_id):
    return TrainingExample(before=before, action=action, after=before,
                           positive=False, evidence_id=evidence_id)


@pytest.fixture
def kite_discriminating():
    """Two demonstrations plus one counter-demonstration per precondition."""
    return [
        kite_positive("a", "b", "d1"),
        kite_positive("c", "d", "d2"),
        kite_negative((F("VEX(e,f)"), F("TOR(f)")), F("KEM(e,f)"), "no_NAL"),
        kite_negative((F("NAL(g)"), F("TOR(h)")), F("KEM(g,h)"), "no_VEX"),
        kite_negative((F("NAL(i)"), F("VEX(i,j)")), F("KEM(i,j)"), "no_TOR"),
        kite_negative((F("NAL(k)"), F("VEX(k,l)"), F("TOR(l)")), None, "no_KEM"),
    ]


# ------------------------------------------------------------------ the claim

def test_the_invented_rule_is_acquired_from_demonstrations(inducer, kite_discriminating):
    """No prior semantics: NAL/VEX/TOR/KEM/ZOR appear nowhere in the substrate,
    so nothing here can come from pretrained meaning attached to the symbols."""
    result = inducer.induce(kite_discriminating)

    assert result.status is InductionStatus.RULE_LEARNED, result.detail
    rule = result.rule
    assert rule.effects.add == frozenset({Fact("ZOR", ("?X0", "?X1"))})
    assert rule.effects.delete == frozenset()
    assert {f.predicate for f in rule.body} == {"NAL", "VEX", "TOR", "KEM"}
    assert rule.is_range_restricted


def test_an_unseen_case_is_solved_by_the_learned_rule(inducer, kite_discriminating):
    """Test 2. The entities m and n were never demonstrated."""
    rule = inducer.induce(kite_discriminating).rule
    unseen = TrainingExample(
        before=(F("NAL(m)"), F("VEX(m,n)"), F("TOR(n)")), action=F("KEM(m,n)"),
    )
    assert [e.add for e in applies(rule, unseen)] == [frozenset({Fact("ZOR", ("m", "n"))})]


def test_the_rule_does_not_fire_when_a_precondition_is_absent(inducer, kite_discriminating):
    """Solving the unseen case is only meaningful if the rule can also decline."""
    rule = inducer.induce(kite_discriminating).rule
    partial = TrainingExample(
        before=(F("NAL(p)"), F("VEX(p,q)")), action=F("KEM(p,q)"),
    )
    assert applies(rule, partial) == []


# --------------------------------------------------------------- version space

def test_underdetermined_demonstrations_yield_hypotheses_not_a_guess(inducer):
    """Test 3. With every predicate co-occurring, which subset causes ZOR is
    genuinely unknown. Choosing one would manufacture confidence."""
    result = inducer.induce([kite_positive("a", "b", "d1"), kite_positive("c", "d", "d2")])

    assert result.status is InductionStatus.MULTIPLE_HYPOTHESES
    assert len(result.candidates) > 1
    assert "separating them would decide" in result.detail


def test_a_discriminating_demonstration_collapses_the_version_space(inducer, kite_discriminating):
    ambiguous = inducer.induce(kite_discriminating[:2])
    resolved = inducer.induce(kite_discriminating)

    assert ambiguous.status is InductionStatus.MULTIPLE_HYPOTHESES
    assert resolved.status is InductionStatus.RULE_LEARNED
    assert any(c.body <= resolved.rule.body for c in ambiguous.candidates), (
        "the survivor must be a specialization of a hypothesis the ambiguous "
        "evidence permitted, not an unrelated rule"
    )
    assert len(resolved.rule.body) > max(len(c.body) for c in ambiguous.candidates), (
        "counter-demonstrations constrain, so the surviving body must be stricter"
    )


def test_one_demonstration_is_not_evidence_of_a_rule(inducer):
    result = inducer.induce([kite_positive("a", "b", "d1")])
    assert result.status is InductionStatus.INSUFFICIENT_EVIDENCE
    assert result.rule is None


def test_conflicting_consequents_are_reported_not_averaged(inducer):
    before = (F("NAL(a)"),)
    result = inducer.induce([
        TrainingExample(before=before, action=F("KEM(a)"),
                        after=before + (F("ZOR(a)"),), evidence_id="d1"),
        TrainingExample(before=(F("NAL(c)"),), action=F("KEM(c)"),
                        after=(F("NAL(c)"), F("QUX(c)")), evidence_id="d2"),
    ])
    assert result.status is InductionStatus.CONTRADICTORY_EVIDENCE


def test_a_rule_refuted_by_every_generalization_is_reported_as_no_rule(inducer):
    """The same antecedent both producing and not producing the effect leaves
    nothing consistent to learn."""
    before = (F("NAL(a)"), F("VEX(a,b)"))
    contradiction = [
        kite_positive("a", "b", "d1"),
        kite_positive("c", "d", "d2"),
        TrainingExample(before=(F("NAL(m)"), F("VEX(m,n)"), F("TOR(n)")),
                        action=F("KEM(m,n)"),
                        after=(F("NAL(m)"), F("VEX(m,n)"), F("TOR(n)")),
                        positive=False, evidence_id="same_state_no_effect"),
    ]
    assert inducer.induce(contradiction).status is InductionStatus.NO_RULE


# ------------------------------------------------------------- state transitions

def test_a_transition_rule_is_learned_and_chains(inducer):
    """Test 6's precondition: learned steps compose into an unseen procedure."""
    def move(who, a, b, evidence_id, opened=True, path=True, acted=True):
        before = [F(f"AT({who},{a})")]
        if path:
            before.append(F(f"PATH({a},{b})"))
        if opened:
            before.append(F(f"OPEN({b})"))
        before = tuple(before)
        ok = opened and path and acted
        return TrainingExample(
            before=before,
            action=F(f"MOVE({who},{a},{b})") if acted else None,
            after=before + (F(f"AT({who},{b})"),) if ok else before,
            positive=ok, evidence_id=evidence_id,
        )

    rule = inducer.induce([
        move("a", "R1", "R2", "t1"), move("b", "R3", "R4", "t2"),
        move("c", "R5", "R6", "n1", opened=False),
        move("d", "R7", "R8", "n2", path=False),
        move("e", "R9", "R10", "n3", acted=False),
    ]).rule
    assert rule is not None
    assert {f.predicate for f in rule.effects.add} == {"AT"}

    first = TrainingExample(
        before=(F("AT(z,HALL)"), F("PATH(HALL,LAB)"), F("OPEN(LAB)")),
        action=F("MOVE(z,HALL,LAB)"),
    )
    step_one = applies(rule, first)
    assert [e.add for e in step_one] == [frozenset({Fact("AT", ("z", "LAB"))})]

    reached = successor_state(frozenset(first.before), step_one)
    second = TrainingExample(
        before=tuple(reached | {F("PATH(LAB,VAULT)"), F("OPEN(VAULT)")}),
        action=F("MOVE(z,LAB,VAULT)"),
    )
    assert [e.add for e in applies(rule, second)] == [frozenset({Fact("AT", ("z", "VAULT"))})]


# ------------------------------------------------------------------- integrity

def test_induction_is_order_independent(inducer, kite_discriminating):
    """A failed experiment must be diagnosable, which requires the learner not
    to depend on the order demonstrations happened to arrive in."""
    forward = inducer.induce(kite_discriminating).rule
    backward = inducer.induce(list(reversed(kite_discriminating))).rule
    assert forward == backward


def test_repeated_evidence_ids_count_once(inducer):
    """Ten derived copies of one demonstration are one root observation."""
    duplicated = [kite_positive("a", "b", "d1")] * 5 + [kite_positive("c", "d", "d2")]
    result = inducer.induce(duplicated)
    assert result.supporting_evidence == ["d1", "d2"]


def test_a_rule_may_not_conclude_about_an_unbound_entity(inducer, kite_discriminating):
    rule = inducer.induce(kite_discriminating).rule
    assert rule.is_range_restricted
    assert not CandidateRule(
        body=frozenset({Fact("NAL", ("?X",))}),
        effects=RuleEffects(add={Fact("ZOR", ("?X", "?Y"))}),
    ).is_range_restricted


def test_demonstrations_must_be_ground():
    """A teacher supplying a variable is stating the rule, not demonstrating it."""
    with pytest.raises(ValueError):
        TrainingExample(before=(Fact("NAL", ("?X",)),), action=F("KEM(a)"))


def test_facts_render_back_to_the_parsers_surface_syntax():
    """Learned rules stay consumable by the existing inference machinery."""
    from core.agents.logical.logical_integration import LogicalFormulaParser

    parser = LogicalFormulaParser()
    for text in ("NAL(a)", "VEX(a, b)", "P"):
        assert parser.is_formal(Fact.parse(text).to_formula())


def test_generalization_aligns_arguments_consistently():
    left = CandidateRule(frozenset({Fact("NAL", ("a",)), Fact("VEX", ("a", "b"))}),
                         RuleEffects(add={Fact("ZOR", ("a", "b"))}))
    right = CandidateRule(frozenset({Fact("NAL", ("c",)), Fact("VEX", ("c", "d"))}),
                          RuleEffects(add={Fact("ZOR", ("c", "d"))}))
    generalized = generalize(left, right)

    assert next(iter(generalized.effects.add)).args[0] == next(
        f.args[0] for f in generalized.body if f.predicate == "NAL"
    ), "a and c must become the same variable in head and body"


def test_matching_enumerates_every_binding():
    """Collapsing to a boolean would hide a rule firing twice."""
    state = frozenset({Fact("VEX", ("a", "b")), Fact("VEX", ("c", "d"))})
    assert len(match_body([Fact("VEX", ("?X", "?Y"))], state)) == 2


def test_variables_are_marked_not_inferred():
    assert is_variable("?X") and not is_variable("X")


def test_a_retraction_is_learned_as_a_delete_effect(inducer):
    """A demonstration where the mover leaves the room it was in. Without
    delete effects a chained transition puts one entity in two rooms at once."""
    def move(who, a, b, evidence_id, opened=True, acted=True):
        before = [F(f"AT({who},{a})"), F(f"PATH({a},{b})")]
        if opened:
            before.append(F(f"OPEN({b})"))
        before = tuple(before)
        ok = opened and acted
        after = (tuple(f for f in before if f != F(f"AT({who},{a})"))
                 + (F(f"AT({who},{b})"),)) if ok else before
        return TrainingExample(
            before=before, action=F(f"MOVE({who},{a},{b})") if acted else None,
            after=after, positive=ok, evidence_id=evidence_id,
        )

    rule = inducer.induce([
        move("a", "R1", "R2", "t1"), move("b", "R3", "R4", "t2"),
        move("c", "R5", "R6", "n1", opened=False),
        move("d", "R7", "R8", "n2", acted=False),
    ]).rule

    assert rule is not None
    assert {f.predicate for f in rule.effects.add} == {"AT"}
    assert {f.predicate for f in rule.effects.delete} == {"AT"}, (
        "leaving the origin must be learned, not just arriving"
    )

    start = frozenset({F("AT(z,HALL)"), F("PATH(HALL,LAB)"), F("OPEN(LAB)")})
    example = TrainingExample(before=tuple(start), action=F("MOVE(z,HALL,LAB)"))
    reached = successor_state(start, applies(rule, example))

    assert F("AT(z,LAB)") in reached
    assert F("AT(z,HALL)") not in reached, "the entity must not be in two places"


# ------------------------------------------------------- structural invariance

def test_the_learner_is_invariant_under_predicate_renaming(inducer, kite_discriminating):
    """induce(D) ≅ rename⁻¹(induce(rename(D))).

    Attacks accidental surface memorization: if the learner is operating on
    relational structure, meaningless symbol names cannot change the rule it
    finds. Any predicate-specific behaviour shows up here as a topology that
    fails to map back.
    """
    renaming = {"NAL": "P17", "VEX": "Q42", "TOR": "R8", "KEM": "S91", "ZOR": "T3"}
    inverse = {v: k for k, v in renaming.items()}

    def rename_fact(fact, table):
        return Fact(table.get(fact.predicate, fact.predicate), fact.args)

    def rename_example(example, table):
        return TrainingExample(
            before=tuple(rename_fact(f, table) for f in example.before),
            action=rename_fact(example.action, table) if example.action else None,
            after=tuple(rename_fact(f, table) for f in example.after),
            positive=example.positive, evidence_id=example.evidence_id,
        )

    direct = inducer.induce(kite_discriminating).rule
    renamed = inducer.induce(
        [rename_example(e, renaming) for e in kite_discriminating]
    ).rule

    assert direct is not None and renamed is not None
    assert {f.predicate for f in renamed.body} == set(renaming[p] for p in
                                                      {f.predicate for f in direct.body})

    mapped_back = CandidateRule(
        body=frozenset(rename_fact(f, inverse) for f in renamed.body),
        effects=RuleEffects(
            add=frozenset(rename_fact(f, inverse) for f in renamed.effects.add),
            delete=frozenset(rename_fact(f, inverse) for f in renamed.effects.delete),
        ),
        action=rename_fact(renamed.action, inverse) if renamed.action else None,
    )
    assert mapped_back == direct, (
        "the learned rule differs under a bijective renaming, so the learner is "
        "keying on symbol identity rather than relational structure"
    )
