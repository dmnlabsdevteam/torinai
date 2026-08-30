#!/usr/bin/env python3
"""Reading a sentence nobody wrote a pattern for, with the model untouched.

The deterministic extractor covers six forms and every seventh was a person
writing another regular expression. A reading DERIVED from sentence/meaning
pairs enters the same chain, after the tested patterns and before any model,
so coverage grows by evidence instead of by authorship.

What must hold: the hand-written patterns still win where they apply, a derived
reading only ever sees what they declined, it declines in turn rather than
guessing, and nothing it covers requires a model.
"""

import pytest

from core.reasoning.neural_bridge import (DerivedReadingFormalizer,
                                          DeterministicExtractor)
from core.semantics.reading_registry import (DerivedReading,
                                             get_reading_registry)


def build_reading():
    """Derive the reading here, from sentence/meaning pairs, as EDU-13 does."""
    from core.execution.procedure import Operator
    from core.learning.procedure_synthesis import IOExample, derive_procedure
    from core.learning.rule_induction import (Fact, TrainingExample,
                                              get_rule_inducer)
    from experiments.edu import __name__ as _  # noqa: F401  (package marker)
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "experiments" / "edu" / "EDU-13"))
    from reading import (DEMONSTRATIONS, TARGETS, TAUGHT, budget,  # noqa: E402
                         demonstrate)
    from experiments.sentence_machine import FLAGS, INSTRUCTIONS, SentenceMachine

    operators = []
    for instruction in DEMONSTRATIONS:
        examples = demonstrate(instruction)
        rules = []
        for target in TARGETS[instruction]:
            result = get_rule_inducer().induce(examples, target_predicate=target)
            assert result.rule is not None, (instruction, target, result.detail)
            rules.append(result.rule)
        operators.append(Operator(action=Fact(instruction, ()), rules=tuple(rules)))

    derived = derive_procedure(
        operators, tuple(Fact(f, ()) for f in FLAGS),
        [IOExample(label=s, build=lambda t=s: SentenceMachine(t), expected=m,
                   max_steps=budget(s)) for s, m in TAUGHT],
        terminal="READING", max_rules=6)
    assert derived.procedures, derived.detail
    return DerivedReading(
        name="copular", procedure=derived.procedures[0],
        machine=SentenceMachine, budget=budget,
        provenance=f"derived from {len(TAUGHT)} sentence/meaning pairs")


@pytest.fixture(scope="module")
def registered():
    registry = get_reading_registry()
    registry.clear()
    registry.register(build_reading())
    yield registry
    registry.clear()


@pytest.mark.asyncio
async def test_a_form_nobody_wrote_a_pattern_for_is_read_without_a_model(registered):
    """A sentence the hand-written patterns decline is read by a DERIVED
    procedure -- no copula, and no lexical anchor for the SVO pattern either.

    THE SENTENCE CHANGED, AND THE TEST DID NOT WEAKEN. It was
    `vault holds gold`, chosen because no pattern covered a bare
    subject-verb-object form. One does now: `_SVO` reads SVO when the SUBJECT is
    a known noun, on the reasoning that the word standing after a known thing is
    the action -- which is how a learner meets a new verb. Once `vault` entered
    the lexicon as a NOUN, the written patterns could read the sentence, and the
    premise of this test ("nobody wrote a pattern for this form") stopped being
    true. A real capability gain that invalidated the setup.

    `quorn` is not in the lexicon, so there is no anchor and the SVO pattern
    declines exactly as the six patterns declined the original -- which is the
    condition this test needs. Verified: with `vault` the written extractor
    reads `vault_holds_gold`; with `quorn` it declines.

    Note the two readers do not agree on the atom -- the written path yields
    `<subject>_<verb>_<object>` and the derived path `<subject>_<object>`. They
    are separate readers and the chain prefers the written one, so this only
    matters where both apply.
    """
    sentence = "quorn holds gold"

    written = await DeterministicExtractor().formalize(sentence, [sentence])
    assert not written.succeeded, "the hand-written patterns were expected to decline"
    assert "outside the supported patterns" in written.error

    derived = await DerivedReadingFormalizer().formalize(sentence, [sentence])
    assert derived.succeeded, derived.error
    assert derived.statement == "quorn_gold"
    assert derived.premises == ["quorn_gold"], "a goal with nothing to prove it from"
    assert derived.requires_model is False


@pytest.mark.asyncio
async def test_polarity_survives_into_the_formal_statement(registered):
    derived = await DerivedReadingFormalizer().formalize("copper is not brittle")
    assert derived.succeeded, derived.error
    assert derived.statement == "~copper_brittle"
    assert derived.requires_model is False


@pytest.mark.asyncio
async def test_it_declines_rather_than_guessing(registered):
    """A reading that produced something for every input would be guessing, and
    a guess becomes a premise the solver cannot doubt."""
    derived = await DerivedReadingFormalizer().formalize("why")
    assert not derived.succeeded
    assert "no derived reading applied" in derived.error


@pytest.mark.asyncio
async def test_the_tested_patterns_still_win_where_they_apply(registered):
    """The derived reading must not shadow a form that already worked."""
    from core.reasoning.neural_bridge import (FormalizerChain,
                                              PassthroughFormalizer)

    chain = FormalizerChain([PassthroughFormalizer(), DeterministicExtractor(),
                             DerivedReadingFormalizer()])
    result = await chain.formalize("Is the vault locked?", ["the vault is locked"])

    assert result.succeeded
    assert result.source == "extractor", "the hand-written pattern should have answered"
    assert result.requires_model is False


@pytest.mark.asyncio
async def test_nothing_is_registered_unless_something_derived_it():
    """An empty registry declines everything, so wiring alone claims nothing."""
    registry = get_reading_registry()
    registry.clear()
    derived = await DerivedReadingFormalizer().formalize("vault holds gold")
    assert not derived.succeeded
