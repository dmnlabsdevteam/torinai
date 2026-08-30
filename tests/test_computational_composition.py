#!/usr/bin/env python3
"""Composing actions that CREATE values, across unrelated domains.

A STRIPS operator moves facts between states. It cannot say that dividing
twenty by four yields a five nothing mentioned beforehand, so a plan could
never pass through a computation -- the substrate reached exactly that ceiling
composing an average out of two folds it had derived itself, and reported
UNREACHABLE for a goal the world reached in three steps.

The repair is an operator with declared OUTPUTS and an account of where each
value comes from. What these tests are for is the claim that the repair is
general: three chains with nothing in common but their shape, and no line
anywhere that knows what DIVIDE, PARSE_NUMBER or LOOKUP mean. Every rule below
is INDUCED from demonstrations; none is written down.

    arithmetic   every value computable while planning     -> GUARANTEED
    file         a value only reading produces, then a
                 computation over it                       -> CONDITIONAL
    lookup       a value only the world holds, consumed
                 without arithmetic                        -> CONDITIONAL

If the guarantee were not carried, the third chain would report a proof that
the result is a particular value while the value is whatever the world happens
to hold -- which is the false certainty this whole layer exists to refuse.
"""

import pytest

from core.learning.rule_grounding import ground_for_problem
from core.learning.rule_induction import (BindingOrigin, Fact, InductionStatus,
                                          TrainingExample, get_rule_inducer)
from core.reasoning.temporal_reasoning import (PlanGuarantee, PlanningStatus,
                                               TemporalReasoningSystem)


def facts(*items):
    return tuple(Fact.parse(i) for i in items)


def learn(target, demonstrations, refused=()):
    """Induce one action's rule from ground before/action/after demonstrations.

    `refused` are demonstrations of the action producing NOTHING. They are what
    establishes a precondition for an action whose output is opaque: a rule
    that concludes only `NUMBER(?y)` needs no term from the body to be range
    restricted, so without them the minimal hypothesis is that parsing works
    with nothing to parse. Measured -- the plan skipped the read.

    An action whose output is DERIVED needs no such demonstration: dropping the
    literal that binds an input leaves the output unaccounted for, and range
    restriction removes the hypothesis on its own.
    """
    examples = []
    for action, before, after in demonstrations:
        act = Fact.parse(action)
        examples.append(TrainingExample(before=before + (act,), action=act,
                                        after=after + (act,), positive=True))
        examples.append(TrainingExample(before=before, action=None, after=before,
                                        positive=False))
    for action, before in refused:
        act = Fact.parse(action)
        examples.append(TrainingExample(before=before + (act,), action=act,
                                        after=before + (act,), positive=False))
    return get_rule_inducer().induce(examples, target_predicate=target)


def plan(rules, state, available, goal):
    grounding = ground_for_problem(rules, state + available, goal)
    result = TemporalReasoningSystem().plan_for_state_goal(
        [f.to_formula() for f in goal],
        {"conditions": [f.to_formula() for f in state + available]},
        grounding.to_actions())
    return grounding, result


def steps_of(result):
    return [s["action"].split("(")[0] for s in result.steps]


# --------------------------------------------------------------------------
# 1 — arithmetic: every value is computable before anything runs
# --------------------------------------------------------------------------

