#!/usr/bin/env python3
"""Arithmetic in the induction language, un-deferred.

Numbers were excluded from `Fact` on purpose while relational induction was
proved -- admitting typed terms early would have given a failed induction test
several possible explanations instead of one. That proof is done, so the
restriction is lifted IN THE INDUCTION OWNER rather than by standing a second
numeric pattern-learner beside it: "what has Torin generalized" keeps one
answer.

The language stays FUNCTION-FREE. A number is a constant term, arithmetic
enters as background RELATIONS, and a learned rule is still a Horn clause.
"""

import pytest

from core.learning.learning_authority import get_learning_authority
from core.learning.rule_induction import (Fact, InductionStatus, canonical_term,
                                          arithmetic_background, is_number)
from core.learning.rule_identity import semantic_fingerprint
from core.reasoning.unification import match_body


# ---- terms ---------------------------------------------------------------

def test_numbers_are_admissible_terms():
    assert Fact.parse("PLUS(5, 4, 9)").args == ("5", "4", "9")
    assert Fact.parse("VALUE(t1, 5)").args == ("t1", "5")
    assert Fact.parse("P(-3)").args == ("-3",)


def test_one_spelling_per_value():
    """Without this a rule learned over 5 would not unify with a fact stating
    5.0, and two identical rules would carry different fingerprints."""
    assert Fact.parse("P(5.0)") == Fact.parse("P(5)")
    assert canonical_term("05") == "5"
    assert is_number("-3.5") and not is_number("t1")


def test_a_term_that_is_neither_identifier_nor_number_is_still_refused():
    with pytest.raises(ValueError, match="neither an identifier"):
        Fact("P", ("one two",))


def test_predicates_must_still_be_identifiers():
    with pytest.raises(ValueError, match="not an identifier"):
        Fact("5PLUS", ("a",))


def test_unification_binds_over_numbers():
    assert match_body([Fact.parse("PLUS(?A, 4, ?B)")],
                      [Fact.parse("PLUS(5, 4, 9)")]) == [{"?A": "5", "?B": "9"}]


def test_fingerprints_survive_numeric_terms():
    from core.learning.rule_induction import CandidateRule, RuleEffects

    def rule(step, x="?X", y="?Y"):
        return CandidateRule(
            body=frozenset({Fact("CURRENT", (x,)), Fact("PLUS", (x, step, y))}),
            effects=RuleEffects(add=frozenset({Fact("CURRENT", (y,))})), action=None)

    assert semantic_fingerprint(rule("4")) == semantic_fingerprint(rule("4.0"))
    assert semantic_fingerprint(rule("4")) != semantic_fingerprint(rule("5"))
    # alpha-renaming invariance must not have been lost
    assert semantic_fingerprint(rule("4")) == semantic_fingerprint(rule("4", "?A", "?B"))


# ---- background ----------------------------------------------------------

def test_background_covers_only_consecutive_transitions():
    """Every pair put four PLUS literals in each state, and Plotkin's LGG pairs
    every same-predicate literal with every other -- the generalisation came
    back with a 22-literal body that blew MAX_BODY_LITERALS and induced
    nothing."""
    background = arithmetic_background([5, 9, 13])
    assert Fact.parse("PLUS(5, 4, 9)") in background
    assert Fact.parse("PLUS(9, 4, 13)") in background
    # 5 -> 13 is not a consecutive transition.
    assert Fact.parse("PLUS(5, 8, 13)") not in background


def test_background_offers_both_relations_and_chooses_neither():
    background = arithmetic_background([3, 9])
    assert Fact.parse("PLUS(3, 6, 9)") in background
    assert Fact.parse("TIMES(3, 3, 9)") in background


def test_background_of_non_numbers_is_empty():
    assert arithmetic_background(["a", "b"]) == frozenset()


# ---- induction -----------------------------------------------------------

@pytest.mark.parametrize("terms,expected_next,relation", [
    ([5, 9, 13, 17], "21", "PLUS"),
    ([11, 18, 25, 32], "39", "PLUS"),
    ([3, 9, 27, 81], "243", "TIMES"),
    ([4, 12, 36, 108], "324", "TIMES"),
])
def test_a_progression_is_induced_by_the_existing_inducer(terms, expected_next, relation):
    result, next_value = get_learning_authority().induce_sequence_rule(terms)
    assert result.status is InductionStatus.RULE_LEARNED, result.status
    assert next_value == expected_next
    assert any(f.predicate == relation for f in result.rule.body)


@pytest.mark.parametrize("terms", [[1, 4, 9, 16], [2, 5, 11, 23]])
def test_a_sequence_with_no_rule_in_this_language_returns_none(terms):
    """Neither has a constant difference or ratio. Inventing a rule would be
    the most tempting fabrication available here."""
    result, next_value = get_learning_authority().induce_sequence_rule(terms)
    assert next_value is None
    assert result.status is not InductionStatus.RULE_LEARNED


