#!/usr/bin/env python3
"""
Cross-Domain Reasoner
Advanced reasoning system for knowledge transfer and analogical reasoning across domains
"""

import asyncio
import logging
from typing import Dict, List, Set, Optional, Any, Tuple
from dataclasses import dataclass, field
from enum import Enum
import json

from .domain_types import (
    Domain, DomainConcept, DomainRelation, DomainKnowledge,
    CrossDomainMapping, KnowledgeTransfer, calculate_concept_similarity
)
from .domain_registry import DomainRegistry
from .universal_ontology import UniversalOntology

logger = logging.getLogger(__name__)


class ReasoningStrategy(Enum):
    """Types of cross-domain reasoning strategies"""
    ANALOGICAL = "analogical"
    STRUCTURAL = "structural"
    FUNCTIONAL = "functional"
    CAUSAL = "causal"
    PATTERN_BASED = "pattern_based"
    ABSTRACTION = "abstraction"
    COMPOSITIONAL = "compositional"


@dataclass
class ReasoningContext:
    """Context for cross-domain reasoning operations"""
    source_domain_id: str
    target_domain_id: str
    reasoning_goal: str
    strategy: ReasoningStrategy
    
    # Context constraints
    allowed_concepts: Optional[Set[str]] = None
    excluded_concepts: Optional[Set[str]] = None
    confidence_threshold: float = 0.5
    
    # Reasoning parameters
    max_depth: int = 3
    max_mappings: int = 10
    require_validation: bool = True


@dataclass
class ReasoningResult:
    """Result of a cross-domain reasoning operation"""
    reasoning_id: str
    source_domain_id: str
    target_domain_id: str
    strategy: ReasoningStrategy
    
    # Results
    success: bool
    confidence: float
    generated_mappings: List[CrossDomainMapping] = field(default_factory=list)
    transferred_knowledge: List[DomainKnowledge] = field(default_factory=list)
    new_insights: List[str] = field(default_factory=list)
    
    # Reasoning trace
    reasoning_steps: List[Dict[str, Any]] = field(default_factory=list)
    used_mappings: List[str] = field(default_factory=list)
    
    # Validation
    validation_score: float = 0.0
    validation_details: Dict[str, Any] = field(default_factory=dict)


