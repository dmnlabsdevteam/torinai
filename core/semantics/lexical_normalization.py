#!/usr/bin/env python3
"""One canonical lexical interpretation of a surface form, for all of Torin.

The invariant:

    One surface form has one canonical lexical interpretation across every
    cognitive path.

This exists because two paths disagreed. Concept identity normalised through
`ConceptResolver`, which singularises, so `men` and `man` were one thing. The
formalizer that turns prose into logic had its own private normaliser that only
lowercased and stripped articles, so to the solver they were two things -- and
"Socrates is a man. All men are mortal. Is Socrates mortal?" could not be
proved, because the encoding produced `socrates_man` alongside
`socrates_men -> socrates_mortal` and modus ponens had nothing to fire on.

A substrate whose concept store believes `men == man` while its logic believes
`men != man` does not have one vocabulary. Both callers now delegate here.

Scope discipline: this normalises GRAMMATICAL variation, never synonymy.
`men -> man` and `people -> person` are morphology. `human -> person` is a
claim about the world, and belongs to concept identity and its alias evidence,
not to a string function. Letting canonicalisation invent equivalences would
turn a lexical layer into an unbounded semantic one, and nothing downstream
could tell which had happened.
"""

from __future__ import annotations

import re
from typing import Dict, FrozenSet

_NORMALISE_STRIP = re.compile(r"[^a-z0-9 _-]+")
_WS = re.compile(r"\s+")

#: Irregulars, keyed by the form that ARRIVES. Both the plural (which must
#: reduce) and the singular (which must not) appear, because the general `-s`
#: rule turns `gases` into `gase` and `analyses` into `analyse`.
PLURAL_EXCEPTIONS: Dict[str, str] = {
    # plural -> singular
    "analyses": "analysis", "bases": "basis", "crises": "crisis",
    "hypotheses": "hypothesis", "theses": "thesis", "matrices": "matrix",
    "indices": "index", "vertices": "vertex", "gases": "gas",
    "lenses": "lens", "phases": "phase", "cases": "case",
    # singular forms that already end in -s or -is and must not be stripped
    "analysis": "analysis", "basis": "basis", "series": "series",
    "species": "species", "gas": "gas", "process": "process",
    "class": "class", "mass": "mass", "glass": "glass", "lens": "lens",
    "stress": "stress", "loss": "loss", "bias": "bias", "axis": "axis",
}

#: Irregular plurals with no rule to derive them. Kept deliberately short:
#: every entry is a claim about English, and an unsupported one silently
#: rewrites a term the substrate reasons over. Extend with a test, not by
#: guesswork.
IRREGULAR_SINGULARS: Dict[str, str] = {
    "men": "man", "women": "woman", "children": "child", "people": "person",
    "mice": "mouse", "feet": "foot", "teeth": "tooth",
    # Each checked against WordNet's lemmatiser before being added, which is
    # the standard this table's docstring asks for. `dice` was in this list and
    # has been removed: WordNet keeps it as its own lemma, and in ordinary use
    # it is a mass noun rather than the plural of `die`. It was guesswork, and
    # this table is explicitly not the place for that.
    "geese": "goose", "oxen": "ox", "lice": "louse",
}

#: Fields of study ending in -ics. These are MASS NOUNS, not plurals, so the
#: general -s rule destroys them: `physics` became `physic`, and physics
#: concepts attached to a domain that does not exist.
#:
#: An explicit set rather than a blanket `-ics` rule, because the rule cannot
#: tell a field from a plural: `characteristics` IS the plural of
#: `characteristic` and must still reduce.
ICS_MASS_NOUNS: FrozenSet[str] = frozenset({
    "physics", "mathematics", "economics", "statistics", "mechanics",
    "electronics", "optics", "dynamics", "thermodynamics", "linguistics",
    "informatics", "robotics", "genetics", "ethics", "politics",
    "logistics", "acoustics", "aerodynamics", "ceramics", "graphics",
    "analytics", "semantics", "kinetics", "photonics", "cybernetics",
})

