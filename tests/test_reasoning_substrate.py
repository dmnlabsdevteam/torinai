#!/usr/bin/env python3
"""
Reasoning substrate regression tests
====================================
Correctness tests for the symbolic reasoning substrate.

These assert outcomes. The older reasoning harnesses in this directory
(test_reasoning_systems.py and its v2) measure latency and record a pass for
any call that completes, so they report 100% success while every proof in the
run comes back proved=False. Nothing here passes unless the answer is right.

Each test names the defect it pins down, so a regression says what broke.
"""

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.reasoning.logical_integration import (  # noqa: E402
    FormulaSyntaxError,
    InferenceRule,
    LogicalFormulaParser,
    LogicalReasoningValidator,
)
from core.reasoning.advanced_proof_engine import (  # noqa: E402
    LogicType,
    Theorem,
    get_proof_engine,
)


def prove(statement, premises, timeout=10.0, logic_type=LogicType.PROPOSITIONAL):
    """Run the proof engine synchronously for a single theorem."""
    engine = get_proof_engine()
    theorem = Theorem(
        theorem_id="test_theorem",
        statement=statement,
        premises=list(premises),
        logic_type=logic_type,
    )
    return asyncio.run(engine.prove_theorem(theorem, timeout=timeout))


# ---------------------------------------------------------------- parser


def test_negation_binds_tighter_than_conjunction():
    """'~a & b' is (~a) & b, not ~(a & b)."""
    parser = LogicalFormulaParser()
    assert parser.parse_ast("~a & b") == (
        "and", ("not", ("atom", "a")), ("atom", "b")
    )


def test_conjunction_binds_tighter_than_disjunction():
    parser = LogicalFormulaParser()
    assert parser.parse_ast("a | b & c") == (
        "or", ("atom", "a"), ("and", ("atom", "b"), ("atom", "c"))
    )


def test_implication_is_right_associative():
    parser = LogicalFormulaParser()
    assert parser.parse_ast("a -> b -> c") == (
        "implies", ("atom", "a"), ("implies", ("atom", "b"), ("atom", "c"))
    )


def test_matching_parentheses_are_not_stripped_blindly():
    """'(a) & (b)' must not collapse into atoms 'a)' and '(b'."""
    parser = LogicalFormulaParser()
    assert parser.parse_ast("(a) & (b)") == (
        "and", ("atom", "a"), ("atom", "b")
    )


@pytest.mark.parametrize("identifier", ["android", "notion", "candidate", "sensor"])
def test_operator_words_inside_identifiers_are_not_rewritten(identifier):
    """Normalisation by str.replace turned 'android' into '∧roid'."""
    parser = LogicalFormulaParser()
    assert parser.parse_ast(identifier) == ("atom", identifier)


@pytest.mark.parametrize(
    "malformed",
    ["Socrates is human", "All humans are mortal", "a &", "(a & b", "a b", "a @ b", ")a("],
)
def test_malformed_input_raises_instead_of_becoming_an_atom(malformed):
    """Unparseable text must fail loudly, not silently become an opaque atom."""
    parser = LogicalFormulaParser()
    with pytest.raises(FormulaSyntaxError):
        parser.parse_ast(malformed)


def test_is_formal_separates_formal_from_natural_language():
    parser = LogicalFormulaParser()
    assert parser.is_formal("human -> mortal") is True
    assert parser.is_formal("Socrates is human") is False


def test_formula_ids_are_unique_within_the_same_second():
    """IDs came from whole-second timestamps and collided in the formula store."""
    parser = LogicalFormulaParser()
    ids = {parser.parse("a").formula_id for _ in range(5)}
    assert len(ids) == 5


# ----------------------------------------------------------- proof engine


