"""Bot wiring tests.

Nothing here contacts Discord: ``tests/conftest.py`` refuses socket connections,
``tree.sync`` is replaced with a recorder, and ``Client.run`` is never called.
"""

import asyncio

import discord
import pytest

from ttrpg_chatbots.bot import TtrpgBot, create_bot, main, ping, run_bot
from ttrpg_chatbots.config import (
    GUILD_ID_ENV_VAR,
    TOKEN_ENV_VAR,
    TOKEN_FILE_ENV_VAR,
    DiscordConfig,
)

GUILD_ID = 123456789012345678
DUMMY_TOKEN = "dummy-token-not-a-real-credential"


class _RecordingResponse:
    def __init__(self) -> None:
        self.messages: list[str] = []

    async def send_message(self, content: str) -> None:
        self.messages.append(content)


class _Interaction:
    def __init__(self) -> None:
        self.response = _RecordingResponse()


def test_bot_registers_the_ping_command() -> None:
    async def build() -> None:
        bot = create_bot()
        try:
            assert bot.tree.get_command("ping") is ping
        finally:
            await bot.close()

    asyncio.run(build())


def test_ping_replies_with_pong() -> None:
    interaction = _Interaction()
    asyncio.run(ping.callback(interaction))  # type: ignore[arg-type]
    assert interaction.response.messages == ["Pong!"]


def test_bot_uses_no_privileged_intents() -> None:
    async def build() -> None:
        bot = create_bot()
        try:
            assert bot.intents.message_content is False
            assert bot.intents.members is False
        finally:
            await bot.close()

    asyncio.run(build())


def _record_sync(monkeypatch, bot) -> list:
    """Replace tree.sync with a recorder so no sync request leaves the process."""
    calls: list = []

    async def sync(*, guild=None):
        calls.append(guild)

    monkeypatch.setattr(bot.tree, "sync", sync)
    return calls


def test_setup_hook_syncs_globally_without_a_guild_id(monkeypatch) -> None:
    async def build() -> None:
        bot = create_bot()
        calls = _record_sync(monkeypatch, bot)
        try:
            await bot.setup_hook()
        finally:
            await bot.close()
        assert calls == [None]

    asyncio.run(build())


def test_setup_hook_syncs_to_the_configured_guild(monkeypatch) -> None:
    async def build() -> None:
        bot = create_bot(guild_id=GUILD_ID)
        calls = _record_sync(monkeypatch, bot)
        try:
            await bot.setup_hook()
        finally:
            await bot.close()
        assert calls == [discord.Object(id=GUILD_ID)]

    asyncio.run(build())


def test_run_bot_forwards_the_token_and_keeps_our_logging(monkeypatch) -> None:
    async def build() -> None:
        recorded = {}

        def fake_run(self, token, **kwargs):
            recorded["bot"] = self
            recorded["token"] = token
            recorded["kwargs"] = kwargs

        monkeypatch.setattr(TtrpgBot, "run", fake_run)
        run_bot(DiscordConfig(token=DUMMY_TOKEN, guild_id=GUILD_ID))
        try:
            assert recorded["token"] == DUMMY_TOKEN
            # log_handler=None stops discord.py from replacing the root handler.
            assert recorded["kwargs"] == {"log_handler": None}
        finally:
            await recorded["bot"].close()

    asyncio.run(build())


def test_main_with_a_dummy_token_delegates_to_run_bot(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv(TOKEN_ENV_VAR, DUMMY_TOKEN)
    for var in (TOKEN_FILE_ENV_VAR, GUILD_ID_ENV_VAR):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.chdir(tmp_path)

    seen = []
    monkeypatch.setattr("ttrpg_chatbots.bot.run_bot", seen.append)
    main()

    assert seen == [DiscordConfig(token=DUMMY_TOKEN, guild_id=None)]
    assert DUMMY_TOKEN not in repr(seen[0])


def test_main_exits_before_connecting_when_no_token_is_configured(monkeypatch, tmp_path) -> None:
    for var in (TOKEN_ENV_VAR, TOKEN_FILE_ENV_VAR):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.chdir(tmp_path)  # hide any developer .env

    def forbid_connecting(*args, **kwargs):
        raise AssertionError("main() tried to connect without configuration")

    monkeypatch.setattr("ttrpg_chatbots.bot.run_bot", forbid_connecting)

    with pytest.raises(SystemExit) as exit_info:
        main()
    assert TOKEN_ENV_VAR in str(exit_info.value)
