#!/usr/bin/env python3
"""Reading a sentence into structure. SEMANTICS OWNS THIS.

MOVED OUT OF `core/reasoning/neural_bridge.py` on 2026-08-24, where 619 lines of
English patterns had grown inside the reasoning module. Reasoning should CONSUME
a reading, not implement one, and language is this faculty's job -- the learned
reader, the lexicon, the claim shapes and the sentence machine all already live
here.

WHAT THIS IS, AND WHAT IT IS NOT. These are hand-written patterns, and they are
scaffolding. The substrate's own reader is DERIVED -- learned from
sentence/meaning pairs, in `derived_reader` and `reading_registry` -- and
measured broader than these on the forms both attempt, while correctly refusing
what it cannot represent. The intended direction is that the derived reading
takes over and this shrinks toward nothing.

It has not been removed because it has not been replaced: these patterns also
cover universals, conditionals, questions and conjunctions, and what share of
those the derived reading handles is unmeasured. Deleting on an unmeasured
assumption would trade working coverage for a silent gap.

WHAT A READING IS. A sentence in, a structure out, or None. It decides only WHAT
a sentence relates -- never whether the formal grammar can carry that relation,
which is genericity's separate stage, and never how to render it for a solver,
which is the reasoning side's job.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from core.reasoning.reasoning_interfaces import Connectivity  # noqa: F401
from core.semantics import lexical_normalization as _lexical
from core.semantics.genericity import (Genericity, classify_genericity,
                                       unrepresentable_reason, _word_class)

logger = logging.getLogger(__name__)


class SentenceReader:
    """Turns a bounded slice of English into structure. Needs no model."""

    _ARTICLES = ("a ", "an ", "the ")
    _DETERMINER = r"(?:(?P<det>a|an|the)\s+)?"
    _COPULA = r"(?:is|are)"
    _FACT = re.compile(
        rf"^{_DETERMINER}(?P<subject>[\w'-]+)\s+{_COPULA}\s+(?P<prop>.+)$",
        re.IGNORECASE,
    )
    _NEGATED_FACT = re.compile(
        rf"^{_DETERMINER}(?P<subject>[\w'-]+)\s+{_COPULA}\s+not\s+(?P<prop>.+)$",
        re.IGNORECASE,
    )
    _SVO = re.compile(
        rf"^{_DETERMINER}(?P<subject>[\w'-]+)\s+(?P<verb>[\w'-]+)\s+"
        rf"(?:(?:a|an|the)\s+)?(?P<object>[\w'-]+)$", re.IGNORECASE)
    _PREPOSITIONS = ("in", "on", "under", "inside", "above", "below",
                     "near", "behind")
    _PREPOSITIONAL = re.compile(
        r"^(?P<prep>in|on|under|inside|above|below|near|behind)\s+"
        r"(?:(?:a|an|the)\s+)?(?P<object>[\w'-]+(?:\s+[\w'-]+)*)$",
        re.IGNORECASE)
    _SV = re.compile(
        rf"^{_DETERMINER}(?P<subject>[\w'-]+)\s+(?P<verb>[\w'-]+)$",
        re.IGNORECASE)
    _UNIVERSAL = re.compile(
        r"^(?:all|every)\s+(?P<p>[\w\s'-]+?)\s+(?:are|is)\s+(?P<q>[\w\s'-]+)$",
        re.IGNORECASE,
    )
    _NEGATIVE_UNIVERSAL = re.compile(
        r"^no\s+(?P<p>[\w\s'-]+?)\s+(?:are|is)\s+(?P<q>[\w\s'-]+)$", re.IGNORECASE
    )
    _CONDITIONAL = re.compile(
        r"^if\s+(?P<antecedent>.+?)[,]?\s+then\s+(?P<consequent>.+)$", re.IGNORECASE
    )
    _QUESTION = re.compile(
        rf"^is\s+{_DETERMINER}(?P<subject>[\w'-]+)\s+(?P<prop>.+?)\s*\?*$",
        re.IGNORECASE,
    )
    def _normalize(self, phrase: str) -> str:
        """Reduce a phrase to a snake_case atom fragment.

        Delegates orthography to the shared lexical layer. This used to be a
        private implementation that only lowercased and stripped articles,
        while concept identity normalised through a singularising one -- so the
        substrate's logic believed `men != man` while its concept store
        believed `men == man`, and the canonical syllogism could not be proved.
        """
        cleaned = phrase.strip().rstrip("?.!,")
        for article in self._ARTICLES:
            if cleaned.lower().startswith(article):
                cleaned = cleaned[len(article):]
                break
        return _lexical.normalise(cleaned)
    def _singular(self, word: str) -> str:
        """Fold a plural onto its singular via the shared morphology.

        Deliberately `singularise` and not `canonical_label`: the latter also
        strips qualifier tails and acronym restatements, which are concept-
        IDENTITY policy -- claims that lithium_iron_phosphate_battery and
        lithium_iron_phosphate are the same thing. That is synonymy, and
        synonymy must come from alias evidence, not from a string function
        applied to a logical predicate.
        """
        return _lexical.singularise(word)
    def _atom(self, subject: str, prop: str) -> str:
        return f"{self._normalize(subject)}_{self._singular(self._normalize(prop))}"
    def _parse_statement(self, text: str) -> Optional[Dict[str, Any]]:
        """Classify one sentence, or return None if it is outside the slice."""
        sentence = text.strip().rstrip(".")
        if not sentence:
            return None

        match = self._CONDITIONAL.match(sentence)
        if match:
            antecedent = self._parse_statement(match.group("antecedent"))
            consequent = self._parse_statement(match.group("consequent"))
            if not antecedent or not consequent:
                return None
            if antecedent["kind"] != "fact" or consequent["kind"] != "fact":
                return None
            return {"kind": "conditional", "antecedent": antecedent, "consequent": consequent}

        match = self._NEGATIVE_UNIVERSAL.match(sentence)
        if match:
            return {
                "kind": "universal",
                "p": match.group("p"),
                "q": match.group("q"),
                "negated": True,
            }

        match = self._UNIVERSAL.match(sentence)
        if match:
            return {
                "kind": "universal",
                "p": match.group("p"),
                "q": match.group("q"),
                "negated": False,
            }

        match = self._NEGATED_FACT.match(sentence)
        if match:
            return self._read_copular(match, negated=True)

        match = self._FACT.match(sentence)
        if match:
            return self._read_copular(match, negated=False)

        # SVO / SV last, and only when the LEXICON identifies the verb.
        #
        # Tried after the copular forms because "the vault is locked" also
        # matches the SVO shape token-for-token; `is` is simply not a verb the
        # lexicon carries. Nothing here guesses: a sentence whose middle word
        # has no established class produces NO reading, which is the honest
        # answer for a word the substrate has not learned.
        for pattern, kind in ((self._SVO, "svo"), (self._SV, "sv")):
            match = pattern.match(sentence)
            if not match:
                continue
            verb = match.group("verb").lower()
            verb_class = _word_class(verb)
            if verb_class not in (None, "VERB"):
                continue        # a known noun or adjective is not the action

            if verb_class is None:
                # THE KNOWN WORDS AROUND IT IDENTIFY THE VERB.
                #
                # Requiring the verb's class BEFORE parsing made a verb
                # unlearnable: to read "the tank pushes water" you needed to
                # know `pushes`, and the only way to learn `pushes` is to read a
                # sentence using it. Measured: with the spelling guess removed,
                # every verb exposure sentence stopped reading and all three
                # verbs stayed undecided.
                #
                # The anchor is the subject. When the thing the sentence is
                # about is a known NOUN, the word standing after it is the
                # action -- which is how a learner meets a new verb. No anchor,
                # no reading: this never guesses from an all-unknown sentence.
                subject_class = _word_class(match.group("subject"))
                if subject_class != "NOUN":
                    continue
            groups = match.groupdict()
            if kind == "svo":
                return {"kind": "svo", "subject": groups["subject"],
                        "verb": verb, "object": groups["object"]}
            return {"kind": "sv", "subject": groups["subject"], "verb": verb}

        return None
    def _read_copular(self, match, *, negated: bool) -> Dict[str, Any]:
        """Classify a copular sentence BEFORE deciding how to represent it.

        The article alone is not a quantification cue. Reading "a" as universal
        turns "A robin is in the yard" into a law about all robins, so the
        proposition type is decided first and the representation follows from
        it.
        """
        subject = match.group("subject")
        prop = match.group("prop")
        determiner = match.groupdict().get("det")

        # THE LEXICON DISCRIMINATES THE COPULAR FORM TOO.
        #
        # Pattern alone cannot separate "the tank is heavy" from "the cold is
        # heavy": both are `det WORD is WORD`. So both read, and noun and
        # adjective were indistinguishable -- which is why classifying the nine
        # held-out words scored 0/9 with every one fitting BOTH frames.
        #
        # A subject must not be a known ADJECTIVE, and a property must not be a
        # known NOUN. Only KNOWN classes reject: a word the substrate has not
        # learned still reads exactly as before, so this adds discrimination
        # where teaching has happened and takes none away where it has not.
        # That is what makes the frames a measurement instead of a formality.
        if _word_class(subject) == "ADJECTIVE":
            return {"kind": "unsupported",
                    "reason": "an adjective cannot be the subject of a fact",
                    "genericity": "n/a", "cue": f"{subject} is a known adjective"}
        # A PREPOSITION IS A RELATION, NOT A PROPERTY.
        #
        # "the valve is in the pump" read as `valve_in_the_pump`: one atom, with
        # the determiner inside it. Structurally false -- it says the valve has
        # a property called "in the pump", so nothing can ask what the valve is
        # in, and `valve_in_the_pump` and `valve_in_the_tank` share nothing.
        # Both things related are nouns, and the relation between them is what
        # the sentence is for.
        # A PREPOSITION WITH NOTHING TO RELATE TO IS NOT A PROPERTY.
        # "the cup is in" read as the property `in`. A relation needs both
        # things; missing one is a sentence with no reading.
        first = prop.strip().split()[0].lower() if prop.strip() else ""
        if first in self._PREPOSITIONS and not self._PREPOSITIONAL.match(prop.strip()):
            return {"kind": "unsupported",
                    "reason": "a preposition with nothing to relate to",
                    "genericity": "n/a", "cue": prop}

        relation = self._PREPOSITIONAL.match(prop.strip())
        if relation:
            other = relation.group("object")
            if _word_class(other) == "ADJECTIVE":
                return {"kind": "unsupported",
                        "reason": "a preposition relates two things, and an "
                                  "adjective is not a thing",
                        "genericity": "n/a", "cue": f"{other} is a known adjective"}

            # WHICH ONE IS IN THE YARD? A relation needs a subject that DENOTES
            # something, and an indefinite subject does not.
            #
            # This branch returned a relation without ever classifying the
            # sentence -- genericity was checked further down and never reached
            # once a preposition matched. So "A robin is in the yard" became
            # `in(robin, yard)`, reading `robin` as a named individual, when the
            # sentence says SOME robin. The existential quantification was
            # dropped silently and the result asserted something about the kind.
            #
            # That is the failure this module's genericity stage exists to
            # prevent, arriving from the other side: not "all robins are in the
            # yard" but "robin, the thing, is in the yard". EXISTENTIAL is
            # deliberately not representable -- the formal grammar has no
            # existential quantifier -- and a locative does not become
            # representable by being a relation.
            #
            # A definite or proper subject reads as INSTANCE and still works:
            # "the cup is in the top cabinet" names a cup, and that is the case
            # this pattern was added for.
            locative_reading = classify_genericity(subject, prop, determiner)
            if not locative_reading.is_representable:
                return {"kind": "unsupported",
                        "subject": subject, "prop": prop,
                        "reason": unrepresentable_reason(locative_reading.genericity),
                        "genericity": locative_reading.genericity.value,
                        "cue": locative_reading.cue}
            return {"kind": "relation", "subject": subject,
                    "preposition": relation.group("prep").lower(),
                    "object": other, "negated": negated}

        # "AND" JOINS TWO CLAIMS, IT DOES NOT NAME ONE THING.
        #
        # "the pump is hot and loud" read as `pump_hot_and_loud` -- a single
        # property whose name contains a conjunction. The sentence asserts two
        # things and the reading asserted one, so neither could be checked
        # against anything else the substrate knew about hot or about loud.
        if " and " in prop or prop.rstrip().endswith(" and"):
            if negated:
                # "not hot and loud" is genuinely ambiguous in English between
                # ~(hot & loud) and (~hot & ~loud). Refusing is the honest
                # answer; picking one would record a claim the sentence does
                # not settle.
                return {"kind": "unsupported",
                        "reason": "a negated conjunction is ambiguous",
                        "genericity": "n/a", "cue": prop}
            # Split on the word, not on " and " with spaces both sides: "hot
            # and" does not contain the padded form, so it split to ["hot and"]
            # and fell through to the plain-fact path, reading a truncated
            # sentence as the property `hot_and`.
            parts = [p.strip() for p in re.split(r"\s+and\s*", prop)]
            usable = [p for p in parts if p]
            if len(usable) != len(parts) or len(usable) < 2:
                # A side with nothing in it. The sentence was cut off, and a
                # cut-off sentence has no reading -- which is different from
                # having a reading nobody checked.
                return {"kind": "unsupported",
                        "reason": "a conjunction with an empty side",
                        "genericity": "n/a", "cue": prop}
            if all(len(p.split()) == 1 for p in usable):
                return {"kind": "conjunction", "subject": subject,
                        "properties": usable, "negated": False}
            return {"kind": "unsupported",
                    "reason": "a conjunct that is not a single property",
                    "genericity": "n/a", "cue": prop}

        if _word_class(prop) == "NOUN":
            return {"kind": "unsupported",
                    "reason": "a noun cannot be a property",
                    "genericity": "n/a", "cue": f"{prop} is a known noun"}

        reading = classify_genericity(subject, prop, determiner)

        if reading.genericity is Genericity.GENERIC_KIND:
            # A claim about a KIND. `_normalize` strips the complement's
            # article downstream, so "a bird" becomes the predicate `bird`.
            return {
                "kind": "universal",
                "p": subject,
                "q": prop,
                "negated": negated,
                "genericity": reading.genericity.value,
                "cue": reading.cue,
                "transformations": list(reading.transformations),
            }

        if reading.genericity is Genericity.INSTANCE:
            return {
                "kind": "fact",
                "subject": subject,
                "prop": prop,
                "negated": negated,
                "genericity": reading.genericity.value,
                "cue": reading.cue,
            }

        # UNDERSTOOD, BUT NOT REPRESENTABLE. Classification succeeded; the
        # formal grammar has no existential quantifier, and an ambiguous
        # sentence has no single reading to choose. Rendering either as an atom
        # would keep the pipeline running while discarding the quantifier.
        return {
            "kind": "unsupported",
            "subject": subject,
            "prop": prop,
            "negated": negated,
            "genericity": reading.genericity.value,
            "cue": reading.cue,
            "reason": unrepresentable_reason(reading.genericity),
        }
    def _parse_goal(self, text: str) -> Optional[Dict[str, Any]]:
        """Parse the query, which may be phrased as a question.

        A goal carries its genericity too. "Is Tweety an animal?" asks about an
        individual; "Is a robin an animal?" asks about a KIND, and the two need
        different formalizations -- see `formalize`.
        """
        match = self._QUESTION.match(text.strip())
        if match:
            reading = classify_genericity(match.group("subject"), match.group("prop"),
                                          match.groupdict().get("det"))
            return {
                "kind": "fact",
                "subject": match.group("subject"),
                "prop": match.group("prop"),
                "negated": False,
                "genericity": reading.genericity.value,
            }
        return self._parse_statement(text)
    def _render_relation(self, node) -> str:
        """`the valve is in the pump` -> valve_in_pump (or ~valve_in_pump).

        The determiner is dropped and the object singularised, so the atom names
        the two THINGS and the relation between them -- which is what lets
        `valve_in_pump` and `valve_in_tank` be recognised as the same question
        asked of different things.
        """
        subject = self._singular(self._normalize(node["subject"]))
        other = self._singular(self._normalize(node["object"]))
        atom = f"{subject}_{node['preposition']}_{other}"
        return f"~{atom}" if node.get("negated") else atom
    def _render_conjunction(self, node) -> List[str]:
        """`the pump is hot and loud` -> [pump_hot, pump_loud]."""
        subject = self._singular(self._normalize(node["subject"]))
        return [f"{subject}_{self._normalize(p)}" for p in node["properties"]]
    def _render_action(self, node) -> str:
        """An action sentence as a single atom.

        The object keeps its own name rather than being folded into the verb,
        so `pump_moves_water` and `pump_moves_air` are different atoms about the
        same action -- which is what lets anything downstream notice they are
        related.
        """
        subject = self._singular(self._normalize(node["subject"]))
        verb = self._normalize(node["verb"])
        if node["kind"] == "sv":
            return f"{subject}_{verb}"
        obj = self._singular(self._normalize(node["object"]))
        return f"{subject}_{verb}_{obj}"
    def _render_fact(self, node: Dict[str, Any]) -> str:
        atom = self._atom(node["subject"], node["prop"])
        return f"~{atom}" if node["negated"] else atom
