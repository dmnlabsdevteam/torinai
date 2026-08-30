#!/usr/bin/env python3
"""
TorinAI Unified Learning System
Integrated learning system combining all learning components
"""

import hashlib
import logging
import asyncio
import json
from contextvars import ContextVar
import time
import uuid
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from enum import Enum
from typing import Dict, List, Any, Optional
from core.database.logging_database import LoggingDatabase

# Import unified LLM service - the teacher model
# Lazy import to avoid circular import during package initialization
try:
    from core.services.unified_llm import get_llm_service, LLMRequest, LLMResponse  # type: ignore
except Exception as _e:
    # Defer import; resolved inside start() when needed
    get_llm_service = None  # type: ignore
    LLMRequest = None  # type: ignore
    LLMResponse = None  # type: ignore

# Import Slack notifier for learning milestone notifications
from core.integration.slack_notifier import get_slack_notifier

logger = logging.getLogger(__name__)


from ..memory import MemoryManager, CognitiveExperience, MemoryType, MemoryPriority
from .meta_learning import MetaLearner, get_meta_learner
from .learning_interfaces import (
    ILearningSystem,
    LearningType,
    LearningExample,
    LearningResult,
)
from .meta_learning import TaskFamily, task_family_for_task_type

# LearningType (how we are learning) -> TaskFamily (what kind of task it is).
# meta_learning registers and selects strategies by TaskFamily; this system
# speaks LearningType. Passing a LearningType through matched nothing, so
# select_strategy() returned None and its caller dereferenced it.
# HOW SOMETHING WAS LEARNED -> WHAT KIND OF PROBLEM IT IS.
#
# This covered 6 of LearningType's 10 members and was read with a
# `.get(learning_type, TaskFamily.CLASSIFICATION)` default, so the four
# substrate types -- the ones naming how the substrate ACTUALLY learns -- were
# silently filed as classification. Combined with the same default catching
# every unstated family, 10,601 of 11,720 recorded decisions were scored
# against the classification arms without anything deciding they were
# classification problems. `classification_transfer` reached 519 trials at
# confidence 1.000 on work that was largely not classification.
#
# CONTRIBUTION is deliberately absent. Admitting a proposal against evidence is
# not a learning problem with strategy alternatives to choose between, so there
# is no honest family for it, and inventing one would put a strategy's credit
# on an event no strategy influenced. Unmapped is stated below, not defaulted.
_LEARNING_TYPE_TO_TASK_FAMILY = {
    LearningType.SUPERVISED: TaskFamily.CLASSIFICATION,
    LearningType.UNSUPERVISED: TaskFamily.PERCEPTION,
    LearningType.REINFORCEMENT: TaskFamily.REINFORCEMENT,
    LearningType.TRANSFER: TaskFamily.CLASSIFICATION,
    LearningType.CONTINUAL: TaskFamily.SEQUENCE,
    LearningType.META: TaskFamily.REASONING,
    # A rule generalised from demonstrations is a reasoning problem.
    LearningType.INDUCTION: TaskFamily.REASONING,
    # A procedure derived from I/O pairs produces a program.
    LearningType.SYNTHESIS: TaskFamily.GENERATION,
    LearningType.CAUSAL: TaskFamily.REASONING,
}

# Import domain knowledge system for transfer learning
from core.domain import (
    CrossDomainReasoner, DomainRegistry, UniversalOntology, UnknownDomain,
    UnresolvedDomainReference)
from core.capability import raise_if_structural

#: How deep learning has recurred WITHIN THE CURRENT TASK.
#:
#: This replaces `self._learning_in_progress` + `self._current_nesting_depth`,
#: two instance attributes shared by every caller of the singleton. They could
#: not tell recursion from concurrency, and `learn_from_example` awaits
#: repeatedly, so any two parallel tasks interleaved through them. Measured
#: with five concurrent (NOT nested) calls: one was rejected outright with
#: "Circular dependency detected", and the guard was left at
#: `in_progress=True, depth=0` afterwards -- stuck, so every later call counted
#: as nested and the system would refuse all learning after three more.
#:
#: A ContextVar is per-task and inherited by awaited callees, which is exactly
#: the distinction the guard needs: a nested call sees its caller's depth, a
#: sibling task starts at zero. Nothing to reset, so it cannot be left corrupt.
_learning_depth: "ContextVar[int]" = ContextVar("learning_depth", default=0)


def _json_safe(value: Any) -> Any:
    """Coerce a value into something the memory store can serialise.

    source_context carries the producer's example verbatim under
    'example_data', so it holds whatever a caller put there -- an enum, a
    dataclass, a datetime. The hot tier serialises that column as JSON and a
    single non-serialisable object fails the WHOLE insert: the memory is lost
    and the lane reports nothing but "Memory agent rejected: None", which is
    indistinguishable from the worthiness filter declining it.

    Observed by putting a LearningType on the example so the strategy could be
    selected by task family -- a correct change that silently stopped every
    learning memory from persisting. Whether an outcome is recorded must not
    depend on which Python types a producer happened to use.
    """
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    if is_dataclass(value) and not isinstance(value, type):
        return _json_safe(asdict(value))
    return str(value)


