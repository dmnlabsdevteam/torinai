#!/usr/bin/env python3
"""
Analogy Discovery
======================================
Discover and reason about analogies between concepts

Purpose:
- Find structural analogies between concepts
- Map relationships across domains
- Generate novel insights through analogy
- Support analogical reasoning

Example Analogies:
- Atom is to molecule as cell is to organism (composition)
- Teacher is to student as doctor is to patient (relationship)
- Code is to program as DNA is to organism (blueprint)
"""

import asyncio
import json as _json
import logging
import os
import json
import importlib
from typing import Dict, Any, List, Optional, Tuple, Set, Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

logger = logging.getLogger(__name__)


class AnalogyType(Enum):
    """Types of analogies"""
    STRUCTURAL = "structural"  # Similar structure, e.g. atom:molecule
    FUNCTIONAL = "functional"  # Similar function, e.g. wing:propeller
    RELATIONAL = "relational"  # Similar relationships
    CAUSAL = "causal"  # Similar cause-effect
    PROCESS = "process"  # Similar processes
    ATTRIBUTE = "attribute"  # Similar attributes


class MappingType(Enum):
    """Types of conceptual mappings"""
    ONE_TO_ONE = "one_to_one"  # Single concept maps to single concept
    ONE_TO_MANY = "one_to_many"  # One concept maps to multiple
    MANY_TO_ONE = "many_to_one"  # Multiple map to one
    PARTIAL = "partial"  # Incomplete mapping
    APPROXIMATE = "approximate"  # Approximate mapping


@dataclass
class Concept:
    """Represents a concept in the analogy"""
    name: str
    domain: str
    description: str

    # Structural properties. attributes stays a list of names because the
    # similarity functions compare them as sets and as embedding text;
    # attribute_values keeps the value each name had, which _add_concept
    # previously discarded via list(attributes.keys()).
    attributes: List[str] = field(default_factory=list)
    attribute_values: Dict[str, str] = field(default_factory=dict)
    relationships: List[Tuple[str, str]] = field(default_factory=list)  # (relation_type, target_concept)

    # Functional properties
    functions: List[str] = field(default_factory=list)
    processes: List[str] = field(default_factory=list)

    # Context
    context: str = ""
    examples: List[str] = field(default_factory=list)


@dataclass
class ConceptMapping:
    """Mapping between two concepts"""
    source: Concept
    target: Concept
    mapping_type: MappingType

    # Similarity measures
    structural_similarity: float  # 0-1, how similar structures are
    functional_similarity: float  # 0-1, how similar functions are

    # Mappings
    attribute_mappings: Dict[str, str]  # source_attr -> target_attr
    relationship_mappings: Dict[str, str]  # source_rel -> target_rel

    # Confidence
    confidence: float = 0.0
    explanations: List[str] = field(default_factory=list)

    # Metadata
    discovered_at: datetime = field(default_factory=datetime.now)
    usage_count: int = 0


@dataclass
class Analogy:
    """Complete analogy between concept sets"""
    analogy_id: str
    analogy_type: AnalogyType
    source_domain: str
    target_domain: str

    # Core mappings
    mappings: List[ConceptMapping]  # A -> B mappings
    primary_mapping: Optional[ConceptMapping] = None  # Core A:B mapping

    # Analogy quality
    coherence: float = 0.0  # How well the analogy holds
    novelty: float = 0.0  # How novel/surprising the analogy is
    utility: float = 0.0  # How useful the analogy is

    # Explanation
    description: str = ""
    insights: List[str] = field(default_factory=list)

    # Metadata
    created_at: datetime = field(default_factory=datetime.now)
    score: float = 0.0


