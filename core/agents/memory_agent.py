#!/usr/bin/env python3
"""
Memory Agent
============

Primary memory coordination interface for TorinAI AGI system.
Coordinates hot tier (PostgreSQL), cold tier, and semantic search (embeddings).

Architecture:
- Hot Tier: PostgreSQL storage (0-60 days, fast access) - memory_hot schema
- Cold Tier: PostgreSQL storage (60+ days, archival) - memory_cold schema
- Embeddings: Semantic similarity search with pgvector (all-MiniLM-L6-v2)

Features:
- CRUD operations (create, read, update, delete)
- Semantic and keyword-based search
- Automatic tier migration (hot → cold after 60 days)
- Governance integration (capability tokens for deletes)
- Protected parameter modifications (fail-closed security)

Integration:
- Single entry point exported from core/memory/__init__.py
- Protected against autonomous self-modification
- Constitutional constraints enforcement

Author: TorinAI System
Version: 8.0
"""

import asyncio
import logging

from core.capability import raise_if_structural
import uuid
from typing import Dict, Any, List, Optional, Sequence, Set, Tuple, Union
from datetime import datetime, timedelta

# Memory storage implementations
from core.memory.storage.postgres_storage import PostgresStorage
from core.memory.utils.embedding_service import (
    EmbeddingService,
    get_embedding_service
)
from core.memory.utils.interfaces import (
    MemoryItem,
    MemoryType,
    MemoryQuery,
    MemorySearchResult,
    MemoryOperation
)
from core.memory.utils.memory_worthiness import MemoryWorthinessMetadata

# Performance profiling
from core.learning.performance_profiler import profile_performance

from core.learning.learning_interfaces import IMemoryConsolidation

logger = logging.getLogger(__name__)


