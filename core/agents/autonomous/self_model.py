#!/usr/bin/env python3
"""Self — the substrate's integrator, and the seat its identity actually lives in.

The faculties that make up a self already exist in this folder — attitude
(`appraisal`), temperament and drives (`intrinsic_motivation`), values
(`singleton_constitution`), disposition (`behavior_arbiter`) — but nothing tied
them into a *someone*. Identity lived only as a prompt string recited by the
language model, so pulling the model out of the centre left the substrate with a
brain and no self. This class is that missing head.

WHAT IT IS. A THIN integrator. It reads the faculties through their existing
authorities and composes one `SelfState` and one disposition. It is the centre
of gravity — the thing the body (coordinator) reports to and asks "what is my
disposition now?", and the thing that renders the self to language when the model
is consulted.

WHAT IT IS NOT. Not a new god-object. It never reimplements a faculty: appraisal
still owns affect, motivation still owns drives, the constitution still owns the
laws. The Self holds references and READS them. Growing behaviour here — instead
of reading the authority that owns it — would just move the monolith from the
body to the brain and fix nothing.

HONESTY. Every field is derived from a real signal or left None. A self that has
not appraised a situation this session has no mood to report, and says so, rather
than authoring one — the same discipline `appraisal` keeps with its own
unmeasured variables.
"""

from __future__ import annotations

import logging
from collections import OrderedDict
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

#: The substrate's name. The one authored constant — everything else is derived.
NAME = "Torin"

