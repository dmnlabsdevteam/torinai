#!/usr/bin/env python3
"""Deriving how to read a sentence, and putting it where reading happens.

`ReadingRegistry` exists so a DERIVED reading can be consulted before any model,
and `DerivedReadingFormalizer` already asks it on every formalization. Nothing
ever registered one. The registry was empty in every process that ever ran, the
formalizer returned nothing every time, and the conversation path fell through
to positional guessing plus a model asked to find the seams in the sentence.

That fallback is what produced the junk: `which_lines_belong_to_which_block` and
`you` admitted as entities, `write --a function count_o--> threshold` admitted
as a relation. Nothing was wrong with the ingress -- it faithfully admitted
whatever it was handed, and it was handed guesses.

    THE CONSTRUCTOR ALREADY EXISTS. `procedure_synthesis.derive_procedure`
    builds a procedure out of operators the substrate has already learned,
    accepting a candidate only when it produces the required answer on EVERY
    example. This supplies it the evidence and registers what comes back.

EDU-13 derived exactly this and proved it on seven held-out sentences whose
content words never appeared in the evidence, with zero model calls. It then
threw it away when the process exited. The only thing this module adds is that
the result survives into the running system.

NO MODEL IS INVOLVED AT ANY POINT.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Any, List, Optional, Tuple

from core.semantics.sentence_machine import (AFFIRMS, COPULAS, DENIES,
                                             DETERMINERS, FLAGS, INSTRUCTIONS,
                                             NEGATORS, SentenceMachine,
                                             tokenize)

logger = logging.getLogger(__name__)

#: Demonstrations of each instruction: (sentence, instructions run first).
#: EVIDENCE, NOT A GRAMMAR. Each row is the machine being shown one step, and
#: what the step is for is induced from the state change it causes.
DEMONSTRATIONS = {
    "BIND_SUBJECT": [("robin is a bird", []), ("vault holds gold", []),
                     ("the cat sees a dog", ["SKIP"])],
    "BIND_OBJECT": [("robin is a bird", ["BIND_SUBJECT", "SKIP", "SKIP"]),
                    ("vault holds gold", ["BIND_SUBJECT", "SKIP"]),
                    ("the cat sees a dog", ["SKIP", "BIND_SUBJECT", "SKIP", "SKIP"])],
    "MARK_NEGATIVE": [("robin is not a mammal", ["BIND_SUBJECT", "SKIP"]),
                      ("gold is not cheap", ["BIND_SUBJECT", "SKIP"]),
                      ("the cat is not a dog", ["SKIP", "BIND_SUBJECT", "SKIP"])],
    "EXTEND_SUBJECT": [("the smoke alarm is red", ["SKIP", "BIND_SUBJECT"]),
                       ("the fire alarm is loud", ["SKIP", "BIND_SUBJECT"])],
    "EXTEND_OBJECT": [("the alarm is a smoke detector",
                       ["SKIP", "BIND_SUBJECT", "SKIP", "SKIP", "BIND_OBJECT"]),
                      ("the pump is a fluid mover",
                       ["SKIP", "BIND_SUBJECT", "SKIP", "SKIP", "BIND_OBJECT"])],
    "SKIP": [("robin is a bird", ["BIND_SUBJECT"]),
             ("vault holds gold", ["BIND_SUBJECT"]),
             ("the cat sees a dog", [])],
    "EMIT": [("robin is a bird", ["BIND_SUBJECT", "SKIP", "SKIP", "BIND_OBJECT"]),
             ("vault holds gold", ["BIND_SUBJECT", "SKIP", "BIND_OBJECT"]),
             ("the cat is not a dog",
              ["SKIP", "BIND_SUBJECT", "SKIP", "MARK_NEGATIVE", "SKIP", "BIND_OBJECT"])],
}

#: One induction per register an instruction writes: a rule may only conclude
#: about terms its body binds.
TARGETS = {
    "BIND_SUBJECT": ["SUBJECT", "AT"], "BIND_OBJECT": ["OBJECT", "AT"],
    "EXTEND_SUBJECT": ["SUBJECT", "AT"], "EXTEND_OBJECT": ["OBJECT", "AT"],
    "MARK_NEGATIVE": ["POLARITY", "AT"], "SKIP": ["AT"], "EMIT": ["READING"],
}

#: Sentence, and what it means. Chosen to force the reading rather than flatter
#: it: a bare subject and one behind a determiner, an affirmative and a
#: negation, so no policy that ignores word class fits them all.
TAUGHT: List[Tuple[str, Tuple[str, str, str]]] = [
    ("robin is a bird", ("robin", "bird", AFFIRMS)),
    ("the vault is locked", ("vault", "locked", AFFIRMS)),
    ("a dog is an animal", ("dog", "animal", AFFIRMS)),
    ("robin is not a mammal", ("robin", "mammal", DENIES)),
    ("the engine is not cold", ("engine", "cold", DENIES)),

    # QUESTIONS. A question makes the same claim a statement does -- "is the
    # vault locked?" and "the vault is locked" relate the same two things -- and
    # differ only in what the asker wants done with it. Which is the query and
    # which the premise is decided by POSITION at formalization, not by grammar,
    # so a reading need not mark the form.
    #
    # It could not read one before, and the reason was teaching rather than
    # capability: every taught sentence put the subject first, so no procedure
    # covering them had to handle a sentence OPENING with a copula. The machine
    # could always express it -- SKIP(is), SKIP(the), BIND_SUBJECT, BIND_OBJECT,
    # EMIT -- nothing was ever asked to.
    #
    # Measured before: the derived reading settled 0 of 2 question cases while
    # the hand-written patterns settled both.
    ("is the vault locked", ("vault", "locked", AFFIRMS)),
    ("is robin a bird", ("robin", "bird", AFFIRMS)),
    ("is the engine not cold", ("engine", "cold", DENIES)),
    ("the smoke alarm is red", ("smoke_alarm", "red", AFFIRMS)),
    ("the fire alarm is loud", ("fire_alarm", "loud", AFFIRMS)),
    ("the alarm is a smoke detector", ("alarm", "smoke_detector", AFFIRMS)),

    # SUBJECT-VERB-OBJECT, no copula. The verb has content AHEAD of it (the
    # object); the object does not. That is the signal the reading learns.
    ("the heart pumps blood", ("heart", "blood", AFFIRMS)),
    ("vault holds gold", ("vault", "gold", AFFIRMS)),
]

MAX_RULES = 12

class _Unanimous:
    """Every procedure that fit the evidence, answering together.

    Exposes the `run` a `DerivedReading` expects, so the registry and the
    formalizer are unaware there is more than one candidate -- what they get is
    a reading the evidence determines, or nothing.
    """

    __slots__ = ("procedures",)

    def __init__(self, procedures):
        self.procedures = tuple(procedures)

    def run(self, machine, max_steps: int):
        # The machine handed in is consumed by the first run, so each candidate
        # gets its own built from the same words.
        sentence = " ".join(machine.words)
        answers, outcomes = set(), []
        for procedure in self.procedures:
            outcome = procedure.run(SentenceMachine(sentence), max_steps)
            outcomes.append(outcome)
            answers.add(tuple(outcome.answer.args)
                        if outcome.produced_answer else None)
        if len(answers) == 1 and None not in answers:
            return outcomes[0]
        if len(answers) > 1:
            logger.info("sentence %r separates the %d surviving readings %s; "
                        "it is the discriminating example that would decide them",
                        sentence, len(self.procedures), sorted(map(str, answers)))
        return outcomes[0] if not outcomes[0].produced_answer else _NoAnswer()


class _NoAnswer:
    """A run that produced nothing, because the candidates did not agree."""

    produced_answer = False
    answer = None
    status = None


_lock = threading.Lock()
_state: dict = {"derived": False, "reading": None, "why": ""}


def budget(sentence: str) -> int:
    """Steps the procedure may take. Two per word plus room to emit."""
    return 2 * len(SentenceMachine(sentence).words) + 6


def _learn_instructions(authority):
    """Induce what each instruction does, from being shown it act."""
    from core.execution.procedure import Operator
    from core.learning.rule_induction import Fact, TrainingExample

    operators = []
    for instruction in INSTRUCTIONS:
        examples = []
        for sentence, prefix in DEMONSTRATIONS[instruction]:
            machine = SentenceMachine(sentence)
            for earlier in prefix:
                if not machine.perform(Fact(earlier, ())):
                    return None, f"{instruction}: setup {earlier} refused on {sentence!r}"
            before = tuple(sorted(machine.observe()))
            action = Fact(instruction, ())
            if not machine.perform(action):
                return None, f"{instruction} refused on {sentence!r} after {prefix}"
            after = tuple(sorted(machine.observe()))
            examples.append(TrainingExample(before=before + (action,), action=action,
                                            after=after + (action,), positive=True))
            # Nothing happens without acting. Without this the induction can
            # explain the state change with a rule that has no action in it.
            examples.append(TrainingExample(before=before, action=None,
                                            after=before, positive=False))

        rules = []
        for target in TARGETS[instruction]:
            result = authority.induce(examples, target_predicate=target)
            if result.rule is None:
                return None, (f"{instruction} explaining {target}: "
                              f"{result.status.value}")
            rules.append(result.rule)
        operators.append(Operator(action=Fact(instruction, ()), rules=tuple(rules)))
    return operators, ""


def derive() -> Tuple[Optional[object], str]:
    """Derive the reading procedure. Once per process, then cached.

    Returns (DerivedReading, "") or (None, why). A failure is REPORTED, never
    swallowed into a silent fallback -- if this cannot be derived, the caller
    must know it is reading by guess.
    """
    with _lock:
        if _state["derived"]:
            return _state["reading"], _state["why"]

        from core.learning.unified_learning_system import get_learning_authority
        from core.learning.procedure_synthesis import IOExample, SynthesisStatus
        from core.learning.rule_induction import Fact
        from core.semantics.reading_registry import DerivedReading

        authority = get_learning_authority()
        try:
            operators, why = _learn_instructions(authority)
            if operators is None:
                _state.update(derived=True, reading=None, why=why)
                logger.warning("reading not derived: %s", why)
                return None, why

            guards = tuple(Fact(flag, ()) for flag in FLAGS)
            examples = [IOExample(label=s,
                                  build=lambda t=s: SentenceMachine(t),
                                  expected=m, max_steps=budget(s))
                        for s, m in TAUGHT]
            result = authority.derive_procedure(
                operators, guards, examples, terminal="READING",
                max_rules=MAX_RULES)
        except Exception as error:
            why = f"derivation raised {type(error).__name__}: {error}"
            _state.update(derived=True, reading=None, why=why)
            logger.warning("reading not derived: %s", why)
            return None, why

        if result.status not in (SynthesisStatus.PROCEDURE_DERIVED,
                                 SynthesisStatus.MULTIPLE_PROCEDURES):
            why = f"synthesis returned {result.status.value}: {result.detail}"
            _state.update(derived=True, reading=None, why=why)
            logger.warning("reading not derived: %s", why)
            return None, why

        # MULTIPLE_PROCEDURES is underdetermination and it is the normal
        # outcome here: five sentences do not pin down the route through six
        # guards. Four procedures fit, and they differ only in how they get
        # there. Picking one would be choosing a reading the evidence does not
        # choose -- so ALL of them read every sentence and they must AGREE.
        # Where they disagree the sentence is exactly the input the synthesis
        # said "would decide", and the honest answer is that this reading does
        # not determine it.
        procedures = tuple(result.procedures)

        reading = DerivedReading(
            name="subject_object_polarity",
            procedure=_Unanimous(procedures),
            machine=SentenceMachine,
            budget=budget,
            provenance=(f"derived from {len(TAUGHT)} sentence/meaning pairs via "
                        f"procedure_synthesis over {len(INSTRUCTIONS)} induced "
                        f"instructions; {len(procedures)} procedure(s) fit and "
                        f"must agree; no model"),
        )
        _state.update(derived=True, reading=reading, why="")
        return reading, ""


def ensure_registered() -> Tuple[bool, str]:
    """Derive the reading if needed and put it in the registry.

    Idempotent: the registry is consulted on every formalization, and the same
    reading appearing twice would make one sentence two readings.
    """
    from core.semantics.reading_registry import get_reading_registry

    registry = get_reading_registry()
    if any(r.name == "subject_object_polarity" for r in registry.readings()):
        return True, ""

    reading, why = derive()
    if reading is None:
        return False, why
    registry.register(reading)
    return True, ""


#: Content words a reading may leave unaccounted for. Exactly one: the
#: relation. `vault holds gold` reads as (vault, gold) and `holds` is the word
#: that says how they relate.
MAX_RESIDUE = 1


def _content_words(sentence: str) -> List[str]:
    """Words that are not part of the supplied six-word function lexicon."""
    return [w for w in tokenize(sentence)
            if w not in COPULAS and w not in DETERMINERS and w not in NEGATORS]


def covers(sentence: str, subject: str, obj: str) -> Tuple[bool, int]:
    """Did the reading ACCOUNT FOR the sentence, or pick two words out of it?

    THE MACHINE ALWAYS EMITS. It walks to the end and reports whatever the
    registers hold, so a twelve-word sentence of the wrong shape produces a
    confident-looking reading rather than a refusal: "A function is a reusable
    block of code that encapsulates logic" came back as (function, logic) and
    the five words carrying the actual claim were dropped on the floor.

    A reading that leaves content words behind did not read the sentence. This
    counts them, and the count is the whole test -- there is no threshold tuned
    to make particular sentences pass.
    """
    # Split multi-token constituents on '_': a grouped subject like
    # 'smoke_alarm' accounts for the sentence words 'smoke' and 'alarm',
    # so a correct multi-word reading is not mistaken for residue.
    accounted = set()
    for _term in (subject, obj):
        accounted.update(_term.split('_'))
    residue = [w for w in _content_words(sentence) if w not in accounted]
    # THE RELATION IS THE COPULA WHEN ONE IS PRESENT, A VERB OTHERWISE.
    # "robin IS a bird" relates its two ends through the copula, so NO content
    # word should be left over; "the heart PUMPS blood" has no copula and the
    # one verb is the relation. So a copula sentence allows zero residue and a
    # verbal one allows exactly the verb. Without this split the one-word budget
    # meant for the verb silently absorbed a dropped noun-phrase word: "the
    # smoke alarm is red" read as (smoke, red) and "all dogs are animals" as
    # (all, animals) -- confident misreadings where an honest decline was right.
    has_copula = any(w in COPULAS for w in tokenize(sentence))
    max_residue = 0 if has_copula else MAX_RESIDUE
    return len(residue) <= max_residue, len(residue)


def relation_in(sentence: str, subject: str, obj: str) -> str:
    """The word saying HOW subject and object relate.

    The reading produces the two ends and the polarity; the relation is what is
    left between them. `vault holds gold` leaves `holds`. `robin is a bird`
    leaves nothing, and the copula is the relation -- the sentence says the one
    IS the other.
    """
    accounted = set()
    for _t in (subject, obj):
        accounted.update(_t.split('_'))
    residue = [w for w in _content_words(sentence) if w not in accounted]
    return residue[0] if residue else "is"


def read(sentence: str) -> Optional[Tuple[str, str, str]]:
    """(subject, object, polarity) for a sentence this reading covers.

    None means THIS READING DOES NOT APPLY, which is an answer. It is not a
    licence to guess -- a caller that cannot read a sentence has not been told
    anything by it.
    """
    reading, _ = derive()
    if reading is None:
        return None
    got = reading.read(sentence)
    if not got:
        return None
    accounted, residue = covers(sentence, got[0], got[1])
    if not accounted:
        logger.info("declining %r: the reading (%s, %s) leaves %d content "
                    "word(s) unaccounted for", sentence, got[0], got[1], residue)
        return None
    return (got[0], got[1], got[2])


# ── TYPED READING ─────────────────────────────────────────────────────────
# The predicate span, typed. The machine binds subject/object and the SPAN
# between them is the relation (syntax); `relation_types` says what that span
# MEANS (semantics). Kept here, in the reader, because delimiting the span is a
# reading job -- the same layer `relation_in` already lives in -- while the type
# and its inference are owned elsewhere.

_REL_LEADING: Optional[set] = None


def _relation_leading_words() -> set:
    """First tokens of every known relation surface form (minus bare function
    words). An object beginning with one of these was mis-bound by a machine
    that has not been taught the construction."""
    from core.semantics.relation_types import all_surface_forms
    words = set()
    for form in all_surface_forms():
        first = form.split()[0]
        if first not in COPULAS and first not in DETERMINERS and first not in NEGATORS:
            words.add(first)
    return words


def _reparse_relation_object(sentence: str, subject: str) -> Optional[Tuple[str, str]]:
    """Recover (relation_span, object) when the machine over-extended the object.

    The machine has only subject/object registers, so a relation word ('made',
    'part') with no predicate slot gets glued onto the object. The relation
    ONTOLOGY is the authority that fixes this, not a per-construction pattern:
    after the subject, the relation is the LONGEST known relation surface form,
    and the object is the content that follows it. Determiners are the supplied
    lexicon and never part of either. Generalises to every relation in the table
    -- a new relation type extends this for free.
    """
    from core.semantics.relation_types import all_surface_forms
    forms = set(all_surface_forms())
    if not forms:
        return None
    max_form = max(len(f.split()) for f in forms)
    toks = tokenize(sentence)
    subj_tokens = subject.split('_')

    end = None
    for i in range(len(toks) - len(subj_tokens) + 1):
        if toks[i:i + len(subj_tokens)] == subj_tokens:
            end = i + len(subj_tokens)
            break
    if end is None:
        return None

    rest = [w for w in toks[end:] if w not in DETERMINERS]
    for n in range(min(max_form, len(rest)), 0, -1):
        cand = " ".join(rest[:n])
        if cand in forms:
            obj_tokens = [w for w in rest[n:]
                          if w not in COPULAS and w not in NEGATORS]
            if obj_tokens:
                return cand, "_".join(obj_tokens)
            return None
    return None


def _object_word_class(obj: str) -> Optional[str]:
    """The lexicon's class for an object's head word, when known -- the hint that
    disambiguates the bare copula (is + ADJECTIVE = property, is + NOUN = kind)."""
    try:
        from core.semantics.lexicon import get_lexicon
        entry = get_lexicon()._entries.get(obj.split('_')[0].lower())
        return entry.word_class if entry else None
    except Exception:
        return None


def predicate_span(sentence: str, subject: str, obj: str) -> str:
    """The ordered relation span: content words between the ends, in order.

    Unlike `relation_in` (which returns one residue word), this keeps the whole
    phrase -- 'made of', 'lives in' -- so a multiword relation survives to be
    typed. Copulas/determiners/negators are the supplied function lexicon and
    are not part of the relation span."""
    # Account for the ends BOTH as their underscore-joined token ("hunting_dog",
    # which is how the sentence tokenises a multi-word lemma) AND as their parts
    # ("hunting","dog"). Splitting only on '_' left the whole-token form in the
    # residue, so a multi-word object leaked into the relation span and every
    # such edge mis-typed as related_to instead of isa -- silently corrupting the
    # taxonomy at scale.
    accounted = set(subject.split('_')) | set(obj.split('_')) | {subject, obj}
    span = [w for w in tokenize(sentence)
            if w not in accounted and w not in COPULAS
            and w not in DETERMINERS and w not in NEGATORS]
    return " ".join(span)


def segment_by_class(sentence: str):
    """Recover (subject, relation_span, object, polarity) of a no-copula sentence
    from TAUGHT content classes + the supplied function lexicon, or None.

    The derived reading covers the shapes it was taught; a sentence with a
    multi-word noun phrase (`the quick brown fox`) or a trailing prepositional
    adjunct (`sells shells by the sea`) is beyond it, and it drops the extra
    content words. When it has, the phrase structure is still recoverable IF the
    substrate has been taught the classes: determiners open a noun phrase,
    adjectives modify up to a noun head, the FIRST verb is the relation (with any
    particle), and a preposition standing AFTER the object opens an adjunct to
    drop (before it, the preposition is the relation). A content word whose class
    has NOT been taught makes this decline -- it never guesses a class, so a
    sentence only reads once its words have been taught, which is the teaching
    loop, not a fallback that agrees with everything.
    """
    from core.semantics.sentence_machine import (AUXILIARIES, COPULAS,
                                                  CONJUNCTIONS, DETERMINERS,
                                                  NEGATORS, PREPOSITIONS,
                                                  PRONOUNS, WH_OBJECT_OPENERS,
                                                  _taught_class, tokenize)
    toks = tokenize(sentence)
    if any(w in COPULAS for w in toks):
        return None            # copula sentences belong to the derived reading
    if any(w in CONJUNCTIONS for w in toks):
        return None            # coordination makes >1 claim -- needs multi-emit
    polarity = DENIES if any(w in NEGATORS for w in toks) else AFFIRMS
    # A wh-question asks for the OBJECT of a relation ("what does a kestrel eat?"):
    # the reading is (subject, relation, <unknown>). The marker `UNKNOWN` is the
    # object being asked -- exactly the fact a knowledge-gap check looks for.
    wh_object = bool(toks) and toks[0] in WH_OBJECT_OPENERS

    def role(w):
        if w in DETERMINERS: return "DET"
        if w in NEGATORS:    return "NEG"
        if w in AUXILIARIES: return "AUX"        # do/does/did -- skipped
        if w in WH_OBJECT_OPENERS: return "WH"   # what/which -- skipped
        if w in PREPOSITIONS: return "PREP"
        if w in PRONOUNS:    return "PRON"
        return _taught_class(w)          # NOUN / ADJECTIVE / VERB, or None

    roles = [role(w) for w in toks]
    # A content word with no class is a word never taught -- decline rather than
    # guess. Function words (DET/NEG/AUX/WH/PREP/PRON) are fine to be "unclassed".
    if any(r is None for r in roles):
        return None
    try:
        v = next(i for i, r in enumerate(roles) if r == "VERB")
    except StopIteration:
        return None                      # no relation verb found

    subj = [w for w, r in zip(toks[:v], roles[:v])
            if r in ("NOUN", "ADJECTIVE", "PRON")]
    if not subj:
        return None
    rel = [toks[v]]
    j = v + 1
    while j < len(toks) and roles[j] == "PREP":
        rel.append(toks[j]); j += 1
    obj: List[str] = []
    while j < len(toks):
        r = roles[j]
        if r in ("NOUN", "ADJECTIVE", "PRON"):
            obj.append(toks[j]); j += 1
        elif r == "DET":
            j += 1
        else:                            # a preposition after the object: adjunct
            break
    if not obj:
        # A wh-question legitimately has no object -- it is asking for one.
        if wh_object:
            return ("_".join(subj), " ".join(rel), "UNKNOWN", polarity)
        return None
    return ("_".join(subj), " ".join(rel), "_".join(obj), polarity)


@dataclass
class TypedReading:
    """A read sentence with its relation TYPED. `relation` is a TypedRelation
    (carrying provenance + generic flag); the caller admits it as a proposition."""
    subject: str
    relation: "Any"          # relation_types.TypedRelation
    obj: str
    polarity: str
    #: Set when the machine could not bind the construction (object absorbed the
    #: relation word). Not a reading -- a request to be TAUGHT this construction.
    needs_construction: Optional[str] = None


def read_typed(sentence: str) -> Optional[TypedReading]:
    """Read a sentence and TYPE its relation, or decline.

    Declines two ways, both honest: `needs_construction` set when the machine
    mis-bound the object across an unlearned relation word (the typer's own
    vocabulary detects it), and None when the leftover is not a recognised
    relation at all (the misread guard, now keyed on the relation ontology
    rather than a raw residue count)."""
    from core.semantics.relation_types import classify, SemanticRelation
    global _REL_LEADING
    if _REL_LEADING is None:
        _REL_LEADING = _relation_leading_words()

    reading, _ = derive()
    if reading is None:
        return None
    got = reading.read(sentence)
    if not got:
        return None
    subject, obj, polarity = got

    # NO-COPULA MULTI-WORD FALLBACK. When the derived reading did not ACCOUNT for
    # the sentence -- it left content words on the floor, which is a multi-word
    # noun phrase or a trailing adjunct it was never taught -- recover the phrase
    # structure from taught classes. Only fires when the reading fell short, so
    # every shape the derived reading does cover is untouched; declines (falls
    # through) when a word's class was never taught.
    accounted, _residue = covers(sentence, subject, obj)
    if not accounted:
        seg = segment_by_class(sentence)
        if seg is not None:
            s_subj, s_rel, s_obj, s_pol = seg
            owc = _object_word_class(s_obj)
            typed = classify(s_rel if s_rel else "is", object_word_class=owc)
            # The ends are class-confident here, so the misread guard (meant for
            # the derived machine's junk spans) does not apply: an unknown verb
            # types as related_to, honestly reading the ends while licensing no
            # inference.
            return TypedReading(s_subj, typed, s_obj, s_pol)

    # OVER-EXTENSION RECOVERY. An untaught construction makes the machine extend
    # the object across the relation ("is made of brass" -> obj 'made_brass').
    # The typer's vocabulary both DETECTS it (object leads with a relation word)
    # and REPAIRS it (re-delimit relation vs object by the longest known form).
    # If the ontology cannot name the relation, decline honestly as unlearned.
    obj_lead = obj.split('_')[0]
    if obj_lead in _REL_LEADING:
        reparsed = _reparse_relation_object(sentence, subject)
        if reparsed is not None:
            rel_span, new_obj = reparsed
            owc = _object_word_class(new_obj)
            retyped = classify(rel_span, object_word_class=owc)
            if retyped.relation is not SemanticRelation.RELATED_TO:
                return TypedReading(subject, retyped, new_obj, polarity)
        logger.info("read_typed %r: object %r absorbed relation word %r and the "
                    "relation could not be named; construction unlearned",
                    sentence, obj, obj_lead)
        return TypedReading(subject, None, obj, polarity, needs_construction=obj_lead)

    span = predicate_span(sentence, subject, obj)
    owc = _object_word_class(obj)
    typed = classify(span if span else "is", object_word_class=owc)

    # Misread guard, now via the ontology: an unrecognised MULTIword leftover is
    # not a relation, it is dropped noun-phrase words -- decline.
    if typed.relation is SemanticRelation.RELATED_TO and len(span.split()) > 1:
        logger.info("read_typed %r: leftover %r is not a recognised relation",
                    sentence, span)
        return None

    return TypedReading(subject, typed, obj, polarity)


# ── MULTI-EMIT ────────────────────────────────────────────────────────────────
# One surface sentence can carry more than one proposition. A relative clause
# ("a robin, WHICH is small, is a bird") makes two claims about robin; a
# predicate conjunction ("the vault is cold AND heavy") makes two about the
# vault. The machine emits ONE reading, so those were mangled or declined. Rather
# than teach the machine to hold several readings, a sentence that carries
# several is DECOMPOSED into the simpler sentences it is equivalent to, each read
# by the one reader -- the relative clause becomes "robin is small", the
# conjunction becomes "the vault is heavy". No new machine: the same reader, run
# once per proposition the surface actually states.

_REL_CLAUSE = None
_PRED_CONJ = None


def _np_head(phrase: str) -> str:
    """The head word a relative 'which/who/that' refers back to: the last word of
    the antecedent noun phrase that is not a determiner. 'a robin' -> 'robin'."""
    toks = [w for w in tokenize(phrase) if w not in DETERMINERS]
    return toks[-1] if toks else phrase.strip()


def decompose(sentence: str) -> Optional[List[str]]:
    """The simpler sentences a multi-proposition surface is equivalent to, or None.

    Handles the two forms that carry more than one claim without a second finite
    clause of their own: a comma-delimited relative clause, and a predicate
    coordinated with 'and'. Anything else returns None and is read whole.
    """
    import re
    global _REL_CLAUSE, _PRED_CONJ
    if _REL_CLAUSE is None:
        # SUBJ , (which|who|that) CLAUSE , REST   -> "SUBJ REST" + "HEAD CLAUSE"
        _REL_CLAUSE = re.compile(
            r"^(?P<subj>.*?),\s*(?:which|who|that)\b\s+(?P<clause>.*?)\s*,\s*"
            r"(?P<rest>.*)$", re.I)
        # SUBJ (is|are) A and B   ->  "SUBJ is A" + "SUBJ is B"
        _PRED_CONJ = re.compile(
            r"^(?P<head>.*\b(?:is|are))\s+(?P<a>.+?)\s+and\s+(?P<b>.+)$", re.I)

    s = sentence.strip().rstrip(".").strip()

    m = _REL_CLAUSE.match(s)
    if m:
        subj, clause, rest = m.group("subj"), m.group("clause"), m.group("rest")
        main = f"{subj} {rest}".strip()
        relative = f"{_np_head(subj)} {clause}".strip()
        return [main, relative]

    m = _PRED_CONJ.match(s)
    if m:
        head, a, b = m.group("head"), m.group("a"), m.group("b")
        return [f"{head} {a}".strip(), f"{head} {b}".strip()]

    return None


def read_all(sentence: str) -> List["TypedReading"]:
    """Every proposition a sentence states, typed. One reading for a plain
    sentence; several when it decomposes (relative clause, conjunction). Empty
    when nothing in it reads -- an honest 'this said nothing I could read'."""
    parts = decompose(sentence)
    if parts:
        out: List[TypedReading] = []
        for part in parts:
            tr = read_typed(part)
            if tr is not None and tr.needs_construction is None:
                out.append(tr)
        # A decomposition that yields nothing readable is not better than reading
        # the whole; fall through so the caller still sees the honest single try.
        if out:
            return out
    tr = read_typed(sentence)
    return [tr] if tr is not None else []
