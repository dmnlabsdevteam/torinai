#!/usr/bin/env python3
"""
Universal Domain Master
=======================
Cross-domain orchestration and knowledge integration system

Purpose:
- Coordinate between multiple knowledge domains
- Execute cross-domain queries with analogical reasoning
- Manage knowledge transfer between domains
- Integrate with Domain Registry and Universal Ontology systems

Features:
- 15 knowledge domains (scientific, technical, business, creative, etc.)
- 7 reasoning strategies (analogical, structural, functional, etc.)
- PostgreSQL persistence (unified.*) for domain relationships
- Tool-based architecture (not autonomous orchestrator)
- Domain-to-domain knowledge mapping
"""

import logging
import asyncio
import uuid
import json
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional, Set, Tuple
from datetime import datetime
from enum import Enum

logger = logging.getLogger(__name__)


# The 15 knowledge domains — imported, not redeclared.
#
# A byte-identical 15-member copy lived here. Identity-based equality made it a
# silent shadow: a registry DomainType reaching this module's _resolve failed
# `isinstance(dt, DomainType)`, fell through to `str(dt)`, and arrived at the
# resolver as 'DomainType.PHYSICAL' rather than 'physical' — an unresolvable
# reference produced by two enums that print the same thing.
#
# domain_types owns it: Domain.domain_type is typed by it and the registry
# builds its category/field membership graph from it.
from core.domain.domain_types import DomainType  # noqa: E402


# THE 7 cross-domain reasoning strategies — imported, not redeclared.
#
# This module defined its own ReasoningStrategy enum with byte-identical members
# to the one in cross_domain_reasoner. Enum equality is identity-based, so
# `master.ReasoningStrategy.ANALOGICAL == reasoner.ReasoningStrategy.ANALOGICAL`
# was False. _generate_mappings passes this value into ReasoningContext, and the
# reasoner looks the strategy up in a dict keyed by ITS enum:
#
#     strategy_func = self.strategies.get(context.strategy)   -> None
#     return ReasoningResult(success=False,
#                            new_insights=["Unsupported reasoning strategy"])
#
# So every one of the seven strategies was unreachable through the master, and
# the failure surfaced as success=False with confidence 0.0 — indistinguishable
# from "these domains have nothing in common". Verified by direct execution.
#
# The reasoner owns the strategies (it maps each member to a method), so it owns
# the vocabulary that names them.
from core.domain.cross_domain_reasoner import ReasoningStrategy  # noqa: E402


# Concept vocabulary — imported, not redeclared.
#
# This module defined a second 12-member ConceptType that had DIVERGED from
# domain_types.ConceptType: `relationship`/`structure` here versus
# `relation`/`rule` there. Ten members overlapped, so a concept typed by one was
# untypeable by the other -- the same defect that made all seven reasoning
# strategies unreachable, but in the vocabulary itself.
#
# domain_types owns it: DomainConcept is typed by it, the registry deserialises
# through it, and universal_ontology maps all twelve members. The two members
# unique to this copy had zero uses repo-wide.
from core.domain.domain_types import ConceptType  # noqa: E402


@dataclass
class CrossDomainQuery:
    """Query spanning multiple domains"""
    query_id: str
    query_text: str
    source_domains: List[DomainType]
    target_domains: List[DomainType]
    reasoning_strategy: ReasoningStrategy = ReasoningStrategy.ANALOGICAL

    # Query parameters
    max_results: int = 10
    min_similarity: float = 0.7
    include_explanations: bool = True

    # Execution context
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class KnowledgeTransferRequest:
    """Request to transfer knowledge from source to target domain"""
    transfer_id: str
    source_domain: DomainType
    target_domain: DomainType
    concept: str
    concept_type: ConceptType

    # Transfer parameters
    transfer_method: ReasoningStrategy = ReasoningStrategy.ANALOGICAL
    preserve_structure: bool = True
    adapt_to_context: bool = True

    # Metadata
    requested_by: str = "system"
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class DomainMapping:
    """Mapping between concepts in different domains"""
    mapping_id: str
    # Canonical registry domain ids (the FIELD: "physics"), not DomainType
    # categories. The field is the identity the concepts actually belong to;
    # storing the category here would discard which field produced the mapping
    # and make the row unreadable back into a domain.
    source_domain: str
    target_domain: str
    source_concept: str
    target_concept: str

    # Mapping metadata
    similarity_score: float
    reasoning_strategy: ReasoningStrategy
    # TRI-STATE: None = proposed and untested, True = accepted, False = refuted.
    # Declared `bool = False` while _generate_mappings passes None and the
    # reader below hands back a nullable column -- so the annotation described a
    # type this field never held, and any construction omitting it silently
    # marked its own mapping refuted.
    verified: Optional[bool] = None
    confidence: float = 0.0

    created_at: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class DomainIntegrationResult:
    """Result from domain integration operation"""
    query_id: str
    success: bool

    # Results
    mappings: List[DomainMapping] = field(default_factory=list)
    insights: List[str] = field(default_factory=list)
    explanations: List[str] = field(default_factory=list)

    # Performance metrics
    execution_time: float = 0.0
    domains_queried: int = 0
    mappings_found: int = 0

    error: Optional[str] = None
    timestamp: datetime = field(default_factory=datetime.now)


class DeficitType(Enum):
    """The kind of epistemic deficiency behind a goal the substrate could not plan.

    Ordered from the most upstream (a symbol with no meaning) to the least
    (deficient but not localised). When several goal conditions fail for
    different reasons, the most upstream one is the blocker to act on.

    This is a MEASUREMENT the domain authority makes about a domain's knowledge
    state -- a sibling of competence, controllability, and learning progress. It
    is NOT a decision about what to do: the disposition (explore / replan /
    disengage) belongs to the AppraisalSystem, which this feeds through the
    signals in `_DEFICIT_SIGNALS`. The type additionally carries WHICH learning
    operation a chosen exploration should run -- the one thing appraisal does not
    decide -- so it can ride an exploration target as a routing key.
    """

    CONCEPT_GAP = "concept_gap"            # the goal predicate is unrepresented
    OPERATOR_GAP = "operator_gap"          # no action produces the predicate
    CAUSAL_GAP = "causal_gap"              # a hypothesis produces it, unvalidated
    BINDING_GAP = "binding_gap"            # validated, but no tool to act it
    RELATION_GAP = "relation_gap"          # blocked on an unreachable relation
    PREREQUISITE_GAP = "prerequisite_gap"  # blocked on an unreachable state
    OBSERVATION_GAP = "observation_gap"    # the world cannot be read
    WORLD_PREVENTS = "world_prevents"      # proved impossible; no learning helps
    UNKNOWN_GAP = "unknown_gap"            # deficient, not yet localised


#: Upstream-first priority. A goal blocked by several deficits is blocked by its
#: most upstream one -- fixing a downstream gap cannot help while an upstream one
#: stands. WORLD_PREVENTS is absolute (a proof), so it outranks everything.
_DEFICIT_PRIORITY: List[DeficitType] = [
    DeficitType.WORLD_PREVENTS,
    DeficitType.OBSERVATION_GAP,
    DeficitType.CONCEPT_GAP,
    DeficitType.OPERATOR_GAP,
    DeficitType.CAUSAL_GAP,
    DeficitType.BINDING_GAP,
    DeficitType.RELATION_GAP,
    DeficitType.PREREQUISITE_GAP,
    DeficitType.UNKNOWN_GAP,
]

#: How each deficit reads AS A MEASUREMENT the AppraisalSystem consumes: the
#: value of learning more here (epistemic opportunity, 0..1) and the causal
#: attribution (an OutcomeClass string, honouring the credit invariant -- a
#: learnable gap is the substrate's own repertoire and moves competence; a world
#: proof or a missing observer/binding is not its strategy's fault and must not).
#: This is deliberately NOT a table of actions (explore/replan/...): those are
#: appraisal's to derive from these signals. Kept here, with the measurement.
_DEFICIT_SIGNALS: Dict[DeficitType, Tuple[float, str]] = {
    DeficitType.CONCEPT_GAP: (0.9, "strategy_failure"),
    DeficitType.OPERATOR_GAP: (0.9, "strategy_failure"),
    DeficitType.CAUSAL_GAP: (0.8, "strategy_failure"),
    DeficitType.RELATION_GAP: (0.7, "strategy_failure"),
    DeficitType.PREREQUISITE_GAP: (0.7, "strategy_failure"),
    DeficitType.BINDING_GAP: (0.3, "infrastructure_failure"),
    DeficitType.OBSERVATION_GAP: (0.1, "infrastructure_failure"),
    DeficitType.WORLD_PREVENTS: (0.0, "external_failure"),
    DeficitType.UNKNOWN_GAP: (0.4, "indeterminate"),
}


class LearningOperation(Enum):
    """The operation a deficit calls for -- the one thing appraisal does NOT
    decide. Appraisal owns the disposition (explore / replan / disengage); once
    it favours learning, WHICH operation follows from the deficit KIND, not from
    disposition. This is the routing key a deficit carries.

    Only the first three are autonomous, model-free operations the substrate can
    run now (all through the always-online explorer). ACHIEVE_PREREQUISITE
    recurses to the intermediate it lacks. ESCALATE is the honest answer when the
    deficiency needs input the substrate cannot self-supply (a relation from
    another domain, a concept proposal, a tool binding, an observer) -- it is not
    a stubbed operation, it is the substrate correctly declining to invent one.
    DISENGAGE is a proved dead end.
    """

    LEARN_OPERATOR = "learn_operator"              # explore for an action producing it
    VALIDATE_CAUSE = "validate_cause"              # contrastives to confirm a hypothesis
    PROBE = "probe"                                # broad exploration to localise
    ACHIEVE_PREREQUISITE = "achieve_prerequisite"  # reach the missing precondition first
    TRANSFER_RELATION = "transfer_relation"        # project the relation from a source domain
    ESCALATE = "escalate"                          # needs input the substrate cannot supply
    DISENGAGE = "disengage"                        # no learning is justified