@pytest.mark.parametrize(
    "name,statement,premises",
    [
        ("modus ponens", "mortal", ["human", "human -> mortal"]),
        ("modus tollens", "~a", ["a -> b", "~b"]),
        ("disjunctive syllogism", "b", ["a | b", "~a"]),
        ("hypothetical chain", "d", ["a", "a -> b", "b -> c", "c -> d"]),
        ("de morgan", "~a & ~b", ["~(a | b)"]),
        ("tautology", "a | ~a", []),
        ("ex falso", "anything", ["p", "~p"]),
        ("biconditional", "b", ["a <-> b", "a"]),
        ("negation precedence", "b", ["~a & b"]),
        ("parenthesised premise", "a", ["(a) & (b)"]),
    ],
)
def test_valid_entailments_are_proved(name, statement, premises):
    proof = prove(statement, premises)
    assert proof.proved is True, f"{name} should be provable (error={proof.error})"
    assert proof.confidence > 0.9


@pytest.mark.parametrize(
    "name,statement,premises",
    [
        ("non sequitur", "mortal", ["human"]),
        ("affirming the consequent", "a", ["a -> b", "b"]),
        ("denying the antecedent", "~b", ["a -> b", "~a"]),
        ("contradiction as goal", "a & ~a", []),
    ],
)
def test_invalid_entailments_are_refused(name, statement, premises):
    proof = prove(statement, premises)
    assert proof.proved is False, f"{name} must not be provable"
    assert proof.confidence == 0.0


def test_natural_language_reports_a_parse_error_not_a_silent_failure():
    """NL premises used to become atoms, so a real theorem failed with no reason."""
    proof = prove("Socrates is mortal", ["Socrates is human", "All humans are mortal"])
    assert proof.proved is False
    assert proof.error and "could not be parsed" in proof.error


def test_quantifiers_are_rejected_rather_than_treated_as_atoms():
    proof = prove("P(a)", ["forall x P(x)"], logic_type=LogicType.FIRST_ORDER)
    assert proof.proved is False
    assert proof.error and "quantifier" in proof.error.lower()


def test_solver_timeout_is_enforced_and_reported_as_undecided():
    """timeout was accepted and documented but never applied to the solver."""
    premises = []
    holes = 9
    for pigeon in range(holes + 1):
        premises.append(" | ".join(f"x{pigeon}_{h}" for h in range(holes)))
    for hole in range(holes):
        for first in range(holes + 1):
            for second in range(first + 1, holes + 1):
                premises.append(f"~(x{first}_{hole} & x{second}_{hole})")

    proof = prove("goal", premises, timeout=0.001)

    assert proof.proved is False
    assert proof.error and "undecided" in proof.error


# -------------------------------------------------------------- validator


def _validate(premises, conclusion, rule):
    return asyncio.run(
        LogicalReasoningValidator().validate_inference(premises, conclusion, rule)
    )


def test_modus_tollens_validates():
    """_validate_modus_tollens was referenced but never defined, so this raised
    AttributeError and the valid inference was reported invalid."""
    valid, errors = _validate(["a -> b", "~b"], "~a", InferenceRule.MODUS_TOLLENS)
    assert valid is True, errors


def test_modus_ponens_validates():
    valid, errors = _validate(["a -> b", "a"], "b", InferenceRule.MODUS_PONENS)
    assert valid is True, errors


def test_invalid_inference_is_rejected():
    valid, _ = _validate(["a -> b", "b"], "a", InferenceRule.MODUS_PONENS)
    assert valid is False


def test_unrecognised_rules_are_not_rubber_stamped():
    """Rules other than modus ponens/tollens were assumed valid unconditionally."""
    valid, _ = _validate(
        ["a | b", "~a"], "a", InferenceRule.DISJUNCTIVE_SYLLOGISM
    )
    assert valid is False

    valid, _ = _validate(
        ["p", "q"], "unrelated_conclusion", InferenceRule.HYPOTHETICAL_SYLLOGISM
    )
    assert valid is False


def test_valid_disjunctive_syllogism_still_accepted():
    valid, errors = _validate(
        ["a | b", "~a"], "b", InferenceRule.DISJUNCTIVE_SYLLOGISM
    )
    assert valid is True, errors


