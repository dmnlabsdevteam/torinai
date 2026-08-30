#!/usr/bin/env python3
"""Genericity: what proposition a copular sentence expresses.

The risk being guarded against is precise. "A robin is a bird" needed to become
a rule about kinds, and the cheap way to get there is to read the article `a`
as a quantifier. That turns "A robin is in the yard" into a law about all
robins -- an overgeneralization machine that proves things nobody said.

So the classification is its own stage, the accepted grammar is deliberately
small, and the negative controls matter more than the positive one.
"""

import asyncio

import pytest

# READING AND GENERICITY ARE SEMANTICS' NOW. They were imported from
# `neural_bridge` when 619 lines of English patterns lived there; the reading
# moved to `core.semantics.sentence_reader` and the classification to
# `core.semantics.genericity` on 2026-08-24. The bridge still re-exports them,
# so this could have kept working while testing the wrong owner -- which is
# exactly how an import outlives the architecture it was written for.
from core.reasoning.neural_bridge import DeterministicExtractor  # noqa: F401
from core.semantics.genericity import Genericity
from core.semantics.genericity import classify_genericity as classify
from core.semantics.sentence_reader import SentenceReader


@pytest.mark.parametrize("determiner,subject,complement,expected", [
    # GENERIC_KIND: both sides denote kinds, the copula classifies.
    ("A", "robin", "a bird", Genericity.GENERIC_KIND),
    ("A", "whale", "a mammal", Genericity.GENERIC_KIND),
    ("A", "square", "a shape", Genericity.GENERIC_KIND),
    # INSTANCE: a proper noun or a definite subject names an individual.
    (None, "Tweety", "a robin", Genericity.INSTANCE),
    (None, "Socrates", "human", Genericity.INSTANCE),
    ("The", "vault", "locked", Genericity.INSTANCE),
    # EXISTENTIAL: the copula locates rather than classifies.
    ("A", "robin", "in the yard", Genericity.EXISTENTIAL),
    ("A", "doctor", "here", Genericity.EXISTENTIAL),
    ("A", "robin", "in a yard", Genericity.EXISTENTIAL),
    # AMBIGUOUS: nothing in the surface form settles it.
    ("A", "bird", "hungry", Genericity.AMBIGUOUS),
    ("A", "car", "fast", Genericity.AMBIGUOUS),
])
def test_the_four_readings(determiner, subject, complement, expected):
    assert classify(subject, complement, determiner).genericity is expected


def test_genericity_is_about_the_proposition_not_its_truth():
    """"A doctor is a parent" is false as a generalisation and is still a
    GENERIC_KIND claim. The formalizer preserves what was said; evidence
    decides truth later. Collapsing the two would let the reader's beliefs
    decide what a sentence means."""
    assert classify("doctor", "a parent", "A").genericity is Genericity.GENERIC_KIND


def test_a_locative_complement_beats_an_indefinite_article_inside_it():
    """"in a yard" contains an article and must not read as a kind."""
    reading = classify("robin", "in a yard", "A")
    assert reading.genericity is Genericity.EXISTENTIAL
    assert "locates" in reading.cue


def test_only_representable_readings_claim_to_be_representable():
    assert Genericity.GENERIC_KIND.is_representable
    assert Genericity.INSTANCE.is_representable
    # Understood, but the formal grammar has no existential quantifier.
    assert not Genericity.EXISTENTIAL.is_representable
    assert not Genericity.AMBIGUOUS.is_representable


@pytest.mark.parametrize("sentence,kind,genericity", [
    ("A robin is a bird", "universal", "generic_kind"),
    ("A bird is an animal", "universal", "generic_kind"),
    ("Tweety is a robin", "fact", "instance"),
    ("A robin is in the yard", "unsupported", "existential"),
    ("A bird is hungry", "unsupported", "ambiguous"),
])
def test_the_parser_carries_the_reading(sentence, kind, genericity):
    node = SentenceReader()._parse_statement(sentence)
    assert node is not None, f"{sentence!r} became unrepresentable"
    assert node["kind"] == kind
    assert node["genericity"] == genericity


def test_universals_are_untouched_by_genericity():
    node = SentenceReader()._parse_statement("All humans are mortal")
    assert node["kind"] == "universal" and node["p"] == "humans"


def _formalize(query, context):
    """Runs its own loop. `get_event_loop()` reuses whatever loop another test
    left behind, which passes in isolation and fails in a full run."""
    return asyncio.run(DeterministicExtractor().formalize(query, context))


def test_the_canonical_chain_formalizes_to_a_provable_structure():
    """THE ORACLE, at the formalization stage.

        A robin is a bird.    GENERIC_KIND   ROBIN(?X) -> BIRD(?X)
        A bird is an animal.  GENERIC_KIND   BIRD(?X)  -> ANIMAL(?X)
        Tweety is a robin.    INSTANCE       ROBIN(tweety)
    """
    result = _formalize("Is Tweety an animal?",
                        ["A robin is a bird", "A bird is an animal",
                         "Tweety is a robin"])
    assert result.succeeded
    assert result.statement == "tweety_animal"
    assert "tweety_robin -> tweety_bird" in result.premises
    assert "tweety_bird -> tweety_animal" in result.premises
    assert "tweety_robin" in result.premises