def test_negatives_are_what_refute_the_vacuous_rule():
    """Without counter-demonstrations the generalisation is
    `PLUS(?X1, ?X2, ?X0) -> CURRENT(?X0)` with ?X2 UNBOUND -- "the next term
    differs from this one by something" -- which fires for every possible
    successor and was reported as RULE_LEARNED."""
    result, _ = get_learning_authority().induce_sequence_rule([5, 9, 13, 17])
    assert result.rule is not None
    for literal in result.rule.body:
        if literal.predicate in ("PLUS", "TIMES"):
            step = literal.args[1]
            assert is_number(step), (
                f"the induced rule leaves its step unbound ({literal}); it "
                f"does not determine a successor")


def test_too_few_terms_is_declined_rather_than_guessed():
    result, next_value = get_learning_authority().induce_sequence_rule([5, 9])
    assert result is None and next_value is None


@pytest.mark.asyncio
async def test_a_sequence_question_is_answered_through_the_production_ingress():
    """A mechanism nothing routes to is not a capability."""
    from core.reasoning.neural_bridge import (ReasoningRequest,
                                              get_neural_bridge)

    bridge = get_neural_bridge()
    await bridge.initialize()
    bridge.llm_service = None

    result = await bridge.reason(ReasoningRequest(
        query="Next term in the sequence 5, 9, 13, 17", context=[]))
    metadata = result.metadata or {}
    assert result.answer == "21"
    assert metadata["verified"] is True
    assert "learning_authority" in metadata["route"]


@pytest.mark.asyncio
async def test_an_unsettled_sequence_reports_undecided_not_an_answer():
    from core.reasoning.neural_bridge import (ReasoningRequest,
                                              get_neural_bridge)

    bridge = get_neural_bridge()
    await bridge.initialize()
    bridge.llm_service = None

    result = await bridge.reason(ReasoningRequest(
        query="Next term in the sequence 2, 5, 11, 23", context=[]))
    assert result.answer == ""
    assert (result.metadata or {})["verified"] is False


# ---- LGG reduction: more evidence must not make induction fail -----------

def _list_world(name, values):
    from core.learning.rule_induction import canonical_term as c
    total, length = sum(values), len(values)
    mean = total / length
    facts = [Fact("LIST", (name,)), Fact("LENGTH", (name, c(str(length)))),
             Fact("SUM", (name, c(str(total)))), Fact("MEAN", (name, c(str(mean)))),
             Fact("MAXIMUM", (name, c(str(max(values)))))]
    for threshold in sorted({mean, max(values)}):
        exceeding = len([v for v in values if v > threshold])
        facts.append(Fact("EXCEEDING",
                          (name, c(str(threshold)), c(str(exceeding)))))
    return tuple(facts)


def _mean_demos(lists):
    from core.learning.rule_induction import TrainingExample, canonical_term as c
    examples = []
    for name, values in lists.items():
        world = _list_world(name, values)
        action = Fact("MEAN_OF", (name,))
        examples.append(TrainingExample(
            before=world + (action,), action=action,
            after=world + (Fact("VALUE", (c(str(sum(values) / len(values))),)),),
            positive=True))
        examples.append(TrainingExample(before=world, action=None, after=world,
                                        positive=False))
    return examples


def test_a_third_demonstration_does_not_break_induction():
    """Plotkin's LGG pairs every same-predicate literal with every other, so a
    state carrying a repeated predicate grows the body with each further
    demonstration: 8 literals per seed became 10 after two and 14 after three,
    blowing MAX_BODY_LITERALS and returning INSUFFICIENT_EVIDENCE.

    MORE EVIDENCE MADE INDUCTION FAIL, and the cap reported it as a shortage of
    shared structure. The cap bounds a 2**n subset enumeration, not what a real
    rule may look like, so it was raised rather than worked around.

    A greedy LGG reduction was tried here first and REVERTED: it picks one
    minimal body and discards the competing ones, so underdetermined
    demonstrations came back RULE_LEARNED instead of MULTIPLE_HYPOTHESES.
    """
    from core.learning.rule_induction import get_rule_inducer

    three = {"l1": [2, 4, 6, 8], "l2": [10, 20, 30], "l3": [1, 2, 3, 10]}
    result = get_rule_inducer().induce(_mean_demos(three), target_predicate="VALUE")
    assert result.status is InductionStatus.RULE_LEARNED, result.detail
    assert {str(f) for f in result.rule.body} == {"MEAN(?X1, ?X0)", "MEAN_OF(?X1)"}


