#!/usr/bin/env python3
"""
Domain Registry
Central registry for managing all domains and their relationships
"""

import asyncio
import hashlib
from datetime import datetime
import json
import logging
import os
from pathlib import Path
from typing import Dict, List, Set, Optional, Any, Tuple
from collections import defaultdict
from dataclasses import dataclass

from .domain_types import (
    Domain, DomainType, DomainConcept, ConceptType, DomainRelation, DomainKnowledge,
    CrossDomainMapping, KnowledgeTransfer, calculate_domain_similarity
)
from core.capability import raise_if_structural

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ResolvedDomain:
    """A domain reference resolved to a canonical registry domain.

    `category` is the DomainType this field belongs to, read from the registry's
    own state (Domain.domain_type / parent_domains), never from a lookup table
    maintained alongside it.
    """
    domain_id: str
    name: str
    category: Optional[str]
    concept_count: int


class UnresolvedDomainReference(LookupError):
    """A domain reference matched no registered field and no category.

    Explicit on purpose. Falling back to a category, a generic domain or a
    placeholder would turn "you named something that does not exist" into a
    well-formed question with an empty answer, and those must stay
    distinguishable.
    """

    def __init__(self, reference: str, known: Optional[List[str]] = None):
        self.reference = reference
        self.known = list(known or [])
        super().__init__(
            f"UNRESOLVED_DOMAIN: {reference!r} matches no registered domain and "
            f"no category"
            + (f"; known: {', '.join(self.known[:12])}" if self.known else "")
        )


class UnknownDomain(LookupError):
    """A domain was referenced that is not registered.

    Distinct from "no mapping found" on purpose: one means the question was
    malformed, the other is a real answer to a well-formed question.
    """

    def __init__(self, missing: List[str], known: Optional[List[str]] = None):
        self.missing = list(missing)
        self.known = list(known or [])
        super().__init__(
            f"domain(s) not registered: {', '.join(self.missing)}"
            + (f" (registered: {', '.join(self.known)})" if self.known else "")
        )


