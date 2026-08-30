#!/usr/bin/env python3
"""
Neural Bridge
=============
Bridges symbolic reasoning with neural processing

Purpose:
- Connect logical reasoning with neural networks
- Hybrid reasoning (symbolic + neural)
- Convert between representations
- Optimize reasoning with neural guidance
"""

import asyncio
import json
import logging
import math
import re
import uuid

from core.semantics import lexical_normalization as _lexical
from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional, Set, Tuple
from enum import Enum

from .arithmetic_reading import read as read_equation
from .arithmetic_reading import read_sequence
# READING BELONGS TO SEMANTICS.
#
# 619 lines of English patterns, plus the genericity stage and the word-class
# lookup, used to live in this file. Reasoning should CONSUME a reading, not
# implement one -- the learned reader, the lexicon, the claim shapes and the
# sentence machine are all in `core.semantics`, and these were the odd ones out.
#
# What stays here is the FORMALIZER: turning a reading into the statement and
# premises a solver can take. That is the reasoning side of the boundary.
from core.semantics.genericity import (Genericity, classify_genericity,
                                       unrepresentable_reason, _word_class,
                                       _subject_and_complement)
from core.semantics.sentence_reader import SentenceReader
from .reasoning_interfaces import (CLASSICAL_REASONING_TYPES, Connectivity,
                                   Formalization, IFormalizer, ReasoningType,
                                   kinds_of_thinking_for)

logger = logging.getLogger(__name__)


class ReasoningMode(Enum):
    """WHICH MACHINERY RUNS WHEN THE SUBSTRATE CANNOT SETTLE IT.

    THESE ARE NOT KINDS OF THINKING. The kinds of thinking are the eleven in
    `ReasoningType` -- deductive, inductive, abductive, analogical, causal,
    probabilistic, fuzzy, temporal, spatial, logical, counterfactual -- and a
    caller names those through `ReasoningRequest.kinds`.

    These seven are execution routes, and the vocabulary shows its age:
    SYMBOLIC / NEURAL / HYBRID / NEURO_SYMBOLIC is the neuro-symbolic framing,
    a taxonomy of implementation, with one member named after a model. Under
    substrate-first that cannot be what an entry point asks for, and it no
    longer is: `_substrate_solvers` runs for EVERY request regardless of mode, and
    the kinds of thinking are tried before any of these. A mode is consulted
    only when neither could settle the question.

    Kept because each names a real handler that does something different, and
    because a caller may legitimately want to choose the fallback.
    """

    SYMBOLIC = "symbolic"                # solver over a formalized statement
    NEURAL = "neural"                    # model inference; the last resort
    HYBRID = "hybrid"                    # propose, constrain, revise
    NEURO_SYMBOLIC = "neuro_symbolic"    # plan then execute
    ABSTRACT = "abstract"                # the strategy registry: all 11 kinds
    CROSS_DOMAIN = "cross_domain"        # grounding between domains


@dataclass
class ReasoningRequest:
    """Request for neural-symbolic reasoning"""
    query: str
    context: List[str] = field(default_factory=list)
    # Reasoning is substrate-first and substrate-only; there is no AUTO mode
    # and no fallback. `mode` is retained for callers that name a specific
    # machinery, and defaults to ABSTRACT -- the eleven kinds of thinking.
    mode: ReasoningMode = ReasoningMode.ABSTRACT

    #: WHICH KINDS OF THINKING THIS ASKS FOR -- the eleven in `ReasoningType`.
    #:
    #: The eleven used to be unreachable from here. `mode` selects one of seven
    #: execution ROUTES, so a caller had no way to ask for causal or temporal
    #: reasoning at all, and those strategies were entered only when the router
    #: happened to pick ABSTRACT. Eleven kinds registered and implemented,
    #: nine of them unaskable.
    #:
    #: Empty means "read it from the query": `kinds_of_thinking_for` looks for
    #: the markers, and an unmarked query falls back to every classical kind,
    #: with each strategy's `is_applicable` refusing unless the material is
    #: actually present. Naming kinds here overrides that reading.
    kinds: List["ReasoningType"] = field(default_factory=list)

    max_steps: int = 10
    confidence_threshold: float = 0.7
    # Vision inputs (optional)
    image: str = None  # Path to image file or PIL Image
    video: str = None  # Path to video file
    # Cached memories (optional) - if provided, skip memory injection
    # Empty list [] = skip injection (memories already in conversation)
    # None = perform fresh memory search
    cached_memories: Optional[List] = None
    # Token budget from caller (if None, neural_bridge uses its own default)
    max_tokens: Optional[int] = None

    # Lightweight task context / metadata used by the reasoning router.
    # This keeps routing decisions cheap and avoids re-parsing the full
    # conversation when a structured task object already exists.
    task_metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ReasoningResult:
    """Result from neural-symbolic reasoning"""
    answer: str
    confidence: float
    reasoning_steps: List[str] = field(default_factory=list)
    mode_used: ReasoningMode = ReasoningMode.HYBRID
    metadata: Dict[str, Any] = field(default_factory=dict)
    full_response: str = ""  # the teacher model's complete chain of thought output


#: Confidence attached to an answer that no solver has checked.
#:
#: This is a placeholder standing for "unverified", not a measurement. It
#: deliberately replaces an earlier heuristic that scored confidence by answer
#: length (0.75 over fifty characters, else 0.6), which meant an empty answer
#: from a dead model still reported 0.6.
#:
#: Gates should key on metadata["verified"] rather than on this number.
#: Verified results take their confidence from the solver instead — see
#: NeuralSymbolicBridge._symbolic_reasoning.
UNVERIFIED_CONFIDENCE = 0.5

#: Default completion budget for a single neural answer.
#:
#: Reasoning models spend part of this on chain-of-thought before emitting any
#: answer, and that thinking is billed against the same allowance, so the
#: budget has to cover both or the answer is truncated to nothing.
NEURAL_TOKEN_BUDGET = 2048

# Reason codes reported on ReasoningResult.metadata["reason"].
#
# These exist so credit assignment can separate three different things that
# all used to look like "low confidence": the substrate reasoned and reached a
# verdict, the input could not be represented at all, and a model was needed
# but unavailable or failing.
REASON_SUBSTRATE_VERIFIED = "substrate_verified"    # solver proved the goal
REASON_SUBSTRATE_REFUTED = "substrate_refuted"      # solver decided against it
#: A KIND OF THINKING derived it -- causal, spatial, temporal and the rest --
#: without propositional formalization or a solver. Distinct from
#: SUBSTRATE_VERIFIED on purpose: that means a solver checked a formalized
#: statement, this means a strategy composed the conclusion from the premises.
#: Both are the substrate answering; they are not the same evidence, and a
#: consumer that treats them alike cannot tell a proof from a derivation.
REASON_DERIVED_BY_KIND = "derived_by_kind"
REASON_SUBSTRATE_UNDECIDED = "substrate_undecided"  # solver gave up (timeout)
REASON_MODEL_COVERAGE = "model_coverage"            # teacher supplied representation
REASON_MODEL_FAILED = "model_generation_failed"     # teacher was asked and failed
REASON_UNSUPPORTED_INPUT = "unsupported_input"      # the substrate could not represent it

#: Function/question words that carry no subject matter, so a belief matching a
#: query only through one of these is not actually relevant. Used by the learned
#: (NEURAL) route to require content-word overlap.
_BELIEF_STOPWORDS = frozenset({
    "what", "when", "where", "who", "whom", "why", "how", "which", "whose",
    "is", "are", "was", "were", "be", "been", "being", "am",
    "do", "does", "did", "done", "have", "has", "had",
    "the", "and", "for", "not", "but", "with", "from", "about", "into",
    "should", "would", "could", "will", "shall", "can", "may", "might", "must",
    "you", "your", "yours", "this", "that", "these", "those", "they", "them",
    "there", "here", "then", "than", "some", "any", "all", "each", "every",
})

#: THE SUBSTRATE IS NOT A MODEL, AND IT NEVER *REQUIRES* ONE.
#:
#: This metadata used to say `model_required: True` whenever the substrate
#: could not formalize an input. That asserts the architecture backwards: it
#: reads as "this system needs a model to answer", when the true statement is
#: "the substrate could not represent THIS INPUT". Whether a teacher happens to
#: be reachable is a separate and optional fact about coverage, not about
#: whether reasoning is possible.
#:
#: `substrate_formalized` is the claim that matters, and it is about the
#: substrate alone. `teacher_available` records reachability without implying
#: dependence. `model_required` is retained as a deprecated alias so existing
#: readers do not break, and it is now always False -- because it is never true.
KEY_SUBSTRATE_FORMALIZED = "substrate_formalized"
KEY_TEACHER_AVAILABLE = "teacher_available"
KEY_TEACHER_CONSULTED = "teacher_consulted"

#: The solver proved the goal, but from premises a model wrote rather than the
#: substrate derived. The entailment is verified; the representation is not,
#: and a proof is only as sound as the premises it starts from.
REASON_ENTAILMENT_ONLY = "entailment_verified_premises_unverified"
#: The capability that owns this kind of question is not present. NOT the
#: same as "could not represent it" -- the reading succeeded and the owner
#: is missing, which is a wiring or environment fault. Reported rather than
#: routed around, so severing a capability is observable instead of being
#: quietly covered by a model.
REASON_CAPABILITY_UNAVAILABLE = "capability_unavailable"
#: The request itself was malformed. Not a failure to reason.
REASON_INVALID_INPUT = "invalid_input"
#: Something raised inside the reasoning path. A fault, never an answer.
REASON_INTERNAL_FAULT = "internal_fault"


#: Arrows that make a context item a RULE rather than a premise. Small and
#: visible: the same three forms `_split_rule` accepts, kept in step with it so
#: an item read as a rule here is one the strategies can actually use.
_IMPLICATION_ARROWS = ("->", "=>", "\u2192")


def _is_implication(text: str) -> bool:
    """Whether this context item states a rule rather than a fact."""
    return any(arrow in text for arrow in _IMPLICATION_ARROWS)


#: Ubiquitous function words that connect any two sentences, so they must not
#: carry topic connectivity. Relational words (before, after, during, inside,
#: through, causes) are DELIBERATELY kept -- they are what a temporal or spatial
#: claim is actually about.
_RELEVANCE_STOPWORDS = frozenset({
    "is", "are", "was", "were", "be", "been", "being", "am",
    "the", "an", "of", "to", "in", "on", "at", "for", "and", "or", "not",
    "this", "that", "these", "those", "it", "its", "as", "by", "with", "from",
    "has", "have", "had", "do", "does", "did", "will", "would", "shall",
    "can", "could", "may", "might", "must", "there", "here",
    "what", "when", "where", "who", "whom", "why", "how", "which", "whose",
    "you", "your", "we", "they", "he", "she", "them", "his", "her",
})


def _content_terms(text: str) -> set:
    """Topic-bearing words, plurals folded so 'ravens' and 'raven' are one term."""
    terms = set()
    for tok in re.findall(r"[a-z0-9]+", str(text).lower()):
        if len(tok) <= 2 or tok in _RELEVANCE_STOPWORDS:
            continue
        if tok.endswith("ies") and len(tok) > 4:
            tok = tok[:-3] + "y"
        elif tok.endswith("es") and len(tok) > 4:
            tok = tok[:-2]
        elif tok.endswith("s") and not tok.endswith("ss") and len(tok) > 3:
            tok = tok[:-1]
        terms.add(tok)
    return terms


def _query_topic(query: str, context) -> set:
    """Terms connected to the query through shared-term co-occurrence across the
    query and its context -- the topic the query is actually about. A conclusion
    OUTSIDE this component answers a different question than the one asked, which
    is the off-topic-kind failure (the temporal kind reading 'during' in an
    unrelated premise). Abduction stays IN the component: its answer 'rained'
    shares no word with 'explains wet lawn' but connects through the rule
    'rained -> wet(lawn)', which does."""
    sentence_terms = [_content_terms(query)] + [_content_terms(c) for c in (context or [])]
    component = set(sentence_terms[0])
    if not component:
        return set()  # the query carries no topic; relevance cannot be judged
    changed = True
    while changed:
        changed = False
        for ts in sentence_terms:
            if ts & component and not ts <= component:
                component |= ts
                changed = True
    return component


def _relevant_to_topic(statement: str, topic: set) -> bool:
    """Relevant when the conclusion shares a term with the query's topic, or when
    the query carried no topic to judge against."""
    if not topic:
        return True
    return bool(_content_terms(statement) & topic)


# ---------------------------------------------------------------------------
# GENERICITY: what proposition a copular sentence expresses.
#
# Lives beside the other reading vocabulary rather than in a module of its own,
# because `DeterministicExtractor` below already owns turning a sentence into a
# proposition (_FACT, _UNIVERSAL, _CONDITIONAL, _QUESTION). A separate module
# would be a second authority on how a sentence is read.
#
# "A robin is a bird" and "A robin is in the yard" have the same surface shape
# and mean different things. Reading the article `a` as a quantifier turns the
# second into a law about all robins -- an overgeneralization machine. So the
# proposition type is decided first and the representation follows from it.
# ---------------------------------------------------------------------------



#: Locative prepositions and adverbs. A copula that LOCATES is not classifying,
#: so an indefinite subject with one of these is existential, never generic.


#: A complement denoting a kind: an indefinite article and a single common noun.


@dataclass(frozen=True)