def test_minimisation_keeps_the_discriminating_literal_and_drops_the_rest():
    """The world offers LENGTH, SUM, MEAN, MAXIMUM and EXCEEDING. Only MEAN
    explains what MEAN_OF produces."""
    from core.learning.rule_induction import get_rule_inducer

    result = get_rule_inducer().induce(
        _mean_demos({"l1": [2, 4, 6, 8], "l2": [10, 20, 30]}),
        target_predicate="VALUE")
    assert result.rule is not None
    predicates = {f.predicate for f in result.rule.body}
    assert "MEAN" in predicates
    assert not ({"SUM", "LENGTH", "MAXIMUM", "EXCEEDING"} & predicates), (
        "reduction kept an observation that does not explain the effect")


def test_the_learned_operator_keeps_its_action():
    """Dropping the action is a different hypothesis -- that the effect happens
    without acting -- and belongs to the version space, not to a silent
    simplification."""
    from core.learning.rule_induction import get_rule_inducer

    result = get_rule_inducer().induce(
        _mean_demos({"l1": [2, 4, 6, 8], "l2": [10, 20, 30]}),
        target_predicate="VALUE")
    assert result.rule.action is not None
    assert result.rule.action in result.rule.body


def test_the_learned_rule_explains_every_positive_and_no_negative_refutes_it():
    from core.learning.rule_induction import get_rule_inducer

    demos = _mean_demos({"l1": [2, 4, 6, 8], "l2": [10, 20, 30]})
    result = get_rule_inducer().induce(demos, target_predicate="VALUE")
    inducer = get_rule_inducer()
    positives = [d for d in demos if d.positive]
    negatives = [d for d in demos if not d.positive]
    assert inducer._explains(result.rule, positives)
    assert not inducer._refuted(result.rule, negatives)


# ---- minimality must be modulo variable renaming ------------------------

def test_subsumption_is_modulo_renaming():
    from core.learning.rule_induction import _subsumes

    general = frozenset({Fact.parse("EXCEEDING(?X1, ?X2, ?X0)")})
    # Same constraint, different variable names, plus an extra literal.
    specific = frozenset({Fact.parse("EXCEEDING(?X1, ?X4, ?X0)"),
                          Fact.parse("EXCEEDING(?X1, ?X2, ?X3)")})
    assert _subsumes(general, specific), (
        "a renamed copy of the same literal was treated as a different constraint")
    assert not _subsumes(specific, general), "a larger body cannot subsume a smaller"


def test_alpha_variant_supersets_do_not_survive_as_hypotheses():
    """Measured before the fix: one correct rule came back as 22 candidates --
    itself plus twenty-one copies carrying extra literals that bind nothing --
    so the version space could never collapse and induction never settled.

    Rule IDENTITY was already renaming-invariant; subsumption was not.
    """
    import sys
    from pathlib import Path

    edu12 = Path(__file__).resolve().parents[1] / "experiments" / "edu" / "EDU-12"
    sys.path.insert(0, str(edu12))
    from program_construction import teach_count_exceeding

    result = teach_count_exceeding()
    assert result.status is InductionStatus.RULE_LEARNED, (
        f"{len(result.candidates)} candidates survived: "
        f"{[sorted(str(f) for f in c.body) for c in result.candidates[:3]]}")
    assert {str(f) for f in result.rule.body} == {
        "COUNT_EXCEEDING(?X1)", "EXCEEDING(?X1, ?X2, ?X0)", "VALUE(?X2)"}


def test_genuinely_distinct_hypotheses_still_report_ambiguity():
    """The pruning must remove RENAMINGS, never real alternatives. If this ever
    fails, subsumption has started manufacturing certainty."""
    from core.learning.learning_authority import get_learning_authority

    # 3,9,27,81 fits both "add a varying amount" and "multiply by three"; only
    # the discriminating negatives collapse it. Without them it must stay open.
    from core.learning.rule_induction import (TrainingExample,
                                              arithmetic_background,
                                              get_rule_inducer)

    examples = []
    for before, after in ((3, 9), (9, 27)):
        background = tuple(arithmetic_background([before, after]))
        examples.append(TrainingExample(
            before=(Fact("CURRENT", (str(before),)), Fact("ADVANCE", ())) + background,
            action=Fact("ADVANCE", ()),
            after=(Fact("CURRENT", (str(after),)),) + background, positive=True))

    result = get_rule_inducer().induce(examples)
    assert result.status is InductionStatus.MULTIPLE_HYPOTHESES, (
        "underdetermined demonstrations collapsed to a single rule")


def test_the_constructed_program_generalises_to_unseen_inputs():
    """Planning against one input is problem-solving; a PROGRAM has to work on
    inputs it was never planned against."""
    import json
    from pathlib import Path

    manifest = (Path(__file__).resolve().parents[1] / "experiments" / "edu" /
                "EDU-12" / "program_construction.json")
    if not manifest.exists():
        pytest.skip("program_construction has not been run")
    record = json.loads(manifest.read_text())
    assert record["model_calls"] == 0
    assert record["passed"] is True
    assert len(record["plan"]) >= 2, "a one-step plan is not a composition"
    assert all(row["correct"] for row in record["held_out"])
