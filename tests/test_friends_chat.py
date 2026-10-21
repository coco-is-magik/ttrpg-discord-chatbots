"""The friends' classifier: social moves answer, everything else is refused honestly."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ttrpg_chatbots.bots.chat import ChatError, FriendChat
from ttrpg_chatbots.reply.context import Context, Turn

DATA = Path("examples/friends_world")


def _chat(**kwargs) -> FriendChat:
    return FriendChat(DATA, **kwargs)


def test_the_dataset_covers_every_friend() -> None:
    assert _chat().friends() == ("friend-a", "friend-b", "friend-c")


def test_a_greeting_is_a_social_reply() -> None:
    answer = _chat().reply("hello there", "friend-a", speaker="Tav")

    assert answer.source == "reply:friend-a"
    assert answer.detail["tag"] == "social:greeting"
    assert answer.detail["known"] is True
    # A social move has no fact behind it; the template is the whole answer.
    assert answer.detail["knowledge_id"] is None
    assert answer.text.strip()


def test_a_lore_question_deflects_because_friends_know_only_social_things() -> None:
    answer = _chat().reply("what is the sunken crown?", "friend-a")

    assert answer.detail["known"] is False
    assert answer.detail["tag"] is None


def test_a_repeated_greeting_does_not_repeat_the_line() -> None:
    chat = _chat()
    first = chat.reply("hey", "friend-a").text
    second = chat.reply("hey", "friend-a").text

    assert first != second


def test_rotation_can_be_switched_off_for_replays() -> None:
    chat = _chat(rotate=False)
    assert chat.reply("hey", "friend-a").text == chat.reply("hey", "friend-a").text


def test_one_friends_rotation_does_not_affect_another() -> None:
    used = _chat()
    used.reply("hey", "friend-a")
    used.reply("hey", "friend-a")
    fresh = _chat()

    assert used.reply("hey", "friend-b").text == fresh.reply("hey", "friend-b").text


def test_an_unknown_friend_is_refused() -> None:
    with pytest.raises(ChatError, match="unknown character"):
        _chat().reply("hey", "nobody")


def test_empty_text_is_refused() -> None:
    with pytest.raises(ChatError, match="empty"):
        _chat().reply("   ", "friend-a")


def test_a_missing_dataset_names_the_path(tmp_path) -> None:
    chat = FriendChat(tmp_path / "absent")
    with pytest.raises(ChatError, match="absent"):
        chat.reply("hey", "friend-a")


# --- context: what the room said a moment ago ---------------------------------------------------


def _after_bot(act: str) -> Context:
    """A context whose newest turn is the friend's own, with that act."""
    return Context(
        (
            Turn("Tav", "earlier", act="social:smalltalk", is_bot=False),
            Turn("friend-a", "said this", act=act, is_bot=True),
        )
    )


def test_the_dataset_ships_an_authored_table() -> None:
    table = _chat().transitions

    assert table is not None
    assert table.source == "authored"
    assert "social:greeting" in table.acts


def test_a_local_table_can_override_the_shipped_one(tmp_path, monkeypatch) -> None:
    local = tmp_path / "measured.json"
    local.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "source": "switchboard",
                "counts": {"social:greeting": {"social:greeting": 2}},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("TTRPG_FRIENDS_TRANSITIONS", str(local))

    table = _chat().transitions

    assert table is not None
    assert table.source == "switchboard"


def test_an_explicit_path_beats_the_environment(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("TTRPG_FRIENDS_TRANSITIONS", str(tmp_path / "from-env.json"))

    chat = FriendChat(DATA, transitions=tmp_path / "absent.json")

    # The explicit path is honoured even though it does not exist, so the table is absent.
    assert chat.transitions is None


def test_a_missing_table_means_context_changes_nothing(tmp_path) -> None:
    without = FriendChat(DATA, transitions=tmp_path / "absent.json")
    after_goodbye = Context((Turn("Tav", "night", act="social:goodbye", is_bot=False),))

    answer = without.reply("hey anyone around?", "friend-a", context=after_goodbye)

    # Priority order alone still answers a presence question as a presence question.
    assert answer.detail["tag"] == "social:presence"


def test_the_table_vetoes_a_reading_that_cannot_follow(tmp_path) -> None:
    # Nothing in the table follows a goodbye with a presence question, so the greeting
    # reading wins even though priority would have picked presence.
    after_goodbye = Context((Turn("Tav", "night", act="social:goodbye", is_bot=False),))

    answer = _chat().reply("hey anyone around?", "friend-a", context=after_goodbye)

    assert answer.detail["tag"] == "social:greeting"
    assert answer.detail["after"] == "social:goodbye"
    assert answer.detail["candidates"] == ["social:presence", "social:greeting"]


def test_a_mention_is_answered_even_when_the_friend_just_spoke() -> None:
    chat = _chat()

    answer = chat.reply(
        "hey", "friend-a", context=_after_bot("social:greeting"), addressed=True
    )

    assert answer is not None


def test_an_unaddressed_repeat_is_left_alone() -> None:
    context = Context(
        (
            Turn("Tav", "hey", act="social:greeting", is_bot=False),
            Turn("friend-a", "Hey.", act="social:greeting", is_bot=True),
        )
    )

    answer = _chat().reply("hey", "friend-a", context=context, addressed=False)

    # Said twice, aimed at nobody: answering again would be noise.
    assert answer is None


def test_an_unaddressed_greeting_after_our_own_is_left_alone() -> None:
    answer = _chat().reply(
        "hello there", "friend-a", context=_after_bot("social:greeting"), addressed=False
    )

    assert answer is None


def test_an_unaddressed_new_move_is_answered() -> None:
    answered = _chat().reply(
        "thanks", "friend-a", context=_after_bot("social:greeting"), addressed=False
    )

    assert answered is not None
    assert answered.detail["tag"] == "social:thanks"
