"""The temporary thread probe: each step reports, and every failure is logged."""

from __future__ import annotations

import logging

import ttrpg_chatbots.bot as bot


class _Record:
    def __init__(self) -> None:
        self.messages: list[str] = []
        self.ephemeral: list[bool] = []
        self.deferred = False

    async def defer(self, *, thinking: bool = False, ephemeral: bool = False) -> None:
        self.deferred = thinking


class _Followup:
    def __init__(self) -> None:
        self.messages: list[str] = []
        self.ephemeral: list[bool] = []

    async def send(self, content: str = "", *, embed=None, ephemeral: bool = False) -> None:
        self.messages.append(content)
        self.ephemeral.append(ephemeral)


class _User:
    display_name = "Tav"
    id = 4242


class _Message:
    id = 900


class _Thread:
    def __init__(self, *, add_fails: bool = False, send_fails: bool = False) -> None:
        self.id = 555
        self.mention = "<#555>"
        self.added: list = []
        self.sent: list = []
        self.add_fails = add_fails
        self.send_fails = send_fails

    async def add_user(self, user) -> None:
        if self.add_fails:
            raise PermissionError("missing access")
        self.added.append(user)

    async def send(self, *, embed=None, content: str = "") -> _Message:
        if self.send_fails:
            raise RuntimeError("cannot send messages in this thread")
        self.sent.append(embed or content)
        return _Message()


class _Channel:
    def __init__(self, thread: _Thread | None = None, *, fails: bool = False) -> None:
        self.id = 777
        self.type = "text"
        self.thread = thread or _Thread()
        self.fails = fails
        self.created: list[dict] = []

    async def create_thread(self, **kwargs) -> _Thread:
        if self.fails:
            raise PermissionError("Missing Permissions")
        self.created.append(kwargs)
        return self.thread


class _Guild:
    id = 1


def _interaction(channel, *, guild=True):
    interaction = type("I", (), {})()
    interaction.response = _Record()
    interaction.followup = _Followup()
    interaction.user = _User()
    interaction.channel = channel
    interaction.guild = _Guild() if guild else None
    return interaction


def _run(interaction) -> str:
    import asyncio

    asyncio.run(bot.testthread.callback(interaction))
    return interaction.followup.messages[-1]


def test_a_private_thread_is_created_and_used(caplog) -> None:
    thread = _Thread()
    interaction = _interaction(_Channel(thread))
    with caplog.at_level(logging.INFO, logger="ttrpg_chatbots.bot"):
        message = _run(interaction)

    assert "thread works" in message
    assert "555" in message
    assert thread.added and thread.sent
    # A private thread, invited explicitly, long archive window — the shape a build needs.
    created = interaction.channel.created[0]
    assert created["invitable"] is False
    assert created["auto_archive_duration"] == 1440
    assert "created private thread 555" in caplog.text
    assert "posted 900 into thread 555" in caplog.text


def test_it_says_so_outside_a_guild(caplog) -> None:
    interaction = _interaction(_Channel(), guild=False)
    with caplog.at_level(logging.WARNING, logger="ttrpg_chatbots.bot"):
        message = _run(interaction)
    assert "needs a server channel" in message
    assert "called outside a guild" in caplog.text


def test_a_refused_thread_creation_is_reported_and_logged(caplog) -> None:
    interaction = _interaction(_Channel(fails=True))
    with caplog.at_level(logging.ERROR, logger="ttrpg_chatbots.bot"):
        message = _run(interaction)
    assert "create_thread failed" in message
    assert "PermissionError" in message
    assert "create_thread failed on channel 777" in caplog.text
    assert "Traceback" in caplog.text  # LOGGER.exception, not a bare warning


def test_failing_to_add_the_player_does_not_stop_the_probe(caplog) -> None:
    thread = _Thread(add_fails=True)
    interaction = _interaction(_Channel(thread))
    with caplog.at_level(logging.ERROR, logger="ttrpg_chatbots.bot"):
        message = _run(interaction)
    assert "thread works" in message
    assert "added you: no" in message
    assert "add_user failed" in caplog.text


def test_failing_to_post_in_the_thread_is_reported(caplog) -> None:
    thread = _Thread(send_fails=True)
    interaction = _interaction(_Channel(thread))
    with caplog.at_level(logging.ERROR, logger="ttrpg_chatbots.bot"):
        message = _run(interaction)
    assert "could not post in it" in message
    assert "send failed on thread 555" in caplog.text
