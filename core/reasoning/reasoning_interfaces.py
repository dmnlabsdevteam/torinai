"""
Reasoning system interfaces for inference and analysis
"""

import asyncio
from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional, Set, Union
from dataclasses import dataclass, field
from enum import Enum


class ReasoningType(Enum):
    """The KINDS OF THINKING Torin can do. One list, and this is it.

    THIS ENUM EXISTED TWICE. `abstract_reasoning_engine` declared its own with
    16 members while this one had 8; six names were shared. Enum equality is
    identity-based, so:

        interfaces.ReasoningType is engine.ReasoningType  ->  False
        A.DEDUCTIVE == B.DEDUCTIVE                        ->  False
        both print as                                     ->  'deductive'

    That is the fourth instance of the defect `tests/test_shadow_enum_guard.py`
    was written to prevent, and it passed only because ReasoningType was not on
    its watch list. It is now. A strategy registered against one copy was
    unreachable from the other, which is the difference between "this mode is
    not implemented" and "this mode is implemented and cannot be found".

    Every member of both copies is here; the shared six had identical values, so
    nothing that looked one up by value changes meaning.

    THE CLASSICAL ELEVEN come first, then the quantum family. They are separated
    because the quantum members need hardware Torin does not currently have --
    see `ReasoningType.is_quantum`.
    """

    # -- the eleven classical kinds of thinking -----------------------------
    DEDUCTIVE = "deductive"            # what must follow from the premises
    INDUCTIVE = "inductive"            # what the cases generalise to
    ABDUCTIVE = "abductive"            # what would best explain the observation
    ANALOGICAL = "analogical"          # what this is structurally like
    CAUSAL = "causal"                  # what brings about what
    PROBABILISTIC = "probabilistic"    # what the evidence makes more likely
    FUZZY = "fuzzy"                    # what holds by degree rather than sharply
    TEMPORAL = "temporal"              # what holds before, after, until
    SPATIAL = "spatial"                # what contains, adjoins, lies within
    LOGICAL = "logical"                # what is satisfiable / provable as stated
    COUNTERFACTUAL = "counterfactual"  # what would have followed instead

    # -- quantum family -----------------------------------------------------
    QUANTUM = "quantum"
    QUANTUM_SUPERPOSITION = "quantum_superposition"
    QUANTUM_ENTANGLEMENT = "quantum_entanglement"
    QUANTUM_INTERFERENCE = "quantum_interference"
    QUANTUM_PARALLELISM = "quantum_parallelism"
    QUANTUM_TUNNELING = "quantum_tunneling"
    QUANTUM_OPTIMIZATION = "quantum_optimization"

    @property
    def is_quantum(self) -> bool:
        """Whether this kind of thinking needs quantum execution.

        Asked so that "no quantum backend is attached" is answered once, by the
        thing that knows, instead of by each caller pattern-matching on a name
        prefix.
        """
        return self.value.startswith("quantum")


#: The kinds of thinking that need no special hardware. This is the list a
#: router must be able to reach in full.
CLASSICAL_REASONING_TYPES = tuple(t for t in ReasoningType if not t.is_quantum)


# ==========================================================================
# WHAT KIND OF THINKING DOES THIS CALL FOR?
#
# ONE ANSWER, OWNED HERE. Three separate things used to decide this and none of
# them was the enum:
#
#   ReasoningType                     the declared vocabulary -- consulted by
#                                     nothing that routes
#   NeuralBridgeRouter._build_context six keyword lists -> six private booleans
#                                     -> a routing MODE
#   _hybrid_reasoning                 three keyword lists -> is_temporal,
#                                     is_statistical, needs_proof -> which
#                                     ENGINES to load
#
# The third was already doing real thinking-mode selection: `is_temporal` IS
# ReasoningType.TEMPORAL and `needs_proof` IS ReasoningType.LOGICAL. They simply
# never said so, so the enum could gain a member that nothing would ever select
# and no one would notice -- which is what happened to CAUSAL, COUNTERFACTUAL,
# SPATIAL and FUZZY.
#
# The markers below are the union of the lists that were already in use, plus
# markers for the kinds that had none. Nothing that used to be detected stops
# being detected.
#
# CLOSED AND VISIBLE, in the style of the preposition list in neural_bridge.
# This is not an attempt at English. It is the handful of words whose presence
# indicates that a particular kind of thinking is being asked for, and it is
# meant to be read and argued with.
# ==========================================================================

