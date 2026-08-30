#!/usr/bin/env python3
"""
Memory Worthiness Metadata
===========================

Structured metadata for intelligent memory filtering.
Reasoning systems self-tag their outputs with rich metadata,
enabling O(1) deterministic filtering by MemoryAgent.

CRITICAL DESIGN PRINCIPLES:
1. Explicit namespacing prevents rule ambiguity
2. Enumerations ensure deterministic filtering
3. Temporal metadata enables timeline reconstruction
4. Action descriptors enable "what did I do?" queries
5. Justification metadata enables "why did I do it?" queries
6. Metadata is IMMUTABLE after write (append-only)
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Any, List, Optional
from datetime import datetime


# Enumerations for deterministic filtering
class DecisionType(Enum):
    """Type of decision made"""
    STRATEGIC = "strategic"  # Long-term planning, architecture
    TACTICAL = "tactical"  # Medium-term execution
    OPERATIONAL = "operational"  # Short-term tasks
    INFORMATIONAL = "informational"  # Pure information retrieval


class ConsequenceLevel(Enum):
    """Impact level if this knowledge is forgotten"""
    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class PatternType(Enum):
    """Type of reasoning pattern"""
    ROUTINE = "routine"  # Known pattern, simple application
    VARIANT = "variant"  # Known pattern with modifications
    EMERGENT = "emergent"  # New pattern discovered


class QueryType(Enum):
    """Type of query being answered"""
    FACTUAL_LOOKUP = "factual_lookup"  # "What is X?"
    SIMPLE_CALCULATION = "simple_calculation"  # "What is 2+2?"
    COMPLEX_REASONING = "complex_reasoning"  # Multi-step inference
    SYNTHESIS = "synthesis"  # Combining multiple sources
    ANALYSIS = "analysis"  # Deep examination
    CREATIVE = "creative"  # Novel generation


class ReusabilityLevel(Enum):
    """How reusable this knowledge is"""
    NONE = "none"  # One-time only
    LOW = "low"  # Rarely reusable
    MEDIUM = "medium"  # Occasionally reusable
    HIGH = "high"  # Frequently reusable


class DomainImportance(Enum):
    """Importance within domain"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


# Namespaced metadata structures

@dataclass
class CognitionMetadata:
    """Cognitive effort metrics - How hard did the system think?"""
    reasoning_steps: int = 0  # Number of reasoning steps
    reasoning_depth: int = 0  # Levels of nested inference
    execution_time_ms: float = 0.0  # Time spent reasoning
    inference_count: int = 0  # Total inferences made
    complexity_score: float = 0.0  # Self-assessed complexity (0.0-1.0)

    # Additional cognitive markers
    required_backtracking: bool = False  # Had to revise reasoning
    used_multiple_strategies: bool = False  # Tried different approaches
    uncertainty_resolved: bool = False  # Resolved ambiguity


@dataclass
class NoveltyMetadata:
    """Novelty indicators - Is this new knowledge?"""
    is_novel: bool = False  # New pattern vs known fact
    contradicts_existing: bool = False  # Conflicts with prior knowledge
    synthesis_of_domains: List[str] = field(default_factory=list)  # Cross-domain reasoning
    pattern_type: PatternType = PatternType.ROUTINE

    # Discovery markers
    first_occurrence: bool = False  # First time seeing this
    connects_disparate_knowledge: bool = False  # Bridges gaps


@dataclass
class CriticalityMetadata:
    """Criticality markers - Will this be needed again?"""
    decision_type: DecisionType = DecisionType.INFORMATIONAL
    domain_importance: DomainImportance = DomainImportance.MEDIUM
    reusability: ReusabilityLevel = ReusabilityLevel.MEDIUM
    consequence_level: ConsequenceLevel = ConsequenceLevel.MEDIUM

    # Usage prediction
    likely_reference_count: int = 0  # Expected future uses
    time_sensitivity: bool = False  # Will become stale quickly


@dataclass
class QueryMetadata:
    """Query classification - What kind of question?"""
    query_type: QueryType = QueryType.FACTUAL_LOOKUP
    requires_synthesis: bool = False
    multi_step: bool = False
    involves_uncertainty: bool = False

    # Query characteristics
    ambiguous_input: bool = False  # Input was unclear
    context_dependent: bool = False  # Answer depends on context


