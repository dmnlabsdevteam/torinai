#!/usr/bin/env python3
"""
Domain Types and Core Abstractions
Fundamental types for universal domain representation and cross-domain reasoning
"""

import uuid
import re
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Set, Optional, Any, Tuple, Union
from datetime import datetime
import json

logger = logging.getLogger(__name__)


class DomainType(Enum):
    """Types of knowledge domains"""
    SCIENTIFIC = "scientific"
    TECHNICAL = "technical"
    BUSINESS = "business"
    CREATIVE = "creative"
    SOCIAL = "social"
    PHYSICAL = "physical"
    ABSTRACT = "abstract"
    MATHEMATICAL = "mathematical"
    LINGUISTIC = "linguistic"
    TEMPORAL = "temporal"
    SPATIAL = "spatial"
    CAUSAL = "causal"
    ETHICAL = "ethical"
    AESTHETIC = "aesthetic"
    PRACTICAL = "practical"


class ConceptType(Enum):
    """Types of concepts within domains"""
    ENTITY = "entity"
    PROCESS = "process"
    PROPERTY = "property"
    RELATION = "relation"
    EVENT = "event"
    STATE = "state"
    RULE = "rule"
    PATTERN = "pattern"
    PRINCIPLE = "principle"
    CONSTRAINT = "constraint"
    GOAL = "goal"
    METHOD = "method"


class ConceptDimension(Enum):
    """Dimensions for concept analysis"""
    STRUCTURAL = "structural"
    FUNCTIONAL = "functional"
    CAUSAL = "causal"
    TEMPORAL = "temporal"
    SPATIAL = "spatial"
    SEMANTIC = "semantic"
    PRAGMATIC = "pragmatic"
    CONTEXTUAL = "contextual"
    EMERGENT = "emergent"
    HIERARCHICAL = "hierarchical"


@dataclass
class DomainConcept:
    """A concept within a specific domain"""
    concept_id: str
    name: str
    domain_id: str
    concept_type: ConceptType
    
    # Core properties
    description: str
    properties: Dict[str, Any] = field(default_factory=dict)
    attributes: Dict[str, Any] = field(default_factory=dict)
    
    # Relationships
    parent_concepts: Set[str] = field(default_factory=set)
    child_concepts: Set[str] = field(default_factory=set)
    related_concepts: Set[str] = field(default_factory=set)
    
    # Cross-domain mappings
    analogous_concepts: Dict[str, str] = field(default_factory=dict)  # domain_id -> concept_id
    
    # Semantic properties
    semantic_weight: float = 1.0
    abstraction_level: float = 0.5  # 0=concrete, 1=abstract
    complexity_score: float = 0.5
    
    # Temporal properties
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: Optional[datetime] = None
    
    # Usage statistics
    usage_count: int = 0
    relevance_score: float = 1.0
    
    def __post_init__(self):
        if not self.concept_id:
            self.concept_id = str(uuid.uuid4())


@dataclass
class DomainRelation:
    """A relationship between concepts"""
    relation_id: str
    source_concept_id: str
    target_concept_id: str
    relation_type: str
    
    # Relationship properties
    strength: float = 1.0  # 0-1 strength of relationship
    directionality: str = "bidirectional"  # bidirectional, unidirectional
    confidence: float = 1.0
    
    # Context
    context: Dict[str, Any] = field(default_factory=dict)
    domain_id: str = ""
    
    # Temporal
    created_at: datetime = field(default_factory=datetime.now)
    
    def __post_init__(self):
        if not self.relation_id:
            self.relation_id = str(uuid.uuid4())


@dataclass
class DomainKnowledge:
    """Knowledge within a domain"""
    knowledge_id: str
    domain_id: str
    knowledge_type: str
    
    # Content
    title: str
    content: Dict[str, Any]
    summary: str = ""
    
    # Structure
    concepts: List[str] = field(default_factory=list)  # concept_ids
    relations: List[str] = field(default_factory=list)  # relation_ids
    
    # Metadata
    tags: Set[str] = field(default_factory=set)
    source: str = ""
    confidence: float = 1.0
    importance: float = 1.0
    
    # Cross-domain aspects
    transferable_patterns: List[str] = field(default_factory=list)
    applicable_domains: Set[str] = field(default_factory=set)
    
    # Temporal
    created_at: datetime = field(default_factory=datetime.now)
    last_accessed: Optional[datetime] = None
    
    def __post_init__(self):
        if not self.knowledge_id:
            self.knowledge_id = str(uuid.uuid4())


