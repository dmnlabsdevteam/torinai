#!/usr/bin/env python3
"""
Universal Ontology
Core ontological framework for representing knowledge across all domains
"""

import asyncio
import logging
from typing import Dict, List, Set, Optional, Any, Tuple
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum

from .domain_types import (
    Domain, DomainConcept, DomainRelation, ConceptType, ConceptDimension
)

logger = logging.getLogger(__name__)


class OntologicalRelationType(Enum):
    """Types of ontological relationships"""
    IS_A = "is_a"  # Subsumption/inheritance
    PART_OF = "part_of"  # Mereological
    INSTANCE_OF = "instance_of"  # Instantiation
    SIMILAR_TO = "similar_to"  # Similarity
    OPPOSITE_TO = "opposite_to"  # Opposition
    CAUSES = "causes"  # Causal
    ENABLES = "enables"  # Enablement
    REQUIRES = "requires"  # Dependency
    EQUIVALENT_TO = "equivalent_to"  # Equivalence
    ANALOGOUS_TO = "analogous_to"  # Analogy


@dataclass
class UniversalConcept:
    """A universal concept that transcends domain boundaries"""
    concept_id: str
    name: str
    universal_category: str
    
    # Core characteristics
    description: str
    essential_properties: Dict[str, Any] = field(default_factory=dict)
    invariant_patterns: List[str] = field(default_factory=list)
    
    # Domain manifestations
    domain_instances: Dict[str, str] = field(default_factory=dict)  # domain_id -> concept_id
    
    # Ontological relationships
    super_concepts: Set[str] = field(default_factory=set)
    sub_concepts: Set[str] = field(default_factory=set)
    related_concepts: Dict[str, Set[str]] = field(default_factory=lambda: defaultdict(set))
    
    # Abstraction properties
    abstraction_level: float = 0.5
    universality_score: float = 0.5  # How universal this concept is across domains
    
    # Usage and validation
    confirmed_domains: Set[str] = field(default_factory=set)
    validation_score: float = 0.0


@dataclass
class UniversalPattern:
    """A pattern that appears across multiple domains"""
    pattern_id: str
    name: str
    pattern_type: str
    
    # Pattern definition
    description: str
    abstract_structure: Dict[str, Any] = field(default_factory=dict)
    manifestation_rules: List[str] = field(default_factory=list)
    
    # Domain occurrences
    domain_manifestations: Dict[str, List[str]] = field(default_factory=dict)  # domain_id -> [concept_ids]
    
    # Pattern properties
    generality_score: float = 0.5
    reliability_score: float = 0.5
    predictive_power: float = 0.5


