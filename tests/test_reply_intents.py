"""The social-intent lexicon: what it catches, and what it must leave alone."""

from __future__ import annotations

import pytest

from ttrpg_chatbots.reply.intents import (
    SOCIAL_HOWAREYOU,
    SOCIAL_REFUSAL,
    SOCIAL_TAGS,
    SOCIAL_THANKS,
    match_intent,
)


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


class TestAskingHowHeIs:
    """The wellbeing question in the clothes people actually use for it.

    Measured live: "anyway how is your day going" was answered with "oh, i do not know that one",
    because every pattern for this move had the word "you" in it. These are the phrasings a person
    uses without thinking about it, and all of them are the same move.
    """

    @pytest.mark.parametrize(
        "message",
        [
            "how are you?",
            "how are you doing",
            "how you doing",
            "how have you been",
            "how you been",
            "how's it going",
            "how are things",
            "how is your day going",
            "anyway how is your day going",
            "how was your day?",
            "how's your day been",
            "how was your weekend",
            "how has your week been",
            "how are you holding up",
        ],
    )
    def test_it_is_the_same_move(self, message: str) -> None:
        assert match_intent(message) == SOCIAL_HOWAREYOU, message

    @pytest.mark.parametrize(
        "message",
        [
            "how is the fence coming along",
            "how was the game",
            "how do you make bread",
            "what is your day rate",
        ],
    )
    def test_but_not_everything_with_how_in_it(self, message: str) -> None:
        """A question about a *thing* is not a question about him: the fence, the game, the bread."""
        assert match_intent(message) != SOCIAL_HOWAREYOU, message


class TestSayingNo:
    """A refusal is its own move, and it sits above thanks.

    Measured: "no thanks" matched the thanks pattern, so it was answered as politeness ("no worries")
    -- the opposite of what was said. And the job that carries a refusal, `decline`, was in the
    vocabulary with no book behind it and no way to be chosen.
    """

    @pytest.mark.parametrize(
        "message",
        [
            "no thanks",
            "no thank you",
            "nah thanks",
            "no ta",
            "i would rather not",
            "rather not",
            "not today",
            "not right now",
            "i am not up for that",
            "i do not want to talk about it",
            "i don't want to get into it",
            "not really my thing",
        ],
    )
    def test_it_is_a_refusal(self, message: str) -> None:
        assert match_intent(message) == SOCIAL_REFUSAL, message

    def test_it_is_not_thanks(self) -> None:
        assert match_intent("no thanks") != SOCIAL_THANKS
        assert match_intent("thanks") == SOCIAL_THANKS

    @pytest.mark.parametrize("message", ["no", "no way", "not much", "nothing much"])
    def test_but_a_bare_no_is_not(self, message: str) -> None:
        """A bare \"no\" answers a question and could mean several things; only an explicit refusal is
        one, because the reply to a refusal is \"fair enough\" and the reply to a bare no is not."""
        assert match_intent(message) != SOCIAL_REFUSAL, message
