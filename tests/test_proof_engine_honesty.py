#!/usr/bin/env python3
"""The proof engine must not claim more than it checked.

Three defects, all found by asking one question of each function: can this
return a value that makes its caller believe something happened that did not?

    verify_proof     looped over the steps with `pass` and returned
                     `proof.proved` -- the claim it was asked to check
    _smt_proof       silently ran a weaker method when Z3 was missing
    prove_theorem    reported `proved=False` from an incomplete method
                     identically to a real refutation
"""

import pytest

import core.reasoning.advanced_proof_engine as engine_module
from core.reasoning.advanced_proof_engine import (CAPABILITY_UNAVAILABLE,
                                                  NEGATIVE_NOT_AUTHORITATIVE,
                                                  AdvancedProofEngine, LogicType,
                                                  Proof, ProofMethod, ProofStep,
                                                  Theorem)


@pytest.fixture
def engine():
    return AdvancedProofEngine()


@pytest.fixture
def syllogism():
    return Theorem(theorem_id="t1", statement="socrates_mortal",
                   premises=["socrates_human", "socrates_human -> socrates_mortal"],
                   logic_type=LogicType.PROPOSITIONAL)


@pytest.mark.asyncio
async def test_a_real_proof_verifies(engine, syllogism):
    proof = await engine.prove_theorem(syllogism)
    assert proof.proved
    verification = await engine.verify_proof(proof, syllogism)
    assert verification.verified and bool(verification) is True


@pytest.mark.asyncio
async def test_a_proof_whose_steps_do_not_follow_is_rejected(engine):
    """The case the old implementation returned True on."""
    fabricated = Proof(theorem_id="t2", proved=True, method=ProofMethod.DIRECT,
                       steps=[ProofStep(1, "a", "Premise", "given"),
                              ProofStep(2, "z", "From nothing", "modus_ponens")])
    verification = await engine.verify_proof(fabricated)
    assert not verification.verified
    assert verification.failed_step == 2


@pytest.mark.asyncio
async def test_a_step_the_checker_cannot_re_derive_blocks_verification(engine):
    """An unexamined step must never be waved through -- that is precisely what
    the previous version did for every step."""
    proof = Proof(theorem_id="t3", proved=True, method=ProofMethod.DIRECT,
                  steps=[ProofStep(1, "a", "Premise", "given"),
                         ProofStep(2, "b", "By magic", "unsupported_rule")])
    verification = await engine.verify_proof(proof)
    assert not verification.verified
    assert verification.unchecked_steps == [2]


@pytest.mark.asyncio
async def test_a_proof_claiming_success_with_no_steps_is_rejected(engine):
    proof = Proof(theorem_id="t4", proved=True, method=ProofMethod.DIRECT, steps=[])
    assert not (await engine.verify_proof(proof)).verified


@pytest.mark.asyncio
async def test_severing_z3_does_not_silently_run_a_weaker_prover(engine, syllogism,
                                                                 monkeypatch):
    """`_smt_proof` must report a capability fault, not degrade."""
    monkeypatch.setattr(engine_module, "_Z3_AVAILABLE", False)
    proof = await engine._smt_proof(syllogism, max_steps=10)
    assert proof.proved is False
    assert proof.error == CAPABILITY_UNAVAILABLE
    assert proof.method is ProofMethod.SMT


@pytest.mark.asyncio
async def test_a_negative_reached_without_the_complete_method_is_marked(
        engine, syllogism, monkeypatch):
    """"I could not derive it" must not read as "it does not follow"."""
    monkeypatch.setattr(engine_module, "_Z3_AVAILABLE", False)
    proof = await engine.prove_theorem(syllogism)
    assert proof.proved is False
    assert proof.error == NEGATIVE_NOT_AUTHORITATIVE


@pytest.mark.asyncio
async def test_a_proof_produced_without_its_solver_never_verifies(engine):
    proof = Proof(theorem_id="t5", proved=True, method=ProofMethod.SMT,
                  error=CAPABILITY_UNAVAILABLE)
    verification = await engine.verify_proof(proof)
    assert not verification.verified
    assert "without its solver" in verification.reason


@pytest.mark.asyncio
async def test_an_smt_proof_cannot_be_verified_without_its_theorem(engine):
    """It carries no re-checkable steps, so there is nothing to examine."""
    proof = Proof(theorem_id="t6", proved=True, method=ProofMethod.SMT,
                  steps=[ProofStep(1, "x", "solver", "smt")])
    assert not (await engine.verify_proof(proof)).verified


# ---- falsifiability: three answers, not two -----------------------------

@pytest.mark.parametrize("claim,expected", [
    # Unbounded universals and absolutes: no finite observation settles them.
    ("This always works", False),
    ("It never fails", False),
    # Value judgements state a preference.
    ("The design is good", False),
    ("We ought to refactor", False),
    # Tautologies hold under every observation.
    ("It is raining or not raining", False),
    # Measurable directions and conditionals can be checked.
    ("Increasing X reduces Y", True),
    ("Caffeine improves recall", True),
    ("If pressure rises the valve opens", True),
    # UNDETERMINED. Not a hedge: a claim whose falsifiability cannot be
    # established should not be admitted as a scientific one, and the caller
    # cannot act on that if a guess already said True.
    ("Purple sleeps furiously", None),
    ("", None),
])
def test_falsifiability_is_three_valued(claim, expected):
    from core.reasoning.hypothesis_testing import HypothesisTestingSystem
    assert HypothesisTestingSystem()._is_falsifiable(claim) is expected


def test_the_unfalsifiable_word_list_is_actually_consulted():
    """It was declared and never read, so "this always works" -- with `always`
    named two lines above -- came back falsifiable."""
    from core.reasoning.hypothesis_testing import HypothesisTestingSystem
    system = HypothesisTestingSystem()
    for word in ("always", "never", "all", "none", "perfect", "impossible", "must"):
        assert system._is_falsifiable(f"The system {word} responds") is False, word


def test_inflected_measurable_verbs_are_recognised():
    """`\\breduce\\b` does not match "reduces"; a measurable claim was reported
    unassessable purely because of inflection."""
    from core.reasoning.hypothesis_testing import HypothesisTestingSystem
    system = HypothesisTestingSystem()
    for claim in ("X reduces Y", "X reducing Y", "X increased Y", "X improves Y"):
        assert system._is_falsifiable(claim) is True, claim