#: Words a document uses about itself. `introduction_of_lifepo4` is document
#: structure, not a thing that exists independently of the document.
STRUCTURAL_PREFIXES = ("introduction_of_", "overview_of_", "review_of_",
                       "summary_of_", "conclusion_of_", "study_of_",
                       "the_", "a_", "an_")

#: Generic tails an extractor appends that name a CATEGORY of the concept
#: rather than a different concept: lithium_iron_phosphate_batteries is the
#: same substance as lithium_iron_phosphate.
#: SINGULAR forms only. Plurals are collapsed before this list is applied, so
#: listing both spellings would strip `safety_characteristics` down to `safety`
#: while leaving `safety_characteristic` intact -- splitting the pair this is
#: meant to merge.
QUALIFIER_TAILS = ("_battery", "_material", "_system", "_device", "_technology")


def normalise(label: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace to underscores."""
    s = _WS.sub(" ", str(label).strip().lower())
    s = _NORMALISE_STRIP.sub("", s)
    return s.strip().replace(" ", "_")


def singularise(word: str) -> str:
    """Reduce a plural to its singular. Grammatical variation only."""
    if word in IRREGULAR_SINGULARS:
        return IRREGULAR_SINGULARS[word]
    if word in PLURAL_EXCEPTIONS:
        return PLURAL_EXCEPTIONS[word]
    # Singular endings the general -s rule destroys:
    #   -sis  synthesis -> synthesi
    #   -ics  physics   -> physic     (a mass noun, not a plural)
    if word.endswith("sis") or word.endswith("xis"):
        return word
    if word in ICS_MASS_NOUNS:
        return word
    if word.endswith("ies") and len(word) > 4:
        return word[:-3] + "y"
    if word.endswith("sses") or word.endswith("shes") or word.endswith("ches"):
        return word[:-2]
    if word.endswith("s") and not word.endswith("ss") and len(word) > 3:
        return word[:-1]
    return word


#: Determiners carry no identity: `the ladder` and `ladder` are one thing.
#: Separated from STRUCTURAL_PREFIXES because those are document artefacts
#: ("introduction_of_") that only make sense for text extracted from a
#: document, while these apply to any surface form in any path.
DETERMINER_PREFIXES = ("the_", "a_", "an_")


def canonical_term(label: str) -> str:
    """The identity-bearing form of a TERM: grammar only, no document heuristics.

    THE GRAMMATICAL CORE THAT EVERY PATH MUST SHARE. This module's invariant is
    that one surface form has one canonical interpretation across every
    cognitive path, and it was written because two paths disagreeing produced
    `socrates_man` beside `socrates_men`, leaving modus ponens nothing to fire
    on. But the only function it offered was `canonical_label`, which also
    applies DOCUMENT heuristics -- acronym restatement, generic category tails
    -- that are correct for a label scraped out of a paper and destructive
    anywhere else: `nervous system` -> `nervous`, `lithium battery` ->
    `lithium`.

    So `cognitive_ingress` could not delegate here without losing meaning, and
    kept its own normaliser instead. That normaliser stripped determiners but
    never singularised, so `bird` and `birds` were two concepts at the one door
    every piece of knowledge enters through -- exactly the split this module
    exists to prevent, in the one place it matters most.

    This is the part that is genuinely common: lowercase, punctuation,
    determiners, plurals. Nothing about documents.
    """
    s = normalise(label).replace("-", "_")
    s = re.sub(r"_+", "_", s).strip("_")

    for prefix in DETERMINER_PREFIXES:
        # `the_` off `the_ladder`, but never off `the_` alone or `then`.
        if s.startswith(prefix) and len(s) > len(prefix):
            s = s[len(prefix):]
            break

    parts = [p for p in s.split("_") if p]
    if parts:
        parts[-1] = singularise(parts[-1])
    return "_".join(parts).strip("_")


#: Verb endings collapsed for RETRIEVAL only. `running`/`ran`/`run` are one
#: thing when you are looking something up and three things when you are
#: deciding what exists.
_VERB_ENDINGS = ("ing", "ed")
_DOUBLED = re.compile(r"([a-z])\1$")


def match_key(label: str) -> str:
    """The RETRIEVAL form of a label. Looser than identity, deliberately.

    TWO JOBS, OPPOSITE FAILURE MODES. `canonical_term` decides what a thing IS
    and must not over-merge: fuse two concepts and the store cannot be
    unfused. This decides whether two words are worth COMPARING, and should
    over-merge slightly: a missed match means the substrate cannot find
    something it already knows, and the failure looks like ignorance rather
    than a lookup miss.

    One function cannot serve both. `analyses -> analysis` is right for
    identity; for retrieval you want `analyses`, `analysing` and `analyse` to
    collide, which would be wrong at the door.

    THIS REPLACES THREE PRIVATE IMPLEMENTATIONS that disagreed with each other
    and with this module, measured across nine ordinary words:

        word        conversation.stem   tool_discovery._stem   canonical_term
        files       fil                 file                   file
        indices     indic               indice                 index
        analyses    analys              analyse                analysis
        batteries   batteri             battery                battery
        geese       geese               geese                  goose

    `fil`, `indic`, `analys`, `batteri` are not words, and `indice` is not the
    singular of anything -- so a query for `indices` could never reach a tool
    filed under `index`. Every path now asks here.
    """
    key = canonical_term(label)
    parts = key.split("_")
    if parts:
        parts[-1] = _reduce_verb(parts[-1])
    return "_".join(p for p in parts if p)


def _reduce_verb(word: str) -> str:
    """Collapse a verb family to one key: cause/causes/caused/causing.

    THE TRAILING `e` IS THE SEAM. Stripping `ed`/`ing` leaves `caus`, while the
    plural rule turns `causes` into `cause` -- so the four forms landed on two
    different keys and a question about what "causes" something could not match
    a relation stored as "caused by". A real test caught exactly that:
    "what causes pressure loss" resolved the concept and then found none of its
    edges.

    Removing a trailing `e` after the suffix work puts the whole family on one
    key. It shortens some nouns too (`file` -> `fil`), which is harmless here
    and would not be at the ingress -- both sides of every comparison are
    reduced the same way, and this is a retrieval key, never an identity.
    """
    for ending in _VERB_ENDINGS:
        if len(word) > len(ending) + 2 and word.endswith(ending):
            # `running` -> `runn` -> `run`; the doubled consonant is an
            # artefact of the suffix, not part of the stem.
            word = _DOUBLED.sub(r"\1", word[: -len(ending)])
            break
    if len(word) > 3 and word.endswith("e"):
        word = word[:-1]
    return word


def canonical_label(label: str) -> str:
    """The identity-bearing form of a DOCUMENT-DERIVED label.

    `canonical_term` plus the collapsing that only makes sense for text pulled
    out of a document: structural prefixes, trailing acronym restatements and
    generic category tails.
    """
    s = normalise(label).replace("-", "_")
    s = re.sub(r"_+", "_", s).strip("_")

    for prefix in STRUCTURAL_PREFIXES:
        if s.startswith(prefix) and len(s) > len(prefix) + 2:
            s = s[len(prefix):]
            break

    # "phosphoric_acid_fuel_cells_pafc" -> the trailing token is the acronym of
    # what precedes it, so it restates rather than distinguishes.
    parts = s.split("_")
    if len(parts) > 2:
        initials = "".join(w[0] for w in parts[:-1] if w)
        tail = parts[-1]
        if tail.isalpha() and len(tail) >= 3 and tail in (initials, initials[-len(tail):]):
            s = "_".join(parts[:-1])

    # Singularise BEFORE stripping tails, so plural and singular spellings of
    # the same qualifier reduce identically.
    parts = s.split("_")
    if parts:
        parts[-1] = singularise(parts[-1])
    s = "_".join(p for p in parts if p)

    for tail in QUALIFIER_TAILS:
        if s.endswith(tail) and len(s) > len(tail) + 2:
            s = s[: -len(tail)]
            break

    return s.strip("_")