# ------------------------------------------------- substrate-first routing
#
# The architectural invariant: model availability affects input coverage, not
# whether Torin has a reasoning floor. An unspecified caller must reach the
# substrate first, and anything Torin can represent itself must never enter
# the model call graph.


class _CallCounter:
    """Wraps an LLM service and records every entry into its call graph."""

    def __init__(self, inner=None):
        self.inner = inner
        self.calls = 0

    def __getattr__(self, name):
        return getattr(self.inner, name)

    async def generate(self, *args, **kwargs):
        self.calls += 1
        if self.inner is None:
            raise AssertionError("substrate path must not call the model")
        return await self.inner.generate(*args, **kwargs)


def _reason_without_model(query, context=None):
    """Run a default-mode request with no model attached, counting LLM calls."""
    from core.reasoning.neural_bridge import (
        NeuralSymbolicBridge,
        ReasoningRequest,
    )

    bridge = NeuralSymbolicBridge()
    bridge.llm_service = None
    # reason() lazily calls initialize(), which re-attaches the global LLM
    # service. Mark the bridge initialized so it stays in the state under
    # test: started up, and no usable model attached.
    bridge.initialized = True

    result = asyncio.run(
        bridge.reason(ReasoningRequest(query=query, context=list(context or [])))
    )
    return result


def test_default_request_mode_is_abstract():
    """The default route is ABSTRACT -- the strategy registry of all 11 kinds,
    run substrate-first. It is never HYBRID (which would ask for neural work),
    and AUTO -- the old model-fallback selector -- no longer exists."""
    from core.reasoning.neural_bridge import ReasoningMode, ReasoningRequest

    assert ReasoningRequest(query="x").mode is ReasoningMode.ABSTRACT
    assert not hasattr(ReasoningMode, "AUTO")


def test_case_a_formal_input_reasons_without_a_model():
    """A. model unavailable + formal input -> substrate proves it."""
    result = _reason_without_model("mortal", ["human", "human -> mortal"])

    assert result.confidence == 0.98
    assert (result.metadata or {}).get("verified") is True
    assert "Proved" in result.answer


def test_case_c_unsupported_input_reports_honest_inability():
    """C. model unavailable + input Torin cannot represent -> no fabrication."""
    result = _reason_without_model("What should I name my startup?")

    metadata = result.metadata or {}
    assert result.answer == ""
    assert result.confidence == 0.0
    assert metadata.get("verified") is False
    assert metadata.get("formalized") is False
    assert metadata.get("reason") == "unsupported_input"
    assert metadata.get("model_available") is False

    # THE SUBSTRATE NEVER *REQUIRES* A MODEL. This assertion used to read
    # `model_required is True`, which was the model-first reading of this
    # situation: the substrate could not represent the input, therefore a model
    # was needed. Under substrate-first that inference is wrong -- an input
    # outside what Torin can represent is a fact about Torin's coverage, and a
    # model is optional coverage that may extend it, never a requirement the
    # substrate declares. `_substrate_first` states this directly, setting the
    # key to False and marking it a deprecated alias, so the old assertion had
    # been contradicting production for as long as both existed.
    assert metadata.get("model_required") is False

    # What is actually true here, and what a caller should branch on: no
    # teacher was reachable, and none was consulted.
    assert metadata.get("teacher_available") is False
    assert metadata.get("teacher_consulted") is False


def test_substrate_path_never_enters_the_model_call_graph():
    """A and C must not touch the model, even when a service object exists.

    _CallCounter raises if generate() is reached, so any escalation fails here.
    """
    from core.reasoning.neural_bridge import NeuralSymbolicBridge, ReasoningRequest

    for query, context in [
        ("mortal", ["human", "human -> mortal"]),
        ("What should I name my startup?", []),
    ]:
        bridge = NeuralSymbolicBridge()
        # An unusable service: present, but model_can_serve() is False.
        counter = _CallCounter(inner=None)
        bridge.llm_service = counter
        bridge.initialized = True

        asyncio.run(bridge.reason(ReasoningRequest(query=query, context=context)))

        assert counter.calls == 0, f"{query!r} entered the model call graph"