def arithmetic_rules():
    total = learn("NUMERATOR", [
        ("TAKE_TOTAL(a)", facts("LIST(a)", "TOTAL(a, 20)", "COUNT(a, 4)"),
         facts("LIST(a)", "TOTAL(a, 20)", "COUNT(a, 4)", "NUMERATOR(20)")),
        ("TAKE_TOTAL(b)", facts("LIST(b)", "TOTAL(b, 60)", "COUNT(b, 3)"),
         facts("LIST(b)", "TOTAL(b, 60)", "COUNT(b, 3)", "NUMERATOR(60)")),
    ])
    count = learn("DENOMINATOR", [
        ("TAKE_COUNT(a)", facts("LIST(a)", "TOTAL(a, 20)", "COUNT(a, 4)", "NUMERATOR(20)"),
         facts("LIST(a)", "TOTAL(a, 20)", "COUNT(a, 4)", "NUMERATOR(20)",
               "DENOMINATOR(4)")),
        ("TAKE_COUNT(b)", facts("LIST(b)", "TOTAL(b, 60)", "COUNT(b, 3)", "NUMERATOR(60)"),
         facts("LIST(b)", "TOTAL(b, 60)", "COUNT(b, 3)", "NUMERATOR(60)",
               "DENOMINATOR(3)")),
    ])
    # The registers are shown holding values that are NOT this list's total and
    # count, because otherwise "divide the numerator by the denominator" and
    # "divide the total by the count" are the same claim on every
    # demonstration, and induction rightly reports both.
    divide = learn("RESULT", [
        ("DIVIDE", facts("LIST(a)", "TOTAL(a, 9)", "COUNT(a, 7)", "NUMERATOR(20)",
               "DENOMINATOR(4)"),
         facts("LIST(a)", "TOTAL(a, 9)", "COUNT(a, 7)", "NUMERATOR(20)",
               "DENOMINATOR(4)", "RESULT(5)")),
        ("DIVIDE", facts("LIST(b)", "TOTAL(b, 2)", "COUNT(b, 8)", "NUMERATOR(60)",
               "DENOMINATOR(3)"),
         facts("LIST(b)", "TOTAL(b, 2)", "COUNT(b, 8)", "NUMERATOR(60)",
               "DENOMINATOR(3)", "RESULT(20)")),
        ("DIVIDE", facts("LIST(c)", "TOTAL(c, 5)", "COUNT(c, 1)", "NUMERATOR(21)",
               "DENOMINATOR(3)"),
         facts("LIST(c)", "TOTAL(c, 5)", "COUNT(c, 1)", "NUMERATOR(21)",
               "DENOMINATOR(3)", "RESULT(7)")),
    ])
    return total, count, divide


def test_division_is_learned_as_a_produced_value_not_a_precondition():
    _, _, divide = arithmetic_rules()
    assert divide.status is InductionStatus.RULE_LEARNED, divide.detail
    rule = divide.rule
    assert len(rule.outputs) == 1
    output = rule.outputs[0]
    assert output.origin is BindingOrigin.DERIVED
    assert output.function == "divide"
    # The quotient is nowhere in the body: it did not have to exist first.
    assert output.variable not in {v for f in rule.body for v in f.variables}
    assert rule.is_range_restricted


def test_an_average_plans_through_a_computed_value_and_is_proved():
    total, count, divide = arithmetic_rules()
    rules = [r.rule for r in (total, count, divide)]
    state = facts("LIST(l1)", "TOTAL(l1, 20)", "COUNT(l1, 4)")
    available = facts("TAKE_TOTAL(l1)", "TAKE_COUNT(l1)", "DIVIDE")

    grounding, result = plan(rules, state, available, facts("RESULT(5)"))

    assert grounding.complete
    assert result.status is PlanningStatus.PLAN_FOUND, result.reason
    assert result.guarantee is PlanGuarantee.GUARANTEED
    assert result.deferred == []
    assert steps_of(result) == ["TAKE_TOTAL", "TAKE_COUNT", "DIVIDE"]


def test_a_division_with_no_answer_takes_no_step():
    """Dividing by zero is a computation with no result, not a result of zero.

    Checked where the computation happens. The value is resolved when the step
    is applied, not when the operator is built, so an operator whose divisor
    turns out to be zero exists and simply never applies.
    """
    total, count, divide = arithmetic_rules()
    rules = [r.rule for r in (total, count, divide)]
    state = facts("LIST(l1)", "TOTAL(l1, 20)", "COUNT(l1, 0)")
    available = facts("TAKE_TOTAL(l1)", "TAKE_COUNT(l1)", "DIVIDE")

    _, result = plan(rules, state, available, facts("RESULT(0)"))

    assert result.status is PlanningStatus.UNREACHABLE, result.reason
    assert not result.steps


# --------------------------------------------------------------------------
# 2 — a file: a value only reading produces, then arithmetic over it
# --------------------------------------------------------------------------

