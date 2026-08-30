#!/usr/bin/env python3
"""
Memory Injector
===============
Injects contextual memories into prompts for enhanced reasoning

Purpose:
- Retrieve relevant memories based on current context
- Format memories for LLM injection
- Track memory usage and effectiveness
"""

import logging
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

logger = logging.getLogger(__name__)


class InjectionMode(Enum):
    """Memory injection modes"""
    SYSTEM_PROMPT = "system_prompt"  # Inject into system message
    USER_CONTEXT = "user_context"    # Inject as user context
    ASSISTANT_CONTEXT = "assistant_context"  # Inject as assistant knowledge
    COMBINED = "combined"            # Mix of all modes


@dataclass
class InjectionConfig:
    """
    Memory injection configuration

    Optimized for performance:
    - max_memories reduced to 3 (was 5) for lower latency
    - min_relevance_score increased to 0.75 (was 0.7) for better quality
    - Content truncated to 100 chars max per memory
    
    Cognitive filtering (like human memory):
    - min_importance_score filters out trivial/routine memories
    - Only significant memories are recalled for context
    """
    # Injection settings
    mode: InjectionMode = InjectionMode.USER_CONTEXT
    max_memories: int = 3  # Reduced from 5 for performance
    max_tokens: int = 500  # Reduced from 1000 for performance

    # Relevance filtering
    min_relevance_score: float = 0.6
    require_exact_match: bool = False
    
    # Importance filtering - filter trivial memories like human cognition
    # Memories with importance_score below this won't be injected
    min_importance_score: float = 0.5  # Only inject moderately+ important memories

    # Formatting
    include_metadata: bool = False  # Disabled for performance
    include_timestamp: bool = False
    format_template: str = "• {content}"

    # Performance
    cache_results: bool = True
    timeout_seconds: float = 5.0

    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class InjectedMemories:
    """Result of memory injection"""
    # Injected content
    formatted_text: str
    memory_ids: List[str] = field(default_factory=list)

    #: THE MEMORIES AS SEPARATE CLAIMS, one string each.
    #:
    #: `formatted_text` is a PROMPT: a header sentence followed by bullets, all
    #: in one string, shaped for a model's context window. That is the right
    #: form for the thing it was built for and the wrong form for everything
    #: else, because a consumer that treats one context item as one claim
    #: receives a header and several unrelated memories fused into a single
    #: statement.
    #:
    #: Measured harm, not a hypothetical: passed as one premise to causal
    #: reasoning, the blob yielded "you have access to the following relevant
    #: context from memory: ... causes ..." as a derived causal link at
    #: CONFIDENCE 1.00, and a root-cause conclusion built on the header text.
    #: Fabricated, confident, and destined for the memory store as knowledge.
    #:
    #: So the claims travel separately alongside the prose. Neither replaces the
    #: other: a prompt wants one blob, a reasoner wants one claim per item.
    records: List[str] = field(default_factory=list)

    # Metadata
    total_memories: int = 0
    total_tokens: int = 0
    injection_mode: InjectionMode = InjectionMode.USER_CONTEXT

    # Performance
    retrieval_time: float = 0.0
    formatting_time: float = 0.0

    timestamp: datetime = field(default_factory=datetime.now)


