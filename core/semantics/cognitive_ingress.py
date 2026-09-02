#!/usr/bin/env python3
"""The one door knowledge comes through.

A sentence that has been READ is not yet knowledge. Something has to admit it,
and until now nothing did: `read()` produced an atom like `cup_in_cabinet`,
handed it to its caller, and the caller dropped it. A thirty-minute teaching run
wrote 1,326 rows to a JSON file while the concept store, the memory system and
the evidence log recorded nothing -- measured directly as 0 concepts, 0
memories, 0 evidence. The substrate was never taught anything.

    THE READER INTERPRETS. THE INGRESS ADMITS. REASONING CONSUMES.

Those are three jobs and they were collapsed into one. This is the middle one,
and it is the only place a proposition enters the system. It admits each
proposition ONCE, with provenance, and propagates it to every store that has a
stake in it:

    concepts   the terms become things that exist, with the relation between
               them -- via ConceptIngestionService, which declares itself the
               only writer of unified.concepts, so this does not write there
    aliases    the surface word binds to the concept it denotes, which is what
               makes a word mean something rather than merely parse
    evidence   the sentence is the root: why any of it is believed
    memory     the episode, so it can be recalled and asked about later

WHAT THIS DOES NOT DO. It does not decide whether the proposition is TRUE. A
teacher's sentence is admitted as an observation with the teacher as its source
and one evidence root; the epistemic status the concept store assigns follows
from how much independent evidence accumulates, not from who said it.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)


@dataclass
class Provenance:
    """Where a proposition came from. Required -- there is no anonymous entry."""

    producer: str                      # "qwen_teacher", "observation", "user"
    source_id: str                     # the sentence, file, or episode id
    source_type: str = "USER_SUPPLIED"  # an EvidenceSourceType member name
    derived_from: Tuple[str, ...] = ()


@dataclass
class Admission:
    """What admitting one proposition actually did. Every field is a count."""

    proposition: str
    surface: str
    admitted: bool = False
    already_present: bool = False
    concepts_created: List[str] = field(default_factory=list)
    concepts_reinforced: List[str] = field(default_factory=list)
    aliases_bound: int = 0
    memories: int = 0
    #: The id of the SEMANTIC memory this admission created (via `_remember`),
    #: or None if nothing was retained. Surfaced so a later turn can point back
    #: at the exact memory this interaction made -- which is what lets
    #: conversational feedback ("no, that's wrong") FLAG the memory the claim
    #: already produced rather than mint a second, parallel record of it.
    memory_id: Optional[str] = None
    evidence_id: str = ""
    polarity: str = "positive"
    #: Set when this admission puts the store in conflict with itself. Surfaced,
    #: never silently resolved -- picking a winner here would hide the fact that
    #: two sources disagree.
    contradicts: Optional[Dict[str, Any]] = None
    refusals: List[str] = field(default_factory=list)

    @property
    def summary(self) -> str:
        conflict = "  CONTRADICTS PRIOR CLAIM" if self.contradicts else ""
        return (f"{self.proposition}[{self.polarity}]: "
                f"+{len(self.concepts_created)} concepts, "
                f"~{len(self.concepts_reinforced)} reinforced, "
                f"{self.aliases_bound} aliases, {self.memories} memories{conflict}")


#: Words that never name a thing. A concept called `you` or `the` is not a
#: concept; it is a reading that went wrong and was written down anyway.
NEVER_A_TERM = frozenset({
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "not", "no", "and", "or", "but", "that", "this", "these", "those",
    "it", "its", "you", "your", "i", "me", "my", "we", "us", "our",
    "he", "she", "they", "them", "their", "him", "her", "who", "which",
    "what", "when", "where", "how", "why", "of", "to", "for", "with",
    "as", "at", "by", "from", "in", "on",
})

#: Words a term may contain. Past this it is a clause, not a name: the store
#: holds things, and `which_lines_belong_to_which_block` is a sentence someone
#: stapled together with underscores.
MAX_TERM_WORDS = 4

#: Words a relation may contain. `is beside`, `is a kind of` -- past this it is
#: a clause the reader failed to segment.
MAX_RELATION_WORDS = 4


def admissible(term: str) -> Tuple[bool, str]:
    """Whether a term may name a concept, and why not when it may not.

    THE DOOR CHECKS, NOT THE CALLER. Every caller had its own idea of what was
    worth writing down, and the one that guessed hardest wrote the most. This
    is the shape test, in the one place everything passes through, so a bad
    reading is refused no matter which path produced it.
    """
    cleaned = term.strip().strip(".,;:!?").lower()
    if not cleaned:
        return False, "empty"
    words = [w for w in cleaned.replace("_", " ").split() if w]
    if not words:
        return False, "empty"
    if len(words) > MAX_TERM_WORDS:
        return False, f"{len(words)} words is a clause, not a name"
    if all(w in NEVER_A_TERM for w in words):
        return False, f"{cleaned!r} is made only of words that never name a thing"
    if words[0] in NEVER_A_TERM and len(words) == 1:
        return False, f"{cleaned!r} never names a thing"
    if any(character.isdigit() for character in cleaned) and len(words) == 1 \
            and cleaned.isdigit():
        return False, "a bare number names no thing"
    return True, ""


def admissible_relation(relation: str) -> Tuple[bool, str]:
    """Whether a relation may be recorded.

    A RELATION IS NOT A TERM AND THE TESTS ARE DIFFERENT. `is`, `in`, `on`, `of`
    are exactly what relations look like -- `robin is a bird` is the commonest
    shape there is -- while the same words never name a thing. Running terms'
    test over relations refused every copula sentence, which is most of them.

    What disqualifies a relation is being a clause: `a function count_o` is a
    fragment of a sentence nobody managed to read.
    """
    cleaned = " ".join(str(relation).strip().strip(".,;:!?").lower().replace("_", " ").split())
    if not cleaned:
        return False, "empty"
    words = cleaned.split()
    if len(words) > MAX_RELATION_WORDS:
        return False, f"{len(words)} words is a clause, not a relation"
    if any(w in ("a", "an", "the") for w in words):
        return False, f"{cleaned!r} carries a determiner, so it is a phrase that was cut mid-term"
    return True, ""


def normalize_term(term: str) -> str:
    """The canonical form of a term, so it names the same thing every time.

    `the ladder` and `ladder` are one thing. Admitting both leaves two concepts
    that never corroborate each other, and a relation pointing at
    `target_surface = 'the ladder'` never resolves to the `ladder` concept --
    which is how an edge ends up dangling forever.

    DELEGATED, BECAUSE THIS DOOR WAS THE ONE PLACE THE INVARIANT HAD TO HOLD.
    `lexical_normalization` states it: one surface form has one canonical
    interpretation across every cognitive path, written after `socrates_man`
    and `socrates_men` split and modus ponens had nothing to fire on. This had
    its own implementation, which stripped determiners and NEVER SINGULARISED
    -- so `bird` and `birds` entered as two concepts at the single door all
    knowledge passes through, which is exactly the split that module exists to
    prevent.

    `canonical_term` is the grammatical core (determiners, plurals, case,
    punctuation). It deliberately does NOT apply `canonical_label`'s
    document heuristics, which would reduce `nervous system` to `nervous` and
    `lithium battery` to `lithium` -- correct for a label scraped from a paper,
    destructive for a term read out of a sentence.
    """
    from core.semantics.lexical_normalization import canonical_term

    return canonical_term(term)


def _parse(proposition: str) -> Optional[Tuple[str, str, Optional[str], bool]]:
    """`cup_in_cabinet` -> (cup, in, cabinet, positive). `~x_hot` -> negative.

    The atom is the reader's output and its shape is the reader's contract, so
    this reads it rather than re-deriving anything from the sentence.
    """
    negated = proposition.startswith("~")
    body = proposition.lstrip("~")
    parts = [p for p in body.split("_") if p]
    if len(parts) < 2:
        return None
    if len(parts) == 2:
        return parts[0], "is", parts[1], not negated
    return parts[0], "_".join(parts[1:-1]), parts[-1], not negated


class CognitiveIngress:
    """Admits propositions. One instance, one door."""

    def __init__(self, db_manager=None):
        self._db = db_manager
        self._service = None
        self._seen: set = set()

    async def _ingestion(self):
        if self._service is None:
            from core.database import get_database_manager
            from core.domain.concept_ingestion import ConceptIngestionService

            self._service = ConceptIngestionService(self._db or get_database_manager())
        return self._service

    async def admit(self, proposition: str, surface: str,
                    provenance: Provenance,
                    word_class_of=None) -> Admission:
        """Admit one read proposition. Idempotent per (proposition, source)."""
        from core.domain.concept_ingestion import EvidenceEnvelope, EvidenceSourceType

        result = Admission(proposition=proposition, surface=surface)

        key = hashlib.sha256(
            f"{proposition}|{provenance.source_id}".encode()).hexdigest()[:16]
        if key in self._seen:
            # ADMITTED ONCE. A sentence read twice is one fact, not two, and
            # counting it twice would inflate the evidence behind it.
            result.already_present = True
            return result

        try:
            source_type = EvidenceSourceType[provenance.source_type]
        except KeyError:
            result.refusals.append(
                f"unknown evidence source {provenance.source_type!r}; "
                f"expected one of {[e.name for e in EvidenceSourceType]}")
            return result

        parsed = _parse(proposition)
        if parsed is None:
            result.refusals.append(f"proposition {proposition!r} has no relation to admit")
            return result
        subject, relation, obj, positive = parsed
        self._seen.add(key)
        return await self._admit_parts(
            subject, relation, obj, positive, surface, provenance,
            source_type, key, result, word_class_of)

    async def admit_relation(self, subject: str, relation: str, obj: str,
                             surface: str, provenance: Provenance,
                             positive: bool = True,
                             description: str = "",
                             domain: str = "language",
                             word_class_of=None) -> Admission:
        """Admit a proposition already split into its parts.

        The atom form (`cup_in_cabinet`) is one way to say a proposition and a
        lossy one -- a multi-word subject cannot survive it. A caller that
        already knows the seams passes them straight through rather than
        encoding them into a string for this to decode again.
        """
        from core.domain.concept_ingestion import EvidenceSourceType

        result = Admission(proposition=f"{subject}|{relation}|{obj}", surface=surface)
        try:
            source_type = EvidenceSourceType[provenance.source_type]
        except KeyError:
            result.refusals.append(f"unknown evidence source {provenance.source_type!r}")
            return result

        key = hashlib.sha256(
            f"{subject}|{relation}|{obj}|{provenance.source_id}".encode()).hexdigest()[:16]
        if key in self._seen:
            result.already_present = True
            return result
        self._seen.add(key)
        return await self._admit_parts(
            subject, relation, obj, positive, surface, provenance,
            source_type, key, result, word_class_of, description, domain)

    async def _admit_parts(self, subject, relation, obj, positive, surface,
                           provenance, source_type, key, result,
                           word_class_of=None, description: str = "",
                           domain: str = "language") -> Admission:
        """The one admission. Every caller funnels here."""
        from core.domain.concept_ingestion import EvidenceEnvelope

        # A negated proposition is a claim that something is NOT so, and it is
        # admitted as such -- `unified.concept_relations.polarity` carries the
        # denial. This used to be dropped to an episode because the store could
        # only represent things that hold, which meant "the mug is not in the
        # cupboard" taught the substrate nothing it could later be asked.

        subject, obj = normalize_term(subject), normalize_term(obj) if obj else obj
        relation = " ".join(str(relation).replace("_", " ").split())

        for name, term in (("subject", subject), ("object", obj)):
            if not term:
                continue
            allowed, why = admissible(term)
            if not allowed:
                result.refusals.append(f"{name} {term!r} not admitted: {why}")
                return result
        allowed, why = admissible_relation(relation)
        if not allowed:
            result.refusals.append(f"relation {relation!r} not admitted: {why}")
            return result

        terms = [t for t in (subject, obj) if t]
        concepts = []
        for term in terms:
            kind = "entity"
            if word_class_of:
                got = word_class_of(term)
                kind = {"NOUN": "entity", "ADJECTIVE": "property",
                        "VERB": "process"}.get(got or "", "entity")
            concepts.append({
                "label": term,
                "kind": kind,
                "domains": [domain],
                "description": description or f"met in use: {surface!r}",
            })
        if obj:
            concepts[0]["relationships"] = [
                [relation, obj, "positive" if positive else "negative"]]

        envelope = EvidenceEnvelope(
            evidence_id=f"read_{key}",
            source_type=source_type,
            source_id=provenance.source_id,
            content=surface,
            producer=provenance.producer,
            structured_data={"concepts": concepts},
            derived_from=provenance.derived_from,
        )

        try:
            service = await self._ingestion()
            ingested = await service.ingest(envelope)
            result.evidence_id = ingested.evidence_id
            result.concepts_created = list(ingested.created)
            result.concepts_reinforced = list(ingested.reinforced)
            for name, reason in ingested.rejected:
                result.refusals.append(f"{name}: {reason}")
            for name, reason in getattr(ingested, "unreadable", ()) or ():
                result.refusals.append(f"{name} could not read the evidence: {reason}")
        except Exception as error:
            result.refusals.append(f"concept ingestion failed: {error}")
            logger.warning("ingress: concept ingestion failed for %r: %s",
                           result.proposition, error)

        result.memories = await self._remember(
            result.proposition, surface, provenance, result)
        result.aliases_bound = await self._bind_aliases(terms, provenance)
        result.polarity = "positive" if positive else "negative"
        result.contradicts = await self._contradiction_check(
            subject, relation, obj) if obj else None
        result.admitted = bool(result.concepts_created or result.concepts_reinforced
                               or result.memories)
        return result

    async def _remember(self, proposition: str, surface: str,
                        provenance: Provenance, result: Admission) -> int:
        """Remember the claim as recallable knowledge -- what was said, findable later by meaning."""
        try:
            from core.memory import get_memory_agent
            from core.memory.utils.interfaces import MemoryType

            agent = await get_memory_agent()
            # KNOWLEDGE, not an event. What was learned has to be findable later
            # by MEANING the same as anything else -- that is the whole point of
            # storing it, and the substrate's alternative to baking knowledge
            # into weights. So it is stored as a semantic claim:
            #
            #   * content is the claim AS SAID -- the reading it was admitted as
            #     ("subject|relation|object") is a fact ABOUT the sentence, not
            #     part of it; splicing it in diluted the embedding so a real
            #     question scored the memory low. It lives in source_context;
            #   * it is NOT marked as an observation event. A raw_event exempts a
            #     memory from the worthiness filter but by the SAME token
            #     classifies it as an event, which recall excludes -- so a taught
            #     fact stored that way was invisible to the recall it exists for;
            #   * being user-supplied it carries real importance, so it clears the
            #     filter as the worthy knowledge it is, not via the event exemption.
            stored, memory_id = await agent.store_memory(
                content=surface,
                memory_type=MemoryType.SEMANTIC,
                importance_score=0.75,
                confidence_score=0.9,
                tags=["language", "admitted_proposition"],
                source_context={
                    "producer": provenance.producer,
                    "source_id": provenance.source_id,
                    # surface IS the claim, so recall hands it back directly.
                    "conclusion": surface,
                    "reading": proposition,
                },
            )
            if not stored:
                # The memory filter can decline. That is a real answer, not a
                # failure, but it must be visible rather than counted as a write.
                result.refusals.append(f"episode not retained: {memory_id}")
            else:
                # The memory this interaction MADE, kept referenceable so a later
                # feedback turn can flag THIS record rather than store another.
                result.memory_id = memory_id
            return 1 if stored else 0
        except Exception as error:
            result.refusals.append(f"episode not retained: {error}")
            logger.warning("ingress: episode not retained: %s", error)
            return 0

    async def _bind_aliases(self, terms: Sequence[str],
                            provenance: Provenance) -> int:
        """Bind the surface word to the concept it denotes.

        THIS IS WHAT MAKES A WORD MEAN SOMETHING. `unified.concept_aliases`
        already holds 1,371 of these; the word-class table I had built was a
        rival to it, recording that `cup` is a noun while nothing recorded what
        `cup` refers to.
        """
        from core.database import get_database_manager

        db = self._db or get_database_manager()
        bound = 0
        for term in terms:
            try:
                rows = await db.execute_query(
                    "SELECT concept_id FROM unified.concepts "
                    "WHERE name = $1 ORDER BY root_evidence_count DESC LIMIT 1",
                    (term,), fetch_all=True)
                if not rows:
                    continue
                # RETURNING, not a blind count: ON CONFLICT DO NOTHING makes a
                # skip indistinguishable from a write, and the ingestion service
                # already binds the canonical alias for a concept it creates.
                written = await db.execute_query(
                    "INSERT INTO unified.concept_aliases "
                    "(alias, concept_id, alias_kind, first_seen) "
                    "VALUES ($1, $2, 'surface_form', NOW()) "
                    "ON CONFLICT DO NOTHING RETURNING alias",
                    (term, rows[0]["concept_id"]), fetch_all=True)
                bound += len(written or ())
            except Exception as error:
                logger.debug("ingress: alias %r not bound: %s", term, error)
        return bound


    async def _contradiction_check(self, subject: str, relation: str,
                                   obj: str) -> Optional[Dict[str, Any]]:
        """Did admitting this put the store at odds with something it holds?"""
        try:
            from core.database import get_database_manager

            db = self._db or get_database_manager()
            rows = await db.execute_query(
                """SELECT p.evidence_id asserted_by, n.evidence_id denied_by
                     FROM unified.concept_relations p
                     JOIN unified.concept_relations n
                       ON p.source_concept_id = n.source_concept_id
                      AND p.relation = n.relation
                      AND p.target_surface = n.target_surface
                    WHERE p.polarity = 'positive' AND n.polarity = 'negative'
                      AND p.relation = $1 AND p.target_surface = $2
                      AND p.source_concept_id LIKE $3
                    LIMIT 1""",
                (relation, obj, f"%:{subject}"), fetch_all=True)
            return dict(rows[0]) if rows else None
        except Exception as error:
            logger.debug("ingress: contradiction check failed: %s", error)
            return None


_ingress: Optional[CognitiveIngress] = None


def get_cognitive_ingress() -> CognitiveIngress:
    global _ingress
    if _ingress is None:
        _ingress = CognitiveIngress()
    return _ingress
