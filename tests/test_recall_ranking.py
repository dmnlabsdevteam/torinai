#!/usr/bin/env python3
"""What recall returns first, and what it declines to return at all.

Two invariants, both of which were once broken on the live path:

  MATCH QUALITY OUTRANKS IMPORTANCE. Importance is a property of a memory;
  similarity is the evidence about the QUESTION. Ranking a tie by importance
  meant the store's most important memory won every tie regardless of what
  was asked -- measured, a 0.839 match returned second beneath a 0.204 one.

  RECALL SEARCHES KNOWLEDGE, NOT THE EVENT LOG. Records kept because they
  HAPPENED are near-identical to each other by construction and cannot be
  found by meaning. They are queried by structure instead. They must still be
  reachable by default, because the subsystems that count them read them
  through the same call.
"""

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.agents.memory_agent import MemoryAgent
from core.memory.utils.interfaces import MemoryItem, MemoryType


def _memory(memory_id, text, similarity, importance, tags=None, raw_event=None):
    item = MemoryItem(
        memory_id=memory_id,
        memory_type=MemoryType.SEMANTIC,
        content={"text": text},
        importance_score=importance,
        tags=set(tags or []),
        thinking_state={"raw_event": raw_event} if raw_event else None,
    )
    item.similarity_score = similarity
    return item


class _Storage:
    """Only the two methods retrieve() reaches for."""

    def __init__(self, items):
        self._items = items

    async def semantic_search(self, **kwargs):
        floor = kwargs.get("min_similarity", 0.0)
        return [m for m in self._items if (m.similarity_score or 0.0) >= floor]

    async def search_by_content(self, **kwargs):
        return []

    async def search_memories(self, **kwargs):
        return []


class _Embeddings:
    def generate_embedding(self, text):
        return [0.0] * 384


def _agent(items):
    agent = MemoryAgent.__new__(MemoryAgent)
    agent.initialized = True
    agent.postgres_storage = _Storage(items)
    agent.embedding_service = _Embeddings()
    return agent


def test_a_better_match_outranks_a_more_important_memory():
    agent = _agent([
        _memory("weak-but-important", "unrelated", similarity=0.204, importance=0.82),
        _memory("the-answer", "a load balancer spreads traffic",
                similarity=0.839, importance=0.70),
    ])
    ranked = asyncio.run(agent.retrieve("what is a load balancer", limit=5,
                                        min_similarity=0.15))
    assert [m.memory_id for m in ranked] == ["the-answer", "weak-but-important"], (
        "the memory that matched the question best must come first; ranking a "
        "corroboration tie by importance answers every question with whichever "
        "memory the store considers most important"
    )


def test_importance_still_separates_equally_good_matches():
    agent = _agent([
        _memory("less-important", "same match quality", similarity=0.6, importance=0.2),
        _memory("more-important", "same match quality", similarity=0.6, importance=0.9),
    ])
    ranked = asyncio.run(agent.retrieve("anything", limit=5, min_similarity=0.15))
    assert [m.memory_id for m in ranked] == ["more-important", "less-important"]


def test_event_records_are_held_back_from_recall_when_asked():
    items = [
        _memory("event", "Governance block on run 41",
                similarity=0.9, importance=0.9, tags=["governance_block"]),
        _memory("knowledge", "pressure loss is caused by friction",
                similarity=0.6, importance=0.5),
    ]
    knowledge_only = asyncio.run(
        _agent(items).retrieve("what causes pressure loss", limit=5,
                               min_similarity=0.15, include_events=False))
    assert [m.memory_id for m in knowledge_only] == ["knowledge"]


