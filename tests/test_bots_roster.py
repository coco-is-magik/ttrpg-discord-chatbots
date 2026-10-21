"""The roster: who is configured, and which of them can actually start."""

from __future__ import annotations

import json

import pytest

from ttrpg_chatbots.bots.identity import BotSpec, BotSpecError
from ttrpg_chatbots.bots.roster import (
    Roster,
    RosterError,
    default_roster,
    load_roster,
    resolve_token,
)


def _write(path, bots) -> None:
    path.write_text(json.dumps({"bots": bots}), encoding="utf-8")


def test_default_roster_is_the_single_helper() -> None:
    roster = default_roster()
    assert [bot.id for bot in roster] == ["ttrpg-bot"]
    helper = roster.helper
    assert helper is not None
    assert helper.role == "helper"
    assert helper.commands is True
    assert helper.listen is False
    assert roster.friends == ()


def test_a_missing_file_is_the_default_not_an_error(tmp_path) -> None:
    assert load_roster(tmp_path / "absent.json").bots == default_roster().bots


def test_the_roster_reads_a_helper_and_three_friends(tmp_path) -> None:
    _write(
        tmp_path / "bots.json",
        [
            {"id": "ttrpg-bot", "role": "helper"},
            {"id": "friend-a", "role": "friend"},
            {"id": "friend-b", "role": "friend"},
            {"id": "friend-c", "role": "friend"},
        ],
    )
    roster = load_roster(tmp_path / "bots.json")
    assert [bot.id for bot in roster.helpers] == ["ttrpg-bot"]
    assert [bot.id for bot in roster.friends] == ["friend-a", "friend-b", "friend-c"]


def test_the_helper_keeps_the_existing_token_variable() -> None:
    assert default_roster().helper.token_var == "DISCORD_TOKEN"


def test_a_friend_derives_its_token_variable() -> None:
    friend = BotSpec(id="friend-a", role="friend")
    assert friend.token_var == "TTRPG_FRIEND_A_TOKEN"
    assert friend.token_file_var == "TTRPG_FRIEND_A_TOKEN_FILE"


def test_a_friend_without_a_token_is_dormant(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("TTRPG_FRIEND_A_TOKEN", raising=False)
    monkeypatch.delenv("TTRPG_FRIEND_A_TOKEN_FILE", raising=False)
    _write(
        tmp_path / "bots.json",
        [{"id": "ttrpg-bot", "role": "helper"}, {"id": "friend-a", "role": "friend"}],
    )
    roster = load_roster(tmp_path / "bots.json")
    friend = roster.get("friend-a")
    assert friend is not None
    assert roster.token_for(friend) is None
    assert "dormant" in roster.describe()[1]


def test_a_token_file_wins_over_the_plain_variable(tmp_path) -> None:
    secret = tmp_path / "friend.token"
    secret.write_text("from-a-file\n", encoding="utf-8")
    friend = BotSpec(id="friend-a", role="friend")
    token = resolve_token(
        friend,
        env={
            "TTRPG_FRIEND_A_TOKEN": "from-the-environment",
            "TTRPG_FRIEND_A_TOKEN_FILE": str(secret),
        },
    )
    assert token == "from-a-file"


def test_a_token_with_whitespace_is_refused() -> None:
    friend = BotSpec(id="friend-a", role="friend")
    with pytest.raises(RosterError, match="whitespace"):
        resolve_token(friend, env={"TTRPG_FRIEND_A_TOKEN": "two tokens here"})


def test_an_unreadable_token_file_names_the_bot(tmp_path) -> None:
    friend = BotSpec(id="friend-a", role="friend")
    with pytest.raises(RosterError, match="friend-a"):
        resolve_token(
            friend,
            env={"TTRPG_FRIEND_A_TOKEN_FILE": str(tmp_path / "missing.txt")},
        )


def test_two_helpers_are_refused(tmp_path) -> None:
    _write(
        tmp_path / "bots.json",
        [{"id": "ttrpg-bot", "role": "helper"}, {"id": "other", "role": "helper"}],
    )
    with pytest.raises(RosterError, match="more than one helper"):
        load_roster(tmp_path / "bots.json")


def test_a_bad_role_names_the_bot(tmp_path) -> None:
    _write(tmp_path / "bots.json", [{"id": "friend-a", "role": "narrator"}])
    with pytest.raises(RosterError, match="friend-a"):
        load_roster(tmp_path / "bots.json")


def test_the_helper_may_not_listen() -> None:
    with pytest.raises(BotSpecError, match="does not listen"):
        BotSpec(id="ttrpg-bot", role="helper", listen=True)


def test_a_friend_may_not_own_commands() -> None:
    with pytest.raises(BotSpecError, match="no commands"):
        BotSpec(id="friend-a", role="friend", commands=True)


def test_an_empty_roster_file_is_an_error(tmp_path) -> None:
    _write(tmp_path / "bots.json", [])
    with pytest.raises(RosterError, match="no bots"):
        load_roster(tmp_path / "bots.json")


def test_a_duplicate_id_is_refused(tmp_path) -> None:
    _write(
        tmp_path / "bots.json",
        [{"id": "friend-a", "role": "friend"}, {"id": "friend-a", "role": "friend"}],
    )
    with pytest.raises(RosterError, match="duplicate"):
        load_roster(tmp_path / "bots.json")


def test_a_direct_roster_with_two_helpers_is_refused() -> None:
    with pytest.raises(RosterError):
        Roster(
            (
                BotSpec(id="one", role="helper"),
                BotSpec(id="two", role="helper"),
            )
        )