#: deficit KIND -> the learning operation it calls for. RELATION/CONCEPT/BINDING/
#: OBSERVATION all ESCALATE, but for DISTINCT reasons the deficit_type preserves;
#: the operation coarsens where the honest response is the same ("needs external
#: input"), while the diagnosis stays specific.
_DEFICIT_OPERATION: Dict["DeficitType", "LearningOperation"] = {
    DeficitType.OPERATOR_GAP: LearningOperation.LEARN_OPERATOR,
    DeficitType.CAUSAL_GAP: LearningOperation.VALIDATE_CAUSE,
    DeficitType.PREREQUISITE_GAP: LearningOperation.ACHIEVE_PREREQUISITE,
    DeficitType.RELATION_GAP: LearningOperation.TRANSFER_RELATION,
    DeficitType.CONCEPT_GAP: LearningOperation.ESCALATE,
    DeficitType.BINDING_GAP: LearningOperation.ESCALATE,
    DeficitType.OBSERVATION_GAP: LearningOperation.ESCALATE,
    DeficitType.WORLD_PREVENTS: LearningOperation.DISENGAGE,
    DeficitType.UNKNOWN_GAP: LearningOperation.PROBE,
}


@dataclass
class EpistemicDeficit:
    """A typed account of why a goal is unreachable, with its evidence.

    Produced by the domain authority; consumed as a measurement (never a
    decision). `target_predicate` is the goal predicate the deficiency is about
    -- the one the substrate must learn to produce, observe, or represent.
    `evidence` records the structural facts the type was read from, so the
    diagnosis is inspectable rather than asserted.
    """

    domain_id: str
    deficit_type: DeficitType
    target_predicate: Optional[str] = None
    confidence: float = 1.0
    evidence: Dict[str, Any] = field(default_factory=dict)

    @property
    def epistemic_opportunity(self) -> float:
        """The value of learning more here -- a property of the deficit KIND."""
        return _DEFICIT_SIGNALS[self.deficit_type][0]

    @property
    def outcome_class(self) -> str:
        """The causal attribution this failure carries, as an OutcomeClass value."""
        return _DEFICIT_SIGNALS[self.deficit_type][1]

    @property
    def operation(self) -> "LearningOperation":
        """The learning operation this deficit calls for -- the routing key."""
        return _DEFICIT_OPERATION[self.deficit_type]

    @property
    def remedy_reason(self) -> str:
        """Why an ESCALATE deficit needs input the substrate cannot self-supply.

        Distinct per kind even though several share the ESCALATE operation, so an
        escalation carries what it is actually waiting for.
        """
        return {
            DeficitType.RELATION_GAP:
                "needs the missing relation from a source domain (transfer, not self-supplied)",
            DeficitType.CONCEPT_GAP:
                "needs a concept proposal for an unrepresented predicate (model-optional)",
            DeficitType.BINDING_GAP:
                "needs a tool binding for the operator's action",
            DeficitType.OBSERVATION_GAP:
                "needs an observation capability for the domain",
        }.get(self.deficit_type, "needs input the substrate cannot supply from here")

    def appraisal_signals(self) -> Dict[str, Any]:
        """The signals the AppraisalSystem consumes for this failure.

        `epistemic` carries the learning opportunity as rising uncertainty
        (open questions remain); `outcome_class` carries the attribution. The
        AppraisalSystem -- not this method -- turns them into disposition.
        """
        return {
            "epistemic": {"uncertainty_increase": self.epistemic_opportunity},
            "outcome_class": self.outcome_class,
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "domain_id": self.domain_id,
            "deficit_type": self.deficit_type.value,
            "target_predicate": self.target_predicate,
            "confidence": self.confidence,
            "epistemic_opportunity": self.epistemic_opportunity,
            "outcome_class": self.outcome_class,
            "operation": self.operation.value,
            "evidence": self.evidence,
        }


