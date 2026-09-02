#!/usr/bin/env python3
"""The semantic type of a relation, kept apart from the words that expressed it.

    THE MACHINE READS A SPAN. THIS SAYS WHAT THE SPAN MEANS. THE ALGEBRA SAYS
    WHAT MAY BE INFERRED FROM IT.

`sentence_machine` recovers a predicate SPAN -- the tokens "made of", "lives
in", "is a" -- as pure syntax. It must not decide what that span MEANS: whether
`made of` is the same KIND of relation as `is a` is a fact about the world, not
about token positions, and collapsing every predicate into one "is" edge is
exactly the contamination that poisons inference at scale (`oak -is-> wood`
chaining into `oak -is-> animal`).

This is the semantic authority for that decision, a sibling of `genericity`
(which owns whether a sentence speaks of a KIND). It maps a surface predicate to
a typed `SemanticRelation`, and it records for each type the algebraic
properties the reasoner needs -- transitivity, inheritance down ISA, symmetry,
inverse. It NEVER performs inference; `core.reasoning.relation_algebra` consumes
these properties. Keeping the properties WITH the type, and the inference apart,
is the same split as reader/ingress/reasoning.

    A TYPE IS A CLAIM, AND A CLAIM NEEDS A SOURCE.

Every mapping records where it came from. The surface->type table below is a
CURATED linguistic mapping (`source="curated_lexical_map"`); a teacher or an
imported ontology may add mappings with their own provenance. An unrecognised
predicate is not forced into a taxonomic edge -- it becomes `RELATED_TO`, which
carries the surface verb and licenses NO inference, so an unknown relation is
inert rather than contaminating.

NO MODEL IS INVOLVED. The mapping is data; the classification is a lookup.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, FrozenSet, List, Optional, Tuple

logger = logging.getLogger(__name__)


class SemanticRelation(Enum):
    """The relation a proposition asserts, by KIND.

    Distinct from `core.reasoning.bayesian_uncertainty.RelationType`, which types
    how BELIEFS relate (supports/contradicts). This types how CONCEPTS relate.
    """

    # ── taxonomic ────────────────────────────────────────────────────────
    ISA = "isa"                    # kind -> superkind: robin ISA bird
    INSTANCE_OF = "instance_of"    # individual -> kind: Fido INSTANCE_OF dog

    # ── mereological (part / whole / membership) ─────────────────────────
    PART_OF = "part_of"            # wheel PART_OF car
    HAS_PART = "has_part"          # car HAS_PART wheel   (inverse of PART_OF)
    MEMBER_OF = "member_of"        # robin MEMBER_OF flock
    HAS_MEMBER = "has_member"      # flock HAS_MEMBER robin

    # ── compositional (substance) ────────────────────────────────────────
    MADE_OF = "made_of"            # cabinet MADE_OF wood
    MATERIAL_OF = "material_of"    # wood MATERIAL_OF cabinet (inverse)

    # ── spatial ──────────────────────────────────────────────────────────
    LOCATED_IN = "located_in"      # robin LOCATED_IN nest (contextual)
    CONTAINS = "contains"          # nest CONTAINS robin (inverse)
    LOCATED_AT = "located_at"      # meeting LOCATED_AT office
    ADJACENT_TO = "adjacent_to"    # kitchen ADJACENT_TO hall (symmetric)

    # ── attribute / property ─────────────────────────────────────────────
    HAS_PROPERTY = "has_property"  # snow HAS_PROPERTY white
    PROPERTY_OF = "property_of"    # white PROPERTY_OF snow (inverse)

    # ── causal / conditional ─────────────────────────────────────────────
    CAUSES = "causes"              # rain CAUSES wetness
    CAUSED_BY = "caused_by"        # wetness CAUSED_BY rain (inverse)
    ENABLES = "enables"            # key ENABLES opening
    PREVENTS = "prevents"          # lock PREVENTS opening
    REQUIRES = "requires"          # combustion REQUIRES oxygen
    REQUIRED_BY = "required_by"    # oxygen REQUIRED_BY combustion (inverse)

    # ── functional / productive ──────────────────────────────────────────
    USED_FOR = "used_for"          # hammer USED_FOR driving_nails
    HAS_FUNCTION = "has_function"  # heart HAS_FUNCTION pumping_blood
    PRODUCES = "produces"          # tree PRODUCES oxygen
    PRODUCED_BY = "produced_by"    # oxygen PRODUCED_BY tree (inverse)
    CREATES = "creates"            # carpenter CREATES cabinet

    # ── behavioural / possessive ─────────────────────────────────────────
    EATS = "eats"                  # robin EATS insects
    EATEN_BY = "eaten_by"          # insects EATEN_BY robin (inverse)
    OWNS = "owns"                  # person OWNS car
    OWNED_BY = "owned_by"          # car OWNED_BY person (inverse)

    # ── lexical / definitional ───────────────────────────────────────────
    SYNONYM_OF = "synonym_of"      # (symmetric)
    ANTONYM_OF = "antonym_of"      # (symmetric)
    DEFINED_AS = "defined_as"      # function DEFINED_AS reusable_block
    DERIVED_FROM = "derived_from"  # oxidation DERIVED_FROM oxygen

    # ── temporal ─────────────────────────────────────────────────────────
    PRECEDES = "precedes"          # ignition PRECEDES combustion
    FOLLOWS = "follows"            # combustion FOLLOWS ignition (inverse)

    # ── dispositional ────────────────────────────────────────────────────
    CAPABLE_OF = "capable_of"      # a disposition/ability: birds CAPABLE_OF fly

    # ── the honest fallback ──────────────────────────────────────────────
    RELATED_TO = "related_to"      # an unrecognised verb: inert, licenses nothing


class Transitivity(Enum):
    """Whether A -r-> B -r-> C entails A -r-> C.

    The middle state is the important one: some relations (PART_OF, LOCATED_IN)
    ARE transitive in some ontologies/contexts and not others, and assuming they
    always chain is exactly the contamination this whole layer exists to stop.
    ONTOLOGY_DEFINED means "only when a context explicitly licenses it" -- the
    conservative default is NOT to chain.
    """
    ALWAYS = "always"                    # logically safe (ISA)
    NEVER = "never"                      # chaining is unsound
    ONTOLOGY_DEFINED = "ontology_defined"  # licensed only in context


class EvidenceBehavior(Enum):
    """What a relation licenses the reasoning layer to DERIVE from an observation.
    Kept beside the type so the knowledge layer never has to guess."""
    LOGICAL_DERIVATION = "logical_derivation"   # transitive closure (ISA)
    INHERITANCE = "inheritance"                 # passes down ISA (HAS_PART, EATS)
    INVERSE_DERIVATION = "inverse_derivation"   # the inverse edge may be derived
    ONTOLOGY_DEFINED = "ontology_defined"       # only a context may license it
    NONE = "none"                               # observation stands alone


@dataclass(frozen=True)
class RelationSpec:
    """One relation type, its surface forms, and the algebra it licenses.

    The algebraic properties are what the reasoner reads; nothing here reasons.
      transitivity -- ALWAYS / NEVER / ONTOLOGY_DEFINED (see Transitivity)
      inheritable  -- A ISA B, B r C |= A r C           (r inherits down a kind)
      symmetric    -- A r B          |= B r A
      inverse      -- the relation of B r' A, DERIVABLE (not observed) from A r B
      generic_safe -- a bare indefinite subject may be read as a universal law
                      about the KIND, rather than one existential situation.
    """

    name: SemanticRelation
    #: Surface predicates that map here. Longest-match wins, so "is made of"
    #: beats "is". CURATED; provenance recorded on every classification.
    surface_forms: FrozenSet[str]
    inverse: Optional[SemanticRelation] = None
    transitivity: Transitivity = Transitivity.NEVER
    inheritable: bool = False
    symmetric: bool = False
    generic_safe: bool = True
    gloss: str = ""

    @property
    def transitive(self) -> bool:
        """Back-compat: chains WITHOUT a context only when ALWAYS transitive."""
        return self.transitivity is Transitivity.ALWAYS

    def evidence_behaviors(self) -> "FrozenSet[EvidenceBehavior]":
        """Everything this relation licenses the reasoner to derive."""
        out = set()
        if self.transitivity is Transitivity.ALWAYS:
            out.add(EvidenceBehavior.LOGICAL_DERIVATION)
        elif self.transitivity is Transitivity.ONTOLOGY_DEFINED:
            out.add(EvidenceBehavior.ONTOLOGY_DEFINED)
        if self.inheritable:
            out.add(EvidenceBehavior.INHERITANCE)
        if self.inverse is not None:
            out.add(EvidenceBehavior.INVERSE_DERIVATION)
        return frozenset(out) or frozenset({EvidenceBehavior.NONE})


#: THE ONTOLOGY. Conservative by construction: a flag is set only where the
#: inference it licenses is sound for the type in general, because a wrong
#: composition rule contaminates every chain that touches it, and the whole
#: point of typing relations is to stop that.
_SPECS: Tuple[RelationSpec, ...] = (
    # taxonomic
    RelationSpec(SemanticRelation.ISA,
                 frozenset({"is a", "is an", "are a", "are", "is kind of",
                            "is a kind of", "is type of", "is a type of",
                            "is sort of", "is a sort of", "isa"}),
                 transitivity=Transitivity.ALWAYS, gloss="subsumption between kinds"),
    RelationSpec(SemanticRelation.INSTANCE_OF,
                 frozenset({"is instance of", "is an instance of",
                            "is the", "instance of"}),
                 gloss="an individual falls under a kind"),
    # mereological
    RelationSpec(SemanticRelation.PART_OF,
                 frozenset({"is part of", "part of", "is a part of"}),
                 inverse=SemanticRelation.HAS_PART, transitivity=Transitivity.ONTOLOGY_DEFINED,
                 gloss="proper part of a whole"),
    RelationSpec(SemanticRelation.HAS_PART,
                 frozenset({"has part", "has a", "have", "has", "consists of",
                            "is made up of", "comprises"}),
                 inverse=SemanticRelation.PART_OF, inheritable=True,
                 gloss="a whole has a part"),
    RelationSpec(SemanticRelation.MEMBER_OF,
                 frozenset({"is member of", "is a member of", "member of",
                            "belongs to"}),
                 inverse=SemanticRelation.HAS_MEMBER,
                 gloss="an element of a collection (NOT transitive)"),
    RelationSpec(SemanticRelation.HAS_MEMBER,
                 frozenset({"has member", "has members", "includes"}),
                 inverse=SemanticRelation.MEMBER_OF,
                 gloss="a collection has an element"),
    # compositional
    RelationSpec(SemanticRelation.MADE_OF,
                 frozenset({"is made of", "made of", "made from",
                            "is made from", "composed of", "is composed of",
                            "built from", "is built from", "consists of"}),
                 inverse=SemanticRelation.MATERIAL_OF,
                 gloss="substance a thing is composed of (does NOT imply ISA)"),
    RelationSpec(SemanticRelation.MATERIAL_OF,
                 frozenset({"is material of", "material of"}),
                 inverse=SemanticRelation.MADE_OF),
    # spatial
    RelationSpec(SemanticRelation.LOCATED_IN,
                 frozenset({"is in", "in", "lives in", "located in",
                            "is located in", "found in", "is found in",
                            "inside", "resides in", "sits in", "dwells in"}),
                 inverse=SemanticRelation.CONTAINS, transitivity=Transitivity.ONTOLOGY_DEFINED,
                 generic_safe=False,
                 gloss="containment location (contextual, not a kind law)"),
    RelationSpec(SemanticRelation.CONTAINS,
                 frozenset({"contains", "holds", "encloses"}),
                 inverse=SemanticRelation.LOCATED_IN, generic_safe=False),
    RelationSpec(SemanticRelation.LOCATED_AT,
                 frozenset({"is at", "at", "located at", "is located at",
                            "on", "is on", "on top of", "sits on", "rests on"}),
                 generic_safe=False),
    RelationSpec(SemanticRelation.ADJACENT_TO,
                 frozenset({"next to", "adjacent to", "beside", "near",
                            "borders", "is next to", "is adjacent to"}),
                 symmetric=True, generic_safe=False),
    # attribute
    RelationSpec(SemanticRelation.HAS_PROPERTY,
                 frozenset({"has property", "is"}),   # bare copula + adjective
                 inverse=SemanticRelation.PROPERTY_OF, inheritable=True,
                 gloss="a quality of the subject"),
    RelationSpec(SemanticRelation.PROPERTY_OF,
                 frozenset({"is property of", "property of"}),
                 inverse=SemanticRelation.HAS_PROPERTY),
    # causal
    RelationSpec(SemanticRelation.CAUSES,
                 frozenset({"causes", "cause", "leads to", "results in",
                            "brings about", "induces"}),
                 inverse=SemanticRelation.CAUSED_BY, transitivity=Transitivity.ONTOLOGY_DEFINED,
                 gloss="one thing brings another about"),
    RelationSpec(SemanticRelation.CAUSED_BY,
                 frozenset({"is caused by", "caused by", "results from",
                            "due to", "stems from"}),
                 inverse=SemanticRelation.CAUSES),
    RelationSpec(SemanticRelation.ENABLES,
                 frozenset({"enables", "allows", "permits", "facilitates"})),
    RelationSpec(SemanticRelation.PREVENTS,
                 frozenset({"prevents", "stops", "blocks", "inhibits"})),
    RelationSpec(SemanticRelation.REQUIRES,
                 frozenset({"requires", "needs", "depends on", "presupposes"}),
                 inverse=SemanticRelation.REQUIRED_BY, inheritable=True),
    RelationSpec(SemanticRelation.REQUIRED_BY,
                 frozenset({"is required by", "required by"}),
                 inverse=SemanticRelation.REQUIRES),
    # functional
    RelationSpec(SemanticRelation.USED_FOR,
                 frozenset({"is used for", "used for", "used to", "for"}),
                 inheritable=True, gloss="purpose the thing serves"),
    RelationSpec(SemanticRelation.HAS_FUNCTION,
                 frozenset({"functions as", "serves as", "acts as",
                            "has function", "is used as"}),
                 inheritable=True),
    RelationSpec(SemanticRelation.PRODUCES,
                 frozenset({"produces", "generates", "yields", "emits",
                            "gives off"}),
                 inverse=SemanticRelation.PRODUCED_BY,
                 gloss="a thing yields an output (does NOT imply ISA)"),
    RelationSpec(SemanticRelation.PRODUCED_BY,
                 frozenset({"is produced by", "produced by"}),
                 inverse=SemanticRelation.PRODUCES),
    RelationSpec(SemanticRelation.CREATES,
                 frozenset({"creates", "makes", "builds", "constructs",
                            "manufactures", "assembles"}),
                 gloss="an agent brings an artefact into being"),
    # behavioural / possessive
    RelationSpec(SemanticRelation.EATS,
                 frozenset({"eats", "eat", "feeds on", "preys on", "consumes"}),
                 inverse=SemanticRelation.EATEN_BY, inheritable=True),
    RelationSpec(SemanticRelation.EATEN_BY,
                 frozenset({"is eaten by", "eaten by"}),
                 inverse=SemanticRelation.EATS),
    RelationSpec(SemanticRelation.OWNS,
                 frozenset({"owns", "possesses"}),
                 inverse=SemanticRelation.OWNED_BY, generic_safe=False),
    RelationSpec(SemanticRelation.OWNED_BY,
                 frozenset({"is owned by", "owned by", "belongs to"}),
                 inverse=SemanticRelation.OWNS, generic_safe=False),
    # lexical
    RelationSpec(SemanticRelation.SYNONYM_OF,
                 frozenset({"means", "is synonym of", "same as",
                            "is the same as", "is synonymous with"}),
                 symmetric=True, transitivity=Transitivity.ONTOLOGY_DEFINED),
    RelationSpec(SemanticRelation.ANTONYM_OF,
                 frozenset({"is opposite of", "antonym of",
                            "is the opposite of", "opposite of"}),
                 symmetric=True),
    RelationSpec(SemanticRelation.DEFINED_AS,
                 frozenset({"is defined as", "defined as", "refers to",
                            "denotes"})),
    RelationSpec(SemanticRelation.DERIVED_FROM,
                 frozenset({"is derived from", "derived from", "comes from",
                            "originates from"})),
    # temporal
    RelationSpec(SemanticRelation.PRECEDES,
                 frozenset({"precedes", "comes before", "is before"}),
                 inverse=SemanticRelation.FOLLOWS, transitivity=Transitivity.ONTOLOGY_DEFINED,
                 generic_safe=False),
    RelationSpec(SemanticRelation.FOLLOWS,
                 frozenset({"follows", "comes after", "is after"}),
                 inverse=SemanticRelation.PRECEDES, generic_safe=False),
    # dispositional
    RelationSpec(SemanticRelation.CAPABLE_OF,
                 frozenset({"can", "is able to", "able to", "can do",
                            "is capable of", "capable of"}),
                 inheritable=True,
                 gloss="a disposition/ability the subject has (inherits down ISA)"),
    # fallback
    RelationSpec(SemanticRelation.RELATED_TO, frozenset(),
                 generic_safe=False, gloss="unrecognised: licenses no inference"),
)

SPEC: Dict[SemanticRelation, RelationSpec] = {s.name: s for s in _SPECS}

#: surface phrase -> type, built once from the specs. Longest phrase wins so a
#: specific construction is never shadowed by a copula it contains.
_SURFACE: Dict[str, SemanticRelation] = {}
for _s in _SPECS:
    for _form in _s.surface_forms:
        # A surface form claimed by two types is a conflict, not a silent
        # last-writer-wins: record the FIRST and log the collision so the table
        # stays inspectable.
        if _form in _SURFACE and _SURFACE[_form] is not _s.name:
            logger.warning("relation surface %r maps to both %s and %s; keeping %s",
                           _form, _SURFACE[_form].value, _s.name.value,
                           _SURFACE[_form].value)
            continue
        _SURFACE[_form] = _s.name

_MAX_WORDS = max((len(f.split()) for f in _SURFACE), default=1)

# Word classes the bare copula "is" resolves to when disambiguation is available.
NOUN, ADJECTIVE, VERB = "NOUN", "ADJECTIVE", "VERB"


@dataclass(frozen=True)
class TypedRelation:
    """The result of classifying a predicate span."""

    relation: SemanticRelation
    surface: str                 # the span as read
    matched: str                 # the surface form that matched (or "")
    source: str                  # provenance of the mapping
    generic: bool                # is this asserted about a kind?

    @property
    def spec(self) -> RelationSpec:
        return SPEC[self.relation]


def _normalize(span: str) -> str:
    return " ".join(str(span).replace("_", " ").lower().split())


def classify(span: str, *,
             object_word_class: Optional[str] = None,
             generic: bool = True,
             source: str = "curated_lexical_map") -> TypedRelation:
    """Type a predicate span. Never guesses beyond the table.

    The bare copula is genuinely ambiguous and is resolved only where the
    evidence to resolve it is present: `is` + an ADJECTIVE object is
    HAS_PROPERTY, `is` + a NOUN is ISA, and with no word-class hint it stays ISA
    (the copula's most common relational reading) rather than inventing a
    property. An unrecognised predicate is RELATED_TO, which licenses nothing.
    """
    norm = _normalize(span)
    words = norm.split()

    # Longest-match over the surface table.
    match: Optional[str] = None
    for n in range(min(_MAX_WORDS, len(words)), 0, -1):
        cand = " ".join(words[:n])
        if cand in _SURFACE:
            match = cand
            break
        # also allow the whole span to match a multiword form not anchored at 0
        if n == len(words) and norm in _SURFACE:
            match = norm
            break

    # VERB + PARTICLE. "sat on", "rests on", "jumps over" put the relation in a
    # trailing preposition the leading verb is not part of the table for. When
    # the anchored match fails, a span whose LAST token is itself a known form
    # (a preposition/particle) is that relation -- the cat SAT ON the mat is
    # LOCATED_AT the mat. Kept deliberately narrow (last token only, and only a
    # single-word form) so a genuine dropped-noun-phrase span, whose last word
    # is a noun and not in the table, still declines rather than being typed.
    if match is None and len(words) > 1 and words[-1] in _SURFACE:
        match = words[-1]

    if match is None:
        return TypedRelation(SemanticRelation.RELATED_TO, span, "", source, generic)

    rel = _SURFACE[match]

    # Disambiguate the bare copula with a word-class hint when there is one.
    # ONLY an ADJECTIVE object makes it HAS_PROPERTY; a NOUN, a VERB, or no hint
    # at all reads as ISA -- the copula's default relational reading -- never a
    # property invented from a non-adjective. (A VERB object arises for a
    # no-copula sentence whose empty span defaults to "is", e.g. "the pump
    # runs"; it must not be read as a property.)
    if match in ("is", "are"):
        rel = (SemanticRelation.HAS_PROPERTY
               if object_word_class == ADJECTIVE else SemanticRelation.ISA)

    generic_result = generic and SPEC[rel].generic_safe
    return TypedRelation(rel, span, match, source, generic_result)


def get_spec(relation: SemanticRelation) -> RelationSpec:
    return SPEC[relation]


def all_surface_forms() -> Dict[str, SemanticRelation]:
    """The full curated table, for inspection and for teaching new mappings."""
    return dict(_SURFACE)


__all__ = ["SemanticRelation", "Transitivity", "EvidenceBehavior",
           "RelationSpec", "TypedRelation", "SPEC",
           "classify", "get_spec", "all_surface_forms",
           "NOUN", "ADJECTIVE", "VERB"]