def test_an_existential_premise_is_declined_by_name_not_silently_dropped():
    """NEGATIVE CONTROL. If this ever concludes, genericity has become an
    overgeneralization machine."""
    result = _formalize("Is Tweety in the yard?",
                        ["A robin is in the yard", "Tweety is a robin"])
    assert not result.succeeded
    assert "existential_quantification_not_supported" in result.error
    # And nothing resembling a location atom was manufactured.
    assert not any("yard" in p for p in result.premises)


def test_an_ambiguous_premise_is_declined_rather_than_resolved():
    result = _formalize("Is Tweety hungry?", ["A bird is hungry", "Tweety is a bird"])
    assert not result.succeeded
    assert "ambiguous_quantification_not_resolved" in result.error


def test_the_reading_survives_into_the_formalization():
    """Quantificational interpretation is cognition-bearing state: a proof
    resting on a universal rule must be able to say why that rule existed."""
    result = _formalize("Is Tweety an animal?",
                        ["A robin is a bird", "Tweety is a robin"])
    assert result.surface_text == ["A robin is a bird", "Tweety is a robin"]
    assert [r["genericity"] for r in result.readings] == ["generic_kind", "instance"]
    assert all(r["cue"] for r in result.readings)
    assert "generic_class_interpretation" in result.transformations


def test_the_accepted_generic_grammar_stays_narrow():
    """Widening needs discriminating tests per construction. Unsupported
    coverage merely reduces what can be read; guessed quantification corrupts
    what is reasoned."""
    for complement in ("a large bird", "the fastest bird", "land surrounded by water"):
        assert classify("robin", complement, "A").genericity is not Genericity.GENERIC_KIND


@pytest.mark.asyncio
async def test_the_whole_chain_proves_the_oracle_with_the_model_detached():
    """One test that exercises every stage at once, which is the point.

        article handling -> genericity classification -> formalization
        -> variable unification -> deduction

    Four isolated happy-path tests can all pass while the chain between them is
    broken; this cannot. The model is DETACHED, not merely unselected, so a
    pass cannot be Qwen quietly rescuing the substrate.
    """
    from core.reasoning.neural_bridge import (ReasoningMode, ReasoningRequest,
                                              get_neural_bridge)

    bridge = get_neural_bridge()
    await bridge.initialize()
    bridge.llm_service = None
    assert not bridge._model_available(), "the model was still reachable"

    proved = await bridge.reason(ReasoningRequest(
        query="Is Tweety an animal?",
        context=["A robin is a bird", "A bird is an animal", "Tweety is a robin"],
        mode=ReasoningMode.SYMBOLIC))
    metadata = proved.metadata or {}
    assert metadata.get("verified") is True, proved.answer
    assert "tweety_animal" in str(proved.answer)

    # NEGATIVE CONTROL through the same path: an existential premise must not
    # license a conclusion about the individual.
    not_proved = await bridge.reason(ReasoningRequest(
        query="Is Tweety in the yard?",
        context=["A robin is in the yard", "Tweety is a robin"],
        mode=ReasoningMode.SYMBOLIC))
    assert not (not_proved.metadata or {}).get("verified"), (
        "an existential premise produced a proof about an individual -- "
        "genericity has become an overgeneralization machine")


# ---- proving a claim about a KIND ---------------------------------------

def test_a_generic_goal_is_proved_of_an_arbitrary_member():
    """"Is a robin an animal?" asks about a kind, and a kind is not an
    individual the universals can be grounded over.

    Grounding over the kind NAME produced `robin_robin -> robin_bird`, and
    `robin_robin` is never asserted -- so a question its premises plainly
    entail came back "not entailed by the premises". Proving something of a
    kind is proving it of an arbitrary member, so one is introduced.
    """
    result = _formalize("Is a robin an animal?",
                        ["A robin is a bird", "A bird is an animal"])
    assert result.succeeded
    assert result.statement.startswith("any_robin")
    # The arbitrary member is asserted to be of the kind, and nothing else.
    assert "any_robin_robin" in result.premises
    assert "any_robin_robin -> any_robin_bird" in result.premises


def test_an_instance_goal_is_not_skolemised():
    """"Is Tweety an animal?" is about Tweety, and introducing an arbitrary
    robin instead would prove a different claim."""
    result = _formalize("Is Tweety an animal?",
                        ["A robin is a bird", "A bird is an animal",
                         "Tweety is a robin"])
    assert result.succeeded
    assert result.statement == "tweety_animal"
    assert not any(p.startswith("any_") for p in result.premises)


@pytest.mark.asyncio
async def test_a_generic_goal_the_premises_do_not_entail_is_still_refused():
    """The skolem must not make everything provable: it asserts membership of
    the kind and nothing more."""
    from core.reasoning.neural_bridge import (ReasoningMode, ReasoningRequest,
                                              get_neural_bridge)

    bridge = get_neural_bridge()
    await bridge.initialize()
    bridge.llm_service = None

    proved = await bridge.reason(ReasoningRequest(
        query="Is a robin an animal?",
        context=["A robin is a bird", "A bird is an animal"],
        mode=ReasoningMode.SYMBOLIC))
    assert (proved.metadata or {}).get("verified") is True

    refused = await bridge.reason(ReasoningRequest(
        query="Is a whale a fish?",
        context=["A whale is a mammal", "A shark is a fish"],
        mode=ReasoningMode.SYMBOLIC))
    assert not (refused.metadata or {}).get("verified"), (
        "an unentailed generic claim was proved -- the arbitrary member is "
        "carrying assumptions it should not have")