def file_rules():
    read = learn("TEXT", [
        ("READ(one)", facts("FILE(one)"), facts("FILE(one)", "TEXT(alpha)")),
        ("READ(two)", facts("FILE(two)"), facts("FILE(two)", "TEXT(beta)")),
    ], refused=[("READ(three)", facts("FACTOR(2)"))])
    parse = learn("NUMBER", [
        ("PARSE_NUMBER", facts("TEXT(alpha)"), facts("TEXT(alpha)", "NUMBER(21)")),
        ("PARSE_NUMBER", facts("TEXT(beta)"), facts("TEXT(beta)", "NUMBER(5)")),
    ], refused=[("PARSE_NUMBER", facts("FILE(one)"))])
    # Three demonstrations, because with the factor fixed at two, doubling and
    # adding a number to itself are the same hypothesis.
    multiply = learn("DOUBLED", [
        ("MULTIPLY", facts("NUMBER(21)", "FACTOR(2)"),
         facts("NUMBER(21)", "FACTOR(2)", "DOUBLED(42)")),
        ("MULTIPLY", facts("NUMBER(5)", "FACTOR(2)"),
         facts("NUMBER(5)", "FACTOR(2)", "DOUBLED(10)")),
        ("MULTIPLY", facts("NUMBER(5)", "FACTOR(3)"),
         facts("NUMBER(5)", "FACTOR(3)", "DOUBLED(15)")),
    ])
    write = learn("WRITTEN", [
        ("WRITE", facts("DOUBLED(42)"), facts("DOUBLED(42)", "WRITTEN(42)")),
        ("WRITE", facts("DOUBLED(10)"), facts("DOUBLED(10)", "WRITTEN(10)")),
    ])
    return read, parse, multiply, write


def test_a_value_no_function_explains_is_an_action_output():
    read, parse, _, _ = file_rules()
    for result in (read, parse):
        assert result.status is InductionStatus.RULE_LEARNED, result.detail
        assert len(result.rule.outputs) == 1
        assert result.rule.outputs[0].origin is BindingOrigin.ACTION_OUTPUT
        assert not result.rule.outputs[0].is_predictable


def test_arithmetic_over_a_value_that_does_not_exist_yet_still_plans():
    read, parse, multiply, write = file_rules()
    assert multiply.status is InductionStatus.RULE_LEARNED, multiply.detail
    assert multiply.rule.outputs[0].function == "multiply"

    rules = [r.rule for r in (read, parse, multiply, write)]
    state = facts("FILE(one)", "FACTOR(2)")
    available = facts("READ(one)", "PARSE_NUMBER", "MULTIPLY", "WRITE")

    grounding, result = plan(rules, state, available, facts("WRITTEN(84)"))

    assert result.status is PlanningStatus.PLAN_FOUND, result.reason
    assert steps_of(result) == ["READ", "PARSE_NUMBER", "MULTIPLY", "WRITE"]
    # Structurally proved, and the exact number is not: 84 is what the plan
    # would write only if the file holds 42.
    assert result.guarantee is PlanGuarantee.CONDITIONAL
    assert result.deferred
    # The consumers were offered PARTIALLY ground: what a read returns has no
    # term until the read happens, so nothing could have enumerated it.
    assert any(o.open_slots for o in grounding.operators)


# --------------------------------------------------------------------------
# 3 — a lookup: a value the world holds, consumed without arithmetic
# --------------------------------------------------------------------------

def lookup_rules():
    lookup = learn("VALUE", [
        ("LOOKUP(alpha)", facts("KEY(alpha)"), facts("KEY(alpha)", "VALUE(seven)")),
        ("LOOKUP(beta)", facts("KEY(beta)"), facts("KEY(beta)", "VALUE(three)")),
    ], refused=[("LOOKUP(gamma)", facts("THRESHOLD(five)"))])
    compare = learn("OVER", [
        ("COMPARE", facts("VALUE(seven)", "THRESHOLD(five)"),
         facts("VALUE(seven)", "THRESHOLD(five)", "OVER(yes)")),
        ("COMPARE", facts("VALUE(three)", "THRESHOLD(five)"),
         facts("VALUE(three)", "THRESHOLD(five)", "OVER(no)")),
    ], refused=[("COMPARE", facts("THRESHOLD(five)")),
                ("COMPARE", facts("VALUE(seven)"))])
    branch = learn("CHOSEN", [
        ("BRANCH", facts("OVER(yes)"), facts("OVER(yes)", "CHOSEN(yes)")),
        ("BRANCH", facts("OVER(no)"), facts("OVER(no)", "CHOSEN(no)")),
    ], refused=[("BRANCH", facts("VALUE(seven)"))])
    return lookup, compare, branch


