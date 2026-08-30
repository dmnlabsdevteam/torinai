"""The shapes learning is asked to take, and which of them are real.

TWO STACKS LEARN IN THIS CODEBASE AND THEY ARE NOT THE SAME SHAPE.

`ILearningSystem` was drawn around the model-based system: `adapt_behavior`,
`consolidate_learning`, `predict_optimal_retry_delay`. Its ONE implementer,
`UnifiedLearningSystem`, refuses six of its sixteen methods outright, each
with a message saying the capability belongs to a different subsystem --
behaviour adaptation to the coordinator, consolidation to memory, strategy
selection to the meta-learner. A contract whose only implementer cannot honour
a third of it is not describing anything; it is a wish list that forces
do-nothing methods.

`learning_authority.py` -- the substrate's own learning owner -- declines it
for exactly that reason, and says so:

    NOT AN `ILearningSystem`. That interface was shaped around the model-based
    system, and implementing it here would mean writing several methods that
    do nothing in order to satisfy a shape. The authority exposes what it
    actually owns.

So the six refused methods are no longer required. Five move to contracts
named for the subsystems that really own them -- `IStrategySelection`
(MetaLearner), `IOutcomePrediction` (PredictiveIntelligenceSystem),
`IMemoryConsolidation` (MemoryAgent) -- and `ILearningSystem` shrinks to the
ten its implementer genuinely provides.

TWO WERE DELETED RATHER THAN REHOMED, because they described nothing.

`adapt_behavior(context: Dict) -> Dict` had ZERO callers anywhere in core/,
experiments/ or tests/, and its body returned
`{'adaptation': 'unified_system', 'context_applied': True}` -- a claim the
context had been applied, from a body that read neither the context nor
anything else. It named neither what is adapted nor from what evidence, which
is why nothing could call it. The two mechanisms that really do adapt
behaviour say both: `MetaLearner.adapt_strategies(task_type: TaskFamily)`
adjusts strategy parameters from measured posteriors, and
`adapt_plan(plan_id, feedback) -> ExecutionPlan` revises one plan given
specific feedback. An interface for the vague third thing would imply somebody
should provide it.

`predict_optimal_retry_delay` went the same way: its body returned a hardcoded
3.0, and the guidance is an explicit backoff policy at the call site until a
real predictor exists.

`ILearningAuthority` is the substrate-shaped contract: induction, procedure
derivation, contribution admission. It describes what the substrate
already does, so the authority can declare it without inventing a method.
"""

import uuid
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence
from dataclasses import dataclass, field
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class LearningType(Enum):
    """How something was learned.

    The first six are model-training vocabulary and are kept because
    `unified_learning_system` reconstructs them from stored strings
    (`LearningType(str(...).lower())`), so removing one orphans every row
    carrying it.

    The substrate does not learn by any of them. It induces rules from
    demonstrations, derives procedures from input/output pairs, and admits
    contributions against evidence -- none of which had a name here, so
    substrate learning could not be labelled at all.
    """

    # Model-training vocabulary (persistence contract -- do not rename)
    SUPERVISED = "supervised"
    UNSUPERVISED = "unsupervised"
    REINFORCEMENT = "reinforcement"
    TRANSFER = "transfer"
    CONTINUAL = "continual"
    META = "meta"

    # How the substrate actually learns
    #: A rule generalised from demonstrations of a transition (RuleInducer).
    INDUCTION = "induction"
    #: A procedure derived from input/output pairs alone (procedure_synthesis).
    SYNTHESIS = "synthesis"
    #: A causal structure narrowed by observation (probabilistic version space).
    CAUSAL = "causal"
    #: A proposal admitted against evidence roots, carrying no confidence of
    #: its own (LearningAuthority.contribute).
    CONTRIBUTION = "contribution"


class AdaptationType(Enum):
    """Types of adaptation"""
    PARAMETER = "parameter"
    STRUCTURAL = "structural"
    BEHAVIORAL = "behavioral"
    STRATEGIC = "strategic"