class MemoryInjector:
    """
    Memory Injector for LLM Prompts

    Intelligently retrieves and formats memories for injection
    into LLM prompts to enhance reasoning with historical context.

    Features:
    - Semantic search for relevant memories
    - Multiple injection modes
    - Token budget management
    - Performance tracking
    """

    def __init__(self):
        # Injection templates by mode
        self.templates = {
            InjectionMode.SYSTEM_PROMPT: self._system_prompt_template,
            InjectionMode.USER_CONTEXT: self._user_context_template,
            InjectionMode.ASSISTANT_CONTEXT: self._assistant_context_template,
            InjectionMode.COMBINED: self._combined_template
        }

        # Statistics
        self.stats = {
            'total_injections': 0,
            'total_memories_injected': 0,
            'avg_relevance_score': 0.0
        }

        logger.info("MemoryInjector initialized")

    async def inject_memories(
        self,
        query: str,
        config: InjectionConfig = None,
        plan: Optional[Any] = None,
    ) -> InjectedMemories:
        """
        Inject memories into prompt

        Args:
            query: Current query/context
            config: Injection configuration

        Returns:
            InjectedMemories with formatted text
        """
        config = config or InjectionConfig()
        start_time = datetime.now()

        logger.info(f"Injecting memories for query: {query[:100]}...")

        # Whether memory belongs here is the POLICY's call, not this module's.
        #
        # `_should_search_memories` is a second, independently-maintained answer
        # to the same question MemoryInjectionPolicy.decide() answers — its own
        # keyword lists and complexity heuristics, drifting from the policy's
        # COMPLEXITY_FLOOR and context rules. This module's job is retrieval,
        # formatting and placement; keeping a relevance opinion here is how the
        # same query gets injected on one path and skipped on another.
        #
        # Falls back to the local heuristic only if the policy cannot be
        # reached, and says so rather than degrading silently.
        # The DECISION travels with the call. A caller that already consulted
        # the policy passes its plan and is never second-guessed here.
        #
        # This module previously re-called the policy with a HARDCODED context.
        # There is no correct constant: a "worthy" one makes the guard always
        # approve, a non-worthy one silently overturns plans the caller had
        # already approved (that bug was live — context_type="reasoning" is not
        # a real context, so every approved plan was being discarded and the
        # caller saw it as "no memories found").
        #
        # A guard that cannot see the caller's context is not a guard; it is a
        # constant. So: use the caller's plan, or decide honestly under "general"
        # for a direct caller, which actually evaluates the query.
        if plan is not None:
            _warranted = bool(getattr(plan, "enabled", False))
            _why = ", ".join(getattr(plan, "reason_codes", ()) or ()) or "caller plan"
        else:
            try:
                from core.memory.utils.memory_injection_policy import get_memory_injection_policy
                _plan = get_memory_injection_policy().decide(
                    query=query, context_type="general"
                )
                _warranted = _plan.enabled
                _why = ", ".join(_plan.reason_codes) or "policy declined"
            except Exception as e:
                # FAIL CLOSED. A second, independently-maintained relevance
                # heuristic here would activate exactly when it cannot be seen,
                # and inject on rules nobody chose. An unreachable policy is a
                # fault, not a licence to substitute different criteria.
                logger.error(
                    "injection policy unreachable (%s) — declining injection rather "
                    "than falling back to separate rules", e
                )
                _warranted, _why = False, "policy_unreachable"

        if not _warranted:
            logger.debug(f"Query does not warrant memory search — skipping ({_why})")
            return InjectedMemories(
                formatted_text="",
                memory_ids=[],
                total_memories=0,
                total_tokens=0,
                injection_mode=config.mode,
                retrieval_time=0.0,
                formatting_time=0.0
            )

        try:
            # Retrieve relevant memories
            retrieval_start = datetime.now()
            memories = await self._retrieve_memories(
                query,
                max_results=config.max_memories,
                min_score=config.min_relevance_score,
                min_importance=config.min_importance_score
            )
            retrieval_time = (datetime.now() - retrieval_start).total_seconds()

            # Format memories
            formatting_start = datetime.now()
            formatted_text = await self._format_memories(
                memories,
                config
            )
            formatting_time = (datetime.now() - formatting_start).total_seconds()

            # Count tokens (rough estimate)
            total_tokens = len(formatted_text.split())

            # Update statistics
            self.stats['total_injections'] += 1
            self.stats['total_memories_injected'] += len(memories)

            if memories:
                avg_score = sum(m.get('relevance_score', 0) for m in memories) / len(memories)
                self.stats['avg_relevance_score'] = avg_score

            result = InjectedMemories(
                formatted_text=formatted_text,
                memory_ids=[m['memory_id'] for m in memories],
                # One claim per entry, in the same order as `memory_ids`, so a
                # consumer can pair a claim with the record it came from.
                records=[str(m.get('claim') or m.get('content') or '').strip()
                         for m in memories
                         if str(m.get('claim') or m.get('content') or '').strip()],
                total_memories=len(memories),
                total_tokens=total_tokens,
                injection_mode=config.mode,
                retrieval_time=retrieval_time,
                formatting_time=formatting_time
            )

            logger.info(
                f"✓ Injected {len(memories)} memories "
                f"({total_tokens} tokens, {retrieval_time + formatting_time:.2f}s)"
            )

            return result

        except Exception as e:
            logger.error(f"Memory injection failed: {e}")
            return InjectedMemories(
                formatted_text="",
                total_memories=0
            )

    async def _retrieve_memories(
        self,
        query: str,
        max_results: int,
        min_score: float,
        min_importance: float = 0.5
    ) -> List[Dict[str, Any]]:
        """Retrieve relevant memories, filtering by both similarity and importance.
        
        Like human memory, we don't recall trivial/routine memories even if
        they're semantically similar to the current context.
        """
        try:
            # Import memory agent
            from core.memory import get_memory_agent

            memory_agent = await get_memory_agent()

            # Search for relevant memories using semantic search
            # KNOWLEDGE ONLY. What is injected here is what the system knows
            # about the topic. Event records -- task outcomes, governance
            # blocks, safety events -- are kept for their COUNT, are
            # near-identical to one another, and answer nothing about a topic;
            # in a similarity search they only take the places that would have
            # gone to something the system actually knows.
            success, results = await memory_agent.search_memories(
                query=query,
                limit=max_results,
                min_similarity=min_score,
                include_events=False,
                require_named_match=True
            )

            if not success:
                logger.warning("Memory search failed")
                return []

            # Convert to dict format, filtering by importance
            # Like human memory: we don't recall trivial/routine memories
            memories = []
            seen_content: set = set()
            for result in results:
                # Filter out trivial memories - importance threshold
                importance = getattr(result, 'importance_score', 1.0)
                if importance < min_importance:
                    logger.debug(
                        f"Skipping low-importance memory {result.memory_id}: "
                        f"importance={importance:.2f} < threshold={min_importance:.2f}"
                    )
                    continue

                seen_content.add(result.memory_id)
                # WHAT THIS MEMORY CLAIMS, IF IT CLAIMS ANYTHING.
                #
                # `content` is the episode written out for a reader; a reasoning
                # memory renders as "Query: ... / Reasoning steps: ... /
                # Answer: ...". Handed to a consumer that reads one item as one
                # statement, that is a document, not a claim.
                #
                # A writer that knew its conclusion records it under
                # `conclusion`. When it is there, THAT is what this memory
                # asserts, and it is what recall should hand back. When it is
                # not -- most older records, and every memory that is an episode
                # rather than a conclusion -- content is all there is, and is
                # used unchanged.
                metadata = result.metadata or {}
                claim = None
                if isinstance(metadata, dict):
                    claim = (metadata.get('conclusion')
                             or (metadata.get('source_context') or {}).get('conclusion')
                             if isinstance(metadata.get('source_context'), dict)
                             else metadata.get('conclusion'))
                memories.append({
                    'memory_id': result.memory_id,
                    'content': result.content,
                    'claim': str(claim).strip() if claim else None,
                    'relevance_score': result.similarity_score,
                    'importance_score': importance,
                    'timestamp': result.created_at,
                    'metadata': metadata,
                    # The derivation, when the record kept one. Carried rather
                    # than dropped: it was read out of the row already.
                    'reasoning_trace': getattr(result, 'reasoning_trace', None),
                })

            if len(results) > len(memories):
                logger.info(
                    f"Filtered {len(results) - len(memories)} trivial memories "
                    f"(importance < {min_importance:.2f})"
                )

            # --- Pending queue check ---
            # Memories enqueued via enqueue_memory() haven't landed in postgres
            # yet but are immediately visible here so the model sees recent context.
            pending = getattr(memory_agent, '_pending_memories', {})
            if pending:
                query_words = set(query.lower().split())
                pending_added = 0
                for pid, entry in list(pending.items()):
                    if entry.get('importance_score', 0) < min_importance:
                        continue
                    # Simple keyword overlap as a fast relevance proxy
                    content_words = set(entry['content'].lower().split())
                    overlap = len(query_words & content_words) / max(len(query_words), 1)
                    if overlap < 0.1:
                        continue
                    memories.append({
                        'memory_id': pid,
                        'content': entry['content'],
                        'relevance_score': overlap,
                        'importance_score': entry.get('importance_score', 0.5),
                        'timestamp': None,
                        'metadata': {'pending': True}
                    })
                    pending_added += 1
                    if len(memories) >= max_results:
                        break
                if pending_added:
                    logger.debug(f"Injected {pending_added} pending (unwritten) memories")

            return memories[:max_results]

        except Exception as e:
            logger.error(f"Memory retrieval failed: {e}")
            return []

    async def _format_memories(
        self,
        memories: List[Dict[str, Any]],
        config: InjectionConfig
    ) -> str:
        """Format memories using template"""
        if not memories:
            return ""

        # Select template
        template_fn = self.templates.get(config.mode)
        if not template_fn:
            template_fn = self._user_context_template

        # Format
        return template_fn(memories, config)

    def _system_prompt_template(
        self,
        memories: List[Dict[str, Any]],
        config: InjectionConfig
    ) -> str:
        """System prompt injection template"""
        lines = ["You have access to the following relevant context from memory:"]

        for mem in memories:
            lines.append(f"• {mem['content']}")

        return "\n".join(lines)

    def _user_context_template(
        self,
        memories: List[Dict[str, Any]],
        config: InjectionConfig
    ) -> str:
        """User context injection template"""
        lines = []
        for mem in memories:
            content = str(mem['content'])
            # Truncate to 300 chars to prevent a single large memory
            # from dominating the context window
            if len(content) > 300:
                content = content[:300] + "..."
            lines.append(f"• {content}")

        return "\n".join(lines)

    def _assistant_context_template(
        self,
        memories: List[Dict[str, Any]],
        config: InjectionConfig
    ) -> str:
        """Assistant context injection template"""
        lines = ["Based on my memory, I recall:"]

        for mem in memories:
            lines.append(f"- {mem['content']}")

        return "\n".join(lines)

    def _combined_template(
        self,
        memories: List[Dict[str, Any]],
        config: InjectionConfig
    ) -> str:
        """Combined injection template"""
        # Use all modes
        return self._user_context_template(memories, config)

    # _should_search_memories() DELETED 2026-08-14 (161 lines).
    #
    # It was a SECOND, independently-maintained answer to "is memory relevant
    # here?" — its own keyword lists and complexity heuristics, drifting from
    # MemoryInjectionPolicy's COMPLEXITY_FLOOR and context rules. Two authorities
    # meant the same query could be injected on one path and skipped on another.
    #
    # It survived only as a fallback for "policy import failed", which is the
    # worst possible time to switch silently to different criteria. That path now
    # fails CLOSED and says so. Relevance is decided once, by the policy.


    async def get_statistics(self) -> Dict[str, Any]:
        """Get injection statistics"""
        return self.stats.copy()


# Global instance
_memory_injector: Optional[MemoryInjector] = None


def get_memory_injector() -> MemoryInjector:
    """Get global memory injector instance"""
    global _memory_injector
    if _memory_injector is None:
        _memory_injector = MemoryInjector()
    return _memory_injector
