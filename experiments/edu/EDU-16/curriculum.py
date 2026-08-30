#!/usr/bin/env python3
"""EDU-16: teaching English from the bottom, in the order you would teach a child.

The substrate begins with three closed function-word sets -- {a, an, the},
{is, are}, {not} -- and NO notion of word classes. Every other word is
undifferentiated CONTENT. So the first lesson is not conjunctions or tense; it
is what a noun is.

    L1  NOUN         a word that names a thing
    L2  ADJECTIVE    a word that describes a thing
    L3  VERB         a word that names an action
    L4  SUBJECT+VERB          "the pump runs"
    L5  SUBJECT+VERB+OBJECT   "the pump moves water"

Each lesson uses only what the previous ones established. L4 cannot be taught
before VERB exists, and L5 cannot be taught before L4.

THE WORLD SUPPLIES TRUTH BY DISTRIBUTION, NOT BY LABEL.

The teacher may say "vault is a noun". That is a proposal. What makes it
evidence is that `vault` fits the slots a noun fits and fails the slots it does
not:

    the ___ is heavy        noun fits, verb does not
    the vault ___ water     verb fits, noun does not
    the vault is ___        adjective fits

So a word's class is decided by which frames accept it, which the substrate can
check itself against sentences it already reads. The teacher points; the
distribution decides.
"""

from dataclasses import dataclass
from typing import Dict, List, Tuple


@dataclass(frozen=True)
class Frame:
    """A slot test. A word belongs to a class if the class's frames accept it."""

    template: str          # '__' marks the slot
    accepts: str           # the class this frame is diagnostic for


#: Diagnostic frames. Deliberately few and visible -- this is not an attempt at
#: English syntax, it is the smallest distributional test that separates three
#: classes using sentences the substrate can already read.
FRAMES: Tuple[Frame, ...] = (
    Frame("the __ is heavy", "NOUN"),
    Frame("the __ is open", "NOUN"),
    Frame("the vault is __", "ADJECTIVE"),
    Frame("the pump is __", "ADJECTIVE"),
    Frame("the pump __ water", "VERB"),
    Frame("the valve __ air", "VERB"),
)

CLASSES = ("NOUN", "ADJECTIVE", "VERB")


#: ── TAUGHT VOCABULARY ───────────────────────────────────────────────────────
#: What the teacher is allowed to use as examples. Kept small on purpose.
TAUGHT: Dict[str, str] = {
    # tier 1 -- the first three of each class
    "vault": "NOUN", "pump": "NOUN", "valve": "NOUN",
    "heavy": "ADJECTIVE", "open": "ADJECTIVE", "hot": "ADJECTIVE",
    "moves": "VERB", "opens": "VERB", "cools": "VERB",
    # tier 2 -- widened so a rule has more than three examples to answer to
    "engine": "NOUN", "filter": "NOUN", "switch": "NOUN", "wire": "NOUN",
    "cold": "ADJECTIVE", "dry": "ADJECTIVE", "loose": "ADJECTIVE",
    "sealed": "ADJECTIVE",
    "heats": "VERB", "turns": "VERB", "blocks": "VERB", "carries": "VERB",
    # tier 3 -- includes the minimal pairs that make the classes discriminable
    "gauge": "NOUN", "belt": "NOUN",
    "warm": "ADJECTIVE", "tight": "ADJECTIVE",
    "warms": "VERB", "tightens": "VERB",
}

#: ── SEALED HELD-OUT VOCABULARY ──────────────────────────────────────────────
#: Never shown to the teacher, never used in a lesson. Classifying these is the
#: only result that means anything: it cannot be recall.
HELD_OUT: Dict[str, str] = {
    "tank": "NOUN", "motor": "NOUN", "pipe": "NOUN", "rotor": "NOUN",
    "bearing": "NOUN", "shaft": "NOUN",
    "loud": "ADJECTIVE", "empty": "ADJECTIVE", "rusty": "ADJECTIVE",
    "smooth": "ADJECTIVE", "worn": "ADJECTIVE", "clean": "ADJECTIVE",
    "pushes": "VERB", "seals": "VERB", "drains": "VERB",
    "spins": "VERB", "lifts": "VERB", "guides": "VERB",
}