def test_neural_remains_available_when_explicitly_requested():
    """Changing the default epistemology must not delete the neural modes."""
    from core.reasoning.neural_bridge import ReasoningMode

    assert ReasoningMode.NEURAL.value == "neural"
    assert ReasoningMode.HYBRID.value == "hybrid"


def test_case_b_supported_natural_language_reasons_without_a_model():
    """B. model unavailable + NL inside the extractor's slice -> substrate proves it.

    This is the case the deterministic extractor exists to move. Before it
    existed, this returned reason=unsupported_input.
    """
    result = _reason_without_model(
        "Is Socrates mortal?", ["Socrates is human", "All humans are mortal"]
    )

    assert result.confidence == 0.98
    assert (result.metadata or {}).get("verified") is True
    assert result.metadata["formalizer"] == "extractor"
    assert result.metadata["model_required"] is False


@pytest.mark.parametrize(
    "name,query,context",
    [
        ("universal syllogism", "Socrates is mortal",
         ["Socrates is human", "All humans are mortal"]),
        ("chained universals", "Socrates is mortal",
         ["Socrates is greek", "All greeks are humans", "All humans are mortal"]),
        ("negative universal", "Socrates is not mortal",
         ["Socrates is human", "No humans are mortal"]),
        ("explicit conditional", "Socrates is mortal",
         ["Socrates is human", "If Socrates is human, then Socrates is mortal"]),
        ("grounding over two subjects", "Plato is mortal",
         ["Socrates is human", "Plato is human", "All humans are mortal"]),
        ("every-form universal", "Socrates is mortal",
         ["Socrates is human", "Every human is mortal"]),
    ],
)
def test_extractor_proves_supported_natural_language(name, query, context):
    result = _reason_without_model(query, context)

    assert result.metadata.get("proved") is True, f"{name}: {result.metadata}"
    assert result.metadata["model_required"] is False


@pytest.mark.parametrize(
    "name,query,context",
    [
        ("missing rule", "Socrates is mortal", ["Socrates is human"]),
        ("wrong direction", "Socrates is human",
         ["Socrates is mortal", "All humans are mortal"]),
        ("unrelated subject", "Plato is mortal",
         ["Socrates is human", "All humans are mortal"]),
    ],
)
def test_extractor_does_not_prove_invalid_natural_language(name, query, context):
    """Grounding must not manufacture entailments that do not hold."""
    result = _reason_without_model(query, context)

    assert result.metadata.get("proved") is not True, f"{name}: {result.metadata}"


def test_extractor_declines_rather_than_guessing_outside_its_slice():
    """A guessed premise is the one failure the solver cannot detect, so an
    unsupported sentence must make the extractor decline the whole request."""
    result = _reason_without_model(
        "Socrates is mortal",
        ["Socrates is human", "Philosophy flourished in Athens during this period"],
    )

    metadata = result.metadata or {}
    assert metadata.get("formalized") is False
    assert metadata.get("reason") == "unsupported_input"


def test_plural_class_names_fold_onto_their_singular():
    """'All humans are mortal' must bind to the atom from 'Socrates is human'."""
    from core.reasoning.neural_bridge import DeterministicExtractor

    formalization = asyncio.run(
        DeterministicExtractor().formalize(
            "Socrates is mortal", ["Socrates is human", "All humans are mortal"]
        )
    )

    assert formalization.succeeded
    assert "socrates_human -> socrates_mortal" in formalization.premises
    assert formalization.requires_model is False