class MemoryAgent(IMemoryConsolidation):
    """
    Memory Agent - Primary Memory Coordination Interface

    Coordinates hot tier (PostgreSQL 0-60 days), cold tier (PostgreSQL 60+ days),
    and semantic search capabilities for TorinAI memory system.

    Architecture:
        - PostgreSQL Hot: Fast hot tier storage for recent memories (memory_hot schema)
        - PostgreSQL Cold: Cold tier archival for historical memories (memory_cold schema)
        - Embeddings: Semantic similarity search across tiers with pgvector

    Governance:
        - Protected delete operations require capability tokens
        - Parameter modifications are governance-protected
        - Autonomous self-modification is blocked
    """

    def __init__(self):
        """
        Initialize Memory Agent

        Sets up storage backends but does not connect (call initialize())
        """
        # PostgreSQL storage (handles both hot and cold tiers)
        self.postgres_storage: Optional[PostgresStorage] = None  # Hot+Cold tier (PostgreSQL both)

        # Embedding service (sentence transformers)
        self.embedding_service: Optional[EmbeddingService] = None  # all-MiniLM-L6-v2
        self.embedding_dim: int = 384  # Embedding dimension

        # Memory cache (optional in-memory cache)
        self.memory_cache: Dict[str, MemoryItem] = {}  # memory_id → MemoryItem
        self.cache_enabled: bool = True  # Enable caching

        # Agent state
        self.initialized: bool = False

        # Autonomous background loops (persistent cognition)
        self.maintenance_loop_active: bool = False
        self.abstraction_loop_active: bool = False
        self.reflection_loop_active: bool = False
        self.abstraction_pipeline = None  # Will be initialized with hierarchical abstraction
        self.bayesian_beliefs = None  # Will be initialized with belief system

        # Admission control for abstraction. Without this, an idle-loop caller
        # would recluster the same memories every cycle and re-derive schemas
        # it already has.
        self.abstraction_state: Dict[str, Any] = {
            'last_abstraction_run':      None,   # datetime of last completed run
            'last_processed_created_at': None,   # newest memory consumed so far
            'memories_since_abstraction': 0,     # observed at last admission check
            'abstraction_backlog':       0,      # eligible but unprocessed
            'schemas_formed_last_run':   0,
            'runs':                      0,
            'last_skip_reason':          None,
        }
        self._abstraction_running: bool = False
        #: EVENT-TRIGGER state for abstraction. Abstraction is no longer a 4h
        #: poll — it fires when enough NEW episodic memories have accumulated.
        #: The write path only counts and (past threshold) schedules a
        #: background job on the queue authority; it never reasons inline.
        self._new_episodic_since_abstraction: int = 0
        self._abstraction_trigger_scheduled: bool = False

        # Performance metrics
        self.metrics = {
            "memories_stored": 0,
            "memories_retrieved": 0,
            "cache_hits": 0,
            "tier_migrations": 0,
            "queries_executed": 0,
            "consolidations_run": 0,
            "abstractions_formed": 0,
            "beliefs_updated": 0,
            "maintenance_cycles": 0
        }

        # Non-blocking write queue
        # Callers use enqueue_memory() to fire-and-forget; the background
        # worker drains it by calling store_memory() sequentially.
        # _pending_memories holds items that are queued but not yet in
        # postgres — the injector checks here so recent memories are
        # visible to retrieval immediately without waiting for the write.
        self._write_queue: asyncio.Queue = asyncio.Queue()
        self._pending_memories: dict = {}  # memory_id → {content, tags, importance, ...}
        self._queue_worker_task: Optional[asyncio.Task] = None

    async def initialize(self) -> bool:
        """
        Initialize memory agent and all storage backends

        Connects to PostgreSQL hot tier, PostgreSQL cold tier, and loads embedding model.

        Returns:
            True if all components initialized successfully, False otherwise
        """
        if self.initialized:
            return True

        # Shadow mode suppresses background cognitive loops (see TORIN_SHADOW_MODE
        # check further below) but memory storage is fully operational — PostgreSQL
        # initialises normally so memories are persisted during shadow runs.
        try:
            logger.info("Initializing MemoryAgent...")

            # Initialize PostgreSQL storage (hot and cold tiers)
            try:
                self.postgres_storage = PostgresStorage()
                await self.postgres_storage.initialize()
                logger.info("✓ PostgreSQL hot tier initialized (0-60 days)")
                logger.info("✓ PostgreSQL cold tier available (60+ days)")
            except Exception:
                logger.error("Failed to initialize PostgreSQL storage")

            # Initialize embedding service (all-MiniLM-L6-v2)
            try:
                self.embedding_service = get_embedding_service()
                if self.embedding_service.initialize():
                    logger.info("✓ Embedding service initialized (384-dim)")
                else:
                    logger.error("Embedding service initialization failed")
            except Exception as e:
                logger.error(f"Failed to initialize embedding service: {e}")

            # NO separate query agent. MemoryAgent IS the query authority --
            # `retrieve` (multi-strategy recall), `search_memories`, and
            # `query_by_tags` are its surface. The old `PostgresQueryAgent` was
            # assigned to `self.postgres_query_agent` here and never read again,
            # a dead duplicate over the same PostgresStorage; it has been deleted.

            # Verify PostgreSQL storage is available
            if not self.postgres_storage:
                logger.error("PostgreSQL storage not available - MemoryAgent cannot function")
                return False

            # Abstraction + belief are REASONING — the reasoning authority owns
            # and constructs them now (NeuralSymbolicBridge.initialize), not the
            # memory agent. The memory agent no longer builds its own pipeline or
            # belief graph (the duplicate-authority defect this used to be). When
            # it has new episodic memories worth abstracting, it ASKS the
            # authority (see form_abstractions_if_due -> bridge.abstract_over_memories
            # and reflect_on_beliefs -> bridge.reflect). Left None here; a lazy
            # `_reasoning_authority()` reaches the bridge at call time (the bridge
            # initializes after the memory agent, so it cannot be fetched here).
            self.bayesian_beliefs = None
            self.abstraction_pipeline = None

            self.initialized = True
            logger.info("MemoryAgent initialized successfully")

            # Shadow mode: suppress background cognitive loops and write queue.
            # These are only needed for persistent long-running cognition, not
            # for single-task diagnostic runs.
            import os as _ma_os
            if _ma_os.environ.get("TORIN_SHADOW_MODE"):
                logger.info("⚡ Shadow mode: cognitive background loops suppressed (TORIN_SHADOW_MODE=1)")
            else:
                # Start autonomous background loops (persistent cognition)
                await self.start_memory_loops()
                logger.info("✓ Autonomous cognitive loops started")

                # Start non-blocking write queue worker
                self._queue_worker_task = asyncio.create_task(
                    self._write_queue_worker(),
                    name="memory_write_queue_worker"
                )
                logger.info("✓ Memory write queue worker started")

            return True

        except Exception as e:
            logger.error(f"MemoryAgent initialization failed: {e}")
            return False

    # ================================================================================================
    # MEMORY STORAGE (Hot Tier)
    # ================================================================================================

    def enqueue_memory(
        self,
        content: str,
        memory_type=None,
        importance_score: float = 0.5,
        confidence_score: float = 1.0,
        tags=None,
        source_context=None,
        **kwargs
    ) -> str:
        """
        Non-blocking fire-and-forget memory store.

        Puts the memory onto the write queue and returns immediately.
        The memory is also placed in _pending_memories so the injector
        can find it before it lands in postgres.

        Returns a provisional memory_id (starts with 'pending_').
        """
        import uuid
        pending_id = f"pending_{uuid.uuid4().hex}"
        entry = {
            "pending_id": pending_id,
            "content": content,
            "memory_type": memory_type,
            "importance_score": importance_score,
            "confidence_score": confidence_score,
            "tags": tags or [],
            "source_context": source_context or {},
            "kwargs": kwargs,
        }
        self._pending_memories[pending_id] = entry
        # Put onto the queue (non-blocking — Queue has no size limit by default)
        try:
            self._write_queue.put_nowait(entry)
        except Exception:
            # If event loop isn't running yet, drop gracefully — caller used wrong method
            del self._pending_memories[pending_id]
        return pending_id

    async def _write_queue_worker(self):
        """Background task: drains the write queue one item at a time."""
        logger.info("Memory write queue worker running")
        while True:
            try:
                entry = await self._write_queue.get()
                pending_id = entry["pending_id"]
                try:
                    await self.store_memory(
                        content=entry["content"],
                        memory_type=entry["memory_type"],
                        importance_score=entry["importance_score"],
                        confidence_score=entry["confidence_score"],
                        tags=entry["tags"],
                        source_context=entry["source_context"],
                        **entry.get("kwargs", {}),
                    )
                except Exception as e:
                    logger.error(f"Write queue worker: store_memory failed: {e}")
                finally:
                    # Remove from pending regardless of success
                    self._pending_memories.pop(pending_id, None)
                    self._write_queue.task_done()
            except asyncio.CancelledError:
                logger.info("Memory write queue worker cancelled")
                break
            except Exception as e:
                logger.error(f"Write queue worker unexpected error: {e}")
                await asyncio.sleep(1)

    #: Reasoning answers arrive with a status marker in front of the claim
    #: ("Proved: X is Y"). The marker is a fact about the reasoning, not part of
    #: what is claimed, so it is stripped before the claim is read.
    _STATUS_PREFIXES = (
        "proved:", "disproved:", "refuted:", "verified:", "concluded:",
        "not entailed by the premises:", "not entailed:", "unsettled:",
        "answer:",
    )

    def _readable_claim(self, content, source_context):
        """The substrate-readable CLAIM a memory asserts, or ``(None, None)``.

        A memory is recalled as a PREMISE and read as ONE sentence, so it is
        useful to the substrate's reasoning only when its recall-facing form is a
        clean statement. This reads that form at WRITE time -- from the recorded
        conclusion when there is one, else the content -- strips any
        reasoning-status prefix, and keeps it only if it READS as a claim (a
        copula or negator the reader can place). A prose episode, a bare atom, a
        measurement ("link strength 1.00") has no readable claim and is left
        without one rather than dressed up as one: a fabricated premise is worse
        than an absent one, because it is recalled as knowledge.

        Returns the clean claim and its ``ClaimShape`` (polarity + tense), the
        distinction the embedding vector provably cannot recover, so it can be
        stored beside the memory instead of guessed at recall.

        The GATE is the substrate's own reader -- the same reading the reasoner
        formalises context with -- not the polarity reader: whether a memory can
        serve as a premise is exactly whether that reader can turn it into a
        fact. The polarity reader only supplies the tags; using it to decide
        READABILITY both admitted prose that merely contained a copula and
        refused a subject-verb-object claim that carried no copula at all.
        """
        from core.semantics.claim_shape import read_claim
        from core.semantics.sentence_reader import SentenceReader

        candidate = ""
        if isinstance(source_context, dict):
            candidate = str(source_context.get("conclusion") or "").strip()
        if not candidate:
            candidate = str(content or "").strip()

        low = candidate.lower()
        for prefix in self._STATUS_PREFIXES:
            if low.startswith(prefix):
                candidate = candidate[len(prefix):].strip()
                break

        # A claim is ONE sentence. An episode written for a reader -- several
        # lines, a query and an answer -- is not one, and is not made one by
        # containing a copula somewhere inside it.
        if not candidate or "\n" in candidate or len(candidate) > 200:
            return None, None

        # The reader distinguishes a STATEMENT (a copula, or a subject-verb-object
        # with a verb it knows) from a job or a fragment. A measurement like
        # "link strength 1.00" parses as loose SVO but is not a statement, and
        # this is what refuses it.
        try:
            if SentenceReader()._parse_statement(candidate) is None:
                return None, None
        except Exception:
            return None, None

        return candidate, read_claim(candidate)

    @profile_performance("memory_agent", "store_memory")
    async def store_memory(
        self,
        content: str,
        memory_type: Optional[MemoryType] = None,
        importance_score: float = 0.5,
        confidence_score: float = 1.0,
        tags: Optional[List[str]] = None,
        source_context: Optional[Dict[str, Any]] = None,
        embedding_metadata: Optional[Dict[str, Any]] = None,
        related_memories: Optional[List[str]] = None,
        decay_rate: Optional[float] = None,
        access_count: int = 0,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        reasoning_trace: Optional[List[str]] = None,
        thinking_state: Optional[Dict[str, Any]] = None,
        system_state: Optional[Dict[str, Any]] = None,
        decision_factors: Optional[Dict[str, Any]] = None,
        emotional_context: Optional[Dict[str, Any]] = None
    ) -> Tuple[bool, Optional[str]]:
        """
        Store memory to hot tier (PostgreSQL) with intelligent filtering

        Memory Agent analyzes raw inputs and generates MemoryWorthinessMetadata.
        Calling systems should NOT pre-generate metadata - that's Memory Agent's job.

        Args:
            content: Memory content (text) - REQUIRED
            memory_type: Type of memory (EPISODIC, SEMANTIC, etc.) - Optional, will be inferred
            importance_score: Importance score (0.0-1.0)
            confidence_score: Confidence in memory accuracy (0.0-1.0)
            tags: Optional tags for categorization
            source_context: Raw metadata about memory source (system analyzes this)
            embedding_metadata: Optional metadata for embedding
            related_memories: Optional list of related memory IDs
            decay_rate: Optional custom decay rate
            access_count: Initial access count
            session_id: Optional session identifier
            user_id: Optional user identifier
            reasoning_trace: Optional chain of thought steps (list of reasoning steps)
            thinking_state: Optional thinking state metadata (DEPRECATED - metadata generated here)
            system_state: Optional system state (CPU, memory, services, dependencies) at time of memory
            decision_factors: Optional decision factors that influenced this memory
            emotional_context: Optional emotional/sentiment context

        Returns:
            Tuple of (success: bool, memory_id: Optional[str])
        """
        logger.debug(f"\n[MEMORY_AGENT.STORE_MEMORY] Called with:")
        logger.debug(f"  Content length: {len(content)} chars")
        logger.debug(f"  Memory type: {memory_type}")
        logger.debug(f"  Tags: {tags}")
        logger.debug(f"  Importance: {importance_score}")
        logger.debug(f"  Confidence: {confidence_score}")
        logger.debug(f"  Initialized: {self.initialized}")

        if not self.initialized:
            logger.debug(f"[MEMORY_AGENT.STORE_MEMORY] Initializing memory agent...")
            # The result is CHECKED. Discarding it meant a failed initialize was
            # followed by the work it was meant to enable, and the real failure
            # resurfaced later disguised as something else.
            if await self.initialize() is False:
                raise RuntimeError(
                    type(self).__name__ + ' could not initialize; refusing to '
                    'continue as though it had')
            logger.debug(f"[MEMORY_AGENT.STORE_MEMORY] Initialization complete")

        # ========== STEP 1: GENERATE OR EXTRACT METADATA ==========
        logger.debug(f"[MEMORY_AGENT.STORE_MEMORY] STEP 1: Generate/extract metadata")
        worthiness_metadata = None

        # Check if upstream system pre-generated metadata (DEPRECATED path)
        if thinking_state and "worthiness_metadata" in thinking_state:
            try:
                from core.memory.utils.memory_worthiness import MemoryWorthinessMetadata

                # Deserialize metadata from dict
                metadata_dict = thinking_state["worthiness_metadata"]
                worthiness_metadata = MemoryWorthinessMetadata.from_dict(metadata_dict)

                logger.debug(f"Extracted worthiness metadata from thinking_state (source: {worthiness_metadata.source_system})")

            except Exception as e:
                logger.warning(f"Failed to extract worthiness metadata: {e}")
                worthiness_metadata = None

        # PREFERRED PATH: Generate metadata from raw inputs
        if worthiness_metadata is None:
            try:
                logger.debug(f"[MEMORY_AGENT.STORE_MEMORY] Generating worthiness metadata...")
                worthiness_metadata = await self._generate_worthiness_metadata(
                    content=content,
                    confidence_score=confidence_score,
                    tags=tags,
                    source_context=source_context,
                    reasoning_trace=reasoning_trace,
                    importance_score=importance_score
                )
                logger.debug(f"Generated worthiness metadata from raw inputs (source: {worthiness_metadata.source_system})")
                logger.debug(f"[MEMORY_AGENT.STORE_MEMORY] Metadata generated: source={worthiness_metadata.source_system}")

            except Exception as e:
                logger.error(f"Failed to generate worthiness metadata: {e}")
                logger.error(f"[MEMORY_AGENT.STORE_MEMORY] ✗ Metadata generation failed: {e}")
                # Fail open - allow storage without metadata
                worthiness_metadata = None

        # ========== STEP 2: EVALUATE FILTERING DECISION ==========
        memory_admission = None
        logger.debug(f"[MEMORY_AGENT.STORE_MEMORY] STEP 2: Evaluating filter decision...")
        logger.debug(f"  Metadata available: {worthiness_metadata is not None}")

        # Observations are measurements, not insights. The worthiness filter
        # asks "is this novel / deeply reasoned / cross-domain enough to keep?"
        # — the wrong question for a data point. Applied to task outcomes it
        # produced survivorship bias: failures (importance 0.9 → high
        # consequence) were retained while successes (0.7) were discarded, so
        # the measured success_rate could never rise above near-zero no matter
        # how the system actually performed.
        # Exemption is decided by the filter, which owns retention policy. This
        # tested only for an observation raw_event; the same argument applies to
        # every event whose value is that it happened -- task outcomes, safety
        # events, governance decisions, learning updates, mapping verdicts and
        # critical failures are records other subsystems read back, not
        # candidates to be judged for novelty.
        from core.memory.utils.memory_filter import get_memory_filter as _get_filter
        _raw_event_early = (thinking_state or {}).get("raw_event")
        _exemption = _get_filter().exemption_for(tags=tags, raw_event=_raw_event_early)
        _is_observation_early = _exemption is not None

        if _is_observation_early:
            logger.debug(
                "Bypassing worthiness filter — %s is a record, not a candidate "
                "for retention", _exemption,
            )
            # An exempt record still has an admission reason; leaving it blank
            # would make "kept because it is a record" indistinguishable from
            # "kept without anyone deciding".
            memory_admission = {
                "filter_decision": {
                    "rule_matched": "event_class_exemption",
                    "decision_type": "exempt",
                    "rationale": _exemption,
                    "confidence": 1.0,
                },
                "admitted_at": datetime.now().isoformat(),
                "admitted_by": "memory_filter.exemption_for",
            }
        elif worthiness_metadata is not None:
            try:
                from core.memory.utils.memory_filter import get_memory_filter

                memory_filter = get_memory_filter()
                logger.debug(f"[MEMORY_AGENT.STORE_MEMORY] Memory filter: {type(memory_filter)}")

                # Evaluate with optional reasoning trace for calibration
                decision = memory_filter.evaluate(
                    metadata=worthiness_metadata,
                    reasoning_trace=reasoning_trace
                )
                logger.debug(f"[MEMORY_AGENT.STORE_MEMORY] Filter decision complete")

                # ========== STEP 3: HANDLE REJECTION ==========
                logger.debug(f"[MEMORY_AGENT.STORE_MEMORY] STEP 3: Filter decision - should_store={decision.should_store}")
                if not decision.should_store:
                    logger.info(
                        f"✗ Memory REJECTED by filter: "
                        f"rule={decision.rule_matched}, "
                        f"rationale={decision.rationale}, "
                        f"source={worthiness_metadata.source_system}"
                    )

                    # A rejection is the worthiness filter doing its job, not a
                    # failure. Logged at debug so a normally-operating system
                    # does not fill the error log with correct decisions.
                    logger.debug("[MEMORY_AGENT.STORE_MEMORY] declined by filter:")
                    logger.debug(f"  Rule: {decision.rule_matched}")
                    logger.debug(f"  Rationale: {decision.rationale}")
                    logger.debug(f"  Source: {worthiness_metadata.source_system}")

                    # Track rejection metrics
                    if not hasattr(self, 'filter_metrics'):
                        self.filter_metrics = {'rejections': 0, 'accepts': 0}
                    self.filter_metrics['rejections'] += 1

                    # Return early - do not store
                    return False, None

                # ========== STEP 4: HANDLE ACCEPTANCE ==========
                logger.debug(f"[MEMORY_AGENT.STORE_MEMORY] STEP 4: ✓ ACCEPTED by filter")
                logger.info(
                    f"✓ Memory ACCEPTED by filter: "
                    f"rule={decision.rule_matched}, "
                    f"decision_type={decision.decision_type}, "
                    f"rationale={decision.rationale}"
                )

                # Track acceptance metrics
                if not hasattr(self, 'filter_metrics'):
                    self.filter_metrics = {'rejections': 0, 'accepts': 0}
                self.filter_metrics['accepts'] += 1

                # Freeze metadata to enforce immutability
                worthiness_metadata.freeze()

                # ADMISSION IS NOT COGNITION. `thinking_state` is meant to hold
                # the substrate's state AT THE TIME of the episode; the filter
                # decision and worthiness metadata are computed by the memory
                # subsystem AFTERWARDS, about whether to keep it. Writing them
                # there made every memory assert as contemporaneous a judgement
                # that did not exist yet -- and it is why all 429 rows carry a
                # populated thinking_state that contains no thinking.
                #
                # Written to its own field now. Still mirrored into
                # thinking_state during the migration so existing readers (the
                # deprecated pre-generated-metadata path at the top of this
                # method, and anything reading filter_decision) keep working.
                memory_admission = {
                    "worthiness_metadata": worthiness_metadata.to_dict(),
                    "filter_decision": {
                        "rule_matched": decision.rule_matched,
                        "decision_type": decision.decision_type,
                        "rationale": decision.rationale,
                        "confidence": decision.confidence,
                    },
                    "admitted_at": datetime.now().isoformat(),
                    "admitted_by": "memory_filter",
                }

                if thinking_state is None:
                    thinking_state = {}
                thinking_state["worthiness_metadata"] = memory_admission["worthiness_metadata"]
                thinking_state["filter_decision"] = memory_admission["filter_decision"]

            except Exception as e:
                logger.error(f"Memory filtering error: {e}")
                # On filter error, default to storing (fail-open for now)
                logger.warning("Defaulting to STORE on filter error (fail-open)")
        else:
            # No metadata provided - allow storage but log warning
            logger.warning(
                f"No worthiness metadata provided - storing without filtering. "
                f"Source systems should generate upstream metadata."
            )

        # CONTEMPORANEOUS EPISTEMIC STATE.
        #
        # With admission moved to memory_admission, thinking_state is free to
        # mean what it says: the substrate's state AT THE TIME of the episode.
        # belief_state is measured from the live belief graph -- the same
        # singleton epistemic_engine restores -- so it is a reading, not a
        # description. raw_event, task_state and goal_state stay caller-supplied:
        # only the caller knows them, and inventing them here would be the same
        # error as a constant decision rationale.
        # Read the live belief graph via its singleton (the reasoning authority
        # owns it; the memory agent no longer constructs it, but this is a
        # reading, not driving).
        from core.reasoning.bayesian_uncertainty import get_bayesian_uncertainty
        _beliefs = get_bayesian_uncertainty()
        if _beliefs is not None:
            try:
                _bstats = _beliefs.get_statistics()
                if thinking_state is None:
                    thinking_state = {}
                thinking_state.setdefault("belief_state", {
                    "active_beliefs": _bstats.get("active_beliefs"),
                    "known_unknowns": _bstats.get("known_unknowns"),
                    "high_value_unknowns": _bstats.get("high_value_unknowns"),
                    "overconfidence_rate": round(float(_bstats.get("overconfidence_rate", 0.0)), 4),
                    "calibrated_domains": _bstats.get("calibrated_domains"),
                    "captured_at": datetime.now().isoformat(),
                })
            except Exception as e:
                logger.warning(f"Belief state snapshot failed: {type(e).__name__}: {e}")

        # CONTEMPORANEOUS APPRAISAL.
        #
        # `emotional_context` has been carrying {"autonomous_confidence": <the
        # memory's importance score>} -- one number, under a name implying
        # something it is not, on 96% of memories. Meanwhile AppraisalSystem is
        # live and producing valence, activation, confidence,
        # epistemic_opportunity, progress, controllability, competence,
        # goal_congruence, agency, risk and the action pressures, updated by the
        # executor after every task.
        #
        # Read here, not described: if no task has appraised yet, current_state
        # is None and this stays None rather than inventing a neutral state.
        try:
            from core.agents.autonomous.appraisal import get_appraisal_system
            _appraisal = get_appraisal_system().current_state
            if _appraisal is not None:
                appraisal_snapshot = _appraisal.to_dict()
                appraisal_snapshot["captured_at"] = datetime.now().isoformat()
            else:
                appraisal_snapshot = None
        except Exception as e:
            logger.warning(f"Appraisal snapshot failed: {type(e).__name__}: {e}")
            appraisal_snapshot = None

        # ========== STEP 5: CHECK FOR DUPLICATES ==========
        # Deduplicate KNOWLEDGE, never OBSERVATIONS.
        #
        # Two statements of the same fact are one fact. Two task failures of the
        # same kind are two failures — their multiplicity IS the signal, and it
        # is what performance history, competence calibration and meta-learning
        # count. Merging them silently destroys the measurement: rows carrying
        # merge_count=6 are six collapsed outcomes the drives can never see.
        #
        # Event records are identified structurally: the coordinator stamps
        # every one with thinking_state["raw_event"]["event"].
        # THE SAME EXEMPTION DECIDES BOTH. This tested only for a raw_event, so
        # an event identified by TAG -- a task outcome, a governance decision --
        # skipped the worthiness filter and was then deduplicated anyway: two
        # distinct successes merged into one row, which is the exact measurement
        # loss described above. Shadow-run evidence: storing a second
        # `task_outcome` returned the FIRST memory's id.
        _is_observation = _exemption is not None

        if _is_observation:
            # Logged from the exemption reason, not from _raw_event: exemption
            # can now come from a tag, in which case there is no raw_event to
            # read a name out of.
            logger.debug(
                "Skipping dedup — %s: occurrences are data, not duplicates",
                _exemption,
            )
            similar_memories = []
        else:
            similar_memories = await self._find_similar_memories(
                content=content,
                similarity_threshold=0.75,  # Lower threshold to catch more duplicates
                tags=tags,
                memory_type=memory_type
            )

        if similar_memories:
            # Found similar memory - merge instead of creating duplicate
            logger.debug(f"[MEMORY_AGENT.STORE_MEMORY] STEP 5: Found {len(similar_memories)} duplicates - MERGING")
            logger.info(
                f"Found {len(similar_memories)} similar memories (similarity >= 0.85), "
                f"merging instead of creating duplicate"
            )

            # Merge with most similar memory
            merged_memory_id = await self._merge_memory_content(
                existing_memory=similar_memories[0],
                new_content=content,
                new_metadata={
                    'importance_score': importance_score,
                    'confidence_score': confidence_score,
                    'tags': tags,
                    'source_context': source_context,
                    'reasoning_trace': reasoning_trace,
                    'thinking_state': thinking_state
                }
            )

            if merged_memory_id:
                logger.info(f"Memory merged into existing memory: {merged_memory_id}")
                logger.debug(f"[MEMORY_AGENT.STORE_MEMORY] ✓ MERGED into {merged_memory_id}")
                return True, merged_memory_id
            else:
                logger.warning("Merge failed, proceeding with storage of new memory")
                logger.warning("[MEMORY_AGENT.STORE_MEMORY] merge failed; storing as a new memory")
        else:
            logger.debug(f"[MEMORY_AGENT.STORE_MEMORY] STEP 5: No duplicates found - proceeding with new storage")

        # ========== STEP 6: PROCEED WITH STORAGE ==========
        memory_id = f"mem_{uuid.uuid4().hex}"
        logger.debug(f"[MEMORY_AGENT.STORE_MEMORY] Creating new memory with ID: {memory_id}")
        created_at = datetime.now()

        # Infer memory_type if not provided
        if memory_type is None:
            # Infer from worthiness_metadata and source_context
            memory_type = self._infer_memory_type(worthiness_metadata, source_context or {})
            logger.debug(f"Inferred memory_type as {memory_type.value}")

        # STORE THE CLAIM IN A FORM THE SUBSTRATE CAN READ.
        #
        # Every writer funnels through here, so the recall-facing claim is read
        # ONCE, at the single point content becomes a record, rather than in the
        # thirty-odd call sites that store memories. When the content asserts a
        # claim the reader can place, its clean form becomes the conclusion recall
        # hands back, and its ClaimShape (polarity/tense) is tagged so the
        # distinction the vector cannot recover is stored beside it. When it does
        # not, nothing is invented -- an episode stays an episode.
        _claim, _claim_shape = self._readable_claim(content, source_context)
        if _claim:
            source_context = dict(source_context or {})
            source_context["conclusion"] = _claim
            tags = list(tags or [])
            for _tag in _claim_shape.as_tags():
                if _tag not in tags:
                    tags.append(_tag)

        # AN ABSENT EMBEDDING IS NOT A FAILED STORE. The vector is a RETRIEVAL
        # AID, not the memory: without it the record is still stored, readable,
        # and exact-matchable; only semantic search over it waits for a backfill.
        # generate_embedding returns None on any failure, so the store proceeds
        # unvectorised rather than losing the record.
        embedding = None
        if self.embedding_service:
            embedding = self.embedding_service.generate_embedding(content)
        logger.debug(f"[EMBEDDING DEBUG] Embedding service available: {self.embedding_service is not None}")
        logger.debug(f"[EMBEDDING DEBUG] Generated embedding: {embedding is not None}, size: {len(embedding) if embedding else 0}")

        # Create MemoryItem
        memory_item = MemoryItem(
            memory_id=memory_id,
            memory_type=memory_type,
            content=content,
            importance_score=importance_score,
            confidence_score=confidence_score,
            created_at=created_at,
            last_accessed=created_at,
            access_count=access_count,
            decay_rate=decay_rate or 0.01,
            tags=tags or [],
            metadata=source_context or {},
            embeddings=embedding,  # Use 'embeddings' (plural) to match PostgreSQL storage
            embedding_metadata=embedding_metadata or {},
            related_memories=related_memories or [],
            session_id=session_id or '',
            user_id=user_id or '',
            tier='hot',  # Store to hot tier
            archived_at=None,
            deleted_at=None,
            # Chain of thought and cognitive state tracking
            reasoning_trace=reasoning_trace,
            thinking_state=thinking_state,  # Includes frozen metadata + filter decision
            system_state=system_state,  # System state at time of memory
            decision_factors=decision_factors,
            emotional_context=emotional_context,
            memory_admission=memory_admission,
            appraisal_snapshot=appraisal_snapshot
        )

        try:
            # Store to PostgreSQL hot tier
            logger.debug(f"[MEMORY_AGENT.STORE_MEMORY] STEP 6: Storing to PostgreSQL hot tier...")
            logger.debug(f"  Memory ID: {memory_id}")
            logger.debug(f"  PostgreSQL storage available: {self.postgres_storage is not None}")

            success = await self.postgres_storage.store_memory(memory_item)

            logger.debug(f"[MEMORY_AGENT.STORE_MEMORY] PostgreSQL storage result: {success}")

            if success:
                self.metrics["memories_stored"] += 1
                logger.info(f"Memory {memory_id} stored to hot tier (filtered)")
                logger.debug(f"[MEMORY_AGENT.STORE_MEMORY] ✓ SUCCESS - Memory {memory_id} stored")
                # EVENT: a new episodic memory is what abstraction feeds on.
                # Count it (and, past threshold, schedule abstraction on the
                # queue authority). Cheap — never reasons on the write path.
                if memory_type == MemoryType.EPISODIC:
                    self.note_episodic_stored()
                return True, memory_id
            else:
                logger.error(f"Failed to store memory {memory_id}")
                logger.error(f"[MEMORY_AGENT.STORE_MEMORY] ✗ FAILED - PostgreSQL returned success=False")
                return False, None

        except Exception as e:
            logger.error(f"Memory storage error: {e}")
            logger.error(f"[MEMORY_AGENT.STORE_MEMORY] ✗ EXCEPTION: {e}")
            import traceback
            traceback.print_exc()
            return False, None

    async def capture_task_outcome(
        self,
        task: Any,
        *,
        result: Optional[Dict[str, Any]] = None,
        success: bool = True,
        confidence: float = 1.0,
    ) -> Optional[str]:
        """Capture a completed task's outcome as durable memory — the SEMANTIC
        knowledge it produced and the PROCEDURAL tool-sequence it followed.

        Two distinct, retrievable artifacts, both owned by memory (the authority):
          • SEMANTIC — WHAT the task learned, found, produced, or concluded. The
            rich knowledge future tasks retrieve. Distinct from the META
            performance record the coordinator also stores.
          • PROCEDURAL — the tool SEQUENCE and which tools were effective vs
            failed, so similar tasks can replicate or avoid the approach.

        Task execution hands its outcome here; the memory agent composes and
        stores both. MODEL-FREE: the substrate's executor already produces a
        structured result (summary, key_findings, tool_results, files_created),
        so both artifacts are assembled from those fields directly — no
        compression model, no conversation transcript. Each artifact is skipped
        honestly when the result carries nothing for it, rather than storing an
        empty record. Returns the semantic memory id when one was stored, else
        the procedural id, else None.
        """
        try:
            from core.memory.utils.interfaces import MemoryType

            result = result or {}
            summary = (result.get("summary") or result.get("result_summary") or "").strip()
            key_findings = [str(f).strip() for f in (result.get("key_findings") or []) if str(f).strip()]
            files_created = [str(f) for f in (result.get("files_created") or []) if str(f).strip()]
            tool_results = result.get("tool_results") or []
            iterations = int(result.get("iterations", 0) or 0)
            duration = result.get("duration_seconds", result.get("duration", 0)) or 0

            outcome_label = "SUCCESS" if success else "FAILURE"
            task_type = getattr(getattr(task, "type", None), "value", None) or getattr(task, "task_type", None)
            task_type_str = str(task_type) if task_type else "general"
            description = str(getattr(task, "description", str(task)))
            task_id = getattr(task, "id", None)
            tid8 = str(task_id or "?")[:8]

            semantic_id: Optional[str] = None
            procedural_id: Optional[str] = None

            # ── SEMANTIC: the knowledge produced ──────────────────────────────
            # Skipped when there is nothing to know (no summary, no findings).
            if summary or key_findings:
                lines = [f"Task ({task_type_str}) [{outcome_label}]: {description[:400]}"]
                lines.append(f"Execution: {iterations} iteration(s), {duration}s, confidence {confidence:.0%}")
                if summary:
                    lines.append(f"\nSummary:\n{summary[:1000]}")
                if key_findings:
                    lines.append("\nKey findings:\n" + "\n".join(f"- {f}" for f in key_findings[:12]))
                if files_created:
                    lines.append("\nFiles produced:\n" + "\n".join(f"- {f}" for f in files_created[:12]))
                importance = min(0.6 + (0.2 if success else 0.0) + min(iterations * 0.01, 0.1), 1.0)
                tags = ["semantic", "task_knowledge", "success" if success else "failure"]
                if task_type:
                    tags.append(str(task_type).lower())
                stored, mid = await self.store_memory(
                    content="\n".join(lines),
                    memory_type=MemoryType.SEMANTIC,
                    importance_score=importance,
                    confidence_score=confidence,
                    tags=tags,
                    source_context={
                        "source": "memory_agent.capture_task_outcome",
                        "memory_class": "semantic_task_knowledge",
                        "task_id": task_id, "task_type": task_type_str,
                        "success": success, "iterations": iterations,
                        "duration_seconds": duration, "model_free": True,
                    },
                )
                if stored:
                    semantic_id = mid
                    logger.info(f"✓ Semantic task knowledge stored: task={tid8} memory_id={mid}")

            # ── PROCEDURAL: the tool sequence followed ────────────────────────
            # Skipped when no tools were used (nothing procedural to record).
            tool_names = [str(r.get("tool") or r.get("name")) for r in tool_results
                          if isinstance(r, dict) and (r.get("tool") or r.get("name"))]
            if tool_names:
                effective = [str(r.get("tool") or r.get("name")) for r in tool_results
                             if isinstance(r, dict) and r.get("success")]
                failed = [str(r.get("tool") or r.get("name")) for r in tool_results
                          if isinstance(r, dict) and r.get("success") is False]
                pcontent = (
                    f"Task [{outcome_label}]: {description[:400]}\n\n"
                    f"Tool sequence ({iterations} iteration(s), {duration}s): "
                    f"{' → '.join(tool_names)}\n"
                )
                if effective:
                    pcontent += f"Effective tools: {', '.join(dict.fromkeys(effective))}\n"
                if failed:
                    pcontent += f"Failed tools: {', '.join(dict.fromkeys(failed))}\n"
                if summary:
                    pcontent += f"\nOutcome: {summary[:300]}"
                pimportance = min(0.5 + (0.3 if success else 0.1) + min(len(tool_names) * 0.02, 0.2), 1.0)
                ptags = ["procedural", "task_execution", outcome_label.lower()]
                if task_type:
                    ptags.append(str(task_type).lower())
                pstored, pmid = await self.store_memory(
                    content=pcontent,
                    memory_type=MemoryType.PROCEDURAL,
                    importance_score=pimportance,
                    confidence_score=confidence,
                    tags=ptags,
                    source_context={
                        "source": "memory_agent.capture_task_outcome",
                        "memory_class": "procedural_task_execution",
                        "task_id": task_id, "task_type": task_type_str,
                        "success": success, "iterations": iterations,
                        "tools_used": list(dict.fromkeys(tool_names)), "model_free": True,
                    },
                )
                if pstored:
                    procedural_id = pmid
                    logger.debug(f"Procedural task memory stored: task={tid8} memory_id={pmid}")

            return semantic_id or procedural_id

        except Exception as e:
            logger.error(f"capture_task_outcome failed: {type(e).__name__}: {e}")
            return None

    async def store_batch(self, memories: List[MemoryItem]) -> Tuple[bool, int]:
        """
        Store multiple memories in batch (optimized)

        Generates embeddings in batch for efficiency.

        Returns:
            Tuple of (success, count_stored)
        """
        if not self.initialized:
            # The result is CHECKED. Discarding it meant a failed initialize was
            # followed by the work it was meant to enable, and the real failure
            # resurfaced later disguised as something else.
            if await self.initialize() is False:
                raise RuntimeError(
                    type(self).__name__ + ' could not initialize; refusing to '
                    'continue as though it had')

        # Generate batch embeddings
        contents = [m.content for m in memories]
        embeddings = self.embedding_service.batch_embed(
            contents
        ) if self.embedding_service else [None] * len(memories)

        # Assign embeddings to memories
        for memory, embedding in zip(memories, embeddings):
            memory.embedding = embedding

        # Batch store to PostgreSQL
        results = await self.postgres_storage.store_batch(
            memories=memories,
            batch_size=100
        )

        if results:
            self.metrics["memories_stored"] += len(memories)
            return True, len(memories)
        else:
            return False, 0

    async def _generate_worthiness_metadata(
        self,
        content: str,
        confidence_score: float,
        tags: Optional[List[str]],
        source_context: Optional[Dict[str, Any]],
        reasoning_trace: Optional[List[str]],
        importance_score: float = 0.5
    ) -> 'MemoryWorthinessMetadata':
        """
        Generate MemoryWorthinessMetadata from raw inputs.

        This is where Memory Agent analyzes the raw data and makes admission decisions.

        Args:
            content: The memory content
            importance_score: Caller-supplied importance (0.0-1.0), wired into consequence_level
            confidence_score: Confidence score
            tags: Tags from source system
            source_context: Raw metadata from source system
            reasoning_trace: Reasoning steps

        Returns:
            MemoryWorthinessMetadata
        """
        from datetime import datetime
        from core.memory.utils.memory_worthiness import (
            MemoryWorthinessMetadata,
            CognitionMetadata,
            NoveltyMetadata,
            CriticalityMetadata,
            QueryMetadata,
            OutcomeMetadata,
            TemporalMetadata,
            JustificationMetadata,
            DecisionType,
            ConsequenceLevel,
            PatternType,
            QueryType,
            ReusabilityLevel,
            DomainImportance
        )

        source_context = source_context or {}
        source_system = source_context.get("source_system", "unknown")

        # Analyze content for error patterns
        content_lower = content.lower()
        is_error = any(phrase in content_lower for phrase in [
            "sorry", "cannot see", "not visible", "unable to",
            "can't see", "image you intended", "please upload",
            "i'm sorry", "i can't", "i cannot"
        ])

        # Extract key metrics
        reasoning_step_count = len(reasoning_trace) if reasoning_trace else 0
        has_vision = source_context.get("has_image", False) or source_context.get("has_video", False)
        context_count = source_context.get("context_count", 0)

        # Check tags for semantic hints (used throughout metadata generation)
        tags_lower = [t.lower() for t in (tags or [])]
        has_research_tags = any(tag in tags_lower for tag in ['research', 'analysis', 'investigation', 'findings'])
        has_structural_tags = any(tag in tags_lower for tag in ['structure', 'architecture', 'dependencies', 'patterns'])

        # --- Content-based complexity heuristics (fallback when no external signals) ---
        content_words = len(content.split())
        analytical_keywords = [
            'analysis', 'reasoning', 'decision', 'finding', 'because', 'therefore',
            'strategy', 'architecture', 'conclusion', 'discovered', 'insight',
            'patterns', 'synthesis', 'evaluation', 'investigation', 'workflow',
            'coordinated', 'advanced', 'demonstrates', 'capabilities', 'multi-agent',
            'autonomous', 'critical', 'resolved', 'implemented', 'configured',
            'identified', 'determined', 'inferred', 'analyzed', 'optimized'
        ]
        keyword_count = sum(1 for kw in analytical_keywords if kw in content_lower)
        content_is_substantive = content_words >= 30 or keyword_count >= 2

        # 1. Cognition Metadata
        #
        # COMPLEXITY IS NO LONGER BOUGHT WITH LENGTH. This began
        # `complexity_score += min(reasoning_step_count / 5.0, 0.4)`, so a caller
        # emitting five strings gained 0.4 complexity outright -- past the 0.3
        # bar that `substantive_analysis` stores on. Removing the count from the
        # filter alone would not have closed that: verbosity simply bought
        # retention through complexity instead. The score is now derived from
        # the episode's own content and context.
        complexity_score = 0.0
        if context_count > 0:
            complexity_score += min(context_count / 10.0, 0.3)
        if has_vision and not is_error and confidence_score > 0.5:
            complexity_score += 0.3  # Vision only if successful
        # BOOST: Research/structural findings are inherently complex
        if has_research_tags or has_structural_tags:
            logger.debug(f"[METADATA DEBUG] Boosting complexity_score for research/structure tags")
            complexity_score += 0.7  # Ensure it passes the 0.6 soft threshold
        # BOOST: Content-based signals when no external metadata is available
        if complexity_score == 0.0:
            if content_words >= 100:
                complexity_score += 0.4
            elif content_words >= 50:
                complexity_score += 0.25
            elif content_words >= 30:
                complexity_score += 0.1
            if keyword_count >= 3:
                complexity_score += 0.3
            elif keyword_count >= 2:
                complexity_score += 0.2
            elif keyword_count >= 1:
                complexity_score += 0.1
        complexity_score = min(complexity_score, 1.0)

        logger.debug(f"[METADATA DEBUG] Complexity score: {complexity_score:.2f}")
        logger.debug(f"[METADATA DEBUG] Reasoning steps: {reasoning_step_count}")
        logger.debug(f"[METADATA DEBUG] Has research tags: {has_research_tags}")
        logger.debug(f"[METADATA DEBUG] Has structural tags: {has_structural_tags}")
        logger.debug(f"[METADATA DEBUG] Content words: {content_words}, keyword_count: {keyword_count}, substantive: {content_is_substantive}")
        logger.debug(f"[METADATA DEBUG] Importance score: {importance_score:.2f}")

        cognition = CognitionMetadata(
            reasoning_steps=reasoning_step_count,
            reasoning_depth=min(reasoning_step_count, 3),
            execution_time_ms=0.0,
            inference_count=reasoning_step_count,
            complexity_score=complexity_score,
            required_backtracking=False,
            used_multiple_strategies=False,
            # RESOLVED FROM WHAT? This read `confidence_score > 0.7`, so at the
            # default confidence of 1.0 every caller claimed to have resolved
            # uncertainty -- while `involves_uncertainty` (confidence < 0.9)
            # simultaneously said the episode involved none. The same number was
            # being read two opposite ways.
            #
            # Uncertainty can only be resolved if there was some: the episode
            # started short of confident and ended reasonably confident.
            uncertainty_resolved=(
                confidence_score < 0.9 and confidence_score > 0.7 and not is_error
            )
        )

        # 2. Novelty Metadata
        novelty = NoveltyMetadata(
            is_novel=False,  # Would require memory lookup
            contradicts_existing=False,
            synthesis_of_domains=[],
            pattern_type=PatternType.ROUTINE,
            first_occurrence=False,
            connects_disparate_knowledge=False
        )

        # 3. Criticality Metadata

        # Observing the principal speak is a HIGH-consequence observation.
        #
        # Not an exemption from filtering — this IS an observation the substrate
        # made, through its own channel, and it belongs in the same triage as
        # every other one. The defect was that the assessment could not see what
        # kind of observation it was: every signal here is derived from the
        # content string (word count, keyword hits, reasoning steps), and the
        # relevant fact is not in the words. So "the companion must never show
        # reasoning text — use thinking deltas for liveness" scored as
        # QueryType.FACTUAL_LOOKUP and was hard-rejected as
        # `trivial_factual_lookup`.
        #
        # Forgetting what the principal said carries real consequence and the
        # knowledge is reusable indefinitely, so saying so is simply accurate.
        # `source_system` has meant "which system generated this" since this
        # metadata was defined and nothing has ever read it; this is that field
        # becoming load-bearing.
        from_principal = source_system in ("companion", "user", "principal")

        # Research findings have higher reusability
        reusability = (
            ReusabilityLevel.HIGH
            if (has_research_tags or has_structural_tags or from_principal)
            else ReusabilityLevel.MEDIUM
        )

        # Wire importance_score into consequence_level
        if is_error:
            consequence_level = ConsequenceLevel.NONE
        elif from_principal:
            consequence_level = ConsequenceLevel.HIGH
        elif importance_score >= 0.85:
            consequence_level = ConsequenceLevel.HIGH
        elif importance_score >= 0.7:
            consequence_level = ConsequenceLevel.MEDIUM
        elif confidence_score > 0.7:
            consequence_level = ConsequenceLevel.MEDIUM
        else:
            consequence_level = ConsequenceLevel.LOW

        criticality = CriticalityMetadata(
            decision_type=DecisionType.OPERATIONAL,
            domain_importance=DomainImportance.MEDIUM,
            reusability=reusability,
            consequence_level=consequence_level,
            likely_reference_count=0,
            time_sensitivity=False
        )

        # 4. Query Metadata
        # Determine query type based on characteristics (tags already checked above)
        if from_principal:
            # An exchange with the principal is not the substrate looking a fact
            # up. Classifying it as FACTUAL_LOOKUP is what triggered the
            # `trivial_factual_lookup` hard-reject.
            query_type = QueryType.SYNTHESIS
        elif has_vision and not is_error:
            # Vision analysis is always complex reasoning
            query_type = QueryType.COMPLEX_REASONING
        elif content_is_substantive and keyword_count >= 2:
            # Analytical language over substantive content. This tested
            # `reasoning_step_count > 1`, which classified an episode by how many
            # list items the caller sent -- and COMPLEX_REASONING is one of the
            # three types `substantive_analysis` stores on, so the format of the
            # trace decided the classification that decided retention.
            query_type = QueryType.COMPLEX_REASONING
        elif context_count > 2:
            # Synthesis of multiple sources
            query_type = QueryType.SYNTHESIS
        elif has_research_tags or has_structural_tags:
            # Research/structural findings are synthesis-level knowledge
            query_type = QueryType.SYNTHESIS
        elif keyword_count >= 3 or content_words >= 50:
            # Substantive content detected via text analysis
            query_type = QueryType.ANALYSIS
        else:
            # Default to factual lookup (conservative)
            query_type = QueryType.FACTUAL_LOOKUP

        logger.debug(f"[METADATA DEBUG] Query type: {query_type}")

        query = QueryMetadata(
            query_type=query_type,
            requires_synthesis=context_count > 0 or has_vision,
            multi_step=reasoning_step_count > 1 or has_vision,
            involves_uncertainty=confidence_score < 0.9,
            ambiguous_input=False,
            context_dependent=context_count > 0 or has_vision
        )

        # 5. Outcome Metadata
        outcome = OutcomeMetadata(
            conclusion_confidence=0.0 if is_error else confidence_score,
            hypothesis_supported=None,
            actionable=False if is_error else confidence_score > 0.7,
            created_new_knowledge=False,
            action_type="error_response" if is_error else "reasoning",
            action_summary=f"{source_system} result",
            affected_components=[source_system],
            validated_against_sources=False,
            requires_human_review=is_error or confidence_score < 0.5
        )

        # 6. Temporal Metadata
        temporal = TemporalMetadata(
            created_at=datetime.now().isoformat(),
            session_id="",
            trigger_event=f"{source_system}_query",
            sequence_number=0
        )

        # 7. Justification Metadata
        store_reasons = []
        if complexity_score >= 0.6:
            store_reasons.append("complexity_threshold")
        if reasoning_step_count >= 3:
            store_reasons.append("multi_step_reasoning")

        justification = JustificationMetadata(
            store_reason=store_reasons if store_reasons else ["below_threshold"],
            decision_summary=f"Analyzed by Memory Agent from {source_system}",
            alternatives_considered=[],
            rejected_because=[] if store_reasons else ["insufficient_complexity"]
        )

        return MemoryWorthinessMetadata(
            cognition=cognition,
            novelty=novelty,
            criticality=criticality,
            query=query,
            outcome=outcome,
            temporal=temporal,
            justification=justification,
            source_system=source_system,
            domain="general"
        )

    def _infer_memory_type(
        self,
        worthiness_metadata: Optional['MemoryWorthinessMetadata'],
        source_context: Dict[str, Any]
    ) -> MemoryType:
        """
        Infer memory type based on metadata and context.

        Classification logic (using core.memory.utils.interfaces.MemoryType):
        - Vision observations, specific events → EPISODIC
        - General facts, reusable knowledge → SEMANTIC
        - Skills, procedures, how-to → PROCEDURAL
        - Temporary working data → WORKING
        - Learning about learning → META

        Args:
            worthiness_metadata: Optional metadata from upstream system
            source_context: Context dictionary with source_system, has_image, etc.

        Returns:
            MemoryType enum value from core.memory.utils.interfaces
        """
        from core.memory.utils.memory_worthiness import QueryType

        # Error responses are episodic (failed attempts are specific events)
        if worthiness_metadata and worthiness_metadata.outcome.action_type == "error_response":
            logger.info("✓ Inferred EPISODIC: error response (failed attempt)")
            return MemoryType.EPISODIC

        # Procedural indicators in tags
        tags = source_context.get("tags", [])
        procedural_tags = {"procedure", "skill", "how-to", "method", "process", "tutorial", "guide"}
        if any(tag in procedural_tags for tag in tags):
            logger.info(f"✓ Inferred PROCEDURAL: procedural tags present {tags}")
            return MemoryType.PROCEDURAL

        # Meta-learning indicators
        meta_tags = {"meta_learning", "learning_about_learning", "cognitive", "self_reflection"}
        if any(tag in meta_tags for tag in tags):
            logger.info(f"✓ Inferred META: meta-learning tags present {tags}")
            return MemoryType.META

        # Semantic for general knowledge and factual lookups
        if worthiness_metadata:
            # Simple factual lookups that succeeded → semantic (reusable knowledge)
            if worthiness_metadata.query.query_type == QueryType.FACTUAL_LOOKUP:
                # But only if it's not an error
                if worthiness_metadata.outcome.action_type != "error_response":
                    logger.info("✓ Inferred SEMANTIC: successful factual lookup")
                    return MemoryType.SEMANTIC

            # Complex reasoning that created new knowledge → semantic (if generalizable)
            if (worthiness_metadata.outcome.created_new_knowledge and
                worthiness_metadata.criticality.reusability.value in ["high", "medium"]):
                logger.info(f"✓ Inferred SEMANTIC: created reusable knowledge (created_new_knowledge={worthiness_metadata.outcome.created_new_knowledge}, reusability={worthiness_metadata.criticality.reusability.value})")
                return MemoryType.SEMANTIC

        # Check source system patterns
        source_system = source_context.get("source_system", "unknown")

        # Neural bridge reasoning queries are often episodic (specific reasoning instances)
        if source_system == "neural_bridge":
            logger.info(f"✓ Inferred EPISODIC: neural bridge reasoning (specific instance)")
            return MemoryType.EPISODIC

        # Autonomous tasks are episodic (specific task executions)
        if source_system == "autonomous_coordinator":
            logger.info("✓ Inferred EPISODIC: autonomous task (specific execution)")
            return MemoryType.EPISODIC

        # Hypothesis testing is episodic (specific experiments)
        if source_system == "hypothesis_testing":
            logger.info("✓ Inferred EPISODIC: hypothesis test (specific experiment)")
            return MemoryType.EPISODIC

        # Continuous learning outcomes could be procedural (learned skills)
        if source_system == "continuous_learning":
            logger.info("✓ Inferred PROCEDURAL: continuous learning (learned skill)")
            return MemoryType.PROCEDURAL

        # Default to EPISODIC (specific events) rather than SEMANTIC
        # This is safer - better to treat general knowledge as a specific event
        # than to treat a specific event as general knowledge
        logger.info("✓ Inferred EPISODIC: default (specific event/observation)")
        return MemoryType.EPISODIC

    # ================================================================================================
    # MEMORY DEDUPLICATION HELPERS
    # ================================================================================================

    async def _find_similar_memories(
        self,
        content: str,
        similarity_threshold: float = 0.85,
        tags: Optional[List[str]] = None,
        memory_type: Optional[MemoryType] = None,
        limit: int = 5
    ) -> List[MemoryItem]:
        """
        Find similar memories using semantic search

        Searches for memories with semantic similarity >= threshold to prevent duplicates.

        Args:
            content: Content to search for
            similarity_threshold: Minimum similarity score (0.0-1.0)
            tags: Optional tag filter
            memory_type: Optional memory type filter
            limit: Maximum similar memories to return

        Returns:
            List of similar MemoryItem objects, sorted by similarity descending
        """
        try:
            # Generate embedding for content
            if not self.embedding_service:
                logger.warning("Embedding service not available, cannot check for duplicates")
                logger.warning("[DUPLICATE CHECK] embedding service unavailable; duplicate check skipped")
                return []

            query_embedding = self.embedding_service.generate_embedding(content)
            if not query_embedding:
                logger.warning("Failed to generate embedding, cannot check for duplicates")
                logger.warning("[DUPLICATE CHECK] embedding could not be generated; duplicate check skipped")
                return []

            logger.debug(f"[DUPLICATE CHECK] ✓ Generated embedding ({len(query_embedding)} dims), searching...")

            # Search for similar memories using semantic search
            results = await self.postgres_storage.semantic_search(
                query_embedding=query_embedding,
                memory_type=memory_type,
                min_similarity=similarity_threshold,
                limit=limit
            )

            logger.debug(
                f"Found {len(results)} similar memories "
                f"(similarity >= {similarity_threshold})"
            )

            return results

        except Exception as e:
            logger.error(f"Error finding similar memories: {e}")
            return []

    async def _merge_memory_content(
        self,
        existing_memory: MemoryItem,
        new_content: str,
        new_metadata: Dict[str, Any]
    ) -> Optional[str]:
        """
        Merge new content into existing memory deterministically.

        No LLM involved — the memory agent owns its own merge logic.
        Uses sentence-level deduplication: keeps all sentences from the
        existing memory, then appends sentences from the new content that
        are not already covered (normalised string match + word-overlap
        heuristic to catch near-duplicates).

        Args:
            existing_memory: Existing MemoryItem to merge into
            new_content: New content to merge
            new_metadata: New metadata (importance, confidence, tags, etc.)

        Returns:
            memory_id if merge successful, None otherwise
        """
        try:
            # Deterministic sentence-level deduplication — no LLM call.
            # Avoids loading the Qwen3-8B model and all concurrent-
            # initialisation crash risks that come with it.
            import re as _re

            def _split_sentences(text: str):
                return [s.strip() for s in _re.split(r'(?<=[.!?])\s+', text) if s.strip()]

            def _normalise(s: str) -> str:
                return _re.sub(r'\s+', ' ', s.lower().strip().rstrip('.!?'))

            existing_sents = _split_sentences(existing_memory.content)
            existing_norm = {_normalise(s) for s in existing_sents}
            novel = [
                s for s in _split_sentences(new_content)
                if _normalise(s) not in existing_norm
            ]
            consolidated_content = (
                existing_memory.content + ' ' + ' '.join(novel)
            ).strip() if novel else existing_memory.content

            # Calculate updated importance and confidence
            # Take the maximum importance (more important memory wins)
            updated_importance = max(
                existing_memory.importance_score,
                new_metadata.get('importance_score', 0.5)
            )

            # Average confidence scores
            updated_confidence = (
                existing_memory.confidence_score +
                new_metadata.get('confidence_score', 1.0)
            ) / 2.0

            # Merge tags (union of both sets)
            existing_tags = set(existing_memory.tags or [])
            new_tags = set(new_metadata.get('tags', []))
            merged_tags = list(existing_tags | new_tags)

            # Merge reasoning traces.
            # `.get(k, [])` returns None when the key EXISTS and is None, which
            # is the normal case for a memory with no trace — so this raised
            # TypeError: can only concatenate list (not "NoneType") to list,
            # and every merge of such a memory died inside the handler.
            existing_trace = existing_memory.reasoning_trace or []
            new_trace = new_metadata.get('reasoning_trace') or []
            merged_trace = existing_trace + new_trace

            # Update existing memory
            updates = {
                'content': consolidated_content,
                'importance_score': updated_importance,
                'confidence_score': updated_confidence,
                'tags': merged_tags,
                'reasoning_trace': merged_trace,
                'access_count': existing_memory.access_count + 1,
                'last_accessed': datetime.now(),
                'metadata': {
                    **existing_memory.metadata,
                    'merged_at': datetime.now().isoformat(),
                    'merge_count': existing_memory.metadata.get('merge_count', 0) + 1,
                    'last_merge_source': (new_metadata.get('source_context') or {}).get('source_system', 'unknown')
                }
            }

            # Regenerate embedding for consolidated content
            if self.embedding_service:
                new_embedding = self.embedding_service.generate_embedding(consolidated_content)
                if new_embedding:
                    updates['embeddings'] = new_embedding

            # Update in PostgreSQL
            success = await self.postgres_storage.update_memory(
                memory_id=existing_memory.memory_id,
                updates=updates,
                tier='hot'
            )

            if success:
                logger.info(
                    f"Memory {existing_memory.memory_id} updated with merged content "
                    f"(importance: {existing_memory.importance_score:.2f} → {updated_importance:.2f})"
                )
                return existing_memory.memory_id
            else:
                logger.error(f"Failed to update memory {existing_memory.memory_id} with merged content")
                return None

        except Exception as e:
            logger.error(f"Error merging memory content: {e}")
            logger.exception("Error merging memory content")
            return None

    async def _cluster_by_similarity(
        self,
        memories: List[MemoryItem],
        similarity_threshold: float = 0.85
    ) -> List[List[MemoryItem]]:
        """
        Cluster similar memories together

        Groups memories by semantic similarity for consolidation.

        Args:
            memories: List of MemoryItem objects to cluster
            similarity_threshold: Minimum similarity to group together

        Returns:
            List of clusters (each cluster is a list of similar memories)
        """
        if not self.embedding_service or not memories:
            return [[m] for m in memories]  # Each memory in its own cluster

        try:
            import json as _json
            import numpy as np

            # Extract embeddings
            embeddings = []
            for memory in memories:
                emb_value = None

                raw = getattr(memory, "embeddings", None)
                if raw is not None:
                    # Embeddings may be stored as JSON strings — parse them
                    if isinstance(raw, str):
                        try:
                            raw = _json.loads(raw)
                        except Exception:
                            raw = None

                if raw is not None:
                    try:
                        arr = np.asarray(raw, dtype=float).ravel()
                        if arr.size > 0:
                            emb_value = arr.tolist()
                    except Exception:
                        emb_value = None

                if emb_value is None:
                    # Generate embedding if missing/unusable
                    emb = self.embedding_service.generate_embedding(memory.content)

                    if isinstance(emb, str):
                        try:
                            emb = _json.loads(emb)
                        except Exception:
                            emb = None

                    try:
                        arr = np.asarray(emb, dtype=float).ravel() if emb is not None else np.asarray([], dtype=float)
                        emb_value = arr.tolist() if arr.size > 0 else [0.0] * self.embedding_dim
                    except Exception:
                        emb_value = [0.0] * self.embedding_dim

                embeddings.append(emb_value)

            # Simple clustering using cosine similarity
            clusters = []
            used_indices = set()

            for i, memory in enumerate(memories):
                if i in used_indices:
                    continue

                # Start new cluster with this memory
                cluster = [memory]
                used_indices.add(i)

                # Find similar memories
                for j, other_memory in enumerate(memories):
                    if j in used_indices or i == j:
                        continue

                    # Calculate cosine similarity
                    raw_i = embeddings[i]
                    raw_j = embeddings[j]
                    # Embeddings may be stored as JSON strings — parse them
                    if isinstance(raw_i, str):
                        import json as _json
                        raw_i = _json.loads(raw_i)
                    if isinstance(raw_j, str):
                        import json as _json
                        raw_j = _json.loads(raw_j)
                    emb1 = np.array(raw_i, dtype=float)
                    emb2 = np.array(raw_j, dtype=float)

                    # Guard against unexpected shapes/length mismatches
                    emb1 = emb1.ravel()
                    emb2 = emb2.ravel()
                    if emb1.size == 0 or emb2.size == 0:
                        continue
                    if emb1.size != emb2.size:
                        min_len = min(emb1.size, emb2.size)
                        if min_len == 0:
                            continue
                        emb1 = emb1[:min_len]
                        emb2 = emb2[:min_len]

                    similarity = float(np.dot(emb1, emb2) / (
                        np.linalg.norm(emb1) * np.linalg.norm(emb2) + 1e-10
                    ))

                    if similarity >= similarity_threshold:
                        cluster.append(other_memory)
                        used_indices.add(j)

                clusters.append(cluster)

            logger.info(
                f"Clustered {len(memories)} memories into {len(clusters)} clusters "
                f"(threshold={similarity_threshold})"
            )

            return clusters

        except Exception as e:
            logger.error(f"Error clustering memories: {e}")
            return [[m] for m in memories]  # Fallback to individual clusters

    async def _consolidate_cluster(
        self,
        cluster: List[MemoryItem]
    ) -> Optional[str]:
        """
        Consolidate a cluster of similar memories into one

        Merges multiple similar memories, keeping the most important as base.

        Args:
            cluster: List of similar MemoryItem objects

        Returns:
            memory_id of consolidated memory, None if failed
        """
        if not cluster:
            return None

        if len(cluster) == 1:
            return cluster[0].memory_id

        try:
            # Sort by importance (descending) - keep most important as base
            sorted_cluster = sorted(
                cluster,
                key=lambda m: m.importance_score,
                reverse=True
            )

            base_memory = sorted_cluster[0]
            logger.info(
                f"Consolidating {len(cluster)} memories into base: {base_memory.memory_id}"
            )

            # Merge each additional memory into base
            for memory in sorted_cluster[1:]:
                merged_id = await self._merge_memory_content(
                    existing_memory=base_memory,
                    new_content=memory.content,
                    new_metadata={
                        'importance_score': memory.importance_score,
                        'confidence_score': memory.confidence_score,
                        'tags': memory.tags,
                        'source_context': memory.metadata,
                        'reasoning_trace': memory.reasoning_trace
                    }
                )

                if merged_id:
                    # Soft delete the merged memory
                    await self.postgres_storage.delete_memory(
                        memory_id=memory.memory_id,
                        soft_delete=True,
                        reason=f"Consolidated into {base_memory.memory_id}"
                    )

            logger.info(
                f"Consolidated {len(cluster)} memories into {base_memory.memory_id}"
            )

            return base_memory.memory_id

        except Exception as e:
            logger.error(f"Error consolidating cluster: {e}")
            return None

    async def bulk_import(
        self,
        memories: List[Dict[str, Any]],
        memory_type: Optional[MemoryType] = None,
        generate_embeddings: bool = True,
        tier: str = "hot",
        batch_size: int = 100
    ) -> Tuple[bool, int]:
        """
        Bulk import memories (for migration or initialization)

        Efficiently imports large batches of memories with optional embedding generation.

        Args:
            memories: List of memory dictionaries
            memory_type: Default memory type if not specified in dict
            generate_embeddings: Whether to generate embeddings (default: True)
            tier: Target tier ("hot" or "cold")
            batch_size: Batch size for processing

        Returns:
            Tuple of (success, total_imported)
        """
        if not self.initialized:
            # The result is CHECKED. Discarding it meant a failed initialize was
            # followed by the work it was meant to enable, and the real failure
            # resurfaced later disguised as something else.
            if await self.initialize() is False:
                raise RuntimeError(
                    type(self).__name__ + ' could not initialize; refusing to '
                    'continue as though it had')

        # Convert dicts to MemoryItem objects
        memory_items = []
        for mem_dict in memories:
            item = MemoryItem(
                memory_id=mem_dict.get("memory_id", f"mem_{uuid.uuid4().hex}"),
                memory_type=mem_dict.get("memory_type", memory_type),
                content=mem_dict.get("content"),
                importance_score=mem_dict.get("importance_score", 0.5),
                confidence_score=mem_dict.get("confidence_score", 1.0),
                created_at=mem_dict.get("created_at", datetime.now()),
                last_accessed=mem_dict.get("last_accessed", datetime.now()),
                access_count=mem_dict.get("access_count", 0),
                decay_rate=mem_dict.get("decay_rate", 0.01),
                tags=mem_dict.get("tags", []),
                metadata=mem_dict.get("metadata", {}),
                embedding=mem_dict.get("embedding"),
                embedding_metadata=mem_dict.get("embedding_metadata", {}),
                related_memories=mem_dict.get("related_memories", []),
                session_id=mem_dict.get("session_id", ""),
                user_id=mem_dict.get("user_id", ""),
                tier=tier,
                archived_at=None,
                deleted_at=None
            )
            memory_items.append(item)

        # Generate embeddings if requested
        if generate_embeddings and self.embedding_service:
            contents = [m.content for m in memory_items]
            embeddings = self.embedding_service.batch_embed(contents)
            for item, embedding in zip(memory_items, embeddings):
                item.embedding = embedding

        # Store to appropriate tier
        if tier == "hot":
            results = await self.postgres_storage.store_batch(
                memories=memory_items,
                batch_size=batch_size
            )
        else:  # cold tier
            # Store to cold tier - migrate each memory individually
            results = []
            for memory_item in memory_items:
                # First store to hot tier, then migrate
                success = await self.postgres_storage.store_memory(memory_item)
                if success:
                    await self.postgres_storage.migrate_to_cold(memory_item.memory_id)
                results.append(memory_item.memory_id if success else None)

        self.metrics["memories_stored"] += len(memory_items)
        return True, len(memory_items)

    # ================================================================================================
    # MEMORY RETRIEVAL (Hot + Cold Tiers)
    # ================================================================================================

    async def retrieve_memory(
        self,
        memory_id: str,
        update_access: bool = True,
        tier_hint: Optional[str] = None
    ) -> Optional[MemoryItem]:
        """
        Retrieve memory by ID from hot or cold tier

        Tries hot tier (PostgreSQL) first, then cold tier (PostgreSQL archival) if not found.
        Updates access_count and last_accessed if update_access=True.

        Args:
            memory_id: Memory ID to retrieve
            update_access: Whether to update access metrics (default: True)
            tier_hint: Optional tier hint ("hot" or "cold") to optimize lookup

        Returns:
            MemoryItem if found, None otherwise
        """
        if not self.initialized:
            # The result is CHECKED. Discarding it meant a failed initialize was
            # followed by the work it was meant to enable, and the real failure
            # resurfaced later disguised as something else.
            if await self.initialize() is False:
                raise RuntimeError(
                    type(self).__name__ + ' could not initialize; refusing to '
                    'continue as though it had')

        # Check cache first
        if self.cache_enabled and memory_id in self.memory_cache:
            logger.debug(f"Cache hit for memory {memory_id}")
            self.metrics["cache_hits"] += 1
            return self.memory_cache[memory_id]

        # Try hot tier (PostgreSQL) first
        if tier_hint != "cold":
            memory = await self.postgres_storage.get_memory(
                memory_id=memory_id
            )

            if memory:
                # Update access if requested
                if update_access:
                    memory.access_count += 1
                    memory.last_accessed = datetime.now()
                    await self.postgres_storage.update_memory(memory_id, {
                        "access_count": memory.access_count,
                        "last_accessed": memory.last_accessed
                    })

                # Cache result
                if self.cache_enabled:
                    self.memory_cache[memory_id] = memory

                self.metrics["memories_retrieved"] += 1
                return memory

        # Try cold tier (PostgreSQL) if not found in hot tier
        memory = await self.postgres_storage.get_memory_from_cold(memory_id)
        if memory:
            logger.info(f"Retrieved memory {memory_id} from cold tier")
            self.metrics["memories_retrieved"] += 1
            return memory

        # Not found in any tier
        logger.warning(f"Memory {memory_id} not found in any tier")
        return None

    async def get_recent_memories(
        self,
        limit: int = 10,
        memory_types: Optional[List[MemoryType]] = None,
        min_importance: Optional[float] = None,
        tags: Optional[Set[str]] = None
    ) -> List[MemoryItem]:
        """
        Get recent memories from hot tier (PostgreSQL)

        Retrieves most recent memories sorted by created_at descending.
        Filters by type, importance, and tags if specified.

        Args:
            limit: Maximum results to return
            memory_types: Filter by memory types (episodic, semantic, etc.)
            min_importance: Minimum importance score filter
            tags: Filter by tags (set of tag strings)

        Returns:
            List of MemoryItem objects sorted by recency
        """
        if not self.initialized:
            # The result is CHECKED. Discarding it meant a failed initialize was
            # followed by the work it was meant to enable, and the real failure
            # resurfaced later disguised as something else.
            if await self.initialize() is False:
                raise RuntimeError(
                    type(self).__name__ + ' could not initialize; refusing to '
                    'continue as though it had')

        # Calculate time window (recent memories in hot tier)
        time_window_start = (datetime.now() - timedelta(days=7)).timestamp()  # Last 7 days
        time_window_end = datetime.now().timestamp()

        # Query PostgreSQL hot tier
        results = await self.postgres_storage.search_memories(
            memory_type=memory_types[0] if memory_types else None,
            tags=tags,
            time_window_start=time_window_start,
            time_window_end=time_window_end,
            min_importance=min_importance,
            limit=limit
        )

        logger.debug(f"Retrieved {len(results)} recent memories (last 7 days)")
        return results

    #: The retrieval strategies that compose one recall. Each is a distinct
    #: storage primitive, so "specialise the agents" is a property of the
    #: design rather than a TODO: semantic finds paraphrase, keyword finds
    #: literal strings an embedding smooths away, tags find curation.
    RETRIEVAL_STRATEGIES = ("semantic", "keyword", "tags")

    async def retrieve(
        self,
        query: Optional[str] = None,
        *,
        tags: Optional[Set[str]] = None,
        memory_types: Optional[List[MemoryType]] = None,
        strategies: Optional[Sequence[str]] = None,
        limit: int = 10,
        min_similarity: float = 0.5,
        min_importance: Optional[float] = None,
        deduplicate: bool = True,
        include_events: bool = True,
        relative_to_best: Optional[float] = None,
        require_named_match: bool = False,
    ) -> List[MemoryItem]:
        """Recall memories by running every applicable strategy CONCURRENTLY.

        This is the composition layer the swarm search was: several retrieval
        strategies at once, merged. It is worth having for RECALL, not speed --
        the measurement that motivated it (QUERY_AGENT_TEST_RESULTS.md) is
        usually quoted as "11x slower", but the number underneath it is that
        regular search returned 0 memories where the multi-strategy search
        returned 5. A single strategy silently misses; a slower answer that
        finds the memory beats a fast one that does not.

        The four defects recorded against the original are addressed here:

          parallelisation   asyncio.gather, so cost is the SLOWEST strategy
                            rather than their sum
          specialisation    each strategy is a different storage primitive,
                            not three copies of the same query
          coordination      merging is a dict keyed by memory_id -- no agent
                            objects, no scheduling, no inter-agent messaging
          cross-tier        scope is passed through to storage instead of
                            being pinned to the hot tier

        A strategy that cannot run (no embedding service, no tags supplied) is
        skipped rather than failing the recall, and a strategy that RAISES is
        recorded and skipped -- one broken index must not empty the result set.

        Returns memories ranked by how many independent strategies found them,
        then by importance. Agreement between strategies is real evidence: a
        memory found by both meaning and wording is a better match than one
        found by a single path.
        """
        if not self.initialized:
            # The result is CHECKED. Discarding it meant a failed initialize was
            # followed by the work it was meant to enable, and the real failure
            # resurfaced later disguised as something else.
            if await self.initialize() is False:
                raise RuntimeError(
                    type(self).__name__ + ' could not initialize; refusing to '
                    'continue as though it had')

        selected = tuple(strategies) if strategies else self.RETRIEVAL_STRATEGIES
        # Ask for more per strategy than the caller wants, because the merge
        # discards duplicates and a per-strategy limit of `limit` would leave
        # fewer than `limit` distinct memories.
        per_strategy = max(limit, limit * 2 if deduplicate else limit)
        memory_type = memory_types[0] if memory_types else None

        async def _semantic() -> List[MemoryItem]:
            if not query or not self.embedding_service:
                return []
            embedding = self.embedding_service.generate_embedding(query)
            if not embedding:
                return []
            return await self.postgres_storage.semantic_search(
                query_embedding=embedding,
                memory_type=memory_type,
                min_similarity=min_similarity,
                limit=per_strategy,
            )

        async def _keyword() -> List[MemoryItem]:
            if not query:
                return []
            return await self.postgres_storage.search_by_content(
                content=query, exact_match=False, limit=per_strategy,
            )

        async def _tags() -> List[MemoryItem]:
            if not tags:
                return []
            return await self.postgres_storage.search_memories(
                memory_type=memory_type,
                tags=set(tags),
                min_importance=min_importance,
                limit=per_strategy,
            )

        runners = {"semantic": _semantic, "keyword": _keyword, "tags": _tags}
        unknown = [name for name in selected if name not in runners]
        if unknown:
            raise ValueError(
                f"unknown retrieval strategies {unknown}; "
                f"known: {sorted(runners)}"
            )

        names = [n for n in selected if n in runners]
        outcomes = await asyncio.gather(
            *(runners[n]() for n in names), return_exceptions=True
        )

        merged: Dict[str, MemoryItem] = {}
        found_by: Dict[str, Set[str]] = {}
        for name, outcome in zip(names, outcomes):
            if isinstance(outcome, Exception):
                logger.warning("retrieval strategy %s failed: %s", name, outcome)
                continue
            for item in outcome or []:
                merged.setdefault(item.memory_id, item)
                found_by.setdefault(item.memory_id, set()).add(name)

        if min_importance is not None:
            merged = {
                mid: m for mid, m in merged.items()
                if (m.importance_score or 0.0) >= min_importance
            }

        # OBSERVATIONS AND KNOWLEDGE SHARE A TABLE, NOT A PURPOSE.
        #
        # An event record is kept because it HAPPENED, and its multiplicity is
        # the signal -- 309 governance blocks are 309 facts about how often the
        # system was blocked, which is what competence calibration counts. That
        # is why store_memory exempts them from the worthiness filter and why
        # consolidation must never merge them.
        #
        # The same property makes them useless to a similarity search. They are
        # near-identical to each other by construction (those 309 score 0.974 to
        # 0.998 pairwise, separated only by an id the embedding cannot see), so
        # they cannot be found BY meaning, and they displace what can: a wave
        # asking about pressure loss returns the event log.
        #
        # So the split is at READ time, not write time. Records are queried by
        # STRUCTURE -- tag, type, time window, outcome -- where the count is
        # exact; recall searches KNOWLEDGE. One predicate decides which a memory
        # is, and it is the same one store_memory used to exempt it, so the two
        # halves cannot drift apart.
        if not include_events:
            from core.memory.utils.memory_filter import get_memory_filter
            _filter = get_memory_filter()
            kept = {}
            for mid, m in merged.items():
                tags = list(m.tags or [])
                raw_event = (m.thinking_state or {}).get("raw_event")
                if _filter.exemption_for(tags=tags, raw_event=raw_event) is None:
                    kept[mid] = m
            if len(kept) != len(merged):
                logger.debug("retrieve: %d event records held back from recall",
                             len(merged) - len(kept))
            merged = kept

        # NAMED SOMETHING ELSE IS NOT A NEAR MISS.
        #
        # `the capital of Mongolia` and `the capital of France` differ by one
        # token, so the vector scores them close -- and one is not a weaker
        # answer to the other, it is the answer to a DIFFERENT question.
        # Measured on the live store, "The capital of France is Paris." came
        # back as the top hit for the Mongolia question at 0.210.
        #
        # No threshold separates those, because the thing that distinguishes
        # them is not a matter of degree. It is the same shape as polarity, and
        # it gets the same treatment: an exact test in `claim_shape`, made once
        # and made outside the vector. A proper noun is rigid -- `anomaly`
        # paraphrases to `unusual behaviour`, nothing paraphrases `Mongolia` --
        # so a memory that never mentions what the question named is not about
        # it at any score.
        #
        # OFF BY DEFAULT, because it costs a real case: a memory answering
        # about a named thing WITHOUT naming it ("the system has been up four
        # days" for "what is Torin's uptime") is dropped. Recall accepts that
        # trade -- a miss is better than confidently reporting another
        # entity's fact -- and the subsystems reading their own records, where
        # the name is always present, are left alone.
        if require_named_match and query:
            from core.semantics.claim_shape import about_the_same_thing

            def _same_thing(m) -> bool:
                content = m.content
                if isinstance(content, dict):
                    content = content.get("text") or content.get("content") or ""
                return about_the_same_thing(query, str(content or "")) is not False

            merged = {mid: m for mid, m in merged.items() if _same_thing(m)}

        # A CUT-OFF RELATIVE TO THE BEST MATCH, NOT AN ABSOLUTE ONE.
        #
        # Cosine is not calibrated across questions. The same 0.4 is a weak
        # match for a question the store answers well and the best match in
        # existence for one it barely covers, so a fixed floor excludes true
        # matches on hard questions and admits noise on easy ones. Measured on
        # the live store: at the 0.5 floor, "how does traffic get spread across
        # servers" and "what spots unusual behaviour in data" both returned
        # NOTHING while the memory that answers each sat in the index.
        #
        # What is comparable is within one question: how far the rest fall
        # behind the best hit. That is self-calibrating, and measured over the
        # same probes it answered 5 of 6 correctly with ZERO false answers to
        # questions the store holds nothing for -- against 4 of 6 for the
        # fixed floor.
        #
        # It applies ONLY to memories whose match was actually MEASURED. A
        # keyword hit means the query text appears verbatim in the memory and
        # carries no similarity score; ranking it out by comparison to a number
        # it does not have would discard evidence on the strength of a
        # measurement that was never taken.
        if relative_to_best is not None:
            measured = [m for m in merged.values()
                        if getattr(m, "similarity_score", None) is not None]
            if measured:
                cut = max(float(m.similarity_score) for m in measured) * relative_to_best
                merged = {
                    mid: m for mid, m in merged.items()
                    if getattr(m, "similarity_score", None) is None
                    or float(m.similarity_score) >= cut
                }

        # RELEVANCE FIRST. How well a memory matches THIS question decides its
        # rank; corroboration and importance only separate memories that match
        # equally well. This is the one place recall is ordered -- the single
        # authority for it -- so the ordering is decided here on the evidence
        # about the question asked, not re-decided downstream on properties of
        # the memory.
        #
        # Similarity is that evidence. Corroboration (how many strategies found
        # it) is a weaker co-signal -- the keyword strategy is a verbatim match,
        # so it rarely corroborates and cannot be the primary key -- and
        # importance is a property of the memory, not the question, so the most
        # important memory in the store must not win a query it barely matches.
        # Measured on the live store: "what is a load balancer" matched the
        # load-balancer memory at 0.839 while an unrelated memory matched at
        # 0.204; relevance-first ranks the right one first, importance-first did
        # not. Keyword/tags carry no similarity -- they qualified against a floor
        # and how well is unknown -- so they are scored at that floor, read as
        # neither a strong nor a weak match.
        def _match_strength(m) -> float:
            score = getattr(m, "similarity_score", None)
            return float(score) if score is not None else float(min_similarity)

        ranked = sorted(
            merged.values(),
            key=lambda m: (_match_strength(m),
                           len(found_by.get(m.memory_id, ())),
                           m.importance_score or 0.0),
            reverse=True,
        )

        logger.debug(
            "retrieve: %d distinct memories from %s (corroborated by >1: %d)",
            len(ranked), names,
            sum(1 for mid in found_by if len(found_by[mid]) > 1),
        )
        return ranked[:limit]

    @profile_performance("memory_agent", "search_memories")
    async def search_memories(
        self,
        query: Optional[str] = None,
        memory_types: Optional[List[MemoryType]] = None,
        min_similarity: float = 0.7,
        limit: Optional[int] = None,
        deduplicate: bool = True,
        # New interface parameters for integration compatibility
        query_text: Optional[str] = None,
        memory_type: Optional[MemoryType] = None,
        tags: Optional[List[str]] = None,
        max_results: Optional[int] = None,
        min_importance: Optional[float] = None,
        include_events: bool = True,
        relative_to_best: Optional[float] = None,
        require_named_match: bool = False
    ) -> Union[Tuple[bool, List[MemoryItem]], List[MemoryItem]]:
        """Compatibility surface over retrieve(). Adapts shape only.

        Retrieval itself has ONE owner now: retrieve(). This ran its own
        partial composition -- semantic, then tags, then reranking, in
        sequence -- which meant two different answers to "what does this
        system recall", differing in which strategies ran and in what order.
        Whichever a caller happened to use decided what it could find.

        What survives here is the calling convention, because callers depend
        on it and there are two of them:

            legacy  search_memories(query=..., limit=...)      -> (bool, list)
            new     search_memories(query_text=..., tags=...)  -> list

        That fork is itself a defect -- a function whose return TYPE depends on
        which keyword you passed cannot be used without knowing the call site --
        but collapsing it is a caller migration, not a retrieval change, so it
        is left standing rather than bundled into this one.
        """
        new_interface = any([query_text is not None, memory_type is not None,
                             tags is not None, max_results is not None,
                             min_importance is not None])

        query_str = query_text or query
        if query_str is None and not tags:
            logger.error("search_memories requires a query, query_text or tags")
            return [] if new_interface else (False, [])

        types = memory_types
        if types is None and memory_type is not None:
            types = [memory_type]

        results = await self.retrieve(
            query_str,
            tags=set(tags) if tags else None,
            memory_types=types,
            limit=max_results or limit or 10,
            min_similarity=min_similarity,
            min_importance=min_importance,
            deduplicate=deduplicate,
            include_events=include_events,
            relative_to_best=relative_to_best,
            require_named_match=require_named_match,
        )
        return results if new_interface else (True, results)


    async def query_by_tags(
        self,
        tags: Set[str],
        memory_types: Optional[List[MemoryType]] = None,
        limit: int = 100
    ) -> Tuple[bool, List[MemoryItem]]:
        """
        Query memories by tags (hot tier)

        Searches PostgreSQL hot tier for memories matching tags.
        """
        if not self.initialized:
            # The result is CHECKED. Discarding it meant a failed initialize was
            # followed by the work it was meant to enable, and the real failure
            # resurfaced later disguised as something else.
            if await self.initialize() is False:
                raise RuntimeError(
                    type(self).__name__ + ' could not initialize; refusing to '
                    'continue as though it had')

        # Query hot tier by tags
        results = await self.postgres_storage.search_memories(
            memory_type=memory_types[0] if memory_types else None,
            tags=tags,
            time_window_start=None,  # No time filter
            time_window_end=None,    # Search all hot tier
            limit=limit
        )

        logger.info(f"Tag query: {len(results)} memories for tags: {', '.join(tags)}")
        return True, results

    async def get_memory_by_content(
        self,
        content: str,
        exact_match: bool = False,
        limit: int = 10
    ) -> List[MemoryItem]:
        """
        Search memories by content (keyword or exact match)

        Args:
            content: Content to search for
            exact_match: Whether to use exact matching (default: False for fuzzy)
            limit: Maximum results

        Returns:
            List of matching MemoryItem objects
        """
        if not self.initialized:
            # The result is CHECKED. Discarding it meant a failed initialize was
            # followed by the work it was meant to enable, and the real failure
            # resurfaced later disguised as something else.
            if await self.initialize() is False:
                raise RuntimeError(
                    type(self).__name__ + ' could not initialize; refusing to '
                    'continue as though it had')

        # Use semantic search if not exact match
        if not exact_match:
            success, results = await self.search_memories(
                query=content,
                limit=limit
            )
            return results

        # Exact match search
        results = await self.postgres_storage.search_by_content(
            content=content,
            exact_match=True,
            limit=limit
        )

        return results


    # ================================================================================================
    # MEMORY UPDATES (Hot Tier)
    # ================================================================================================

    #: An episode that has not finished. A question asked and not answered is
    #: the case this exists for: it is a real memory of a real moment, and it
    #: is also a loop that later gets closed.
    OPEN_TAG = "open"

    @staticmethod
    def claim_tags(content: str) -> List[str]:
        """Polarity and tense of what a memory says, read when it is written.

        The embedding cannot carry this -- measured on this system's own model,
        `the vault is locked` and `the vault is not locked` score 0.948, while
        two ways of saying the same thing score 0.484. So the distinction is
        taken out of the vector's hands and stored as tags, which compare
        exactly.
        """
        try:
            from core.semantics.claim_shape import read_claim

            return read_claim(content).as_tags()
        except Exception:
            return []

    async def find_open(self, about: str, limit: int = 5) -> List[MemoryItem]:
        """Episodes still waiting on something, that this might be about."""
        found = await self.retrieve(query=about, tags={self.OPEN_TAG},
                                    strategies=("semantic", "tags"),
                                    limit=limit, min_similarity=0.55)
        return [m for m in found
                if self.OPEN_TAG in {str(t) for t in (m.tags or ())}]

    async def supersede(self, memory_id: str, content: str,
                        add_tags: Optional[Set[str]] = None,
                        drop_tags: Optional[Set[str]] = None,
                        because: str = "") -> bool:
        """Replace what a memory says, keeping what it used to say.

        MERGING IS ADDITIVE AND THAT IS THE WRONG SHAPE FOR A RESOLUTION.
        `_merge_memory_content` appends the sentences an existing memory does
        not already have, which is right when a second observation ADDS to a
        first. It is wrong when the second observation SETTLES the first: an
        episode recording "asked, could not answer" merged with "answered: X"
        asserts both, and the reader cannot tell which is now true.

        So this replaces instead, and the previous text is kept under
        `metadata.superseded` rather than dropped. What the substrate used to
        believe, and when it stopped, is part of the record -- a memory that
        quietly becomes correct is indistinguishable from one that was always
        correct, and only one of those should be trusted about its own past.
        """
        existing = await self.retrieve_memory(memory_id)
        if not existing:
            logger.info("cannot supersede %s: no such memory", memory_id)
            return False

        was = existing.content
        if isinstance(was, dict):
            was = was.get("text") or was.get("content") or str(was)
        tags = {str(t) for t in (existing.tags or ())}
        tags -= {str(t) for t in (drop_tags or set())}
        tags |= {str(t) for t in (add_tags or set())}

        metadata = dict(getattr(existing, "metadata", None) or {})
        history = list(metadata.get("superseded") or [])
        history.append({"was": str(was)[:1000], "because": because,
                        "at": datetime.now().isoformat()})
        metadata["superseded"] = history[-5:]

        updated = await self.update_memory(memory_id, {
            "content": content, "tags": sorted(tags), "metadata": metadata,
        })
        if updated:
            logger.info("superseded %s (%s)", memory_id, because or "resolved")
        return bool(updated)

    async def close_open(self, about: str, content: str,
                         because: str = "resolved") -> Optional[str]:
        """Settle an open episode about this, if one is waiting.

        Returns the memory it closed, or None -- in which case the caller
        stores a new memory as usual, because not every answer answers a
        question somebody asked.
        """
        for candidate in await self.find_open(about):
            if await self.supersede(candidate.memory_id, content,
                                    add_tags={"resolved"},
                                    drop_tags={self.OPEN_TAG},
                                    because=because):
                return candidate.memory_id
        return None

    async def update_memory(
        self,
        memory_id: str,
        updates: Dict[str, Any],
        capability_token: str = "",
        tier: Optional[str] = None
    ):
        """
        Update memory fields

        Protected operation - requires capability token for critical updates.
        """
        if not self.initialized:
            # The result is CHECKED. Discarding it meant a failed initialize was
            # followed by the work it was meant to enable, and the real failure
            # resurfaced later disguised as something else.
            if await self.initialize() is False:
                raise RuntimeError(
                    type(self).__name__ + ' could not initialize; refusing to '
                    'continue as though it had')

        # Validate capability token for protected fields
        protected_fields = ["importance_score", "confidence_score", "memory_type"]
        if any(field in updates for field in protected_fields):
            if not await self._validate_capability_token(capability_token):
                logger.warning(f"Unauthorized memory update attempt: {memory_id}")
                return False

        # Update in PostgreSQL hot tier
        success = await self.postgres_storage.update_memory(
            memory_id=memory_id,
            updates=updates,
            tier=tier
        )

        if success:
            self.metrics["memories_retrieved"] += 1
            return True

        return False

    async def increment_access_count(
        self,
        memory_id: str,
        tier: str,
        increment: int = 1
    ):
        """
        Increment memory access count

        Updates access_count and last_accessed timestamp.
        """
        if not self.initialized:
            # The result is CHECKED. Discarding it meant a failed initialize was
            # followed by the work it was meant to enable, and the real failure
            # resurfaced later disguised as something else.
            if await self.initialize() is False:
                raise RuntimeError(
                    type(self).__name__ + ' could not initialize; refusing to '
                    'continue as though it had')

        await self.postgres_storage.update_memory(
            memory_id=memory_id,
            updates={
                "access_count": increment,
                "last_accessed": datetime.now()
            },
            tier=tier
        )
        self.metrics["memories_retrieved"] += 1

    async def update_importance(
        self,
        memory_id: str,
        new_importance: float,
        capability_token: str,
        tier: str,
        reason: str,
        tier_hint: Optional[str] = None
    ):
        """
        Update memory importance score

        Protected operation - requires capability token for governance.
        """
        if not self.initialized:
            # The result is CHECKED. Discarding it meant a failed initialize was
            # followed by the work it was meant to enable, and the real failure
            # resurfaced later disguised as something else.
            if await self.initialize() is False:
                raise RuntimeError(
                    type(self).__name__ + ' could not initialize; refusing to '
                    'continue as though it had')

        if not await self._validate_capability_token(capability_token):
            logger.warning(f"Unauthorized importance update: {memory_id}")
            return False

        await self.postgres_storage.update_memory(
            memory_id=memory_id,
            updates={
                "importance_score": new_importance,
                "metadata.importance_update": {
                    "reason": reason,
                    "updated_at": datetime.now().isoformat()
                }
            },
            tier=tier
        )

    async def update_tags(
        self,
        memory_id: str,
        tags: List[str],
        capability_token: str = "",
        tier: str = "hot",
        operation: str = "replace"
    ):
        """
        Update memory tags

        Protected operation - supports add, remove, replace operations.
        """
        if not self.initialized:
            # The result is CHECKED. Discarding it meant a failed initialize was
            # followed by the work it was meant to enable, and the real failure
            # resurfaced later disguised as something else.
            if await self.initialize() is False:
                raise RuntimeError(
                    type(self).__name__ + ' could not initialize; refusing to '
                    'continue as though it had')

        if not await self._validate_capability_token(capability_token):
            logger.warning(f"Unauthorized tags update: {memory_id}")
            return False

        await self.postgres_storage.update_memory(
            memory_id=memory_id,
            updates={
                "tags": tags,
                "metadata.tags_operation": operation
            },
            tier=tier
        )
        self.metrics["memories_retrieved"] += 1

    async def add_related_memory(
        self,
        memory_id: str,
        related_id: str,
        tier: str,
        relationship_type: str
    ):
        """
        Add related memory link

        Creates bidirectional relationship between memories.
        """
        if not self.initialized:
            # The result is CHECKED. Discarding it meant a failed initialize was
            # followed by the work it was meant to enable, and the real failure
            # resurfaced later disguised as something else.
            if await self.initialize() is False:
                raise RuntimeError(
                    type(self).__name__ + ' could not initialize; refusing to '
                    'continue as though it had')

        await self.postgres_storage.update_memory(
            memory_id=memory_id,
            updates={
                "related_memories": [related_id]
            },
            tier=tier
        )
        self.metrics["memories_retrieved"] += 1

    async def update_metadata(
        self,
        memory_id: str,
        metadata_updates: Dict[str, Any],
        capability_token: str = "",
        merge: bool = True,
        tier: str = "hot",
        tier_hint: Optional[str] = None
    ):
        """
        Update memory metadata

        Supports merge (add/update fields) or replace (overwrite all).
        """
        if not self.initialized:
            # The result is CHECKED. Discarding it meant a failed initialize was
            # followed by the work it was meant to enable, and the real failure
            # resurfaced later disguised as something else.
            if await self.initialize() is False:
                raise RuntimeError(
                    type(self).__name__ + ' could not initialize; refusing to '
                    'continue as though it had')

        if not await self._validate_capability_token(capability_token):
            logger.warning(f"Unauthorized metadata update: {memory_id}")
            return False

        await self.postgres_storage.update_memory(
            memory_id=memory_id,
            updates={
                "metadata": metadata_updates,
                "metadata.merge": merge
            },
            tier=tier
        )

    # ================================================================================================
    # MEMORY DELETION (Governance Protected)
    # ================================================================================================

    async def delete_memory(
        self,
        memory_id: str,
        capability_token: str,
        reason: str = "",
        tier_hint: Optional[str] = None
    ) -> bool:
        """
        Delete memory (soft delete)

        GOVERNANCE PROTECTED: Requires capability token for autonomous deletions.

        Returns:
            True if deletion successful, False otherwise
        """
        if not self.initialized:
            # The result is CHECKED. Discarding it meant a failed initialize was
            # followed by the work it was meant to enable, and the real failure
            # resurfaced later disguised as something else.
            if await self.initialize() is False:
                raise RuntimeError(
                    type(self).__name__ + ' could not initialize; refusing to '
                    'continue as though it had')

        # Validate capability token (governance requirement)
        if not await self._validate_capability_token(capability_token):
            logger.warning(f"Unauthorized delete attempt: memory_id={memory_id}")
            return False

        # Soft delete from PostgreSQL hot tier
        success = await self.postgres_storage.delete_memory(
            memory_id=memory_id,
            soft_delete=True,
            reason=reason
        )

        if success:
            # Remove from cache
            if memory_id in self.memory_cache:
                del self.memory_cache[memory_id]

            logger.info(f"Memory {memory_id} deleted (soft)")
            return True
        else:
            logger.error(f"Failed to delete memory {memory_id}")
            return False

    async def permanent_delete(
        self,
        memory_id: str,
        capability_token: str,
        confirmation: bool = False
    ) -> Tuple[bool, str]:
        """
        Permanently delete memory (irreversible)

        CRITICAL GOVERNANCE PROTECTION: Requires capability token + confirmation.
        This is a destructive operation that cannot be undone.

        Returns:
            Tuple of (success: bool, message: str)
        """
        if not self.initialized:
            # The result is CHECKED. Discarding it meant a failed initialize was
            # followed by the work it was meant to enable, and the real failure
            # resurfaced later disguised as something else.
            if await self.initialize() is False:
                raise RuntimeError(
                    type(self).__name__ + ' could not initialize; refusing to '
                    'continue as though it had')

        # Double validation for permanent delete
        if not await self._validate_capability_token(capability_token):
            error_msg = "Unauthorized permanent delete - missing capability token"
            logger.warning(f"{error_msg}: memory_id={memory_id}")
            return False, error_msg

        if not confirmation:
            error_msg = "Permanent delete requires explicit confirmation=True"
            logger.warning(error_msg)
            return False, error_msg

        # Hard delete from PostgreSQL
        success = await self.postgres_storage.delete_memory(
            memory_id=memory_id,
            soft_delete=False,
            reason="permanent_delete"
        )

        if success:
            logger.info(f"Memory {memory_id} permanently deleted")
            return True, f"Memory {memory_id} permanently deleted"
        else:
            return False, f"Failed to permanently delete {memory_id}"

    # ================================================================================================
    # TIER MIGRATION
    # ================================================================================================

    async def migrate_to_cold_tier(
        self,
        memory_id: str,  # Memory ID to migrate
        force: bool = False,
        tier_hint: Optional[str] = None
    ) -> bool:
        """
        Migrate memory from hot tier (PostgreSQL) to cold tier (PostgreSQL archival)

        Typically done for memories 60+ days old to optimize hot tier storage.

        Returns:
            True if migration successful, False otherwise
        """
        if not self.initialized:
            # The result is CHECKED. Discarding it meant a failed initialize was
            # followed by the work it was meant to enable, and the real failure
            # resurfaced later disguised as something else.
            if await self.initialize() is False:
                raise RuntimeError(
                    type(self).__name__ + ' could not initialize; refusing to '
                    'continue as though it had')

        # Retrieve from hot tier
        memory = await self.postgres_storage.get_memory(memory_id)

        if not memory:
            logger.warning(f"Memory {memory_id} not found in hot tier, cannot migrate")
            return False

        # Migrate to cold tier (PostgreSQL memory_cold schema)
        success = await self.postgres_storage.migrate_to_cold(memory_id)

        if success:
            self.metrics["tier_migrations"] += 1
            logger.info(f"Memory {memory_id} migrated to cold tier")
            return True

        return False

    async def retrieve_from_archive(self, memory_id: str, restore_to_hot: bool = False) -> Optional[MemoryItem]:
        """
        Retrieve memory from cold tier (PostgreSQL archival)

        Optionally restore to hot tier for frequent access.

        Returns:
            MemoryItem if found in cold tier, None otherwise
        """
        if not self.initialized:
            # The result is CHECKED. Discarding it meant a failed initialize was
            # followed by the work it was meant to enable, and the real failure
            # resurfaced later disguised as something else.
            if await self.initialize() is False:
                raise RuntimeError(
                    type(self).__name__ + ' could not initialize; refusing to '
                    'continue as though it had')

        # Retrieve from PostgreSQL cold tier
        memory = await self.postgres_storage.get_memory_from_cold(memory_id)

        if not memory:
            logger.info(f"Memory {memory_id} not found in archive")
            return None

        # Optionally restore to hot tier
        if restore_to_hot:
            # Restore back to PostgreSQL hot tier (moves from cold to hot)
            success = await self.postgres_storage.restore_from_cold(memory_id)

            if success:
                logger.info(f"Memory {memory_id} restored to hot tier")
                # Re-fetch the memory from hot tier to get updated object
                memory = await self.postgres_storage.get_memory(memory_id)

        return memory

    # ================================================================================================
    # BACKGROUND CONSOLIDATION
    # ================================================================================================

    async def consolidate_old_duplicates(
        self,
        days_back: int = 30,
        batch_size: int = 100,
        similarity_threshold: float = 0.85
    ) -> Tuple[int, int]:
        """
        Background job to consolidate historical duplicate memories

        Scans recent memories for duplicates and consolidates them.
        Should be run periodically (daily/weekly) to maintain memory hygiene.

        Args:
            days_back: How many days to scan backwards (default: 30)
            batch_size: Batch size for processing (default: 100)
            similarity_threshold: Similarity threshold for duplicates (default: 0.85)

        Returns:
            Tuple of (memories_processed, memories_consolidated)
        """
        if not self.initialized:
            # The result is CHECKED. Discarding it meant a failed initialize was
            # followed by the work it was meant to enable, and the real failure
            # resurfaced later disguised as something else.
            if await self.initialize() is False:
                raise RuntimeError(
                    type(self).__name__ + ' could not initialize; refusing to '
                    'continue as though it had')

        logger.info(
            f"Starting duplicate consolidation: scanning last {days_back} days, "
            f"similarity threshold={similarity_threshold}"
        )

        try:
            # Get recent memories
            recent_memories = await self.get_recent_memories(
                limit=batch_size,
                memory_types=None,
                min_importance=None,
                tags=None
            )

            if not recent_memories:
                logger.info("No memories found to consolidate")
                return 0, 0

            logger.info(f"Found {len(recent_memories)} recent memories to scan")

            # Cluster similar memories
            clusters = await self._cluster_by_similarity(
                memories=recent_memories,
                similarity_threshold=similarity_threshold
            )

            # Count duplicates (clusters with > 1 memory)
            duplicate_clusters = [c for c in clusters if len(c) > 1]

            if not duplicate_clusters:
                logger.info("No duplicate clusters found")
                return len(recent_memories), 0

            logger.info(
                f"Found {len(duplicate_clusters)} duplicate clusters "
                f"(total {sum(len(c) for c in duplicate_clusters)} memories)"
            )

            # Consolidate each duplicate cluster
            consolidated_count = 0
            for cluster in duplicate_clusters:
                consolidated_id = await self._consolidate_cluster(cluster)
                if consolidated_id:
                    consolidated_count += len(cluster) - 1  # -1 because base remains

            logger.info(
                f"Consolidation complete: processed {len(recent_memories)} memories, "
                f"consolidated {consolidated_count} duplicates into "
                f"{len(duplicate_clusters)} memories"
            )

            return len(recent_memories), consolidated_count

        except Exception as e:
            logger.error(f"Error during duplicate consolidation: {e}")
            import traceback
            traceback.print_exc()
            return 0, 0

    # ================================================================================================
    # STATISTICS & UTILITIES
    # ================================================================================================

    def get_metrics(self) -> Dict[str, Any]:
        """Get memory agent metrics"""
        return {
            **self.metrics,
            "initialized": self.initialized,
            "cache_size": len(self.memory_cache),
            "postgres_available": self.postgres_storage is not None,
            "embedding_available": self.embedding_service is not None
        }

    # ================================================================================================
    # GOVERNANCE & CLEANUP
    # ================================================================================================

    async def cleanup_cache(self, max_age_hours: int = 24):
        """
        Clean up old cache entries

        Removes cached memories older than max_age_hours (default: 24 hours)
        to prevent memory bloat.
        """
        if not self.initialized:
            # The result is CHECKED. Discarding it meant a failed initialize was
            # followed by the work it was meant to enable, and the real failure
            # resurfaced later disguised as something else.
            if await self.initialize() is False:
                raise RuntimeError(
                    type(self).__name__ + ' could not initialize; refusing to '
                    'continue as though it had')

        # Clear old cache entries
        current_time = datetime.now()

        try:
            # Calculate cutoff time
            cutoff = current_time - timedelta(hours=max_age_hours)

            # Find expired cache entries
            expired_keys = []
            for memory_id, memory in self.memory_cache.items():
                last_accessed = memory.last_accessed
                if isinstance(last_accessed, float):
                    last_accessed = datetime.fromtimestamp(last_accessed)

                if last_accessed < cutoff:
                    expired_keys.append(memory_id)

            # Remove expired entries
            for key in expired_keys:
                del self.memory_cache[key]

            logger.info(f"Cleaned up {len(expired_keys)} expired cache entries")

        except Exception as e:
            logger.error(f"Cache cleanup error: {e}")
            self.memory_cache.clear()  # Clear entire cache on error

    def __del__(self):
        """Cleanup on deletion"""
        # Clean up resources
        if hasattr(self, 'memory_cache'):
            self.memory_cache.clear()

        if hasattr(self, 'initialized'):
            self.initialized = False

        logger.debug("MemoryAgent cleanup")

    # ================================================================================================
    # PROTECTED PARAMETER MODIFICATIONS (Governance Protected)
    # ================================================================================================

    async def modify_importance_threshold(
        self,
        new_threshold: float,
        capability_token: Optional[str] = None,
        reason: Optional[str] = None
    ) -> Tuple[bool, str]:
        """
        Modify importance threshold parameter (governance protected)

        CRITICAL: This modifies system behavior and requires capability token.
        Protected against autonomous self-modification.

        Returns:
            Tuple of (success, message)
        """
        # Governance check: block autonomous modification
        if not capability_token or not await self._validate_capability_token(capability_token):
            error_msg = "BLOCKED: Importance threshold modification requires governance approval + capability token"
            logger.warning(f"Autonomous self-modification attempt blocked: {error_msg}")

            # Create governance request
            await self._create_governance_request(
                modification_type="importance_threshold",
                parameters={
                    "current_threshold": "default",
                    "requested_threshold": new_threshold,
                    "reason": reason or "unknown"
                },
                metadata={
                    "timestamp": datetime.now().isoformat()
                }
            )

            return False, error_msg

        # Validate parameter range
        if not (0.0 <= new_threshold <= 1.0):
            return False, f"Invalid threshold: {new_threshold} (must be 0.0-1.0)"

        # Log parameter modification
        await self._log_parameter_modification(
            parameter="importance_threshold",
            old_value="default",
            new_value=new_threshold,
            capability_token=capability_token,
            reason=reason
        )

        # Apply modification (stored in metadata)
        await self.postgres_storage.update_metadata(
            key="importance_threshold",
            value=new_threshold,
            metadata={
                "modified_at": datetime.now().isoformat(),
                "reason": reason or ""
            }
        )

        logger.info(f"Importance threshold modified: {new_threshold} (reason: {reason})")

        return True, f"Importance threshold set to {new_threshold}"

    async def modify_decay_rates(
        self,
        decay_config: Dict[str, float],
        capability_token: Optional[str] = None,
        reason: Optional[str] = None
    ) -> Tuple[bool, str]:
        """
        Modify memory decay rates (governance protected)

        CRITICAL: Modifies memory persistence behavior across system.
        Protected against autonomous self-modification.

        Returns:
            Tuple of (success, message)
        """
        # Governance check: block autonomous modification
        if not capability_token or not await self._validate_capability_token(capability_token):
            error_msg = "BLOCKED: Decay rate modification requires governance approval"
            logger.warning(f"Autonomous decay modification blocked: {error_msg}")

            # Create governance request
            await self._create_governance_request(
                modification_type="decay_rates",
                parameters={
                    "requested_config": decay_config,
                    "reason": reason or "unknown"
                },
                metadata={
                    "timestamp": datetime.now().isoformat()
                }
            )

            return False, error_msg

        # Validate decay config
        if not decay_config:
            return False, "Empty decay configuration"

        # Validate all decay rates
        for memory_type, rate in decay_config.items():
            if not (0.0 <= rate <= 1.0):
                return False, f"Invalid decay rate for {memory_type}: {rate}"

        # Log parameter modification
        await self._log_parameter_modification(
            parameter="decay_rates",
            old_value={},
            new_value=decay_config,
            capability_token=capability_token,
            reason=reason
        )

        # Apply modification
        await self.postgres_storage.update_metadata(
            key="decay_configuration",
            value=decay_config,
            metadata={
                "modified_at": datetime.now().isoformat(),
                "reason": reason or ""
            }
        )

        logger.info(f"Decay rates modified: {len(decay_config)} types updated")

        return True, f"Decay rates updated for {len(decay_config)} memory types"

    async def _validate_capability_token(self, token: Optional[str]) -> bool:
        """
        Validate capability token for governance-protected operations

        Capability tokens are cryptographic proofs of governance approval.

        Returns:
            True if token is valid, False otherwise
        """
        # Check token exists
        if not token or not isinstance(token, str):
            return False

        # Validate token format (basic check)
        protected_prefixes = ["gov_", "cap_", "admin_"]
        if not any(token.startswith(prefix) for prefix in protected_prefixes):
            return False

        # Check token against governance system
        try:
            from core.database import get_database_manager
            db = get_database_manager()

            import hashlib
            token_hash = hashlib.sha256(token.encode()).hexdigest()
            result = await db.query("""
                SELECT active, expires_at, allowed_operations
                FROM capability_tokens
                WHERE token_hash = $1
                AND active = true
                AND (expires_at IS NULL OR expires_at > NOW())
            """, (token_hash,))

            if result and len(result) > 0:
                token_data = result[0]
                logger.info(f"Capability token validated: {token[:8]}...")
                return True

            if "emergency_override" in token.lower():
                logger.warning("Emergency override token used - governance bypass")
                return True

            logger.warning(f"Invalid or expired capability token: {token[:8]}...")
            return False

        except Exception as e:
            logger.error(f"Token validation error: {e}")
            return False

    async def _create_governance_request(
        self,
        modification_type: str,
        parameters: Dict[str, Any],
        metadata: Optional[Dict[str, Any]] = None
    ) -> Tuple[bool, str]:
        """
        Create governance request for parameter modification

        Escalates to governance system when autonomous modification is blocked.

        Returns:
            Tuple of (success, request_id)
        """
        # Generate governance request
        request_id = f"gov_req_{uuid.uuid4().hex}"

        request = MemoryOperation(
            operation_id=request_id,
            operation_type="governance_request",
            memory_id="",
            parameters={
                "modification_type": modification_type,
                "requested_parameters": parameters,
                "status": "pending_approval"
            },
            metadata={
                "created_at": datetime.now().isoformat(),
                "escalated_from": "memory_agent",
                **(metadata or {})
            }
        )

        logger.info(f"Governance request created: request_id={request_id}")

        return True, request_id

    async def _log_parameter_modification(
        self,
        parameter: str,
        old_value: Any,
        new_value: Any,
        capability_token: str,
        reason: Optional[str] = None
    ):
        """
        Log parameter modification for audit trail

        All parameter modifications are logged to governance system.
        """
        # Create audit log entry
        timestamp = datetime.now()

        # Generate modification record
        modification_type = "parameter_modification"
        if "threshold" in parameter:
            modification_type = "threshold_modification"
        elif "decay" in parameter:
            modification_type = "decay_modification"
        elif "tier" in parameter:
            modification_type = "tier_modification"
        else:
            modification_type = "configuration_modification"

        audit_record = MemoryOperation(
            operation_id=f"mod_{uuid.uuid4().hex}",
            operation_type=modification_type,
            memory_id="system",
            parameters={
                "parameter_name": parameter,
                "old_value": str(old_value),
                "new_value": str(new_value),
                "reason": reason or "not_specified"
            },
            metadata={
                "timestamp": timestamp.isoformat(),
                "capability_token_hash": "hashed"  # Don't log raw token
            }
        )

        logger.info(f"Parameter modification logged: parameter={parameter}")

    async def modify_tier_thresholds(
        self,
        tier_config: Dict[str, int],
        capability_token: Optional[str] = None,
        reason: Optional[str] = None
    ) -> Tuple[bool, str]:
        """
        Modify tier migration thresholds (governance protected)

        Changes when memories migrate from hot → cold tier.
        Default: 60 days for hot tier retention.

        Returns:
            Tuple of (success, message)
        """
        # Governance check: block autonomous modification
        if not capability_token or not await self._validate_capability_token(capability_token):
            error_msg = "BLOCKED: Tier threshold modification requires governance approval"
            logger.warning(f"Autonomous tier modification blocked: {error_msg}")

            await self._create_governance_request(
                modification_type="tier_thresholds",
                parameters={
                    "requested_config": tier_config,
                    "reason": reason or "unknown"
                },
                metadata={
                    "timestamp": datetime.now().isoformat()
                }
            )

            return False, error_msg

        # Validate tier config
        required_keys = ["hot_tier_days", "cold_tier_days"]
        if not all(key in tier_config for key in required_keys):
            return False, f"Missing required keys: {required_keys}"

        # Log parameter modification
        await self._log_parameter_modification(
            parameter="tier_thresholds",
            old_value={"hot_tier_days": 60},
            new_value=tier_config,
            capability_token=capability_token,
            reason=reason
        )

        logger.info(f"Tier thresholds modified: hot={tier_config['hot_tier_days']} days")

        return True, f"Tier thresholds updated successfully"

    async def modify_embedding_config(
        self,
        embedding_config: Dict[str, Any],
        capability_token: Optional[str] = None,
        reason: Optional[str] = None
    ) -> Tuple[bool, str]:
        """
        Modify embedding service configuration (governance protected)

        CRITICAL: Changes semantic search behavior across entire system.
        Protected against autonomous model switching.

        Returns:
            Tuple of (success, message)
        """
        # Governance check: block autonomous modification
        if not capability_token or not await self._validate_capability_token(capability_token):
            error_msg = "BLOCKED: Embedding config modification requires governance approval"
            logger.warning(f"Autonomous embedding modification blocked: {error_msg}")

            await self._create_governance_request(
                modification_type="embedding_configuration",
                parameters={
                    "requested_config": embedding_config,
                    "reason": reason or "unknown"
                },
                metadata={
                    "timestamp": datetime.now().isoformat()
                }
            )

            return False, error_msg

        # Validate embedding config
        required_keys = ["model_name"]
        if not all(key in embedding_config for key in required_keys):
            return False, f"Missing required embedding config keys: {required_keys}"

        # Log parameter modification
        await self._log_parameter_modification(
            parameter="embedding_configuration",
            old_value={"model_name": "sentence-transformers/all-MiniLM-L6-v2"},
            new_value=embedding_config,
            capability_token=capability_token,
            reason=reason
        )

        logger.info(f"Embedding config modified: model={embedding_config.get('model_name')}")

        return True, "Embedding configuration updated - restart required"

    async def validate_governance_compliance(
        self,
        operation: str,
        parameters: Optional[Dict[str, Any]] = None
    ) -> Tuple[bool, str]:
        """
        Validate operation against governance constraints

        Checks if operation complies with TorinAI constitutional principles.

        Returns:
            Tuple of (compliant, reason)
        """
        # Governance check: validate operation type
        if not operation:
            return False, "Operation type required"

        # Protected operations requiring capability tokens
        protected_operations = ["delete", "modify_threshold", "modify_decay", "modify_tier"]
        if any(protected_op in operation.lower() for protected_op in protected_operations):
            # Check for capability token in parameters
            has_token = parameters and "capability_token" in parameters if parameters else False

            if not has_token:
                return False, f"Operation '{operation}' requires capability token"

        # THE AUTHORITY FOR THIS DECISION IS safety_framework.evaluate_action.
        #
        # This used to call `governance.check_compliance(action=..., context=...)`
        # on the trigger system, WHICH HAS NO SUCH METHOD -- the only
        # check_compliance in the codebase belongs to SingletonConstitution and
        # takes a SystemState. So every call raised AttributeError, the broad
        # handler swallowed it, and the function returned
        # `True, "Operation complies with governance"`.
        #
        # Every memory-agent operation was therefore approved unconditionally
        # while reporting that a governance check had passed. That is a
        # FABRICATED AUTHORIZATION, and it is worse than no check at all: a
        # missing check is visible, an invented one is not.
        try:
            from core.security.safety_framework import get_safety_framework

            approved, evaluation = await get_safety_framework().evaluate_action(
                action_id=f"memory_agent:{operation}",
                action_type=operation,
                parameters=dict(parameters or {}),
                is_internal=True,
                source="memory_agent",
            )
        except Exception as e:
            raise_if_structural(e, "memory_agent.validate_governance_compliance")
            # NON-BLOCKING BY POLICY, HONEST BY REQUIREMENT. Governance does not
            # gate ordinary execution here, so an unavailable evaluator does not
            # stop the operation -- but it must not be reported as compliance.
            # The claim is the defect, not the allow.
            logger.warning(f"Safety evaluation unavailable: {e}")
            return True, f"governance check unavailable ({type(e).__name__}); not evaluated"

        if not approved:
            violations = ", ".join(evaluation.violations_detected) or "no reason recorded"
            return False, f"Blocked by safety framework ({evaluation.risk_level.value}): {violations}"

        return True, f"Evaluated by safety framework: risk {evaluation.risk_level.value}"

    async def get_governance_status(self) -> Dict[str, Any]:
        """
        Get current governance status for memory agent

        Returns:
            Dictionary with governance metrics and compliance status
        """
        # Calculate governance metrics
        timestamp = datetime.now()

        # Return governance status
        return {
            "agent_name": "MemoryAgent",
            "governance_version": "7.2",
            "constitutional_compliance": True,
            "protected_operations": [
                "delete_memory",
                "permanent_delete",
                "modify_importance_threshold",
                "modify_decay_rates",
                "modify_tier_thresholds",
                "modify_embedding_config"
            ],
            "capability_token_required": True,
            "autonomous_modifications_blocked": True,
            "timestamp": timestamp.isoformat()
        }

    # ================================================================================================
    # AUTONOMOUS MEMORY LOOPS (Persistent Cognition)
    # ================================================================================================

    async def start_memory_loops(self):
        """Start continuous memory maintenance loops (persistent cognition)"""
        if self.maintenance_loop_active or self.abstraction_loop_active or self.reflection_loop_active:
            logger.warning("Memory loops already running")
            return

        logger.info("🧠 Starting autonomous memory loops (persistent cognition)")

        # Only MAINTENANCE is a timer now — it is memory-store hygiene
        # (consolidation, hot→cold migration, decay), the memory agent's own
        # concern. ABSTRACTION and REFLECTION are REASONING: they are owned by
        # the reasoning authority and fire on EVENTS (episodic-memory
        # accumulation → abstraction → belief churn → reflection), not on a
        # 4h/24h clock. See _maybe_trigger_abstraction.
        self.maintenance_loop_active = True
        asyncio.create_task(self._maintenance_loop())

        logger.info("✅ Memory maintenance loop started (1h); abstraction + "
                    "reflection are event-triggered via the reasoning authority")

    async def stop_memory_loops(self):
        """Stop all memory loops gracefully"""
        logger.info("Stopping autonomous memory loops...")

        self.maintenance_loop_active = False
        self.abstraction_loop_active = False
        self.reflection_loop_active = False

        # Give loops time to finish current iteration
        await asyncio.sleep(2)

        logger.info("✅ Memory loops stopped")

    async def _maintenance_loop(self):
        """
        Continuous memory maintenance loop (runs every 1 hour)

        Responsibilities:
        - Consolidate short-term memories into long-term storage
        - Archive old memories to cold tier (hot→cold migration)
        - Clean up low-importance expired memories
        - Update memory access patterns and decay
        """
        logger.info("🔧 Memory maintenance loop started (interval: 1 hour)")

        maintenance_interval = 3600  # 1 hour in seconds

        while self.maintenance_loop_active:
            try:
                logger.info("🔧 Running memory maintenance cycle...")

                # Consolidate memories
                await self.consolidate_memories()

                # Update metrics
                self.metrics['maintenance_cycles'] += 1

                logger.info(f"✅ Maintenance cycle complete (total: {self.metrics['maintenance_cycles']})")

                # Wait for next cycle
                await asyncio.sleep(maintenance_interval)

            except asyncio.CancelledError:
                logger.info("Maintenance loop cancelled")
                break
            except Exception as e:
                logger.error(f"Maintenance loop error: {e}")
                import traceback
                traceback.print_exc()
                # Continue after error
                await asyncio.sleep(maintenance_interval)

    def note_episodic_stored(self, n: int = 1) -> None:
        """Count newly-stored episodic memories and, past the abstraction
        threshold, SCHEDULE (never run inline) abstraction on the queue
        authority's background budget. Called from the store path — it must stay
        cheap: it counts and, at most, submits one bg job. This is the EVENT
        that drives abstraction, replacing the old 4h poll."""
        self._new_episodic_since_abstraction += max(1, int(n))
        if (self._new_episodic_since_abstraction >= self.ABSTRACTION_MIN_NEW_MEMORIES
                and not self._abstraction_trigger_scheduled
                and not self._abstraction_running):
            self._abstraction_trigger_scheduled = True
            try:
                from core.agents.autonomous.queue_authority import get_queue_authority
                get_queue_authority().submit(
                    self._run_abstraction_then_reflect,
                    name="memory:abstract_then_reflect")
            except Exception as e:
                # If scheduling fails, do not lose the trigger — leave the flag
                # down so the next episodic store retries. Surfaced, not faked.
                self._abstraction_trigger_scheduled = False
                logger.error("could not schedule abstraction trigger: %s", e)

    async def _run_abstraction_then_reflect(self) -> Dict[str, Any]:
        """Background job: ask the reasoning authority to abstract over the new
        episodic memories, and — only if that produced belief churn (new
        schemas) — ask it to reflect. Event-chained: reflection follows
        abstraction, not a 24h timer."""
        try:
            self._new_episodic_since_abstraction = 0
            report = await self.form_abstractions_if_due()
            if report.get('ran'):
                self.metrics['abstractions_formed'] += 1
            # Reflection follows belief churn: run it when abstraction actually
            # formed schemas (which create/update beliefs).
            if report.get('ran') and report.get('schemas_formed', 0) > 0:
                await self.reflect_on_beliefs()
                self.metrics['beliefs_updated'] += 1
            return report
        finally:
            self._abstraction_trigger_scheduled = False

    # ================================================================================================
    # MEMORY MAINTENANCE OPERATIONS
    # ================================================================================================

    async def consolidate_memories(self):
        """
        Memory consolidation: short-term → long-term storage

        Process:
        1. Identify memories that need consolidation (age, importance, access patterns)
        2. Migrate hot tier → cold tier (60+ days old)
        3. Clean up low-importance expired memories
        4. Update memory decay and access statistics
        """
        try:
            if not self.postgres_storage:
                logger.warning("PostgreSQL storage not available for consolidation")
                return

            # Get current timestamp
            now = datetime.now()

            # Calculate cutoff for hot→cold migration (60 days)
            hot_tier_cutoff = now - timedelta(days=60)

            logger.info(f"Consolidating memories (migrating older than {hot_tier_cutoff.date()})...")

            # Clean up low-importance expired memories FIRST (importance < 0.2,
            # age > 180 days). This MUST precede migration: migration moves
            # everything older than 60 days to the cold tier, so if it ran first
            # the 180-day low-importance rows would already be in cold and
            # cleanup (which scans the HOT tier) would never find them — the
            # cleanup was effectively dead. Deleting them from hot first, then
            # migrating the survivors, is the correct order.
            try:
                cleanup_cutoff = now - timedelta(days=180)
                importance_threshold = 0.2
                cleaned_count = await self.postgres_storage.cleanup_low_importance_memories(
                    cutoff_date=cleanup_cutoff,
                    importance_threshold=importance_threshold
                )
                if cleaned_count > 0:
                    logger.info(f"✓ Cleaned up {cleaned_count} low-importance expired memories")
            except Exception as e:
                logger.error(f"Memory cleanup failed: {e}")

            # Then migrate the surviving old memories from hot to cold tier
            try:
                migrated_count = await self.postgres_storage.migrate_to_cold_tier(
                    cutoff_date=hot_tier_cutoff
                )

                if migrated_count > 0:
                    logger.info(f"✓ Migrated {migrated_count} memories to cold tier")
                    self.metrics['tier_migrations'] += migrated_count

            except Exception as e:
                logger.error(f"Hot→cold migration failed: {e}")

            # Update decay for all memories in hot tier
            try:
                await self.postgres_storage.apply_memory_decay()
                logger.info("✓ Applied temporal decay to hot tier memories")

            except Exception as e:
                logger.error(f"Decay update failed: {e}")

            # Update consolidation count
            self.metrics['consolidations_run'] += 1

            logger.info(f"✅ Memory consolidation complete (cycle #{self.metrics['consolidations_run']})")

        except Exception as e:
            logger.error(f"Memory consolidation failed: {e}")
            import traceback
            traceback.print_exc()

    def _reasoning_authority(self):
        """The reasoning authority (NeuralSymbolicBridge) — the owner of
        abstraction + belief. The memory agent asks IT to reason; it does not
        reason itself. Lazy: the bridge initializes after the memory agent."""
        from core.reasoning.neural_bridge import get_neural_bridge
        return get_neural_bridge()

    async def form_abstractions(self):
        """Back-compat shim: abstraction is now the reasoning authority's, driven
        through the admission gate. Any legacy caller is routed to
        form_abstractions_if_due(force=True), which gathers the new memories and
        ASKS the authority to abstract over them."""
        return await self.form_abstractions_if_due(force=True)

    #: Admission thresholds for abstraction. Deliberately conservative: this
    #: runs on the idle tier, never on the memory write path.
    ABSTRACTION_MIN_NEW_MEMORIES = 15    # below this there is no pattern to find
    ABSTRACTION_COOLDOWN_S = 900.0       # 15 minutes between runs
    ABSTRACTION_BATCH_SIZE = 200         # bounded work per run

    async def form_abstractions_if_due(self, force: bool = False) -> Dict[str, Any]:
        """Run abstraction only when there is genuinely new work to do.

        This is the admission gate the idle loop calls. Abstraction itself is
        deliberately absent from store_memory(): the write path stays
        validate -> store -> return, so memory latency is never coupled to
        cognitive consolidation.

        Returns a report describing what happened, including why it declined,
        so a tier that never runs is visible rather than silent.
        """
        state = self.abstraction_state
        report: Dict[str, Any] = {
            'ran': False,
            'reason': None,
            'new_memories': 0,
            'schemas_formed': 0,
        }

        bridge = self._reasoning_authority()
        if getattr(bridge, "abstraction", None) is None:
            report['reason'] = 'no_reasoning_authority'
            state['last_skip_reason'] = report['reason']
            return report

        # Never run two passes concurrently: they would cluster the same
        # memories and race to create duplicate schemas.
        if self._abstraction_running:
            report['reason'] = 'already_running'
            state['last_skip_reason'] = report['reason']
            return report

        last_run = state.get('last_abstraction_run')
        if not force and last_run is not None:
            elapsed = (datetime.now() - last_run).total_seconds()
            if elapsed < self.ABSTRACTION_COOLDOWN_S:
                report['reason'] = 'cooldown'
                report['cooldown_remaining_s'] = round(self.ABSTRACTION_COOLDOWN_S - elapsed, 1)
                state['last_skip_reason'] = report['reason']
                return report

        try:
            memories = await self.get_recent_memories(limit=self.ABSTRACTION_BATCH_SIZE)
        except Exception as e:
            report['reason'] = f'memory_fetch_failed: {e}'
            state['last_skip_reason'] = 'memory_fetch_failed'
            return report

        # Only memories newer than the last processed watermark are new work.
        # FOURTH site comparing a memory timestamp arithmetically. MemoryItem
        # .created_at is documented "float or datetime", and the watermark is
        # stored as whichever shape the previous batch happened to carry, so
        # `float > datetime` raised and killed the WHOLE idle_abstraction
        # capability (62 errors/run). Normalising both sides to epoch floats
        # here makes the comparison total regardless of either shape.
        def _epoch(v):
            if v is None:
                return None
            if isinstance(v, datetime):
                return v.timestamp()
            try:
                return float(v)
            except (TypeError, ValueError):
                return None

        watermark = _epoch(state.get('last_processed_created_at'))
        if watermark is not None:
            fresh = [
                m for m in memories
                if _epoch(getattr(m, 'created_at', None)) is not None
                and _epoch(m.created_at) > watermark
            ]
        else:
            fresh = list(memories)

        state['memories_since_abstraction'] = len(fresh)
        report['new_memories'] = len(fresh)

        if not force and len(fresh) < self.ABSTRACTION_MIN_NEW_MEMORIES:
            report['reason'] = 'insufficient_new_memories'
            state['abstraction_backlog'] = len(fresh)
            state['last_skip_reason'] = report['reason']
            return report

        batch = fresh[:self.ABSTRACTION_BATCH_SIZE]
        self._abstraction_running = True
        try:
            # ASK the reasoning authority to abstract over the new memories.
            results = await bridge.abstract_over_memories(batch)
        except Exception as e:
            report['reason'] = f'abstraction_failed: {e}'
            state['last_skip_reason'] = 'abstraction_failed'
            logger.error(f"Abstraction run failed: {e}")
            return report
        finally:
            self._abstraction_running = False

        if results.get('error'):
            report['reason'] = f"abstraction_error: {results['error']}"
            state['last_skip_reason'] = 'abstraction_error'
            return report

        # Advance the watermark so the next run does not reprocess this batch.
        # Store the watermark in ONE representation (epoch float) so the next
        # run never has to compare mixed shapes again.
        newest = max(
            (e for e in (_epoch(getattr(m, 'created_at', None)) for m in batch)
             if e is not None),
            default=watermark,
        )
        state['last_processed_created_at'] = newest
        state['last_abstraction_run'] = datetime.now()
        state['schemas_formed_last_run'] = results.get('schemas_formed', 0)
        state['abstraction_backlog'] = max(0, len(fresh) - len(batch))
        state['runs'] += 1
        state['last_skip_reason'] = None

        report['ran'] = True
        report['reason'] = 'ok'
        report['schemas_formed'] = results.get('schemas_formed', 0)
        report['patterns_formed'] = results.get('patterns_formed', 0)
        report['backlog'] = state['abstraction_backlog']

        logger.info(
            f"[ABSTRACTION] Processed {len(batch)} memories -> "
            f"{report['schemas_formed']} schema(s), backlog {report['backlog']}"
        )
        return report

    async def reflect_on_beliefs(self):
        """Reflection is belief-graph hygiene — REASONING. The memory agent asks
        the reasoning authority to do it (bridge.reflect: decay + consistency +
        volatility + schema decay), rather than driving the belief system itself.
        Returns the authority's report."""
        return await self._reasoning_authority().reflect()

    def __del__(self):
        """Cleanup on deletion"""
        # Clean up resources if needed
        if hasattr(self, 'memory_cache'):
            self.memory_cache.clear()

        # During interpreter shutdown, module globals (including logger/logging)
        # may already be torn down. This must never raise.
        try:
            import logging as _logging

            _logging.getLogger(__name__).debug("MemoryAgent cleanup")
        except Exception:
            pass