class UniversalDomainMaster:
    """
    Universal Domain Master - Cross-Domain Orchestration Tool

    Singleton tool that coordinates cross-domain knowledge integration
    and reasoning. Enables agents to execute queries spanning multiple
    knowledge domains with intelligent reasoning strategies.

    Architecture:
    - Tool-based interface (not autonomous orchestrator)
    - Integration with Domain Registry
    - PostgreSQL persistence (unified.*) for domain relationships
    - 15 domain types with 7 reasoning strategies
    - Concept mapping and knowledge transfer

    Features:
    - Cross-domain query execution
    - Knowledge transfer orchestration
    - Domain-to-domain mapping
    - Analogical reasoning
    - Concept alignment
    """

    # Bounded cognition: a category reference expands to its member fields, and
    # a category-vs-category query is |sources| x |targets| reasoning calls. Cap
    # the expansion per side; the resolver ranks by concept overlap first and
    # logs whatever it drops, so the bound is visible rather than silent.
    MAX_RESOLVED_FIELDS: int = 4

    _instance: Optional['UniversalDomainMaster'] = None

    def __new__(cls, *args, **kwargs):
        """Singleton pattern"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        # Prevent re-initialization
        if hasattr(self, '_initialized'):
            return

        self.db = None  # Will be set to TorinUnifiedDatabase in initialize()

        # Domain registry cache
        self.domain_cache: Dict[DomainType, Dict[str, Any]] = {}
        self.mapping_cache: Dict[Tuple[DomainType, DomainType], List[DomainMapping]] = {}

        # Statistics
        self.stats = {
            'total_queries': 0,
            'successful_queries': 0,
            'failed_queries': 0,
            'total_transfers': 0,
            'total_mappings': 0
        }

        self._initialized = True
        logger.info("🧰 UniversalDomainMaster initialized as Singleton tool (not autonomous orchestrator)")

    async def initialize(self):
        """Initialize database and load domain registry"""
        try:
            # Get PostgreSQL database connection
            from core.database import get_database_manager
            self.db = get_database_manager()

            # Ensure database is initialized
            if not self.db.initialized:
                await self.db.initialize()

            # Create tables (idempotent - only creates if not exists)
            await self._create_tables()

            # Load domain definitions
            await self._load_domain_registry()

            logger.info("✓ Universal Domain Master initialized successfully")

        except Exception as e:
            logger.error(f"Failed to initialize Universal Domain Master: {e}")
            raise

    async def _create_tables(self):
        """Create database tables (PostgreSQL - tables already exist in schema)"""
        # Tables are created in postgres_schemas.sql:
        # - unified.domains
        # - unified.domain_mappings
        # - unified.knowledge_transfers
        # - unified.cross_domain_queries
        # This method is kept for compatibility but does nothing
        pass

    async def _load_domain_registry(self):
        """Load domain definitions from database"""
        if not self.db:
            return

        # Check if domains exist
        count_result = await self.db.execute_query(
            "SELECT COUNT(*) as count FROM unified.domains",
            fetch_all=True
        )
        count = count_result[0]['count'] if count_result else 0

        if count == 0:
            # Initialize default domains
            await self._initialize_default_domains()

        # Load into cache
        rows = await self.db.execute_query(
            "SELECT domain_id, domain_name, description, metadata FROM unified.domains",
            fetch_all=True
        )

        for row in rows:
            # Parse domain_id to get domain_type (format: "domain_scientific")
            domain_id = row['domain_id']
            domain_type_str = domain_id.replace('domain_', '')
            try:
                domain_type = DomainType(domain_type_str)
                self.domain_cache[domain_type] = {
                    'domain_id': row['domain_id'],
                    'domain_name': row['domain_name'],
                    'description': row['description'],
                    'concepts': []  # Can be extracted from metadata JSONB if needed
                }
            except ValueError:
                logger.warning(f"Unknown domain type in database: {domain_type_str}")

        logger.info(f"Loaded {len(self.domain_cache)} domains into cache")

    async def _initialize_default_domains(self):
        """RETIRED: seeding the DomainType categories into unified.domains.

        This wrote all 15 DomainType values as domain rows on every startup
        (ON CONFLICT DO NOTHING, so the rows carried their original 2026-02-13
        timestamps and looked historical rather than re-asserted). Verified
        against the live registry, nothing read them:

          * a category reference resolves through the FIELD domains' own
            domain_type -- resolve_domain_reference("physical") still returns
            physics/fluid_mechanics/mechanics/... with every category row
            removed
          * the one exception, domain_abstract, is a precondition of
            DomainRegistry._project_universal_level, which now provides it
            itself rather than depending on this module's startup order

        What they did do is make 15 concept-less rows count as registered
        domains, so the registry reported "15 empty domains" beside its 18 real
        fields and every category looked like a knowledge domain holding
        nothing. A domain is something Torin has learned; a DomainType is a
        classification of one. Persisting the classifications as domains put
        both in one table with no way to tell them apart.

        Left as a no-op rather than deleted so the existing rows are not
        removed implicitly -- dropping them is a data decision, not a code one.
        """
        return

    async def _initialize_default_domains_RETIRED(self):
        if not self.db:
            return

        default_domains = [
            (DomainType.SCIENTIFIC, "Scientific Domain", "Natural sciences and research"),
            (DomainType.TECHNICAL, "Technical Domain", "Engineering and technology"),
            (DomainType.BUSINESS, "Business Domain", "Commerce and economics"),
            (DomainType.CREATIVE, "Creative Domain", "Arts and creative expression"),
            (DomainType.SOCIAL, "Social Domain", "Human interaction and society"),
            (DomainType.PHYSICAL, "Physical Domain", "Physical world and materials"),
            (DomainType.ABSTRACT, "Abstract Domain", "Abstract concepts and theory"),
            (DomainType.MATHEMATICAL, "Mathematical Domain", "Mathematics and logic"),
            (DomainType.LINGUISTIC, "Linguistic Domain", "Language and communication"),
            (DomainType.TEMPORAL, "Temporal Domain", "Time and sequence"),
            (DomainType.SPATIAL, "Spatial Domain", "Space and location"),
            (DomainType.CAUSAL, "Causal Domain", "Cause and effect relationships"),
            (DomainType.ETHICAL, "Ethical Domain", "Ethics and morality"),
            (DomainType.AESTHETIC, "Aesthetic Domain", "Beauty and aesthetics"),
            (DomainType.PRACTICAL, "Practical Domain", "Practical applications")
        ]

        for domain_type, name, description in default_domains:
            await self.db.execute_query(
                """INSERT INTO unified.domains (domain_id, domain_name, description)
                   VALUES ($1, $2, $3)
                   ON CONFLICT (domain_id) DO NOTHING""",
                (f"domain_{domain_type.value}", name, description),
                commit=True
            )

    # ==================================================================
    # DOMAIN CREATION & DISCOVERY — the single authority
    #
    # A domain is something the substrate has learned or can act in. A
    # DomainType merely classifies one. Nothing in the codebase created a
    # domain at runtime: `register_domain` had zero callers and the only rows
    # in unified.domains were the 15 DomainType categories seeded once. So the
    # substrate could learn operators in a domain forever and that domain never
    # became a thing the rest of the system could refer to. These methods are
    # where that changes, and they live HERE because the Universal Domain Master
    # is the authority for the domain system -- creation included.
    # ==================================================================

    async def _registry(self):
        """The domain store this authority writes through.

        The registry owns persistence and indexing; the Master owns the
        DECISION to bring a domain into existence. One store, one authority --
        not a second cache of domains keyed by DomainType, which is what
        `domain_cache` was and why classifications and learned domains were
        indistinguishable.
        """
        from core.domain.domain_registry import get_domain_registry
        registry = get_domain_registry()
        if not registry.initialized:
            await registry.initialize()
        return registry

    def is_learned_domain(self, domain) -> bool:
        """A domain the substrate actually has capability in, not a DomainType
        category seeded into the same table."""
        return bool((getattr(domain, "boundaries", None) or {}).get("origin") == "learned")

    async def ensure_domain(
        self, domain_id: str, *, name: Optional[str] = None,
        description: str = "", domain_type: Optional[DomainType] = None,
    ) -> "Any":
        """Register an operational domain as a first-class Domain, idempotently.

        THE SINGLE AUTHORITY for a domain coming into existence. When the
        substrate first has real capability in a domain -- a binding, a learned
        operator, grounded evidence -- this makes that domain something beliefs,
        exploration, cross-domain transfer and concepts can all refer to by one
        identity.

        Idempotent: an already-registered domain is returned unchanged. This is
        the first caller `DomainRegistry.register_domain` has ever had; routing
        every creation through here keeps one account of what domains exist.
        """
        from core.domain.domain_types import Domain

        registry = await self._registry()
        existing = registry.domains.get(domain_id)
        if existing is not None:
            return existing

        # Classify only if not told. A learned domain is ABSTRACT until it earns
        # a sharper type -- the same honest default the concept loader uses for
        # an unmapped field, rather than guessing.
        if domain_type is None:
            field = domain_id.replace("domain_", "")
            domain_type = registry._FIELD_TO_DOMAIN_TYPE.get(field, DomainType.ABSTRACT)

        domain = Domain(
            domain_id=domain_id,
            name=name or domain_id.replace("_", " ").strip().title() or domain_id,
            domain_type=domain_type,
            description=description or (
                f"Operational domain the substrate acts and learns in: {domain_id}"),
            # MARK IT LEARNED so it is never confused with a DomainType category
            # in the same table -- the distinction the retired seeder's own note
            # said nothing recorded.
            boundaries={"origin": "learned"},
            maturity_score=0.1,  # newly discovered; competence is low
        )
        await registry.register_domain(domain)
        # A domain the substrate has just discovered is one it is not yet
        # competent in. Record that as an epistemic belief at maximum
        # uncertainty so the domain SURFACES in the epistemic engine's unstable
        # regions -- which is what intrinsic motivation reads to choose what to
        # explore. Exploration then flows here through the designed motivation
        # system, not a bespoke selector.
        try:
            await self.ensure_competence_belief(domain_id)
        except Exception as e:
            from core.capability import raise_if_structural
            raise_if_structural(e, "universal_domain_master.ensure_domain.belief")
            logger.info("competence belief for %s deferred: %s", domain_id, e)
        logger.info("UDM registered operational domain %s (type=%s)",
                    domain_id, domain_type.value)
        return domain

    # ── DOMAIN COMPETENCE AS AN EPISTEMIC BELIEF ──────────────────────────
    # Operator-learning competence per domain is tracked as a belief so the
    # SAME intrinsic-motivation machinery that chooses every other exploration
    # target chooses which domain to learn operators in. A belief at ~0.5
    # posterior has near-maximal entropy and appears in get_unstable_regions;
    # as operators are learned its posterior rises and it exits the set. This
    # is the competence drive's inverted-U for free: explore where competence
    # is UNCERTAIN, not where it is mastered or hopeless.

    def _competence_claim(self, domain_id: str) -> str:
        return f"the substrate has learned the operators of domain {domain_id}"

    @staticmethod
    def _uncertainty():
        from core.reasoning.bayesian_uncertainty import get_uncertainty_system
        return get_uncertainty_system()

    async def ensure_competence_belief(self, domain_id: str):
        """The belief tracking whether the substrate has learned a domain's
        operators, created at maximum uncertainty if absent."""
        unc = self._uncertainty()
        claim = self._competence_claim(domain_id)
        existing = next((b for b in unc.beliefs.values()
                         if b.claim == claim and b.domain == domain_id), None)
        if existing is None:
            existing = unc.create_belief(claim, domain=domain_id, prior=0.5)
            # Durable, not fire-and-forget: competence decides what the substrate
            # explores after a restart, so it must actually reach the store.
            await unc.flush_belief(existing.belief_id)
        return existing

    #: One exploration cycle is one weak, noisy data point about competence, not
    #: a confident verdict. A low evidence quality dampens the belief so
    #: competence is EARNED over several cycles: a single failure only nudges the
    #: belief (a domain is not abandoned after one bad cycle), and competence
    #: does not reach certainty in a handful of successes. Measured: at 0.15 one
    #: failure from 0.5 leaves entropy ~0.96 (still explored), while it takes
    #: several consistent cycles to move the belief out of the exploration set.
    COMPETENCE_EVIDENCE_QUALITY: float = 0.15

    async def record_competence_evidence(
        self, domain_id: str, *, learned: bool,
        quality: Optional[float] = None) -> None:
        """Move a domain's competence belief toward learned / not-learned.

        A newly learned operator is evidence the substrate is becoming competent
        (posterior up, entropy down → the domain eventually leaves exploration).
        A cycle that acted and learned nothing is weak evidence against, so a
        domain that yields nothing stops being chased -- but only after several
        cycles, never after one (see COMPETENCE_EVIDENCE_QUALITY).
        """
        if quality is None:
            quality = self.COMPETENCE_EVIDENCE_QUALITY
        unc = self._uncertainty()
        belief = await self.ensure_competence_belief(domain_id)
        unc.update_belief(
            belief.belief_id, {"source": "operator_learning", "quality": quality},
            evidence_supports=learned)
        # Flush the update durably -- a competence change that only lives in
        # memory would be undone by the next restart, and the domain would be
        # re-explored as if nothing had been learned.
        await unc.flush_belief(belief.belief_id)

    async def refresh_competence_beliefs(self) -> int:
        """Decay every competence belief toward uncertainty by the time elapsed
        since it was last touched.

        Competence that is no longer being earned erodes, so a domain the
        substrate WRONGLY believes it has mastered drifts back into the unstable
        set and is re-verified against the world -- which corrects a false
        estimate through failure. Called each exploration cycle. Returns how many
        competence beliefs were decayed.
        """
        unc = self._uncertainty()
        prefix = "the substrate has learned the operators of domain "
        decayed = 0
        for belief in list(unc.beliefs.values()):
            if isinstance(belief.claim, str) and belief.claim.startswith(prefix):
                await unc.decay_belief(belief.belief_id)
                decayed += 1
        return decayed

    #: How many recent competence observations to measure progress over.
    LEARNING_PROGRESS_WINDOW: int = 4
    #: A surfaced domain whose competence is not RISING by at least this much
    #: over the window is not worth exploring now: it is stuck (noise, no
    #: expected information gain) or falling (already being classified as
    #: blocked). Optimism for the unexplored is handled separately.
    MIN_LEARNING_PROGRESS: float = 0.01
    #: Learning progress assigned to a domain with too little history to measure
    #: -- optimism in the face of the unknown, so a fresh domain is tried before
    #: it is judged.
    OPTIMISTIC_PROGRESS: float = 1.0

    def _competence_belief_of(self, domain_id: str):
        unc = self._uncertainty()
        claim = self._competence_claim(domain_id)
        return next((b for b in unc.beliefs.values()
                     if b.claim == claim and b.domain == domain_id), None)

    def learning_progress(self, domain_id: str) -> float:
        """Signed learning progress: how much competence has RISEN over the
        recent window (`confidence_history`).

        This is the derivative of competence, the principled form of expected
        information gain. A domain being learned has POSITIVE progress and is
        worth more exploration; one that is stuck (noise -- competence
        oscillates, net ~0) or falling (being classified as unlearnable) has
        zero/negative progress and is deprioritized. A domain with too little
        history to measure is optimistic, so it is tried before it is judged.

        Progress is measured in-memory; after a restart it resets to optimistic
        while the competence LEVEL persists -- the substrate re-measures the
        rate by exploring, which is the honest thing to do, and never wrongly
        skips a domain on a rate it no longer remembers.
        """
        belief = self._competence_belief_of(domain_id)
        if belief is None:
            return 0.0
        history = belief.confidence_history
        if len(history) < 2:
            return self.OPTIMISTIC_PROGRESS
        window = min(self.LEARNING_PROGRESS_WINDOW, len(history) - 1)
        return history[-1] - history[-1 - window]

    #: Below this, the substrate's actions do not meaningfully move the domain
    #: (they produce no effect, or the world changes on its own regardless):
    #: uncontrollable, so exploring it cannot build steerable competence.
    CONTROLLABILITY_FLOOR: float = 0.05

    async def _ensure_controllability_table(self):
        if not self.db:
            return
        await self.db.execute_query(
            """CREATE TABLE IF NOT EXISTS unified.domain_controllability (
                   domain_id          VARCHAR PRIMARY KEY,
                   action_attempts    BIGINT NOT NULL DEFAULT 0,
                   action_effects     BIGINT NOT NULL DEFAULT 0,
                   still_observations BIGINT NOT NULL DEFAULT 0,
                   ambient_changes    BIGINT NOT NULL DEFAULT 0,
                   updated_at         TIMESTAMPTZ NOT NULL DEFAULT NOW())""")

    async def record_controllability(
        self, domain_id: str, *, action_attempts: int = 0, action_effects: int = 0,
        still_observations: int = 0, ambient_changes: int = 0) -> None:
        """Accumulate evidence about whether the substrate's actions move a
        domain. `action_*` come from acting (attempts, and how many changed the
        world); the observation counts come from watching the world with NO
        action taken (and how often it moved anyway). Persisted so controllability
        survives a restart, since it is expensive to re-measure."""
        if not self.db:
            return
        await self._ensure_controllability_table()
        await self.db.execute_query(
            """INSERT INTO unified.domain_controllability
                   (domain_id, action_attempts, action_effects,
                    still_observations, ambient_changes)
               VALUES ($1,$2,$3,$4,$5)
               ON CONFLICT (domain_id) DO UPDATE SET
                   action_attempts    = domain_controllability.action_attempts + EXCLUDED.action_attempts,
                   action_effects     = domain_controllability.action_effects + EXCLUDED.action_effects,
                   still_observations = domain_controllability.still_observations + EXCLUDED.still_observations,
                   ambient_changes    = domain_controllability.ambient_changes + EXCLUDED.ambient_changes,
                   updated_at         = NOW()""",
            (domain_id, int(action_attempts), int(action_effects),
             int(still_observations), int(ambient_changes)),
            commit=True)

    async def controllability(self, domain_id: str) -> float:
        """How much the substrate's actions move a domain, in [0,1].

        `action_effect_rate * (1 - ambient_rate)`: controllable means acting
        produces effects AND the world is otherwise stable. Actions that produce
        nothing, or a world that moves on its own, both drive it toward 0 -- an
        uncontrollable domain the substrate cannot learn to steer, which is
        distinct from noise (noise is caught by learning progress). Optimistic
        (1.0) with no evidence yet, so a fresh domain is tried before it is
        judged.
        """
        if not self.db:
            return 1.0
        await self._ensure_controllability_table()
        rows = await self.db.execute_query(
            "SELECT action_attempts, action_effects, still_observations, "
            "ambient_changes FROM unified.domain_controllability WHERE domain_id=$1",
            (domain_id,), fetch_all=True)
        if not rows:
            return 1.0
        row = rows[0]
        attempts = row["action_attempts"] or 0
        if attempts == 0:
            return 1.0  # not yet acted here -- optimistic
        action_effect_rate = (row["action_effects"] or 0) / attempts
        still = row["still_observations"] or 0
        ambient_rate = ((row["ambient_changes"] or 0) / still) if still else 0.0
        return max(0.0, min(1.0, action_effect_rate * (1.0 - ambient_rate)))

    async def diagnose_deficit(
        self, domain_id: str, goal_conditions, world, outcome,
    ) -> "EpistemicDeficit":
        """WHAT kind of knowledge is missing behind a goal that would not plan.

        A sibling of competence, controllability, and learning progress: a
        model-free MEASUREMENT of a domain's knowledge state, read from signals
        that already exist -- the planner's verdict, the rule store, the
        bindings, and the domain's vocabulary. It makes no decision; it returns a
        typed deficit whose `appraisal_signals()` feed the AppraisalSystem, which
        owns the disposition. The default is UNKNOWN_GAP: the substrate may know
        THAT it is deficient before it knows HOW, and manufacturing a specific
        type it cannot support would be worse than admitting that.

        Returns exactly one deficit: when several goal conditions fail for
        different reasons, the most UPSTREAM one, since a downstream fix cannot
        help while an upstream deficiency stands.
        """
        from core.execution.operator_binding import get_binding_registry
        from core.learning.rule_induction import Fact
        from core.learning.rule_store import get_rule_store

        registry = get_binding_registry()

        # OBSERVATION dominates: a world that cannot be read leaves nothing to
        # reason over, and every other diagnosis would rest on a world never
        # observed.
        bindings = list(registry.bindings_for(domain_id) or ())
        if registry.observe_world(domain_id) is None:
            return EpistemicDeficit(
                domain_id, DeficitType.OBSERVATION_GAP,
                evidence={"bindings": len(bindings)})

        # A planner UNREACHABLE over a COMPLETE operator set means "no plan with
        # the operators I have NOW", not "impossible". Alone it does not
        # distinguish a learnable OPERATOR_GAP from a genuine world constraint --
        # an empty operator set is trivially "complete" and its exhaustion proves
        # only that nothing has been learned yet. So this is NOT WORLD_PREVENTS on
        # its own; it upgrades an otherwise-UNKNOWN result AFTER the structural
        # analysis has found the pieces are all there (see below).
        status = getattr(getattr(outcome, "status", None), "value",
                         getattr(outcome, "status", None))
        unreachable_proof = (
            status == "unreachable" and bool(getattr(outcome, "grounding_complete", False)))

        rules = await get_rule_store().load(domain_id=domain_id)
        actable = {b.predicate for b in bindings}
        world_facts = self._parse_facts(world or [], Fact)
        world_predicates = {f.predicate for f in world_facts}
        goal_facts = self._parse_facts(goal_conditions, Fact)

        vocabulary: Set[str] = set(world_predicates) | set(actable)
        executable_effect_predicates: Set[str] = set()
        for stored in rules:
            rule = stored.rule
            for fact in (*rule.effects.add, *rule.effects.delete, *rule.body):
                vocabulary.add(fact.predicate)
            if rule.action is not None:
                vocabulary.add(rule.action.predicate)
            if stored.is_executable:
                executable_effect_predicates |= {e.predicate for e in rule.effects.add}

        unmet = [g for g in goal_facts if g not in world_facts]
        if not unmet:
            return EpistemicDeficit(
                domain_id, DeficitType.UNKNOWN_GAP, confidence=0.5,
                evidence={"note": "goal conditions already hold; failure is elsewhere"})

        diagnoses: List[EpistemicDeficit] = []
        for goal in unmet:
            predicate = goal.predicate
            producers = [r for r in rules
                         if any(e.predicate == predicate for e in r.rule.effects.add)]
            actionable = [r for r in producers if r.rule.action is not None]
            executable = [r for r in actionable if r.is_executable]
            deficit_type, evidence = self._classify_deficit(
                predicate, world_predicates=world_predicates, vocabulary=vocabulary,
                actionable=actionable, executable=executable, actable=actable,
                executable_effect_predicates=executable_effect_predicates)
            diagnoses.append(EpistemicDeficit(
                domain_id, deficit_type, target_predicate=predicate, evidence=evidence))

        diagnoses.sort(key=lambda d: _DEFICIT_PRIORITY.index(d.deficit_type))
        chosen = diagnoses[0]

        # WORLD_PREVENTS is the upgrade of an otherwise-UNKNOWN result: every
        # unmet goal predicate is structurally SUFFICIENT (represented, produced
        # by a validated bound operator whose preconditions are reachable) and yet
        # the planner PROVED the goal unreachable over its complete operator set.
        # The pieces are all there and still cannot be composed -- that is a
        # genuine constraint of the world, and no learning operation would help.
        # Absent that proof, structural sufficiency is UNKNOWN (deficient but
        # unlocalised), never "impossible".
        if chosen.deficit_type is DeficitType.UNKNOWN_GAP and unreachable_proof:
            chosen = EpistemicDeficit(
                domain_id, DeficitType.WORLD_PREVENTS,
                target_predicate=chosen.target_predicate,
                evidence={"planning_status": "unreachable",
                          "operators_considered": getattr(outcome, "operators_considered", None),
                          "note": "structurally sufficient yet proved unreachable"})

        if len(diagnoses) > 1:
            chosen.evidence["other_unmet"] = [
                {d.target_predicate: d.deficit_type.value} for d in diagnoses[1:]]
        logger.info("deficit diagnosis for %s: %s (%s)", domain_id,
                    chosen.deficit_type.value, chosen.target_predicate)
        return chosen

    @staticmethod
    def _classify_deficit(
        predicate, *, world_predicates, vocabulary, actionable, executable,
        actable, executable_effect_predicates,
    ) -> Tuple["DeficitType", Dict[str, Any]]:
        """Diagnose one unmet goal predicate from local structural facts.

        Branch order follows the causal chain from symbol to action: represented?
        -> any operator produces it? -> any VALIDATED? -> bound to a tool? -> are
        its preconditions reachable? -> else undiagnosed.
        """
        # CONCEPT: the predicate appears nowhere in the domain. The substrate has
        # no representation to attach an operator to.
        if predicate not in vocabulary:
            return DeficitType.CONCEPT_GAP, {"predicate_in_vocabulary": False}

        # OPERATOR: represented, but nothing the substrate knows PRODUCES it.
        if not actionable:
            return DeficitType.OPERATOR_GAP, {"actionable_producers": 0}

        # CAUSAL: an actionable rule claims to produce it, but none is VALIDATED
        # -- a hypothesis, not an established operator. The fix is evidence.
        if not executable:
            return DeficitType.CAUSAL_GAP, {
                "hypothesised_producers": len(actionable), "validated_producers": 0}

        # BINDING: a VALIDATED operator produces it, but none of the validated
        # producers' actions is bound to a tool -- known in principle, cannot act.
        bound = [r for r in executable
                 if r.rule.action is not None and r.rule.action.predicate in actable]
        if not bound:
            unbound = sorted({r.rule.action.predicate for r in executable
                              if r.rule.action is not None})
            return DeficitType.BINDING_GAP, {"unbound_actions": unbound}

        # A bound, validated operator exists; the block is a PRECONDITION it needs
        # that the world lacks and no validated operator can produce. Relational
        # (arity >= 2) is a missing RELATION; unary is a missing PREREQUISITE.
        missing: List[Any] = []
        for producer in bound:
            gaps = [pre for pre in producer.rule.preconditions
                    if pre.predicate not in world_predicates
                    and pre.predicate not in executable_effect_predicates]
            if not gaps:
                missing = []
                break
            if not missing or len(gaps) < len(missing):
                missing = gaps
        if missing:
            relational = [m for m in missing if len(m.args) >= 2]
            chosen = relational[0] if relational else missing[0]
            deficit = DeficitType.RELATION_GAP if relational else DeficitType.PREREQUISITE_GAP
            return deficit, {"missing_precondition": str(chosen)}

        # Represented, produced, validated, bound, preconditions reachable -- and
        # still no plan. Real, but the local signals do not localise it.
        return DeficitType.UNKNOWN_GAP, {"note": "no local signal separates the deficit"}

    @staticmethod
    def _parse_facts(conditions, Fact) -> Set[Any]:
        """Parse fact strings, dropping any that do not parse -- a malformed
        condition is not evidence of a deficit type."""
        facts: Set[Any] = set()
        for condition in conditions:
            try:
                facts.add(Fact.parse(str(condition)))
            except ValueError:
                logger.debug("deficit diagnosis skipped unparseable condition %r", condition)
        return facts

    async def address_deficit(self, deficit: "EpistemicDeficit", *, _depth: int = 0) -> Dict[str, Any]:
        """Run the learning operation a diagnosed deficit calls for.

        The deficit's KIND already fixed WHICH operation (its `.operation`); this
        executes it against the existing subsystems, never re-deciding. It is the
        step that makes the discrimination matter: an OPERATOR_GAP explores for an
        action, a CAUSAL_GAP gathers the contrastives that validate a hypothesis,
        a PREREQUISITE_GAP turns to the intermediate it lacks -- and a deficit the
        substrate cannot resolve from here (a relation or concept it must be
        given, a binding or observer that must be wired) ESCALATEs honestly rather
        than burning the budget exploring for an operator that was never missing.

        Runs no model. Returns what the operation did; it does not decide whether
        to run -- that is appraisal's, upstream.
        """
        from core.learning.exploration import SubstrateExplorer, get_proposer

        op = deficit.operation
        domain = deficit.domain_id
        base = {"domain": domain, "deficit_type": deficit.deficit_type.value,
                "operation": op.value}

        if op in (LearningOperation.LEARN_OPERATOR, LearningOperation.VALIDATE_CAUSE,
                  LearningOperation.PROBE):
            proposer = get_proposer(domain)
            if proposer is None:
                # The operation is right; the substrate just has no way to act in
                # this domain yet. That is a binding/observer gap, not a licence
                # to fake exploration.
                return {**base, "ran": False, "reason": "no proposer registered for domain"}
            # Explore RECORDS (and enqueues signatures for induction); it does not
            # induce here. Controllability comes from the ACTING this cycle and is
            # recorded now; COMPETENCE follows the induction that the always-online
            # learner drains off the acting path -- learning is what moves
            # competence, not the acting that fed it -- so it is not recorded here.
            summary = await SubstrateExplorer().explore(domain, proposer, max_actions=8)
            await self.record_controllability(
                domain,
                action_attempts=summary.get("acted", 0),
                action_effects=summary.get("positive", 0),
                still_observations=summary.get("still_observations", 0),
                ambient_changes=summary.get("ambient_changes", 0))
            return {**base, "ran": True, "summary": summary}

        if op is LearningOperation.ACHIEVE_PREREQUISITE:
            # The operator for the goal exists and is bound; what blocks it is a
            # precondition the world lacks. Turn to THAT as its own goal: diagnose
            # what is missing about the precondition and address it (one level --
            # a chain of prerequisites is pursued across cycles, not by unbounded
            # recursion in one call).
            missing = deficit.evidence.get("missing_precondition")
            if not missing or _depth >= 1:
                return {**base, "ran": False, "reason": "prerequisite not localised"
                        if not missing else "prerequisite chain deferred to next cycle"}
            from core.execution.operator_binding import get_binding_registry
            observed = get_binding_registry().observe_world(domain)
            world = sorted(str(f) for f in observed) if observed is not None else []
            sub = await self.diagnose_deficit(domain, [missing], world, None)
            result = await self.address_deficit(sub, _depth=_depth + 1)
            return {**base, "ran": result.get("ran", False),
                    "prerequisite": missing, "resolved_via": result}

        if op is LearningOperation.TRANSFER_RELATION:
            # The operator for the goal exists and is bound; what blocks it is a
            # relational precondition the domain has no way to produce. Seek that
            # relation from a domain that HAS it: project the source's
            # relation-producing operator across the correspondence its shared
            # operators establish. The projection is a CANDIDATE -- analogy
            # proposes, only this domain's own evidence attests. If no source can
            # supply it, escalate honestly rather than pretend.
            from core.learning.rule_induction import Fact
            missing = deficit.evidence.get("missing_precondition")
            try:
                relation = Fact.parse(str(missing)).predicate if missing else deficit.target_predicate
            except ValueError:
                relation = deficit.target_predicate
            result = await self.transfer_relation(domain, relation)
            if result.get("transferred"):
                return {**base, "ran": True, **result}
            return {**base, "ran": False, "escalated": True,
                    "reason": deficit.remedy_reason, "transfer": result}

        if op is LearningOperation.ESCALATE:
            return {**base, "ran": False, "escalated": True,
                    "reason": deficit.remedy_reason}

        # DISENGAGE
        return {**base, "ran": False, "disengaged": True,
                "reason": "the world forbids the goal; no learning is justified"}

    async def transfer_relation(self, target_domain: str, relation_predicate: str) -> Dict[str, Any]:
        """Acquire a relation a domain cannot produce by projecting the operator
        that produces it from a domain that can.

        Model-free and structural. A source domain qualifies when its operators
        SHARE enough structure with the target to fix a predicate correspondence
        (`_partial_correspondence`), and it has an operator -- one the target
        LACKS -- whose effect adds a binary relation. That operator is projected
        into the target vocabulary: its shared preconditions renamed through the
        correspondence, its own action carried across, its produced relation
        mapped to the one the target needs. Any operator with a precondition the
        correspondence does NOT cover is skipped -- importing a source's private
        vocabulary would be inventing, not transferring.

        The projection lands as a CANDIDATE with zero evidence (via
        `record_projection`): the analogy has PROPOSED that this domain can
        produce the relation, and only this domain's own observations can raise
        it to executable. So a successful transfer converts a RELATION_GAP into a
        CAUSAL_GAP -- a hypothesis to validate -- not a finished capability.
        """
        from core.learning.analogical_projection import project, ProjectionOutcome
        from core.learning.rule_store import get_rule_store

        store = get_rule_store()
        from collections import defaultdict
        by_domain: Dict[str, List[Any]] = defaultdict(list)
        for stored in await store.executable_rules():
            if stored.rule.action is not None and stored.domain_id:
                by_domain[stored.domain_id].append(stored)

        target_ops = [s.rule for s in by_domain.get(target_domain, [])]
        if not target_ops:
            return {"transferred": False,
                    "reason": "the target has no operators to fix a correspondence"}

        for source_domain, stored_ops in by_domain.items():
            if source_domain == target_domain:
                continue
            source_ops = [s.rule for s in stored_ops]
            mapping, aligned = self._partial_correspondence(source_ops, target_ops)
            # The correspondence -- fixed by the operators the two domains SHARE --
            # is what says which source relation IS the one the target needs.
            # Only a producer of THAT relation is transferred; mapping an
            # arbitrary binary relation onto the target would be guessing, not
            # transferring (the shared goal operator already names the pairing).
            source_relations = {sp for sp, tp in mapping.items() if tp == relation_predicate}
            if not source_relations:
                continue
            aligned_ids = {id(r) for r in aligned}
            for stored in stored_ops:
                producer = stored.rule
                if id(producer) in aligned_ids:
                    continue  # already an operator the target has
                if not any(f.predicate in source_relations and f.arity >= 2
                           for f in producer.effects.add):
                    continue
                # Everything the producer touches EXCEPT its own action must be
                # covered by the correspondence; importing a source's private
                # precondition would be inventing, not transferring. The action
                # itself is carried across -- it is the capability the target
                # lacks, and it remains an unbound symbol until a binding is
                # supplied (a further, honest gap).
                touched = ({f.predicate for f in producer.preconditions}
                           | {f.predicate for f in producer.effects.add}
                           | {f.predicate for f in producer.effects.delete})
                if any(p not in mapping for p in touched):
                    continue
                corr = {p: mapping[p] for p in touched}
                corr[producer.action.predicate] = mapping.get(
                    producer.action.predicate, producer.action.predicate)
                result = project(
                    producer, corr, source_rule_id=stored.rule_id,
                    source_domain=source_domain, target_domain=target_domain)
                if result.outcome is not ProjectionOutcome.FULL_PROJECTION:
                    continue
                projected = await store.record_projection(result)
                logger.info("transferred relation %s into %s from %s (candidate %s)",
                            relation_predicate, target_domain, source_domain,
                            projected.rule_id)
                return {"transferred": True, "source_domain": source_domain,
                        "source_rule_id": stored.rule_id, "rule_id": projected.rule_id,
                        "produces": relation_predicate, "mapping": corr}
        return {"transferred": False,
                "reason": "no source domain has a mappable operator producing the relation"}

    async def select_exploration_target(self, explorable_domains, targets) -> Optional[str]:
        """The domain to explore now: among the operator-domains intrinsic
        motivation surfaced and we can explore, the CONTROLLABLE one with the
        highest LEARNING PROGRESS, or None if none qualifies.

        Motivation supplies the candidates (uncertain, worth attention); two
        signals choose among them so the substrate seeks controllable
        information gain rather than raw entropy:
          - CONTROLLABILITY gates: a domain whose outcomes the substrate cannot
            steer (actions inert, or the world moves on its own) is dropped, even
            if it looks uncertain and even if its competence is drifting.
          - LEARNING PROGRESS ranks the rest: competence that is rising is
            productive; stuck (noise) or falling (unlearnable) drops out.
        A fresh domain is optimistic on both and gets tried before it is judged.
        Severing any input still removes exactly its own contribution.
        """
        explorable = set(explorable_domains or ())
        seen, candidates = set(), []
        for target in targets or ():
            domain = self.is_competence_belief(target)
            if domain in explorable and domain not in seen:
                seen.add(domain)
                if await self.controllability(domain) < self.CONTROLLABILITY_FLOOR:
                    continue  # the substrate cannot steer this domain -- skip it
                candidates.append((domain, self.learning_progress(domain)))
        if not candidates:
            return None
        candidates.sort(key=lambda c: c[1], reverse=True)
        domain, progress = candidates[0]
        if progress < self.MIN_LEARNING_PROGRESS:
            return None  # nothing controllable is making progress -- do not chase it
        return domain

    def is_competence_belief(self, target) -> Optional[str]:
        """If an exploration target is a domain-competence belief, the domain it
        is about; else None. Lets the exploration tier pick the operator-domain
        targets out of everything intrinsic motivation surfaces."""
        claim = getattr(target, "claim", None) or (
            getattr(target, "metadata", {}) or {}).get("claim", "")
        prefix = "the substrate has learned the operators of domain "
        if isinstance(claim, str) and claim.startswith(prefix):
            return getattr(target, "domain", None) or claim[len(prefix):]
        return None

    async def learned_domains(self) -> List["Any"]:
        """Every operational domain the substrate has, excluding the DomainType
        categories that share the table."""
        registry = await self._registry()
        return [d for d in registry.domains.values() if self.is_learned_domain(d)]

    async def similar_domains(self, domain_id: str, *, threshold: float = 0.0):
        """Domains most similar to a known one, by concept structure.

        The authority-level entry point for 'what is this domain like'. The
        ranking itself is the registry's concept-based measure -- one
        implementation, delegated to here rather than reimplemented -- so the
        capability is unchanged; consolidating the ENTRY means callers ask the
        Master rather than each reaching for its own registry handle.
        """
        registry = await self._registry()
        return await registry.find_similar_domains(domain_id, threshold=threshold)

    async def suggest_mappings(self, source_domain_id: str, target_domain_id: str):
        """Concept-level correspondences between two domains -- the mapping
        ground truth transfer consumes.

        The authority-level entry for 'how do these two domains correspond'. The
        computation is the registry's concept-similarity mapping (one
        implementation, delegated to here); consolidating the ENTRY means callers
        ask the Master rather than each holding their own registry handle.
        """
        registry = await self._registry()
        return await registry.suggest_cross_domain_mappings(
            source_domain_id, target_domain_id)

    # ==================================================================
    # DOMAIN DISCOVERY BY CRYSTALLIZATION
    #
    # WHEN a provisional operational domain (a bucket of learned operators under
    # a string domain_id) becomes a first-class Domain is not decided by contact
    # -- minting on contact is how "21 domains for one topic" happened. It is
    # decided by structure: a provisional domain crystallizes when its operators
    # are coherent AND structurally DISTINCT from every domain already known,
    # and MERGES when they are the same structure under a renaming.
    #
    # Distinctness is judged on OPERATOR structure, not concepts, because an
    # explored domain may hold only operators. Predicate NAMES are abstracted
    # away: MOVE(x,a,b) and MOVE_FILE(f,s,d) with the same wiring are the same
    # operator wearing different names -- which is exactly a transfer bridge.
    #
    # The one irreversible mistake is a WRONG MERGE: it destroys a domain's
    # identity. So this is conservative -- it crystallizes unless a merge is
    # positively established, and never the reverse.
    # ==================================================================

    @staticmethod
    def _operator_skeleton(rule) -> Optional[tuple]:
        """A predicate-agnostic structural signature of one learned operator.

        Variables are canonicalized by first appearance (action arguments seed
        the order, so an operator whose variables all come through its action --
        the common case -- is fully canonical). Constants are kept, since they
        constrain structure. Predicate NAMES are dropped: what remains is the
        wiring -- which literal shares which variable with the action and with
        the effects. Two operators that differ only in what their predicates are
        called produce the same skeleton.
        """
        from core.reasoning.unification import is_variable

        action = getattr(rule, "action", None)
        if action is None:
            return None

        order: Dict[str, str] = {}

        def canon(arg: str) -> str:
            if is_variable(arg):
                if arg not in order:
                    order[arg] = f"v{len(order)}"
                return order[arg]
            return f"c:{arg}"

        # Action first, in argument order, to seed the canonical variable names.
        action_sig = (action.arity, tuple(canon(a) for a in action.args))

        def lit(role: str, f) -> tuple:
            return (role, f.arity, tuple(canon(a) for a in f.args))

        body = sorted(lit("PRE", f) for f in rule.body if f != action)
        add = sorted(lit("ADD", f) for f in rule.effects.add)
        dele = sorted(lit("DEL", f) for f in rule.effects.delete)
        return (action_sig, tuple(body), tuple(add), tuple(dele))

    async def _domain_operators(self, domain_id: str) -> List[Any]:
        """The validated, executable operators of an operational domain."""
        from core.learning.rule_store import get_rule_store
        stored = await get_rule_store().executable_rules(domain_id=domain_id)
        return [s.rule for s in stored if getattr(s.rule, "action", None) is not None]

    def _operators_coherent(self, rules: List[Any]) -> bool:
        """The operators form one domain, not unrelated fragments.

        Coherent means their predicates connect: the graph whose nodes are
        operators and whose edges join operators that share any predicate is
        connected. A single operator is trivially coherent. Fragments that share
        nothing are not yet a domain and should keep accumulating before they
        crystallize.
        """
        if len(rules) <= 1:
            return bool(rules)

        def preds(rule) -> set:
            ps = {f.predicate for f in rule.body}
            ps |= {f.predicate for f in rule.effects.add}
            ps |= {f.predicate for f in rule.effects.delete}
            return ps

        pred_sets = [preds(r) for r in rules]
        # union-find over operators sharing a predicate
        parent = list(range(len(rules)))

        def find(i):
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i

        for i in range(len(rules)):
            for j in range(i + 1, len(rules)):
                if pred_sets[i] & pred_sets[j]:
                    parent[find(i)] = find(j)
        return len({find(i) for i in range(len(rules))}) == 1

    def _correspondence(self, source: List[Any], target: List[Any]) -> Optional[Dict[str, str]]:
        """A consistent predicate renaming under which every source operator is
        an existing target operator, or None.

        The sound MERGE criterion: a mapping is returned only when the WHOLE
        source operator set maps onto the target's under one predicate bijection.
        Anything short of that returns None -- the domains are treated as
        distinct, which is the safe error (a wrong merge destroys identity; a
        missed merge only fragments, and a later pass can still merge).

        This is the full-alignment special case of `_partial_correspondence`, so
        the alignment logic lives in exactly one place.
        """
        mapping, aligned = self._partial_correspondence(source, target)
        if mapping and len(aligned) == len(source):
            return mapping
        return None

    def _partial_correspondence(
        self, source: List[Any], target: List[Any]
    ) -> Tuple[Dict[str, str], List[Any]]:
        """The predicate renaming induced by the operators source and target SHARE.

        Aligns every source operator that has a structural (skeleton) match in the
        target, accumulating ONE consistent predicate bijection; source operators
        with no consistent match are left out and reported via `aligned`, so a
        caller can tell shared structure from novel. Unlike a full correspondence
        this does not require the WHOLE source set to map -- which is exactly what
        lets an operator the target LACKS be projected across the mapping its
        shared operators establish (the basis of relation transfer).

        Literals are aligned by their PREDICATE-AGNOSTIC key -- role, arity and
        canonical variable positions -- so AT(v0,v1) aligns with LOC(v0,v1) even
        though the names sort differently; a permutation search finds a consistent
        predicate assignment where a key covers several literals.
        """
        import itertools
        from collections import defaultdict
        from core.reasoning.unification import is_variable

        def canon(rule) -> Dict[str, str]:
            order: Dict[str, str] = {}
            seq = list(rule.action.args)
            for f in sorted(rule.body, key=lambda x: x.arity):
                seq += list(f.args)
            for f in sorted(rule.effects.add, key=lambda x: x.arity):
                seq += list(f.args)
            for f in sorted(rule.effects.delete, key=lambda x: x.arity):
                seq += list(f.args)
            for a in seq:
                if is_variable(a) and a not in order:
                    order[a] = f"v{len(order)}"
            return order

        def keyed(rule):
            order = canon(rule)

            def k(role, f):
                return (role, f.arity,
                        tuple(order.get(a, f"c:{a}") for a in f.args))
            by_key: Dict[tuple, List[str]] = defaultdict(list)
            by_key[k("ACT", rule.action)].append(rule.action.predicate)
            for f in rule.body:
                if f != rule.action:
                    by_key[k("PRE", f)].append(f.predicate)
            for f in rule.effects.add:
                by_key[k("ADD", f)].append(f.predicate)
            for f in rule.effects.delete:
                by_key[k("DEL", f)].append(f.predicate)
            return by_key

        target_by_skel: Dict[tuple, List[Any]] = defaultdict(list)
        for rule in target:
            skel = self._operator_skeleton(rule)
            if skel is not None:
                target_by_skel[skel].append(rule)

        mapping: Dict[str, str] = {}
        inverse: Dict[str, str] = {}

        def align(src, tgt) -> bool:
            s_keys, t_keys = keyed(src), keyed(tgt)
            if set(s_keys) != set(t_keys):
                return False
            if any(len(s_keys[k]) != len(t_keys[k]) for k in s_keys):
                return False
            keys = list(s_keys)

            def backtrack(i, fwd, rev) -> bool:
                if i == len(keys):
                    mapping.update(fwd)
                    inverse.update(rev)
                    return True
                sps, tps = s_keys[keys[i]], t_keys[keys[i]]
                for perm in itertools.permutations(tps):
                    nf, nr, ok = dict(fwd), dict(rev), True
                    for sp, tp in zip(sps, perm):
                        if nf.get(sp, mapping.get(sp)) not in (None, tp):
                            ok = False
                            break
                        if nr.get(tp, inverse.get(tp)) not in (None, sp):
                            ok = False
                            break
                        nf[sp], nr[tp] = tp, sp
                    if ok and backtrack(i + 1, nf, nr):
                        return True
                return False

            return backtrack(0, {}, {})

        aligned: List[Any] = []
        for rule in source:
            skel = self._operator_skeleton(rule)
            if any(align(rule, cand) for cand in target_by_skel.get(skel, [])):
                aligned.append(rule)
        return mapping, aligned

    async def provisional_domains(self) -> List[str]:
        """Operational domains that have validated operators but are not yet
        registered as first-class Domains -- the candidates for crystallization.

        A provisional domain is a bucket where learning has been accumulating
        under a string domain_id. It becomes a real domain only once discovery
        decides it has earned one.
        """
        from core.learning.rule_store import get_rule_store
        registry = await self._registry()
        rules = await get_rule_store().executable_rules()
        domain_ids = {r.domain_id for r in rules if getattr(r, "domain_id", None)}
        return sorted(d for d in domain_ids if d not in registry.domains)

    async def discover_domains(self, *, limit: int = 8) -> Dict[str, Any]:
        """Crystallize provisional operational domains -- the discovery step,
        meant to run in idle work.

        Each provisional domain is either minted as a new first-class domain or
        merged into an existing one, decided by operator structure. This is the
        substrate's map of subjects growing from what it has actually learned.
        """
        outcomes = []
        for domain_id in (await self.provisional_domains())[:max(0, int(limit))]:
            try:
                outcomes.append(await self.crystallize(domain_id))
            except Exception as e:
                from core.capability import raise_if_structural
                raise_if_structural(e, "universal_domain_master.discover_domains")
                logger.error("crystallize(%s) failed: %s", domain_id, e)
        return {
            "examined": len(outcomes),
            "crystallized": sum(1 for o in outcomes if o.get("status") == "crystallized"),
            "merged": sum(1 for o in outcomes if o.get("status") == "merged"),
            "outcomes": outcomes,
        }

    async def crystallize(self, provisional_domain_id: str) -> Dict[str, Any]:
        """Decide whether a provisional operational domain is new or already
        known, and act on it.

        Returns a decision: 'crystallized' (registered as a new first-class
        domain), 'merged' (its operators are an existing domain's under a
        recorded predicate correspondence), 'incoherent' (its operators do not
        yet form one domain), or 'empty'/'already_registered'.
        """
        registry = await self._registry()
        if registry.domains.get(provisional_domain_id) is not None:
            return {"status": "already_registered", "domain_id": provisional_domain_id}

        rules = await self._domain_operators(provisional_domain_id)
        if not rules:
            return {"status": "empty", "domain_id": provisional_domain_id}

        if not self._operators_coherent(rules):
            return {"status": "incoherent", "domain_id": provisional_domain_id,
                    "operators": len(rules)}

        # Compare against every registered LEARNED domain's operators. A
        # registered domain with no operators (a DomainType category) offers
        # nothing to match and is skipped.
        #
        # A correspondence that is the IDENTITY -- every predicate maps to
        # itself -- means the same vocabulary, so this is the same subject
        # re-learned or extended under a different id: MERGE. A correspondence
        # that RENAMES predicates means the same STRUCTURE over a different
        # vocabulary: that is an ANALOGY between two distinct subjects (movement
        # and warehouse logistics share the shape of "a thing moves along a
        # link"), and merging them would destroy the distinction. Those become
        # transfer bridges on a domain that still crystallizes as its own.
        analogies: List[tuple] = []
        for other in await self.learned_domains():
            target = await self._domain_operators(other.domain_id)
            if not target:
                continue
            correspondence = self._correspondence(rules, target)
            if correspondence is None:
                continue
            if all(k == v for k, v in correspondence.items()):
                await self._record_domain_correspondence(
                    provisional_domain_id, other.domain_id, correspondence)
                logger.info("crystallize: %s is %s (same vocabulary) -- merged",
                            provisional_domain_id, other.domain_id)
                return {"status": "merged", "domain_id": provisional_domain_id,
                        "into": other.domain_id, "correspondence": correspondence}
            analogies.append((other.domain_id, correspondence))

        # No same-vocabulary match: a new domain. Record any structural
        # analogies as transfer bridges, then crystallize it as its own.
        domain = await self.ensure_domain(provisional_domain_id)
        for other_id, correspondence in analogies:
            await self._record_domain_correspondence(
                provisional_domain_id, other_id, correspondence)
        if analogies:
            logger.info("crystallize: %s is new, analogous to %s",
                        provisional_domain_id, [o for o, _ in analogies])
        return {"status": "crystallized", "domain_id": provisional_domain_id,
                "domain_type": domain.domain_type.value, "operators": len(rules),
                "analogies": [o for o, _ in analogies]}

    async def _record_domain_correspondence(
        self, source_domain: str, target_domain: str, mapping: Dict[str, str]) -> None:
        """Persist that one domain's operators are another's under a predicate
        renaming -- the transfer bridge a merge produces."""
        if not self.db:
            return
        await self.db.execute_query(
            """INSERT INTO unified.domain_mappings
                   (mapping_id, source_domain, target_domain, source_concept,
                    target_concept, similarity_score, reasoning_strategy,
                    verified, confidence, metadata)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10::jsonb)
               ON CONFLICT DO NOTHING""",
            (f"opcorr_{source_domain}_{target_domain}", source_domain,
             target_domain, source_domain, target_domain, 1.0,
             ReasoningStrategy.ANALOGICAL.value, True, 1.0,
             json.dumps({"kind": "operator_correspondence", "mapping": mapping})),
            commit=True,
        )

    async def execute_cross_domain_query(
        self,
        query: CrossDomainQuery
    ) -> DomainIntegrationResult:
        """
        Execute cross-domain query

        Finds relationships and mappings between concepts across
        multiple knowledge domains using the specified reasoning strategy.
        """
        start_time = datetime.now()
        self.stats['total_queries'] += 1

        logger.info(
            f"Executing cross-domain query: {query.query_text[:100]}... "
            f"(strategy: {query.reasoning_strategy.value})"
        )

        try:
            # Find mappings between source and target domains
            mappings = await self._find_cross_domain_mappings(
                query.source_domains,
                query.target_domains,
                query.reasoning_strategy,
                query.min_similarity
            )

            # Generate insights
            insights = await self._generate_insights(mappings, query)

            # Generate explanations if requested
            explanations = []
            if query.include_explanations:
                explanations = await self._generate_explanations(mappings, query)

            # Calculate execution time
            execution_time = (datetime.now() - start_time).total_seconds()

            # Store query record
            await self._store_query_record(query, mappings, execution_time, success=True)

            self.stats['successful_queries'] += 1

            result = DomainIntegrationResult(
                query_id=query.query_id,
                success=True,
                mappings=mappings,
                insights=insights,
                explanations=explanations,
                execution_time=execution_time,
                domains_queried=len(query.source_domains) + len(query.target_domains),
                mappings_found=len(mappings)
            )

            logger.info(
                f"✓ Cross-domain query completed: {len(mappings)} mappings found "
                f"in {execution_time:.2f}s"
            )

            return result

        except Exception as e:
            logger.error(f"Cross-domain query failed: {e}")
            self.stats['failed_queries'] += 1

            execution_time = (datetime.now() - start_time).total_seconds()

            return DomainIntegrationResult(
                query_id=query.query_id,
                success=False,
                error=str(e),
                execution_time=execution_time
            )

    async def _resolved_field_keys(self, refs) -> List[str]:
        """Domain references -> canonical field keys, via the registry resolver.

        One resolution path shared by the reader and the writer, so a mapping
        stored under a key is looked up under the same key.
        """
        from core.domain.cross_domain_reasoner import get_cross_domain_reasoner
        from core.domain.domain_registry import UnresolvedDomainReference

        reasoner = get_cross_domain_reasoner()
        await reasoner.initialize()
        registry = reasoner.domain_registry

        keys, seen = [], set()
        for ref in refs or []:
            name = ref.value if isinstance(ref, DomainType) else str(ref)
            try:
                resolved = registry.resolve_domain_reference(
                    name, require_concepts=True,
                    max_targets=self.MAX_RESOLVED_FIELDS,
                )
            except UnresolvedDomainReference as e:
                logger.warning("Skipping unresolved domain reference: %s", e)
                continue
            for rd in resolved:
                k = registry._domain_key(rd.domain_id)
                if k not in seen:
                    seen.add(k)
                    keys.append(k)
        return keys

    async def _find_cross_domain_mappings(
        self,
        source_domains: List[DomainType],
        target_domains: List[DomainType],
        strategy: ReasoningStrategy,
        min_similarity: float
    ) -> List[DomainMapping]:
        """Find mappings between source and target domains"""
        mappings = []

        # Check cache first
        for source in source_domains:
            for target in target_domains:
                cache_key = (source, target)
                if cache_key in self.mapping_cache:
                    cached_mappings = [
                        m for m in self.mapping_cache[cache_key]
                        if m.similarity_score >= min_similarity
                    ]
                    mappings.extend(cached_mappings)

        if mappings:
            logger.debug(f"Found {len(mappings)} cached mappings")
            return mappings

        # Query database for existing mappings.
        #
        # Rows store CANONICAL FIELD keys ("physics"), so the lookup resolves the
        # caller's references the same way the writer does. Querying by
        # DomainType.value here would ask for "physical" and never match a row
        # the writer stored under "physics" -- a read/write asymmetry that reads
        # as "no mappings exist" rather than as a key mismatch.
        if self.db:
            source_keys = await self._resolved_field_keys(source_domains)
            target_keys = await self._resolved_field_keys(target_domains)
            for source in source_keys:
                for target in target_keys:
                    rows = await self.db.execute_query(
                        """SELECT mapping_id, source_domain, target_domain, source_concept,
                                  target_concept, similarity_score, reasoning_strategy,
                                  verified, confidence
                           FROM unified.domain_mappings
                           WHERE source_domain = $1 AND target_domain = $2
                           AND similarity_score >= $3
                           -- verified IS NULL  = candidate, never ontologically judged
                           -- verified IS TRUE  = accepted knowledge
                           -- verified IS FALSE = rejected; must never be returned
                           AND (verified IS NULL OR verified IS TRUE)""",
                        (source, target, min_similarity),
                        fetch_all=True
                    )

                    for row in rows:
                        mapping = DomainMapping(
                            mapping_id=row['mapping_id'],
                            source_domain=row['source_domain'],
                            target_domain=row['target_domain'],
                            source_concept=row['source_concept'],
                            target_concept=row['target_concept'],
                            similarity_score=row['similarity_score'],
                            reasoning_strategy=ReasoningStrategy(row['reasoning_strategy']),
                            verified=row['verified'],
                            confidence=row['confidence']
                        )
                        mappings.append(mapping)

        # If no mappings found, generate new ones
        if not mappings:
            mappings = await self._generate_mappings(
                source_domains,
                target_domains,
                strategy,
                min_similarity
            )

        # Update cache
        for source in source_domains:
            for target in target_domains:
                cache_key = (source, target)
                self.mapping_cache[cache_key] = [
                    m for m in mappings
                    if m.source_domain == source and m.target_domain == target
                ]

        return mappings

    async def _generate_mappings(
        self,
        source_domains: List[DomainType],
        target_domains: List[DomainType],
        strategy: ReasoningStrategy,
        min_similarity: float
    ) -> List[DomainMapping]:
        """Generate cross-domain mappings via the real reasoner.

        This previously called the neural bridge, DISCARDED its output, and
        emitted placeholder concepts:

            source_concept = f"{source.value}_concept"   ->  "technical_concept"
            target_concept = f"{target.value}_concept"   ->  "scientific_concept"

        Only `result.confidence` was used. Any row it stored would have been a
        durable, restart-surviving assertion that "technical_concept maps to
        scientific_concept" — a placeholder wearing the shape of knowledge, and
        it would have counted toward the >=2 cross-domain significance rule.
        The table is empty today only because the confidence threshold happened
        not to be met.

        CrossDomainReasoner implements the seven real strategies and already
        emits List[CrossDomainMapping] with actual concept identities, so this
        is a delegation, not a translation layer.

        Everything produced here is a CANDIDATE: `verified=None` means no
        ontological validation has been performed. It is NOT `False` (which
        would assert rejection) and NOT `True`. UniversalOntology's validator is
        deliberately NOT called — it is a stub that returns valid=True
        unconditionally, so calling it would stamp every model proposal as
        validated knowledge.
        """
        from core.domain.cross_domain_reasoner import (
            get_cross_domain_reasoner, ReasoningContext as XDomainContext,
        )
        from core.domain.domain_registry import UnresolvedDomainReference

        reasoner = get_cross_domain_reasoner()
        await reasoner.initialize()
        registry = reasoner.domain_registry

        # Resolve references to canonical registry domains BEFORE reasoning.
        #
        # This minted `f"domain_{source.value}"` directly from DomainType, which
        # always names a CATEGORY (domain_physical). Every concept lives in a
        # FIELD (domain_physics), so the reasoner was handed empty domains and
        # returned honest "no mappings" for pairs that in fact share concepts.
        #
        # The resolver turns either level into canonical field ids, exact match
        # winning over category expansion, and bounds the fan-out so a category
        # pair does not become every-field-against-every-field.
        def _resolve(dts, *, rank_against=None):
            out, seen = [], set()
            for dt in dts:
                ref = dt.value if isinstance(dt, DomainType) else str(dt)
                try:
                    for rd in registry.resolve_domain_reference(
                        ref,
                        require_concepts=True,
                        max_targets=self.MAX_RESOLVED_FIELDS,
                        rank_against=rank_against,
                    ):
                        if rd.domain_id not in seen:
                            seen.add(rd.domain_id)
                            out.append(rd)
                except UnresolvedDomainReference as e:
                    logger.warning("Skipping unresolved domain reference: %s", e)
            return out

        resolved_sources = _resolve(source_domains)
        if not resolved_sources:
            logger.info(
                "No source domain resolved to a field with concepts (%s); "
                "returning no candidates",
                ", ".join(getattr(d, "value", str(d)) for d in source_domains),
            )
            return []

        mappings: List[DomainMapping] = []
        for source in resolved_sources:
            for target in _resolve(target_domains, rank_against=source.domain_id):
                if source.domain_id == target.domain_id:
                    continue
                try:
                    ctx = XDomainContext(
                        source_domain_id=source.domain_id,
                        target_domain_id=target.domain_id,
                        reasoning_goal=(
                            f"identify conceptual correspondences from the "
                            f"{source.name} domain to the {target.name} domain"
                        ),
                        strategy=strategy,
                        confidence_threshold=min_similarity,
                        # The reasoner's own quality gate stays ON: it answers
                        # "is this a well-formed candidate", which is a
                        # different question from ontological acceptance.
                        require_validation=True,
                    )
                    result = await reasoner.reason_across_domains(ctx)
                except Exception as e:
                    # No fabricated fallback. The previous version emitted more
                    # placeholder mappings on failure, which is how a durable
                    # store fills with noise the moment the producer errors.
                    logger.warning(
                        "Cross-domain reasoning failed for %s->%s (%s); "
                        "returning no candidates rather than placeholders",
                        source.domain_id, target.domain_id, e
                    )
                    continue

                if not getattr(result, "success", False):
                    continue

                for gm in (getattr(result, "generated_mappings", None) or []):
                    sim = float(getattr(gm, "strength", 0.0) or getattr(gm, "confidence", 0.0) or 0.0)
                    if sim < min_similarity:
                        continue
                    mapping = DomainMapping(
                        mapping_id=getattr(gm, "mapping_id", None)
                        or f"mapping_{uuid.uuid4().hex[:16]}",
                        source_domain=registry._domain_key(source.domain_id),
                        target_domain=registry._domain_key(target.domain_id),
                        source_concept=gm.source_concept_id,
                        target_concept=gm.target_concept_id,
                        similarity_score=sim,
                        reasoning_strategy=strategy,
                        # UNVALIDATED. None != False: nothing has judged it.
                        verified=None,
                        confidence=float(getattr(gm, "confidence", sim) or sim),
                    )
                    mappings.append(mapping)
                    await self._store_mapping(mapping)

        if mappings:
            logger.info(
                "Generated %d cross-domain CANDIDATE mapping(s) — unvalidated",
                len(mappings)
            )
        return mappings


    async def _store_mapping(self, mapping: DomainMapping):
        """Store mapping in database"""
        if not self.db:
            return

        await self.db.execute_query(
            """INSERT INTO unified.domain_mappings
               (mapping_id, source_domain, target_domain, source_concept,
                target_concept, similarity_score, reasoning_strategy,
                verified, confidence, metadata)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
               -- Untargeted ON CONFLICT: mapping_id is not the only uniqueness
               -- constraint. uq_domain_mappings_semantic makes the RELATIONSHIP
               -- unique (source/target domain + concepts + strategy), so two
               -- schemas independently rediscovering the same mapping produce
               -- one row rather than a duplicate under a fresh uuid.
               ON CONFLICT DO NOTHING""",
            (
                mapping.mapping_id,
                mapping.source_domain,
                mapping.target_domain,
                mapping.source_concept,
                mapping.target_concept,
                mapping.similarity_score,
                mapping.reasoning_strategy.value,
                mapping.verified,
                mapping.confidence,
                json.dumps(mapping.metadata) if mapping.metadata else None
            ),
            commit=True
        )

    async def _generate_insights(
        self,
        mappings: List[DomainMapping],
        query: CrossDomainQuery
    ) -> List[str]:
        """Generate insights from mappings"""
        insights = []

        if not mappings:
            return insights

        # Generate summary insights
        insights.append(
            f"Found {len(mappings)} cross-domain mappings using "
            f"{query.reasoning_strategy.value} reasoning"
        )

        # Domain coverage
        source_domains = {m.source_domain for m in mappings}
        target_domains = {m.target_domain for m in mappings}
        insights.append(
            f"Coverage: {len(source_domains)} source domains, "
            f"{len(target_domains)} target domains"
        )

        # Average similarity
        avg_similarity = sum(m.similarity_score for m in mappings) / len(mappings)
        insights.append(f"Average similarity: {avg_similarity:.2f}")

        return insights

    async def _generate_explanations(
        self,
        mappings: List[DomainMapping],
        query: CrossDomainQuery
    ) -> List[str]:
        """Generate explanations for mappings"""
        explanations = []

        for mapping in mappings[:5]:  # Limit to top 5
            explanation = (
                f"{mapping.source_concept} ({mapping.source_domain}) maps to "
                f"{mapping.target_concept} ({mapping.target_domain}) "
                f"with {mapping.similarity_score:.0%} similarity using "
                f"{mapping.reasoning_strategy.value} reasoning"
            )
            explanations.append(explanation)

        return explanations

    async def _store_query_record(
        self,
        query: CrossDomainQuery,
        mappings: List[DomainMapping],
        execution_time: float,
        success: bool
    ):
        """Store query execution record"""
        if not self.db:
            return

        await self.db.execute_query(
            """INSERT INTO unified.cross_domain_queries
               (query_id, query_text, source_domains, target_domains,
                reasoning_strategy, execution_time, mappings_found, success)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
               ON CONFLICT (query_id) DO NOTHING""",
            (
                query.query_id,
                query.query_text,
                ','.join(d.value for d in query.source_domains),
                ','.join(d.value for d in query.target_domains),
                query.reasoning_strategy.value,
                execution_time,
                len(mappings),
                success
            ),
            commit=True
        )

    async def request_knowledge_transfer(
        self,
        transfer: KnowledgeTransferRequest
    ) -> bool:
        """Request knowledge transfer from source to target domain"""
        self.stats['total_transfers'] += 1

        logger.info(
            f"Knowledge transfer: {transfer.concept} "
            f"({transfer.source_domain.value} → {transfer.target_domain.value})"
        )

        try:
            # Store transfer record
            if self.db:
                await self.db.execute_query(
                    """INSERT INTO unified.knowledge_transfers
                       (transfer_id, source_domain, target_domain, concept,
                        concept_type, transfer_method, success, requested_by, metadata)
                       VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                       ON CONFLICT (transfer_id) DO NOTHING""",
                    (
                        transfer.transfer_id,
                        transfer.source_domain.value,
                        transfer.target_domain.value,
                        transfer.concept,
                        transfer.concept_type.value,
                        transfer.transfer_method.value,
                        True,
                        transfer.requested_by,
                        json.dumps(transfer.metadata) if transfer.metadata else None
                    ),
                    commit=True
                )

            logger.info(f"✓ Knowledge transfer completed: {transfer.transfer_id}")
            return True

        except Exception as e:
            logger.error(f"Knowledge transfer failed: {e}")
            return False

    async def get_statistics(self) -> Dict[str, Any]:
        """Get domain master statistics"""
        return {
            **self.stats,
            "domains_loaded": len(self.domain_cache),
            "cached_mappings": sum(len(v) for v in self.mapping_cache.values())
        }

    async def shutdown(self):
        """Shutdown and cleanup"""
        # Database connection is managed by TorinUnifiedDatabase singleton
        # No need to close here
        logger.info("Universal Domain Master shutdown complete")


# Global instance
_universal_domain_master: Optional[UniversalDomainMaster] = None


def get_universal_domain_master() -> UniversalDomainMaster:
    """Get global Universal Domain Master instance"""
    global _universal_domain_master
    if _universal_domain_master is None:
        _universal_domain_master = UniversalDomainMaster()
    return _universal_domain_master


# Alias for backwards compatibility
get_domain_master = get_universal_domain_master