def test_a_chain_of_values_the_world_holds_plans_but_is_never_proved():
    lookup, compare, branch = lookup_rules()
    for result in (lookup, compare, branch):
        assert result.status is InductionStatus.RULE_LEARNED, result.detail

    rules = [r.rule for r in (lookup, compare, branch)]
    state = facts("KEY(alpha)", "THRESHOLD(five)")
    available = facts("LOOKUP(alpha)", "COMPARE", "BRANCH")

    _, result = plan(rules, state, available, facts("CHOSEN(yes)"))

    assert result.status is PlanningStatus.PLAN_FOUND, result.reason
    assert steps_of(result) == ["LOOKUP", "COMPARE", "BRANCH"]
    assert result.guarantee is PlanGuarantee.CONDITIONAL
    # Nothing here can prove the value is over the threshold; a guarantee would
    # be a claim about a world the plan has not looked at yet.
    assert not result.proved


# --------------------------------------------------------------------------
# what must still be refused
# --------------------------------------------------------------------------

def test_a_value_from_nowhere_is_still_refused():
    """Provenance, not permission: an effect term nothing accounts for."""
    from core.learning.rule_induction import CandidateRule, RuleEffects

    invented = CandidateRule(
        body=frozenset({Fact("P", ("?x",))}),
        effects=RuleEffects(add=frozenset({Fact("MAGIC", ("?y",))})))
    assert not invented.is_range_restricted
    assert invented.binding_origins()["?y"] is BindingOrigin.UNBOUND


def test_an_output_may_not_be_a_value_the_body_already_binds():
    from core.learning.rule_induction import (CandidateRule, OutputBinding,
                                              RuleEffects)

    with pytest.raises(ValueError, match="already bound"):
        CandidateRule(
            body=frozenset({Fact("N", ("?n",)), Fact("D", ("?d",)), Fact("GO", ())}),
            effects=RuleEffects(add=frozenset({Fact("R", ("?n",))})),
            action=Fact("GO", ()),
            outputs=(OutputBinding("?n", BindingOrigin.DERIVED, function="divide",
                                   inputs=("?n", "?d")),))


def test_which_function_produces_the_value_is_part_of_the_rule_s_identity():
    """Two rules that agree on every literal and disagree on the computation
    are two predictions, not one rule stored twice."""
    from core.learning.rule_identity import semantic_fingerprint
    from core.learning.rule_induction import (CandidateRule, OutputBinding,
                                              RuleEffects)

    body = frozenset({Fact("GO", ()), Fact("N", ("?n",)), Fact("D", ("?d",))})
    effects = RuleEffects(add=frozenset({Fact("R", ("?q",))}))

    def with_function(name):
        return CandidateRule(body, effects, Fact("GO", ()),
                             (OutputBinding("?q", BindingOrigin.DERIVED,
                                            function=name, inputs=("?n", "?d")),))

    assert (semantic_fingerprint(with_function("divide"))
            != semantic_fingerprint(with_function("subtract")))


def test_a_computation_survives_being_stored_and_read_back():
    """A rule whose output is dropped in transit comes back meaning something
    else -- and, having lost the account of where its value comes from, stops
    being range restricted at all."""
    from core.learning.rule_store import from_json, to_json

    _, _, divide = arithmetic_rules()
    restored = from_json(to_json(divide.rule))

    assert restored.outputs == divide.rule.outputs
    assert restored.is_range_restricted
    assert restored == divide.rule


def test_a_rule_stored_before_outputs_existed_still_reads():
    from core.learning.rule_store import from_json

    older = {
        "schema_version": 2,
        "body": [{"predicate": "AT", "args": ["?X0", "?X1"]},
                 {"predicate": "MOVE", "args": ["?X0", "?X1"]}],
        "add_effects": [{"predicate": "AT", "args": ["?X0", "?X1"]}],
        "delete_effects": [],
        "action": {"predicate": "MOVE", "args": ["?X0", "?X1"]},
    }
    assert from_json(older).outputs == ()


def test_an_analogy_carries_the_computation_across():
    """Projecting a rule that computes a value must not project one that
    concludes about a term nothing accounts for."""
    from core.learning.analogical_projection import ProjectionOutcome, project

    _, _, divide = arithmetic_rules()
    result = project(
        divide.rule, source_rule_id="r_divide", source_domain="ledger",
        target_domain="telemetry",
        correspondences={"DIVIDE": "AVERAGE", "NUMERATOR": "TOTAL_READING",
                         "DENOMINATOR": "SAMPLE_COUNT", "RESULT": "MEAN_READING"})

    assert result.outcome is ProjectionOutcome.FULL_PROJECTION, result.detail
    assert result.rule.outputs == divide.rule.outputs
    assert result.rule.is_range_restricted


