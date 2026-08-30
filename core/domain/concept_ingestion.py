#!/usr/bin/env python3
"""Concept Ingestion Service

The single edge across which experience becomes semantic structure.

Torin's concept layer answers "what things, kinds of things, properties and
relationships does Torin know how to represent?" -- distinct from memory (what
happened), beliefs (what is currently thought true) and induced schemas (what
recurring rule was abstracted). Nothing may write a semantic concept except
through this service, so that every concept in the store carries a chain back
to the observation that produced it.

Before this existed, `unified.concepts` had exactly one producer:
AnalogyDiscovery._load_sample_data, which wrote twelve hardcoded demonstration
concepts (atom, molecule, cell, market, ...) on every initialize(). Twelve of
the store's thirteen rows were those fixtures, and every analogy and every
cross-domain mapping computed downstream was computed over them.

Design constraints this enforces:

  * The LLM proposes, the substrate decides. An extractor emits a
    ConceptCandidate; it never assigns identity, never dedupes, never writes.
  * Concept identity is separate from claims about the concept. Knowing a thing
    called "atom" exists is cheap; asserting it relates to "molecule" is not.
  * Support counts DISTINCT ROOT evidence. A memory is a representation of prior
    experience, so counting it as fresh evidence would let Torin re-read its own
    narrative and promote a weak statement by repetition.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from core.semantics import lexical_normalization as _lexical

from .domain_types import ConceptType

logger = logging.getLogger(__name__)


class EvidenceSourceType(Enum):
    """Where an observation came from.

    MEMORY_RETROSPECTIVE is deliberately last-class: it is the only source that
    is itself a representation of earlier evidence rather than a fresh
    observation, and it MUST carry derived_from.
    """
    RESEARCH_FINDING = "research_finding"
    #: A rule the substrate induced for itself. DERIVATIVE by construction: it
    #: is a generalization OF demonstrations, so it must declare the evidence it
    #: was induced from. Ingesting it as a root would let one rule count as
    #: fresh support for the concepts its own training examples already
    #: supported -- the version space would appear corroborated by itself.
    INDUCED_RULE = "induced_rule"
    TOOL_OBSERVATION = "tool_observation"
    TASK_ARTIFACT = "task_artifact"
    PERCEPTION = "perception"
    USER_SUPPLIED = "user_supplied"
    IMPORTED_KNOWLEDGE = "imported_knowledge"
    MEMORY_RETROSPECTIVE = "memory_retrospective"


#: Sources that are fresh observations. Anything outside this set is derivative
#: and cannot introduce root evidence of its own.
_ROOT_SOURCES = frozenset({
    EvidenceSourceType.RESEARCH_FINDING,
    EvidenceSourceType.TOOL_OBSERVATION,
    EvidenceSourceType.TASK_ARTIFACT,
    EvidenceSourceType.PERCEPTION,
    EvidenceSourceType.USER_SUPPLIED,
    EvidenceSourceType.IMPORTED_KNOWLEDGE,
})


class ConceptExistence(Enum):
    """How well established a concept's EXISTENCE is.

    Says nothing about claims made about the concept -- those carry their own
    support. UNSEEN is never stored: the absence of a row is that state.
    """
    UNSEEN = "UNSEEN"
    PROPOSED = "PROPOSED"
    OBSERVED = "OBSERVED"
    WELL_SUPPORTED = "WELL_SUPPORTED"


#: POLICY THRESHOLD for corroboration status. NOT a calibrated probability of
#: correctness.
#:
#: WELL_SUPPORTED means "supported by at least this many independent evidentiary
#: roots" -- nothing more. Two independent sources can both be wrong, and root
#: independence measures corroboration, not truth. Reading this as a validated
#: fact is the same error as reading a competence score off an unmet minimum
#: attempt count.
#:
#: One good structured source is enough to OBSERVE a concept: a provisional node
#: with real provenance beats no node. Consequential use -- cross-domain
#: mapping, knowledge transfer -- is what requires corroboration.
WELL_SUPPORTED_MIN_ROOTS = 2


class InvalidProvenance(ValueError):
    """A lineage chain could not be resolved to an origin.

    Cyclic, dangling, self-referential or unbounded lineage. Raised rather than
    resolved to something plausible: an arbitrary root silently inflates
    corroboration, which is the failure the root walk exists to prevent.
    """


class IngestionRefused(ValueError):
    """An envelope was malformed. Refused loudly rather than skipped.

    A silently dropped envelope is indistinguishable from one that produced no
    concepts, and only one of those is a defect.
    """


@dataclass(frozen=True)
class EvidenceEnvelope:
    """A canonical observation with provenance. Makes no claim about truth.

    Distinct from unified.evidence, which is hypothesis-scoped
    (`supports_hypothesis BOOLEAN NOT NULL`) -- that is evidence bearing on a
    claim, this is an observation that occurred.
    """
    evidence_id: str
    source_type: EvidenceSourceType
    source_id: str
    content: str
    producer: str
    structured_data: Dict[str, Any] = field(default_factory=dict)
    observed_at: Optional[datetime] = None
    #: Evidence ids this was derived from. REQUIRED for derivative sources.
    derived_from: Tuple[str, ...] = ()

    def __post_init__(self):
        if not self.evidence_id:
            raise IngestionRefused("evidence_id is required")
        if not str(self.content).strip():
            raise IngestionRefused(f"{self.evidence_id}: content is empty")
        if not self.producer:
            raise IngestionRefused(f"{self.evidence_id}: producer is required")
        if self.source_type not in _ROOT_SOURCES and not self.derived_from:
            raise IngestionRefused(
                f"{self.evidence_id}: source_type={self.source_type.value} is "
                f"derivative and must declare derived_from. Ingesting it as a "
                f"root would let a restatement of earlier evidence count as new "
                f"support for the same concept."
            )


@dataclass(frozen=True)
class ConceptCandidate:
    """A PROPOSAL. Carries no identity and is never persisted as-is."""
    label: str
    concept_kind: ConceptType
    domain_candidates: Tuple[str, ...]
    evidence_ids: Tuple[str, ...]
    extraction_confidence: float
    extractor: str
    description: str = ""
    attributes: Dict[str, Any] = field(default_factory=dict)
    #: (relation, target_surface) or (relation, target_surface, polarity).
    #: Polarity defaults to "positive"; "negative" records a DENIAL, which is a
    #: claim in its own right and used to be unrepresentable -- a negated
    #: reading had nowhere to go but an episode.
    relationships: Tuple[Tuple[str, ...], ...] = ()


@dataclass(frozen=True)
class ConceptIdentity:
    """The canonical identity the resolver assigned to a candidate."""
    concept_id: str
    name: str
    domain: str
    concept_kind: ConceptType


@dataclass
class IngestionResult:
    """What an ingestion actually did. Every field is an observed count."""
    evidence_id: str
    candidates: int = 0
    created: List[str] = field(default_factory=list)
    reinforced: List[str] = field(default_factory=list)
    promoted: List[Tuple[str, str]] = field(default_factory=list)
    rejected: List[Tuple[str, str]] = field(default_factory=list)
    #: Extractors that could not read the evidence at all, as (name, reason).
    #: WITHOUT this, candidates=0 means both "read it, found no concepts" and
    #: "could not read it" -- the same silent-negative this service exists to
    #: prevent elsewhere. A caller must be able to tell an empty observation
    #: from a broken extractor.
    extraction_failures: List[Tuple[str, str]] = field(default_factory=list)

    @property
    def accepted(self) -> int:
        return len(self.created) + len(self.reinforced)

    @property
    def read_successfully(self) -> bool:
        """True only if every registered extractor actually read the evidence."""
        return not self.extraction_failures


# ==========================================================================
# Extraction
# ==========================================================================

class ConceptExtractor:
    """Derives concepts from structure. Model-free by construction.

    THIS WAS A PASS-THROUGH, NOT AN EXTRACTOR. It required a producer to hand
    over a finished `concepts` list, so it could only relay semantic work
    something else had already done. No producer in the codebase supplied that
    key. The deterministic path therefore never fired, and every one of the 90
    concepts and 195 relations in the live store carries
    `provenance.extractor = 'llm_structured'` -- concept ingestion was
    model-dependent in practice while being model-free by construction.

    Structure the substrate produces is ALREADY semantic. An induced operator
    states which relations it requires, which it adds and which it retracts;
    that is a concept graph written in logic. Reading it through a prompt would
    make Torin's knowledge of its own rules contingent on a model's paraphrase
    of them, and would put a sampling step between an induced rule and the
    graph the analogy matcher searches.

    ONE READER PER STRUCTURAL FORM, dispatched on the key that carries it.
    There is no generic reader: a generic reader over unrecognised structure is
    inference, which is the thing this extractor exists to not do. An
    unrecognised envelope is NAMED as unread rather than returning [], because
    an unreadable envelope and one that genuinely holds no concepts are
    different facts and only one of them is a defect.
    """

    name = "structured"

    #: Structural forms, each with a `_read_<form>` reader. Order is the order
    #: readers run; a producer may carry more than one form.
    FORMS = ("concepts", "operator", "observation", "statements", "capability")

    #: Kept as the name of the first form for callers that referenced it.
    STRUCTURED_KEY = "concepts"

    #: Edge labels an operator induces. DOMAIN-NEUTRAL by design: `requires`,
    #: `adds` and `removes` are what a structure learned in one domain and a
    #: situation observed in another can be compared on. `PATH` and `LINK`
    #: cannot be, so the predicate names go in the ENDPOINTS and the roles go
    #: on the edges.
    OPERATOR_ROLES = ("requires", "adds", "removes")

    #: Set when the evidence could not be read at all. Reset every call.
    last_failure: Optional[str] = None

    def extract(self, envelope: EvidenceEnvelope) -> List[ConceptCandidate]:
        self.last_failure = None
        data = envelope.structured_data or {}
        present = [f for f in self.FORMS if data.get(f)]

        if not present:
            self.last_failure = (
                f"no structural form present (looked for {', '.join(self.FORMS)}); "
                f"nothing here can be read without inference"
            )
            return []

        out: List[ConceptCandidate] = []
        for form in present:
            out.extend(getattr(self, f"_read_{form}")(data[form], envelope))
        return out

    # ---- form: concepts -------------------------------------------------

    def _read_concepts(self, raw, envelope: EvidenceEnvelope) -> List[ConceptCandidate]:
        """A producer that already holds concept structure declares it directly."""
        out: List[ConceptCandidate] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            label = str(item.get("label") or item.get("name") or "").strip()
            if not label:
                continue
            kind_raw = str(item.get("kind") or item.get("concept_kind") or "entity")
            try:
                kind = ConceptType(kind_raw.lower())
            except ValueError:
                # An unrecognised kind is a producer defect. Named, not coerced
                # to ENTITY, which would silently mistype the concept forever.
                logger.warning(
                    "%s proposed concept %r with unknown kind %r; skipping",
                    envelope.producer, label, kind_raw,
                )
                continue
            domains = item.get("domains") or item.get("domain") or []
            if isinstance(domains, str):
                domains = [domains]
            rels = tuple(
                (str(r[0]), str(r[1])) if len(r) < 3 else (str(r[0]), str(r[1]), str(r[2]))
                for r in (item.get("relationships") or [])
                if isinstance(r, (list, tuple)) and len(r) >= 2
            )
            out.append(ConceptCandidate(
                label=label,
                concept_kind=kind,
                domain_candidates=tuple(str(d).strip().lower() for d in domains if str(d).strip()),
                evidence_ids=(envelope.evidence_id,),
                extraction_confidence=float(item.get("confidence", 1.0)),
                extractor=self.name,
                description=str(item.get("description") or ""),
                attributes=dict(item.get("attributes") or {}),
                relationships=rels,
            ))
        return out

    # ---- form: observation ----------------------------------------------

    def _read_observation(self, form, envelope: EvidenceEnvelope) -> List[ConceptCandidate]:
        """One demonstrated state transition: what held, what was done, what changed.

        Only the OBSERVED DELTA becomes an edge. The state that happened to hold
        is recorded as concepts and nothing more, because which of those facts
        the action needed is exactly what induction determines -- an observation
        that emitted `requires` would answer the learner's question for it, and
        the rule induced from it would then be corroborated by its own premise.
        """
        if not isinstance(form, dict):
            self.last_failure = f"observation form is {type(form).__name__}, not an object"
            return []

        domain = str(form.get("domain") or "").strip()
        if not domain:
            self.last_failure = "observation form carries no domain"
            return []

        atoms: Dict[str, int] = {}
        for atom in form.get("atoms") or []:
            if not isinstance(atom, dict) or not str(atom.get("predicate") or "").strip():
                self.last_failure = "observation form has an atom with no predicate"
                return []
            atoms.setdefault(str(atom["predicate"]).strip(), int(atom.get("arity") or 0))

        out: List[ConceptCandidate] = []
        action = form.get("action")
        if isinstance(action, dict) and str(action.get("predicate") or "").strip():
            predicate = str(action["predicate"]).strip()
            edges: List[Tuple[str, str]] = []
            for role in ("adds", "removes"):
                for atom in form.get(role) or []:
                    if isinstance(atom, dict) and str(atom.get("predicate") or "").strip():
                        edges.append((role, str(atom["predicate"]).strip()))
            atoms.pop(predicate, None)
            out.append(ConceptCandidate(
                label=predicate,
                concept_kind=ConceptType.PROCESS,
                domain_candidates=(domain,),
                evidence_ids=(envelope.evidence_id,),
                extraction_confidence=1.0,
                extractor=self.name,
                description=f"{predicate}/{int(action.get('arity') or 0)} operator",
                attributes={"arity": int(action.get("arity") or 0)},
                relationships=tuple(edges),
            ))

        for predicate, arity in sorted(atoms.items()):
            out.append(ConceptCandidate(
                label=predicate,
                concept_kind=self._atom_kind(arity),
                domain_candidates=(domain,),
                evidence_ids=(envelope.evidence_id,),
                extraction_confidence=1.0,
                extractor=self.name,
                description=f"{predicate}/{arity} atom",
                attributes={"arity": arity},
            ))

        if not out:
            self.last_failure = "observation form named neither an action nor any atom"
        return out

    # ---- form: statements -----------------------------------------------

    #: Sentence shapes the substrate can read WITHOUT a model. Delegated to
    #: DeterministicExtractor, which is the existing owner of "what does this
    #: English sentence assert" -- it already shares core.semantics with concept
    #: identity, so `men` and `man` cannot mean one thing to the logic and
    #: another to the concept store. A second parser here would be a second
    #: answer to the same question.
    _STATEMENT_RELATIONS = {(False, "is_a"), (True, "is_not_a")}

    def _read_statements(self, raw, envelope: EvidenceEnvelope) -> List[ConceptCandidate]:
        """Assertions in prose, parsed deterministically or DECLINED.

        Prose is where a model is usually reached for, and where reaching for
        one puts generation underneath knowledge. The bounded slice below needs
        no model, and anything outside it is declined and counted rather than
        guessed at -- a wrong guess writes a false premise into the store, and
        nothing downstream can detect it.

        This is the same bargain the formalizer chain makes: cover what can be
        covered deterministically, name the remainder, and let the covered share
        grow by adding patterns rather than by adding inference.
        """
        from core.reasoning.neural_bridge import DeterministicExtractor

        domain = str((envelope.structured_data or {}).get("domain") or "").strip()
        if not domain:
            self.last_failure = "statements form carries no domain"
            return []

        parser = DeterministicExtractor()
        proposals: Dict[str, ConceptType] = {}
        edges: Dict[str, List[Tuple[str, str]]] = {}
        declined = 0

        def note(label: str, kind: ConceptType) -> Optional[str]:
            label = str(label or "").strip()
            if not label:
                return None
            proposals.setdefault(label, kind)
            return label

        for sentence in raw:
            parsed = parser._parse_statement(str(sentence))
            if not parsed:
                declined += 1
                continue

            if parsed["kind"] == "fact":
                subject = note(parsed["subject"], ConceptType.ENTITY)
                prop = note(parsed["prop"], ConceptType.PROPERTY)
                relation = "is_not_a" if parsed["negated"] else "is_a"
            elif parsed["kind"] == "universal":
                subject = note(parsed["p"], ConceptType.ENTITY)
                prop = note(parsed["q"], ConceptType.PROPERTY)
                relation = "is_not_a" if parsed["negated"] else "is_a"
            elif parsed["kind"] == "conditional":
                # The IMPLICATION is between the properties, not the subject:
                # "if x is p then x is q" says p entails q for anything, which
                # is the part that transfers.
                subject = note(parsed["antecedent"]["prop"], ConceptType.PROPERTY)
                prop = note(parsed["consequent"]["prop"], ConceptType.PROPERTY)
                relation = "implies"
            else:
                declined += 1
                continue

            if subject and prop:
                edges.setdefault(subject, []).append((relation, prop))

        if not proposals:
            self.last_failure = (
                f"none of {declined} statement(s) matched a shape the substrate "
                f"can read without a model")
            return []
        if declined:
            logger.info(
                "%s: %d statement(s) read, %d declined as outside the "
                "deterministic slice", envelope.evidence_id,
                len(raw) - declined, declined)

        return [ConceptCandidate(
            label=label,
            concept_kind=kind,
            domain_candidates=(domain,),
            evidence_ids=(envelope.evidence_id,),
            extraction_confidence=1.0,
            extractor=self.name,
            description="",
            relationships=tuple(edges.get(label, ())),
        ) for label, kind in sorted(proposals.items())]

    # ---- form: capability -----------------------------------------------

    def _read_capability(self, form, envelope: EvidenceEnvelope) -> List[ConceptCandidate]:
        """A DECLARED operator: a tool, what it needs, and what it provides.

        Every tool is an operator the substrate can invoke, and its parameter
        list is a precondition list written in a different notation. Projecting
        the registry makes tools searchable by CrossDomainGrounder the same way
        a learned rule is -- an unfamiliar situation shaped like "needs two
        locations, moves something between them" can then ground onto a tool
        rather than only onto a rule.

        Declared, not observed: this says what the tool claims about itself.
        What invoking it establishes is a TOOL_OBSERVATION and arrives
        separately, so a tool that is declared and never used stays
        distinguishable from one that has actually done work.
        """
        if not isinstance(form, dict):
            self.last_failure = f"capability form is {type(form).__name__}, not an object"
            return []

        tool = str(form.get("tool") or "").strip()
        domain = str(form.get("domain") or "").strip()
        if not tool:
            self.last_failure = "capability form names no tool"
            return []
        if not domain:
            self.last_failure = f"capability {tool!r} carries no domain"
            return []

        edges: List[Tuple[str, str]] = []
        targets: Dict[str, ConceptType] = {}
        for role, key, kind in (("requires", "required", ConceptType.PROPERTY),
                                ("accepts", "optional", ConceptType.PROPERTY),
                                ("provides", "provides", ConceptType.METHOD)):
            for item in form.get(key) or []:
                label = str(item or "").strip()
                if not label:
                    continue
                edges.append((role, label))
                targets.setdefault(label, kind)

        if not edges:
            self.last_failure = (
                f"tool {tool!r} declares neither parameters nor capabilities; "
                f"an operator with no structure cannot support a correspondence")
            return []

        out = [ConceptCandidate(
            label=tool,
            concept_kind=ConceptType.METHOD,
            domain_candidates=(domain,),
            evidence_ids=(envelope.evidence_id,),
            extraction_confidence=1.0,
            extractor=self.name,
            description=str(form.get("description") or "")[:400],
            attributes={"required": len(form.get("required") or []),
                        "optional": len(form.get("optional") or []),
                        "provides": len(form.get("provides") or []),
                        "safety": str(form.get("safety") or "undeclared")},
            relationships=tuple(edges),
        )]
        out.extend(ConceptCandidate(
            label=label, concept_kind=kind, domain_candidates=(domain,),
            evidence_ids=(envelope.evidence_id,), extraction_confidence=1.0,
            extractor=self.name,
        ) for label, kind in sorted(targets.items()))
        return out

    # ---- form: operator -------------------------------------------------

    @staticmethod
    def _atom_kind(arity: int) -> ConceptType:
        """Read off the logic, not guessed.

        An atom over two or more terms asserts something BETWEEN things; an
        atom over one term asserts something ABOUT a thing.
        """
        return ConceptType.RELATION if arity >= 2 else ConceptType.STATE

    def _read_operator(self, form, envelope: EvidenceEnvelope) -> List[ConceptCandidate]:
        """An action predicate, its preconditions and its effects, as a subgraph.

        The PREDICATE is the endpoint, never the ground atom. `AT(?X0, ?X2)`
        names one instantiation and carries variable names that mean nothing
        outside the rule that bound them; `at` is the relation itself, and is
        the only part of the atom another domain can correspond to.

        The action becomes the hub and every precondition and effect becomes an
        outgoing edge, because that is the shape CrossDomainGrounder searches:
        a concept together with its resolved outgoing edges.
        """
        if not isinstance(form, dict):
            self.last_failure = f"operator form is {type(form).__name__}, not an object"
            return []

        action = str(form.get("action") or "").strip()
        domain = str(form.get("domain") or "").strip()
        if not action:
            self.last_failure = "operator form carries no action predicate"
            return []
        if not domain:
            self.last_failure = f"operator {action!r} carries no domain"
            return []

        edges: List[Tuple[str, str]] = []
        arities: Dict[str, int] = {}
        counts: Dict[str, int] = {}

        for role in self.OPERATOR_ROLES:
            atoms = form.get(role) or []
            counts[role] = len(atoms)
            for atom in atoms:
                if not isinstance(atom, dict):
                    self.last_failure = (
                        f"operator {action!r}: {role} atom is "
                        f"{type(atom).__name__}, not an object")
                    return []
                predicate = str(atom.get("predicate") or "").strip()
                if not predicate:
                    self.last_failure = f"operator {action!r}: a {role} atom has no predicate"
                    return []
                arity = int(atom.get("arity") or 0)
                edges.append((role, predicate))
                # First arity seen wins; a predicate used at two arities is one
                # relation observed in two forms, not two concepts.
                arities.setdefault(predicate, arity)

        if not edges:
            self.last_failure = (
                f"operator {action!r} has no preconditions or effects; an "
                f"operator with no structure cannot support a correspondence")
            return []

        action_arity = int(form.get("arity") or 0)
        out = [ConceptCandidate(
            label=action,
            concept_kind=ConceptType.PROCESS,
            domain_candidates=(domain,),
            evidence_ids=(envelope.evidence_id,),
            extraction_confidence=1.0,
            extractor=self.name,
            description=f"{action}/{action_arity} operator",
            # Read by AnalogyDiscovery._structural_similarity, which scores on
            # attributes and edges. An operator with a label alone is
            # identifiable and structurally empty, so every pair scores 0.0.
            attributes={"arity": action_arity, **counts},
            relationships=tuple(edges),
        )]

        for predicate, arity in sorted(arities.items()):
            out.append(ConceptCandidate(
                label=predicate,
                concept_kind=self._atom_kind(arity),
                domain_candidates=(domain,),
                evidence_ids=(envelope.evidence_id,),
                extraction_confidence=1.0,
                extractor=self.name,
                description=f"{predicate}/{arity} atom",
                attributes={"arity": arity},
            ))
        return out



# ==========================================================================
# Resolution
# ==========================================================================

_NORMALISE_STRIP = re.compile(r"[^a-z0-9 _-]+")
_WS = re.compile(r"\s+")


class ConceptResolver:
    """Normalisation, identity and domain attachment. Owned by the substrate."""

    #: Labels that are artefacts of how a task was worded rather than things.
    #: Rejected explicitly so the reason appears in the result.
    _NON_CONCEPTS = frozenset({
        "thing", "things", "it", "this", "that", "data", "result", "results",
        "output", "value", "item", "items", "object", "objects", "test",
        "example", "sample", "todo", "unknown", "none", "null",
    })

    MIN_LABEL_LEN = 2
    MAX_LABEL_LEN = 64

    #: Words a document uses about itself. `introduction_of_lifepo4` is document
    #: structure, not a thing that exists independently of the document.
    _STRUCTURAL_PREFIXES = ("introduction_of_", "overview_of_", "review_of_",
                            "summary_of_", "conclusion_of_", "study_of_",
                            "the_", "a_", "an_")

    #: Generic tails an extractor appends that name a CATEGORY of the concept
    #: rather than a different concept: lithium_iron_phosphate_batteries is the
    #: same substance as lithium_iron_phosphate.
    #: SINGULAR forms only. Plurals are collapsed before this list is applied,
    #: so listing both spellings would strip `safety_characteristics` down to
    #: `safety` while leaving `safety_characteristic` intact -- splitting the
    #: pair this is meant to merge.
    _QUALIFIER_TAILS = ("_battery", "_material", "_system", "_device",
                        "_technology")

    #: Fields of study ending in -ics. These are MASS NOUNS, not plurals, so the
    #: general -s rule destroys them: `physics` became `physic`, and physics
    #: concepts attached to a domain that does not exist.
    #:
    #: An explicit set rather than a blanket `-ics` rule, because the rule
    #: cannot tell a field from a plural: `characteristics` IS the plural of
    #: `characteristic` and must still reduce.
    _ICS_MASS_NOUNS = frozenset({
        "physics", "mathematics", "economics", "statistics", "mechanics",
        "electronics", "optics", "dynamics", "thermodynamics", "linguistics",
        "informatics", "robotics", "genetics", "ethics", "politics",
        "logistics", "acoustics", "aerodynamics", "ceramics", "graphics",
        "analytics", "semantics", "kinetics", "photonics", "cybernetics",
    })

    #: Morphology tables live in core.semantics.lexical_normalization, which is
    #: the single owner. Kept as aliases so existing readers of these names on
    #: the class continue to see the same data rather than a stale copy.
    _PLURAL_EXCEPTIONS = _lexical.PLURAL_EXCEPTIONS
    _IRREGULAR_SINGULARS = _lexical.IRREGULAR_SINGULARS

    def normalise(self, label: str) -> str:
        return _lexical.normalise(label)

    def _singularise(self, word: str) -> str:
        return _lexical.singularise(word)

    def canonical_label(self, label: str) -> str:
        """The identity-bearing form of a label.

        Delegates to core.semantics.lexical_normalization so concept identity
        and the prose-to-logic formalizer cannot disagree about whether `men`
        and `man` are the same word.
        """
        return _lexical.canonical_label(label)

    def reject_reason(self, candidate: ConceptCandidate) -> Optional[str]:
        norm = self.canonical_label(candidate.label)
        if len(norm) < self.MIN_LABEL_LEN:
            return f"label {candidate.label!r} too short after normalisation"
        if len(norm) > self.MAX_LABEL_LEN:
            return f"label {candidate.label!r} exceeds {self.MAX_LABEL_LEN} chars"
        if norm in self._NON_CONCEPTS or self._singularise(norm) in self._NON_CONCEPTS:
            return f"{norm!r} is a placeholder word, not a concept"
        if norm.isdigit():
            return f"{norm!r} is a bare number"
        if not candidate.domain_candidates:
            return f"{norm!r} has no domain; a concept must belong somewhere"
        return None

    def resolve(self, candidate: ConceptCandidate) -> ConceptIdentity:
        """Structural identity only — no store lookup. See resolve_identity."""
        name = self.canonical_label(candidate.label)
        domain = self.canonical_label(candidate.domain_candidates[0])
        return ConceptIdentity(
            concept_id=f"{domain}:{name}",
            name=name,
            domain=domain,
            concept_kind=candidate.concept_kind,
        )


# ==========================================================================
# Service
# ==========================================================================

class ConceptIngestionService:
    """The only writer of unified.concepts."""

    #: Lineage longer than this is refused rather than walked. Real chains are
    #: source -> finding -> summary -> memory -> extraction; anything deeper is
    #: a malformed graph.
    MAX_LINEAGE_DEPTH = 32

    def __init__(self, db_manager=None):
        self._db = db_manager
        self.resolver = ConceptResolver()
        self.extractors: List[ConceptExtractor] = [ConceptExtractor()]

    def register_extractor(self, extractor) -> bool:
        """Register an extractor. The ownership path production uses.

        Idempotent by extractor name, so a service that is a singleton cannot
        accumulate duplicate extractors across callers -- which would run the
        same interpretation twice and record it under one name.

        Callers must go through this rather than appending to `.extractors`, so
        a test exercises the same path production does.
        """
        name = getattr(extractor, "name", None) or getattr(extractor, "extractor_id", None)
        if not name:
            raise ValueError(f"{type(extractor).__name__} has no .name; "
                             f"extractor attribution requires one")
        if any((getattr(e, "name", None) or getattr(e, "extractor_id", None)) == name
               for e in self.extractors):
            logger.debug("Extractor %r already registered", name)
            return False
        self.extractors.append(extractor)
        logger.info("Registered concept extractor %r", name)
        return True

    def db(self):
        if self._db is None:
            from core.database import get_database_manager
            self._db = get_database_manager()
        return self._db

    async def _ready(self):
        """Ensure the store is reachable before the first write.

        execute_query raises rather than no-opping when the manager has not been
        initialized, so an uninitialized service would fail at its first write
        with a message about the database rather than about ingestion.
        """
        db = self.db()
        if not getattr(db, "initialized", False):
            await db.initialize()

    # ---- identity -------------------------------------------------------

    async def resolve_identity(self, candidate: ConceptCandidate) -> ConceptIdentity:
        """Resolve a candidate to a canonical identity, consulting the store.

        Structural normalisation alone cannot stop identity drift, because the
        extractor also invents the DOMAIN. One live run produced 21 domains for
        a single topic area -- energy, energy_conversion, energy_engineering,
        energy_storage, battery_technology -- so the same substance landed under
        several of them and each copy held a fraction of the evidence.

        Resolution order, first match wins:

          1. a recorded alias                 -> that concept
          2. the same canonical label already
             registered in ANY domain         -> that concept, domain kept
          3. otherwise mint, preferring a
             domain the registry already knows

        Rule 2 treats the label as the identity and the domain as an attribute
        of it. `chemistry:electrolyte` and `electrochemistry:electrolyte` are one
        electrolyte observed by two extractions, and merging them is what lets
        evidence accumulate on a single node instead of splitting.
        """
        name = self.resolver.canonical_label(candidate.label)

        rows = await self.db().execute_query(
            "SELECT concept_id FROM unified.concept_aliases WHERE alias = $1",
            (name,), fetch_all=True,
        )
        if rows:
            cid = rows[0]["concept_id"]
            return ConceptIdentity(
                concept_id=cid, name=name,
                domain=cid.split(":", 1)[0], concept_kind=candidate.concept_kind,
            )

        rows = await self.db().execute_query(
            "SELECT concept_id, domain FROM unified.concepts WHERE name = $1 "
            "ORDER BY root_evidence_count DESC, created_at ASC LIMIT 1",
            (name,), fetch_all=True,
        )
        if rows:
            cid, dom = rows[0]["concept_id"], rows[0]["domain"]
            await self._record_alias(name, cid, "label")
            return ConceptIdentity(
                concept_id=cid, name=name, domain=dom,
                concept_kind=candidate.concept_kind,
            )

        # 3. Acronym identity: ysz <-> yttria_stabilized_zirconia. Deterministic,
        #    so it merges without guessing. Formula-vs-name (lifepo4 vs
        #    lithium_iron_phosphate) is NOT resolvable this way and is left
        #    split until an explicit alias source supplies it — an unmerged
        #    pair is recoverable, a wrongly merged one is not.
        proposed = self.resolver.canonical_label(candidate.domain_candidates[0]) \
            if candidate.domain_candidates else None
        acronym = await self._acronym_match(name, candidate.concept_kind, proposed)
        if acronym:
            await self._record_alias(name, acronym, "acronym")
            return ConceptIdentity(
                concept_id=acronym, name=acronym.split(":", 1)[1],
                domain=acronym.split(":", 1)[0], concept_kind=candidate.concept_kind,
            )

        domain = await self._resolve_domain(candidate)
        identity = ConceptIdentity(
            concept_id=f"{domain}:{name}", name=name, domain=domain,
            concept_kind=candidate.concept_kind,
        )
        await self._record_alias(name, identity.concept_id, "canonical")
        # The raw label maps to the same node, so the next extraction that
        # spells it differently resolves here rather than minting a twin.
        raw = self.resolver.normalise(candidate.label)
        if raw != name:
            await self._record_alias(raw, identity.concept_id, "surface_form")
        return identity

    #: Acronym identity is LEXICAL and deterministic, so it is resolved here
    #: rather than inferred.
    #:
    #: Embedding similarity was tried for this and is actively wrong on short
    #: labels — measured on the real encoder:
    #:
    #:     ysz ~ yttria stabilized zirconia            0.33   SAME referent
    #:     sofc ~ solid oxide fuel cell                0.28   SAME referent
    #:     oxygen vacancy ~ oxygen vacancy formation   0.94   DIFFERENT referents
    #:     lithium iron phosphate ~ lithium cobalt oxide 0.71 DIFFERENT referents
    #:
    #: A substring sits near its superset and an acronym sits nowhere near its
    #: expansion, so at every threshold the false merges arrive before the true
    #: ones. A false merge is unrecoverable — two referents fuse into one node
    #: whose evidence no longer means anything — so no threshold was chosen.
    #: THREE, not two. A two-letter acronym carries almost no information:
    #: there are 676 possible pairs against thousands of concepts, so
    #: collisions are expected rather than exceptional. Observed at 2: the
    #: learned predicate `IN` (spatial containment, archive domain) was fused
    #: with `include_number`, a password-policy parameter, because its initials
    #: are i-n. The two referents became one node and its evidence stopped
    #: meaning anything -- the unrecoverable failure this matcher's own
    #: docstring warns about.
    #:
    #: The acronyms worth merging are longer and genuinely distinctive: ysz,
    #: sofc, pcfc. Nothing of value is lost at 3.
    MIN_ACRONYM_LEN = 3
    MAX_ACRONYM_LEN = 8

    def _acronym_of(self, name: str) -> Optional[str]:
        parts = [p for p in name.split("_") if p]
        if len(parts) < 2:
            return None
        letters = "".join(p[0] for p in parts)
        if self.MIN_ACRONYM_LEN <= len(letters) <= self.MAX_ACRONYM_LEN:
            return letters
        return None

    #: An acronym PROPOSES identity; it must not establish it alone.
    #:
    #: Raising MIN_ACRONYM_LEN from 2 to 3 removed the `in` / `include_number`
    #: fusion but does not solve this: three-character collisions are
    #: inevitable as the store grows from hundreds of concepts to tens of
    #: thousands, and the failure is asymmetric. A MISSED match yields UNKNOWN,
    #: which is recoverable. A FALSE merge fuses two referents into one node
    #: whose evidence no longer means anything, and nothing downstream can
    #: detect it.
    #:
    #: So identity fails toward AMBIGUITY, not toward false equivalence: an
    #: acronym is accepted only with corroboration from something other than
    #: its initials.
    _CORROBORATION_REQUIRED = True

    async def _corroborates(self, name: str, candidate_id: str,
                            kind: Optional[ConceptType] = None,
                            proposed_domain: Optional[str] = None) -> Optional[str]:
        """A reason to believe the acronym and its expansion are one thing.

        Returns the corroborating signal, or None. Deliberately conservative:
        initials plus nothing else is not evidence of sameness.
        """
        rows = await self.db().execute_query(
            "SELECT domain, concept_kind FROM unified.concepts WHERE concept_id = $1",
            (candidate_id,), fetch_all=True)
        if not rows:
            return None
        candidate_domain, candidate_kind = rows[0]["domain"], rows[0]["concept_kind"]

        # 1. Same domain: two names for one thing in one field is the ordinary
        #    case an acronym exists to serve.
        #
        #    The domain comes from the CANDIDATE BEING RESOLVED, not from a
        #    lookup: an acronym is usually resolved before any concept bearing
        #    that spelling exists, so asking the store for its domain returns
        #    nothing and corroboration could never succeed in the direction it
        #    matters most.
        domain = proposed_domain
        if domain is None:
            own = await self.db().execute_query(
                "SELECT domain FROM unified.concepts WHERE name = $1 LIMIT 1",
                (name,), fetch_all=True)
            domain = own[0]["domain"] if own else None

        if domain and domain == candidate_domain:
            # UNIQUE within that domain, or it is ambiguous rather than
            # corroborated. Three-character collisions happen inside one domain
            # too, and "whichever row sorted first" is not evidence -- it is a
            # coin toss recorded as identity.
            rivals = await self.db().execute_query(
                """SELECT count(*) n FROM unified.concepts
                   WHERE domain = $1
                     AND array_length(string_to_array(name, '_'), 1) >= 2
                     AND (SELECT string_agg(left(part, 1), '' ORDER BY ord)
                          FROM unnest(string_to_array(name, '_'))
                               WITH ORDINALITY AS t(part, ord)) = $2""",
                (candidate_domain, self._acronym_of(name) or name), fetch_all=True)
            if rivals and int(rivals[0]["n"]) > 1:
                logger.info(
                    "acronym %r has %d expansions in domain %s; AMBIGUOUS, "
                    "refusing rather than taking the first",
                    name, int(rivals[0]["n"]), candidate_domain)
                return None
            return "same_domain_unique"

        # 2. Same kind AND a shared relation neighbour: they behave alike and
        #    are connected to at least one identical thing.
        # kind is optional: a caller that does not know the concept kind
        # cannot corroborate on it, and must not crash trying.
        if kind is not None and candidate_kind == kind.value:
            shared = await self.db().execute_query(
                """SELECT 1 FROM unified.concept_relations a
                   JOIN unified.concept_relations b
                     ON a.relation = b.relation
                    AND a.target_concept_id = b.target_concept_id
                    AND a.polarity = b.polarity
                   WHERE a.source_concept_id = $1 AND b.source_concept_id = $2
                   LIMIT 1""",
                (candidate_id, f"{domain or candidate_domain}:{name}"), fetch_all=True)
            if shared:
                return "same_kind_shared_neighbour"

        return None

    async def _acronym_match(self, name: str,
                             kind: Optional[ConceptType] = None,
                             proposed_domain: Optional[str] = None) -> Optional[str]:
        """Existing concept this name is the acronym of, or vice versa.

        Exact initials only. `pcfc` does not resolve to
        `proton_conducting_ceramic_fuel_cell` (initials `pccfc`), and it should
        not: guessing at near-misses is how `cathode` becomes `anode`.
        """
        # EXACT, AND OVER THE WHOLE STORE. This used to pull the 500
        # best-supported concepts and scan them in Python, so acronym identity
        # quietly stopped working for anything outside that window -- and the
        # window is a function of how big the store happens to be. Projecting
        # the tool registry took it past 1000 concepts and a freshly learned
        # expansion (root_evidence_count = 1) fell off the end, so `ysz` no
        # longer resolved to `yttria_stabilized_zirconia`. Identity must not
        # depend on how much else has been learned.
        acr = self._acronym_of(name)
        if acr:
            # `name` is the expansion: is its acronym a concept?
            rows = await self.db().execute_query(
                "SELECT concept_id FROM unified.concepts WHERE name = $1 "
                "ORDER BY root_evidence_count DESC, created_at ASC LIMIT 1",
                (acr,), fetch_all=True)
            if rows:
                hit = rows[0]["concept_id"]
                reason = await self._corroborates(name, hit, kind, proposed_domain)
                if reason:
                    logger.info("acronym identity %r -> %s (%s)", name, hit, reason)
                    return hit
                logger.info(
                    "acronym %r matches %s on initials alone; REFUSED -- "
                    "initials are a proposal, not evidence of sameness",
                    name, hit)

        # `name` is the acronym: is there a concept whose initials spell it?
        # Computed in SQL so every row participates, not just the top slice.
        if self.MIN_ACRONYM_LEN <= len(name) <= self.MAX_ACRONYM_LEN:
            rows = await self.db().execute_query(
                """SELECT concept_id FROM unified.concepts
                   WHERE array_length(string_to_array(name, '_'), 1) >= 2
                     AND (SELECT string_agg(left(part, 1), '' ORDER BY ord)
                          FROM unnest(string_to_array(name, '_'))
                               WITH ORDINALITY AS t(part, ord)) = $1
                   ORDER BY root_evidence_count DESC, created_at ASC LIMIT 1""",
                (name,), fetch_all=True)
            if rows:
                hit = rows[0]["concept_id"]
                reason = await self._corroborates(name, hit, kind, proposed_domain)
                if reason:
                    logger.info("acronym identity %r -> %s (%s)", name, hit, reason)
                    return hit
                logger.info(
                    "acronym %r matches %s on initials alone; REFUSED -- a "
                    "missed match is UNKNOWN and recoverable, a false merge "
                    "fuses two referents forever", name, hit)

        return None

    async def _resolve_domain(self, candidate: ConceptCandidate) -> str:
        """Prefer a domain the registry already knows over an invented one."""
        proposals = [self.resolver.canonical_label(d) for d in candidate.domain_candidates]
        proposals = [d for d in proposals if d]
        if not proposals:
            return "general"

        try:
            from .domain_registry import get_domain_registry
            registry = get_domain_registry()
            if not registry.initialized:
                await registry.initialize()
            known = {registry._domain_key(d) for d in registry.domains}
        except Exception as e:
            logger.warning("Domain registry unavailable during resolution: %s", e)
            return proposals[0]

        for d in proposals:
            if d in known:
                return d
        # None known: take the extractor's first proposal, but say so, because a
        # new domain per extraction is how 21 domains appeared for one topic.
        logger.info(
            "New domain %r for concept %r (proposals %s were unknown to the registry)",
            proposals[0], candidate.label, proposals,
        )
        return proposals[0]

    async def _resolve_target(self, surface: str) -> Optional[str]:
        """Resolve a relation target to a canonical concept_id, or None.

        Relation targets went into `unified.concepts.relationships` as raw prose
        — `[["part_of", "solid oxide fuel cell"]]` — so identity resolution
        stopped at concept labels and never reached the graph. Measured on the
        live store: 0 of 18 edges carried a concept_id, and 5 resolved to
        nothing because the target was written in a form the resolver would have
        merged (`oxygen ions` vs the canonical `oxygen_ion`).

        Two independently extracted aliases therefore produced different graph
        topology even after their concepts had been unified, which is fatal for
        structural comparison: the analogy engine compares edges, and edges that
        do not share endpoints cannot correspond.

        None is a real answer — the target names something not yet learned.
        """
        name = self.resolver.canonical_label(surface)
        if not name:
            return None

        rows = await self.db().execute_query(
            "SELECT concept_id FROM unified.concept_aliases WHERE alias = $1",
            (name,), fetch_all=True)
        if rows:
            return rows[0]["concept_id"]

        rows = await self.db().execute_query(
            "SELECT concept_id FROM unified.concepts WHERE name = $1 "
            "ORDER BY root_evidence_count DESC LIMIT 1", (name,), fetch_all=True)
        if rows:
            return rows[0]["concept_id"]

        return await self._acronym_match(name)

    async def _record_relations(
        self,
        identity: ConceptIdentity,
        candidate: ConceptCandidate,
        envelope: EvidenceEnvelope,
    ) -> None:
        """Persist edges with canonical endpoints where they resolve."""
        for edge in candidate.relationships:
            relation, surface = edge[0], edge[1]
            # An extractor that knows nothing of polarity emits a 2-tuple, and
            # what it saw was an assertion. Absence of a denial is not a denial.
            polarity = str(edge[2]) if len(edge) > 2 else "positive"
            if polarity not in ("positive", "negative"):
                logger.warning("edge %s--%s->%s has unknown polarity %r; refusing",
                               identity.concept_id, relation, surface, polarity)
                continue
            target = await self._resolve_target(surface)
            await self.db().execute_query(
                """INSERT INTO unified.concept_relations
                       (source_concept_id, relation, target_concept_id,
                        target_surface, evidence_id, extractor, polarity)
                   VALUES ($1,$2,$3,$4,$5,$6,$7)
                   ON CONFLICT (source_concept_id, relation, target_surface,
                                evidence_id, polarity)
                   DO UPDATE SET target_concept_id = COALESCE(
                       EXCLUDED.target_concept_id, unified.concept_relations.target_concept_id)""",
                (identity.concept_id, str(relation)[:128], target,
                 str(surface), envelope.evidence_id, candidate.extractor, polarity),
                commit=True,
            )

    async def contradictions(self, concept_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Triples asserted BOTH ways, with the evidence behind each side.

        Holding a denial is only worth doing if the conflict it creates can be
        seen. Two rows disagreeing is not a bug to be deduplicated away -- it is
        the system noticing it was told opposite things, and which source said
        which is exactly what decides who is wrong.
        """
        rows = await self.db().execute_query(
            """SELECT p.source_concept_id, p.relation, p.target_surface,
                      p.evidence_id AS asserted_by, n.evidence_id AS denied_by,
                      p.extractor AS asserted_extractor, n.extractor AS denied_extractor
                 FROM unified.concept_relations p
                 JOIN unified.concept_relations n
                   ON p.source_concept_id = n.source_concept_id
                  AND p.relation = n.relation
                  AND p.target_surface = n.target_surface
                WHERE p.polarity = 'positive' AND n.polarity = 'negative'
                  AND ($1::text IS NULL OR p.source_concept_id = $1)""",
            (concept_id,), fetch_all=True) or []
        return [dict(r) for r in rows]

    async def holds(self, source_concept_id: str, relation: str,
                    target_surface: str) -> Optional[bool]:
        """True if asserted, False if denied, None if never claimed either way.

        THREE ANSWERS, NOT TWO. "I was never told" is not "no", and collapsing
        them is how a system invents facts it was never given. A triple claimed
        both ways returns None too -- it is unresolved, and the caller should
        ask `contradictions()` rather than be handed a coin flip.
        """
        rows = await self.db().execute_query(
            """SELECT DISTINCT polarity FROM unified.concept_relations
                WHERE source_concept_id = $1 AND relation = $2
                  AND target_surface = $3""",
            (source_concept_id, relation, target_surface), fetch_all=True) or []
        found = {r["polarity"] for r in rows}
        if found == {"positive"}:
            return True
        if found == {"negative"}:
            return False
        return None

    async def relink_dangling_edges(self) -> int:
        """Attach edges whose target has since been learned.

        A concept mentioned before it was learned leaves a dangling edge. When
        it arrives, the edge must connect — otherwise the graph's topology
        depends on ingestion ORDER, and two runs over the same corpus produce
        different structures.
        """
        rows = await self.db().execute_query(
            "SELECT DISTINCT target_surface FROM unified.concept_relations "
            "WHERE target_concept_id IS NULL", fetch_all=True) or []
        linked = 0
        for row in rows:
            target = await self._resolve_target(row["target_surface"])
            if not target:
                continue
            await self.db().execute_query(
                "UPDATE unified.concept_relations SET target_concept_id = $1 "
                "WHERE target_surface = $2 AND target_concept_id IS NULL",
                (target, row["target_surface"]), commit=True)
            linked += 1
        if linked:
            logger.info("Relinked %d previously dangling edge target(s)", linked)
        return linked

    async def _record_alias(self, alias: str, concept_id: str, kind: str) -> None:
        await self.db().execute_query(
            """INSERT INTO unified.concept_aliases (alias, concept_id, alias_kind)
               VALUES ($1,$2,$3) ON CONFLICT (alias) DO NOTHING""",
            (alias, concept_id, kind), commit=True,
        )

    # ---- provenance -----------------------------------------------------

    async def _root_evidence_ids(self, evidence_id: str, _path: Tuple[str, ...] = ()) -> Set[str]:
        """Walk derived_from to origin.

        This is what stops repetition becoming support. Two memories written
        from one research finding resolve to the same single root, so they
        contribute one unit of support between them rather than two.
        """
        path = list(_path or ())
        depth = len(path)

        if evidence_id in path:
            raise InvalidProvenance(
                f"cyclic lineage: {' -> '.join(path + [evidence_id])}. A cycle "
                f"has no origin, so no root can be resolved."
            )
        if depth >= self.MAX_LINEAGE_DEPTH:
            raise InvalidProvenance(
                f"lineage exceeds {self.MAX_LINEAGE_DEPTH} hops "
                f"({' -> '.join(path[:4])} ... {evidence_id}); refusing to walk "
                f"further rather than guessing at a root"
            )

        rows = await self.db().execute_query(
            "SELECT source_type, derived_from FROM unified.evidence_envelopes WHERE evidence_id = $1",
            (evidence_id,), fetch_all=True,
        )
        if not rows:
            # A DANGLING PARENT IS NOT A ROOT.
            #
            # This returned {evidence_id}, which recreated the exact support
            # inflation the root walk exists to prevent: a derivative whose
            # parent was missing or deleted became its own independent root, so
            # a broken chain manufactured corroboration. Unknown lineage is a
            # provenance error, not an origin.
            if not path:
                raise InvalidProvenance(
                    f"evidence {evidence_id} is not recorded; cannot resolve its root"
                )
            raise InvalidProvenance(
                f"dangling lineage: {' -> '.join(path)} -> {evidence_id}, which "
                f"is not recorded. A missing ancestor cannot be treated as an "
                f"independent root."
            )

        parents = rows[0]["derived_from"]
        if isinstance(parents, str):
            parents = json.loads(parents)
        parents = [str(p) for p in (parents or []) if p]

        if evidence_id in parents:
            raise InvalidProvenance(f"{evidence_id} declares itself as its own ancestor")

        if not parents:
            return {evidence_id}

        roots: Set[str] = set()
        for p in parents:
            roots |= await self._root_evidence_ids(p, tuple(path) + (evidence_id,))
        if not roots:
            raise InvalidProvenance(
                f"{evidence_id} declares ancestors {parents} but none resolved to a root"
            )
        return roots

    # ---- persistence ----------------------------------------------------

    async def record_evidence(self, envelope: EvidenceEnvelope) -> None:
        await self._ready()
        await self.db().execute_query(
            """INSERT INTO unified.evidence_envelopes
                   (evidence_id, source_type, source_id, producer, content,
                    structured_data, derived_from, observed_at)
               VALUES ($1,$2,$3,$4,$5,$6::jsonb,$7::jsonb,COALESCE($8, NOW()))
               ON CONFLICT (evidence_id) DO NOTHING""",
            (
                envelope.evidence_id,
                envelope.source_type.value,
                envelope.source_id,
                envelope.producer,
                envelope.content,
                json.dumps(envelope.structured_data or {}),
                json.dumps(list(envelope.derived_from)),
                envelope.observed_at,
            ),
            commit=True,
        )

    async def _status_for(self, root_count: int) -> ConceptExistence:
        if root_count >= WELL_SUPPORTED_MIN_ROOTS:
            return ConceptExistence.WELL_SUPPORTED
        if root_count >= 1:
            return ConceptExistence.OBSERVED
        return ConceptExistence.PROPOSED

    async def _persist(
        self,
        identity: ConceptIdentity,
        candidate: ConceptCandidate,
        envelope: EvidenceEnvelope,
        roots: Set[str],
    ) -> Tuple[bool, Optional[str]]:
        """Upsert the concept and link its evidence. Returns (created, promoted_to)."""
        db = self.db()

        existing = await db.execute_query(
            "SELECT epistemic_status FROM unified.concepts WHERE concept_id = $1",
            (identity.concept_id,), fetch_all=True,
        )
        before = existing[0]["epistemic_status"] if existing else None

        # Link evidence FIRST so the count reflects this observation.
        for root in roots:
            await db.execute_query(
                """INSERT INTO unified.concept_evidence
                       (concept_id, evidence_id, root_evidence_id,
                        extraction_confidence, extractor)
                   VALUES ($1,$2,$3,$4,$5)
                   ON CONFLICT (concept_id, root_evidence_id) DO NOTHING""",
                (identity.concept_id, envelope.evidence_id, root,
                 candidate.extraction_confidence, candidate.extractor),
                commit=True,
            )

        n = (await db.execute_query(
            "SELECT count(DISTINCT root_evidence_id) n FROM unified.concept_evidence WHERE concept_id = $1",
            (identity.concept_id,), fetch_all=True,
        ))[0]["n"]
        status = await self._status_for(int(n))

        provenance = {
            "first_producer": envelope.producer,
            "first_source_type": envelope.source_type.value,
            "extractor": candidate.extractor,
        }

        await db.execute_query(
            """INSERT INTO unified.concepts
                   (concept_id, name, domain, description, attributes,
                    relationships, functions, processes, context, examples,
                    concept_kind, epistemic_status, provenance,
                    root_evidence_count, created_at)
               VALUES ($1,$2,$3,$4,$5::jsonb,$6::jsonb,'[]'::jsonb,'[]'::jsonb,
                       '', '[]'::jsonb, $7,$8,$9::jsonb,$10, NOW())
               ON CONFLICT (concept_id) DO UPDATE SET
                   description         = COALESCE(NULLIF(EXCLUDED.description,''),
                                                  unified.concepts.description),
                   attributes          = unified.concepts.attributes || EXCLUDED.attributes,
                   -- MERGED, NOT REPLACED. Learning one thing about a concept
                   -- is not grounds for forgetting the rest: teaching
                   -- `pressure loss is caused by valve throttling` erased
                   -- `caused by pipe friction` and `caused by minor losses`,
                   -- so a concept got narrower every time anything was added
                   -- to it. Note the two lines either side of this one --
                   -- description is preserved and attributes are merged --
                   -- which is what makes the replacement an oversight rather
                   -- than a policy.
                   relationships       = (
                       SELECT COALESCE(jsonb_agg(DISTINCT edge), '[]'::jsonb)
                       FROM jsonb_array_elements(
                           unified.concepts.relationships || EXCLUDED.relationships
                       ) AS edge
                   ),
                   epistemic_status    = EXCLUDED.epistemic_status,
                   root_evidence_count = EXCLUDED.root_evidence_count,
                   updated_at          = NOW()""",
            (
                identity.concept_id, identity.name, identity.domain,
                candidate.description,
                json.dumps(candidate.attributes or {}),
                json.dumps([list(r) for r in candidate.relationships]),
                identity.concept_kind.value,
                status.value,
                json.dumps(provenance),
                int(n),
            ),
            commit=True,
        )

        # MEMBERSHIP. A concept is identified by NAME on purpose -- domain-
        # qualified ids once scattered one coherent corpus across many domains.
        # But a concept that evidence from several domains merges into must
        # RECORD that it spans them, or the merge is silent: two domains using
        # one name for different things would look like one concept with no
        # trace of the collision. `unified.concept_domains` exists for exactly
        # this and had no writer; this is its writer. Never fatal.
        try:
            from core.domain.concept_identity import ConceptIdentityService
            identity_service = ConceptIdentityService(db)
            sources = [d for d in (candidate.domain_candidates or ()) if d and d.strip()]
            for source_domain in (sources or [identity.domain]):
                await identity_service.add_membership(
                    identity.concept_id, source_domain,
                    source=candidate.extractor, evidence_id=envelope.evidence_id)
        except Exception as e:
            from core.capability import raise_if_structural
            raise_if_structural(e, "concept_ingestion.add_membership")
            logger.debug("membership recording skipped for %s: %s",
                         identity.concept_id, e)

        created = before is None
        promoted = status.value if (before and before != status.value) else None
        return created, promoted

    # ---- entry point ----------------------------------------------------

    async def ingest(self, envelope: EvidenceEnvelope) -> IngestionResult:
        """Turn one observation into semantic structure. The only write path."""
        result = IngestionResult(evidence_id=envelope.evidence_id)
        await self._ready()
        await self.record_evidence(envelope)

        candidates: List[ConceptCandidate] = []
        from .semantic_extraction import ExtractionResult, record_attempt

        for ex in self.extractors:
            produced = ex.extract(envelope)
            if inspect.isawaitable(produced):
                produced = await produced

            if isinstance(produced, ExtractionResult):
                # Typed contract: the attempt is recorded whether or not it
                # yielded anything, so "read it, found nothing" and "never read
                # it" stay distinguishable in the record, not just in a log line.
                await record_attempt(self.db(), produced)
                candidates.extend(produced.candidates)
                if not produced.observed_absence and not produced.candidates:
                    result.extraction_failures.append(
                        (produced.extractor_id,
                         f"{produced.execution_status.value}: {produced.failure_reason}"))
                continue

            candidates.extend(produced or [])
            failure = getattr(ex, "last_failure", None)
            if failure:
                result.extraction_failures.append((getattr(ex, "name", "?"), failure))
        result.candidates = len(candidates)

        if not candidates:
            if result.extraction_failures:
                logger.error(
                    "Evidence %s from %s yielded no candidates because "
                    "extraction FAILED: %s — this is not the same as evidence "
                    "that contains no concepts",
                    envelope.evidence_id, envelope.producer,
                    "; ".join(f"{n}: {r}" for n, r in result.extraction_failures),
                )
            else:
                logger.info(
                    "Evidence %s from %s was read successfully and contains no "
                    "concepts", envelope.evidence_id, envelope.producer,
                )
            return result

        roots = await self._root_evidence_ids(envelope.evidence_id)

        for cand in candidates:
            reason = self.resolver.reject_reason(cand)
            if reason:
                result.rejected.append((cand.label, reason))
                continue
            identity = await self.resolve_identity(cand)
            created, promoted = await self._persist(identity, cand, envelope, roots)
            await self._record_relations(identity, cand, envelope)
            (result.created if created else result.reinforced).append(identity.concept_id)
            if promoted:
                result.promoted.append((identity.concept_id, promoted))

        # Targets named before their concept existed can now attach.
        await self.relink_dangling_edges()

        logger.info(
            "Ingested %s: %d candidate(s) -> %d created, %d reinforced, "
            "%d rejected, %d promoted (roots=%d)",
            envelope.evidence_id, result.candidates, len(result.created),
            len(result.reinforced), len(result.rejected), len(result.promoted),
            len(roots),
        )
        return result


_service: Optional[ConceptIngestionService] = None


def get_concept_ingestion_service(db_manager=None) -> ConceptIngestionService:
    global _service
    if _service is None:
        _service = ConceptIngestionService(db_manager)
    return _service


__all__ = [
    "EvidenceSourceType", "ConceptExistence", "EvidenceEnvelope",
    "ConceptCandidate", "ConceptIdentity", "IngestionResult",
    "ConceptIngestionService",
    "IngestionRefused", "InvalidProvenance", "get_concept_ingestion_service",
    "WELL_SUPPORTED_MIN_ROOTS",
]
