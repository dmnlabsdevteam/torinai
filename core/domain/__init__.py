#!/usr/bin/env python3
"""
Universal Domain System
Core domain abstractions for cross-domain reasoning and knowledge integration
"""

from .domain_types import (
    Domain, DomainType, ConceptType, ConceptDimension,
    DomainKnowledge, DomainConcept, DomainRelation,
    CrossDomainMapping, KnowledgeTransfer
)
from .domain_registry import (
    DomainRegistry, UnknownDomain, UnresolvedDomainReference)
from .universal_ontology import UniversalOntology
from .cross_domain_reasoner import CrossDomainReasoner

__all__ = [
    'Domain', 'DomainType', 'ConceptType', 'ConceptDimension',
    'DomainKnowledge', 'DomainConcept', 'DomainRelation',
    'CrossDomainMapping', 'KnowledgeTransfer', 'UnknownDomain',
    'UnresolvedDomainReference',
    'DomainRegistry', 'UniversalOntology', 'CrossDomainReasoner'
]

from .concept_ingestion import (
    ConceptIngestionService, get_concept_ingestion_service,
    EvidenceEnvelope, EvidenceSourceType, ConceptExistence,
    ConceptCandidate, ConceptIdentity, IngestionResult, IngestionRefused,
)
