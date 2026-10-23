"""Is this about something he knows?

The last thing that used to be the old classifier's job, and the tests are the two measurements that
made it necessary: naming beats phrasing, and a distance ceiling applied *after* a name is found
refuses the very messages it was supposed to accept.
"""

from __future__ import annotations

from pathlib import Path

from ttrpg_chatbots.decide.subject import choose
from ttrpg_chatbots.reply.datasets import load_world
from ttrpg_chatbots.reply.entities import EntityIndex

WORLD = Path("examples/friends_world")


def _world():
    return load_world(WORLD)


def _subject(text: str, character: str | None = "friend-a"):
    world = _world()
    return choose(
        text=text,
        index=EntityIndex(world.knowledge),
        knowledge=world.knowledge,
        character=world.character(character) if character else None,
    )


def test_a_name_is_enough_even_when_the_phrasing_is_odd() -> None:
    # Measured before this module existed: "howre the rangers doing?" scored 0.651 against its own
    # fact and 0.714 against an unrelated one, so no ceiling could separate them. The word "rangers"
    # was right there.
    found = _subject("howre the rangers doing?")

    assert found is not None
    assert found.tag == "topic:rangers"
    assert "rangers" in found.text.lower()


def test_a_subject_he_knows_answers_with_a_stance_not_a_recital() -> None:
    found = _subject("do you like hockey?")

    assert found is not None
    assert found.is_stance
    assert "hockey" in found.text.lower()


def test_a_subject_nobody_named_is_nothing() -> None:
    assert _subject("what is the plot of dune?") is None


def test_an_ordinary_message_names_nothing() -> None:
    assert _subject("i am nervous about tomorrow") is None
    assert _subject("rough day at work") is None


def test_a_character_only_speaks_about_what_it_knows() -> None:
    # friend-b is deliberately neutral: the same question, a different character, no answer.
    assert _subject("do you like hockey?", character="friend-b") is None


def test_the_closest_fact_in_the_subject_wins() -> None:
    best = _subject("do you follow the rangers?")
    other = _subject("what about the rangers?")

    assert best is not None and other is not None
    assert best.item_id != other.item_id, "two phrasings should reach two different facts"


def test_a_friend_does_not_answer_with_another_friends_line() -> None:
    """Two friends can hold the same subject tag without sharing a mouth.

    `topic:computers` is one tag and both friends know it, so before lines were owned, whichever line
    scored closest got spoken -- by either of them. Otto's line about taking a computer apart is not
    Terry's answer about machines that phone home.
    """
    world = _world()
    index = EntityIndex(world.knowledge)

    terry = choose(
        text="do you like computers?",
        index=index,
        knowledge=world.knowledge,
        character=world.character("friend-a"),
    )
    otto = choose(
        text="do you like computers?",
        index=index,
        knowledge=world.knowledge,
        character=world.character("friend-b"),
    )

    assert terry is not None and otto is not None
    assert terry.item_id != otto.item_id
    assert "machine" in terry.text or "phone" in terry.text, terry.text
    assert "apart" in otto.text, otto.text


def test_a_shared_line_is_answerable_by_anyone_who_knows_the_tag() -> None:
    from ttrpg_chatbots.reply.types import KnowledgeItem

    shared = KnowledgeItem(id="k-x", text="Hey there.", tags=frozenset({"social:greeting"}))

    assert shared.owned_by("friend-a") and shared.owned_by("friend-b")
    assert shared.owned_by(None), "no character means the world dataset, which is everybody's"


def test_a_line_owned_by_one_friend_is_not_offered_to_another() -> None:
    from ttrpg_chatbots.reply.types import KnowledgeItem

    mine = KnowledgeItem(
        id="k-y", text="Do you like trains?", tags=frozenset({"topic:trains"}), character="friend-b"
    )

    assert mine.owned_by("friend-b")
    assert not mine.owned_by("friend-a")


def test_a_positive_message_does_not_get_his_sympathy_line() -> None:
    """Polarity picks between the items of one subject.

    Measured live: "i was thinking of getting a plant for my desk" is good news, and the closest item
    by distance was the sympathy line ("oh no, i am sorry") because both mention a plant and "my".
    """
    world = _world()
    index = EntityIndex(world.knowledge)

    happy = choose(
        text="i was thinking of getting a plant for my desk",
        index=index,
        knowledge=world.knowledge,
        character=world.character("friend-b"),
        polarity="positive",
    )
    sad = choose(
        text="my plant is dying",
        index=index,
        knowledge=world.knowledge,
        character=world.character("friend-b"),
        polarity="negative",
    )

    assert happy is not None and sad is not None
    assert "sorry" not in happy.text.lower(), happy.text
    assert happy.item_id != sad.item_id


def test_a_carried_subject_is_only_used_when_there_is_one() -> None:
    world = _world()
    index = EntityIndex(world.knowledge)

    nothing_named = choose(
        text="do you think i should try again",
        index=index,
        knowledge=world.knowledge,
        character=world.character("friend-b"),
    )
    carried = choose(
        text="do you think i should try again",
        index=index,
        knowledge=world.knowledge,
        character=world.character("friend-b"),
        carried="topic:plants",
    )

    assert nothing_named is None, "with no carried subject and nothing named, there is nothing to say"
    assert carried is not None and carried.tag == "topic:plants"


def test_a_carried_subject_still_respects_what_he_may_know() -> None:
    world = _world()
    index = EntityIndex(world.knowledge)

    # Terry does not know about trains; carrying one at him must not teach him.
    assert (
        choose(
            text="what about it",
            index=index,
            knowledge=world.knowledge,
            character=world.character("friend-a"),
            carried="topic:trains",
        )
        is None
    )


def test_a_generic_slot_word_is_not_a_name() -> None:
    """Slot values are searched as whole words, so a common one is a trap.

    Measured: "my last one died" named topic:terry-davis, because one of his items had the slot
    value "how he died". The name beat the carried subject, and the answer to a plant that had just
    died was "oh".
    """
    world = _world()
    index = EntityIndex(world.knowledge)

    assert index.tags_for("my last one died") == frozenset()
    assert index.tags_for("a cup of tea") == frozenset()


def test_a_name_he_cannot_answer_falls_back_to_the_conversation() -> None:
    """A subject he does not know is not a reason to forget what was being talked about."""
    world = _world()
    index = EntityIndex(world.knowledge)

    # Terry knows nothing about trains; the carried subject still answers.
    found = choose(
        text="the trains were late again",
        index=index,
        knowledge=world.knowledge,
        character=world.character("friend-a"),
        carried="topic:rangers",
    )

    assert found is not None
    assert found.tag == "topic:rangers", found.tag
