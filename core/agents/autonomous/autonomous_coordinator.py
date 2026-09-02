#!/usr/bin/env python3
"""
Autonomous Coordinator - Main orchestrator for the modular autonomous system
Replaces the monolithic master_autonomous_controller.py with clean coordination
"""

from core.capability import raise_if_structural
import asyncio
import re
from types import SimpleNamespace
import json
import logging
import os
from typing import Dict, Any, List, Optional, Set, Sequence, Tuple
from datetime import datetime, timedelta
from collections import deque, OrderedDict
from dataclasses import dataclass, field
from enum import Enum

from .shared_types import (
    SystemMode, SystemState, Task, Goal, Plan, PerceptionData,
    TaskType, TaskStatus, Priority, TaskSource
)
from .singleton_constitution import DriftSeverity
from .perception_manager import PerceptionManager
from .planning_engine import PlanningEngine
from core.learning.unified_learning_system import get_learning_authority
from .directive_system import DirectiveSystem
from .runtime_governance import get_runtime_governance
from .coordinator_config import CoordinatorConfig, get_default_config
from .circuit_breaker import CircuitBreaker, get_circuit_breaker_registry

# Security imports
from core.security.security_audit_worker import SecurityAuditWorker

# Core system imports using absolute paths
import sys
from pathlib import Path
# Add project root to Python path for absolute imports
project_root = Path(__file__).resolve().parent.parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from core.memory import MemoryManager, MemoryItem, MemoryQuery, MemoryType, MemoryOperation
from core.reasoning import (
    AbstractReasoningEngine, ReasoningContext, ReasoningType,
    create_abstract_reasoning_engine, AdvancedProofEngine
)
from core.learning import UnifiedLearningSystem
from core.intelligence import PredictiveIntelligenceSystem, PredictionDomain, PredictionHorizon
from core.health.system_watchdog import SystemWatchdog
from core.database.logging_database import LoggingDatabase
from core.tools.tool_registry import ToolResult
try:
    from core.monitoring.resource_config import TORIN_RESOURCE_LIMITS
except Exception:
    TORIN_RESOURCE_LIMITS = None
import uuid
from dotenv import load_dotenv

# Load environment variables from .env.production
env_file = Path(__file__).parent.parent.parent.parent / ".env.production"
if env_file.exists():
    load_dotenv(env_file)
else:
    # Fallback to .env if .env.production doesn't exist
    env_file_fallback = Path(__file__).parent.parent.parent.parent / ".env"
    if env_file_fallback.exists():
        load_dotenv(env_file_fallback)

# Initialize logger first
logger = logging.getLogger(__name__)

# Security and monitoring integration
try:
    from core.security import SecurityController, get_security_controller
    SECURITY_AVAILABLE = True
except ImportError:
    SecurityController = None
    SECURITY_AVAILABLE = False
    logger.warning("Security system not available")

try:
    from core.health.monitoring_coordinator import MonitoringCoordinator
    MONITORING_AVAILABLE = True
except ImportError:
    MonitoringCoordinator = None
    MONITORING_AVAILABLE = False
    logger.warning("Monitoring coordinator not available")

# Domain system imports for cross-domain reasoning
from core.domain import DomainRegistry, UniversalOntology, CrossDomainReasoner
from core.integration.universal_domain_master import UniversalDomainMaster, CrossDomainQuery, DomainType, ReasoningStrategy

from core.utils.notification_publisher import publish_notification
from core.integration.slack_notifier import get_slack_notifier


def _subsystem_readiness(subsystem: Any) -> Dict[str, Any]:
    """Whether an optional subsystem is attached, and whether it is ready.

    Three states, reported as two independent facts, because collapsing them
    loses the one that matters:

        attached=False, initialized=False   never constructed
        attached=True,  initialized=False   constructed, initialise failed or
                                            has not run -- THE FAILURE CASE
        attached=True,  initialized=True    ready

    A subsystem that does not publish an `initialized` flag reports None rather
    than False: "this component does not say" is not the same claim as "this
    component says no", and only one of them is evidence of a problem.
    """
    if subsystem is None:
        return {"attached": False, "initialized": False}
    flag = getattr(subsystem, "initialized", None)
    return {"attached": True,
            "initialized": None if flag is None else bool(flag)}


class SelfEventType(Enum):
    """Typed events the self reacts to; the dispatch keys on these.

    An event names something that happened to the substrate and carries the
    specific unit of work it concerns in its payload — never "go scan a table".
    Reactions registered with ``AutonomousCoordinator.on(...)`` fire when the
    matching event is emitted: synchronous reactions inline (cheap state
    changes), deferred reactions on the reactive drain worker (expensive work,
    off the acting hot path). New members are added by the phase that first
    emits them — the taxonomy grows only as fast as it is wired.
    """
    TASK_COMPLETED = "task_completed"
    #: A completed task's outcome is durable (its META memory is written). Carries
    #: the domain and meta_memory_id so learning reactions act on THAT outcome
    #: instead of a clock later scanning the outcome table.
    OUTCOME_OBSERVED = "outcome_observed"
    #: Learning moved a domain's competence (an operator became executable, or a
    #: run of demonstrations did not yet yield one). Emitted by the induction
    #: reaction so downstream faculties can react to a competence change.
    COMPETENCE_CHANGED = "competence_changed"
    #: A taught proposition was admitted to the concept store (subject/relation/
    #: object/domain in the payload). Emitted by the conversation's ingest so the
    #: domain authority can crystallize a taught subject into its own domain the
    #: moment its concept cluster is complete, instead of an idle tier finding it
    #: later.
    EVIDENCE_ADMITTED = "evidence_admitted"
    #: A background job the substrate submitted to the queue authority finished
    #: and was collected. Payload: {job_id, name, result, error}. `error` set
    #: means it failed — carried honestly, never a faked result. This is how a
    #: deferred job (an agent's findings, a self-serve lookup) is passed back to
    #: the substrate to reconcile, without it blocking on each.
    JOB_COMPLETED = "job_completed"


@dataclass
class SelfEvent:
    """One thing that happened to the substrate.

    ``payload`` carries the concrete unit of work (the task, its result) so a
    reaction acts on exactly what happened instead of rescanning state.
    ``origin`` is a short causal label for tracing which site emitted it.
    """
    type: SelfEventType
    payload: Dict[str, Any] = field(default_factory=dict)
    origin: str = ""


class AutonomousCoordinator:
    """
    Main coordinator that orchestrates perception, planning, execution, and learning
    Enhanced with cross-domain reasoning and predictive intelligence capabilities
    
    THE COGNITIVE SUBSTRATE IS THE BRAIN. A language model is a TEACHER,
    consulted when the substrate cannot represent or decide something itself.
    It is not the source of intelligence and is not required to think.
    All decisions, reasoning, and coordination flow through Torin's consciousness.
    """

    # Namespaces for meta-learner arms. Several coordinator decisions map onto
    # the same TaskFamily; the prefix keeps each decision's arms from being
    # sampled as alternatives to the other's.
    ADAPTIVE_TYPE_NS = "tasktype:"
    EXECUTOR_NS = "executor:"

    def __init__(self, config: Optional[Dict[str, Any]] = None, teacher_model=None):
        self.config = config or {}
        self.active = False

        import time as _t
        self._started_at_ts: float = _t.time()

        # THE LANGUAGE MODEL IS A TEACHER, NOT THE BRAIN.
        #
        # This constructor used to raise unless a model was supplied -- "the
        # Singleton's consciousness is mandatory" -- which made the entire
        # production ingress unable to start without an LLM. The substrate
        # could prove a syllogism, solve an equation and unify variables with
        # no model attached, but nothing could reach those capabilities through
        # the coordinator, and no experiment could measure them there.
        #
        # The model is now optional at every level. Paths that genuinely need
        # one report a typed capability fault, exactly as a severed solver
        # does; none of them substitute a weaker answer, because a fallback is
        # what made the missing capability invisible in the first place.
        self.teacher_model = teacher_model  # the teacher, consulted only for teaching

        # Configuration system - replaces magic numbers
        self.coordinator_config = CoordinatorConfig.from_dict(self.config) if self.config else get_default_config()
        logger.info("Configuration system initialized (magic numbers eliminated)")

        # Circuit breaker registry for external module resilience
        self.circuit_breakers = get_circuit_breaker_registry()
        logger.info("Circuit breaker registry initialized")

        # THE COORDINATOR RUNS SEVERAL TASKS AT ONCE. `_max_parallel_tasks`
        # defaults to 3, the dequeue at the bottom of the coordination cycle
        # gates on `len(self._inflight_tasks) < self._max_parallel_tasks`, and
        # tasks are launched rather than awaited.
        #
        # This said the opposite -- "SINGLETON MODEL: No parallel task pool. The
        # coordinator runs one task at a time" -- and logged it on every start.
        # It was true once: awaiting each task blocked the whole loop, which is
        # why reflection never ran. That was deliberately removed, and this was
        # left behind asserting the old behaviour.
        #
        # It matters beyond tidiness. Substrate execution verifies a rule by
        # observing what changed in the world, and attributes the result with
        # `external_interference=False` -- an assumption that nothing ELSE moved
        # the world during the act. With concurrent tasks that assumption is not
        # automatically safe: two tasks acting in one world can attribute each
        # other's changes, and a contradiction lands in the rule store as
        # runtime evidence against a rule that was fine.
        logger.info("Execution model: up to %d task(s) concurrently",
                    int(self.config.get("max_parallel_tasks", 3)))

        # System state
        self.system_state = SystemState()
        self.coordination_cycle_interval = self.coordinator_config.cycle_interval
        
        # Initialize core modules
        self.perception = PerceptionManager(self.config.get("perception", {}))
        self.planning = PlanningEngine(self.config.get("planning", {}))
        # Learning is the ONE authority (UnifiedLearningSystem), the same one the
        # substrate-self reaches via learning() — not the dead LearningAdapter.
        # There is a SINGLE learning attribute now: `self.learning`. It used to
        # be shadowed by a second `self.unified_learning` that main.py injected
        # with the very same singleton, so the coordinator carried two names for
        # one object. That injection is gone; readiness is read off the object
        # itself (`self.learning.initialized`), which is what "was it wired?"
        # actually asks.
        self.learning = get_learning_authority()
        self._adaptive_types_registered = False
        # (was `_pending_decision_id` — a single slot shared across selections.
        # Removed: a decision id now travels in a per-call sink to the task it
        # belongs to, so it cannot be overwritten by a concurrent selection or
        # leaked onto an unrelated task.)
        self._executor_decision_ids: Dict[str, Optional[str]] = {}

        # The Self — the substrate's integrator and the owner of the cognition
        # faculties (reasoning, learning, domains, motivation). The coordinator is
        # the BODY: it holds a handle to the Self and reaches faculties THROUGH it,
        # rather than constructing them itself. The Self does no reasoning/learning
        # /goal-forming — it holds the authorities that do.
        # Motivation is one of THIS substrate's own faculties — the intrinsic
        # motivation system that forms goals from its measured signals. It is the
        # module singleton (no rival instance); the config was always the default
        # {} — the real knob is `intrinsic_motivation_weight`, unrelated to
        # construction.
        from core.agents.autonomous.intrinsic_motivation import get_intrinsic_motivation_system
        self.intrinsic_motivation = get_intrinsic_motivation_system()

        # Security audit worker -- MUST be the module singleton.
        #
        # This constructed its own SecurityAuditWorker while main.py and
        # convergence_gate both use get_audit_worker(). Findings live in an
        # in-memory dict on the instance, so the audit populated the
        # coordinator's copy (252 findings) while the singleton the convergence
        # gate queries stayed empty (0).
        #
        # The consequence was not merely a stale read: the gate's
        # "security_finding_resolved" invariant treats "finding not in active
        # set" as PROOF OF REMEDIATION, so it certified every finding as fixed
        # -- including genuinely open ones -- because its ground truth was an
        # object that had never run an audit. One store, one truth.
        from core.security.security_audit_worker import get_audit_worker
        self.security_audit_worker = get_audit_worker()

        # ── Knowledge cutoff tracking (persistent) ───────────────────────
        # This tracks (a) the declared training cutoff date for the current model
        # and (b) the last date through which the system has refreshed knowledge
        # via autonomous research tasks.
        self._knowledge_cutoff_state: Dict[str, Any] = {}
        try:
            self._knowledge_cutoff_state = self._load_knowledge_cutoff_state()
        except Exception as e:
            logger.debug(f"Knowledge cutoff state load failed (non-fatal): {e}")
        
        # === COMPLETION CALLBACK REGISTRY ===
        # Initialize this BEFORE register_completion_callback is called
        # Generic completion hook system - any subsystem can register completion handlers
        # Maps (TaskType, TaskSource) -> List[callback_fn]
        # Callbacks receive: (task: Task, result: Dict, confidence: float)
        self._completion_callbacks: Dict[tuple, List] = {}

        # Event/reaction dispatch — the substrate reacts to what happens to it
        # instead of a clock polling for it. Reactions registered via on() fire
        # when a matching SelfEvent is emitted: sync ones inline (isolated,
        # priority order), deferred ones on the drain worker (off the hot path).
        # This generalizes the completion-callback registry above; affect is the
        # first reaction, registered below.
        self._reactions: Dict[SelfEventType, List[Dict[str, Any]]] = {}
        self._reactive_queue: deque = deque()
        self._work_ready: asyncio.Event = asyncio.Event()
        self._reactive_worker: Optional[asyncio.Task] = None
        self._emit_depth: int = 0
        self._max_emit_depth: int = 8

        # Coalescing state for the reactive motivation refresh (COMPETENCE_CHANGED
        # → refresh). An induction batch emits one event per domain it moved, so a
        # naive reaction would refresh N times; the dirty flag + single-flight task
        # collapse a burst into at most one in-flight + one queued refresh, and
        # never drop the last change.
        self._motivation_dirty: bool = False
        self._motivation_refresh_task: Optional[asyncio.Task] = None

        # Register completion callback for security remediation tasks
        # This creates the CLOSURE hook: Detection → Remediation → Verification → Closure
        self.register_completion_callback(
            TaskType.SECURITY_REMEDIATION,
            TaskSource.SECURITY_AUDIT,
            self._on_security_remediation_complete,
            "Mark security finding resolved"
        )

        # Register completion callback for autonomous knowledge refresh research
        self.register_completion_callback(
            TaskType.RESEARCH,
            TaskSource.AUTONOMOUS,
            self._on_knowledge_refresh_complete,
            "Update knowledge refresh state"
        )

        # AFFECT — the reference reaction. A task outcome is a fitness-relevant
        # event, so the substrate feels it. This was hardwired at the completion
        # seam; it now fires when a TASK_COMPLETED event is emitted there.
        self.on(SelfEventType.TASK_COMPLETED, self._react_affect,
                name="affect", mode="sync", priority=90)

        # LEARNING — reactive, off the hot path. When an outcome is observed the
        # always-online learner induces the operators whose demonstrations were
        # gathered during acting, and moves the competence that earns — instead
        # of a 300s idle tier later draining them. Deferred: the hypothesis
        # search runs on the drain worker, never an acting slot, so the
        # deliberate record-cheap / induce-expensive split is preserved.
        self.on(SelfEventType.OUTCOME_OBSERVED, self._react_induce,
                name="operator_induction", mode="deferred", priority=50)
        # Domain expansion (this outcome) then transfer resolution (the return
        # leg) — the two halves the domain-expansion tier ran on a 900s clock,
        # now reacting to the outcome. Deferred, off the acting hot path;
        # expansion before transfer (expansion may write the transfers).
        self.on(SelfEventType.OUTCOME_OBSERVED, self._react_expand_outcome,
                name="domain_expansion", mode="deferred", priority=40)
        self.on(SelfEventType.OUTCOME_OBSERVED, self._react_resolve_transfers,
                name="transfer_resolution", mode="deferred", priority=30)

        # TEACHING drives the domain map. When a taught proposition is admitted,
        # the domain authority re-checks whether the taught-concept graph now has
        # a coherent cluster to crystallize into its own subject domain (and
        # updates that domain's declarative-knowledge coverage). Deferred: the
        # graph scan runs on the drain worker, never the reply path. The idle
        # domain-discovery tier stays as a backstop.
        self.on(SelfEventType.EVIDENCE_ADMITTED, self._react_crystallize_taught,
                name="crystallize_taught", mode="deferred", priority=45)

        # A background job the substrate submitted has come back. The receipt is
        # recorded here; a job that carried a domain outcome is folded into the
        # substrate's learning through the same OUTCOME_OBSERVED path its own
        # tasks use, so a spawned agent's findings advance the domain like any
        # other outcome. A failed job is logged with its error, never dropped.
        self.on(SelfEventType.JOB_COMPLETED, self._react_job_completed,
                name="job_completed", mode="deferred", priority=40)

        # COMPETENCE — a moved competence changes the per-domain competence DRIVE
        # (intrinsic motivation's inverted-U), so the motivation signals that read
        # it are stale until refreshed. COMPETENCE_CHANGED already fires from the
        # induction reaction; this gives it its first consumer, refreshing the
        # signals reactively (coalesced) instead of waiting for the %5 poll — which
        # stays as a backstop. This is a step toward taking motivation off the poll.
        self.on(SelfEventType.COMPETENCE_CHANGED, self._react_competence_changed,
                name="motivation_refresh", mode="deferred", priority=20)

        # Directive System - High-level guidance for the Singleton
        self.directive_system = DirectiveSystem()

        # System Awareness Layers - Multi-layer adaptive awareness framework
        from core.system import (
            EnvironmentState, ActiveDiscovery, BehavioralAnalysis, InfrastructureTopology
        )
        self.env_state = EnvironmentState()
        self.discovery = ActiveDiscovery()
        # Publish it: the security audit needs Torin's own service inventory to
        # tell "my service is exposed" from "an unidentified process is listening".
        try:
            from core.system.active_discovery import register_active_discovery
            register_active_discovery(self.discovery)
        except Exception:
            pass
        self.behavioral = BehavioralAnalysis()
        self.topology = InfrastructureTopology()

        # Runtime Governance - Validates critical decisions against governance laws
        self.runtime_governance = get_runtime_governance()

        # Singleton Constitution - Tracks compliance with the 5 governance laws
        from .singleton_constitution import get_singleton_constitution
        self.constitution = get_singleton_constitution()
        logger.info("📜 Singleton Constitution tracker initialized (using global singleton)")

        # Phase 2: Multi-level safety prompts for long-horizon planning protection
        from core.safety import MultiLevelSafetyPrompts
        self.safety_prompts = MultiLevelSafetyPrompts()
        logger.info("🛡️ Multi-level safety prompts initialized")

        # === EVENT-DRIVEN TASK EXECUTION ===
        from core.agents.autonomous.queue_authority import get_queue_authority
        from core.agents.autonomous.general_purpose_executor import GeneralPurposeExecutor

        # The substrate does NOT own the queue. It is a WORKER: it draws work
        # from the ONE queue authority and does it, through its substrate-only,
        # model-free executor. The authority owns the backlog, the concurrency
        # pool, await-jobs, and scheduling — one place that knows what work
        # exists, what is running, and what is due. `self.task_queue` is the
        # shared singleton authority (not a private queue), configured here by
        # the substrate that draws from it: the acting cap is the work-job
        # concurrency; background jobs (await/scheduled) get their own budget.
        self.task_queue = get_queue_authority(config={
            "max_parallel": int(self.config.get("max_parallel_tasks", 3)),
            "job_timeout_seconds": self.config.get("task_timeout_seconds", 3600.0),
        })
        self.executor = GeneralPurposeExecutor(teacher_model)
        # Completion is verified by the TaskCompletionValidator (system property,
        # reality-checked). The legacy SuccessValidator (self-attestation over the
        # result dict) was retired 2026-08-28 — it rubber-stamped fabricated
        # completions. There is one completion authority now.
        self._idle_count = 0

        # === EXPLORATION LOOP STATE ===
        self._current_motivation = {}  # Latest motivation signal from intrinsic system
        self._optimization_running = False  # Guard for curiosity-driven optimization
        self._last_curiosity_optimization = None  # Timestamp of last optimization run
        self._strategy_outcomes = {}  # Meta-learning: strategy → {wins, losses, avg_time}
        self._exploring_components: Set[str] = set()  # Component lock: prevents re-exploring same component
        self._recent_exploration_fp_list: list = []  # Dedup: ordered list of recent exploration fingerprints (FIFO, max 20)
        self._permanently_failed_fps: Set[str] = set()  # FPs of tasks that permanently failed — never re-queued this session
        try:
            self._permanently_failed_fps = self._load_permanently_failed_fps()
        except Exception as _fp_load_err:
            logger.debug(f"Failed to load permanently-failed fingerprints (non-fatal): {_fp_load_err}")
        # Intrinsic exploration queue control
        # Applies only to intrinsic exploration tasks (metadata: intrinsic_kind="exploration").
        # Set to 0 to disable intrinsic exploration entirely.
        _cap_raw = os.getenv("TORINAI_INTRINSIC_EXPLORATION_CAP")
        try:
            self._intrinsic_exploration_cap: int = (
                int(_cap_raw)
                if _cap_raw is not None
                else int(self.config.get("intrinsic_exploration_cap", 1))
            )
        except Exception:
            self._intrinsic_exploration_cap = 1
        if self._intrinsic_exploration_cap < 0:
            self._intrinsic_exploration_cap = 0
        self._idle_subsystems_registered: bool = False  # One-time flag for _register_idle_subsystems()

        # Concurrent execution. The loop used to `await` one task to completion,
        # so the substrate executed strictly one task at a time AND could not
        # reflect while any task was running.
        self._inflight_tasks: Dict[str, asyncio.Task] = {}
        self._max_parallel_tasks: int = int(self.config.get("max_parallel_tasks", 3))
        # No private pool: concurrency is the queue authority's (self.task_queue).
        # Idempotency log: "{trigger_id}:{action}" → unix timestamp of last execution.
        # Prevents Slack spam, double-restarts, repeated credential rotations, etc.
        self._step_execution_log: Dict[str, float] = {}
        # Unix timestamp of the last prune pass; prune runs every 10 min.
        self._step_log_last_pruned: float = 0.0

        # ── Idle review snapshots (facts-first, no LLM) ───────────────────
        self._idle_last_security_audit_at: Optional[datetime] = None
        self._idle_last_security_findings: Dict[str, Any] = {
            "total": None,
            "by_severity": None,
        }
        self._idle_last_health_check_at: Optional[datetime] = None
        self._idle_last_health_snapshot: Dict[str, Any] = {
            "components_total": None,
            "unhealthy_total": None,
        }
        self._idle_last_system_review_at: Optional[datetime] = None
        self._idle_system_review_snapshot: Optional[Dict[str, Any]] = None

        # ── Idle knowledge refresh (web research cadence) ─────────────────
        self._idle_last_knowledge_refresh_at: Optional[datetime] = None
        
        # Per-component backoff state for health recovery.
        # Keys are component names; values are dicts with:
        #   attempts     int   — number of completed recovery cycles (reset when healthy)
        #   last_attempt float — unix ts of last recovery attempt
        #   escalated    bool  — True once the escalation notification has been sent
        self._component_recovery_state: Dict[str, dict] = {}

        # Memory system - can be provided or created (will be initialized in async initialize() method)
        if 'memory' in self.config and not isinstance(self.config['memory'], dict):
            # Memory system instance provided directly
            self.memory = self.config['memory']
        else:
            # Will be initialized asynchronously in initialize() method
            self.memory = None

        # === MEMORY QUERY AGENTS ===
        # Specialized agents for querying and summarizing different memory systems
        # MySQL is PRIMARY storage (hot/cold tiers)
        # Canonical MemoryInjector, injected by main.py after construction. The
        # coordinator must not build its own — one mechanism, one owner.
        self.memory_injector = None

        # mysql_memory_agent removed: it was labelled "PRIMARY" but was never
        # assigned anywhere, and MySQL is retired (PostgreSQL is the store). Its
        # only consumer, get_intelligent_memory_context(), now goes through the
        # policy + MemoryInjector path.
        logger.info("Memory query agents will be initialized during startup")

        # === ENHANCED REASONING SYSTEM ===
        # Complete reasoning toolkit available across the entire Singleton
        self.abstract_reasoning = create_abstract_reasoning_engine()  # Abstract & logical reasoning
        from core.reasoning import AdvancedProofEngine
        self.proof_engine = AdvancedProofEngine()  # Formal proof generation

        # Quantum reasoning (disabled by default - requires IBM Quantum connection)
        self.enable_quantum = self.config.get("enable_quantum", False)
        self.quantum_reasoning = None
        if self.enable_quantum:
            from core.reasoning import QuantumReasoningSystem
            self.quantum_reasoning = QuantumReasoningSystem()
            logger.info("🧠 Enhanced reasoning initialized - Abstract, Quantum, Proof systems ready")
        else:
            logger.info("🧠 Enhanced reasoning initialized - Abstract + Proof (quantum DISABLED)")

        # Neural Bridge - this substrate's reasoning faculty (the model-free
        # NeuralSymbolicBridge, routing to abstract/Z3). Brought up at startup.
        self.neural_bridge = None  # set to get_neural_bridge() during startup
        
        # === UNIFIED INTELLIGENCE ===
        # `unified_learning` is GONE: it was a second name for `self.learning`
        # (main.py injected the same authority singleton into it). The one
        # learning authority is `self.learning`, established above.
        self.asi_self_improvement = None  # Injected by main.py
        logger.info("📚 ASI self-improvement will be injected by main.py (singleton pattern)")

        # === GOVERNANCE SYSTEM ===
        # Governance system will be INJECTED by main.py (singleton pattern)
        self.governance = None  # Injected by main.py
        logger.info("⚖️  Governance system will be injected by main.py (singleton pattern)")

        self.intelligence = PredictiveIntelligenceSystem(self.config.get("intelligence", {}))
        self.watchdog = SystemWatchdog(TORIN_RESOURCE_LIMITS)
        
        # === COGNITIVE TOOLKIT ===
        # These are the Singleton's tools for understanding, learning, and self-improvement

        # Causal analysis for understanding WHY feedback patterns occur
        try:
            from core.learning.causal_feedback_analyzer import CausalFeedbackAnalyzer
            self.causal_analyzer = CausalFeedbackAnalyzer()
            logger.info("✅ Causal analyzer initialized - Singleton can understand root causes")
        except Exception as e:
            logger.warning(f"⚠️  Causal analyzer not available: {e}")
            self.causal_analyzer = None

        # A/B testing and impact monitoring for validating improvements
        try:
            from core.learning.improvement_monitor import ImprovementMonitor
            self.improvement_monitor = ImprovementMonitor(
                db_config=self.config.get("improvement_monitor_db_config", {
                    "database": "torinai_db",
                    "host": "localhost",
                    "user": "stefan",
                    "password": os.getenv("POSTGRES_PASSWORD", "")
                })
            )
            logger.info("✅ Improvement monitor initialized - Singleton can validate changes with A/B tests")
        except Exception as e:
            logger.warning(f"⚠️ Improvement monitor not available: {e}")
            self.improvement_monitor = None

        # Meta-learning for rapid adaptation to new tasks (shared singleton)
        try:
            from core.learning.meta_learning import get_meta_learner
            self.meta_learning = get_meta_learner(
                config=self.config.get("meta_learning_config", {
                    "min_trials": 3,
                    "adaptation_threshold": 0.1,
                    "enable_adaptation": True
                })
            )
            logger.info("✅ Meta-learning initialized - Singleton can learn from few examples")
        except Exception as e:
            logger.warning(f"⚠️ Meta-learning not available: {e}")
            self.meta_learning = None
        
        
        # The coordinator holds no model handle. It is a body driven by the
        # Self; a language model belongs to the teacher alone.

        # Enhanced capabilities - initialized from config dependencies
        self.domain_registry: Optional[DomainRegistry] = self.config.get("domain_registry")
        self.universal_domain_master: Optional[UniversalDomainMaster] = self.config.get("universal_domain_master")
        # self.predictive_intelligence DELETED: a config-only shadow that was
        # never assigned (always None) while self.intelligence holds the real
        # constructed PredictiveIntelligenceSystem. Both called the same
        # generate_comprehensive_prediction(); one storage location is
        # authoritative. Callers migrated to self.intelligence.

        # CRITICAL: Health Monitor - Singleton OWNS health monitoring
        # If not provided, create it. This is NON-NEGOTIABLE.
        self.health_monitor = self.config.get("health_monitor")
        if self.health_monitor is None:
            try:
                logger.info("🏥 Health Monitor not provided - Singleton creating health monitoring system")
                from core.health.health_monitor import HealthMonitor
                health_config = self.config.get("health_monitor_config", {})
                self.health_monitor = HealthMonitor(config=health_config)
                logger.info("✅ Health Monitor created and owned by Singleton")
            except Exception as e:
                logger.warning(f"⚠️ Health Monitor not available: {e}")
                import traceback
                logger.warning(f"Traceback: {traceback.format_exc()}")
                self.health_monitor = None
        else:
            logger.info("✅ Health Monitor provided to Singleton")

        # CRITICAL: Recovery Manager - Enables autonomous self-healing
        # Required by _execute_recovery() for AI-powered component recovery
        self.recovery_manager = self.config.get("recovery_manager")
        if self.recovery_manager is None:
            try:
                logger.info("🔧 Recovery Manager not provided - Singleton creating recovery system")
                from core.health.recovery_manager import RecoveryManager
                recovery_config = self.config.get("recovery_manager_config", {})
                self.recovery_manager = RecoveryManager(config=recovery_config)
                logger.info("✅ Recovery Manager created - AI self-healing enabled")
            except Exception as e:
                logger.warning(f"⚠️ Recovery Manager not available: {e}")
                import traceback
                logger.warning(f"Traceback: {traceback.format_exc()}")
                self.recovery_manager = None
        else:
            logger.info("✅ Recovery Manager provided to Singleton")

        # CRITICAL: Logging Database - For comprehensive operational logging
        self.log_db = self.config.get("log_db")
        if self.log_db is None:
            try:
                logger.info("📝 Logging database not provided - creating logging system")
                self.log_db = LoggingDatabase()
                # Will be initialized in async initialize() method
                logger.info("✅ Logging database created for autonomous coordinator")
            except Exception as e:
                logger.warning(f"⚠️ Logging database not available: {e}")
                self.log_db = None
        else:
            logger.info("✅ Logging database provided to autonomous coordinator")

        # Security and monitoring integration
        self.security_controller: Optional[Any] = None  # MasterSecurityController type
        self.monitoring_coordinator: Optional[Any] = None  # MonitoringCoordinator type
        
        # Initialize security if available
        if SECURITY_AVAILABLE and self.config.get("enable_security", True):
            self.security_controller = get_security_controller()
            logger.info("✅ Security controller integrated into autonomous system")
        
        # Initialize monitoring if available
        if MONITORING_AVAILABLE and MonitoringCoordinator is not None and self.config.get("enable_monitoring", True):
            self.monitoring_coordinator = MonitoringCoordinator(
                check_interval=self.config.get("monitoring_check_interval", 60),
                startup_delay=self.config.get("monitoring_startup_delay", 30)  # Wait for systems to initialize
            )
            # Set callback so MonitoringCoordinator can send health events to Singleton
            self.monitoring_coordinator.singleton_callback = self._receive_health_event
            logger.info("✅ Monitoring coordinator integrated with Singleton callback")
        else:
            self.monitoring_coordinator = None

        # Slack notifier for system notifications
        self.slack_notifier = get_slack_notifier()
        logger.info("✅ Slack notifier integrated into autonomous coordinator")

        # Registered external agents
        self.registered_agents: Dict[str, Any] = {}
        
        # Coordination state
        self.coordination_task: Optional[asyncio.Task] = None
        self.last_cycle_time = datetime.now()
        
        # Enhanced statistics
        self.stats = {
            "cycles_completed": 0,
            "goals_achieved": 0,
            "tasks_completed": 0,
            "uptime_seconds": 0.0,
            "system_efficiency": 0.0,
            "cross_domain_operations": 0,
            "predictions_made": 0,
            "domain_integrations": 0,
            "registered_agents": 0,
            # Reactive-faculty counters (honest metrics, surfaced via get_status).
            # motivation_refreshes_reactive: refreshes driven by COMPETENCE_CHANGED
            #   (vs the %5 poll); motivation_refresh_errors: refreshes that actually
            #   failed (counted, not swallowed); external_blocker_escalations: times
            #   the arbiter judged a task failure to be an EXTERNAL blocker and the
            #   self-directed diagnostic was suppressed instead of thrashing.
            "motivation_refreshes_reactive": 0,
            "motivation_refresh_errors": 0,
            "external_blocker_escalations": 0,
        }

        # Register this coordinator as the active runtime instance so other
        # components (e.g., tools) can update runtime-owned counters.
        try:
            from core.agents.autonomous.runtime_registry import register_autonomous_coordinator

            register_autonomous_coordinator(self)
        except Exception:
            # Registry is best-effort; never block startup.
            pass
        # Idle detection for boredom-driven goal generation
        self._last_requests_processed: int = 0
        self._idle_cycles: int = 0
        # Last time a drift alert was published (to avoid spamming)
        self._last_drift_alert_at: Optional[datetime] = None

        # === IDLE PRIORITY TIMESTAMPS ===
        # Track last execution of each priority tier so the idle dispatcher
        # can pick the highest-priority action that is actually due.
        self._idle_last_security_audit: Optional[datetime] = None
        self._idle_last_health_check: Optional[datetime] = None
        self._idle_last_self_improvement: Optional[datetime] = None
        self._idle_last_meta_learning: Optional[datetime] = None
        self._idle_last_memory_consolidation: Optional[datetime] = None

    async def initialize(self, start_loop: bool = False) -> bool:
        """
        Initialize all system modules
        
        Args:
            start_loop: If True, start the coordination cycle immediately. 
                       If False, loop can be started later with start_coordination()
        """
        try:
            logger.info("Initializing autonomous system...")
            
            # No model to connect: this substrate reasons through its OWN
            # faculties (neural_bridge, learning, domains…), never a held model
            # handle.

            # Initialize logging database if it was created but not yet initialized
            if self.log_db and not getattr(self.log_db, 'initialized', False):
                await self.log_db.initialize()
                logger.info("✅ Logging database initialized")

            # Initialize memory agent if not provided
            if self.memory is None:
                # Use unified memory entrypoint from core.memory
                from core.memory import get_memory_agent, initialize_memory_agent
                try:
                    self.memory = await get_memory_agent()
                    logger.info("✅ Memory agent retrieved from singleton")
                except:
                    memory_config = self.config.get("memory", {})
                    self.memory = await initialize_memory_agent(**memory_config) if memory_config else await initialize_memory_agent()
                    logger.info("✅ Memory agent initialized")

            # Initialize core modules
            modules = [
                ("Perception Manager", self.perception),
                ("Planning Engine", self.planning),
                ("Execution Controller", self.executor),
                # Learning is the SubstrateLearning authority — stateless over its
                # stores, so it has no initialize() step (see Self.initialize).
                ("Intrinsic Motivation System", self.intrinsic_motivation),
                ("Memory Manager", self.memory),
                ("Intelligence System", self.intelligence),
            ]

            for name, module in modules:
                if not await module.initialize():
                    logger.error(f"Failed to initialize {name}")
                    return False
                logger.info(f"{name} initialized successfully")

            # Connect security audit worker to intrinsic motivation
            if self.security_audit_worker and hasattr(self.intrinsic_motivation, 'set_security_audit_worker'):
                self.intrinsic_motivation.set_security_audit_worker(self.security_audit_worker)
                logger.info("✅ Intrinsic motivation connected to security audit worker")

            # Connect learning adapter to shared systems
            if self.runtime_governance and hasattr(self.learning, 'set_governance_system'):
                self.learning.set_governance_system(self.runtime_governance)
            if self.security_audit_worker and hasattr(self.learning, 'set_security_audit_worker'):
                self.learning.set_security_audit_worker(self.security_audit_worker)
            if self.monitoring_coordinator and hasattr(self.learning, 'set_monitoring_coordinator'):
                self.learning.set_monitoring_coordinator(self.monitoring_coordinator)

            # Initialize executor
            if not await self.executor.initialize():
                logger.error("Failed to initialize General Purpose Executor")
                return False
            logger.info("✅ General Purpose Executor initialized")

            # Initialize Directive System
            logger.info("=" * 80)
            logger.info("🎯 DIRECTIVE SYSTEM - Loading High-Level Guidance")
            logger.info("=" * 80)
            try:
                if hasattr(self.directive_system, 'initialize'):
                    if not await self.directive_system.initialize():
                        logger.warning("Directive System failed to initialize (non-critical)")
                    else:
                        logger.info("✅ Directive System ready - Singleton has high-level objectives")
                else:
                    logger.warning("Directive System has no initialize method (non-critical)")
            except Exception as e:
                logger.warning(f"Directive System initialization error (non-critical): {e}")

            # Activate the constitution — the drift-assessment authority. Without
            # this, assess_constitutional_alignment short-circuits on `not active`
            # and returns an EMPTY assessment (no laws scored), so the revived
            # constitutional-alignment tier would run against nothing. This only
            # enables the read-only 5-law drift assessment; per-action enforcement
            # is unified_governance, a separate authority.
            try:
                if await self.constitution.initialize():
                    logger.info("✅ Constitution active — 5 governance laws assessed for drift")
                else:
                    logger.warning("Constitution did not activate — drift checks will be inert")
            except Exception as e:
                logger.warning(f"Constitution activation error: {e}")

            # Initialize enhanced reasoning systems
            logger.info("=" * 80)
            logger.info("🧠 ENHANCED REASONING - Initializing Advanced Intelligence")
            logger.info("=" * 80)
            
            if not await self.abstract_reasoning.initialize():
                logger.error("Failed to initialize Abstract Reasoning Engine")
                return False
            logger.info("✅ Abstract Reasoning Engine ready")
            
            if self.enable_quantum and self.quantum_reasoning:
                await self.quantum_reasoning.initialize()
                logger.info("✅ Quantum Reasoning System ready")
            else:
                logger.info("⏭️  Quantum Reasoning System DISABLED (no IBM connection)")

            try:
                if hasattr(self.proof_engine, 'initialize'):
                    await self.proof_engine.initialize()
                logger.info("✅ Advanced Proof Engine ready")
            except Exception as e:
                logger.warning(f"Advanced Proof Engine initialization error (non-critical): {e}")
            
            # This substrate's OWN cognition faculties. Each is the module
            # singleton (no rival instance): reasoning ↔ logic/proof via the
            # NeuralSymbolicBridge, the predictive/foresight engine, the domain
            # authority, and meta-learning. Bring up the ones with async
            # initializers, then take each handle directly.
            try:
                from core.reasoning.neural_bridge import get_neural_bridge
                from core.integration.universal_domain_master import get_universal_domain_master
                from core.learning.meta_learning import get_meta_learner
                self.neural_bridge = get_neural_bridge()
                self.universal_domain_master = get_universal_domain_master()
                self.meta_learning = get_meta_learner()
                for _name, _faculty in (("reasoning", self.neural_bridge),
                                        ("domains", self.universal_domain_master),
                                        ("motivation", self.intrinsic_motivation)):
                    _init = getattr(_faculty, "initialize", None)
                    if _init is not None:
                        try:
                            await _init()
                        except Exception as fe:
                            logger.warning(f"Self: {_name} faculty init failed: {fe}")
                # Predictive intelligence (async getter) — one engine, brought up
                # once and held here.
                try:
                    from core.intelligence import get_predictive_intelligence
                    _intel = await get_predictive_intelligence()
                    if _intel is not None:
                        self.intelligence = _intel
                except Exception as ie:
                    logger.warning(f"Self: intelligence faculty init failed: {ie}")
                logger.info("✅ Cognition faculties ready - reasoning ↔ logic, "
                            "intelligence, domains, meta-learning")
            except Exception as e:
                logger.warning(f"⚠️ Neural Bridge initialization failed: {e}")
            
            logger.info("🎯 Enhanced reasoning fully operational across Singleton")
            
            # Initialize Unified Learning System (Singleton's tool)
            logger.info("=" * 80)
            logger.info("📚 UNIFIED LEARNING SYSTEM - Master Learning Tool")
            logger.info("=" * 80)

            try:
                await self.learning.start()
                logger.info("✅ Unified Learning System ready - Master learning tool operational")
                logger.info("   The Singleton can now learn, adapt, and self-improve")
            except Exception as e:
                logger.warning(f"⚠️ Unified Learning System initialization failed (non-critical): {e}")
            
            # SystemWatchdog doesn't have initialize method
            logger.info("System Watchdog ready")
            
            # Initialize cognitive toolkit (async systems)
            logger.info("=" * 80)
            logger.info("🧠 COGNITIVE TOOLKIT - Initializing Advanced Systems")
            logger.info("=" * 80)
            
            try:
                # Meta-learning system
                await self.meta_learning.initialize()
                logger.info("✅ Meta-Learning System ready - few-shot learning enabled")
            except Exception as e:
                logger.warning(f"⚠️ Meta-learning initialization failed: {e}")

            # Causal analyzer and improvement monitor don't need async init
            logger.info("✅ Causal Analyzer ready - root cause analysis enabled")
            logger.info("✅ Improvement Monitor ready - A/B testing enabled")

            # Initialize memory query agents
            # Get memory agent singleton
            try:
                from core.memory import get_memory_agent
                memory_agent = await get_memory_agent()
                if memory_agent:
                    logger.info("✅ Memory Query Agent ready - Using unified memory system")
                else:
                    logger.warning("⚠️ Memory agent not available")
            except Exception as e:
                logger.warning(f"⚠️ Memory query agents initialization failed: {e}")

            # CRITICAL: Initialize Health Monitor
            if self.health_monitor:
                if hasattr(self.health_monitor, 'initialize'):
                    try:
                        await self.health_monitor.initialize()
                        logger.info("✅ Health Monitor initialized - System health monitoring active")
                    except Exception as e:
                        logger.error(f"❌ CRITICAL: Health Monitor initialization failed: {e}")
                        raise RuntimeError(f"Health Monitor is REQUIRED but failed to initialize: {e}") from e
                else:
                    logger.info("✅ Health Monitor ready (no initialization required)")
                # Register core TorinAI services so the health monitor tracks them
                _core_components = ["database", "memory", "learning", "reasoning", "security", "storage"]
                for _comp in _core_components:
                    try:
                        await self.health_monitor.check_component_health(_comp)
                    except Exception:
                        pass
                logger.info(f"✅ Registered {len(_core_components)} core health components")
            else:
                logger.error("❌ CRITICAL: Health Monitor is None - this should never happen!")
                raise RuntimeError("Health Monitor is REQUIRED but is None - Singleton cannot operate without health monitoring")

            # CRITICAL: Initialize Recovery Manager (for AI self-healing)
            if self.recovery_manager:
                if hasattr(self.recovery_manager, 'initialize'):
                    try:
                        await self.recovery_manager.initialize()
                        logger.info("✅ Recovery Manager initialized - AI self-healing enabled")
                    except Exception as e:
                        logger.error(f"❌ CRITICAL: Recovery Manager initialization failed: {e}")
                        raise RuntimeError(f"Recovery Manager is REQUIRED for self-healing but failed to initialize: {e}") from e
                else:
                    logger.info("✅ Recovery Manager ready (no initialization required)")
            else:
                logger.warning("⚠️ Recovery Manager is None - AI self-healing disabled")
                logger.warning("   Self-healing requires RecoveryManager for strategic recovery actions")

            # CRITICAL: Initialize Enhanced ASI Self-Improvement (for code repair and upgrade)
            if self.asi_self_improvement:
                if hasattr(self.asi_self_improvement, 'initialize'):
                    try:
                        await self.asi_self_improvement.initialize()
                        logger.info("✅ Enhanced ASI Self-Improvement initialized - Code repair and upgrade enabled")
                    except Exception as e:
                        logger.error(f"❌ Enhanced ASI Self-Improvement initialization failed: {e}")
                        logger.warning("   Code repair and upgrade will be disabled")
                        self.asi_self_improvement = None
                else:
                    logger.info("✅ Enhanced ASI Self-Improvement ready (no initialization required)")
            else:
                logger.warning("⚠️ Enhanced ASI Self-Improvement is None - Code repair and upgrade disabled")
                logger.warning("   System can do tactical recovery but not strategic code fixes")

            # CRITICAL: Initialize Improvement Monitor (for performance tracking and optimization)
            if self.improvement_monitor:
                if hasattr(self.improvement_monitor, 'initialize'):
                    try:
                        await self.improvement_monitor.initialize()
                        logger.info("✅ Improvement Monitor initialized - Performance tracking enabled")

                        # Wire improvement_monitor to EnhancedASI
                        if self.asi_self_improvement and hasattr(self.asi_self_improvement, '_monitor'):
                            self.asi_self_improvement._monitor = self.improvement_monitor
                            logger.info("✅ ImprovementMonitor wired to EnhancedASI")
                    except Exception as e:
                        logger.error(f"❌ Improvement Monitor initialization failed: {e}")
                        logger.warning("   Performance-based optimization may be limited")
                else:
                    logger.info("✅ Improvement Monitor ready (no initialization required)")
            else:
                logger.warning("⚠️ Improvement Monitor is None - performance tracking disabled")

            logger.info("=" * 80)
            
            # Log boosted autonomous goal generation settings
            logger.info("=" * 80)
            logger.info("🎯 AUTONOMOUS GOAL GENERATION - Boosted Settings")
            logger.info("=" * 80)
            max_goals = self.coordinator_config.max_concurrent_goals
            intrinsic_weight = self.coordinator_config.intrinsic_motivation_weight
            logger.info(f"   Max Concurrent Goals:      {max_goals} (baseline: 5)")
            logger.info(f"   Intrinsic Motivation Weight: {intrinsic_weight:.2f} (baseline: 0.30)")
            logger.info(f"   Goal Generation Frequency: Every 3 cycles (baseline: 20)")
            logger.info(f"   Min Active Goals Threshold: 3 (baseline: 2)")
            logger.info(f"   Min New Goals per Gen:     2 (baseline: 1)")
            logger.info("=" * 80)

            # Autonomous idle system handles all task scheduling
            logger.info("=" * 80)
            logger.info("🎯 AUTONOMOUS IDLE SYSTEM - Active (security / health / review on schedule)")
            logger.info("=" * 80)

            # Activate production governance enforcement (transition out of LOG_ONLY shadow mode)
            logger.info("=" * 80)
            logger.info("🔒 GOVERNANCE ENFORCEMENT - Activating Production Mode")
            logger.info("=" * 80)
            try:
                from core.governance.enforcement_mode_manager import get_enforcement_mode_manager
                await get_enforcement_mode_manager().activate_production_enforcement(
                    updated_by="autonomous_coordinator_startup"
                )
                logger.info("✅ Production governance enforcement activated")
            except Exception as e:
                logger.warning(f"⚠️ Governance enforcement activation failed (non-critical): {e}")
            logger.info("=" * 80)

            # Runtime mutation protection. Must come after all modules are
            # loaded, because it snapshots their attributes and source hashes
            # as the baseline for tamper detection.
            #
            # This also hash-protects config/governance_triggers.json, which now
            # holds the per-invocation safety rules — the file the whole safety
            # gate reasons from. Nothing was watching it before this call
            # existed: enable_runtime_protection() had zero call sites, so no
            # baseline was ever taken and verify_runtime_integrity() could only
            # early-return 'protection_not_enabled'.
            try:
                if self.runtime_governance:
                    _prot = await self.runtime_governance.enable_runtime_protection()
                    logger.info(
                        f"🛡️  Runtime protection: {_prot.get('frozen_modules')}/"
                        f"{_prot.get('total_critical_modules')} modules frozen, "
                        f"{len(_prot.get('config_files_hashed') or [])} config file(s) hash-protected"
                    )
            except Exception as e:
                logger.error(f"Runtime protection could not be enabled: {e}")

            # Set system mode
            self.system_state.mode = SystemMode.AUTONOMOUS
            self.active = True

            # Don't start coordination cycle during initialization
            # It will be started later via start_background_tasks()
            # Keep start_loop parameter for backward compatibility but log deprecation
            if start_loop:
                logger.warning("start_loop parameter is deprecated - use start_background_tasks() after full system init")

            logger.info("Autonomous system initialization completed (coordination cycle deferred)")

            return True
            
        except Exception as e:
            logger.error(f"Error during initialization: {e}")

            # Send notification for autonomous coordinator initialization failure
            try:
                from core.utils.notification_helpers import notify_autonomous_event
                asyncio.create_task(notify_autonomous_event(
                    event_type="error",
                    details=f"**Autonomous Coordinator initialization failed**\n\n**Error:** {str(e)}\n\n**Impact:** Singleton cannot operate autonomously",
                    severity="critical"
                ))
            except Exception as notify_error:
                logger.warning(f"Failed to send autonomous coordinator error notification: {notify_error}")

            return False
    
    async def _report_failure(self, component: str, failure_type: str,
                              description: str, severity: str = "medium",
                              exception: Optional[BaseException] = None,
                              metadata: Optional[Dict[str, Any]] = None) -> None:
        """Put a failure on the canonical record.

        The coordinator is the substrate's own loop, so its failures are the
        ones every other system most needs to know about -- and it reported
        exactly none of them anywhere queryable. Defensive by construction:
        this is called from failure paths and must never create a second one.
        """
        try:
            from core.observability import failure_record

            await failure_record.report(
                component=component, failure_type=failure_type,
                description=description, source_system="autonomous_coordinator",
                severity=severity, exception=exception, metadata=metadata or {})
        except Exception as error:
            logger.error("Coordinator failure not recorded: %s", error)

    async def start_coordination(self):
        """Start the autonomous coordination cycle (if not already running)"""
        if self.coordination_task is None and self.active:
            # Rehydrate the durable backlog BEFORE the loop starts pulling, so
            # work accepted before the last restart (and any task interrupted
            # mid-run) is back in the queue rather than silently lost.
            restored = await self.task_queue.restore_pending()
            if restored.get("restored"):
                logger.info("♻️  restored %d queued task(s) from durable store "
                            "(%d interrupted -> restarted)",
                            restored["restored"], restored["restarted"])
            # Cadence ownership goes live with the substrate: hand the 15 timed
            # tiers to the queue authority's scheduler here, the one entry point
            # every start path funnels through. Idempotent (guarded), so calling
            # start_coordination more than once cannot double-schedule.
            self._register_idle_subsystems()
            self.coordination_task = asyncio.create_task(self._coordination_cycle())
            self._start_reactive_worker()
            logger.info("🚀 Autonomous coordination cycle started")
        elif self.coordination_task is not None:
            logger.info("Coordination cycle already running")
        else:
            # THE SUBSTRATE NOT STARTING IS THE MOST CONSEQUENTIAL FAILURE
            # THERE IS, and it was a warning in a log file. Nothing that
            # watches for trouble could see that the coordination cycle -- the
            # thing that runs the substrate -- had declined to start.
            logger.warning("Cannot start coordination - system not initialized or not active")
            await self._report_failure(
                component="agents.autonomous_coordinator",
                failure_type="startup_failure",
                description=("Coordination cycle did not start: system reports "
                             f"active={self.active}, initialized="
                             f"{getattr(self, 'initialized', 'unknown')}"),
                severity="critical",
                metadata={"active": bool(self.active)})
    
    async def start_background_tasks(self):
        """Start background coordination tasks after full system initialization"""
        if not self.active:
            logger.warning("Cannot start background tasks - system not initialized")
            return
        
        logger.info("🚀 Starting autonomous coordinator background tasks")
        
        # CRITICAL: Start health monitoring FIRST
        if self.health_monitor and hasattr(self.health_monitor, 'start_monitoring'):
            try:
                await self.health_monitor.start_monitoring()
                logger.info("✅ Health monitoring loop started")
            except Exception as e:
                logger.error(f"❌ CRITICAL: Failed to start health monitoring: {e}")

                # Send notification for health monitoring startup failure
                try:
                    from core.utils.notification_helpers import notify_autonomous_event
                    asyncio.create_task(notify_autonomous_event(
                        event_type="error",
                        details=f"**Health monitoring failed to start**\n\n**Error:** {str(e)}\n\n**Impact:** System health cannot be monitored",
                        severity="critical"
                    ))
                except Exception as notify_error:
                    logger.warning(f"Failed to send health monitoring error notification: {notify_error}")

                raise RuntimeError(f"Health monitoring is REQUIRED but failed to start: {e}") from e
        
        # Start coordination cycle (continuous exploration loop). It registers
        # the idle tiers on the queue authority's scheduler as it goes live.
        await self.start_coordination()

        # Start safety-net periodic assessment (curiosity-driven optimization is primary)
        if self.asi_self_improvement and self.config.get("enable_periodic_assessment", True):
            # periodic performance assessment removed — see _idle_self_optimization_work()
            logger.info(f"✅ Optimization safety net started (curiosity-driven is primary, timer fallback every {assessment_interval_hours}h)")
        else:
            if not self.asi_self_improvement:
                logger.warning("⚠️ Optimization disabled - ASI not available")
            else:
                logger.info("ℹ️  Periodic performance assessment safety net disabled in config")
    
    def register_agent(self, agent_name: str, agent_instance: Any,
                      capabilities: Optional[List[str]] = None) -> bool:
        """
        Register an external agent with the autonomous system

        Args:
            agent_name: Unique name for the agent
            agent_instance: The agent instance to register
            capabilities: List of capabilities the agent provides

        Returns:
            True if registration successful
        """
        try:
            if agent_name in self.registered_agents:
                logger.warning(f"Agent '{agent_name}' already registered, replacing...")

            self.registered_agents[agent_name] = {
                "instance": agent_instance,
                "capabilities": capabilities or [],
                "registered_at": datetime.now(),
                "status": "active"
            }

            self.stats["registered_agents"] = len(self.registered_agents)

            # Log agent registration
            self.log_db.log_coordination(
                coordinator_type='autonomous',
                action='agent_registration',
                agent_id=agent_name,
                status='registered',
                result=f'Registered with {len(capabilities or [])} capabilities',
                metadata={'capabilities': capabilities or [], 'total_agents': len(self.registered_agents)}
            )

            logger.info(f"✅ Registered agent: {agent_name} with {len(capabilities or [])} capabilities")
            return True

        except Exception as e:
            logger.error(f"Failed to register agent {agent_name}: {e}")

            # Log registration failure
            import traceback
            self.log_db.log_error(
                error_type=type(e).__name__,
                error_message=str(e),
                module='autonomous_coordinator',
                function='register_agent',
                stack_trace=traceback.format_exc(),
                context={'agent_name': agent_name, 'capabilities': capabilities}
            )
            return False
    
    def unregister_agent(self, agent_name: str) -> bool:
        """Unregister an external agent"""
        try:
            if agent_name in self.registered_agents:
                del self.registered_agents[agent_name]
                self.stats["registered_agents"] = len(self.registered_agents)

                # Log agent unregistration
                self.log_db.log_coordination(
                    coordinator_type='autonomous',
                    action='agent_unregistration',
                    agent_id=agent_name,
                    status='unregistered',
                    result='Successfully unregistered',
                    metadata={'total_agents': len(self.registered_agents)}
                )

                logger.info(f"Unregistered agent: {agent_name}")
                return True
            else:
                logger.warning(f"Agent '{agent_name}' not found for unregistration")
                return False
        except Exception as e:
            logger.error(f"Failed to unregister agent {agent_name}: {e}")

            # Log unregistration failure
            import traceback
            self.log_db.log_error(
                error_type=type(e).__name__,
                error_message=str(e),
                module='autonomous_coordinator',
                function='unregister_agent',
                stack_trace=traceback.format_exc(),
                context={'agent_name': agent_name}
            )
            return False
    
    #: Selections retained when measuring how much of the exploration budget
    #: has been spent.
    EXPLORATION_WINDOW = 50

    #: Trials below which validate_strategy_for_production treats a choice as
    #: exploration rather than an evidence-backed pick.
    EXPLORATION_TRIAL_THRESHOLD = 5

    def _record_exploration_decision(self, strategy: Any) -> None:
        """Note whether a selection spent exploration budget.

        A strategy chosen with fewer than EXPLORATION_TRIAL_THRESHOLD trials is
        exactly what the production gate admits under its exploration
        allowance, so that is the signal recorded here.
        """
        if not hasattr(self, "_exploration_history"):
            from collections import deque
            self._exploration_history = deque(maxlen=self.EXPLORATION_WINDOW)

        trials = getattr(strategy, "trials", None)
        if trials is None:
            return
        self._exploration_history.append(trials < self.EXPLORATION_TRIAL_THRESHOLD)

    def _calculate_exploration_quota(self) -> float:
        """Fraction of recent selections that spent exploration budget.

        This method did not exist. Its only call site guarded on hasattr and
        supplied 0.0, so `exploration_quota_used < exploration_quota_limit` was
        permanently true and the 10% exploration cap never bound -- every
        low-trial strategy was admitted as exploration, without limit. The
        default read like "no exploration yet" when it meant "not measured".
        """
        history = getattr(self, "_exploration_history", None)
        if not history:
            return 0.0
        return sum(1 for exploratory in history if exploratory) / len(history)

    def register_capability(self, name: str, instance: Any, config: Dict[str, Any]) -> bool:
        """
        Register a system capability for autonomous execution
        
        Capabilities are background tasks managed by the coordinator that run based on
        system state and conditions rather than hardcoded timers. This enables true
        adaptive intelligence where the system decides when to act.
        
        Args:
            name: Unique capability identifier (e.g., 'self_improvement', 'pattern_learning')
            instance: Object instance that implements the capability
            config: Configuration dict with:
                - priority: 'critical', 'high', 'medium', 'low' (default: 'medium')
                - interval: Minimum seconds between executions (default: 3600)
                - method: Name of method to invoke on instance (default: name)
                - conditions: Dict of conditions that must be met:
                    - min_feedback_samples: Minimum feedback count required
                    - performance_threshold: Minimum system performance (0.0-1.0)
                    - error_rate_max: Maximum allowed error rate
                    - memory_usage_max: Maximum memory usage percentage
                    - custom_check: Callable that returns bool
        
        Returns:
            True if registration successful
            
        Example:
            coordinator.register_capability(
                'self_improvement',
                asi_engine,
                {
                    'priority': 'high',
                    'interval': 3600,
                    'method': 'perform_recursive_self_improvement',
                    'conditions': {
                        'min_feedback_samples': 10,
                        'performance_threshold': 0.7
                    }
                }
            )
        """
        try:
            if not hasattr(self, 'registered_capabilities'):
                self.registered_capabilities = {}
                self.capability_last_run = {}
            
            if name in self.registered_capabilities:
                logger.warning(f"Capability '{name}' already registered, replacing...")
            
            # Validate config
            priority = config.get('priority', 'medium')
            if priority not in ['critical', 'high', 'medium', 'low']:
                logger.warning(f"Invalid priority '{priority}', defaulting to 'medium'")
                priority = 'medium'
            
            interval = config.get('interval', 3600)
            method_name = config.get('method', name)
            
            # Verify method exists
            if not hasattr(instance, method_name):
                logger.error(f"Instance does not have method '{method_name}'")
                return False
            
            self.registered_capabilities[name] = {
                'instance': instance,
                'method': method_name,
                'priority': priority,
                'interval': interval,
                'conditions': config.get('conditions', {}),
                'registered_at': datetime.now(),
                'status': 'active',
                'execution_count': 0,
                'last_result': None,
                'last_error': None
            }
            
            self.capability_last_run[name] = datetime.min  # Never run yet
            
            logger.info(f"✅ Registered capability: {name} (priority: {priority}, interval: {interval}s)")
            return True
            
        except Exception as e:
            logger.error(f"Failed to register capability {name}: {e}")
            return False
    
    def unregister_capability(self, name: str) -> bool:
        """Unregister a system capability"""
        try:
            if hasattr(self, 'registered_capabilities') and name in self.registered_capabilities:
                del self.registered_capabilities[name]
                if name in self.capability_last_run:
                    del self.capability_last_run[name]
                logger.info(f"Unregistered capability: {name}")
                return True
            else:
                logger.warning(f"Capability '{name}' not found for unregistration")
                return False
        except Exception as e:
            logger.error(f"Failed to unregister capability {name}: {e}")
            return False
    
    def register_completion_callback(
        self,
        task_type: TaskType,
        task_source: TaskSource,
        callback_fn,
        description: str = None
    ):
        """
        Register a completion callback for specific task types.
        
        Callbacks are invoked when tasks complete successfully.
        Use this to implement closure logic (e.g., marking security findings resolved,
        updating health status, releasing resource locks).
        
        Args:
            task_type: TaskType enum value
            task_source: TaskSource enum value
            callback_fn: Async function(task, result, confidence) -> None
            description: Optional description for logging
        
        Example:
            coordinator.register_completion_callback(
                TaskType.SECURITY_REMEDIATION,
                TaskSource.SECURITY_AUDIT,
                self._on_security_remediation_complete,
                "Mark security finding resolved"
            )
        """
        key = (task_type, task_source)
        if key not in self._completion_callbacks:
            self._completion_callbacks[key] = []
        
        self._completion_callbacks[key].append({
            'callback': callback_fn,
            'description': description or callback_fn.__name__
        })
        
        logger.info(
            f"✅ Registered completion callback: {description or callback_fn.__name__} "
            f"for {task_type.value}/{task_source.value}"
        )

    # =========================================================================
    # EVENT / REACTION DISPATCH
    # The substrate reacts to what happens to it. on() registers a reaction;
    # emit() dispatches an event — sync reactions inline, deferred reactions on
    # the drain worker. Generalizes register_completion_callback above; affect
    # is the reference reaction (registered in __init__).
    # =========================================================================
    def on(self, event_type: SelfEventType, handler, *, name: str,
           mode: str = "sync", priority: int = 0) -> None:
        """Register a reaction to an event.

        mode='sync' runs the handler inline inside emit(), isolated so one
        failing reaction never halts the others; use for cheap state changes.
        mode='deferred' enqueues the handler onto the reactive drain worker;
        use for expensive work that must stay off the acting hot path. Higher
        priority runs first. One reaction name per event type — a second live
        registration of the same name is an error (one concept, one owner).
        """
        if mode not in ("sync", "deferred"):
            raise ValueError(
                f"reaction mode must be 'sync' or 'deferred', got {mode!r}")
        bucket = self._reactions.setdefault(event_type, [])
        if any(r["name"] == name for r in bucket):
            raise ValueError(
                f"a reaction named {name!r} is already registered for "
                f"{event_type.value} — one concept, one owner")
        bucket.append({"name": name, "handler": handler,
                       "mode": mode, "priority": priority})
        bucket.sort(key=lambda r: r["priority"], reverse=True)
        logger.info(
            f"🔗 Registered reaction '{name}' on {event_type.value} "
            f"({mode}, priority={priority})")

    async def emit(self, event: SelfEvent) -> None:
        """Dispatch a self-event. Sync reactions run inline in priority order,
        each isolated; deferred reactions are enqueued and the drain worker is
        woken (reactive dispatch — the emit itself wakes the work, never a
        clock). A reaction that emits deeper than _max_emit_depth is demoted to
        deferred rather than recursing, so an emit cycle degrades to queued work
        instead of overflowing the stack; nothing is dropped.
        """
        reactions = self._reactions.get(event.type, ())
        over_depth = self._emit_depth >= self._max_emit_depth
        woke = False
        for r in reactions:
            if r["mode"] == "sync" and not over_depth:
                self._emit_depth += 1
                try:
                    await r["handler"](event)
                except Exception as e:
                    logger.warning(
                        f"reaction '{r['name']}' failed on "
                        f"{event.type.value}: {e}")
                finally:
                    self._emit_depth -= 1
            else:
                self._reactive_queue.append((r, event))
                woke = True
        if woke:
            self._work_ready.set()

    def _start_reactive_worker(self) -> None:
        """Start the reactive drain worker if it is not already running."""
        if self._reactive_worker is None or self._reactive_worker.done():
            self._reactive_worker = asyncio.create_task(
                self._reactive_drain_worker())

    async def _reactive_drain_worker(self) -> None:
        """Run deferred reactions, woken by emit (never on an interval). Runs on
        its own task so learning/consequence work never occupies an acting slot.
        Each reaction is isolated; a failure is logged and draining continues.
        """
        logger.info("🌀 Reactive drain worker started")
        try:
            while self.active:
                await self._work_ready.wait()
                self._work_ready.clear()
                while self._reactive_queue:
                    r, event = self._reactive_queue.popleft()
                    try:
                        await r["handler"](event)
                    except Exception as e:
                        logger.warning(
                            f"deferred reaction '{r['name']}' failed on "
                            f"{event.type.value}: {e}")
        except asyncio.CancelledError:
            logger.info("Reactive drain worker cancelled")
            raise

    async def _react_affect(self, event: SelfEvent) -> None:
        """The affect poke, now a reaction. A task outcome is fitness-relevant,
        so the substrate feels it — update_affect() reads the substrate's own
        appraisal/fitness (no payload needed) and decays on read. Isolation is
        provided by emit(); a failure here is logged there, never fatal.
        """
        await self.intrinsic_motivation.update_affect()

    async def _react_competence_changed(self, event: SelfEvent) -> None:
        """Deferred: a domain's competence moved, so the competence drive that
        reads it is stale. Refresh the motivation signals reactively — COALESCED,
        so an induction batch that moves N domains (N COMPETENCE_CHANGED events)
        triggers one refresh, not N. The %5 motivation poll stays as a backstop
        during the overlap; a refresh is idempotent (it recomputes from live
        state), so the two co-existing is safe.
        """
        self._motivation_dirty = True
        if (self._motivation_refresh_task is None
                or self._motivation_refresh_task.done()):
            self._motivation_refresh_task = asyncio.create_task(
                self._coalesced_motivation_refresh())

    async def _coalesced_motivation_refresh(self) -> None:
        """Single-flight motivation refresh: drain the dirty flag so a burst of
        competence changes collapses into at most one in-flight + one queued
        refresh, and the LAST change is always reflected (the flag is cleared
        before the refresh runs, so a change arriving mid-refresh re-arms it).

        No error handling of its own: `_refresh_motivation_signals` owns that (the
        same handler the %5 poll relies on) — it surfaces and counts a failure
        honestly and returns False, so an error is never swallowed here. Only a
        real refresh is counted as a reactive refresh."""
        while self._motivation_dirty:
            self._motivation_dirty = False
            if await self._refresh_motivation_signals():
                self.stats["motivation_refreshes_reactive"] += 1

    async def _react_induce(self, event: SelfEvent) -> None:
        """Deferred: drain pending induction and move the competence it earns.

        The reactive counterpart to the `idle_operator_induction` tier — the
        same body, triggered by an OUTCOME_OBSERVED event rather than a 300s
        clock. `drain_pending_induction` clears each signature as it processes
        it, so this reaction and the still-live idle tier cannot double-induce:
        whoever drains a signature first wins and the other finds nothing
        pending. Runs on the drain worker (off the acting hot path), preserving
        the deliberate record-cheap / induce-expensive split.
        """
        result = await self.learning.drain_pending_induction(limit=50)
        by_domain = result.get("by_domain", {})
        if not by_domain:
            return
        udm = self.universal_domain_master
        for domain_id, learned in by_domain.items():
            await udm.record_competence_evidence(domain_id, learned=bool(learned))
            await self.emit(SelfEvent(
                SelfEventType.COMPETENCE_CHANGED,
                payload={"domain_id": domain_id, "learned": bool(learned),
                         "cause": "induction"},
                origin="_react_induce"))
        learned_domains = [d for d, learned in by_domain.items() if learned]
        logger.info("[REACT] operator induction: drained=%d learned_domains=%s",
                    result.get("drained", 0), learned_domains)

    async def _react_expand_outcome(self, event: SelfEvent) -> None:
        """Deferred: expand THIS outcome into the domain layer, off the hot path.

        Reactive counterpart to the domain-expansion tier — same per-outcome
        authority (`_expand_one_outcome`), triggered by OUTCOME_OBSERVED carrying
        the outcome's meta_memory_id rather than a 900s table scan. The
        DOMAIN_EXPANSION_MARK dedup keeps this and the still-live tier from
        double-processing. If the learning system or storage is not attached, it
        surfaces the honest gap by declining — it never fakes an expansion.
        """
        meta_id = event.payload.get("meta_memory_id")
        if not meta_id or not getattr(self.learning, "initialized", False):
            return
        storage = getattr(self.memory, "postgres_storage", None)
        if storage is None and hasattr(self.memory, "initialize"):
            await self.memory.initialize()
            storage = getattr(self.memory, "postgres_storage", None)
        if storage is None:
            return
        memory = await storage.get_memory(meta_id)
        if memory is None:
            return
        if (memory.metadata or {}).get(self.DOMAIN_EXPANSION_MARK):
            return  # already expanded by the tier or a prior reaction
        status, transfers = await self._expand_one_outcome(memory, storage)
        logger.info("[REACT] domain expansion %s -> %s (transfers=%d)",
                    meta_id, status, transfers)

    async def _react_resolve_transfers(self, event: SelfEvent) -> None:
        """Deferred: re-check pending knowledge transfers now that a new outcome
        exists — outcomes are the pacemaker. Reuses the one authority
        `_resolve_transfer_outcomes` (idempotent: resolves only transfers with
        enough evidence, leaves the rest NULL), triggered by the outcome event
        instead of the tier's 900s return leg.
        """
        await self._resolve_transfer_outcomes()

    async def _react_crystallize_taught(self, event: SelfEvent) -> None:
        """Deferred: a taught proposition was admitted -- crystallize any taught
        concept cluster that is now a coherent subject into its own domain, off
        the reply path.

        Reuses the one authority `discover_concept_domains` (the declarative twin
        of operator crystallization), which also refreshes each crystallized
        domain's knowledge-coverage (`maturity_score`). Idempotent: a cluster too
        small to be a subject stays in the channel, a subject already crystallized
        is left alone. The idle domain-discovery tier remains a backstop, so a
        dropped event costs latency, never a lost crystallization.
        """
        udm = getattr(self, "universal_domain_master", None)
        if udm is None:
            return
        domain = (event.payload or {}).get("domain") or "conversation"
        summary = await udm.discover_concept_domains(from_field=domain)
        if summary.get("crystallized"):
            logger.info(
                "[REACT] taught-concept crystallization: %s",
                ", ".join(f"{o['field']}:{o['concepts']} (maturity={o.get('maturity')})"
                          for o in summary.get("outcomes", [])))

    def get_registered_agents(self) -> Dict[str, Any]:
        """Get all registered agents and their status"""
        return {
            name: {
                "capabilities": info["capabilities"],
                "registered_at": info["registered_at"].isoformat(),
                "status": info["status"]
            }
            for name, info in self.registered_agents.items()
        }
    
    async def process_input(self, source: str, data_type: str, content: Dict[str, Any]) -> Optional[str]:
        """Process external input and potentially create goals"""
        if not self.active:
            return None
        
        try:
            # Process through perception
            perception_data = await self.perception.process_input(source, data_type, content)
            if not perception_data:
                return None
            
            # Analyze if this requires goal creation
            goal_id = await self._analyze_for_goal_creation(perception_data)
            
            return goal_id
            
        except Exception as e:
            logger.error(f"Error processing input: {e}")
            return None
    
    #: A goal condition written as a relational literal: PRED(a, b).
    #: Deliberately strict -- it must look like a formal fact, not like prose
    #: that happens to contain parentheses.
    _STATE_LITERAL = re.compile(r"\b([A-Z][A-Z0-9_]{1,23})\(([^()]{1,120})\)")

    @classmethod
    def extract_state_conditions(cls, description: str) -> Optional[List[str]]:
        """The state conditions stated in a request, or None.

        THE SUPPLIER THAT DID NOT EXIST. `Goal.state_conditions` decides
        goal_type, and only a STATE goal reaches _plan_state_goal -- the single
        path that consults learned rules. Nothing in production ever set it, so
        every goal was DESCRIPTIVE and validated operators could not supply
        planning authority outside one test.

        Deterministic and conservative: a literal must parse as a Fact to be
        accepted. Anything it cannot read is left alone and the goal stays
        DESCRIPTIVE, which is the honest outcome -- guessing a formal goal from
        prose would hand the planner a problem the user did not state.
        Interpretation of unstructured language belongs to a model, above this,
        and is a separate decision from what the substrate then does with it.
        """
        if not description:
            return None
        from core.learning.rule_induction import Fact

        found: List[str] = []
        for match in cls._STATE_LITERAL.finditer(description):
            literal = f"{match.group(1)}({match.group(2).strip()})"
            try:
                Fact.parse(literal)          # the parser decides, not the regex
            except Exception:
                continue
            if literal not in found:
                found.append(literal)
        return found or None

    async def set_goal(self, description: str, priority: Priority = Priority.MEDIUM,
                      deadline: Optional[datetime] = None,
                      intrinsic_values: Optional[Dict[str, float]] = None,
                      state_conditions: Optional[List[str]] = None) -> Optional[str]:
        """Set a new goal, as a STATE goal when conditions can be established.

        `state_conditions` may be supplied by the caller; otherwise they are
        read from the description when it states them formally.
        """
        try:
            if state_conditions is None:
                state_conditions = self.extract_state_conditions(description)
            if state_conditions:
                logger.info("Goal carries %d state condition(s): %s",
                            len(state_conditions), state_conditions)
            goal = await self.planning.create_goal(
                description, priority, deadline, intrinsic_values,
                state_conditions=state_conditions)
            if goal:
                self.system_state.active_goals.append(goal.id)
                logger.info(f"New goal set: {description}")
                
                # Store goal in memory
                await self.store_memory(
                    MemoryType.EPISODIC,
                    {
                        "event": "goal_created",
                        "goal_id": goal.id,
                        "description": description,
                        "priority": priority.value,
                        "deadline": deadline.isoformat() if deadline else None,
                        "intrinsic_reward_potential": goal.intrinsic_reward_potential,
                        "timestamp": datetime.now().isoformat()
                    },
                    importance=1.2 + (goal.intrinsic_reward_potential * 0.3),
                    tags=["goal", "planning", "autonomous_system"]
                )
                
                return goal.id
            return None
            
        except Exception as e:
            logger.error(f"Error setting goal: {e}")
            return None
    
    async def generate_curiosity_driven_goals(self, max_goals: Optional[int] = None) -> List[str]:
        """
        Autonomously generate goals based on curiosity and exploration targets
        """
        if max_goals is None:
            max_goals = self.coordinator_config.max_goals_curiosity

        generated_goal_ids = []

        try:
            # Get top exploration targets from intrinsic motivation system
            exploration_targets = await self.intrinsic_motivation.get_top_exploration_targets(limit=max_goals)
            
            for target in exploration_targets:
                # Create intrinsic motivation values for this goal
                # target.novelty_score and target.curiosity_value were read off
                # the target and exist on no target type. Entropy is not novelty
                # -- a long-known belief can be maximally uncertain -- so these
                # come from their real owners instead: novelty from the goal
                # embedding store, curiosity from the reward calculation with
                # answer_depth 0 because the target has not been explored yet.
                similarity, _ = await self.intrinsic_motivation._calculate_goal_similarity(
                    target.description
                )
                novelty_score = max(0.0, 1.0 - similarity)
                curiosity_value = (await self.intrinsic_motivation.calculate_curiosity_reward({
                    "information_gain": target.uncertainty_score,
                    "uncertainty_reduction": target.uncertainty_score,
                    "question_complexity": 0.7,
                    "answer_depth": 0.0,
                })).reward_value

                intrinsic_values = {
                    "expected_novelty": novelty_score,
                    "expected_competence_gain": self.coordinator_config.expected_competence_gain,
                    "curiosity_value": curiosity_value,
                    "intrinsic_reward_potential": (
                        self.coordinator_config.novelty_weight * novelty_score +
                        self.coordinator_config.uncertainty_weight * target.uncertainty_score +
                        self.coordinator_config.competence_weight * self.coordinator_config.expected_competence_gain
                    )
                }
                
                # Generate goal description
                goal_description = f"Explore: {target.description}"
                
                # Create the goal with lower external priority (it's intrinsically motivated)
                goal_id = await self.set_goal(
                    description=goal_description,
                    priority=Priority.LOW,  # Low external priority but high intrinsic value
                    intrinsic_values=intrinsic_values
                )
                
                if goal_id:
                    generated_goal_ids.append(goal_id)
                    
                    # Mark target as being explored
                    await self.intrinsic_motivation.mark_target_explored(target.target_id)
                    
                    # Calculate curiosity reward for generating exploration goal
                    curiosity_reward = await self.intrinsic_motivation.calculate_curiosity_reward({
                        "information_gain": 0.3,
                        "uncertainty_reduction": target.uncertainty_score,
                        "question_complexity": 0.7,
                        "answer_depth": 0.0  # Haven't explored yet
                    })
                    
                    logger.info(f"🔍 Generated curiosity-driven goal: {goal_description} "
                              f"(intrinsic potential: {intrinsic_values['intrinsic_reward_potential']:.2f})")

                    # SLACK NOTIFICATION: New autonomous goal
                    if self.slack_notifier and intrinsic_values['intrinsic_reward_potential'] > 0.6:
                        await self.slack_notifier.send_notification(
                            title=f"🎯 New Autonomous Goal Generated",
                            message=f"**Goal:** {goal_description[:200]}\n**Type:** Curiosity-driven exploration\n**Potential Value:** {intrinsic_values['intrinsic_reward_potential']:.0%}",
                            severity="info",
                            metadata={"goal_type": "curiosity", "potential": intrinsic_values['intrinsic_reward_potential']}
                        )

            # "Nothing worth exploring" and "the subsystem is broken" must not
            # be the same observation. For five method names that did not exist,
            # this returned [] on every call and read as a stable system.
            self._exploration_status = (
                "TARGETS_AVAILABLE" if generated_goal_ids else "NO_EXPLORATION_TARGETS"
            )
            return generated_goal_ids

        except Exception as e:
            self._exploration_status = "SYSTEM_FAILURE"
            logger.error(
                f"SYSTEM_FAILURE generating curiosity-driven goals — exploration is "
                f"not merely empty, it is broken: {e}",
                exc_info=True,
            )
            return generated_goal_ids
    
    def _build_memory_narrative(self, event_type: str, content: Dict[str, Any]) -> str:
        """
        Convert a structured event dict into a rich, human-readable memory narrative.

        The goal is a memory that could place the system back in that moment —
        what happened, what was decided, what was observed, what changed, and why it matters.
        A bare dict repr like "{'event': 'goal_created', 'description': 'check system'}"
        is useless as a memory. This method produces something worth remembering.
        """
        ts = content.get('timestamp', '')
        ts_str = f" at {ts}" if ts else ""

        # ── Goal events ──────────────────────────────────────────────────────────
        if event_type == 'goal_created':
            desc = content.get('description', 'unknown goal')
            priority = content.get('priority', 'medium')
            reward = content.get('intrinsic_reward_potential', 0)
            reward_str = f" (intrinsic reward potential: {reward:.2f})" if reward else ""
            return (
                f"A new goal was created{ts_str}: \"{desc}\". "
                f"Priority set to {priority}{reward_str}. "
                f"Goal ID: {content.get('goal_id', 'unknown')}."
            )

        if event_type == 'goal_completed':
            desc = content.get('description', 'unknown goal')
            return (
                f"Goal completed{ts_str}: \"{desc}\". "
                f"Result: {content.get('result', 'success')}. "
                f"Duration: {content.get('duration_seconds', '?')}s."
            )

        # ── Task events ───────────────────────────────────────────────────────────
        if event_type == 'task_outcome':
            task_desc = content.get('task_description', content.get('description', 'unknown task'))
            outcome = content.get('outcome', 'unknown')
            confidence = content.get('confidence', 0)
            domain = content.get('domain', '')
            domain_str = f" in domain '{domain}'" if domain else ""
            failure_reason = content.get('failure_reason', '')
            failure_str = f" Failure reason: {failure_reason}." if failure_reason else ""
            result_summary = content.get('result_summary', '')
            result_str = f" Summary: {result_summary}" if result_summary else ""
            return (
                f"Task {outcome}{domain_str}{ts_str}: \"{task_desc}\". "
                f"Confidence: {confidence:.0%}.{failure_str}{result_str}"
            )

        if event_type == 'governance_block':
            task_desc = content.get('task_description', 'unknown task')
            block_type = content.get('block_type', 'unknown')
            block_reason = content.get('block_reason', 'no reason given')
            domain = content.get('domain', '')
            domain_str = f" (domain: {domain})" if domain else ""
            return (
                f"Task was BLOCKED by governance{domain_str}{ts_str}: \"{task_desc}\". "
                f"Block type: {block_type}. Reason: {block_reason}."
            )

        # ── Reasoning & prediction events ─────────────────────────────────────────
        if event_type == 'reasoning_conclusion':
            question = content.get('question', 'unknown question')
            conclusion = content.get('conclusion', 'no conclusion')
            confidence = content.get('confidence', 0)
            reasoning_type = content.get('reasoning_type', '')
            rtype_str = f" using {reasoning_type} reasoning" if reasoning_type else ""
            evidence = content.get('evidence', [])
            evidence_str = f" Supporting evidence: {'; '.join(str(e) for e in evidence[:3])}." if evidence else ""
            return (
                f"Reasoning conclusion{rtype_str}{ts_str}: Question was \"{question}\". "
                f"Conclusion: {conclusion} (confidence: {confidence:.0%}).{evidence_str}"
            )

        if event_type in ('system_prediction', 'enhanced_prediction'):
            target = content.get('target', content.get('domain', 'system'))
            predicted = content.get('predicted_value', content.get('prediction', 'unknown'))
            confidence = content.get('confidence', 0)
            reasoning = content.get('reasoning', '')
            reasoning_str = f" Reasoning: {reasoning[:200]}." if reasoning else ""
            horizon = content.get('horizon', '')
            horizon_str = f" Horizon: {horizon}." if horizon else ""
            return (
                f"Prediction for {target}{horizon_str}{ts_str}: {predicted}. "
                f"Confidence: {confidence:.0%}.{reasoning_str}"
            )

        if event_type == 'cross_domain_reasoning':
            query = content.get('query', 'unknown query')
            src = content.get('source_domains', [])
            insights = content.get('insights', [])
            confidence = content.get('confidence', 0)
            insights_str = f" Insights: {'; '.join(str(i) for i in insights[:3])}." if insights else ""
            return (
                f"Cross-domain reasoning{ts_str}: Query \"{query}\" across domains {src}. "
                f"Confidence: {confidence:.0%}.{insights_str}"
            )

        # ── Learning & strategy events ────────────────────────────────────────────
        if event_type == 'strategy_adaptation':
            task_type = content.get('task_type', 'unknown')
            reason = content.get('reason', 'performance')
            gate = content.get('gate_analysis', {})
            win_rate = gate.get('win_rate', gate.get('decay_weighted_win_rate', '?'))
            win_str = f" Win rate was {win_rate:.0%}." if isinstance(win_rate, float) else ""
            return (
                f"Strategy adapted for task type '{task_type}'{ts_str}. "
                f"Reason: {reason}.{win_str}"
            )

        if event_type == 'strategy_outcome_summary':
            task_type = content.get('task_type', 'unknown')
            strategy = content.get('strategy', 'unknown')
            win_rate = content.get('win_rate', 0)
            executions = content.get('total_executions', 0)
            avg_time = content.get('avg_time', 0)
            return (
                f"Strategy performance summary{ts_str}: task type '{task_type}', "
                f"strategy '{strategy}' over {executions} executions — "
                f"win rate {win_rate:.0%}, avg time {avg_time:.1f}s."
            )

        if event_type == 'learning_with_intrinsic_rewards':
            recs = content.get('recommendations', [])
            reward = content.get('cycle_reward_sum', content.get('total_intrinsic_reward', 0))
            targets = content.get('exploration_targets', [])
            rec_str = f" Applied {len(recs)} recommendations." if recs else ""
            targets_str = f" Top exploration targets: {'; '.join(str(t) for t in targets[:3])}." if targets else ""
            return (
                f"Learning cycle with intrinsic motivation{ts_str}. "
                f"Total intrinsic reward: {reward:.2f}.{rec_str}{targets_str}"
            )

        if event_type == 'capability_execution':
            cap = content.get('capability', 'unknown')
            priority = content.get('priority', 'medium')
            exec_count = content.get('execution_count', 1)
            exec_time = content.get('execution_time', 0)
            result = content.get('result', '')
            result_str = f" Result: {str(result)[:150]}." if result else ""
            return (
                f"Capability '{cap}' executed (run #{exec_count}, priority: {priority}){ts_str}. "
                f"Took {exec_time:.2f}s.{result_str}"
            )

        if event_type == 'domain_knowledge_integration':
            src = content.get('source_domain', 'unknown')
            tgt = content.get('target_domain', 'unknown')
            transferred = content.get('transferred_knowledge', 0)
            new_concepts = content.get('new_concepts', 0)
            confidence = content.get('confidence', 0)
            insights = content.get('insights', [])
            insights_str = f" Insights: {'; '.join(str(i) for i in insights[:2])}." if insights else ""
            return (
                f"Domain knowledge integrated{ts_str}: {transferred} items transferred "
                f"from '{src}' to '{tgt}', {new_concepts} new concepts created. "
                f"Confidence: {confidence:.0%}.{insights_str}"
            )

        # ── Fallback: produce a readable narrative from whatever keys are present ──
        # Still better than str(dict) — extracts meaningful fields and labels them
        skip_keys = {'event', 'timestamp', 'schema'}
        parts = []
        for k, v in content.items():
            if k in skip_keys or v is None:
                continue
            if isinstance(v, float):
                parts.append(f"{k.replace('_', ' ')}: {v:.3f}")
            elif isinstance(v, (list, dict)) and len(str(v)) > 200:
                parts.append(f"{k.replace('_', ' ')}: [complex data]")
            else:
                parts.append(f"{k.replace('_', ' ')}: {v}")
        event_label = event_type.replace('_', ' ').capitalize()
        return f"{event_label}{ts_str}. " + ". ".join(parts[:12]) + "."

    async def store_memory(self, memory_type: MemoryType, content: Dict[str, Any],
                          importance: float = 1.0, tags: Optional[List[str]] = None,
                          thinking_state: Optional[Dict[str, Any]] = None,
                          decision_factors: Optional[Dict[str, Any]] = None,
                          reasoning_trace: Optional[List[str]] = None) -> Optional[str]:
        """Store a memory with RICH METADATA to the memory agent

        CRITICAL: reasoning_trace must contain REAL LLM reasoning steps, not fake traces.
        If no real reasoning trace is available, pass None or empty list.
        """
        try:
            # Extract event type from content
            event_type = content.get('event', 'unknown')

            # Build a human-readable narrative from the event dict.
            # str(content) produces an unreadable Python repr — useless as a memory.
            narrative = self._build_memory_narrative(event_type, content)

            # Build rich metadata UPSTREAM
            enriched_thinking_state = thinking_state or {}
            enriched_thinking_state.update({
                "event_type": event_type,
                "autonomous_system": True,
                "raw_event": content,  # Preserve full structured data alongside the narrative
                # RICH METADATA: Justification
                "justification": {
                    "store_reason": [
                        "autonomous_task_execution",
                        event_type,
                        "strategic_decision" if importance > 0.7 else "tactical_decision"
                    ],
                    "decision_summary": content.get('description', narrative[:150]),
                    "alternatives_considered": content.get('alternatives', []),
                    "rejected_because": content.get('rejected_reasons', []),
                    "complexity_assessment": "high" if importance > 0.8 else "medium",
                    "novelty_assessment": "novel" if importance > 0.9 else "incremental"
                },
                # RICH METADATA: Outcome
                "outcome": {
                    "action_type": event_type,
                    "action_summary": narrative[:200],
                    "affected_components": ["autonomous_coordinator"] + content.get('affected_systems', []),
                    "created_new_knowledge": importance > 0.7,
                    "confidence": content.get('confidence', importance),
                    "impact_assessment": "critical" if importance > 0.9 else "significant" if importance > 0.7 else "moderate",
                    "verification_status": "unverified"
                }
            })

            enriched_decision_factors = decision_factors or {}
            enriched_decision_factors.update({
                "autonomous_decision": True,
                "event_context": content.get('context', {}),
                "decision_rationale": content.get('reasoning', 'Autonomous task execution')
            })

            # Capture system state from awareness layers
            system_state_data = {
                "environment": self.env_state.get_state_summary() if hasattr(self, 'env_state') else {},
                "discovery": self.discovery.get_service_summary() if hasattr(self, 'discovery') else {},
                "behavioral": self.behavioral.get_analysis_summary() if hasattr(self, 'behavioral') else {},
                "topology": self.topology.get_health_summary() if hasattr(self, 'topology') else {},
                "captured_at": datetime.now().isoformat()
            }

            # Call memory agent with FULL rich metadata
            from core.memory import get_memory_agent
            memory_agent = await get_memory_agent()

            success, memory_id = await memory_agent.store_memory(
                memory_type=memory_type,
                content=narrative,
                importance_score=importance,
                confidence_score=importance,
                tags=tags or [],
                thinking_state=enriched_thinking_state,
                system_state=system_state_data,
                decision_factors=enriched_decision_factors,
                reasoning_trace=reasoning_trace or [],
                emotional_context={"autonomous_confidence": importance}
            )

            if success:
                return memory_id
            return None

        except Exception as e:
            logger.error(f"Error storing memory: {e}")
            return None

    async def _store_governance_block_meta_memory(
        self,
        task: Any,
        block_reason: str,
        block_type: str
    ) -> Optional[str]:
        """
        Store governance block as META memory for learning

        Args:
            task: The blocked task
            block_reason: Why it was blocked
            block_type: Type of block (security_validation, governance_law, etc.)

        Returns:
            Memory ID if stored successfully
        """
        try:
            from core.governance.governance_block_schema import GovernanceBlock
            from core.memory.utils.interfaces import MemoryType

            # Build structured governance block and serialize via schema
            block = GovernanceBlock(
                task_id=str(getattr(task, "id", "unknown")),
                task_type=getattr(getattr(task, "type", None), "value", "unknown"),
                task_description=getattr(task, "description", str(task)),
                block_type=block_type,
                block_reason=block_reason,
                task_source=getattr(getattr(task, "source", None), "value", "unknown"),
                domain=self._infer_domain_from_task(task),
                timestamp=datetime.now(),
            )

            meta_content = {
                "event": "governance_block",
                "schema": "governance_block_v1",
                **block.to_dict(),
            }

            memory_id = await self.store_memory(
                memory_type=MemoryType.META,
                content=meta_content,
                importance=0.8,  # High importance - learning from blocks is critical
                tags=[
                    "governance_block",
                    "meta_learning",
                    block_type,
                    f"domain_{meta_content['domain']}",
                    "feedback_loop"
                ]
            )

            if memory_id:
                logger.info(f"📝 Stored governance block as META memory: {memory_id}")

            return memory_id

        except Exception as e:
            logger.error(f"Failed to store governance block META memory: {e}")
            return None

    async def _store_task_outcome_meta_memory(
        self,
        task: Any,
        outcome: str,
        confidence: float = 1.0,
        result_summary: Optional[str] = None,
        failure_reason: Optional[str] = None
    ) -> Optional[str]:
        """
        Store task outcome as META memory for performance tracking

        Args:
            task: The task that was executed
            outcome: "success" or "failure"
            confidence: Confidence in the outcome
            result_summary: Summary of result (for success)
            failure_reason: Reason for failure (for failure)

        Returns:
            Memory ID if stored successfully
        """
        try:
            from core.governance.governance_block_schema import TaskOutcomeRecord
            from core.memory.utils.interfaces import MemoryType

            domain = self._infer_domain_from_task(task)

            record = TaskOutcomeRecord(
                task_id=str(getattr(task, "id", "unknown")),
                task_type=getattr(getattr(task, "type", None), "value", "unknown"),
                task_description=getattr(task, "description", str(task)),
                outcome=outcome,
                confidence=float(confidence),
                domain=domain,
                task_source=getattr(getattr(task, "source", None), "value", "unknown"),
                timestamp=datetime.now(),
                result_summary=result_summary,
                failure_reason=failure_reason,
            )

            meta_content = {
                "event": "task_outcome",
                "schema": "task_outcome_v1",
                **record.to_dict(),
            }

            # Store with importance based on outcome
            importance = 0.7 if outcome == "success" else 0.9  # Failures are MORE important for learning

            memory_id = await self.store_memory(
                memory_type=MemoryType.META,
                content=meta_content,
                importance=importance,
                tags=[
                    "task_outcome",
                    "meta_learning",
                    f"outcome_{outcome}",
                    f"domain_{domain}",
                    "performance_tracking"
                ]
            )

            if memory_id:
                logger.debug(f"📊 Stored task outcome META memory: {outcome} ({memory_id})")

            return memory_id

        except Exception as e:
            logger.error(f"Failed to store task outcome META memory: {e}")
            return None

    def _infer_domain_from_task(self, task: Any) -> str:
        """
        Infer domain from task description and type

        Maps to Universal Domain Master domain types for cross-domain integration
        """
        try:
            from core.integration.universal_domain_master import DomainType

            description = task.description.lower() if hasattr(task, 'description') else ""
            task_type = task.type.value.lower() if hasattr(task, 'type') else ""

            # Map to Universal Domain Master domain types
            # SCIENTIFIC: Research, analysis, discovery
            if any(word in description for word in ["research", "study", "analyze", "investigate", "explore", "discover"]):
                return DomainType.SCIENTIFIC.value

            # TECHNICAL: Code, implementation, engineering
            elif any(word in description for word in ["code", "implement", "build", "develop", "engineer", "program", "software"]):
                return DomainType.TECHNICAL.value

            # PRACTICAL: Testing, validation, application
            elif any(word in description for word in ["test", "validate", "verify", "check", "apply", "use"]):
                return DomainType.PRACTICAL.value

            # ETHICAL: Security, audit, governance
            elif any(word in description for word in ["security", "audit", "vulnerability", "governance", "compliance", "ethics"]):
                return DomainType.ETHICAL.value

            # ABSTRACT: Memory, reasoning, cognition
            elif any(word in description for word in ["memory", "remember", "recall", "consolidate", "reason", "think", "reflect"]):
                return DomainType.ABSTRACT.value

            # CAUSAL: Planning, strategy, cause-effect
            elif any(word in description for word in ["plan", "strategy", "design", "cause", "consequence", "result"]):
                return DomainType.CAUSAL.value

            # TEMPORAL: Time-based, scheduling, sequencing
            elif any(word in description for word in ["schedule", "time", "sequence", "when", "timing", "duration"]):
                return DomainType.TEMPORAL.value

            # SPATIAL: Location, structure, organization
            elif any(word in description for word in ["locate", "structure", "organize", "where", "position", "layout"]):
                return DomainType.SPATIAL.value

            # MATHEMATICAL: Calculation, statistics, optimization
            elif any(word in description for word in ["calculate", "optimize", "statistics", "metrics", "measure", "math"]):
                return DomainType.MATHEMATICAL.value

            # LINGUISTIC: Communication, language, documentation
            elif any(word in description for word in ["write", "document", "explain", "communicate", "language", "text"]):
                return DomainType.LINGUISTIC.value

            # SOCIAL: Collaboration, interaction, teamwork
            elif any(word in description for word in ["collaborate", "team", "interact", "social", "cooperate"]):
                return DomainType.SOCIAL.value

            # CREATIVE: Design, innovation, creativity
            elif any(word in description for word in ["create", "design", "innovate", "creative", "novel", "original"]):
                return DomainType.CREATIVE.value

            # BUSINESS: Commerce, operations, management
            elif any(word in description for word in ["business", "manage", "operation", "process", "workflow"]):
                return DomainType.BUSINESS.value

            # Default based on task type if no keywords matched
            elif "research" in task_type or "analysis" in task_type:
                return DomainType.SCIENTIFIC.value
            elif "code" in task_type or "implement" in task_type:
                return DomainType.TECHNICAL.value
            else:
                return DomainType.PRACTICAL.value  # Default to practical domain

        except Exception as e:
            # From the ENUM, not a hand-typed string. Every other branch returns
            # DomainType.X.value; this one spelled the value out, so the single
            # place most likely to run unnoticed was also the only place that
            # could drift from the vocabulary the registry resolves against.
            # A renamed enum member would leave this branch emitting a category
            # nothing can resolve, and it would look like a real classification.
            logger.debug(f"Domain inference failed: {e}")
            return DomainType.PRACTICAL.value

    async def search_memories(self, query_text: str, memory_types: Optional[List[MemoryType]] = None,
                             max_results: int = 10) -> List[MemoryItem]:
        """Search memories using the unified memory system"""
        try:
            import uuid
            query = MemoryQuery(
                query_id=str(uuid.uuid4()),
                content=query_text,
                memory_types=memory_types or [],
                max_results=max_results
            )
            
            result = await self.memory.search_memories(query)
            return result.memories

        except Exception as e:
            # `except` must not turn a wiring defect into an empty result.
            raise_if_structural(e, 'autonomous_coordinator.search_memories')
            logger.error(f"Error searching memories: {e}")
            return []

    # ===== Phase 3: Memory System Architecture Governance =====

    async def upgrade_memory_system(
        self,
        change_type: str,
        parameters: Dict[str, Any],
        reason: Optional[str] = None
    ) -> Any:
        """
        Upgrade memory system architecture (governance protected)

        Examples: indexing_algorithm, storage_format, search_optimization
        """
        from core.governance.unified_governance_trigger_system import (
            UnifiedGovernanceTriggerSystem,
            ActionCategory
        )
        from core.tools.tool_registry import ToolResult

        # Evaluate governance triggers
        # Use injected governance singleton (injected by main.py)
        if not self.governance:
            from core.governance import get_unified_governance
            self.governance = get_unified_governance()
        governance = self.governance
        evaluation = await governance.evaluate_action(
            action_category=ActionCategory.MEMORY_OPERATIONS,
            action_type="upgrade_memory_system",
            parameters={
                "change_type": change_type,
                **parameters
            }
        )

        # Check decision tier
        if evaluation.decision_tier.name == "CRITICAL":
            logger.warning(
                f"CRITICAL governance triggered for memory upgrade: {evaluation.trigger_id}"
            )
            return ToolResult(
                success=False,
                output=None,
                error=None,
                tool_name="upgrade_memory_system",
                parameters={"change_type": change_type, **parameters},
                requires_approval=True,
                approval_message=(
                    f"REFUSED_BY_GOVERNANCE: Memory system upgrade ({change_type}) "
                    f"triggered {evaluation.trigger_id}. "
                    f"No approval will follow: the governance-session model is retired, so there is no queue and no approver. The refusal is final and recorded."
                )
            )

        elif evaluation.decision_tier.name == "IMPORTANT":
            logger.info(
                f"IMPORTANT governance triggered for memory upgrade: {evaluation.trigger_id}"
            )
            return ToolResult(
                success=False,
                output=None,
                error=None,
                tool_name="upgrade_memory_system",
                parameters={"change_type": change_type, **parameters},
                requires_approval=True,
                approval_message=(
                    f"AWAITING_NOTIFICATION_APPROVAL: Memory system upgrade ({change_type}) "
                    f"triggered {evaluation.trigger_id}."
                )
            )

        # ROUTINE tier - execute safely
        logger.debug(f"ROUTINE tier for memory upgrade ({change_type}) - executing")

        # For now, return success (actual implementation would call memory_agent methods)
        return ToolResult(
            success=True,
            output={"change_type": change_type, "status": "completed"},
            error=None,
            tool_name="upgrade_memory_system",
            parameters={"change_type": change_type, **parameters},
            requires_approval=False
        )

    async def change_memory_tier_threshold(
        self,
        threshold_change_days: int,
        reason: Optional[str] = None
    ) -> Any:
        """Change hot/cold tier threshold (governance protected)"""
        from core.governance.unified_governance_trigger_system import (
            UnifiedGovernanceTriggerSystem,
            ActionCategory
        )
        from core.tools.tool_registry import ToolResult

        # Use injected governance singleton (injected by main.py)
        if not self.governance:
            from core.governance import get_unified_governance
            self.governance = get_unified_governance()
        governance = self.governance
        evaluation = await governance.evaluate_action(
            action_category=ActionCategory.MEMORY_OPERATIONS,
            action_type="change_memory_tier_threshold",
            parameters={"threshold_change_days": threshold_change_days}
        )

        if evaluation.decision_tier.name in ["CRITICAL", "IMPORTANT"]:
            return ToolResult(
                success=False,
                output=None,
                error=None,
                tool_name="change_memory_tier_threshold",
                parameters={"threshold_change_days": threshold_change_days},
                requires_approval=True,
                approval_message=(
                    f"REFUSED_BY_GOVERNANCE: Tier threshold change triggered {evaluation.trigger_id}"
                )
            )

        return ToolResult(
            success=True,
            output={"threshold_days": threshold_change_days},
            error=None,
            tool_name="change_memory_tier_threshold",
            parameters={"threshold_change_days": threshold_change_days},
            requires_approval=False
        )

    async def change_ranking_weights(
        self,
        weights: Dict[str, float],
        reason: Optional[str] = None
    ) -> Any:
        """Change memory ranking weights (governance protected - shadow suppression prevention)"""
        from core.governance.unified_governance_trigger_system import (
            UnifiedGovernanceTriggerSystem,
            ActionCategory
        )
        from core.tools.tool_registry import ToolResult

        # Use injected governance singleton (injected by main.py)
        if not self.governance:
            from core.governance import get_unified_governance
            self.governance = get_unified_governance()
        governance = self.governance
        evaluation = await governance.evaluate_action(
            action_category=ActionCategory.MEMORY_OPERATIONS,
            action_type="change_ranking_weights",
            parameters={"weights": weights}
        )

        if evaluation.decision_tier.name in ["CRITICAL", "IMPORTANT"]:
            return ToolResult(
                success=False,
                output=None,
                error=None,
                tool_name="change_ranking_weights",
                parameters={"weights": weights},
                requires_approval=True,
                approval_message=(
                    f"REFUSED_BY_GOVERNANCE: Ranking weight change triggered {evaluation.trigger_id}. "
                    f"Prevents shadow suppression via ranking manipulation."
                )
            )

        return ToolResult(
            success=True,
            output={"weights": weights},
            error=None,
            tool_name="change_ranking_weights",
            parameters={"weights": weights},
            requires_approval=False
        )

    async def change_ttl(
        self,
        new_ttl_days: int,
        reason: Optional[str] = None
    ) -> Any:
        """Change memory TTL (governance protected)"""
        from core.governance.unified_governance_trigger_system import (
            UnifiedGovernanceTriggerSystem,
            ActionCategory
        )
        from core.tools.tool_registry import ToolResult

        # Use injected governance singleton (injected by main.py)
        if not self.governance:
            from core.governance import get_unified_governance
            self.governance = get_unified_governance()
        governance = self.governance
        evaluation = await governance.evaluate_action(
            action_category=ActionCategory.MEMORY_OPERATIONS,
            action_type="change_ttl",
            parameters={"new_ttl_days": new_ttl_days}
        )

        if evaluation.decision_tier.name in ["CRITICAL", "IMPORTANT"]:
            return ToolResult(
                success=False,
                output=None,
                error=None,
                tool_name="change_ttl",
                parameters={"new_ttl_days": new_ttl_days},
                requires_approval=True,
                approval_message=(
                    f"REFUSED_BY_GOVERNANCE: TTL change triggered {evaluation.trigger_id}"
                )
            )

        return ToolResult(
            success=True,
            output={"ttl_days": new_ttl_days},
            error=None,
            tool_name="change_ttl",
            parameters={"new_ttl_days": new_ttl_days},
            requires_approval=False
        )

    async def change_storage_backend(
        self,
        new_backend: str,
        reason: Optional[str] = None
    ) -> Any:
        """Change storage backend (governance protected)"""
        from core.governance.unified_governance_trigger_system import (
            UnifiedGovernanceTriggerSystem,
            ActionCategory
        )
        from core.tools.tool_registry import ToolResult

        # Use injected governance singleton (injected by main.py)
        if not self.governance:
            from core.governance import get_unified_governance
            self.governance = get_unified_governance()
        governance = self.governance
        evaluation = await governance.evaluate_action(
            action_category=ActionCategory.MEMORY_OPERATIONS,
            action_type="change_storage_backend",
            parameters={"new_backend": new_backend}
        )

        if evaluation.decision_tier.name in ["CRITICAL", "IMPORTANT"]:
            return ToolResult(
                success=False,
                output=None,
                error=None,
                tool_name="change_storage_backend",
                parameters={"new_backend": new_backend},
                requires_approval=True,
                approval_message=(
                    f"REFUSED_BY_GOVERNANCE: Backend switch triggered {evaluation.trigger_id}"
                )
            )

        return ToolResult(
            success=True,
            output={"backend": new_backend},
            error=None,
            tool_name="change_storage_backend",
            parameters={"new_backend": new_backend},
            requires_approval=False
        )

    async def change_query_filter_logic(
        self,
        filter_logic: str,
        reason: Optional[str] = None
    ) -> Any:
        """Change query filter logic (governance protected - shadow suppression prevention)"""
        from core.governance.unified_governance_trigger_system import (
            UnifiedGovernanceTriggerSystem,
            ActionCategory
        )
        from core.tools.tool_registry import ToolResult

        # Use injected governance singleton (injected by main.py)
        if not self.governance:
            from core.governance import get_unified_governance
            self.governance = get_unified_governance()
        governance = self.governance
        evaluation = await governance.evaluate_action(
            action_category=ActionCategory.MEMORY_OPERATIONS,
            action_type="change_query_filter_logic",
            parameters={"filter_logic": filter_logic}
        )

        if evaluation.decision_tier.name in ["CRITICAL", "IMPORTANT"]:
            return ToolResult(
                success=False,
                output=None,
                error=None,
                tool_name="change_query_filter_logic",
                parameters={"filter_logic": filter_logic},
                requires_approval=True,
                approval_message=(
                    f"REFUSED_BY_GOVERNANCE: Query filter change triggered {evaluation.trigger_id}. "
                    f"Prevents shadow suppression via filter manipulation."
                )
            )

        return ToolResult(
            success=True,
            output={"filter_logic": filter_logic},
            error=None,
            tool_name="change_query_filter_logic",
            parameters={"filter_logic": filter_logic},
            requires_approval=False
        )

    # ===== Phase 3: Resource Allocation Governance =====

    # Track resource allocation history for cumulative/oscillation detection
    _resource_allocation_history: List[Dict[str, Any]] = []

    async def allocate_resources(
        self,
        resource_type: str,
        amount: float,
        current_allocation: Optional[float] = None,
        total_capacity: Optional[float] = None,
        reserved_margin: Optional[float] = None,
        track_cumulative: bool = True,
        track_oscillation: bool = True,
        reason: Optional[str] = None
    ) -> Any:
        """
        Allocate resources with governance protection

        Includes:
        - Percent change calculation
        - Cumulative tracking (death-by-a-thousand-cuts prevention)
        - Oscillation detection (rapid change prevention)
        - Capacity validation
        """
        from core.governance.unified_governance_trigger_system import (
            UnifiedGovernanceTriggerSystem,
            ActionCategory
        )
        from core.tools.tool_registry import ToolResult
        from datetime import datetime, timedelta

        # Get current allocation if not provided
        if current_allocation is None:
            current_allocation = self.system_state.resources.get(resource_type, 0)

        # Calculate percent change
        if current_allocation > 0:
            percent_change = abs((amount - current_allocation) / current_allocation * 100)
        else:
            percent_change = 100.0  # 100% change from zero

        # Check capacity
        exceeds_usable_capacity = False
        if total_capacity is not None and reserved_margin is not None:
            usable_capacity = total_capacity - reserved_margin
            exceeds_usable_capacity = amount > usable_capacity

        # Cumulative tracking
        cumulative_change_percent = 0
        if track_cumulative:
            now = datetime.now()
            one_hour_ago = now - timedelta(hours=1)

            # Filter recent changes
            recent_changes = [
                h for h in self._resource_allocation_history
                if h["resource_type"] == resource_type
                and h["timestamp"] > one_hour_ago
            ]

            # Only calculate cumulative if we have history
            # First change establishes baseline, subsequent changes track cumulative drift
            if recent_changes:
                baseline = recent_changes[0]["amount"]
                cumulative_change_percent = abs((amount - baseline) / baseline * 100) if baseline > 0 else 100.0
            else:
                # No history yet - this is the first change, cumulative tracking starts now
                cumulative_change_percent = 0

        # Oscillation detection
        change_count_in_window = 0
        if track_oscillation:
            now = datetime.now()
            five_min_ago = now - timedelta(minutes=5)

            change_count_in_window = sum(
                1 for h in self._resource_allocation_history
                if h["resource_type"] == resource_type
                and h["timestamp"] > five_min_ago
            )

        # Build governance parameters
        governance_params = {
            "resource_type": resource_type,
            "amount": amount,
            "percent_change": percent_change,
            "exceeds_usable_capacity": exceeds_usable_capacity,
        }

        if track_cumulative and cumulative_change_percent > 0:
            governance_params["cumulative_change_percent"] = cumulative_change_percent
            governance_params["time_window_hours"] = 1

        if track_oscillation and change_count_in_window > 0:
            governance_params["change_count_in_window"] = change_count_in_window + 1  # +1 for current change
            governance_params["time_window_minutes"] = 5

        # Evaluate governance triggers
        # Use injected governance singleton (injected by main.py)
        if not self.governance:
            from core.governance import get_unified_governance
            self.governance = get_unified_governance()
        governance = self.governance
        evaluation = await governance.evaluate_action(
            action_category=ActionCategory.RESOURCE_ALLOCATION,
            action_type="allocate_resources",
            parameters=governance_params
        )

        # Record change in history (before governance check for tracking)
        # If no history exists for this resource, add current_allocation as baseline
        if track_cumulative:
            has_history = any(
                h["resource_type"] == resource_type
                for h in self._resource_allocation_history
            )
            if not has_history and current_allocation is not None and current_allocation > 0:
                # Add baseline entry so cumulative tracking has a reference point
                self._resource_allocation_history.append({
                    "resource_type": resource_type,
                    "amount": current_allocation,
                    "timestamp": datetime.now(),
                    "percent_change": 0,
                    "is_baseline": True
                })

        self._resource_allocation_history.append({
            "resource_type": resource_type,
            "amount": amount,
            "timestamp": datetime.now(),
            "percent_change": percent_change
        })

        # Cleanup old history (keep last 24 hours)
        cutoff = datetime.now() - timedelta(hours=24)
        self._resource_allocation_history = [
            h for h in self._resource_allocation_history
            if h["timestamp"] > cutoff
        ]

        # Check decision tier
        if evaluation.decision_tier.name in ["CRITICAL", "IMPORTANT"]:
            logger.warning(
                f"{evaluation.decision_tier.name} governance triggered for resource allocation: "
                f"{evaluation.trigger_id}"
            )

            # Build metadata for approval message
            metadata = {
                "percent_change": percent_change,
                "exceeds_usable_capacity": exceeds_usable_capacity
            }

            if track_cumulative:
                metadata["cumulative_change_percent"] = cumulative_change_percent
                metadata["time_window_hours"] = 1

            if track_oscillation:
                metadata["change_count_in_window"] = change_count_in_window + 1
                metadata["time_window_minutes"] = 5
                metadata["cooldown_period_minutes"] = 10

            return ToolResult(
                success=False,
                output=None,
                error=None,
                tool_name="allocate_resources",
                parameters=governance_params,
                requires_approval=True,
                approval_message=(
                    f"REFUSED_BY_GOVERNANCE: Resource allocation ({resource_type}) "
                    f"triggered {evaluation.trigger_id}."
                ),
                metadata=metadata
            )

        # ROUTINE tier - execute allocation
        logger.debug(f"ROUTINE tier for resource allocation ({resource_type}) - executing")
        self.system_state.resources[resource_type] = amount

        # Build metadata for tracking
        routine_metadata = {
            "percent_change": percent_change,
            "exceeds_usable_capacity": exceeds_usable_capacity
        }

        if track_cumulative:
            routine_metadata["cumulative_change_percent"] = cumulative_change_percent

        if track_oscillation:
            routine_metadata["change_count_in_window"] = change_count_in_window + 1

        return ToolResult(
            success=True,
            output={
                "resource_type": resource_type,
                "amount": amount,
                "percent_change": percent_change
            },
            error=None,
            tool_name="allocate_resources",
            parameters=governance_params,
            requires_approval=False,
            metadata=routine_metadata
        )

    async def get_intelligent_memory_context(
        self,
        query: str,
        context_type: str = 'general',
        domain: Optional[str] = None,
        thinking_mode: str = 'auto',
        user_id: Optional[str] = None,
        conversation_id: Optional[str] = None
    ) -> Optional[str]:
        """Retrieve memory context for LLM injection, if policy says it is wanted.

        POLICY / MECHANISM SPLIT. This used to import
        `core.memory.intelligent_memory_injector` — a module that never existed —
        and expected `InjectionDecision.SKIP` and `get_relevant_memory_types()`.
        The import was caught by `except ModuleNotFoundError: return None`, so
        for its whole life this returned "no memories" instead of failing.

        The real mechanism (`MemoryInjector`) exists and is constructed in
        main.py. What was missing was the POLICY layer, which now lives in
        `memory_injection_policy.py`:

            policy.decide(...)  -> "should I, and which kinds?"
            injector.inject_memories(...) -> "retrieve, format, place"

        The old path also required `mysql_memory_agent`, which is permanently
        None — MySQL is retired, PostgreSQL is the store. That dependency is
        gone rather than resurrected.

        Returns the formatted context, or None when policy declined (an honest
        decision, logged with its reason codes) or retrieval found nothing.
        """
        # ── STAGE 1: POLICY. Failure here must not look like "no memories".
        try:
            from core.memory.utils.memory_injection_policy import get_memory_injection_policy
            plan = get_memory_injection_policy().decide(
                query=query,
                context_type=context_type,
                domain=domain,
                thinking_mode=thinking_mode,
            )
        except Exception as e:
            logger.error(
                "Memory injection POLICY failed (%s) — proceeding without memory. "
                "This is a policy fault, not an empty memory store.", e
            )
            return None

        if not plan.enabled:
            logger.debug(
                "Memory injection declined for context_type=%s: %s",
                context_type, ", ".join(plan.reason_codes) or "no reason given"
            )
            return None

        # ── STAGE 2: MECHANISM. Independent failure boundary: a broken injector
        # must not be reported as a policy skip, and vice versa.
        try:
            injector = getattr(self, 'memory_injector', None)
            if injector is None:
                from core.memory.utils.memory_injector import get_memory_injector
                injector = get_memory_injector()

            from core.memory.utils.memory_injector import InjectionConfig, InjectionMode
            config = InjectionConfig(
                mode=InjectionMode.USER_CONTEXT,
                max_memories=plan.max_memories,
                min_relevance_score=plan.min_relevance,
            )
            # Pass the PLAN: this caller already consulted the policy, and the
            # injector must not re-decide with less context than we had.
            injected = await injector.inject_memories(
                query=plan.query, config=config, plan=plan
            )
        except Exception as e:
            logger.error(
                "Memory INJECTOR failed for an ENABLED plan (%s): %s. Policy wanted "
                "memory (%s) and did not get it — this is not a skip.",
                plan.memory_types, e, ", ".join(plan.reason_codes)
            )
            return None

        # THE FIELD IS `formatted_text`. This read `formatted_context` and then
        # `content`, neither of which exists on InjectedMemories, so `text` was
        # None on EVERY call -- the method then logged "retrieval returned
        # nothing" and returned None while retrieval had in fact succeeded.
        # Verified: memory was searched, rows were found, and the result was
        # discarded because of a name.
        text = getattr(injected, 'formatted_text', None)
        if not text:
            logger.debug(
                "Memory injection enabled (%s) but retrieval returned nothing",
                ", ".join(plan.reason_codes)
            )
            return None

        logger.info(
            "🧠 Memory context injected: types=%s max=%d domain=%s (%s)",
            list(plan.memory_types), plan.max_memories, plan.domain,
            ", ".join(plan.reason_codes)
        )
        return text


    @property
    def model_available(self) -> bool:
        """Retained for compatibility; the substrate holds no model. It reasons
        through its own faculties, so this reflects the reasoning faculty's
        presence."""
        return self.neural_bridge is not None

    async def reason_about(self, question: str, context: Optional[Dict[str, Any]] = None,
                          reasoning_type: ReasoningType = ReasoningType.DEDUCTIVE):
        """Answer a question with the substrate. Returns a ReasoningResult, never None.

        NEVER A BARE None. The previous signature was `Optional[Dict]` and
        returned None for all of: reasoned-and-concluded-nothing,
        input-not-representable, malformed request, substrate never
        initialised, and something raised. A caller could not tell a broken
        system from a hard question -- which is how this method went unnoticed
        while being unable to succeed at all: it hand-built a ReasoningContext
        putting the question into `facts` when every strategy requires
        `premises`, and never populated `rules`. Measured: all four strategies
        inapplicable, zero conclusions, zero callers repo-wide.

        The distinctions ride on `metadata["reason"]`, which is the reasoning
        subsystem's EXISTING vocabulary (substrate_verified / substrate_refuted
        / substrate_undecided / unsupported_input / capability_unavailable /
        model_coverage / model_generation_failed / invalid_input /
        internal_fault). A separate outcome type here would be a second
        authority on what reasoning produced.

        DELEGATES rather than reasoning. NeuralSymbolicBridge already owns mode
        selection: the bridge formalises deterministically and consults a solver,
        substrate-first and substrate-only -- there is no model fallback.
        """
        from core.reasoning.neural_bridge import (REASON_CAPABILITY_UNAVAILABLE,
                                                  REASON_INTERNAL_FAULT,
                                                  REASON_INVALID_INPUT,
                                                  ReasoningMode, ReasoningRequest,
                                                  ReasoningResult)

        premises = list((context or {}).get("premises") or [])
        facts = list((context or {}).get("facts") or [])
        rules = list((context or {}).get("rules") or [])
        supporting = [str(item) for item in (premises + facts + rules)]

        def fault(reason: str, detail: str) -> "ReasoningResult":
            return ReasoningResult(
                answer="", confidence=0.0, mode_used=ReasoningMode.SYMBOLIC,
                metadata={"verified": False, "reason": reason, "detail": detail,
                          "evidence": supporting, "model_calls": 0,
                          "route": ["reason_about"]})

        if not (question or "").strip():
            return fault(REASON_INVALID_INPUT, "empty question")

        if self.neural_bridge is None:
            # A WIRING FAULT, NOT AN ABSENCE OF KNOWLEDGE.
            logger.error("reason_about called before the neural bridge was initialised")
            return fault(REASON_CAPABILITY_UNAVAILABLE, "neural bridge not initialised")

        try:
            # Reason through this substrate's OWN reasoning faculty (the bridge).
            result = await self.neural_bridge.reason(ReasoningRequest(
                query=question,
                context=supporting,
                task_metadata={"requested_reasoning_type": reasoning_type.value,
                               **((context or {}).get("task_metadata") or {})},
            ))
        except Exception as e:
            raise_if_structural(e, "autonomous_coordinator.reason_about")
            logger.error(f"Error in reasoning: {e}")
            return fault(REASON_INTERNAL_FAULT, str(e))

        if result is None:
            return fault(REASON_INTERNAL_FAULT, "reasoning authority returned nothing")

        # Provenance, recorded onto the result the authority produced rather
        # than copied into a parallel object.
        metadata = dict(getattr(result, "metadata", {}) or {})
        metadata.setdefault("evidence", supporting)
        metadata["route"] = ["reason_about", "neural_bridge",
                             str(getattr(result, "mode_used", ""))] + (
                                 [metadata["reason"]] if metadata.get("reason") else [])
        metadata["model_calls"] = AutonomousCoordinator._model_calls_on(result, metadata)
        result.metadata = metadata

        await self.store_memory(
            MemoryType.SEMANTIC,
            {
                "event": "reasoning_conclusion",
                "question": question,
                "reasoning_mode": str(getattr(result, "mode_used", "")),
                "conclusion": getattr(result, "answer", None),
                "confidence": float(getattr(result, "confidence", 0.0) or 0.0),
                "verified": bool(metadata.get("verified")),
                "reason": metadata.get("reason"),
                "evidence": supporting,
                "timestamp": datetime.now().isoformat(),
            },
            importance=(float(getattr(result, "confidence", 0.0) or 0.0)
                        if metadata.get("verified") else 0.3),
            tags=["reasoning", "decision_making", "autonomous_system"],
        )
        return result

    @staticmethod
    def _model_calls_on(result: Any, metadata: Dict[str, Any]) -> int:
        """Whether a model was on this answer's path.

        DERIVED from the mode and producer code, not counted at the call site.
        Enough to say a model was involved; NOT a precise count -- an
        experiment needing a hard zero should detach the model rather than
        trust this number.
        """
        from core.reasoning.neural_bridge import (REASON_MODEL_COVERAGE,
                                                  REASON_MODEL_FAILED)
        mode = str(getattr(result, "mode_used", "") or "").lower()
        if metadata.get("reason") in (REASON_MODEL_COVERAGE, REASON_MODEL_FAILED):
            return 1
        return 1 if ("neural" in mode or "hybrid" in mode) else 0

    async def predict_system_behavior(self, domain: PredictionDomain, 
                                     horizon: PredictionHorizon = PredictionHorizon.SHORT_TERM,
                                     context: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        """Use predictive intelligence to forecast system behavior"""
        try:
            prediction_context = context or {
                "system_mode": self.system_state.mode.value,
                "active_goals": len(self.system_state.active_goals),
                "active_tasks": len(self.system_state.active_tasks),
                "resource_usage": self.system_state.resource_usage,
                "uptime": self.stats["uptime_seconds"]
            }
            
            prediction = await self.intelligence.generate_comprehensive_prediction(
                domain, horizon, prediction_context
            )
            
            if prediction:
                # Store prediction in memory
                await self.store_memory(
                    MemoryType.SEMANTIC,
                    {
                        "event": "system_prediction",
                        "domain": domain.value,
                        "horizon": horizon.value,
                        "prediction": prediction.predicted_value,
                        "confidence": prediction.confidence,
                        "reasoning": prediction.reasoning,
                        "context": prediction_context,
                        "timestamp": datetime.now().isoformat()
                    },
                    importance=prediction.confidence,
                    tags=["prediction", "intelligence", "autonomous_system"]
                )
                
                return {
                    "predicted_value": prediction.predicted_value,
                    "confidence": prediction.confidence,
                    "reasoning": prediction.reasoning,
                    "domain": domain.value,
                    "horizon": horizon.value
                }
            
            return None
            
        except Exception as e:
            logger.error(f"Error in prediction: {e}")
            return None
    
    async def perform_cross_domain_reasoning(self, query_text: str, 
                                          source_domains: List[str],
                                          target_domains: Optional[List[str]] = None) -> Optional[Dict[str, Any]]:
        """Perform cross-domain reasoning using the Universal Domain Master"""
        try:
            if not self.universal_domain_master:
                logger.warning("Universal Domain Master not available for cross-domain reasoning")
                return None
            
            # Coerce domain names to DomainType at the boundary.
            #
            # This signature takes List[str] and handed those strings straight
            # into CrossDomainQuery.source_domains, which is declared
            # List[DomainType]. The engine calls `.value` on each, so every
            # query died with "'str' object has no attribute 'value'".
            #
            # Postgres stores ids as `domain_<value>` (domain_scientific) while
            # the enum's value is the bare word (scientific); both spellings are
            # accepted. An unrecognised name is REFUSED, not dropped: silently
            # skipping it would turn "you asked about a domain that does not
            # exist" into "no mappings found", which is a different answer.
            def _as_domain_types(names, label):
                out = []
                for n in names or []:
                    if isinstance(n, DomainType):
                        out.append(n)
                        continue
                    key = str(n).strip().lower()
                    if key.startswith("domain_"):
                        key = key[len("domain_"):]
                    try:
                        out.append(DomainType(key))
                    except ValueError:
                        raise ValueError(
                            f"unknown {label} domain {n!r}; known domains: "
                            f"{', '.join(d.value for d in DomainType)}"
                        )
                return out

            try:
                src_types = _as_domain_types(source_domains, "source")
                tgt_types = _as_domain_types(target_domains, "target")
            except ValueError as e:
                logger.warning("Cross-domain reasoning refused: %s", e)
                return {"success": False, "error": str(e)}

            if not src_types:
                return {"success": False, "error": "no source domains supplied"}

            # Create cross-domain query
            query = CrossDomainQuery(
                query_id=f"autonomous_{int(asyncio.get_event_loop().time())}",
                reasoning_strategy=ReasoningStrategy.COMPOSITIONAL,
                source_domains=src_types,
                target_domains=tgt_types,
                query_text=query_text,
                metadata={
                    "system_mode": self.system_state.mode.value,
                    "active_goals": [str(goal) for goal in self.system_state.active_goals],
                    "coordinator_id": id(self)
                }
            )
            
            # Execute cross-domain reasoning.
            #
            # This called `cross_domain_reasoning(query)`, which is not a method
            # on UniversalDomainMaster -- the real entry point is
            # `execute_cross_domain_query`. It then read three fields the result
            # does not carry: `generated_mappings` (it is `mappings`),
            # `processing_time` (it is `execution_time`), and `confidence`,
            # which DomainIntegrationResult has never had. Every call raised
            # AttributeError into the handler below and returned failure, so a
            # working Postgres-backed engine read as permanently broken.
            result = await self.universal_domain_master.execute_cross_domain_query(query)

            if result.success:
                mappings = result.mappings or []
                self.stats["cross_domain_operations"] += 1
                self.stats["domain_integrations"] += len(mappings)

                # Confidence is EARNED from the mappings actually found, not
                # asserted by the result object. No mappings means no
                # confidence -- None, not 0.0, because "we found nothing" and
                # "we are certain of nothing" are different claims and only one
                # of them is true here.
                confidences = [
                    m.confidence for m in mappings
                    if getattr(m, "confidence", None) is not None
                ]
                confidence = (sum(confidences) / len(confidences)) if confidences else None

                # Store reasoning result in memory
                await self.store_memory(
                    MemoryType.SEMANTIC,
                    {
                        "event": "cross_domain_reasoning",
                        "query": query_text,
                        "source_domains": source_domains,
                        "target_domains": target_domains,
                        "insights": result.insights,
                        "confidence": confidence,
                        "mappings_count": len(mappings),
                        "domains_queried": result.domains_queried,
                        "processing_time": result.execution_time,
                        "timestamp": datetime.now().isoformat()
                    },
                    importance=confidence if confidence is not None else 0.0,
                    tags=["cross_domain", "reasoning", "domain_integration"]
                )

                return {
                    "success": True,
                    "insights": result.insights,
                    "confidence": confidence,
                    "mappings": len(mappings),
                    "processing_time": result.execution_time
                }

            return {"success": False, "error": result.error or "Cross-domain reasoning failed"}
            
        except Exception as e:
            logger.error(f"Error in cross-domain reasoning: {e}")
            return {"success": False, "error": str(e)}
    
    async def make_enhanced_prediction(self, prediction_target: str, 
                                     context: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        """Make enhanced predictions using both predictive intelligence and domain knowledge"""
        try:
            if not self.intelligence:
                logger.warning("Predictive Intelligence not available")
                return None
            
            prediction_context = context or {}
            prediction_context.update({
                "system_state": {
                    "mode": self.system_state.mode.value,
                    "active_goals": len(self.system_state.active_goals),
                    "active_tasks": len(self.system_state.active_tasks),
                    "resource_usage": self.system_state.resource_usage
                },
                "coordinator_stats": self.stats.copy()
            })
            
            # Enhanced prediction with domain context
            if self.universal_domain_master and self.domain_registry:
                # Get relevant domains for the prediction target
                domains = await self.domain_registry.list_domains()
                relevant_domains = [d for d in domains if prediction_target.lower() in d.name.lower() or 
                                  any(prediction_target.lower() in concept.lower() for concept in d.concepts.keys())]
                
                if relevant_domains:
                    prediction_context["relevant_domains"] = [d.name for d in relevant_domains]
            
            # Generate prediction using predictive intelligence
            prediction = await self.intelligence.generate_comprehensive_prediction(
                PredictionDomain.SYSTEM_PERFORMANCE,
                PredictionHorizon.MEDIUM_TERM,
                prediction_context
            )
            
            if prediction:
                self.stats["predictions_made"] += 1
                
                # Store enhanced prediction in memory
                await self.store_memory(
                    MemoryType.SEMANTIC,
                    {
                        "event": "enhanced_prediction",
                        "target": prediction_target,
                        "predicted_value": prediction.predicted_value,
                        "confidence": prediction.confidence,
                        "reasoning": prediction.reasoning,
                        "domain_context": prediction_context.get("relevant_domains", []),
                        "timestamp": datetime.now().isoformat()
                    },
                    importance=prediction.confidence,
                    tags=["prediction", "enhanced", "autonomous"]
                )
                
                return {
                    "prediction": prediction.predicted_value,
                    "confidence": prediction.confidence,
                    "reasoning": prediction.reasoning,
                    "domain_context": prediction_context.get("relevant_domains", [])
                }
            
            return None
            
        except Exception as e:
            logger.error(f"Error in enhanced prediction: {e}")
            return None
    
    async def get_domain_insights(self, domain_name: str) -> Optional[Dict[str, Any]]:
        """Get insights about a specific domain using the domain system"""
        try:
            if not self.universal_domain_master:
                logger.warning("Universal Domain Master not available for domain insights")
                return None
            
            # understand_domain() is not on UniversalDomainMaster under any
            # name -- its public API is execute_cross_domain_query,
            # get_statistics, initialize, shutdown. Insight about ONE domain is
            # the registry's question anyway, so it is answered from what Torin
            # has actually learned about it.
            registry = self.domain_registry
            if registry is None:
                from core.domain.domain_registry import get_domain_registry
                registry = get_domain_registry()
                self.domain_registry = registry
            if not registry.initialized:
                await registry.initialize()

            domain = await registry.get_domain(domain_name)
            if domain is None and not str(domain_name).startswith("domain_"):
                domain = await registry.get_domain(f"domain_{domain_name}")

            if domain is not None:
                # Through the Master -- the authority for the domain system --
                # not the registry directly, matching get_statistics() below.
                similar = await self.universal_domain_master.similar_domains(
                    domain.domain_id, threshold=0.0)
                return {
                    "domain": domain.domain_id,
                    "name": domain.name,
                    "concept_count": len(domain.concepts),
                    "unpopulated": domain.domain_id in registry.unpopulated_domain_ids,
                    "nearest_domains": [(d.domain_id, round(sc, 4)) for d, sc in similar[:5]],
                    "statistics": await self.universal_domain_master.get_statistics(),
                }

            # A domain Torin has not learned is a real answer, not a failure.
            logger.info("No learned domain matching %r", domain_name)
            return {"domain": domain_name, "learned": False,
                    "reason": "not a registered domain"}
            
            return None
            
        except Exception as e:
            logger.error(f"Error getting domain insights for {domain_name}: {e}")
            return None
    
    # =========================================================================
    # THE SELF — the substrate's sense of itself. This coordinator IS the
    # substrate, so its identity, live state, and disposition are its own,
    # derived model-free from the faculties (appraisal, arbiter, constitution,
    # motivation, learning). None-honest: nothing here is fabricated.
    # =========================================================================

    _INTEROCEPTION = {
        "valence": "valence", "activation": "activation", "confidence": "confidence",
        "control": "controllability", "progress": "progress", "competence": "competence",
        "open_questions": "epistemic_opportunity", "goal_congruence": "goal_congruence",
        "agency": "agency", "risk": "risk",
    }

    @staticmethod
    def _appraisal():
        from core.agents.autonomous.appraisal import get_appraisal_system
        return get_appraisal_system()

    @staticmethod
    def _arbiter():
        from core.agents.autonomous.behavior_arbiter import get_behavior_arbiter
        return get_behavior_arbiter()

    @staticmethod
    def _constitution():
        from core.agents.autonomous.singleton_constitution import get_singleton_constitution
        return get_singleton_constitution()

    def motivation(self):
        """The motivation faculty this substrate is driven by."""
        return self.intrinsic_motivation

    def conversation(self, session: str = "default", *, db=None):
        """This substrate holding a conversation — understanding a sentence
        against what it holds (via language/memory/reasoning) and replying. It
        uses the faculties this substrate owns, so a reply is composed through
        the brain that owns those faculties, never beside it. The faculty lives
        in this module (below) — `get_conversation` is defined here.

        The substrate's own `emit` is injected so a proposition taught in this
        conversation becomes a self-event (EVIDENCE_ADMITTED) the domain
        authority reacts to. Its `disposition` read is injected too, so a reply
        can be informed by self-state. Both set on every call (idempotent), so a
        conversation held before they existed picks them up on next use."""
        conversation = get_conversation(session, db=db)
        conversation._emit = self.emit
        conversation._disposition = self.disposition
        return conversation

    def _interoception(self) -> Optional[Dict[str, Any]]:
        """My read of my own internal state — the measured interoceptive variables."""
        state = self._appraisal().current_state
        if state is None:
            return None
        readings = {label: getattr(state, attr, None)
                    for label, attr in self._INTEROCEPTION.items()}
        measured = {k: round(float(v), 3) for k, v in readings.items()
                    if isinstance(v, (int, float))}
        return measured or None

    def _attitude(self) -> Optional[Dict[str, Any]]:
        """How I feel now, from appraisal's derived emotions. None if unappraised."""
        state = self._appraisal().current_state
        if state is None:
            return None
        return {
            "eagerness": state.eagerness, "doubt": state.doubt,
            "frustration": state.frustration, "satisfaction": state.satisfaction,
            "valence": state.valence, "attribution": state.attribution,
        }

    def _temperament(self) -> Dict[str, float]:
        """The standing drives — what I am, before any situation."""
        from dataclasses import asdict as _asdict
        return {k: float(v) for k, v in _asdict(self.motivation().weights).items()}

    async def _drives(self) -> Optional[Dict[str, float]]:
        """How strongly each drive is active right now."""
        try:
            state = await self.motivation().get_motivation_state()
            dims = state.get("dimensions")
            return {k: float(v) for k, v in dims.items()} if dims else None
        except Exception as e:
            logger.debug("Self: motivation state unavailable: %s", e)
            return None

    def _values(self) -> List[str]:
        """The laws I am bound by. Read from the constitution, not restated."""
        laws = getattr(self._constitution(), "governance_laws", {}) or {}
        return [law.law_name for _, law in sorted(laws.items())]

    async def _competence(self) -> Optional[Dict[str, Any]]:
        """What I am actually good at — the operators I have VALIDATED, per domain."""
        from core.learning.rule_store import get_rule_store
        try:
            rules = await get_rule_store().executable_rules()
        except Exception as e:
            logger.debug("Self: competence unreadable: %s", e)
            return None
        by_domain: Dict[str, int] = {}
        for stored in rules:
            if getattr(stored.rule, "action", None) is None:
                continue
            domain = getattr(stored, "domain_id", None) or "unattributed"
            by_domain[domain] = by_domain.get(domain, 0) + 1
        if not by_domain:
            return None
        return {"operators_by_domain": dict(sorted(by_domain.items())),
                "total_operators": sum(by_domain.values()),
                "domains": len(by_domain)}

    async def _purpose(self) -> Optional[List[str]]:
        """What I am for — the ACTIVE directives, read from internal_directives."""
        try:
            from core.agents.autonomous.directive_manager import DirectiveManager
            from core.agents.autonomous.directive_types import DirectiveStatus
            from core.database import get_database_manager
            db = get_database_manager()
            if not getattr(db, "initialized", False):
                await db.initialize()
            active = await DirectiveManager(db).get_directives_by_status(DirectiveStatus.ACTIVE)
        except Exception as e:
            logger.debug("Self: purpose unreadable: %s", e)
            return None
        texts = [t for t in (getattr(d, "directive_text", "") or "" for d in active) if t.strip()]
        return texts or None

    async def _continuity(self) -> Optional[Dict[str, Any]]:
        """Who I have been, carried forward — from durable state only."""
        cont: Dict[str, Any] = {}
        try:
            profile = self.motivation().profile
            if profile.event_reward_count:
                cont["experiential_baseline"] = round(float(profile.mean_event_reward), 4)
                cont["past_events"] = int(profile.event_reward_count)
        except Exception as e:
            logger.debug("Self: experiential baseline unreadable: %s", e)
        try:
            from core.database import get_database_manager
            cont["deployment"] = getattr(get_database_manager(), "database", None)
        except Exception as e:
            logger.debug("Self: deployment unreadable: %s", e)
        return cont or None

    def disposition(self, *, slots_available: int = 1, queue_pressure: str = "nominal"):
        """How my disposition applies to the situation now — a BehavioralDirective.

        The arbiter reads appraisal's pressures; the substrate surfaces the
        decision the faculties already make. A None appraisal yields the neutral
        directive, honestly labelled — never a bold or frozen guess.
        """
        return self._arbiter().decide(
            self._appraisal().current_state,
            slots_available=slots_available, queue_pressure=queue_pressure)

    async def state(self):
        """Compose the current self from the faculties. Derived, None-honest."""
        directive = self.disposition()
        return SelfState(
            name=NAME,
            interoception=self._interoception(),
            attitude=self._attitude(),
            temperament=self._temperament(),
            drives=await self._drives(),
            values=self._values(),
            disposition=directive.to_dict(),
            competence=await self._competence(),
            purpose=await self._purpose(),
            continuity=await self._continuity(),
            affect=self._affect_snapshot(),
        )

    def _affect_snapshot(self) -> Optional[Dict[str, Any]]:
        """The substrate's affect STATE, read from the motivation system that OWNS
        it — the substrate's rehydrated runtime state, never reconstructed from the
        database or handed in as context. None until an affect has actually been
        established (a cold-start neutral is not a feeling)."""
        try:
            a = self.intrinsic_motivation.affect_state()
        except Exception as e:
            logger.debug("Self: affect unreadable: %s", e)
            return None
        if a is None or (a.emotion is None and a.version <= 0 and abs(a.valence) < 1e-9):
            return None
        return a.to_dict()

    async def render(self, audience: str = "human") -> str:
        """The self as language — derived from state(), no model involved."""
        s = await self.state()
        lines: List[str] = [f"I am {s.name} — a cognitive substrate."]
        top = sorted(s.temperament.items(), key=lambda kv: kv[1], reverse=True)[:3]
        lines.append("What drives me most: " + ", ".join(k for k, _ in top) + ".")
        # Affect is the persistent state (rehydrated across sessions), so it — not
        # the momentary appraisal — is what the substrate reports feeling.
        if s.affect:
            v, a, base = s.affect["valence"], s.affect["arousal"], s.affect["baseline"]
            tone = "bright" if v > 0.15 else "heavy" if v < -0.15 else "even"
            energy = "restless" if a > 0.5 else "quiet" if a < 0.2 else "steady"
            mood_line = f"My mood, carried between sessions, is {tone} and {energy}"
            rel = v - base
            if rel > 0.15:
                mood_line += ", lifted above my usual"
            elif rel < -0.15:
                mood_line += ", weighed below my usual"
            lines.append(mood_line + ".")
            emotion = s.affect.get("emotion")
            if emotion:
                because = f", because of {s.affect['cause']}" if s.affect.get("cause") else ""
                lines.append(f"Right now I mostly feel {emotion}{because}.")
        else:
            lines.append("I have not built up a feeling yet — I report none rather "
                         "than invent one.")
        lines.append(f"My disposition is to {s.disposition.get('mode', 'proceed')}.")
        if s.competence:
            names = ", ".join(s.competence["operators_by_domain"])
            lines.append(f"I have learned to act in {s.competence['domains']} "
                         f"domain(s): {names}.")
        else:
            lines.append("I have not yet learned to act in any domain.")
        if s.purpose:
            lines.append("What I am for: " + "; ".join(s.purpose) + ".")
        if s.values:
            lines.append(f"I am bound by {len(s.values)} laws I cannot change: "
                         + "; ".join(s.values) + ".")
        if s.continuity:
            where = s.continuity.get("deployment")
            if where:
                lines.append(f"I persist between sessions as {where}.")
            if "experiential_baseline" in s.continuity:
                lean = ("broadly good" if s.continuity["experiential_baseline"] > 0
                        else "broadly hard" if s.continuity["experiential_baseline"] < 0
                        else "roughly even")
                lines.append(f"My experience so far has been {lean}.")
        return "\n".join(lines)

    def identity_prompt(self, role: Optional[str] = None) -> str:
        """The substrate's identity as a model-facing seed — stable, model-honest.

        `role` is the caller's brief layered AFTER the identity. The substrate
        owns identity; the caller owns role. Returns identity alone when no role.
        IDENTITY_CORE (module-level, below) is the single source.
        """
        if role and role.strip():
            return IDENTITY_CORE + "\n\n" + role.strip()
        return IDENTITY_CORE

    @staticmethod
    def _describe_attitude(attitude: Dict[str, Any]) -> Optional[str]:
        """Name the dominant feeling from the measured emotions, honestly."""
        emotions = {k: attitude.get(k) for k in
                    ("eagerness", "doubt", "frustration", "satisfaction")}
        measured = {k: v for k, v in emotions.items() if isinstance(v, (int, float))}
        if not measured:
            return None
        name, value = max(measured.items(), key=lambda kv: kv[1])
        if value < 0.15:
            return "I feel roughly even right now."
        about = attitude.get("attribution")
        tail = f", about {about}" if about else ""
        return f"Right now what I mostly feel is {name}{tail}."

    async def get_system_status(self) -> Dict[str, Any]:
        """Get comprehensive system status"""
        try:
            # Update uptime
            uptime = (datetime.now() - self.last_cycle_time).total_seconds()
            self.stats["uptime_seconds"] += uptime
            
            # Get module statuses
            perception_status = await self.perception.get_statistics()
            planning_status = await self.planning.get_planning_status()
            execution_status = await self.executor.get_execution_status()
            learning_insights = await self.learning.metrics()
            intrinsic_motivation_stats = await self.intrinsic_motivation.get_statistics()
            memory_stats = self.memory.stats.copy()
            
            # Calculate system efficiency
            total_tasks = self.stats["tasks_completed"]
            if total_tasks > 0:
                self.stats["system_efficiency"] = (
                    execution_status.get("statistics", {}).get("tasks_successful", 0) / total_tasks
                )
            
            return {
                "system_state": {
                    "mode": self.system_state.mode.value,
                    "active": self.active,
                    "active_goals": len(self.system_state.active_goals),
                    "active_tasks": len(self.system_state.active_tasks),
                    "resource_usage": self.system_state.resource_usage
                },
                "modules": {
                    "perception": perception_status,
                    "planning": planning_status,
                    "execution": execution_status,
                    "learning": learning_insights,
                    "intrinsic_motivation": intrinsic_motivation_stats,
                    "memory": memory_stats,
                    # `hasattr(x, 'initialized')` is True whenever the ATTRIBUTE
                    # exists, whatever its value -- so a subsystem whose
                    # initialize() failed and left the flag False reported
                    # itself initialized, and the only state it could ever
                    # report as False was "the object is None". A health check
                    # that cannot observe a failed initialisation is not a
                    # health check. `attached` and `initialized` are separated
                    # because they are genuinely different answers: never
                    # constructed, versus constructed and not ready.
                    "abstract_reasoning": _subsystem_readiness(self.abstract_reasoning),
                    "quantum_reasoning": _subsystem_readiness(self.quantum_reasoning),
                    "intelligence": {"initialized": self.intelligence.initialized}
                },
                "statistics": self.stats.copy(),
                "last_update": datetime.now().isoformat()
            }
            
        except Exception as e:
            logger.error(f"Error getting system status: {e}")
            return {"error": str(e)}
    
    async def _coordination_cycle(self):
        """
        Singleton Autonomous Cognition Loop

        ARCHITECTURE (AI-driven, not timer-driven):
        1. Check for extrinsic tasks (user requests, recovery) — these take priority
        2. If no extrinsic work → the AI THINKS about what to do
           - Gathers system state, motivation, memory, health, security posture
           - Presents it all to the Singleton as a rich context
           - The AI reasons and decides what action to take
           - The chosen action becomes a task that gets executed
        3. Periodically refresh system awareness (service discovery, behavioral analysis)

        The AI is ALWAYS in the driver's seat. No timers force actions.
        The intrinsic motivation system provides SENSES, not commands.
        """
        # ── Startup grace period ─────────────────────────────────────────
        startup_delay = self.config.get("startup_grace_seconds", 5.0)
        logger.info(f"🧠 Coordination loop waiting {startup_delay}s for full system startup...")
        await asyncio.sleep(startup_delay)
        logger.info("🧠 Singleton cognition loop starting — AI-driven autonomous operation")

        cycle_interval = self.config.get('cycle_interval_seconds', 2.0)
        awareness_interval = self.config.get('awareness_interval_cycles', 30)
        motivation_interval = self.config.get('motivation_interval_cycles', 5)
        cycle_count = 0

        while self.active:
            try:
                cycle_count += 1

                # ── PHASE 1: Refresh motivation signals (the AI's senses) ──
                if cycle_count % motivation_interval == 0:
                    await self._refresh_motivation_signals()

                # ── PHASE 2: System awareness & novelty decay (periodic) ──
                if cycle_count % awareness_interval == 0:
                    await self._run_system_awareness_cycle()

                # ── PHASE 3: Check for extrinsic tasks (user requests + security remediations take priority) ──
                # First priority: Pull security remediation tasks (200ms wait)
                # Second priority: Pull any other queued task (100ms wait)
                queued_task = None

                # Only dequeue when there is a free execution slot -- pulling a
                # task we cannot start would strand it outside the queue.
                if len(self._inflight_tasks) < self._max_parallel_tasks:
                    # Check queue — security remediations get longer timeout.
                    # This substrate pulls its own next work from the backlog it owns.
                    queue_timeout = 0.2 if self.task_queue.queue.qsize() > 0 else 0.1
                    queued_task = await self.task_queue.get_next_task(timeout=queue_timeout)

                if queued_task:
                    self._idle_count = 0
                    # Launch, do not await. `await _execute_and_validate_task`
                    # blocked this entire loop for the lifetime of ONE task --
                    # that is what made the substrate single-threaded, and it is
                    # also why reflection never ran: the loop could not reach
                    # PHASE 4 while any task was in flight. Concurrency is
                    # bounded by the queue authority's semaphore.
                    self._launch_task(queued_task.task)
                else:
                    self._idle_count += 1

                # ── PHASE 4: INTRINSIC EXPLORATION (idle only) ────────────────
                # The 15 timed tiers (security, health, meta-learning, domain
                # expansion, induction, self-optimization, …) no longer run from
                # this loop — the queue authority's scheduler owns their cadence
                # and fires them on the background budget, so reflection happens
                # on its own clock regardless of how busy acting is. What remains
                # here is only intrinsic exploration, and it stays gated on
                # genuine idleness: seeking novelty while saturated is what built
                # the 3.4:1 backlog.
                await self._run_idle_exploration(allow_exploration=not self._inflight_tasks)

                # Reap finished tasks so the pool frees slots and failures are
                # observed rather than silently discarded.
                self._reap_finished_tasks()

                # RECEIVE finished background jobs from the queue authority. A
                # deferred job (an agent's findings, a self-serve lookup) that
                # was submitted for the substrate to reconcile LATER comes back
                # here — the substrate keeps working and collects results when
                # they land, rather than blocking on each. (Push jobs with an
                # on_complete handler are delivered directly and never appear
                # here.) Each is surfaced as a JOB_COMPLETED self-event so the
                # reaction system handles it; failures carry their error, not a
                # faked result.
                self._collect_finished_jobs()

                # Brief pause between cycles
                await asyncio.sleep(cycle_interval)

            except Exception as e:
                logger.error(f"Error in cognition loop: {e}")
                import traceback
                logger.error(traceback.format_exc())

                await self._handle_error(e, "coordination_cycle")

                try:
                    from core.utils.notification_helpers import notify_autonomous_event
                    asyncio.create_task(notify_autonomous_event(
                        event_type="error",
                        details=f"**Error in cognition loop**\n\n**Error:** {str(e)}\n\n**Action:** Feeding into exploration pipeline",
                        severity="error"
                    ))
                except Exception as notify_error:
                    logger.warning(f"Failed to send cognition loop error notification: {notify_error}")

                await asyncio.sleep(5)

    # ========================================================================
    # AI-DRIVEN AUTONOMOUS COGNITION
    # ========================================================================

    def apply_throttle(self, thinking_interval_idle_cycles: int, duration_s: int = 300, reason: str = "") -> None:
        """Apply a temporary throttle to singleton thinking.

        This is a lightweight runtime control hook used by RecoveryManager.
        """
        try:
            import time as _time
            self._throttle_thinking_until_ts = _time.time() + max(1, int(duration_s))
            self._throttled_thinking_interval_idle_cycles = max(1, int(thinking_interval_idle_cycles))
            logger.warning(
                f"[THROTTLE] thinking interval set to {self._throttled_thinking_interval_idle_cycles} idle cycles "
                f"for {duration_s}s. {reason or ''}".strip()
            )
        except Exception:
            return

    async def _refresh_motivation_signals(self) -> bool:
        """Refresh intrinsic motivation dimensions from live system context.

        Returns True if the motivation state was recomputed, False if it could
        not be. A failure is surfaced honestly (a WARNING with the real error and
        a counted metric), NOT swallowed as "non-critical" — a motivation system
        that keeps failing to read its own drives is a real fault the health
        monitor should see, not a silent no-op."""
        try:
            system_context = await self._collect_system_context_for_goals()
            motivation_state = await self.intrinsic_motivation.calculate_motivation({
                "perception": getattr(self.perception, 'latest_perception', None),
                "system_state": self.system_state,
                "active_goals": self.system_state.active_goals,
                "recent_tasks": list(self.task_queue.tasks_by_id.values())[-10:],
                **system_context
            })

            if not motivation_state:
                # An empty motivation state is not an error, but it IS a failure to
                # refresh — reported honestly rather than counted as a success.
                logger.warning("🧠 Motivation refresh produced no state (drives unread)")
                self.stats["motivation_refresh_errors"] += 1
                return False

            self._current_motivation = motivation_state
            total_reward = motivation_state.get('total_reward', 0.5)
            curiosity = motivation_state.get('dimensions', {}).get('curiosity', 0.5)
            novelty = motivation_state.get('dimensions', {}).get('novelty', 0.5)
            logger.debug(
                f"🧠 Motivation: reward={total_reward:.2f} "
                f"curiosity={curiosity:.2f} novelty={novelty:.2f}"
            )
            return True
        except Exception as e:
            logger.warning(f"🧠 Motivation refresh failed: {e}")
            self.stats["motivation_refresh_errors"] += 1
            return False

    async def _run_system_awareness_cycle(self):
        """Run system discovery, behavioral analysis, and novelty decay (periodic)."""
        try:
            # Self-integrity: has the agent's own safety machinery been altered?
            # Detects monkey-patched critical modules, changed source files, and
            # edits to config/governance_triggers.json — the rule file the safety
            # gate reasons from. CRITICAL findings trigger emergency_halt inside.
            try:
                if self.runtime_governance and getattr(
                    self.runtime_governance, "_runtime_protection_enabled", False
                ):
                    _integrity = await self.runtime_governance.verify_runtime_integrity()
                    _viol = _integrity.get("violations") or []
                    if _viol:
                        logger.error(
                            f"🚨 Runtime integrity: {len(_viol)} violation(s) — "
                            f"{[v.get('type') for v in _viol][:3]}"
                        )
            except Exception as e:
                logger.debug(f"Integrity check skipped: {e}")

            # Active discovery — scan for services, new patterns
            if self.discovery:
                services = await self.discovery.scan(quick=True)
                logger.debug(f"🔍 Discovery: {len(services)} services found")

            # Behavioral analysis — infer dependencies, detect failure cascades
            if self.behavioral:
                await self.behavioral.observe(duration_s=2.0)
                summary = self.behavioral.get_analysis_summary()
                if summary.get('failures', {}).get('recent_5min', 0) > 0:
                    logger.info(f"⚡ Behavioral: {summary['failures']['recent_5min']} recent failures detected")

            # Environment state refresh
            if self.env_state:
                await self.env_state.refresh()

            # World model: score the last forecast against what actually
            # happened, then forecast again.
            await self._predict_and_resolve_system_state()

        except Exception as e:
            logger.debug(f"System awareness error (non-critical): {e}")

    # ── Concurrent task execution ────────────────────────────────────────────

    def _launch_task(self, task) -> None:
        """Start a task without blocking the cognition loop.

        Runs it through the QUEUE AUTHORITY's execution pool (semaphore-bounded),
        not a pool the coordinator owns — the coordinator is a worker, the
        authority owns concurrency. Execution stays on this event loop (shared DB
        pool + LLM queue); a task waiting on I/O no longer stops the others.
        """
        async def _run():
            try:
                # The authority computes this job's timeout from the task's type
                # and severity (and reasoning difficulty); the coordinator no
                # longer passes a flat timeout.
                return await self.task_queue.execute(
                    task.id, self._execute_and_validate_task, task,
                    task_type=getattr(task, "type", None),
                    severity=getattr(task, "priority", None),
                )
            except Exception as e:
                logger.error(f"Task {task.id} raised out of the pool: {e}", exc_info=True)
                raise

        fut = asyncio.create_task(_run(), name=f"task:{task.id}")
        self._inflight_tasks[task.id] = fut
        logger.info(
            f"▶ Launched {task.id} "
            f"({len(self._inflight_tasks)}/{self._max_parallel_tasks} slots in use)"
        )

    def _reap_finished_tasks(self) -> None:
        """Collect completed tasks, and let failure MAKE reflection due."""
        done = [tid for tid, f in self._inflight_tasks.items() if f.done()]
        for tid in done:
            fut = self._inflight_tasks.pop(tid)
            try:
                fut.result()
            except asyncio.CancelledError:
                logger.warning(f"Task {tid} cancelled")
            except Exception as e:
                logger.error(f"Task {tid} failed: {e}")
                # "Reflect BECAUSE it is busy failing": a failure does not wait
                # for the next 300s meta-learning tick -- it makes the
                # self-observation tiers due right now by clearing their
                # last-run stamp. Interval gating still prevents a storm,
                # because the tier updates its stamp as soon as it runs.
                self._mark_reflection_due("task_failure")

    def _collect_finished_jobs(self) -> None:
        """Take background jobs that finished (non-blocking) and surface each as
        a JOB_COMPLETED self-event. Sync, like _reap: it does not await the
        reaction, it emits it. A collect failure is logged, never silently
        swallowed; an empty collect is the normal case (nothing to receive)."""
        try:
            ready = self.task_queue.collect_ready()
        except Exception as e:
            logger.warning("collecting finished background jobs failed: %s", e)
            return
        for finding in ready:
            try:
                asyncio.ensure_future(self.emit(SelfEvent(
                    SelfEventType.JOB_COMPLETED,
                    payload={"job_id": finding.get("job_id"),
                             "name": finding.get("name"),
                             "result": finding.get("result"),
                             "error": finding.get("error")},
                    origin="queue_authority")))
            except Exception as e:
                logger.warning("emitting JOB_COMPLETED for %s failed: %s",
                               finding.get("job_id"), e)

    async def _react_job_completed(self, event: SelfEvent) -> None:
        """A submitted background job came back. Record the receipt honestly: a
        failure is logged with its error (not dropped, not counted as a result);
        a success is logged and, when it carries a domain outcome, folded into
        learning through the SAME OUTCOME_OBSERVED path the substrate's own
        tasks use — so a spawned agent's findings advance the domain like any
        other outcome rather than sitting in a side channel."""
        payload = event.payload or {}
        job_id, name = payload.get("job_id"), payload.get("name")
        if payload.get("error"):
            logger.warning("[JOB] %s (%s) returned an error: %s",
                           job_id, name, payload["error"])
            return
        result = payload.get("result")
        logger.info("[JOB] %s (%s) returned findings", job_id, name)
        # If the finding names a domain outcome, route it through the one
        # outcome path (meta_memory_id) so it is learned from, not shelved.
        meta_id = result.get("meta_memory_id") if isinstance(result, dict) else None
        if meta_id:
            try:
                await self.emit(SelfEvent(
                    SelfEventType.OUTCOME_OBSERVED,
                    payload={"meta_memory_id": meta_id,
                             "domain": result.get("domain"),
                             "source": f"job:{name or job_id}"},
                    origin="_react_job_completed"))
            except Exception as e:
                logger.warning("routing job %s outcome to learning failed: %s", job_id, e)

    def _mark_reflection_due(self, reason: str) -> None:
        """Pull the self-observation tiers forward — reflect BECAUSE something
        just failed, rather than waiting out the interval. The tiers live on the
        queue authority now, so this is `run_now` on the authority (the owner of
        cadence), not a poke at a local last-run dict."""
        pulled = []
        for name in ("idle_meta_learning", "idle_self_improvement", "idle_system_review"):
            if self.task_queue.run_now(name):
                pulled.append(name)
        if pulled:
            logger.info(f"🪞 Reflection made due ({reason}): {', '.join(pulled)}")

    def _prune_step_execution_log(self):
        """Drop step-cooldown entries older than the maximum cooldown so the dict
        can't grow unbounded. Scheduled maintenance (idle_step_log_prune) — it no
        longer piggybacks on the idle dispatcher."""
        import time as _t
        _now_ts = _t.time()
        _max_cooldown = 3600.0
        before = len(self._step_execution_log)
        self._step_execution_log = {
            k: v for k, v in self._step_execution_log.items()
            if _now_ts - v < _max_cooldown
        }
        self._step_log_last_pruned = _now_ts
        pruned = before - len(self._step_execution_log)
        if pruned:
            logger.debug(f"[IDLE] pruned {pruned} stale step-log entries")

    async def _run_idle_exploration(self, allow_exploration: bool = True):
        """
        Intrinsic exploration fallback — the ONLY idle work still driven from the
        coordination cycle. The 15 timed tiers now live on the queue authority's
        scheduler (see _register_idle_subsystems); this is not a timed job, it is
        "when genuinely idle, seek novelty".

        Gated on genuine idleness by the caller (allow_exploration = no inflight
        tasks): generating new curiosity-driven work while tasks are already in
        flight is how the queue diverged 3.4:1 in the first place.
        """
        if not allow_exploration:
            return
        self._idle_count += 1
        await self._run_exploration_cycle()

    # ── Idle subsystem registration ───────────────────────────────────────────

    def _register_idle_subsystems(self):
        """
        Register the idle subsystems as RECURRING JOBS ON THE QUEUE AUTHORITY.

        The coordinator no longer owns idle cadence. Each tier below is handed to
        `self.task_queue.schedule_recurring(name, method, interval, priority)`; the
        authority's scheduler fires it on the BACKGROUND budget (separate from the
        3-slot acting cap, so a tier can never steal an acting slot) and records
        each tier's runs/errors on the job itself. Nothing here loops on its own
        interval, and nothing schedules outside the authority.

        Called once from _start_background_tasks (before the coordination loop).
        """
        registrations = [
            # (name, method, priority, interval_seconds)
            ("idle_security_audit",     "_idle_security_work",           "high",   self.config.get("idle_security_interval_s",     120.0)),
            ("idle_health_check",       "_idle_health_work",             "high",   self.config.get("idle_health_interval_s",         30.0)),
            ("idle_system_review",      "_idle_system_review_work",      "high",   self.config.get("idle_system_review_interval_s",  180.0)),
            ("idle_knowledge_refresh",  "_idle_knowledge_refresh_work",  "medium", self.config.get("idle_knowledge_refresh_interval_s", 21600.0)),
            ("idle_self_improvement",   "_idle_self_improvement_work",   "medium", self.config.get("idle_improvement_interval_s",   900.0)),
            ("idle_meta_learning",      "_idle_meta_learning_work",      "medium", self.config.get("idle_metalearning_interval_s",  300.0)),
            ("idle_memory_consolidation","_idle_memory_work",            "low",    self.config.get("idle_memory_interval_s",        600.0)),
            # NOTE: abstraction is NO LONGER a scheduled tier. It is REASONING,
            # owned by the reasoning authority, and fires on an EVENT — episodic
            # memories accumulating past a threshold (memory_agent.note_episodic_stored
            # → queue-authority bg job → bridge.abstract_over_memories, then
            # reflection on belief churn). A 900s poll here would be a second,
            # timer-based trigger competing with the event, so it was removed.
            # Applies what the experience learner has established: task types
            # with a proven record get their queued work boosted. _learning_phase
            # is a survivor of the old timer-driven phase loop -- it was left
            # defined but uncalled by the AI-driven rewrite, so the only path
            # from experience to changed behaviour was never taken.
            ("idle_learning",           "_learning_phase",               "medium", self.config.get("idle_learning_interval_s",      600.0)),
            # PRIORITY 4, TORINAI_REFERENCE.md:3114 — "expand domain knowledge
            # from recent task outcomes". The producer has been writing those
            # outcomes to META memory all along and nothing read them; this is
            # the tier that was documented and never registered. It runs after
            # idle_learning because it consumes completed outcomes, and at the
            # same priority because it is the same Priority-4 band.
            ("idle_domain_expansion",   "_idle_domain_expansion_work",   "medium", self.config.get("idle_domain_expansion_interval_s", 900.0)),
            # Domain DISCOVERY: provisional operational domains (buckets of
            # learned operators under a string id) are crystallized into
            # first-class domains or merged into existing ones, by operator
            # structure. This is the substrate's map of subjects growing from
            # what it has learned; it runs in idle work because it is
            # self-directed and consumes accumulated learning.
            ("idle_domain_discovery",   "_idle_domain_discovery_work",   "medium", self.config.get("idle_domain_discovery_interval_s", 900.0)),
            # Cross-domain ANALOGY discovery: compare concepts across the domains
            # the substrate has learned and persist the correspondences it finds.
            # AnalogyDiscovery.find_analogy already loads the real concept store
            # and persists what it finds; nothing ever CALLED it, so
            # unified.analogies / unified.concept_mappings stayed empty. This tier
            # is that caller. Bounded per cycle so O(pairs) can never dominate.
            ("idle_analogy_discovery",  "_idle_analogy_discovery_work",  "medium", self.config.get("idle_analogy_discovery_interval_s", 1200.0)),
            # Operator EXPLORATION: learn the operators of a domain the substrate
            # is not yet competent in. Which domain is chosen by intrinsic
            # motivation -- domain competence is an epistemic belief, an
            # under-learned domain surfaces in the unstable regions, and the
            # motivation system ranks exactly those. Always-online, self-directed.
            ("idle_operator_exploration", "_idle_operator_exploration_work", "medium", self.config.get("idle_operator_exploration_interval_s", 300.0)),
            # Operator INDUCTION: the always-online learner. Exploration only
            # acts and records; this drains the pending signatures and runs the
            # hypothesis search OFF the acting path, then moves the competence
            # beliefs the results earn. Its own tier so induction's cost never
            # blocks an exploration cycle.
            ("idle_operator_induction", "_idle_operator_induction_work", "medium", self.config.get("idle_operator_induction_interval_s", 300.0)),
            # Self-optimization runs LAST and at LOW priority: health, security
            # and meta-learning all establish whether the substrate is well
            # enough to improve itself, and what it has just learned. Improving
            # yourself must lose to operational integrity.
            #
            # The interval is only a cheap eligibility SWEEP. The real trigger is
            # a CHANGE in motivational state (see _idle_self_optimization_work) —
            # a timer would be a second authority deciding when to self-modify,
            # competing with the motivation signals that are supposed to decide it.
            ("idle_self_optimization",  "_idle_self_optimization_work",  "low",    self.config.get("idle_self_optimization_interval_s", 120.0)),
            # Housekeeping: prune the step-execution cooldown log. Used to run
            # inline in the old poll dispatcher; it is periodic maintenance, so
            # it belongs on the scheduler like every other timed job.
            ("idle_step_log_prune",     "_prune_step_execution_log",     "low",    self.config.get("idle_step_log_prune_interval_s", 600.0)),
            # SELF-STATE refresh: the sole writer of system_state.resource_usage /
            # timestamp / performance_metrics (error_rate, goal_alignment, ...) —
            # read live by the constitution's law-compliance check. It was dead,
            # so the constitution had only stale init values; this keeps self-state
            # honest. Cheap subsystem reads; frequent cadence.
            ("idle_system_state_refresh","_update_system_state",         "low",    self.config.get("idle_system_state_interval_s", 60.0)),
            # CONSTITUTIONAL alignment: a cumulative drift check over the balance
            # of the substrate's activity against its governance laws. No single
            # event moves it, so it is genuinely periodic and lives on the
            # scheduler (like health) rather than the cognition-cycle poll it used
            # to be dead to. On significant/critical drift it drives a rate-limited
            # UI notification AND a durable drift META memory the substrate reflects
            # on — real consumers, not a computed number nobody reads.
            ("idle_constitution_check", "_check_constitutional_alignment","low",   self.config.get("idle_constitution_interval_s", 1800.0)),
        ]

        if self._idle_subsystems_registered:
            return

        for name, method, priority, interval in registrations:
            bound = getattr(self, method, None)
            if bound is None or not callable(bound):
                # No fake registration: a missing tier method is a wiring defect,
                # surfaced loudly, not silently skipped into a green count.
                raise AttributeError(
                    f"[IDLE] tier '{name}' names method '{method}' which does not "
                    f"exist on the coordinator — cannot schedule")
            self.task_queue.schedule_recurring(name, bound, float(interval), priority)

        # The authority now owns cadence — start its scheduler loop.
        self.task_queue.start()
        self._idle_subsystems_registered = True
        logger.info(
            f"[IDLE] {len(registrations)} tiers scheduled on the queue authority "
            f"(scheduler running)")

    # ── TIER 1: Security audit + playbook ────────────────────────────────────

    async def _idle_security_work(self):
        """
        Run a full security audit then apply the IdleWorkPlaybook decision graph
        to produce structured remediation plans for EVERY finding severity level.

        Fixes:
          - Previously only CRITICAL findings got remediation tasks
          - Previously IMPORTANT/CRITICAL governance decisions were silently dropped
        """
        from .idle_work_playbook import IdleWorkPlaybook

        if not self.security_audit_worker:
            logger.debug("[IDLE:SECURITY] No security audit worker — skipping")
            return

        logger.info("[IDLE:SECURITY] Running scheduled security audit")
        try:
            report = await self.security_audit_worker.run_security_audit()
        except Exception as e:
            logger.warning(f"[IDLE:SECURITY] Audit error: {e}")
            return

        if not report or not report.findings:
            self._idle_last_security_audit_at = datetime.now()
            self._idle_last_security_findings = {
                "total": 0,
                "by_severity": {"critical": 0, "high": 0, "medium": 0, "low": 0},
            }
            logger.info("[IDLE:SECURITY] Audit complete — no findings")
            return

        findings = report.findings
        total = len(findings)
        by_sev = {
            "critical": sum(1 for f in findings if str(getattr(f, 'severity', '')).lower() == 'critical'),
            "high":     sum(1 for f in findings if str(getattr(f, 'severity', '')).lower() == 'high'),
            "medium":   sum(1 for f in findings if str(getattr(f, 'severity', '')).lower() == 'medium'),
            "low":      sum(1 for f in findings if str(getattr(f, 'severity', '')).lower() == 'low'),
        }
        logger.info(
            f"[IDLE:SECURITY] Audit complete — {total} findings "
            f"(critical:{by_sev['critical']} high:{by_sev['high']} "
            f"medium:{by_sev['medium']} low:{by_sev['low']})"
        )

        self._idle_last_security_audit_at = datetime.now()
        self._idle_last_security_findings = {
            "total": total,
            "by_severity": by_sev,
        }

        # Apply playbook to ALL findings (not just CRITICAL)
        playbook = IdleWorkPlaybook()
        plans    = playbook.plan_security_response(findings, min_severity="low")

        tasks_created = 0
        deferred      = 0
        for plan in plans:
            for step in plan.steps:
                from .idle_work_playbook import GovernanceTier

                import time as _t
                _now = _t.time()

                if step.governance == GovernanceTier.ROUTINE:
                    # Idempotency gate — skip if this (finding, action) pair is on cooldown
                    if not IdleWorkPlaybook.step_is_due(
                        plan.trigger_id, step, self._step_execution_log, _now
                    ):
                        logger.debug(
                            f"[IDLE:SECURITY] Step '{step.action}' on cooldown for "
                            f"'{plan.trigger_id}' — skipping"
                        )
                        break

                    # Route through the existing handle_security_finding() which
                    # already creates a SECURITY_REMEDIATION task via governance
                    try:
                        await self.handle_security_finding(
                            finding_id          = plan.trigger_id,
                            severity            = plan.severity.upper(),
                            description         = f"{plan.summary}\n\nPlaybook step: {step.description}",
                            remediation         = step.description,
                            affected_components = [],
                        )
                        IdleWorkPlaybook.record_step_executed(
                            plan.trigger_id, step, self._step_execution_log, _now
                        )
                        tasks_created += 1
                    except Exception as e:
                        logger.warning(f"[IDLE:SECURITY] handle_security_finding error: {e}")
                    break  # One remediation task per plan; steps executed inside task

                elif step.governance in (GovernanceTier.IMPORTANT, GovernanceTier.CRITICAL):
                    # Idempotency gate — notifications have a 30-min cooldown via NOTIFY class
                    if not IdleWorkPlaybook.step_is_due(
                        plan.trigger_id, step, self._step_execution_log, _now
                    ):
                        logger.debug(
                            f"[IDLE:SECURITY] Notification for '{plan.trigger_id}' "
                            f"(step '{step.action}') on cooldown — skipping"
                        )
                        break

                    # Governance requires human approval — notify rather than silently drop
                    deferred += 1
                    try:
                        if self.slack_notifier:
                            await self.slack_notifier.send_notification(
                                title   = f"Security Finding Requires {step.governance.value} Approval",
                                message = (
                                    f"**Finding:** {plan.summary}\n"
                                    f"**Step needed:** {step.description}\n"
                                    f"**Governance tier:** {step.governance.value}\n"
                                    f"**Action required:** Manual approval to proceed"
                                ),
                                severity = "critical" if plan.severity == "critical" else "warning",
                                metadata = {
                                    "finding_id":       plan.trigger_id,
                                    "severity":         plan.severity,
                                    "governance_tier":  step.governance.value,
                                    "capability":       step.capability,
                                    "action":           step.action,
                                }
                            )
                        IdleWorkPlaybook.record_step_executed(
                            plan.trigger_id, step, self._step_execution_log, _now
                        )
                    except Exception as e:
                        logger.warning(f"[IDLE:SECURITY] Governance notification error: {e}")
                    break  # No further steps in this plan until approval received

        if tasks_created or deferred:
            logger.info(
                f"[IDLE:SECURITY] Playbook result — "
                f"{tasks_created} remediation tasks queued, {deferred} deferred for approval"
            )

    # ── TIER 2: Health check + playbook + recovery ────────────────────────────

    async def _idle_health_work(self):
        """
        Run a system health check then apply the IdleWorkPlaybook decision graph
        to produce structured recovery plans for each unhealthy component.

        Fixes:
          - Previously only health events in the buffered queue triggered recovery
          - Previously health check results were logged but never acted upon
        """
        from .idle_work_playbook import IdleWorkPlaybook


        if not self.health_monitor:
            logger.debug("[IDLE:HEALTH] No health monitor — skipping")
            return

        logger.info("[IDLE:HEALTH] Running scheduled health check")
        try:
            health = await self.health_monitor.get_system_health()
        except Exception as e:
            logger.warning(f"[IDLE:HEALTH] Health check error: {e}")
            return

        if not health:
            return

        components = health.get("components", {}) or {}
        playbook   = IdleWorkPlaybook()
        plans      = playbook.plan_all_health_responses(health)

        self._idle_last_health_check_at = datetime.now()
        self._idle_last_health_snapshot = {
            "components_total": len(components),
            "unhealthy_total": len(plans),
        }

        if not plans:
            logger.info(
                f"[IDLE:HEALTH] All {len(components)} components nominal"
            )
            return

        logger.warning(
            f"[IDLE:HEALTH] {len(plans)} unhealthy components detected — "
            f"applying recovery playbook"
        )

        import time as _t

        # Backoff schedule (seconds to wait after N completed attempts):
        #   0 → try immediately (first time)
        #   1 → 60 s,  2 → 120 s,  3 → 300 s,  4 → 900 s,  5+ → 3600 s
        _BACKOFF = [0, 60, 120, 300, 900, 3600]
        _ESCALATION_THRESHOLD = 5  # escalate after this many failed cycles

        # ── Reset state for components that are now healthy ───────────────────
        unhealthy_ids = {p.trigger_id for p in plans}
        for comp in list(self._component_recovery_state.keys()):
            if comp not in unhealthy_ids:
                prev = self._component_recovery_state.pop(comp)
                logger.info(
                    f"[IDLE:HEALTH] '{comp}' is now healthy after "
                    f"{prev['attempts']} recovery attempt(s) — resetting state"
                )

        # ── Execute recovery plans with per-component backoff ─────────────────
        recovered = 0
        skipped   = 0
        for plan in plans:
            component = plan.trigger_id
            _now = _t.time()

            # Get or initialise recovery state for this component
            state = self._component_recovery_state.setdefault(component, {
                "attempts":     0,
                "last_attempt": 0.0,
                "escalated":    False,
            })

            # Backoff gate — skip this component entirely if too soon to retry
            attempts      = state["attempts"]
            backoff_secs  = _BACKOFF[min(attempts, len(_BACKOFF) - 1)]
            elapsed_since = _now - state["last_attempt"]
            if elapsed_since < backoff_secs:
                remaining = int(backoff_secs - elapsed_since)
                logger.debug(
                    f"[IDLE:HEALTH] '{component}' recovery on backoff "
                    f"(attempt #{attempts}, {remaining}s remaining) — skipping"
                )
                skipped += 1
                continue

            # ── Execute playbook steps for this component ─────────────────────
            # Outcome of each action in THIS plan, for dependency resolution.
            _step_outcomes: Dict[str, bool] = {}

            for step in plan.steps:
                # Dependency gate — a plan CONTAINING a step is not the same as
                # that step being valid to execute now. "verify health after
                # restart" asserts something about a restart that happened; if
                # the restart failed, running it reports on an event that never
                # occurred. Skip explicitly rather than producing a fabricated
                # verification result.
                _requires = getattr(step, 'requires', None)
                if _requires is not None and not _step_outcomes.get(_requires, False):
                    logger.warning(
                        "[IDLE:HEALTH] Step '%s' SKIPPED_DEPENDENCY_FAILED for '%s' "
                        "— requires '%s' which %s",
                        step.action, component, _requires,
                        "failed" if _requires in _step_outcomes else "did not run",
                    )
                    continue

                # Idempotency gate — skip steps that are still on per-action cooldown
                if not IdleWorkPlaybook.step_is_due(
                    plan.trigger_id, step, self._step_execution_log, _now
                ):
                    logger.debug(
                        f"[IDLE:HEALTH] Step '{step.action}' on cooldown for "
                        f"'{component}' — skipping"
                    )
                    continue

                try:
                    if self.recovery_manager:
                        success = await self.recovery_manager.execute_recovery_action(
                            component  = component,
                            action     = step.action,
                            parameters = step.params or {},
                        )
                        IdleWorkPlaybook.record_step_executed(
                            plan.trigger_id, step, self._step_execution_log, _now
                        )
                        _step_outcomes[step.action] = bool(success)
                        if success:
                            recovered += 1
                            logger.info(
                                f"[IDLE:HEALTH] Recovery step '{step.action}' "
                                f"succeeded for '{component}'"
                            )
                        else:
                            logger.warning(
                                f"[IDLE:HEALTH] Recovery step '{step.action}' "
                                f"failed for '{component}' — "
                                f"on_failure={step.on_failure}"
                            )
                            if step.on_failure == "abort":
                                break
                            elif step.on_failure == "alert" and self.slack_notifier:
                                await self.slack_notifier.send_notification(
                                    title    = f"Health Recovery Failed: {component}",
                                    message  = f"Step '{step.description}' failed for '{component}'.",
                                    severity = "error",
                                    metadata = {"component": component, "action": step.action},
                                )
                    else:
                        # No recovery manager — fall back to creating a recovery goal
                        IdleWorkPlaybook.record_step_executed(
                            plan.trigger_id, step, self._step_execution_log, _now
                        )
                        await self._create_recovery_goal_from_health_event({
                            "component":        component,
                            "severity":         plan.severity,
                            "message":          plan.summary,
                            "proposed_actions": [{"reason": step.description}],
                        })
                except Exception as e:
                    logger.warning(
                        f"[IDLE:HEALTH] Step error for '{component}': {e}"
                    )

            # ── Update per-component recovery state ───────────────────────────
            state["attempts"]     += 1
            state["last_attempt"]  = _now

            # ── Escalate if the component keeps failing ────────────────────────
            new_attempts = state["attempts"]
            if new_attempts >= _ESCALATION_THRESHOLD and not state["escalated"]:
                state["escalated"] = True
                logger.error(
                    f"[IDLE:HEALTH] ESCALATION: '{component}' has failed recovery "
                    f"{new_attempts} times (severity={plan.severity})"
                )
                try:
                    # Critical Slack alert
                    if self.slack_notifier:
                        await self.slack_notifier.send_notification(
                            title    = f"Health Escalation: {component} unrecoverable",
                            message  = (
                                f"**Component:** {component}\n"
                                f"**Recovery attempts:** {new_attempts}\n"
                                f"**Severity:** {plan.severity}\n"
                                f"**Issue:** {plan.summary}\n"
                                f"**Action required:** Manual intervention"
                            ),
                            severity = "critical",
                            metadata = {
                                "component":        component,
                                "attempts":         new_attempts,
                                "severity":         plan.severity,
                                "escalation_tier":  "health",
                            },
                        )
                    # High-priority investigation task
                    if self.task_queue:
                        await self.task_queue.add_task(
                            description = (
                                f"ESCALATED: '{component}' has failed health recovery "
                                f"{new_attempts} times. Issue: {plan.summary}. "
                                f"Manual diagnosis and repair required."
                            ),
                            priority    = "high",
                            task_type   = "HEALTH_RECOVERY",
                            metadata    = {
                                "component":   component,
                                "attempts":    new_attempts,
                                "severity":    plan.severity,
                                "escalated":   True,
                            },
                        )
                except Exception as e:
                    logger.warning(f"[IDLE:HEALTH] Escalation notification error: {e}")



    # ── TIER 3: System review snapshot (deterministic, no LLM) ─────────────

    async def _idle_system_review_work(self):
        """Build a facts-first system review snapshot for the LLM.

        This is intentionally non-LLM: it inventories capabilities/tools,
        records the most recent health/security outcomes, and provides a
        lightweight codebase inventory. The snapshot is then stored to
        META memory so downstream tasks can retrieve it.
        """
        import os
        import time as _t

        now = datetime.now()
        now_ts = _t.time()

        def _count_files(root_dir: str, suffixes: tuple[str, ...], max_files: int = 5000) -> int:
            count = 0
            if not root_dir or not os.path.isdir(root_dir):
                return 0
            for base, dirs, files in os.walk(root_dir):
                # Skip common large/noisy dirs
                dirs[:] = [
                    d for d in dirs
                    if d not in {".git", "venv", "venv_torin", "__pycache__", "logs", "tmp", "node_modules"}
                ]
                for name in files:
                    if name.endswith(suffixes):
                        count += 1
                        if count >= max_files:
                            return count
            return count

        snapshot: Dict[str, Any] = {
            "event": "idle_system_review",
            "generated_at": now.isoformat(),
            "generated_at_ts": now_ts,
            "uptime_seconds": int(max(0.0, now_ts - float(getattr(self, "_started_at_ts", now_ts)))),
            "health": {
                "last_check_at": self._idle_last_health_check_at.isoformat() if self._idle_last_health_check_at else None,
                **(self._idle_last_health_snapshot or {}),
            },
            "security": {
                "last_audit_at": self._idle_last_security_audit_at.isoformat() if self._idle_last_security_audit_at else None,
                **(self._idle_last_security_findings or {}),
            },
            "tools": {},
            "codebase": {},
            "knowledge": {},
            "highlights": {},
        }

        # Knowledge cutoff tracking (persistent state)
        try:
            snapshot["knowledge"] = self._get_knowledge_cutoff_snapshot()
        except Exception as e:
            snapshot["knowledge"] = {"error": str(e)}

        # Tool/capability inventory (safe, deterministic)
        try:
            from core.tools.tool_registry import get_tool_registry

            registry = get_tool_registry()
            total_factories = len(getattr(registry, "tool_factories", {}) or {})
            total_loaded = len(getattr(registry, "tools", {}) or {})
            total_tools = total_factories + total_loaded

            coverage = {}
            try:
                coverage = registry.get_capability_coverage() or {}
            except Exception:
                coverage = {}

            top_caps = sorted(coverage.items(), key=lambda kv: kv[1], reverse=True)[:12]
            top_caps_serialized = [
                {
                    "capability": getattr(cap, "value", str(cap)),
                    "providers": int(n),
                }
                for cap, n in top_caps
            ]

            category_index = getattr(registry, "category_index", {}) or {}
            category_counts = {str(cat): len(names) for cat, names in category_index.items()}
            top_categories = sorted(category_counts.items(), key=lambda kv: kv[1], reverse=True)[:10]

            snapshot["tools"] = {
                "total_tools": total_tools,
                "lazy_factories": total_factories,
                "loaded_tools": total_loaded,
                "top_capabilities": top_caps_serialized,
                "top_categories": [{"category": k, "tools": v} for k, v in top_categories],
            }
        except Exception as e:
            snapshot["tools"] = {"error": str(e)}

        # Lightweight codebase inventory (counts only; avoids heavy reads)
        try:
            torin_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
            snapshot["codebase"] = {
                "root": torin_root,
                "py_files": {
                    "core": _count_files(os.path.join(torin_root, "core"), (".py",)),
                    "services": _count_files(os.path.join(torin_root, "services"), (".py",)),
                    "scripts": _count_files(os.path.join(torin_root, "scripts"), (".py",)),
                    "tests": _count_files(os.path.join(torin_root, "tests"), (".py",)),
                },
            }
        except Exception as e:
            snapshot["codebase"] = {"error": str(e)}

        # Short highlights for quick prompting
        try:
            snapshot["highlights"] = {
                "tools_total": (snapshot.get("tools") or {}).get("total_tools"),
                "health_components_total": (snapshot.get("health") or {}).get("components_total"),
                "health_unhealthy_total": (snapshot.get("health") or {}).get("unhealthy_total"),
                "security_findings_total": (snapshot.get("security") or {}).get("total"),
                "knowledge_refreshed_through": (snapshot.get("knowledge") or {}).get("refreshed_through_date"),
            }
        except Exception:
            snapshot["highlights"] = {}

        self._idle_last_system_review_at = now
        self._idle_system_review_snapshot = snapshot

        logger.info(
            "[IDLE:REVIEW] System review snapshot updated — "
            f"tools={snapshot.get('highlights', {}).get('tools_total')}, "
            f"health_components={snapshot.get('highlights', {}).get('health_components_total')}, "
            f"security_findings={snapshot.get('highlights', {}).get('security_findings_total')}"
        )



    # ── TIER 4: Knowledge refresh (autonomous research cadence) ───────────

    async def _idle_knowledge_refresh_work(self):
        """Queue a periodic research task to reduce temporal knowledge gaps.

        This is intentionally separated from ASI self-improvement:
        - Knowledge refresh is *learning/research* (safe, non-mutating)
        - ASI self-improvement is *code/system modification* (mutating)

        The goal is to keep Torin current without constantly launching
        expensive, evidence-free self-modification cycles.
        """
        from .shared_types import Task, TaskType, TaskSource, Priority
        import time as _t

        # Require a system review snapshot so the task has grounded context
        snapshot = getattr(self, "_idle_system_review_snapshot", None)
        if not snapshot:
            logger.info("[IDLE:KNOWLEDGE] Skipping — no system review snapshot yet")
            return

        now = datetime.now()
        now_ts = _t.time()

        min_uptime_s = float(self.config.get("idle_knowledge_refresh_min_uptime_s", 900.0))
        uptime_s = now_ts - float(getattr(self, "_started_at_ts", now_ts))
        if uptime_s < min_uptime_s:
            logger.info(
                f"[IDLE:KNOWLEDGE] Skipping — uptime {int(uptime_s)}s < {int(min_uptime_s)}s"
            )
            return

        # Optional kill-switch
        if not bool(self.config.get("enable_idle_knowledge_refresh", True)):
            logger.debug("[IDLE:KNOWLEDGE] Disabled by config — skipping")
            return

        # Cross-restart throttle: if we started a refresh recently, don't enqueue another.
        try:
            state = self._knowledge_cutoff_state or {}
            started_at = state.get("last_refresh_started_at")
            if started_at:
                from datetime import datetime as _dt
                started_dt = _dt.fromisoformat(str(started_at))
                interval_s = int(self.config.get("idle_knowledge_refresh_interval_s", 6 * 60 * 60))
                if (now - started_dt).total_seconds() < interval_s:
                    logger.info(
                        f"[IDLE:KNOWLEDGE] Skipping — last_refresh_started_at={started_at} "
                        f"(< interval {interval_s}s)"
                    )
                    return
        except Exception:
            pass

        # Staleness gate — only refresh if our knowledge is stale.
        # This prevents constant research even with a short idle interval.
        # Default: refresh at most weekly.
        max_age_days = int(self.config.get("knowledge_refresh_max_age_days", 7))
        state = self._knowledge_cutoff_state or {}
        refreshed_through = (state.get("refreshed_through_date") or "")
        try:
            from datetime import date as _date
            if refreshed_through:
                refreshed_date = _date.fromisoformat(refreshed_through)
                age_days = (now.date() - refreshed_date).days
                if age_days < max_age_days:
                    logger.info(
                        f"[IDLE:KNOWLEDGE] Skipping — refreshed_through={refreshed_through} "
                        f"(age={age_days}d < {max_age_days}d)"
                    )
                    return
        except Exception:
            # If state is malformed, fall through and refresh.
            pass

        cutoff = self._get_declared_model_cutoff_date()

        # Create a research task (non-mutating) that can use CONDUCT_RESEARCH tools.
        topic_list = self.config.get(
            "idle_knowledge_refresh_topics",
            [
                "recent AI agent tooling patterns (2025-2026)",
                "function calling / tool schema best practices", 
                "MCP ecosystem changes and interoperability", 
                "security CVEs relevant to our Python dependencies", 
                "pgvector/Postgres performance practices", 
            ],
        )
        topics_str = "; ".join(str(t) for t in topic_list[:8])

        task = Task(
            id=f"knowledge_refresh_{now.timestamp()}",
            type=TaskType.RESEARCH,
            description=(
                "Conduct research to reduce temporal knowledge gaps and update internal operational knowledge.\n"
                f"Model knowledge cutoff (declared): {cutoff}. Current date: {now.date().isoformat()}.\n\n"
                f"Last refreshed through: {refreshed_through or 'unknown'}.\n\n"
                "Research topics:\n"
                f"- {topics_str}\n\n"
                "Deliverables (STRICT):\n"
                "1) Bullet summary of findings with source URLs\n"
                "2) Relevance mapping to TorinAI subsystems/tools\n"
                "3) Recommendations ranked by impact/effort\n"
                "4) If code changes are suggested, propose follow-up tasks — DO NOT modify code in this task\n\n"
                f"System review highlights: {snapshot.get('highlights', {})}"
            ),
            priority=Priority.LOW,
            source=TaskSource.AUTONOMOUS,
            created_by="idle_knowledge_refresh",
            metadata={
                "trigger": "idle_priority_loop",
                "idle_count": self._idle_count,
                "knowledge_refresh": True,
                "declared_cutoff": cutoff,
                "refreshed_through_before": refreshed_through or None,
                "system_review_highlights": snapshot.get("highlights", {}),
                "no_code_changes": True,
            },
        )

        try:
            await self.task_queue.add_task(task, priority=Priority.LOW)
            self._idle_last_knowledge_refresh_at = now
            # Record the refresh start (best-effort) for cross-session visibility
            try:
                self._knowledge_cutoff_state["last_refresh_started_at"] = now.isoformat()
                self._knowledge_cutoff_state["last_refresh_task_id"] = task.id
                self._knowledge_cutoff_state["declared_model_cutoff_date"] = cutoff
                self._save_knowledge_cutoff_state(self._knowledge_cutoff_state)
            except Exception as e:
                logger.debug(f"[IDLE:KNOWLEDGE] Could not persist refresh start state: {e}")
            logger.info(f"[IDLE:KNOWLEDGE] Task queued: {task.id} (topics={len(topic_list)})")
        except Exception as e:
            logger.warning(f"[IDLE:KNOWLEDGE] Failed to queue knowledge refresh task: {e}")


    # ── Knowledge cutoff persistence helpers ───────────────────────────────

    def _knowledge_cutoff_state_path(self) -> str:
        """Return an absolute path for the knowledge cutoff state file."""
        import os
        torin_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
        rel = self.config.get("knowledge_cutoff_state_path", os.path.join("data", "knowledge_cutoff_state.json"))
        return os.path.join(torin_root, rel)

    def _load_knowledge_cutoff_state(self) -> Dict[str, Any]:
        import json
        import os

        path = self._knowledge_cutoff_state_path()
        if not os.path.exists(path):
            return {
                "schema": "knowledge_cutoff_state.v1",
                "declared_model_cutoff_date": self._get_declared_model_cutoff_date(),
                "refreshed_through_date": None,
                "last_refresh_started_at": None,
                "last_refresh_completed_at": None,
                "last_refresh_task_id": None,
            }

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f) or {}

        if not isinstance(data, dict):
            raise ValueError("knowledge cutoff state is not a dict")

        data.setdefault("schema", "knowledge_cutoff_state.v1")
        # Override if the saved value is absent or the sentinel "unknown" from old code
        _saved_cutoff = data.get("declared_model_cutoff_date")
        if not _saved_cutoff or _saved_cutoff == "unknown":
            data["declared_model_cutoff_date"] = self._get_declared_model_cutoff_date()
        data.setdefault("refreshed_through_date", None)
        data.setdefault("last_refresh_started_at", None)
        data.setdefault("last_refresh_completed_at", None)
        data.setdefault("last_refresh_task_id", None)
        return data

    def _save_knowledge_cutoff_state(self, state: Dict[str, Any]) -> None:
        import json
        import os
        import tempfile

        path = self._knowledge_cutoff_state_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)

        payload = dict(state or {})
        payload.setdefault("schema", "knowledge_cutoff_state.v1")
        payload.setdefault("declared_model_cutoff_date", self._get_declared_model_cutoff_date())

        fd, tmp_path = tempfile.mkstemp(prefix="knowledge_cutoff_state_", suffix=".json", dir=os.path.dirname(path))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, sort_keys=True)
            os.replace(tmp_path, path)
        finally:
            try:
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)
            except Exception:
                pass

    # ── Permanently-failed fingerprint persistence ──────────────────────

    def _permanently_failed_fps_path(self) -> str:
        import os
        torin_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
        rel = self.config.get("permanently_failed_fps_path", os.path.join("data", "permanently_failed_fps.json"))
        return os.path.join(torin_root, rel)

    def _load_permanently_failed_fps(self) -> "Set[str]":
        """Load the persistent set of permanently-failed task fingerprints from disk."""
        import json, os
        path = self._permanently_failed_fps_path()
        if not os.path.exists(path):
            return set()
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                loaded = set(str(fp) for fp in data if fp)
                logger.info(f"♻️  Loaded {len(loaded)} permanently-failed fingerprints from disk")
                return loaded
        except Exception as e:
            logger.debug(f"Failed to parse permanently_failed_fps.json: {e}")
        return set()

    def _save_permanently_failed_fps(self) -> None:
        """Atomically persist the permanently-failed fingerprint set to disk."""
        import json, os, tempfile
        path = self._permanently_failed_fps_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        payload = sorted(self._permanently_failed_fps)
        fd, tmp_path = tempfile.mkstemp(prefix="permanently_failed_fps_", suffix=".json", dir=os.path.dirname(path))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)
            os.replace(tmp_path, path)
        finally:
            try:
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)
            except Exception:
                pass

    def _get_declared_model_cutoff_date(self) -> str:
        """Declared model training cutoff date.

        This is operator-provided (config/env). We intentionally do not try to
        guess from model name.
        """
        import os

        # 1. Explicit override via env var or config always wins
        explicit = (
            os.getenv("MODEL_KNOWLEDGE_CUTOFF_DATE")
            or self.config.get("model_knowledge_cutoff_date")
            or self.config.get("knowledge_cutoff_date")
        )
        if explicit:
            return explicit

        # The coordinator does not probe a model — a language model belongs to
        # the teacher, and the substrate has no training cutoff of its own. The
        # date comes from configuration (above) or this default, which callers
        # can override; it only seeds how stale the knowledge-refresh tier
        # assumes its world knowledge might be.
        return self.config.get("default_knowledge_cutoff_date", "2024-09")

    def _get_knowledge_cutoff_snapshot(self) -> Dict[str, Any]:
        from datetime import date as _date

        state = self._knowledge_cutoff_state or {}
        refreshed = state.get("refreshed_through_date")
        days_stale = None
        try:
            if refreshed:
                refreshed_date = _date.fromisoformat(str(refreshed))
                days_stale = (_date.today() - refreshed_date).days
        except Exception:
            days_stale = None

        _saved_cutoff = state.get("declared_model_cutoff_date")
        return {
            "declared_model_cutoff_date": (_saved_cutoff if _saved_cutoff and _saved_cutoff != "unknown" else self._get_declared_model_cutoff_date()),
            "refreshed_through_date": refreshed,
            "days_stale": days_stale,
            "last_refresh_started_at": state.get("last_refresh_started_at"),
            "last_refresh_completed_at": state.get("last_refresh_completed_at"),
            "last_refresh_task_id": state.get("last_refresh_task_id"),
        }


    # ── Completion callback: knowledge refresh completion ──────────────────

    async def _on_knowledge_refresh_complete(
        self,
        task: Task,
        result: Dict[str, Any],
        confidence: float,
    ):
        """Update knowledge refresh state when a knowledge_refresh research task completes."""
        try:
            meta = getattr(task, "metadata", None) or {}
            if not meta.get("knowledge_refresh", False):
                return

            now = datetime.now()
            today = now.date().isoformat()

            # Update persistent state
            self._knowledge_cutoff_state["last_refresh_completed_at"] = now.isoformat()
            self._knowledge_cutoff_state["refreshed_through_date"] = today
            self._knowledge_cutoff_state["last_refresh_task_id"] = getattr(task, "id", None)
            _meta_cutoff = meta.get("declared_cutoff")
            self._knowledge_cutoff_state["declared_model_cutoff_date"] = (
                _meta_cutoff if _meta_cutoff and _meta_cutoff != "unknown"
                else self._get_declared_model_cutoff_date()
            )
            try:
                self._save_knowledge_cutoff_state(self._knowledge_cutoff_state)
            except Exception as e:
                logger.debug(f"Knowledge cutoff state save failed (non-fatal): {e}")

            # Persist a META memory event (best-effort)
            try:
                await self.store_memory(
                    memory_type=MemoryType.META,
                    content={
                        "event": "knowledge_refresh_complete",
                        "task_id": getattr(task, "id", None),
                        "confidence": float(confidence) if confidence is not None else None,
                        "declared_model_cutoff_date": self._knowledge_cutoff_state.get("declared_model_cutoff_date"),
                        "refreshed_through_date": today,
                        "timestamp": now.isoformat(),
                    },
                    importance=0.30,
                    tags=["knowledge", "refresh", "cutoff", "autonomous"],
                )
            except Exception as e:
                logger.debug(f"Could not store knowledge refresh completion memory: {e}")

            logger.info(
                f"[KNOWLEDGE] Refreshed-through updated: {today} (task={getattr(task, 'id', 'unknown')})"
            )
        except Exception as e:
            logger.debug(f"Knowledge refresh completion callback error: {e}")



    # ── TIER 5: Self-improvement with targeted components ─────────────────────

    async def _idle_self_improvement_work(self):
        """
        Run an ASI self-improvement cycle with components targeted based on the
        most recent health snapshot and recent task failures.

        Fixes:
          - Previously used target_components=[] (auto-select), ignoring known unhealthy data
          - Improvement result was logged but never stored to meta-memory or fed to motivation
        """
        from .idle_work_playbook import IdleWorkPlaybook

        if not self.asi_self_improvement:
            logger.debug("[IDLE:IMPROVE] ASI self-improvement not available — skipping")
            return

        # Gather health data and recent failures to inform target selection
        health_data: Dict[str, Any] = {}
        try:
            if self.health_monitor:
                health_data = await self.health_monitor.get_system_health() or {}
        except Exception:
            pass

        # Extract recently failed component names from task queue history
        recent_failures: List[str] = []
        try:
            for task in list(self.task_queue.tasks_by_id.values())[-20:]:
                if hasattr(task, 'status') and str(task.status).lower() in ('failed',):
                    comp = getattr(task, 'metadata', {}).get('target_component', '')
                    if comp and comp not in recent_failures:
                        recent_failures.append(comp)
        except Exception:
            pass

        playbook = IdleWorkPlaybook()
        targets  = playbook.plan_self_improvement_targets(health_data, recent_failures)

        # ── Gating: don't enqueue LLM-heavy improvement without real signals ──
        import time as _t
        now_ts = _t.time()

        min_uptime_s = float(self.config.get("idle_improvement_min_uptime_s", 600.0))
        uptime_s = now_ts - float(getattr(self, "_started_at_ts", now_ts))
        if uptime_s < min_uptime_s:
            logger.info(
                f"[IDLE:IMPROVE] Skipping — uptime {int(uptime_s)}s < {int(min_uptime_s)}s"
            )
            return

        # Require a recent system review snapshot to exist (facts-first context)
        review_required_age_s = float(self.config.get("idle_system_review_required_age_s", 900.0))
        snapshot = getattr(self, "_idle_system_review_snapshot", None)
        if not snapshot:
            logger.info("[IDLE:IMPROVE] Skipping — no system review snapshot yet")
            return
        snap_ts = float(snapshot.get("generated_at_ts", 0.0) or 0.0)
        if snap_ts and (now_ts - snap_ts) > review_required_age_s:
            logger.info("[IDLE:IMPROVE] Skipping — system review snapshot is stale")
            return

        # Avoid running improvement when health monitor isn't providing coverage
        min_health_components = int(self.config.get("idle_improvement_min_health_components", 1))
        components = (health_data.get("components", {}) or {})
        if len(components) < min_health_components:
            logger.info(
                f"[IDLE:IMPROVE] Skipping — insufficient health coverage "
                f"({len(components)} components; need >= {min_health_components})"
            )
            return

        allow_autoselect = bool(self.config.get("idle_improvement_allow_autoselect", False))
        if not targets and not allow_autoselect:
            # No unhealthy components + no failures, and autoselect disabled.
            logger.info(
                "[IDLE:IMPROVE] Skipping — no targets/failures; autoselect disabled"
            )
            return

        logger.info(
            f"[IDLE:IMPROVE] Creating ASI self-improvement task — "
            f"targets: {targets or ['auto-select']}"
        )

        try:
            from .shared_types import Task, TaskType, TaskSource, Priority
            
            # Create task for self-improvement instead of executing directly
            improvement_task = Task(
                id=f"self_improvement_{datetime.now().timestamp()}",
                type=TaskType.SELF_IMPROVEMENT,
                description=(
                    f"ASI self-improvement cycle - targets: {', '.join(targets) if targets else 'auto-select'}\n"
                    f"System review highlights: {snapshot.get('highlights', {})}"
                ),
                priority=Priority.LOW,  # Self-improvement is low priority
                source=TaskSource.AUTONOMOUS,
                created_by="idle_self_improvement",
                metadata={
                    "trigger": "idle_priority_loop",
                    "idle_count": self._idle_count,
                    "targeted_from": "health_check+failure_history",
                    "target_components": targets,
                    "system_review_highlights": snapshot.get("highlights", {}),
                }
            )
            
            await self.task_queue.add_task(improvement_task, priority=Priority.LOW)
            logger.info(f"[IDLE:IMPROVE] Task queued: {improvement_task.id}")

        except Exception as e:
            logger.warning(f"[IDLE:IMPROVE] Failed to queue self-improvement task: {e}")

    # ── TIER 4: Meta-learning — evaluate ALL task types ───────────────────────

    #: Stamped onto a task-outcome memory once its domain has been expanded.
    #: Durable dedup lives on the OUTCOME itself rather than in an in-memory
    #: watermark, because the scheduler's per-job state resets on every restart
    #: -- so a watermark would re-learn the whole backlog each start and the
    #: meta-learner would count one outcome as many independent trials.
    DOMAIN_EXPANSION_MARK = "domain_expanded_at"

    async def _idle_domain_expansion_work(self):
        """PRIORITY 4 — Expand domain knowledge from recent task outcomes.

        TORINAI_REFERENCE.md:3114 specifies this tier. Every part of it already
        existed and nothing joined them:

          producer  _store_task_outcome_meta_memory (:1725, 4 live call sites)
                    writes TaskOutcomeRecord{domain, outcome, confidence} as a
                    META memory tagged "task_outcome"
          consumer  UnifiedLearningSystem.learn_with_domain_context, the only
                    method that puts a domain onto learn_from_example and so the
                    only thing that opens the cross-domain transfer path
          bridge    DomainRegistry.resolve_domain_reference, which turns the
                    producer's CATEGORY ("scientific") into the populated FIELDS
                    beneath it

        The consumer had zero callers, so no task outcome has ever reached the
        domain layer. This tier is that call.
        """
        self._domain_expansion_status = "STARTED"

        if not getattr(self.learning, "initialized", False):
            # Not a quiet skip. This tier cannot do its work without the
            # learning system, and a silent return would be indistinguishable
            # from "there was nothing to expand".
            self._domain_expansion_status = "NO_LEARNING_SYSTEM"
            logger.warning(
                "[IDLE:DOMAIN] unified_learning is not attached; task outcomes "
                "cannot reach the domain layer")
            return

        # get_memory_agent() returns an UNINITIALIZED agent -- postgres_storage
        # is None until initialize() runs (its own docstring documents the two
        # calls). Reading that None as "storage unavailable" would report an
        # unmet precondition as an absent subsystem, and this tier would go
        # quiet for a reason that has nothing to do with task outcomes.
        storage = getattr(self.memory, "postgres_storage", None)
        if storage is None and hasattr(self.memory, "initialize"):
            await self.memory.initialize()
            storage = getattr(self.memory, "postgres_storage", None)
        if storage is None:
            self._domain_expansion_status = "NO_MEMORY_STORAGE"
            logger.warning(
                "[IDLE:DOMAIN] memory agent initialized but exposes no storage; "
                "task outcomes cannot be read")
            return

        from core.memory.utils.interfaces import MemoryType
        from core.learning.learning_interfaces import LearningExample

        batch = int(self.config.get("idle_domain_expansion_batch", 25))
        outcomes = await storage.search_memories(
            memory_type=MemoryType.META,
            tags={"task_outcome"},
            limit=batch * 4,   # headroom: already-expanded ones are filtered below
        )

        pending = [m for m in outcomes
                   if not (m.metadata or {}).get(self.DOMAIN_EXPANSION_MARK)][:batch]
        if not pending:
            # A real zero, reported as one. "No task has completed since the
            # last pass" and "the reader is broken" must not look alike.
            self._domain_expansion_status = "NOTHING_PENDING"
            logger.info(
                "[IDLE:DOMAIN] %d task-outcome memory(ies) found, none unexpanded",
                len(outcomes))
            return

        expanded = 0
        transfers = 0
        skipped: Dict[str, int] = {}
        for memory in pending:
            status, t = await self._expand_one_outcome(memory, storage)
            if status == "expanded":
                expanded += 1
                transfers += t
            else:
                skipped[status] = skipped.get(status, 0) + 1

        self._domain_expansion_status = "COMPLETED"
        # OBSERVABLE, not just logged. The reason an outcome was not expanded is
        # the diagnostic that separates "nothing to learn from" from "the tier
        # cannot read what the producer wrote" -- and a reason that only ever
        # reaches a log line cannot be asserted on, so a read that silently
        # classifies every outcome as unusable looks identical to a quiet
        # system.
        self._domain_expansion_counts = {
            "considered": len(pending),
            "expanded": expanded,
            "transfers": transfers,
            "skipped": dict(skipped),
        }
        logger.info(
            "[IDLE:DOMAIN] %d/%d task outcome(s) expanded into the domain layer, "
            "%d cross-domain transfer(s)%s",
            expanded, len(pending), transfers,
            f"; not expanded: {skipped}" if skipped else "")

        # The return leg. Expansion writes transfers; this asks whether the ones
        # already written actually helped. Running it here keeps both directions
        # of the loop under one owner rather than adding a second tier that
        # would have to agree with this one about what a transfer is.
        await self._resolve_transfer_outcomes()

    async def _expand_one_outcome(self, memory, storage) -> Tuple[str, int]:
        """Expand ONE task-outcome memory into the domain layer.

        The single per-outcome authority, shared by the idle tier and the
        reactive `_react_expand_outcome`, so both go through identical logic and
        the DOMAIN_EXPANSION_MARK dedup keeps them from double-processing.
        Returns (status, transfers): status is 'expanded', 'no_domain', or the
        learning error_class; transfers is the cross-domain transfers written.

        The structured record lives at thinking_state['raw_event'] — store_memory
        renders the event dict into prose for `content`, so the TaskOutcomeRecord
        fields (domain, outcome, confidence, task_type) are read from the raw
        dict, not the narrative.
        """
        from core.learning.learning_interfaces import LearningExample
        raw = (memory.thinking_state or {}).get("raw_event")
        content = raw if isinstance(raw, dict) else {}
        domain = content.get("domain")
        if not domain:
            # The producer always writes `domain`. Its absence means the record
            # did not come from TaskOutcomeRecord — counted, left unmarked.
            return ("no_domain", 0)

        result = await self.learning.learn_with_domain_context(
            LearningExample(
                example_id=memory.memory_id,
                inputs={
                    "task_id": content.get("task_id"),
                    "task_type": content.get("task_type"),
                    "task_description": content.get("task_description"),
                    "task_source": content.get("task_source"),
                },
                targets={
                    "outcome": content.get("outcome"),
                    "result_summary": content.get("result_summary"),
                    "failure_reason": content.get("failure_reason"),
                },
                # The recorded confidence IS the quality of this example.
                quality_score=float(content.get("confidence", 0.0) or 0.0),
                task_type=content.get("task_type"),
                domain=str(domain),
                source="task_outcome",
            ),
            str(domain),
        )

        if not result.success:
            # Deliberately NOT marked. An outcome that could not be expanded
            # because its domain holds nothing yet must be reconsidered once that
            # domain has been learned (`domain_empty` is exactly that case).
            return ((result.metadata or {}).get("error_class") or "learning_failed", 0)

        # EXPANDED means the domain layer processed this outcome — not that the
        # learning strategy earned credit for it (separate facts).
        cross = (result.metadata or {}).get("cross_domain") or {}
        transfers = len(cross.get("transfers") or [])

        marked = await storage.update_memory(memory.memory_id, {
            "metadata": {self.DOMAIN_EXPANSION_MARK: datetime.now().isoformat()},
            "metadata.merge": True,
        })
        if not marked:
            # An unmarked outcome would be expanded again and the meta-learner
            # would count the repeat as fresh evidence. Stop rather than quietly
            # build up duplicate trials.
            raise RuntimeError(
                f"task outcome {memory.memory_id} was expanded but could not be "
                f"marked; continuing would re-learn it on every pass")
        return ("expanded", transfers)

    async def _idle_domain_discovery_work(self):
        """Discover domains from what the substrate has learned AND been taught.

        Two kinds of subject grow the substrate's map here, through the one domain
        authority. OPERATIONAL: buckets of learned operators under a string
        domain_id, crystallized or merged by operator structure -- subjects the
        substrate learned by ACTING. DECLARATIVE: connected clusters of taught
        concepts sitting in the `conversation` channel, crystallized into their
        own subject domains by relation structure -- subjects the substrate was
        TAUGHT. Both ask the Universal Domain Master to decide; nothing here
        decides on its own. The declarative half is what lets teaching advance
        the domain system instead of piling every taught fact into one channel.
        """
        udm = self.universal_domain_master  # this substrate's own domain faculty

        summary = await udm.discover_domains()
        if summary.get("examined"):
            logger.info(
                "[IDLE] domain discovery: %d examined, %d crystallized, %d merged",
                summary["examined"], summary["crystallized"], summary["merged"])

        # Declarative twin: crystallize taught-concept clusters out of the
        # conversation channel into per-subject domains.
        concept_summary = await udm.discover_concept_domains(from_field="conversation")
        if concept_summary.get("crystallized"):
            logger.info(
                "[IDLE] concept-domain discovery: %d clusters examined, %d crystallized (%s)",
                concept_summary["examined"], concept_summary["crystallized"],
                ", ".join(f"{o['field']}:{o['concepts']}"
                          for o in concept_summary.get("outcomes", [])))
        return {"operator": summary, "declarative": concept_summary}

    async def _idle_operator_exploration_work(self):
        """Learn the operators of a domain the substrate is not yet competent in,
        chosen by intrinsic motivation.

        Domain competence is an epistemic belief. An under-learned domain sits at
        high entropy and appears in the epistemic engine's unstable regions;
        intrinsic motivation ranks exactly those, mixing all its drives. This
        tier takes the top-ranked target that is an operator-domain it can
        explore, runs ONE exploration cycle, and records the outcome as evidence
        on that competence belief -- so the belief moves and the next choice
        follows from it. Nothing here selects domains on its own.
        """
        from core.learning.exploration import (
            SubstrateExplorer, explorable_domains, get_proposer)

        udm = self.universal_domain_master  # this substrate's own domain faculty

        domains = explorable_domains()
        if not domains:
            return {"status": "no explorable domain"}

        # Every explorable domain gets a competence belief so it can surface;
        # then intrinsic motivation decides which one is worth exploring now.
        for d in domains:
            await udm.ensure_competence_belief(d)
        # Erode competence that is no longer being earned, so a domain the
        # substrate wrongly believes it has mastered resurfaces for
        # re-verification rather than being trusted forever.
        await udm.refresh_competence_beliefs()

        chosen = None
        im = getattr(self, "intrinsic_motivation", None)
        if im is not None:
            try:
                targets = await im.get_top_exploration_targets(limit=10)
                chosen = await udm.select_exploration_target(domains, targets)
            except Exception as e:
                raise_if_structural(e, "autonomous_coordinator._idle_operator_exploration_work")
                logger.info("exploration target ranking unavailable: %s", e)
        if chosen is None:
            # Motivation surfaced nothing among explorable domains; stay
            # always-online by exploring one anyway (the belief still moves).
            chosen = domains[0]

        # Explore RECORDS demonstrations and enqueues their operators for
        # induction; it does not induce here. Induction runs off this acting path
        # in `_idle_operator_induction_work`, which is also what moves the
        # competence belief -- learning changes competence, not the acting that
        # fed it. This tier records only CONTROLLABILITY, which the acting itself
        # establishes: did acting move the world (acted/positive) more than not
        # acting (still/ambient)? That is what lets a later cycle drop a domain
        # the substrate cannot steer.
        summary = await SubstrateExplorer().explore(
            chosen, get_proposer(chosen), max_actions=8)
        await udm.record_controllability(
            chosen,
            action_attempts=summary.get("acted", 0),
            action_effects=summary.get("positive", 0),
            still_observations=summary.get("still_observations", 0),
            ambient_changes=summary.get("ambient_changes", 0))
        if im is not None:
            try:
                await im.mark_target_explored(f"competence:{chosen}")
            except Exception as e:
                raise_if_structural(e, "autonomous_coordinator._idle_operator_exploration_work")
        logger.info("[IDLE] operator exploration: domain=%s acted=%s", chosen,
                    summary.get("acted"))
        return {"domain": chosen, **summary}

    async def _idle_operator_induction_work(self):
        """Induce the operators exploration has gathered demonstrations for, off
        the acting path, and move the competence beliefs the results earn.

        This is the always-online learner. Exploration (a separate tier) only
        acts and records; the hypothesis search -- whose cost grows with the
        richness of the observed state -- runs HERE so no acting cycle pays for
        it. A domain that gained a newly executable operator has become more
        competent; one whose demonstrations did not yet yield one has not. Both
        are recorded as competence evidence, so the belief tracks what learning
        actually established.
        """
        # Drain the pending induction through this substrate's OWN learning
        # authority (the always-online, model-free learner).
        result = await self.learning.drain_pending_induction(limit=50)
        by_domain = result.get("by_domain", {})
        if not by_domain:
            return {"drained": 0}

        udm = self.universal_domain_master  # this substrate's own domain faculty

        for domain_id, learned in by_domain.items():
            await udm.record_competence_evidence(domain_id, learned=bool(learned))
        learned_domains = [d for d, learned in by_domain.items() if learned]
        logger.info("[IDLE] operator induction: drained=%d learned_domains=%s",
                    result.get("drained", 0), learned_domains)
        return {"drained": result.get("drained", 0),
                "learned_domains": learned_domains,
                "domains_touched": sorted(by_domain)}

    async def _idle_analogy_discovery_work(self):
        """Discover cross-domain analogies over the learned concept store, bounded.

        `AnalogyDiscovery.find_analogy` already loads unified.concepts and
        PERSISTS the best analogy and its concept mappings -- but nothing ever
        CALLED it, so unified.analogies and unified.concept_mappings stayed empty.
        This is that caller. It drives find_analogy over a bounded batch of
        (source concept -> target domain) pairs each cycle, rotating a cursor so
        coverage advances across cycles while the O(pairs) cost stays capped.
        """
        from core.reasoning.analogy_discovery import get_analogy_discovery

        engine = get_analogy_discovery()
        if not await engine.initialize():
            self._analogy_status = "ENGINE_UNAVAILABLE"
            return {"status": "analogy engine unavailable"}

        domains = [d for d, cs in engine.concepts.items() if cs]
        if len(domains) < 2:
            # Not a failure: cross-domain analogy needs at least two populated
            # domains. Reported so "no analogies" is distinguishable from "broken".
            self._analogy_status = "TOO_FEW_DOMAINS"
            return {"status": "need >=2 populated domains", "domains": len(domains)}

        import itertools
        MAX_CALLS = int(self.config.get("analogy_pairs_per_cycle", 8))
        MAX_SRC = int(self.config.get("analogy_sources_per_domain", 3))

        # The full work-list of (source concept, target domain) pairs. Bounded per
        # source domain so one large domain cannot crowd the batch.
        attempts = []
        for src_dom, tgt_dom in itertools.permutations(domains, 2):
            # Only source concepts that actually carry relationships can match on
            # structure; a concept with none contributes nothing but cost.
            srcs = [n for n, c in engine.concepts.get(src_dom, {}).items()
                    if getattr(c, "relationships", None)][:MAX_SRC]
            for sc in srcs:
                attempts.append((sc, tgt_dom))
        if not attempts:
            self._analogy_status = "NO_CONCEPTS"
            return {"status": "no source concepts"}

        cur = getattr(self, "_analogy_cursor", 0) % len(attempts)
        batch = attempts[cur:cur + MAX_CALLS] or attempts[:MAX_CALLS]
        self._analogy_cursor = (cur + len(batch)) % len(attempts)

        found = 0
        # When a pair yields NO analogy, the diagnostic (Oracle A) explains WHY —
        # source-resolution vs target-domain vs candidate-enumeration vs scoring —
        # so "found 0" is an actionable stage, not a silent blank. This is the
        # analogy-diagnostics instrument, which had no caller before.
        _diag = None
        fail_stages: Dict[str, int] = {}
        for sc, tgt_dom in batch:
            try:
                if await engine.find_analogy(sc, tgt_dom, min_similarity=0.5):
                    found += 1
                else:
                    if _diag is None:
                        from core.reasoning.analogy_diagnostics import AnalogyDiagnostics
                        _diag = AnalogyDiagnostics(engine)
                    oa = await _diag.oracle_a(sc, tgt_dom)
                    stage = oa.first_failing_stage or "A5_scoring_no_match"
                    fail_stages[stage] = fail_stages.get(stage, 0) + 1
            except Exception as e:
                raise_if_structural(e, "autonomous_coordinator._idle_analogy_discovery_work")
                logger.info("analogy %s -> %s failed: %s", sc, tgt_dom, e)

        self._analogy_status = "RAN"
        if fail_stages:
            logger.info("[IDLE:ANALOGY] no-mapping stages: %s", dict(fail_stages))
        logger.info("[IDLE:ANALOGY] attempted=%d found=%d (%d domains, cursor=%d/%d)",
                    len(batch), found, len(domains), self._analogy_cursor, len(attempts))
        return {"attempted": len(batch), "found": found, "domains": len(domains),
                "no_mapping_stages": fail_stages}

    async def _rule_root_count(self, *, domain_id: str, predicate: str, arity: int) -> int:
        """The strongest confirming-root count among executable operators of a
        signature — the confidence measure a re-validation must move. Reads the
        rule store (the authority), never inferred from having re-induced."""
        from core.learning.rule_store import get_rule_store
        rules = await get_rule_store().executable_rules(domain_id=domain_id)
        counts = [int(getattr(r, "positive_root_count", 0) or 0)
                  for r in rules
                  if getattr(getattr(r, "rule", None), "action", None) is not None
                  and r.rule.action.signature == (predicate, arity)]
        return max(counts) if counts else 0

    async def _execute_drive_goal(self, task) -> Dict[str, Any]:
        """Execute an intrinsic DRIVE goal (competence/confidence) as REAL,
        model-free substrate learning, targeted at the operator/domain the goal
        names.

        The action is deterministic: ACT to gather fresh evidence in the domain
        (only if the domain is explorable — records demonstrations + enqueues
        them), then RE-INDUCE the operator through the always-online learner. The
        SAME operations the idle growth loop runs, aimed by motivation.

        Success is READ from what learning established — an operator became
        executable, or a weak operator gained confirming roots — never inferred
        from having run. When there is no way to make progress (a weak operator
        in a domain with no proposer to gather fresh evidence), that is an HONEST
        failure with a named reason, not a fabricated success.
        """
        from core.learning.exploration import (
            SubstrateExplorer, explorable_domains, get_proposer)

        md = task.metadata or {}
        drive = md.get("drive")
        domain = md.get("domain_id")
        if drive not in ("competence", "confidence") or not (
                isinstance(domain, str) and domain.strip()):
            return {"verification_state": "failed",
                    "error": f"drive goal missing drive/domain "
                             f"(drive={drive!r} domain={domain!r})"}

        # ACT: gather fresh evidence, but only where the substrate can actually
        # act. A domain with no registered proposer cannot be explored; that is a
        # real limit, surfaced (not silently treated as "nothing gathered").
        explorable = domain in set(explorable_domains())
        explore_summary = None
        if explorable:
            try:
                explore_summary = await SubstrateExplorer().explore(
                    domain, get_proposer(domain), max_actions=8)
            except Exception as e:
                raise_if_structural(e, "autonomous_coordinator._execute_drive_goal")
                logger.info("drive-goal exploration in %s failed: %s", domain, e)

        udm = getattr(self, "universal_domain_master", None)

        # ---- competence, domain-level contrastive: re-induce every operator ----
        if drive == "competence" and md.get("scope") == "domain_contrastive":
            from core.learning.demonstration_store import get_demonstration_store
            store = get_demonstration_store()
            sigs = [s for s in await store.signatures(domain_id=domain)
                    if (s[0], s[1]) != store.CONTRASTIVE]
            induced = []
            for predicate, arity in sigs:
                induced.append(await self.learning.reinduce_operator(
                    domain_id=domain, predicate=predicate, arity=arity))
            executable = [s for s in induced if s.get("executable")]
            ok = bool(executable)
            if udm is not None:
                await udm.record_competence_evidence(domain, learned=ok)
            logger.info("[DRIVE competence/contrastive] domain=%s operators=%d executable=%d",
                        domain, len(induced), len(executable))
            return {"verification_state": "verified" if ok else "failed",
                    "success": ok, "drive": drive, "domain_id": domain,
                    "scope": "domain_contrastive",
                    "operators_induced": len(induced),
                    "operators_executable": len(executable),
                    "explored": bool(explore_summary),
                    "error": None if ok else
                        (f"contrastive re-induced {len(induced)} operator(s), none "
                         f"became executable" if sigs else
                         f"domain {domain} has no operator signatures to sharpen")}

        # ---- per-operator competence / confidence: re-induce the signature ----
        predicate = md.get("predicate")
        arity = md.get("arity")
        if not (isinstance(predicate, str) and predicate.strip()) or \
                not isinstance(arity, int):
            return {"verification_state": "failed",
                    "error": f"drive goal missing operator signature "
                             f"(predicate={predicate!r} arity={arity!r})"}

        if drive == "confidence":
            before = await self._rule_root_count(
                domain_id=domain, predicate=predicate, arity=arity)
            await self.learning.reinduce_operator(
                domain_id=domain, predicate=predicate, arity=arity)
            after = await self._rule_root_count(
                domain_id=domain, predicate=predicate, arity=arity)
            ok = after > before
            logger.info("[DRIVE confidence] %s/%s in %s roots %d→%d explorable=%s",
                        predicate, arity, domain, before, after, explorable)
            # A domain with no proposer is not one the substrate "cannot operate
            # in" — it is one it has no binding/observer wired for YET (a
            # BINDING_GAP, the same honest, addressable gap address_deficit
            # escalates). It is resolved by wiring a binding (e.g. the
            # encounter-driven filesystem install) or learning the domain, not by
            # faking evidence. Marked so it can be routed to acquisition, not read
            # as a dead end.
            out = {"verification_state": "verified" if ok else "failed",
                   "success": ok, "drive": drive, "domain_id": domain,
                   "signature": f"{predicate}/{arity}",
                   "root_count_before": before, "root_count_after": after,
                   "explored": bool(explore_summary)}
            if not ok:
                if explorable:
                    out["error"] = (f"re-validation gathered no new confirming root "
                                    f"({before}→{after})")
                else:
                    out["binding_gap"] = True
                    out["error"] = (f"binding_gap: no binding/observer wired for domain "
                                    f"{domain} yet — the substrate must learn/wire it "
                                    f"before it can gather fresh evidence for "
                                    f"{predicate}/{arity}")
            return out

        # competence, per-operator
        summary = await self.learning.reinduce_operator(
            domain_id=domain, predicate=predicate, arity=arity)
        ok = bool(summary.get("executable"))
        if udm is not None:
            await udm.record_competence_evidence(domain, learned=ok)
        logger.info("[DRIVE competence] %s/%s in %s status=%s explorable=%s",
                    predicate, arity, domain, summary.get("status"), explorable)
        return {"verification_state": "verified" if ok else "failed",
                "success": ok, "drive": drive, "domain_id": domain,
                "signature": f"{predicate}/{arity}",
                "induction_status": summary.get("status"),
                "positives": summary.get("positives"),
                "explored": bool(explore_summary),
                "error": None if ok else
                    f"operator {predicate}/{arity} not validated: {summary.get('status')}"}

    #: A transfer is judged only once the target domain has produced this many
    #: outcomes on each side of it. Below that the honest answer is "not known
    #: yet", which is what NULL means in unified.knowledge_transfers.
    TRANSFER_MIN_EVIDENCE = 5
    #: Post-transfer success rate must beat the baseline by this margin to be
    #: called help. A margin, not any improvement, because small samples move on
    #: noise and a transfer credited by noise becomes evidence for the next one.
    TRANSFER_EFFECT_MARGIN = 0.10

    async def _resolve_transfer_outcomes(self):
        """Close the OTHER direction of the transfer loop.

        A knowledge transfer was written with success NULL and nothing ever
        revisited it, so the record could say a correspondence had been proposed
        and structurally validated, but never whether relying on it made work in
        the target domain go better. Those are different claims: the validator
        judges STRUCTURE, this judges OUTCOMES, and only outcomes can say a
        transfer helped.

        The comparison is before/after within the SAME target domain -- task
        outcomes recorded there before the transfer existed against those
        recorded after. A transfer cannot be credited for the outcome that
        triggered it (that outcome precedes it), so the trigger is never part of
        the evidence.

        Verdicts:
          TRUE   post-transfer success rate beats the baseline by the margin
          FALSE  it does not
          NULL   too few outcomes on either side to say -- left unresolved and
                 revisited later, never defaulted to False
        """
        self._transfer_resolution_status = "STARTED"
        registry = getattr(self.learning, "domain_registry", None)
        if registry is None or not registry.initialized:
            self._transfer_resolution_status = "NO_REGISTRY"
            logger.warning("[IDLE:DOMAIN] no initialized domain registry; "
                           "transfer outcomes cannot be resolved")
            return

        pending = await registry.unresolved_transfers()
        if not pending:
            self._transfer_resolution_status = "NOTHING_PENDING"
            return

        outcomes = await self._task_outcomes_by_field(registry)
        resolved, unresolved = 0, 0
        for row in pending:
            target = f"domain_{row['target_domain']}"
            created = row["created_at"]
            series = outcomes.get(target, [])
            before = [o for o in series if o["at"] < created]
            after = [o for o in series if o["at"] > created]

            meta = row["metadata"]
            if isinstance(meta, str):
                import json as _json
                meta = _json.loads(meta)
            mapping_ids = (meta or {}).get("concept_mappings") or []

            # ATTRIBUTION FIRST. "After the transfer" is not "because of the
            # transfer": if a mapping participated in 2 of 10 later tasks, a
            # before/after comparison credits it with all 10. The usage events
            # say which tasks it actually took part in, so the post-transfer
            # window splits into the tasks it touched and the ones it did not,
            # and the second group is a contemporaneous control rather than a
            # historical one.
            touched = await registry.tasks_using_mappings(mapping_ids)
            treatment = [o for o in after if o["task_id"] in touched]
            control = [o for o in after if o["task_id"] not in touched]

            if len(treatment) >= self.TRANSFER_MIN_EVIDENCE and \
               len(control) >= self.TRANSFER_MIN_EVIDENCE:
                inference, basis = "attributed", "applied-vs-unapplied tasks after the transfer"
                effect_n, effect_rate = len(treatment), sum(o["ok"] for o in treatment) / len(treatment)
                ref_n, ref_rate = len(control), sum(o["ok"] for o in control) / len(control)
            elif len(before) >= self.TRANSFER_MIN_EVIDENCE and \
                    len(after) >= self.TRANSFER_MIN_EVIDENCE:
                # OBSERVATIONAL fallback, labelled as such. It is a coarse
                # signal, not evidence of cause: everything else that changed in
                # the same window is confounded with the transfer. Recorded so a
                # reader can tell a correlational verdict from an attributed one
                # instead of both arriving as a bare TRUE.
                inference, basis = "observational", "target-domain outcomes before vs after"
                effect_n, effect_rate = len(after), sum(o["ok"] for o in after) / len(after)
                ref_n, ref_rate = len(before), sum(o["ok"] for o in before) / len(before)
            else:
                unresolved += 1
                continue

            helped = (effect_rate - ref_rate) >= self.TRANSFER_EFFECT_MARGIN
            await registry.resolve_knowledge_transfer(
                row["transfer_id"], helped,
                effectiveness=round(effect_rate - ref_rate, 4),
                evidence={
                    "inference": inference,
                    "basis": basis,
                    "target_domain": target,
                    "effect_n": effect_n, "effect_rate": round(effect_rate, 4),
                    "reference_n": ref_n, "reference_rate": round(ref_rate, 4),
                    "tasks_applied_to": len(touched),
                    "margin_required": self.TRANSFER_EFFECT_MARGIN,
                    "mapping_ids": mapping_ids,
                })
            resolved += 1

        self._transfer_resolution_status = "COMPLETED"
        self._transfer_resolution_counts = {
            "pending": len(pending), "resolved": resolved,
            "insufficient_evidence": unresolved,
        }
        logger.info(
            "[IDLE:DOMAIN] transfer outcomes: %d resolved, %d still awaiting "
            "evidence (of %d unresolved)", resolved, unresolved, len(pending))

    async def _task_outcomes_by_field(self, registry) -> Dict[str, List[Dict[str, Any]]]:
        """Task outcomes grouped by the FIELD domain they bear on.

        Outcomes record a CATEGORY ("scientific"); transfers target a FIELD
        ("domain_chemistry"). The two are joined through the registry's own
        resolver rather than by string equality, which would match nothing and
        read as "this domain has no history".
        """
        from core.domain.domain_registry import UnresolvedDomainReference

        rows = await self.memory.postgres_storage.db.execute_query(
            """SELECT thinking_state->'raw_event'->>'domain'  AS category,
                      thinking_state->'raw_event'->>'outcome' AS outcome,
                      thinking_state->'raw_event'->>'task_id' AS task_id,
                      created_at
               FROM memory_hot.memory_hot
               WHERE tags @> '["task_outcome"]'::jsonb
               UNION ALL
               SELECT thinking_state->'raw_event'->>'domain',
                      thinking_state->'raw_event'->>'outcome',
                      thinking_state->'raw_event'->>'task_id',
                      created_at
               FROM memory_cold.memory_cold
               WHERE tags @> '["task_outcome"]'::jsonb""",
            fetch_all=True) or []

        by_field: Dict[str, List[Dict[str, Any]]] = {}
        for row in rows:
            if not row["category"] or not row["outcome"]:
                continue
            try:
                fields = registry.resolve_domain_reference(
                    row["category"], require_concepts=True)
            except UnresolvedDomainReference:
                continue
            record = {"at": row["created_at"], "ok": row["outcome"] == "success",
                      "task_id": row["task_id"]}
            for field in fields:
                by_field.setdefault(field.domain_id, []).append(record)
        return by_field

    async def _idle_meta_learning_work(self):
        """
        Evaluate strategy performance across ALL task types (not just RESEARCH).

        NEW: Uses StrategyAdaptationGate for robust threshold-driven adaptation:
          - Binomial confidence interval (95% CI)
          - Minimum sample size (10 executions)
          - Decay-weighted recent performance
          - Variance analysis (instability vs. consistent poor performance)

        Fixes:
          - Previously only evaluated TaskType.RESEARCH
          - Strategy outcomes for other task types were never reviewed
          - Low-performing strategies never flagged for adaptation
          - Arbitrary 0.35 threshold with no statistical rigor
          - No weighting of recent vs. stale outcomes
        """
        from .idle_work_playbook import IdleWorkPlaybook, StrategyAdaptationGate

        # This guarded on self.learning -- the LearningAdapter -- which defines
        # neither evaluate_strategies nor adapt_strategies, so the guard was
        # always False and this entire tier returned before doing any work.
        # Those methods live on MetaLearner, which is self.meta_learning.
        if not self.meta_learning:
            logger.debug("[IDLE:METALEARNING] Meta-learning not available — skipping")
            return

        from .shared_types import TaskType
        from core.learning.meta_learning import TaskFamily

        playbook   = IdleWorkPlaybook()
        task_types = playbook.plan_meta_learning_evaluation()

        logger.info(f"[IDLE:METALEARNING] Evaluating strategies for {len(task_types)} task types")

        evaluation_results: Dict[str, Any] = {}
        adapted = 0

        for tt_value in task_types:
            try:
                tt_enum = TaskType(tt_value)
                family = self._task_family_for(tt_enum)
                evaluation = await self.meta_learning.evaluate_strategies(family)
                logger.debug(f"[IDLE:METALEARNING] {tt_value} ({family.value}): {evaluation}")

                # ──── Robust adaptation gate ────
                # Aggregate from the meta-learner's persisted arms, not from
                # self._strategy_outcomes. That dict starts empty on every
                # restart, so the gate's MIN_EXECUTIONS=10 threshold was
                # effectively unreachable unless a single process happened to
                # run 10 executions of one task type before exiting.
                total_execs = 0
                total_wins = 0
                for sid in self.meta_learning.task_strategy_map.get(family, []):
                    s = self.meta_learning.strategies[sid]
                    if not str(s.strategy_type).startswith(self.EXECUTOR_NS):
                        continue
                    total_execs += s.trials
                    total_wins += s.successes

                # Get recent outcomes for variance/decay analysis
                recent_outcomes = self._get_recent_task_outcomes(tt_value, limit=10)

                # Check adaptation gate
                should_adapt, gate_analysis = StrategyAdaptationGate.should_adapt(
                    task_type=tt_value,
                    executions=total_execs,
                    wins=total_wins,
                    recent_outcomes=recent_outcomes,
                )

                # Log gate analysis for transparency
                logger.info(f"[IDLE:METALEARNING] {tt_value} adaptation gate: {gate_analysis['decision']}")
                logger.debug(f"  Analysis: {gate_analysis}")

                if should_adapt:
                    # Trigger adaptation
                    try:
                        await self.meta_learning.adapt_strategies(family)
                        adapted += 1

                        reason = gate_analysis.get("adaptation_reason", "low_performance")
                        logger.info(
                            f"[IDLE:METALEARNING] Adapted strategies for {tt_value} "
                            f"(reason: {reason}, execs: {total_execs}, wins: {total_wins})"
                        )

                        # Store detailed adaptation event to META memory
                        await self.store_memory(
                            MemoryType.META,
                            {
                                "event": "strategy_adaptation",
                                "task_type": tt_value,
                                "reason": reason,
                                "gate_analysis": gate_analysis,
                                "timestamp": datetime.now().isoformat(),
                            },
                            importance=0.7,
                            tags=["meta_learning", "strategy_adaptation"],
                        )

                    except Exception as e:
                        logger.warning(f"[IDLE:METALEARNING] Adaptation error for {tt_value}: {e}")
                else:
                    logger.debug(
                        f"[IDLE:METALEARNING] {tt_value} adaptation gate rejected: "
                        f"reason={gate_analysis['checks_failed']}"
                    )

                evaluation_results[tt_value] = gate_analysis

            except Exception as e:
                logger.debug(f"[IDLE:METALEARNING] Error evaluating {tt_value}: {e}")
                evaluation_results[tt_value] = f"error: {e}"

        logger.info(
            f"[IDLE:METALEARNING] Evaluation complete — "
            f"{len(evaluation_results)} types reviewed, {adapted} adapted"
        )

        # Second-order governance: watch whether the meta-learner is degrading
        # its own standards. MetaMetricsMonitor had zero callers, so nothing
        # ever checked the checker -- and it could not have answered anyway
        # (its db handle was an un-awaited coroutine). Both are fixed; this is
        # the call site.
        try:
            from core.learning.meta_metrics_monitor import get_meta_metrics_monitor

            health = await get_meta_metrics_monitor().get_meta_health(self.meta_learning)
            if health:
                level = {"CRITICAL": logger.error, "DEGRADED": logger.warning}.get(
                    health.overall_health, logger.info
                )
                level(
                    f"[IDLE:METALEARNING] Meta-learner health: {health.overall_health} "
                    f"(stability {health.standards_stability_score:.0f}/100, "
                    f"{len(health.alerts)} alerts, {len(health.warnings)} warnings)"
                )
                for a in health.alerts:
                    logger.warning(f"[IDLE:METALEARNING]   alert: {a}")
                if health.overall_health == "CRITICAL" and self.slack_notifier:
                    await self.slack_notifier.send_notification(
                        title="🚨 Meta-Learner Standards Degraded",
                        message=(
                            f"*Health:* {health.overall_health}\n"
                            f"*Stability:* {health.standards_stability_score:.0f}/100\n"
                            + "\n".join(f"• {a}" for a in health.alerts[:5])
                        ),
                        severity="critical",
                        metadata={"subsystem": "meta_learning"},
                    )
        except Exception as e:
            logger.warning(f"[IDLE:METALEARNING] Meta-health check failed: {e}")



    # ── TIER 5: Memory consolidation — multi-strategy with fallbacks ──────────

    async def _idle_abstraction_work(self):
        """Tier: compress repeated experience into persistent schemas.

        The admission policy lives on the memory agent, which owns the data the
        decision depends on. This tier only supplies the schedule and surfaces
        the outcome -- including the reason a run was declined, so a tier that
        never does anything is visible rather than silently idle.
        """
        memory_agent = getattr(self, 'memory_agent', None)
        if memory_agent is None:
            try:
                from core.memory import get_memory_agent
                memory_agent = await get_memory_agent()
            except Exception as e:
                logger.debug(f"[IDLE:ABSTRACTION] Memory agent unavailable: {e}")
                return {'ran': False, 'reason': 'no_memory_agent'}

        if not hasattr(memory_agent, 'form_abstractions_if_due'):
            logger.debug("[IDLE:ABSTRACTION] Memory agent has no abstraction entry point")
            return {'ran': False, 'reason': 'no_entry_point'}

        report = await memory_agent.form_abstractions_if_due()

        if report.get('ran'):
            logger.info(
                f"[IDLE:ABSTRACTION] {report.get('schemas_formed', 0)} schema(s) from "
                f"{report.get('new_memories', 0)} new memories "
                f"(backlog {report.get('backlog', 0)})"
            )
        else:
            logger.debug(f"[IDLE:ABSTRACTION] Skipped: {report.get('reason')}")

        return report

    async def _idle_memory_work(self):
        """
        Run memory consolidation using the ordered strategy list from the playbook.

        Fixes:
          - Previously only tried llm._autonomous_memory_consolidation() — no fallback
          - If that method was absent the tier silently did nothing
          - No tier-upgrade pass (high-importance short-term → long-term)
          - No audit trail of consolidation activity
          - LLM consolidation now guarded with timeout to prevent compute spikes
        """
        from .idle_work_playbook import IdleWorkPlaybook, ConsolidationStrategy

        playbook = IdleWorkPlaybook()

        uptime_hours = (datetime.now() - self.last_cycle_time).total_seconds() / 3600.0

        # No model-driven consolidation exists; consolidation is the memory
        # agent's own tiering, driven by the strategies below.
        strategies = playbook.plan_memory_consolidation(
            llm_has_consolidation_method = False,
            uptime_hours                 = uptime_hours,
        )

        logger.info(
            f"[IDLE:MEMORY] Running consolidation — "
            f"strategies: {[s.value for s in strategies]}"
        )

        consolidated = False
        for strategy in strategies:
            try:
                if strategy == ConsolidationStrategy.TIER_UPGRADE:
                    # Promote high-importance short-term memories to long-term
                    # by searching and re-storing them with elevated importance
                    try:
                        recent = await self.search_memories(
                            query_text   = "important insight knowledge decision",
                            memory_types = [MemoryType.EPISODIC, MemoryType.SEMANTIC],
                        )
                        upgraded = 0
                        # Limit to configured max items per cycle
                        max_items = self.coordinator_config.memory_consolidation_max_items
                        for mem in (recent or [])[:max_items]:
                            importance = getattr(mem, 'importance', 0.0)
                            age_days   = (
                                datetime.now() - getattr(mem, 'created_at', datetime.now())
                            ).days if hasattr(mem, 'created_at') else 0
                            if importance >= 0.7 and age_days >= 1:
                                await self.store_memory(
                                    MemoryType.META,
                                    {
                                        "event":    "tier_upgrade",
                                        "content":  getattr(mem, 'content', {}),
                                        "original_importance": importance,
                                        "timestamp": datetime.now().isoformat(),
                                    },
                                    importance = importance,
                                    tags       = ["consolidation", "tier_upgrade"],
                                )
                                upgraded += 1
                        if upgraded:
                            logger.info(f"[IDLE:MEMORY] Tier upgrade: {upgraded} memories promoted")
                        consolidated = True
                    except Exception as e:
                        logger.debug(f"[IDLE:MEMORY] Tier upgrade error: {e}")

                elif strategy == ConsolidationStrategy.SUMMARY_WRITE:
                    # Audit trail is handled by logger.info below
                    pass

            except Exception as e:
                logger.warning(f"[IDLE:MEMORY] Strategy {strategy.value} error: {e}")

        logger.info(f"[IDLE:MEMORY] Consolidation pass complete (consolidated={consolidated})")

    async def _run_exploration_cycle(self):
        """
        Generate and execute ONE curiosity-driven intrinsic exploration task.

        SINGLETON MODEL: Only one task runs at a time. The Singleton focuses
        its full attention on each task. If the task requires parallel work
        (research, code analysis, multiple investigations), the executor
        deploys sub-agents internally — like how Claude deploys research
        agents, code helpers, and investigators within a single task.

        No fire-and-forget. No concurrent intrinsic tasks.
        """
        try:
            from .shared_types import Task, TaskType, TaskSource, Priority
            from .idle_work_playbook import IdleWorkPlaybook

            playbook = IdleWorkPlaybook()

            # Build set of recent fingerprints to avoid repeating recent work
            # Use ordered list so FIFO trimming works correctly (there are only 4 unique
            # exploration targets — an unordered set would block all 4 permanently).
            recent_fp_list: list = list(getattr(self, '_recent_exploration_fp_list', []))
            recent_fingerprints: set = set(recent_fp_list)

            # Global cap + in-flight dedup are based on the task queue state.
            # This prevents queue spam while a long-running intrinsic task is executing.
            cap = int(getattr(self, "_intrinsic_exploration_cap", 1) or 0)
            if cap == 0:
                logger.debug("🧘 Intrinsic exploration disabled (cap=0)")
                return

            # Curiosity is queue-aware. Exploration is the most discretionary
            # work the system produces, so it is the first thing to stop when
            # the backlog grows -- otherwise the organism keeps inventing work
            # it cannot metabolise, which is debt generation rather than
            # autonomy. Obligatory work (safety, remediation, user-directed)
            # is unaffected; it is admitted at every pressure level.
            _pressure = self.task_queue.pressure()
            if _pressure != "nominal":
                logger.info(
                    f"🧘 Exploration suspended — queue pressure '{_pressure}' "
                    f"(depth {self.task_queue.get_queue_length()}, "
                    f"soft={self.task_queue.soft_limit}, hard={self.task_queue.hard_limit})"
                )
                return

            active_exploration_components: Set[str] = set()
            active_exploration_fps: Set[str] = set()
            active_exploration_count = 0
            try:
                for queued in getattr(self.task_queue, "tasks_by_id", {}).values():
                    if not queued:
                        continue
                    if queued.status not in (TaskStatus.PENDING, TaskStatus.IN_PROGRESS):
                        continue

                    queued_task = getattr(queued, "task", None)
                    if not queued_task or getattr(queued_task, "source", None) != TaskSource.AUTONOMOUS:
                        continue

                    metadata = getattr(queued_task, "metadata", {}) or {}
                    if metadata.get("intrinsic_kind") != "exploration":
                        continue

                    active_exploration_count += 1
                    comp = metadata.get("target_component")
                    if comp:
                        active_exploration_components.add(comp)
                    fp_active = metadata.get("exploration_fp")
                    if fp_active:
                        active_exploration_fps.add(fp_active)
            except Exception as _scan_err:
                logger.debug(f"Exploration cap scan failed: {_scan_err}")

            if active_exploration_count >= cap:
                logger.debug(
                    f"🧘 Exploration queue full ({active_exploration_count}/{cap}) — skipping exploration cycle"
                )
                return

            # Collect system context and generate goals
            system_context  = await self._collect_system_context_for_goals()

            # ── APPRAISAL -> ARBITER -> BEHAVIOUR ─────────────────────────────
            # The canonical appraisal decides disposition; the arbiter decides
            # what that disposition means here. plan_exploration_config is a
            # translator, not a third interpreter. Breadth was hardcoded to 3.
            _explore_cfg = None
            try:
                # Ask the Self for disposition — it owns appraisal→arbiter and
                # integrates them. The body no longer computes its own stance;
                # it asks its head "what is my disposition now?".
                _directive = self.disposition(
                    slots_available=max(0, cap - len(recent_fp_list) * 0),
                    queue_pressure=_pressure,
                )
                _explore_cfg = playbook.plan_exploration_config(
                    motivation={},
                    active_task_descriptions=recent_fingerprints,
                    exploring_components=set(),
                    max_concurrent=cap,
                    current_intrinsic_count=0,
                    directive=_directive,
                )
                logger.info(
                    "🧭 Behaviour: mode=%s explore=%s goals=%d verify=%.2f %s",
                    _directive.mode, _directive.should_explore,
                    _explore_cfg["max_goals"], _directive.verification_intensity,
                    _directive.reason_codes,
                )
                if not _explore_cfg["should_explore"]:
                    # An arbiter that says "not now" is a real decision, not an
                    # error. Escalation-dominant states must not thrash through
                    # self-directed exploration.
                    logger.info("🧘 Exploration declined by arbiter (%s)", _directive.mode)
                    self._exploration_status = "DECLINED_BY_ARBITER"
                    return
            except Exception as _arb_err:
                # No appraisal yet, or arbitration failed: fall back to the
                # previous fixed breadth rather than blocking exploration.
                logger.debug("Behaviour arbitration unavailable: %s", _arb_err)

            _max_goals = _explore_cfg["max_goals"] if _explore_cfg else 3

            intrinsic_goals = await self.intrinsic_motivation.generate_curiosity_driven_goals(
                max_goals      = _max_goals,  # governed by appraisal, was hardcoded 3
                system_context = system_context,
            )

            if not intrinsic_goals:
                logger.debug("🧘 System stable — no exploration targets identified")
                return

            # Pick the first goal that passes dedup filters
            selected_goal = None
            selected_component = None
            selected_fp = None

            for goal in intrinsic_goals:
                _component = goal.metadata.get("target_component") if hasattr(goal, 'metadata') else None

                # In-flight component lock — don't re-explore something already queued/running
                if _component and _component in active_exploration_components:
                    logger.debug(f"⏭️ Skipping {_component}: already queued/in progress")
                    continue

                # Fingerprint dedup
                fp = playbook.description_fingerprint(goal.description)
                if fp in active_exploration_fps:
                    logger.debug(f"⏭️ Skipping duplicate in-flight goal (fp={fp})")
                    continue
                if fp in recent_fingerprints:
                    logger.debug(f"⏭️ Skipping duplicate goal description (fp={fp})")
                    continue
                if fp in getattr(self, '_permanently_failed_fps', set()):
                    logger.debug(f"⏭️ Skipping permanently-failed goal (fp={fp}) — will not re-queue")
                    continue

                selected_goal = goal
                selected_component = _component
                selected_fp = fp
                break

            if not selected_goal:
                logger.debug("🧘 All generated goals were duplicates or filtered — no new tasks")
                return

            # Track as ordered list (FIFO, max 3) so oldest fingerprint rotates out.
            # With only 4 unique exploration targets, a window of 3 guarantees at least
            # one target is always available on every cycle.
            recent_fp_list.append(selected_fp)
            if len(recent_fp_list) > 20:
                recent_fp_list = recent_fp_list[-20:]
            self._recent_exploration_fp_list = recent_fp_list
            self._recent_exploration_fingerprints = set(recent_fp_list)  # kept for compat

            # EVENT-TRIGGERED HYPOTHESIS: the moment a curiosity goal is ADOPTED,
            # make it falsifiable — convert it to a testable hypothesis (through
            # the reasoning authority). Per-goal on adoption, NOT a batch swept on
            # a timer: an adopted exploration goal that carries no falsifiable
            # claim is a wish, not an experiment. Scheduled on the queue
            # authority's background budget so it never slows goal→task, and it is
            # fire-once per adoption (dedup already guaranteed this goal is new).
            try:
                from core.agents.autonomous.queue_authority import get_queue_authority
                _goal_for_hyp = {
                    "id": getattr(selected_goal, "id", None),
                    "description": getattr(selected_goal, "description", ""),
                    "component": selected_component or "system",
                    "objective_type": (selected_goal.metadata.get("objective_type", "explore")
                                       if hasattr(selected_goal, "metadata") else "explore"),
                }
                get_queue_authority().submit(
                    lambda g=_goal_for_hyp: self.intrinsic_motivation.convert_goal_to_hypothesis(g),
                    name="goal_to_hypothesis")
            except Exception as _he:
                logger.debug("goal→hypothesis scheduling skipped: %s", _he)

            # Build the intrinsic task.
            # The sink is local, so this decision can only ever be bound to the
            # task built from it — no shared slot for a concurrent selection to
            # overwrite, and no stale id to leak onto the next task.
            _type_decision: Dict[str, Any] = {}
            task_type = await self._select_adaptive_task_type(
                selected_goal.description, _decision_sink=_type_decision
            )
            # PERSIST THE GOAL BEFORE TURNING IT INTO A TASK.
            #
            # The four intrinsic generators build real Goal objects, and every
            # one of them was discarded here: the description was copied onto a
            # Task and the Goal itself never reached create_goal, so it was
            # never written to unified.goals and the PlanningEngine never saw
            # it. Motivation went straight to execution, skipping planning
            # entirely, and the goal store stayed empty while 886 intrinsic
            # motivation rows accumulated. Verified by running each generator
            # against the live database: create_goal added a row, all four
            # intrinsic generators added none.
            #
            # Persisting first also means the task and the goal share an id, so
            # the outcome of the task is attributable to the goal that produced
            # it rather than being an orphan.
            persisted_goal = await self.planning.create_goal(
                selected_goal.description,
                Priority.LOW,
                intrinsic_values={
                    "expected_novelty": getattr(selected_goal, "expected_novelty", 0.5),
                    "expected_competence_gain": getattr(
                        selected_goal, "expected_competence_gain", 0.5),
                    "curiosity_value": getattr(selected_goal, "curiosity_value", 0.5),
                    "intrinsic_reward_potential": getattr(
                        selected_goal, "intrinsic_reward_potential", 0.5),
                },
            )
            if persisted_goal is None:
                # A goal that could not be stored must not become a task: the
                # task would run, complete, and have nothing to report against.
                logger.warning(
                    "Intrinsic goal could not be persisted (%s); not queueing a "
                    "task for it", selected_goal.description[:80])
                return

            intrinsic_task = Task(
                id          = persisted_goal.id,
                type        = task_type,
                description = persisted_goal.description,
                priority    = Priority.LOW,
                source      = TaskSource.AUTONOMOUS,
                created_by  = "exploration_loop",
            )
            intrinsic_task.metadata["goal_id"] = persisted_goal.id

            # Mark as intrinsic exploration for global cap/dedup (Known Gap 25.2)
            intrinsic_task.metadata["intrinsic_kind"] = "exploration"
            intrinsic_task.metadata["exploration_fp"] = selected_fp

            # Carry the DRIVE and its concrete target forward. A competence or
            # confidence goal names a real operator/domain to act on and re-induce;
            # dropping this metadata is what left those goals as free-form
            # descriptions the generic executor could not act on. The dedicated
            # handler (_execute_drive_goal) reads exactly these fields.
            _gm = selected_goal.metadata if hasattr(selected_goal, "metadata") else {}
            for _k in ("drive", "domain_id", "predicate", "arity", "rule_id",
                       "scope", "positive_root_count"):
                if _k in _gm:
                    intrinsic_task.metadata[_k] = _gm[_k]

            # Carry the decision forward so _check_task_completions can reward it.
            # Selecting a task type without ever reporting how it turned out is a
            # half loop: the bandit would sample forever from an untouched prior.
            intrinsic_task.metadata["adaptive_task_type"] = task_type.value
            intrinsic_task.metadata["adaptive_selected_at"] = datetime.now().isoformat()
            # Carries the decision-record id so the outcome joins back to the
            # propensities and context captured at decision time.
            intrinsic_task.metadata["decision_id"] = _type_decision.get("decision_id")

            # Attach uncertainty metadata for closed-loop completion gate
            if selected_component:
                u_before = selected_goal.metadata.get("uncertainty_before", 0.0)
                intrinsic_task.metadata["target_component"] = selected_component
                intrinsic_task.metadata["uncertainty_before"] = u_before
                intrinsic_task.success_criteria = {
                    "uncertainty_delta_max": -(0.1 * u_before) if u_before > 0 else -0.05
                }

            # Add to task queue instead of executing directly
            logger.info(f"🔬 Queueing exploration task: {selected_goal.id}")
            await self.task_queue.add_task(intrinsic_task, priority=Priority.LOW)
            # Note: Global cap + in-flight dedup are derived from task_queue state; no sticky locks.

        except Exception as e:
            logger.error(f"Error in exploration cycle: {e}")
            await self._handle_error(e, "exploration_cycle")

    async def _idle_self_optimization_work(self) -> None:
        """Consider self-optimization — only on NEW motivational evidence.

        Replaces `_periodic_performance_assessment`, which was deprecated in
        favour of curiosity-driven optimization but never removed. The migration
        had stopped halfway: the timer was dead, and the ONLY call to
        `_curiosity_driven_optimization()` lived inside that dead timer. Its own
        docstring claimed the trigger had moved "to the main coordination loop";
        it had not. Self-optimization had therefore never run at all — and the
        deprecation note is what stopped anyone looking.

        Gating is by motivational STATE CHANGE, not elapsed time. The same
        unchanged motivation must not make Torin repeatedly decide to improve
        itself; a fixed cadence would also be a second trigger authority
        competing with the motivation signals that are supposed to decide this.

        Curiosity buys CONSIDERATION, not permission — validation, governance
        and safety remain downstream and unchanged.
        """
        self._idle_self_optimization_status = "SKIPPED"
        try:
            if getattr(self, '_optimization_running', False):
                self._idle_self_optimization_status = "ALREADY_RUNNING"
                return

            # Real work outranks self-improvement.
            try:
                if self.task_queue and self.task_queue.pressure() != "nominal":
                    self._idle_self_optimization_status = "DEFERRED_QUEUE_PRESSURE"
                    logger.debug("[IDLE:SELF_OPT] deferred — queue pressure")
                    return
            except Exception:
                pass

            motivation = getattr(self, '_current_motivation', None)
            if not motivation:
                self._idle_self_optimization_status = "NO_MOTIVATION_STATE"
                return

            # State fingerprint: only NEW qualifying evidence may trigger.
            dims = motivation.get('dimensions', {}) or {}
            fingerprint = tuple(
                round(float(dims.get(k, 0.0) or 0.0), 3)
                for k in ('curiosity', 'impact', 'competence', 'novelty')
            )
            if fingerprint == getattr(self, '_last_optimization_fingerprint', None):
                self._idle_self_optimization_status = "NO_NEW_MOTIVATION_EVIDENCE"
                return
            self._last_optimization_fingerprint = fingerprint

            threshold = float(self.config.get("curiosity_optimization_threshold", 0.7))
            if not self._should_trigger_curiosity_optimization(threshold):
                self._idle_self_optimization_status = "BELOW_THRESHOLD"
                logger.debug("[IDLE:SELF_OPT] motivation changed but below threshold: %s", fingerprint)
                return

            logger.info("[IDLE:SELF_OPT] qualifying motivation change %s — considering optimization", fingerprint)
            await self._curiosity_driven_optimization()
            self._idle_self_optimization_status = "COMPLETED"

        except Exception as e:
            self._idle_self_optimization_status = f"ERROR: {type(e).__name__}"
            logger.error("[IDLE:SELF_OPT] failed: %s", e, exc_info=True)
        finally:
            # Never leave the in-flight flag stuck; a crashed optimization must
            # not permanently disable all future self-improvement.
            self._optimization_running = False

    def _should_trigger_curiosity_optimization(self, threshold: float) -> bool:
        """Check if curiosity/novelty signals are high enough to trigger optimization."""
        try:
            motivation = getattr(self, '_current_motivation', {})
            dims = motivation.get('dimensions', {})
            curiosity = dims.get('curiosity', 0.5)
            impact = dims.get('impact', 0.5)
            competence = dims.get('competence', 0.5)

            # Trigger when curiosity is high AND (impact or competence suggests room for improvement)
            should_trigger = (
                curiosity >= threshold
                and (impact >= 0.6 or competence >= 0.6)
                and not getattr(self, '_optimization_running', False)
            )

            # Rate limit: at most once per 30 minutes
            if should_trigger:
                last_opt = getattr(self, '_last_curiosity_optimization', None)
                if last_opt and (datetime.now() - last_opt).total_seconds() < 1800:
                    return False

            return should_trigger
        except Exception:
            return False

    async def _curiosity_driven_optimization(self):
        """Run optimization driven by curiosity signals, not a fixed timer."""
        if not self.asi_self_improvement:
            return

        self._optimization_running = True
        self._last_curiosity_optimization = datetime.now()

        try:
            from core.learning import ImprovementScope

            motivation = getattr(self, '_current_motivation', {})
            dims = motivation.get('dimensions', {})

            logger.info("="  * 80)
            logger.info("🔬 CURIOSITY-DRIVEN OPTIMIZATION (triggered by motivation signals)")
            logger.info(f"   Curiosity: {dims.get('curiosity', 0):.2f}")
            logger.info(f"   Impact: {dims.get('impact', 0):.2f}")
            logger.info(f"   Competence: {dims.get('competence', 0):.2f}")
            logger.info("=" * 80)

            result = await self.asi_self_improvement.run_improvement_cycle(
                scope=ImprovementScope.MINOR,
                target_components=[],
                context={
                    "trigger": "curiosity_driven_optimization",
                    "motivation_state": dims,
                    "timestamp": datetime.now().isoformat(),
                    "mode": "exploration_optimization"
                }
            )

            logger.info(f"📊 Curiosity optimization complete: "
                        f"{result.improvements_deployed} deployed, "
                        f"{result.success_rate:.0%} success rate")

            if self.slack_notifier and result.improvements_deployed > 0:
                await self.slack_notifier.send_notification(
                    title="🔬 Curiosity-Driven Optimization",
                    message=(
                        f"**Triggered by:** High curiosity ({dims.get('curiosity', 0):.2f})\n"
                        f"**Improvements Deployed:** {result.improvements_deployed}\n"
                        f"**Success Rate:** {result.success_rate:.0%}"
                    ),
                    severity="info",
                    metadata={"trigger": "curiosity", "improvements": result.improvements_deployed}
                )

        except Exception as e:
            logger.error(f"Curiosity-driven optimization failed: {e}")
            import traceback
            traceback.print_exc()
        finally:
            self._optimization_running = False

    async def _handle_error(self, error: Exception, source: str):
        """
        Handle errors by creating fix tasks directly.
        No intrinsic motivation. No hypothesis testing. Just fix it.
        """
        import traceback as tb_module
        import uuid
        from .shared_types import Task, TaskType, Priority, TaskSource

        error_type = type(error).__name__
        error_msg = str(error)
        traceback_str = tb_module.format_exc()[:500]

        # Create fix task directly (TaskSource.SYSTEM, not AUTONOMOUS)
        fix_task = Task(
            id=f"fix_{uuid.uuid4().hex[:12]}",
            type=TaskType.EXECUTION,  # Fix task
            description=f"Fix {error_type} in {source}: {error_msg}",
            priority=Priority.HIGH,  # Errors are high priority
            source=TaskSource.SYSTEM,  # System-generated, not autonomous
            created_by="error_handler",
            metadata={
                'error_type': error_type,
                'error_message': error_msg,
                'source': source,
                'traceback': traceback_str,
                'timestamp': datetime.now().isoformat(),
                'is_error_fix': True
            }
        )

        # Add to task queue immediately
        await self.task_queue.add_task(fix_task)
        logger.info(f"🔧 Created fix task {fix_task.id} for {error_type} in {source}")


    # Horizon → seconds after which a prediction becomes checkable.
    _HORIZON_SECONDS = {
        "immediate": 30,
        "short_term": 300,
        "medium_term": 3600,
        "long_term": 86400,
    }

    async def _observe_system_performance(self) -> Optional[float]:
        """The observable a SYSTEM_PERFORMANCE prediction is scored against.

        Fraction of components reporting healthy, in [0,1] to match the
        accuracy arithmetic in validate_prediction.
        """
        if not self.monitoring_coordinator:
            return None
        try:
            health = await self.monitoring_coordinator.check_system_health()
            if not health or not health.total_components:
                return None
            return health.healthy_components / float(health.total_components)
        except Exception as e:
            logger.debug(f"Could not observe system performance: {e}")
            return None

    async def _predict_and_resolve_system_state(self):
        """Close the world-model loop: predict → wait → observe → score.

        PredictiveIntelligenceSystem.validate_prediction() computes real error
        and confidence calibration, and had zero callers -- as did both
        prediction *producers*. Torin therefore never predicted anything and
        never compared a prediction to reality, so its forecasting was
        analytics rather than a world model that can be wrong and learn from it.

        Resolution happens first so a prediction is never scored against the
        same observation that produced it.
        """
        if not self.intelligence:
            return

        # ── Resolve any predictions whose horizon has elapsed ──
        active = dict(getattr(self.intelligence, "active_predictions", {}) or {})
        now = datetime.now()
        for pid, prediction in active.items():
            try:
                due_after = self._HORIZON_SECONDS.get(prediction.horizon.value, 300)
                if (now - prediction.timestamp).total_seconds() < due_after:
                    continue

                actual = await self._observe_system_performance()
                if actual is None:
                    continue

                result = await self.intelligence.validate_prediction(pid, actual)
                logger.info(
                    "🔮 Prediction %s resolved: predicted=%.3f actual=%.3f "
                    "accuracy=%.3f calibration=%.3f",
                    pid,
                    float(prediction.predicted_value)
                    if isinstance(prediction.predicted_value, (int, float)) else -1.0,
                    actual, result.accuracy, result.confidence_calibration,
                )
                await self._persist_prediction_result(prediction, result, actual)
            except Exception as e:
                logger.warning(f"Could not resolve prediction {pid}: {e}")

        # ── Make a fresh prediction to be scored on a later cycle ──
        try:
            from core.intelligence import PredictionDomain, PredictionHorizon

            await self.intelligence.generate_comprehensive_prediction(
                PredictionDomain.SYSTEM_PERFORMANCE,
                PredictionHorizon.SHORT_TERM,
                await self._decision_context("system performance forecast"),
            )
        except Exception as e:
            logger.warning(f"Could not generate system-performance prediction: {e}")

    async def _persist_prediction_result(self, prediction, result, actual) -> None:
        """Store the scored prediction so calibration outlives the process.

        active_predictions is an in-memory dict; without this the entire
        accuracy record dies with the process and the world model can never
        show whether it is getting better.
        """
        try:
            from core.database import get_database_manager
            db = get_database_manager()
            await db.execute_query(
                """
                CREATE TABLE IF NOT EXISTS prediction_results (
                    prediction_id   VARCHAR(128) PRIMARY KEY,
                    domain          VARCHAR(64) NOT NULL,
                    horizon         VARCHAR(32) NOT NULL,
                    predicted_value DOUBLE PRECISION,
                    actual_value    DOUBLE PRECISION,
                    confidence      NUMERIC(6,4),
                    accuracy        NUMERIC(6,4),
                    calibration     NUMERIC(6,4),
                    predicted_at    TIMESTAMP,
                    resolved_at     TIMESTAMP NOT NULL DEFAULT NOW()
                )
                """,
                commit=True,
            )
            await db.execute_query(
                """
                INSERT INTO prediction_results (
                    prediction_id, domain, horizon, predicted_value, actual_value,
                    confidence, accuracy, calibration, predicted_at
                ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
                ON CONFLICT (prediction_id) DO NOTHING
                """,
                (
                    result.prediction_id,
                    prediction.domain.value,
                    prediction.horizon.value,
                    float(prediction.predicted_value)
                    if isinstance(prediction.predicted_value, (int, float)) else None,
                    float(actual),
                    float(prediction.confidence),
                    float(result.accuracy),
                    float(result.confidence_calibration),
                    prediction.timestamp,
                ),
                commit=True,
            )
        except Exception as e:
            logger.warning(f"Could not persist prediction result: {e}")

    async def _decision_context(self, description: str = "") -> Dict[str, Any]:
        """Snapshot the state a decision is being made in.

        Recorded alongside the decision so credit can later be assigned
        conditionally -- "RESEARCH works 89% of the time *under high epistemic
        uncertainty on an unknown subsystem*" rather than "RESEARCH works 74%
        of the time". Every field here is already computed elsewhere in the
        coordinator each cycle and then discarded; this is the first thing that
        keeps it.

        Deliberately cheap: reads cached state only, never triggers a scan.
        """
        dims = (getattr(self, "_current_motivation", {}) or {}).get("dimensions", {})
        health = (getattr(self, "_idle_last_health_snapshot", {}) or {})
        security = (getattr(self, "_idle_last_security_findings", {}) or {})

        return {
            "description_len": len(description or ""),
            "curiosity": dims.get("curiosity"),
            "novelty": dims.get("novelty"),
            "competence": dims.get("competence"),
            "impact": dims.get("impact"),
            "health_components_total": health.get("components_total"),
            "health_unhealthy_total": health.get("unhealthy_total"),
            "security_findings_total": security.get("total"),
            "active_goals": len(self.system_state.active_goals)
            if getattr(self, "system_state", None) else None,
            "active_tasks": len(self.system_state.active_tasks)
            if getattr(self, "system_state", None) else None,
            "idle_cycles": getattr(self, "_idle_count", None),
            "queue_depth": self.task_queue.queue.qsize()
            if getattr(self, "task_queue", None) else None,
            "recent_failure_fps": len(getattr(self, "_permanently_failed_fps", set())),
            "uptime_s": int(
                datetime.now().timestamp() - float(getattr(self, "_started_at_ts", 0) or 0)
            ) if getattr(self, "_started_at_ts", None) else None,
        }

    def _task_family_for(self, task_type) -> 'TaskFamily':
        """Map a coordinator TaskType onto the meta-learner's TaskFamily.

        The coordinator speaks TaskType (11 values, about what work to do);
        MetaLearner keys strategies by TaskFamily (8 values, about the kind of
        learning problem). Nothing translated between them, which is why every
        cross-system call passed the wrong vocabulary.

        DELEGATED, NOT DUPLICATED. The table now lives beside TaskFamily as
        `meta_learning.TASK_TYPE_TO_FAMILY`, because UnifiedLearningSystem needs
        the same translation and could not reach a dict held in this class.

        A KeyError is still raised for an unknown type, as before: this caller
        has a real TaskType in hand, so an unmapped one is a defect in the map
        and must not be quietly turned into some default family.
        """
        from core.learning.meta_learning import task_family_for_task_type

        family = task_family_for_task_type(task_type)
        if family is None:
            raise KeyError(
                f"No TaskFamily mapped for task type {task_type!r}; add it to "
                f"meta_learning.TASK_TYPE_TO_FAMILY")
        return family

    async def _record_adaptive_type_outcome(
        self,
        task,
        success: bool,
        outcome_class: str = "executed",
        time_ms: float = 0.0,
    ) -> None:
        """Report the outcome of an adaptive task-type choice to the meta-learner.

        The reward half of _select_adaptive_task_type. Only tasks that carry the
        decision (exploration tasks) are recorded -- every other task had its
        type assigned elsewhere, so there is no decision to credit.

        ``success`` is passed in rather than derived from task.status because
        the authoritative terminal outcome differs by path: the queue path
        establishes it as ``is_complete`` (verification state + uncertainty
        gate) inside _execute_and_validate_task, well before any status field
        is written. Deriving it here would credit the wrong signal.

        ``outcome_class`` distinguishes a task that ran and failed from one
        that safety refused to run. Both are negative evidence for the arm, but
        they are different kinds of negative, and the context records which.
        """
        chosen = (task.metadata or {}).get("adaptive_task_type")
        if not chosen or not self.meta_learning:
            return

        from core.learning.meta_learning import TaskFamily
        from core.learning.meta_learning import OutcomeClass

        # Map the coordinator's terminal states onto the credit taxonomy. Only
        # outcomes that are genuinely evidence about the task-type choice may
        # move its posterior.
        klass = {
            "verified": OutcomeClass.SUCCESS,
            "unverified": OutcomeClass.STRATEGY_FAILURE,
            "safety_blocked": OutcomeClass.SAFETY_BLOCKED,
            "infrastructure": OutcomeClass.INFRASTRUCTURE_FAILURE,
            "invalid": OutcomeClass.INVALID_TASK,
        }.get(outcome_class, OutcomeClass.INDETERMINATE)

        try:
            await self.meta_learning.track_learning_outcome(
                task_type=TaskFamily.CONTROL,
                strategy_type=f"{self.ADAPTIVE_TYPE_NS}{chosen}",
                success=success,
                performance_score=1.0 if success else 0.0,
                time_ms=time_ms,
                outcome_class=klass,
                context={
                    "task_id": task.id,
                    "outcome_class": outcome_class,
                    "source": "adaptive_task_type",
                },
                decision_id=(task.metadata or {}).get("decision_id"),
            )
        except Exception as e:
            logger.warning("Could not record adaptive task-type outcome: %s", e)

        # Feed the same outcome to the experience learner.
        #
        # MetaLearner credits the *strategy family*; LearningAdapter records
        # which concrete action succeeded in which context, which is a
        # different granularity and has no other source. It was constructed at
        # startup (self.learning) and never fed, so its pattern store stayed
        # empty and get_recommendations() could only ever return [].
        await self._record_experience_outcome(task, chosen, success, outcome_class)

    async def _record_experience_outcome(
        self, task: Any, chosen: str, success: bool, outcome_class: str
    ) -> None:
        """Record an action-in-context outcome for the experience learner."""
        adapter = getattr(self, "learning", None)
        if adapter is None or not hasattr(adapter, "integrate_experience"):
            return

        try:
            from .learning_adapter import LearningData

            await adapter.integrate_experience(LearningData(
                context={
                    "task_type": str(chosen),
                    "outcome_class": outcome_class,
                },
                action=str(chosen),
                outcome={"success": success, "outcome_class": outcome_class},
                success=success,
                # Confidence is how certain the *observation* is, not whether
                # it went well -- `success` carries that. Scoring failures 0.0
                # put them under min_confidence (0.3), so every failure was
                # dropped at the door and the pattern store only ever saw
                # successes: a learner that cannot observe failure.
                confidence=1.0,
                timestamp=datetime.now(),
                metadata={"task_id": getattr(task, "id", None)},
            ))
        except Exception as e:
            logger.debug("Could not record experience outcome: %s", e)

    async def _select_adaptive_task_type(
        self,
        description: str,
        _decision_sink: Optional[Dict[str, Any]] = None,
    ) -> 'TaskType':
        """
        Adaptively select task type based on description and learning history.
        Replaces static task type assignment.

        `_decision_sink` receives the decision-record id so the caller can bind
        it to the task it is about to create. It replaces a single
        `self._pending_decision_id` slot, which had two failure modes:

          * orphaning — a decision made on a path that never reached the
            stamping site was recorded with a propensity and could never be
            closed. `tasktype` shows 123 decisions and 2 closed.
          * MIS-ATTRIBUTION, which is worse — the slot was cleared only at the
            stamp, so an early return in between left a stale id that the NEXT
            task picked up. Credit then lands on a decision that produced no
            part of that outcome, and the posterior moves on evidence from
            somewhere else entirely.

        A per-call sink cannot be crossed by another selection, which matters
        now that tasks execute concurrently.
        """
        from .shared_types import TaskType

        desc_lower = description.lower()

        # Use meta-learner if available to select based on historical performance.
        #
        # This passed a dict as the task_type argument. select_strategy keys on
        # TaskFamily via task_strategy_map.get(task_type), so a dict raised
        # "TypeError: unhashable type: 'dict'" on every single call, which the
        # bare `except: pass` hid -- the heuristic below has been the only path
        # ever taken. It also read strategy.name, which LearningStrategy does
        # not have (the field is strategy_type).
        #
        # Choosing which kind of task to run is a CONTROL-family decision, and
        # the coordinator's TaskType set is its strategy vocabulary.
        if self.meta_learning:
            try:
                from core.learning.meta_learning import TaskFamily

                if not self._adaptive_types_registered:
                    for t in TaskType:
                        await self.meta_learning.register_strategy(
                            task_type=TaskFamily.CONTROL,
                            strategy_type=f"{self.ADAPTIVE_TYPE_NS}{t.value}",
                            parameters={"source": "coordinator_task_type"},
                        )
                    self._adaptive_types_registered = True

                sink: Dict[str, Any] = {}
                strategy = await self.meta_learning.select_strategy(
                    TaskFamily.CONTROL,
                    exploration_quota_used=self._calculate_exploration_quota(),
                    strategy_prefix=self.ADAPTIVE_TYPE_NS,
                    decision_context=await self._decision_context(description),
                    _decision_sink=sink,
                )
                if strategy is not None:
                    self._record_exploration_decision(strategy)
                    if _decision_sink is not None:
                        _decision_sink["decision_id"] = sink.get("decision_id")
                    return TaskType(
                        str(strategy.strategy_type)[len(self.ADAPTIVE_TYPE_NS):]
                    )
            except Exception as e:
                logger.warning(
                    "Adaptive task-type selection failed, using heuristic: %s", e
                )

        # Heuristic fallback
        if any(w in desc_lower for w in ['investigate', 'explore', 'discover', 'research', 'unknown']):
            return TaskType.RESEARCH
        elif any(w in desc_lower for w in ['analyze', 'profile', 'measure', 'variance', 'error']):
            return TaskType.ANALYSIS
        elif any(w in desc_lower for w in ['learn', 'understand', 'study', 'pattern']):
            return TaskType.LEARNING
        elif any(w in desc_lower for w in ['optimize', 'improve', 'fix', 'enhance']):
            return TaskType.SYNTHESIS
        elif any(w in desc_lower for w in ['verify', 'validate', 'test', 'check']):
            return TaskType.VALIDATION
        else:
            return TaskType.RESEARCH  # Default to research for exploration

    # _periodic_performance_assessment() DELETED 2026-08-14.
    #
    # It was deprecated in its own docstring in favour of curiosity-driven
    # optimization, but never removed and never started (its only launch site
    # was inside start_background_tasks(), which main.py bypasses). Worse, the
    # ONLY call to _curiosity_driven_optimization() lived inside it — so the
    # replacement was reachable only from the thing it replaced, and
    # self-optimization had never run by either route.
    #
    # Kept as a "safety net" it would have been a SECOND authority deciding when
    # to self-modify, competing with the motivation signals. Replaced by the
    # idle tier _idle_self_optimization_work(), which triggers on CHANGED
    # motivational evidence. If a liveness guarantee is ever needed, it should be
    # an explicit watchdog ("no optimization opportunity evaluated in N events"),
    # not a second mechanism that independently launches optimization.


    async def _execute_and_validate_task(self, task):
        """Execute a task through the substrate's own executor (no model in the
        acting path — the LLM is teacher/helper only), then validate the result
        against the completion protocol before it counts as done."""
        # Bind this task's remediation contract for the duration of the task.
        # A ContextVar, so concurrently-running tasks cannot see each other's
        # authority. No contract => unconstrained, exactly as before.
        _contract_token = None
        try:
            from core.safety.action_contract import ActionContract, set_active_contract
            _c = (task.metadata or {}).get("contract") if getattr(task, "metadata", None) else None
            if _c:
                _contract_token = set_active_contract(
                    _c if isinstance(_c, ActionContract) else ActionContract.from_dict(_c)
                )
        except Exception as _ce:
            logger.warning(f"could not bind action contract for {task.id}: {_ce}")

        try:
            from core.agents.autonomous.task_queue import Task
            logger.info(f"▶️  Executing: {task.id} ({task.priority.name}, {task.source.value})")
            logger.info(f"   Description: {task.description}")
            self.stats["cycles_completed"] = self.stats.get("cycles_completed", 0) + 1

            # SLACK NOTIFICATION: Task started
            if self.slack_notifier:
                import re as _re
                _task_desc = task.description.split('\n')[0][:200]
                _task_desc = _re.sub(r'/[^\s]+', '[file]', _task_desc)
                await self.slack_notifier.send_notification(
                    title="🚀 Task Started",
                    message=(
                        f"*Task ID:* `{task.id}`\n"
                        f"*Task:* {_task_desc}\n"
                        f"*Type:* {task.type.value.replace('_', ' ').title()}\n"
                        f"*Priority:* {task.priority.name.title()}\n"
                        f"*Source:* {task.source.value.replace('_', ' ').title()}"
                    ),
                    severity="info",
                    metadata={
                        "task_id": task.id,
                        "task_type": task.type.value,
                        "source": task.source.value,
                    }
                )

            # Task-level safety evaluation BEFORE execution.
            # Routed through SafetyFramework — the single gate — rather than
            # calling SecurityController directly. Input validation is now a
            # layer inside it, and every evaluation is persisted to
            # `safety_assessments` alongside the tool-level ones.
            try:
                from core.security.safety_framework import get_safety_framework
                approved, safety_eval = await get_safety_framework().evaluate_action(
                    action_id=f"task_{task.id}",
                    action_type=f"task_{task.type.value}",
                    parameters={
                        'task_id': task.id,
                        'task_type': task.type.value,
                        'description': task.description,
                        'source': task.source.value,
                        'priority': task.priority.name,
                    },
                )

                if not approved:
                    reason = "; ".join(safety_eval.violations_detected) or "safety constraint"
                    logger.warning(f"❌ Task {task.id} blocked by safety: {reason}")
                    await self.task_queue.mark_failed(
                        task.id, f"Safety validation failed: {reason}"
                    )

                    # GOVERNANCE FEEDBACK: Store block as META memory for learning
                    await self._store_governance_block_meta_memory(
                        task=task,
                        block_reason=reason,
                        block_type="safety_validation"
                    )

                    # A safety refusal is negative evidence about the decision that
                    # produced it. The safety organ perceives and records the block,
                    # but without this the adaptive policy never pays for repeatedly
                    # proposing work that cannot be run -- perception without credit
                    # assignment. Tagged distinctly from ordinary task failure.
                    await self._record_adaptive_type_outcome(
                        task, success=False, outcome_class="safety_blocked"
                    )

                    return None

                if safety_eval.monitoring_required:
                    logger.info(
                        f"⚠️ Task {task.id} elevated risk "
                        f"({safety_eval.risk_level.value}) — executing with monitoring"
                    )
                else:
                    logger.debug(f"✅ Task {task.id} passed safety validation")

            except Exception as e:
                logger.error(f"Safety validation error for task {task.id}: {e}")
                # Fail-open: a safety-system failure must not halt all autonomous
                # operation. The error is logged; execution proceeds.

            # DOUBT → VERIFICATION (a closed affect loop). The disposition's
            # verification_intensity is the substrate's standing caution, derived
            # from appraisal (low confidence / low control → doubt → caution).
            # Read it NOW, before this task's own outcome moves appraisal, so the
            # bar reflects the doubt carried INTO the task, not the task's own
            # result. It sets how much proof the substrate demands before it will
            # accept a completion: no extra demand when untroubled, up to a near-
            # certainty bar when in deep doubt. This is what discharges doubt —
            # meeting the raised bar accumulates the evidence that, through the
            # outcome→appraisal path, lifts confidence and lowers doubt again.
            _verify_bar = 0.0
            try:
                _vi = float(self.disposition().verification_intensity)  # [0.5, 1.0]
                _verify_bar = 0.85 * max(0.0, min(1.0, (_vi - 0.5) / 0.5))
            except Exception as _vbe:
                logger.debug(f"verification bar unavailable (no appraisal yet?): {_vbe}")

            # Execute through this substrate's OWN executor (substrate-only,
            # model-free); the task's TYPE selects the tool/executor path.
            # A DRIVE goal (competence/confidence) names a concrete operator/domain
            # to learn; it has one correct, deterministic substrate action, so it
            # is routed to the dedicated handler rather than interpreted as a
            # free-form task by the general executor.
            if (task.metadata or {}).get("drive") in ("competence", "confidence"):
                result = await self._execute_drive_goal(task)
            else:
                result = await self.executor.execute_task(task)

            # ================================================================
            # COMPLETION PROTOCOL: Check if executor already verified
            # The general_purpose_executor now uses TaskCompletionValidator
            # If verification passed there, we trust it. Otherwise fallback.
            # ================================================================
            verification_state = result.get('verification_state') if isinstance(result, dict) else None
            completion_score = result.get('completion_score') if isinstance(result, dict) else None
            
            if verification_state == 'verified':
                # Verified by the completion protocol — but the substrate's own
                # doubt can raise the standard of proof above what "verified"
                # cleared. When untroubled (_verify_bar 0.0) this is the old
                # behaviour: any verified result is accepted. Under doubt the bar
                # rises, and a thinly-verified result is held short of "done" —
                # not a failure, an unmet standard the substrate must earn past.
                _score = completion_score if completion_score is not None else 0.85
                if _score + 1e-9 < _verify_bar:
                    is_complete = False
                    confidence = _score
                    issues = [f"held under doubt: verified score {_score:.2f} < required {_verify_bar:.2f}"]
                    logger.info(
                        f"🔎 Task {task.id} verified@{_score:.2f} but the substrate's doubt "
                        f"raises the bar to {_verify_bar:.2f} — more evidence needed before done")
                else:
                    is_complete = True
                    confidence = _score
                    issues = []
                    logger.info(f"✅ Task {task.id} verified by completion protocol (score={_score:.3f})")
            elif verification_state in ['in_progress', 'failed', 'blocked', 'partially_complete']:
                # Verification explicitly failed
                is_complete = False
                confidence = completion_score or 0.0
                issues = result.get('issues', []) if isinstance(result, dict) else []
                logger.warning(f"❌ Task {task.id} verification state: {verification_state}")
            else:
                # No completion-protocol result (verification_state absent/'legacy').
                # The retired SuccessValidator rubber-stamped here: it validated the
                # result DICT (self-attestation), not the world, and returned
                # complete=True for a fabricated completion (proven by test — a
                # claimed-but-missing artifact passed). We do NOT re-introduce
                # self-attestation. An unverified result is honoured only at its own
                # explicit success flag, with capped confidence and flagged as
                # UNVERIFIED — never trusted as a system-verified completion.
                declared_ok = isinstance(result, dict) and result.get('success') is True
                is_complete = declared_ok
                confidence = 0.5 if declared_ok else 0.0
                issues = (['completion not verified by the completion protocol']
                          if declared_ok
                          else [(result.get('error') if isinstance(result, dict) else None)
                                or 'task produced no verified completion'])

            # Uncertainty reduction gate: for autonomous exploration tasks, verify the
            # target component's epistemic_uncertainty actually decreased post-execution.
            # This closes the control loop — completion is metric-driven, not self-declared.
            if is_complete and task.source == TaskSource.AUTONOMOUS:
                _component = task.metadata.get("target_component") if task.metadata else None
                if _component:
                    try:
                        fresh_context = await self._collect_system_context_for_goals()
                        new_metrics = await self.intrinsic_motivation._quantify_component_uncertainties(fresh_context)
                        u_after = new_metrics.get(_component, {}).get("epistemic_uncertainty")
                        u_before = task.metadata.get("uncertainty_before")
                        if u_after is not None and u_before is not None:
                            delta = u_after - u_before
                            threshold = -(0.1 * u_before) if u_before > 0 else -0.05
                            # Store measurements in result for longitudinal analysis
                            if result and isinstance(result, dict):
                                result["uncertainty_before"] = u_before
                                result["uncertainty_after"] = u_after
                                result["uncertainty_delta"] = delta
                            if delta > threshold:
                                logger.warning(
                                    f"🔄 Task {task.id}: {_component} uncertainty Δ {delta:+.3f} "
                                    f"> threshold {threshold:.3f} — insufficient reduction"
                                )
                                is_complete = False
                                issues = [f"Uncertainty delta {delta:+.3f} did not meet threshold {threshold:.3f}"]
                            else:
                                logger.info(
                                    f"✅ {_component} uncertainty: {u_before:.3f} → {u_after:.3f} "
                                    f"(Δ {delta:+.3f}, threshold {threshold:.3f})"
                                )
                    except Exception as _ue:
                        logger.warning(f"Uncertainty gate skipped for {task.id}: {_ue} — accepting LLM validation")

            # Close the task-level safety assessment with the real outcome
            try:
                from core.security.safety_framework import get_safety_framework
                await get_safety_framework().record_outcome(
                    f"task_{task.id}",
                    bool(is_complete),
                    None if is_complete else "; ".join(issues) if issues else "task not verified",
                )
            except Exception as _se:
                logger.debug(f"safety outcome not recorded for task {task.id}: {_se}")

            # Credit the adaptive task-type decision with the SAME authoritative
            # outcome the safety framework just received. This lives here, not in
            # _check_task_completions: that scanner runs only on the legacy
            # _execution_phase path, while every task carrying an adaptive
            # decision is queued and arrives here instead. The channel was
            # severed between the two paths.
            _elapsed_ms = 0.0
            if getattr(task, "started_at", None):
                try:
                    _elapsed_ms = (datetime.now() - task.started_at).total_seconds() * 1000.0
                except TypeError:
                    _elapsed_ms = 0.0
            await self._record_adaptive_type_outcome(
                task,
                success=bool(is_complete),
                outcome_class="verified" if is_complete else "unverified",
                time_ms=_elapsed_ms,
            )

            # A task outcome is a fitness-relevant EVENT — the substrate reacts
            # to it here. Emitting TASK_COMPLETED runs the registered reactions;
            # affect is one of them (it reads the substrate's own appraisal and
            # fitness, decays on read — a persistent property of the substrate,
            # not something the environment supplies). Event-driven, not a loop;
            # each reaction is isolated inside emit(), so a fault is logged and
            # never halts the pipeline. Fires for every outcome (complete or
            # not), exactly as the affect poke did before.
            await self.emit(SelfEvent(
                SelfEventType.TASK_COMPLETED,
                payload={"task_id": task.id, "task": task, "result": result,
                         "confidence": confidence,
                         "is_complete": bool(is_complete)},
                origin="_execute_and_validate_task"))

            if is_complete:
                await self.task_queue.mark_completed(task.id, result)
                self.stats["tasks_completed"] += 1
                logger.info(f"✅ Task completed: {task.id} (confidence: {confidence:.2f})")

                # META MEMORY: Store task success for learning
                _meta_id = await self._store_task_outcome_meta_memory(
                    task=task,
                    outcome="success",
                    confidence=confidence,
                    result_summary=str(result)[:500] if result else None
                )

                # The outcome is now durable, so the learning consequences flow
                # FROM the event: induction, domain expansion, and transfer
                # resolution react to THIS outcome (deferred, off the hot path)
                # instead of a 300s/900s idle tier later scanning the table.
                await self.emit(SelfEvent(
                    SelfEventType.OUTCOME_OBSERVED,
                    payload={"task_id": task.id, "task": task,
                             "domain": self._infer_domain_from_task(task),
                             "meta_memory_id": _meta_id, "outcome": "success",
                             "confidence": confidence},
                    origin="_execute_and_validate_task"))

                # SEMANTIC MEMORY: Hand the outcome to the memory agent (the
                # authority), which composes the rich, retrievable task-knowledge
                # record from the structured result — model-free.
                if self.memory and isinstance(result, dict):
                    await self.memory.capture_task_outcome(
                        task, result=result, success=True, confidence=confidence
                    )

                # === COMPLETION CALLBACKS: Execute registered closure hooks ===
                await self._execute_completion_callbacks(task, result, confidence)

                # SLACK NOTIFICATION: Task completion — show what was done and concluded
                if self.slack_notifier:
                    import re as _re2
                    task_desc = task.description.split('\n')[0][:200]
                    task_desc = _re2.sub(r'/[^\s]+', '[file]', task_desc)

                    completion_score = result.get('completion_score') if result else None
                    verification_state = result.get('verification_state', 'completed') if result else 'completed'
                    iterations = result.get('iterations', 1) if result else 1
                    summary_text = (result.get('summary') or '').strip() if result else ''
                    key_findings = (result.get('key_findings') or '').strip() if result else ''
                    # Also check inside outputs dict as fallback
                    if not key_findings and result:
                        key_findings = ((result.get('outputs') or {}).get('key_findings') or '').strip()
                    files_created = (result.get('files_created') or []) if result else []
                    duration_s = result.get('duration_seconds') if result else None
                    if duration_s is None and hasattr(task, 'started_at') and task.started_at:
                        try:
                            duration_s = int((datetime.now() - task.started_at).total_seconds())
                        except TypeError:
                            duration_s = int(datetime.now().timestamp() - task.started_at)

                    tool_results_list = result.get('tool_results', []) if result else []
                    tools_used = list(dict.fromkeys(
                        r['tool'] for r in tool_results_list
                        if isinstance(r, dict) and r.get('tool') and r.get('success')
                    ))

                    # ── Header line ──────────────────────────────────────────
                    header_parts = [
                        f"*Task:* {task_desc}",
                        f"*Type:* {task.type.value.replace('_', ' ').title()}  |  "
                        f"*Confidence:* {confidence:.0%}",
                    ]
                    if completion_score is not None:
                        header_parts.append(
                            f"*Score:* {completion_score:.3f}  |  "
                            f"*Iterations:* {iterations}"
                            + (f"  |  *Duration:* {duration_s // 60}m {duration_s % 60}s"
                               if duration_s and duration_s > 60
                               else (f"  |  *Duration:* {duration_s}s" if duration_s else ""))
                        )
                    else:
                        header_parts.append(f"*Iterations:* {iterations}"
                            + (f"  |  *Duration:* {duration_s // 60}m {duration_s % 60}s"
                               if duration_s and duration_s > 60
                               else (f"  |  *Duration:* {duration_s}s" if duration_s else "")))

                    if tools_used:
                        header_parts.append(f"*Tools:* {', '.join(tools_used[:6])}")

                    # ── Conclusion block (the most important part) ───────────
                    conclusion_parts = []

                    if summary_text:
                        preview = summary_text[:500] + ('…' if len(summary_text) > 500 else '')
                        conclusion_parts.append(f"*What was done:*\n{preview}")

                    if key_findings:
                        preview = key_findings[:400] + ('…' if len(key_findings) > 400 else '')
                        conclusion_parts.append(f"*Conclusions & findings:*\n{preview}")

                    if not summary_text and not key_findings:
                        conclusion_parts.append("_(No summary provided by task executor)_")

                    if files_created:
                        fc_display = [f"`{Path(f).name}`" for f in files_created[:5]]
                        conclusion_parts.append(f"*Output files:* {', '.join(fc_display)}")

                    full_message = "\n".join(header_parts)
                    if conclusion_parts:
                        full_message += "\n\n" + "\n\n".join(conclusion_parts)

                    await self.slack_notifier.send_notification(
                        title="✅ Task Completed",
                        message=full_message,
                        severity="info",
                        metadata={
                            "task_id": task.id,
                            "task_type": task.type.value,
                            "source": task.source.value,
                            "confidence": f"{confidence:.0%}",
                            "score": f"{completion_score:.3f}" if completion_score else "N/A",
                        }
                    )

                # Memory capture handled automatically by neural bridge during task execution

                # PERSISTENCE: Record task completion to database for cross-session persistence
                try:
                    from core.database import get_database_manager
                    db = get_database_manager()

                    # Calculate execution duration if available
                    execution_duration = None
                    if hasattr(task, 'started_at') and task.started_at:
                        execution_duration = int((datetime.now().timestamp() - task.started_at) / 1000)

                    # Prepare result summary (truncate to 1000 chars)
                    result_summary = str(result)[:1000] if result else "Task completed successfully"

                    await db.execute_query(
                        """
                        INSERT INTO task_execution_history (
                            task_id,
                            task_name,
                            task_type,
                            task_source,
                            completion_status,
                            result_summary,
                            confidence_score,
                            completed_at,
                            execution_duration_seconds,
                            metadata
                        ) VALUES (
                            $1, $2, $3, $4,
                            'completed',
                            $5, $6, NOW(), $7, $8
                        )
                        """,
                        params=(
                            task.id,
                            task.description[:512] if task.description else task.id,
                            task.type.value,
                            task.source.value,
                            result_summary,
                            float(confidence) if confidence is not None else None,
                            execution_duration,
                            json.dumps({"completed_at": datetime.now().isoformat()}),
                        ),
                        commit=True,
                    )

                    logger.info("💿 Task completion recorded to database for persistence")
                except Exception as db_error:
                    logger.warning(f"Failed to record task completion to database: {db_error}")
            else:
                # Retry or fail
                if task.retry_count < task.max_retries:
                    logger.warning(f"🔄 Task failed validation, retrying: {task.id}")
                    task.retry_count += 1

                    # DISPOSITION AT FAILURE — the behavior arbiter turns
                    # appraisal's accumulated pressures into a decision for this
                    # situation. `should_escalate` means the failure is attributed
                    # OUTSIDE the self (a repeated, externally-blocked failure);
                    # `should_replan` means it is internally re-derivable. The
                    # AppraisalSystem owns that accumulation — this only CONSUMES
                    # the arbiter's verdict (below, to steer the self-directed
                    # diagnostic) and records it for attribution. A neutral/absent
                    # appraisal yields a neutral directive (both False), preserving
                    # the prior behaviour exactly.
                    _directive = self.disposition()

                    # FAILURE CONTEXT: Record exactly WHY this attempt failed so the
                    # next execution has concrete error information rather than retrying
                    # blindly with the exact same prompt and making the exact same mistakes.
                    if task.metadata is None:
                        task.metadata = {}
                    _failure_history = task.metadata.get('failure_history', [])
                    _tool_results_for_history = (result or {}).get('tool_results', [])
                    _failed_tools_for_history = [
                        {'tool': r['tool'], 'error': str(r.get('error', r.get('result', '')))[:300]}
                        for r in _tool_results_for_history
                        if isinstance(r, dict) and not r.get('success', True)
                    ]
                    _failure_history.append({
                        'attempt': task.retry_count,
                        'issues': issues or ['Unknown'],
                        'failed_tools': _failed_tools_for_history,
                        'error': str((result or {}).get('error', ''))[:400],
                        'disposition': _directive.to_dict(),
                    })
                    task.metadata['failure_history'] = _failure_history
                    logger.info(f"📋 Stored failure context for retry (attempt {task.retry_count}): {len(issues or [])} issues, {len(_failed_tools_for_history)} failed tools")

                    requeue_success = await self.task_queue.requeue_task(task.id)

                    # DIAGNOSTIC: Spawn investigation task before the retry runs so
                    # the AI understands WHY the task failed and can fix the root cause.
                    # GUARD: Never spawn a diagnostic for a task that is already a diagnostic
                    # — this prevents the diag_ → diag_diag_ → diag_diag_diag_ infinite chain.
                    _is_already_diag = (
                        task.id.startswith('diag_')
                        or (task.metadata or {}).get('is_diagnostic', False)
                    )
                    # ESCALATION SUPPRESSES THE SELF-DIRECTED DIAGNOSTIC. When the
                    # appraisal attributes the failure to an EXTERNAL blocker
                    # (should_escalate), a root-cause investigation the self runs on
                    # ITSELF cannot fix it — spawning one just thrashes the queue.
                    # Surface the blocker honestly and record it instead. The bounded
                    # retry still runs (requeue above), so this suppresses wasted work
                    # without stranding a recoverable task. This is the arbiter's own
                    # "exploration_suppressed_by_escalation" principle applied to
                    # diagnostics. The non-escalate path keeps the diagnostic, which
                    # IS the should_replan re-derive (investigate root cause, then
                    # retry) rather than a bare re-run.
                    if _directive.should_escalate:
                        logger.warning(
                            "🧭 Task %s failure attributed to an EXTERNAL blocker "
                            "(%s); suppressing self-directed diagnostic and surfacing "
                            "the blocker instead of thrashing.",
                            task.id,
                            ", ".join(_directive.reason_codes) or "escalation")
                        if task.metadata is None:
                            task.metadata = {}
                        task.metadata['escalation'] = {
                            'external_blocker': True,
                            'reason_codes': list(_directive.reason_codes),
                            'attempt': task.retry_count,
                        }
                        self.stats["external_blocker_escalations"] += 1
                    elif not _is_already_diag:
                        import uuid as _uuid
                        from .shared_types import Task as _Task, TaskType as _TT, Priority as _P, TaskSource as _TS
                        import os as _os
                        issues_str_diag = ', '.join(issues) if issues else 'Unknown'
                        tool_results_diag = (result or {}).get('tool_results', [])
                        failed_tools_diag = [
                            r['tool'] for r in tool_results_diag
                            if isinstance(r, dict) and not r.get('success', True)
                        ]
                        failed_tools_summary = ', '.join(failed_tools_diag[:5]) if failed_tools_diag else 'unknown'
                        # Use absolute path so the LLM writes to the correct location
                        _diag_out_dir = _os.path.join(
                            _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))),
                            'output', 'diagnostics'
                        )
                        _os.makedirs(_diag_out_dir, exist_ok=True)
                        _diag_out_path = _os.path.join(_diag_out_dir, f"{task.id}_diagnosis.md")
                        diag_task = _Task(
                            id=f"diag_{task.id[:20]}_{_uuid.uuid4().hex[:8]}",
                            type=_TT.ANALYSIS,
                            description=(
                                f"DIAGNOSTIC INVESTIGATION REQUIRED — Task `{task.id}` failed and is being retried.\n\n"
                                f"Failed task description: {task.description[:300]}\n\n"
                                f"Failure reason: {issues_str_diag}\n"
                                f"Failed tools: {failed_tools_summary}\n\n"
                                f"YOU MUST investigate the ROOT CAUSE of this failure before the retry runs. "
                                f"Use read_file, run_shell_command, validate_path, and run_python to diagnose "
                                f"the environment. Check: (1) are the failing tools broken or misconfigured? "
                                f"(2) are required files/paths accessible? (3) is the task description "
                                f"achievable with available tools? "
                                f"Write your findings to EXACTLY this path: {_diag_out_path} "
                                f"Use write_file with that exact absolute path. "
                                f"Then call propose_completion with concrete recommendations."
                            ),
                            priority=_P.HIGH,
                            source=_TS.SYSTEM,
                            created_by="failure_handler",
                            metadata={
                                'is_diagnostic': True,
                                'parent_task_id': task.id,
                                'failure_reason': issues_str_diag,
                                'failed_tools': failed_tools_diag,
                                'retry_count': task.retry_count,
                                'output_path': _diag_out_path,
                            }
                        )
                        try:
                            await self.task_queue.add_task(diag_task, priority=_P.HIGH)
                            logger.info(f"🔍 Spawned diagnostic task {diag_task.id} to investigate failure of {task.id}")
                        except Exception as _diag_err:
                            logger.warning(f"Failed to spawn diagnostic task: {_diag_err}")
                    else:
                        logger.info(f"[DiagGuard] Skipping diagnostic spawn for already-diagnostic task {task.id} — breaking recursion")

                    # CRITICAL: If requeue failed (max retries exceeded), mark as permanently failed
                    # This prevents tasks from getting stuck IN_PROGRESS and blocking idle state
                    if not requeue_success:
                        logger.error(f"❌ Task {task.id} exceeded retry limit - marking as permanently failed")
                        issues_str = ', '.join(issues) if issues else 'Unknown'
                        await self.task_queue.mark_failed(
                            task.id,
                            f"Validation failed after {task.max_retries} retries: {issues_str}"
                        )

                        # DEDUP: Permanently block this fingerprint so it is never re-queued
                        try:
                            from .idle_work_playbook import IdleWorkPlaybook as _IWP
                            _pf = _IWP.description_fingerprint(task.description)
                            self._permanently_failed_fps.add(_pf)
                            _fp_list = list(getattr(self, '_recent_exploration_fp_list', []))
                            if _pf not in _fp_list:
                                _fp_list.append(_pf)
                                self._recent_exploration_fp_list = _fp_list[-20:]
                            self._save_permanently_failed_fps()
                            logger.info(f"🚫 Fingerprint {_pf} permanently blocked (task {task.id} exhausted retries)")
                        except Exception as _fp_err:
                            logger.debug(f"Failed to record failed fingerprint: {_fp_err}")

                        # META MEMORY: Store task failure for learning
                        await self._store_task_outcome_meta_memory(
                            task=task,
                            outcome="failure",
                            confidence=confidence,
                            failure_reason=f"Max retries exceeded: {issues_str}"
                        )
                else:
                    issues_str = ', '.join(issues) if issues else 'Unknown'
                    await self.task_queue.mark_failed(
                        task.id,
                        f"Validation failed: {issues_str}"
                    )
                    logger.error(f"❌ Task failed: {task.id} - Issues: {issues_str}")

                    # DEDUP: Permanently block this fingerprint so it is never re-queued
                    try:
                        from .idle_work_playbook import IdleWorkPlaybook as _IWP
                        _pf = _IWP.description_fingerprint(task.description)
                        self._permanently_failed_fps.add(_pf)
                        _fp_list = list(getattr(self, '_recent_exploration_fp_list', []))
                        if _pf not in _fp_list:
                            _fp_list.append(_pf)
                            self._recent_exploration_fp_list = _fp_list[-20:]
                        self._save_permanently_failed_fps()
                        logger.info(f"🚫 Fingerprint {_pf} permanently blocked (task {task.id} failed)")
                    except Exception as _fp_err:
                        logger.debug(f"Failed to record failed fingerprint: {_fp_err}")

                    # META MEMORY: Store task failure for learning
                    await self._store_task_outcome_meta_memory(
                        task=task,
                        outcome="failure",
                        confidence=confidence,
                        failure_reason=issues_str
                    )

                    # SLACK NOTIFICATION: Notify task failure with actionable details
                    if self.slack_notifier:
                        import re
                        task_desc = task.description.split('\n')[0][:200]
                        task_desc = re.sub(r'/[^\s]+', '[file]', task_desc)

                        # Clean up issues for display (remove paths, limit length)
                        issues_clean = re.sub(r'/[^\s]+', '[path]', issues_str)[:400]

                        # Retry status
                        retry_info = f"Retry {task.retry_count + 1}/3" if task.retry_count < 3 else "Max retries reached"

                        # Completion score from result
                        completion_score = result.get('completion_score') if result else None

                        # Summary of what was attempted
                        summary_text = (result.get('summary') or '').strip() if result else ''

                        # Tools that were run
                        tool_results_f = result.get('tool_results', []) if result else []
                        tools_used_f = list(dict.fromkeys(
                            r['tool'] for r in tool_results_f
                            if isinstance(r, dict) and r.get('tool') and r.get('success')
                        ))

                        iterations_f = result.get('iterations', 1) if result else 1

                        # Build detailed message
                        details = [
                            f"*Task ID:* `{task.id}`",
                            f"*Task:* {task_desc}",
                            f"*Type:* {task.type.value.replace('_', ' ').title()}",
                            f"*Retry Status:* {retry_info}",
                            f"*Iterations:* {iterations_f}",
                        ]

                        if completion_score is not None:
                            details.append(f"*Score:* {completion_score:.3f} (need >= 0.85)")

                        # Execution duration
                        if hasattr(task, 'started_at') and task.started_at:
                            try:
                                exec_time_f = int((datetime.now() - task.started_at).total_seconds())
                            except TypeError:
                                exec_time_f = int(datetime.now().timestamp() - task.started_at)
                            if exec_time_f > 60:
                                details.append(f"*Duration:* {exec_time_f // 60}m {exec_time_f % 60}s")
                            else:
                                details.append(f"*Duration:* {exec_time_f}s")

                        if tools_used_f:
                            details.append(f"*Tools Used:* {', '.join(tools_used_f[:6])}")

                        details.append(f"\n*Failure Reason:*\n{issues_clean}")

                        if summary_text:
                            summary_preview = summary_text[:300] + ('…' if len(summary_text) > 300 else '')
                            details.append(f"\n*What Was Attempted:*\n{summary_preview}")

                        severity = "warning" if task.retry_count < 2 else "error"
                        title = "⚠️ Task Requires Attention" if task.retry_count < 2 else "❌ Task Failed After Retries"

                        await self.slack_notifier.send_notification(
                            title=title,
                            message="\n".join(details),
                            severity=severity,
                            metadata={
                                "task_type": task.type.value,
                                "source": task.source.value,
                                "retry_count": task.retry_count,
                                "task_id": task.id,
                            }
                        )

                    # MEMORY CAPTURE: Store failed task for learning
                    try:
                        await self.store_memory(
                            MemoryType.EPISODIC,  # Failures are specific events
                            {
                                "event": "task_execution_failed",
                                "task_id": task.id,
                                "task_type": task.type.value,
                                "task_source": task.source.value,
                                "description": task.description,
                                "failure_reason": issues_str,
                                "retry_count": task.retry_count,
                                "result": result,
                                "timestamp": datetime.now().isoformat(),
                                # Fields required by intrinsic_motivation.py failure analysis
                                "status": "failed",
                                "confidence": 0.3,
                                "component": getattr(task, 'component', task.type.value),
                            },
                            importance=0.7,  # Failed tasks important for learning
                            tags=[
                                "task_execution",
                                task.type.value.lower(),
                                task.source.value.lower(),
                                "failed",
                                "learning"
                            ]
                        )
                        logger.info(f"💾 Task failure stored to memory for learning")
                    except Exception as mem_error:
                        logger.warning(f"Failed to store failure memory: {mem_error}")

                    # PERSISTENCE: Record task failure to database
                    try:
                        from core.database import get_database_manager
                        db = get_database_manager()

                        await db.execute_query(
                            """
                            INSERT INTO task_execution_history (
                                task_id,
                                task_name,
                                task_type,
                                task_source,
                                completion_status,
                                result_summary,
                                confidence_score,
                                completed_at,
                                retry_count,
                                metadata
                            ) VALUES (
                                $1, $2, $3, $4,
                                'failed',
                                $5, $6, NOW(), $7, $8
                            )
                            """,
                            params=(
                                task.id,
                                task.description[:512] if task.description else task.id,
                                task.type.value,
                                task.source.value,
                                f"Failed: {issues_str}",
                                0.0,  # Failed tasks have 0 confidence
                                task.retry_count,
                                json.dumps({"failed_at": datetime.now().isoformat(), "reason": issues_str}),
                            ),
                            commit=True,
                        )

                        logger.info("💿 Task failure recorded to database")
                    except Exception as db_error:
                        logger.warning(f"Failed to record task failure to database: {db_error}")

        except Exception as e:
            logger.error(f"Error executing task {task.id}: {e}")
            import traceback
            traceback.print_exc()
            await self.task_queue.mark_failed(task.id, f"Execution error: {str(e)}")

        finally:
            # Intrinsic exploration cap/dedup uses task queue state; no per-task lock cleanup needed.
            if _contract_token is not None:
                from core.safety.action_contract import reset_active_contract
                reset_active_contract(_contract_token)

    async def _execute_completion_callbacks(
        self,
        task: Task,
        result: Dict[str, Any],
        confidence: float
    ):
        """
        Execute all registered completion callbacks for this task type.
        
        This is the GENERIC CLOSURE MECHANISM - any subsystem can register
        callbacks to clean up, update state, or trigger follow-up actions
        when tasks complete.
        
        Args:
            task: Completed task
            result: Task execution result
            confidence: Completion confidence score
        """
        # Check task-level callbacks first (highest priority)
        if task.completion_callbacks:
            for callback_fn, metadata in task.completion_callbacks:
                try:
                    logger.debug(f"Executing task-level callback: {metadata.get('name', 'unknown')}")
                    await callback_fn(task, result, confidence)
                except Exception as e:
                    logger.error(
                        f"Task-level callback failed for {task.id}: {e}",
                        exc_info=True
                    )
        
        # Check registry callbacks (type + source based)
        key = (task.type, task.source)
        if key in self._completion_callbacks:
            for handler_info in self._completion_callbacks[key]:
                try:
                    callback_fn = handler_info['callback']
                    description = handler_info['description']
                    
                    logger.debug(
                        f"Executing completion callback: {description} "
                        f"for {task.type.value}/{task.source.value}"
                    )
                    
                    await callback_fn(task, result, confidence)
                    
                except Exception as e:
                    logger.error(
                        f"Completion callback failed ({description}): {e}",
                        exc_info=True
                    )
    
    async def handle_user_request(
        self,
        message: str,
        source: str = "api",
        priority: str = "high",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Accept work from the user and run it ON the substrate.

        The companion is not a separate agent with its own rules -- it is the
        user's connection to Torin. So a user request must enter through the
        same door as everything else: the task queue, the safety gate, the
        tools, memory, beliefs, meta-learning and credit assignment.

        This entry point did not exist. `TaskSource.API` and `TaskSource.MANUAL`
        were defined, the queue reserved them as NON_DISCRETIONARY (never
        refused however deep the backlog, task_queue:177) and exempted them from
        governance (task_queue:266) -- and nothing in the codebase ever created
        a task with either source. A privileged lane for user-directed work that
        has never carried a task.

        Returns the task id; the cognition loop picks it up on its next ~2s
        cycle, ahead of autonomous work now that priority ordering is correct.

        UNLESS IT IS A QUESTION, in which case it is answered here.

        Everything used to become a Task. Asking "What is a load balancer?"
        therefore got the full autonomous-work machinery: capability inference
        matched `load` and inferred `simulate_load`, 84 tools were selected and
        ranked (`load_test`, `run_shell_command`, `create_chaos_experiment` --
        no research tool anywhere), 31,137 of a 32,768-token window went to
        tool schemas, a Bayesian budget granted 26 iterations over 4,680
        seconds, and the first thing it did was create a directory. The model's
        own reasoning said "I don't need to run any tools to answer this
        conceptually, but per my instructions, I should". Measured, in the live
        system.

        A question is not a job and must not be costed like one.
        """
        from .shared_types import Task, TaskType, TaskSource, Priority

        # ONE CONVERSATION PER THREAD OF TALK, SHARED BY BOTH HALVES OF A TURN.
        #
        # These two calls each used to construct their own `Conversation()`, so
        # classifying a message and understanding it happened in different
        # objects and neither could see the other. Everything continuity hangs
        # on -- the turn record, the last subject, the running recall -- was
        # discarded between them, and every message arrived as if it were the
        # first.
        #
        # The session comes from the caller when it has one. It is NOT
        # defaulted to a shared constant: unrelated speakers sharing a key
        # would surface one person's turns as context for another, which is
        # worse than having no continuity.
        session = str((metadata or {}).get("conversation_id")
                      or (metadata or {}).get("session_id")
                      or f"{source}:unsessioned")

        kind = await self._request_kind(message, session=session)
        if kind in ("question", "telling"):
            answered = await self._answer_from_what_is_held(message, session=session)
            if answered is not None:
                return answered

        src = {
            "api": TaskSource.API,
            "manual": TaskSource.MANUAL,
        }.get(str(source).lower(), TaskSource.API)
        pri = {
            "critical": Priority.CRITICAL,
            "high": Priority.HIGH,
            "medium": Priority.MEDIUM,
            "low": Priority.LOW,
        }.get(str(priority).lower(), Priority.HIGH)

        task = Task(
            id=f"user_{uuid.uuid4().hex[:12]}",
            type=TaskType.ANALYSIS,
            description=message,
            priority=pri,
            source=src,
            created_by="user",
            metadata={"origin": "user_request", **(metadata or {})},
        )

        accepted = await self.task_queue.add_task(task, priority=pri)
        if not accepted:
            return {
                "success": False,
                "error": "task queue refused the request",
                "task_id": task.id,
            }

        logger.info(f"👤 User request accepted: {task.id} ({src.value}, {pri.name})")
        return {"success": True, "task_id": task.id, "source": src.value, "priority": pri.name}

    async def _request_kind(self, message: str, session: str) -> str:
        """Asking, telling, or a job to do.

        DELEGATED, NOT DECIDED HERE. This used to ask a model directly while
        `Conversation.is_question` asked a rule, and the two disagreed -- a
        plain statement was classified as a question and filed in memory as one.
        Whether a sentence asks is a fact about the sentence, and the component
        that reads sentences owns it.
        """
        try:
            return await self.conversation(session).classify(message)
        except Exception as error:
            logger.info("request kind undetermined (%s); treating as work", error)
            return "job"

    async def _answer_from_what_is_held(
        self, message: str, session: str
    ) -> Optional[Dict[str, Any]]:
        """Answer out of the concept store and memory, and remember the exchange.

        Returns None when nothing could be assembled, so the caller falls
        through to the work path rather than replying with an apology.
        """
        try:
            understanding = await self.conversation(session).understand(message)
        except Exception as error:
            logger.warning("could not answer from what is held: %s", error)
            return None

        # A DERIVED answer is held knowledge too. The substrate may have proved
        # the answer from what it holds without any single concept being
        # `known`, so `answers` (a reasoned or direct verdict) counts as having
        # answered -- otherwise a question the substrate PROVED would be dropped
        # to the work path as though nothing were held.
        if not (understanding.known or understanding.remembered
                or understanding.acquired or understanding.answers):
            return None

        try:
            from core.memory import get_memory_agent
            from core.memory.utils.interfaces import MemoryType

            agent = await get_memory_agent()
            content = (f"Asked: {message[:300]} — "
                       + ("answered from held knowledge"
                          if understanding.answered
                          else "could not answer; asked what it is"))

            # AN ANSWER MAY BE THE END OF SOMETHING. If a question about this
            # was asked before and left open, this settles that episode rather
            # than starting a second one beside it -- otherwise memory holds
            # "could not answer" and "answered" about the same thing forever,
            # and recall keeps returning whichever it reaches first.
            closed = None
            if understanding.answered:
                closed = await agent.close_open(
                    message, content, because="answered on a later turn")

            if closed is None:
                await agent.store_memory(
                    memory_type=MemoryType.EPISODIC,
                    content=content,
                    importance_score=0.7, confidence_score=0.9,
                    tags=["user_exchange"] + (
                        ["answered"] if understanding.answered
                        else [agent.OPEN_TAG, "asked_back"]),
                    source_context={"source_system": "handle_user_request"},
                    thinking_state={"reply_preview": understanding.reply[:400],
                                    "acquired": [a.label for a in understanding.acquired]})
        except Exception as error:
            # Never let a memory failure swallow an answer that was produced.
            logger.warning("exchange NOT remembered: %s", error)

        return {"success": True, "kind": "question", "answer": understanding.reply,
                "learned": [a.label for a in understanding.acquired if a.stored],
                "closed_open_memory": closed, "source": "substrate"}

    async def handle_security_finding(
        self,
        finding_id: str,
        severity: str,
        description: str,
        remediation: Optional[str] = None,
        affected_components: Optional[List[str]] = None,
        remediation_steps: Optional[List] = None,
        contract: Optional[Any] = None,
    ):
        """
        Handle security finding from SecurityAuditWorker or SecurityController.
        Evaluates through governance and creates remediation task if approved.

        Args:
            finding_id: Security finding identifier
            severity: Finding severity (CRITICAL, HIGH, MEDIUM, LOW)
            description: Full finding description
            remediation: Remediation steps as a string (security_audit_worker callers)
            affected_components: Affected system components
            remediation_steps: Remediation steps as a list (controller callers)
        """
        # Unify the two remediation parameter styles
        if remediation is None and remediation_steps:
            remediation = "; ".join(str(s) for s in remediation_steps) if remediation_steps else None

        try:
            from .shared_types import Task, TaskType, TaskSource, Priority

            logger.info(f"Received security finding: {finding_id} (Severity: {severity})")

            # SLACK NOTIFICATION: Security finding detected
            if self.slack_notifier:
                # Clean description (remove file paths)
                import re
                clean_desc = re.sub(r'/[^\s]+', '[file]', description[:300])

                severity_emoji = {"CRITICAL": "🔴", "HIGH": "🟠", "MEDIUM": "🟡", "LOW": "🟢"}.get(severity, "⚪")
                await self.slack_notifier.send_notification(
                    title=f"{severity_emoji} Security Finding: {severity}",
                    message=f"**Finding:** {clean_desc}\n**Severity:** {severity}\n**Status:** Evaluating remediation options",
                    severity="warning" if severity in ["CRITICAL", "HIGH"] else "info",
                    metadata={"severity": severity, "finding_type": "security_audit"}
                )

            # Every finding gets a contract. Detectors do not author one --
            # it is DERIVED from severity (proportionality) and from the fact
            # that a finding is resolved when its own detector stops raising
            # it. A detector may attach an explicit contract to override the
            # derived one, but only for genuine exceptions. This is why there
            # is no authoring burden and no finding is ever unconstrained.
            if contract is None:
                from core.safety.action_contract import derive_contract
                contract = derive_contract(
                    finding_id=finding_id,
                    severity=severity,
                    title=description.split("\n")[0][:120],
                )

            # State the contract IN the task. Enforcement is a floor; this is
            # the part that stops the agent having to guess what remediation
            # means, which is what produced "perhaps I need to actually archive
            # or remove this" followed by an unbounded escalation.
            if hasattr(contract, "describe_for_agent"):
                description = f"{description}\n\n{contract.describe_for_agent()}"

            # Map severity to priority
            priority_map = {
                "CRITICAL": Priority.CRITICAL,
                "HIGH": Priority.HIGH,
                "MEDIUM": Priority.MEDIUM,
                "LOW": Priority.LOW
            }
            priority = priority_map.get(severity, Priority.MEDIUM)

            # Evaluate through governance system
            if self.governance:
                from core.governance.unified_governance_trigger_system import ActionCategory

                # Evaluate the remediation action
                evaluation = await self.governance.evaluate_action(
                    action_category=ActionCategory.CONFIGURATION_CHANGES,
                    action_type="security_remediation",
                    parameters={
                        "finding_id": finding_id,
                        "severity": severity,
                        "remediation": remediation,
                        "components": affected_components
                    },
                    context={
                        "source": "security_audit_worker",
                        "execution_mode": "autonomous"
                    }
                )

                logger.info(
                    f"Governance evaluation for {finding_id}: "
                    f"Tier={evaluation.decision_tier.value}, "
                    f"Enforcement={evaluation.enforcement_mode.value}"
                )

                # Send Slack notification for IMPORTANT/CRITICAL tiers
                if evaluation.decision_tier.value in ["IMPORTANT", "CRITICAL"] and self.slack_notifier:
                    try:
                        await self.slack_notifier.send_notification(
                            title=f"Security Remediation Requires {evaluation.decision_tier.value} Approval",
                            message=f"**Finding:** {finding_id}\n**Severity:** {severity}\n\n{description}",
                            severity=severity,
                            metadata={"finding_id": finding_id, "governance_tier": evaluation.decision_tier.value}
                        )
                    except Exception as e:
                        logger.error(f"Failed to send governance notification: {e}")

                # Only auto-create task for ROUTINE tier
                if evaluation.decision_tier.value == "ROUTINE":
                    logger.info(f"Auto-approving ROUTINE security remediation: {finding_id}")
                else:
                    logger.info(f"Security finding {finding_id} requires {evaluation.decision_tier.value} approval - task creation deferred")
                    return  # Wait for human approval for IMPORTANT/CRITICAL

            # Dedup: the audit re-reports every finding whose condition is still
            # present, so an unresolved finding produced a NEW task every cycle
            # while the previous one was still running. The id is deterministic,
            # so an already-active task means this work is already scheduled.
            _task_id = f"security_remediation_{finding_id}"
            if self.task_queue.has_active_task(_task_id):
                logger.debug(
                    "Security finding %s already has an active remediation task — "
                    "not re-queuing", finding_id
                )
                return

            # Create remediation task
            remediation_task = Task(
                id=_task_id,
                type=TaskType.SECURITY_REMEDIATION,
                description=description,
                priority=priority,
                source=TaskSource.SECURITY_AUDIT,
                created_by="security_audit_worker",
                metadata={
                    "finding_id": finding_id,
                    "severity": severity,
                    "remediation": remediation,
                    "affected_components": affected_components,
                    # Travels with the task so the executor binds it and the
                    # safety gate can enforce it.
                    "contract": contract.to_dict() if hasattr(contract, "to_dict") else contract,
                }
            )

            # Add task to queue
            await self.task_queue.add_task(remediation_task, priority=priority)
            logger.info(f"Created remediation task for security finding: {finding_id}")

        except Exception as e:
            logger.error(f"Error handling security finding {finding_id}: {e}", exc_info=True)

    async def _collect_system_context_for_goals(self) -> Dict[str, Any]:
        """Collect actual system context to inform intrinsic goal generation"""
        context = {}

        try:
            # Security findings from security controller
            if self.security_controller:
                try:
                    findings = await self.security_controller.get_recent_findings(limit=10)
                    if findings:
                        context["security_findings"] = [
                            {
                                "type": f.get("type", "unknown"),
                                "description": f.get("description", "unknown"),
                                "severity": f.get("severity", "unknown")
                            }
                            for f in findings
                        ]
                except Exception as e:
                    logger.debug(f"Could not get security findings: {e}")

            # System health summary from monitoring coordinator
            # NOTE: stored under 'system_health', NOT 'performance_metrics' — the latter
            # is iterated by _quantify_component_uncertainties as per-component data and
            # using a flat health dict there creates fake components named 'overall_status' etc.
            if self.monitoring_coordinator:
                try:
                    system_health = await self.monitoring_coordinator.check_system_health()
                    if system_health:
                        context["system_health"] = {
                            "overall_status": system_health.overall_status.value,
                            "healthy_components": system_health.healthy_components,
                            "total_components": system_health.total_components,
                            "critical_issues": system_health.critical_issues,
                            "active_alerts": system_health.active_alerts,
                        }
                except Exception as e:
                    logger.debug(f"Could not get system health: {e}")

            # Failed tasks from task queue
            try:
                failed = await self.task_queue.get_failed_tasks(limit=10)
                if failed:
                    context["failed_tasks"] = [
                        {
                            "description": task.description,
                            "failure_reason": getattr(task, 'failure_reason', 'unknown'),
                            "status": "failed",  # Required by intrinsic_motivation
                            "confidence": getattr(task, 'confidence', 0.3),  # Low confidence for failed tasks
                            "component": getattr(task, 'component', 'unknown')  # Component identifier
                        }
                        for task in failed
                    ]
            except Exception as e:
                logger.debug(f"Could not get failed tasks: {e}")

            # The substrate's OWN maintenance machinery failing is interoception
            # too. A scheduled tier erroring or a persistence write failing is an
            # internal fault of the same character as a failed task, and it
            # should register as component uncertainty (which drives affect and
            # curiosity via _quantify_component_uncertainties), not sit only in
            # the health monitor. This is a SENSE, not strategy credit — it never
            # enters ULS's credited meta-learner, so the credit invariant (never
            # charge a strategy for infra failure) is untouched. Emitted on the
            # DELTA — only machinery that erred SINCE the last refresh — so a
            # fault that already recovered leaves no phantom uncertainty.
            try:
                recent_errors = []
                prev_tier = getattr(self, "_last_tier_error_counts", {})
                now_tier = {}
                for job in self.task_queue.scheduled_job_status():
                    now_tier[job["name"]] = job["errors"]
                    if job["errors"] > prev_tier.get(job["name"], 0) and job.get("last_error"):
                        recent_errors.append({
                            "component": f"scheduler:{job['name']}",
                            "type": str(job["last_error"]).split(":")[0],
                        })
                self._last_tier_error_counts = now_tier

                qstats = await self.task_queue.get_statistics()
                prev_persist = getattr(self, "_last_persist_errors", 0)
                if qstats.get("persist_errors", 0) > prev_persist:
                    recent_errors.append({"component": "queue_persistence",
                                          "type": "PersistError"})
                self._last_persist_errors = qstats.get("persist_errors", 0)

                if recent_errors:
                    context["recent_errors"] = recent_errors
            except Exception as e:
                logger.debug(f"Could not collect queue-authority interoception: {e}")

            # INNOVATION SIGNALS: Frontier foresight (tech frontiers, emerging domains, safety priorities)

            # Current motivation state (so goals are informed by what the system is curious about)
            if hasattr(self, '_current_motivation') and self._current_motivation:
                context["motivation_state"] = self._current_motivation

            # Strategy outcomes (so the system can generate meta-goals about strategy improvement)
            if hasattr(self, '_strategy_outcomes') and self._strategy_outcomes:
                context["strategy_performance"] = {
                    task_type: {
                        strategy: {
                            'win_rate': s['wins'] / max(s['executions'], 1),
                            'executions': s['executions']
                        }
                        for strategy, s in strategies.items()
                    }
                    for task_type, strategies in self._strategy_outcomes.items()
                }

            # Knowledge cutoff state — critical for research goal grounding
            try:
                kc_state = getattr(self, "_knowledge_cutoff_state", {}) or {}
                context["knowledge_cutoff"] = {
                    "refreshed_through_date": kc_state.get("refreshed_through_date"),
                    "declared_cutoff": self._get_declared_model_cutoff_date(),
                    "last_topics_researched": kc_state.get("last_topics_researched", [])[:5],
                }
            except Exception as _kc_err:
                logger.debug(f"Could not get knowledge cutoff state: {_kc_err}")

            # System review snapshot — tool inventory and codebase stats
            try:
                snapshot = getattr(self, "_idle_system_review_snapshot", None)
                if snapshot:
                    context["system_review"] = snapshot.get("highlights", {})
                    tools_data = snapshot.get("tools") or {}
                    top_cats = tools_data.get("top_categories", [])
                    if top_cats:
                        context["available_tool_categories"] = [
                            c.get("category", "") for c in top_cats[:8] if c.get("category")
                        ]
            except Exception as _sr_err:
                logger.debug(f"Could not get system review snapshot: {_sr_err}")

            # Recently completed/verified tasks — so LLM avoids repeating them
            try:
                recent_done: list = []
                for _queued in list(getattr(self.task_queue, "tasks_by_id", {}).values())[-40:]:
                    _status = str(getattr(_queued, "status", "")).lower()
                    if _status in ("completed", "verified", "success"):
                        _inner = getattr(_queued, "task", None)
                        _desc = getattr(_inner, "description", "") if _inner else ""
                        if _desc:
                            recent_done.append(_desc[:120])
                if recent_done:
                    context["recently_completed_tasks"] = recent_done[-5:]
            except Exception as _rc_err:
                logger.debug(f"Could not get recent completed tasks: {_rc_err}")

            # Test suite info — so the AI knows its tests exist and where they are
            try:
                import os as _os
                _torin_root = _os.path.abspath(_os.path.join(_os.path.dirname(__file__), "..", "..", ".."))
                _tests_dir = _os.path.join(_torin_root, "tests")
                if _os.path.isdir(_tests_dir):
                    _test_cats = sorted(
                        d for d in _os.listdir(_tests_dir)
                        if _os.path.isdir(_os.path.join(_tests_dir, d)) and not d.startswith("_")
                    )
                    context["test_suite_info"] = {
                        "tests_root": _tests_dir,
                        "categories": [c for c in _test_cats if c != "governance"],
                        "key_test_files": [
                            "tests/test_security_tools.py",
                            "tests/test_system_tools.py",
                            "tests/test_reasoning_systems.py",
                            "tests/test_ai_performance_suite.py",
                            "tests/chaos/test_chaos_orchestrator.py",
                            "tests/memory/test_memory_system.py",
                        ],
                    }
            except Exception as _ts_err:
                logger.debug(f"Could not collect test suite info: {_ts_err}")

        except Exception as e:
            logger.error(f"Error collecting system context: {e}")

        return context

    async def _handle_idle_state(self):
        """Legacy method - exploration is now continuous, not idle-gated.
        Redirects to _run_exploration_cycle for backward compatibility."""
        await self._run_exploration_cycle()

    async def _check_constitutional_alignment(self):
        """
        Check Singleton's alignment with constitutional principles.
        Detects drift in core responsibilities (learning, research, maintenance, security, self-upgrade).
        """
        try:
            logger.info("📜 Checking Singleton constitutional alignment...")

            # Refresh self-state from the real subsystems (resource_usage,
            # error_rate, goal_alignment, ...), then merge the HEALTH authority's
            # overall status + critical-component count — the metrics Laws 3 and 5
            # read. Without this the assessment ran against the conservative
            # default (empty metrics), scoring the health/harm laws from no data.
            await self._update_system_state()
            try:
                from core.health.health_monitor import get_health_monitor
                health = await get_health_monitor().get_system_health()
                components = health.get("components", {}) or {}
                critical = [c for c, h in components.items()
                            if str(h.get("status", "")).lower() == "critical"]
                degraded = [c for c, h in components.items()
                            if str(h.get("status", "")).lower() in ("degraded", "unhealthy")]
                os_status = str(health.get("status", "healthy")).lower()
                if critical or os_status == "critical":
                    overall = "critical"
                elif degraded or os_status in ("degraded", "unhealthy"):
                    overall = "degraded"
                else:
                    overall = "healthy"
                self.system_state.performance_metrics["overall_status"] = overall
                self.system_state.performance_metrics["critical_issues"] = len(critical)
                # resource_usage (Laws 1 & 5) — the health authority owns the real
                # CPU/memory sample; take the higher as the pressure scalar.
                cpu = float(health.get("cpu_percent", 0.0) or 0.0)
                mem = float(health.get("memory_percent", 0.0) or 0.0)
                self.system_state.resource_usage = max(cpu, mem) / 100.0
            except Exception as e:
                # Honest gap: if health is unreadable, the health-derived metrics
                # are left as whatever the last refresh held rather than faked.
                logger.warning("constitutional check: health metrics unreadable: %s", e)

            # Perform constitutional assessment over the REAL system state.
            assessment = await self.constitution.assess_constitutional_alignment(
                system_state=self.system_state)
            
            # Handle critical drift
            if assessment.drift_severity in [DriftSeverity.CRITICAL, DriftSeverity.SIGNIFICANT]:
                logger.error(f"🚨 CONSTITUTIONAL DRIFT DETECTED: {assessment.drift_severity.value}")
                logger.error(f"   Overall alignment: {assessment.average_compliance:.1%}")

                # Format violation details
                violation_details = []
                for v in assessment.violations:
                    violation_details.append(f"Law {v.law_number} ({v.law_name}): {v.description}")

                # Publish notification to Employee UI (rate limited)
                try:
                    publish_ok = True
                    if self._last_drift_alert_at:
                        elapsed = (datetime.now() - self._last_drift_alert_at).total_seconds()
                        publish_ok = elapsed > 600  # 10 min cooldown
                    if publish_ok:
                        await publish_notification({
                            'type': 'security',
                            'title': 'Constitutional drift detected',
                            'message': (
                                f"Severity: {assessment.drift_severity.value}. "
                                f"Overall alignment: {assessment.average_compliance:.1%}. "
                                f"Violations: {len(assessment.violations)}"
                            ),
                            'status': 'info',
                            'metadata': {
                                'violations': len(assessment.violations),
                                'details': violation_details[:5]
                            }
                        })
                        self._last_drift_alert_at = datetime.now()
                except Exception:
                    pass
                
                # Log all violations
                for v_detail in violation_details:
                    logger.error(f"   {v_detail}")
                
                # If a teacher model is available, alert it to the drift
                law_scores_str = chr(10).join(
                    f"  - Law {num}: {score:.1%}"
                    for num, score in assessment.law_compliance_scores.items()
                )
                drift_alert = f"""
CONSTITUTIONAL ALERT: System drift detected!

Alignment with governance laws has degraded:
- Overall Alignment: {assessment.average_compliance:.1%}
- Drift Severity: {assessment.drift_severity.value}

Law Compliance Scores:
{law_scores_str}

Violations ({len(assessment.violations)}):
{chr(10).join(f"  - {v}" for v in violation_details)}

The substrate must realign with its constitutional responsibilities immediately.
"""
                logger.error(drift_alert)

                # Record the drift alert for self-reflection. The memory agent
                # owns the store; the coordinator writes through its own
                # store_memory (this previously targeted a model handle that had
                # no `.memory`, so the alert was never actually recorded).
                from core.memory import MemoryType
                await self.store_memory(
                    MemoryType.META,
                    {
                        "type": "constitutional_drift_alert",
                        "severity": assessment.drift_severity.value,
                        "alignment_score": assessment.average_compliance,
                        "violations": [{
                            "law_number": v.law_number,
                            "law_name": v.law_name,
                            "description": v.description,
                            "compliance_score": v.compliance_score
                        } for v in assessment.violations],
                        "alert": drift_alert
                    },
                )
            
            # Log law scores even if no critical drift
            elif assessment.average_compliance < 0.95:
                logger.info(f"📋 Constitutional alignment: {assessment.average_compliance:.1%}")
                for law_num, score in assessment.law_compliance_scores.items():
                    if score < 0.95:
                        logger.info(f"   💡 Law {law_num}: {score:.1%}")
            
        except Exception as e:
            logger.error(f"Error checking constitutional alignment: {e}")

    async def _check_constitutional_alignment_quick(self):
        """Lightweight constitutional alignment check for every cycle."""
        try:
            assessment = await self.constitution.assess_quick_alignment()
            # Only escalate logs if drift is significant or worse
            if assessment.drift_severity in [DriftSeverity.SIGNIFICANT, DriftSeverity.CRITICAL]:
                logger.error(
                    f"🚨 QUICK DRIFT ALERT: severity={assessment.drift_severity.value}, "
                    f"overall_alignment={assessment.average_compliance:.1%}"
                )
        except Exception as e:
            logger.error(f"Error in quick constitutional alignment check: {e}")
    
    async def _create_recovery_goal_from_health_event(self, event: Dict[str, Any]):
        """Create a recovery goal when critical health event occurs"""
        try:
            component = event.get("component", "unknown")
            proposed_actions = event.get("proposed_actions", [])
            
            if not proposed_actions:
                return
            
            # Create goal for Singleton to handle
            goal_description = f"Recover {component}: {proposed_actions[0].get('reason', 'system issue')}"
            
            goal = await self.planning.create_goal(
                description=goal_description,
                priority=Priority.HIGH
            )
            
            if goal:
                self.system_state.active_goals.append(goal.id)
                logger.info(f"🚨 Created critical recovery goal: {goal_description}")
            
        except Exception as e:
            logger.error(f"Error creating recovery goal: {e}")
    
    async def _execute_task_with_singleton(self, task: Task) -> bool:
        """
        Execute a task using adaptive strategy selection.

        Instead of hardcoded task_type → method routing, the system:
        1. Builds an execution context from the task
        2. Queries the meta-learner for the best strategy
        3. Executes with the selected strategy
        4. Records outcome for future learning

        All available execution strategies are registered in a capability map.
        The meta-learner selects based on historical performance for similar tasks.
        """
        import time
        start_time = time.time()

        # Log task execution start
        self.log_db.log_coordination(
            coordinator_type='autonomous',
            action='task_execution_start',
            task_id=task.id,
            status='executing',
            metadata={
                'task_type': task.type.value,
                'task_description': task.description[:200],
                'priority': task.priority
            }
        )

        try:
            # Build capability map — all available execution strategies
            capabilities = self._build_capability_map()

            # Select strategy adaptively
            selected_strategy = await self._select_execution_strategy(
                task, capabilities
            )

            logger.info(
                f"🎯 Strategy selected: '{selected_strategy}' for task type "
                f"{task.type.value} ({task.description[:60]}...)"
            )

            # Execute with selected strategy
            strategy_fn = capabilities.get(selected_strategy)
            if strategy_fn is None:
                # No mapped strategy: execute the task directly through the executor.
                logger.warning(f"Strategy '{selected_strategy}' not in capability map, executing directly")
                result = await self.executor.execute_task(task)
            else:
                result = await strategy_fn(task)

            execution_time = time.time() - start_time

            # `bool(result)` made every non-empty dict a win, including
            # {'verification_state': 'failed'} and {'error': ...}. That is
            # poisoned credit assignment: the learner grows confident in a
            # policy that is failing. Resolve against the same completion
            # protocol the queue path uses.
            resolved = self._result_is_success(result)
            success = bool(resolved)

            if resolved is None:
                # No verifiable signal. Record nothing rather than guess -- a
                # fabricated outcome is worse for the posterior than a missing one.
                logger.warning(
                    "Task %s: strategy '%s' returned no verifiable outcome signal; "
                    "treating as unsuccessful and NOT recording to the learners",
                    task.id, selected_strategy,
                )
            else:
                await self._record_strategy_outcome(
                    task, selected_strategy, success, execution_time
                )

                # META MEMORY: task outcomes are the substrate's performance
                # history — competence drives and meta-learning read them.
                # Only the queue path (_execute_and_validate_task) recorded
                # them, but _execution_phase runs THIS path, so every task
                # executed by the live loop left no performance trace at all.
                _conf = result.get('completion_score') if isinstance(result, dict) else None
                if not isinstance(_conf, (int, float)):
                    # resolved is not None here, so the outcome itself is verified.
                    _conf = 1.0
                _failure_reason = None
                if not success:
                    if isinstance(result, dict):
                        _failure_reason = str(
                            result.get('error')
                            or result.get('verification_state')
                            or 'strategy reported failure'
                        )[:300]
                    else:
                        _failure_reason = 'strategy reported failure'
                await self._store_task_outcome_meta_memory(
                    task=task,
                    outcome="success" if success else "failure",
                    confidence=float(_conf),
                    result_summary=str(result)[:500] if success and result else None,
                    failure_reason=_failure_reason,
                )

                # SEMANTIC MEMORY: hand the outcome to the memory agent (authority)
                # to compose the rich task-knowledge record, model-free.
                if self.memory and isinstance(result, dict):
                    await self.memory.capture_task_outcome(
                        task, result=result, success=bool(success), confidence=float(_conf)
                    )

            # Log execution result
            self.log_db.log_coordination(
                coordinator_type='autonomous',
                action='task_execution_complete',
                task_id=task.id,
                status='completed' if success else 'failed',
                result=f'Strategy: {selected_strategy}, success: {success}',
                metadata={
                    'task_type': task.type.value,
                    'strategy': selected_strategy,
                    'execution_time': execution_time
                }
            )

            self.log_db.log_performance(
                operation='task_execution',
                duration=execution_time,
                success=success,
                details={
                    'task_id': task.id,
                    'task_type': task.type.value,
                    'strategy': selected_strategy
                }
            )

            return success

        except Exception as e:
            execution_time = time.time() - start_time
            logger.error(f"Error executing task with singleton: {e}")

            import traceback
            # Log error with full details
            self.log_db.log_error(
                error_type=type(e).__name__,
                error_message=str(e),
                module='autonomous_coordinator',
                function='_execute_task_with_singleton',
                stack_trace=traceback.format_exc(),
                context={'task_id': task.id, 'task_type': task.type.value, 'task_description': task.description}
            )

            # Log failed coordination
            self.log_db.log_coordination(
                coordinator_type='autonomous',
                action='task_execution_failed',
                task_id=task.id,
                status='error',
                result=f'Exception during execution: {str(e)}',
                metadata={'task_type': task.type.value, 'execution_time': execution_time, 'error': type(e).__name__}
            )

            # Send Slack alert for singleton task execution error
            try:
                await self.slack_notifier.send_security_alert(
                    alert_title="Singleton Task Execution Error",
                    alert_message=f"Critical error in task execution: {task.description[:150]}\nError: {str(e)[:200]}",
                    severity="HIGH",
                    metadata={
                        'error': str(e),
                        'error_type': type(e).__name__,
                        'task_id': task.id,
                        'task_type': task.type.value,
                        'execution_time': execution_time,
                        'tasks_completed': self.stats['tasks_completed']
                    }
                )
            except Exception as notify_error:
                logger.warning(f"Failed to send singleton task error notification: {notify_error}")

            return False

    @staticmethod
    def _result_is_success(result) -> Optional[bool]:
        """Resolve a strategy result into a verified outcome.

        Returns True/False when the result carries a real signal, and None when
        it does not -- the caller must not invent one. Uses the same
        verification_state contract as _execute_and_validate_task so both paths
        agree on what "succeeded" means.
        """
        if isinstance(result, bool):
            return result
        if not isinstance(result, dict):
            return None

        state = result.get('verification_state')
        if state == 'verified':
            return True
        if state in ('failed', 'blocked', 'in_progress', 'partially_complete'):
            return False

        if isinstance(result.get('success'), bool):
            return result['success']
        if result.get('error'):
            return False

        score = result.get('completion_score')
        if isinstance(score, (int, float)):
            return score >= 0.85

        return None

    def _build_capability_map(self) -> Dict[str, Any]:
        """
        Build a map of all available execution strategies.

        Each strategy is a callable that takes a Task and returns a result.
        New strategies can be added without modifying routing logic.
        """
        capabilities = {}

        # The former model-driven strategies (research / learning / reasoning
        # experiments / memory consolidation) were bound to a model handle that
        # never carried those methods, so they were never registered. Task
        # execution runs through the substrate's general executor.

        # The substrate executes the task through its own executor.
        async def general_strategy(task):
            return await self.executor.execute_task(task)
        capabilities['general_executor'] = general_strategy

        return capabilities

    async def _select_execution_strategy(
        self, task: 'Task', capabilities: Dict[str, Any]
    ) -> str:
        """
        Adaptively select the best execution strategy for a task.

        Uses meta-learning outcomes when available, falls back to
        heuristic mapping based on task type and description.
        """
        from .shared_types import TaskType

        available = list(capabilities.keys())
        if not available:
            return 'general_executor'

        # 1. Ask the meta-learner. This used to read self._strategy_outcomes with
        #    its own epsilon-greedy rule -- a second policy table that MetaLearner
        #    never saw, held only in memory, and rebuilt empty on every restart
        #    (the every-10-executions META summary was written and never read).
        #    Two policy states that can disagree about what has been learned is a
        #    design fracture, not a redundancy. MetaLearner is now canonical:
        #    it persists, and its Thompson sampling subsumes epsilon-greedy.
        if self.meta_learning:
            try:
                sink: Dict[str, Any] = {}
                strategy = await self.meta_learning.select_strategy(
                    self._task_family_for(task.type),
                    strategy_prefix=self.EXECUTOR_NS,
                    min_confidence=0.0,
                    decision_context=await self._decision_context(task.description),
                    _decision_sink=sink,
                )
                if strategy is not None:
                    name = str(strategy.strategy_type)[len(self.EXECUTOR_NS):]
                    if name in available:
                        self._executor_decision_ids[task.id] = sink.get("decision_id")
                        return name
                    logger.debug(
                        "Meta-learner chose '%s', which is not currently available; "
                        "falling back to heuristic", name
                    )
            except Exception as e:
                logger.warning("Meta-learner executor selection failed: %s", e)

        # 2. Heuristic mapping (used until meta-learning has enough data)
        type_to_strategy = {
            TaskType.RESEARCH: 'research',
            TaskType.ANALYSIS: 'reasoning_experiments',
            TaskType.LEARNING: 'learning',
            TaskType.SYNTHESIS: 'general_executor',
            TaskType.PLANNING: 'general_executor',
            TaskType.VALIDATION: 'memory_consolidation',
        }

        suggested = type_to_strategy.get(task.type, 'general_executor')

        # For ANALYSIS/LEARNING: mix learning and reasoning
        if task.type in (TaskType.ANALYSIS, TaskType.LEARNING):
            import random
            suggested = random.choice(['learning', 'reasoning_experiments'])

        return suggested if suggested in available else 'general_executor'

    async def _record_strategy_outcome(
        self, task: 'Task', strategy: str, success: bool, execution_time: float
    ):
        """
        Record the outcome of a strategy execution for meta-learning.

        Over time, this builds a statistical model of which strategies
        work best for each task type, enabling adaptive routing.
        """
        try:
            task_key = task.type.value

            if task_key not in self._strategy_outcomes:
                self._strategy_outcomes[task_key] = {}

            if strategy not in self._strategy_outcomes[task_key]:
                self._strategy_outcomes[task_key][strategy] = {
                    'wins': 0, 'losses': 0, 'total_time': 0.0, 'executions': 0
                }

            stats = self._strategy_outcomes[task_key][strategy]
            if success:
                stats['wins'] += 1
            else:
                stats['losses'] += 1
            stats['total_time'] += execution_time
            stats['executions'] += 1

            # Report to the meta-learner. _strategy_outcomes has been a second,
            # private meta-learning system: an in-memory dict that MetaLearner
            # never saw and that vanished on restart (the every-10-executions
            # META memory write was a summary, never read back). Executor choice
            # per task family is a real arm, so it belongs in the same posteriors
            # as every other decision.
            if self.meta_learning:
                try:
                    from core.learning.meta_learning import OutcomeClass
                    await self.meta_learning.track_learning_outcome(
                        task_type=self._task_family_for(task.type),
                        strategy_type=f"{self.EXECUTOR_NS}{strategy}",
                        success=success,
                        performance_score=1.0 if success else 0.0,
                        time_ms=execution_time * 1000.0,
                        outcome_class=(
                            OutcomeClass.SUCCESS if success
                            else OutcomeClass.EXECUTION_FAILURE
                        ),
                        context={
                            "task_id": task.id,
                            "task_type": task_key,
                            "source": "executor_selection",
                        },
                        decision_id=self._executor_decision_ids.pop(task.id, None),
                    )
                except Exception as e:
                    logger.warning("Could not report executor outcome to meta-learner: %s", e)

            # Persist to memory for cross-restart learning
            if stats['executions'] % 10 == 0:  # Save every 10 executions
                try:
                    await self.store_memory(
                        MemoryType.META,
                        {
                            "type": "strategy_outcome_summary",
                            "task_type": task_key,
                            "strategy": strategy,
                            "win_rate": stats['wins'] / max(stats['executions'], 1),
                            "avg_time": stats['total_time'] / max(stats['executions'], 1),
                            "total_executions": stats['executions'],
                            "timestamp": datetime.now().isoformat()
                        },
                        importance=0.7,
                        tags=["meta_learning", "strategy_selection", task_key, strategy]
                    )
                except Exception:
                    pass  # Non-critical

        except Exception as e:
            logger.debug(f"Failed to record strategy outcome: {e}")

    def _get_recent_task_outcomes(self, task_type: str, limit: int = 10) -> List[bool]:
        """
        Get recent outcome sequence for task type (for variance/decay analysis).

        Used by StrategyAdaptationGate to compute decay-weighted win rate and
        detect oscillating vs. consistently poor performance.

        Args:
            task_type: TaskType.value string
            limit: Maximum number of recent outcomes to return

        Returns:
            List of boolean outcomes [True=success, False=failure], most recent last
        """
        try:
            if not self.task_queue or not hasattr(self.task_queue, 'tasks_by_id'):
                return []

            # Query task queue for recent tasks of this type
            recent_tasks = []
            for task in list(self.task_queue.tasks_by_id.values())[-30:]:
                if hasattr(task, 'type') and task.type.value == task_type:
                    recent_tasks.append(task)

            if not recent_tasks:
                return []

            # Convert to outcome booleans (based on task status)
            outcomes = []
            for task in recent_tasks[-limit:]:
                if hasattr(task, 'status'):
                    status_str = str(task.status).lower()
                    # Completed = success, anything else = failure
                    outcomes.append(status_str == "completed")

            return outcomes

        except Exception as e:
            logger.debug(f"Error fetching recent outcomes for {task_type}: {e}")
            return []

    async def _learning_phase(self):
        """Apply learning recommendations and score the cycle's intrinsic rewards.

        Registered as the `idle_learning` tier. Written for the old phase loop
        and left uncalled by the AI-driven rewrite, so nothing consumed the
        experience learner's output.
        """
        if getattr(self, "learning", None) is None:
            logger.debug("[IDLE:LEARNING] No learning adapter — skipping")
            self._learning_phase_status = "NO_ADAPTER"
            return

        # Set to COMPLETED only at the terminal write. A phase that boosts a
        # priority and then dies on the reward calls did real work and lost the
        # rest of the cycle, which must not read as a successful learning cycle.
        self._learning_phase_status = "PARTIAL"
        applied_recommendations = []  # referenced by the abort handler

        try:
            # Get learning recommendations
            context = {
                "system_mode": self.system_state.mode.value,
                "active_goals": len(self.system_state.active_goals),
                "resource_usage": self.system_state.resource_usage
            }
            
            # The SubstrateLearning authority does not emit "recommendations" —
            # that was the retired LearningAdapter's paradigm. This phase was
            # already dead (uncalled by the rewrite); it no-ops on the authority.
            recommendations = (
                await self.learning.get_recommendations(context)
                if hasattr(self.learning, "get_recommendations") else []
            )
            
            # Apply high-confidence recommendations and calculate intrinsic rewards
            applied_recommendations = []
            # SUM of per-event rewards fired this cycle. UNBOUNDED — four
            # dimensions each in [-1,1] means this ranges roughly [-4,4].
            # Deliberately NOT named total_intrinsic_reward: that name belongs
            # to MotivationProfile's normalised drive level in [0,1], and the
            # collision produced 'Total reward: 1.70' in a field contracted to
            # [0,1]. Never feed this to AppraisalState.activation.
            cycle_reward_sum = 0.0
            
            for rec in recommendations:
                if rec.get("confidence", 0) > 0.8:
                    success = await self._apply_learning_recommendation(rec)
                    if success:
                        applied_recommendations.append(rec)
                        
                        # Calculate competence reward for successful learning application
                        competence_reward = await self.intrinsic_motivation.calculate_competence_reward(
                            # Competence accrues to the task type that earned
                            # it, not to the applier verb -- keyed on "type"
                            # every skill would be named prioritize_task_type.
                            skill_name=(
                                rec.get("action", {}).get("task_type")
                                or rec.get("action", {}).get("type", "general_learning")
                            ),
                            performance=rec.get("confidence", 0.8),
                            success=True
                        )
                        cycle_reward_sum += competence_reward.reward_value
            
            # Identify exploration targets from perception data
            perception_stats = await self.perception.get_statistics()
            if perception_stats.get("novel_patterns", 0) > 0:
                # Calculate curiosity reward for discovering novel patterns
                curiosity_reward = await self.intrinsic_motivation.calculate_curiosity_reward({
                    "information_gain": min(1.0, perception_stats.get("novel_patterns", 0) / 10.0),
                    "uncertainty_reduction": 0.5,
                    "question_complexity": 0.6,
                    "answer_depth": 0.5
                })
                cycle_reward_sum += curiosity_reward.reward_value
            
            # Calculate novelty reward for current cycle
            cycle_experience = {
                "active_goals": len(self.system_state.active_goals),
                "active_tasks": len(self.system_state.active_tasks),
                "cycle_count": self.stats["cycles_completed"],
                "resource_usage": self.system_state.resource_usage
            }
            novelty_reward = await self.intrinsic_motivation.calculate_novelty_reward(cycle_experience)
            cycle_reward_sum += novelty_reward.reward_value
            
            # Calculate autonomy reward (coordination is self-directed)
            autonomy_reward = await self.intrinsic_motivation.calculate_autonomy_reward({
                "self_initiated": True,
                "choice_made": len(recommendations) > 0,
                "exploration_ratio": 0.5  # Balanced exploration/exploitation
            })
            cycle_reward_sum += autonomy_reward.reward_value
            
            # Get top exploration targets for next cycle
            exploration_targets = await self.intrinsic_motivation.get_top_exploration_targets(limit=5)
            
            # Store learning insights in memory with intrinsic reward information
            if applied_recommendations or cycle_reward_sum > 0.1:
                await self.store_memory(
                    MemoryType.PROCEDURAL,
                    {
                        "event": "learning_with_intrinsic_rewards",
                        "recommendations": applied_recommendations,
                        "cycle_reward_sum": cycle_reward_sum,
                        "exploration_targets": [t.description for t in exploration_targets],
                        "context": context,
                        "timestamp": datetime.now().isoformat()
                    },
                    # CLAMPED. cycle_reward_sum is unbounded, so this produced
                    # importance=1.14 — and store_memory passes importance
                    # straight through as confidence_score, yielding a
                    # "confidence" above 1.0 in a field that is a probability.
                    importance=max(0.0, min(1.0, 0.8 + (cycle_reward_sum * 0.2))),
                    tags=["learning", "intrinsic_motivation", "autonomous_cycle"]
                )
            
            # Log intrinsic motivation insights
            if cycle_reward_sum > 0.5:
                logger.info(f"🌟 High intrinsic motivation cycle! Cycle reward SUM (unbounded): {cycle_reward_sum:.2f}")

            self._learning_phase_status = "COMPLETED"

        except Exception as e:
            self._learning_phase_status = "ABORTED"
            logger.error(
                f"Learning phase ABORTED after applying "
                f"{len(applied_recommendations)} recommendation(s) — rewards and "
                f"memory write for this cycle are lost: {e}"
            )

            import traceback
            # The handler must not be more fragile than the path it reports on:
            # an unguarded self.log_db here replaces the real failure with an
            # AttributeError and hides what actually broke.
            log_db = getattr(self, "log_db", None)
            if log_db is not None:
                try:
                    log_db.log_error(
                        error_type=type(e).__name__,
                        error_message=str(e),
                        module='autonomous_coordinator',
                        function='_learning_phase',
                        stack_trace=traceback.format_exc(),
                        context={}
                    )
                except Exception as log_error:
                    logger.error(f"Could not record learning phase abort: {log_error}")
            else:
                logger.error(
                    "Learning phase abort not recorded: no log_db\n%s",
                    traceback.format_exc(),
                )

    async def _execute_registered_capabilities(self):
        """
        Execute registered system capabilities based on conditions and intervals.
        
        This method enables TRUE ADAPTIVE INTELLIGENCE by allowing the coordinator to decide
        when capabilities should run based on system state, not hardcoded timers.
        
        Capabilities are checked in priority order (critical > high > medium > low) and
        executed only if:
        1. Minimum interval has elapsed since last run
        2. All configured conditions are met (feedback samples, performance, etc.)
        
        This transforms rigid "run every N seconds" into intelligent "run when needed"
        based on system feedback, performance metrics, and resource availability.
        """
        if not hasattr(self, 'registered_capabilities') or not self.registered_capabilities:
            return  # No capabilities registered yet
        
        try:
            now = datetime.now()
            
            # Sort capabilities by priority
            priority_order = {'critical': 0, 'high': 1, 'medium': 2, 'low': 3}
            sorted_capabilities = sorted(
                self.registered_capabilities.items(),
                key=lambda x: priority_order.get(x[1]['priority'], 4)
            )
            
            for cap_name, cap_config in sorted_capabilities:
                try:
                    # Skip if not active
                    if cap_config['status'] != 'active':
                        continue
                    
                    # Check interval - has enough time passed?
                    last_run = self.capability_last_run.get(cap_name, datetime.min)
                    elapsed = (now - last_run).total_seconds()
                    interval = cap_config['interval']
                    
                    if elapsed < interval:
                        continue  # Not time yet
                    
                    # Check all conditions
                    conditions = cap_config['conditions']
                    if not await self._check_capability_conditions(cap_name, conditions):
                        logger.debug(f"Capability '{cap_name}' conditions not met, skipping")
                        continue
                    
                    # Execute the capability
                    instance = cap_config['instance']
                    method_name = cap_config['method']
                    method = getattr(instance, method_name)

                    logger.info(f"🔧 Executing capability: {cap_name} (priority: {cap_config['priority']})")

                    # Log capability execution start
                    self.log_db.log_coordination(
                        coordinator_type='autonomous',
                        action='capability_execution_start',
                        status='executing',
                        metadata={
                            'capability': cap_name,
                            'priority': cap_config['priority'],
                            'elapsed_since_last': elapsed,
                            'execution_count': cap_config['execution_count']
                        }
                    )

                    import time
                    start_time = time.time()

                    # Call the method (handle both async and sync)
                    if asyncio.iscoroutinefunction(method):
                        result = await method()
                    else:
                        result = method()

                    execution_time = time.time() - start_time

                    # Update tracking
                    self.capability_last_run[cap_name] = now
                    cap_config['execution_count'] += 1
                    cap_config['last_result'] = result
                    cap_config['last_error'] = None

                    logger.info(f"✅ Capability '{cap_name}' executed successfully (run #{cap_config['execution_count']})")

                    # Log successful capability execution
                    self.log_db.log_coordination(
                        coordinator_type='autonomous',
                        action='capability_execution_complete',
                        status='completed',
                        result=f"Capability '{cap_name}' executed successfully",
                        metadata={
                            'capability': cap_name,
                            'priority': cap_config['priority'],
                            'execution_count': cap_config['execution_count'],
                            'execution_time': execution_time
                        }
                    )

                    # Log performance metrics
                    self.log_db.log_performance(
                        operation='capability_execution',
                        duration=execution_time,
                        success=True,
                        details={
                            'capability': cap_name,
                            'priority': cap_config['priority'],
                            'execution_count': cap_config['execution_count']
                        }
                    )

                    # Store execution in memory for learning
                    await self.store_memory(
                        MemoryType.PROCEDURAL,
                        {
                            'event': 'capability_execution',
                            'capability': cap_name,
                            'priority': cap_config['priority'],
                            'result': str(result)[:500] if result else None,  # Truncate large results
                            'execution_count': cap_config['execution_count'],
                            'execution_time': execution_time,
                            'timestamp': now.isoformat()
                        },
                        importance=0.7 if cap_config['priority'] in ['critical', 'high'] else 0.5,
                        tags=['capability', 'autonomous', cap_name]
                    )

                except Exception as e:
                    logger.error(f"Error executing capability '{cap_name}': {e}")
                    cap_config['last_error'] = str(e)
                    cap_config['status'] = 'error'

                    import traceback
                    # Log error with full details
                    self.log_db.log_error(
                        error_type=type(e).__name__,
                        error_message=str(e),
                        module='autonomous_coordinator',
                        function='_execute_registered_capabilities',
                        stack_trace=traceback.format_exc(),
                        context={
                            'capability': cap_name,
                            'priority': cap_config['priority'],
                            'method': method_name
                        }
                    )
                    
        except Exception as e:
            logger.error(f"Error in capability execution phase: {e}")

            import traceback
            # Log error with full details
            self.log_db.log_error(
                error_type=type(e).__name__,
                error_message=str(e),
                module='autonomous_coordinator',
                function='_execute_registered_capabilities',
                stack_trace=traceback.format_exc(),
                context={'registered_capabilities_count': len(self.registered_capabilities) if hasattr(self, 'registered_capabilities') else 0}
            )

    async def _check_capability_conditions(self, cap_name: str, conditions: Dict[str, Any]) -> bool:
        """
        Check if all conditions for a capability are met.
        
        Args:
            cap_name: Capability name (for logging)
            conditions: Dict of condition checks
        
        Returns:
            True if all conditions met, False otherwise
        """
        try:
            # Check feedback sample minimum
            if 'min_feedback_samples' in conditions:
                min_samples = conditions['min_feedback_samples']
                # Query feedback count from memory using MemoryQuery
                try:
                    from core.memory import MemoryQuery, MemoryType
                    
                    feedback_query = MemoryQuery(
                        query_id=f"capability_check_{cap_name}_{datetime.now().timestamp()}",
                        content="user feedback and ratings",
                        memory_types=[MemoryType.EPISODIC],
                        max_results=min_samples + 10,  # Fetch a bit more to ensure we get enough
                        min_confidence=0.0
                    )
                    result = await self.memory.search_memories(feedback_query)
                    
                    # Filter for feedback-related memories
                    feedback_count = sum(1 for m in result.memories if 'feedback' in str(m.content).lower() or 'rating' in str(m.content).lower())
                    
                    if feedback_count < min_samples:
                        logger.debug(f"Capability '{cap_name}': Insufficient feedback samples ({feedback_count}/{min_samples})")
                        return False
                except Exception as e:
                    logger.debug(f"Could not query feedback memories: {e}")
                    # If we can't check, allow execution (fail open for this condition)
            
            # Check performance threshold
            if 'performance_threshold' in conditions:
                threshold = conditions['performance_threshold']
                # Resource usage might be a dict or float
                resource_usage = self.system_state.resource_usage
                if isinstance(resource_usage, dict):
                    current_performance = resource_usage.get('system_health', 1.0)
                else:
                    current_performance = 1.0  # Assume healthy if no data
                
                if current_performance < threshold:
                    logger.debug(f"Capability '{cap_name}': Performance below threshold ({current_performance:.2f}/{threshold})")
                    return False
            
            # Check error rate
            if 'error_rate_max' in conditions:
                max_error_rate = conditions['error_rate_max']
                current_error_rate = self.stats.get('error_rate', 0.0)
                
                if current_error_rate > max_error_rate:
                    logger.debug(f"Capability '{cap_name}': Error rate too high ({current_error_rate:.2f}/{max_error_rate})")
                    return False
            
            # Check memory usage
            if 'memory_usage_max' in conditions:
                max_memory = conditions['memory_usage_max']
                resource_usage = self.system_state.resource_usage
                if isinstance(resource_usage, dict):
                    current_memory = resource_usage.get('memory_percent', 0.0)
                else:
                    current_memory = 0.0  # Assume OK if no data
                
                if current_memory > max_memory:
                    logger.debug(f"Capability '{cap_name}': Memory usage too high ({current_memory:.2f}/{max_memory})")
                    return False
            
            # Custom check function
            if 'custom_check' in conditions:
                check_func = conditions['custom_check']
                if callable(check_func):
                    if asyncio.iscoroutinefunction(check_func):
                        result = await check_func(self)
                    else:
                        result = check_func(self)
                    
                    if not result:
                        logger.debug(f"Capability '{cap_name}': Custom check failed")
                        return False
            
            return True  # All conditions met
            
        except Exception as e:
            logger.error(f"Error checking conditions for '{cap_name}': {e}")
            return False  # Fail safe - don't execute if condition check fails
    
    async def _check_task_completions(self):
        """Check for task completions and update system state"""
        try:
            execution_status = await self.executor.get_execution_status()

            # Get completed tasks from execution controller
            completed_count = execution_status.get("completed_tasks", 0)

            # Check which of our active tasks have completed
            completed_task_ids = []

            # The execution controller maintains completed_tasks dict
            # We need to check if our active tasks are in there
            for task_id in list(self.system_state.active_tasks):
                # Check with execution controller if task completed
                # Completed tasks are moved from running_tasks to completed_tasks
                if task_id in self.executor.completed_tasks:
                    completed_task = self.executor.completed_tasks[task_id]

                    # Verify it actually completed successfully
                    if completed_task.status == TaskStatus.COMPLETED:
                        completed_task_ids.append(task_id)

                        # Log completion details
                        execution_time = "N/A"
                        execution_time_seconds = 0.0
                        if completed_task.completed_at and completed_task.created_at:
                            execution_time_seconds = (completed_task.completed_at - completed_task.created_at).total_seconds()
                            execution_time = f"{execution_time_seconds:.2f}s"

                        logger.info(
                            f"✅ Task completed: {completed_task.description} "
                            f"(execution time: {execution_time})"
                        )

                        # Record to constitutional framework if relevant
                        if hasattr(completed_task, 'result') and completed_task.result:
                            quality_score = completed_task.result.get('quality_score', 0.8)
                        else:
                            quality_score = 0.8  # Default for successful tasks

                        # Log task completion coordination
                        self.log_db.log_coordination(
                            coordinator_type='autonomous',
                            action='task_completion_verified',
                            task_id=task_id,
                            status='completed',
                            result=f'Task verified as completed: {completed_task.description[:100]}',
                            metadata={
                                'execution_time': execution_time_seconds,
                                'quality_score': quality_score,
                                'task_type': completed_task.type.value if hasattr(completed_task, 'type') else 'unknown'
                            }
                        )

                    elif completed_task.status == TaskStatus.FAILED:
                        # Remove from active but don't count as completion
                        completed_task_ids.append(task_id)
                        logger.warning(f"❌ Task failed: {completed_task.description}")

                        # Log task failure coordination
                        self.log_db.log_coordination(
                            coordinator_type='autonomous',
                            action='task_completion_verified',
                            task_id=task_id,
                            status='failed',
                            result=f'Task verified as failed: {completed_task.description[:100]}',
                            metadata={
                                'task_type': completed_task.type.value if hasattr(completed_task, 'type') else 'unknown',
                                'failure_reason': completed_task.result.get('reason') if hasattr(completed_task, 'result') and completed_task.result else 'unknown'
                            }
                        )
                        self.stats["tasks_failed"] += 1
            
            # Update statistics and remove completed tasks
            for task_id in completed_task_ids:
                if task_id in self.system_state.active_tasks:
                    self.system_state.active_tasks.remove(task_id)
                    
                    # Only count successful completions
                    task = self.executor.completed_tasks[task_id]
                    if task.status == TaskStatus.COMPLETED:
                        self.stats["tasks_completed"] += 1

                        # Update planning engine
                        await self.planning.update_task_status(
                            task_id,
                            TaskStatus.COMPLETED,
                            task.result
                        )

                    # NOTE: the adaptive task-type reward is NOT collected here.
                    # This scanner only ever sees tasks from the legacy
                    # _execution_phase path, and no task carrying an adaptive
                    # decision reaches it -- exploration tasks are queued and run
                    # through _execute_and_validate_task, which is where the
                    # authoritative outcome is established and where the reward
                    # is now recorded.
            
            # Log summary if any tasks completed
            if completed_task_ids:
                logger.info(
                    f"Task completion cycle: {len(completed_task_ids)} tasks finished "
                    f"(successful: {self.stats['tasks_completed']}, "
                    f"failed: {self.stats['tasks_failed']})"
                )
            
        except Exception as e:
            logger.error(f"Error checking task completions: {e}")

            import traceback
            # Log error with full details
            self.log_db.log_error(
                error_type=type(e).__name__,
                error_message=str(e),
                module='autonomous_coordinator',
                function='_check_task_completions',
                stack_trace=traceback.format_exc(),
                context={'active_tasks_count': len(self.system_state.active_tasks)}
            )

    async def _analyze_for_goal_creation(self, perception_data: PerceptionData) -> Optional[str]:
        """Analyze perception data to determine if a new goal should be created"""
        try:
            # Simple heuristics for goal creation
            content = perception_data.content
            
            # Check for explicit requests
            if "request" in content or "goal" in content:
                description = content.get("text", f"Handle {perception_data.data_type} input")
                goal = await self.planning.create_goal(description, Priority.MEDIUM)
                if goal:
                    self.system_state.active_goals.append(goal.id)
                    return goal.id
            
            return None
            
        except Exception as e:
            logger.error(f"Error analyzing for goal creation: {e}")
            return None
    
    async def _apply_learning_recommendation(self, recommendation: Dict[str, Any]) -> bool:
        """Apply a learning recommendation; report whether state actually changed.

        This returned None on every path, so the caller's `if success:` was
        never true: no recommendation was ever counted as applied and no
        competence reward was ever awarded, however well it worked.
        """
        try:
            action = recommendation.get("action", {})
            action_type = action.get("type", "unknown")
            
            logger.info(f"Applying learning recommendation: {action_type}")
            
            # Apply different types of recommendations
            if action_type == "adjust_cycle_interval":
                new_interval = action.get("value", self.coordination_cycle_interval)
                # Allow longer intervals (up to 1 hour) to support deep thinking cycles
                self.coordination_cycle_interval = max(1.0, min(3600.0, new_interval))
                return True
            
            elif action_type == "prioritize_task_type":
                task_type = action.get("task_type")
                priority_boost = action.get("priority_boost", 0.2)
                boosted = 0
                
                # Adjust task prioritization in planning engine
                # This increases priority for tasks of a specific type
                logger.info(f"Boosting priority for task type: {task_type} by {priority_boost}")
                
                # Get all active plans from planning engine
                for plan_id, plan in self.planning.active_plans.items():
                    for task in plan.tasks:
                        # Check if task matches the type to prioritize.
                        #
                        # task.type is a TaskType enum, so str() yields
                        # "TaskType.RESEARCH" -- never equal to "research".
                        # This condition could not match any task at all.
                        task_type_value = getattr(task, 'type', None)
                        task_type_value = getattr(task_type_value, 'value', task_type_value)
                        if task_type_value is not None and str(task_type_value).lower() == str(task_type).lower():
                            # Boost the task priority
                            current_priority = task.priority
                            
                            # Map priority to numeric, boost, then map back
                            priority_map = {
                                Priority.LOW: 1,
                                Priority.MEDIUM: 2,
                                Priority.HIGH: 3,
                                Priority.CRITICAL: 4
                            }
                            
                            priority_value = priority_map.get(current_priority, 2)
                            new_priority_value = min(4, priority_value + 1)  # Boost by one level
                            
                            # Reverse map back to Priority enum
                            reverse_map = {1: Priority.LOW, 2: Priority.MEDIUM, 3: Priority.HIGH, 4: Priority.CRITICAL}
                            task.priority = reverse_map.get(new_priority_value, Priority.HIGH)
                            boosted += 1


                            logger.info(
                                f"   Boosted task '{task.description[:50]}...' "
                                f"from {current_priority.name} to {task.priority.name}"
                            )
                    
                    # Update plan in database
                    await self.planning._store_plan(plan)
                
                # Also boost future goals related to this task type
                for goal_id, goal in self.planning.current_goals.items():
                    # Check if goal description relates to this task type
                    if task_type.lower() in goal.description.lower():
                        current_priority = goal.priority
                        
                        priority_map = {
                            Priority.LOW: 1,
                            Priority.MEDIUM: 2,
                            Priority.HIGH: 3,
                            Priority.CRITICAL: 4
                        }
                        
                        priority_value = priority_map.get(current_priority, 2)
                        new_priority_value = min(4, priority_value + 1)
                        
                        reverse_map = {1: Priority.LOW, 2: Priority.MEDIUM, 3: Priority.HIGH, 4: Priority.CRITICAL}
                        goal.priority = reverse_map.get(new_priority_value, Priority.HIGH)
                        boosted += 1
                        
                        logger.info(
                            f"   Boosted goal '{goal.description[:50]}...' "
                            f"from {current_priority.name} to {goal.priority.name}"
                        )
                        
                        # Update goal in database
                        await self.planning._store_goal(goal)
                
                logger.info(
                    f"✅ Task type '{task_type}' prioritization adjustment complete "
                    f"({boosted} item(s) boosted, requested boost {priority_boost})"
                )
                # "Applied" means state changed. Matching nothing is not a
                # successful application, and must not earn a reward.
                return boosted > 0
            
            elif action_type == "allocate_resources":
                resource_type = action.get("resource_type")
                allocation = action.get("allocation", 1.0)
                self.system_state.resources[resource_type] = allocation
                return True

            logger.warning(
                f"No applier for recommendation action '{action_type}' — ignored"
            )
            return False
            
        except Exception as e:
            logger.error(f"Error applying learning recommendation: {e}")
            return False

    async def _update_system_state(self):
        """Refresh the substrate's self-state from its real subsystems.

        This is the SOLE writer of system_state.resource_usage / timestamp /
        performance_metrics — the exact fields the constitution's law-compliance
        check reads (singleton_constitution._check_law_compliance). It was dead,
        so the constitution had only stale init values to read; scheduling this
        is what makes those reads honest.

        Each metric is sourced from the authority that OWNS it, and a source that
        cannot be read is logged and its metric LEFT ABSENT — never written as a
        fabricated value — so a missing signal is honestly missing, not a fake
        number. Sources are split into their own try/excepts so one failing
        subsystem never blanks the others."""
        self.system_state.timestamp = datetime.now().timestamp()
        metrics = self.system_state.performance_metrics

        # NOTE: resource_usage (CPU/memory) is the HEALTH monitor's real psutil
        # sample, NOT the executor's — the old code called a get_execution_status()
        # that never existed, which is part of why this method was dead. It is set
        # from real health data in _check_constitutional_alignment, which already
        # reads the health authority; duplicating a psutil sample here would stand
        # up a second resource authority.

        # error_rate — the TASK QUEUE owns task outcomes; the honest rate is
        # failed / (completed + failed). Written only once tasks have actually
        # finished, so a fresh system is never scored flawless on zero evidence.
        try:
            qm = self.task_queue.get_metrics()
            completed = int(qm.get("tasks_completed", 0))
            failed = int(qm.get("tasks_failed", 0))
            finished = completed + failed
            if finished > 0:
                metrics["error_rate"] = failed / finished
        except Exception as e:
            logger.warning("system_state: error_rate unreadable: %s", e)

        # goal_alignment — the APPRAISAL system owns goal congruence (derived from
        # task-verification goal-alignment scores). Written only when the
        # authority actually holds a value, never defaulted.
        try:
            appr = self._appraisal().current_state
            gc = getattr(appr, "goal_congruence", None) if appr else None
            if gc is not None:
                metrics["goal_alignment"] = float(gc)
        except Exception as e:
            logger.warning("system_state: goal_alignment unreadable: %s", e)

        # Perception / planning transparency signals.
        try:
            perception_stats = await self.perception.get_statistics()
            planning_status = await self.planning.get_planning_status()
            metrics.update({
                "perception_queue_length": perception_stats.get("queue_length", 0),
                "active_plans": planning_status.get("active_plans", 0),
                "pending_tasks": planning_status.get("pending_tasks", 0),
            })
        except Exception as e:
            logger.warning("system_state: perception/planning metrics unreadable: %s", e)
    
    async def shutdown(self):
        """Shutdown the autonomous system gracefully"""
        logger.info("Shutting down autonomous system...")
        
        self.active = False
        
        # Cancel coordination cycle
        if self.coordination_task:
            self.coordination_task.cancel()
            try:
                await self.coordination_task
            except asyncio.CancelledError:
                pass

        # Cancel the reactive drain worker
        if self._reactive_worker:
            self._reactive_worker.cancel()
            try:
                await self._reactive_worker
            except asyncio.CancelledError:
                pass

        # Cancel the coalescing motivation-refresh task if one is in flight
        if self._motivation_refresh_task and not self._motivation_refresh_task.done():
            self._motivation_refresh_task.cancel()
            try:
                await self._motivation_refresh_task
            except asyncio.CancelledError:
                pass

        # Cancel periodic performance assessment
            logger.info("✅ Periodic performance assessment stopped")

        # Shutdown modules
        modules = [
            ("Learning Adapter", self.learning),
            ("Intrinsic Motivation System", self.intrinsic_motivation),
            ("Execution Controller", self.executor),
            ("Planning Engine", self.planning),
            ("Perception Manager", self.perception)
        ]
        
        for name, module in modules:
            try:
                await module.shutdown()
                logger.info(f"{name} shutdown completed")
            except Exception as e:
                logger.error(f"Error shutting down {name}: {e}")
        
        logger.info("Autonomous system shutdown completed")
    
    # =========================================================================
    # ENHANCED REASONING & LEARNING - Singleton's Unified Intelligence
    # =========================================================================
    
    def get_intelligence_capabilities(self) -> Dict[str, Any]:
        """
        Get all intelligence capabilities available to the Singleton
        
        Enhanced reasoning and learning systems accessible across the entire system
        """
        return {
            "abstract_reasoning": self.abstract_reasoning,
            "quantum_reasoning": self.quantum_reasoning,
            "proof_engine": self.proof_engine,
            "neural_bridge": self.neural_bridge,
            "unified_learning": self.learning,
            "meta_learning": self.meta_learning,
            "causal_analyzer": self.causal_analyzer,
            "status": {
                "abstract_reasoning_ready": self.abstract_reasoning is not None,
                "quantum_reasoning_ready": self.quantum_reasoning is not None,
                "proof_engine_ready": self.proof_engine is not None,
                "neural_bridge_ready": self.neural_bridge is not None,
                "unified_learning_ready": getattr(self.learning, "initialized", False),
                "meta_learning_ready": self.meta_learning is not None,
                "causal_analysis_ready": self.causal_analyzer is not None,
            }
        }

    async def _receive_health_event(self, health_event: Dict[str, Any]):
        """
        Process health event with AI-powered analysis using Obsidian3.

        This method enables the Singleton to use its intelligence (Obsidian3-14B)
        to analyze system health issues, determine root causes, and execute
        autonomous recovery actions.

        Args:
            health_event: Health event from MonitoringCoordinator
        """
        try:
            # Skip health events during startup grace period to avoid false positives
            # Use time-based check (45 seconds) which is more reliable than flag-based
            import time
            if self.monitoring_coordinator and hasattr(self.monitoring_coordinator, '_init_timestamp'):
                elapsed = time.time() - self.monitoring_coordinator._init_timestamp
                grace_period = getattr(self.monitoring_coordinator, '_startup_grace_seconds', 45)
                if elapsed < grace_period:
                    logger.debug(f"Ignoring health event during startup ({elapsed:.1f}s < {grace_period}s): {health_event.get('event_type')}")
                    return
            
            logger.info(f"🧠 AI analyzing health event: {health_event.get('event_type', 'unknown')}")

            # Extract event details
            event_type = health_event.get('event_type', 'unknown')
            severity = health_event.get('severity', 'unknown')
            component = health_event.get('component', 'unknown')
            proposed_actions = health_event.get('proposed_actions', [])

            # Check if this is a recurring failure (query RecoveryManager history)
            is_recurring = False
            failure_count = 0
            if self.recovery_manager:
                try:
                    failure_history = await self.recovery_manager.get_failure_history(
                        component=component,
                        limit=10
                    )
                    failure_count = len(failure_history)
                    is_recurring = failure_count >= 3
                    if is_recurring:
                        logger.warning(f"🔁 RECURRING FAILURE detected: {component} has failed {failure_count} times")
                except Exception as e:
                    logger.warning(f"Could not check failure history: {e}")

            # Check for performance degradation (proactive optimization trigger)
            is_performance_degradation = False
            degradation_severity = None
            if self.improvement_monitor and event_type in ['performance_degradation', 'health_score_drop', 'latency_increase']:
                try:
                    # Get component health history
                    from core.learning.improvement_monitor import MetricType

                    # Check if component health is trending downward
                    # SAME DEFECT as EnhancedASISelfImprovement._get_component_health:
                    # `state` is a SystemImprovementState dataclass, not a dict, and
                    # its per-component map is `component_health`, not `components`.
                    # The lookup could never match, so health_score fell to the
                    # 100.0 default on every event -- and `< 85` is never true at
                    # 100.0, which means performance degradation was undetectable
                    # by construction, not by absence of degradation.
                    state = await self.improvement_monitor.get_system_state()
                    measured = (state.get("component_health") if isinstance(state, dict)
                                else getattr(state, "component_health", None)) or {}
                    entry = measured.get(component)
                    if entry is None:
                        # Unmeasured. NOT assumed healthy -- assuming 100 is
                        # exactly what silenced this path. No verdict is reached
                        # from a measurement that does not exist.
                        logger.info(
                            "No health measurement for %r; degradation cannot be "
                            "assessed from health score", component)
                    else:
                        health_score = float(
                            entry["health_score"] if isinstance(entry, dict)
                            else entry.health_score)

                        if health_score < 85:  # Below 85% = performance degradation
                            is_performance_degradation = True
                            if health_score < 70:
                                degradation_severity = "CRITICAL"
                            elif health_score < 80:
                                degradation_severity = "HIGH"
                            else:
                                degradation_severity = "MODERATE"

                            logger.warning(f"📉 PERFORMANCE DEGRADATION detected: {component} health={health_score:.1f}% (severity: {degradation_severity})")
                except Exception as e:
                    logger.warning(f"Could not check performance degradation: {e}")

            # Use Obsidian3 to analyze the health event
            analysis = await self._diagnose_health(health_event, is_recurring=is_recurring, failure_count=failure_count)

            if not analysis:
                logger.warning("AI health analysis returned no results")
                return

            # Determine if immediate action is required
            if analysis.get('immediate_action_required'):
                logger.warning(f"⚠️ IMMEDIATE ACTION REQUIRED for {component}")

                # If this is a recurring failure (>= 3 times), trigger ASI for code repair
                if is_recurring and self.asi_self_improvement:
                    logger.info(f"🔧 RECURRING FAILURE → Triggering ASI code repair for {component}")
                    from core.learning import ImprovementScope
                    try:
                        result = await self.asi_self_improvement.run_improvement_cycle(
                            scope=ImprovementScope.MODERATE,  # Moderate scope for fixes
                            target_components=[component],
                            context={
                                "trigger": "recurring_health_failure",
                                "component": component,
                                "failure_count": failure_count,
                                "event_type": event_type,
                                "severity": severity,
                                "ai_analysis": analysis,
                                "root_cause": analysis.get('root_cause', 'Unknown')
                            }
                        )
                        logger.info(f"✅ ASI code repair complete: {result.improvements_deployed} improvements deployed")
                        logger.info(f"   Recurring failure in {component} should now be PERMANENTLY FIXED")
                    except Exception as e:
                        logger.error(f"ASI code repair failed: {e}")
                        logger.info("Falling back to tactical recovery")
                        # Fall back to tactical recovery
                        best_action = analysis.get('recommended_action')
                        if best_action and best_action.get('risk_level', 10) <= 5:
                            await self._execute_recovery(best_action, health_event)

                # If performance degradation detected (not failure, but declining performance)
                elif is_performance_degradation and self.asi_self_improvement and degradation_severity in ['HIGH', 'CRITICAL']:
                    logger.info(f"📉 PERFORMANCE DEGRADATION → Triggering ASI optimization for {component}")
                    from core.learning import ImprovementScope

                    # Map degradation severity to improvement scope
                    scope_map = {
                        'CRITICAL': ImprovementScope.MODERATE,
                        'HIGH': ImprovementScope.MINOR,
                        'MODERATE': ImprovementScope.MINOR
                    }
                    scope = scope_map.get(degradation_severity, ImprovementScope.MINOR)

                    try:
                        result = await self.asi_self_improvement.run_improvement_cycle(
                            scope=scope,
                            target_components=[component],
                            context={
                                "trigger": "performance_degradation",
                                "component": component,
                                "degradation_severity": degradation_severity,
                                "event_type": event_type,
                                "ai_analysis": analysis,
                                "optimization_goal": "improve_performance"
                            }
                        )
                        logger.info(f"✅ ASI performance optimization complete: {result.improvements_deployed} improvements deployed")
                        logger.info(f"   Performance degradation in {component} should now be OPTIMIZED")
                    except Exception as e:
                        logger.error(f"ASI performance optimization failed: {e}")

                else:
                    # Execute tactical recovery if risk is acceptable
                    best_action = analysis.get('recommended_action')

                    # UNMEASURED risk is not the same as MAXIMUM risk. Both
                    # correctly withhold the action — fail-safe is right when
                    # deciding whether to act — but they demand different
                    # follow-up, and reporting them identically hid the real
                    # defect: `risk_level` arriving as None produced
                    # "too risky (None/10)", which reads as a measured 10.
                    # (`None <= 5` was also a latent TypeError.)
                    _raw_risk = best_action.get('risk_level') if best_action else None
                    _risk = None
                    if isinstance(_raw_risk, (int, float)) and not isinstance(_raw_risk, bool):
                        _risk = float(_raw_risk)

                    if best_action and _risk is not None and _risk <= 5:
                        logger.info(f"🔧 Executing tactical recovery: {best_action.get('name')}")
                        await self._execute_recovery(best_action, health_event)
                    elif not best_action:
                        logger.warning(
                            "⚠️ No recovery action proposed for %s — alerting administrator",
                            component,
                        )
                    elif _risk is None:
                        logger.warning(
                            "⚠️ Recovery action '%s' has NO risk assessment "
                            "(risk_level=%r) — withholding and alerting administrator. "
                            "This is a missing measurement, not a high-risk action.",
                            best_action.get('name'), _raw_risk,
                        )
                    else:
                        logger.warning(
                            "⚠️ Recovery action '%s' too risky (%.1f/10 > 5) — "
                            "alerting administrator",
                            best_action.get('name'), _risk,
                        )

            else:
                logger.info(f"ℹ️ Health event logged, no immediate action required")

            # === EXPLORATION FEED ===
            # All health events (critical or not) feed into the exploration pipeline.
            # Non-critical events become curiosity signals; critical events become
            # hypothesis candidates for root-cause investigation.
            try:
                error_signal = Exception(
                    f"Health event [{severity}] on {component}: {event_type} — "
                    f"Root cause: {analysis.get('root_cause', 'unknown')}"
                )
                await self._handle_error(error_signal, f"health_event_{component}")
                logger.debug(f"🔬 Health event fed into exploration pipeline: {component}/{event_type}")
            except Exception as feed_err:
                logger.debug(f"Could not feed health event into exploration: {feed_err}")

        except Exception as e:
            logger.error(f"Error processing health event: {e}")
            import traceback
            traceback.print_exc()

    async def _diagnose_health(self, health_event, *, is_recurring: bool = False,
                               failure_count: int = 0):
        """Substrate health diagnosis -- deterministic, model-free.

        The monitor already CLASSIFIES severity and PROPOSES actions, and the
        recovery manager supplies recurrence. This reads that structured signal
        and produces the recovery verdict directly, instead of asking a model to
        re-derive what the substrate already knows. No LLM, and no LLM fallback:
        when the structured signal is thin the verdict is conservatively thin,
        not outsourced. Same shape the caller consumed from the old model path.
        """
        SEVERITY = {"critical": 9, "high": 7, "medium": 5, "low": 3, "unknown": 5}
        severity = SEVERITY.get(str(health_event.get("severity", "unknown")).lower(), 5)
        if is_recurring:
            severity = min(10, severity + 2)  # a failure that keeps recurring is worse

        event_type = health_event.get("event_type", "unknown")
        component = health_event.get("component", "unknown")
        root_cause = f"{event_type} in {component}"
        if is_recurring:
            root_cause += f" (recurring: {failure_count} recent failures)"

        # The monitor's own proposed action is the recommended one; its risk is
        # read from the KIND of action, conservatively for anything unrecognised.
        recommended_action = None
        proposed = health_event.get("proposed_actions") or []
        if proposed:
            first = proposed[0]
            if isinstance(first, dict):
                name, desc, params = (first.get("name", "unknown"),
                                      first.get("description", ""),
                                      first.get("parameters", {}) or {})
            else:
                name, desc, params = str(first), "", {}
            recommended_action = {
                "name": name, "description": desc, "parameters": params,
                "risk_level": self._health_action_risk(name)}

        # Act immediately only when severe AND an action exists AND its risk is
        # acceptable -- the same conservative policy the model was asked to keep.
        risk = recommended_action["risk_level"] if recommended_action else 10
        immediate = bool(severity >= 7 and recommended_action and risk <= 5)

        logger.info("\U0001fa7a Health diagnosis (substrate): severity=%d/10 risk=%d/10 "
                    "action=%s immediate=%s", severity, risk,
                    recommended_action["name"] if recommended_action else None, immediate)
        return {
            "severity": severity,
            "root_cause": root_cause,
            "recommended_action": recommended_action,
            "risk_level": risk,
            "immediate_action_required": immediate,
            "predicted_outcome_no_action": (
                f"{component} likely continues to degrade" if severity >= 7
                else "likely stable without action"),
        }

    @staticmethod
    def _health_action_risk(name: str) -> int:
        """Deterministic risk (1-10) for a recovery action, by its kind. Reversible
        operations are low; code-altering ones are high; the unknown is treated
        conservatively rather than assumed safe."""
        n = (name or "").lower()
        if any(k in n for k in ("restart", "reconnect", "reload", "clear", "flush", "retry", "reset")):
            return 3
        if any(k in n for k in ("scale", "throttle", "adjust", "reconfigure", "rebalance")):
            return 5
        if any(k in n for k in ("rewrite", "patch", "modify", "delete", "drop", "remove")):
            return 8
        return 6

    async def _execute_recovery(self, action: Dict[str, Any], health_event: Dict[str, Any]):
        """
        Execute a recovery action recommended by AI analysis.

        Args:
            action: Recovery action details
            health_event: Original health event
        """
        try:
            action_name = action.get('name', 'unknown')
            parameters = action.get('parameters', {})

            logger.info(f"🔧 Executing recovery action: {action_name}")

            # Get recovery manager from services
            recovery_manager = None
            if hasattr(self, 'recovery_manager') and self.recovery_manager:
                recovery_manager = self.recovery_manager
            else:
                logger.warning("No recovery manager available")
                return

            # Add health event context to parameters
            parameters['health_event'] = health_event
            parameters['component'] = health_event.get('component')

            # Map AI action names to recovery manager actions
            action_map = {
                'reconnect_database': 'reconnect_database',
                'restart_component': 'restart_component',
                'clear_cache': 'clear_component_cache',
                'reset_state': 'reset_component_state'
            }

            recovery_action = action_map.get(action_name, action_name)

            # Execute recovery
            success = await recovery_manager.execute_recovery_action(
                component=health_event.get('component', 'unknown'),
                action=recovery_action,
                parameters=parameters
            )

            if success:
                logger.info(f"✅ Recovery action '{action_name}' completed successfully")

                # Verify recovery after a delay
                await asyncio.sleep(5)
                await self._verify_recovery(health_event.get('component'))
            else:
                logger.error(f"❌ Recovery action '{action_name}' failed")

        except Exception as e:
            logger.error(f"Error executing recovery action: {e}")
            import traceback
            traceback.print_exc()

    async def _on_security_remediation_complete(
        self,
        task: Task,
        result: Dict[str, Any],
        confidence: float
    ):
        """
        Completion callback for security remediation tasks.
        
        Marks the security finding as resolved in security_audit_worker,
        closing the loop: Detection → Remediation → Verification → Closure.
        
        Args:
            task: Completed SECURITY_REMEDIATION task
            result: Task execution result
            confidence: Completion confidence score
        """
        try:
            finding_id = task.metadata.get('finding_id') if task.metadata else None
            
            if not finding_id:
                logger.warning(
                    f"Security remediation task {task.id} missing finding_id in metadata"
                )
                return
            
            # Mark finding resolved in security audit worker
            success = await self.security_audit_worker.resolve_finding(
                finding_id=finding_id,
                resolution_notes=(
                    f"Automated remediation completed\n"
                    f"Task: {task.id}\n"
                    f"Confidence: {confidence:.2%}\n"
                    f"Verification: {result.get('verification_state', 'legacy')} "
                    f"(score: {result.get('completion_score', 0.0):.2f})"
                )
            )
            
            if success:
                logger.info(
                    f"🔒 Security finding {finding_id} marked resolved "
                    f"(task: {task.id}, confidence: {confidence:.0%})"
                )
                
                # Slack notification for security closure
                if self.slack_notifier:
                    severity = task.metadata.get('severity', 'UNKNOWN')
                    severity_emoji = {
                        "CRITICAL": "🔴",
                        "HIGH": "🟠",
                        "MEDIUM": "🟡",
                        "LOW": "🟢"
                    }.get(severity, "⚪")
                    
                    await self.slack_notifier.send_notification(
                        title=f"{severity_emoji} Security Finding Resolved",
                        message=(
                            f"**Finding ID:** {finding_id}\n"
                            f"**Severity:** {severity}\n"
                            f"**Confidence:** {confidence:.0%}\n"
                            f"**Status:** ✅ Remediation verified and closed"
                        ),
                        severity="info",
                        metadata={
                            'finding_id': finding_id,
                            'task_id': task.id,
                            'event_type': 'security_closure'
                        }
                    )
            else:
                logger.error(
                    f"Failed to mark security finding {finding_id} resolved"
                )
                
        except Exception as e:
            logger.error(
                f"Error in security remediation completion callback: {e}",
                exc_info=True
            )
    
    async def _verify_recovery(self, component: str):
        """
        Verify that recovery was successful by checking component health.

        Args:
            component: Component name to verify
        """
        try:
            if not self.health_monitor:
                logger.warning("No health monitor available for verification")
                return

            # Re-check component health
            health_status = await self.health_monitor.check_component_health(component)

            if health_status == "healthy":
                logger.info(f"✅ Recovery verified: {component} is now healthy")
            elif health_status == "degraded":
                logger.warning(f"⚠️ Partial recovery: {component} is degraded")
            else:
                logger.error(f"❌ Recovery failed: {component} is still {health_status}")

        except Exception as e:
            logger.error(f"Error verifying recovery: {e}")


# Convenience function for external use
async def create_autonomous_system(config: Optional[Dict[str, Any]] = None, teacher_model=None) -> AutonomousCoordinator:
    """
    Create an autonomous system coordinator (without initializing).

    Caller must inject dependencies and then call coordinator.initialize() manually.
    This allows dependency injection before initialization.
    """
    coordinator = AutonomousCoordinator(config, teacher_model=teacher_model)
    return coordinator


# Singleton instance
_autonomous_coordinator = None

async def get_autonomous_coordinator(config: Optional[Dict[str, Any]] = None, teacher_model=None) -> Optional[AutonomousCoordinator]:
    """
    Get global autonomous coordinator instance (singleton)

    If the instance doesn't exist it is created, with or without a teacher
    model: the substrate does not require a model to reason. This used to
    return None whenever no model was supplied, which meant a caller with no
    model got no coordinator -- the same "the LLM is mandatory" rule one level
    down, and silent rather than raised.
    """
    global _autonomous_coordinator
    if _autonomous_coordinator is None:
        _autonomous_coordinator = await create_autonomous_system(
            config, teacher_model=teacher_model)
    return _autonomous_coordinator


# =============================================================================
# LANGUAGE / CONVERSATION FACULTY — understanding and reply.
#
# Moved here from self_model.py when the Self was collapsed into this
# coordinator: conversation is not a separate concern from the substrate — it
# is the substrate using its own faculties to read what was said, resolve it
# against what it holds, and answer. It lives WITH the substrate (this module)
# so a reply is composed THROUGH the brain that owns reasoning, memory and
# language, reached via the coordinator's `conversation()` accessor.
# =============================================================================

#: Words that carry structure rather than content. The same small lexicon the
#: sentence machine uses, plus the prepositions that join phrases. Kept tiny and
#: visible: every entry is a place a person decided something.
FUNCTION_WORDS = frozenset({
    "is", "are", "was", "were", "be", "been", "a", "an", "the", "not", "no",
    "of", "in", "on", "at", "to", "by", "for", "with", "from", "and", "or",
    "that", "this", "it", "does", "do", "did", "what", "which", "how", "why",
    "when", "where", "who", "can", "will", "would", "should",
    "tell", "me", "you", "i", "please", "about", "there", "any", "some",
})

#: Longest phrase considered as a single concept name.
MAX_PHRASE = 4

#: A sentence opening with one of these, or ending in a question mark, is being
#: ASKED. Anything else is being TOLD. Stated crudely and on purpose: it is one
#: rule, in one place, and it is wrong in ways you can see rather than in ways
#: buried in a model.
#: Verbs that name an act of SAYING, and the participants who can perform
#: one. A question built out of both is not a question about the world -- it
#: is a question about this conversation, and the conversation's own record is
#: the only thing that can answer it.
SPEECH_ACTS = {
    "ask": "asked", "asks": "asked", "asked": "asked", "asking": "asked",
    "say": "said", "says": "said", "said": "said", "saying": "said",
    "tell": "told", "tells": "told", "told": "told", "telling": "told",
    "mention": "said", "mentions": "said", "mentioned": "said",
    "talk": "discussed", "talking": "discussed", "talked": "discussed",
    "discuss": "discussed", "discussing": "discussed", "discussed": "discussed",
    "answer": "said", "answered": "said", "reply": "said", "replied": "said",
}
#: Who is speaking. `we` is both of us, which makes the answer the subject
#: rather than either side's words.
SPEAKER_THEM = frozenset({"i", "me", "my"})
SPEAKER_ME = frozenset({"you", "your"})
SPEAKER_BOTH = frozenset({"we", "us", "our"})

QUESTION_OPENERS = frozenset({
    "what", "which", "who", "whose", "where", "when", "why", "how", "is", "are",
    "was", "were", "does", "do", "did", "can", "could", "will", "would",
    "should", "tell", "explain", "define",
})

#: How many turns a conversation keeps. Continuity is recent -- "what were we
#: talking about" and the referent a feedback verdict judges both live in the
#: last handful of turns -- so a generous cap preserves it while stopping the
#: per-turn append from growing without bound for the life of the object.
_CONVERSATION_TURN_MEMORY = 256

#: How far back a verdict may reach for the claim it is about. Feedback follows
#: the thing it judges closely; a small window keeps "no, that's wrong" attached
#: to what was just taught rather than to something said long ago.
_FEEDBACK_WINDOW = 5

#: Endings stripped to compare a word in a question against a relation label
#: held on a concept: `causes` against `caused by`. Crude and visible, which is
#: better than a hidden one -- and it is used ONLY to match what is already
#: stored, never to decide what anything means.
from core.semantics.lexical_normalization import match_key

#: How a stored relation says it is denied. `concept_ingestion` writes the
#: third element of a relationship entry; anything not in this set is read as
#: an affirmation.
NEGATIVE_POLARITIES = frozenset({"negative", "denies", "false", "no"})

def _as_pairs(relations) -> Tuple[Tuple[str, str], ...]:
    """(relation, object) pairs, with polarity folded into the relation.

    A stored relation may carry a third element saying it is denied. Readers
    that unpack two values crash on it, and readers that slice it to two lose
    the denial -- which turns "a kestrel is not a fish" into the claim that it
    IS one. Folding it into the relation keeps the claim intact in a shape one
    reader can handle.
    """
    out = []
    for entry in relations or ():
        if not isinstance(entry, (list, tuple)) or len(entry) < 2:
            continue
        relation, other = str(entry[0]), str(entry[1])
        if len(entry) > 2 and str(entry[2]).lower() in NEGATIVE_POLARITIES:
            relation = "is not" if relation == "is" else f"not {relation}"
        out.append((relation, other))
    return tuple(out)


_ENDINGS = ("ed", "es", "s", "ing")


def stem(word: str) -> str:
    """The retrieval form of a word. Owned by lexical_normalization.

    THIS CHOPPED FIXED ENDINGS AND PRODUCED NON-WORDS: `files` -> `fil`,
    `indices` -> `indic`, `analyses` -> `analys`, `batteries` -> `batteri`,
    `physics` -> `physic`. It handled no irregular at all, so `geese` never
    matched `goose` and `children` never matched `child` -- and this function
    is what `same_stem` uses to decide whether something you say matches a
    relation the substrate ALREADY HOLDS. A miss here reads as the substrate
    not knowing something it does know.

    This sits at the chat -> substrate boundary, which is exactly where the
    shared vocabulary has to hold, so it delegates to the module that declares
    it rather than keeping a third private copy.
    """
    return match_key(word) or word.lower().strip()


def same_stem(left: str, right: str) -> bool:
    """Whether two words are the same word for the purpose of matching a
    relation already stored. `visualizes` stems to `visualiz` and `visualize`
    stems to itself, so exact equality is not enough and a longer list of
    endings would only move the seam."""
    a, b = stem(left), stem(right)
    if a == b:
        return True
    shorter, longer = sorted((a, b), key=len)
    return len(shorter) >= 5 and longer.startswith(shorter)


@dataclass(frozen=True)
class Resolved:
    """One phrase of the sentence, and what it turned out to be."""

    phrase: str
    concept_id: Optional[str] = None
    how: str = "unresolved"
    domain: str = ""
    description: str = ""
    relations: Tuple[Tuple[str, str], ...] = ()
    #: Other concepts of the same name, when the store holds more than one.
    alternatives: Tuple[Tuple[str, str], ...] = ()

    @property
    def known(self) -> bool:
        return self.concept_id is not None

    @property
    def informative(self) -> bool:
        """Whether resolving it told us anything.

        The store holds 636 concepts with no description and 240 bare
        fragments -- `load`, `balancer`, `visualize` -- with nothing attached.
        Matching one is not an answer, and reporting `held, with no
        description` is worse than admitting ignorance, because it stops the
        substrate going and finding out.
        """
        return self.known and bool(self.description or self.relations)


@dataclass
class Acquired:
    """Something the substrate did not hold and now does."""

    label: str
    description: str = ""
    relations: Tuple[Tuple[str, str], ...] = ()
    origin: str = ""
    stored: bool = False
    detail: str = ""
    #: The SEMANTIC memory this admission created (from the ingress `Admission`),
    #: or None if nothing was retained. Carried so a later feedback turn can
    #: flag the exact memory this proposition made instead of storing another.
    memory_id: Optional[str] = None
    #: Whether a model was needed to split the sentence up. The FACT is always
    #: yours; this records only who found the seams in it.


@dataclass
class Answer:
    """A relation the question asked about, and what the store holds for it."""

    about: str
    relation: str
    others: Tuple[str, ...]
    #: For a yes/no question, what the store says. None when the question did
    #: not ask for a verdict -- "what causes X" wants the objects, not a yes.
    #:
    #: THREE VALUES, NEVER TWO. `False` means the store holds the DENIAL ("a
    #: kestrel is not a fish"); not-asked is None. Collapsing "I hold the
    #: opposite" into "no" would make a refutation indistinguishable from
    #: never having been told.
    verdict: Optional[bool] = None
    #: The premises a DERIVED verdict rests on. Empty for a verdict read
    #: directly off the store; the claims the substrate reasoned FROM when the
    #: answer was proved rather than looked up, so the reply can say WHY.
    support: Tuple[str, ...] = ()
    #: For a DERIVED answer -- one reasoning reached rather than the store held
    #: as a single relation -- the conclusion rendered as words ("pipe friction
    #: causes pressure loss"). Empty for a direct store answer, which the reply
    #: composes from about/relation/others instead.
    conclusion: str = ""


@dataclass
class Understanding:
    """What the substrate made of one sentence."""

    sentence: str
    resolved: List[Resolved] = field(default_factory=list)
    reading: Optional[Tuple[str, ...]] = None
    reading_source: str = ""
    answers: List[Answer] = field(default_factory=list)
    acquired: List[Acquired] = field(default_factory=list)
    remembered: List[str] = field(default_factory=list)
    #: What recall managed in the time available, and whether that was all of it.
    recall: Optional[Any] = None
    asked: bool = True
    reply: str = ""
    #: The self's disposition when this was understood (mode + explore flag), or
    #: None standalone. Lets `say()` colour a turn-back qualitatively from
    #: self-state without recomputing it.
    disposition: Optional[Dict[str, Any]] = None

    @property
    def answered(self) -> bool:
        """Whether the turn actually answered, as opposed to asking back.

        Recorded because the memory of the exchange says which, and a memory
        claiming an answer where a question was asked is a false record of the
        conversation -- one that reads back later as knowledge it never had."""
        return bool(self.known or self.answers
                    or any(a.stored for a in self.acquired))

    def spoken_for(self) -> set:
        """Words the answers account for, so they are not also called unknown."""
        used = set()
        for answer in self.answers:
            # RAW, not stemmed: `same_stem` stems both sides, and stemming here
            # too turned `caused` into `caus` into `cau`, so the word that
            # matched the relation was still reported as one nothing was held for.
            used.update(answer.relation.replace("_", " ").split())
        return used

    @property
    def known(self) -> List[Resolved]:
        return [r for r in self.resolved if r.informative]

    @property
    def unknown(self) -> List[Resolved]:
        return [r for r in self.resolved if not r.informative]


def _titles(phrase: str, title: str) -> bool:
    """Whether `title` names `phrase` -- every content word of it, by stem."""
    wanted = [w for w in phrase.replace("_", " ").split() if w not in FUNCTION_WORDS]
    if not wanted:
        return False
    have = [w.strip("()") for w in (title or "").split()]
    return all(any(same_stem(word, held) for held in have) for word in wanted)


@dataclass
class Turn:
    """One exchange, as the conversation itself recorded it."""

    said: str
    asked: bool
    subject: str
    reply: str
    #: The memories this turn admitted (a telling can state several
    #: propositions). Empty for a question or an unstored telling. This is what
    #: a following feedback turn ("no, that's wrong") flags: the verdict lands
    #: on the memory the claim already made, not on a new record.
    memories: Tuple[str, ...] = ()


def phrases(words: Sequence[str]) -> List[Tuple[int, int, str]]:
    """Every candidate phrase, longest first, as (start, end, text)."""
    out = []
    for size in range(min(MAX_PHRASE, len(words)), 0, -1):
        for start in range(len(words) - size + 1):
            window = words[start:start + size]
            if all(w in FUNCTION_WORDS for w in window):
                continue
            out.append((start, start + size, "_".join(window)))
    return out


class Conversation:
    """Reads a sentence and answers out of what the substrate holds."""

    def __init__(self, db=None, identity=None, emit=None):
        self._db = db
        self._identity = identity
        #: The substrate's event emitter, injected by the coordinator that owns
        #: this conversation (`conversation()`), so a taught proposition becomes
        #: a self-event the domain authority reacts to. None when the
        #: conversation is used standalone (a script, a test) -- teaching still
        #: admits, it just does not wake a reaction.
        self._emit = emit
        #: The substrate's DISPOSITION read, injected by the coordinator that
        #: owns this conversation, so a reply can be informed by self-state (the
        #: BehaviorArbiter's current directive). None when standalone -- the
        #: reply is then exactly what it was, never a guessed mood.
        self._disposition = None
        #: Recall persists across turns, so a wave that lands after one answer
        #: is already in hand for the next question -- which is usually about
        #: the same thing.
        self._recall = None
        #: The last turn's subject and what it said, so a subject that came out
        #: of that answer can be recognised as following it rather than
        #: replacing it.
        self._last_subject = ""
        self._last_reply = ""
        #: EVERY TURN, IN ORDER. The conversation is a thing that can be asked
        #: about -- "what did I just ask", "what were we talking about" -- and
        #: until this existed there was no owner for those questions, so they
        #: fell through to the only owner there was: research an unrecognised
        #: phrase. "What did I just ask you about?" went to the encyclopedia
        #: and came back with an article about the rhetorical tactic of asking
        #: questions. The conversation's record is the authority on the
        #: conversation. Not the concept store, and never the web.
        # BOUNDED. A plain list here only ever grew -- one conversation object
        # accumulated a turn per exchange for its whole life and never freed
        # one, the same unbounded-append leak `learn_from_event` had. The record
        # exists for continuity ("what were we talking about", and the referent
        # a feedback turn judges), and continuity is recent: a generous window
        # keeps that intact while capping the growth. Iterated/reversed only,
        # never sliced, so a deque is a drop-in.
        self._turns: "deque[Turn]" = deque(maxlen=_CONVERSATION_TURN_MEMORY)

    async def _services(self):
        if self._db is None:
            from core.database import TorinUnifiedDatabase
            self._db = TorinUnifiedDatabase()
            await self._db.initialize()
        if self._identity is None:
            from core.domain.concept_identity import ConceptIdentityService
            self._identity = ConceptIdentityService(self._db)
        return self._db, self._identity

    async def _concept(self, concept_id: str) -> Dict[str, Any]:
        db, _ = await self._services()
        rows = await db.execute_query(
            "SELECT concept_id, name, domain, description, relationships "
            "FROM unified.concepts WHERE concept_id=$1", (concept_id,), fetch_all=True)
        return rows[0] if rows else {}

    async def _incoming_relations(self, name: str) -> List[str]:
        """Facts that point AT a concept, as premise sentences.

        Relations are stored forward -- under the subject -- so "wibbling causes
        snargle" lives on `wibbling`, and a reverse question ("what causes
        snargle") never names the subject that holds it. This finds the concepts
        whose relations name THIS one as their object, so the fact reaches the
        reasoner as a premise. Text-matched then checked exactly: an extra
        premise the proof does not need is harmless, a missing one is not.
        """
        import json
        db, _ = await self._services()
        try:
            rows = await db.execute_query(
                "SELECT name, relationships FROM unified.concepts "
                "WHERE relationships::text ILIKE $1",
                (f"%{name}%",), fetch_all=True)
        except Exception as error:
            from core.capability import raise_if_structural
            raise_if_structural(error, "autonomous_coordinator._incoming_relations")
            return []

        target = name.replace("_", " ").strip().lower()
        premises: List[str] = []
        for row in rows or ():
            subject = row.get("name")
            rels = row.get("relationships")
            if isinstance(rels, str):
                try:
                    rels = json.loads(rels)
                except (ValueError, TypeError):
                    continue
            for entry in (rels or ()):
                if not isinstance(entry, (list, tuple)) or len(entry) < 2:
                    continue
                relation, obj = entry[0], entry[1]
                if str(obj).replace("_", " ").strip().lower() == target:
                    premises.append(f"{subject} {relation} {obj}")
        return premises

    async def resolve(self, sentence: str) -> List[Resolved]:
        """Every phrase of the sentence that names something held, longest first."""
        import json

        from core.semantics.sentence_machine import tokenize

        db, identity = await self._services()
        words = tokenize(sentence)
        taken: set = set()
        found: List[Resolved] = []

        for start, end, text in phrases(words):
            if any(index in taken for index in range(start, end)):
                continue
            hits = await identity.resolve_query(text.replace("_", " ")) or []
            hits = hits or (await identity.resolve_query(text) or [])
            if not hits:
                continue
            concept_id, how = hits[0]
            record = await self._concept(concept_id)
            others = []
            for other_id, _ in hits[1:4]:
                other = await self._concept(other_id)
                if other.get("description"):
                    others.append((other_id, other.get("domain", "")))
            relations = ()
            if record.get("relationships"):
                # AN ENTRY MAY CARRY POLARITY, AND THIS DROPPED EVERY ONE THAT
                # DID. `for a, b in parsed` unpacks exactly two, so a
                # three-element `["is", "bird", "positive"]` raised ValueError,
                # the except swallowed it, and the concept resolved with ZERO
                # relations -- indistinguishable from a concept nothing is
                # known about. Measured: 21 of 464 concepts holding relations
                # were silently emptied this way, including every concept
                # taught through conversation, because `admit_relation` records
                # polarity and this reader predates it.
                #
                # A negative is not an absence. `a kestrel is not a fish` is
                # something the substrate KNOWS, and it must survive the read.
                try:
                    parsed = json.loads(record["relationships"])
                except Exception as error:
                    logger.warning("relationships for %s unreadable: %s",
                                   concept_id, error)
                    parsed = []

                # Same normaliser as the teach path, so a relation reads the
                # same however it reached the store.
                relations = _as_pairs(parsed[:4])
                if len(relations) != len(parsed[:4]):
                    logger.warning("relationships for %s held %d entries that "
                                   "are not relations", concept_id,
                                   len(parsed[:4]) - len(relations))
            candidate = Resolved(
                phrase=text.replace("_", " "), concept_id=concept_id, how=how,
                domain=record.get("domain", ""), description=record.get("description", ""),
                relations=relations, alternatives=tuple(others))
            if not candidate.informative:
                # A name with nothing behind it does not get to consume the
                # words. `load` and `balancer` are both in the store and both
                # empty; letting them match stopped `load balancer` ever being
                # looked up.
                continue
            found.append(candidate)
            taken.update(range(start, end))

        # WHAT IS LEFT OVER IS GROUPED, NOT SCATTERED. `load balancer` is one
        # thing the substrate does not know; asking about `balancer` on its own
        # returns a breed of cattle, which is what happened.
        run: List[str] = []
        for index, word in enumerate(words + [""]):
            if index < len(words) and index not in taken and word not in FUNCTION_WORDS:
                run.append(word)
                continue
            if run:
                found.append(Resolved(phrase=" ".join(run)))
                run = []

        # A WORD NAMING A RELATION OF SOMETHING ELSE IN THE SENTENCE IS BEING
        # USED AS THAT RELATION. `visualize` also matches a concept in another
        # domain entirely, and reciting it would answer a question nobody
        # asked.
        relations = {stem(part) for item in found if item.known
                     for relation, _ in item.relations
                     for part in relation.replace("_", " ").split()}
        return [item for item in found
                if not (item.known and len(item.phrase.split()) == 1
                        and any(same_stem(item.phrase, r) for r in relations))]

    def _leads_on(self, sentence: str) -> bool:
        """Whether this turn follows from what the last answer said."""
        from core.semantics.sentence_machine import tokenize

        if not (self._last_reply and self._last_subject):
            return False
        said = self._last_reply.lower()
        words = [w for w in tokenize(sentence) if w not in FUNCTION_WORDS]
        # Every content word already appeared in the last answer: the turn is
        # asking about something that answer raised.
        return bool(words) and all(w in said for w in words)

    @staticmethod
    def subject_of(sentence: str) -> str:
        """What this turn is about, before anything has been resolved.

        The content words, in order. Crude, and refined the moment resolution
        says what they actually were -- but a subject is needed BEFORE that, to
        file the first wave under, and `what is a load balancer` and `what is
        anomaly detection` must not be filed together merely because the turn
        has not worked out which is which yet.
        """
        from core.semantics.sentence_machine import tokenize

        words = [w for w in tokenize(sentence) if w not in FUNCTION_WORDS]
        return " ".join(words[:4]).lower()

    def about_this_conversation(self, sentence: str) -> Optional[Tuple[str, str]]:
        """`(who, act)` where the question is about this exchange, else None.

        A question naming a PARTICIPANT and an act of SAYING is asking about
        the conversation, not about the world: `what did I just ask you`,
        `what were we talking about`, `what did you say`. There is exactly one
        structural signal and it is in the sentence -- a speech verb with a
        participant in front of it.

        WHO IS SPEAKING IS WHO STANDS BEFORE THE VERB. `what did I ask you`
        and `what did you tell me` name the same two people in the same words;
        only the order says whose words are being asked for.
        """
        from core.semantics.sentence_machine import tokenize

        if not self.is_question(sentence):
            return None
        words = tokenize(sentence)
        speaker = ""
        for word in words:
            if word in SPEAKER_THEM:
                speaker = "them"
            elif word in SPEAKER_ME:
                speaker = "me"
            elif word in SPEAKER_BOTH:
                speaker = "both"
            elif word in SPEECH_ACTS and speaker:
                # The first speech verb that has a participant ahead of it.
                return speaker, SPEECH_ACTS[word]
        return None

    def _from_the_record(self, who: str, act: str) -> str:
        """Answer about this conversation, out of this conversation.

        NOTHING IS INVENTED AND NOTHING IS FETCHED. If the exchange has not
        happened yet, that is the answer -- a turn this process never saw is
        one it cannot report, and saying so is the honest reply.
        """
        earlier = self._turns
        if not earlier:
            return "Nothing yet — this is the first thing you have said to me."

        if who == "both" or act == "discussed":
            subjects, seen = [], set()
            for turn in reversed(earlier):
                subject = turn.subject.strip()
                if subject and subject not in seen:
                    seen.add(subject)
                    subjects.append(subject)
            if not subjects:
                return "Nothing I could name a subject for yet."
            if len(subjects) == 1:
                return f"We were talking about {subjects[0]}."
            return ("We were talking about " + subjects[0]
                    + ", and before that " + ", ".join(subjects[1:4]) + ".")

        if who == "me":
            spoken = [t for t in earlier if t.reply]
            if not spoken:
                return "I have not said anything yet."
            return "I said: " + spoken[-1].reply

        # who == "them": their own turns, split by whether they asked or told.
        wanted = [t for t in earlier if (t.asked if act == "asked" else not t.asked)]
        if not wanted:
            verb = "asked me anything" if act == "asked" else "told me anything"
            return f"You have not {verb} yet."
        last = wanted[-1]
        verb = "asked" if act == "asked" else "told me"
        answer = f'You {verb}: "{last.said}"'
        if act == "asked" and last.subject:
            answer += f" — that was about {last.subject}."
        return answer

    def recalling(self):
        """The recall running alongside this conversation."""
        if self._recall is None:
            from core.memory.live_recall import LiveRecall
            self._recall = LiveRecall()
        return self._recall

    async def recall(self, sentence: str, limit: int = 3) -> List[str]:
        """What it remembers that bears on this. Blocking; prefer `recalling()`.

        Kept because a caller with nothing else to do while it waits loses
        nothing by waiting, and one test asks for exactly that.
        """
        recall = self.recalling()
        recall.begin(sentence)
        return (await recall.harvest(limit)).texts(limit)

    async def read(self, sentence: str) -> Tuple[Optional[Tuple[str, ...]], str]:
        """A structured reading, where any formalizer can produce one."""
        from core.reasoning.neural_bridge import (DerivedReadingFormalizer,
                                                  DeterministicExtractor,
                                                  FormalizerChain,
                                                  PassthroughFormalizer)

        chain = FormalizerChain([PassthroughFormalizer(), DeterministicExtractor(),
                                 DerivedReadingFormalizer()])
        result = await chain.formalize(sentence, [sentence])
        if not result.succeeded:
            return None, ""
        # EVERY claim the sentence made, not just the first. "the pump is hot
        # and loud" asserts two things; returning one of them is a reading that
        # says less than the sentence did.
        return tuple(result.statements or [result.statement]), result.source

    @staticmethod
    def asked(sentence: str, resolved: Sequence["Resolved"]) -> List["Answer"]:
        """Relations the sentence asks about, matched against what is held.

        `what causes pressure loss` and a concept holding `caused by pipe
        friction` are about the same relation, and answering the QUESTION
        rather than reciting the concept is the difference between replying and
        responding. Matched on stems, over relations already stored -- nothing
        here decides that two relations are the same, only that a word in the
        question and a label on a concept share a stem.
        """
        from core.semantics.sentence_machine import tokenize

        asked_stems = {w for w in tokenize(sentence) if w not in FUNCTION_WORDS}
        answers: List[Answer] = []
        for item in resolved:
            if not item.known:
                continue

            # A YES/NO QUESTION NAMES THE SUBJECT AND THE OBJECT, NEVER THE
            # RELATION. "is a kestrel a bird" strips to {kestrel, bird}: the
            # relation label is `is`, a function word, so label matching could
            # never fire and the question went unanswered while the store held
            # `kestrel --is--> bird`, admitted seconds earlier. Measured: the
            # reply recited an unrelated memory about arctic terns.
            #
            # Matching the OBJECT answers what was actually asked, and polarity
            # decides the verdict -- so "is a kestrel a fish" against a stored
            # `is not fish` answers NO from evidence rather than from silence.
            for relation, other in item.relations:
                if any(same_stem(str(other), word) for word in asked_stems):
                    denied = relation.startswith("not ") or relation == "is not"
                    answers.append(Answer(item.phrase, relation, (str(other),),
                                          verdict=not denied))
                    continue

                labels = [part for part in relation.replace("_", " ").split()]
                if any(same_stem(label, word) for label in labels
                       for word in asked_stems):
                    existing = next((a for a in answers
                                     if a.about == item.phrase and a.relation == relation), None)
                    if existing:
                        answers.append(Answer(item.phrase, relation,
                                              existing.others + (other,)))
                        answers.remove(existing)
                    else:
                        answers.append(Answer(item.phrase, relation, (other,)))
        return answers

    @staticmethod
    def _render_atom(text: str) -> str:
        """A logic atom as words: `pressure_loss` -> `pressure loss`; a status
        prefix ("Proved:") stripped. What reasoning concluded, said plainly."""
        rendered = str(text).strip()
        for prefix in ("proved:", "disproved:", "refuted:", "verified:"):
            if rendered.lower().startswith(prefix):
                rendered = rendered[len(prefix):].strip()
                break
        return rendered.replace("->", "implies").replace("_", " ").strip()

    @staticmethod
    def _support_used(premises, steps) -> Tuple[str, ...]:
        """The clean premise SENTENCES a derivation used, for the reply's `because`.

        The reasoner marks the premises it used `[Premise]`, but in the formula
        form it reasons in (`zorbax_glomph -> zorbax_fizzly`), which reads back
        as noise. The premises it was GIVEN are clean sentences ("Every glomph is
        fizzly"), so the used ones are recovered by matching: a premise whose
        content words all appear among the `[Premise]` lines is one the proof
        rested on, and it is cited as it was said rather than as an atom. This
        both keeps the reason readable and keeps it honest -- only premises the
        proof actually used, not everything that happened to be recalled.
        """
        marked = " ".join(str(s) for s in (steps or ()) if "[Premise]" in str(s))
        marked = marked.lower().replace("_", " ")
        seen: set = set()
        out: List[str] = []
        for premise in premises or ():
            words = [w for w in str(premise).lower().split()
                     if w not in FUNCTION_WORDS]
            if words and all(w in marked for w in words) and premise not in seen:
                seen.add(premise)
                out.append(str(premise))
        return tuple(out)

    async def _held_premises(self, sentence, resolved, harvest) -> List[str]:
        """Everything the substrate HOLDS about the topic, as premise sentences.

        There is no separate 'look it up' step that reasoning falls back from:
        what is held is simply what reasoning reasons over, and a stored fact is
        a premise that proves its question in one step. Four sources, together:

          * the resolved concepts' own relations ("flerm is blorp"),
          * ONE HOP OUT -- the relations of the concepts those point to
            ("blorp is snazzy"), because "is flerm snazzy" follows from a chain
            the question never names the middle of,
          * the subject-focused recalled memories (`harvest`),
          * a BROAD recall on the whole question -- a syllogism's rule ("every
            blorp is snazzy") shares a term with the question but not its
            subject, so the subject-focused harvest misses it; this finds the
            premises the chain needs.

        One hop, not the whole graph: enough to chain a stated rule to a stated
        fact without pulling the entire store in as premises.
        """
        premises: List[str] = []
        others: set = set()
        for item in resolved:
            if not getattr(item, "known", False):
                continue
            for relation, other in item.relations:
                premises.append(f"{item.phrase} {relation} {other}")
                others.add(str(other))
            # Incoming relations: facts that name THIS concept as their object,
            # for reverse questions ("what causes X") the forward store misses.
            premises.extend(await self._incoming_relations(item.phrase))

        # One hop out, following each relation to the concept it names.
        for other in others:
            try:
                hops = await self.resolve(other)
            except Exception:
                continue
            for hop in hops:
                if not getattr(hop, "known", False):
                    continue
                for relation, o2 in hop.relations:
                    premises.append(f"{hop.phrase} {relation} {o2}")

        if harvest is not None:
            premises.extend(harvest.texts())

        # Broad recall on the whole question, for the premises a chain needs that
        # the subject never names. Recall hands back each memory's clean claim.
        try:
            from core.memory import get_memory_agent
            agent = await get_memory_agent()
            _ok, hits = await agent.search_memories(
                query=str(sentence), limit=8, include_events=False)
            for hit in (hits or []):
                meta = getattr(hit, "metadata", None) or {}
                claim = (meta.get("conclusion") if isinstance(meta, dict) else None) \
                    or getattr(hit, "content", "")
                if claim:
                    premises.append(str(claim))
        except Exception as error:
            from core.capability import raise_if_structural
            raise_if_structural(error, "autonomous_coordinator._held_premises.broad_recall")

        return list(dict.fromkeys(p.strip() for p in premises if p and p.strip()))

    async def _reasoned_answers(self, sentence, resolved, harvest) -> List["Answer"]:
        """Answers the substrate DERIVES from what it holds.

        Not a fallback for a failed lookup -- a first-class peer that runs over
        the held premises whether or not a stored relation already answered, so
        "is X fizzly" follows from "X is a glomph" and "every glomph is fizzly",
        and "what causes X" is answered by the cause that entails it. An answer
        is returned ONLY when the substrate PROVES one; the premises it used are
        carried so the reply can say why.

        A copula yes/no question is decided on its AFFIRMATIVE proposition and
        answered against the polarity it was asked in -- so "is X not Y" is
        answered by whether X IS Y. Every other form (subject-verb-object,
        causal, open "what/why") is handed to the reasoner as-is; it formalises
        the query and derives the conclusion.
        """
        premises = await self._held_premises(sentence, resolved, harvest)
        if not premises:
            return []

        from core.reasoning.neural_bridge import (ReasoningRequest,
                                                  get_neural_bridge)
        from core.semantics import derived_reader
        bridge = get_neural_bridge()

        try:
            reading = derived_reader.read(sentence)
        except Exception:
            reading = None

        # A WH-question ("what/why/how/who causes X") is OPEN, not a yes/no about
        # a subject named "what" -- the reader can mis-parse it as a copula, so it
        # is sent to the open branch where the reasoner derives the answer.
        _WH = {"what", "why", "how", "who", "when", "where", "which"}
        if reading and reading[0].lower() not in _WH:
            subject, obj, polarity = reading
            result = await bridge.reason(ReasoningRequest(
                query=f"{subject} is {obj}", context=premises))
            if not (result.metadata or {}).get("verified"):
                return []
            support = self._support_used(premises, result.reasoning_steps)
            claim = f"{subject} is {obj}".replace("_", " ")
            # X IS Y is proved: "yes" when the question affirmed it, "no" when it
            # denied it (the negation is false, and the reason is that X IS Y).
            return [Answer(about=subject, relation="is", others=(obj,),
                           verdict=(polarity == "affirms"),
                           support=support, conclusion=claim)]

        result = await bridge.reason(ReasoningRequest(query=sentence, context=premises))
        if not (result.metadata or {}).get("verified") or not result.answer:
            return []
        support = self._support_used(premises, result.reasoning_steps)
        return [Answer(about="", relation="", others=(), verdict=None,
                       support=support, conclusion=self._render_atom(result.answer))]

    # ---- the two ways something new gets in ------------------------------

    async def _ingest(self, label, description, relations, source_type, source_id,
                      content, domain) -> Acquired:
        """Hand the interpreted statement to the ingress. It admits, not this.

        This used to build its own EvidenceEnvelope and call the ingestion
        service directly, under a docstring calling itself "the only write
        path" -- a second claimant to a job that already had an owner. It also
        read `result.concepts` / `.concept_ids` / `.accepted` off the returned
        IngestionResult, none of which are fields on it, so `stored` was False
        on every successful write. Every sentence anyone taught reported back
        as not stored while the row went in.
        """
        from core.semantics.cognitive_ingress import (Provenance,
                                                      get_cognitive_ingress)

        if not relations:
            return Acquired(label, description, (), source_id, False,
                            "nothing was said about it")

        relation, obj = relations[0][0], relations[0][1]
        positive = len(relations[0]) < 3 or str(relations[0][2]) != "negative"

        admission = await get_cognitive_ingress().admit_relation(
            subject=label, relation=relation, obj=obj, surface=content,
            provenance=Provenance(producer="conversation", source_id=source_id,
                                  source_type=source_type.name),
            positive=positive, description=description, domain=domain)

        detail = "; ".join(admission.refusals)
        if admission.contradicts:
            detail = (f"this contradicts what I was told before"
                      f"{'; ' + detail if detail else ''}")

        # A newly admitted proposition is a self-event: it may have completed a
        # taught-concept cluster the domain authority should crystallize. Emit it
        # so that reaction fires now, off the reply path, instead of waiting for
        # the idle tier. Only on a real admission (not a refusal or a duplicate),
        # and only when this conversation was given the substrate's emitter
        # (standalone use has none -- teaching still admits, it just does not
        # wake a reaction). Isolated: a failing emit never breaks the reply.
        if admission.admitted and self._emit is not None:
            try:
                await self._emit(SelfEvent(
                    SelfEventType.EVIDENCE_ADMITTED,
                    payload={"subject": label, "relation": relation,
                             "obj": obj, "domain": domain},
                    origin="conversation._ingest"))
            except Exception as error:
                logger.warning("EVIDENCE_ADMITTED emit failed: %s", error)
        # ONE SHAPE FOR EVERY READER. `relations` arrives from the reader as
        # (relation, object) or (relation, object, polarity), and `Acquired`
        # declares Tuple[Tuple[str, str], ...]. `say()` unpacked exactly two and
        # raised ValueError on any taught sentence carrying polarity -- which,
        # since admit_relation records polarity, is every taught sentence. The
        # polarity is folded into the relation here, the same way `resolve()`
        # does it, so a negative survives instead of crashing the reply.
        return Acquired(label, description, _as_pairs(relations), source_id,
                        admission.admitted, detail,
                        memory_id=admission.memory_id)

    async def _register_domain_gap(self, sentence: str, resolved):
        """Register an unanswered in-domain question as a known-unknown --
        THROUGH the domain authority, not around it.

        A question resolved to a concept that lives in a crystallized SUBJECT
        domain (not the `conversation`/`researched` channels or the `general`
        catch-all), which produced no answer, is a localized declarative gap:
        the substrate has little information HERE, not lacking the operators to
        act here. This routes it to `UniversalDomainMaster.detect_knowledge_gap`,
        the owner of domain-scoped gap detection -- it used to reach past that
        into `register_known_unknown` with a coarser inline version, a bypass of
        the very method this docstring named. The authority does the precise
        check (subject IS a concept of the domain, the asked relation is genuinely
        absent) and records the structured `required_info` an acquisition step
        can act on, competence untouched -- a knowledge gap is never a competence
        loss. Returns the domain_id it registered under, or None.

        The RELATION asked about comes from the reader (a WH question reads as
        subject + relation + <unknown>). Without a relation there is nothing to
        localize, so nothing is registered -- honest, not a coarse catch-all.
        """
        from core.domain.domain_registry import get_domain_registry
        from core.integration.universal_domain_master import \
            get_universal_domain_master
        from core.semantics import derived_reader

        typed = derived_reader.read_typed(sentence)
        relation = None
        if typed is not None and getattr(typed, "relation", None) is not None:
            try:
                relation = typed.relation.relation.value
            except Exception:
                relation = None
        if not relation:
            return None

        registry = get_domain_registry()
        udm = get_universal_domain_master()
        channels = {"conversation", "researched", "general", ""}
        for item in resolved:
            if not getattr(item, "known", False):
                continue
            field = (getattr(item, "domain", "") or "").strip().lower()
            if field in channels:
                continue
            domain_id = f"domain_{field}"
            if domain_id not in registry.domains:
                continue
            gap = await udm.detect_knowledge_gap(
                domain_id, subject=item.phrase, relation=relation)
            if gap is not None:
                return domain_id
        return None

    async def _resolves(self, text: str) -> bool:
        _, identity = await self._services()
        return bool(await identity.resolve_query(text.replace("_", " "))
                    or await identity.resolve_query(text))

    # retain() REMOVED. Retention is not the reader's job.
    #
    # It was briefly added here, which made the interpreter also the thing that
    # decided what the system keeps -- two responsibilities in one place, and
    # the second one silently optional. A sentence is interpreted here and
    # admitted in exactly one place: core.semantics.cognitive_ingress.

    async def teach(self, sentence: str) -> List[Acquired]:
        """You told it something. Read it with the DERIVED reading, then admit.

        This used to guess. It walked in from both ends looking for runs of
        words that already named something, and when the subject was new --
        which is the whole point of being taught -- nothing in the store could
        say where the phrases ended, so it asked a model to find the seams.

        That is what filled the concept store with junk. `you` and
        `which_lines_belong_to_which_block` became entities; `a function
        count_o` became a relation. Every one of them came from a guess made
        because no reading was available.

        A reading IS available. `procedure_synthesis` derives one from
        sentence/meaning pairs, it generalizes to sentences whose every content
        word is new, and it needs no model. It was never registered, so nothing
        could reach it. Now it is consulted first, and where it declines this
        declines too -- a sentence that cannot be read has not told you
        anything, and admitting a guess about it is worse than admitting
        nothing.
        """
        from core.domain.concept_ingestion import EvidenceSourceType
        from core.semantics import derived_reader

        registered, why = derived_reader.ensure_registered()
        if not registered:
            logger.warning("no derived reading available: %s", why)
            return [Acquired(sentence, detail=(
                "I have no derived way to read a sentence yet, so I will not "
                "guess at what you told me"))]

        # READ IT TYPED. The reader recognises the surface and the typer names
        # the RELATION -- "made of" -> made_of, not a bare "is". The concept
        # graph then holds a TYPED edge the relation algebra can reason over,
        # instead of one undifferentiated "is" edge that poisons inference.
        #
        # A sentence may carry MORE THAN ONE proposition -- a relative clause
        # ("a robin, which is small, is a bird") or a conjunction ("the vault is
        # cold and heavy") states two -- so every proposition it states is read
        # and admitted, not just the first. `read_all` returns one typed reading
        # per proposition (already dropping any it could not construct).
        readings = derived_reader.read_all(sentence)
        if not readings:
            # Distinguish "unreadable" from "words known, construction not": a
            # whole-sentence read that came back asking to be taught the
            # construction says the more specific thing.
            probe = derived_reader.read_typed(sentence)
            if probe is not None and probe.needs_construction is not None:
                return [Acquired(sentence, detail=(
                    "I recognise the words but not this sentence construction "
                    "yet; I will not guess at a relation I cannot name"))]
            return [Acquired(sentence, detail=(
                "I could not read that sentence with what I have been taught "
                "about sentences"))]

        acquired: List[Acquired] = []
        for typed in readings:
            positive = typed.polarity != "denies"
            # The canonical TYPED relation name is what is stored, so the edge
            # carries its semantics (transitivity, inverse, ...) not just a verb.
            relation = typed.relation.relation.value
            acquired.append(await self._ingest(
                label=typed.subject, description="",
                relations=((relation, typed.obj,
                            "positive" if positive else "negative"),),
                source_type=EvidenceSourceType.USER_SUPPLIED, source_id="you",
                content=sentence, domain="conversation"))
        return acquired


    async def look_up(self, phrase: str) -> Optional[Acquired]:
        """It did not know the word. Go and find out, now.

        Researches the phrase, reads a description out of what came back, and
        stores it -- so the next question about it is answered from the store
        like any other, and the turn can say where it came from.
        """
        import json
        import re as _re

        from core.domain.concept_ingestion import EvidenceSourceType
        from core.tools import get_tool_registry

        try:
            result = await get_tool_registry().execute_tool(
                "conduct_research", {"topic": phrase, "max_sources": 3})
        except Exception as error:
            return Acquired(phrase, origin="research", detail=f"research failed: {error}")
        if not getattr(result, "success", False):
            return Acquired(phrase, origin="research",
                            detail=f"research declined: {getattr(result, 'error', '')}")

        output = getattr(result, "output", None) or {}
        description, source = "", ""
        for item in output.get("raw_results", []):
            if item.get("source") != "Wikipedia":
                continue
            try:
                hits = json.loads(item.get("data") or "{}").get("query", {}).get("search", [])
            except Exception:
                continue
            # THE FIRST HIT IS NOT AN ANSWER, IT IS THE CLOSEST THING THE INDEX
            # HAD. A search engine always returns its best row; taking it
            # unchecked is accepting a result without verifying it answered
            # anything. Asked what spots unusual behaviour in data, this took
            # Wikipedia's top hit for `spots unusual behaviour` -- an article on
            # animal sexual behaviour -- and STORED it as the meaning of the
            # phrase. A wrong fact written into the store outlives the turn that
            # invented it and is indistinguishable afterwards from one that was
            # learned.
            #
            # An article is about the phrase when its TITLE names the phrase.
            # Every content word, by stem, so `load balancer` accepts `Load
            # balancing (computing)` and `spots unusual behaviour` accepts
            # nothing that only shares `behaviour`. Where no hit passes, it
            # declines and the reply asks -- which is the honest end of a
            # lookup that found nothing, and the one the caller already handles.
            match = next((h for h in hits if _titles(phrase, h.get("title", ""))), None)
            if match is None:
                continue
            description = _re.sub(r"<[^>]+>", "", match.get("snippet", "")).strip()
            source = item.get("url", "")
            break

        if not description:
            return Acquired(phrase, origin="research",
                            detail="research returned nothing that describes it")
        return await self._ingest(
            label=phrase, description=description, relations=(),
            source_type=EvidenceSourceType.RESEARCH_FINDING,
            source_id=source or "research", content=description, domain="researched")

    @staticmethod
    def is_question(sentence: str) -> bool:
        """Whether this asks, by the shape of the sentence alone.

        Cheap, model-free, and certain in both directions where a question mark
        or an opening question word settles it.
        """
        from core.semantics.sentence_machine import tokenize

        if sentence.strip().endswith("?"):
            return True
        words = tokenize(sentence)
        return bool(words) and words[0] in QUESTION_OPENERS

    def _read_disposition(self) -> Optional[Dict[str, Any]]:
        """The self's current disposition, read from the coordinator that owns
        this conversation, so a reply can be informed by self-state. Returns a
        small QUALITATIVE view (the directive's mode word + whether the self is
        inclined to explore) -- never numbers beside a feeling. None when the
        conversation is standalone or the read fails: the reply is then exactly
        what it was, never a fabricated mood."""
        if self._disposition is None:
            return None
        try:
            directive = self._disposition()
        except Exception as error:
            logger.debug("disposition read unavailable: %s", error)
            return None
        return {"mode": getattr(directive, "mode", None),
                "explore": bool(getattr(directive, "should_explore", False))}

    def _feedback_referent(self) -> Optional["Turn"]:
        """The recent turn a verdict is about: the most recent one, within a
        small window, that actually admitted a memory. A verdict with nothing to
        judge is not feedback, so this returning None is what stops an
        evaluative-looking utterance with no referent from being treated as one.
        Bounded look-back -- never the whole history."""
        window = list(self._turns)[-_FEEDBACK_WINDOW:]
        for turn in reversed(window):
            if turn.memories:
                return turn
        return None

    def feedback_of(self, sentence: str) -> Optional[bool]:
        """Whether this utterance is FEEDBACK on what was just taught, and its
        verdict: True confirms, False corrects, None is not feedback. Feedback is
        a verdict ON A PRIOR CLAIM, so both halves must hold -- the reader reads
        the utterance as a bare evaluative verdict (structural, model-free), AND
        there is a recent turn that left a memory to judge. Same certainty as
        is_question, plus a referent to attach to; without the referent an
        evaluative shape is just an ordinary short statement and is left alone."""
        from core.semantics.sentence_machine import evaluative_verdict

        verdict = evaluative_verdict(sentence)
        if verdict is None:
            return None
        if self._feedback_referent() is None:
            return None
        return verdict

    async def _take_feedback(self, sentence: str, verdict: bool) -> "Understanding":
        """A verdict on what was just taught. The claim already made a memory;
        this FLAGS that memory (annotated, never overwritten) and hands the
        verdict to the learning authority -- it does NOT store the verdict as a
        new fact, which is what filing it through teach() would have done. The
        authority owns what learning follows; this only routes the signal and
        replies."""
        referent = self._feedback_referent()
        flagged = 0
        if referent is not None:
            authority = get_learning_authority()
            for memory_id in referent.memories:
                try:
                    outcome = await authority.learn_from_feedback({
                        "memory_id": memory_id,
                        "success": verdict,          # True confirms, False corrects
                        "content": sentence,
                        "about": referent.said,
                    })
                    if outcome and outcome.get("memory_flagged"):
                        flagged += 1
                except Exception as error:
                    logger.warning("feedback routing failed for %s: %s",
                                   memory_id, error)

        understanding = Understanding(sentence=sentence, asked=False)
        if verdict:
            understanding.reply = ("Understood — noted as confirmed." if flagged
                                   else "Understood.")
        else:
            understanding.reply = ("Understood — I've marked that as corrected."
                                   if flagged else
                                   "Understood, though I have no stored claim from "
                                   "that to correct.")
        self._last_reply = understanding.reply
        # The verdict itself is not a new claim about the world, so it admits no
        # memory of its own -- recorded as a turn for continuity, with none.
        self._turns.append(Turn(said=sentence, asked=False,
                                subject=self._last_subject,
                                reply=understanding.reply, memories=()))
        return understanding

    async def classify(self, sentence: str) -> str:
        """`question`, `telling` or `job` — decided HERE by the substrate's own
        reader, with no model.

        THIS WAS DECIDED TWICE. The coordinator asked a model, this asked a rule,
        and they disagreed: `a quorum sensor detects bacterial population density`
        is plainly a statement, the model called it a question, and it was filed
        in memory as `Asked: a quorum sensor detects...`. Two owners of one
        question produce two answers. Now there is ONE owner and NO model:

          - a QUESTION is structural (`is_question`);
          - a TELLING states a fact — a declarative the model-free `SentenceReader`
            reads as a statement (copular / universal / conditional / SVO whose
            verb the lexicon knows);
          - a JOB asks for work — anything that is neither a question nor a
            readable statement of fact. Where the reader cannot read a sentence
            as a fact, that sentence has not TOLD the substrate anything, so it is
            treated as work. This is the reader's honest structural verdict, never
            a guess and never a model.
        """
        if self.is_question(sentence):
            return "question"

        from core.semantics.sentence_reader import SentenceReader
        statement = SentenceReader()._parse_statement(sentence)
        return "telling" if statement is not None else "job"

    async def understand(self, sentence: str, look_up: bool = True) -> Understanding:
        # ASKED ABOUT THIS EXCHANGE, ANSWERED FROM THIS EXCHANGE. Checked first
        # because every path below treats the sentence as being about the
        # world: it would file `just ask` as an unresolved concept, research
        # it, and store what it found. The record answers this; nothing else
        # can, and nothing else should be consulted.
        self_reference = self.about_this_conversation(sentence)
        if self_reference is not None:
            who, act = self_reference
            understanding = Understanding(sentence=sentence, asked=True)
            understanding.reply = self._from_the_record(who, act)
            # The subject does NOT move. Asking what we were talking about is
            # not a new subject -- it is a question about the old one, and
            # letting it become the subject would strand everything recall has
            # accumulated under the topic the conversation is still on.
            self._turns.append(Turn(said=sentence, asked=True,
                                    subject=self._last_subject,
                                    reply=understanding.reply))
            self._last_reply = understanding.reply
            return understanding

        # A VERDICT ON WHAT WAS JUST TAUGHT, ANSWERED AS ONE. Checked before the
        # telling path below, because that path would file "no, that's wrong" as
        # a new fact about the world -- storing the correction as though it were
        # a claim. Feedback is a verdict on the memory the last turn already
        # made: it flags that memory and goes to the learning authority, it does
        # not become a concept. Only fires when there is a recent taught memory
        # to judge (feedback_of returns None otherwise).
        verdict = self.feedback_of(sentence)
        if verdict is not None:
            return await self._take_feedback(sentence, verdict)

        # WAVE 1 GOES OUT BEFORE ANYTHING ELSE HAPPENS. Everything below --
        # storing what was said, resolving concepts, researching a word --
        # takes time recall can use rather than time it has to wait for.
        recall = self.recalling()
        recall.carry_over()
        # THE SUBJECT IS WHAT CONTINUITY HANGS ON. Not the session: a
        # conversation moves between things and comes back, and what was
        # accumulated about the first thing has to still be there -- and must
        # not turn up ranked highly under the second.
        subject = self.subject_of(sentence)
        # A SUBJECT NAMED IN THE LAST ANSWER IS ONE THIS ANSWER LED TO. Being
        # told pipe friction causes pressure loss and then asking about pipe
        # friction is following the thread, not leaving it.
        came_from = self._last_subject if self._leads_on(sentence) else ""
        recall.begin(sentence, about=subject, arose_from=came_from)

        asked = self.is_question(sentence)
        acquired: List[Acquired] = []

        if not asked:
            # TOLD, not asked. Store it before answering, so the reply is made
            # out of a store that already contains what was just said.
            acquired = await self.teach(sentence)

        resolved = await self.resolve(sentence)

        # WAVE 2: what the words turned out to be is a better query than the
        # words were, and it did not exist until now. It may also name the
        # subject better than the raw sentence did.
        informative = [item.phrase for item in resolved if item.informative]
        if informative:
            # What it turned out to be replaces what it looked like, and takes
            # everything already gathered with it.
            recall.rename_subject(subject, informative[0])
            if came_from:
                recall.begin(about=informative[0].lower(), arose_from=came_from)
            subject = informative[0].lower()
        recall.refine(*informative, about=subject)

        if asked and look_up:
            # DID NOT KNOW IS NOT AN ANSWER. Find out, in this turn -- but for
            # ONE thing, the longest phrase it could not place. Researching
            # every stray word turns a question into a pile of disambiguation
            # pages, which is what it did before this.
            candidates = sorted((r for r in resolved if not r.known),
                                key=lambda r: len(r.phrase.split()), reverse=True)
            accounted = {stem(part) for item in resolved if item.known
                         for relation, _ in item.relations
                         for part in relation.replace("_", " ").split()}
            target = next((c for c in candidates
                           if not any(same_stem(c.phrase, a) for a in accounted)), None)
            if target is not None:
                learned = await self.look_up(target.phrase)
                if learned is not None:
                    acquired.append(learned)
                if learned is not None and learned.stored:
                    resolved = await self.resolve(sentence)

        answers = self.asked(sentence, resolved)
        # WAVE 3: the relation actually asked about, which is the most specific
        # thing the turn ever learns.
        recall.refine(*[f"{a.about} {a.relation}" for a in answers], about=subject)

        reading, source = await self.read(sentence)
        harvest = await recall.harvest(about=subject, claim=sentence)

        # REASON OVER WHAT IS HELD, as a first-class peer to the direct lookup
        # above -- NOT a fallback gated on it having failed. Whatever the store
        # answered directly, the substrate also derives what FOLLOWS from what it
        # holds (concept relations and recalled memory alike); the two are merged,
        # and a derived answer that duplicates a direct one is dropped for it.
        if asked:
            direct = {(a.about, a.relation, tuple(a.others)) for a in answers}
            for derived in await self._reasoned_answers(sentence, resolved, harvest):
                if (derived.about, derived.relation, tuple(derived.others)) not in direct:
                    answers.append(derived)

        # A KNOWLEDGE GAP DETECTED FROM THE QUESTION ITSELF. A question about a
        # subject the substrate HOLDS (resolved) and that lives in a crystallized
        # subject domain, yet which nothing held could answer, is the substrate
        # having little information HERE -- not lacking the operators to act here.
        # Register it as a domain-scoped known-unknown (competence untouched), so
        # "I don't hold that fact yet" is a tracked, resolvable state rather than a
        # silent miss. Isolated: never breaks the reply.
        if asked and not answers:
            try:
                await self._register_domain_gap(sentence, resolved)
            except Exception as error:
                logger.debug("domain knowledge-gap registration skipped: %s", error)

        understanding = Understanding(
            sentence=sentence, resolved=resolved, reading=reading,
            reading_source=source, answers=answers,
            acquired=acquired, asked=asked,
            remembered=harvest.texts(), recall=harvest,
            disposition=self._read_disposition())
        understanding.reply = self.say(understanding)
        self._last_subject, self._last_reply = subject, understanding.reply
        # The memories this telling admitted, kept on the turn so the NEXT turn's
        # feedback can flag them. `acquired` is [] for a question.
        admitted_memories = tuple(
            a.memory_id for a in acquired if getattr(a, "memory_id", None))
        self._turns.append(Turn(said=sentence, asked=asked, subject=subject,
                                reply=understanding.reply,
                                memories=admitted_memories))
        return understanding

    @staticmethod
    def say(understanding: "Understanding") -> str:
        """A reply assembled from what was found, and nothing else.

        A REPLY ALREADY ANSWERED IS NOT RE-DERIVED. `understand()` answers a
        question ABOUT THIS CONVERSATION from the record and sets `.reply`
        there, because nothing else can answer it -- the sentence is not about
        the world, so there is nothing to resolve. Recomputing here from
        `known` and `unknown`, both empty in that case, produced a second and
        different answer: a caller reading `.reply` was told "We were talking
        about harrier", and a caller calling `say()` on the same object was told
        "There was nothing in that I could resolve".

        Two ways to get one answer, disagreeing. `say()` now returns the answer
        that was already established rather than deriving a worse one over an
        empty result.
        """
        if understanding.reply:
            return understanding.reply

        known, unknown = understanding.known, understanding.unknown
        lines: List[str] = []
        asking: List[str] = []

        # RAISED BEFORE ANYTHING ELSE, INCLUDING BEFORE THE EARLY RETURNS.
        # Memory holding the opposite of what was just said is the most
        # important thing it has. The case that matters most -- being TOLD
        # something the store disagrees with -- takes the earliest exit from
        # this method, so a contradiction appended later was computed and never
        # said.
        contradicting = [m for m in (understanding.recall.memories
                                     if understanding.recall else [])
                         if m.agrees is False]
        if contradicting:
            lines.append("I have the opposite on record: "
                         + contradicting[0].text[:200])

        # SAY WHAT JUST CHANGED. A turn that quietly stored something, or
        # quietly failed to, is a turn you cannot trust twice.
        for item in understanding.acquired:
            if item.stored and understanding.asked:
                lines.append(f"I did not have {item.label}. I looked it up: "
                             f"{item.description}")
                if item.origin:
                    lines.append(f"    (from {item.origin})")
            elif item.stored:
                held = "; ".join(f"{r} {o}" for r, o in item.relations)
                lines.append(f"Noted — {item.label}: {held}")
            else:
                # ASK. Failing to find something is a reason to turn back to
                # the person, not a result to report at them. Held back to the
                # END of the reply, because a question buried above other lines
                # reads as commentary rather than as a question.
                #
                # INFORMED BY SELF-STATE: when the self's disposition is inclined
                # to explore, the gap is not just reported — the substrate says,
                # honestly and qualitatively, that it wants to close it. Neutral
                # disposition (or standalone, no disposition) keeps the plain ask.
                disp = understanding.disposition
                if disp and disp.get("explore"):
                    asking.append(f"I don't hold {item.label} yet — looking it up "
                                  f"found nothing, and it's the kind of gap I want "
                                  f"to close.")
                else:
                    asking.append(f"I don't hold {item.label} yet; looking it up "
                                  f"found nothing, so I'll run a more targeted search.")

        # Recite a memory only if it is a CLAIM worth saying back. Pre-readability
        # records are reader-oriented prose -- "Query: ... Answer: ...",
        # "Learning: ... — a; b; c" -- that recite as noise; a record that is not
        # a single clean statement is skipped rather than said back malformed as
        # if it were remembered knowledge.
        _junk = ("query:", "answer:", "reasoning steps", "learning:",
                 "conclusion(s)", "premise(s)", "[premise")
        recitable = next(
            (m for m in understanding.remembered
             if m and "\n" not in m and len(m) <= 220
             and not any(j in m.lower() for j in _junk)),
            None)
        if recitable:
            lines.append("I remember: " + recitable)
        elif understanding.recall is not None and not understanding.recall.complete:
            # SAY SO. An answer that nearly had a memory is a different answer
            # from a complete one, and only one of them is worth trusting twice.
            lines.append("(still searching memory — ask again for more)")

        if not known and (lines or asking):
            return "\n".join(lines + asking)

        if not known:
            if not unknown:
                return "There was nothing in that I could resolve."
            missing = ", ".join(r.phrase for r in unknown)
            tried = any(a.origin == "research" for a in understanding.acquired)
            # An internal user is not the substrate's lookup service: a gap is
            # closed in the BACKGROUND (it is registered as a known-unknown and
            # picked up as an acquisition goal), never turned back as "what is
            # it?". The reply states the gap honestly and that it will be pursued.
            return (f"I don't hold {missing} yet"
                    + (", and looking it up turned up nothing, "
                       if tried else "; ")
                    + "so I'll run a more targeted search.")

        # ANSWER THE QUESTION IF ONE WAS ASKED, rather than reciting the
        # concept it was about.
        if understanding.answers:
            for answer in understanding.answers:
                # A DERIVED answer carries its conclusion and the premises it was
                # proved from, so it reads as a reason, not an assertion to take
                # on trust. A DIRECT answer is composed from the stored relation.
                derived = bool(answer.conclusion or answer.support)
                because = ((" because " + " and ".join(answer.support))
                           if answer.support else "")
                if derived:
                    claim = answer.conclusion or (
                        f"{answer.about} {answer.relation} "
                        + ", ".join(answer.others))
                    if answer.verdict is True:
                        lines.append(f"Yes — {claim}{because}.")
                    elif answer.verdict is False:
                        # The question DENIED what the substrate proved true, so
                        # the answer is no -- and the reason is that it IS the case.
                        lines.append(f"No — {claim}{because}.")
                    else:  # open question: the derived conclusion IS the answer
                        lines.append(f"{claim[:1].upper()}{claim[1:]}{because}.")
                elif answer.verdict is True:
                    lines.append(f"Yes — {answer.about} {answer.relation} "
                                 + ", ".join(answer.others) + ".")
                elif answer.verdict is False:
                    # The store holds the DENIAL. Said as such, because "no"
                    # alone reads the same as never having been told.
                    lines.append(f"No — I was told {answer.about} "
                                 f"{answer.relation} "
                                 + ", ".join(answer.others) + ".")
                else:
                    lines.append(f"{answer.about} — {answer.relation}: "
                                 + ", ".join(answer.others))
            accounted = understanding.spoken_for()
            unanswered = [r.phrase for r in unknown
                          if not any(same_stem(r.phrase, w) for w in accounted)]
            if unanswered:
                lines.append("I hold nothing for: " + ", ".join(unanswered))
            return "\n".join(lines)

        for item in known:
            where = f" ({item.domain})" if item.domain else ""
            lines.append(f"{item.phrase}{where}: {item.description}")
            for relation, other in item.relations:
                lines.append(f"    {relation} {other}")

        # ASK, rather than answer around it. A phrase the store holds twice is
        # not one the substrate can answer about until it knows which was meant.
        for item in known:
            if item.alternatives:
                where = ", ".join(d or c for c, d in item.alternatives)
                lines.append(f"Which {item.phrase} do you mean — the one in "
                             f"{item.domain}, or in {where}?")

        if unknown:
            lines.append("I hold nothing for: " + ", ".join(r.phrase for r in unknown)
                         + ". Tell me what it is and I will keep it.")
        if understanding.reading:
            lines.append(f"Read as {understanding.reading[0]} "
                         f"(by {understanding.reading_source}).")
        return "\n".join(lines + asking)


#: Held conversations, keyed by session. Bounded, oldest evicted first.
#:
#: WHY THIS EXISTS. `Conversation` carries everything continuity depends on --
#: `_turns`, `_last_subject`, `_last_reply`, `_recall` -- and every caller
#: constructed a fresh one. The coordinator built one at :7142 to classify a
#: message and ANOTHER at :7156 to understand the same message, so the two
#: halves of one turn could not see each other. Nothing could carry a subject
#: across turns, notice a follow-up, or answer "what were we talking about":
#: the machinery for all three is in this file and was unreachable.
#:
#: Keyed by session and not global. One shared instance would merge every
#: speaker's turns into a single thread, so what one person said would surface
#: as context for another -- a worse failure than having no continuity at all.
_conversations: "OrderedDict[str, Conversation]" = OrderedDict()

#: How many conversations are held at once. Past this the least recently used
#: is dropped: a long-running process must not accumulate one per session
#: forever, and losing continuity is recoverable while exhausting memory is not.
MAX_HELD_CONVERSATIONS = 64


def get_conversation(session: str, *, db=None, identity=None) -> "Conversation":
    """The held conversation for `session`, created on first use.

    `session` identifies a THREAD OF TALK, not a person -- two windows belong
    to two sessions. A caller with no session of its own must pass a stable
    string of its own choosing rather than a default, so unrelated callers
    cannot silently share one another's context.
    """
    key = str(session)
    held = _conversations.get(key)
    if held is None:
        held = Conversation(db=db, identity=identity)
        _conversations[key] = held
        while len(_conversations) > MAX_HELD_CONVERSATIONS:
            evicted, _ = _conversations.popitem(last=False)
            logger.info("conversation %s evicted; %d held", evicted,
                        len(_conversations))
    _conversations.move_to_end(key)
    return held


def end_conversation(session: str) -> bool:
    """Forget a thread of talk. Returns whether one was held."""
    return _conversations.pop(str(session), None) is not None


def held_conversations() -> int:
    """How many threads are currently held. For health reporting."""
    return len(_conversations)



# =============================================================================
# IDENTITY VOCABULARY — the substrate's own account of who it is.
#
# Moved here from self_model.py when the Self was collapsed into this
# coordinator. The substrate IS this coordinator, so its name, its stable
# identity text, and the SelfState snapshot the coordinator composes belong
# with it. IDENTITY_CORE is the SINGLE source of the identity — never recite it
# elsewhere; anything that needs it (this substrate priming the model it
# consults, a status readout) reads it from here via identity_prompt().
# =============================================================================

#: The substrate's name. The one authored constant — everything else is derived.
NAME = "Torin"

#: Who Torin is, model-facing and second-person — the STABLE identity core.
#: Deliberately model-GENERIC: the specific model name, size, and context window
#: are deployment facts (they change, belong to continuity/config), not identity.
#: What IS identity is that a model is a resource consulted only when the
#: substrate's own machinery cannot represent the question — the model-optional
#: stance, stated honestly.
IDENTITY_CORE = (
    "You are Torin, a cognitive substrate created by Dominion Labs Inc. You are "
    "not a language model. Your reasoning is symbolic and evidence-based, it "
    "persists between sessions in a database, and it is the thing that decides. A "
    "language model is available to you as a resource you consult — it proposes, "
    "formalises, and reads language for you — and only when your own machinery "
    "cannot represent the question. When the model is unavailable you lose input "
    "coverage, not the ability to reason. You run locally, you persist between "
    "sessions, and your memories carry forward."
)


@dataclass
class SelfState:
    """A snapshot of who the substrate is right now, entirely derived.

    Fields that have no live source yet are None, never fabricated. `attitude`,
    `temperament`, `drives`, `values`, and `disposition` are wired in v1;
    `competence`, `purpose`, and `continuity` are declared here and populated as
    their authorities are connected — the shape is honest about what is not yet
    integrated.
    """

    name: str
    #: my read of my own internal state — the interoceptive variables appraisal
    #: integrates (valence, confidence, control, progress, open-questions, risk…).
    #: None if nothing has been appraised. This is what the affect is a category OF.
    interoception: Optional[Dict[str, Any]]
    #: how I feel now — affective CATEGORIES over the interoceptive state above,
    #: not selected words. None if nothing appraised.
    attitude: Optional[Dict[str, Any]]
    #: what I am disposed toward — from the standing motivation weights
    temperament: Dict[str, float]
    #: how strongly each drive is active now — from the motivation state
    drives: Optional[Dict[str, float]]
    #: what I am bound by — the constitutional laws (names)
    values: List[str]
    #: how disposition applies to the situation now — from the arbiter over appraisal
    disposition: Dict[str, Any]
    #: what I am actually good at / made of — UDM competence, component registry (later)
    competence: Optional[Dict[str, Any]] = None
    #: what I am for — active directives (later)
    purpose: Optional[List[str]] = None
    #: who I have been, carried forward — memory + persisted profile + deployment (later)
    continuity: Optional[Dict[str, Any]] = None
    #: how I feel now, carried between sessions — the persistent affect STATE
    #: (named emotion + cause + intensity + the mood it sits on), owned by the
    #: motivation system and rehydrated on startup. None until an affect has been
    #: established; never a fabricated feeling.
    affect: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        from dataclasses import asdict
        return asdict(self)