class PassthroughFormalizer(IFormalizer):
    """Accepts input already written in the formal grammar.

    Consulted first and needs no language model, so a formally-stated query
    reasons at full strength even when the model is unavailable.
    """

    name = "passthrough"

    async def formalize(
        self,
        query: str,
        context: Optional[List[str]] = None
    ) -> Formalization:
        # Imported lazily: logical_integration imports this package inside its
        # own functions, so a module-level import here would risk a cycle.
        from core.agents.logical.logical_integration import LogicalFormulaParser

        parser = LogicalFormulaParser()

        if not query or not parser.is_formal(query):
            return Formalization(
                source=self.name,
                succeeded=False,
                error="query is not written in the formal grammar"
            )

        # Context items that do not parse are dropped rather than guessed at.
        # This is sound: withholding a premise can only make a goal harder to
        # prove, never cause something false to be proved.
        premises = [item for item in (context or []) if parser.is_formal(item)]
        ignored = len(context or []) - len(premises)
        if ignored:
            logger.debug(
                f"passthrough formalizer ignored {ignored} non-formal context item(s)"
            )

        return Formalization(
            statement=str(query).strip(),
            premises=premises,
            source=self.name,
            succeeded=True,
            requires_model=False,
        )




class DeterministicExtractor(IFormalizer):
    """Translates a bounded slice of natural language into the formal grammar.

    Needs no model, so every input it covers is reasoned about with the model
    untouched. Its purpose is to keep shrinking the set of inputs that require
    model-backed coverage; adding a pattern here moves that share permanently.

    The substrate is propositional, so universally quantified sentences cannot
    be represented directly. They are instead *grounded*: "All humans are
    mortal" becomes one implication per subject actually mentioned, e.g.
    socrates_human -> socrates_mortal. That keeps the encoding sound while
    staying inside propositional logic.

    Supported today::

        X is [a] P            ->  x_p
        X is not [a] P        ->  ~x_p
        All P are Q           ->  <s>_p -> <s>_q      for each subject s
        Every P is Q          ->  (same)
        No P is Q             ->  <s>_p -> ~<s>_q     for each subject s
        If X is P then X is Q ->  x_p -> x_q
        Is X [a] P ?          ->  goal x_p

    Anything else is declined so the chain can fall through, rather than
    guessed at. A wrong guess here would put a false premise in front of the
    solver, which is the one failure mode the substrate cannot detect.
    """

    name = "extractor"

    #: The reading itself, owned by the semantics faculty. This class is now
    #: only the formalizer: it asks what the sentence says and renders that into
    #: the solver's grammar.
    _reader = SentenceReader()


    #: An optional leading determiner on the SUBJECT. `_normalize` already
    #: strips articles, but it runs on the captured groups -- and the pattern
    #: never matched in the first place, because the subject is deliberately a
    #: single token and "A robin" is two. So "A robin is a bird" was not merely
    #: mis-parsed, it was UNREPRESENTABLE: `_parse_statement` returned None, the
    #: sentence never reached a solver, and the symbolic path reported 0.0
    #: confidence that read as "the substrate cannot do this" rather than "the
    #: substrate was never given it". Measured: the bare "robin is a bird"
    #: parsed correctly all along.
    #:
    #: Widened here rather than by allowing multi-word subjects, because a
    #: multi-word subject makes "All humans are mortal" ambiguous against the
    #: universal pattern, and single-token subjects are relied on downstream.

    #: `is|are`, not `is`. These two patterns accepted only the singular copula
    #: while `_UNIVERSAL` immediately below already accepted both, so
    #: "the valves are open" produced NO reading at all -- not a wrong one, no
    #: reading -- purely because of the number of the subject. The sentence
    #: machine's own COPULAS set has held {is, are} the whole time.

    #: SUBJECT VERB OBJECT, gated on the lexicon.
    #:
    #: This shape -- "the pump moves water" -- was unreadable, which is most of
    #: English. It cannot be matched by pattern alone: "the pump moves water"
    #: and "the cold water flows" have the same token shape and differ only in
    #: which word is the verb. So the pattern finds the candidate and the
    #: LEXICON decides, which means the reading only works for words whose
    #: class has been established. Teaching a verb therefore changes what the
    #: substrate can read, and that change is measurable.

    #: A closed list of place relations. Small and visible on purpose: this is
    #: not an attempt at English prepositions, it is the handful whose meaning
    #: is a relation between two things.

    #: The object may be more than one word ("the top cabinet"). Matching only
    #: a single word meant "the cup is in the top cabinet" failed the pattern
    #: and FELL THROUGH to the plain-fact path, which put `in` in the property
    #: slot -- so positional observation dutifully recorded `in` as an
    #: adjective, along with `on`, `near`, `at`, `for` and `under`. Six false
    #: entries out of 1,326, every one produced by a pattern that degraded
    #: instead of refusing.

    #: SUBJECT VERB, same gate. "the motor drains".












    async def formalize(
        self,
        query: str,
        context: Optional[List[str]] = None
    ) -> Formalization:
        if not query or not str(query).strip():
            return Formalization(
                source=self.name, succeeded=False, error="empty query"
            )

        goal = self._reader._parse_goal(str(query))
        # An action sentence is a goal too. Restricting goals to "fact" meant
        # the SVO/SV forms parsed correctly and were then thrown away here, so
        # teaching a verb changed nothing observable.
        if goal is None or goal["kind"] not in ("fact", "svo", "sv",
                                                "relation", "conjunction"):
            return Formalization(
                source=self.name,
                succeeded=False,
                error=f"goal is outside the supported patterns: {query!r}",
            )

        parsed: List[Dict[str, Any]] = []
        for sentence in (context or []):
            node = self._reader._parse_statement(str(sentence))
            if node is None:
                # Decline rather than drop the sentence. A silently ignored
                # premise turns a provable goal into an unexplained failure.
                return Formalization(
                    source=self.name,
                    succeeded=False,
                    error=f"unsupported premise: {sentence!r}",
                )
            if node["kind"] == "unsupported":
                # Classified successfully, cannot be represented. Naming which
                # is the difference between "Torin misread this" and "the
                # formal language has no existential quantifier".
                return Formalization(
                    source=self.name,
                    succeeded=False,
                    error=f"{node['reason']}: {sentence!r} reads as "
                          f"{node['genericity']} ({node['cue']})",
                )
            parsed.append(node)

        # Subjects are the individuals universals get grounded over.
        #
        # A GENERIC GOAL HAS NO INDIVIDUAL, and without one it cannot be
        # proved. "Is a robin an animal?" grounded the universals over the KIND
        # name, producing `robin_robin -> robin_bird`, and `robin_robin` is
        # never asserted -- so a question whose premises plainly entail it came
        # back "not entailed by the premises".
        #
        # Proving something of a kind is proving it of an ARBITRARY member, so
        # one is introduced: a fresh individual asserted to be of that kind.
        # Nothing else is assumed about it, which is what makes the conclusion
        # general rather than a claim about one thing.
        skolem = None
        if goal.get("genericity") == Genericity.GENERIC_KIND.value:
            kind = self._reader._singular(self._reader._normalize(goal["subject"]))
            skolem = f"any_{kind}"
        subjects = {skolem or self._reader._normalize(goal["subject"])}
        for node in parsed:
            if node["kind"] == "fact":
                subjects.add(self._reader._normalize(node["subject"]))
            elif node["kind"] == "conditional":
                subjects.add(self._reader._normalize(node["antecedent"]["subject"]))
                subjects.add(self._reader._normalize(node["consequent"]["subject"]))
            elif node["kind"] in ("svo", "sv", "relation", "conjunction"):
                subjects.add(self._reader._normalize(node["subject"]))

        premises: List[str] = []
        for node in parsed:
            if node["kind"] == "fact":
                premises.append(self._reader._render_fact(node))

            elif node["kind"] in ("svo", "sv"):
                # "the pump moves water" -> pump_moves_water
                # "the motor drains"     -> motor_drains
                # An action is a relation between the actor and what it acts on,
                # rendered as one atom so it lands in the same solver the copular
                # facts do rather than needing a second representation.
                premises.append(self._reader._render_action(node))

            elif node["kind"] == "relation":
                premises.append(self._reader._render_relation(node))

            elif node["kind"] == "conjunction":
                # TWO CLAIMS, TWO PREMISES. This is the whole point of reading
                # "and" as a conjunction: each half stands on its own and can be
                # checked against anything else known about it.
                premises.extend(self._reader._render_conjunction(node))

            elif node["kind"] == "conditional":
                antecedent = self._reader._render_fact(node["antecedent"])
                consequent = self._reader._render_fact(node["consequent"])
                premises.append(f"({antecedent}) -> ({consequent})")

            elif node["kind"] == "universal":
                p = self._reader._singular(self._reader._normalize(node["p"]))
                q = self._reader._singular(self._reader._normalize(node["q"]))
                for subject in sorted(subjects):
                    consequent = f"~{subject}_{q}" if node["negated"] else f"{subject}_{q}"
                    premises.append(f"{subject}_{p} -> {consequent}")

        if not premises:
            return Formalization(
                source=self.name,
                succeeded=False,
                error="no premises could be represented",
            )

        if skolem is not None:
            # The arbitrary member is of the goal's kind, and the goal becomes a
            # claim about it.
            kind = self._reader._singular(self._reader._normalize(goal["subject"]))
            premises.append(f"{skolem}_{kind}")
            statement = f"{skolem}_{self._reader._singular(self._reader._normalize(goal['prop']))}"
        elif goal["kind"] in ("svo", "sv"):
            statement = self._reader._render_action(goal)
        elif goal["kind"] == "relation":
            statement = self._reader._render_relation(goal)
        elif goal["kind"] == "conjunction":
            # A conjunctive GOAL asks for BOTH halves. `statement` can hold one,
            # so the rest travel in `statements` rather than being dropped.
            all_claims = self._reader._render_conjunction(goal)
            statement = all_claims[0]
            every_statement = all_claims
        else:
            statement = self._reader._render_fact(goal)
        readings = [
            {"surface": surface, "genericity": node.get("genericity"),
             "cue": node.get("cue"), "kind": node["kind"]}
            for surface, node in zip([str(c) for c in (context or [])], parsed)
        ]
        transformations = sorted({t for node in parsed
                                  for t in node.get("transformations", [])}
                                 | {"article_removal", "singularisation"})
        return Formalization(
            statement=statement,
            statements=locals().get("every_statement") or [statement],
            premises=premises,
            source=self.name,
            succeeded=True,
            requires_model=False,
            connectivity=self._connectivity(statement, premises),
            surface_text=[str(c) for c in (context or [])],
            readings=readings,
            transformations=transformations,
        )

    @staticmethod
    def _connectivity(statement: str, premises: List[str]) -> Connectivity:
        """Whether the goal's atom occurs anywhere in the premises.

        A goal the premises never mention cannot be decided by them, and the
        solver's 0.0 would be read as "not entailed" when it means "you asked
        something these premises do not speak to". Reported so the caller can
        tell a translation gap from a genuine non-entailment.

        Deliberately a vocabulary test and not a reachability proof: whether
        the goal FOLLOWS is the solver's job, and duplicating that judgement
        here would give the substrate two answers to the same question.
        """
        goal_atom = statement.lstrip("~").strip()
        if not goal_atom:
            return Connectivity.DISCONNECTED
        mentioned = any(
            goal_atom in re.split(r"[^\w]+", premise) for premise in premises
        )
        return Connectivity.CONNECTED if mentioned else Connectivity.DISCONNECTED


class DerivedReadingFormalizer(IFormalizer):
    """Formalizes with readings the substrate derived, not ones anyone wrote.

    Consulted after the hand-written patterns and before any model, so it only
    ever sees input the tested path declined -- and every input it covers is
    one more reasoned about with the model untouched. `requires_model` stays
    False, which is what makes the substrate-native share move for a reason
    other than somebody adding a regex.

    Declines where no registered reading applies, exactly as the extractor
    does. A reading that produced something for every sentence would be
    guessing, and a guess here becomes a premise the solver cannot doubt.
    """

    name = "derived"

    @staticmethod
    def _atom(sentence: str) -> Optional[Tuple[str, str]]:
        """The formal atom for one sentence, and which reading produced it."""
        from core.semantics.reading_registry import get_reading_registry
        from core.semantics.derived_reader import covers

        for reading in get_reading_registry().readings():
            try:
                produced = reading.read(sentence)
            except Exception as error:  # a derived procedure is still a program
                logger.debug("derived reading %s failed on %r: %s",
                             reading.name, sentence, error)
                continue
            if produced is None:
                continue
            subject, obj, polarity = produced

            # THE MACHINE ALWAYS EMITS. A reading that leaves content words
            # behind did not read the sentence, it picked two words out of it --
            # "what should I name my startup?" came back as (what, startup). The
            # covers() residue guard turns that guess into a decline, so a
            # sentence the reading does not account for reaches the solver as
            # nothing rather than as a fabricated premise.
            accounted, _residue = covers(sentence, subject, obj)
            if not accounted:
                logger.debug("derived reading left content words behind on %r",
                             sentence)
                continue

            # A DERIVED READING IS STILL SUBJECT TO REPRESENTABILITY.
            #
            # The reading says WHAT the sentence relates; genericity says
            # whether the formal grammar can carry that relation. They are
            # separate stages on purpose, and skipping the second here let the
            # learned reader do exactly what the hand-written patterns had just
            # been stopped from doing: "a robin is in the yard" came back as
            # `robin_yard`, which reads `robin` as a named individual when the
            # sentence says SOME robin. The existential quantification was
            # dropped silently, and the atom asserted something about the kind.
            #
            # Measured at the time: patterns declined it and the derived reader
            # did not, so removing the patterns would have reintroduced the
            # overgeneralisation through the other reader.
            #
            # This adds no pattern and no wording knowledge. It applies the
            # representability rule the substrate already owns to whatever the
            # reading produced.
            determiner, complement = _subject_and_complement(sentence, subject)
            reading_kind = classify_genericity(subject, complement, determiner)
            if not reading_kind.is_representable:
                logger.info("derived reading declined %r: %s", sentence,
                            unrepresentable_reason(reading_kind.genericity))
                continue

            atom = f"{subject}_{obj}"
            return (atom if polarity == "affirms" else f"~{atom}"), reading.name
        return None

    async def formalize(self, query: str,
                        context: Optional[List[str]] = None) -> Formalization:
        """Query and premises alike, which is the extractor's own contract.

        A sentence is worth reading wherever it appears; formalizing only the
        question would offer the solver a goal with nothing to prove it from.
        """
        premises, used, surface = [], [], []
        for sentence in (context or []):
            read = self._atom(sentence)
            if read is None:
                # A CONTEXT SENTENCE THAT CANNOT BE READ IS NOT DROPPED. Dropping
                # it would hand the solver an incomplete premise set, and a
                # missing premise is the one failure the solver cannot detect --
                # it would prove a goal the full context might have refuted. So
                # an unreadable premise declines the whole request, exactly as
                # the deterministic extractor does.
                return Formalization(
                    succeeded=False, source=self.name,
                    error=f"context sentence not readable by any derived "
                          f"reading: {sentence!r}")
            premises.append(read[0])
            used.append(read[1])
            surface.append(sentence)

        goal = self._atom(query)
        if goal is None:
            return Formalization(
                succeeded=False, source=self.name,
                error="no derived reading applied to this input")

        return Formalization(
            statement=goal[0], premises=premises,
            source=f"{self.name}:{goal[1]}", succeeded=True,
            requires_model=False, surface_text=[query] + surface,
            transformations=[f"read by {name}" for name in dict.fromkeys([goal[1]] + used)],
        )


