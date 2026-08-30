#!/usr/bin/env python3
"""One authority for binding variables to terms, and the oracle that pins it.

Deduction was implemented twice and the two disagreed about whether a rule
applies. `core/learning/rule_induction.py` unified properly;
`DeductiveReasoningStrategy._apply_rule` tested whether the rule's condition
text was a SUBSTRING of the premise, variable name included -- so no rule
containing a variable could ever fire, and the engine reported zero conclusions
with no error for every reasoning type. The coordinator routed to that one.

The oracle below is the permanent pin. A substring implementation cannot
satisfy it, and `test_substring_containment_cannot_satisfy_the_oracle` proves
that rather than asserting it.
"""

import asyncio

import pytest

from core.learning.rule_induction import Fact
from core.learning.rule_induction import match_body as learning_match_body
from core.reasoning.abstract_reasoning_engine import (DeductiveReasoningStrategy,
                                                      ReasoningContext,
                                                      ReasoningPremise,
                                                      ReasoningType)
from core.reasoning.unification import (Atom, apply_substitution, entails,
                                        match_body, match_literal, unify)

# THE ORACLE.
#     premise:  HUMAN(socrates)
#     rule:     HUMAN(?X) -> MORTAL(?X)
#     expected: ?X = socrates, MORTAL(socrates)
PREMISE = "HUMAN(socrates)"
RULE = "HUMAN(?X) -> MORTAL(?X)"
EXPECTED = "MORTAL(socrates)"


def test_the_oracle_at_the_level_of_the_unifier():
    bindings = match_body([Atom.parse("HUMAN(?X)")], [Atom.parse(PREMISE)])
    assert bindings == [{"?X": "socrates"}]
    derived = apply_substitution(Atom.parse("MORTAL(?X)"), bindings[0])
    assert derived.to_formula() == EXPECTED
    assert derived.is_ground


@pytest.mark.asyncio
async def test_the_oracle_through_the_deductive_strategy():
    """The end the coordinator actually reaches."""
    strategy = DeductiveReasoningStrategy()
    premise = ReasoningPremise(premise_id="p1", statement=PREMISE, confidence=1.0)
    context = ReasoningContext(
        context_id="oracle", domain="logic", problem_type="deduction",
        premises=[premise], rules=[RULE],
        allowed_reasoning_types=[ReasoningType.DEDUCTIVE])

    assert strategy.is_applicable(context)
    conclusions = await strategy.reason(context)
    assert conclusions, "the deductive strategy produced nothing for the oracle"
    assert any(c.statement == EXPECTED for c in conclusions), \
        [c.statement for c in conclusions]


def test_substring_containment_cannot_satisfy_the_oracle():
    """Proves the oracle discriminates, rather than asserting that it does.

    This is the exact test the retired implementation performed.
    """
    condition = "HUMAN(?X)".lower()
    assert condition not in PREMISE.lower(), (
        "substring containment matched the oracle, so the oracle no longer "
        "distinguishes real unification from string comparison")


def test_if_then_prose_form_reaches_the_same_conclusion():
    strategy = DeductiveReasoningStrategy()
    parsed = strategy._split_rule("If HUMAN(?X) then MORTAL(?X)")
    assert parsed is not None
    body, head = parsed
    assert [a.to_formula() for a in body] == ["HUMAN(?X)"]
    assert head.to_formula() == "MORTAL(?X)"


def test_a_variable_cannot_bind_two_different_constants():
    assert unify(Atom.parse("LIKES(?X, ?X)"), Atom.parse("LIKES(ann, bob)")) is None
    assert unify(Atom.parse("LIKES(?X, ?X)"), Atom.parse("LIKES(ann, ann)")) == {"?X": "ann"}


def test_arity_and_predicate_must_agree():
    assert unify(Atom.parse("P(?X)"), Atom.parse("P(a, b)")) is None
    assert unify(Atom.parse("P(?X)"), Atom.parse("Q(a)")) is None


def test_bindings_are_never_mutated_across_branches():
    """A caller enumerating alternatives must be able to abandon one branch
    without having corrupted the others."""
    original = {"?Y": "b"}
    unify(Atom.parse("P(?X)"), Atom.parse("P(a)"), original)
    assert original == {"?Y": "b"}


def test_a_multi_literal_body_enumerates_every_solution():
    state = [Atom.parse("PARENT(ann, bob)"), Atom.parse("PARENT(bob, cid)"),
             Atom.parse("PARENT(ann, dee)")]
    solutions = match_body([Atom.parse("PARENT(?X, ?Y)"), Atom.parse("PARENT(?Y, ?Z)")], state)
    assert solutions == [{"?X": "ann", "?Y": "bob", "?Z": "cid"}]
    assert entails([Atom.parse("PARENT(ann, ?Y)")], state)
    assert len(match_literal(Atom.parse("PARENT(ann, ?Y)"), state)) == 2


def test_learning_and_reasoning_share_one_implementation():
    """Not two implementations kept in agreement -- one function."""
    assert learning_match_body is match_body


def test_the_protocol_spans_both_subsystems_without_either_importing_the_other():
    """A reasoning Atom pattern binds against a learning Fact ground."""
    assert match_body([Atom.parse("HUMAN(?X)")], [Fact.parse(PREMISE)]) == [{"?X": "socrates"}]
    assert match_body([Fact.parse("HUMAN(?X)")], [Atom.parse(PREMISE)]) == [{"?X": "socrates"}]


def test_an_unrepresentable_premise_is_not_a_failed_match():
    """"I could not read this" and "this does not follow" are different
    answers and must not share a return value."""
    strategy = DeductiveReasoningStrategy()
    assert strategy._as_atom("Socrates is human") is None
    assert strategy._as_atom("") is None
    assert strategy._split_rule("some prose with no implication") is None