def test_event_records_are_reachable_by_default():
    """The subsystems that COUNT events read them through this same call, and
    their multiplicity is the signal. Excluding them by default would silently
    empty performance history."""
    items = [
        _memory("event", "Governance block on run 41",
                similarity=0.9, importance=0.9, tags=["governance_block"]),
        _memory("knowledge", "pressure loss is caused by friction",
                similarity=0.6, importance=0.5),
    ]
    everything = asyncio.run(
        _agent(items).retrieve("governance", limit=5, min_similarity=0.15))
    assert {m.memory_id for m in everything} == {"event", "knowledge"}


def test_a_cut_off_relative_to_the_best_match_drops_the_tail():
    """A fixed floor is not comparable across questions -- 0.4 is noise for one
    and the best thing in existence for another. What IS comparable is how far
    the rest fall behind the best hit for THIS question."""
    agent = _agent([
        _memory("best", "the answer", similarity=0.80, importance=0.1),
        _memory("close", "also relevant", similarity=0.65, importance=0.1),
        _memory("tail", "vaguely worded", similarity=0.30, importance=0.9),
    ])
    kept = asyncio.run(agent.retrieve("a question", limit=5, min_similarity=0.2,
                                      relative_to_best=0.75))
    assert [m.memory_id for m in kept] == ["best", "close"], (
        "0.30 is less than 75% of 0.80 and must not be offered alongside it"
    )


def test_the_relative_cut_off_does_not_judge_what_it_never_measured():
    """A keyword hit means the query text appears verbatim in the memory and
    carries no similarity. Cutting it on a comparison to a number it does not
    have discards evidence on a measurement never taken."""
    agent = _agent([_memory("best", "the answer", similarity=0.80, importance=0.1)])
    keyword_only = _memory("verbatim", "contains the query exactly",
                           similarity=None, importance=0.1)

    async def _content(**kwargs):
        return [keyword_only]

    agent.postgres_storage.search_by_content = _content
    kept = asyncio.run(agent.retrieve("a question", limit=5, min_similarity=0.2,
                                      relative_to_best=0.75))
    assert {m.memory_id for m in kept} == {"best", "verbatim"}


def test_a_memory_naming_a_different_thing_is_not_a_weaker_answer():
    """`the capital of Mongolia` and `the capital of France` differ by one
    token and score close. One is not a worse answer to the other; it is the
    answer to a different question, and no threshold separates them."""
    agent = _agent([
        _memory("wrong-country", "The capital of France is Paris.",
                similarity=0.95, importance=0.9),
    ])
    kept = asyncio.run(agent.retrieve("what is the capital of Mongolia", limit=5,
                                      min_similarity=0.2, require_named_match=True))
    assert kept == [], "a 0.95 score does not make Paris the capital of Mongolia"


def test_the_name_test_stays_silent_where_nothing_was_named():
    """Most questions name nothing, and a paraphrase shares no words at all:
    `what spots unusual behaviour in data` is answered by a memory about
    anomaly detection. The test must decline, not reject."""
    agent = _agent([
        _memory("paraphrase", "Asked: What is anomaly detection?",
                similarity=0.386, importance=0.5),
    ])
    kept = asyncio.run(agent.retrieve("what spots unusual behaviour in data",
                                      limit=5, min_similarity=0.2,
                                      require_named_match=True))
    assert [m.memory_id for m in kept] == ["paraphrase"]


def test_a_strategy_without_a_similarity_is_not_scored_as_a_perfect_match():
    """Keyword and tag hits carry no similarity. Treating a missing score as
    1.0 would put every keyword hit above every semantic one; treating it as
    0.0 would bury them. They are scored at the floor they had to clear."""
    strong = _memory("strong", "near restatement", similarity=0.9, importance=0.1)
    keyword_only = _memory("keyword", "exact wording", similarity=None, importance=0.1)

    agent = _agent([strong])

    async def _content(**kwargs):
        return [keyword_only]

    agent.postgres_storage.search_by_content = _content
    ranked = asyncio.run(agent.retrieve("wording", limit=5, min_similarity=0.5))
    assert [m.memory_id for m in ranked] == ["strong", "keyword"]


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
