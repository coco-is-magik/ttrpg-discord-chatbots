"""The layer below the message: parts, packaging, pacing, and assembling a split thought.

Every test here is about *shape* rather than wording, which is the point of the layer: measured from the
first dataset, 260 messages arrived in exactly one package each, so the packaging never varied even when
every word was new.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from ttrpg_chatbots.conv.parts import Delivery, Part, Turn
from ttrpg_chatbots.deliver.pace import total_seconds, typing_seconds, waits
from ttrpg_chatbots.deliver.split import package
from ttrpg_chatbots.parts import read
from ttrpg_chatbots.perceive.assembly import Assembler


# --- parts, derived -------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text, kinds",
    [
        ("Messing with the tank", ("content",)),
        ("ah, oh", ("reaction",)),
        ("Messing with the tank. how is otis doing?", ("content", "question")),
        ("oh nice ^^. how is it going?", ("reaction", "question")),
        ("half watching an old series", ("content",)),
        ("i have four on the windowsill. anyway", ("content", "aside")),
        ("*the garage, not the shed", ("correction",)),
    ],
)
def test_parts_are_read_out_of_the_text(text, kinds):
    assert tuple(part.kind for part in read(text)) == kinds


def test_an_emoji_or_a_kaomoji_is_its_own_kind():
    assert read("🐠")[0].kind == "emoji"
    assert read("(＾▽＾)")[0].kind == "emoji"
    assert read("^^")[0].kind == "emoji"


def test_reading_parts_never_loses_a_word():
    """The parts are the same sentence, cut up. A split that drops a word is a bug."""
    for text in (
        "Messing with the tank. how is otis doing?",
        "oh nice ^^. how is it going?",
        "i have four on the windowsill. anyway",
        "th- this is the train",
    ):
        parts = read(text)
        assert " ".join(part.text for part in parts).split() == text.split()


def test_a_part_must_say_something():
    with pytest.raises(ValueError):
        Part(kind="content", text="   ")
    with pytest.raises(ValueError):
        Part(kind="nonsense", text="hello")


def test_a_turn_needs_at_least_one_part():
    with pytest.raises(ValueError):
        Turn(parts=())
    with pytest.raises(TypeError):
        Turn(parts=("a string is not a part",))


def test_a_turn_reads_as_its_whole_text():
    turn = Turn(parts=read("Messing with the tank. how is otis doing?"))
    assert turn.text == "Messing with the tank. how is otis doing?"
    assert turn.words == 8


# --- packaging ------------------------------------------------------------------------------


def test_one_part_is_one_message():
    assert package(Turn(parts=read("Messing with the tank"))) == ("Messing with the tank",)


def test_a_reaction_and_the_substance_arrive_separately():
    messages = package(Turn(parts=read("oh nice ^^. how is it going?")))
    assert len(messages) == 2
    assert messages[0].startswith("oh nice")
    assert messages[1] == "how is it going?"


def test_a_hand_back_arrives_on_its_own():
    messages = package(Turn(parts=read("Messing with the tank. how is otis doing?")))
    assert messages == ("Messing with the tank.", "how is otis doing?")


def test_splitting_can_be_switched_off():
    """False is exactly the behaviour before parts existed, which is what makes the change safe."""
    turn = Turn(parts=read("Messing with the tank. how is otis doing?"))
    assert package(turn, delivery=Delivery(split=False)) == (turn.text,)


def test_the_number_of_messages_is_capped_without_losing_words():
    turn = Turn(parts=read("oh nice. Messing with the tank. how is otis doing?"))
    messages = package(turn, delivery=Delivery(max_messages=2))
    assert len(messages) == 2
    assert " ".join(messages).split() == turn.text.split()


def test_an_emoji_alone_is_a_message_but_not_when_it_is_the_whole_turn():
    assert package(Turn(parts=(Part(kind="emoji", text="🐠"),))) == ("🐠",)
    turn = Turn(parts=(Part(kind="content", text="half watching a series"), Part(kind="emoji", text="🐠")))
    assert package(turn) == ("half watching a series", "🐠")


def test_an_aside_goes_last():
    turn = Turn(parts=(Part(kind="aside", text="wait"), Part(kind="content", text="i found it")))
    assert package(turn) == ("i found it", "wait")


def test_packaging_never_produces_an_empty_message():
    for text in ("ah, oh", "🐠", "Mm, i hear you honey", "oh, i do not know that one"):
        messages = package(Turn(parts=read(text)))
        assert messages
        assert all(message.strip() for message in messages)


def test_a_nonsense_cap_is_refused():
    with pytest.raises(ValueError):
        package(Turn(parts=read("oh nice. how are you?")), delivery=Delivery(max_messages=0))


# --- pacing ----------------------------------------------------------------------------------


def test_the_first_wait_is_typing_and_later_ones_add_the_pause():
    messages = ("half watching a series", "how is it going?")
    gaps = waits(messages, delivery=Delivery(pause=2.0))
    assert len(gaps) == 2
    assert gaps[0] == pytest.approx(typing_seconds(messages[0]))
    assert gaps[1] > gaps[0]
    assert gaps[1] == pytest.approx(2.0 + typing_seconds(messages[1]))


def test_typing_time_is_bounded_at_both_ends():
    assert typing_seconds("hi") >= 0.8
    assert typing_seconds("word " * 200) <= 12.0


def test_a_slow_typist_takes_longer():
    assert typing_seconds("half watching a series", wpm=45) > typing_seconds(
        "half watching a series", wpm=75
    )


def test_no_typing_indicator_means_no_wait():
    assert waits(("morning",), delivery=Delivery(show_typing=False)) == (0.0,)


def test_a_turn_takes_longer_than_any_single_message():
    messages = ("half watching a series", "how is it going?")
    assert total_seconds(messages) > max(waits(messages))


def test_a_nonsense_speed_is_refused():
    with pytest.raises(ValueError):
        typing_seconds("hello", wpm=0)


# --- assembling a human's split thought -------------------------------------------------------


def test_a_thought_split_across_three_messages_is_one_turn():
    start = datetime(2026, 10, 24, 20, 0)
    assembler = Assembler()
    for index, text in enumerate(("i have been thinking", "about the garage", "the whole thing is rotten")):
        assert assembler.feed(text, start + timedelta(seconds=index * 3)) == ()
    assert assembler.flush(start + timedelta(seconds=7)) == ()
    turn = assembler.flush(start + timedelta(seconds=30))
    assert turn == ("i have been thinking about the garage the whole thing is rotten",)


def test_a_message_after_a_pause_finishes_the_previous_thought():
    start = datetime(2026, 10, 24, 20, 0)
    assembler = Assembler()
    assembler.feed("the garage is rotten", start)
    finished = assembler.feed("anyway how are you", start + timedelta(seconds=40))
    assert finished == ("the garage is rotten",)
    assert assembler.pending == ("anyway how are you",)


def test_a_short_message_stretches_the_window():
    """"about the garage" is not a whole thought, so it waits twice as long for the rest of it."""
    start = datetime(2026, 10, 24, 20, 0)
    longer = Assembler()
    longer.feed("i have been thinking about it", start)
    assert longer.flush(start + timedelta(seconds=8)) == ("i have been thinking about it",)

    short = Assembler()
    short.feed("about the garage", start)
    assert short.flush(start + timedelta(seconds=8)) == ()
    assert short.flush(start + timedelta(seconds=14)) == ("about the garage",)


def test_an_empty_message_is_not_a_turn():
    assembler = Assembler()
    assert assembler.feed("   ", datetime(2026, 10, 24, 20, 0)) == ()
    assert assembler.pending == ()


def test_a_nonsense_window_is_refused():
    with pytest.raises(ValueError):
        Assembler(window=0)


# --- stumbles ---------------------------------------------------------------------------------


def test_a_word_that_starts_with_the_fragment_is_not_false_started():
    """Measured live: "re- rearranging" was in the channel and reads as a typo, not hesitation."""
    from ttrpg_chatbots.reply.style import _introduce_stutter

    assert _introduce_stutter("rearranging my shelf") == "rearranging my shelf"
    assert _introduce_stutter("unfinished business") == "unfinished business"
    assert _introduce_stutter("inside the tank") == "inside the tank"


def test_an_ordinary_word_still_stutters():
    from ttrpg_chatbots.reply.style import _introduce_stutter

    assert _introduce_stutter("think it is late") == "th- think it is late"
    assert _introduce_stutter("hi") == "h- hi"
    assert _introduce_stutter("i think so") == "i- i think so"
    assert _introduce_stutter("watching the trains") == "wa- watching the trains"