class AnalogyDiscovery:
    """
    Analogy Discovery System

    Purpose:
    - Discover analogies between concepts across domains
    - Map structural and functional similarities
    - Generate novel insights through analogical reasoning
    - Support creative problem-solving

    Usage:
        discovery = AnalogyDiscovery()
        await discovery.initialize()

        analogy = await discovery.find_analogy(
            source_concept="atom",
            target_domain="biology"
        )
    """

    def __init__(self, config: Dict[str, Any] = None):
        # Configuration (from environment or defaults)
        self.config = config or {}

        # Concept knowledge base (domain -> concept_name -> Concept)
        self.concepts: Dict[str, Dict[str, Concept]] = {}

        # Known analogies
        self.analogies: Dict[str, Analogy] = {}

        # Similarity thresholds
        self.similarity_threshold: Dict[str, float] = {
            'structural': 0.6,
            'functional': 0.5,
            'relational': 0.7,
            'attribute': 0.5
        }

        # Statistics
        self.stats = {
            'analogies_found': 0,
            'concepts_indexed': 0,
            'mappings_created': 0,
            'successful_transfers': 0,
            'failed_analogies': 0,
            'domains_covered': 0
        }

        # Attached by initialize(). Resolution cannot happen here: obtaining the
        # unified database is async, and the previous synchronous attempt
        # searched for core.database.postgresql_manager / database.
        # postgresql_manager -- neither of which exists -- so self.db was always
        # None and every write was skipped by the `if not self.db` guards.
        self.db = None

        # Seed concepts and schema are loaded by initialize() rather than here.
        # __init__ cannot do that work: the previous version called
        # asyncio.run() from a constructor, which raises RuntimeError whenever
        # an event loop is already running, and handed raw SQL strings to
        # asyncio.create_task(), which accepts only coroutines. It also called
        # self._async_load_concepts(), a method that was never defined.
        self._initialized = False

    async def _resolve_database(self) -> Optional[Any]:
        """Attach the unified database used by the rest of the system.

        This replaces a search for core.database.postgresql_manager /
        database.postgresql_manager, modules that do not exist in this
        codebase. The lookup always failed, so persistence was disabled in
        every production run while the in-memory concept base still populated
        and made the system look healthy.
        """
        try:
            from core.database.unified_database_postgres import get_unified_database

            database = await get_unified_database()
            if not getattr(database, "initialized", False):
                await database.initialize()
            return database
        except Exception as e:
            logger.warning(
                f"Analogy persistence unavailable, running in-memory only: {e}"
            )
            return None

    #: Only the table this module owns. unified.concepts and
    #: unified.analogies are declared in data/system/postgres_schemas.sql --
    #: creating unqualified copies here produced a second, divergent set in the
    #: default schema while the declared tables stayed empty.
    _SCHEMA_STATEMENTS = (
        """
            CREATE TABLE IF NOT EXISTS unified.concept_mappings (
                mapping_id VARCHAR(255) PRIMARY KEY,
                source_concept VARCHAR(255),
                target_concept VARCHAR(255),
                mapping_type VARCHAR(50),
                structural_similarity FLOAT,
                functional_similarity FLOAT,
                confidence FLOAT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """,
    )

    async def initialize(self) -> bool:
        """Create the schema and load the seed concept base.

        Safe to call repeatedly; the work runs once.
        """
        if self._initialized:
            return True

        try:
            if self.db is None:
                self.db = await self._resolve_database()

            await self._create_tables()

            # Restore learned concepts. Without this the engine came up knowing
            # only its hardcoded samples, so anything it had previously learned
            # was durable in the store but absent from cognition -- persisted
            # without being available.
            restored = await self._load_concepts_from_store()

            if restored == 0:
                # An empty concept base is a real state and must read as one.
                logger.warning(
                    "Concept store is empty. Analogy discovery has nothing to "
                    "reason over; any 'no analogy found' result reflects absent "
                    "knowledge, not absent similarity."
                )
            self._initialized = True
            total = sum(len(concepts) for concepts in self.concepts.values())
            logger.info(
                f"Analogy discovery initialized: {total} concepts across "
                f"{len(self.concepts)} domains"
            )
            return True
        except Exception as e:
            logger.error(f"Analogy discovery initialization failed: {e}")
            return False

    async def _ensure_initialized(self) -> None:
        """Load the concept base on first use."""
        if not self._initialized:
            await self.initialize()

    async def _load_concepts_from_store(self) -> int:
        """Load persisted concepts into the in-memory knowledge base.

        Returns the number restored. Seeding runs afterwards and is an upsert,
        so restored concepts are not duplicated or overwritten by samples.
        """
        if not self.db:
            return 0

        try:
            rows = await self.db.execute_query(
                """
                SELECT concept_id, name, domain, description, attributes,
                       relationships, functions, processes, context, examples
                FROM unified.concepts
                """,
                fetch_all=True,
            )
        except Exception as e:
            logger.warning(f"Could not restore concepts from store: {e}")
            return 0

        def _decode(value, default):
            if value is None:
                return default
            if isinstance(value, (dict, list)):
                return value
            try:
                return _json.loads(value)
            except Exception:
                return default

        restored = 0
        for row in rows or []:
            try:
                relationships = [
                    tuple(item) if isinstance(item, (list, tuple)) else (str(item), "")
                    for item in _decode(row["relationships"], [])
                ]
                # The column holds the full value map; the in-memory view keeps
                # attributes as the name list the similarity functions expect.
                stored_attributes = _decode(row["attributes"], [])
                if isinstance(stored_attributes, dict):
                    attribute_names = list(stored_attributes.keys())
                    attribute_values = stored_attributes
                else:
                    attribute_names = list(stored_attributes)
                    attribute_values = {}

                concept = Concept(
                    name=row["name"],
                    domain=row["domain"],
                    description=row["description"] or "",
                    attributes=attribute_names,
                    attribute_values=attribute_values,
                    relationships=relationships,
                    functions=_decode(row["functions"], []),
                    processes=_decode(row["processes"], []),
                    context=row["context"] or "",
                    examples=_decode(row["examples"], []),
                )
                self.concepts.setdefault(concept.domain, {})[concept.name] = concept
                restored += 1
            except Exception as row_error:
                logger.debug(f"Skipping malformed concept row: {row_error}")

        if restored:
            self.stats['concepts_indexed'] += restored
            logger.info(f"Analogy discovery: restored {restored} concept(s) from store")

        return restored

    async def _create_tables(self):
        """Create the backing tables when a database is configured.

        Previously a bare `pass`, so the tables the persistence methods write
        to were never created.
        """
        if not self.db:
            logger.debug("No database configured; analogy persistence is disabled")
            return

        for statement in self._SCHEMA_STATEMENTS:
            try:
                await self.db.execute_query(statement)
            except Exception as e:
                logger.warning(f"Could not create analogy table: {e}")

    async def _add_concept(
        self,
        name: str,
        domain: str,
        description: str = "",
        attributes: Optional[Dict[str, str]] = None,
        relationships: Optional[List[Tuple[str, str]]] = None
    ) -> Concept:
        """Add a concept to the knowledge base"""
        concept = Concept(
            name=name,
            domain=domain,
            description=description,
            attributes=list(attributes.keys()) if attributes else [],
            attribute_values=dict(attributes) if attributes else {},
            relationships=relationships or []
        )

        if domain not in self.concepts:
            self.concepts[domain] = {}
        self.concepts[domain][name] = concept
        self.stats['concepts_indexed'] += 1

        # Persist to database
        await self._persist_concept(concept)

        return concept

    # ==================================================================================
    # Analogy Discovery
    # ==================================================================================

    async def find_analogy(
        self,
        source_concept: str,
        target_domain: str,
        min_similarity: float = 0.5
    ) -> Optional[Analogy]:
        """
        Find analogies for a source concept in a target domain

        Args:
            source_concept: Concept to find analogies for
            target_domain: Domain to search for analogies
            min_similarity: Minimum similarity threshold

        Returns:
            Best analogy found or None
        """
        logger.info(f"Finding analogies: {source_concept} -> {target_domain}")

        # Concept base loads on first use, since it cannot be loaded from the
        # constructor without blocking or a running event loop.
        await self._ensure_initialized()

        # Find source concept in knowledge base
        source = None
        for domain, concepts in self.concepts.items():
            if source_concept in concepts:
                logger.info(f"Found source concept in {domain}")
                source = concepts[source_concept]
                break

        if not source:
            logger.warning(f"Source concept not found: {source_concept}")
            return None

        analogies = []

        # Compare with all concepts in target domain
        target_concepts = self.concepts.get(target_domain, {})
        if not target_concepts:
            logger.warning(f"Target domain not found: {target_domain}")
            return None

        # Find best mappings to target domain
        for target_name, target in target_concepts.items():
            # Calculate mapping
            mapping = await self._calculate_mapping(
                source,
                target,
                min_similarity
            )

            if mapping and mapping.confidence >= min_similarity:
                # Create analogy from this mapping
                analogy = await self._create_analogy_from_mapping(
                    source,
                    target,
                    mapping
                )

                if analogy and analogy.coherence >= min_similarity:
                    analogies.append(analogy)
                    self.stats['analogies_found'] += 1

        # Sort by coherence * novelty
        if analogies:
            analogies.sort(key=lambda a: a.score, reverse=True)
            best_analogy = analogies[0]
            await self._persist_analogy(best_analogy)

        logger.info(f"✓ Found {len(analogies)} analogies for {source_concept} in {target_domain}")

        return analogies[0] if analogies else None

    async def _calculate_mapping(
        self,
        source: Concept,
        target: Concept,
        min_similarity: float
    ) -> Optional[ConceptMapping]:
        """
        Calculate mapping between two concepts

        Args:
            source: Source concept
            target: Target concept
            min_similarity: Minimum similarity threshold

        Returns:
            ConceptMapping or None if similarity too low
        """
        mapping_id = f"{source.name}:{target.name}"

        # Calculate structural similarity
        struct_sim = await self._structural_similarity(source, target)
        if struct_sim < min_similarity * 0.5:  # Early exit if very dissimilar
            return None

        # Calculate functional similarity
        func_sim = await self._functional_similarity(source, target)
        if func_sim < min_similarity * 0.5:
            return None

        # Overall confidence (weighted average)
        confidence = struct_sim * 0.6 + func_sim * 0.4

        # Map attributes (find corresponding attributes)
        attr_mappings = await self._map_attributes(source, target)

        # Map relationships
        rel_mappings = await self._map_relationships(source, target)

        # Determine mapping type
        if len(attr_mappings) == len(source.attributes):
            mapping_type = MappingType.ONE_TO_ONE
        elif len(attr_mappings) >= len(source.attributes) * 0.7:
            mapping_type = MappingType.PARTIAL
        elif len(attr_mappings) >= len(source.attributes) * 0.5:
            mapping_type = MappingType.APPROXIMATE
        else:
            mapping_type = MappingType.PARTIAL

        if confidence < min_similarity:
            return None

        mapping = ConceptMapping(
            source=source,
            target=target,
            mapping_type=mapping_type,
            structural_similarity=struct_sim,
            functional_similarity=func_sim,
            attribute_mappings=attr_mappings,
            relationship_mappings=rel_mappings,
            confidence=confidence
        )

        # Generate explanations for the mapping
        explanations = await self._explain_mapping(source, target, mapping)
        mapping.explanations = explanations

        return mapping

    async def _structural_similarity(
        self,
        concept1: Concept,
        concept2: Concept
    ) -> float:
        """Calculate structural similarity between concepts"""
        # Compare attributes
        attr_overlap = await self._attribute_overlap(concept1.attributes, concept2.attributes)
        if not attr_overlap:
            return 0.0

        # Compare relationships
        rel_overlap = await self._relationship_overlap(concept1.relationships, concept2.relationships)

        # Weighted combination
        similarity = attr_overlap * 0.5 + rel_overlap * 0.5

        return similarity

    async def _functional_similarity(
        self,
        concept1: Concept,
        concept2: Concept
    ) -> float:
        """Calculate functional similarity between concepts"""
        # Compare functions/purposes
        if not concept1.functions and not concept2.functions:
            return 0.5  # No functional info

        # Calculate overlap in functions
        functions_overlap = 0.0
        if concept1.functions and concept2.functions:
            common = set(concept1.functions) & set(concept2.functions)
            total = set(concept1.functions) | set(concept2.functions)
            functions_overlap = len(common) / len(total) if total else 0.0

        return functions_overlap

    async def _attribute_overlap(
        self,
        attrs1: List[str],
        attrs2: List[str]
    ) -> float:
        """Calculate overlap between attribute lists"""
        if not attrs1 or not attrs2:
            return 0.0

        # Simple overlap - count exact matches
        common_attrs = set(attrs1) & set(attrs2)
        total_attrs = set(attrs1) | set(attrs2)

        return len(common_attrs) / len(total_attrs) if total_attrs else 0.0

    async def _relationship_overlap(
        self,
        rels1: List[Tuple[str, str]],
        rels2: List[Tuple[str, str]]
    ) -> float:
        """Calculate overlap between relationship lists"""
        if not rels1 or not rels2:
            return 0.0

        # Compare relationship types (first element of tuple)
        rel_types1 = {rel[0] for rel in rels1}
        rel_types2 = {rel[0] for rel in rels2}

        common = rel_types1 & rel_types2
        total = rel_types1 | rel_types2

        return len(common) / len(total) if total else 0.0

    async def _map_attributes(
        self,
        source: Concept,
        target: Concept
    ) -> Dict[str, str]:
        """Map attributes from source to target"""
        mappings = {}

        # Direct attribute matches
        for attr1 in source.attributes:
            for attr2 in target.attributes:
                # Exact match
                if attr1 == attr2:
                    mappings[attr1] = attr2
                # Semantic similarity (would use embeddings in production)
                elif await self._attributes_similar(attr1, attr2):
                    mappings[attr1] = attr2

        return mappings

    async def _map_relationships(
        self,
        source: Concept,
        target: Concept
    ) -> Dict[str, str]:
        """Map relationships from source to target"""
        mappings = {}

        for rel1_type, rel1_target in source.relationships:
            for rel2_type, rel2_target in target.relationships:
                # Match relationship types
                if rel1_type == rel2_type or await self._relations_similar(rel1_type, rel2_type):
                    mappings[f"{rel1_type}:{rel1_target}"] = f"{rel2_type}:{rel2_target}"

        return mappings

    async def _attributes_similar(self, attr1: str, attr2: str) -> bool:
        """Check if two attributes are semantically similar using embeddings"""
        try:
            from core.memory.utils.embedding_service import get_embedding_service
            embedding_svc = get_embedding_service()

            emb1 = await embedding_svc.get_embedding(attr1)
            emb2 = await embedding_svc.get_embedding(attr2)

            import numpy as np
            similarity = np.dot(emb1, emb2) / (np.linalg.norm(emb1) * np.linalg.norm(emb2))

            return similarity > 0.7

        except Exception as e:
            logger.debug(f"Embedding similarity failed, using heuristics: {e}")

        attr1_lower = attr1.lower().replace('_', ' ')
        attr2_lower = attr2.lower().replace('_', ' ')

        # Same length?
        if len(attr1_lower) == len(attr2_lower):
            return True

        # Contains same words?
        words1 = set(attr1_lower.split())
        words2 = set(attr2_lower.split())

        # Synonym mapping (very basic)
        synonyms = {
            'size': ['magnitude', 'scale', 'dimension'],
            'type': ['kind', 'category', 'class'],
            'function': ['purpose', 'role', 'use'],
            'structure': ['form', 'organization', 'composition'],
            'property': ['characteristic', 'attribute', 'feature'],
            'contains': ['includes', 'has', 'comprises']
        }

        for word1, word2 in zip(words1, words2):
            if word1 in synonyms and (word2 in synonyms[word1] or \
               word2 in synonyms and word1 in synonyms[word2]):
                return True

        return False

    async def _relations_similar(
        self,
        rel1: str,
        rel2: str
    ) -> bool:
        """Check if two relationship types are similar"""

        # Normalize
        rel1 = rel1.lower().strip()
        rel2 = rel2.lower().strip()

        if rel1 == rel2:
            return True

        # Basic synonym mapping
        rel_synonyms = {
            'composes': ['makes up', 'forms', 'constitutes'],
            'contains': ['has', 'includes', 'comprises'],
            'causes': ['leads to', 'results in', 'produces']
        }

        for key, synonyms in rel_synonyms.items():
            if (rel1 == key and rel2 in synonyms) or \
               (rel2 == key and rel1 in synonyms):
                return True

        return False

    async def _create_analogy_from_mapping(
        self,
        source: Concept,
        target: Concept,
        mapping: ConceptMapping
    ) -> Optional[Analogy]:
        """Create an analogy from a concept mapping"""

        analogy_id = f"{source.name}:{target.name}:{datetime.now().timestamp()}"

        # Determine analogy type based on what's similar
        if mapping.structural_similarity > 0.7:
            analogy_type = AnalogyType.STRUCTURAL
        elif mapping.functional_similarity > 0.7:
            analogy_type = AnalogyType.FUNCTIONAL
        else:
            analogy_type = AnalogyType.RELATIONAL

        # Calculate analogy quality metrics
        coherence = mapping.confidence

        # Novelty: higher if domains are very different
        domain_distance = await self._domain_distance(source.domain, target.domain)
        novelty = min(1.0, domain_distance * 1.5)  # Scale up domain distance

        # Utility: how useful is this analogy?
        utility = coherence * 0.6 + novelty * 0.4

        # Overall score
        score = coherence * novelty * 0.5 + utility * 0.5

        # Generate description
        description = await self._describe_analogy(source, target, mapping)

        analogy = Analogy(
            analogy_id=analogy_id,
            analogy_type=analogy_type,
            source_domain=source.domain,
            target_domain=target.domain,
            mappings=[mapping],
            primary_mapping=mapping,
            coherence=coherence,
            novelty=novelty,
            utility=utility,
            description=description,
            score=score
        )

        # Generate insights
        if analogy.score > 0.7:
            analogy.insights.append(f"Strong {analogy_type.value} analogy discovered")

        return analogy

    async def _domain_distance(
        self,
        domain1: str,
        domain2: str
    ) -> float:
        """Calculate semantic distance between domains"""

        # Same domain = 0 distance
        if domain1 == domain2:
            return 0.0

        # Related domains have lower distance
        related_domains = {
            'physics': ['chemistry', 'engineering'],
            'biology': ['chemistry', 'medicine'],
            'mathematics': ['physics', 'computer_science'],
            'computer_science': ['mathematics', 'engineering'],
            'linguistics': ['psychology', 'anthropology'],
            'economics': ['sociology', 'political_science']
        }

        # Check if domains are related
        if domain1 in related_domains and domain2 in related_domains[domain1]:
            return 0.3  # Moderately close

        # Otherwise, distant
        return 1.0

    async def _explain_mapping(
        self,
        source: Concept,
        target: Concept,
        mapping: ConceptMapping
    ) -> List[str]:
        """Generate human-readable explanations for a mapping"""

        explanations = [
            f"{source.name} is to {source.domain} as {target.name} is to {target.domain}"
        ]

        # Explain attribute mappings
        if mapping.attribute_mappings:
            explanations.append(
                f"Similar attributes: {', '.join(list(mapping.attribute_mappings.keys()))}"
            )

        # Explain relationship mappings
        if mapping.relationship_mappings:
            explanations.append(
                f"Similar relationships: {len(mapping.relationship_mappings)} common patterns"
            )

        # Explain similarity
        if mapping.structural_similarity > 0.8:
            explanations.append("Very similar structures")
        elif mapping.functional_similarity > 0.8:
            explanations.append("Similar functions/purposes")

        return " | ".join(explanations) + "."

    async def _describe_analogy(
        self,
        source: Concept,
        target: Concept,
        mapping: ConceptMapping
    ) -> str:
        """Generate description of the analogy"""

        description = f"{source.name} ({source.domain})"
        if source.description:
            description += f": {source.description}"

        description += f" is analogous to {target.name} ({target.domain})"
        if target.description:
            description += f": {target.description}"

        return description

    # ==================================================================================
    # Database Persistence
    # ==================================================================================

    async def _persist_concept(
        self,
        concept: Concept
    ) -> bool:
        """Persist concept to database"""
        try:
            if not self.db:
                return False

            # Concept carries no concept_id field, so reading one raised
            # AttributeError before the query ever ran and every concept write
            # failed silently. Domain+name is the natural key and keeps the
            # upsert idempotent across restarts.
            concept_id = f"{concept.domain}:{concept.name}"

            await self.db.execute_query(
                """
                INSERT INTO unified.concepts
                    (concept_id, name, domain, description, attributes,
                     relationships, functions, processes, context, examples, created_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, NOW())
                ON CONFLICT (concept_id) DO UPDATE SET
                    description = EXCLUDED.description,
                    attributes = EXCLUDED.attributes,
                    relationships = EXCLUDED.relationships,
                    functions = EXCLUDED.functions,
                    processes = EXCLUDED.processes,
                    context = EXCLUDED.context,
                    examples = EXCLUDED.examples,
                    updated_at = NOW()
                """,
                params=(
                    concept_id,
                    concept.name,
                    concept.domain,
                    concept.description,
                    # These columns are JSONB; str() produced Python reprs with
                    # single quotes, which are not valid JSON.
                    _json.dumps(concept.attribute_values or concept.attributes or []),
                    _json.dumps([list(r) for r in (concept.relationships or [])]),
                    _json.dumps(concept.functions or []),
                    _json.dumps(concept.processes or []),
                    concept.context or "",
                    _json.dumps(concept.examples or []),
                ),
                commit=True,
            )

            return True

        except Exception as e:
            logger.error(f"Failed to persist concept: {e}")
            return False

    async def _persist_analogy(
        self,
        analogy: Analogy
    ) -> bool:
        """Persist analogy to database"""
        try:
            if not self.db:
                return False

            await self.db.execute_query(
                """
                INSERT INTO unified.analogies (
                    analogy_id, analogy_type, source_domain, target_domain,
                    coherence, novelty, utility, score, description, insights,
                    mappings, primary_mapping, created_at
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, NOW())
                ON CONFLICT (analogy_id) DO UPDATE SET
                    coherence = EXCLUDED.coherence,
                    novelty = EXCLUDED.novelty,
                    utility = EXCLUDED.utility,
                    score = EXCLUDED.score,
                    insights = EXCLUDED.insights,
                    mappings = EXCLUDED.mappings
                """,
                params=(
                    analogy.analogy_id,
                    getattr(analogy.analogy_type, "value", str(analogy.analogy_type)),
                    analogy.source_domain,
                    analogy.target_domain,
                    float(analogy.coherence),
                    float(analogy.novelty),
                    float(analogy.utility),
                    float(analogy.score),
                    analogy.description,
                    _json.dumps(analogy.insights or []),
                    _json.dumps([str(m) for m in (analogy.mappings or [])]),
                    _json.dumps(str(analogy.primary_mapping)) if analogy.primary_mapping else None,
                ),
                commit=True,
            )

            return True

        except Exception as e:
            logger.error(f"Failed to persist analogy: {e}")
            return False

    async def _persist_mapping(
        self,
        mapping: ConceptMapping,
        analogy_id: str = None
    ) -> bool:
        """Persist concept mapping to database"""

        try:
            if not self.db:
                return False

            await self.db.execute_query(
                """
                INSERT INTO unified.concept_mappings (
                    analogy_id, mappings, confidence, created_at
                )
                VALUES ($1, $2, $3, NOW())
                """,
                params=(
                    analogy_id,
                    str(mapping.mappings),
                    mapping.confidence
                ),
                commit=True,
            )

            return True

        except Exception as e:
            logger.error(f"Failed to persist mapping: {e}")
            return False

    # ==================================================================================
    # Query and Retrieval
    # ==================================================================================

    async def get_analogies_for_concept(
        self,
        concept_name: str
    ) -> List[Analogy]:
        """Get all analogies involving a concept"""
        return [
            analogy for analogy in self.analogies.values()
            if (analogy.primary_mapping and
                (analogy.primary_mapping.source.name == concept_name or
                 analogy.primary_mapping.target.name == concept_name))
        ]

    async def get_best_analogies(self, limit: int = 10) -> List[Analogy]:
        """Get highest-scoring analogies"""
        analogies = sorted(
            self.analogies.values(),
            key=lambda a: a.score,
            reverse=True
        )
        return analogies[:limit]

    async def get_novel_analogies(self, limit: int = 10) -> List[Analogy]:
        """Get most novel analogies"""
        analogies = sorted(
            self.analogies.values(),
            key=lambda a: a.novelty,
            reverse=True
        )
        return analogies[:limit]

    # ==================================================================================
    # Statistics
    # ==================================================================================

    async def get_statistics(self) -> Dict[str, Any]:
        """Get analogy discovery statistics"""
        return {
            **self.stats,
            'domains_indexed': len(self.concepts),
            'total_concepts': sum(len(concepts) for concepts in self.concepts.values()),
            'total_analogies': len(self.analogies),
            'high_quality_analogies': len([a for a in self.analogies.values() if a.score > 0.7])
        }