#: ── SEALED HELD-OUT SENTENCES ───────────────────────────────────────────────
#: For L4/L5. Every content word is from HELD_OUT, so a sentence cannot be read
#: by having memorised the lesson's words.
HELD_OUT_SENTENCES: Tuple[Tuple[str, str, Tuple[str, ...]], ...] = (
    ("the motor is rusty",        "L1-L2", ("motor_rusty",)),
    ("the tank is not empty",     "L1-L2", ("~tank_empty",)),
    ("the pipes are loud",        "L6",    ("pipes_loud",)),
    ("the rotors are smooth",     "L6",    ("rotors_smooth",)),
    ("the shaft is not worn",     "L7",    ("~shaft_worn",)),
    ("the bearing is not clean",  "L7",    ("~bearing_clean",)),
    ("the motor drains",          "L4",    ("motor_drains",)),
    ("the rotor spins",           "L4",    ("rotor_spins",)),
    ("the pump pushes water",     "L5",    ("pump_pushes_water",)),
    ("the valve seals the pipe",  "L5",    ("valve_seals_pipe",)),
    ("the bearing lifts the shaft", "L5",  ("bearing_lifts_shaft",)),
    ("the shaft guides the belt", "L5",    ("shaft_guides_belt",)),
)


#: ── EXPOSURE CORPUS ────────────────────────────────────────────────────────
#: Sentences the substrate is GIVEN to read, using held-out words. This is how a
#: learner meets a new word: used, in a sentence, not defined.
#:
#: SEPARATE FROM THE GRADED SENTENCES ON PURPOSE. If class were harvested from
#: the same sentences the reading score is computed on, the two measurements
#: would share their data and neither would mean anything on its own. Nothing
#: here states a class; the classes are what the substrate has to extract.
EXPOSURE: Tuple[str, ...] = (
    # nouns and adjectives meet each other first
    "the tank is loud",
    "the motor is empty",
    "the pipe is rusty",
    "the rotor is smooth",
    "the bearing is worn",
    "the shaft is clean",
    # then verbs, anchored on nouns the previous sentences established
    "the tank pushes water",
    "the motor seals air",
    "the pipe drains water",
    "the rotor spins air",
    "the bearing lifts water",
    "the shaft guides air",
)


LESSONS: Tuple[Tuple[str, str, str], ...] = (
    ("L1_NOUN", "NOUN",
     "A noun names a thing. Teach that a noun is the word that can follow "
     "'the' and be what a sentence is about."),
    ("L2_ADJECTIVE", "ADJECTIVE",
     "An adjective describes a thing. Teach that it is the word that can "
     "follow 'is' or 'are' to say what a thing is like."),
    ("L3_VERB", "VERB",
     "A verb names an action. Teach that it is the word that says what the "
     "thing DOES, and that it is not what the thing IS."),
    ("L4_SUBJECT_VERB", "SUBJECT+VERB",
     "A simple sentence is a noun followed by a verb: the thing and what it "
     "does. Build only on NOUN and VERB."),
    ("L5_SUBJECT_VERB_OBJECT", "SUBJECT+VERB+OBJECT",
     "Some actions are done TO something. A sentence can name the thing "
     "acting, the action, and the thing acted on. Build only on L4."),
    ("L6_PLURAL", "PLURAL",
     "More than one thing. Teach that a noun can name one thing or many, and "
     "that the sentence changes 'is' to 'are' when it names many."),
    ("L7_NEGATION", "NEGATION",
     "Saying a thing is NOT so. Teach that 'not' after 'is' or 'are' reverses "
     "what the sentence claims, and that it changes the claim, not the thing."),
    ("L8_PREPOSITION", "PREPOSITION",
     "Where a thing is. Teach that a word like 'in' or 'on' relates one thing "
     "to another thing, and that both things are nouns."),
    ("L9_CONJUNCTION", "CONJUNCTION",
     "Saying two things at once. Teach that 'and' joins two claims about the "
     "same thing, so the sentence says both of them."),
)


TEACHER_CONTRACT = """You are teaching a cognitive substrate English from the
beginning. It already reads only one sentence shape: "the X is Y", including
"are" and "not". It has NO concept of nouns, verbs or adjectives.

Teach ONE concept at a time, in the order given. Use only words from the
vocabulary you are given. Explain in plain, short sentences a beginner could
follow, then give two contrasting examples and one counterexample.

You must not:
- claim the student has learned anything
- assert that a word IS a noun/verb/adjective as though your saying so settles
  it; give the pattern that shows it instead
- use any word outside the vocabulary you are given
- refer to any held-out word or sentence

State the RULE that separates the class from the others, because a rule can be
tested against sentences and a label cannot.
"""