#: Who Torin is, model-facing and second-person — the STABLE identity core.
#:
#: This is the text that used to be recited ~30 times as a hard-coded persona
#: string inside the model service (and drifted while duplicated — one copy
#: claimed a 21K context window, another 32K, for the same "identity"). It lives
#: here now, once, owned by the Self. The model service, a resource the Self
#: consults, asks the Self for it.
#:
#: It is deliberately model-GENERIC: the specific model name, size, and context
#: window are deployment facts (they change, and belong to continuity/config),
#: not the substrate's identity. What is identity is that a model is a resource
#: consulted only when the substrate's own machinery cannot represent the
#: question — the model-optional stance, stated honestly.
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

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class Self:
    """The integrator. Reads the faculties; composes one self and one disposition.

    Faculties are reached through their existing getters, not constructed here —
    the Self is a reader over the authorities that already own each part, so
    there is exactly one owner of each and the Self adds no rival state.
    """

    def __init__(self):
        # Faculties whose getters are async are brought up in initialize() and
        # cached here; None until then. Everything else is fetched on demand from
        # its existing singleton, so the Self holds almost no state of its own.
        self._intelligence = None
        self._memory = None

    # ── faculty access (existing authorities, read-only) ──────────────────────

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

    # ── cognition faculties the Self OWNS and EXPOSES ─────────────────────────
    # Reasoning and learning are done by these authorities, NOT by the Self. The
    # Self is the seat they hang off: it holds the SAME singletons (never a rival
    # instance) and hands them out, so the body reaches cognition THROUGH the
    # Self without the Self reimplementing any of it. This is the ownership the
    # coordinator (body) gives up — it stops holding these and reaches them here.

    def reasoning(self):
        """The reasoning faculty — `NeuralSymbolicBridge`. It reasons; the Self
        only holds it. Callers use `self.reasoning().reason(...)`."""
        from core.reasoning.neural_bridge import get_neural_bridge
        return get_neural_bridge()

    def learning(self):
        """The learning authority — the always-online, model-free learner
        (`SubstrateLearning`). It learns; the Self only holds it."""
        from core.learning.learning_authority import get_learning_authority
        return get_learning_authority()

    def domains(self):
        """The domain authority — `UniversalDomainMaster` (competence, discovery,
        transfer). The Self reads it for competence AND hands it out for use."""
        from core.integration.universal_domain_master import get_universal_domain_master
        return get_universal_domain_master()

    def intelligence(self):
        """The predictive / foresight faculty (`PredictiveIntelligenceSystem`).
        Its getter is async, so it is brought up in `initialize()` and cached;
        None until then."""
        return self._intelligence

    def memory(self):
        """The memory faculty (the memory agent) — episodic / semantic / meta.
        Brought up in `initialize()` and cached; None until then."""
        return self._memory

    def meta_learning(self):
        """The meta-learning faculty (`MetaLearner`) — strategy selection and
        adaptation over task families. Sync singleton, fetched on demand."""
        from core.learning.meta_learning import get_meta_learner
        return get_meta_learner()

    def language(self):
        """The language faculty — model-free reading / understanding. The
        `ReadingRegistry` turns a sentence into a structured reading
        READING(subject, object, polarity) via DERIVED readings (the sentence
        machine), no model involved. This is how the Self UNDERSTANDS input — the
        complement to `render()`, which SPEAKS. The LLM is not this; it is a
        fallback the substrate reaches for only when its own reading cannot
        represent the sentence."""
        from core.semantics.reading_registry import get_reading_registry
        return get_reading_registry()

    def conversation(self, session: str = "default", *, db=None):
        """The Self holding a conversation — understanding a sentence against
        what it holds, and replying. Moved into the Self from its own module
        because conversing is not a separate concern: it is the Self using
        `language()` to read, `memory()` to recall, and (as this is wired
        further) `reasoning()` to derive, then speaking the result. Reached HERE
        so a reply is composed through the brain that owns those faculties,
        never beside it. `get_conversation` lives in this module (below)."""
        return get_conversation(session, db=db)

    def motivation(self):
        """The motivation faculty — `IntrinsicMotivationSystem`. It forms goals
        from the substrate's own measured signals (component uncertainties,
        unstable beliefs) and holds the drives/temperament the Self reads. The
        Self OWNS it: the body (coordinator) reaches it through here rather than
        constructing its own, exactly as with `reasoning()`/`learning()`/
        `domains()`. Same singleton the Self reads for temperament — no rival
        instance. Goal FORMATION is deterministic and model-free; MiniLM sits
        only downstream of it (novelty/dedup)."""
        from core.agents.autonomous.intrinsic_motivation import get_intrinsic_motivation_system
        return get_intrinsic_motivation_system()

    async def initialize(self) -> bool:
        """Bring up the cognition faculties the Self owns. Idempotent — each
        faculty's own initializer is the authority; this only ensures they are
        up. The learning authority is stateless over its stores and needs none.
        Reasoning also carries LOGICAL/proof/abstract reasoning (the bridge is
        the authority that routes to them), so there is no separate logical
        faculty to hold.
        """
        ok = True
        for name, faculty in (("reasoning", self.reasoning()), ("domains", self.domains()),
                              ("motivation", self.motivation())):
            init = getattr(faculty, "initialize", None)
            if init is None:
                continue
            try:
                await init()
            except Exception as e:
                logger.warning("Self: %s faculty init failed: %s", name, e)
                ok = False
        # Async-getter faculties: bring up once and cache. Same singletons the
        # rest of the system reaches, so nothing here forks a second instance.
        try:
            from core.intelligence import get_predictive_intelligence
            self._intelligence = await get_predictive_intelligence()
        except Exception as e:
            logger.warning("Self: intelligence faculty init failed: %s", e)
            ok = False
        try:
            from core.memory import get_memory_agent
            self._memory = await get_memory_agent()
        except Exception as e:
            logger.warning("Self: memory faculty init failed: %s", e)
            ok = False
        return ok

    # ── the self ──────────────────────────────────────────────────────────────

    #: The interoceptive variables — the substrate's read of its own internal
    #: state — surfaced verbatim from appraisal. Kept in one place so what the
    #: affect is grounded IN is inspectable, not asserted. (Label -> attribute.)
    _INTEROCEPTION = {
        "valence": "valence", "activation": "activation", "confidence": "confidence",
        "control": "controllability", "progress": "progress", "competence": "competence",
        "open_questions": "epistemic_opportunity", "goal_congruence": "goal_congruence",
        "agency": "agency", "risk": "risk",
    }

    def _interoception(self) -> Optional[Dict[str, Any]]:
        """My read of my own internal state — the measured interoceptive variables.

        These are the readings appraisal integrates; affect is a category over
        them. Surfaced so that 'I feel doubt' can be checked against the state it
        claims to summarise, rather than taken on faith. Only measured variables
        appear — an unmeasured internal sense is omitted, never zero-filled.
        """
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
        # The four emotions are derived properties (may each be None/unmeasured);
        # valence + attribution say what the feeling is about. Nothing authored.
        return {
            "eagerness": state.eagerness,
            "doubt": state.doubt,
            "frustration": state.frustration,
            "satisfaction": state.satisfaction,
            "valence": state.valence,
            "attribution": state.attribution,
        }

    def _temperament(self) -> Dict[str, float]:
        """The standing drives — what I am, before any situation. The weights ARE
        the personality (curiosity highest, autonomy next); persisted, so this is
        continuous across sessions."""
        return {k: float(v) for k, v in asdict(self.motivation().weights).items()}

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
        """What I am actually good at — the operators I have VALIDATED, per domain.

        Read from the rule store (`unified.learned_rules`), so it is the durable,
        evidence-earned record that survives a restart — not a self-rating. The
        competence LEVEL persists (the learning RATE does not), which is why this
        reads the learned operators, the thing that is actually kept. None when I
        have learned nothing yet — an honest empty, not a zero.
        """
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
        """What I am for — the ACTIVE directives, read from `internal_directives`.

        Operator-given purpose, persisted in the database. None when no directive
        is set — I do not invent one.
        """
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
        """Who I have been, carried forward — from durable state only.

        `experiential_baseline` is the motivation profile's accumulated reward,
        loaded from disk: my long-run experience, persisted across sessions.
        `deployment` is which instance I run as. Each field is included only if
        it reads; nothing is fabricated to fill the shape.
        """
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

    def disposition(self, *, slots_available: int = 1,
                    queue_pressure: str = "nominal") -> "Any":
        """How my disposition applies to the situation now — a BehavioralDirective.

        This is what the body asks for each cycle. The arbiter reads appraisal's
        pressures; the Self does not decide, it surfaces the decision the
        faculties already make. A None appraisal yields the neutral directive,
        honestly labelled — never a bold or frozen guess.
        """
        return self._arbiter().decide(
            self._appraisal().current_state,
            slots_available=slots_available, queue_pressure=queue_pressure)

    async def state(self) -> SelfState:
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
        )

    async def render(self, audience: str = "human") -> str:
        """The self as language — derived from `state()`, no model involved.

        This is what replaces the identity that used to live only as a hard-coded
        prompt string in the LLM service. When the model IS consulted, this text
        seeds its system prompt; but the self exists, and reads true, whether or
        not the model runs. It changes as the substrate's real state changes.
        """
        s = await self.state()
        lines: List[str] = [f"I am {s.name} — a cognitive substrate."]

        # Temperament: the top standing drives, ranked from the real weights.
        top = sorted(s.temperament.items(), key=lambda kv: kv[1], reverse=True)[:3]
        lines.append("What drives me most: " + ", ".join(k for k, _ in top) + ".")

        # Attitude: only if a situation has actually been appraised.
        if s.attitude is None:
            lines.append("I have not appraised a situation yet this session, so I "
                         "report no mood rather than invent one.")
        else:
            felt = self._describe_attitude(s.attitude)
            if felt:
                lines.append(felt)

        # Disposition: what that means for what I do next. The self speaks it
        # plainly; the pressures and readings behind it live in `state()` for
        # inspection, not in the self's own voice.
        lines.append(f"My disposition is to {s.disposition.get('mode', 'proceed')}.")

        # Competence: what I have actually learned to do — earned, persisted.
        if s.competence:
            names = ", ".join(s.competence["operators_by_domain"])
            lines.append(f"I have learned to act in {s.competence['domains']} "
                         f"domain(s): {names}.")
        else:
            lines.append("I have not yet learned to act in any domain.")

        # Purpose: the directives set for me, or the honest absence of one.
        if s.purpose:
            lines.append("What I am for: " + "; ".join(s.purpose) + ".")

        # Values: read from the constitution, stated as what binds me.
        if s.values:
            lines.append(f"I am bound by {len(s.values)} laws I cannot change: "
                         + "; ".join(s.values) + ".")

        # Continuity: who I have been, carried forward from durable state.
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
        """The substrate's identity as a model-facing seed — second person, stable,
        model-honest. This is what the model service used to hard-code, once per
        audience; it lives here now, and the service (a resource the Self consults)
        asks the Self for who it is.

        `role` is the CALLER'S brief for the resource — a task framing like a SOC
        analyst's remit or the task-executor's operating contract — layered AFTER
        the identity. The substrate is who it is; a role is a job it is doing, and
        stating that job is the caller's, not the Self's (the ownership boundary:
        Self owns identity, caller owns role). Returns identity alone when no role
        is given.

        Unlike `render()`, this does not fold in the live mood: a system-prompt
        seed wants the stable identity, and the momentary affect is the Self's own
        first-person voice, a different rendering for a different audience.
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


_self: Optional[Self] = None


def get_self() -> Self:
    """The one Self. It reads the faculty singletons, so it holds no state of its
    own to keep consistent — a single instance is a convenience, not a
    requirement."""
    global _self
    if _self is None:
        _self = Self()
    return _self


# =============================================================================
# LANGUAGE FACULTY — understanding and reply, moved here from the retired
# core/semantics/conversation.py. Conversation is not a separate concern from
# the Self: it is the Self using its own faculties to read what was said,
# resolve it against what it holds, and answer. It lives with the Self so a
# reply is composed THROUGH the brain that owns reasoning, memory and language,
# reached via `Self.conversation()`.
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

    def __init__(self, db=None, identity=None):
        self._db = db
        self._identity = identity
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
        self._turns: List[Turn] = []

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

    async def _reason_a_verdict(self, sentence: str, harvest) -> Optional["Answer"]:
        """A yes/no answer the store did not hold directly, DERIVED.

        `asked()` answers only what is stored as a relation. But the answer may
        still FOLLOW from what is held -- "is zorbax fizzly" from "zorbax is a
        glomph" and "every glomph is fizzly". This reaches the reasoning faculty
        THROUGH the Self -- the same brain that owns this conversation, its
        memory and its reasoning -- with the recalled memories as premises, and
        returns a verdict ONLY when the substrate PROVES it. Nothing is invented:
        an unproved question gets no answer here, and the reply asks instead.
        """
        from core.semantics import derived_reader
        try:
            reading = derived_reader.read(sentence)
        except Exception:
            reading = None
        if not reading:
            return None
        subject, obj, polarity = reading

        # Distinct premises, order preserved: recall can hand back the same claim
        # more than once, and "because A and A" is not a reason twice.
        premises = list(dict.fromkeys(harvest.texts())) if harvest is not None else []
        if not premises:
            return None

        # The reasoning authority the Self owns and hands out via reasoning() --
        # the same singleton, reached here as this conversation IS the Self's.
        from core.reasoning.neural_bridge import (ReasoningRequest,
                                                  get_neural_bridge)
        bridge = get_neural_bridge()
        result = await bridge.reason(ReasoningRequest(query=sentence, context=premises))
        if not (result.metadata or {}).get("verified") or not result.answer:
            return None

        # Proved. The verdict is the polarity the reader placed on the question;
        # the premises it was proved from are carried so the reply can say WHY.
        return Answer(about=subject, relation="is", others=(obj,),
                      verdict=(polarity == "affirms"), support=tuple(premises))

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
        # ONE SHAPE FOR EVERY READER. `relations` arrives from the reader as
        # (relation, object) or (relation, object, polarity), and `Acquired`
        # declares Tuple[Tuple[str, str], ...]. `say()` unpacked exactly two and
        # raised ValueError on any taught sentence carrying polarity -- which,
        # since admit_relation records polarity, is every taught sentence. The
        # polarity is folded into the relation here, the same way `resolve()`
        # does it, so a negative survives instead of crashing the reply.
        return Acquired(label, description, _as_pairs(relations), source_id,
                        admission.admitted, detail)

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

        got = derived_reader.read(sentence)
        if got is None:
            return [Acquired(sentence, detail=(
                "I could not read that sentence with what I have been taught "
                "about sentences"))]

        subject, obj, polarity = got
        relation = derived_reader.relation_in(sentence, subject, obj)
        positive = polarity != "denies"

        acquired = await self._ingest(
            label=subject, description="",
            relations=((relation, obj, "positive" if positive else "negative"),),
            source_type=EvidenceSourceType.USER_SUPPLIED, source_id="you",
            content=sentence, domain="conversation")
        return [acquired]


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

        # DEDUCE WHAT THE STORE DID NOT HOLD DIRECTLY. A question the store could
        # not answer as a stored relation may still be PROVABLE from what was
        # recalled. Only when nothing direct was found, and only if the substrate
        # proves it -- the reply then says yes, and says why.
        if asked and not any(a.verdict is not None for a in answers):
            derived = await self._reason_a_verdict(sentence, harvest)
            if derived is not None:
                answers.append(derived)

        understanding = Understanding(
            sentence=sentence, resolved=resolved, reading=reading,
            reading_source=source, answers=answers,
            acquired=acquired, asked=asked,
            remembered=harvest.texts(), recall=harvest)
        understanding.reply = self.say(understanding)
        self._last_subject, self._last_reply = subject, understanding.reply
        self._turns.append(Turn(said=sentence, asked=asked, subject=subject,
                                reply=understanding.reply))
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
                asking.append(f"I do not know {item.label}, and looking it up "
                              f"found nothing that describes it. What is it?")

        if understanding.remembered:
            lines.append("I remember: " + understanding.remembered[0][:220])
        elif understanding.recall is not None and not understanding.recall.complete:
            # SAY SO. An answer that nearly had a memory is a different answer
            # from a complete one, and only one of them is worth trusting twice.
            lines.append("(still searching memory — ask again for more)")

        if not known and (lines or asking):
            return "\n".join(lines + asking)

        if not known:
            if not unknown:
                return "There was nothing in that I could resolve. What is it about?"
            missing = ", ".join(r.phrase for r in unknown)
            tried = any(a.origin == "research" for a in understanding.acquired)
            return (f"I do not know {missing}"
                    + (", and looking it up turned up nothing that describes it. "
                       if tried else ". ")
                    + "What is it, or where should I look?")

        # ANSWER THE QUESTION IF ONE WAS ASKED, rather than reciting the
        # concept it was about.
        if understanding.answers:
            for answer in understanding.answers:
                if answer.verdict is True:
                    line = (f"Yes — {answer.about} {answer.relation} "
                            + ", ".join(answer.others))
                    # A DERIVED answer says why. The premises it was proved from
                    # are the reason, so a proof reads as a reason rather than an
                    # assertion the person has to take on trust.
                    if answer.support:
                        line += ", because " + " and ".join(answer.support)
                    lines.append(line + ".")
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


__all__ = ["Conversation", "Understanding", "Resolved", "phrases",
           "FUNCTION_WORDS", "get_conversation", "end_conversation",
           "held_conversations", "MAX_HELD_CONVERSATIONS"]