@dataclass
class OutcomeMetadata:
    """Outcome characteristics - What was produced?"""
    conclusion_confidence: float = 1.0  # Confidence in conclusion (0.0-1.0)
    hypothesis_supported: Optional[bool] = None  # For hypothesis testing
    actionable: bool = False  # Leads to action
    created_new_knowledge: bool = False  # Generated novel insight

    # Explicit action descriptors (CRITICAL - enables "what did I do?" queries)
    action_type: Optional[str] = None  # "architectural_decision", "hypothesis_test", "pattern_discovery", etc.
    action_summary: str = ""  # Human-readable summary of what was done
    affected_components: List[str] = field(default_factory=list)  # What systems were impacted

    # Quality markers
    validated_against_sources: bool = False
    requires_human_review: bool = False


@dataclass
class TemporalMetadata:
    """Temporal context - When and why did this happen? (CRITICAL for timeline reconstruction)"""
    created_at: str = ""  # ISO 8601 timestamp (immutable)
    session_id: str = ""  # Session identifier for temporal grouping
    trigger_event: str = ""  # What caused this memory: "user_query", "autonomous_reasoning", "hypothesis_test"
    sequence_number: int = 0  # Order within session for causal reconstruction


@dataclass
class JustificationMetadata:
    """Rationale - Why was this stored? (CRITICAL - enables "why did I do it?" queries)"""
    store_reason: List[str] = field(default_factory=list)  # Rules that matched: ["multi_level_inference", "strategic_decision"]
    decision_summary: str = ""  # Why this memory is valuable
    alternatives_considered: List[str] = field(default_factory=list)  # Other approaches considered
    rejected_because: List[str] = field(default_factory=list)  # Why alternatives were rejected