REASONING_TYPE_MARKERS = {
    # -- was `needs_proof` + `formal_markers` -------------------------------
    ReasoningType.LOGICAL: (
        "prove", "proof", "verify", "guarantee", "constraint", "invariant",
        "assert", "precondition", "postcondition", "state machine",
        "statechart", "satisfiable", "consistent",
    ),
    # -- was `is_temporal` --------------------------------------------------
    ReasoningType.TEMPORAL: (
        "when", "before", "after", "during", "until", "temporal", "timeline",
        "sequence", "eventually", "always", "never", "meanwhile", "then",
    ),
    # -- was `is_statistical` -----------------------------------------------
    ReasoningType.PROBABILISTIC: (
        "probability", "probable", "likely", "unlikely", "statistical",
        "hypothesis", "odds", "chance", "expected", "prior", "posterior",
    ),
    # -- was part of `cross_domain_markers` ---------------------------------
    ReasoningType.ANALOGICAL: (
        "analogy", "analogical", "like ", "similar to", "resembles",
        "corresponds to", "transfer", "map to", "across domains",
    ),
    # -- had NO selector anywhere before ------------------------------------
    ReasoningType.CAUSAL: (
        "cause", "causes", "caused", "because", "due to", "leads to",
        "results in", "brings about", "triggers", "effect of", "consequence",
        "why does", "why did", "responsible for",
    ),
    ReasoningType.COUNTERFACTUAL: (
        "would have", "what if", "if instead", "instead of", "otherwise",
        "had it", "were it not", "counterfactual", "alternative outcome",
    ),
    ReasoningType.SPATIAL: (
        "inside", "within", "outside", "above", "below", "beneath", "near",
        "adjacent", "contains", "borders", "distance", "location", "between ",
    ),
    ReasoningType.FUZZY: (
        "roughly", "approximately", "somewhat", "mostly", "partially",
        "more or less", "to a degree", "tends to", "borderline", "vague",
    ),
    # -- reachable before only via the strategy registry --------------------
    ReasoningType.DEDUCTIVE: (
        "therefore", "thus", "hence", "it follows", "entails", "implies",
        "must be", "deduce",
    ),
    ReasoningType.INDUCTIVE: (
        "generally", "in general", "usually", "pattern", "every observed",
        "all observed", "tend to", "generalise", "generalize",
    ),
    ReasoningType.ABDUCTIVE: (
        "explain", "explanation", "account for", "best explains", "diagnose",
        "what would cause", "suspect",
    ),
}


def kinds_of_thinking_for(text: str) -> tuple:
    """Which ReasoningTypes the text asks for, most-evidenced first.

    RETURNS EMPTY WHEN NOTHING MATCHES, and that is deliberate. A default of
    "deductive" would make an unrecognised request indistinguishable from one
    that genuinely calls for deduction, and the caller could never tell that
    classification had failed. An empty result means "this text carries no
    marker of any kind of thinking" -- which is a fact the caller can act on,
    by asking for a mode explicitly or by declining.

    Several kinds can be asked for at once; "why did it fail before the
    timeout?" is causal AND temporal, and returning one of them would silently
    drop the other.
    """
    if not text:
        return ()
    lowered = f" {str(text).lower()} "
    scored = []
    for kind, markers in REASONING_TYPE_MARKERS.items():
        hits = sum(1 for marker in markers if marker in lowered)
        if hits:
            scored.append((hits, kind.value, kind))
    # Sorted by evidence, then by name so the order is stable across runs
    # rather than dependent on dict insertion.
    scored.sort(key=lambda row: (-row[0], row[1]))
    return tuple(kind for _, _, kind in scored)


def asks_for(text: str, kind: ReasoningType) -> bool:
    """Whether the text carries a marker of one specific kind of thinking.

    The convenience form for a caller that only cares about one -- what
    `is_temporal = any(kw in query for kw in [...])` used to do inline, now
    reading from the one marker table.
    """
    return kind in kinds_of_thinking_for(text)


class InferenceStrategy(Enum):
    """HOW an inference is searched for. Also previously declared twice.

    `abstract_reasoning_engine.InferenceMethod` held 12 members to this one's 5,
    sharing only FORWARD_CHAINING and BACKWARD_CHAINING -- so BIDIRECTIONAL,
    BEST_FIRST and MONTE_CARLO were invisible to the engine that does the
    searching, and the other seven were invisible to everything typed against
    this module. Merged here; `InferenceMethod` is now an alias of this class,
    not a second one.

    Distinct from ReasoningType on purpose: DEDUCTIVE says what kind of
    conclusion is being drawn, FORWARD_CHAINING says how the search for it runs.
    Collapsing them is what produced two overlapping vocabularies in the first
    place.
    """

    FORWARD_CHAINING = "forward_chaining"
    BACKWARD_CHAINING = "backward_chaining"
    BIDIRECTIONAL = "bidirectional"
    BEST_FIRST = "best_first"
    MONTE_CARLO = "monte_carlo"
    RESOLUTION = "resolution"
    UNIFICATION = "unification"
    PATTERN_MATCHING = "pattern_matching"
    CONSTRAINT_SATISFACTION = "constraint_satisfaction"
    BAYESIAN_INFERENCE = "bayesian_inference"
    FUZZY_LOGIC = "fuzzy_logic"
    NEURAL_REASONING = "neural_reasoning"
    QUANTUM_REASONING = "quantum_reasoning"
    QUANTUM_MEASUREMENT = "quantum_measurement"
    QUANTUM_GATE_OPERATIONS = "quantum_gate_operations"


