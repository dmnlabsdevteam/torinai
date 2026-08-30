#!/usr/bin/env python3
"""Remembering while thinking, instead of before it.

`retrieve` already runs its strategies concurrently and ranks by corroboration.
What it cannot do is start before the caller knows what to ask for -- and the
caller never knows that at the start.

    THE BEST QUERY IS NOT AVAILABLE UNTIL THE REQUEST IS PARTLY UNDERSTOOD.

Recall placed after understanding waits; recall placed before it runs with the
worst query of the turn -- the raw sentence, articles and all. Both are the same
mistake, which is treating recall as a step. It is not a step. Understanding a
request and remembering things about it improve each other, so they belong
alongside one another:

    request arrives ──> WAVE 1 on the raw text            (immediately, no wait)
    concepts resolve ─> WAVE 2 on what they turned out to be
    relation matched ─> WAVE 3 on the thing actually asked
    compose the reply using whatever has landed

Every wave is a task the moment it is known, and nothing is awaited until an
answer is actually being assembled.

CORROBORATION ACROSS FORMULATIONS. `retrieve` ranks a memory higher when
several strategies found it. The same argument holds a level up: a memory that
the raw sentence AND the resolved concept both surface is more likely to be the
one that matters than a memory only one phrasing reached. Waves are merged the
same way.

A DEADLINE, AND IT IS REPORTED. Recall must never hold up an answer, so harvest
takes what has landed and leaves the rest running. What it must not do is
pretend that was everything: `complete` says whether anything was still in
flight, because an answer missing a memory it nearly had is a different answer
from a complete one, and only one of them is worth trusting twice.

NOTHING IN FLIGHT IS WASTED. A wave that lands after the answer went out is
kept, and the next turn on the same conversation starts with it already in
hand -- which is the case that recurs, because people ask about what they were
just asking about.

A BRANCH IS NOT A SWITCH. Asking about pressure loss, being told pipe friction
causes it, and then asking about pipe friction is not changing the subject --
it is following one. Isolating the second from the first throws away exactly
the context that makes it make sense, and treating them as one lets an
unrelated topic contaminate both. So a subject records what it AROSE FROM, and
recall under it can draw on its parent at lower standing: inherited context,
never mistaken for something found about the subject itself.

WHAT IS SEARCHED IS KNOWLEDGE. Memories divide into two kinds that want
opposite handling. Knowledge is one fact, merged on rediscovery, found by
meaning. An observation is one occurrence, never merged, and its MULTIPLICITY
is the signal -- how often a thing happened is what competence calibration
counts, so collapsing duplicates would destroy the measurement. They already
sit in one table under one index, which makes the event log a competitor in
every similarity search: identical rows that rank near each other and answer
nothing. Waves therefore ask for knowledge only; counting events is a query by
tag and time, where the number is exact.

KEPT PER SUBJECT, THOUGH, NOT IN ONE POOL. A conversation is not one thread.
Work on A, turn to B, come back to A: waves fired for A land while B is being
answered, and a single pool merges them into B's results -- where they rank
high, because corroboration counts formulations and A had several. The answer
to B is then supported by memories about A, with a number attached saying how
well supported it is.

So results are held under the subject they were sought for. Turning to B does
not disturb A, and coming back to A resumes with everything A had accumulated,
including the waves that landed while the conversation was elsewhere. That is
also why returning to a subject is FASTER than starting it: the work continued
while attention was somewhere else.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Set

logger = logging.getLogger(__name__)

#: How long an answer may wait for recall. Short on purpose: this is the budget
#: for improving an answer, not for producing one.
DEFAULT_DEADLINE = 0.4

#: Queries per turn. Each is a database round trip and an embedding; past a
#: handful they compete with the work they exist to inform.
MAX_WAVES = 6

#: What a wave will look at, and what it will keep.
#:
#: ADMISSION is deliberately low and is NOT the standard. Cosine is not
#: comparable across questions -- 0.4 is noise for a question the store
#: answers well and the best thing in existence for one it barely covers -- so
#: a fixed floor throws away true matches on exactly the hard questions recall
#: exists for. Measured on the live store, the 0.5 floor that stood here
#: returned NOTHING for "how does traffic get spread across servers" and
#: "what spots unusual behaviour in data" while the memory answering each sat
#: in the index.
#:
#: The standard is the GAP: how far the rest fall behind the best hit for THIS
#: question. Over the same probes that scored 4 of 6 with the fixed floor, this
#: scores 5 of 6 -- and still answers NOTHING to questions the store holds
#: nothing for, which is the property a lower floor is supposed to cost.
ADMISSION = 0.2
KEEP_WITHIN = 0.75


@dataclass
class Recalled:
    """One memory, and how many different ways the turn arrived at it."""

    memory_id: str
    text: str
    importance: float
    reached_by: Set[str] = field(default_factory=set)
    #: True where this memory asserts the same polarity as what was asked,
    #: False where it asserts the opposite, None where either is unreadable.
    #: A CONTRADICTION IS NOT A MISS -- it is the most relevant thing memory
    #: can offer, and reporting it as a match is what makes it dangerous.
    agrees: Optional[bool] = None

    @property
    def corroboration(self) -> int:
        return len(self.reached_by)


@dataclass
class Harvest:
    """What recall had to offer when the answer was assembled."""

    memories: List[Recalled] = field(default_factory=list)
    complete: bool = True
    waited: float = 0.0
    waves: int = 0
    still_running: int = 0
    #: How many of these came from the subject this one branched off.
    inherited: int = 0
    arose_from: str = ""

    def texts(self, limit: int = 3) -> List[str]:
        return [m.text for m in self.memories[:limit]]


def _text_of(item: Any) -> str:
    content = getattr(item, "content", None)
    if isinstance(content, dict):
        content = content.get("text") or content.get("content") or str(content)
    return str(content or "").strip().strip('"')


class LiveRecall:
    """Recall that runs alongside the turn rather than in front of it."""

    def __init__(self, agent=None, deadline: float = DEFAULT_DEADLINE,
                 per_wave: int = 5):
        self._agent = agent
        self.deadline = deadline
        self.per_wave = per_wave
        #: query -> task, and the subject each was sought under.
        self._waves: Dict[str, asyncio.Task] = {}
        self._wave_subject: Dict[str, str] = {}
        #: subject -> memory_id -> what was found for it.
        self._landed: Dict[str, Dict[str, Recalled]] = {}
        #: subject -> the subject it came out of, where it came out of one.
        self._arose_from: Dict[str, str] = {}
        self._asked: Set[str] = set()

    async def _memory_agent(self):
        if self._agent is None:
            from core.memory import get_memory_agent
            self._agent = await get_memory_agent()
        return self._agent

    def begin(self, *queries: str, about: str = "", arose_from: str = "") -> None:
        """Start recalling, under a subject. Returns immediately.

        `arose_from` records that this subject came out of another, which is
        what separates following a thread from changing the subject.
        """
        subject = (about or (queries[0] if queries else "")).strip().lower()
        parent = (arose_from or "").strip().lower()
        if parent and parent != subject and subject not in self._arose_from:
            self._arose_from[subject] = parent
        for query in queries:
            text = (query or "").strip()
            key = f"{subject}|{text.lower()}"
            if not text or key in self._asked:
                continue
            if len(self._waves) >= MAX_WAVES:
                logger.debug("live recall: %d waves already in flight, not adding %r",
                             len(self._waves), text[:40])
                return
            self._asked.add(key)
            self._wave_subject[text] = subject
            self._waves[text] = asyncio.create_task(self._wave(text))

    #: Reads as what it is at the call site: `recall.refine(*concept_names)`.
    refine = begin

    async def _wave(self, query: str) -> List[Any]:
        try:
            agent = await self._memory_agent()
            # RECALL SEARCHES KNOWLEDGE, NOT THE EVENT LOG. Records kept
            # because they HAPPENED -- task outcomes, governance blocks, safety
            # events -- are near-identical to each other by construction, so
            # they cannot be found by meaning and they displace what can. They
            # are queried by structure instead, where their count is exact.
            return await agent.retrieve(query=query, limit=self.per_wave,
                                        min_similarity=ADMISSION,
                                        relative_to_best=KEEP_WITHIN,
                                        require_named_match=True,
                                        include_events=False)
        except Exception as error:
            logger.info("live recall wave %r failed: %s", query[:40], error)
            return []

    def _absorb(self, query: str, items: Sequence[Any]) -> None:
        subject = self._wave_subject.get(query, "")
        found = self._landed.setdefault(subject, {})
        for item in items or []:
            memory_id = getattr(item, "memory_id", None) or _text_of(item)[:60]
            text = _text_of(item)
            if not text:
                continue
            existing = found.get(memory_id)
            if existing is None:
                existing = Recalled(memory_id=memory_id, text=text,
                                    importance=float(getattr(item, "importance_score", 0) or 0))
                found[memory_id] = existing
            existing.reached_by.add(query)

    async def harvest(self, limit: int = 3, about: str = "",
                      claim: str = "") -> Harvest:
        """What has landed FOR THIS SUBJECT. Leaves anything slower running.

        `claim` is the sentence being answered; each memory is marked as
        agreeing with it, contradicting it, or unreadable.
        """
        subject = (about or "").strip().lower()
        started = time.monotonic()
        mine = [q for q, s in self._wave_subject.items()
                if q in self._waves and s == subject]
        waves = len(mine)
        if mine:
            # Only this subject's waves are waited on. Another subject's slow
            # query must not delay an answer that does not need it.
            await asyncio.wait([self._waves[q] for q in mine], timeout=self.deadline,
                               return_when=asyncio.ALL_COMPLETED)
        for query, task in list(self._waves.items()):
            if task.done():
                self._absorb(query, task.result() if not task.cancelled() else [])
                del self._waves[query]
        still = sum(1 for q, s in self._wave_subject.items()
                    if q in self._waves and s == subject)

        own = self._landed.get(subject, {})
        if claim:
            from core.semantics.claim_shape import read_claim

            asked_shape = read_claim(claim)
            for recalled in own.values():
                recalled.agrees = asked_shape.agrees_with(read_claim(recalled.text))

        ranked = sorted(own.values(),
                        key=lambda m: (m.corroboration, m.importance), reverse=True)

        # INHERITED CONTEXT, RANKED BENEATH ITS OWN. A branch may lean on what
        # the subject it came from gathered, and must never outrank it: what
        # was found about THIS subject is what the question was about.
        inherited: List[Recalled] = []
        parent, seen = self._arose_from.get(subject), {subject}
        while parent and parent not in seen and len(ranked) + len(inherited) < limit:
            seen.add(parent)
            for recalled in sorted(self._landed.get(parent, {}).values(),
                                   key=lambda m: (m.corroboration, m.importance),
                                   reverse=True):
                if recalled.memory_id not in own and len(ranked) + len(inherited) < limit:
                    inherited.append(recalled)
            parent = self._arose_from.get(parent)

        return Harvest(memories=(ranked + inherited)[:limit], complete=still == 0,
                       waited=time.monotonic() - started, waves=waves,
                       still_running=still, inherited=len(inherited),
                       arose_from=self._arose_from.get(subject, ""))

    def rename_subject(self, was: str, now: str) -> None:
        """Carry what was filed provisionally over to what it turned out to be.

        The first wave goes out before anything has been resolved, so it is
        filed under the raw words. Resolution then names the concept -- and
        without this, that is a SECOND subject: `causes pressure loss` and
        `pressure loss` held apart, so returning to the topic with different
        wording found nothing, which is the case this whole scoping exists for.
        """
        was, now = (was or "").strip().lower(), (now or "").strip().lower()
        if not was or not now or was == now:
            return
        moving = self._landed.pop(was, None)
        if moving:
            into = self._landed.setdefault(now, {})
            for memory_id, recalled in moving.items():
                if memory_id in into:
                    into[memory_id].reached_by |= recalled.reached_by
                else:
                    into[memory_id] = recalled
        for query, subject in self._wave_subject.items():
            if subject == was:
                self._wave_subject[query] = now

    def subjects(self) -> List[str]:
        """Subjects this conversation has accumulated anything about."""
        return sorted(self._landed)

    def thread(self, subject: str) -> List[str]:
        """This subject and what it came out of, nearest first."""
        out, seen = [], set()
        current = (subject or "").strip().lower()
        while current and current not in seen:
            out.append(current)
            seen.add(current)
            current = self._arose_from.get(current, "")
        return out

    def carry_over(self) -> int:
        """Fold in whatever landed after the answer went out. The next turn on
        this conversation starts with it, which is the case that recurs."""
        gathered = 0
        for query, task in list(self._waves.items()):
            if task.done():
                self._absorb(query, task.result() if not task.cancelled() else [])
                del self._waves[query]
                gathered += 1
        return gathered

    def close(self) -> None:
        for task in self._waves.values():
            task.cancel()
        self._waves.clear()


__all__ = ["LiveRecall", "Harvest", "Recalled", "DEFAULT_DEADLINE", "MAX_WAVES",
           "ADMISSION", "KEEP_WITHIN"]
