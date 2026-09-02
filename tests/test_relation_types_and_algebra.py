#!/usr/bin/env python3
"""Typed relations + licensed inference, with the isolation negative-controls.

The negative controls are the point: a typed graph must REFUSE the chains that
naive reachability would accept (made-of never becomes isa, part-of never
becomes isa, located-in never becomes isa).
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.semantics.relation_types import (
    classify, SemanticRelation as R, NOUN, ADJECTIVE)
from core.reasoning.relation_algebra import (
    Edge, compose, derive_from, entails, is_licensed)


# ---------------------------------------------------------------- typing

def test_predicate_spans_get_distinct_types_not_all_isa():
    cases = {
        "is a": R.ISA,
        "has": R.HAS_PART,
        "eats": R.EATS,
        "makes": R.CREATES,
        "lives in": R.LOCATED_IN,
        "is part of": R.PART_OF,
        "is made of": R.MADE_OF,
        "is used for": R.USED_FOR,
        "causes": R.CAUSES,
    }
    for span, expected in cases.items():
        got = classify(span)
        assert got.relation is expected, f"{span!r} -> {got.relation} != {expected}"
    # everything the machine reads carries its provenance
    assert classify("is a").source == "curated_lexical_map"


def test_unknown_predicate_is_inert_not_taxonomic():
    got = classify("flurbles")
    assert got.relation is R.RELATED_TO
    assert got.matched == "" and got.surface == "flurbles"
    # RELATED_TO must license no inference
    assert compose(R.RELATED_TO, R.ISA) is None
    assert compose(R.ISA, R.RELATED_TO) is None


def test_bare_copula_disambiguates_on_object_class():
    assert classify("is", object_word_class=ADJECTIVE).relation is R.HAS_PROPERTY
    assert classify("is", object_word_class=NOUN).relation is R.ISA
    assert classify("is").relation is R.ISA  # default, never invents a property


def test_generic_safety_is_typed():
    assert classify("is a").generic is True          # a kind law
    assert classify("lives in").generic is False     # contextual, not universal
    assert classify("owns").generic is False


# ---------------------------------------------------------- transitivity

def test_isa_chain_derives_animal():
    edges = [Edge("robin", R.ISA, "bird"), Edge("bird", R.ISA, "vertebrate"),
             Edge("vertebrate", R.ISA, "animal")]
    d = entails("robin", R.ISA, "animal", edges)
    assert d is not None and d.hops == 3          # derived, 3 observed hops
    assert d.edge == Edge("robin", R.ISA, "animal")


def test_instance_of_rides_up_isa():
    edges = [Edge("fido", R.INSTANCE_OF, "dog"), Edge("dog", R.ISA, "mammal")]
    assert entails("fido", R.INSTANCE_OF, "mammal", edges) is not None
    # but fido is NOT a subKIND of mammal
    assert entails("fido", R.ISA, "mammal", edges) is None


# ----------------------------------------------------------- inheritance

def test_generic_property_inherits_down_isa():
    edges = [Edge("robin", R.ISA, "bird"), Edge("bird", R.HAS_PART, "wings")]
    assert entails("robin", R.HAS_PART, "wings", edges) is not None
    edges2 = [Edge("robin", R.ISA, "bird"), Edge("bird", R.EATS, "insects")]
    assert entails("robin", R.EATS, "insects", edges2) is not None


def test_membership_does_not_transit():
    # robin member_of flock, flock member_of ecosystem  ⊬  robin member_of ecosystem
    edges = [Edge("robin", R.MEMBER_OF, "flock"),
             Edge("flock", R.MEMBER_OF, "ecosystem")]
    assert entails("robin", R.MEMBER_OF, "ecosystem", edges) is None


# ---------------------------------------------- ISOLATION (negative controls)

def test_made_of_never_becomes_isa():
    # "A widget is made of brass." + "Brass is a material."
    edges = [Edge("widget", R.MADE_OF, "brass"), Edge("brass", R.ISA, "material")]
    assert entails("widget", R.ISA, "brass", edges) is None
    assert entails("widget", R.ISA, "material", edges) is None
    # and nothing derived from widget is an ISA edge at all
    assert all(d.edge.relation is not R.ISA for d in derive_from("widget", edges))


def test_part_of_never_becomes_isa():
    # "A zorble is part of a colony." + "A colony is a group."
    edges = [Edge("zorble", R.PART_OF, "colony"), Edge("colony", R.ISA, "group")]
    assert entails("zorble", R.ISA, "colony", edges) is None
    assert entails("zorble", R.ISA, "group", edges) is None


def test_located_in_never_becomes_isa():
    # "A zorble lives in a burrow." + "A burrow is a shelter."
    edges = [Edge("zorble", R.LOCATED_IN, "burrow"), Edge("burrow", R.ISA, "shelter")]
    assert entails("zorble", R.ISA, "burrow", edges) is None
    assert entails("zorble", R.ISA, "shelter", edges) is None


def test_creates_composes_with_nothing_taxonomic():
    # "A carpenter makes a cabinet." + "A cabinet is furniture."
    edges = [Edge("carpenter", R.CREATES, "cabinet"),
             Edge("cabinet", R.ISA, "furniture")]
    assert entails("carpenter", R.ISA, "cabinet", edges) is None
    assert entails("carpenter", R.CREATES, "furniture", edges) is None  # CREATES not inheritable-object


def test_isolation_is_the_default_across_all_pairs():
    # A composition is licensed ONLY by an explicit rule; assert the vast
    # majority of pairs compose to nothing (isolation is the default).
    rels = list(R)
    licensed = sum(1 for a in rels for b in rels if is_licensed(a, b))
    total = len(rels) * len(rels)
    assert licensed < total * 0.10, f"too many licensed pairs ({licensed}/{total})"


# ------------------------------------------- reader integration (real machine)

def test_read_typed_covers_all_seven_constructions():
    from core.semantics import derived_reader as dr
    cases = {
        "A zorble is a fintch.": R.ISA,
        "A zorble has flippers.": R.HAS_PART,
        "A zorble eats krill.": R.EATS,
        "A tinker makes a widget.": R.CREATES,
        "A zorble lives in a burrow.": R.LOCATED_IN,
        "A zorble is part of a colony.": R.PART_OF,
        "A widget is made of brass.": R.MADE_OF,
    }
    for sent, expected in cases.items():
        tr = dr.read_typed(sent)
        assert tr is not None and tr.relation is not None, f"declined: {sent}"
        assert tr.relation.relation is expected, \
            f"{sent} -> {tr.relation.relation} != {expected}"


def test_read_typed_object_is_clean_after_overextension_recovery():
    from core.semantics import derived_reader as dr
    tr = dr.read_typed("A widget is made of brass.")
    assert tr.obj == "brass" and tr.relation.relation is R.MADE_OF
    tr2 = dr.read_typed("A finger is part of a hand.")
    assert tr2.obj == "hand" and tr2.relation.relation is R.PART_OF


def test_made_of_sentence_never_licenses_isa_end_to_end():
    """The whole arc: read a made-of sentence, feed the typed edge to the
    algebra with the material itself a kind, and confirm no ISA is derivable."""
    from core.semantics import derived_reader as dr
    tr = dr.read_typed("A cabinet is made of oak.")
    assert tr.relation.relation is R.MADE_OF
    edges = [Edge(tr.subject, tr.relation.relation, tr.obj),
             Edge("oak", R.ISA, "wood"), Edge("wood", R.ISA, "material")]
    assert entails("cabinet", R.ISA, "oak", edges) is None
    assert entails("cabinet", R.ISA, "material", edges) is None


# ===================== ACQUISITION + GENERALIZATION (open-world) =============

def _teach(sentences):
    """Teach via the REAL reader; return typed Edges (subject, relation, obj)."""
    from core.semantics import derived_reader as dr
    edges = []
    for s in sentences:
        tr = dr.read_typed(s)
        assert tr is not None and tr.relation is not None, f"could not read: {s}"
        edges.append(Edge(tr.subject, tr.relation.relation, tr.obj))
    return edges


def test_open_world_acquisition_and_generalization():
    from core.reasoning.relation_algebra import answer, TRUE, UNKNOWN, OBSERVED, DERIVED

    # Phase 1 — teach only these five facts.
    edges = _teach([
        "A zorble is a fintch.",
        "A fintch is an animal.",
        "A zorble has flippers.",
        "A zorble eats krill.",
        "A zorble lives in a burrow.",
    ])

    # Phase 2 — ask what it was NOT directly told.

    # generalization by ISA transitivity (never taught directly)
    a = answer("zorble", R.ISA, "animal", edges)
    assert a.verdict == TRUE and a.basis == DERIVED
    assert a.derivation.hops == 2                      # zorble->fintch->animal
    assert [e.obj for e in a.derivation.path] == ["fintch", "animal"]

    # taught facts are TRUE and OBSERVED (not derived)
    assert answer("zorble", R.HAS_PART, "flippers", edges).basis == OBSERVED
    assert answer("zorble", R.EATS, "krill", edges).basis == OBSERVED

    # THE NEGATIVE CONTROL: never told, cannot derive -> UNKNOWN, not FALSE.
    wings = answer("zorble", R.HAS_PART, "wings", edges)
    assert wings.verdict == UNKNOWN
    assert wings.verdict != "false"


def test_inverse_is_derived_with_provenance_not_observed():
    from core.reasoning.relation_algebra import (
        answer, derive_from, TRUE, DERIVED, INVERSE)
    # "A zorble has flippers."  =>  flippers PART_OF zorble  (DERIVED, not seen)
    edges = _teach(["A zorble has flippers."])
    inv = answer("flippers", R.PART_OF, "zorble", edges)
    assert inv.verdict == TRUE and inv.basis == DERIVED
    assert inv.derivation.rules == (INVERSE,)
    # the observed direction stays observed
    assert answer("zorble", R.HAS_PART, "flippers", edges).basis == "observed"


def test_ontology_defined_relations_do_not_chain_by_default():
    from core.reasoning.relation_algebra import answer, UNKNOWN, TRUE
    from core.semantics.relation_types import SemanticRelation as SR
    # finger PART_OF hand, hand PART_OF arm  -- PART_OF is ONTOLOGY_DEFINED,
    # so it must NOT chain on its own.
    edges = [Edge("finger", SR.PART_OF, "hand"), Edge("hand", SR.PART_OF, "arm")]
    assert answer("finger", SR.PART_OF, "arm", edges).verdict == UNKNOWN
    # ...but a context that licenses PART_OF transitivity DOES chain it.
    licensed = answer("finger", SR.PART_OF, "arm", edges,
                      context_licenses=frozenset({SR.PART_OF}))
    assert licensed.verdict == TRUE
