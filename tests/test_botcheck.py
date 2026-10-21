"""``/botcheck``: the helper's own audit, and the friends it cannot see yet."""

from __future__ import annotations

import asyncio

import pytest

import ttrpg_chatbots.bot as bot
from ttrpg_chatbots.bots.identity import BotSpec
from ttrpg_chatbots.bots.permissions import requirements_for
from ttrpg_chatbots.bots.roster import Roster, RosterError


class _Response:
    def __init__(self) -> None:
        self.deferred = False
        self.messages: list[str] = []

    async def defer(self, *, thinking: bool = False, ephemeral: bool = False) -> None:
        self.deferred = thinking

    async def send_message(self, content: str) -> None:
        self.messages.append(content)


class _Followup:
    def __init__(self) -> None:
        self.messages: list[str] = []
        self.ephemeral: list[bool] = []

    async def send(self, content: str = "", *, embed=None, ephemeral: bool = False, file=None) -> None:
        self.messages.append(content)
        self.ephemeral.append(ephemeral)


class _Permissions:
    def __init__(self, allowed: set[str]) -> None:
        self._allowed = frozenset(allowed)

    def __getattr__(self, name: str) -> bool:
        return name in self._allowed


class _Channel:
    id = 555

    def __init__(self, allowed: set[str], name: str = "general") -> None:
        self.name = name
        self._allowed = allowed

    def permissions_for(self, member) -> _Permissions:
        return _Permissions(self._allowed)


class _Member:
    pass


class _Guild:
    def __init__(self, channels: list[_Channel]) -> None:
        self.channels = channels
        self.me = _Member()

    def get_channel(self, channel_id):
        return next((channel for channel in self.channels if channel.id == channel_id), None)


class _Interaction:
    def __init__(self, guild, channel) -> None:
        self.guild = guild
        self.channel = channel
        self.response = _Response()
        self.followup = _Followup()
        self.command = None
        self.user = _Member()


def _helper_names() -> set[str]:
    return {requirement.name for requirement in requirements_for("helper")}


def _run(guild, channel, roster: Roster) -> _Interaction:
    interaction = _Interaction(guild, channel)
    asyncio.run(bot.botcheck.callback(interaction))
    return interaction


def _four_bots() -> Roster:
    return Roster(
        (
            BotSpec(id="ttrpg-bot", role="helper", commands=True),
            BotSpec(id="friend-a", role="friend", listen=False),
        )
    )


def test_a_healthy_helper_is_reported_as_healthy(monkeypatch) -> None:
    channel = _Channel(_helper_names())
    monkeypatch.setattr(bot, "load_roster", _four_bots)
    interaction = _run(_Guild([channel]), channel, _four_bots())

    message = interaction.followup.messages[-1]
    assert "ttrpg-bot:" in message
    assert "every required permission" in message


def test_a_missing_permission_is_named_with_its_fix(monkeypatch) -> None:
    channel = _Channel(_helper_names() - {"create_private_threads"})
    monkeypatch.setattr(bot, "load_roster", _four_bots)
    interaction = _run(_Guild([channel]), channel, _four_bots())

    message = interaction.followup.messages[-1]
    assert "Create Private Threads" in message
    assert "fix:" in message
    assert "grant" in message.lower()


def test_a_friend_without_a_user_id_says_why_it_cannot_be_checked(monkeypatch) -> None:
    channel = _Channel(_helper_names())
    monkeypatch.setattr(bot, "load_roster", _four_bots)
    interaction = _run(_Guild([channel]), channel, _four_bots())

    message = interaction.followup.messages[-1]
    assert "friend-a" in message
    assert "no user_id" in message


def test_a_dm_is_refused(monkeypatch) -> None:
    monkeypatch.setattr(bot, "load_roster", _four_bots)
    interaction = _run(None, _Channel(_helper_names()), _four_bots())

    assert "only exist in a server" in interaction.followup.messages[-1]


def test_a_broken_roster_is_reported_not_raised(monkeypatch) -> None:
    def explode():
        raise RosterError("bots.json is not valid JSON")

    monkeypatch.setattr(bot, "load_roster", explode)
    interaction = _run(_Guild([]), _Channel(_helper_names()), _four_bots())

    assert "error: bots.json is not valid JSON" in interaction.followup.messages[-1]


def test_the_reply_is_ephemeral(monkeypatch) -> None:
    channel = _Channel(_helper_names())
    monkeypatch.setattr(bot, "load_roster", _four_bots)
    interaction = _run(_Guild([channel]), channel, _four_bots())

    assert interaction.followup.ephemeral[-1] is True
