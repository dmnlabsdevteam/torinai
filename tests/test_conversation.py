#!/usr/bin/env python3
"""Talking to the substrate: understanding, answering, asking, and telling a
question from a job.

Four claims, each with a way to be wrong:

    UNDERSTANDS   a sentence resolves to things the substrate holds, and a
                  phrase is read as a phrase -- `pressure loss` is one thing,
                  not `pressure` and `loss`
    COMMUNICATES  the reply is assembled out of stored descriptions and
                  relations, never generated, and it answers the QUESTION
                  rather than reciting the concept it was about
    ASKS          where it holds nothing and cannot find anything, it asks --
                  and where a phrase means two things, it asks which
    DISCRIMINATES a question is answered; a job is queued. This is the one that
                  was broken: everything was a job, so `What is a load
                  balancer?` got 84 tools, a 26-iteration budget and 4,680
                  seconds, and created a directory.

What must never happen is answering about something it does not hold. Every
claim below has a negative beside it for exactly that reason.
"""

import os

import pytest

os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")
os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")

from core.agents.autonomous.self_model import Conversation, phrases


@pytest.fixture(scope="module")
def talk():
    return Conversation()


def test_a_phrase_is_read_as_a_phrase():
    """`pressure loss` is one concept and `pressure` is another; reading the
    shorter out of the longer changes the subject."""
    found = [text for _, _, text in phrases(["what", "causes", "pressure", "loss"])]
    assert "pressure_loss" in found
    assert found.index("causes_pressure_loss") < found.index("pressure_loss"), \
        "longest first, so the longest match wins the words"


@pytest.mark.asyncio
async def test_it_understands_a_sentence_as_things_it_holds(talk):
    understanding = await talk.understand("what causes pressure loss")

    assert any(r.phrase == "pressure loss" for r in understanding.known), \
        [r.phrase for r in understanding.resolved]
    held = next(r for r in understanding.known if r.phrase == "pressure loss")
    assert held.description, "a name with nothing behind it is not understanding"
    assert held.domain


@pytest.mark.asyncio
async def test_it_answers_the_question_rather_than_reciting_the_concept(talk):
    understanding = await talk.understand("what causes pressure loss")

    assert understanding.answers, "the question named a relation it holds"
    answer = understanding.answers[0]
    assert answer.about == "pressure loss"
    assert "cause" in answer.relation
    # Every word of the answer came out of the store.
    for other in answer.others:
        assert other in understanding.reply


@pytest.mark.asyncio
async def test_it_asks_when_it_holds_nothing_and_can_find_nothing(talk):
    understanding = await talk.understand("what is a zorblatt manifold")

    assert not understanding.known
    assert not understanding.answered, "asking back is not answering"
    assert understanding.reply.rstrip().endswith("?"), understanding.reply
    assert "zorblatt manifold" in understanding.reply
    # And it must not have invented one.
    assert not any(a.stored for a in understanding.acquired)


@pytest.mark.asyncio
async def test_a_name_with_nothing_behind_it_is_not_an_answer(talk):
    """The store holds 240 bare fragments with no description. Matching one is
    not knowing, and saying `held, with no description` stopped it ever going
    to find out."""
    understanding = await talk.understand("what is a load balancer")

    assert "no description" not in understanding.reply
    assert not any(r.phrase in ("load", "balancer") for r in understanding.known)


@pytest.mark.asyncio
async def test_telling_it_something_is_not_asking_it_something(talk):
    assert talk.is_question("what is a load balancer") is True
    assert talk.is_question("Is pressure loss caused by pipe friction?") is True
    assert talk.is_question("a firewall blocks network traffic") is False
    assert talk.is_question("run a load test against the api") is False


@pytest.mark.asyncio
async def test_it_remembers_what_happened_not_only_what_things_are():
    """The concept store holds what things ARE; memory holds what HAPPENED.
    Answering out of one and not the other is why it could describe a concept
    and not that you had just discussed it."""
    talk = Conversation()
    remembered = await talk.recall("load balancer")
    assert isinstance(remembered, list)
    # Recall must return text, never raw objects a caller has to unpick.
    assert all(isinstance(item, str) for item in remembered)


# ------------------------------------------------------------------ polarity