@dataclass
class MemoryWorthinessMetadata:
    """
    Comprehensive metadata for memory filtering decisions.

    Structured with explicit namespacing to prevent rule ambiguity.
    All fields use enumerations for deterministic filtering.

    CRITICAL ARCHITECTURAL INVARIANT:
    - This metadata is IMMUTABLE after write
    - No retroactive reinterpretation allowed
    - Corrections must be new memories, not edits
    - Ensures recall is historical, not revisionist
    """
    # Namespaced metadata
    cognition: CognitionMetadata = field(default_factory=CognitionMetadata)
    novelty: NoveltyMetadata = field(default_factory=NoveltyMetadata)
    criticality: CriticalityMetadata = field(default_factory=CriticalityMetadata)
    query: QueryMetadata = field(default_factory=QueryMetadata)
    outcome: OutcomeMetadata = field(default_factory=OutcomeMetadata)

    # Temporal and rationale (CRITICAL for recall)
    temporal: TemporalMetadata = field(default_factory=TemporalMetadata)
    justification: JustificationMetadata = field(default_factory=JustificationMetadata)

    # System metadata (non-scored)
    source_system: str = "unknown"  # Which system generated this
    domain: str = "general"  # Primary domain

    # IMMUTABILITY MARKER
    frozen_at_write: bool = False  # Set to True after first write, prevents modification

    def freeze(self):
        """Mark metadata as immutable - called after first write"""
        object.__setattr__(self, 'frozen_at_write', True)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage (IMMUTABLE after write)"""
        return {
            "cognition": {
                "reasoning_steps": self.cognition.reasoning_steps,
                "reasoning_depth": self.cognition.reasoning_depth,
                "execution_time_ms": self.cognition.execution_time_ms,
                "inference_count": self.cognition.inference_count,
                "complexity_score": self.cognition.complexity_score,
                "required_backtracking": self.cognition.required_backtracking,
                "used_multiple_strategies": self.cognition.used_multiple_strategies,
                "uncertainty_resolved": self.cognition.uncertainty_resolved
            },
            "novelty": {
                "is_novel": self.novelty.is_novel,
                "contradicts_existing": self.novelty.contradicts_existing,
                "synthesis_of_domains": self.novelty.synthesis_of_domains,
                "pattern_type": self.novelty.pattern_type.value,
                "first_occurrence": self.novelty.first_occurrence,
                "connects_disparate_knowledge": self.novelty.connects_disparate_knowledge
            },
            "criticality": {
                "decision_type": self.criticality.decision_type.value,
                "domain_importance": self.criticality.domain_importance.value,
                "reusability": self.criticality.reusability.value,
                "consequence_level": self.criticality.consequence_level.value,
                "likely_reference_count": self.criticality.likely_reference_count,
                "time_sensitivity": self.criticality.time_sensitivity
            },
            "query": {
                "query_type": self.query.query_type.value,
                "requires_synthesis": self.query.requires_synthesis,
                "multi_step": self.query.multi_step,
                "involves_uncertainty": self.query.involves_uncertainty,
                "ambiguous_input": self.query.ambiguous_input,
                "context_dependent": self.query.context_dependent
            },
            "outcome": {
                "conclusion_confidence": self.outcome.conclusion_confidence,
                "hypothesis_supported": self.outcome.hypothesis_supported,
                "actionable": self.outcome.actionable,
                "created_new_knowledge": self.outcome.created_new_knowledge,
                "action_type": self.outcome.action_type,
                "action_summary": self.outcome.action_summary,
                "affected_components": self.outcome.affected_components,
                "validated_against_sources": self.outcome.validated_against_sources,
                "requires_human_review": self.outcome.requires_human_review
            },
            "temporal": {
                "created_at": self.temporal.created_at,
                "session_id": self.temporal.session_id,
                "trigger_event": self.temporal.trigger_event,
                "sequence_number": self.temporal.sequence_number
            },
            "justification": {
                "store_reason": self.justification.store_reason,
                "decision_summary": self.justification.decision_summary,
                "alternatives_considered": self.justification.alternatives_considered,
                "rejected_because": self.justification.rejected_because
            },
            "source_system": self.source_system,
            "domain": self.domain,
            "frozen_at_write": self.frozen_at_write
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'MemoryWorthinessMetadata':
        """Create from dictionary (verify immutability)"""
        instance = cls(
            cognition=CognitionMetadata(**data.get("cognition", {})),
            novelty=NoveltyMetadata(
                is_novel=data.get("novelty", {}).get("is_novel", False),
                contradicts_existing=data.get("novelty", {}).get("contradicts_existing", False),
                synthesis_of_domains=data.get("novelty", {}).get("synthesis_of_domains", []),
                pattern_type=PatternType(data.get("novelty", {}).get("pattern_type", "routine")),
                first_occurrence=data.get("novelty", {}).get("first_occurrence", False),
                connects_disparate_knowledge=data.get("novelty", {}).get("connects_disparate_knowledge", False)
            ),
            criticality=CriticalityMetadata(
                decision_type=DecisionType(data.get("criticality", {}).get("decision_type", "informational")),
                domain_importance=DomainImportance(data.get("criticality", {}).get("domain_importance", "medium")),
                reusability=ReusabilityLevel(data.get("criticality", {}).get("reusability", "medium")),
                consequence_level=ConsequenceLevel(data.get("criticality", {}).get("consequence_level", "medium")),
                likely_reference_count=data.get("criticality", {}).get("likely_reference_count", 0),
                time_sensitivity=data.get("criticality", {}).get("time_sensitivity", False)
            ),
            query=QueryMetadata(
                query_type=QueryType(data.get("query", {}).get("query_type", "factual_lookup")),
                requires_synthesis=data.get("query", {}).get("requires_synthesis", False),
                multi_step=data.get("query", {}).get("multi_step", False),
                involves_uncertainty=data.get("query", {}).get("involves_uncertainty", False),
                ambiguous_input=data.get("query", {}).get("ambiguous_input", False),
                context_dependent=data.get("query", {}).get("context_dependent", False)
            ),
            outcome=OutcomeMetadata(**data.get("outcome", {})),
            temporal=TemporalMetadata(**data.get("temporal", {})),
            justification=JustificationMetadata(**data.get("justification", {})),
            source_system=data.get("source_system", "unknown"),
            domain=data.get("domain", "general"),
            frozen_at_write=data.get("frozen_at_write", False)
        )

        # Restore frozen state
        if instance.frozen_at_write:
            object.__setattr__(instance, 'frozen_at_write', True)

        return instance


# Convenience exports
__all__ = [
    "MemoryWorthinessMetadata",
    "CognitionMetadata",
    "NoveltyMetadata",
    "CriticalityMetadata",
    "QueryMetadata",
    "OutcomeMetadata",
    "TemporalMetadata",
    "JustificationMetadata",
    "DecisionType",
    "ConsequenceLevel",
    "PatternType",
    "QueryType",
    "ReusabilityLevel",
    "DomainImportance"
]