# Singleton instance
_analogy_discovery: Optional[AnalogyDiscovery] = None


def get_analogy_discovery() -> AnalogyDiscovery:
    """Get global analogy discovery instance"""
    global _analogy_discovery
    if _analogy_discovery is None:
        _analogy_discovery = AnalogyDiscovery()
    return _analogy_discovery


# CLI test
async def main():
    """Test analogy discovery"""
    logging.basicConfig(level=logging.INFO)

    discovery = get_analogy_discovery()

    print("\n=== Analogy Discovery Test ===")

    # Find analogies for "atom" in biology domain
    analogy = await discovery.find_analogy(
        source_concept="atom",
        target_domain="biology"
    )

    if analogy:
        print(f"\nAnalogy Found:")
        print(f"  Type: {analogy.analogy_type.value}")
        print(f"  Description: {analogy.description}")
        print(f"  Coherence: {analogy.coherence:.2f}")
        print(f"  Novelty: {analogy.novelty:.2f}")
        print(f"  Score: {analogy.score:.2f}")

        if analogy.primary_mapping:
            print(f"\n  Primary Mapping:")
            print(f"    {analogy.primary_mapping.source.name} -> {analogy.primary_mapping.target.name}")
            print(f"    Confidence: {analogy.primary_mapping.confidence:.2f}")
            if analogy.primary_mapping.explanations:
                print(f"    Explanation: {analogy.primary_mapping.explanations[0]}")
    else:
        print("\nNo analogies found")

    # Get statistics
    stats = await discovery.get_statistics()
    print(f"\nStatistics:")
    for key, value in stats.items():
        print(f"  {key}: {value}")


if __name__ == "__main__":
    asyncio.run(main())