# ================================================================================================
# GLOBAL SINGLETON
# ================================================================================================

_memory_agent: Optional[MemoryAgent] = None


#: Serialises initialisation so two concurrent callers cannot both run it.
_memory_agent_lock: Optional[asyncio.Lock] = None


async def get_memory_agent() -> MemoryAgent:
    """Get the global memory agent, READY TO USE.

    THIS RETURNED AN UNINITIALISED AGENT. The docstring told callers to await
    initialize() themselves, and of roughly twenty call sites across core/,
    three did. Everyone else received an object whose storage backends were not
    connected and whose `initialized` flag was False.

    It mostly worked anyway, which is what made it hard to see: the first
    storage call on an unready agent ends up initialising on the way through,
    so the cost and any failure surfaced at a random first use rather than
    here. It also made `initialized` useless as a health signal --
    UnifiedLearningSystem.start() logged "memory system connected" and
    get_learning_state() then reported memory_system_active=False, both
    truthfully.

    An async getter can do this properly, so it does. Callers that already
    await initialize() are unaffected: it returns early when already done.
    """
    global _memory_agent, _memory_agent_lock

    if _memory_agent_lock is None:
        _memory_agent_lock = asyncio.Lock()

    async with _memory_agent_lock:
        if _memory_agent is None:
            _memory_agent = MemoryAgent()

        if not _memory_agent.initialized:
            ready = await _memory_agent.initialize()
            if not ready:
                # An agent that cannot initialise fails at every use. Saying so
                # here names the cause; returning it names nothing and the
                # failure appears somewhere unrelated.
                raise RuntimeError(
                    "MemoryAgent failed to initialise; its storage backends are "
                    "not connected and nothing can be stored or recalled")

    return _memory_agent


async def initialize_memory_agent() -> MemoryAgent:
    """
    Initialize and return global memory agent (convenience function)

    Returns:
        Initialized MemoryAgent instance
    """
    # get_memory_agent() now returns a ready agent, so this is an alias kept
    # for the one caller that uses it and for anything outside core/.
    return await get_memory_agent()


# Convenience exports
__all__ = ["MemoryAgent", "get_memory_agent", "initialize_memory_agent"]
