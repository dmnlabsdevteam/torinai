#!/usr/bin/env python3
"""
Shared types and enums for the autonomous system
Essential data structures
"""

from enum import Enum
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional, Set
from datetime import datetime


# ============================================================================
# CORE ENUMS (Simplified from 26+ enums to essential ones)
# ============================================================================

class SystemMode(Enum):
    """System operational modes"""
    AUTONOMOUS = "autonomous"
    SUPERVISED = "supervised"
    MAINTENANCE = "maintenance"
    SHUTDOWN = "shutdown"


class TaskType(Enum):
    """Task type classification"""
    RESEARCH = "research"
    ANALYSIS = "analysis"
    SYNTHESIS = "synthesis"
    EXECUTION = "execution"
    PLANNING = "planning"
    VALIDATION = "validation"
    COMMUNICATION = "communication"
    LEARNING = "learning"
    OPTIMIZATION = "optimization"
    SECURITY_REMEDIATION = "security_remediation"
    SELF_IMPROVEMENT = "self_improvement"


class TaskStatus(Enum):
    """
    Task execution status - aligned with CompletionState.
    
    State Machine:
    PLANNED -> IN_PROGRESS (execution starts)
    IN_PROGRESS -> AWAITING_VERIFICATION (LLM proposes completion)
    AWAITING_VERIFICATION -> VERIFIED (system validates)
    AWAITING_VERIFICATION -> IN_PROGRESS (validation failed, retry)
    IN_PROGRESS -> FAILED (unrecoverable error)
    IN_PROGRESS -> BLOCKED (dependency not met)
    
    CRITICAL: Only the completion validator can move to VERIFIED.
    """
    PLANNED = "planned"
    PENDING = "pending"  # Legacy - maps to PLANNED
    IN_PROGRESS = "in_progress"
    AWAITING_VERIFICATION = "awaiting_verification"  # LLM proposed completion
    VERIFIED = "verified"  # System confirmed completion
    COMPLETED = "completed"  # Legacy - maps to VERIFIED
    FAILED = "failed"
    CANCELLED = "cancelled"
    BLOCKED = "blocked"
    PARTIALLY_COMPLETE = "partially_complete"  # Budget exhausted


class GoalType(Enum):
    """What kind of thing a goal is, which decides how it may be planned.

    STATE goals name conditions that must hold in the world; they are planned
    by search over learned operators and are allowed to fail. DESCRIPTIVE goals
    are prose and get template decomposition.

    The distinction exists so that template planning can never be reached by a
    state planner failing. Otherwise an unreachable goal quietly becomes
    "Research -> Analyze -> Execute" and the system manufactures a plan exactly
    when real planning proved there wasn't one.
    """

    STATE = "state"
    DESCRIPTIVE = "descriptive"