def test_running_the_same_action_twice_yields_two_different_unknowns():
    """Two reads of a file are two answers.

    One unknown for the whole operator would make the second read produce a
    state the search had already seen, and it would be discarded as a
    repetition of the first.
    """
    read = learn("TEXT", [
        ("READ(one)", facts("FILE(one)"), facts("FILE(one)", "TEXT(alpha)")),
        ("READ(two)", facts("FILE(two)"), facts("FILE(two)", "TEXT(beta)")),
    ], refused=[("READ(three)", facts("SLOT(a)"))])
    # Storing CONSUMES the text, so filling a second slot needs a second read.
    # Learned unscoped, because the retraction is half of what the action does.
    store = learn(None, [
        ("STORE(a)", facts("SLOT(a)", "TEXT(alpha)"),
         facts("SLOT(a)", "HELD(a, alpha)")),
        ("STORE(b)", facts("SLOT(b)", "TEXT(beta)"),
         facts("SLOT(b)", "HELD(b, beta)")),
    ])
    assert read.status is InductionStatus.RULE_LEARNED, read.detail
    assert store.status is InductionStatus.RULE_LEARNED, store.detail

    rules = [read.rule, store.rule]
    state = facts("FILE(one)", "SLOT(a)", "SLOT(b)")
    available = facts("READ(one)", "STORE(a)", "STORE(b)")

    _, result = plan(rules, state, available, facts("HELD(a, x)", "HELD(b, y)"))

    assert result.status is PlanningStatus.PLAN_FOUND, result.reason
    assert steps_of(result).count("READ") == 2, steps_of(result)
    unknowns = [p["term"] for step in result.trace for p in step["produced"]]
    assert len(unknowns) == len(set(unknowns)), unknowns


def test_a_computed_value_can_be_traced_back_to_what_the_problem_supplied():
    """The chain is read out of what the planner recorded while applying the
    steps -- an account of a derivation that cannot be checked against the
    derivation is prose."""
    total, count, divide = arithmetic_rules()
    rules = [r.rule for r in (total, count, divide)]
    state = facts("LIST(l1)", "TOTAL(l1, 20)", "COUNT(l1, 4)")
    available = facts("TAKE_TOTAL(l1)", "TAKE_COUNT(l1)", "DIVIDE")

    _, result = plan(rules, state, available, facts("RESULT(5)"))
    rendered = "\n".join(TemporalReasoningSystem.explain_value(result, "5"))

    assert "divide(20, 4)" in rendered
    assert "step 3, DIVIDE" in rendered
    # both operands, the step that put each one there, and where it read it
    assert "20 <- NUMERATOR(20)  asserted by step 1" in rendered
    assert "4 <- DENOMINATOR(4)  asserted by step 2" in rendered
    assert "TOTAL(l1, 20)  supplied by the problem" in rendered
    assert "COUNT(l1, 4)  supplied by the problem" in rendered


def test_a_value_the_plan_cannot_predict_says_so_in_its_own_derivation():
    read, parse, multiply, write = file_rules()
    rules = [r.rule for r in (read, parse, multiply, write)]

    _, result = plan(rules, facts("FILE(one)", "FACTOR(2)"),
                     facts("READ(one)", "PARSE_NUMBER", "MULTIPLY", "WRITE"),
                     facts("WRITTEN(84)"))

    doubled = next(p["term"] for step in result.trace for p in step["produced"]
                   if p.get("function") == "multiply")
    rendered = "\n".join(TemporalReasoningSystem.explain_value(result, doubled))

    assert "multiply(" in rendered
    assert "FACTOR(2)  supplied by the problem" in rendered
    # and the half it never knew, named as such rather than given an origin
    assert "not predictable; the value arrived when the step ran" in rendered
    assert "FILE(one)  supplied by the problem" in rendered


def test_a_term_the_plan_never_produced_is_not_given_an_origin():
    total, count, divide = arithmetic_rules()
    rules = [r.rule for r in (total, count, divide)]
    _, result = plan(rules, facts("LIST(l1)", "TOTAL(l1, 20)", "COUNT(l1, 4)"),
                     facts("TAKE_TOTAL(l1)", "TAKE_COUNT(l1)", "DIVIDE"),
                     facts("RESULT(5)"))

    assert "supplied by the problem" in "\n".join(
        TemporalReasoningSystem.explain_value(result, "20"))
    assert "not produced by this plan" in "\n".join(
        TemporalReasoningSystem.explain_value(result, "999"))
