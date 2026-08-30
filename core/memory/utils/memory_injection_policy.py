#!/usr/bin/env python3
"""
MemoryInjectionPolicy — decides WHETHER and WHAT, never HOW.

    task / cognitive context
            ↓
    MemoryInjectionPolicy      "Do I need memory here, and which kinds?"
            ↓
    MemoryInjectionPlan
            ↓
    MemoryInjector             "How do I retrieve, format and place it?"
            ↓
    model context

WHY THIS EXISTS
---------------
`autonomous_coordinator.get_intelligent_memory_context()` imported
`core.memory.intelligent_memory_injector` — a module that was never written —
and expected `InjectionContext` / `InjectionDecision.SKIP` /
`get_relevant_memory_types()`. The import was guarded by
`except ModuleNotFoundError: return None`, so 103 lines of real policy logic
looked like a normal "no memories" result for its entire lifetime.

Meanwhile `core/memory/utils/memory_injector.py` DOES exist, is constructed at
`main.py:1175`, and works — but it answers a different question. `MemoryInjector`
places memories (SYSTEM_PROMPT / USER_CONTEXT / ASSISTANT_CONTEXT / COMBINED).
It has no opinion on whether memory is wanted at all.

So this was never a missing memory capability. It was a policy layer accidentally
specified by its only caller, on top of a perfectly real mechanism.

`InjectionDecision.SKIP` and `InjectionMode.USER_CONTEXT` deliberately do NOT
live in one enum here: "should I inject?" and "where do the memories go?" are
different questions, and merging them is how the original confusion started.
`enabled=False` is the honest replacement for the fictional SKIP.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)


# Context types that justify pulling prior experience. Cheap/­routine work does
# not: injecting memory into every call costs tokens and dilutes the prompt.
_MEMORY_WORTHY_CONTEXTS = frozenset({
    "deep_reasoning", "research", "analysis", "planning", "debugging",
    # Executing a task is exactly when "have I done this before, and what
    # happened" matters — a remediation the agent already attempted and failed
    # is the most valuable thing it could be told.
    #
    # Added when GeneralPurposeExecutor was routed through this policy. That
    # path previously retrieved UNCONDITIONALLY, so omitting this would have
    # unified the decision by silently disabling memory for every autonomous
    # task — replacing three inconsistent answers with one consistently wrong
    # one. Unifying a mechanism must not quietly change behaviour.
    "task_execution",
})

# Post-retrieval relevance floor, per context. Values are PARITY with what each
# consumer used before centralisation, not a judgement about what is optimal:
#   task_execution — GeneralPurposeExecutor's hardcoded min_similarity=0.7
#   everything else — the policy's existing 0.5
# Change these from measurement, one context at a time.
_CONTEXT_MIN_RELEVANCE = {
    "task_execution": 0.7,
}

# An explicit user reference to the past overrides the heuristics below.
_MEMORY_KEYWORDS = (
    "remember", "recall", "previously", "last time", "before", "earlier",
    "you said", "we discussed", "history", "past",
)

_COMPLEXITY_HINTS = (
    "why", "how", "compare", "analyse", "analyze", "explain", "investigate",
    "root cause", "trade-off", "tradeoff", "design",
)


@dataclass(frozen=True)
class MemoryInjectionPlan:
    """What the policy decided, and why.

    `enabled=False` is a real decision — not an error and not an empty result.
    `reason_codes` exists so a skip is auditable rather than silent, which is
    what the original `return None` could never express.
    """

    enabled: bool
    query: str

    memory_types: Tuple[str, ...] = ()
    summarize: bool = False
    max_memories: int = 5
    min_relevance: float = 0.0

    domain: Optional[str] = None
    complexity: Optional[float] = None
    reason_codes: Tuple[str, ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "enabled": self.enabled,
            "memory_types": list(self.memory_types),
            "summarize": self.summarize,
            "max_memories": self.max_memories,
            "domain": self.domain,
            "complexity": self.complexity,
            "reason_codes": list(self.reason_codes),
        }


class MemoryInjectionPolicy:
    """Decides whether memory should be injected, and which kinds.

    Holds NO retrieval and NO formatting. It never touches a store; it produces
    a plan that MemoryInjector executes. Keeping those apart means the policy can
    later consume appraisal state (high doubt -> retrieve prior evidence; replan
    pressure -> retrieve failed strategies) without acquiring any opinion about
    prompt layout.
    """

    # Below this, a request is routine enough that prior context is noise.
    COMPLEXITY_FLOOR = 0.35
    # Above this many candidate memories, summarise rather than paste.
    SUMMARIZE_ABOVE = 3

    def decide(
        self,
        query: str,
        context_type: str = "general",
        domain: Optional[str] = None,
        thinking_mode: str = "auto",
        appraisal: Optional[Any] = None,
    ) -> MemoryInjectionPlan:
        """Produce an injection plan. Pure function of the inputs; no I/O."""
        q = (query or "").strip()
        if not q:
            return MemoryInjectionPlan(False, query=q, reason_codes=("empty_query",))

        reasons = []
        explicit = any(k in q.lower() for k in _MEMORY_KEYWORDS)
        complexity = self.assess_complexity(q)
        worthy = context_type in _MEMORY_WORTHY_CONTEXTS

        if explicit:
            reasons.append("explicit_memory_request")
        if worthy:
            reasons.append(f"context:{context_type}")
        if complexity >= self.COMPLEXITY_FLOOR:
            reasons.append(f"complexity:{complexity:.2f}")

        # An explicit request always wins. Otherwise the context type or enough
        # complexity must justify the cost.
        enabled = explicit or worthy or complexity >= self.COMPLEXITY_FLOOR
        if not enabled:
            return MemoryInjectionPlan(
                False, query=q, complexity=complexity,
                domain=domain or self.extract_domain(q),
                reason_codes=("routine_request_no_memory_needed",),
            )

        # WHICH kinds — this is policy, and belongs here rather than on the
        # injector. The injector must not decide what is cognitively relevant.
        types = ["episodic"]
        if context_type in ("deep_reasoning", "analysis", "debugging"):
            types.append("procedural")
        if context_type in ("research", "analysis"):
            types.append("semantic")
        if explicit:
            types.append("semantic")
        # Past task outcomes are relevant whenever the system is deciding how to
        # act, not merely recalling facts.
        if context_type in ("planning", "debugging", "deep_reasoning"):
            types.append("meta")

        max_mem = 3 if complexity < 0.6 else 6

        # POST-retrieval relevance: "is THIS memory relevant enough to inject",
        # distinct from `enabled`, which is the PRE-retrieval question "is memory
        # potentially useful here at all". Keeping them separate matters — one
        # avoids a search, the other filters its results.
        #
        # Per-context because this repair is a semantic unification and must not
        # change retrieval population. GeneralPurposeExecutor used a hardcoded
        # min_similarity=0.7; folding it into the shared default of 0.5 would
        # have loosened task-start retrieval as a side effect, and then any later
        # behavioural difference could be attributed to either the unification or
        # the threshold. Those must not ship together.
        #
        # 0.5 / 0.6 / 0.7 should be chosen by measurement — relevant-memory
        # recall, irrelevant-injection rate, token cost, task outcome, completion
        # latency — not aesthetically. Until then, parity.
        min_rel = _CONTEXT_MIN_RELEVANCE.get(context_type, 0.5)
        if explicit:
            min_rel = min(min_rel, 0.3)   # an explicit recall request widens the net

        return MemoryInjectionPlan(
            enabled=True,
            query=q,
            memory_types=tuple(dict.fromkeys(types)),
            summarize=max_mem > self.SUMMARIZE_ABOVE,
            max_memories=max_mem,
            min_relevance=min_rel,
            domain=domain or self.extract_domain(q),
            complexity=complexity,
            reason_codes=tuple(reasons),
        )

    # ── helpers the coordinator previously expected ON the injector ──────────
    @staticmethod
    def assess_complexity(query: str) -> float:
        """Rough request complexity in [0,1].

        Deliberately crude and LABELLED as a heuristic: it gates a cost decision,
        not a cognitive claim. It is not persisted and nothing reasons about it
        as evidence.
        """
        q = (query or "").lower()
        if not q:
            return 0.0
        words = len(q.split())
        length_term = min(1.0, words / 40.0)
        hint_term = min(1.0, sum(1 for h in _COMPLEXITY_HINTS if h in q) / 3.0)
        clause_term = min(1.0, (q.count(",") + q.count(";") + q.count(" and ")) / 4.0)
        return round(min(1.0, 0.5 * length_term + 0.3 * hint_term + 0.2 * clause_term), 4)

    @staticmethod
    def extract_domain(query: str) -> Optional[str]:
        """Best-effort domain tag, or None. None means UNKNOWN, not 'general'."""
        q = (query or "").lower()
        table = {
            "security": ("security", "vulnerab", "exploit", "attack", "auth"),
            "technical": ("code", "function", "bug", "compile", "refactor", "api"),
            "scientific": ("research", "hypothes", "experiment", "evidence"),
            "planning": ("plan", "schedule", "roadmap", "milestone"),
        }
        for dom, needles in table.items():
            if any(n in q for n in needles):
                return dom
        return None


_policy: Optional[MemoryInjectionPolicy] = None


def get_memory_injection_policy() -> MemoryInjectionPolicy:
    """Shared policy — one authority for 'should memory be injected'."""
    global _policy
    if _policy is None:
        _policy = MemoryInjectionPolicy()
    return _policy