@dataclass
class Domain:
    """A knowledge domain with its structure and characteristics"""
    domain_id: str
    name: str
    domain_type: DomainType
    
    # Domain characteristics
    description: str
    scope: str = ""
    boundaries: Dict[str, Any] = field(default_factory=dict)
    
    # Structure
    concepts: Dict[str, DomainConcept] = field(default_factory=dict)
    relations: Dict[str, DomainRelation] = field(default_factory=dict)
    knowledge: Dict[str, DomainKnowledge] = field(default_factory=dict)
    
    # Hierarchical structure
    parent_domains: Set[str] = field(default_factory=set)
    child_domains: Set[str] = field(default_factory=set)
    
    # Cross-domain connections
    related_domains: Dict[str, float] = field(default_factory=dict)  # domain_id -> similarity_score
    
    # Domain-specific properties
    core_principles: List[str] = field(default_factory=list)
    methodologies: List[str] = field(default_factory=list)
    vocabulary: Dict[str, str] = field(default_factory=dict)
    
    # Metrics
    complexity_score: float = 0.5
    formalization_level: float = 0.5  # How formal/structured the domain is
    maturity_score: float = 0.5  # How well-developed the domain knowledge is
    
    # Temporal
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: Optional[datetime] = None
    
    def __post_init__(self):
        if not self.domain_id:
            self.domain_id = str(uuid.uuid4())
    
    def add_concept(self, concept: DomainConcept) -> None:
        """Add a concept to this domain"""
        concept.domain_id = self.domain_id
        self.concepts[concept.concept_id] = concept
        self.updated_at = datetime.now()
    
    def add_relation(self, relation: DomainRelation) -> None:
        """Add a relation to this domain"""
        relation.domain_id = self.domain_id
        self.relations[relation.relation_id] = relation
        self.updated_at = datetime.now()
    
    def add_knowledge(self, knowledge: DomainKnowledge) -> None:
        """Add knowledge to this domain"""
        knowledge.domain_id = self.domain_id
        self.knowledge[knowledge.knowledge_id] = knowledge
        self.updated_at = datetime.now()
    
    def get_concept_by_name(self, name: str) -> Optional[DomainConcept]:
        """Get a concept by name"""
        for concept in self.concepts.values():
            if concept.name.lower() == name.lower():
                return concept
        return None
    
    def get_related_concepts(self, concept_id: str) -> List[DomainConcept]:
        """Get all concepts related to a given concept"""
        if concept_id not in self.concepts:
            return []
        
        concept = self.concepts[concept_id]
        related_ids = (concept.parent_concepts | 
                      concept.child_concepts | 
                      concept.related_concepts)
        
        return [self.concepts[cid] for cid in related_ids if cid in self.concepts]


@dataclass
class CrossDomainMapping:
    """Mapping between concepts across domains"""
    mapping_id: str
    source_domain_id: str
    target_domain_id: str
    source_concept_id: str
    target_concept_id: str
    
    # Mapping properties
    mapping_type: str  # analogy, similarity, transformation, etc.
    strength: float = 1.0
    confidence: float = 1.0
    bidirectional: bool = True
    
    # Transformation information
    transformation_rules: Dict[str, Any] = field(default_factory=dict)
    context_requirements: Dict[str, Any] = field(default_factory=dict)
    
    # Validation. TRI-STATE, and the third state is the important one:
    #   None  -- proposed, never put to the ontological test
    #   True  -- tested, structure was preserved
    #   False -- tested, structure was NOT preserved
    # This was a plain `bool = False`, so a freshly suggested candidate and a
    # candidate the validator had actually refuted were the same value. Every
    # consumer -- unified.domain_mappings' readers included -- filters on
    # `verified IS NULL OR verified IS TRUE` precisely to keep those apart, and
    # a default of False marked every untested suggestion as refuted.
    validated: Optional[bool] = None
    validation_score: float = 0.0
    
    # Usage
    usage_count: int = 0
    success_rate: float = 0.0
    
    # Temporal
    created_at: datetime = field(default_factory=datetime.now)
    last_used: Optional[datetime] = None
    
    def __post_init__(self):
        if not self.mapping_id:
            self.mapping_id = str(uuid.uuid4())


