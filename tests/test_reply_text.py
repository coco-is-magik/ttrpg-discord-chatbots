"""How texting variants become words the lexicon knows.

This is the layer that turns one class of miss into one fix: on 2026-10-21, "yoooo", "heyo whats
good" and "whats cookin good lookin" all fell through to a refusal, because every pattern was
written for careful English.
"""

from __future__ import annotations

import pytest

from ttrpg_chatbots.reply.text import normalise_typing


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("yoooo", "yo"),
        ("heyyy there", "hey there"),
        ("sooo good", "so good"),
        ("whats up", "what's up"),
        ("whos that", "who's that"),
        ("im fine", "i'm fine"),
        ("dont worry", "don't worry"),
        ("howre you", "how are you"),
        ("whatre you doing", "what are you doing"),
        ("u up", "you up"),
        ("ur car", "your car"),
        ("sup", "what's up"),
    ],
)
def test_typing_variants_are_normalised(text: str, expected: str) -> None:
    assert normalise_typing(text) == expected


def test_ordinary_words_are_left_alone() -> None:
    # The normaliser must not "fix" words that are already words.
    assert normalise_typing("him and her were here") == "him and her were here"


def test_punctuation_and_mentions_survive() -> None:
    assert normalise_typing("<@123> hey!! whats up?") == "<@123> hey!! what's up?"


def test_empty_input_is_empty() -> None:
    assert normalise_typing("") == ""
    assert normalise_typing("   ") == ""