#: `InferenceMethod` was the second name for this same concept. Kept as an
#: alias so existing callers keep working, and so that `InferenceMethod.X is
#: InferenceStrategy.X` -- which was the whole problem before.
InferenceMethod = InferenceStrategy


class UncertaintyMode(Enum):
    """WHAT KIND OF UNCERTAINTY is being quantified.

    RENAMED FROM `ReasoningMode`. It never was a way of thinking: epistemic vs
    aleatoric is a statement about where uncertainty comes from, not about how a
    conclusion is drawn. Sharing a name with `neural_bridge.ReasoningMode` --
    which is about ROUTING, and shares not one member with this -- made it read
    as a third competing list of reasoning modes.

    `ReasoningMode` below is kept as an alias for existing callers.
    """

    EPISTEMIC = "epistemic"
    ALEATORIC = "aleatoric"
    BAYESIAN = "bayesian"


#: Existing callers import `ReasoningMode` from here. Alias, not a copy.
ReasoningMode = UncertaintyMode


@dataclass
class ReasoningRequest:
    """Request for reasoning/uncertainty computation"""
    query: str
    mode: ReasoningMode
    context: Optional[Dict[str, Any]] = None


@dataclass
class ReasoningResult:
    """Result from reasoning computation"""
    uncertainty: float
    confidence: float = 1.0
    reasoning: Optional[str] = None


@dataclass
class ReasoningTask:
    """Reasoning task specification"""
    task_id: str
    task_type: ReasoningType
    premises: List[Dict[str, Any]]
    goals: List[str]
    constraints: Optional[List[str]] = None
    context: Optional[Dict[str, Any]] = None


@dataclass
class InferenceResult:
    """Result of inference operation"""
    result_id: str
    conclusions: List[Dict[str, Any]]
    confidence: float
    reasoning_path: List[str]
    metadata: Optional[Dict[str, Any]] = None


class Connectivity(Enum):
    """Whether the formal reading links the goal to the premises at all.

    Three outcomes were previously collapsed into `succeeded` plus a solver
    confidence of 0.0, which made them indistinguishable:

      UNSUPPORTED   the language could not be translated
      DISCONNECTED  it translated, but the goal shares no vocabulary with the
                    premises, so the solver was asked something the premises
                    cannot speak to
      CONNECTED     the reading links up; whatever the solver returns is a
                    verdict about entailment rather than about translation

    The dangerous one was DISCONNECTED reported as a successful formalization:
    the caller then reads 0.0 as "not entailed" when the truth is "nothing was
    asked that these premises could answer". That is a translation failure
    wearing the costume of a reasoning result.
    """

    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    UNSUPPORTED = "unsupported"


@dataclass
class Formalization:
    """A query rendered into the proof engine's formal grammar."""

    statement: str = ""
    premises: List[str] = field(default_factory=list)

    # Which formalizer produced this, for attribution in proof metadata.
    source: str = ""
    succeeded: bool = False
    error: Optional[str] = None

    #: Every claim the sentence makes, when it makes more than one.
    #:
    #: `statement` is a single string, so "the pump is hot and loud" could only
    #: return `pump_hot` and the second claim was silently dropped -- a reading
    #: that asserts less than the sentence did, which is a quieter failure than
    #: asserting the wrong thing. A conjunction fills this with both atoms and
    #: readers that want the whole sentence use it.
    statements: List[str] = field(default_factory=list)

    #: Set by formalizers that can determine it. UNSUPPORTED whenever the
    #: translation itself failed, so `succeeded` and this never disagree.
    connectivity: "Connectivity" = None  # type: ignore[assignment]

    def __post_init__(self):
        if self.connectivity is None:
            self.connectivity = (
                Connectivity.CONNECTED if self.succeeded else Connectivity.UNSUPPORTED
            )

    # Whether producing this representation needed a model. Deterministic
    # formalizers set False, model-backed ones set True. Tracking it here is
    # what makes the substrate-native vs model-formalized share measurable as
    # the deterministic extractor grows.
    requires_model: bool = False

    #: The sentences this was built from, kept so a proof can be traced back to
    #: what was actually said rather than to the atoms it became.
    surface_text: List[str] = field(default_factory=list)

    #: Per-sentence genericity, with the cue that produced it. QUANTIFICATIONAL
    #: INTERPRETATION IS COGNITION-BEARING STATE: whether "A robin is a bird"
    #: was read as a claim about a kind or about an individual determines
    #: whether a universal rule exists at all, so a proof resting on that rule
    #: must be able to say why it existed. Discarding the reading after
    #: emitting the formula makes that unreconstructable.
    readings: List[Dict[str, Any]] = field(default_factory=list)

    #: What was done to the surface text on the way in -- article removal,
    #: singularisation, generic class interpretation.
    transformations: List[str] = field(default_factory=list)


