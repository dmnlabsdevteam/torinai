#!/usr/bin/env python3
"""Discovering what a rule means in a vocabulary it has never seen.

Transfer is only transfer if the mapping is DERIVED from the target world. A
correspondence supplied by the experimenter measures the experimenter.

Two things a single transition cannot do, and both were refusals until they
were repaired:

    it cannot rule out a property that varies independently of the law --
    one observation is consistent with the property being part of it

    it cannot tell apart two preconditions the source rule uses symmetrically,
    and where both mappings yield the SAME rule there is nothing to tell apart

The second is the failure worth naming: refusing there is refusing to notice
that the question was empty. What must still be refused is a choice between
mappings that produce genuinely different rules.
"""

from core.learning.analogical_projection import derive_correspondence
from core.learning.rule_induction import (CandidateRule, Fact, RuleEffects,
                                          TrainingExample)

F = Fact.parse


def transition(before, action, added):
    return TrainingExample(before=tuple(F(b) for b in before) + (F(action),),
                           action=F(action),
                           after=tuple(F(b) for b in before) + (F(action),)
                           + tuple(F(a) for a in added),
                           positive=True)


SYMMETRIC = CandidateRule(
    body=frozenset({F("ACT(?x)"), F("P(?x)"), F("Q(?x)")}),
    effects=RuleEffects(add=frozenset({F("R(?x)")})),
    action=F("ACT(?x)"))


def test_symmetric_preconditions_map_either_way_to_the_same_rule():
    """Nothing to choose, so choosing is not required."""
    correspondence, why = derive_correspondence(
        SYMMETRIC, [transition(["PA(o1)", "QA(o1)"], "AA(o1)", ["RA(o1)"]),
                    transition(["PA(o2)", "QA(o2)"], "AA(o2)", ["RA(o2)"])])

    assert correspondence, why
    assert correspondence["ACT"] == "AA"
    assert correspondence["R"] == "RA"
    assert {correspondence["P"], correspondence["Q"]} == {"PA", "QA"}
    assert "same rule" in why


def test_a_property_that_comes_and_goes_is_not_part_of_the_law():
    """Present in one firing transition and absent from another, so it cannot
    be a precondition -- which one transition could never establish."""
    correspondence, why = derive_correspondence(
        SYMMETRIC, [transition(["PA(o1)", "QA(o1)", "NOISE(o1)"], "AA(o1)", ["RA(o1)"]),
                    transition(["PA(o2)", "QA(o2)"], "AA(o2)", ["RA(o2)"])])

    assert correspondence, why
    assert "NOISE" not in correspondence.values()


def test_one_transition_cannot_exclude_it_and_says_so():
    correspondence, why = derive_correspondence(
        SYMMETRIC, transition(["PA(o1)", "QA(o1)", "NOISE(o1)"], "AA(o1)", ["RA(o1)"]))

    assert not correspondence
    assert "different rules" in why


def test_mappings_that_give_different_rules_are_still_refused():
    """The asymmetric case: one precondition is retracted and the other is not,
    so which is which changes the rule and the evidence must decide it."""
    asymmetric = CandidateRule(
        body=frozenset({F("ACT(?x)"), F("P(?x)"), F("Q(?x)")}),
        effects=RuleEffects(add=frozenset({F("R(?x)")}),
                            delete=frozenset({F("P(?x)")})),
        action=F("ACT(?x)"))

    # The target never shows a retraction, so nothing names which one P is.
    correspondence, why = derive_correspondence(
        asymmetric, [transition(["PA(o1)", "QA(o1)"], "AA(o1)", ["RA(o1)"]),
                     transition(["PA(o2)", "QA(o2)"], "AA(o2)", ["RA(o2)"])])

    assert not correspondence
    assert "refusing to choose" in why


def test_a_transition_that_changes_nothing_licenses_nothing():
    still = TrainingExample(before=(F("PA(o1)"), F("AA(o1)")), action=F("AA(o1)"),
                            after=(F("PA(o1)"), F("AA(o1)")), positive=False)
    correspondence, why = derive_correspondence(SYMMETRIC, [still])
    assert not correspondence
    assert "changed anything" in why