class CrossDomainReasoner:
    """
    Advanced cross-domain reasoning engine for knowledge transfer and analogical inference
    """
    
    def __init__(self, domain_registry: DomainRegistry, universal_ontology: UniversalOntology):
        self.domain_registry = domain_registry
        self.universal_ontology = universal_ontology
        
        # Reasoning strategies
        self.strategies = {
            ReasoningStrategy.ANALOGICAL: self._analogical_reasoning,
            ReasoningStrategy.STRUCTURAL: self._structural_reasoning,
            ReasoningStrategy.FUNCTIONAL: self._functional_reasoning,
            ReasoningStrategy.CAUSAL: self._causal_reasoning,
            ReasoningStrategy.PATTERN_BASED: self._pattern_based_reasoning,
            ReasoningStrategy.ABSTRACTION: self._abstraction_reasoning,
            ReasoningStrategy.COMPOSITIONAL: self._compositional_reasoning
        }
        
        # Reasoning cache
        self.reasoning_cache: Dict[str, ReasoningResult] = {}
        
        self._lock = asyncio.Lock()
        self.initialized = False
    
    async def initialize(self) -> bool:
        """Initialize the cross-domain reasoner"""
        try:
            # Validate dependencies are set
            if self.domain_registry is None:
                raise RuntimeError("domain_registry dependency not injected - dependency injection failed")
            
            if self.universal_ontology is None:
                raise RuntimeError("universal_ontology dependency not injected - dependency injection failed")
            
            # Ensure dependencies are initialized
            if not hasattr(self.domain_registry, 'initialized') or not self.domain_registry.initialized:
                await self.domain_registry.initialize()
            
            if not hasattr(self.universal_ontology, 'initialized') or not self.universal_ontology.initialized:
                await self.universal_ontology.initialize()
            
            self.initialized = True
            logger.info("Cross-domain reasoner initialized")
            return True
        except RuntimeError:
            # Re-raise RuntimeError as-is (expected configuration errors)
            raise
        except Exception as e:
            logger.error(f"Failed to initialize cross-domain reasoner: {e}")
            raise RuntimeError(f"Cross-domain reasoner initialization failed: {e}") from e
    
    async def reason_across_domains(self, context: ReasoningContext) -> ReasoningResult:
        """Perform cross-domain reasoning using the specified strategy"""
        if not self.initialized:
            # The result is CHECKED. Discarding it meant a failed initialize was
            # followed by the work it was meant to enable, and the real failure
            # resurfaced later disguised as something else.
            if await self.initialize() is False:
                raise RuntimeError(
                    type(self).__name__ + ' could not initialize; refusing to '
                    'continue as though it had')
        
        # Check cache first
        cache_key = self._generate_cache_key(context)
        if cache_key in self.reasoning_cache:
            return self.reasoning_cache[cache_key]
        
        # Get reasoning strategy
        strategy_func = self.strategies.get(context.strategy)
        if not strategy_func:
            return ReasoningResult(
                reasoning_id=cache_key,
                source_domain_id=context.source_domain_id,
                target_domain_id=context.target_domain_id,
                strategy=context.strategy,
                success=False,
                confidence=0.0,
                new_insights=["Unsupported reasoning strategy"]
            )
        
        try:
            # Execute reasoning strategy
            result = await strategy_func(context)
            
            # Validate results if required
            if context.require_validation:
                await self._validate_reasoning_result(result)

            # Cache the result
            self.reasoning_cache[cache_key] = result

            # STORE TO MEMORY WITH RICH METADATA
            if result.success and result.confidence >= 0.4:
                try:
                    from core.memory import get_memory_agent
                    from core.memory.utils.interfaces import MemoryType

                    memory_agent = await get_memory_agent()

                    # Build rich metadata UPSTREAM
                    thinking_state = {
                        "reasoning_id": result.reasoning_id,
                        "source_domain": context.source_domain_id,
                        "target_domain": context.target_domain_id,
                        "strategy": context.strategy.value,
                        # RICH METADATA: Justification
                        "justification": {
                            "store_reason": [
                                "cross_domain_synthesis",
                                "multi_domain_inference",
                                context.strategy.value,
                                f"{len(result.generated_mappings)}_mappings_generated"
                            ],
                            "decision_summary": f"Cross-domain reasoning from {context.source_domain_id} to {context.target_domain_id} using {context.strategy.value}",
                            "alternatives_considered": ["single_domain_reasoning", "direct_transfer", "no_mapping"],
                            "rejected_because": ["insufficient_domain_coverage", "requires_cross_domain_synthesis", "knowledge_gap"],
                            "complexity_assessment": "very_high" if len(result.reasoning_steps) > 5 else "high",
                            "novelty_assessment": "novel" if len(result.new_insights) > 2 and result.confidence > 0.8 else "incremental"
                        },
                        # RICH METADATA: Outcome
                        "outcome": {
                            "action_type": "cross_domain_reasoning",
                            "action_summary": f"Generated {len(result.generated_mappings)} cross-domain mappings with {len(result.new_insights)} insights",
                            "affected_components": ["cross_domain_reasoner", context.source_domain_id, context.target_domain_id],
                            "created_new_knowledge": len(result.new_insights) > 0,
                            "confidence": result.confidence,
                            # Self-reported by the strategy that produced the
                            # result. Labelled as such so a reader cannot mistake
                            # it for an assessed impact.
                            "impact_assessment": "critical" if result.confidence > 0.9 else "significant" if result.confidence > 0.7 else "moderate",
                            "impact_assessment_basis": "self_reported_confidence",
                            # `require_validation` is a REQUEST for validation,
                            # not its outcome. Stamping "verified" from it meant
                            # asking for validation was sufficient to be marked
                            # verified -- _validate_reasoning_result computed
                            # result.validation_score and no one ever read it.
                            # That is how a probe wrote a mapping memory marked
                            # verified at confidence 1.0.
                            "verification_status": _verification_status(context, result),
                            "validation_score": getattr(result, "validation_score", None),
                        }
                    }

                    decision_factors = {
                        "strategy": context.strategy.value,
                        "source_domain": context.source_domain_id,
                        "target_domain": context.target_domain_id,
                        "max_mappings": context.max_mappings,
                        "validation_required": context.require_validation,
                        # RICH METADATA: Strategy selection
                        "strategy_selection": {
                            "chosen_strategy": context.strategy.value,
                            "selection_rationale": "Best fit for domain characteristics and available knowledge",
                            "alternative_strategies": ["transfer_learning", "direct_analogy", "compositional"],
                            "confidence_in_choice": 0.9
                        }
                    }

                    # Store with full rich metadata
                    await memory_agent.store_memory(
                        memory_type=MemoryType.SEMANTIC,
                        content=f"Cross-domain reasoning: {len(result.new_insights)} insights, {len(result.generated_mappings)} mappings",
                        importance_score=result.confidence,
                        confidence_score=result.confidence,
                        tags=["cross_domain_reasoning", context.source_domain_id, context.target_domain_id, context.strategy.value],
                        thinking_state=thinking_state,
                        decision_factors=decision_factors,
                        reasoning_trace=[str(step) for step in result.reasoning_steps],
                        emotional_context={"reasoning_confidence": result.confidence}
                    )
                except Exception as e:
                    logger.warning(f"Failed to store cross-domain reasoning to memory: {e}")

            return result
            
        except Exception as e:
            logger.error(f"Reasoning failed: {e}")
            return ReasoningResult(
                reasoning_id=cache_key,
                source_domain_id=context.source_domain_id,
                target_domain_id=context.target_domain_id,
                strategy=context.strategy,
                success=False,
                confidence=0.0,
                new_insights=[f"Reasoning error: {str(e)}"]
            )
    
    async def _analogical_reasoning(self, context: ReasoningContext) -> ReasoningResult:
        """Perform analogical reasoning between domains"""
        result = ReasoningResult(
            reasoning_id=self._generate_cache_key(context),
            source_domain_id=context.source_domain_id,
            target_domain_id=context.target_domain_id,
            strategy=context.strategy,
            success=False,
            confidence=0.0
        )
        
        # Get domains
        source_domain = await self.domain_registry.get_domain(context.source_domain_id)
        target_domain = await self.domain_registry.get_domain(context.target_domain_id)
        
        if not source_domain or not target_domain:
            return result
        
        # Find structural similarities
        structural_mappings = await self._find_structural_similarities(source_domain, target_domain)
        result.reasoning_steps.append({
            "step": "structural_analysis",
            "mappings_found": len(structural_mappings)
        })
        
        # Generate analogical mappings
        analogical_mappings = []
        for struct_mapping in structural_mappings:
            # Create cross-domain mapping
            mapping = CrossDomainMapping(
                mapping_id="",
                source_domain_id=context.source_domain_id,
                target_domain_id=context.target_domain_id,
                source_concept_id=struct_mapping["source_concept"],
                target_concept_id=struct_mapping["target_concept"],
                mapping_type="analogical",
                strength=struct_mapping["similarity"],
                confidence=struct_mapping["similarity"] * 0.8
            )
            analogical_mappings.append(mapping)
        
        result.generated_mappings = analogical_mappings[:context.max_mappings]
        
        # Generate insights based on analogies
        insights = await self._generate_analogical_insights(analogical_mappings, source_domain, target_domain)
        result.new_insights = insights
        
        # Calculate overall confidence
        if analogical_mappings:
            avg_confidence = sum(m.confidence for m in analogical_mappings) / len(analogical_mappings)
            result.confidence = avg_confidence
            result.success = avg_confidence >= context.confidence_threshold
        
        return result
    
    async def _structural_reasoning(self, context: ReasoningContext) -> ReasoningResult:
        """Perform structural reasoning based on domain organization"""
        result = ReasoningResult(
            reasoning_id=self._generate_cache_key(context),
            source_domain_id=context.source_domain_id,
            target_domain_id=context.target_domain_id,
            strategy=context.strategy,
            success=False,
            confidence=0.0
        )
        
        # Get domains
        source_domain = await self.domain_registry.get_domain(context.source_domain_id)
        target_domain = await self.domain_registry.get_domain(context.target_domain_id)
        
        if not source_domain or not target_domain:
            return result
        
        # Analyze structural patterns
        source_structure = await self._analyze_domain_structure(source_domain)
        target_structure = await self._analyze_domain_structure(target_domain)
        
        result.reasoning_steps.append({
            "step": "structure_analysis",
            "source_patterns": len(source_structure["patterns"]),
            "target_patterns": len(target_structure["patterns"])
        })
        
        # Find structural correspondences
        structural_correspondences = await self._find_structural_correspondences(
            source_structure, target_structure, source_domain, target_domain
        )
        
        # Generate structural mappings
        structural_mappings = []
        for correspondence in structural_correspondences:
            mapping = CrossDomainMapping(
                mapping_id="",
                source_domain_id=context.source_domain_id,
                target_domain_id=context.target_domain_id,
                source_concept_id=correspondence["source_concept"],
                target_concept_id=correspondence["target_concept"],
                mapping_type="structural",
                strength=correspondence["structural_similarity"],
                confidence=correspondence["structural_similarity"]
            )
            structural_mappings.append(mapping)
        
        result.generated_mappings = structural_mappings[:context.max_mappings]
        
        # Generate structural insights
        if structural_mappings:
            result.new_insights = [
                f"Structural correspondence found: {len(structural_mappings)} mappings",
                f"Common organizational patterns detected",
                f"Structural similarity score: {sum(m.strength for m in structural_mappings) / len(structural_mappings):.2f}"
            ]
            
            result.confidence = sum(m.confidence for m in structural_mappings) / len(structural_mappings)
            result.success = result.confidence >= context.confidence_threshold
        
        return result
    
    async def _functional_reasoning(self, context: ReasoningContext) -> ReasoningResult:
        """Perform functional reasoning based on purpose and role"""
        result = ReasoningResult(
            reasoning_id=self._generate_cache_key(context),
            source_domain_id=context.source_domain_id,
            target_domain_id=context.target_domain_id,
            strategy=context.strategy,
            success=False,
            confidence=0.0
        )
        
        # Get domains
        source_domain = await self.domain_registry.get_domain(context.source_domain_id)
        target_domain = await self.domain_registry.get_domain(context.target_domain_id)
        
        if not source_domain or not target_domain:
            return result
        
        # Analyze functional roles
        source_functions = await self._extract_functional_roles(source_domain)
        target_functions = await self._extract_functional_roles(target_domain)
        
        result.reasoning_steps.append({
            "step": "functional_analysis",
            "source_functions": len(source_functions),
            "target_functions": len(target_functions)
        })
        
        # Find functional correspondences
        functional_mappings = []
        for source_func in source_functions:
            for target_func in target_functions:
                functional_similarity = await self._calculate_functional_similarity(
                    source_func, target_func
                )
                
                if functional_similarity >= context.confidence_threshold:
                    mapping = CrossDomainMapping(
                        mapping_id="",
                        source_domain_id=context.source_domain_id,
                        target_domain_id=context.target_domain_id,
                        source_concept_id=source_func["concept_id"],
                        target_concept_id=target_func["concept_id"],
                        mapping_type="functional",
                        strength=functional_similarity,
                        confidence=functional_similarity
                    )
                    functional_mappings.append(mapping)
        
        result.generated_mappings = functional_mappings[:context.max_mappings]
        
        # Generate functional insights
        if functional_mappings:
            result.new_insights = [
                f"Functional equivalences found: {len(functional_mappings)} mappings",
                "Similar functional roles across domains",
                "Potential for functional knowledge transfer"
            ]
            
            result.confidence = sum(m.confidence for m in functional_mappings) / len(functional_mappings)
            result.success = result.confidence >= context.confidence_threshold
        
        return result
    
    async def _causal_reasoning(self, context: ReasoningContext) -> ReasoningResult:
        """Perform causal reasoning based on cause-effect relationships"""
        result = ReasoningResult(
            reasoning_id=self._generate_cache_key(context),
            source_domain_id=context.source_domain_id,
            target_domain_id=context.target_domain_id,
            strategy=context.strategy,
            success=False,
            confidence=0.0
        )
        
        # Get domains
        source_domain = await self.domain_registry.get_domain(context.source_domain_id)
        target_domain = await self.domain_registry.get_domain(context.target_domain_id)
        
        if not source_domain or not target_domain:
            return result
        
        # Extract causal patterns
        source_causal = await self._extract_causal_patterns(source_domain)
        target_causal = await self._extract_causal_patterns(target_domain)
        
        result.reasoning_steps.append({
            "step": "causal_analysis",
            "source_patterns": len(source_causal),
            "target_patterns": len(target_causal)
        })
        
        # Find causal correspondences
        causal_mappings = []
        for source_pattern in source_causal:
            for target_pattern in target_causal:
                causal_similarity = await self._calculate_causal_similarity(
                    source_pattern, target_pattern,
                    source_domain, target_domain,
                )
                
                if causal_similarity >= context.confidence_threshold:
                    mapping = CrossDomainMapping(
                        mapping_id="",
                        source_domain_id=context.source_domain_id,
                        target_domain_id=context.target_domain_id,
                        source_concept_id=source_pattern["effect_concept"],
                        target_concept_id=target_pattern["effect_concept"],
                        mapping_type="causal",
                        strength=causal_similarity,
                        confidence=causal_similarity
                    )
                    causal_mappings.append(mapping)
        
        result.generated_mappings = causal_mappings[:context.max_mappings]
        
        # Generate causal insights
        if causal_mappings:
            result.new_insights = [
                f"Causal patterns found: {len(causal_mappings)} correspondences",
                "Similar cause-effect relationships across domains",
                "Potential for predictive transfer"
            ]
            
            result.confidence = sum(m.confidence for m in causal_mappings) / len(causal_mappings)
            result.success = result.confidence >= context.confidence_threshold
        
        return result
    
    async def _pattern_based_reasoning(self, context: ReasoningContext) -> ReasoningResult:
        """Perform pattern-based reasoning using universal patterns"""
        result = ReasoningResult(
            reasoning_id=self._generate_cache_key(context),
            source_domain_id=context.source_domain_id,
            target_domain_id=context.target_domain_id,
            strategy=context.strategy,
            success=False,
            confidence=0.0
        )
        
        # Get domains
        source_domain = await self.domain_registry.get_domain(context.source_domain_id)
        target_domain = await self.domain_registry.get_domain(context.target_domain_id)
        
        if not source_domain or not target_domain:
            return result
        
        # Analyze domains for universal patterns
        source_analysis = await self.universal_ontology.analyze_domain_concepts(source_domain)
        target_analysis = await self.universal_ontology.analyze_domain_concepts(target_domain)
        
        result.reasoning_steps.append({
            "step": "pattern_analysis",
            "source_patterns": len(source_analysis["identified_patterns"]),
            "target_patterns": len(target_analysis["identified_patterns"])
        })
        
        # Find common patterns
        source_patterns = {p["pattern_name"] for p in source_analysis["identified_patterns"]}
        target_patterns = {p["pattern_name"] for p in target_analysis["identified_patterns"]}
        common_patterns = source_patterns & target_patterns
        
        # Generate pattern-based mappings
        pattern_mappings = []
        for pattern_name in common_patterns:
            # Find pattern manifestations in both domains
            source_pattern = next(p for p in source_analysis["identified_patterns"] 
                                if p["pattern_name"] == pattern_name)
            target_pattern = next(p for p in target_analysis["identified_patterns"] 
                                if p["pattern_name"] == pattern_name)
            
            # Create mappings based on pattern correspondence
            pattern_similarity = min(source_pattern["confidence"], target_pattern["confidence"])
            
            if pattern_similarity >= context.confidence_threshold:
                mapping = CrossDomainMapping(
                    mapping_id="",
                    source_domain_id=context.source_domain_id,
                    target_domain_id=context.target_domain_id,
                    source_concept_id=f"pattern_{pattern_name}_source",
                    target_concept_id=f"pattern_{pattern_name}_target",
                    mapping_type="pattern_based",
                    strength=pattern_similarity,
                    confidence=pattern_similarity
                )
                pattern_mappings.append(mapping)
        
        result.generated_mappings = pattern_mappings
        
        # Generate pattern insights
        if common_patterns:
            result.new_insights = [
                f"Common universal patterns: {', '.join(common_patterns)}",
                f"Pattern-based correspondences: {len(pattern_mappings)}",
                "Shared organizational principles detected"
            ]
            
            if pattern_mappings:
                result.confidence = sum(m.confidence for m in pattern_mappings) / len(pattern_mappings)
                result.success = result.confidence >= context.confidence_threshold
            else:
                result.confidence = 0.5
                result.success = True  # Found patterns even without mappings
        
        return result
    
    async def _abstraction_reasoning(self, context: ReasoningContext) -> ReasoningResult:
        """Perform abstraction-based reasoning using universal concepts"""
        result = ReasoningResult(
            reasoning_id=self._generate_cache_key(context),
            source_domain_id=context.source_domain_id,
            target_domain_id=context.target_domain_id,
            strategy=context.strategy,
            success=False,
            confidence=0.0
        )
        
        # Get domains
        source_domain = await self.domain_registry.get_domain(context.source_domain_id)
        target_domain = await self.domain_registry.get_domain(context.target_domain_id)
        
        if not source_domain or not target_domain:
            return result
        
        # Analyze for universal concept mappings
        source_analysis = await self.universal_ontology.analyze_domain_concepts(source_domain)
        target_analysis = await self.universal_ontology.analyze_domain_concepts(target_domain)
        
        # Find shared universal concepts
        source_universals = {m["universal_concept"] for m in source_analysis["universal_mappings"]}
        target_universals = {m["universal_concept"] for m in target_analysis["universal_mappings"]}
        shared_universals = source_universals & target_universals
        
        result.reasoning_steps.append({
            "step": "abstraction_analysis",
            "shared_universals": len(shared_universals)
        })
        
        # Generate abstraction-based mappings
        abstraction_mappings = []
        for universal_id in shared_universals:
            # Find domain concepts mapped to this universal concept
            source_mapping = next(m for m in source_analysis["universal_mappings"] 
                                if m["universal_concept"] == universal_id)
            target_mapping = next(m for m in target_analysis["universal_mappings"] 
                                if m["universal_concept"] == universal_id)
            
            mapping = CrossDomainMapping(
                mapping_id="",
                source_domain_id=context.source_domain_id,
                target_domain_id=context.target_domain_id,
                source_concept_id=source_mapping["domain_concept"],
                target_concept_id=target_mapping["domain_concept"],
                mapping_type="abstraction",
                strength=min(source_mapping["similarity_score"], target_mapping["similarity_score"]),
                confidence=min(source_mapping["confidence"], target_mapping["confidence"])
            )
            abstraction_mappings.append(mapping)
        
        result.generated_mappings = abstraction_mappings[:context.max_mappings]
        
        # Generate abstraction insights
        if shared_universals:
            result.new_insights = [
                f"Shared universal abstractions: {len(shared_universals)}",
                f"Abstraction-based mappings: {len(abstraction_mappings)}",
                "Common abstract principles identified"
            ]
            
            if abstraction_mappings:
                result.confidence = sum(m.confidence for m in abstraction_mappings) / len(abstraction_mappings)
                result.success = result.confidence >= context.confidence_threshold
        
        return result
    
    async def _compositional_reasoning(self, context: ReasoningContext) -> ReasoningResult:
        """Perform compositional reasoning based on part-whole relationships"""
        result = ReasoningResult(
            reasoning_id=self._generate_cache_key(context),
            source_domain_id=context.source_domain_id,
            target_domain_id=context.target_domain_id,
            strategy=context.strategy,
            success=False,
            confidence=0.0
        )
        
        # Get domains
        source_domain = await self.domain_registry.get_domain(context.source_domain_id)
        target_domain = await self.domain_registry.get_domain(context.target_domain_id)
        
        if not source_domain or not target_domain:
            return result
        
        # Extract compositional structures
        source_compositions = await self._extract_compositional_structures(source_domain)
        target_compositions = await self._extract_compositional_structures(target_domain)
        
        result.reasoning_steps.append({
            "step": "compositional_analysis",
            "source_compositions": len(source_compositions),
            "target_compositions": len(target_compositions)
        })
        
        # Find compositional correspondences
        compositional_mappings = []
        for source_comp in source_compositions:
            for target_comp in target_compositions:
                comp_similarity = await self._calculate_compositional_similarity(
                    source_comp, target_comp,
                    source_domain, target_domain,
                )
                
                if comp_similarity >= context.confidence_threshold:
                    mapping = CrossDomainMapping(
                        mapping_id="",
                        source_domain_id=context.source_domain_id,
                        target_domain_id=context.target_domain_id,
                        source_concept_id=source_comp["whole_concept"],
                        target_concept_id=target_comp["whole_concept"],
                        mapping_type="compositional",
                        strength=comp_similarity,
                        confidence=comp_similarity
                    )
                    compositional_mappings.append(mapping)
        
        result.generated_mappings = compositional_mappings[:context.max_mappings]
        
        # Generate compositional insights
        if compositional_mappings:
            result.new_insights = [
                f"Compositional structures found: {len(compositional_mappings)} correspondences",
                "Similar part-whole organizations",
                "Potential for hierarchical knowledge transfer"
            ]
            
            result.confidence = sum(m.confidence for m in compositional_mappings) / len(compositional_mappings)
            result.success = result.confidence >= context.confidence_threshold
        
        return result
    
    # Helper methods for reasoning strategies
    
    async def _find_structural_similarities(self, source_domain: Domain, 
                                          target_domain: Domain) -> List[Dict[str, Any]]:
        """Find structural similarities between domains"""
        similarities = []
        
        for source_concept in source_domain.concepts.values():
            for target_concept in target_domain.concepts.values():
                similarity = calculate_concept_similarity(source_concept, target_concept)
                
                if similarity > 0.5:  # Threshold for structural similarity
                    similarities.append({
                        "source_concept": source_concept.concept_id,
                        "target_concept": target_concept.concept_id,
                        "similarity": similarity,
                        "basis": "structural"
                    })
        
        return similarities
    
    async def _analyze_domain_structure(self, domain: Domain) -> Dict[str, Any]:
        """Analyze the structural patterns in a domain"""
        structure = {
            "patterns": [],
            "hierarchies": [],
            "clusters": [],
            "connectivity": {}
        }
        
        # Analyze hierarchical patterns
        for relation in domain.relations.values():
            if relation.relation_type in ["is_a", "part_of"]:
                structure["hierarchies"].append({
                    "parent": relation.source_concept_id,
                    "child": relation.target_concept_id,
                    "type": relation.relation_type
                })
        
        # Analyze concept connectivity
        concept_connections = {}
        for concept_id in domain.concepts.keys():
            connections = len([r for r in domain.relations.values() 
                             if r.source_concept_id == concept_id or r.target_concept_id == concept_id])
            concept_connections[concept_id] = connections
        
        structure["connectivity"] = concept_connections
        
        return structure
    
    def _concept_similarity(
        self, domain_a: "Domain", id_a: str, domain_b: "Domain", id_b: str
    ) -> float:
        """Semantic similarity between two concepts, resolved from their domains.

        Returns 0.0 when either concept cannot be resolved -- an unresolvable
        concept is NOT evidence of similarity.
        """
        from core.domain.domain_types import calculate_concept_similarity

        c_a = (domain_a.concepts or {}).get(id_a)
        c_b = (domain_b.concepts or {}).get(id_b)
        if c_a is None or c_b is None:
            return 0.0
        try:
            return float(calculate_concept_similarity(c_a, c_b))
        except Exception as e:
            logger.debug(f"concept similarity failed for {id_a}/{id_b}: {e}")
            return 0.0

    async def _find_structural_correspondences(self, source_structure: Dict[str, Any],
                                             target_structure: Dict[str, Any],
                                             source_domain: Domain,
                                             target_domain: Domain) -> List[Dict[str, Any]]:
        """Find structural correspondences between domain structures"""
        correspondences = []
        
        # Compare hierarchical patterns
        source_hierarchies = source_structure["hierarchies"]
        target_hierarchies = target_structure["hierarchies"]
        
        for source_hier in source_hierarchies:
            for target_hier in target_hierarchies:
                if source_hier["type"] == target_hier["type"]:
                    # Matching relation TYPE only says the shapes agree. It says
                    # nothing about whether the concepts are related, so it can
                    # only be a weighting term -- never the score.
                    #
                    # This emitted a hardcoded 0.7 and never read source_domain
                    # or target_domain at all, so N x M same-typed relations all
                    # passed the 0.5 threshold regardless of content: two
                    # entirely unrelated domains scored 0.700 with maps=1.
                    parent_sim = self._concept_similarity(
                        source_domain, source_hier["parent"],
                        target_domain, target_hier["parent"],
                    )
                    child_sim = self._concept_similarity(
                        source_domain, source_hier.get("child", ""),
                        target_domain, target_hier.get("child", ""),
                    )
                    semantic = max(parent_sim, (parent_sim + child_sim) / 2.0)
                    similarity = 0.2 + 0.8 * semantic   # type match worth 0.2
                    if semantic <= 0.0:
                        continue                        # unrelated: emit nothing
                    correspondences.append({
                        "source_concept": source_hier["parent"],
                        "target_concept": target_hier["parent"],
                        "structural_similarity": round(similarity, 4),
                        "parent_similarity": round(parent_sim, 4),
                        "child_similarity": round(child_sim, 4),
                        "basis": "hierarchical_pattern"
                    })
        
        return correspondences
    
    async def _extract_functional_roles(self, domain: Domain) -> List[Dict[str, Any]]:
        """Extract functional roles from domain concepts"""
        functional_roles = []
        
        for concept in domain.concepts.values():
            # Analyze concept properties for functional indicators
            functional_properties = []
            for prop_key, prop_value in concept.properties.items():
                if any(keyword in prop_key.lower() for keyword in ["function", "role", "purpose", "goal"]):
                    functional_properties.append(prop_value)
            
            if functional_properties:
                functional_roles.append({
                    "concept_id": concept.concept_id,
                    "name": concept.name,
                    "functions": functional_properties,
                    "type": concept.concept_type
                })
        
        return functional_roles
    
    async def _calculate_functional_similarity(self, func1: Dict[str, Any], 
                                             func2: Dict[str, Any]) -> float:
        """Calculate functional similarity between two functional roles"""
        # Simple function similarity based on overlap
        funcs1 = set(str(f).lower() for f in func1["functions"])
        funcs2 = set(str(f).lower() for f in func2["functions"])
        
        if not funcs1 or not funcs2:
            return 0.0
        
        overlap = len(funcs1 & funcs2)
        total = len(funcs1 | funcs2)
        
        return overlap / total if total > 0 else 0.0
    
    async def _extract_causal_patterns(self, domain: Domain) -> List[Dict[str, Any]]:
        """Extract causal patterns from domain"""
        causal_patterns = []
        
        for relation in domain.relations.values():
            if relation.relation_type in ["causes", "enables", "leads_to", "results_in"]:
                causal_patterns.append({
                    "cause_concept": relation.source_concept_id,
                    "effect_concept": relation.target_concept_id,
                    "causal_type": relation.relation_type,
                    "strength": relation.strength
                })
        
        return causal_patterns
    
    async def _calculate_causal_similarity(
        self, pattern1: Dict[str, Any], pattern2: Dict[str, Any],
        source_domain: "Domain" = None, target_domain: "Domain" = None,
    ) -> float:
        """Similarity between causal patterns, grounded in the concepts related.

        Previously this compared only the relation-type string and the edge
        strength, never cause_concept or effect_concept. Two mismatched types at
        equal strength floored at (0.5 + 1.0)/2 = 0.75 -- above the 0.5
        threshold -- so the type check could never reject anything, and
        arbitrary edges of equal strength read as causal analogies.
        """
        type_match = 1.0 if pattern1["causal_type"] == pattern2["causal_type"] else 0.5
        strength_similarity = 1.0 - abs(pattern1["strength"] - pattern2["strength"])
        structural = (type_match + strength_similarity) / 2.0

        if source_domain is None or target_domain is None:
            # Cannot ground it -> not evidence of an analogy.
            return 0.0

        cause_sim = self._concept_similarity(
            source_domain, pattern1.get("cause_concept", ""),
            target_domain, pattern2.get("cause_concept", ""),
        )
        effect_sim = self._concept_similarity(
            source_domain, pattern1.get("effect_concept", ""),
            target_domain, pattern2.get("effect_concept", ""),
        )
        semantic = (cause_sim + effect_sim) / 2.0
        # Structural agreement WEIGHTS semantic correspondence; it cannot
        # substitute for it. Unrelated concepts -> 0.0 regardless of shape.
        return round(structural * semantic, 4)
    
    async def _extract_compositional_structures(self, domain: Domain) -> List[Dict[str, Any]]:
        """Extract compositional structures from domain"""
        compositions = []
        
        for relation in domain.relations.values():
            if relation.relation_type in ["part_of", "contains", "composed_of"]:
                compositions.append({
                    "whole_concept": relation.target_concept_id,
                    "part_concept": relation.source_concept_id,
                    "composition_type": relation.relation_type
                })
        
        return compositions
    
    async def _calculate_compositional_similarity(
        self, comp1: Dict[str, Any], comp2: Dict[str, Any],
        source_domain: "Domain" = None, target_domain: "Domain" = None,
    ) -> float:
        """Similarity between compositional structures, grounded in concepts.

        This returned 1.0 whenever two composition_type STRINGS matched and
        never read whole_concept or part_concept. Verified: two entirely
        unrelated domains (alpha part_of beta vs zeta part_of omega) scored
        confidence 1.000 -- and because reason_across_domains stores anything
        above 0.4, that fabrication was written to semantic memory as
        impact 'critical', status 'verified'.
        """
        type_match = 1.0 if comp1["composition_type"] == comp2["composition_type"] else 0.7

        if source_domain is None or target_domain is None:
            return 0.0

        whole_sim = self._concept_similarity(
            source_domain, comp1.get("whole_concept", ""),
            target_domain, comp2.get("whole_concept", ""),
        )
        part_sim = self._concept_similarity(
            source_domain, comp1.get("part_concept", ""),
            target_domain, comp2.get("part_concept", ""),
        )
        semantic = (whole_sim + part_sim) / 2.0
        return round(type_match * semantic, 4)
    
    async def _generate_analogical_insights(self, mappings: List[CrossDomainMapping],
                                          source_domain: Domain,
                                          target_domain: Domain) -> List[str]:
        """Generate insights from analogical mappings"""
        insights = []

        # Handle empty mappings
        if not mappings:
            insights.append(f"No strong analogical mappings found between {source_domain.name} and {target_domain.name}")
            return insights

        if len(mappings) > 5:
            insights.append(f"Strong analogical correspondence: {len(mappings)} concept mappings found")

        # Analyze mapping types
        mapping_types = [m.mapping_type for m in mappings]
        if mapping_types:
            most_common_type = max(set(mapping_types), key=mapping_types.count)
            insights.append(f"Dominant mapping type: {most_common_type}")

        # Analyze confidence levels
        high_confidence_mappings = [m for m in mappings if m.confidence > 0.8]
        if high_confidence_mappings:
            insights.append(f"High confidence mappings: {len(high_confidence_mappings)}")

        return insights
    
    async def _validate_reasoning_result(self, result: ReasoningResult) -> None:
        """Validate the reasoning result"""
        # Simple validation - could be much more sophisticated
        validation_score = 0.0
        validation_details = {}
        
        # Validate mappings
        if result.generated_mappings:
            avg_confidence = sum(m.confidence for m in result.generated_mappings) / len(result.generated_mappings)
            validation_score += avg_confidence * 0.5
            validation_details["mapping_confidence"] = avg_confidence
        
        # Validate insights
        if result.new_insights:
            validation_score += 0.3  # Insights add to validation
            validation_details["insights_generated"] = len(result.new_insights)
        
        # Validate reasoning steps
        if result.reasoning_steps:
            validation_score += 0.2  # Traceable reasoning adds to validation
            validation_details["reasoning_steps"] = len(result.reasoning_steps)
        
        result.validation_score = min(validation_score, 1.0)
        result.validation_details = validation_details
    
    def _generate_cache_key(self, context: ReasoningContext) -> str:
        """Generate a cache key for reasoning context"""
        return f"{context.source_domain_id}_{context.target_domain_id}_{context.strategy.value}_{context.reasoning_goal}"
    
    async def get_reasoning_statistics(self) -> Dict[str, Any]:
        """Get statistics about reasoning operations"""
        total_reasoning = len(self.reasoning_cache)
        successful_reasoning = len([r for r in self.reasoning_cache.values() if r.success])
        
        strategy_usage = {}
        for result in self.reasoning_cache.values():
            strategy = result.strategy.value
            strategy_usage[strategy] = strategy_usage.get(strategy, 0) + 1
        
        return {
            "total_reasoning_operations": total_reasoning,
            "successful_operations": successful_reasoning,
            "success_rate": successful_reasoning / total_reasoning if total_reasoning > 0 else 0,
            "strategy_usage": strategy_usage,
            "average_confidence": sum(r.confidence for r in self.reasoning_cache.values()) / total_reasoning if total_reasoning > 0 else 0
        }