@dataclass
class KnowledgeTransfer:
    """A knowledge transfer operation between domains"""
    transfer_id: str
    source_domain_id: str
    target_domain_id: str
    
    # Transfer content
    source_knowledge_ids: List[str] = field(default_factory=list)
    target_knowledge_ids: List[str] = field(default_factory=list)
    
    # Transfer properties
    transfer_type: str = "analogy"  # analogy, abstraction, specialization, etc.
    success_probability: float = 0.5
    
    # Mappings used
    concept_mappings: List[str] = field(default_factory=list)  # mapping_ids
    
    # Results
    transferred_concepts: List[str] = field(default_factory=list)
    new_insights: List[str] = field(default_factory=list)
    validation_results: Dict[str, Any] = field(default_factory=dict)
    
    # Metrics
    effectiveness_score: float = 0.0
    novelty_score: float = 0.0
    
    # Temporal
    initiated_at: datetime = field(default_factory=datetime.now)
    completed_at: Optional[datetime] = None
    
    def __post_init__(self):
        if not self.transfer_id:
            self.transfer_id = str(uuid.uuid4())


# Utility functions for domain operations
def _lexical_similarity(a: str, b: str) -> float:
    """Token-overlap similarity over concept text. Sync and O(1)-ish.

    Deliberately lexical rather than embedding-based: this is called inside the
    cross-domain strategies' cartesian-product loops (N x M concept pairs), and
    an async embedding round-trip per pair would be ruinous. Embeddings would be
    a strict improvement IF this is ever moved off the hot path or backed by a
    pair cache -- embedding_service.compute_similarity() already exists for it.
    """
    if not a or not b:
        return 0.0
    ta = {t for t in re.split(r"[^a-z0-9]+", a.lower()) if len(t) > 2}
    tb = {t for t in re.split(r"[^a-z0-9]+", b.lower()) if len(t) > 2}
    if not ta or not tb:
        return 1.0 if a.strip().lower() == b.strip().lower() else 0.0
    return len(ta & tb) / len(ta | tb)


# Pair-cache backing the encoder, which is what the note above said was the
# precondition for using it here. Concept text is stable and the strategies
# walk the same concepts repeatedly, so the cartesian-product loops encode each
# distinct string once, not once per pair.
_EMBED_CACHE: Dict[str, Optional[List[float]]] = {}
_EMBED_CACHE_MAX = 4096
_EMBED_STATE: Dict[str, Any] = {"degraded_warned": False}


def _embed(text: str) -> Optional[List[float]]:
    """Cached encode through the shared embedding service. None if unavailable."""
    key = text.strip().lower()
    if not key:
        return None
    if key in _EMBED_CACHE:
        return _EMBED_CACHE[key]
    try:
        from core.memory.utils.embedding_service import get_embedding_service
        vec = get_embedding_service().generate_embedding(text)
    except Exception as e:  # encoder absent / model not cached locally
        logger.debug(f"concept embedding unavailable: {e}")
        vec = None
    if len(_EMBED_CACHE) < _EMBED_CACHE_MAX:
        _EMBED_CACHE[key] = vec
    return vec


def _semantic_similarity(a: str, b: str) -> float:
    """How close two pieces of concept text are in MEANING.

    Token overlap cannot express the thing cross-domain reasoning exists to
    find. "muscular organ that pumps blood through vessels" and "mechanical
    device that pumps fluid through pipes" are the same idea in two domains,
    and share 0.38 of their words; the encoder puts them at 0.51 while placing
    an unrelated concept at 0.00. Lexical overlap remains the fallback, but it
    announces itself rather than silently degrading the whole subsystem to
    word-matching.
    """
    if not a or not b:
        return 0.0
    if a.strip().lower() == b.strip().lower():
        return 1.0

    va, vb = _embed(a), _embed(b)
    if va is not None and vb is not None:
        try:
            from core.memory.utils.embedding_service import get_embedding_service
            sim = get_embedding_service().compute_similarity(va, vb)
            if sim is not None:
                return float(sim)
        except Exception as e:
            logger.debug(f"concept similarity encode failed: {e}")

    if not _EMBED_STATE["degraded_warned"]:
        _EMBED_STATE["degraded_warned"] = True
        logger.warning(
            "DEGRADED: concept similarity has fallen back to lexical token overlap "
            "because the embedding service is unavailable. Cross-domain analogies "
            "between differently-named concepts will be under-scored and most will "
            "fall below the mapping threshold."
        )
    return _lexical_similarity(a, b)