# ------------------------------------------------- premise trustworthiness
#
# The solver checks entailment, never whether the premises faithfully
# represent the input. A single invented premise would otherwise yield a
# confident "Proved:" for a conclusion the source never supported.


def _prove_with_formalization(query, context, statement, premises, requires_model):
    from core.reasoning.neural_bridge import NeuralSymbolicBridge, ReasoningRequest
    from core.reasoning.reasoning_interfaces import Formalization

    bridge = NeuralSymbolicBridge()
    bridge.llm_service = None
    bridge.initialized = True

    formalization = Formalization(
        statement=statement,
        premises=list(premises),
        source="llm" if requires_model else "extractor",
        succeeded=True,
        requires_model=requires_model,
    )
    return asyncio.run(
        bridge._symbolic_reasoning(
            ReasoningRequest(query=query, context=list(context)),
            formalization=formalization,
        )
    )


def test_model_written_premises_never_earn_a_verified_verdict():
    """An entailment proved from model-written premises is not verified.

    The source below says nothing about trials, so a proof resting on that
    premise must not come back as verified fact.
    """
    from core.reasoning.neural_bridge import REASON_ENTAILMENT_ONLY, UNVERIFIED_CONFIDENCE

    result = _prove_with_formalization(
        query="Is the drug safe?",
        context=["The drug is under review."],
        statement="drug_is_safe",
        premises=["drug_passed_trials", "drug_passed_trials -> drug_is_safe"],
        requires_model=True,
    )

    metadata = result.metadata
    assert metadata["verified"] is False
    assert result.confidence <= UNVERIFIED_CONFIDENCE
    assert metadata["reason"] == REASON_ENTAILMENT_ONLY
    assert "Proved:" not in result.answer

    # The solver's finding is preserved, just not conflated with verification.
    assert metadata["entailment_verified"] is True
    assert metadata["premises_trusted"] is False


def test_substrate_derived_premises_do_earn_a_verified_verdict():
    """The trust rule must not punish premises the substrate derived itself."""
    result = _prove_with_formalization(
        query="Is Socrates mortal?",
        context=["Socrates is human", "All humans are mortal"],
        statement="socrates_mortal",
        premises=["socrates_human", "socrates_human -> socrates_mortal"],
        requires_model=False,
    )

    assert result.metadata["verified"] is True
    assert result.metadata["premises_trusted"] is True
    assert result.confidence == 0.98


def test_every_result_carries_the_credit_assignment_contract():
    """A substrate verdict and an inability must be told apart by metadata alone.

    Both come back with low-or-zero confidence in some cases, so confidence is
    not enough to distinguish them.
    """
    from core.reasoning.neural_bridge import (
        REASON_SUBSTRATE_REFUTED,
        REASON_SUBSTRATE_VERIFIED,
        REASON_UNSUPPORTED_INPUT,
    )

    contract = {"verified", "formalized", "reason", "model_required", "model_available"}

    proved = _reason_without_model("mortal", ["human", "human -> mortal"])
    refuted = _reason_without_model("mortal", ["human"])
    unsupported = _reason_without_model("What should I name my startup?")

    for result in (proved, refuted, unsupported):
        assert contract <= set(result.metadata or {}), (
            f"missing keys: {contract - set(result.metadata or {})}"
        )

    assert proved.metadata["reason"] == REASON_SUBSTRATE_VERIFIED
    assert refuted.metadata["reason"] == REASON_SUBSTRATE_REFUTED
    assert unsupported.metadata["reason"] == REASON_UNSUPPORTED_INPUT

    # A refuted goal is a real substrate verdict, not a failure to represent.
    assert refuted.metadata["formalized"] is True
    assert unsupported.metadata["formalized"] is False


def test_deterministic_formalization_is_marked_as_needing_no_model():
    """model_required=False is the substrate-native marker the extractor grows."""
    result = _reason_without_model("mortal", ["human", "human -> mortal"])

    assert result.metadata["formalizer"] == "passthrough"
    assert result.metadata["model_required"] is False