def test_a_statement_and_its_negation_are_not_the_same_claim():
    """The measurement this exists for: on this system's own embedding model,
    `the vault is locked` and `the vault is not locked` score 0.948, while two
    ways of saying the same thing score 0.484. No threshold separates them, so
    the distinction is read when the memory is written and compared exactly."""
    from core.semantics.claim_shape import read_claim

    locked = read_claim("the vault is locked")
    unlocked = read_claim("the vault is not locked")

    assert locked.polarity == "affirms" and unlocked.polarity == "denies"
    assert locked.agrees_with(unlocked) is False
    assert locked.agrees_with(read_claim("the safe is secured")) is True


def test_tense_is_part_of_the_claim():
    from core.semantics.claim_shape import read_claim

    assert read_claim("the vault was locked").tense == "past"
    assert read_claim("the vault is locked").tense == "present"
    assert read_claim("the vault wasn't locked").polarity == "denies"


def test_a_question_makes_no_claim():
    """`what is a load balancer` read as an affirmative claim about load
    balancers, so every question filed in memory carried a polarity nothing
    asserted."""
    from core.semantics.claim_shape import read_claim

    assert not read_claim("what is a load balancer").known
    assert not read_claim("is the vault locked?").known
    # And an unreadable claim agrees with nothing rather than agreeing weakly.
    assert read_claim("the vault is locked").agrees_with(
        read_claim("what is a load balancer")) is None


def test_a_change_over_time_is_not_placed_in_one_tense():
    from core.semantics.claim_shape import read_claim

    both = read_claim("it was locked and is now open")
    assert both.tense is None, "a described change belongs to neither tense"


def test_a_question_about_the_conversation_is_answered_from_the_conversation():
    """`What did I just ask you about?` was parsed as a question about a thing
    called `just ask`, researched on Wikipedia, and answered with an article on
    the rhetorical tactic of asking questions -- because nothing owned
    questions about the exchange itself, so they fell through to the owner of
    unrecognised phrases."""
    import asyncio

    from core.agents.autonomous.self_model import Conversation, Turn

    talk = Conversation()
    assert talk.about_this_conversation("What did I just ask you about?") == ("them", "asked")
    assert talk.about_this_conversation("What were we talking about?") == ("both", "discussed")
    assert talk.about_this_conversation("What did you say?") == ("me", "said")
    # A question about the world is not one of these, however many people it
    # mentions: there is no speech verb with a participant in front of it.
    assert talk.about_this_conversation("What is a load balancer?") is None
    assert talk.about_this_conversation("Who asked the first question in history?") is None

    # Answered from the record, with no lookup and no store access at all.
    talk._turns = [Turn(said="What causes pressure loss?", asked=True,
                        subject="pressure loss", reply="minor losses")]
    reply = asyncio.run(talk.understand("What did I just ask you about?")).reply
    assert "pressure loss" in reply and "What causes pressure loss?" in reply


def test_nothing_said_yet_is_reported_rather_than_invented():
    import asyncio

    from core.agents.autonomous.self_model import Conversation

    reply = asyncio.run(Conversation().understand("What did I just ask you about?")).reply
    assert "Nothing yet" in reply


def test_asking_about_the_conversation_does_not_become_the_subject():
    """Asking what we were talking about is a question ABOUT the subject, not
    a new one -- letting it replace the subject strands everything recall has
    accumulated under the topic still being discussed."""
    import asyncio

    from core.agents.autonomous.self_model import Conversation, Turn

    talk = Conversation()
    talk._last_subject = "pressure loss"
    talk._turns = [Turn(said="What causes pressure loss?", asked=True,
                        subject="pressure loss", reply="minor losses")]
    asyncio.run(talk.understand("What were we talking about?"))
    assert talk._last_subject == "pressure loss"


def test_research_that_does_not_name_the_phrase_is_refused():
    """A search engine always returns its best row. Taking it unchecked stored
    an article on animal sexual behaviour as the meaning of `spots unusual
    behaviour`, and a wrong fact written into the store is indistinguishable
    afterwards from one that was learned."""
    from core.agents.autonomous.self_model import _titles

    assert _titles("load_balancer", "Load balancing (computing)")
    assert _titles("anomaly_detection", "Anomaly detection")
    assert not _titles("spots_unusual_behaviour", "Animal sexual behaviour"), (
        "sharing one word with the title is not being about the phrase"
    )
    assert not _titles("", "Anything")