def calculate_concept_similarity(concept1: DomainConcept, concept2: DomainConcept) -> float:
    """Similarity between two concepts, dominated by what they MEAN.

    The previous version scored ONLY structural metadata -- concept_type
    equality (0.3), property-KEY overlap (0.4) and abstraction-level proximity
    (0.3) -- and never read `name` or `description`. Two entirely unrelated
    concepts that happened to share a type and abstraction level scored a
    floor of 0.6 by construction.

    That floor was load-bearing in the worst way: cross_domain_reasoner stores
    any mapping above 0.4 into semantic memory, so unrelated domains produced
    persisted, "verified" cross-domain equivalences. Verified before this fix:
    `alpha part_of beta` vs `zeta part_of omega` scored 0.6.

    Meaning now dominates (0.6 of the weight); structure is weak corroboration.
    """
    name_sim = _semantic_similarity(
        getattr(concept1, "name", "") or "", getattr(concept2, "name", "") or ""
    )
    desc_sim = _semantic_similarity(
        getattr(concept1, "description", "") or "",
        getattr(concept2, "description", "") or "",
    )
    # A matching name is the strongest signal, but it is the WRONG thing to
    # require here: a cross-domain analogy has different names by definition --
    # that is what makes it cross-domain. The previous weighting capped the
    # description's contribution at 0.3 of the semantic term, so with name_sim=0
    # the semantic term could not exceed 0.3 and the total could not exceed
    #     0.6*0.3 + 0.2 + 0.1 + 0.1 = 0.58
    # against suggest_cross_domain_mappings' `> 0.6` threshold. A PERFECT
    # analogy -- identical description, identical properties, identical type and
    # abstraction, differing only in name -- scored 0.58 and was rejected.
    # Cross-domain mappings were unreachable by construction; only concepts
    # sharing a name could produce one, which is not an analogy at all.
    # Description now carries the semantic term on its own when names differ.
    semantic = max(name_sim, 0.30 * name_sim + 0.70 * desc_sim)

    props1 = set(concept1.properties.keys())
    props2 = set(concept2.properties.keys())
    prop_overlap = (
        len(props1 & props2) / len(props1 | props2) if (props1 and props2) else 0.0
    )

    type_match = 1.0 if concept1.concept_type == concept2.concept_type else 0.0
    abs_diff = abs(concept1.abstraction_level - concept2.abstraction_level)
    abstraction = 1.0 - min(1.0, abs_diff)

    # Structure CORROBORATES meaning; it must not substitute for it. Summed
    # unconditionally, the three structural terms are a 0.40 floor for any two
    # concepts that share a type, an abstraction level and their property keys
    # -- regardless of what they mean. `glacier` and `compiler` with identical
    # metadata scored 0.4868 that way, over the 0.40 at which
    # cross_domain_reasoner persists a mapping into semantic memory. That is
    # how a fabricated "cross-domain mapping" memory got written at confidence
    # 1.0 during an audit probe. Gating on the semantic term means shared
    # metadata amplifies a real resemblance and contributes nothing to an
    # imaginary one.
    corroboration = min(1.0, semantic / 0.35)

    score = (
        0.60 * semantic          # what the concepts actually are
        + corroboration * (
            0.20 * prop_overlap    # shared structure
            + 0.10 * type_match    # weak: everything is an "entity"
            + 0.10 * abstraction   # weak: proximity is not relatedness
        )
    )
    return round(min(score, 1.0), 4)


def _surface_key(text: str) -> str:
    """Canonical form for matching a relation target against a concept name.

    Relation targets are stored as the surface form the evidence used
    ('pressure loss'); concept names are canonical ('pressure_loss'). Comparing
    them raw matched 8 of 153 domain pairs when the underlying graph connects
    many more.
    """
    return re.sub(r"[^a-z0-9]+", "_", str(text or "").strip().lower()).strip("_")


def _relation_vocabulary(domain: Domain) -> Set[str]:
    """The relation types a domain's concepts actually use.

    Read from concept.properties['relationships'], populated for 89 of 90
    learned concepts. Domain.vocabulary and Domain.relations are both empty for
    every learned domain, so neither can serve here.
    """
    verbs: Set[str] = set()
    for concept in domain.concepts.values():
        for pair in (concept.properties or {}).get("relationships", []) or []:
            if isinstance(pair, (list, tuple)) and pair:
                verbs.add(_surface_key(pair[0]))
    return {v for v in verbs if v}