class UniversalOntology:
    """
    Universal ontological framework for cross-domain knowledge representation
    """
    
    def __init__(self):
        self.universal_concepts: Dict[str, UniversalConcept] = {}
        self.universal_patterns: Dict[str, UniversalPattern] = {}
        self.category_hierarchy: Dict[str, Set[str]] = defaultdict(set)
        
        # Core ontological categories
        self.core_categories = {
            "entity": "Physical or abstract things that exist",
            "process": "Activities, changes, or transformations",
            "property": "Characteristics or attributes",
            "relation": "Connections or associations",
            "event": "Occurrences in time",
            "state": "Conditions or situations",
            "role": "Functions or positions",
            "goal": "Intended outcomes or purposes",
            "constraint": "Limitations or restrictions",
            "resource": "Available means or materials"
        }
        
        self.initialized = False
        self._lock = asyncio.Lock()
    
    async def initialize(self) -> bool:
        """Initialize the universal ontology"""
        try:
            async with self._lock:
                await self._setup_core_ontology()
                await self._initialize_universal_patterns()
                self.initialized = True
                logger.info("Universal ontology initialized")
                return True
        except Exception as e:
            logger.error(f"Failed to initialize universal ontology: {e}")
            return False
    
    async def _setup_core_ontology(self):
        """Setup core universal concepts and categories"""
        # Create core universal concepts
        core_concepts = [
            ("entity", "thing", "The most fundamental category of existence"),
            ("process", "change", "Any kind of transformation or activity"),
            ("property", "attribute", "Characteristics that entities possess"),
            ("relation", "connection", "Associations between entities"),
            ("time", "temporal", "The dimension of temporal existence"),
            ("space", "spatial", "The dimension of spatial existence"),
            ("causation", "causal", "The relationship of cause and effect"),
            ("similarity", "comparative", "The relationship of resemblance"),
            ("difference", "comparative", "The relationship of distinction"),
            ("whole", "mereological", "Complete unified entities"),
            ("part", "mereological", "Components of wholes"),
            ("system", "structural", "Organized collections of interacting parts"),
            ("pattern", "structural", "Recurring arrangements or configurations"),
            ("information", "informational", "Data with meaning or significance"),
            ("knowledge", "epistemic", "Justified true beliefs or understanding"),
            ("goal", "teleological", "Intended outcomes or purposes"),
            ("action", "agential", "Deliberate activities performed by agents"),
            ("resource", "practical", "Available means for achieving goals"),
            ("constraint", "practical", "Limitations or restrictions on possibilities")
        ]
        
        for concept_name, category, description in core_concepts:
            concept = UniversalConcept(
                concept_id=f"universal_{concept_name}",
                name=concept_name,
                universal_category=category,
                description=description,
                universality_score=0.9,  # Core concepts are highly universal
                validation_score=1.0     # Assumed validated
            )
            self.universal_concepts[concept.concept_id] = concept
            self.category_hierarchy[category].add(concept.concept_id)
    
    async def _initialize_universal_patterns(self):
        """Initialize common universal patterns"""
        patterns = [
            {
                "name": "hierarchy",
                "type": "structural",
                "description": "Ordered levels of organization with subsumption relationships",
                "structure": {"levels": "ordered", "relations": ["is_a", "part_of"]},
                "rules": ["transitivity", "asymmetry"]
            },
            {
                "name": "composition",
                "type": "structural", 
                "description": "Wholes composed of interacting parts",
                "structure": {"whole": "entity", "parts": "set", "interactions": "relations"},
                "rules": ["emergent_properties", "downward_causation"]
            },
            {
                "name": "process_flow",
                "type": "temporal",
                "description": "Sequential stages of transformation",
                "structure": {"stages": "ordered", "transitions": "processes", "states": "conditions"},
                "rules": ["temporal_ordering", "state_transitions"]
            },
            {
                "name": "feedback_loop",
                "type": "causal",
                "description": "Circular causal relationships creating self-regulation",
                "structure": {"elements": "agents", "feedback": "causal_loop"},
                "rules": ["circular_causation", "self_regulation"]
            },
            {
                "name": "trade_off",
                "type": "optimization",
                "description": "Competing objectives requiring balance",
                "structure": {"objectives": "goals", "constraints": "limitations"},
                "rules": ["pareto_optimality", "constraint_satisfaction"]
            }
        ]
        
        for pattern_data in patterns:
            pattern = UniversalPattern(
                pattern_id=f"pattern_{pattern_data['name']}",
                name=pattern_data["name"],
                pattern_type=pattern_data["type"],
                description=pattern_data["description"],
                abstract_structure=pattern_data["structure"],
                manifestation_rules=pattern_data["rules"],
                generality_score=0.8,
                reliability_score=0.7
            )
            self.universal_patterns[pattern.pattern_id] = pattern
    
    async def analyze_domain_concepts(self, domain: Domain) -> Dict[str, Any]:
        """Analyze domain concepts for universal patterns and mappings"""
        analysis = {
            "universal_mappings": [],
            "identified_patterns": [],
            "novel_concepts": [],
            "ontological_gaps": [],
            "suggestions": []
        }
        
        # Find mappings to universal concepts
        for concept in domain.concepts.values():
            mappings = await self._find_universal_mappings(concept)
            if mappings:
                analysis["universal_mappings"].extend(mappings)
            else:
                analysis["novel_concepts"].append({
                    "concept_id": concept.concept_id,
                    "name": concept.name,
                    "reason": "No clear universal mapping found"
                })
        
        # Identify universal patterns in the domain
        patterns = await self._identify_patterns_in_domain(domain)
        analysis["identified_patterns"] = patterns
        
        # Suggest ontological improvements
        suggestions = await self._generate_ontological_suggestions(domain)
        analysis["suggestions"] = suggestions
        
        return analysis
    
    async def _find_universal_mappings(self, concept: DomainConcept) -> List[Dict[str, Any]]:
        """Find potential mappings from domain concept to universal concepts"""
        mappings = []
        
        for universal_concept in self.universal_concepts.values():
            similarity_score = await self._calculate_concept_universality(concept, universal_concept)
            
            if similarity_score > 0.6:  # Threshold for considering a mapping
                mappings.append({
                    "domain_concept": concept.concept_id,
                    "universal_concept": universal_concept.concept_id,
                    "similarity_score": similarity_score,
                    "mapping_type": self._determine_mapping_type(concept, universal_concept),
                    "confidence": similarity_score * 0.8
                })
        
        # Sort by similarity score
        mappings.sort(key=lambda x: x["similarity_score"], reverse=True)
        return mappings[:3]  # Return top 3 mappings
    
    async def _calculate_concept_universality(self, domain_concept: DomainConcept, 
                                           universal_concept: UniversalConcept) -> float:
        """Calculate how well a domain concept maps to a universal concept"""
        score = 0.0
        
        # Name similarity
        if universal_concept.name.lower() in domain_concept.name.lower():
            score += 0.3
        
        # Type compatibility
        if self._are_types_compatible(domain_concept.concept_type, universal_concept.universal_category):
            score += 0.4
        
        # Property overlap
        domain_props = set(domain_concept.properties.keys())
        universal_props = set(universal_concept.essential_properties.keys())
        if domain_props and universal_props:
            overlap = len(domain_props & universal_props) / len(domain_props | universal_props)
            score += 0.3 * overlap
        
        return min(score, 1.0)
    
    def _are_types_compatible(self, concept_type: ConceptType, universal_category: str) -> bool:
        """Check if a domain concept type is compatible with a universal category"""
        compatibility_map = {
            ConceptType.ENTITY: ["thing", "structural", "mereological"],
            ConceptType.PROCESS: ["change", "temporal", "causal"],
            ConceptType.PROPERTY: ["attribute", "comparative"],
            ConceptType.RELATION: ["connection", "structural"],
            ConceptType.EVENT: ["temporal", "causal"],
            ConceptType.STATE: ["temporal", "structural"],
            ConceptType.RULE: ["epistemic", "practical"],
            ConceptType.PATTERN: ["structural", "informational"],
            ConceptType.PRINCIPLE: ["epistemic", "practical"],
            ConceptType.CONSTRAINT: ["practical", "structural"],
            ConceptType.GOAL: ["teleological", "practical"],
            ConceptType.METHOD: ["practical", "agential"]
        }
        
        compatible_categories = compatibility_map.get(concept_type, [])
        return universal_category in compatible_categories
    
    def _determine_mapping_type(self, domain_concept: DomainConcept, 
                               universal_concept: UniversalConcept) -> str:
        """Determine the type of mapping between concepts"""
        if domain_concept.name.lower() == universal_concept.name.lower():
            return "exact_match"
        elif universal_concept.name.lower() in domain_concept.name.lower():
            return "specialization"
        elif domain_concept.name.lower() in universal_concept.name.lower():
            return "generalization"
        else:
            return "analogy"
    
    async def _identify_patterns_in_domain(self, domain: Domain) -> List[Dict[str, Any]]:
        """Identify universal patterns present in the domain"""
        identified_patterns = []
        
        for pattern in self.universal_patterns.values():
            manifestation = await self._find_pattern_manifestation(domain, pattern)
            if manifestation:
                identified_patterns.append({
                    "pattern_id": pattern.pattern_id,
                    "pattern_name": pattern.name,
                    "manifestation": manifestation,
                    "confidence": manifestation.get("confidence", 0.5)
                })
        
        return identified_patterns
    
    async def _find_pattern_manifestation(self, domain: Domain, 
                                        pattern: UniversalPattern) -> Optional[Dict[str, Any]]:
        """Find if and how a universal pattern manifests in the domain"""
        # This is a simplified pattern matching - could be much more sophisticated
        if pattern.name == "hierarchy":
            return await self._find_hierarchy_pattern(domain)
        elif pattern.name == "composition":
            return await self._find_composition_pattern(domain)
        elif pattern.name == "process_flow":
            return await self._find_process_flow_pattern(domain)
        
        return None
    
    async def _find_hierarchy_pattern(self, domain: Domain) -> Optional[Dict[str, Any]]:
        """Find hierarchical patterns in domain concepts"""
        hierarchical_relations = []
        
        for relation in domain.relations.values():
            if relation.relation_type in ["is_a", "part_of", "specializes", "generalizes"]:
                hierarchical_relations.append(relation)
        
        if len(hierarchical_relations) >= 2:  # Minimum for a hierarchy
            return {
                "type": "hierarchy",
                "relations": [r.relation_id for r in hierarchical_relations],
                "confidence": min(0.8, len(hierarchical_relations) / len(domain.relations) * 2)
            }
        
        return None
    
    async def _find_composition_pattern(self, domain: Domain) -> Optional[Dict[str, Any]]:
        """Find compositional patterns in domain concepts"""
        compositional_relations = []
        
        for relation in domain.relations.values():
            if relation.relation_type in ["part_of", "contains", "composed_of"]:
                compositional_relations.append(relation)
        
        if len(compositional_relations) >= 1:
            return {
                "type": "composition",
                "relations": [r.relation_id for r in compositional_relations],
                "confidence": min(0.7, len(compositional_relations) / max(1, len(domain.relations)))
            }
        
        return None
    
    async def _find_process_flow_pattern(self, domain: Domain) -> Optional[Dict[str, Any]]:
        """Find process flow patterns in domain concepts"""
        process_concepts = [c for c in domain.concepts.values() 
                          if c.concept_type == ConceptType.PROCESS]
        
        if len(process_concepts) >= 2:
            # Look for temporal or sequential relationships
            sequential_relations = []
            for relation in domain.relations.values():
                if relation.relation_type in ["follows", "precedes", "enables", "leads_to"]:
                    sequential_relations.append(relation)
            
            if sequential_relations:
                return {
                    "type": "process_flow",
                    "processes": [c.concept_id for c in process_concepts],
                    "relations": [r.relation_id for r in sequential_relations],
                    "confidence": 0.6
                }
        
        return None
    
    async def _generate_ontological_suggestions(self, domain: Domain) -> List[Dict[str, Any]]:
        """Generate suggestions for improving domain ontology"""
        suggestions = []
        
        # Suggest missing core concepts
        core_concept_names = {uc.name for uc in self.universal_concepts.values()}
        domain_concept_names = {c.name.lower() for c in domain.concepts.values()}
        
        missing_core_concepts = core_concept_names - domain_concept_names
        if missing_core_concepts:
            suggestions.append({
                "type": "missing_concepts",
                "description": "Consider adding these universal concepts to your domain",
                "concepts": list(missing_core_concepts)[:5]  # Top 5
            })
        
        # Suggest additional relationships
        if len(domain.relations) < len(domain.concepts) * 0.5:
            suggestions.append({
                "type": "sparse_relations",
                "description": "Domain might benefit from more explicit relationships between concepts",
                "recommendation": "Add more relations to capture domain structure"
            })
        
        # Suggest pattern implementation
        suggestions.append({
            "type": "pattern_suggestion", 
            "description": "Consider implementing these universal patterns",
            "patterns": ["hierarchy", "composition"] if len(domain.concepts) > 5 else ["composition"]
        })
        
        return suggestions
    
    async def create_universal_concept(self, name: str, category: str, 
                                     description: str) -> UniversalConcept:
        """Create a new universal concept"""
        concept = UniversalConcept(
            concept_id=f"universal_{name}_{len(self.universal_concepts)}",
            name=name,
            universal_category=category,
            description=description
        )
        
        async with self._lock:
            self.universal_concepts[concept.concept_id] = concept
            self.category_hierarchy[category].add(concept.concept_id)
        
        return concept
    
    async def link_domain_concept_to_universal(self, domain_id: str, domain_concept_id: str,
                                             universal_concept_id: str) -> bool:
        """Link a domain concept to a universal concept"""
        if universal_concept_id not in self.universal_concepts:
            return False
        
        async with self._lock:
            universal_concept = self.universal_concepts[universal_concept_id]
            universal_concept.domain_instances[domain_id] = domain_concept_id
            universal_concept.confirmed_domains.add(domain_id)
            
            # Update universality score based on number of domains
            num_domains = len(universal_concept.confirmed_domains)
            universal_concept.universality_score = min(0.95, 0.1 + (num_domains * 0.15))
        
        return True
    
    #: ConceptType for each universal concept, keyed on the ontology's own
    #: concept name. Keyed per concept rather than per `universal_category`
    #: because two categories carry concepts of different kinds: "structural"
    #: holds both `system` (a thing) and `pattern` (an arrangement), and
    #: "practical" holds both `resource` (a thing) and `constraint` (a limit).
    _UNIVERSAL_CONCEPT_TYPES: Dict[str, ConceptType] = {
        "entity": ConceptType.ENTITY,
        "whole": ConceptType.ENTITY,
        "part": ConceptType.ENTITY,
        "system": ConceptType.ENTITY,
        "information": ConceptType.ENTITY,
        "knowledge": ConceptType.ENTITY,
        "resource": ConceptType.ENTITY,
        "process": ConceptType.PROCESS,
        "action": ConceptType.PROCESS,
        "property": ConceptType.PROPERTY,
        "time": ConceptType.PROPERTY,     # a dimension things are extended in
        "space": ConceptType.PROPERTY,
        "relation": ConceptType.RELATION,
        "causation": ConceptType.RELATION,
        "similarity": ConceptType.RELATION,
        "difference": ConceptType.RELATION,
        "pattern": ConceptType.PATTERN,
        "goal": ConceptType.GOAL,
        "constraint": ConceptType.CONSTRAINT,
    }

    def project_universal_level(
        self, domain_id: str
    ) -> Tuple[List[DomainConcept], List[DomainRelation]]:
        """Express the universal level as domain concepts and relations.

        The ontology holds 19 universal concepts and 5 universal patterns --
        the genuinely domain-independent level. The DomainRegistry holds the
        learned FIELDS. Nothing joined them, so `domain_abstract` sat empty
        while the abstract concepts existed one module away, and any reference
        to the ABSTRACT category resolved to nothing.

        This is a PROJECTION, not a copy into a second store. The ontology
        stays the authority: the registry rebuilds this view on every load and
        never persists it to unified.concepts, so the two cannot drift and the
        universal level never appears in the record as something Torin learned.

        Only structure the ontology actually records is emitted. Where a
        concept has no recorded relations, none are invented -- an abstract
        concept with no edges is reported as it is, because a fabricated edge
        would be indistinguishable from a discovered one to everything
        downstream that scores structural correspondence.
        """
        concepts: List[DomainConcept] = []
        relations: List[DomainRelation] = []
        by_name = {c.name: f"{domain_id}:{c.name}" for c in self.universal_concepts.values()}

        missing = sorted(c.name for c in self.universal_concepts.values()
                         if c.name not in self._UNIVERSAL_CONCEPT_TYPES)
        if missing:
            # RAISE, do not skip. Dropping an unassigned concept would shrink
            # the abstract level silently and leave the registry reporting a
            # smaller universal vocabulary than the ontology holds -- a wrong
            # answer that looks like a complete one. Adding a universal concept
            # is a deliberate act; assigning its type is part of that act.
            raise ValueError(
                f"universal concept(s) {missing} have no ConceptType assignment "
                f"in _UNIVERSAL_CONCEPT_TYPES; the projection cannot represent "
                f"them and must not silently omit them")

        for uc in self.universal_concepts.values():
            ctype = self._UNIVERSAL_CONCEPT_TYPES[uc.name]
            concepts.append(DomainConcept(
                concept_id=by_name[uc.name],
                name=uc.name,
                domain_id=domain_id,
                concept_type=ctype,
                description=uc.description,
                properties={
                    "universal_category": uc.universal_category,
                    "universality_score": uc.universality_score,
                    "source": "universal_ontology",
                    "universal_concept_id": uc.concept_id,
                },
            ))
            # Recorded ontological structure. Empty on the core concepts today;
            # emitted rather than assumed absent so that anything later linked
            # via link_domain_concept_to_universal appears here without a
            # second change. super_concepts/related_concepts hold concept IDS,
            # while patterns name concepts by NAME, so references are resolved
            # through _projected_ref, which accepts either and refuses unknowns.
            for parent in uc.super_concepts:
                relations.append(self._projected_relation(
                    domain_id, by_name[uc.name],
                    self._projected_ref(parent, domain_id, uc.concept_id), "is_a"))
            for rel_type, targets in uc.related_concepts.items():
                for t in targets:
                    relations.append(self._projected_relation(
                        domain_id, by_name[uc.name],
                        self._projected_ref(t, domain_id, uc.concept_id),
                        str(rel_type)))

        # Patterns carry declared structure -- hierarchy states relations
        # ["is_a", "part_of"], composition states {"whole": "entity",
        # "interactions": "relations"}. Where a declared value names a
        # universal concept, that IS a recorded edge and is emitted as one.
        for up in self.universal_patterns.values():
            pid = f"{domain_id}:{up.name}"
            concepts.append(DomainConcept(
                concept_id=pid, name=up.name, domain_id=domain_id,
                concept_type=ConceptType.PATTERN, description=up.description,
                properties={
                    "pattern_type": up.pattern_type,
                    "abstract_structure": up.abstract_structure,
                    "manifestation_rules": up.manifestation_rules,
                    "generality_score": up.generality_score,
                    "source": "universal_ontology",
                    "universal_pattern_id": up.pattern_id,
                },
            ))
            for role, value in up.abstract_structure.items():
                for token in (value if isinstance(value, list) else [value]):
                    target = self._structure_token_to_concept(str(token), by_name)
                    if target is None:
                        # A genuine non-reference: "ordered", "set", "conditions"
                        # describe the role's shape, they do not name a universal
                        # concept. Retained in the pattern's properties above.
                        continue
                    relations.append(self._projected_relation(
                        domain_id, pid, target, str(role)))

        return concepts, relations

    @staticmethod
    def _projected_relation(domain_id: str, source_id: str, target_id: str,
                            relation_type: str) -> DomainRelation:
        """A projection edge with a STABLE id.

        The projection is rebuilt on every load. A generated uuid would give the
        same ontological edge a different identity each start, so any structure
        compared across restarts would look changed when nothing had.
        """
        return DomainRelation(
            relation_id=f"{source_id}--{relation_type}->{target_id}",
            source_concept_id=source_id,
            target_concept_id=target_id,
            relation_type=relation_type,
            domain_id=domain_id,
        )

    def _projected_ref(self, ref: str, domain_id: str, owner: str) -> str:
        """Resolve an ontology reference (id or name) to its projected id.

        Refuses unknown references. Returning a placeholder or skipping would
        drop a recorded ontological edge, and a missing edge is read downstream
        as "these do not correspond" -- the exact conflation between absent
        wiring and a real negative this subsystem keeps producing.
        """
        target = self.universal_concepts.get(ref)
        if target is None:
            for c in self.universal_concepts.values():
                if c.name == ref:
                    target = c
                    break
        if target is None:
            raise KeyError(
                f"universal concept {owner!r} references {ref!r}, which is not a "
                f"registered universal concept; the projection would silently "
                f"lose this edge")
        return f"{domain_id}:{target.name}"

    def _structure_token_to_concept(
        self, token: str, by_name: Dict[str, str]
    ) -> Optional[str]:
        """Map a declared structure value to a universal concept, or None.

        Patterns declare structure in plural prose ("relations", "processes",
        "goals"). Candidates are tested EXPLICITLY against real concept names;
        no generic stemming. `str.rstrip("s")` -- the obvious shortcut -- strips
        every trailing "s", turning "processes" into "processe", which matches
        nothing and drops the process_flow -> process edge without a trace.
        """
        for candidate in (token, token[:-1], token[:-2]):
            if candidate in by_name:
                return by_name[candidate]
        return None

    async def get_universal_concept_by_name(self, name: str) -> Optional[UniversalConcept]:
        """Get a universal concept by name"""
        for concept in self.universal_concepts.values():
            if concept.name.lower() == name.lower():
                return concept
        return None
    
    async def get_concepts_by_category(self, category: str) -> List[UniversalConcept]:
        """Get all universal concepts in a category"""
        return [self.universal_concepts[cid] for cid in self.category_hierarchy[category]]
    
    async def suggest_cross_domain_analogies(self, source_domain_id: str, 
                                           target_domain_id: str) -> List[Dict[str, Any]]:
        """Suggest analogies between domains based on universal concepts"""
        analogies = []
        
        # Find universal concepts present in both domains
        source_universals = set()
        target_universals = set()
        
        for universal_concept in self.universal_concepts.values():
            if source_domain_id in universal_concept.domain_instances:
                source_universals.add(universal_concept.concept_id)
            if target_domain_id in universal_concept.domain_instances:
                target_universals.add(universal_concept.concept_id)
        
        # Common universal concepts suggest direct analogies
        common_universals = source_universals & target_universals
        
        for universal_id in common_universals:
            universal_concept = self.universal_concepts[universal_id]
            source_concept_id = universal_concept.domain_instances[source_domain_id]
            target_concept_id = universal_concept.domain_instances[target_domain_id]
            
            analogies.append({
                "type": "direct_analogy",
                "source_concept": source_concept_id,
                "target_concept": target_concept_id,
                "universal_basis": universal_id,
                "confidence": universal_concept.universality_score
            })
        
        return analogies
    
    #: Fraction of the source concept's relations that must be preserved at the
    #: target for a mapping to be ACCEPTED. A POLICY threshold, not a measured
    #: error rate: it says how much structure must survive, not how likely the
    #: mapping is to be true.
    RELATION_PRESERVATION_THRESHOLD = 0.5

    #: Below this many edges on either side, structure cannot be judged. The
    #: verdict is INDETERMINATE, never REJECTED -- an unmeasurable mapping is
    #: not a refuted one.
    MIN_EDGES_TO_JUDGE = 2

    async def validate_cross_domain_mapping(self, mapping_data: Dict[str, Any]) -> Dict[str, Any]:
        """Test whether a proposed mapping PRESERVES STRUCTURE.

        This returned `valid=True, confidence=0.7` unconditionally, with a
        comment saying real logic "would be implemented". Calling it would have
        stamped every proposal as validated knowledge -- which is why
        universal_domain_master._generate_mappings deliberately did NOT call it
        and left `verified=None` instead.

        A mapping is a claim that two concepts occupy analogous positions in
        their own structures. That is testable against the learned graph: if
        A relates to X by R, an analogous B should relate to something by R too.
        Similarity of the two concepts is NOT evidence for it -- similarity is
        what proposed the mapping in the first place, so accepting on similarity
        would be accepting the hypothesis as its own confirmation.

        Three verdicts, and REJECTED must be reachable or the validator is
        decorative:

            ACCEPTED       enough of the source's structure survives at the target
            REJECTED       structure was measurable and did not correspond
            INDETERMINATE  too few edges on either side to judge
        """
        result = {
            "verdict": "INDETERMINATE",
            "valid": False,
            "confidence": 0.0,
            "issues": [],
            "suggestions": [],
            "measurements": {},
        }

        source_id = mapping_data.get("source_concept_id")
        target_id = mapping_data.get("target_concept_id")
        if not source_id or not target_id:
            result["issues"].append("mapping does not name both concepts")
            return result

        try:
            from core.database import get_database_manager
            db = get_database_manager()
            if not getattr(db, "initialized", False):
                await db.initialize()

            async def edges(cid):
                rows = await db.execute_query(
                    "SELECT relation, target_concept_id FROM unified.concept_relations "
                    "WHERE source_concept_id = $1 AND target_concept_id IS NOT NULL",
                    (cid,), fetch_all=True) or []
                return [(r["relation"], r["target_concept_id"]) for r in rows]

            src_edges = await edges(source_id)
            tgt_edges = await edges(target_id)
        except Exception as e:
            # Unmeasurable is not refuted.
            result["issues"].append(f"structure unavailable: {e}")
            return result

        result["measurements"] = {
            "source_edges": len(src_edges),
            "target_edges": len(tgt_edges),
        }

        if len(src_edges) < self.MIN_EDGES_TO_JUDGE or len(tgt_edges) < self.MIN_EDGES_TO_JUDGE:
            result["issues"].append(
                f"too few edges to judge ({len(src_edges)}/{len(tgt_edges)}; "
                f"{self.MIN_EDGES_TO_JUDGE} needed on each side)")
            return result

        # RELATION PRESERVATION -- the load-bearing test. Raw relation labels;
        # relation-class normalisation is deliberately not applied so its
        # contribution can be measured separately later.
        src_relations = [r for r, _t in src_edges]
        tgt_relations = {r for r, _t in tgt_edges}
        preserved = [r for r in src_relations if r in tgt_relations]
        preservation = len(preserved) / len(src_relations)

        # DEGREE CONSISTENCY -- an analogue occupying the same role should have
        # a comparable number of connections. Reported, not gating.
        degree_ratio = min(len(src_edges), len(tgt_edges)) / max(len(src_edges), len(tgt_edges))

        result["measurements"].update({
            "relations_preserved": len(preserved),
            "relation_preservation": round(preservation, 4),
            "preserved_relations": sorted(set(preserved)),
            "degree_consistency": round(degree_ratio, 4),
            "threshold": self.RELATION_PRESERVATION_THRESHOLD,
        })

        if preservation >= self.RELATION_PRESERVATION_THRESHOLD:
            result["verdict"] = "ACCEPTED"
            result["valid"] = True
            # Confidence is EARNED from what survived, not asserted.
            result["confidence"] = round(preservation * degree_ratio, 4)
        else:
            result["verdict"] = "REJECTED"
            result["valid"] = False
            result["confidence"] = 0.0
            result["issues"].append(
                f"only {len(preserved)}/{len(src_relations)} source relations "
                f"({preservation:.0%}) are present at the target")
            if preserved:
                result["suggestions"].append(
                    f"partial structure survives via {sorted(set(preserved))}")

        return result


# Singleton instance
_universal_ontology = None


def get_universal_ontology() -> UniversalOntology:
    """Get global universal ontology instance (singleton)"""
    global _universal_ontology
    if _universal_ontology is None:
        _universal_ontology = UniversalOntology()
    return _universal_ontology