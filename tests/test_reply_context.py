"""The turn record the classifier consults: what it remembers, and what it refuses to guess.

Context is deliberately dumb -- it stores turns and answers questions about them. These tests
pin the answers, because every conversational rule in the replier is built on them.
"""

from __future__ import annotations

import pytest

from ttrpg_chatbots.reply.context import DEFAULT_WINDOW, Context, Turn


def _human(text: str, act: str | None = None) -> Turn:
    return Turn("Tav", text, act=act, is_bot=False)


def _bot(text: str, act: str | None = None) -> Turn:
    return Turn("friend-a", text, act=act, is_bot=True)


def test_a_turn_needs_a_speaker() -> None:
    with pytest.raises(ValueError, match="speaker"):
        Turn("   ", "hello")


def test_a_turn_with_no_text_is_still_a_turn() -> None:
    # An image or an emoji is somebody taking a turn, even though it says nothing.
    turn = Turn("Tav", "")

    assert turn.says_nothing is True


def test_the_window_keeps_the_tail_not_the_head() -> None:
    turns = [Turn(f"p{index}", str(index)) for index in range(20)]

    context = Context.of(turns, window=3)

    assert [turn.text for turn in context.turns] == ["17", "18", "19"]
    assert len(context) == 3
    assert bool(Context()) is False


def test_a_window_must_be_at_least_one() -> None:
    with pytest.raises(ValueError, match="window"):
        Context.of([], window=0)


def test_the_default_window_is_the_documented_size() -> None:
    turns = [Turn("p", str(index)) for index in range(DEFAULT_WINDOW + 5)]

    assert len(Context.of(turns)) == DEFAULT_WINDOW


def test_previous_act_comes_from_the_latest_turn_only() -> None:
    # Reaching back past an unclassified remark would describe a conversation that is not
    # the one being answered, so the answer is None instead.
    context = Context((_human("hey", "social:greeting"), _human("look at this", None)))

    assert context.previous_act is None
    assert Context((_human("hey", "social:greeting"),)).previous_act == "social:greeting"


def test_last_speakers_are_found_from_the_end() -> None:
    context = Context(
        (
            _human("hey", "social:greeting"),
            _bot("hey", "social:greeting"),
            _human("thanks", "social:thanks"),
        )
    )

    assert context.last_human is not None and context.last_human.text == "thanks"
    assert context.last_bot is not None and context.last_bot.text == "hey"
    assert context.latest is not None and context.latest.text == "thanks"


def test_bot_spoke_last_is_about_the_newest_turn() -> None:
    after_bot = Context((_human("hey", "social:greeting"), _bot("hey", "social:greeting")))
    after_human = Context((_bot("hey", "social:greeting"), _human("thanks", "social:thanks")))

    assert after_bot.bot_spoke_last() is True
    assert after_human.bot_spoke_last() is False
    assert Context().bot_spoke_last() is False


def test_act_from_bot_needs_the_bot_to_have_spoken_last() -> None:
    assert Context((_bot("hey", "social:greeting"),)).act_from_bot("social:greeting") is True
    # A human's greeting is not the bot having greeted.
    assert Context((_human("hey", "social:greeting"),)).act_from_bot("social:greeting") is False


def test_repeated_ignores_case_and_spacing_but_not_the_bot() -> None:
    context = Context((_human("  Hey   there  ", "social:greeting"),))

    assert context.repeated("hey there") is True
    assert context.repeated("hey there!") is False
    assert context.repeated("") is False
    assert Context((_bot("hey there", "social:greeting"),)).repeated("hey there") is False


def test_acts_and_sequence_skip_turns_without_an_act() -> None:
    context = Context(
        (
            _human("hey", "social:greeting"),
            _human("look", None),
            _bot("hey", "social:greeting"),
            _human("ok", "social:agreement"),
        )
    )

    assert context.acts == ("social:greeting", "social:greeting", "social:agreement")
    assert context.sequence() == "greeting>greeting>agreement"
    assert context.sequence(limit=1) == "agreement"