def structural_complexity(domain: Domain) -> float:
    """Complexity COMPUTED from the graph, in [0, 1].

    Domain.complexity_score is the dataclass default 0.5 for all 33 learned
    domains — nothing computes it — so the complexity term of the similarity
    score was `0.2 * (1 - 0)` for every pair: a constant contributing no
    information while appearing to.

    Size, connectedness and relational variety, each saturating so a large
    domain does not dominate.
    """
    n = len(domain.concepts)
    if not n:
        return 0.0
    edges = sum(len(c.related_concepts or ()) for c in domain.concepts.values())
    size = min(1.0, n / 20.0)
    density = min(1.0, (edges / n) / 4.0) if n else 0.0
    variety = min(1.0, len(_relation_vocabulary(domain)) / 12.0)
    return round(0.4 * size + 0.3 * density + 0.3 * variety, 4)


def calculate_domain_similarity(domain1: Domain, domain2: Domain) -> float:
    """Similarity between two domains, from measures that can actually fire.

    The previous version had four terms of which TWO WERE STRUCTURALLY DEAD and
    a third was constant. Measured over 153 pairs of 18 populated domains:

        concept overlap   0.4  0/153 pairs shared an exact concept name
        principle overlap 0.2  0/33 domains had core_principles populated
        type match        0.2  fires
        complexity        0.2  ALL complexity_score == 0.5 -> always exactly 0.2

        distinct values produced: [0.2, 0.4]   ceiling 0.4

    60% of the weight could never contribute, so the score had two reachable
    values and could not rank anything. It was nevertheless being used to choose
    which domains to attempt knowledge transfer from, while the concept-level
    mapping strength that DOES discriminate (0.0-0.80 across the same domains)
    was computed only afterwards, on whichever three the constant happened to
    yield.

    Why concept-name overlap could never fire: under the identity model a
    concept shared by two domains is ONE concept with two domain memberships,
    not two rows with the same name. That term asked a question the data model
    is designed to make impossible.

    The replacements use what the graph actually holds:

        type affinity        0.15  same DomainType, or same category family
        conceptual coupling  0.35  relation targets naming the other's concepts
        structural signature 0.30  shared relation vocabulary (Jaccard)
        scale affinity       0.20  computed complexity, not the 0.5 default
    """
    score = 0.0

    # 1. TYPE AFFINITY — unchanged in intent, reduced in weight because it is
    #    coarse: 4 distinct types across 18 populated domains.
    if domain1.domain_type == domain2.domain_type:
        score += 0.15

    # 2. CONCEPTUAL COUPLING — does one domain's structure REFER to the other's
    #    concepts? This is the honest replacement for name overlap: domains are
    #    related when their concepts are linked, not when they duplicate names.
    names1 = {_surface_key(c.name) for c in domain1.concepts.values()}
    names2 = {_surface_key(c.name) for c in domain2.concepts.values()}
    targets1 = {_surface_key(t) for c in domain1.concepts.values()
                for t in (c.related_concepts or ())}
    targets2 = {_surface_key(t) for c in domain2.concepts.values()
                for t in (c.related_concepts or ())}
    if names1 and names2:
        crossing = len(targets1 & names2) + len(targets2 & names1)
        reachable = len(targets1) + len(targets2)
        if reachable:
            score += 0.35 * min(1.0, crossing / reachable)

    # 3. STRUCTURAL SIGNATURE — two domains that describe their concepts with
    #    the same KINDS of relation share structure even with no shared
    #    vocabulary of things. This is what the dead principle-overlap term was
    #    reaching for, measured from data that exists.
    verbs1, verbs2 = _relation_vocabulary(domain1), _relation_vocabulary(domain2)
    if verbs1 and verbs2:
        score += 0.30 * (len(verbs1 & verbs2) / len(verbs1 | verbs2))

    # 4. SCALE AFFINITY — computed complexity. Domains of wildly different
    #    maturity are poor transfer partners regardless of topic.
    c1, c2 = structural_complexity(domain1), structural_complexity(domain2)
    score += 0.20 * (1.0 - abs(c1 - c2))

    return round(min(score, 1.0), 4)