class FormalizerChain(IFormalizer):
    """Consults formalizers in order and returns the first success.

    The order encodes trust: formal input first (no model at all), then any
    deterministic extractor, then the language model. Promoting a deterministic
    extractor later is a list insertion here, not a change to any caller.
    """

    name = "chain"

    def __init__(self, formalizers: List[IFormalizer]) -> None:
        self.formalizers = list(formalizers)

    async def formalize(
        self,
        query: str,
        context: Optional[List[str]] = None
    ) -> Formalization:
        failures: List[str] = []

        for formalizer in self.formalizers:
            try:
                result = await formalizer.formalize(query, context)
            except Exception as e:
                failures.append(f"{formalizer.name}: {e}")
                continue

            if result.succeeded:
                return result
            if result.error:
                failures.append(f"{formalizer.name}: {result.error}")

        return Formalization(
            source=self.name,
            succeeded=False,
            error="; ".join(failures) or "no formalizer produced a formal statement"
        )



class NeuralSymbolicBridge:
    """
    Neural-Symbolic Reasoning Bridge

    Purpose:
    - Bridge symbolic logic and neural networks
    - Hybrid reasoning combining both approaches
    - Optimize reasoning with neural guidance
    - Convert between symbolic and neural representations

    Usage:
        bridge = NeuralSymbolicBridge()
        await bridge.initialize()

        request = ReasoningRequest(
            query="What is 2+2?",
            mode=ReasoningMode.HYBRID
        )

        result = await bridge.reason(request)
        print(f"Answer: {result.answer}")
        print(f"Confidence: {result.confidence}")
    """

    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}
        self.initialized = False

        # Memory agent for persisting reasoning traces
        self.memory_agent = None


        # Statistics
        self.statistics = {
            'total_requests': 0,
            'symbolic_requests': 0,
            'neural_requests': 0,
            'hybrid_requests': 0,
            'neuro_symbolic_requests': 0,
            'abstract_requests': 0,
            'cross_domain_requests': 0,
            'average_confidence': 0.0,
        }

        logger.info("NeuralBridge initialized")

    async def initialize(self) -> bool:
        """Initialize neural bridge with LLM service and memory agent"""
        try:
            logger.info("Initializing Neural Bridge")


            # Get memory agent for persisting reasoning traces
            try:
                from core.memory import get_memory_agent
                self.memory_agent = await get_memory_agent()
                await self.memory_agent.initialize()
                logger.info("✓ Connected to MemoryAgent for reasoning trace persistence")
            except Exception as e:
                logger.warning(f"MemoryAgent not available: {e}")
                self.memory_agent = None

            # Derive the subject-object reading from its teacher pairs and put
            # it in the registry -- an explicit, once-per-process step (idempotent,
            # cached), NOT a side effect of formalizing, so an empty registry
            # still means "nothing was derived". This is what makes the derived
            # reader non-empty at runtime; model-free via procedure_synthesis.
            try:
                from core.semantics.derived_reader import ensure_registered
                ok, why = ensure_registered()
                if not ok:
                    logger.warning("derived reading not registered: %s", why)
            except Exception as e:
                logger.warning("derived reading registration skipped: %s", e)

            self.initialized = True
            logger.info("✓ Neural Bridge ready")
            return True

        except Exception as e:
            logger.error(f"Failed to initialize neural bridge: {e}")
            return False

    def _finish(self, request: "ReasoningRequest",
                result: "ReasoningResult") -> "ReasoningResult":
        """The single exit for `reason()`: count it, remember it, return it.

        EVERY PATH LEAVES THROUGH HERE. `reason()` had two exits -- the
        substrate-first early return and the end of the router ladder -- and
        only the second updated statistics or captured the result to memory.
        Whether a conclusion was recorded therefore depended on which branch
        produced it rather than on what it was, which is precisely the kind of
        difference that is invisible until someone asks why the record looks
        the way it does.

        The two conditions on capture are unchanged and both matter:

            result.answer      an empty answer is a refusal, and storing "the
                               substrate could not represent this" as a
                               semantic memory would fill the store with
                               non-answers.

            cached_memories is None
                               a standalone call. Inside the executor's agent
                               loop the whole conversation is captured once at
                               task end by _capture_semantic_task_memory();
                               storing each iteration would pay for embeddings
                               and a pgvector search per turn to write records
                               the filter mostly declines anyway.
        """
        self._update_stats(request, result)

        if self.memory_agent and result.answer and request.cached_memories is None:
            asyncio.create_task(self._capture_reasoning_memory(request, result))

        return result

    async def reason(self, request: ReasoningRequest) -> ReasoningResult:
        """
        Perform neural-symbolic reasoning

        Args:
            request: Reasoning request

        Returns:
            Reasoning result with answer and confidence
        """
        if not self.initialized:
            # The result is CHECKED. Discarding it meant a failed initialize was
            # followed by the work it was meant to enable, and the real failure
            # resurfaced later disguised as something else.
            if await self.initialize() is False:
                raise RuntimeError(
                    type(self).__name__ + ' could not initialize; refusing to '
                    'continue as though it had')

        # ========== MEMORY INJECTION (once per task, not per iteration) ==========
        # Memory lifecycle:
        #   - Executor retrieves memories ONCE at task start and bakes them into
        #     the initial user message in conversation_history.
        #   - During iteration, executor passes cached_memories=[] (empty list)
        #     to signal "memories are already in conversation, don't re-inject".
        #   - When context fills up, 8B model compresses everything (including
        #     the initial memories) into a summary.  Memories are absorbed into
        #     the summary and carried forward — exactly like Claude/GPT.
        #   - Only when cached_memories is None (standalone calls outside the
        #     executor loop, e.g. chat requests) do we perform a fresh search.
        if request.cached_memories is not None:
            # Caller explicitly controls memory injection.
            # Empty list = skip (memories already in conversation).
            # Non-empty list = format and inject (one-time injection).
            if request.cached_memories:
                # ONE CLEAN CLAIM PER ITEM -- substrate-readable, no stamp.
                #
                # The eleven kinds of thinking take request.context as PREMISES
                # and read each item as ONE sentence. A memory must therefore
                # reach them as the claim it asserts, not as "[date] ..." -- the
                # stamp is prompt formatting the substrate reader cannot parse.
                # Measured: the SAME premise refuses when stamped and proves when
                # clean. A memory that recorded its conclusion hands that back
                # (it is what the memory asserts); otherwise its content,
                # unstamped and untruncated at a sentence-breaking boundary.
                claims = []
                for mem in request.cached_memories[:3]:
                    meta = getattr(mem, "metadata", None)
                    conclusion = meta.get("conclusion") if isinstance(meta, dict) else None
                    claim = str(conclusion or getattr(mem, "claim", None)
                                or getattr(mem, "content", "") or "").strip()
                    if claim:
                        claims.append(claim)

                if isinstance(request.context, str):
                    request.context = claims + [request.context]
                elif request.context is None:
                    request.context = claims
                else:
                    request.context[0:0] = claims
                logger.debug("One-time memory injection: %d claims", len(claims))
            else:
                logger.debug("Skipping memory injection (memories already in conversation)")
        else:
            # Standalone call (chat, one-shot reasoning) — perform fresh search
            try:
                from core.memory.utils.memory_injector import get_memory_injector, InjectionConfig, InjectionMode

                injector = get_memory_injector()
                config = InjectionConfig(
                    mode=InjectionMode.USER_CONTEXT,
                    max_memories=3,
                    min_relevance_score=0.6
                )

                search_query = request.query
                if request.image or request.video:
                    search_query = f"{request.query} [multimodal vision image analysis]"
                    logger.debug("Enhanced search query for multimodal memory injection")

                injected = await injector.inject_memories(
                    query=search_query,
                    config=config
                )

                # ONE CONTEXT ITEM, ONE CLAIM.
                #
                # This inserted `injected.formatted_text` -- a header sentence
                # plus every retrieved memory as bullets, in ONE string. That is
                # correct for a prompt and wrong for everything downstream that
                # reads a context item as a single statement, which now includes
                # the eleven kinds of thinking: they take request.context as
                # premises.
                #
                # Measured before this change: the blob passed to causal
                # reasoning produced "you have access to the following relevant
                # context from memory: ... causes ..." as a derived causal link
                # at CONFIDENCE 1.00, plus a root cause built from the header
                # text. Fabricated, confident, and headed for the memory store
                # as knowledge.
                #
                # The individual claims carry the same text to the model -- the
                # model path joins context with newlines -- while giving every
                # other consumer one statement per item.
                if injected.records:
                    if isinstance(request.context, str):
                        request.context = list(injected.records) + [request.context]
                    elif request.context is None:
                        request.context = list(injected.records)
                    else:
                        request.context[0:0] = list(injected.records)
                    logger.info("✓ Injected %d memories as separate claims (%d tokens)",
                                injected.total_memories, injected.total_tokens)
                elif injected.formatted_text:
                    logger.info(f"✓ Injected {injected.total_memories} relevant memories ({injected.total_tokens} tokens)")
                    if isinstance(request.context, str):
                        request.context = [injected.formatted_text, request.context]
                    elif request.context is None:
                        request.context = [injected.formatted_text]
                    else:
                        request.context.insert(0, injected.formatted_text)
                else:
                    logger.debug("No relevant memories found for injection")

            except Exception as e:
                logger.warning(f"Memory injection failed (continuing without): {e}")
        # ================================================

        try:
            # ── EVERY MODE IS A REACHABLE PEER ─────────────────────────
            # No privileged pre-gate. With no model in the architecture there
            # is no "first" for the substrate to be before -- reasoning is just
            # picking a strategy and running it. A caller names one in
            # request.mode and it runs directly; ABSTRACT (the default) means
            # "no strategy named" and runs the full pipeline below.
            if request.mode != ReasoningMode.ABSTRACT:
                chosen = await self._run_mode(request)
                if chosen is not None:
                    return self._finish(request, chosen)
                return self._finish(
                    request, self._unsettled(request, [request.mode.value, "unsettled"]))

            # ── DEFAULT (ABSTRACT): the whole substrate, model-free ────────
            # Deterministic solvers (arithmetic, sequence, proof), then the
            # eleven kinds, then cross-domain grounding, then honest inability.
            # Order, not privilege.
            substrate = await self._substrate_solvers(request)

            # A refutation/verification from a LOSSY propositional reading is
            # DEFERRED to the kinds -- they may read the query more richly and
            # deserve the credit -- and returned only if no kind settles it.
            deferred_substrate = None
            if (substrate is not None
                    and (substrate.metadata or {}).get("reason")
                        in (REASON_SUBSTRATE_REFUTED, REASON_SUBSTRATE_VERIFIED)
                    and (request.kinds
                         or kinds_of_thinking_for(request.query)
                         or any(_is_implication(str(c)) and "?" in str(c)
                                for c in (request.context or [])))):
                # ...or the context carries a PREDICATE rule (a variable,
                # like human(?x) -> mortal(?x)) the propositional reading cannot
                # use. A plain propositional rule (human -> mortal) IS usable, so
                # a proof over it stands; only the variable case is lossy and is
                # deferred to the deductive kind that unifies it, kept as fallback.
                deferred_substrate, substrate = substrate, None

            if substrate is not None:
                return self._finish(request, substrate)

            by_kind = await self._reason_by_kind(request)
            if by_kind is not None:
                return self._finish(request, by_kind)

            if deferred_substrate is not None:
                return self._finish(request, deferred_substrate)

            # Cross-domain grounding, on explicit domain intent (source/target
            # domains named in task_metadata). Not a kind -- it maps structure
            # BETWEEN domains. Only a confident grounding returns; otherwise
            # honest inability stands.
            if self._is_cross_domain_request(request):
                cross = await self._cross_domain_reasoning(request)
                if cross is not None and cross.confidence > 0.0:
                    cross.metadata = {**(cross.metadata or {}),
                                      "route": ["kinds_of_thinking", "cross_domain"]}
                    return self._finish(request, cross)

            return self._finish(
                request, self._unsettled(
                    request, ["substrate", "kinds_of_thinking", "unsettled"]))

        except Exception as e:
            logger.error(f"Reasoning failed: {e}")
            return ReasoningResult(
                answer="Error: Reasoning failed",
                confidence=0.0,
                mode_used=request.mode
            )

    def _extract_reasoning_steps(self, response: str) -> List[str]:
        """
        Extract reasoning steps from LLM response

        Looks for:
        - THINKING: sections with numbered steps
        - Numbered lists (1., 2., 3.)
        - Step markers (Step 1:, Step 2:)
        - Multiple sentences as individual steps

        Returns list of reasoning steps
        """
        reasoning_steps = []

        # Try to extract THINKING section
        if "THINKING:" in response:
            thinking_section = response.split("THINKING:")[1].split("\n\n")[0] if "THINKING:" in response else ""

            # Extract numbered points from THINKING
            import re
            numbered_points = re.findall(r'(?:^|\n)\s*\d+\.\s*\*?\*?(.+?)(?:\n|$)', thinking_section, re.MULTILINE)
            if numbered_points:
                reasoning_steps.extend([point.strip() for point in numbered_points])

        # If no THINKING section, look for numbered lists anywhere in response
        if not reasoning_steps:
            import re
            numbered_points = re.findall(r'(?:^|\n)\s*\d+\.\s*\*?\*?(.+?)(?:\n|$)', response, re.MULTILINE)
            if numbered_points:
                reasoning_steps.extend([point.strip()[:200] for point in numbered_points])  # Limit length

        # Look for "Step N:" patterns
        if not reasoning_steps:
            import re
            step_points = re.findall(r'(?:Step|step)\s+\d+:\s*(.+?)(?:\n|$)', response, re.MULTILINE)
            if step_points:
                reasoning_steps.extend([point.strip()[:200] for point in step_points])

        # If still no steps found, split the response into sentences.
        #
        # THIS SPLIT ON EVERY PERIOD. `.split('.')` cuts decimals and JSON as
        # readily as sentences, and these steps are persisted as the memory
        # `reasoning_trace` -- so the stored traces from this path are shredded:
        # an analysis answering `"target_value": 95.0` was recorded as the
        # fragments '"target_value": 95' and '0,\n "potential": 20'. A structured
        # answer has no sentences to find, so it is left alone rather than
        # chopped into nonsense.
        if not reasoning_steps:
            import re
            stripped = response.strip()
            looks_structured = stripped.startswith(('{', '[')) or '```' in stripped
            if not looks_structured:
                # Split on sentence-ending punctuation followed by whitespace,
                # which leaves 95.0 and version numbers intact.
                sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+', stripped)
                             if s.strip() and len(s.strip()) > 20]
                if sentences:
                    reasoning_steps = sentences[:5]

        # NO STEPS MEANS NO STEPS. This returned ["Direct neural inference"] --
        # a sentence the model never produced, written into the reasoning trace
        # as though it had been. It also made every unparseable answer report
        # exactly one reasoning step, which is the count the memory filter reads.
        return reasoning_steps

    #: Wall-clock bound for a single symbolic proof attempt, in seconds. Keeps
    #: the reasoning loop responsive when a formalization turns out to be hard.
    SYMBOLIC_PROOF_TIMEOUT = 10.0

    def _model_available(self) -> bool:
        """Whether a teacher could serve a request right now — asked of the TEACHER
        authority, not a model handle this reasoner holds. The substrate reasoner
        never consults the model itself (its reasoning is deterministic); this only
        reports, for a higher layer, whether escalating to a teacher is possible."""
        from core.learning.llm_teacher import teacher_reachable
        return teacher_reachable()

    async def _verify_candidate(
        self,
        candidate: str,
        request: ReasoningRequest
    ) -> Dict[str, Any]:
        """Check a model-proposed answer against the substrate.

        Returns the solver's confidence when the claim could be formalized and
        proved from the request context, and the unverified placeholder when it
        could not. Only deterministic formalizers are used, so scoring a
        candidate never costs another model call.
        """
        try:
            formalization = await self._get_deterministic_formalizer().formalize(
                candidate, request.context
            )
            if not formalization.succeeded:
                return {"verified": False, "confidence": UNVERIFIED_CONFIDENCE}

            from core.reasoning.advanced_proof_engine import (
                LogicType,
                Theorem,
                get_proof_engine,
            )

            proof = await get_proof_engine().prove_theorem(
                Theorem(
                    theorem_id=f"candidate_{uuid.uuid4().hex[:8]}",
                    statement=formalization.statement,
                    premises=list(formalization.premises),
                    logic_type=LogicType.PROPOSITIONAL,
                ),
                timeout=self.SYMBOLIC_PROOF_TIMEOUT,
            )

            if proof.proved:
                return {"verified": True, "confidence": proof.confidence}

            # Formalized but not entailed: the claim is not supported by the
            # context. That is weaker than merely unverified.
            if not proof.error:
                return {"verified": False, "confidence": 0.0}

            return {"verified": False, "confidence": UNVERIFIED_CONFIDENCE}

        except Exception as e:
            logger.debug(f"Candidate verification failed: {e}")
            return {"verified": False, "confidence": UNVERIFIED_CONFIDENCE}

    async def _check_argument_fallacies(
        self,
        answer: str,
        request: Optional[ReasoningRequest] = None,
    ) -> Optional[str]:
        """Run the argumentation engine's fallacy detection over an answer.

        Works on plain text, so unlike the solver checks it needs no
        formalization step and applies to every model answer.

        The request's context supplies the argument's premises. Passing the
        answer as its own premise instead would make every argument circular
        and trip begging_question on correct answers.
        """
        if not answer or not answer.strip():
            return None

        try:
            from core.reasoning.formal_argumentation import (
                ArgumentType,
                get_argumentation_system,
            )

            system = get_argumentation_system()
            await system.load()   # prior claims/arguments (Postgres-backed), non-fatal
            claim = system.create_claim(statement=answer.strip()[:500])
            argument = system.create_argument(
                claim,
                premises=[str(c) for c in (getattr(request, "context", None) or [])],
                argument_type=ArgumentType.DEDUCTIVE,
            )
            fallacies = system.detect_fallacies(argument)
            await system.persist()   # to the unified Postgres DB, off critical path
        except Exception as e:
            logger.debug(f"Fallacy detection unavailable: {e}")
            return None

        if not fallacies:
            return None

        names = sorted({f.fallacy_type.value for f in fallacies})
        return f"Argument contains detected fallacies: {', '.join(names)}"

    async def _check_formalizability(
        self,
        answer: str,
        request: ReasoningRequest,
    ) -> Optional[str]:
        """Pressure the answer toward phrasing the substrate can verify.

        This is not a claim that the answer is wrong -- it says the answer
        cannot be *checked*, and asks for a restatement the substrate can
        represent. Fed back through the refinement loop, it makes the next
        answer more likely to be verifiable rather than merely plausible.

        An earlier version of this idea looked for the words 'therefore' and
        'because', which pushed toward the appearance of reasoning. Keying it
        to the extractor's actual grammar pushes toward phrasing that can be
        put in front of the solver, so the pressure and the verification share
        one definition of "checkable". Every pattern added to the extractor
        widens what satisfies this check.
        """
        if not answer or not answer.strip():
            return None

        try:
            formalization = await self._get_deterministic_formalizer().formalize(
                answer, request.context
            )
        except Exception as e:
            logger.debug(f"Formalizability check unavailable: {e}")
            return None

        if formalization.succeeded:
            return None

        return (
            "Answer cannot be represented for verification. State the "
            "conclusion in a checkable form, for example 'X is Y', "
            "'All P are Q', 'No P is Q', or 'if X is P then X is Q'."
        )

    async def _check_temporal_consistency(
        self,
        temporal_engine: Any,
        answer: str,
        request: ReasoningRequest,
    ) -> Optional[str]:
        """Check temporal claims with the temporal engine.

        Returns a violation string, or None when consistent or when the claim
        could not be represented. Inability to check is not a violation.
        """
        try:
            from core.reasoning.temporal_reasoning import TimePoint

            statements = [str(c) for c in (request.context or [])] + [answer]
            propositions = []
            for statement in statements:
                text = statement.strip()
                if not text:
                    continue
                propositions.append(
                    temporal_engine.create_proposition(text[:200], TimePoint.PRESENT)
                )

            if len(propositions) < 2:
                return None

            # A proposition and its explicit negation cannot both hold at the
            # same time point.
            claims = {}
            for proposition in propositions:
                key = proposition.statement.lower().replace("not ", "").strip()
                negated = "not " in proposition.statement.lower()
                if key in claims and claims[key] != negated:
                    return (
                        f"Temporal inconsistency: contradictory claims about "
                        f"{key[:60]!r} at the same time point"
                    )
                claims[key] = negated

            return None

        except Exception as e:
            logger.debug(f"Temporal consistency check unavailable: {e}")
            return None

    async def _check_formal_constraints(
        self,
        answer: str,
        request: ReasoningRequest,
    ) -> Optional[str]:
        """Verify an answer against its context with the solver.

        Only runs when the claim and context can be formalized deterministically.
        An answer that cannot be represented is not reported as a violation --
        being unable to check something is not evidence against it.
        """
        try:
            formalization = await self._get_deterministic_formalizer().formalize(
                answer, request.context
            )
            if not formalization.succeeded:
                return None

            from core.reasoning.advanced_proof_engine import (
                LogicType,
                Theorem,
                get_proof_engine,
            )

            # Does the context actually refute the claim?
            negated_goal = (
                formalization.statement[1:]
                if formalization.statement.startswith("~")
                else f"~{formalization.statement}"
            )

            refutation = await get_proof_engine().prove_theorem(
                Theorem(
                    theorem_id=f"refute_{uuid.uuid4().hex[:8]}",
                    statement=negated_goal,
                    premises=list(formalization.premises),
                    logic_type=LogicType.PROPOSITIONAL,
                ),
                timeout=self.SYMBOLIC_PROOF_TIMEOUT,
            )

            if refutation.proved:
                return (
                    f"Formal contradiction: the context entails "
                    f"{negated_goal}, contradicting the answer"
                )

            return None

        except Exception as e:
            logger.debug(f"Formal constraint check unavailable: {e}")
            return None

    def _solve_equation(self, equation) -> ReasoningResult:
        """Answer a read equation with the capability that owns arithmetic.

        No fallback. If the solver is absent the request does NOT continue to a
        model: the reading succeeded, so this is a missing capability, and
        answering it from somewhere else would make the solver decorative --
        severing it would change nothing and the experiment measuring it would
        be measuring the model.
        """
        from core.reasoning.constraint_solver import get_constraint_solver

        solver = get_constraint_solver()
        route = ["arithmetic_reading", "constraint_solver"]

        if not solver.available:
            return ReasoningResult(
                answer="", confidence=0.0, mode_used=ReasoningMode.SYMBOLIC,
                reasoning_steps=[f"Read as a linear equation: {equation.as_text()}"],
                metadata={"verified": False, "formalized": True,
                          "reason": REASON_CAPABILITY_UNAVAILABLE,
                          "capability": "constraint_solver",
                          "route": route, "model_required": False})

        solution = solver.solve_linear(equation.variable, equation.coefficient,
                                       equation.constant, equation.target)
        if not solution.satisfiable:
            return ReasoningResult(
                answer="", confidence=0.0, mode_used=ReasoningMode.SYMBOLIC,
                reasoning_steps=[f"Read as a linear equation: {equation.as_text()}"],
                metadata={"verified": False, "formalized": True,
                          "reason": REASON_SUBSTRATE_REFUTED, "route": route,
                          KEY_SUBSTRATE_FORMALIZED: True,
                          KEY_TEACHER_CONSULTED: False})

        value = solution.model.get(equation.variable)
        return ReasoningResult(
            answer=f"{equation.variable} = {value}",
            confidence=1.0,
            mode_used=ReasoningMode.SYMBOLIC,
            reasoning_steps=[f"Read as a linear equation: {equation.as_text()}",
                             f"Solved by the constraint solver: {equation.variable} = {value}"],
            metadata={"verified": True, "formalized": True,
                      "reason": REASON_SUBSTRATE_VERIFIED,
                      # Decided by the substrate, with no teacher involved.
                      KEY_SUBSTRATE_FORMALIZED: True,
                      KEY_TEACHER_CONSULTED: False,
                      "capability": "constraint_solver", "route": route,
                      "solution": solution.model})

    def _extend_sequence(self, sequence) -> ReasoningResult:
        """Extend a sequence by the rule the learning authority induces.

        No fallback and no guess. If induction does not settle on a single rule
        -- MULTIPLE_HYPOTHESES, NO_RULE, insufficient terms -- the answer is
        that it was not settled. A sequence with no constant difference or
        ratio genuinely has no rule in this language, and inventing one would
        be the most tempting fabrication available here.
        """
        from core.learning.learning_authority import get_learning_authority

        route = ["sequence_reading", "learning_authority", "rule_induction"]
        result, next_value = get_learning_authority().induce_sequence_rule(sequence.terms)

        if result is None:
            return ReasoningResult(
                answer="", confidence=0.0, mode_used=ReasoningMode.SYMBOLIC,
                metadata={"verified": False, "formalized": True,
                          "reason": REASON_UNSUPPORTED_INPUT, "route": route})

        if next_value is None:
            return ReasoningResult(
                answer="", confidence=0.0, mode_used=ReasoningMode.SYMBOLIC,
                reasoning_steps=[f"Read as a sequence: {sequence.as_text()}",
                                 f"Induction: {result.status.value}"],
                metadata={"verified": False, "formalized": True,
                          "reason": REASON_SUBSTRATE_UNDECIDED,
                          "induction_status": result.status.value, "route": route})

        rule = sorted(str(f) for f in result.rule.body) if result.rule else []
        return ReasoningResult(
            answer=str(next_value), confidence=1.0, mode_used=ReasoningMode.SYMBOLIC,
            reasoning_steps=[f"Read as a sequence: {sequence.as_text()}",
                             f"Induced rule: {rule}",
                             f"Next term: {next_value}"],
            metadata={"verified": True, "formalized": True,
                      "reason": REASON_SUBSTRATE_VERIFIED,
                      # Decided by the substrate, with no teacher involved.
                      KEY_SUBSTRATE_FORMALIZED: True,
                      KEY_TEACHER_CONSULTED: False,
                      "induced_rule": rule, "route": route})

    async def _run_mode(self, request: ReasoningRequest) -> Optional[ReasoningResult]:
        """Run the substrate strategy the caller named. MODEL-FREE, every one.

        Each mode is a peer entry point. Returns the strategy's result, or None
        when it does not settle the request -- the caller then gets honest
        inability, never a model.
        """
        mode = request.mode
        if mode == ReasoningMode.SYMBOLIC:
            return await self._substrate_solvers(request)
        if mode == ReasoningMode.NEURAL:
            return await self._neural_reasoning(request)
        if mode == ReasoningMode.HYBRID:
            return await self._hybrid_reasoning(request)
        if mode == ReasoningMode.NEURO_SYMBOLIC:
            return await self._neuro_symbolic_reasoning(request)
        if mode == ReasoningMode.CROSS_DOMAIN:
            return await self._cross_domain_reasoning(request)
        return None

    def _unsettled(self, request: ReasoningRequest, route: list) -> ReasoningResult:
        """Honest inability: the substrate did not settle this.

        Told apart from a wrong answer by its reason code, not its confidence.
        No model fills the gap -- an unsettled request is reported, never handed
        off.
        """
        return ReasoningResult(
            answer="", confidence=0.0, reasoning_steps=[],
            mode_used=ReasoningMode.SYMBOLIC,
            metadata={
                "verified": False, "formalized": False,
                KEY_SUBSTRATE_FORMALIZED: False,
                "reason": REASON_UNSUPPORTED_INPUT,
                "model_required": False,
                "model_available": self._model_available(),
                KEY_TEACHER_AVAILABLE: self._model_available(),
                KEY_TEACHER_CONSULTED: False,
                "route": list(route),
            })

    async def _substrate_solvers(
        self,
        request: ReasoningRequest
    ) -> Optional[ReasoningResult]:
        """Try to answer from the substrate alone, before any model is touched.

        Returns a ReasoningResult when the question was settled here, and
        None when the input has no deterministic formalization here -- in
        which case the caller proceeds to the kinds of thinking.

        The probe uses only deterministic formalizers, so an input Torin can
        represent itself never enters the model call graph.
        """
        # ARITHMETIC FIRST, AND BEFORE ANY MODEL. The constraint solver runs
        # here so Z3 PRODUCES the answer -- "Torin can do algebra" is a
        # substrate claim, never contingent on a model checking it.
        equation = read_equation(request.query)
        if equation is not None:
            return self._solve_equation(equation)

        # A sequence question is answered by INDUCING its rule, which is
        # learning, so it goes to the learning authority rather than to a
        # solver. Substrate-first for the same reason arithmetic is: the rule
        # is derived from the terms, not recalled from a model.
        sequence = read_sequence(request.query)
        if sequence is not None:
            return self._extend_sequence(sequence)

        try:
            formalization = await self._get_deterministic_formalizer().formalize(
                request.query, request.context
            )
        except Exception as e:
            logger.warning(f"Deterministic formalization failed: {e}")
            formalization = Formalization(
                source="deterministic", succeeded=False, error=str(e)
            )

        if formalization.succeeded:
            # Torin can represent this. The solver decides it; no model needed.
            return await self._symbolic_reasoning(request, formalization=formalization)

        # DETERMINISTIC FORMALIZATION FAILED -- WHICH IS NOT THE END, AND NEVER
        # DEPENDS ON A MODEL. The eleven kinds of thinking are substrate
        # reasoning too, and they have not been tried yet. Substrate-first must
        # ALWAYS fall through to them, whether or not a model happens to exist.
        #
        # This used to branch on `_model_available()`: with a model it returned
        # None (kinds ran), without one it returned `unsupported_input` and the
        # kinds never ran -- so the SAME question was answered by a kind of
        # thinking or declared unrepresentable depending only on whether a model
        # was around. That is exactly the model-in-the-muddle this architecture
        # forbids. It is always substrate first: substrate-first, then the
        # kinds, and the model only as a last resort decided at the end of
        # reason() -- never a factor in whether the substrate keeps reasoning.
        logger.info(
            "Substrate-first could not formalize the request deterministically; "
            "falling through to the eleven kinds of thinking (%s)",
            formalization.error)
        return None

    def _get_deterministic_formalizer(self) -> IFormalizer:
        """Formalizers that require no model at all.

        This is what the substrate-first router probes with, so the probe never
        enters the model call graph. The deterministic extractor registers here
        as it grows, which continuously shrinks the set of inputs that need
        model-backed coverage without any downstream contract changing.
        """
        return FormalizerChain([
            PassthroughFormalizer(),
            DeterministicExtractor(),
            DerivedReadingFormalizer(),
        ])

    async def _symbolic_reasoning(
        self,
        request: ReasoningRequest,
        formalization: Optional[Formalization] = None,
    ) -> ReasoningResult:
        """Formal reasoning in which the solver decides and the model only translates.

        A caller that has already formalized the request (the substrate-first
        router) passes it in so the work is not repeated.

        The query is formalized (explicitly-formal input bypasses the model
        entirely), handed to Z3, and both the verdict and its confidence come
        from the solver.

        The previous implementation only checked that Z3 was *importable*, set
        a placeholder string as its "formal result", awarded itself +0.3
        confidence for it and then let the LLM answer the question. No symbolic
        reasoning took place, and the confidence reported was unrelated to
        anything verified.
        """
        try:
            if formalization is None:
                # Deterministic only. There is no model backstop: a query the
                # substrate cannot formalize is reported as unformalizable, not
                # handed to a model to read.
                formalization = await self._get_deterministic_formalizer().formalize(
                    request.query, request.context
                )
        except Exception as e:
            logger.error(f"Formalization failed: {e}")
            return ReasoningResult(
                answer=f"Error: {e}",
                confidence=0.0,
                mode_used=ReasoningMode.SYMBOLIC,
                metadata={"formalized": False, "verified": False},
            )

        if not formalization.succeeded:
            # Without a formal reading there is nothing to verify, so there is
            # nothing to be confident about either.
            logger.info(f"Symbolic reasoning could not formalize query: {formalization.error}")
            return ReasoningResult(
                answer="",
                confidence=0.0,
                reasoning_steps=[],
                mode_used=ReasoningMode.SYMBOLIC,
                metadata={
                    "formalized": False,
                    "verified": False,
                    "formalizer_error": formalization.error,
                },
            )

        from core.reasoning.advanced_proof_engine import (
            LogicType,
            Theorem,
            get_proof_engine,
        )

        theorem = Theorem(
            theorem_id=f"symbolic_{uuid.uuid4().hex[:8]}",
            statement=formalization.statement,
            premises=list(formalization.premises),
            logic_type=LogicType.PROPOSITIONAL,
        )

        try:
            proof = await get_proof_engine().prove_theorem(
                theorem, timeout=self.SYMBOLIC_PROOF_TIMEOUT
            )
        except Exception as e:
            logger.error(f"Proof attempt failed: {e}")
            return ReasoningResult(
                answer=f"Error: {e}",
                confidence=0.0,
                mode_used=ReasoningMode.SYMBOLIC,
                metadata={"formalized": True, "verified": False},
            )

        reasoning_steps = [
            f"{step.step_number}. {step.statement}  [{step.justification}]"
            for step in proof.steps
        ]

        # Verification is only as strong as its weakest link. The solver checks
        # the entailment, never whether the premises faithfully represent what
        # was actually said, so a proof built on model-written premises has an
        # unverified foundation and must not claim to be verified.
        #
        # Without this, a single hallucinated premise yields a confident
        # "Proved:" at 0.98 for a conclusion the source never supported --
        # the one failure mode the solver cannot detect on its own.
        premises_trusted = not formalization.requires_model

        if proof.proved and premises_trusted:
            answer = f"Proved: {formalization.statement}"
            reason = REASON_SUBSTRATE_VERIFIED
            verified = True
            confidence = proof.confidence
        elif proof.proved:
            answer = (
                f"Entailed by unverified premises: {formalization.statement} "
                f"(premises were written by a model, not derived from the input)"
            )
            reason = REASON_ENTAILMENT_ONLY
            verified = False
            confidence = min(proof.confidence, UNVERIFIED_CONFIDENCE)
        elif proof.error:
            answer = f"Undecided: {proof.error}"
            reason = REASON_SUBSTRATE_UNDECIDED
            verified = False
            confidence = proof.confidence
        else:
            answer = f"Not entailed by the premises: {formalization.statement}"
            reason = REASON_SUBSTRATE_REFUTED
            verified = False
            confidence = proof.confidence

        return ReasoningResult(
            answer=answer,
            confidence=confidence,
            reasoning_steps=reasoning_steps,
            mode_used=ReasoningMode.SYMBOLIC,
            metadata={
                "formalized": True,
                "formalizer": formalization.source,
                # Kept separate so the distinction survives downstream: the
                # solver's verdict on the inference, and whether the premises
                # it started from were themselves trustworthy.
                "entailment_verified": bool(proof.proved),
                "premises_trusted": premises_trusted,
                # True when a deterministic formalizer handled the input. The
                # share of results with this True is the substrate-native
                # fraction the deterministic extractor is meant to grow.
                #
                # Stated as what the SUBSTRATE did, not as what a model was
                # "required" for -- the substrate is not a model and does not
                # require one; a teacher only widens which inputs it can take.
                KEY_SUBSTRATE_FORMALIZED: not bool(formalization.requires_model),
                KEY_TEACHER_CONSULTED: bool(formalization.requires_model),
                KEY_TEACHER_AVAILABLE: self._model_available(),
                "model_required": bool(formalization.requires_model),  # deprecated alias
                "model_available": self._model_available(),
                "reason": reason,
                # verified means end-to-end: the goal follows AND the premises
                # were derived by the substrate rather than written by a model.
                "verified": verified,
                "proved": bool(proof.proved),
                "statement": formalization.statement,
                "premises": list(formalization.premises),
                "proof_error": proof.error,
            },
        )

    async def _neural_reasoning(self, request: ReasoningRequest) -> Optional[ReasoningResult]:
        """Learned / inductive inference. MODEL-FREE.

        The learned counterpart to `_symbolic_reasoning`'s formal proof: rather
        than deriving from the request's own premises, this reasons from what the
        substrate has LEARNED and persisted.

          * Bayesian beliefs (`bayesian_uncertainty`): accumulated probabilistic
            claims. A text query is answered from the belief most relevant to
            it, reporting the posterior and the epistemic state behind it.
          * induced rules (`RuleInducer`): when the request carries
            demonstrations (before / action / after), a rule is INDUCED from
            them. A state transition to generalize is the only shape the inducer
            accepts, so this runs only when one is supplied.

        No model is consulted. Returns None when nothing learned bears on the
        request -- honest inability, never a model fallback. 'NEURAL' is the
        historical name for this route; what it does is learned inference.
        """
        # ---- Induced-rule path: generalize from supplied demonstrations ----
        demonstrations = (request.task_metadata or {}).get("demonstrations")
        if demonstrations:
            induced = await self._induce_from_demonstrations(
                demonstrations,
                (request.task_metadata or {}).get("target_predicate"),
            )
            if induced is not None:
                return induced

        # ---- Belief path: reason from accumulated learned beliefs ----
        try:
            from core.reasoning.bayesian_uncertainty import get_uncertainty_system
            uncertainty_sys = get_uncertainty_system()
        except Exception as e:
            logger.debug(f"Bayesian uncertainty not available: {e}")
            return None

        # Content-word overlap only. Matching on question words like "what"
        # or on substrings ("cat" in "category") produced false relevance -- a
        # startup-naming query matched a belief about test images through the
        # shared word "what". Tokenize both sides and drop stopwords so a match
        # means shared subject matter, not shared grammar.
        import re
        query_terms = {t for t in re.findall(r"[a-z0-9]+", request.query.lower())
                       if len(t) > 2 and t not in _BELIEF_STOPWORDS}
        scored = []
        for belief in uncertainty_sys.beliefs.values():
            claim_terms = {t for t in re.findall(r"[a-z0-9]+", belief.claim.lower())
                           if len(t) > 2 and t not in _BELIEF_STOPWORDS}
            overlap = len(query_terms & claim_terms)
            if overlap:
                # rank by relevance, then by how settled the belief is
                scored.append((overlap, -belief.entropy, belief))
        if not scored:
            logger.info("learned inference: no belief bears on the query")
            return None

        scored.sort(key=lambda row: (row[0], row[1]), reverse=True)
        belief = scored[0][2]

        # Confidence is the belief's calibration -- what the evidence earned --
        # never a generation score. Low entropy = the evidence has settled it;
        # high entropy = still open, and reported as such.
        confidence = max(0.0, min(0.98, 1.0 - belief.entropy))

        return ReasoningResult(
            answer=f"P({belief.claim}) = {belief.posterior_probability:.3f}",
            confidence=confidence,
            reasoning_steps=[
                f"consulted {len(uncertainty_sys.beliefs)} learned belief(s)",
                f"most relevant: {belief.claim[:80]!r} "
                f"(posterior={belief.posterior_probability:.3f}, "
                f"entropy={belief.entropy:.3f})",
            ],
            mode_used=ReasoningMode.NEURAL,
            metadata={
                "verified": True,
                "formalized": False,
                KEY_SUBSTRATE_FORMALIZED: False,
                "reason": REASON_DERIVED_BY_KIND,
                "model_required": False,
                "model_available": self._model_available(),
                "learned_from": "bayesian_belief",
                "belief_id": belief.belief_id,
                "posterior": belief.posterior_probability,
                "entropy": belief.entropy,
                "route": ["substrate", "learned_inference", "belief"],
            },
        )

    async def _induce_from_demonstrations(
        self, demonstrations, target_predicate
    ) -> Optional[ReasoningResult]:
        """Induce a rule from supplied before/action/after demonstrations.

        Returns a ReasoningResult carrying the induced rule, or None when the
        demonstrations do not determine one (too few, contradictory, or no
        effect to explain) -- the inducer's own honest verdicts, surfaced rather
        than papered over.
        """
        try:
            from core.learning.rule_induction import (
                Fact, TrainingExample, get_rule_inducer)
        except Exception as e:
            logger.debug(f"rule induction unavailable: {e}")
            return None

        def _fact(item):
            if isinstance(item, (list, tuple)) and item:
                return Fact(predicate=str(item[0]),
                            args=tuple(str(a) for a in item[1:]))
            if isinstance(item, dict):
                return Fact(predicate=str(item["predicate"]),
                            args=tuple(str(a) for a in item.get("args", ())))
            raise ValueError(f"cannot read a fact from {item!r}")

        def _facts(items):
            return tuple(_fact(it) for it in (items or ()))

        try:
            examples = [
                TrainingExample(
                    before=_facts(d.get("before")),
                    action=(_fact(d["action"]) if d.get("action") else None),
                    after=_facts(d.get("after")),
                    positive=bool(d.get("positive", True)),
                )
                for d in demonstrations
            ]
        except Exception as e:
            logger.warning(f"malformed demonstrations for induction: {e}")
            return None

        try:
            result = get_rule_inducer().induce(
                examples, target_predicate=target_predicate)
        except Exception as e:
            logger.warning(f"rule induction failed: {e}")
            return None

        rule = result.rule
        if rule is None:
            logger.info("induction did not determine a rule: %s (%s)",
                        result.status.value, result.detail)
            return None

        total = result.positive_coverage + result.negative_coverage
        return ReasoningResult(
            answer=str(rule),
            confidence=min(0.98, result.positive_coverage / max(1, total)),
            reasoning_steps=[
                f"induced from {result.positive_coverage} positive / "
                f"{result.negative_coverage} negative demonstration(s)",
                result.detail or "",
            ],
            mode_used=ReasoningMode.NEURAL,
            metadata={
                "verified": True,
                "formalized": False,
                KEY_SUBSTRATE_FORMALIZED: False,
                "reason": REASON_DERIVED_BY_KIND,
                "model_required": False,
                "model_available": self._model_available(),
                "learned_from": "rule_induction",
                "induction_status": result.status.value,
                "route": ["substrate", "learned_inference", "induced_rule"],
            },
        )

    async def _hybrid_reasoning(self, request: ReasoningRequest) -> Optional[ReasoningResult]:
        """Propose -> constrain -> revise, entirely on the substrate. MODEL-FREE.

        The substrate PROPOSES by deriving candidates from the request's context
        (the kinds), the constraint engines CONSTRAIN each candidate -- Z3
        refutation, temporal consistency, fallacy detection, Bayesian entropy --
        and on a violation the substrate REVISES by moving to the next-best
        derivation that has not been refuted, never by asking a model.
        Confidence is the derivation's own, earned by the substrate and adjusted
        only by epistemic state.

        Returns None when the substrate cannot propose a candidate that survives
        its own constraints: honest inability, never a model fallback.
        """
        from core.reasoning.reasoning_interfaces import ReasoningType
        from core.reasoning.abstract_reasoning_engine import (
            create_abstract_reasoning_engine)

        max_iterations = 3
        is_temporal = ReasoningType.TEMPORAL in kinds_of_thinking_for(request.query)

        uncertainty_sys = None
        try:
            from core.reasoning.bayesian_uncertainty import get_uncertainty_system
            uncertainty_sys = get_uncertainty_system()
        except Exception as e:
            logger.debug(f"Bayesian uncertainty not available: {e}")

        temporal_engine = None
        if is_temporal:
            try:
                from core.reasoning.temporal_reasoning import get_temporal_system
                temporal_engine = get_temporal_system()
            except Exception as e:
                logger.debug(f"Temporal reasoning not available: {e}")

        # PROPOSE: derive candidates once; the engine is deterministic, so
        # revision walks down these by confidence rather than re-deriving.
        kinds = (list(request.kinds)
                 or list(kinds_of_thinking_for(request.query))
                 or list(CLASSICAL_REASONING_TYPES))
        try:
            engine = create_abstract_reasoning_engine()
            result = await engine.reason(self._build_reasoning_context(request, kinds))
        except Exception as e:
            logger.warning(f"hybrid propose failed: {e}")
            return None

        # The engine already ranks conclusions (certain kinds ahead of
        # degree/belief kinds), so preserve that order rather than re-sorting by
        # raw confidence -- which would let a 0.95 probabilistic degree outrank
        # a certain deductive conclusion.
        candidates = [c for c in (result.conclusions or ())
                      if getattr(c, "origin", "derived") == "derived"]
        if not candidates:
            return None

        history = []
        for iteration, candidate in enumerate(candidates[:max_iterations]):
            answer = candidate.statement

            # CONSTRAIN: the substrate cross-checks its own derivation.
            violations = []
            v = await self._check_formal_constraints(answer, request)
            if v:
                violations.append(v)
            if temporal_engine and is_temporal:
                v = await self._check_temporal_consistency(temporal_engine, answer, request)
                if v:
                    violations.append(v)
            v = await self._check_argument_fallacies(answer, request)
            if v:
                violations.append(v)

            conf_delta = 0.0
            if uncertainty_sys:
                terms = answer.lower().split()[:10]
                relevant = [b for b in uncertainty_sys.beliefs.values()
                            if any(t in b.claim.lower() for t in terms)]
                if relevant:
                    avg_entropy = sum(b.entropy for b in relevant) / len(relevant)
                    if avg_entropy > 0.5 and candidate.confidence > 0.7:
                        violations.append(
                            f"High epistemic uncertainty ({avg_entropy:.3f}) "
                            f"contradicts a confident derivation")
                    else:
                        conf_delta += (1.0 - avg_entropy) * 0.1

            history.append({"answer": answer, "confidence": candidate.confidence,
                            "violations": violations, "conf_delta": conf_delta,
                            "steps": list(candidate.reasoning_steps or ())})

            # CONVERGE: first derivation to clear every constraint wins.
            if not violations:
                final_conf = min(0.98, candidate.confidence + conf_delta)
                logger.info(f"hybrid converged at candidate {iteration + 1} "
                            f"(confidence {final_conf:.2f})")
                return ReasoningResult(
                    answer=answer,
                    confidence=final_conf,
                    reasoning_steps=history[-1]["steps"] + [
                        f"cleared the constraint gauntlet on attempt {iteration + 1}"],
                    mode_used=ReasoningMode.HYBRID,
                    metadata={
                        "verified": True,
                        "formalized": False,
                        KEY_SUBSTRATE_FORMALIZED: False,
                        "reason": REASON_DERIVED_BY_KIND,
                        "model_required": False,
                        "model_available": self._model_available(),
                        "orchestration_iterations": iteration + 1,
                        "converged": True,
                        "confidence_adjustment": conf_delta,
                        "route": ["substrate", "kinds_of_thinking", "hybrid"],
                    })

            logger.info(f"hybrid candidate {iteration + 1} violated "
                        f"{len(violations)} constraint(s); revising")

        # No candidate cleared every constraint. Report the least-violating one
        # as unverified rather than inventing a clean answer.
        best = min(history, key=lambda h: len(h["violations"]))
        return ReasoningResult(
            answer=best["answer"],
            confidence=best["confidence"] * 0.7,
            reasoning_steps=best["steps"] + [
                f"{len(best['violations'])} constraint(s) unresolved after "
                f"{len(history)} attempt(s)"],
            mode_used=ReasoningMode.HYBRID,
            metadata={
                "verified": False,
                "formalized": False,
                KEY_SUBSTRATE_FORMALIZED: False,
                "reason": REASON_DERIVED_BY_KIND,
                "model_required": False,
                "model_available": self._model_available(),
                "orchestration_iterations": len(history),
                "converged": False,
                "final_violations": best["violations"],
                "route": ["substrate", "kinds_of_thinking", "hybrid"],
            })

    async def _neuro_symbolic_reasoning(self, request: ReasoningRequest) -> Optional[ReasoningResult]:
        """Ensemble of substrate reasoning kinds, arbitrated formally. MODEL-FREE.

        The three classical inference kinds -- deductive, inductive, abductive --
        each derive a candidate from the SAME context through the abstract
        reasoning engine, with no model in the path. A formal argumentation
        engine (Dung semantics) then decides which candidate is skeptically
        accepted, and the solver checks each for consistency with the context.
        Nothing is generated: every candidate is a real derivation, so a kind
        that concludes nothing simply does not enter the ensemble -- it is not
        filled in by a model.

        Returns None when no kind derives anything: honest inability, which the
        caller tells apart from a wrong answer, never a model fallback.
        """
        from core.reasoning.reasoning_interfaces import ReasoningType
        from core.reasoning.abstract_reasoning_engine import (
            create_abstract_reasoning_engine)

        ensemble = [ReasoningType.DEDUCTIVE, ReasoningType.INDUCTIVE,
                    ReasoningType.ABDUCTIVE]

        # Phase 1: THE SUBSTRATE DERIVES -- one candidate per kind, no model.
        logger.info("neuro-symbolic ensemble: deductive / inductive / abductive (model-free)")
        try:
            context = self._build_reasoning_context(request, ensemble)
            engine = create_abstract_reasoning_engine()
            result = await engine.reason(context)
        except Exception as e:
            logger.warning(f"neuro-symbolic ensemble failed to run: {e}")
            return None

        derived = [c for c in (result.conclusions or ())
                   if getattr(c, "origin", "derived") == "derived"]
        by_kind: Dict[str, Any] = {}
        for c in derived:
            k = c.reasoning_type.value
            if k not in by_kind or c.confidence > by_kind[k].confidence:
                by_kind[k] = c

        candidate_answers = [
            {
                "path": k,
                "answer": c.statement,
                "full_response": c.statement,
                "verified": True,
                "base_confidence": c.confidence,
            }
            for k, c in by_kind.items()
        ]

        if not candidate_answers:
            logger.info("neuro-symbolic: no kind in the ensemble derived a conclusion")
            return None

        logger.info(f"neuro-symbolic derived {len(candidate_answers)} candidate(s): "
                    f"{[c['path'] for c in candidate_answers]}")

        try:
            # Phase 2: FORMAL ARBITRATION
            # Use formal argumentation to evaluate argument strength
            logger.info("⚖️ Arbitrating with formal argumentation engine")
            
            argument_scores = []
            try:
                from core.reasoning.formal_argumentation import (
                    FormalArgumentationSystem, Argument, Claim,
                    ArgumentType, ArgumentStrength,
                )

                arg_engine = FormalArgumentationSystem()

                path_types = {
                    'deductive': ArgumentType.DEDUCTIVE,
                    'inductive': ArgumentType.INDUCTIVE,
                    'abductive': ArgumentType.ABDUCTIVE,
                }

                def _strength(confidence: float) -> ArgumentStrength:
                    if confidence >= 0.9:
                        return ArgumentStrength.CONCLUSIVE
                    if confidence >= 0.75:
                        return ArgumentStrength.STRONG
                    if confidence >= 0.5:
                        return ArgumentStrength.MODERATE
                    return ArgumentStrength.WEAK

                arguments = []
                for candidate in candidate_answers:
                    claim = Claim(
                        claim_id=f"claim_{candidate['path']}",
                        statement=candidate['answer'],
                        confidence=candidate['base_confidence'],
                        source=candidate['path'],
                    )
                    argument = Argument(
                        argument_id=candidate['path'],
                        claim=claim,
                        argument_type=path_types.get(candidate['path'], ArgumentType.INDUCTIVE),
                        conclusion=candidate['answer'],
                        strength=_strength(candidate['base_confidence']),
                    )
                    argument.fallacies_detected = [
                        f.fallacy_type for f in arg_engine.detect_fallacies(argument)
                    ]
                    arguments.append(argument)

                root = Claim(claim_id="claim_root", statement=request.query)
                graph = arg_engine.build_argument_graph(
                    topic=request.query[:120],
                    root_claim=root,
                    arguments=arguments,
                )

                # Skeptical acceptance (grounded) outranks credulous acceptance
                # (member of some preferred extension), which outranks defeat.
                grounded = set(graph.grounded_extension)
                credulous = {a for ext in graph.preferred_extensions for a in ext}

                for candidate in candidate_answers:
                    arg_id = candidate['path']
                    if arg_id in grounded:
                        argument_strength, status = 1.0, 'grounded'
                    elif arg_id in credulous:
                        argument_strength, status = 0.6, 'credulous'
                    else:
                        argument_strength, status = 0.2, 'defeated'

                    argument_scores.append(argument_strength)
                    candidate['argument_strength'] = argument_strength
                    candidate['acceptance'] = status

                    logger.info(
                        f"  {candidate['path']}: {status} "
                        f"(argument_strength={argument_strength:.3f})"
                    )

                logger.info(
                    f"  Dung semantics: grounded={sorted(grounded)}, "
                    f"{len(graph.preferred_extensions)} preferred extension(s), "
                    f"{len(graph.attacks)} attack(s)"
                )

            except Exception as e:
                logger.warning(f"Formal argumentation failed, using base confidence: {e}")
                argument_scores = [c['base_confidence'] for c in candidate_answers]
            
            # Phase 3: CONSISTENCY VERIFICATION
            # Check logical consistency with constraint solver
            logger.info("🔬 Verifying logical consistency")
            
            consistency_scores = []
            try:
                from core.reasoning.constraint_solver import ConstraintSolver
                solver = ConstraintSolver()
                
                if solver.available:
                    for candidate in candidate_answers:
                        # Consistency is decided by the solver: does the context
                        # actually entail the negation of this candidate?
                        #
                        # This previously scored an answer inconsistent when it
                        # contained the words 'but', 'however' or 'although' --
                        # a proxy anti-correlated with what it claimed to
                        # measure, since it penalised qualified reasoning while
                        # a flat self-contradiction with no discourse markers
                        # scored a clean 1.0.
                        contradiction = await self._check_formal_constraints(
                            candidate['answer'], request
                        )

                        if contradiction:
                            consistency = 0.0
                        else:
                            # No contradiction found. Unformalizable answers land
                            # here too, so this means "not shown inconsistent"
                            # rather than "verified consistent".
                            consistency = 1.0

                        consistency_scores.append(consistency)
                        candidate['consistency'] = consistency
                else:
                    consistency_scores = [1.0] * len(candidate_answers)
            
            except Exception as e:
                logger.debug(f"Constraint solver not available: {e}")
                consistency_scores = [1.0] * len(candidate_answers)
            
            # Phase 4: WEIGHTED ARBITRATION
            # Combine argument strength + consistency + base confidence
            for i, candidate in enumerate(candidate_answers):
                arg_score = argument_scores[i] if i < len(argument_scores) else 0.5
                cons_score = consistency_scores[i] if i < len(consistency_scores) else 1.0
                base_conf = candidate['base_confidence']
                
                # Weighted combination
                final_score = (
                    arg_score * 0.4 +      # Argument strength (40%)
                    cons_score * 0.3 +     # Consistency (30%)
                    base_conf * 0.3        # Base confidence (30%)
                )
                
                candidate['final_score'] = final_score
                
                logger.info(
                    f"  {candidate['path']}: final_score={final_score:.3f} "
                    f"(arg={arg_score:.2f}, cons={cons_score:.2f}, base={base_conf:.2f})"
                )
            
            # Select winner
            winner = max(candidate_answers, key=lambda c: c['final_score'])
            
            logger.info(
                f"✓ Arbitration selected: {winner['path']} "
                f"(score={winner['final_score']:.3f})"
            )
            
            metadata = {
                "parallel_paths": len(candidate_answers),
                "winning_path": winner['path'],
                "arbitration_scores": {
                    c['path']: c['final_score'] for c in candidate_answers
                },
                "argument_strength": winner.get('argument_strength', 0.0),
                "consistency": winner.get('consistency', 1.0),
                # substrate-first credit-assignment contract
                "verified": True,
                "formalized": False,
                KEY_SUBSTRATE_FORMALIZED: False,
                "reason": REASON_DERIVED_BY_KIND,
                "model_required": False,
                "model_available": self._model_available(),
                "route": ["substrate", "kinds_of_thinking", "neuro_symbolic"],
            }
            
            return ReasoningResult(
                answer=winner['answer'],
                confidence=winner['final_score'],
                reasoning_steps=[
                    f"Evaluated {len(candidate_answers)} parallel reasoning paths",
                    f"Formal arbitration selected {winner['path']} path",
                    f"Argument strength: {winner.get('argument_strength', 0):.2f}",
                    f"Logical consistency: {winner.get('consistency', 1):.2f}"
                ],
                mode_used=ReasoningMode.NEURO_SYMBOLIC,
                full_response=winner['full_response'],
                metadata=metadata
            )
            
        except Exception as e:
            logger.error(f"Neuro-symbolic arbitration error: {e}")
            return None

    def _build_reasoning_context(self, request: "ReasoningRequest", kinds: list):
        """The ONE place a ReasoningRequest becomes a ReasoningContext.

        Shared by every substrate route that runs the kinds -- `_reason_by_kind`
        and the ensemble in `_neuro_symbolic_reasoning` -- so the split of the
        context into premises / rules / facts / goal has a single owner rather
        than a copy per caller. See the inline notes below for why each split
        matters; they were paid for in measured defects.
        """
        from core.reasoning.abstract_reasoning_engine import (
            ReasoningContext, ReasoningPremise)
        context = ReasoningContext(
            context_id=f"kinds_{uuid.uuid4().hex[:12]}",
            domain=str((request.task_metadata or {}).get("domain") or "general"),
            problem_type="reasoning_request",
            # THE CONTEXT IS SPLIT BY WHAT EACH ITEM IS.
            #
            # A flat list of strings was not enough. Abduction searches
            # `context.rules` backwards and deduction fires over them, so a
            # context item that IS an implication has to arrive as a rule --
            # passed as a premise it is inert, and both strategies produced
            # nothing and fell through to a model. Measured: "what best explains
            # the wet lawn?" with `rained -> lawn_wet` in context reached the
            # model, while abduction sat registered and applicable.
            premises=[
                ReasoningPremise(premise_id=f"ctx{i}", statement=str(item),
                                 confidence=1.0, source="request_context")
                for i, item in enumerate(request.context or ())
                if not _is_implication(str(item))
            ],
            rules=[str(item) for item in (request.context or ())
                   if _is_implication(str(item))],
            # THE QUESTION IS NOT A FACT. It used to be passed as
            # `facts=[request.query]`, and abduction reads its observations from
            # premises PLUS facts -- so "what best explains the wet lawn?"
            # became something to be explained. Nothing explains a question, so
            # coverage halved and every abductive conclusion was scored at
            # exactly half its true value: 0.35 where the formula gives 0.70.
            #
            # A quiet, plausible number. The conclusion was right and only its
            # confidence was wrong, which is the kind of error nothing reports.
            # The stated context IS the known state. Counterfactual reasoning
            # needs it -- there is nothing to compare an alternative against
            # without the conditions that actually hold -- and emptying `facts`
            # entirely to keep the question out made every counterfactual
            # inapplicable and sent it to a model.
            #
            # Safe to repeat the premises here: `_observations` deduplicates on
            # the statement text, so nothing is counted twice.
            facts=[str(item) for item in (request.context or ())
                   if not _is_implication(str(item))],
            # THE QUESTION IS THE GOAL. Logical and probabilistic reasoning both
            # need a claim to settle -- a prover with no theorem and a belief
            # system with no proposition have nothing to do -- and with
            # `target_conclusions` empty both refused and the request went to a
            # model. What is being asked about is the query itself.
            target_conclusions=[request.query],
            allowed_reasoning_types=kinds,
            # Deliberately permissive: this gate is about whether a conclusion
            # was DERIVED, and the strategies already refuse when the material
            # is absent. A high floor here would silently drop sound
            # low-confidence derivations in favour of a model's guess.
            confidence_threshold=0.05,
        )
        return context

    async def _reason_by_kind(
        self, request: ReasoningRequest
    ) -> Optional[ReasoningResult]:
        """Try the ELEVEN KINDS OF THINKING. None if none of them applies.

        Which kinds are tried: whatever the caller named in `request.kinds`,
        otherwise whatever the query's own markers indicate, otherwise every
        classical kind. That last fallback is not a guess -- each strategy's
        `is_applicable` then refuses unless the context carries the material it
        needs, which is a stricter filter than any list fixed in advance.

        RETURNS None RATHER THAN AN EMPTY RESULT when nothing applies or nothing
        is concluded. The caller must be able to tell "no kind of thinking fits
        this" from "a kind ran and found nothing", because only the first should
        fall through to a model.

        Every kind here is model-free. This runs after `_substrate_solvers` and
        before any execution route, which is the whole ordering: what Torin can
        prove, then what Torin can derive, then what a model can propose.
        """
        try:
            from core.reasoning.abstract_reasoning_engine import (
                ReasoningContext, ReasoningPremise, create_abstract_reasoning_engine)
        except Exception as error:
            logger.debug("kind-based reasoning unavailable: %s", error)
            return None

        kinds = (list(request.kinds)
                 or list(kinds_of_thinking_for(request.query))
                 or list(CLASSICAL_REASONING_TYPES))

        context = self._build_reasoning_context(request, kinds)

        try:
            engine = create_abstract_reasoning_engine()
            result = await engine.reason(context)
        except Exception as error:
            logger.warning("kind-based reasoning failed: %s: %s",
                           type(error).__name__, error)
            return None

        derived = [c for c in (result.conclusions or ())
                   if getattr(c, "origin", "derived") == "derived"]
        if not derived:
            logger.info("no kind of thinking settled this (tried %s)",
                        ", ".join(k.value for k in kinds[:6]))
            return None

        # RELEVANCE. A kind can derive a SOUND conclusion about an OFF-TOPIC
        # context sentence: the temporal kind reading 'during' in an unrelated
        # premise answers about that premise, not the query. Keep only
        # conclusions connected to the query's own topic; if a kind produced
        # only off-topic ones, the query is unsettled here, not answered by
        # something it did not ask about.
        topic = _query_topic(request.query, request.context)
        on_topic = [c for c in derived if _relevant_to_topic(c.statement, topic)]
        if not on_topic:
            logger.info("kinds derived only off-topic conclusions for %r",
                        request.query)
            return None

        best = on_topic[0]
        logger.info("settled by %s reasoning at %.2f",
                    best.reasoning_type.value, best.confidence)
        return ReasoningResult(
            answer=best.statement,
            confidence=best.confidence,
            reasoning_steps=list(best.reasoning_steps or ()),
            mode_used=ReasoningMode.ABSTRACT,
            metadata={
                # THE CREDIT-ASSIGNMENT CONTRACT. Every result must carry these
                # five, so a verdict and an inability are told apart by metadata
                # rather than by confidence -- both can be low.
                "verified": True,
                "formalized": False,   # derived, not propositionally formalized
                "reason": REASON_DERIVED_BY_KIND,
                "model_required": False,
                "model_available": self._model_available(),

                "kind": best.reasoning_type.value,
                "kinds_considered": [k.value for k in kinds],
                "conclusions": len(derived),
                KEY_SUBSTRATE_FORMALIZED: False,
                "route": ["substrate", "kinds_of_thinking",
                          best.reasoning_type.value],
            },
        )

    async def _abstract_reasoning(self, request: ReasoningRequest) -> ReasoningResult:
        """Route through AbstractReasoningEngine + analogy discovery + hierarchical abstraction."""
        logger.info("Using abstract reasoning (AbstractReasoningEngine + analogy + abstraction)")

        try:
            from core.reasoning.abstract_reasoning_engine import (
                create_abstract_reasoning_engine,
                ReasoningContext,
                ReasoningType,
            )

            engine = create_abstract_reasoning_engine()

            context = ReasoningContext(
                context_id="neural_bridge_abstract",
                domain="autonomous_system",
                problem_type="abstract_reasoning",
                facts=[request.query],
                allowed_reasoning_types=[
                    ReasoningType.DEDUCTIVE,
                    ReasoningType.INDUCTIVE,
                    ReasoningType.ANALOGICAL,
                ],
                max_inference_depth=5,
                confidence_threshold=request.confidence_threshold or 0.7,
            )

            result = await engine.reason(context)

            if not result or not result.conclusions:
                return ReasoningResult(
                    answer="No high-confidence abstract conclusions found.",
                    confidence=0.0,
                    reasoning_steps=["AbstractReasoningEngine returned no conclusions"],
                    mode_used=ReasoningMode.ABSTRACT,
                )

            best = result.conclusions[0]
            steps = best.reasoning_steps or ["Abstract reasoning applied"]
            
            # Phase 1: Enhance with analogy discovery
            analogies = []
            try:
                from core.reasoning.analogy_discovery import get_analogy_discovery
                analogy_engine = get_analogy_discovery()
                logger.info("🔗 Attempting analogy discovery")
                # Note: Placeholder - full integration requires domain extraction
                analogies = ["Analogy discovery engine available"]
            except Exception as e:
                logger.debug(f"Analogy discovery not available: {e}")
            
            # Phase 1: Enhance with hierarchical abstraction
            abstractions = []
            try:
                from core.reasoning.hierarchical_abstraction import get_hierarchical_abstraction
                abstraction_engine = get_hierarchical_abstraction()
                logger.info("🏗️ Attempting hierarchical abstraction")
                # Note: Placeholder - full integration requires concept extraction
                abstractions = ["Hierarchical abstraction engine available"]
            except Exception as e:
                logger.debug(f"Hierarchical abstraction not available: {e}")
            
            metadata = {
                "total_conclusions": result.total_inferences,
                "overall_confidence": result.overall_confidence,
            }
            if analogies:
                metadata["analogies"] = analogies
                steps.extend(analogies)
            if abstractions:
                metadata["abstractions"] = abstractions
                steps.extend(abstractions)

            return ReasoningResult(
                answer=best.statement,
                confidence=best.confidence,
                reasoning_steps=steps,
                mode_used=ReasoningMode.ABSTRACT,
                metadata=metadata,
            )

        except Exception as e:
            logger.error(f"Abstract reasoning error: {e}")
            return ReasoningResult(
                answer=f"Error during abstract reasoning: {e}",
                confidence=0.0,
                reasoning_steps=["Abstract reasoning failed"],
                mode_used=ReasoningMode.ABSTRACT,
            )

    def _is_cross_domain_request(self, request: ReasoningRequest) -> bool:
        """True only when the caller named domains to reason ACROSS.

        Cross-domain grounding is not one of the eleven kinds -- it maps
        structure BETWEEN domains, so it needs at least a source domain to
        ground. A caller asks for it by putting source_domains (and optionally
        target_domains) in task_metadata. Without that there is nothing to
        ground across, so the substrate reports honest inability rather than
        inventing a domain to reason from.
        """
        meta = request.task_metadata or {}
        return bool(meta.get("source_domains") or meta.get("target_domains"))

    async def _cross_domain_reasoning(self, request: ReasoningRequest) -> Optional[ReasoningResult]:
        """Cross-domain grounding via UniversalDomainMaster. MODEL-FREE.

        Maps structure BETWEEN named domains (source -> target) and returns what
        that grounding produced. Not one of the eleven kinds. Returns None when
        nothing grounds across the domains -- honest inability, never a
        fabricated 'no insights' answer.
        """
        logger.info("cross-domain grounding (UniversalDomainMaster)")
        try:
            from core.integration.universal_domain_master import (
                get_universal_domain_master, CrossDomainQuery,
                ReasoningStrategy as UDMReasoningStrategy)

            master = get_universal_domain_master()
            meta = request.task_metadata or {}
            source_domains = meta.get("source_domains") or ["autonomous_system"]
            target_domains = meta.get("target_domains") or None

            query = CrossDomainQuery(
                query_id="neural_bridge_cross_domain",
                # ANALOGICAL maps concepts BY CORRESPONDENCE across domains,
                # which is what a cross-domain question asks; COMPOSITIONAL and
                # STRUCTURAL returned nothing on real concept pairs. Threshold
                # 0.5, not the 0.7 default: genuine analogies (heart<->pump)
                # score 0.5-0.8 by semantic similarity, so 0.7 rejects exactly
                # the correspondences this is for. Every mapping is a CANDIDATE
                # (verified=None) regardless.
                reasoning_strategy=UDMReasoningStrategy.ANALOGICAL,
                source_domains=source_domains,
                target_domains=target_domains,
                query_text=request.query,
                min_similarity=0.5,
                metadata={"source": "neural_bridge", "task_type": meta.get("task_type")},
            )
            result = await master.execute_cross_domain_query(query)
        except Exception as e:
            logger.warning(f"cross-domain grounding failed to run: {e}")
            return None

        if not getattr(result, "success", False) or not getattr(result, "mappings", None):
            logger.info("cross-domain: no mapping grounds these domains")
            return None

        mapping_conf = [getattr(m, "confidence", 0.0) for m in result.mappings]
        confidence = sum(mapping_conf) / len(mapping_conf) if mapping_conf else 0.0
        insights_text = ("\n".join(str(i) for i in result.insights)
                         if result.insights
                         else f"{len(result.mappings)} cross-domain mapping(s) grounded")

        return ReasoningResult(
            answer=insights_text,
            confidence=confidence,
            reasoning_steps=[
                f"grounded {len(result.mappings)} mapping(s) across "
                f"{getattr(result, 'domains_queried', 0)} domain(s)"],
            mode_used=ReasoningMode.CROSS_DOMAIN,
            metadata={
                "verified": True,
                "formalized": False,
                KEY_SUBSTRATE_FORMALIZED: False,
                "reason": REASON_DERIVED_BY_KIND,
                "model_required": False,
                "model_available": self._model_available(),
                "mappings": len(result.mappings),
                "processing_time": getattr(result, "execution_time", 0.0),
                "route": ["substrate", "cross_domain"],
            },
        )

    def _update_stats(self, request: ReasoningRequest, result: ReasoningResult):
        """Update statistics"""
        self.statistics['total_requests'] += 1

        # The mode actually used is what the result records (a kind of thinking,
        # a proof, or honest non-settlement). There is no AUTO bucket any more.
        mode = result.mode_used or request.mode

        if mode == ReasoningMode.SYMBOLIC:
            self.statistics['symbolic_requests'] += 1
        elif mode == ReasoningMode.NEURAL:
            self.statistics['neural_requests'] += 1
        elif mode == ReasoningMode.NEURO_SYMBOLIC:
            self.statistics['neuro_symbolic_requests'] += 1
        elif mode == ReasoningMode.ABSTRACT:
            self.statistics['abstract_requests'] += 1
        elif mode == ReasoningMode.CROSS_DOMAIN:
            self.statistics['cross_domain_requests'] += 1
        else:
            self.statistics['hybrid_requests'] += 1

        # Update average confidence
        n = self.statistics['total_requests']
        self.statistics['average_confidence'] = (
            (self.statistics['average_confidence'] * (n - 1) + result.confidence) / n
        )


    async def _capture_reasoning_memory(self, request: ReasoningRequest, result: ReasoningResult) -> None:
        """
        Persist a reasoning trace to the memory agent (background task, never raises).

        The memory filter decides whether the trace is worth keeping — trivial
        single-step responses are rejected automatically, complex multi-step
        reasoning with high confidence is retained.
        """
        try:
            complexity = self._calculate_complexity_score(request, result)

            # Skip traces that are almost certainly noise (very low complexity + low confidence)
            if complexity < 0.15 and result.confidence < 0.6:
                logger.debug(f"Skipping trivial reasoning trace (complexity={complexity:.2f}, confidence={result.confidence:.2f})")
                return

            # Format content: query → steps → answer
            steps_block = ""
            if result.reasoning_steps and result.reasoning_steps != ["Direct neural inference"]:
                steps_text = "\n".join(f"  {i+1}. {s}" for i, s in enumerate(result.reasoning_steps))
                steps_block = f"\n\nReasoning steps:\n{steps_text}"

            content = (
                f"Query: {request.query[:500]}"
                f"{steps_block}"
                f"\n\nAnswer: {result.answer[:800]}"
            )

            # Importance: blend complexity and confidence, bias up for multimodal
            importance = min(0.4 + complexity * 0.4 + result.confidence * 0.2, 1.0)
            if request.image or request.video:
                importance = min(importance + 0.1, 1.0)

            # Tags
            mode_tag = result.mode_used.value if result.mode_used else "hybrid"
            tags = ["reasoning", mode_tag]

            # TAG THE KIND OF THINKING, NOT ONLY THE ROUTE IT TOOK.
            #
            # `mode_used` is the execution route, so every kind-derived
            # conclusion was stored as "abstract" -- a causal derivation and a
            # spatial one were indistinguishable in the record, and a later
            # reader could not ask "what has Torin concluded causally?" at all.
            # The kind is the more informative fact and is what makes the record
            # readable afterwards.
            kind = (result.metadata or {}).get("kind")
            if kind and kind not in tags:
                tags.append(str(kind))
            if request.image or request.video:
                tags.append("multimodal")
            if len(result.reasoning_steps) >= 3:
                tags.append("multi_step")

            # Memory type: import lazily to avoid circular imports at module load
            try:
                import importlib

                memory_models = importlib.import_module("core.memory.models")
                MemoryType = getattr(memory_models, "MemoryType", None)
                if MemoryType is None:
                    raise AttributeError("MemoryType not available")
                mem_type = MemoryType.REASONING if len(result.reasoning_steps) >= 2 else MemoryType.EPISODIC
            except Exception:
                mem_type = None  # memory agent will infer

            # Use enqueue_memory() — non-blocking fire-and-forget.
            # The write queue worker in MemoryAgent will persist this
            # in the background while the caller continues immediately.
            # The pending dict makes it visible to injection right away.
            self.memory_agent.enqueue_memory(
                content=content,
                memory_type=mem_type,
                importance_score=importance,
                confidence_score=result.confidence,
                tags=tags,
                source_context={
                    "source": "neural_bridge",
                    "mode": mode_tag,
                    "query_length": len(request.query),
                    "complexity": complexity,
                    # THE CLAIM, KEPT AS A CLAIM.
                    #
                    # `content` renders the whole episode for a reader --
                    # "Query: ... / Reasoning steps: ... / Answer: ..." -- and
                    # `reasoning_trace` holds the derivation. Neither is a
                    # statement: a trace step reads "link strength 1.00", which
                    # is a measurement of the reasoning, not something that is
                    # the case.
                    #
                    # What a past conclusion contributes to later reasoning is
                    # the CONCLUSION. Recalling it should hand back "disk
                    # exhaustion causes checkout timeout", not a document about
                    # having concluded it. Stored here, at the moment it is
                    # known, rather than parsed back out of prose later.
                    "conclusion": result.answer,
                    "conclusion_confidence": result.confidence,
                    "conclusion_kind": (result.metadata or {}).get("kind"),
                },
                reasoning_trace=result.reasoning_steps,
            )
            logger.debug(f"Reasoning trace enqueued (importance={importance:.2f})")

        except Exception as e:
            # Background task — log and swallow; never propagate to caller
            logger.warning(f"_capture_reasoning_memory failed: {e}")

    def _calculate_complexity_score(self, request: ReasoningRequest, result: ReasoningResult) -> float:
        """Calculate complexity score (0.0-1.0) for neural-symbolic reasoning"""
        score = 0.0

        # Factor 1: Number of reasoning steps (up to 0.4)
        if result.reasoning_steps:
            score += min(len(result.reasoning_steps) / 5.0, 0.4)

        # Factor 2: Context usage (up to 0.3)
        score += min(len(request.context) / 10.0, 0.3)

        # FACTOR 3 REMOVED: a flat +0.2 for `mode_used == HYBRID`.
        #
        # Complexity is a property of the RESULT -- how many steps it took, how
        # much context it needed -- not of which engine produced it. This added
        # 0.2 unconditionally for one enum member, and since complexity feeds
        # `importance` at 0.4x, it made every hybrid answer 0.08 more important
        # to remember than an identical answer from any other mode.
        #
        # Measured on identical content and identical steps, before removal:
        #
        #     symbolic @ 0.98 confidence -> importance 0.838
        #     hybrid   @ 0.98 confidence -> importance 0.918
        #     hybrid   @ 0.35 confidence -> importance 0.830
        #
        # A hybrid guess at 35% confidence was stored as almost exactly as
        # important as a Z3-verified refutation proof at 98%. Nothing about the
        # content justified the difference; the mode alone did.

        # Factor 4: Confidence (up to 0.1, inverted - lower confidence = more complex)
        score += min((1.0 - result.confidence) * 0.2, 0.1)

        # Factor 5: Vision/multimodal processing (0.3) - ONLY if successful
        # Vision queries involve expensive multimodal processing
        # BUT: Only boost if not an error response (don't reward failures)
        if request.image is not None or request.video is not None:
            # Detect error responses
            answer_lower = result.answer.lower() if result.answer else ""
            is_error = any(phrase in answer_lower for phrase in [
                "sorry", "cannot see", "not visible", "unable to",
                "can't see", "image you intended", "please upload"
            ])

            # Only boost for successful vision analysis
            if not is_error and result.confidence > 0.5:
                score += 0.3

        return min(score, 1.0)

    async def get_statistics(self) -> Dict[str, Any]:
        """Get bridge statistics"""
        return self.statistics.copy()


# Singleton instance
_neural_bridge = None


def get_neural_bridge() -> NeuralSymbolicBridge:
    """Get global neural bridge instance"""
    global _neural_bridge
    if _neural_bridge is None:
        _neural_bridge = NeuralSymbolicBridge()
    return _neural_bridge


# CLI test
async def main():
    """Test neural bridge"""
    logging.basicConfig(level=logging.INFO)

    bridge = get_neural_bridge()
    await bridge.initialize()

    # Test reasoning
    request = ReasoningRequest(
        query="What is the capital of France?",
        mode=ReasoningMode.HYBRID
    )

    result = await bridge.reason(request)

    print("\n=== Neural Bridge Test ===")
    print(f"Query: {request.query}")
    print(f"Answer: {result.answer}")
    print(f"Confidence: {result.confidence}")
    print(f"Mode: {result.mode_used.value}")
    print(f"Steps: {result.reasoning_steps}")

    # Get statistics
    stats = await bridge.get_statistics()
    print(f"\nStatistics: {stats}")


if __name__ == "__main__":
    asyncio.run(main())