def _verification_status(context: "ReasoningContext", result: "ReasoningResult") -> str:
    """What was actually established about this result, in its own words.

    Deliberately avoids "verified". `validation_score` is computed from the
    result's OWN mapping confidences -- it is a self-consistency check, not an
    independent oracle, and naming it "verified" is what let a self-scored
    result be persisted as established fact.
    """
    if not getattr(context, "require_validation", False):
        return "unvalidated"
    score = getattr(result, "validation_score", None)
    if score is None:
        return "validation_did_not_run"
    return "self_consistent" if score >= 0.6 else "self_consistency_low"


# Backwards compatibility aliases
CrossDomainContext = ReasoningContext
MappingStrategy = ReasoningStrategy


# Singleton instance
_cross_domain_reasoner = None


def get_cross_domain_reasoner() -> CrossDomainReasoner:
    """Get global cross-domain reasoner instance (singleton)"""
    global _cross_domain_reasoner
    if _cross_domain_reasoner is None:
        from core.domain.domain_registry import get_domain_registry
        from core.domain.universal_ontology import get_universal_ontology

        domain_registry = get_domain_registry()
        universal_ontology = get_universal_ontology()
        _cross_domain_reasoner = CrossDomainReasoner(domain_registry, universal_ontology)
    return _cross_domain_reasoner