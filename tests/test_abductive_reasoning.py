#!/usr/bin/env python3
"""
Abductive reasoning + explanation connectivity tests
====================================================
ReasoningType.ABDUCTIVE was declared but no strategy implemented it, so a
context allowing abduction selected no strategy and silently produced nothing.
IReasoningEngine.explain_reasoning was declared with zero implementations.

Each test names the behaviour it pins down.
"""

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.reasoning.abstract_reasoning_engine import (  # noqa: E402
    AbductiveReasoningStrategy,
    InferenceMethod,
    ReasoningContext,
    ReasoningPremise,
    ReasoningResult,
    ReasoningType,
    create_abstract_reasoning_engine,
)

WET = "WetGround"
SLIPPERY = "SlipperyRoad"


def context(premises=(WET,), facts=(SLIPPERY,), rules=None, domain="diagnostics"):
    return ReasoningContext(
        context_id="ctx",
        domain=domain,
        problem_type="explain",
        premises=[
            ReasoningPremise(premise_id=f"p{i}", statement=s)
            for i, s in enumerate(premises)
        ],
        facts=list(facts),
        rules=list(
            rules
            if rules is not None
            else [
                "Rain -> WetGround",
                "Sprinkler -> WetGround",
                "Rain -> SlipperyRoad",
                "Frost & Ice -> SlipperyRoad",
            ]
        ),
        allowed_reasoning_types=[ReasoningType.ABDUCTIVE],
    )


def explain(ctx):
    return asyncio.run(AbductiveReasoningStrategy().reason(ctx))


# ------------------------------------------------------------- the strategy


def test_abductive_strategy_is_registered_with_the_engine():
    """ReasoningType.ABDUCTIVE was declared with nothing implementing it, so
    _select_strategies could never return one for an abductive context."""
    engine = create_abstract_reasoning_engine()

    assert ReasoningType.ABDUCTIVE in engine.strategies


def test_the_explanation_covering_most_observations_wins():
    """Rain accounts for both observations; Sprinkler for one."""
    results = explain(context())

    assert results, "abduction produced no explanation"
    assert results[0].statement == "Rain"
    assert results[0].evidence_strength == pytest.approx(1.0)


def test_a_simpler_explanation_outranks_a_more_assuming_one():
    """Occam: an explanation resting on more conjuncts assumes more. Sprinkler
    and (Frost ∧ Ice) each cover one observation, so only simplicity separates
    them."""
    ranked = {c.statement: c for c in explain(context())}

    assert ranked["Sprinkler"].confidence > ranked["(Frost ∧ Ice)"].confidence
    assert ranked["Sprinkler"].coherence_score > ranked["(Frost ∧ Ice)"].coherence_score


def test_structural_plausibility_cannot_reach_certainty():
    """Explaining every observation is not evidence that it is true."""
    best = explain(context())[0]

    assert best.confidence <= AbductiveReasoningStrategy.STRUCTURAL_CONFIDENCE_CEILING
    assert best.confidence < 1.0


def test_an_explanation_the_observations_deny_is_refused():
    """With ¬Rain observed, Rain must not survive as an explanation."""
    ranked = {
        c.statement: c
        for c in explain(
            context(
                premises=(WET, "~Rain"),
                facts=(),
                rules=["Rain -> WetGround", "Sprinkler -> WetGround"],
            )
        )
    }

    assert ranked["Rain"].confidence == 0.0
    assert ranked["Rain"].logical_validity == 0.0
    assert ranked["Sprinkler"].confidence > 0.0


def test_refused_explanations_are_dropped_by_engine_validation():
    """logical_validity < 0.3 is dropped by _validate_conclusion, so a denied
    explanation must not merely rank low -- it must not survive validation."""
    engine = create_abstract_reasoning_engine()
    ctx = context(
        premises=(WET, "~Rain"),
        facts=(),
        rules=["Rain -> WetGround", "Sprinkler -> WetGround"],
    )
    ranked = {c.statement: c for c in explain(ctx)}

    assert asyncio.run(engine._validate_conclusion(ranked["Rain"], ctx)) is False


def test_competing_explanations_are_carried_on_every_conclusion():
    """Abduction without its alternatives reads as deduction."""
    for conclusion in explain(context()):
        assert conclusion.alternative_conclusions
        assert conclusion.statement not in conclusion.alternative_conclusions


def test_unparseable_rules_are_ignored_not_fatal():
    """A natural-language rule cannot support abduction, but must not stop it."""
    results = explain(
        context(rules=["Rain -> WetGround", "when it is wet the ground gets wet"])
    )

    assert [c.statement for c in results] == ["Rain"]


def test_rules_that_are_not_implications_are_ignored():
    results = explain(context(rules=["Rain & Wind", "Rain -> WetGround"]))

    assert [c.statement for c in results] == ["Rain"]


def test_no_rules_means_no_explanation_not_a_guess():
    ctx = context(rules=[])

    assert AbductiveReasoningStrategy().is_applicable(ctx) is False
    assert explain(ctx) == []


def test_observations_with_no_matching_rule_yield_nothing():
    assert explain(context(rules=["Fever -> Infection"])) == []


def test_the_derivation_names_the_rules_it_fired():
    """A conclusion whose steps do not cite its rules cannot be checked."""
    steps = " ".join(explain(context())[0].reasoning_steps)

    assert "Rain -> WetGround" in steps
    assert "Rain -> SlipperyRoad" in steps
    assert "defeasible" in steps


def test_inference_method_is_recorded_as_backward_chaining():
    assert explain(context())[0].inference_method == InferenceMethod.BACKWARD_CHAINING


# ------------------------------------------------------------- explanation


def _result_for(conclusions, ctx):
    return ReasoningResult(result_id="r1", context=ctx, conclusions=conclusions)


def test_explanation_renders_the_recorded_derivation():
    """explain_reasoning was declared on IReasoningEngine and never implemented."""
    engine = create_abstract_reasoning_engine()
    ctx = context()
    conclusions = explain(ctx)

    lines = asyncio.run(engine.explain_reasoning(_result_for(conclusions, ctx)))
    text = "\n".join(lines)

    assert "Rain" in text
    assert "abductive reasoning" in text
    assert "Rain -> WetGround" in text
    assert "competing:" in text


def test_explanation_resolves_premise_ids_to_statements():
    """An explanation citing 'p0' explains nothing to a reader."""
    engine = create_abstract_reasoning_engine()
    ctx = context()
    conclusions = explain(ctx)

    text = "\n".join(asyncio.run(engine.explain_reasoning(_result_for(conclusions, ctx))))

    assert f"from: {WET}" in text
    assert "p0" not in text


def test_explanation_reports_a_missing_derivation_rather_than_inventing_one():
    """A strategy that recorded no steps must be reported as such."""
    engine = create_abstract_reasoning_engine()
    ctx = context()
    conclusion = explain(ctx)[0]
    conclusion.reasoning_steps = []

    text = "\n".join(asyncio.run(engine.explain_reasoning(_result_for([conclusion], ctx))))

    assert "none recorded" in text


def test_explaining_nothing_says_so():
    engine = create_abstract_reasoning_engine()

    lines = asyncio.run(engine.explain_reasoning(_result_for([], context())))

    assert len(lines) == 1
    assert "no derivation" in lines[0].lower()


def test_explanation_accepts_a_bare_conclusion():
    engine = create_abstract_reasoning_engine()
    conclusion = explain(context())[0]

    lines = asyncio.run(engine.explain_reasoning(conclusion))

    assert any("Rain" in line for line in lines)
