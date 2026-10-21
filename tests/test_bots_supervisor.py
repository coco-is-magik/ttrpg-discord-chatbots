"""The supervisor: who starts, who is dormant, and one failure does not sink the rest."""

from __future__ import annotations

import asyncio
import logging

import discord
import pytest

from ttrpg_chatbots.bots.identity import ROLE_FRIEND, BotSpec
from ttrpg_chatbots.bots.permissions import requirements_for
from ttrpg_chatbots.bots.roster import Roster, RosterError
from ttrpg_chatbots.bots.supervisor import (
    Entry,
    FriendBot,
    _run_all,
    build_entries,
    explain_failure,
    run,
)


class _Client:
    """A stand-in for a Discord client: records what would have happened."""

    def __init__(self, *, fail: BaseException | None = None) -> None:
        self.started: str | None = None
        self.closed = False
        self.runs: list[tuple[str, dict]] = []
        self.fail = fail

    async def start(self, token: str) -> None:
        if self.fail is not None:
            raise self.fail
        self.started = token

    async def close(self) -> None:
        self.closed = True

    def run(self, token: str, **kwargs) -> None:
        self.runs.append((token, kwargs))


def _helper() -> BotSpec:
    return BotSpec(id="ttrpg-bot", role="helper", commands=True)


def _friend(name: str = "friend-a", *, listen: bool = True) -> BotSpec:
    return BotSpec(id=name, role="friend", listen=listen)


def _roster(*bots: BotSpec) -> Roster:
    return Roster(tuple(bots))


def test_a_dormant_friend_is_not_started(monkeypatch, caplog) -> None:
    caplog.set_level(logging.INFO)
    monkeypatch.delenv("TTRPG_FRIEND_A_TOKEN", raising=False)
    monkeypatch.delenv("TTRPG_FRIEND_A_TOKEN_FILE", raising=False)
    entries = build_entries(
        _roster(_helper(), _friend()),
        helper_token="helper-token",
        create_helper=lambda guild_id: _Client(),
    )
    assert [entry.spec.id for entry in entries] == ["ttrpg-bot"]
    assert "dormant" in caplog.text


def test_a_friend_with_a_token_is_started(monkeypatch) -> None:
    monkeypatch.setenv("TTRPG_FRIEND_A_TOKEN", "friend-token")
    entries = build_entries(
        _roster(_helper(), _friend()),
        helper_token="helper-token",
        create_helper=lambda guild_id: _Client(),
    )
    assert [entry.spec.id for entry in entries] == ["ttrpg-bot", "friend-a"]
    assert isinstance(entries[1].client, FriendBot)


def test_the_helper_is_built_with_the_guild_id() -> None:
    seen = []

    def factory(guild_id):
        seen.append(guild_id)
        return _Client()

    build_entries(_roster(_helper()), helper_token="token", guild_id=42, create_helper=factory)
    assert seen == [42]


def test_no_token_anywhere_is_an_error(monkeypatch) -> None:
    monkeypatch.delenv("TTRPG_FRIEND_A_TOKEN", raising=False)
    monkeypatch.delenv("TTRPG_FRIEND_A_TOKEN_FILE", raising=False)
    with pytest.raises(RosterError, match="no bot has a token"):
        build_entries(_roster(_friend()), helper_token="")


def test_a_friend_requests_message_content_only_when_listening() -> None:
    assert FriendBot(_friend(listen=False)).intents.message_content is False
    assert FriendBot(_friend(listen=True)).intents.message_content is True


def test_the_listener_gate_does_not_touch_the_message_when_off() -> None:
    class _Exploding:
        def __getattr__(self, name):
            raise AssertionError(f"on_message inspected {name!r} while listening was off")

    asyncio.run(FriendBot(_friend(listen=False)).on_message(_Exploding()))


def test_an_entry_never_shows_its_token() -> None:
    entry = Entry(spec=_helper(), client=_Client(), token="super-secret")
    assert "super-secret" not in repr(entry)


def test_a_rejected_token_names_the_variable() -> None:
    message = explain_failure(_helper(), discord.LoginFailure("nope"))
    assert "DISCORD_TOKEN" in message
    assert "regenerate" in message


def test_a_missing_privileged_intent_says_where_to_enable_it() -> None:
    message = explain_failure(_friend(), discord.PrivilegedIntentsRequired(0))
    assert "Message Content" in message
    assert "Developer Portal" in message


def test_one_failing_bot_does_not_stop_the_other(caplog) -> None:
    good, bad = _Client(), _Client(fail=RuntimeError("boom"))
    entries = (
        Entry(spec=_helper(), client=good, token="one"),
        Entry(spec=_friend(), client=bad, token="two"),
    )
    asyncio.run(_run_all(entries))

    assert bad.closed is True
    assert good.closed is True  # returned normally, then closed on the way out
    assert "friend-a" in caplog.text
    assert "boom" in caplog.text


def test_a_single_bot_uses_the_blocking_run_path() -> None:
    client = _Client()
    run(
        _roster(_helper()),
        helper_token="helper-token",
        create_helper=lambda guild_id: client,
    )
    assert client.runs == [("helper-token", {"log_handler": None})]


def test_several_bots_go_through_asyncio(monkeypatch) -> None:
    monkeypatch.setenv("TTRPG_FRIEND_A_TOKEN", "friend-token")
    seen = []

    async def fake_run_all(entries):
        seen.extend(entry.spec.id for entry in entries)

    monkeypatch.setattr("ttrpg_chatbots.bots.supervisor._run_all", fake_run_all)
    run(
        _roster(_helper(), _friend()),
        helper_token="helper-token",
        create_helper=lambda guild_id: _Client(),
    )
    assert seen == ["ttrpg-bot", "friend-a"]


def test_a_roster_without_a_helper_warns(monkeypatch, caplog) -> None:
    monkeypatch.setenv("TTRPG_FRIEND_A_TOKEN", "friend-token")
    run(
        _roster(_friend(listen=False)),
        helper_token="",
        create_helper=lambda guild_id: _Client(),
        create_friend=lambda spec: _Client(),
    )
    assert "no helper" in caplog.text


class _Perm:
    def __init__(self, allowed: set[str]) -> None:
        self._allowed = frozenset(allowed)

    def __getattr__(self, name: str) -> bool:
        return name in self._allowed


class _Chan:
    id = 7
    name = "general"

    def __init__(self, allowed: set[str]) -> None:
        self._allowed = allowed

    def permissions_for(self, member) -> _Perm:
        return _Perm(self._allowed)


class _Guild:
    def __init__(self, channel) -> None:
        self._channel = channel
        self.me = object()

    def get_channel(self, channel_id):
        return self._channel if channel_id == self._channel.id else None


class _Friend(FriendBot):
    """A FriendBot whose guilds are supplied rather than fetched from a gateway."""

    def __init__(self, spec, guild) -> None:
        super().__init__(spec)
        self._guild = guild

    @property
    def guilds(self):
        return (self._guild,)


def test_a_friend_that_is_not_listening_is_not_warned_about_message_content(caplog) -> None:
    """The audit must not nag about an intent this bot deliberately did not request."""
    caplog.set_level(logging.DEBUG)
    spec = BotSpec(id="friend-a", role="friend", listen=False, channels=(7,))
    allowed = {requirement.name for requirement in requirements_for(ROLE_FRIEND)}
    friend = _Friend(spec, _Guild(_Chan(allowed)))

    asyncio.run(friend.check_permissions())

    assert "message_content" not in caplog.text
    assert "checks passed" in caplog.text