@dataclass
class LearningEvent:
    """Learning event data"""
    event_id: str
    event_type: LearningType
    data: Dict[str, Any]
    outcome: Optional[Dict[str, Any]] = None
    #: When it happened. Defaulted to 0.0 -- the Unix epoch -- so an event with
    #: no stamp claimed to have occurred in 1970 and sorted before everything.
    timestamp: float = field(default_factory=lambda: datetime.now().timestamp())
    #: None until something measures it. 0.0 is a measurement meaning "no
    #: confidence at all", which is a different claim from "not assessed".
    confidence: Optional[float] = None


@dataclass
class Knowledge:
    """Knowledge representation"""
    knowledge_id: str
    category: str
    content: Dict[str, Any]
    confidence: float
    source: str
    timestamp: float
    tags: Optional[List[str]] = None


@dataclass
class LearningExample:
    """Example for learning systems"""
    example_id: str
    inputs: Dict[str, Any]
    targets: Optional[Dict[str, Any]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    # Quality metrics. None means UNASSESSED. These defaulted to
    # quality_score=1.0 and importance=1.0, so every example asserted itself
    # perfect and maximally important until something said otherwise -- and a
    # consumer weighting by quality could not tell a graded example from an
    # ungraded one.
    quality_score: Optional[float] = None
    difficulty: Optional[float] = None
    importance: Optional[float] = None

    # Temporal information
    timestamp: float = field(default_factory=lambda: datetime.now().timestamp())

    # Learning context
    task_type: Optional[str] = None
    domain: str = "general"
    source: str = "unknown"

    def __post_init__(self):
        if not self.example_id:
            self.example_id = str(uuid.uuid4())


@dataclass
class LearningResult:
    """Result of a learning operation"""
    result_id: str
    success: bool
    learned_knowledge: Dict[str, Any]

    # Performance metrics. None means NOT MEASURED; 0.0 means measured at
    # zero. A learning result that was never scored reported accuracy 0.0,
    # which reads as "it learned nothing" rather than "nobody checked".
    accuracy: Optional[float] = None
    confidence: Optional[float] = None
    processing_time: Optional[float] = None

    # Strategy information
    # Was typed against a second, dead "LearningStrategy" enum that duplicated
    # LearningType above; retyped onto the live one.
    strategy_used: Optional[LearningType] = None
    strategy_effectiveness: Optional[float] = None

    # Meta information
    improvements: List[str] = field(default_factory=list)
    insights: List[str] = field(default_factory=list)

    # Error information
    error: Optional[str] = None
    warnings: List[str] = field(default_factory=list)

    # Additional context
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.result_id:
            self.result_id = str(uuid.uuid4())


class IAdaptationEngine(ABC):
    """Observing the system, changing it, and checking whether that helped.

    THIS DESCRIBES `EnhancedASISelfImprovement`, WHICH ALREADY DOES ALL OF IT.
    The old five methods -- analyze_performance, identify_adaptation_needs,
    generate_adaptation_strategy, apply_adaptation, validate_adaptation -- map
    one for one onto phases that exist and run:

        analyze_performance          -> _assess_improvements
                                        ImprovementMonitor.detect_degradation
        identify_adaptation_needs    -> select_targets_by_constraint (Z3)
        generate_adaptation_strategy -> _generate_improvements
        apply_adaptation             -> _deploy_improvements
        validate_adaptation          -> _evaluate_impact
                                        _check_capability_regression

    Nothing declared it, so a search for "who adapts the system" found an
    abstract class with no implementer while a working eight-phase cycle sat
    in `enhanced_asi_self_improvement.py`.

    THE PHASES ARE INTERNAL AND STAY INTERNAL. Requiring `_assess_improvements`
    as an abstract method would make an implementation detail part of the
    contract and force any other engine to adopt this one's decomposition. The
    contract is what a CALLER can use: observe the system, run a cycle, read
    what happened. The five phases are how this implementation runs one cycle.
    """

    @abstractmethod
    async def observe_system(self) -> Dict[str, Any]:
        """What the system looks like now -- environment, topology, behaviour.

        Adaptation that has not looked cannot be evidence-based, which is why
        observation is part of the contract and not a private step.
        """
        raise NotImplementedError("Subclasses must implement observe_system()")

    @abstractmethod
    async def run_improvement_cycle(self, scope: Any = None,
                                    **options: Any) -> Any:
        """Assess, select, change, and measure -- once.

        Returns the cycle record, including what was NOT done and why. A cycle
        that changed nothing is a real outcome and must be reported as one
        rather than as a failure.
        """
        raise NotImplementedError(
            "Subclasses must implement run_improvement_cycle()")

    @abstractmethod
    async def get_persisted_statistics(self) -> Dict[str, Any]:
        """What adaptation has actually achieved, from the durable record.

        FROM THE STORE, NOT FROM MEMORY. An engine reporting its own
        in-process counters says zero after every restart, and a health check
        constructing one fresh reads that as "self-improvement has never run".
        """
        raise NotImplementedError(
            "Subclasses must implement get_persisted_statistics()")


# `IKnowledgeManager` was REMOVED, and not because its capabilities are
# missing. Every one of them is owned:
#
#     store_knowledge    -> ConceptIngestionService.ingest, which declares
#                           itself "the only writer of unified.concepts";
#                           RuleStore.record_induction for learned rules
#     retrieve_knowledge -> MemoryAgent.retrieve_memory; RuleStore.get
#     update_knowledge   -> RuleStore.validate (an epistemic status transition)
#     validate_knowledge -> RuleStore.validate, which enforces that a rule
#                           cannot validate itself using the evidence it was
#                           induced from
#     merge_knowledge    -> RuleStore.supersede, which keeps the refuted rule,
#                           its refuting evidence AND its replacement;
#                           MemoryAgent.consolidate_old_duplicates
#
# IT ASSUMED ONE KNOWLEDGE STORE WITH ONE NOTION OF VALIDITY. The substrate
# has three, separated on purpose: concepts promoted by independent evidence
# roots, rules moving CANDIDATE -> SUPPORTED -> VALIDATED -> REFUTED where
# REFUTED is RETAINED ("a store that erases its failures can only ever report
# survivorship"), and memories tiered by a filter. Collapsing those into one
# `validate_knowledge(id) -> bool` would flatten RuleStore's provenance
# invariant into a boolean.
#
# So the capability list lives here as a map to its owners, and there is no
# interface implying a single one exists.


class ILearningSystem(ABC):
    """Main learning system interface"""
    
    @abstractmethod
    async def initialize(self) -> bool:
        """Initialize the learning system"""
        # Implementation required in subclasses
        # Should set up learning algorithms, models, and data structures
        # Returns initialization success
        raise NotImplementedError("Subclasses must implement initialize()")
    
    @abstractmethod
    async def learn_from_data(self, data: Dict[str, Any], learning_type: LearningType) -> LearningEvent:
        """Learn from provided data"""
        # Implementation required in subclasses
        # Should process data using appropriate learning algorithms
        # Returns learning event with results
        raise NotImplementedError("Subclasses must implement learn_from_data()")
    
    @abstractmethod
    async def learn_from_experience(self, experience: Dict[str, Any]) -> LearningEvent:
        """Learn from experience data"""
        # Implementation required in subclasses
        # Should extract patterns and knowledge from experience
        # Returns learning event
        raise NotImplementedError("Subclasses must implement learn_from_experience()")
    
    @abstractmethod
    async def learn_from_feedback(self, feedback: Dict[str, Any]) -> LearningEvent:
        """Learn from feedback"""
        # Implementation required in subclasses
        # Should incorporate feedback into learning models
        # Returns learning event
        raise NotImplementedError("Subclasses must implement learn_from_feedback()")
    
    @abstractmethod
    async def transfer_learning(self, source_domain: str, target_domain: str) -> bool:
        """Transfer learning between domains"""
        # Implementation required in subclasses
        # Should transfer knowledge from source to target domain
        # Returns transfer success
        raise NotImplementedError("Subclasses must implement transfer_learning()")
    
    @abstractmethod
    async def get_learning_metrics(self) -> Dict[str, Any]:
        """Get learning performance metrics"""
        # Implementation required in subclasses
        # Should return comprehensive learning statistics
        # Returns metrics dictionary
        raise NotImplementedError("Subclasses must implement get_learning_metrics()")
    
    @abstractmethod
    def learn_from_event(self, event: Dict[str, Any]) -> bool:
        """Learn from an autonomous system event"""
        # Implementation required in subclasses
        # Should process system events for learning opportunities
        # Returns learning success
        raise NotImplementedError("Subclasses must implement learn_from_event()")
    
    @abstractmethod
    async def process_experience(self, experience: Dict[str, Any]) -> Dict[str, Any]:
        """Process experience data for learning"""
        # Implementation required in subclasses
        # Should extract learning signals from experience
        # Returns processed experience data
        raise NotImplementedError("Subclasses must implement process_experience()")
    
    @abstractmethod
    async def query_experiences(self, query: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Query past experiences"""
        # Implementation required in subclasses
        # Should search experience database using query parameters
        # Returns matching experiences
        raise NotImplementedError("Subclasses must implement query_experiences()")
    
    @abstractmethod
    async def get_experience_count(self) -> int:
        """Get total count of experiences"""
        # Implementation required in subclasses
        # Should return total number of stored experiences
        # Returns experience count
        raise NotImplementedError("Subclasses must implement get_experience_count()")


class IMemoryConsolidation(ABC):
    """Turning recent memory into long-term knowledge, and moving it down tiers.

    Drawn from `MemoryAgent`'s real surface. `UnifiedLearningSystem` refuses
    `consolidate_learning` and names the owner: "Memory consolidation is owned
    by MemoryAgent (hot/cold tiering); call it there." Behind that refusal sit
    five working methods -- `consolidate_memories`, `consolidate_old_duplicates`,
    `_consolidate_cluster`, `migrate_to_cold_tier`, `modify_tier_thresholds` --
    and none of them were typed as consolidating anything, so a search for the
    capability found the stub that raises and not the code that works.

    THAT IS THE DEFECT THIS INTERFACE EXISTS TO FIX. Not a missing capability:
    a working one nothing could name.
    """

    @abstractmethod
    async def consolidate_memories(self) -> Any:
        """Fold recent memory into longer-lived structure."""
        raise NotImplementedError("Subclasses must implement consolidate_memories()")

    @abstractmethod
    async def consolidate_old_duplicates(self, days_back: int = 30,
                                         batch_size: int = 100,
                                         similarity_threshold: float = 0.85) -> Any:
        """Merge memories that say the same thing.

        DEDUPLICATION IS LOSSY AND THE THRESHOLD DECIDES WHAT IS LOST. It is a
        parameter here rather than a constant inside, because a store that
        silently merged near-duplicates once destroyed performance history --
        failures were kept and successes discarded, and the survivorship was
        invisible from the outside.
        """
        raise NotImplementedError(
            "Subclasses must implement consolidate_old_duplicates()")

    @abstractmethod
    async def migrate_to_cold_tier(self, memory_id: str, force: bool = False,
                                   tier_hint: Optional[str] = None) -> bool:
        """Move one memory out of the hot tier."""
        raise NotImplementedError("Subclasses must implement migrate_to_cold_tier()")


class IStrategySelection(ABC):
    """Choosing an approach, and learning which approach pays off.

    DRAWN FROM `MetaLearner`'S REAL SURFACE, not from an idea of what strategy
    selection should look like. The first version of this interface asked for
    `recommend_strategies(context: Dict) -> List[str]` and
    `update_strategy_effectiveness(strategy: str, effectiveness: float)`, which
    match nothing: the meta-learner selects a `LearningStrategy` for a
    `TaskFamily` and records an outcome with a performance score, a duration
    and an outcome class. Declaring the generic shape would have forced two
    adapter methods that flatten a typed decision into a list of strings --
    the same do-nothing-to-satisfy-a-shape problem `learning_authority`
    refused `ILearningSystem` over.

    `UnifiedLearningSystem` refuses the old names and points here:
    "Use MetaLearner.select_strategy, which ranks real registered arms by
    their measured posteriors."

    Types are left open because this package must not import the concrete
    module it describes; the docstrings name what each argument really is.
    """

    @abstractmethod
    async def select_strategy(self, task_type: Any, **constraints: Any) -> Optional[Any]:
        """The strategy to try for this `TaskFamily`, or None if none qualifies.

        None is a real answer: no registered arm met the gate, which is not
        the same as picking the least bad one.
        """
        raise NotImplementedError("Subclasses must implement select_strategy()")

    @abstractmethod
    async def track_learning_outcome(self, task_type: Any, strategy_type: Any,
                                     success: bool, performance_score: float,
                                     time_ms: float, **context: Any) -> Any:
        """Record how a strategy actually performed, so the posterior moves.

        The credit invariant applies here: a strategy is never charged for an
        infrastructure failure, which is what `outcome_class` distinguishes.
        """
        raise NotImplementedError(
            "Subclasses must implement track_learning_outcome()")

    @abstractmethod
    async def evaluate_strategies(self, task_type: Any = None) -> Dict[str, Any]:
        """What the arms currently look like, on measured evidence."""
        raise NotImplementedError("Subclasses must implement evaluate_strategies()")


class IOutcomePrediction(ABC):
    """Predicting what will happen, and CHECKING the prediction afterwards.

    Drawn from `PredictiveIntelligenceSystem`'s real surface. The first draft
    of this asked for `predict_outcome(domain, context)` -- a shape that owner
    does not have, which would have forced an adapter method for the second
    time in one file. Contracts here are written from the implementation
    outward, because the alternative is what produced six methods that existed
    only to raise.

    `UnifiedLearningSystem` names this owner directly: "PredictiveIntelligence
    System is the prediction owner", after its own body "returned constant
    0.85/0.8 for every context".

    VALIDATION IS PART OF THE CONTRACT, not an extra. A predictor that never
    checks its predictions against what actually happened cannot be wrong, and
    a confidence it never has to answer for is decoration. `validate_prediction`
    is the method that makes the rest of it evidence.

    `predict_optimal_retry_delay` is deliberately absent. It has no owner: the
    previous implementation returned a hardcoded 3.0, and the stated guidance
    is an explicit backoff policy at the call site until a real predictor
    exists. An interface for it would imply somebody provides it.
    """

    @abstractmethod
    async def generate_comprehensive_prediction(self, domain: Any, horizon: Any,
                                                **context: Any) -> Any:
        """A prediction for this domain over this horizon, with its uncertainty."""
        raise NotImplementedError(
            "Subclasses must implement generate_comprehensive_prediction()")

    @abstractmethod
    async def validate_prediction(self, prediction_id: str, actual_value: Any) -> Any:
        """Score a past prediction against what actually happened."""
        raise NotImplementedError("Subclasses must implement validate_prediction()")

    @abstractmethod
    async def get_prediction_insights(self) -> Dict[str, Any]:
        """How the predictor has actually been doing, on validated outcomes."""
        raise NotImplementedError(
            "Subclasses must implement get_prediction_insights()")


class ILearningAuthority(ABC):
    """What the substrate actually does.

    Drawn from `LearningAuthority`'s real surface rather than from an idea of
    what a learner should look like, so it can be declared without a single
    method that exists to satisfy a shape.

    THE ASYMMETRY IS THE POINT. `induce` and `derive_procedure` produce
    knowledge from evidence the world supplied. `contribute` admits a proposal
    from anywhere -- including a language model -- as a CANDIDATE with no
    confidence of its own. A contributor may propose; only evidence promotes.
    """

    @abstractmethod
    def induce(self, examples: Sequence[Any], target_predicate: Optional[str] = None):
        """Generalise a rule from demonstrations of a transition."""
        raise NotImplementedError("Subclasses must implement induce()")

    @abstractmethod
    def derive_procedure(self, operators, guards, examples,
                         terminal: str = "RESULT", max_rules: Optional[int] = None):
        """Compose learned operators into a procedure that produces the answer."""
        raise NotImplementedError("Subclasses must implement derive_procedure()")

    @abstractmethod
    async def contribute(self, contribution: Any):
        """Admit a proposal as a candidate. Never as knowledge."""
        raise NotImplementedError("Subclasses must implement contribute()")

    @abstractmethod
    async def rules(self, domain_id: Optional[str] = None):
        """The rules currently held, with their epistemic status."""
        raise NotImplementedError("Subclasses must implement rules()")

    @abstractmethod
    async def metrics(self) -> Dict[str, Any]:
        """What has been learned, and on what evidence."""
        raise NotImplementedError("Subclasses must implement metrics()")
