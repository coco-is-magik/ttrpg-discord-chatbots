"""Discord bot wiring."""

from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from ttrpg_chatbots.config import ConfigError, DiscordConfig, load_discord_config

LOGGER = logging.getLogger(__name__)


@app_commands.command(name="ping", description="Check that the bot is online.")
async def ping(interaction: discord.Interaction) -> None:
    """Reply with a pong."""
    await interaction.response.send_message("Pong!")


class TtrpgBot(commands.Bot):
    """Bot that owns this project's command tree.

    Slash commands need no privileged intents, so the default intents are used.
    Message-content commands would require enabling the Message Content intent in
    the Discord developer portal.
    """

    def __init__(self, guild_id: int | None = None) -> None:
        super().__init__(
            command_prefix=commands.when_mentioned,
            intents=discord.Intents.default(),
            help_command=None,
        )
        self.tree.add_command(ping)
        self._sync_guild = discord.Object(id=guild_id) if guild_id is not None else None

    async def setup_hook(self) -> None:
        # Syncing to a single guild is immediate; the global scope can take up to
        # an hour to propagate, so a dev guild id keeps iteration practical.
        await self.tree.sync(guild=self._sync_guild)

    async def on_ready(self) -> None:
        LOGGER.info("Connected to Discord as %s", self.user)


def create_bot(guild_id: int | None = None) -> TtrpgBot:
    """Build the bot without connecting."""
    return TtrpgBot(guild_id=guild_id)


def run_bot(config: DiscordConfig) -> None:
    """Connect to Discord and run until interrupted."""
    bot = create_bot(guild_id=config.guild_id)
    LOGGER.info("Starting bot; slash commands scope: %s", config.guild_id or "global")
    bot.run(config.token, log_handler=None)


def main() -> None:
    """Entry point for the ``ttrpg-chatbots-bot`` console script."""
    discord.utils.setup_logging(level=logging.INFO)
    try:
        config = load_discord_config()
    except ConfigError as error:
        raise SystemExit(f"configuration error: {error}") from error
    run_bot(config)