class Priority(Enum):
    """Priority levels for tasks and goals"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


#: The rank of each priority, defined once.
#:
#: `unified.goals.priority` is an INTEGER column while Priority's values are
#: strings, so persistence needs an ordinal. That ordinal already existed
#: implicitly inside PlanningEngine.get_next_tasks's sort; naming it here keeps
#: storage and ordering from drifting into two different answers about whether
#: HIGH outranks MEDIUM.
PRIORITY_ORDINAL: Dict["Priority", int] = {
    Priority.LOW: 0,
    Priority.MEDIUM: 1,
    Priority.HIGH: 2,
    Priority.CRITICAL: 3,
}

_ORDINAL_PRIORITY: Dict[int, "Priority"] = {v: k for k, v in PRIORITY_ORDINAL.items()}


def priority_from_ordinal(ordinal: Optional[int]) -> Priority:
    """Reverse PRIORITY_ORDINAL. Unknown ranks raise rather than defaulting.

    Silently returning MEDIUM for an unrecognised value would let a corrupted
    row load as an ordinary goal, and the corruption would never be visible.
    """
    if ordinal not in _ORDINAL_PRIORITY:
        raise ValueError(
            f"priority ordinal {ordinal!r} is not one of "
            f"{sorted(_ORDINAL_PRIORITY)}"
        )
    return _ORDINAL_PRIORITY[ordinal]


class TaskSource(Enum):
    """Task source types for governance differentiation"""
    API = "api"  # Tasks from API requests
    MANUAL = "manual"  # Manually created by human
    AUTONOMOUS = "autonomous"  # AI-generated tasks
    SYSTEM = "system"  # System-generated tasks
    SECURITY_AUDIT = "security_audit"  # Security audit worker findings


#: The actor a task belongs to when it is the SUBSTRATE'S OWN work.
#:
#: Not a user, and deliberately not a string a user could ever hold. Health
#: monitoring, security auditing, the idle loops -- this is Torin's own
#: cognition, and its memories and learned evidence belong to Torin, never to
#: whoever happened to be connected when a loop fired. Scoping the substrate's
#: health knowledge to a passing user would be as wrong as leaking that user's
#: context into the substrate's learning.
SUBSTRATE_ACTOR = "__substrate__"

#: Which sources are the substrate acting on its own behalf. A task from one of
#: these is owned by the substrate; anything else is owned by the user who
#: caused it, and MUST carry that user's id as its actor.
_SUBSTRATE_SOURCES = frozenset({
    TaskSource.AUTONOMOUS, TaskSource.SYSTEM, TaskSource.SECURITY_AUDIT,
})


def actor_for(source: "TaskSource", user_id: Optional[str]) -> str:
    """The actor a task belongs to, decided by its source.

    ONE RULE, IN ONE PLACE, so the internal/external line cannot be drawn
    differently at different call sites. Substrate-sourced work is the
    substrate's own; user-sourced work (API, MANUAL) is the user's and requires
    an id. A user-sourced task with no id is a bug the caller must fix, not a
    task to file under the substrate -- filing it there is exactly the leak this
    guards against, so it raises rather than defaulting.
    """
    if source in _SUBSTRATE_SOURCES:
        return SUBSTRATE_ACTOR
    if not user_id:
        raise ValueError(
            f"a {source.value} task must name the user it belongs to; "
            f"refusing to file user work under the substrate")
    if user_id == SUBSTRATE_ACTOR:
        raise ValueError("a user may not claim the substrate's actor id")
    return user_id


def is_substrate_actor(actor: Optional[str]) -> bool:
    """Whether this actor is the substrate itself rather than a user."""
    return actor is None or actor == SUBSTRATE_ACTOR


# ============================================================================
# CORE DATA STRUCTURES (Simplified from 40+ classes)
# ============================================================================

@dataclass
class Task:
    """
    Task representation with verifiable completion criteria.
    
    Completion:
    - success_criteria: optional hints the coordinator seeds for a task.
    A task is VERIFIED by the substrate re-observing the world (the executor
    confirms its own effects / re-observes the goal state) — not by a
    generator-policing completion protocol, which has been retired.
    """
    id: str
    type: TaskType
    description: str
    priority: Priority = Priority.MEDIUM
    status: TaskStatus = TaskStatus.PENDING
    created_at: datetime = field(default_factory=datetime.now)
    estimated_duration: float = 0.0  # minutes
    dependencies: List[str] = field(default_factory=list)
    result: Optional[Dict[str, Any]] = None
    completed_at: Optional[datetime] = None
    deadline: Optional[datetime] = None  # Hard deadline for IterationController time budget
    #: How this task came to exist. For a state plan: the goal and plan it
    #: belongs to, the planning mode and verdict, the grounded operator, and the
    #: learned rule that authorised it. Kept so the record answers not only what
    #: Torin did but which acquired experience gave it authority to do it.
    provenance: Optional[Dict[str, Any]] = None

    # Phase 5A: Task source tracking for governance
    source: TaskSource = TaskSource.AUTONOMOUS
    #: WHO THIS TASK BELONGS TO. `SUBSTRATE_ACTOR` for the substrate's own work;
    #: a user id for anything a user caused. Everything downstream -- which
    #: memories may enter its cognition, whose evidence a runtime outcome
    #: attributes to, which profile it feeds -- reads this. Defaults to the
    #: substrate because the default source is AUTONOMOUS; a user-facing entry
    #: point sets it via `actor_for(source, user_id)`.
    actor: str = SUBSTRATE_ACTOR
    created_by: str = "autonomous_coordinator"
    governance_approved: bool = False
    governance_action_id: Optional[str] = None

    # === COMPLETION PROTOCOL FIELDS ===
    # Legacy field (still used for backwards compatibility)
    success_criteria: Optional[Dict[str, Any]] = None
    
    # NEW: Formal acceptance criteria (list of criterion dicts)
    acceptance_criteria: List[Dict[str, Any]] = field(default_factory=list)
    
    # NEW: Required artifacts (file paths or output keys)
    required_artifacts: List[str] = field(default_factory=list)
    
    # NEW: Validation strategy (unit_tests, static_analysis, research_validation, etc.)
    validation_strategy: str = "auto"
    
    # NEW: Completion score from last verification attempt
    completion_score: Optional[float] = None
    
    # NEW: Premature completion detection fields
    remaining_risks: List[str] = field(default_factory=list)
    open_questions: List[str] = field(default_factory=list)
    assumptions: List[str] = field(default_factory=list)
    
    # NEW: Budget constraints
    max_time_seconds: Optional[int] = None
    max_tokens: Optional[int] = None
    max_iterations: Optional[int] = None
    
    # NEW: Graph-based completion (parent/child/dependencies)
    parent_task_id: Optional[str] = None
    child_task_ids: List[str] = field(default_factory=list)
    
    # NEW: Verification tracking
    verification_attempts: int = 0
    last_verification_result: Optional[Dict[str, Any]] = None
    
    # NEW: Generic completion callbacks (Phase 6: Closure Hooks)
    # List of (callback_fn, metadata) tuples to execute on task completion
    # Each callback receives (task, result, confidence) and can perform cleanup actions
    completion_callbacks: List[tuple] = field(default_factory=list)
    verified_at: Optional[datetime] = None
    
    # Execution tracking
    retry_count: int = 0
    max_retries: int = 1
    metadata: Dict[str, Any] = field(default_factory=dict)

    #: The tools this task may use, or None for UNRESTRICTED. None is the
    #: substrate's own work (it has every tool); a list is a SCOPED grant the
    #: substrate defines when it deploys an agent, so a spawned copy can
    #: only reach the tools it was given. The executor enforces this.
    allowed_tools: Optional[List[str]] = None

    def __post_init__(self):
        """Validate and fix types after initialization"""
        # Ensure priority is a Priority enum, not a dict or other type
        if not isinstance(self.priority, Priority):
            if isinstance(self.priority, dict):
                # If it's a dict, try to extract the value or use default
                priority_value = self.priority.get('value', 'medium') if 'value' in self.priority else 'medium'
                self.priority = Priority[priority_value.upper()] if isinstance(priority_value, str) else Priority.MEDIUM
            elif isinstance(self.priority, str):
                # Convert string to Priority enum
                try:
                    self.priority = Priority[self.priority.upper()]
                except (KeyError, AttributeError):
                    self.priority = Priority.MEDIUM
            else:
                # Default fallback
                self.priority = Priority.MEDIUM


@dataclass
class Goal:
    """Simplified autonomous goal"""
    id: str
    description: str
    priority: Priority = Priority.MEDIUM
    deadline: Optional[datetime] = None
    created_at: datetime = field(default_factory=datetime.now)
    completed_at: Optional[datetime] = None
    status: str = "active"
    # Intrinsic motivation fields
    expected_novelty: float = 0.5  # Expected novelty from pursuing this goal
    expected_competence_gain: float = 0.5  # Expected skill improvement
    curiosity_value: float = 0.5  # Curiosity-driven interest in this goal
    intrinsic_reward_potential: float = 0.5  # Overall intrinsic reward potential
    metadata: Dict[str, Any] = field(default_factory=dict)
    #: Conditions that must hold in the world for this goal to be achieved.
    #: Present => the goal has state semantics and is planned by search over
    #: learned operators. Absent => it is a description, and only template
    #: planning applies. Planning MODE is chosen by this field and never by a
    #: planner having failed.
    state_conditions: Optional[List[str]] = None

    @property
    def goal_type(self) -> "GoalType":
        return GoalType.STATE if self.state_conditions else GoalType.DESCRIPTIVE

    def __post_init__(self):
        """Validate and fix types after initialization"""
        # Ensure all intrinsic values are floats, not dicts
        for field_name in ['expected_novelty', 'expected_competence_gain', 'curiosity_value', 'intrinsic_reward_potential']:
            value = getattr(self, field_name)
            if isinstance(value, dict):
                # If it's a dict, try to extract the value or use default
                value = value.get('value', 0.5) if 'value' in value else 0.5
            # Ensure it's a float
            try:
                setattr(self, field_name, float(value))
            except (TypeError, ValueError):
                setattr(self, field_name, 0.5)


@dataclass
class PerceptionData:
    """Simplified perception information"""
    source: str
    data_type: str
    content: Dict[str, Any]
    confidence: float = 1.0
    timestamp: float = field(default_factory=lambda: datetime.now().timestamp())
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Plan:
    """Simplified execution plan"""
    id: str
    goal_id: str
    tasks: List[Task]
    estimated_duration: float = 0.0
    confidence: float = 0.5
    created_at: datetime = field(default_factory=datetime.now)
    completed_at: Optional[datetime] = None
    status: str = "active"
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SystemState:
    """Current system state snapshot"""
    timestamp: float = field(default_factory=lambda: datetime.now().timestamp())
    mode: SystemMode = SystemMode.AUTONOMOUS
    active_tasks: List[str] = field(default_factory=list)
    active_goals: List[str] = field(default_factory=list)
    performance_metrics: Dict[str, float] = field(default_factory=dict)
    resources: Dict[str, Any] = field(default_factory=dict)
    resource_usage: float = 0.0


@dataclass
class LearningData:
    """Learning experience data for pattern recognition and adaptation"""
    context: Dict[str, Any]
    action: Dict[str, Any]
    outcome: Dict[str, Any]
    success: bool
    confidence: float = 0.5
    timestamp: float = field(default_factory=lambda: datetime.now().timestamp())
    metadata: Dict[str, Any] = field(default_factory=dict)