class DomainRegistry:
    """
    Central registry for all domains and cross-domain relationships
    """
    
    def __init__(self, db_manager=None):
        # PostgreSQL only. This class used to keep its own SQLite file while
        # unified.domains held the same 15 domains in the substrate's real
        # database -- two stores for one concept, and the SQLite one sat inside
        # the live path: UniversalDomainMaster -> CrossDomainReasoner -> here.
        self._db_manager = db_manager
        # Domains present in the store but carrying no concepts, relations or
        # vocabulary. Counted, never silently dropped: "registered but empty"
        # and "not registered" are different answers, and the difference decides
        # whether transfer has anything to work with.
        self.unpopulated_domain_ids: List[str] = []
        self.domains: Dict[str, Domain] = {}
        self.cross_domain_mappings: Dict[str, CrossDomainMapping] = {}
        self.knowledge_transfers: Dict[str, KnowledgeTransfer] = {}
        
        # Indexes for fast lookup
        self.concept_index: Dict[str, Set[str]] = defaultdict(set)  # concept_name -> domain_ids
        self.relation_index: Dict[str, Set[str]] = defaultdict(set)  # relation_type -> domain_ids
        self.domain_similarity_cache: Dict[Tuple[str, str], float] = {}
        
        self._lock = asyncio.Lock()
        self.initialized = False
    
    def _db(self):
        """The one database this registry speaks to."""
        if self._db_manager is None:
            from core.database import get_database_manager
            self._db_manager = get_database_manager()
        return self._db_manager

    async def initialize(self) -> bool:
        """Initialize the domain registry against PostgreSQL.

        Failure is no longer swallowed into `return False`. A registry that
        cannot reach its store must not come up reporting zero domains, because
        that is indistinguishable from a store that is genuinely empty -- and
        every consumer downstream treats "no domains" as a real answer.
        """
        async with self._lock:
            await self._db().initialize()
            await self._load_domains()
            await self._load_concepts()
            self._repair_category_links()
            await self._project_universal_level()
            await self._load_mappings()
            await self._rebuild_indexes()
            self.initialized = True
            logger.info(
                "Domain registry initialized from unified.domains: %d domains "
                "(%d populated, %d empty), %d mappings",
                len(self.domains),
                len(self.domains) - len(self.unpopulated_domain_ids),
                len(self.unpopulated_domain_ids),
                len(self.cross_domain_mappings),
            )
            return True


    def _repair_category_links(self) -> None:
        """Make the category hierarchy consistent BY CONSTRUCTION.

        Every typed domain must be reachable from its DomainType category, both
        ways. Two ways it wasn't: the load path set the PARENT link
        unconditionally but the reciprocal CHILD link only when the category node
        already existed at that moment (load-order dependent), and a domain
        crystallized in-session was persisted with no link at all. Either way a
        real learned domain -- an 86-concept `code_generation`, a taught `bird`
        -- became invisible to category-level resolution. This runs after all
        domains and concepts are loaded, so every node exists: for each domain it
        ensures the category node is present and the parent<->child link holds on
        BOTH sides. Idempotent; a node is never made its own child.
        """
        repaired = 0
        for domain_id, domain in list(self.domains.items()):
            dtype = domain.domain_type
            if dtype is None:
                continue
            category_id = f"domain_{dtype.value}"
            if domain_id == category_id:
                continue
            category = self.domains.get(category_id)
            if category is None:
                category = Domain(
                    domain_id=category_id,
                    name=dtype.value.replace("_", " ").title(),
                    domain_type=dtype,
                    description=f"Domain category: {dtype.value}",
                )
                self.domains[category_id] = category
            if category_id not in domain.parent_domains:
                domain.parent_domains.add(category_id)
                repaired += 1
            if domain_id not in category.child_domains:
                category.child_domains.add(domain_id)
                repaired += 1
        if repaired:
            logger.info("domain hierarchy: repaired %d category link(s) so every "
                        "typed domain is reachable from its category", repaired)

    @staticmethod
    def _domain_key(domain_id: str) -> str:
        """`domain_scientific` -> `scientific`, the spelling unified.* columns use."""
        k = str(domain_id).strip().lower()
        return k[len("domain_"):] if k.startswith("domain_") else k

    def _domain_from_row(self, row) -> Domain:
        """Build a Domain from a unified.domains row.

        `metadata` holds the full serialised Domain when one has been written.
        When it is NULL the row is still a real, registered domain -- it simply
        has no structure yet -- so it is reconstructed from its columns and
        recorded in unpopulated_domain_ids. Returning None here instead would
        make a registered-but-empty domain indistinguishable from one that was
        never registered, and those are the two answers this registry exists to
        tell apart.
        """
        domain_id = row["domain_id"]
        meta = row.get("metadata") if hasattr(row, "get") else row["metadata"]
        if meta:
            if isinstance(meta, str):
                meta = json.loads(meta)
            # A fully serialised domain carries its type and creation time.
            # Deserialise it even when it holds no concepts yet: a newly
            # discovered learned domain is a real, empty domain, and the old
            # gate keyed on concepts/relations/vocabulary dropped such a
            # domain's own metadata -- its origin marker and its type -- in the
            # window before it had learned anything, reconstructing it as an
            # unpopulated category.
            if meta.get("domain_type") and meta.get("created_at"):
                return self._deserialize_domain(meta)

        self.unpopulated_domain_ids.append(domain_id)
        key = self._domain_key(domain_id)
        try:
            domain_type = DomainType(key)
        except ValueError:
            domain_type = DomainType.ABSTRACT
        return Domain(
            domain_id=domain_id,
            name=row["domain_name"] or domain_id,
            domain_type=domain_type,
            description=row["description"] or "",
        )

    async def _load_domains(self):
        """Load domains from unified.domains.

        Was SQLite: ``SELECT *`` then ``json.loads(row[4])``, binding the loader
        to column ORDER. Against a store whose fourth column was ``concepts``
        rather than ``data`` every row raised inside a per-row ``except`` and was
        dropped to ``logger.warning``, so the registry came up reporting zero
        domains -- identical to an empty one. Five .db files existed across the
        tree in three schemas because the path was relative to the CWD.
        """
        rows = await self._db().execute_query(
            "SELECT domain_id, domain_name, description, metadata FROM unified.domains",
            fetch_all=True,
        ) or []

        failed: List[str] = []
        for row in rows:
            try:
                domain = self._domain_from_row(dict(row))
            except Exception as e:
                failed.append(f"{row['domain_id']} ({type(e).__name__}: {e})")
                continue
            self.domains[domain.domain_id] = domain

        if failed:
            # Corrupt content is a defect, not an absent domain. ERROR so it
            # cannot read as a quiet miss.
            logger.error(
                "unified.domains: %d/%d rows failed to load: %s",
                len(failed), len(rows), "; ".join(failed[:5]),
            )
        if self.unpopulated_domain_ids:
            logger.warning(
                "unified.domains: %d/%d domains are registered but hold no "
                "concepts, relations or vocabulary (%s). Cross-domain reasoning "
                "scores structural similarity over exactly those, so these "
                "domains cannot produce a mapping until they are populated.",
                len(self.unpopulated_domain_ids), len(rows),
                ", ".join(self.unpopulated_domain_ids[:8]),
            )

    # unified.concepts files concepts under FIELD names (physics, biology,
    # economics) while DomainType enumerates CATEGORIES (physical, scientific,
    # business). These are two levels of one taxonomy, not two competing names
    # for it, so neither is discarded: the field becomes the domain_id, the
    # category becomes its domain_type.
    #
    # The pairing is explicit because nothing in the data records it and
    # inferring it from string similarity is how `linguistics` silently becomes
    # something other than `linguistic`. Anything absent here is loaded and
    # reported, never dropped -- see _load_concepts.
    #: Which CATEGORY each learned FIELD belongs to.
    #
    #: This table is the only thing that connects a caller's category reference
    #: ("scientific", "physical") to the fields that actually hold concepts. A
    #: field missing from it is not rejected -- it loads under the ABSTRACT
    #: fallback (:268-273) and is named in the startup log. That fallback was
    #: absorbing 15 of the 18 populated fields, so `physical` resolved to
    #: physics alone while fluid_mechanics, mechanics and thermodynamics sat
    #: under `abstract`, and every category-level lookup missed the concepts it
    #: was asking for.
    #
    #: Assignments below are made against the concepts each field actually
    #: holds, not against the field name.
    _FIELD_TO_DOMAIN_TYPE: Dict[str, DomainType] = {
        # Physical science: fields whose concepts are physical quantities,
        # laws and conserved relationships.
        "physics": DomainType.PHYSICAL,              # current, dielectric, conservation_of_power
        "mechanics": DomainType.PHYSICAL,            # engine, spring, raised_weight
        "fluid_mechanics": DomainType.PHYSICAL,      # hydraulic_grade_line, minor_loss, pipe_friction
        "fluid_dynamics": DomainType.PHYSICAL,       # flow_rate, system_pressure
        "thermodynamics": DomainType.PHYSICAL,       # compressed_gas

        # Empirical science: fields whose concepts are studied substances,
        # phenomena, or the record of their study.
        "biology": DomainType.SCIENTIFIC,
        "chemistry": DomainType.SCIENTIFIC,          # chemical_energy_storage
        "material_science": DomainType.SCIENTIFIC,   # rust_accumulation, scale_accumulation
        "materials_science": DomainType.SCIENTIFIC,  # dielectric_insulating
        # Its concepts are the scientists themselves (georg_ohm, ohm_person).
        # Filed with the sciences rather than SOCIAL so that a scientific
        # reference reaches the provenance of the laws in `physics`.
        "history_of_science": DomainType.SCIENTIFIC,

        # Engineering: fields whose concepts are designed artefacts and the
        # systems built from them.
        "engineering": DomainType.TECHNICAL,         # sealed_chamber
        "engineering_design": DomainType.TECHNICAL,  # physical_restriction
        "computer_science": DomainType.TECHNICAL,
        "electronics": DomainType.TECHNICAL,         # capacitor, ac/dc_circuit
        "electrical_engineering": DomainType.TECHNICAL,  # battery, circuit_theory
        "hydraulic": DomainType.TECHNICAL,           # hydraulic_accumulator, hydraulic_fluid
        "process_industry": DomainType.TECHNICAL,    # measurement_point, pipe_length_specification_rule
        "flow_measurement": DomainType.TECHNICAL,    # special_flow_smoothing_vane

        # Applied trades: fields whose concepts are installed conditions and
        # the ways real installations fail.
        "plumbing": DomainType.PRACTICAL,            # blockage, collapsed_line, malfunctioning_valve
        "construction": DomainType.PRACTICAL,        # galvanized_pipe, steel_pipe

        "mathematics": DomainType.MATHEMATICAL,
        "linguistics": DomainType.LINGUISTIC,
        "economics": DomainType.BUSINESS,
    }

    #: Recognizable terms per DomainType, for classifying a field the explicit
    #: map above does not name. A newly-encountered domain is classified from
    #: the terms in its own name so it is wired automatically, rather than left
    #: for a human to add to the table above.
    _DOMAIN_TYPE_TERMS = {
        DomainType.MATHEMATICAL: {"math", "mathematics", "arithmetic", "algebra",
                                  "calculus", "geometry", "logic", "number", "numeric"},
        DomainType.PHYSICAL: {"physics", "physical", "mechanics", "mechanical", "fluid",
                              "thermodynamics", "thermo", "electronics", "electrical", "circuit"},
        DomainType.SCIENTIFIC: {"biology", "bio", "chemistry", "chem", "material",
                                "materials", "science", "scientific", "research"},
        DomainType.LINGUISTIC: {"language", "linguistic", "linguistics", "conversation",
                                "communication", "documentation", "semantic", "semantics",
                                "text", "nlp", "reading", "grammar"},
        DomainType.BUSINESS: {"business", "economics", "econ", "finance", "market", "commerce"},
        DomainType.CREATIVE: {"art", "creative", "design", "music", "aesthetic"},
        DomainType.SOCIAL: {"social", "society"},
        DomainType.PRACTICAL: {"plumbing", "construction", "trade", "installation",
                               "maintenance", "repair"},
        # The substrate's own operating fields resolve here.
        DomainType.TECHNICAL: {"ai", "ml", "code", "coding", "software", "program",
                               "programming", "data", "database", "db", "network",
                               "networking", "security", "system", "systems", "execution",
                               "filesystem", "file", "reasoning", "computer", "computing",
                               "tool", "tools", "api", "monitoring", "memory", "learning",
                               "engineering", "electronic", "tech", "technical", "test",
                               "testing", "generation", "processing", "search", "substrate"},
    }

    @classmethod
    def _classify_field(cls, field: str) -> DomainType:
        """Classify a knowledge field into a DomainType, automatically.

        Explicit assignments (made against the concepts a field actually holds)
        win. An unknown field is classified by the recognizable terms in its own
        name, so a newly-encountered domain is wired without a human editing a
        table. Only a field with no recognizable signal falls to ABSTRACT.
        """
        explicit = cls._FIELD_TO_DOMAIN_TYPE.get(field)
        if explicit is not None:
            return explicit
        tokens = set(field.lower().replace("-", " ").replace("_", " ").split())
        for domain_type, terms in cls._DOMAIN_TYPE_TERMS.items():
            if tokens & terms:
                return domain_type
        return DomainType.ABSTRACT

    async def _load_concepts(self):
        """Load concepts from unified.concepts and attach them to their domains.

        Without this the registry held 15 domains with no concepts, relations or
        vocabulary, while 13 fully-formed concepts sat unread in the same
        database -- so every structural-similarity score was computed over
        nothing and cross-domain reasoning correctly returned no mappings, for a
        reason that looked like an empty system rather than an unread table.
        The analogies already stored (physics->biology, engineering->biology)
        were produced against these same field names, so this is the level the
        working producer reasons at.
        """
        rows = await self._db().execute_query(
            """SELECT concept_id, name, domain, description, attributes, relationships
               FROM unified.concepts""",
            fetch_all=True,
        ) or []

        def _j(v, default):
            if v in (None, ""):
                return default
            return json.loads(v) if isinstance(v, str) else v

        unclassified: Set[str] = set()
        attached = 0
        for row in rows:
            field = (row["domain"] or "").strip().lower()
            if not field:
                continue
            domain_id = f"domain_{field}"

            if domain_id not in self.domains:
                dtype = self._classify_field(field)
                if dtype is DomainType.ABSTRACT and field not in self._FIELD_TO_DOMAIN_TYPE:
                    # No recognizable signal in the field name: classified as
                    # ABSTRACT automatically, not left for a human to map.
                    unclassified.add(field)
                self.domains[domain_id] = Domain(
                    domain_id=domain_id,
                    name=field.replace("_", " ").title(),
                    domain_type=dtype,
                    description=f"Knowledge field: {field}",
                )
                # Membership recorded in the registry's OWN structure. Domain
                # already carries parent_domains/child_domains, so category ->
                # field is expressed there rather than in a second lookup table
                # the resolver would have to consult. The classification above
                # seeds this once; everything downstream reads the graph.
                category_id = f"domain_{dtype.value}"
                self.domains[domain_id].parent_domains.add(category_id)
                if category_id in self.domains:
                    self.domains[category_id].child_domains.add(domain_id)

            # relationships is [[verb, target], ...]; the target is the related
            # concept. The verb is kept in properties rather than thrown away.
            rels = _j(row["relationships"], [])
            related, verbs = set(), []
            for r in rels:
                if isinstance(r, (list, tuple)) and len(r) >= 2:
                    verbs.append([r[0], r[1]])
                    related.add(str(r[1]))
                elif isinstance(r, str):
                    related.add(r)

            self.domains[domain_id].concepts[row["concept_id"]] = DomainConcept(
                concept_id=row["concept_id"],
                name=row["name"],
                domain_id=domain_id,
                # unified.concepts records no type. ENTITY is the taxonomy's
                # least-committal member and the shape these rows actually have
                # (named things with attributes); it is not inferred per row.
                concept_type=ConceptType.ENTITY,
                description=row["description"] or "",
                attributes=_j(row["attributes"], {}),
                properties={"relationships": verbs} if verbs else {},
                related_concepts=related,
            )
            attached += 1

        # A domain that just received concepts is no longer empty.
        self.unpopulated_domain_ids = [
            d for d in self.unpopulated_domain_ids
            if not self.domains.get(d) or not self.domains[d].concepts
        ]

        if unclassified:
            logger.info(
                "unified.concepts: %d field(s) had no recognizable domain signal "
                "and were auto-classified as ABSTRACT: %s",
                len(unclassified), ", ".join(sorted(unclassified)),
            )
        logger.info(
            "unified.concepts: attached %d concepts across %d fields",
            attached,
            len({(r["domain"] or "").strip().lower() for r in rows if r["domain"]}),
        )

    def _resolved(self, domain: Domain) -> ResolvedDomain:
        return ResolvedDomain(
            domain_id=domain.domain_id,
            name=domain.name,
            category=domain.domain_type.value if domain.domain_type else None,
            concept_count=len(domain.concepts),
        )

    def resolve_domain_reference(
        self,
        reference: str,
        *,
        require_concepts: bool = True,
        max_targets: Optional[int] = None,
        rank_against: Optional[str] = None,
    ) -> List[ResolvedDomain]:
        """Resolve a caller's domain reference to canonical registry domains.

            "physics"   -> [domain_physics]                  exact field
            "physical"  -> [domain_physics, ...]             category -> members
            "nonsense"  -> UnresolvedDomainReference         explicit

        Replaces coercing every reference through DomainType, which is what
        produced the category/field split in the first place: the master minted
        ``domain_{DomainType.value}`` and asked for `domain_physical`, a category
        with no concepts, while every concept sat in `domain_physics`.

        EXACT WINS. A reference naming a registered field resolves to that field
        and is never widened to its category, so "physics" cannot become
        "physical".

        Category expansion reads parent/child links held on the Domain objects
        themselves -- the registry's own state -- so there is no second ontology
        to drift from this one.
        """
        if not self.initialized:
            raise RuntimeError(
                "resolve_domain_reference called before initialize(); resolving "
                "against an unloaded registry would report every reference as "
                "unresolved"
            )

        raw = str(reference).strip()
        key = self._domain_key(raw)
        canonical = f"domain_{key}"

        # 1. Exact identity: id, canonical id, or name.
        match = self.domains.get(raw) or self.domains.get(canonical)
        if match is None:
            for d in self.domains.values():
                if d.name.strip().lower() == raw.lower():
                    match = d
                    break

        if match is not None:
            children = [
                self.domains[c] for c in sorted(match.child_domains)
                if c in self.domains
            ]
            # If the reference names a CATEGORY (a DomainType value), the answer
            # is every domain OF that type -- not only the ones wired as
            # children. A learned subject domain that never got linked into the
            # hierarchy (a persisted crystallized domain, or one whose reciprocal
            # child link was lost to load order) is still of this type, and
            # category-level reasoning must reach it or it silently skips real
            # knowledge -- an 86-concept `code_generation` domain went missing
            # exactly this way. `_bound` dedupes, so unioning is safe. An EXACT
            # FIELD reference ("physics") is NOT a DomainType value and so is
            # never widened -- exact still wins.
            try:
                as_category = DomainType(key)
            except ValueError:
                as_category = None
            if as_category is not None:
                members = list(children)
                members += [d for d in self.domains.values()
                            if d.domain_type == as_category]
                if match.concepts:
                    members.append(match)
                return self._bound(members, require_concepts, max_targets, rank_against)
            # A node with members is a category. It contributes itself only if
            # it actually carries concepts.
            if children:
                members = list(children)
                if match.concepts:
                    members.append(match)
                return self._bound(members, require_concepts, max_targets, rank_against)
            return self._bound([match], require_concepts, max_targets, rank_against)

        # 2. Category with no registered node of its own.
        try:
            dtype = DomainType(key)
        except ValueError:
            raise UnresolvedDomainReference(raw, sorted(self.domains))

        members = [d for d in self.domains.values() if d.domain_type == dtype]
        if not members:
            raise UnresolvedDomainReference(raw, sorted(self.domains))
        return self._bound(members, require_concepts, max_targets, rank_against)

    def _bound(
        self,
        members: List[Domain],
        require_concepts: bool,
        max_targets: Optional[int],
        rank_against: Optional[str],
    ) -> List[ResolvedDomain]:
        """Discard empties, rank by concept overlap, cap.

        Category expansion is combinatorial -- every source field against every
        target field -- so it is bounded here rather than at the reasoner. An
        empty member is DISCARDED, not reasoned over: a field with no concepts
        cannot produce a mapping, and letting it through would add a negative
        result that is an artefact of absent data rather than evidence about the
        domains.
        """
        seen: Set[str] = set()
        unique: List[Domain] = []
        for d in members:                    # same field reachable by several
            if d.domain_id in seen:          # paths is still reasoned over once
                continue
            seen.add(d.domain_id)
            unique.append(d)

        if require_concepts:
            unique = [d for d in unique if d.concepts]

        source = self.domains.get(rank_against) if rank_against else None
        if source is not None and source.concepts:
            src_names = {c.name.lower() for c in source.concepts.values()}
            src_rel = {r.lower() for c in source.concepts.values()
                       for r in getattr(c, "related_concepts", set())}
            src_terms = src_names | src_rel

            def relevance(d: Domain) -> Tuple[float, int]:
                terms = {c.name.lower() for c in d.concepts.values()}
                terms |= {r.lower() for c in d.concepts.values()
                          for r in getattr(c, "related_concepts", set())}
                overlap = len(src_terms & terms)
                return (overlap / max(1, len(terms)), len(d.concepts))

            unique.sort(key=relevance, reverse=True)
        else:
            unique.sort(key=lambda d: len(d.concepts), reverse=True)

        if max_targets is not None:
            dropped = len(unique) - max_targets
            if dropped > 0:
                logger.info(
                    "Domain resolution capped at %d target(s); %d lower-ranked "
                    "field(s) not reasoned over: %s",
                    max_targets, dropped,
                    ", ".join(d.domain_id for d in unique[max_targets:]),
                )
            unique = unique[:max_targets]

        return [self._resolved(d) for d in unique]

    #: The registry domain that holds the universal level.
    UNIVERSAL_DOMAIN_ID = "domain_abstract"

    async def _project_universal_level(self):
        """Attach the UniversalOntology's universal level to domain_abstract.

        ABSTRACT is not a field of study; it is the level every field is an
        instance of, and its concepts (entity, process, causation, system,
        feedback_loop, trade_off ...) live in UniversalOntology. The registry
        held `domain_abstract` as a row with no concepts, so a reference to the
        ABSTRACT category resolved to nothing -- while the concepts sat one
        module away, fully formed. The two stores were never joined.

        DERIVED, never persisted. The ontology remains the single authority:
        this view is rebuilt on every initialize() and is not written to
        unified.concepts, so the universal level cannot drift from its owner
        and never enters the record as something Torin learned.
        """
        from .universal_ontology import get_universal_ontology

        ontology = get_universal_ontology()
        if not ontology.initialized:
            await ontology.initialize()

        concepts, relations = ontology.project_universal_level(
            self.UNIVERSAL_DOMAIN_ID)

        domain = self.domains.get(self.UNIVERSAL_DOMAIN_ID)
        if domain is None:
            # The registry needs this node, so the registry provides it --
            # IN MEMORY, like the concepts it holds. It used to come from
            # UniversalDomainMaster._initialize_default_domains, which seeded
            # all 15 DomainType categories into unified.domains at every boot.
            # Fourteen of those had no reader at all (category references
            # resolve through the field domains' own domain_type), and the
            # fifteenth was load-bearing for a requirement declared here --
            # so this module's precondition was being met by a side effect of
            # another module's startup.
            domain = Domain(
                domain_id=self.UNIVERSAL_DOMAIN_ID,
                name="Abstract Domain",
                domain_type=DomainType.ABSTRACT,
                description="The universal level: concepts every field instantiates",
            )
            self.domains[self.UNIVERSAL_DOMAIN_ID] = domain

        # Persisted concepts would already have been attached by _load_concepts.
        # Refusing the collision keeps one owner for the universal level: if the
        # ontology's concepts are ever written to unified.concepts, this fails
        # loudly rather than quietly holding two copies that can disagree.
        clash = sorted(set(domain.concepts) & {c.concept_id for c in concepts})
        if clash:
            raise ValueError(
                f"{self.UNIVERSAL_DOMAIN_ID} already holds persisted concept(s) "
                f"{clash[:5]} that the universal projection also produces; the "
                f"universal level would have two owners")

        for concept in concepts:
            domain.concepts[concept.concept_id] = concept
        for relation in relations:
            domain.relations[relation.relation_id] = relation

        logger.info(
            "Universal level projected onto %s: %d concept(s), %d relation(s)",
            self.UNIVERSAL_DOMAIN_ID, len(concepts), len(relations))

    async def _load_mappings(self):
        """Load cross-domain mappings from unified.domain_mappings."""
        rows = await self._db().execute_query(
            """SELECT mapping_id, metadata, source_domain, target_domain,
                      source_concept, target_concept, similarity_score,
                      reasoning_strategy, confidence, verified
               FROM unified.domain_mappings
               WHERE verified IS NULL OR verified IS TRUE""",
            fetch_all=True,
        ) or []

        failed: List[str] = []
        for row in rows:
            meta = row["metadata"]
            try:
                # THE STRUCTURED COLUMNS ARE AUTHORITATIVE. The cross-domain
                # reasoner writes a mapping into the columns (source_domain,
                # similarity_score, ...) and does not always duplicate it into
                # the metadata blob. A metadata blob is only a full serialised
                # mapping when it carries `mapping_id`; some rows (operator-
                # correspondence, kind=operator_correspondence) store a PARTIAL
                # blob without the mapping fields, and deserialising that raised
                # KeyError and dropped a real mapping. So metadata is used only
                # when it is a complete mapping; otherwise the columns are.
                if isinstance(meta, str):
                    meta = json.loads(meta)
                if isinstance(meta, dict) and "mapping_id" in meta:
                    mapping = self._deserialize_mapping(meta)
                else:
                    mapping = self._mapping_from_row(row)
            except Exception as e:
                failed.append(f"{row['mapping_id']} ({type(e).__name__}: {e})")
                continue
            self.cross_domain_mappings[mapping.mapping_id] = mapping

        if failed:
            logger.error(
                "unified.domain_mappings: %d/%d rows failed to load: %s",
                len(failed), len(rows), "; ".join(failed[:5]),
            )

        await self._reconcile_usage_counts()

    async def _reconcile_usage_counts(self):
        """usage_count is a PROJECTION of mapping_usage_events, so derive it.

        The stored value is a cache of a count the events already determine. It
        was previously maintained independently -- incremented per application
        with no record of which application -- so a value could survive that no
        event justifies, and nothing could tell a real count from a stale one.
        Deriving it on load makes the events authoritative and the cache
        unable to drift.
        """
        rows = await self._db().execute_query(
            "SELECT mapping_id, count(*) AS n FROM unified.mapping_usage_events "
            "GROUP BY mapping_id", fetch_all=True) or []
        counts = {r["mapping_id"]: int(r["n"]) for r in rows}

        corrected = 0
        for mapping_id, mapping in self.cross_domain_mappings.items():
            derived = counts.get(mapping_id, 0)
            if mapping.usage_count != derived:
                mapping.usage_count = derived
                corrected += 1
        if corrected:
            logger.info(
                "Reconciled usage_count on %d mapping(s) against "
                "unified.mapping_usage_events", corrected)
    
    async def register_domain(self, domain: Domain) -> bool:
        """Register a new domain"""
        try:
            async with self._lock:
                self.domains[domain.domain_id] = domain
                await self._persist_domain(domain)
                await self._update_indexes_for_domain(domain)
                logger.info(f"Registered domain: {domain.name} ({domain.domain_id})")
                return True
        except Exception as e:
            logger.error(f"Failed to register domain {domain.name}: {e}")
            return False
    
    async def get_domain(self, domain_id: str) -> Optional[Domain]:
        """Get a domain by ID"""
        return self.domains.get(domain_id)
    
    async def get_domain_by_name(self, name: str) -> Optional[Domain]:
        """Get a domain by name"""
        for domain in self.domains.values():
            if domain.name.lower() == name.lower():
                return domain
        return None
    
    async def list_domains(self, domain_type: Optional[DomainType] = None) -> List[Domain]:
        """List all domains, optionally filtered by type"""
        domains = list(self.domains.values())
        if domain_type:
            domains = [d for d in domains if d.domain_type == domain_type]
        return domains
    
    async def find_similar_domains(self, domain_id: str, threshold: float = 0.5) -> List[Tuple[Domain, float]]:
        """Find domains similar to the given domain"""
        if domain_id not in self.domains:
            return []
        
        target_domain = self.domains[domain_id]
        similar_domains = []
        
        for other_id, other_domain in self.domains.items():
            if other_id == domain_id:
                continue
            
            # Check cache first
            cache_key = (min(domain_id, other_id), max(domain_id, other_id))
            if cache_key in self.domain_similarity_cache:
                similarity = self.domain_similarity_cache[cache_key]
            else:
                similarity = calculate_domain_similarity(target_domain, other_domain)
                self.domain_similarity_cache[cache_key] = similarity
            
            if similarity >= threshold:
                similar_domains.append((other_domain, similarity))
        
        # Sort by similarity score
        similar_domains.sort(key=lambda x: x[1], reverse=True)
        return similar_domains
    
    async def find_concepts_across_domains(self, concept_name: str) -> List[Tuple[Domain, DomainConcept]]:
        """Find concepts with similar names across all domains"""
        results = []
        concept_name_lower = concept_name.lower()
        
        for domain in self.domains.values():
            for concept in domain.concepts.values():
                if concept_name_lower in concept.name.lower():
                    results.append((domain, concept))
        
        return results
    
    @staticmethod
    def _mapping_key(source_domain_id: str, target_domain_id: str,
                     source_concept_id: str, target_concept_id: str,
                     mapping_type: str) -> str:
        """Stable identity for a cross-domain mapping: the relationship it states."""
        digest = hashlib.sha256(
            "\x1f".join((source_domain_id, target_domain_id, source_concept_id,
                         target_concept_id, mapping_type)).encode()
        ).hexdigest()[:32]
        return f"xdm_{digest}"

    async def add_cross_domain_mapping(self, mapping: CrossDomainMapping) -> bool:
        """Add a cross-domain mapping.

        A write that cannot be performed is not a mapping that "wasn't added" --
        it is a broken store. The bare `except -> return False` here made a
        NotNullViolation indistinguishable from a legitimate refusal, and the
        one caller reads the bool as the latter.
        """
        async with self._lock:
            # CARRY FORWARD what was accumulated, replace only what was re-judged.
            #
            # suggest_cross_domain_mappings mints a FRESH CrossDomainMapping on
            # every call, with usage_count=0 and success_rate=0.0 from the
            # dataclass defaults. Storing it wholesale overwrote the running
            # totals of the mapping it re-derived -- both here and, through
            # _persist_mapping's `metadata = EXCLUDED.metadata`, in the store --
            # so usage_count could never exceed 1 no matter how often the
            # correspondence was relied upon. The verdict is new each time; the
            # history is not, and a re-derivation is not a reset.
            prior = self.cross_domain_mappings.get(mapping.mapping_id)
            if prior is not None:
                mapping.usage_count = max(mapping.usage_count, prior.usage_count)
                mapping.success_rate = (prior.success_rate if mapping.success_rate == 0.0
                                        else mapping.success_rate)
                mapping.last_used = mapping.last_used or prior.last_used
                mapping.created_at = prior.created_at
            self.cross_domain_mappings[mapping.mapping_id] = mapping
            try:
                await self._persist_mapping(mapping)
            except Exception as e:
                del self.cross_domain_mappings[mapping.mapping_id]
                raise_if_structural(e, "DomainRegistry.add_cross_domain_mapping")
                logger.error("Failed to persist cross-domain mapping %s: %s",
                             mapping.mapping_id, e)
                return False
            logger.info(f"Added cross-domain mapping: {mapping.mapping_id}")
            return True
    
    async def get_cross_domain_mappings(self, source_domain_id: str, 
                                      target_domain_id: Optional[str] = None) -> List[CrossDomainMapping]:
        """Get cross-domain mappings for a domain"""
        mappings = []
        for mapping in self.cross_domain_mappings.values():
            if mapping.source_domain_id == source_domain_id:
                if target_domain_id is None or mapping.target_domain_id == target_domain_id:
                    mappings.append(mapping)
        return mappings
    
    async def suggest_cross_domain_mappings(self, source_domain_id: str, 
                                          target_domain_id: str) -> List[CrossDomainMapping]:
        """Suggest potential cross-domain mappings based on concept similarity.

        Raises UnknownDomain if either domain is not registered. Returning []
        for that case made "these domains have no analogy" and "you asked about
        a domain that does not exist" the same answer -- so a typo, an
        uninitialized registry and a genuine negative were indistinguishable to
        every caller.
        """
        missing = [d for d in (source_domain_id, target_domain_id) if d not in self.domains]
        if missing:
            raise UnknownDomain(missing, sorted(self.domains))

        source_domain = self.domains[source_domain_id]
        target_domain = self.domains[target_domain_id]
        
        suggested_mappings = []
        
        for source_concept in source_domain.concepts.values():
            for target_concept in target_domain.concepts.values():
                # Calculate concept similarity
                from .domain_types import calculate_concept_similarity
                similarity = calculate_concept_similarity(source_concept, target_concept)
                
                if similarity > 0.6:  # Threshold for suggestion
                    mapping = CrossDomainMapping(
                        # DETERMINISTIC, derived from the relationship itself.
                        # An empty id makes __post_init__ mint a fresh uuid4, so
                        # re-proposing the same concept pair produced a new row
                        # every run and ON CONFLICT (mapping_id) never fired --
                        # the store would accumulate duplicate rows of the same
                        # mapping, each with its own verdict. The identity of a
                        # mapping is which two concepts it relates, not when it
                        # happened to be rediscovered.
                        mapping_id=self._mapping_key(
                            source_domain_id, target_domain_id,
                            source_concept.concept_id, target_concept.concept_id,
                            "similarity"),
                        source_domain_id=source_domain_id,
                        target_domain_id=target_domain_id,
                        source_concept_id=source_concept.concept_id,
                        target_concept_id=target_concept.concept_id,
                        mapping_type="similarity",
                        strength=similarity,
                        confidence=similarity * 0.8,  # Slightly lower confidence
                        # A SUGGESTION, not a refutation. This said False, which
                        # is the validator's verdict for "tested and does not
                        # hold" -- so every candidate this method proposed was
                        # born marked as already disproven.
                        validated=None
                    )
                    suggested_mappings.append(mapping)
        
        # Sort by strength
        suggested_mappings.sort(key=lambda x: x.strength, reverse=True)
        return suggested_mappings[:10]  # Return top 10 suggestions
    
    async def create_knowledge_transfer(self, transfer: KnowledgeTransfer) -> bool:
        """Create a knowledge transfer record.

        Same defect as add_cross_domain_mapping: the broad except swallowed a
        NOT NULL violation on every call, so the in-memory dict held transfers
        the table never received and callers were told it worked.
        """
        async with self._lock:
            self.knowledge_transfers[transfer.transfer_id] = transfer
            try:
                await self._persist_transfer(transfer)
            except Exception as e:
                del self.knowledge_transfers[transfer.transfer_id]
                raise_if_structural(e, "DomainRegistry.create_knowledge_transfer")
                logger.error("Failed to persist knowledge transfer %s: %s",
                             transfer.transfer_id, e)
                return False
            logger.info(f"Created knowledge transfer: {transfer.transfer_id}")
            return True
    
    @staticmethod
    def _usage_id(mapping_id: str, task_id: str, application_stage: str) -> str:
        """Identity of ONE application: which mapping, on which task, at which stage.

        Derived, not generated, so the same logical application always produces
        the same id. Autonomous execution retries; a counter incremented per
        attempt turns one use into three, and the resulting usage_count is then
        evidence for a correspondence that was applied once.
        """
        digest = hashlib.sha256(
            "\x1f".join((mapping_id, task_id, application_stage)).encode()
        ).hexdigest()[:32]
        return f"use_{digest}"

    async def record_mapping_usage(
        self, mapping_ids: List[str], *, task_id: str,
        application_stage: str = "transfer_applied",
        transfer_id: Optional[str] = None,
        provenance: Optional[Dict[str, Any]] = None,
    ) -> int:
        """Record that these mappings were APPLIED, as durable EVENTS.

        `usage_count` was a mutable integer on the mapping, which could say only
        "13" -- not which tasks, when, or whether two of those were the same
        application retried. It also could not answer the question transfer
        evaluation actually needs: on WHICH tasks did this correspondence
        participate? Without that, "the domain improved after the transfer" is
        the only available signal, and it cannot separate the tasks the mapping
        touched from the ones it did not.

        Each application is written once, keyed by (mapping_id, task_id, stage).
        usage_count becomes a PROJECTION of these events rather than a number
        maintained in parallel with them, so it cannot drift from the record and
        is reconstructible after any restart.

        Returns the number of NEW events (a retried application returns 0).
        """
        if not task_id:
            raise ValueError(
                "record_mapping_usage requires the task the mapping was applied "
                "to; an application with no task cannot be attributed to an "
                "outcome and would only inflate a count")

        recorded = 0
        async with self._lock:
            for mapping_id in mapping_ids:
                mapping = self.cross_domain_mappings.get(mapping_id)
                if mapping is None:
                    continue
                status = await self._db().execute_query(
                    """INSERT INTO unified.mapping_usage_events
                           (usage_id, mapping_id, transfer_id, task_id,
                            application_stage, source_domain, target_domain,
                            provenance)
                       VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb)
                       ON CONFLICT (usage_id) DO NOTHING""",
                    (self._usage_id(mapping_id, task_id, application_stage),
                     mapping_id, transfer_id, task_id, application_stage,
                     self._domain_key(mapping.source_domain_id),
                     self._domain_key(mapping.target_domain_id),
                     json.dumps(provenance or {})),
                    commit=True)
                if self._rows_affected(status) == 0:
                    continue  # same application seen again; not a second use
                recorded += 1

                # usage_count is now DERIVED from the events, never incremented
                # independently of them.
                mapping.usage_count = await self._usage_count(mapping_id)
                mapping.last_used = datetime.now()
                await self._persist_mapping(mapping)
        return recorded

    @staticmethod
    def _rows_affected(status: Any) -> int:
        """Rows touched by a write, from asyncpg's 'INSERT 0 1' status string."""
        try:
            return int(str(status).strip().split()[-1])
        except (ValueError, IndexError, AttributeError):
            return 0

    async def _usage_count(self, mapping_id: str) -> int:
        rows = await self._db().execute_query(
            "SELECT count(*) AS n FROM unified.mapping_usage_events WHERE mapping_id = $1",
            (mapping_id,), fetch_all=True)
        return int(rows[0]["n"]) if rows else 0

    async def tasks_using_mappings(self, mapping_ids: List[str]) -> Set[str]:
        """The tasks these mappings actually participated in.

        This is what turns "outcomes after the transfer" into "outcomes the
        transfer touched". Without it a target domain's whole post-transfer
        history is one undifferentiated block, and a mapping applied to 2 of 10
        tasks gets credited for all 10.
        """
        if not mapping_ids:
            return set()
        rows = await self._db().execute_query(
            "SELECT DISTINCT task_id FROM unified.mapping_usage_events "
            "WHERE mapping_id = ANY($1::text[])",
            (list(mapping_ids),), fetch_all=True) or []
        return {r["task_id"] for r in rows}

    async def unresolved_transfers(self) -> List[Dict[str, Any]]:
        """Transfers whose outcome is not yet known (success IS NULL)."""
        return await self._db().execute_query(
            """SELECT transfer_id, source_domain, target_domain, concept,
                      created_at, metadata
               FROM unified.knowledge_transfers
               WHERE success IS NULL
               ORDER BY created_at""",
            fetch_all=True,
        ) or []

    async def resolve_knowledge_transfer(
        self, transfer_id: str, helped: bool, effectiveness: float,
        evidence: Dict[str, Any],
    ) -> bool:
        """Record whether a transfer actually helped, with its evidence.

        This closes the other direction of the loop. A transfer was written
        with `success` NULL and nothing ever revisited it, so the record said
        only that a correspondence had been proposed and validated -- never
        whether relying on it made work in the target domain go better. A
        validated structural analogy is a claim about structure; whether it
        HELPS is a claim about outcomes, and only the second can be earned.

        The evidence is stored with the verdict so the judgement is auditable
        and can be revised when more outcomes arrive, rather than being an
        opaque boolean.
        """
        status = await self._db().execute_query(
            """UPDATE unified.knowledge_transfers
               SET success      = $2,
                   completed_at = NOW(),
                   metadata     = COALESCE(metadata, '{}'::jsonb) || $3::jsonb
               WHERE transfer_id = $1""",
            (transfer_id, helped,
             json.dumps({"effectiveness_score": effectiveness,
                         "outcome_evidence": evidence})),
            commit=True,
        )

        # Credit the mappings the transfer was carried by. A transfer that
        # helped is evidence about the correspondences it used.
        mapping_ids = list(evidence.get("mapping_ids") or [])
        async with self._lock:
            for mapping_id in mapping_ids:
                mapping = self.cross_domain_mappings.get(mapping_id)
                if mapping is None:
                    continue
                uses = max(1, mapping.usage_count)
                helped_before = mapping.success_rate * (uses - 1)
                mapping.success_rate = (helped_before + (1.0 if helped else 0.0)) / uses
                await self._persist_mapping(mapping)

        logger.info(
            "Knowledge transfer %s resolved: helped=%s effectiveness=%.3f (%s)",
            transfer_id, helped, effectiveness, evidence.get("basis", "n/a"))
        return status is not None

    async def get_domain_statistics(self) -> Dict[str, Any]:
        """Get comprehensive statistics about the domain registry"""
        # LEARNED and DERIVED counted apart. The universal level is projected
        # from UniversalOntology on every load and is never persisted, so
        # folding it into one total reports 24 designed concepts as though
        # Torin had learned them -- and an operator reading a single number has
        # no way to tell which part of the graph came from experience.
        projected = sum(
            1 for d in self.domains.values() for c in d.concepts.values()
            if (c.properties or {}).get("source") == "universal_ontology")
        derived_domains = sum(
            1 for d in self.domains.values()
            if any((c.properties or {}).get("source") == "universal_ontology"
                   for c in d.concepts.values()))

        stats = {
            "total_domains": len(self.domains),
            "populated_domains": sum(1 for d in self.domains.values() if d.concepts),
            "empty_domains": len(self.unpopulated_domain_ids),
            "derived_domains": derived_domains,
            "domain_types": {},
            "total_concepts": 0,        # effective graph: learned + projected
            "learned_concepts": 0,      # persisted in unified.concepts
            "projected_concepts": projected,  # derived from the ontology
            "total_relations": 0,
            "total_knowledge": 0,
            "cross_domain_mappings": len(self.cross_domain_mappings),
            "knowledge_transfers": len(self.knowledge_transfers),
            "most_connected_domains": [],
            "largest_domains": []
        }
        
        # Domain type distribution
        for domain in self.domains.values():
            domain_type = domain.domain_type.value
            stats["domain_types"][domain_type] = stats["domain_types"].get(domain_type, 0) + 1
            stats["total_concepts"] += len(domain.concepts)
            stats["learned_concepts"] += sum(
                1 for c in domain.concepts.values()
                if (c.properties or {}).get("source") != "universal_ontology")
            stats["total_relations"] += len(domain.relations)
            stats["total_knowledge"] += len(domain.knowledge)
        
        # Most connected domains (by cross-domain mappings)
        domain_connections = defaultdict(int)
        for mapping in self.cross_domain_mappings.values():
            domain_connections[mapping.source_domain_id] += 1
            domain_connections[mapping.target_domain_id] += 1
        
        most_connected = sorted(domain_connections.items(), key=lambda x: x[1], reverse=True)[:5]
        stats["most_connected_domains"] = [
            {"domain_id": domain_id, "domain_name": self.domains[domain_id].name, "connections": count}
            for domain_id, count in most_connected if domain_id in self.domains
        ]
        
        # Largest domains (by concept count)
        largest = sorted(self.domains.values(), key=lambda x: len(x.concepts), reverse=True)[:5]
        stats["largest_domains"] = [
            {"domain_id": domain.domain_id, "domain_name": domain.name, "concept_count": len(domain.concepts)}
            for domain in largest
        ]
        
        return stats
    
    async def _rebuild_indexes(self):
        """Rebuild all indexes"""
        self.concept_index.clear()
        self.relation_index.clear()
        
        for domain in self.domains.values():
            await self._update_indexes_for_domain(domain)
    
    async def _update_indexes_for_domain(self, domain: Domain):
        """Update indexes for a specific domain"""
        # Concept index
        for concept in domain.concepts.values():
            self.concept_index[concept.name.lower()].add(domain.domain_id)
        
        # Relation index
        for relation in domain.relations.values():
            self.relation_index[relation.relation_type].add(domain.domain_id)
    
    async def _persist_domain(self, domain: Domain):
        """Persist a domain to unified.domains.

        The full Domain (concepts, relations, vocabulary, metrics) goes into the
        `metadata` jsonb column; the scalar columns stay queryable.
        """
        await self._db().execute_query(
            """INSERT INTO unified.domains
                   (domain_id, domain_name, description, metadata, last_accessed)
               VALUES ($1, $2, $3, $4::jsonb, NOW())
               ON CONFLICT (domain_id) DO UPDATE SET
                   domain_name   = EXCLUDED.domain_name,
                   description   = EXCLUDED.description,
                   metadata      = EXCLUDED.metadata,
                   last_accessed = NOW()""",
            (
                domain.domain_id,
                domain.name,
                domain.description,
                json.dumps(self._serialize_domain(domain)),
            ),
            commit=True,
        )

    async def _persist_mapping(self, mapping: CrossDomainMapping):
        """Persist a cross-domain mapping to unified.domain_mappings.

        `verified` carries the ontological verdict and MUST be written
        explicitly. It was omitted from the column list, so every row this
        method wrote took the column default (FALSE = refuted) no matter what
        the validator had decided. Both consumers -- _load_mappings here and
        UniversalDomainMaster._find_cross_domain_mappings -- select on
        `verified IS NULL OR verified IS TRUE`, so a mapping the validator had
        ACCEPTED was stored as rejected and became permanently unreadable,
        including by this registry's own loader on restart.
        """
        await self._db().execute_query(
            """INSERT INTO unified.domain_mappings
                   (mapping_id, source_domain, target_domain, source_concept,
                    target_concept, similarity_score, reasoning_strategy,
                    verified, confidence, metadata, created_at)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10::jsonb, NOW())
               ON CONFLICT (mapping_id) DO UPDATE SET
                   similarity_score = EXCLUDED.similarity_score,
                   verified         = EXCLUDED.verified,
                   confidence       = EXCLUDED.confidence,
                   metadata         = EXCLUDED.metadata""",
            (
                mapping.mapping_id,
                self._domain_key(mapping.source_domain_id),
                self._domain_key(mapping.target_domain_id),
                mapping.source_concept_id,
                mapping.target_concept_id,
                mapping.strength,
                str(mapping.mapping_type),
                mapping.validated,  # None | True | False, passed through as-is
                mapping.confidence,
                json.dumps(self._serialize_mapping(mapping)),
            ),
            commit=True,
        )

    async def _persist_transfer(self, transfer: KnowledgeTransfer):
        """Persist a knowledge transfer to unified.knowledge_transfers.

        ONE ROW PER TRANSFERRED CONCEPT. The table's grain is a single concept
        (`concept`, `concept_type` are singular and NOT NULL) and the sibling
        writer, UniversalDomainMaster._execute_transfer, writes it that way.
        This method wrote one row per operation with `concept = ""` and omitted
        `concept_type` entirely -- a NOT NULL column with no default -- so every
        insert raised NotNullViolation, which create_knowledge_transfer caught
        and turned into `return False`. The table stayed empty while callers
        were told the transfer succeeded.

        KnowledgeTransfer models an operation over many concepts, so it is
        expanded here. The operation stays recoverable: each row's metadata
        carries the whole serialized transfer under a shared `operation_id`.
        """
        if not transfer.target_knowledge_ids:
            raise ValueError(
                f"KnowledgeTransfer {transfer.transfer_id} has no target concepts; "
                "there is nothing to record as transferred")

        target_domain = self.domains.get(transfer.target_domain_id)
        payload = json.dumps({**self._serialize_transfer(transfer),
                              "operation_id": transfer.transfer_id})

        for concept_id in transfer.target_knowledge_ids:
            concept = target_domain.concepts.get(concept_id) if target_domain else None
            if concept is None:
                raise KeyError(
                    f"KnowledgeTransfer {transfer.transfer_id} names target concept "
                    f"{concept_id!r}, which is not in domain "
                    f"{transfer.target_domain_id!r}")
            await self._db().execute_query(
                """INSERT INTO unified.knowledge_transfers
                       (transfer_id, source_domain, target_domain, concept,
                        concept_type, transfer_method, success, metadata,
                        created_at, completed_at)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb, $9, $10)
                   ON CONFLICT (transfer_id) DO UPDATE SET
                       success      = EXCLUDED.success,
                       metadata     = EXCLUDED.metadata,
                       completed_at = EXCLUDED.completed_at""",
                (
                    f"{transfer.transfer_id}:{concept_id}",
                    self._domain_key(transfer.source_domain_id),
                    self._domain_key(transfer.target_domain_id),
                    concept.name,
                    concept.concept_type.value,
                    str(transfer.transfer_type),
                    # No outcome yet is NOT a failed transfer. NULL means unresolved.
                    getattr(transfer, "success", None),
                    payload,
                    transfer.initiated_at,
                    transfer.completed_at,
                ),
                commit=True,
            )
    
    def _serialize_domain(self, domain: Domain) -> Dict[str, Any]:
        """Serialize domain to dict for storage"""
        return {
            "domain_id": domain.domain_id,
            "name": domain.name,
            "domain_type": domain.domain_type.value,
            "description": domain.description,
            "scope": domain.scope,
            "boundaries": domain.boundaries,
            "concepts": {cid: self._serialize_concept(c) for cid, c in domain.concepts.items()},
            "relations": {rid: self._serialize_relation(r) for rid, r in domain.relations.items()},
            "knowledge": {kid: self._serialize_knowledge(k) for kid, k in domain.knowledge.items()},
            "parent_domains": list(domain.parent_domains),
            "child_domains": list(domain.child_domains),
            "related_domains": domain.related_domains,
            "core_principles": domain.core_principles,
            "methodologies": domain.methodologies,
            "vocabulary": domain.vocabulary,
            "complexity_score": domain.complexity_score,
            "formalization_level": domain.formalization_level,
            "maturity_score": domain.maturity_score,
            "created_at": domain.created_at.isoformat(),
            "updated_at": domain.updated_at.isoformat() if domain.updated_at else None
        }
    
    def _serialize_concept(self, concept: DomainConcept) -> Dict[str, Any]:
        """Serialize concept to dict"""
        return {
            "concept_id": concept.concept_id,
            "name": concept.name,
            "domain_id": concept.domain_id,
            "concept_type": concept.concept_type.value,
            "description": concept.description,
            "properties": concept.properties,
            "attributes": concept.attributes,
            "parent_concepts": list(concept.parent_concepts),
            "child_concepts": list(concept.child_concepts),
            "related_concepts": list(concept.related_concepts),
            "analogous_concepts": concept.analogous_concepts,
            "semantic_weight": concept.semantic_weight,
            "abstraction_level": concept.abstraction_level,
            "complexity_score": concept.complexity_score,
            "created_at": concept.created_at.isoformat(),
            "updated_at": concept.updated_at.isoformat() if concept.updated_at else None,
            "usage_count": concept.usage_count,
            "relevance_score": concept.relevance_score
        }
    
    def _serialize_relation(self, relation: DomainRelation) -> Dict[str, Any]:
        """Serialize relation to dict"""
        return {
            "relation_id": relation.relation_id,
            "source_concept_id": relation.source_concept_id,
            "target_concept_id": relation.target_concept_id,
            "relation_type": relation.relation_type,
            "strength": relation.strength,
            "directionality": relation.directionality,
            "confidence": relation.confidence,
            "context": relation.context,
            "domain_id": relation.domain_id,
            "created_at": relation.created_at.isoformat()
        }
    
    def _serialize_knowledge(self, knowledge: DomainKnowledge) -> Dict[str, Any]:
        """Serialize knowledge to dict"""
        return {
            "knowledge_id": knowledge.knowledge_id,
            "domain_id": knowledge.domain_id,
            "knowledge_type": knowledge.knowledge_type,
            "title": knowledge.title,
            "content": knowledge.content,
            "summary": knowledge.summary,
            "concepts": knowledge.concepts,
            "relations": knowledge.relations,
            "tags": list(knowledge.tags),
            "source": knowledge.source,
            "confidence": knowledge.confidence,
            "importance": knowledge.importance,
            "transferable_patterns": knowledge.transferable_patterns,
            "applicable_domains": list(knowledge.applicable_domains),
            "created_at": knowledge.created_at.isoformat(),
            "last_accessed": knowledge.last_accessed.isoformat() if knowledge.last_accessed else None
        }
    
    def _serialize_mapping(self, mapping: CrossDomainMapping) -> Dict[str, Any]:
        """Serialize mapping to dict"""
        return {
            "mapping_id": mapping.mapping_id,
            "source_domain_id": mapping.source_domain_id,
            "target_domain_id": mapping.target_domain_id,
            "source_concept_id": mapping.source_concept_id,
            "target_concept_id": mapping.target_concept_id,
            "mapping_type": mapping.mapping_type,
            "strength": mapping.strength,
            "confidence": mapping.confidence,
            "bidirectional": mapping.bidirectional,
            "transformation_rules": mapping.transformation_rules,
            "context_requirements": mapping.context_requirements,
            "validated": mapping.validated,
            "validation_score": mapping.validation_score,
            "usage_count": mapping.usage_count,
            "success_rate": mapping.success_rate,
            "created_at": mapping.created_at.isoformat(),
            "last_used": mapping.last_used.isoformat() if mapping.last_used else None
        }
    
    def _serialize_transfer(self, transfer: KnowledgeTransfer) -> Dict[str, Any]:
        """Serialize transfer to dict"""
        return {
            "transfer_id": transfer.transfer_id,
            "source_domain_id": transfer.source_domain_id,
            "target_domain_id": transfer.target_domain_id,
            "source_knowledge_ids": transfer.source_knowledge_ids,
            "target_knowledge_ids": transfer.target_knowledge_ids,
            "transfer_type": transfer.transfer_type,
            "success_probability": transfer.success_probability,
            "concept_mappings": transfer.concept_mappings,
            "transferred_concepts": transfer.transferred_concepts,
            "new_insights": transfer.new_insights,
            "validation_results": transfer.validation_results,
            "effectiveness_score": transfer.effectiveness_score,
            "novelty_score": transfer.novelty_score,
            "initiated_at": transfer.initiated_at.isoformat(),
            "completed_at": transfer.completed_at.isoformat() if transfer.completed_at else None
        }
    
    def _deserialize_domain(self, data: Dict[str, Any]) -> Domain:
        """Deserialize domain from dict"""
        from datetime import datetime
        
        domain = Domain(
            domain_id=data["domain_id"],
            name=data["name"],
            domain_type=DomainType(data["domain_type"]),
            description=data["description"],
            scope=data.get("scope", ""),
            boundaries=data.get("boundaries", {}),
            parent_domains=set(data.get("parent_domains", [])),
            child_domains=set(data.get("child_domains", [])),
            related_domains=data.get("related_domains", {}),
            core_principles=data.get("core_principles", []),
            methodologies=data.get("methodologies", []),
            vocabulary=data.get("vocabulary", {}),
            complexity_score=data.get("complexity_score", 0.5),
            formalization_level=data.get("formalization_level", 0.5),
            maturity_score=data.get("maturity_score", 0.5),
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]) if data.get("updated_at") else None
        )
        
        # Deserialize concepts, relations, and knowledge
        for cid, cdata in data.get("concepts", {}).items():
            domain.concepts[cid] = self._deserialize_concept(cdata)
        
        for rid, rdata in data.get("relations", {}).items():
            domain.relations[rid] = self._deserialize_relation(rdata)
            
        for kid, kdata in data.get("knowledge", {}).items():
            domain.knowledge[kid] = self._deserialize_knowledge(kdata)
        
        return domain
    
    def _deserialize_concept(self, data: Dict[str, Any]) -> DomainConcept:
        """Deserialize concept from dict"""
        from datetime import datetime
        from .domain_types import ConceptType
        
        return DomainConcept(
            concept_id=data["concept_id"],
            name=data["name"],
            domain_id=data["domain_id"],
            concept_type=ConceptType(data["concept_type"]),
            description=data["description"],
            properties=data.get("properties", {}),
            attributes=data.get("attributes", {}),
            parent_concepts=set(data.get("parent_concepts", [])),
            child_concepts=set(data.get("child_concepts", [])),
            related_concepts=set(data.get("related_concepts", [])),
            analogous_concepts=data.get("analogous_concepts", {}),
            semantic_weight=data.get("semantic_weight", 1.0),
            abstraction_level=data.get("abstraction_level", 0.5),
            complexity_score=data.get("complexity_score", 0.5),
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]) if data.get("updated_at") else None,
            usage_count=data.get("usage_count", 0),
            relevance_score=data.get("relevance_score", 1.0)
        )
    
    def _deserialize_relation(self, data: Dict[str, Any]) -> DomainRelation:
        """Deserialize relation from dict"""
        from datetime import datetime
        
        return DomainRelation(
            relation_id=data["relation_id"],
            source_concept_id=data["source_concept_id"],
            target_concept_id=data["target_concept_id"],
            relation_type=data["relation_type"],
            strength=data.get("strength", 1.0),
            directionality=data.get("directionality", "bidirectional"),
            confidence=data.get("confidence", 1.0),
            context=data.get("context", {}),
            domain_id=data.get("domain_id", ""),
            created_at=datetime.fromisoformat(data["created_at"])
        )
    
    def _deserialize_knowledge(self, data: Dict[str, Any]) -> DomainKnowledge:
        """Deserialize knowledge from dict"""
        from datetime import datetime
        
        return DomainKnowledge(
            knowledge_id=data["knowledge_id"],
            domain_id=data["domain_id"],
            knowledge_type=data["knowledge_type"],
            title=data["title"],
            content=data["content"],
            summary=data.get("summary", ""),
            concepts=data.get("concepts", []),
            relations=data.get("relations", []),
            tags=set(data.get("tags", [])),
            source=data.get("source", ""),
            confidence=data.get("confidence", 1.0),
            importance=data.get("importance", 1.0),
            transferable_patterns=data.get("transferable_patterns", []),
            applicable_domains=set(data.get("applicable_domains", [])),
            created_at=datetime.fromisoformat(data["created_at"]),
            last_accessed=datetime.fromisoformat(data["last_accessed"]) if data.get("last_accessed") else None
        )
    
    def _mapping_from_row(self, row) -> CrossDomainMapping:
        """Build a mapping from the table's structured columns, for rows the
        cross-domain reasoner wrote without a metadata blob."""
        from datetime import datetime
        return CrossDomainMapping(
            mapping_id=row["mapping_id"],
            source_domain_id=str(row["source_domain"]),
            target_domain_id=str(row["target_domain"]),
            source_concept_id=str(row["source_concept"]),
            target_concept_id=str(row["target_concept"]),
            mapping_type=str(row["reasoning_strategy"] or "analogical"),
            strength=float(row["similarity_score"] or 0.0),
            confidence=float(row["confidence"] if row["confidence"] is not None
                             else row["similarity_score"] or 0.0),
            validated=row["verified"],
            created_at=datetime.now(),
        )

    def _deserialize_mapping(self, data: Dict[str, Any]) -> CrossDomainMapping:
        """Deserialize mapping from dict"""
        from datetime import datetime
        
        return CrossDomainMapping(
            mapping_id=data["mapping_id"],
            source_domain_id=data["source_domain_id"],
            target_domain_id=data["target_domain_id"],
            source_concept_id=data["source_concept_id"],
            target_concept_id=data["target_concept_id"],
            mapping_type=data["mapping_type"],
            strength=data.get("strength", 1.0),
            confidence=data.get("confidence", 1.0),
            bidirectional=data.get("bidirectional", True),
            transformation_rules=data.get("transformation_rules", {}),
            context_requirements=data.get("context_requirements", {}),
            validated=data.get("validated"),  # absent == unjudged, not refuted
            validation_score=data.get("validation_score", 0.0),
            usage_count=data.get("usage_count", 0),
            success_rate=data.get("success_rate", 0.0),
            created_at=datetime.fromisoformat(data["created_at"]),
            last_used=datetime.fromisoformat(data["last_used"]) if data.get("last_used") else None
        )


# Singleton instance
_domain_registry = None


def get_domain_registry() -> DomainRegistry:
    """Get global domain registry instance (singleton)"""
    global _domain_registry
    if _domain_registry is None:
        _domain_registry = DomainRegistry()
    return _domain_registry