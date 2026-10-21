"""The social-intent lexicon: what it catches, and what it must leave alone."""

from __future__ import annotations

import pytest

from ttrpg_chatbots.reply.intents import SOCIAL_TAGS, match_intent


@pytest.mark.parametrize(
    ("text", "tag"),
    [
        ("hey", "social:greeting"),
        ("Hello there", "social:greeting"),
        ("good morning", "social:greeting"),
        ("anyone around tonight?", "social:presence"),
        ("are you around?", "social:presence"),
        ("thanks!", "social:thanks"),
        ("thank you", "social:thanks"),
        ("see you later", "social:goodbye"),
        ("good night", "social:goodbye"),
        ("how are you?", "social:howareyou"),
        ("how's it going", "social:howareyou"),
        ("sorry about that", "social:apology"),
        ("sounds good", "social:agreement"),
        ("what's up?", "social:smalltalk"),
    ],
)
def test_social_moves_are_recognised(text: str, tag: str) -> None:
    assert match_intent(text) == tag


@pytest.mark.parametrize(
    "text",
    [
        "what is the sunken crown?",
        "tell me about the guild",
        "how deep is the quay?",
        "what happened at greyfall?",
        "when is the turning tide rite spoken?",
        "roll stealth",
        "",
        "   ",
        # A closing is a whole message. These are questions that happen to contain a word a
        # closing uses, and answering them with a farewell ends the conversation by accident.
        "is the game on later?",
    ],
)
def test_questions_and_commands_are_not_social_moves(text: str) -> None:
    """The lexicon must not steal a real question; that is what the fact classifier is for."""
    assert match_intent(text) is None


@pytest.mark.parametrize(
    ("text", "tag"),
    [
        ("later", "social:goodbye"),
        ("ok later", "social:goodbye"),
        ("alright, night", "social:goodbye"),
        ("night bud", "social:goodbye"),
        ("doing anything later?", "social:plans"),
        ("got plans tonight?", "social:plans"),
        ("what are you doing tonight?", "social:plans"),
        ("any plans later tonight?", "social:plans"),
    ],
)
def test_a_closing_is_recognised_only_when_it_leads(text: str, tag: str) -> None:
    assert match_intent(text) == tag


def test_presence_beats_greeting_when_a_message_has_both() -> None:
    assert match_intent("hey, anyone around tonight?") == "social:presence"


def test_good_night_is_a_goodbye_not_a_greeting() -> None:
    assert match_intent("good night") == "social:goodbye"


def test_the_tag_list_has_no_duplicates() -> None:
    assert len(set(SOCIAL_TAGS)) == len(SOCIAL_TAGS)