class UnifiedLearningSystem(ILearningSystem):
    """Unified learning system that coordinates all learning components"""
    
    def __init__(self, config: Optional[Dict[str, Any]] = None, domain_master=None):
        self.config = config or {}
        self.domain_master = domain_master
        self.initialized = False

        # Initialize components
        self.memory_system = None  # Will be injected by main.py
        self.llm_service = None  # Will be injected by main.py
        meta_db_path = config.get('meta_learning_db_path', 'meta_learning.db') if config else 'meta_learning.db'
        # Use global MetaLearner singleton so meta-learning is shared
        self.meta_learning = get_meta_learner(config=self.config.get("meta_learning_config"))

        # Domain knowledge integration for transfer learning (use singletons)
        self.domain_registry = None
        self.universal_ontology = None
        self.cross_domain_reasoner = None  # Will be initialized in initialize() method - needs domain_registry and universal_ontology

        self.domain_learning_stats = {
            "cross_domain_transfers": 0,
            "domain_specific_learning": 0,
            "transfer_learning_successes": 0
        }

        # Logging Database - For comprehensive learning activity logging (compliance & accountability)
        self.log_db = LoggingDatabase()
        # Note: Will be initialized in async start() method

        # Initialize the teacher model - Unified LLM Service
        self.llm_service = None  # Initialized in async start()

        # System state. The queue is bounded: it used to grow for the life of
        # the process because nothing ever removed from it.
        self.active_learning_tasks = []
        self._max_queued_events = 200
        #: Strong references to in-flight event tasks. Without these, asyncio
        #: only holds a weak reference and a task can be garbage-collected
        #: mid-flight, losing the learning silently.
        self._event_tasks: set = set()
        # PER-PROCESS COUNTERS ONLY. These reset on restart, which is fine for
        # what they are, but they must not be confused with the recorded totals
        # -- `get_learning_metrics` reports both, labelled.
        #
        # `knowledge_base_size` was removed from here: nothing ever assigned it,
        # so it was reported as 0 forever, including in the Slack milestone
        # ("Knowledge Base Size: 0"). It is measured now, from the stores that
        # actually hold knowledge.
        self.system_metrics = {
            "total_learning_sessions": 0,
            "successful_adaptations": 0,
            "cross_domain_insights": 0
        }

        # Exploration quota tracking (for MetaLearner hard gate)
        self.recent_strategy_usage = []  # Track last 100 strategy selections
        self.max_recent_strategies = 100

        # Circular dependency guard. The depth itself lives in the
        # `_learning_depth` ContextVar so it is per-task; only the limit is
        # configurable state on the instance.
        self._max_nesting_depth = 3

        # Slack notifier for learning milestones
        self.slack_notifier = get_slack_notifier()
    
    #: Fire-and-forget notification tasks, held so the event loop cannot
    #: garbage-collect them mid-flight. asyncio keeps only a weak reference to a
    #: task, so a create_task() whose result nobody stores can vanish before it
    #: runs -- silently, and only sometimes.
    _pending_notifications: set = set()

    def _notify(self, **kwargs) -> None:
        """Send a Slack notification WITHOUT holding the learning path.

        A notification is a side effect. Whether a chat message was delivered
        says nothing about whether learning succeeded, so nothing here waits to
        find out.

        This was `self._notify(...)` at six sites,
        and the cost of that landed somewhere it had no business being: every
        AbstractReasoningEngine.reason() call blocked indefinitely at
        `_update_learning`, because reasoning -> learning -> notification, and
        the notification would not resolve. Instrumenting the awaits showed it
        exactly --

            ENTER select_strategy  EXIT 4ms
            ENTER store_memory     EXIT 148ms
            ENTER slack            (never exits)

        -- so every registered kind of thinking was unreachable through its own
        engine because a webhook was unreachable. `SEND_DEADLINE_SECONDS` in the
        notifier now bounds that at 35 s for every caller, but a bound is not
        the same as not waiting: reasoning should not pay 35 s either, and it
        has no reason to wait even 35 ms.

        Failures are logged and dropped. There is nothing sensible for a
        learning routine to DO about an undelivered chat message.
        """
        notifier = getattr(self, "slack_notifier", None)
        if notifier is None:
            return
        try:
            task = asyncio.ensure_future(notifier.send_notification(**kwargs))
        except RuntimeError:
            # No running loop -- called from sync context during teardown.
            logger.debug("notification skipped: no running event loop")
            return
        self._pending_notifications.add(task)
        task.add_done_callback(self._pending_notifications.discard)

        def _log_failure(finished):
            if finished.cancelled():
                return
            error = finished.exception()
            if error is not None:
                logger.warning("notification failed: %s: %s",
                               type(error).__name__, error)
        task.add_done_callback(_log_failure)

    async def start(self) -> None:
        """Start the unified learning system

        Raises:
            RuntimeError: If critical learning components fail to initialize
        """
        try:
            # Initialize logging database
            await self.log_db.initialize()
            logger.info("✅ Logging database initialized for learning activity tracking")

            # CRITICAL: Connect to the teacher model - Unified LLM Service
            logger.info("🎓 Connecting to Unified LLM Service (the teacher model)...")
            # Resolve lazy import here to avoid circular import at module load time
            _get = get_llm_service
            if _get is None:
                from core.services.unified_llm import get_llm_service as _resolved_get
                _get = _resolved_get

            # Check if get_llm_service is async
            if asyncio.iscoroutinefunction(_get):
                self.llm_service = await _get()  # Await if async
            else:
                self.llm_service = _get()  # Call directly if sync

            # Validate teacher-model connection
            if self.llm_service is None:
                raise RuntimeError("LLM service returned None")

            # Check is_initialized if it exists
            if hasattr(self.llm_service, 'is_initialized') and not self.llm_service.is_initialized:
                raise RuntimeError("LLM service is not initialized")
                
            logger.info("✅ Teacher model connected — it proposes; the substrate decides")

            # CRITICAL: Get memory system if not already set
            if self.memory_system is None:
                logger.info("Getting memory system from global singleton...")
                from core.memory import get_memory_agent
                self.memory_system = await get_memory_agent()

            # "CONNECTED" WAS ASSERTED, NOT CHECKED.
            #
            # get_memory_agent() returns the singleton WITHOUT initialising it
            # -- its own docstring tells the caller to await initialize()
            # next -- and this logged the tick regardless. Verified:
            # get_learning_state() reported memory_system_active=False right
            # after start() said the memory system was connected. It worked
            # anyway only because store_memory initialises lazily on first use,
            # so the first learning call of every process paid that cost and
            # any failure surfaced there instead of here.
            #
            # initialize() is idempotent (it returns early when already
            # initialised), so calling it is safe whoever else has.
            if hasattr(self.memory_system, "initialize"):
                await self.memory_system.initialize()

            if not getattr(self.memory_system, "initialized", False):
                raise RuntimeError(
                    "Memory system did not initialise; learning would be "
                    "recorded against a store that is not ready")

            logger.info("✅ Memory system connected and initialised")

            # Get domain systems if not already set
            if self.domain_registry is None:
                logger.info("Getting domain registry from global singleton...")
                from core.domain.domain_registry import get_domain_registry
                self.domain_registry = get_domain_registry()

            if self.universal_ontology is None:
                logger.info("Getting universal ontology from global singleton...")
                from core.domain.universal_ontology import get_universal_ontology
                self.universal_ontology = get_universal_ontology()

            if self.cross_domain_reasoner is None:
                logger.info("Getting cross-domain reasoner from global singleton...")
                from core.domain.cross_domain_reasoner import get_cross_domain_reasoner
                self.cross_domain_reasoner = get_cross_domain_reasoner()

            logger.info("✅ Domain systems connected")
            
            # CRITICAL: Initialize meta-learning system
            logger.info("Initializing meta-learning system...")

            # Set LLM service on meta-learner BEFORE calling initialize
            self.meta_learning.llm_service = self.llm_service

            await self.meta_learning.initialize()  # This raises on failure

            if not self.meta_learning.active:
                raise RuntimeError("MetaLearningSystem is not active after initialization")

            if self.meta_learning.llm_service is None:
                raise RuntimeError("MetaLearningSystem has no LLM service connection")
                
            logger.info("✅ Meta-learning system initialized")

            self.initialized = True
            logger.info("✅ Unified learning system started successfully")

            # NOTE: No Slack notification here - system startup notification is sent by main.py
            # to avoid duplicate notifications

        except RuntimeError as re:
            # RuntimeError we raised - just re-raise
            self.initialized = False

            # 📢 Slack alert for initialization failure
            self._notify(
                message=f"🚨 **Learning System Initialization Failed**\n"
                        f"• Error: {str(re)}\n"
                        f"• Type: RuntimeError\n"
                        f"• Impact: Learning functionality unavailable\n"
                        f"• Action: Check component initialization",
                channel="ALERTS",
                severity="error"
            )
            raise

        except Exception as e:
            logger.error(f"Unexpected error starting unified learning system: {e}")
            self.initialized = False

            # 📢 Slack alert for unexpected initialization error
            self._notify(
                message=f"🚨 **Learning System Critical Error**\n"
                        f"• Error: {type(e).__name__}\n"
                        f"• Message: {str(e)}\n"
                        f"• Impact: Learning system failed to start\n"
                        f"• Action: Review logs for full stack trace",
                channel="ALERTS",
                severity="error"
            )

            raise RuntimeError(
                f"Unexpected error during learning system initialization: {e}\n"
                f"Check logs for full stack trace."
            ) from e
    
    async def _report_unmapped_learning_type(self, learning_type_name: str) -> None:
        """Record that a learning type has no family, on the failure record.

        A warning in a log file is what the CLASSIFICATION default effectively
        was -- invisible to every consumer. This puts it where the systems that
        watch for gaps can read it.
        """
        try:
            from core.observability import failure_record

            await failure_record.report(
                component="learning.unified_learning_system",
                failure_type="unmapped_learning_type",
                description=(f"Learning type {learning_type_name!r} has no "
                             f"TaskFamily; the example could not be scored "
                             f"against any strategy pool"),
                source_system="unified_learning_system",
                severity="medium",
                metadata={"learning_type": learning_type_name})
        except Exception as error:
            logger.error("Could not report unmapped learning type %r: %s",
                         learning_type_name, error)

    async def learn_from_example(self, example: Dict[str, Any]):
        """Learn from example - route to memory system + meta-learning

        This method NO LONGER uses learning_engine (deleted).
        Instead, it routes to:
        1. Meta-learning for strategy selection
        2. Memory system for persistent storage
        3. Meta-learning for outcome tracking

        Raises:
            RuntimeError: If circular dependency detected (learning calling learning)
        """
        if not self.initialized:
            await self.start()

        # CIRCULAR DEPENDENCY GUARD. Counts recursion within THIS task only, so
        # parallel learning is not mistaken for a cycle. See _learning_depth.
        depth = _learning_depth.get() + 1
        if depth > self._max_nesting_depth:
            logger.error(
                "🛑 CIRCULAR DEPENDENCY DETECTED: learning recursed %d levels "
                "within one task (limit %d)", depth, self._max_nesting_depth)
            raise RuntimeError(
                f"Circular dependency detected: learning called itself {depth} "
                f"levels deep within a single task. This prevents deadlock. "
                f"Check for autonomous_coordinator <-> learning circular calls."
            )
        if depth > 1:
            logger.warning("Learning nested call within one task (depth %d)", depth)

        depth_token = _learning_depth.set(depth)

        start_time = time.time()
        learning_id = str(uuid.uuid4())

        try:
            # Extract learning type.
            #
            # Accepted as either the enum or its value, because the mapping
            # below is keyed by the ENUM: a producer that states
            # 'type': 'continual' would otherwise miss the lookup and fall to
            # the CLASSIFICATION default while appearing to have declared
            # itself. An unrecognised name is reported rather than silently
            # becoming SUPERVISED.
            learning_type = example.get('type') or LearningType.SUPERVISED
            if not isinstance(learning_type, LearningType):
                try:
                    learning_type = LearningType(str(learning_type).lower())
                except ValueError:
                    logger.warning(
                        "Unknown learning type %r; treating as SUPERVISED",
                        learning_type)
                    learning_type = LearningType.SUPERVISED
            learning_type_name = learning_type.value

            # 🧠 Use meta-learning to select optimal strategy with HARD GATE
            logger.info(f"📚 Learning from example (type: {learning_type_name})")

            # Calculate exploration quota used
            exploration_quota = self._calculate_exploration_quota()

            # Two different taxonomies meet here. This layer describes HOW it is
            # learning (LearningType: supervised/unsupervised/...); meta_learning
            # keys its strategies by WHAT KIND of task it is (TaskFamily:
            # classification/perception/...). Passing a LearningType straight
            # through never matched any registered strategy, so select_strategy
            # returned None and the next line dereferenced it.
            # The map is a LOSSY BRIDGE and the producer often knows better.
            # Six LearningTypes fan into eight TaskFamilies, so REASONING is
            # reachable only via META and CONTROL/GENERATION/REGRESSION not at
            # all. A reasoning engine reporting a derivation had to arrive as
            # CONTINUAL and be scored against the sequence arms, which say
            # nothing about reasoning. A stated family is used as given; the map
            # remains the fallback for callers that only speak LearningType.
            stated_family = example.get('task_family')
            task_family = None
            if stated_family is not None:
                if isinstance(stated_family, TaskFamily):
                    task_family = stated_family
                else:
                    try:
                        task_family = TaskFamily(str(stated_family).lower())
                    except ValueError:
                        logger.warning(
                            "Unknown task_family %r; deriving from learning type",
                            stated_family)
            if task_family is None:
                task_family = _LEARNING_TYPE_TO_TASK_FAMILY.get(learning_type)
            if task_family is None:
                # NO DEFAULT FAMILY. A learning type with no family has no arm
                # pool to be scored against, and choosing one anyway credits a
                # strategy for work it did not do -- which is exactly how the
                # classification arms accumulated 10,601 decisions.
                #
                # This returns rather than continuing, matching the existing
                # `strategy is None` path a few lines down: everything after
                # this point is written around a selected strategy (usage
                # tracking, memory tags, outcome credit), so there is no
                # "learn anyway" branch to fall into. The caller gets a named
                # reason instead of a silent mis-filing.
                logger.warning(
                    "No task family for learning type %r; no strategy pool "
                    "exists for it (add it to _LEARNING_TYPE_TO_TASK_FAMILY "
                    "if it has one)", learning_type_name)
                await self._report_unmapped_learning_type(learning_type_name)
                return {'success': False, 'error': 'unmapped_learning_type',
                        'learning_type': learning_type_name}

            # CAPTURE THE DECISION so the outcome can be joined back onto it.
            #
            # select_strategy writes the decision row (chosen arm, propensity,
            # candidates, context) and hands back its id through _decision_sink;
            # track_learning_outcome closes that row with what actually
            # happened. This lane passed neither, so every decision it made was
            # written open and never closed: 1,891 of 1,894 rows sat at
            # outcome_known=false with performance_score NULL. The propensity
            # needed for off-policy estimation was being recorded faithfully and
            # the reward beside it never was, which is the half that cannot be
            # reconstructed afterwards.
            decision_sink: Dict[str, Any] = {}
            strategy = await self.meta_learning.select_strategy(
                task_type=task_family,
                prefer_fast=False,
                min_confidence=0.5,
                enable_hard_gate=True,  # HARD GATE: Block unreliable strategies
                exploration_quota_used=exploration_quota,
                # The BASE decision problem. Namespaced arms in the same family
                # (executor:*, tasktype:*) belong to the coordinator's own
                # decisions and are not alternatives to a learning strategy.
                exclude_namespaced=True,
                decision_context={'learning_type': learning_type_name,
                                  'domain': example.get('domain'),
                                  'source': example.get('source')},
                _decision_sink=decision_sink,
            )
            decision_id = decision_sink.get("decision_id")

            if strategy is None:
                logger.error(
                    f"No learning strategy available for {learning_type} "
                    f"(mapped to {task_family}). Registered families: "
                    f"{sorted({s.task_type.value for s in self.meta_learning.strategies.values()})}"
                )
                return {'success': False, 'error': 'no_strategy_available'}

            # Track strategy usage for exploration quota
            self._track_strategy_usage(strategy)

            logger.info(
                f"🎯 Meta-learning selected strategy: {strategy.strategy_type} "
                f"(trials={strategy.trials}, success_rate={strategy.success_rate:.1%}, "
                f"exploration_quota={exploration_quota:.1%})"
            )

            # 💾 ASK memory agent to store (it handles categorization, weighting, type)
            memory_id = None
            if self.memory_system:
                # Memory agent decides: memory_type, priority, worthiness, categorization
                # We just provide content + source_context (raw metadata)
                success, memory_id = await self.memory_system.store_memory(
                    content=f"Learning: {example.get('content', str(example)[:200])}",
                    importance_score=example.get('accuracy', 0.5),  # Hint for importance weighting
                    # strategy.strategy_id, not the dataclass. Memory lowercases
                    # every tag, so passing the object raised
                    # "'LearningStrategy' object has no attribute 'lower'" and
                    # the memory was rejected -- which surfaced only as
                    # "Memory agent rejected: None".
                    tags=['learning', learning_type_name, strategy.strategy_id,
                          'unified_learning_system'],
                    # JSON-safe at the boundary. 'example_data' is the
                    # producer's payload verbatim and this column is serialised
                    # as JSON, so one enum or dataclass in it loses the whole
                    # memory.
                    source_context=_json_safe({
                        'learning_id': learning_id,
                        'learning_type': learning_type_name,
                        'strategy': strategy.strategy_id,
                        'strategy_type': str(strategy.strategy_type),
                        # The OUTCOME AS STATED, not defaulted to a win. This
                        # read `example.get('success', True)`, so an example
                        # that said nothing was persisted as a success while the
                        # credit path below correctly recorded it as unknown --
                        # the stored record and the posterior disagreed.
                        'success': example.get('success'),
                        'accuracy': example.get('accuracy', 0.0),
                        'timestamp': time.time(),
                        'source': 'unified_learning_system',
                        'example_data': example
                    })
                )

                if success:
                    logger.info(f"💾 Memory agent stored learning: {memory_id}")
                else:
                    logger.warning(f"⚠️  Memory agent rejected: {memory_id}")

                # 📢 Slack notification for important learning milestones
                # STATED, not defaulted. `example.get('success', True)` fired
                # this "High-Accuracy Learning Achieved" alert for examples that
                # said nothing about their outcome -- while the credit path
                # below correctly classed the very same example as
                # INSUFFICIENT_EVIDENCE. The notification claimed a win the
                # posterior refused to award.
                if example.get('success') is True and example.get('accuracy', 0.0) > 0.9:
                    self._notify(
                        message=f"🎓 **High-Accuracy Learning Achieved**\n"
                                f"• Type: {learning_type}\n"
                                f"• Strategy: {strategy.strategy_id}\n"
                                f"• Accuracy: {example.get('accuracy', 0.0):.2%}\n"
                                f"• Memory ID: {memory_id}",
                        channel="ACTIVITY",
                        severity="info"
                    )
            else:
                logger.warning("⚠️  Memory system not available - learning NOT persisted!")

                # 📢 Slack alert for missing memory system
                self._notify(
                    message="⚠️ **Learning System Warning**\n"
                            f"Memory system unavailable - learning experience NOT persisted!\n"
                            f"Learning ID: {learning_id}",
                    channel="ALERTS",
                    severity="warning"
                )

            # 📊 Track outcome in meta-learning for strategy optimization
            #
            # `example.get('success', True)` defaulted an unknown outcome to a
            # win, so any example lacking the key silently rewarded whatever
            # strategy was selected. Absent means unknown, and unknown earns no
            # credit.
            from core.learning.meta_learning import OutcomeClass, is_credit_eligible
            raw_success = example.get('success')
            if isinstance(raw_success, bool):
                success = raw_success
                outcome_class = (
                    OutcomeClass.SUCCESS if success else OutcomeClass.STRATEGY_FAILURE
                )
            else:
                success = False
                outcome_class = OutcomeClass.INSUFFICIENT_EVIDENCE
            metrics = {
                'accuracy': example.get('accuracy', 0.0),
                'confidence': example.get('confidence', 0.0),
                # The duration of the WORK, when the producer states it.
                # Measuring locally times this method's own bookkeeping -- 0.12s
                # against a 43s reasoning operation in the observed case -- and
                # that number becomes strategy.avg_time_ms and the efficiency
                # term of effectiveness_score, so the score would rank
                # strategies by how fast their paperwork was.
                'latency': float(
                    example.get('duration_s') or (time.time() - start_time)),
            }

            # Signature is (task_type, strategy_type, success, performance_score,
            # time_ms). It was called with strategy=/metrics=, which raised
            # TypeError on every invocation — so the bandit's successes/failures
            # never incremented and Thompson sampling drew from Beta(1,1) forever.
            await self.meta_learning.track_learning_outcome(
                task_type=task_family,
                strategy_type=strategy.strategy_type,
                success=success,
                performance_score=float(metrics.get('accuracy') or 0.0),
                time_ms=float(metrics.get('latency') or 0.0) * 1000.0,
                outcome_class=outcome_class,
                context={'confidence': metrics.get('confidence'),
                         'learning_type': learning_type_name},
                decision_id=decision_id,
            )

            # Update system metrics
            self.system_metrics['total_learning_sessions'] += 1
            if success:
                self.system_metrics['successful_adaptations'] += 1

            logger.info(f"✅ Learning complete in {metrics['latency']:.2f}s - Success: {success}")

            # CRITICAL: Log learning activity for compliance.
            #
            # This called log_activity(activity_type=, details=), which is not on
            # LoggingDatabase -- the class exposes log_operation(operation_type,
            # component, message, level, metadata). It sits in the SUCCESS path,
            # directly after "Learning complete", so every successful
            # learn_from_example raised AttributeError here; the except handler
            # then called the same missing method and raised again, so the
            # original outcome was never reported either. learn_from_example is
            # the one learning entry point the coordinator invokes.
            await self.log_db.log_operation(
                operation_type='learning',
                component='unified_learning_system',
                message=f"learning {learning_id} success={success}",
                level='INFO',
                metadata={
                    'learning_id': learning_id,
                    'learning_type': learning_type_name,
                    'strategy': strategy.strategy_id,
                    'strategy_type': str(strategy.strategy_type),
                    'success': success,
                    'accuracy': example.get('accuracy', 0.0),
                    'latency': metrics['latency'],
                    'memory_id': memory_id,
                    'source': example.get('source', 'user_interaction')
                }
            )

            # 📢 Slack notification for learning milestones (every 100 adaptations)
            if self.system_metrics["successful_adaptations"] % 100 == 0 and success:
                self._notify(
                    message=f"🎓 **Learning Milestone Reached**\n"
                            f"• Total Sessions: {self.system_metrics['total_learning_sessions']}\n"
                            f"• Successful Adaptations: {self.system_metrics['successful_adaptations']}\n"
                            f"• Latest Accuracy: {example.get('accuracy', 0.0):.2%}",
                    channel="ACTIVITY",
                    severity="success"
                )

            # CROSS-DOMAIN: learning in a domain looks for what it already
            # knows elsewhere.
            #
            # Every part of this existed and none of it was reachable:
            # self.cross_domain_reasoner was assigned at :169 and never read,
            # transfer_learning_across_domains (:822) had zero callers,
            # learn_with_domain_context (:897) had zero callers, and the
            # cross_domain_transfers / cross_domain_insights counters were
            # incremented by code nothing invoked. learn_from_example is the one
            # entry point the coordinator actually calls, so the transfer path
            # attaches here rather than to a new lane beside it.
            transfer = None
            domain = example.get('domain') or example.get('domain_id')
            if domain:
                # Gated on the DOMAIN, not on `success`. `success` here is the
                # credit signal -- it reports whether the selected strategy
                # earned credit, and an example that does not state its outcome
                # is INSUFFICIENT_EVIDENCE (:378-385) rather than a failure.
                # Whether a strategy earned credit is a different question from
                # whether Torin already holds a structure that applies here, and
                # an attempt that went badly is if anything MORE reason to ask
                # it. Gating on success meant the transfer path could not fire
                # for any example lacking an explicit outcome.
                transfer = await self._transfer_from_known_domains(
                    str(domain), task_id=example.get('task_id'))

            return {
                'success': success,
                # The IDENTIFIER. Returning the dataclass leaked an internal
                # object into every caller's payload, and anything that tried to
                # serialise the result failed on it.
                'strategy_used': strategy.strategy_id,
                'stored_in_memory': memory_id is not None,
                'memory_id': memory_id,
                'learning_id': learning_id,
                'metrics': metrics,
                'cross_domain': transfer,
                # WHY the outcome was what it was, and whether it moved a
                # posterior. `success` alone cannot separate "the strategy
                # failed" from "nothing could be concluded": both are False, and
                # only the first is evidence about the strategy. Callers that
                # need that distinction were reduced to guessing from it.
                'outcome_class': outcome_class.value,
                'credit_applied': is_credit_eligible(outcome_class),
            }

        except Exception as e:
            logger.error(f"❌ Learning from example failed: {e}")

            # 📢 ROBUST Slack alert for learning failure
            self._notify(
                message=f"🚨 **Learning System Failure**\n"
                        f"• Error: {type(e).__name__}\n"
                        f"• Message: {str(e)}\n"
                        f"• Example Type: {example.get('type', 'unknown')}\n"
                        f"• Session: {self.system_metrics['total_learning_sessions']}\n"
                        f"• Successful Adaptations: {self.system_metrics['successful_adaptations']}",
                channel="ALERTS",
                severity="error"
            )

            # Log error with full stack trace
            import traceback
            try:
                await self.log_db.log_operation(
                    operation_type='learning_error',
                    component='unified_learning_system',
                    message=f"{type(e).__name__}: {e}",
                    level='ERROR',
                    metadata={
                        'error_type': type(e).__name__,
                        'error_message': str(e),
                        'example_type': example.get('type', 'unknown'),
                        'stack_trace': traceback.format_exc()
                    }
                )
            except Exception as log_error:
                # An error handler that raises destroys the error it was handling.
                # This one called a missing method and replaced every real
                # learning failure with AttributeError: log_activity.
                logger.error("Could not record learning failure %r: %s", e, log_error)

            return {
                "success": False,
                "error": str(e),
                "strategy_used": None,
                "stored_in_memory": False
            }

        finally:
            # Restore this task's depth exactly as it was. A token reset cannot
            # leave the guard in a state that rejects future work, which the
            # previous flag-and-counter pair demonstrably could.
            _learning_depth.reset(depth_token)


    def _calculate_exploration_quota(self) -> float:
        """
        Calculate % of recent cycles that used exploration strategies

        Returns:
            Float 0.0-1.0 representing exploration quota used
        """
        if not self.recent_strategy_usage:
            return 0.0

        # Count strategies with < 20 trials (exploration threshold)
        exploration_count = sum(
            1 for strategy in self.recent_strategy_usage
            if strategy.trials < 20
        )

        return exploration_count / len(self.recent_strategy_usage)

    def _track_strategy_usage(self, strategy):
        """
        Track strategy usage for exploration quota calculation

        Args:
            strategy: LearningStrategy that was just used
        """
        # Add to recent usage
        self.recent_strategy_usage.append(strategy)

        # Keep only last N strategies
        if len(self.recent_strategy_usage) > self.max_recent_strategies:
            self.recent_strategy_usage.pop(0)

        logger.debug(
            f"Strategy usage tracked: {strategy.strategy_id} "
            f"(recent={len(self.recent_strategy_usage)}, "
            f"exploration={self._calculate_exploration_quota():.1%})"
        )

    async def process_interaction(self, user_input: str, system_response: str) -> None:
        """Process a user interaction for learning"""
        interaction_example = {
            "input": user_input,
            "output": system_response,
            "context": {"interaction_type": "chat", "timestamp": asyncio.get_event_loop().time()}
        }
        
        await self.learn_from_example(interaction_example)
    
    
    def get_system_status(self) -> Dict[str, Any]:
        """Get comprehensive system status"""
        return {
            "initialized": self.initialized,
            "components": {
                "memory_system": getattr(self.memory_system, 'initialized', False),
                "meta_learning": getattr(self.meta_learning, 'initialized', False),
                "llm_service": self.llm_service is not None
            },
            "metrics": self.system_metrics,
            "active_tasks": len(self.active_learning_tasks)
        }
    
    # ILearningSystem interface implementations
    async def initialize(self) -> bool:
        """Initialize the unified learning system
        
        Raises:
            RuntimeError: If initialization fails
        """
        await self.start()  # This raises on failure
        return True
    
    async def learn_from_data(self, data: Dict[str, Any], learning_type) -> Any:
        """Learn from provided data"""
        # The caller's learning_type has to travel INTO the example.
        #
        # It was only echoed back in the envelope below, while
        # learn_from_example reads example['type'] -- a key nothing ever set --
        # and so defaulted every event to SUPERVISED, which the table at :46
        # maps to CLASSIFICATION. learn_from_experience declares CONTINUAL and
        # the outcome was still recorded against CLASSIFICATION; the other five
        # TaskFamily branches were unreachable no matter what a caller asked
        # for. A payload that names its own type is the more specific statement
        # and still wins.
        result = await self.learn_from_example({'type': learning_type, **data})
        return {
            'event_id': f"unified_{int(time.time())}",
            'event_type': learning_type,
            'data': data,
            'outcome': result,
            'timestamp': time.time(),
            # The example's OWN stated confidence, or None. This was a literal
            # 0.8 on every envelope regardless of what happened -- including
            # for a learning call that failed -- so a caller reading it learned
            # only that someone had typed 0.8.
            'confidence': data.get('confidence'),
        }
    
    async def learn_from_experience(self, experience: Dict[str, Any]) -> Any:
        """Learn from experience data"""
        return await self.learn_from_data(experience, LearningType.CONTINUAL)
    
    async def learn_from_feedback(self, feedback: Dict[str, Any]) -> Any:
        """Learn from feedback, reading the outcome the feedback states.

        THE FEEDBACK'S OWN OUTCOME WAS UNREADABLE. This wrapped it as
        `{'feedback': feedback}`, and learn_from_example reads `success`,
        `accuracy` and `content` from the TOP level -- so they sat one layer
        down and were never seen. Verified: feedback stating
        `success=True, accuracy=0.95` was recorded as `success=False,
        accuracy=0.0`, i.e. INSUFFICIENT_EVIDENCE. Praise and complaint were
        indistinguishable, and no feedback could ever credit a strategy.

        The feedback's fields are lifted to the top level, exactly as
        learn_from_data does with its payload, and the original is kept intact
        under `feedback` for anything that wants the raw form.
        """
        payload: Dict[str, Any] = {'feedback': feedback, 'source': 'feedback'}
        if isinstance(feedback, dict):
            payload.update({k: v for k, v in feedback.items() if k != 'feedback'})
        payload.setdefault('type', LearningType.CONTINUAL)
        if 'content' not in payload:
            payload['content'] = str(feedback)[:500]

        result = await self.learn_from_example(payload)
        return {
            'event_id': f"unified_feedback_{int(time.time())}",
            'event_type': 'feedback',
            'data': feedback,
            'outcome': result,
            'timestamp': time.time(),
            # As above: was a literal 0.7 on every feedback envelope.
            'confidence': feedback.get('confidence') if isinstance(feedback, dict) else None,
        }
    
    async def transfer_learning(self, source_domain: str, target_domain: str) -> bool:
        """Transfer learning between domains.

        Delegates to the real implementation. This returned a bare ``True``
        unconditionally -- reporting a transfer that was never attempted, while
        transfer_learning_across_domains sat 200 lines below doing the actual
        work of proposing, validating and persisting the mappings.
        """
        result = await self.transfer_learning_across_domains(
            source_domain, target_domain, {"trigger": "transfer_learning"})
        return bool(result.get("success"))
    
    async def knowledge_base_size(self) -> Optional[Dict[str, int]]:
        """What the substrate actually holds, by store. None if unreadable.

        There was a `knowledge_base_size` counter in `system_metrics` that
        nothing ever wrote to, so every consumer -- including the Slack
        milestone -- reported 0. A count of what is known is measurable; it was
        just never measured.
        """
        try:
            from core.database import get_database_manager

            db = get_database_manager()
            rows = await db.execute_query(
                """SELECT (SELECT count(*) FROM unified.concepts)            AS concepts,
                          (SELECT count(*) FROM unified.learned_rules)       AS rules,
                          (SELECT count(*) FROM memory_hot.memory_hot)       AS memories""",
                None, fetch_all=True)
        except Exception as error:
            logger.error("Knowledge base size unavailable: %s", error)
            return None
        if not rows:
            return None
        row = rows[0]
        return {"concepts": int(row["concepts"]), "rules": int(row["rules"]),
                "memories": int(row["memories"]),
                "total": int(row["concepts"]) + int(row["rules"]) + int(row["memories"])}

    async def get_learning_metrics(self) -> Dict[str, Any]:
        """Learning metrics: this process's counters, and the recorded totals.

        Returned `self.system_metrics` alone -- three counters that start at
        zero every run. A caller asking a long-lived system how much it had
        learned got whatever had happened since the last restart, with nothing
        saying so.
        """
        try:
            recorded = await self.get_experience_count()
        except RuntimeError as error:
            # None, not 0: an unreadable store is not an empty one.
            logger.error("Recorded experience count unavailable: %s", error)
            recorded = None
        return {
            "this_process": dict(self.system_metrics),
            "recorded_experiences": recorded,
            "knowledge_base": await self.knowledge_base_size(),
        }
    
    async def get_learning_state(self) -> Dict[str, Any]:
        """Get current learning system state for self-improvement analysis"""
        return {
            'initialized': self.initialized,
            'active_tasks': len(self.active_learning_tasks),
            'total_learning_sessions': self.system_metrics.get('total_learning_sessions', 0),
            'successful_adaptations': self.system_metrics.get('successful_adaptations', 0),
            'knowledge_base': await self.knowledge_base_size(),
            # `x is not None` was true by construction for meta_learning (set
            # unconditionally in __init__) and for the other two after start(),
            # so all three reported "active" without checking anything. Each is
            # now asked whether it is actually initialised, and None means the
            # component is absent rather than inactive.
            'llm_service_active': (None if self.llm_service is None
                                   else bool(getattr(self.llm_service, 'is_initialized', True))),
            'memory_system_active': (None if self.memory_system is None
                                     else bool(getattr(self.memory_system, 'initialized', False))),
            'meta_learning_active': (None if self.meta_learning is None
                                     else bool(getattr(self.meta_learning, 'active', False))),
            'recent_tasks': self.active_learning_tasks[-5:] if self.active_learning_tasks else []
        }
    
    async def consolidate_learning(self) -> Dict[str, Any]:
        """Consolidate recent learning. NOT IMPLEMENTED.

        Returned {'consolidated': True} without consolidating anything.
        Consolidation is owned by the memory agent's tiering.
        """
        raise NotImplementedError(
            "consolidate_learning is not implemented. Memory consolidation is "
            "owned by MemoryAgent (hot/cold tiering); call it there.")
    
    def learn_from_event(self, event: Dict[str, Any]) -> bool:
        """Learn from an autonomous system event. Returns whether learning began.

        THIS RETURNED True HAVING LEARNED NOTHING. It appended the event to
        `active_learning_tasks` -- a list that is only ever appended to, never
        drained and never learned from -- and reported success. The interface
        documents the return as "learning success", so every caller was told
        the event had been learned from when it had merely been remembered.
        The list also grew without bound for the life of the process.

        The method is synchronous and cannot await, so the event is handed to
        the real learning path as a task. The return value now states what
        actually happened: True when learning was started, False when there is
        no running loop to start it on -- in which case the event is queued and
        the queue is bounded.
        """
        record = {'type': 'event', 'data': event, 'timestamp': time.time()}
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # No loop: nothing can be learned right now. Say so rather than
            # reporting success, and keep the queue bounded.
            self.active_learning_tasks.append(record)
            del self.active_learning_tasks[:-self._max_queued_events]
            logger.warning(
                "learn_from_event called with no running event loop; the event "
                "was queued (%d held) but nothing has been learned from it",
                len(self.active_learning_tasks))
            return False

        # The event's own fields travel into the example, so an event that
        # states its outcome earns or loses credit like any other example.
        example = {k: v for k, v in event.items() if k != 'type'}
        example.setdefault('type', event.get('type', LearningType.CONTINUAL))
        example.setdefault('source', 'autonomous_event')

        task = loop.create_task(self.learn_from_example(example))
        self._event_tasks.add(task)
        task.add_done_callback(self._event_tasks.discard)

        record['task_scheduled'] = True
        self.active_learning_tasks.append(record)
        del self.active_learning_tasks[:-self._max_queued_events]
        return True

    
    async def predict_optimal_retry_delay(self, context: Dict[str, Any]) -> float:
        """Predict optimal retry delay. NOT IMPLEMENTED.

        Returned the constant 3.0 while its name promised a prediction from
        context, so a caller could not tell a learned delay from a literal.
        """
        raise NotImplementedError(
            "predict_optimal_retry_delay is not implemented; it returned a "
            "hardcoded 3.0. Use an explicit backoff policy at the call site "
            "until a real predictor exists.")
    
    async def process_experience(self, experience: Dict[str, Any]) -> Dict[str, Any]:
        """Process experience data for learning"""
        result = await self.learn_from_example(experience)
        return {'processed': True, 'unified_result': result}
    
    async def update_strategy_effectiveness(self, strategy: str, effectiveness: float) -> bool:
        """Update effectiveness for a strategy. NOT IMPLEMENTED.

        Wrote `strategy_<name>` keys into system_metrics -- a counters dict
        reported as system metrics -- creating a second, unpersisted copy of a
        number MetaLearner already owns, derives from trials and stores in
        meta_learning_strategies.effectiveness_score.
        """
        raise NotImplementedError(
            "update_strategy_effectiveness is not implemented. Strategy "
            "effectiveness is owned and persisted by MetaLearner; record the "
            "outcome via track_learning_outcome and let it derive the score.")
    
    async def recommend_strategies(self, context: Dict[str, Any]) -> List[str]:
        """Recommend strategies for a context. NOT IMPLEMENTED.

        Returned a fixed list of four subsystem names -- not strategies, not
        derived from the context, and not any arm the bandit can select.
        """
        raise NotImplementedError(
            "recommend_strategies is not implemented; it returned a fixed list "
            "of subsystem names. Use MetaLearner.select_strategy, which ranks "
            "real registered arms by their measured posteriors.")
    
    async def drain_events(self, timeout: float = 30.0) -> Dict[str, int]:
        """Wait for event-driven learning to finish. Call before shutting down.

        `learn_from_event` is synchronous and hands the work to a task, so if
        the process exits first that learning is abandoned mid-flight: the
        decision row was written when the arm was selected and the outcome
        never arrives. Verified -- one such row was left open by a test process
        that exited before its task completed.

        Returns what happened, so a caller can see whether the wait was enough
        rather than assuming it was.
        """
        pending = [t for t in self._event_tasks if not t.done()]
        if not pending:
            return {"pending": 0, "completed": 0, "timed_out": 0}

        logger.info("Draining %d in-flight learning task(s)", len(pending))
        done, not_done = await asyncio.wait(pending, timeout=timeout)
        if not_done:
            # Stated, not silently dropped: these will need reaping.
            logger.warning(
                "%d learning task(s) did not finish within %.0fs; their "
                "decisions will be closed as INDETERMINATE by the reaper",
                len(not_done), timeout)
        return {"pending": len(pending), "completed": len(done),
                "timed_out": len(not_done)}

    async def query_experiences(self, query: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Search recorded learning experiences.

        THE QUERY WAS IGNORED. This returned the last ten entries of an
        in-process list regardless of what was asked for, so every query got
        the same answer and none of it survived a restart.

        `unified.operation_logs` is where `learn_from_example` records each
        completed experience (595 of them, all written by this component), so
        that is what a query searches. Supported keys: `learning_type`,
        `strategy`, `success`, `source`, `since_minutes`, `limit`.
        """
        clauses = ["component = 'unified_learning_system'",
                   "operation_type = 'learning'"]
        params: List[Any] = []

        for key in ("learning_type", "strategy", "source"):
            if query.get(key) is not None:
                params.append(str(query[key]))
                clauses.append(f"metadata->>'{key}' = ${len(params)}")
        if isinstance(query.get("success"), bool):
            clauses.append(
                f"(metadata->>'success')::boolean IS {str(query['success']).upper()}")
        if query.get("since_minutes"):
            clauses.append(
                f"created_at > NOW() - INTERVAL '{int(query['since_minutes'])} minutes'")

        limit = max(1, min(int(query.get("limit", 50)), 500))
        try:
            from core.database import get_database_manager

            rows = await get_database_manager().execute_query(
                f"SELECT log_id, message, metadata, created_at FROM unified.operation_logs "
                f"WHERE {' AND '.join(clauses)} ORDER BY created_at DESC LIMIT {limit}",
                tuple(params) or None, fetch_all=True) or []
        except Exception as error:
            # Empty would read as "no experience matches", which is a different
            # answer from "the store could not be searched".
            logger.error("Experience query failed: %s", error)
            raise RuntimeError(
                f"Could not search recorded experiences: {error}") from error

        out: List[Dict[str, Any]] = []
        for row in rows:
            metadata = row["metadata"]
            if isinstance(metadata, str):
                try:
                    metadata = json.loads(metadata)
                except (TypeError, ValueError):
                    metadata = {}
            out.append({"log_id": row["log_id"], "message": row["message"],
                        "recorded_at": row["created_at"], **(metadata or {})})
        return out

    async def get_experience_count(self) -> int:
        """How many learning experiences have been recorded, in total.

        Counted `len(self.active_learning_tasks)` -- an in-process list that
        holds queued events rather than experiences, and starts empty every
        run. The recorded count is 595 and survives restarts.
        """
        try:
            from core.database import get_database_manager

            rows = await get_database_manager().execute_query(
                "SELECT count(*) AS n FROM unified.operation_logs "
                "WHERE component = 'unified_learning_system' "
                "  AND operation_type = 'learning'", None, fetch_all=True)
        except Exception as error:
            logger.error("Experience count unavailable: %s", error)
            raise RuntimeError(
                f"Could not count recorded experiences: {error}") from error
        return int(rows[0]["n"]) if rows else 0
    
    async def predict_outcome(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Predict an outcome for a context. NOT IMPLEMENTED.

        Returned predicted_success=0.85, confidence=0.8 and the reasoning
        string 'unified_learning_analysis' for every input -- constants dressed
        as an analysis, which is the one shape a consumer cannot detect as
        fabricated.
        """
        raise NotImplementedError(
            "predict_outcome is not implemented; it returned constant "
            "0.85/0.8 for every context. PredictiveIntelligenceSystem is the "
            "prediction owner.")

    async def _transfer_from_known_domains(self, target_domain: str,
                                           max_sources: int = 3,
                                           task_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """When learning in a domain, ask what already-learned domain applies.

        This is the call site transfer_learning_across_domains never had. It
        answers the question the cross-domain layer exists for -- "does a
        structure I already hold fit this?" -- at the moment new learning
        arrives, which is when the answer can still change what is stored.

        Sources are ranked by the registry's own similarity so a transfer is
        attempted against the domains most likely to carry a correspondence,
        rather than every domain in the store. A domain never transfers from
        itself.
        """
        registry = self.domain_registry
        if registry is None:
            from core.domain.domain_registry import get_domain_registry
            registry = get_domain_registry()
            self.domain_registry = registry
        # Initialize REGARDLESS of who assigned it. start() (:156-159) sets
        # self.domain_registry from the singleton accessor and never awaits
        # initialize(), so registry.domains is empty and every domain reads as
        # "not registered" -- an assigned handle that is not a loaded registry.
        if not registry.initialized:
            await registry.initialize()

        # RESOLVE the reference; do not coerce it.
        #
        # This built `f"domain_{target_domain}"` by hand -- the exact coercion
        # resolve_domain_reference exists to replace. The live producer
        # (_infer_domain_from_task) classifies work into CATEGORIES
        # ("scientific", "technical"), and `domain_scientific` is a registered
        # domain holding ZERO concepts, so the coercion resolved to a real-but-
        # empty node and every transfer came back "nothing similar". The
        # concepts were never in the category; they are in the fields beneath
        # it, which is what the resolver returns.
        try:
            resolved = registry.resolve_domain_reference(
                target_domain, require_concepts=True)
        except UnresolvedDomainReference:
            # Naming something that does not exist is a different fact from
            # naming a real domain with nothing in it, and is kept separate.
            logger.info(
                "Cross-domain transfer skipped: %r resolves to no registered domain",
                target_domain)
            return {"attempted": False, "reason": "target domain not registered"}

        if not resolved:
            logger.info(
                "Cross-domain transfer skipped: %r resolves only to domains "
                "holding no concepts", target_domain)
            return {"attempted": False, "reason": "target domain holds no concepts"}

        # A category names many fields. Transfer INTO the best-attested one:
        # the resolver already ranks by concept count, and reasoning into every
        # member would multiply one observation into many transfers that share
        # a single piece of evidence.
        canonical = resolved[0].domain_id
        if len(resolved) > 1:
            logger.info(
                "%r resolved to %d populated field(s); transferring into %s",
                target_domain, len(resolved), canonical)

        try:
            # Through the Master -- the authority for the domain system -- for
            # the similarity ranking. The two-stage selection below still reads
            # the registry directly for the mapping ground truth; only the
            # 'what is this domain like' entry is consolidated here.
            from core.integration.universal_domain_master import UniversalDomainMaster
            similar = await UniversalDomainMaster().similar_domains(canonical, threshold=0.0)
        except Exception as e:
            raise_if_structural(e, "UnifiedLearningSystem._transfer_from_known_domains")
            logger.warning("Similarity ranking unavailable: %s", e)
            return {"attempted": False, "reason": f"similarity unavailable: {e}"}

        # TWO-STAGE SELECTION: cheap filter, then rank on the real signal.
        #
        # Ranking by domain similarity alone correlates only 0.209 with the
        # concept-level mapping strength transfer actually consumes — they
        # answer different questions ("are these fields alike?" versus "do these
        # two concepts correspond?"). Ranking on the proxy put a domain with
        # ZERO mappings in the top three while domains at 0.80 were skipped.
        #
        # suggest_cross_domain_mappings is the ground truth and is too costly to
        # run against every domain, so similarity is used for what it is good
        # for -- narrowing the field -- and the shortlist is then ordered by
        # what will actually be transferred.
        shortlist = [d.domain_id for d, _score in similar
                     if d.domain_id != canonical and d.concepts][:max_sources * 3]

        scored = []
        from core.integration.universal_domain_master import UniversalDomainMaster
        _udm = UniversalDomainMaster()
        for candidate in shortlist:
            try:
                # Through the Master, matching the similarity call above.
                mappings = await _udm.suggest_mappings(candidate, canonical)
            except Exception as e:
                raise_if_structural(e, "UnifiedLearningSystem._transfer_from_known_domains")
                logger.debug("Mapping probe failed for %s: %s", candidate, e)
                continue
            if mappings:
                scored.append((max(m.strength for m in mappings), len(mappings), candidate))

        scored.sort(reverse=True)
        sources = [c for _s, _n, c in scored[:max_sources]]
        if scored:
            logger.info(
                "Transfer sources for %s ranked by mapping strength: %s",
                canonical, [(c, round(s, 3)) for s, _n, c in scored[:max_sources]])
        if not sources:
            # Two different real negatives, kept apart. "No other populated
            # domain" is a statement about coverage; "populated domains exist
            # but none share a mapping" is a statement about correspondence, and
            # only the second says anything about this domain's relationship to
            # what Torin knows.
            reason = ("no other populated domain" if not shortlist
                      else f"{len(shortlist)} domain(s) searched, none share a mapping")
            return {"attempted": True, "sources_considered": len(shortlist),
                    "transfers": [], "reason": reason}

        transfers = []
        for src in sources:
            result = await self.transfer_learning_across_domains(
                src, canonical,
                {"trigger": "learn_from_example", "task_id": task_id})
            if result and result.get("success"):
                # "mapping_count" is the key transfer_learning_across_domains
                # actually returns. Reading "mappings_found" with a .get default
                # reported 0 mappings on every SUCCESSFUL transfer -- the same
                # source that had just been ranked first on 10 real mappings.
                # A default silently supplies a plausible value for a key that
                # does not exist, which is why the contradiction survived.
                #
                # It counts VALIDATED mappings. The candidate total is reported
                # beside it rather than in place of it, so a transfer can never
                # be read as larger than what survived validation.
                transfers.append({"source": src,
                                  "validated": result["mapping_count"],
                                  "candidates": result["candidates_considered"]})

        logger.info(
            "Cross-domain: learning in %s consulted %d known domain(s), %d transferred",
            canonical, len(sources), len(transfers))
        return {"attempted": True, "sources_considered": len(sources),
                "transfers": transfers}

    async def transfer_learning_across_domains(self, source_domain: str, target_domain: str,
                                               knowledge: Dict[str, Any]) -> Dict[str, Any]:
        """Transfer learned knowledge from one domain to another"""
        try:
            logger.info(f"Transfer learning: {source_domain} -> {target_domain}")

            # THE ATTEMPT IS COUNTED HERE, THE SUCCESS BELOW.
            #
            # Both counters were incremented on the same line in the success
            # branch, so `transfer_learning_successes` was always exactly equal
            # to `cross_domain_transfers` and one of the two carried no
            # information -- while get_domain_learning_stats reported them side
            # by side as if they were independent facts. A success rate could
            # never be anything but 100%.
            self.domain_learning_stats["cross_domain_transfers"] += 1

            # Cross-domain mapping is owned by the DomainRegistry, not the
            # reasoner. This called find_cross_domain_mapping() on
            # cross_domain_reasoner -- a method that class does not implement --
            # so every transfer raised AttributeError into the broad except
            # below and returned {"success": False}. Meanwhile
            # suggest_cross_domain_mappings() has always worked: verified
            # end-to-end discovering the heart->pump analogy between a
            # cardiovascular and a hydraulics domain.
            registry = self.domain_registry
            if registry is None:
                from core.domain.domain_registry import get_domain_registry
                registry = get_domain_registry()
                self.domain_registry = registry
            if not registry.initialized:
                await registry.initialize()

            # start() assigns the ontology handle without initialising it, the
            # same defect the registry had; validation would then run against an
            # unloaded ontology.
            if self.universal_ontology is None:
                from core.domain.universal_ontology import get_universal_ontology
                self.universal_ontology = get_universal_ontology()
            if not getattr(self.universal_ontology, "initialized", False):
                await self.universal_ontology.initialize()

            mappings = await registry.suggest_cross_domain_mappings(
                source_domain, target_domain
            )

            # VALIDATE, then PERSIST WITH THE VERDICT.
            #
            # suggest_cross_domain_mappings recomputes candidates on every call
            # and nothing ever stored them, which is why unified.domain_mappings
            # held 0 rows while 29 candidates were being found. add_cross_domain_
            # mapping and create_knowledge_transfer both existed with zero
            # callers; each takes exactly the dataclass produced here.
            #
            # Every candidate is stored WITH what was decided about it:
            #   validated=True   structure survived the test -> knowledge
            #   validated=False  structure was measurable and did not correspond
            #   validated=None   too little structure to judge -> still a candidate
            # All three are persisted, because the readers of this table
            # (_load_mappings, UniversalDomainMaster._find_cross_domain_mappings)
            # select `verified IS NULL OR verified IS TRUE` -- they are built to
            # tell an untested proposal from a refuted one. Dropping the
            # indeterminate rows would throw away that distinction, and storing
            # any of them without a verdict is how a proposal silently becomes
            # knowledge.
            accepted, rejected, indeterminate = [], [], []
            for candidate in mappings:
                verdict = await self.universal_ontology.validate_cross_domain_mapping({
                    "source_concept_id": candidate.source_concept_id,
                    "target_concept_id": candidate.target_concept_id,
                })
                candidate.validation_score = float(verdict.get("confidence", 0.0) or 0.0)
                if verdict["verdict"] == "ACCEPTED":
                    candidate.validated = True
                    accepted.append(candidate)
                elif verdict["verdict"] == "REJECTED":
                    candidate.validated = False
                    rejected.append(candidate)
                else:
                    indeterminate.append(candidate)
                if not await registry.add_cross_domain_mapping(candidate):
                    raise RuntimeError(
                        f"Cross-domain mapping {candidate.mapping_id} could not be "
                        f"stored; refusing to report a transfer that was not recorded")

            logger.info(
                "Cross-domain %s -> %s: %d candidate(s) -> %d accepted, %d rejected, "
                "%d indeterminate",
                source_domain, target_domain, len(mappings),
                len(accepted), len(rejected), len(indeterminate))

            # Only a VALIDATED mapping may carry a transfer. This is the line
            # between transfer proposed and transfer learned.
            mapping = accepted[0] if accepted else None
            if mapping is not None:
                from core.domain.domain_types import KnowledgeTransfer
                # Identified by WHAT IS TRANSFERRED, not by when it ran. A uuid4
                # here wrote a fresh row on every pass, so re-deriving the same
                # transfer accumulated identical rows that a reader would count
                # as repeated independent transfers. Re-running now updates the
                # one row the transfer corresponds to.
                digest = hashlib.sha256("\x1f".join(
                    [source_domain, target_domain, "structural_analogy"]
                    + sorted(m.mapping_id for m in accepted)).encode()).hexdigest()[:32]
                transfer = KnowledgeTransfer(
                    transfer_id=f"xfer_{digest}",
                    source_domain_id=source_domain,
                    target_domain_id=target_domain,
                    source_knowledge_ids=[m.source_concept_id for m in accepted],
                    target_knowledge_ids=[m.target_concept_id for m in accepted],
                    transfer_type="structural_analogy",
                    success_probability=mapping.validation_score,
                    # mapping_ids -- the field is List[str], and the mappings are
                    # already persisted rows, so the transfer references them
                    # rather than restating the concept pairs.
                    concept_mappings=[m.mapping_id for m in accepted],
                    transferred_concepts=[m.target_concept_id for m in accepted],
                    validation_results={
                        "accepted": len(accepted), "rejected": len(rejected),
                        "indeterminate": len(indeterminate),
                    },
                    effectiveness_score=mapping.validation_score,
                )
                if not await registry.create_knowledge_transfer(transfer):
                    raise RuntimeError(
                        f"Knowledge transfer {transfer.transfer_id} could not be "
                        f"stored; refusing to report an unrecorded transfer")
                # APPLIED, not merely discovered. usage_count is what separates a
                # correspondence Torin keeps relying on from one it derived once,
                # and nothing had ever incremented it.
                # ATTRIBUTABLE. A usage event names the task it was applied to,
                # which is what lets transfer evaluation later ask "did the tasks
                # this mapping touched differ from the ones it did not?" rather
                # than only "did the domain improve afterwards?". Without a task
                # the application is unattributable, so it is not recorded as a
                # use at all.
                task_id = (knowledge or {}).get("task_id")
                if task_id:
                    await registry.record_mapping_usage(
                        [m.mapping_id for m in accepted],
                        task_id=str(task_id),
                        transfer_id=transfer.transfer_id,
                        provenance={"trigger": (knowledge or {}).get("trigger"),
                                    "source_domain": source_domain,
                                    "target_domain": target_domain})
                else:
                    logger.info(
                        "Transfer %s applied with no task identity; usage not "
                        "recorded (it could not be attributed to an outcome)",
                        transfer.transfer_id)

            if mapping:
                # Apply the mapping to transfer knowledge
                transferred_knowledge = {
                    "source_domain": source_domain,
                    "target_domain": target_domain,
                    "original_knowledge": knowledge,
                    "transferred_knowledge": (
                        mapping.to_dict() if hasattr(mapping, "to_dict")
                        else str(mapping)
                    ),
                    # The counts are kept APART. "mapping_count" previously
                    # reported every candidate the similarity scan produced, so a
                    # transfer in which the validator accepted 2 of 10 was
                    # reported to the caller as 10 mappings -- the eight refuted
                    # ones counted as transferred knowledge.
                    "mapping_count": len(accepted),
                    "candidates_considered": len(mappings),
                    "rejected": len(rejected),
                    "indeterminate": len(indeterminate),
                    # The mapping's OWN confidence, or None. The default was
                    # 0.7, and `or 0.7` additionally rewrote a genuine 0.0 --
                    # so a mapping the validator had no confidence in was
                    # reported at 0.7, the same figure as one that was never
                    # measured.
                    "confidence": (float(mapping.confidence)
                                   if getattr(mapping, "confidence", None) is not None
                                   else None),
                    "success": True
                }

                self.domain_learning_stats["transfer_learning_successes"] += 1
                self.system_metrics["cross_domain_insights"] += 1

                logger.info(f"Transfer learning successful: {source_domain} -> {target_domain}")
                return transferred_knowledge
            else:
                # Two different negatives. "Nothing looked similar enough to
                # propose" and "things were proposed and the validator refuted
                # them" say opposite things about these two domains, and only
                # the second is evidence about their correspondence.
                if not mappings:
                    error, error_class = ("No candidate mapping proposed",
                                          "no_candidate")
                else:
                    error = (f"{len(mappings)} candidate(s) proposed, none validated "
                             f"({len(rejected)} refuted, {len(indeterminate)} unjudgeable)")
                    error_class = "no_validated_mapping"
                logger.info("Transfer learning %s -> %s: %s",
                            source_domain, target_domain, error)
                return {
                    "success": False,
                    "error": error,
                    "error_class": error_class,
                    "candidates_considered": len(mappings),
                    "rejected": len(rejected),
                    "indeterminate": len(indeterminate),
                }

        except UnknownDomain as e:
            logger.warning(f"Transfer learning on unregistered domain(s): {e}")
            return {
                "success": False,
                "error": str(e),
                "error_class": "unknown_domain",
                "unregistered_domains": e.missing,
            }
        except Exception as e:
            # A defect here must not come back as "no mapping found" -- that is
            # exactly how the missing find_cross_domain_mapping() stayed hidden.
            raise_if_structural(e, "UnifiedLearningSystem.transfer_learning_across_domains")
            logger.error(f"Error in transfer learning: {e}", exc_info=True)
            return {"success": False, "error": str(e), "error_class": "operational"}

    async def learn_with_domain_context(self, example: LearningExample,
                                        domain: str) -> LearningResult:
        """Learn from example with domain-specific context"""
        try:
            logger.info(f"Domain-specific learning in domain: {domain}")

            registry = self.domain_registry
            if registry is None:
                from core.domain.domain_registry import get_domain_registry
                registry = self.domain_registry = get_domain_registry()
            if not registry.initialized:
                await registry.initialize()

            # RESOLVE the reference. Do not create a domain from it.
            #
            # This did `get_domain(domain)` and, on a miss, REGISTERED a new
            # empty Domain named after the reference. The caller's references
            # are CATEGORIES ('scientific', 'technical') produced by
            # _infer_domain_from_task, so what it created were empty
            # category-level domains -- which is where the 15 concept-less
            # domains beside the 18 real fields came from. Each one then made
            # the category look registered and populated-by-zero, so every
            # lookup through it returned a well-formed empty answer.
            #
            # A domain is something Torin has learned, not something minted on
            # first mention. The registry already resolves a category to the
            # fields beneath it; the reference is answered, never invented.
            resolved = registry.resolve_domain_reference(domain, require_concepts=True)
            if not resolved:
                logger.info(
                    "Domain-specific learning skipped: %r holds no learned concepts",
                    domain)
                return LearningResult(
                    result_id=str(uuid.uuid4()),
                    success=False,
                    learned_knowledge={},
                    error=f"domain reference {domain!r} holds no learned concepts",
                    metadata={"domain": domain, "domain_specific": True,
                              # Both facts present on EVERY path. A caller that
                              # has to check which keys exist before reading
                              # them is back to guessing what a result means.
                              "learning_recorded": False,
                              "strategy_earned_credit": False,
                              "error_class": "domain_empty"},
                )

            # The FIELD is what carries concepts and what the transfer path
            # reasons over. The caller's original reference is kept in metadata
            # so a category-level question stays distinguishable from a
            # field-level one.
            field = resolved[0].domain_id
            if field != domain:
                logger.info("Domain reference %r resolved to field %s", domain, field)

            # Perform learning using unified learning system.
            #
            # A fourth defect in the same method: `{**example}` was spreading a
            # LearningExample dataclass, which is not a mapping ->
            # TypeError: 'LearningExample' object is not a mapping. TypeError is
            # in STRUCTURAL_DEFECT_TYPES, so raise_if_structural below re-raises
            # it and even the except-branch LearningResult never returns.
            # learn_from_example takes Dict[str, Any]; convert at the boundary.
            # Resolved before the payload so an unknown task type simply
            # leaves the family unstated rather than raising here.
            _stated_family = task_family_for_task_type(example.task_type)

            payload = {
                **asdict(example),
                'domain': field,
                'domain_specific': True,
                # STATED, not defaulted. Without a 'type' this fell to
                # SUPERVISED -> CLASSIFICATION, so every task outcome was scored
                # against the classification arms by omission rather than by any
                # decision. A completed task is experience accumulated over
                # time, which is what CONTINUAL names, and the existing table at
                # :48 maps it to SEQUENCE. This lane earned no credit at all
                # before the outcome was readable, so nothing it built up is
                # being moved.
                'type': LearningType.CONTINUAL,
                # THE FAMILY THE WORK ACTUALLY BELONGS TO.
                #
                # Without this the family came from LearningType.CONTINUAL ->
                # SEQUENCE, so a completed security_remediation was scored
                # against the sequence arms. The example already carries the
                # coordinator's task type; TASK_TYPE_TO_FAMILY is the authority
                # on what family that is, and three task types (execution,
                # planning, security_remediation) are CONTROL work -- the
                # family whose arms choose between remediation APPROACHES and
                # which had never once been selected.
                #
                # Omitted when the task type is absent or unknown, so the
                # CONTINUAL mapping still applies rather than a guess.
                **({'task_family': _stated_family} if _stated_family else {}),
                # Lifted to the top level because the transfer path reads it
                # there. Without the task identity a mapping application cannot
                # be tied to the outcome it may have influenced, which is the
                # difference between counting uses and attributing them.
                'task_id': (example.inputs or {}).get('task_id'),
            }

            # THE OUTCOME THE PRODUCER RECORDED, LIFTED TO WHERE IT IS READ.
            #
            # TaskOutcomeRecord states the result as targets['outcome'] --
            # "success" or "failure" -- and its confidence as quality_score.
            # asdict() puts both one level down from where learn_from_example
            # looks (it reads top-level 'success' and 'accuracy'), so every task
            # outcome arrived stating nothing about how it went and was
            # correctly classified INSUFFICIENT_EVIDENCE. 269 consecutive
            # outcomes were recorded that way, 4 of the 5 underlying tasks
            # having actually succeeded: the strategy could never earn or lose
            # credit from the one signal this tier exists to deliver.
            #
            # Only an outcome that is actually stated is lifted. An example that
            # says nothing about how it went stays INSUFFICIENT_EVIDENCE, which
            # is the honest reading and the case the test at
            # test_domain_expansion_chain.py pins as (recorded=True,
            # credit=False).
            outcome = (example.targets or {}).get('outcome')
            if isinstance(outcome, str) and outcome.lower() in ('success', 'failure'):
                succeeded = outcome.lower() == 'success'
                quality = float(example.quality_score or 0.0)
                payload['success'] = succeeded
                # performance_score measures HOW WELL the work went, not how
                # sure we are that it went badly -- so a confident failure
                # scores 0.0, not 0.9.
                payload['accuracy'] = quality if succeeded else 0.0
                payload['confidence'] = quality

            learning_result = await self.learn_from_example(payload)

            # LEARNED and EARNED CREDIT are different facts.
            #
            # learn_from_example's 'success' is the CREDIT signal: whether the
            # selected strategy earned credit for this example. An example that
            # states no outcome is INSUFFICIENT_EVIDENCE, not a failure. This
            # returned that flag as its own `success`, so an example that was
            # learned from perfectly well -- including one whose cross-domain
            # transfer ran and produced validated mappings -- came back as
            # success=False with no error and no error_class. A caller cannot
            # tell that from a real failure, and the only honest reading of a
            # bare False is "it did not work".
            #
            # `error` present means learn_from_example actually failed. Its
            # absence means the example WAS learned from, and the credit
            # question is reported separately.
            failure = learning_result.get('error')
            recorded = failure is None
            earned_credit = bool(learning_result.get('success', False))

            if recorded:
                self.domain_learning_stats["domain_specific_learning"] += 1
                logger.info(
                    "Domain-specific learning recorded for %s (strategy credit: %s)",
                    field, "earned" if earned_credit else "not earned")

            metrics = learning_result.get('metrics', {}) or {}
            return LearningResult(
                result_id=learning_result.get('memory_id') or str(uuid.uuid4()),
                success=recorded,
                learned_knowledge=learning_result.get('learned_knowledge', {}) or {},
                accuracy=float(metrics.get('accuracy', 0.0) or 0.0),
                confidence=float(metrics.get('confidence', 0.0) or 0.0),
                error=failure,
                metadata={
                    "domain": field,
                    "domain_reference": domain,
                    "domain_specific": True,
                    # The two facts, named separately and always both present.
                    # `success` IS learning_recorded -- stated here so the
                    # relationship is checkable rather than conventional. The
                    # state the old interface could not represent at all is
                    # (recorded=True, credit=False): an example learned from
                    # whose strategy earned no credit. That is the normal case
                    # for an outcome carrying no accuracy signal, and it used to
                    # arrive at every caller as a bare success=False.
                    "learning_recorded": recorded,
                    "strategy_earned_credit": earned_credit,
                    # strategy_earned_credit=False meant two opposite things:
                    # "the posterior did not move because nothing could be
                    # concluded" and "the posterior moved, recording a failure".
                    # Those are the difference between no evidence and negative
                    # evidence, so the class and the credit decision are stated
                    # rather than left to be inferred from a single False.
                    "outcome_class": learning_result.get('outcome_class'),
                    "credit_applied": learning_result.get('credit_applied', False),
                    "cross_domain": learning_result.get('cross_domain'),
                    "metrics": metrics,
                    **({} if recorded else {"error_class": "learn_from_example_failed"}),
                },
            )

        except Exception as e:
            raise_if_structural(e, "UnifiedLearningSystem.learn_with_domain_context")
            logger.error(f"Error in domain-specific learning: {e}", exc_info=True)
            return LearningResult(
                result_id=str(uuid.uuid4()),
                success=False,
                learned_knowledge={},
                error=str(e),
                metadata={"domain": domain, "domain_specific": True,
                          "learning_recorded": False,
                          "strategy_earned_credit": False,
                          "error_class": type(e).__name__},
            )

    def get_domain_learning_stats(self) -> Dict[str, Any]:
        """Get statistics about domain knowledge usage in learning"""
        return {
            "cross_domain_transfers": self.domain_learning_stats["cross_domain_transfers"],
            "domain_specific_learning": self.domain_learning_stats["domain_specific_learning"],
            "transfer_learning_successes": self.domain_learning_stats["transfer_learning_successes"],
            "total_cross_domain_insights": self.system_metrics["cross_domain_insights"],
            # Meaningful only now that attempts and successes are counted
            # separately. None with no attempts: a rate over zero tries is
            # undefined, and 0.0 would read as "every transfer failed".
            "transfer_success_rate": (
                self.domain_learning_stats["transfer_learning_successes"]
                / self.domain_learning_stats["cross_domain_transfers"]
                if self.domain_learning_stats["cross_domain_transfers"] else None),
        }


# Singleton instance
_unified_learning_system = None


def get_unified_learning_system() -> UnifiedLearningSystem:
    """Get global unified learning system instance (singleton)"""
    global _unified_learning_system
    if _unified_learning_system is None:
        _unified_learning_system = UnifiedLearningSystem()
    return _unified_learning_system