class IFormalizer(ABC):
    """Translates natural language into formal logic for the solver.

    Formalizers are deliberately fallible and hold no authority over truth.
    They decide only *what* is handed to the solver; the verdict and its
    confidence come from the solver alone. A bad formalization can therefore
    make a query unprovable, but can never make a false claim come back proved.

    Implementations are consulted cheapest-and-most-trustworthy first. Input
    that is already formal needs no model at all, which is what allows a
    deterministic extractor to take priority over a language model later
    without any caller changing.
    """

    #: Short identifier recorded on the Formalization it produces.
    name: str = "formalizer"

    @abstractmethod
    async def formalize(
        self,
        query: str,
        context: Optional[List[str]] = None
    ) -> Formalization:
        """Return a Formalization; succeeded=False when this formalizer cannot help."""
        pass


class IInferenceEngine(ABC):
    """Interface for inference operations"""
    
    @abstractmethod
    async def infer(self, premises: List[Dict[str, Any]], strategy: InferenceStrategy) -> InferenceResult:
        """Perform inference on premises"""
        pass
    
    @abstractmethod
    async def deduce(self, premises: List[Dict[str, Any]], rules: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Perform deductive reasoning"""
        pass
    
    @abstractmethod
    async def induce(self, observations: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Perform inductive reasoning"""
        pass
    
    @abstractmethod
    async def abduce(self, observations: List[Dict[str, Any]], hypotheses: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Perform abductive reasoning"""
        pass
    
    @abstractmethod
    async def validate_inference(self, inference: InferenceResult) -> float:
        """Validate inference result"""
        pass


class IAnalysisEngine(ABC):
    """Interface for data analysis operations"""
    
    @abstractmethod
    async def analyze_patterns(self, data: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Analyze patterns in data"""
        pass
    
    @abstractmethod
    async def analyze_relationships(self, entities: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Analyze relationships between entities"""
        pass
    
    @abstractmethod
    async def analyze_trends(self, time_series: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Analyze trends in time series data"""
        pass
    
    @abstractmethod
    async def analyze_anomalies(self, data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Detect and analyze anomalies"""
        pass
    
    @abstractmethod
    async def generate_insights(self, analysis_results: Dict[str, Any]) -> List[str]:
        """Generate insights from analysis"""
        pass


class IReasoningEngine(ABC):
    """Main reasoning engine interface"""
    
    @abstractmethod
    async def initialize(self) -> bool:
        """Initialize the reasoning engine"""
        pass
    
    @abstractmethod
    async def reason(self, task: ReasoningTask) -> InferenceResult:
        """Perform reasoning on a task"""
        pass
    
    @abstractmethod
    async def solve_problem(self, problem: Dict[str, Any]) -> Dict[str, Any]:
        """Solve a complex problem"""
        pass
    
    @abstractmethod
    async def explain_reasoning(self, result: InferenceResult) -> List[str]:
        """Explain the reasoning process"""
        pass
    
    @abstractmethod
    async def learn_reasoning_patterns(self, examples: List[Dict[str, Any]]) -> bool:
        """Learn new reasoning patterns from examples"""
        pass
    
    @abstractmethod
    async def get_reasoning_capabilities(self) -> List[ReasoningType]:
        """Get supported reasoning types"""
        pass
    
    @abstractmethod
    async def evaluate_reasoning_performance(self) -> Dict[str, Any]:
        """Evaluate reasoning engine performance"""
        pass
    
    @abstractmethod
    async def process_query(self, query: Union[str, Dict[str, Any]]) -> Dict[str, Any]:
        """Process a query (string or dict) and return reasoning results"""
        pass