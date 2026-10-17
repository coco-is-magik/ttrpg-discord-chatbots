"""Discord bot wiring.

Every slash command here is a thin adapter: it validates the interaction, hands the work
to :class:`~ttrpg_chatbots.conversation.Conversation` in a worker thread, and reports the
result. Anything that takes time (loading a dataset, synthesizing speech, calling a model)
is awaited off the event loop, so the gateway heartbeat never stalls.

Slash commands need no privileged intents. Voice needs ``PyNaCl``, ``libopus`` and, on
current Discord, ``davey``; :func:`voice_readiness` reports what is missing instead of
letting ``/join`` fail with a stack trace.
"""

from __future__ import annotations

import argparse
import asyncio
import logging

import discord
from discord import app_commands
from discord.ext import commands

from ttrpg_chatbots.config import ConfigError, DiscordConfig, load_discord_config
from ttrpg_chatbots.conversation import Conversation, ConversationError
from ttrpg_chatbots.respond import Answer
from ttrpg_chatbots.voice.discord_voice import play_in
from ttrpg_chatbots.voice.player import VoicePlayer
from ttrpg_chatbots.voice.sources import PcmFrameSource

LOGGER = logging.getLogger(__name__)

# Discord rejects messages longer than 2000 characters.
MAX_MESSAGE = 1900


def voice_readiness() -> tuple[bool, str]:
    """Whether this machine can join a voice channel, and why not if it cannot."""
    missing = []
    try:
        import nacl  # noqa: F401
    except ImportError:
        missing.append("PyNaCl (install the 'voice' extra)")
    if not discord.opus.is_loaded():
        try:
            discord.opus._load_default()  # noqa: SLF001 - the documented loader
        except Exception:  # noqa: BLE001 - reported, not raised
            missing.append("libopus (install your distro's opus package)")
    try:
        import davey  # noqa: F401
    except ImportError:
        missing.append("davey (the DAVE end-to-end encryption library)")
    if missing:
        return False, "voice unavailable: missing " + ", ".join(missing)
    return True, "voice ready"


def _clip_text(text: str) -> str:
    return text if len(text) <= MAX_MESSAGE else text[: MAX_MESSAGE - 1] + "…"


def _describe(answer: Answer) -> str:
    """The reply, plus a quiet note about where it came from."""
    note = f"\n-# answered by `{answer.source}`"
    if answer.degraded:
        note += f" (fallback: {answer.fallback_reason})"
    return _clip_text(answer.text) + note


def _voice_client(interaction: discord.Interaction) -> discord.VoiceClient | None:
    """The guild's voice client, or ``None`` outside a guild or when not connected."""
    guild = interaction.guild
    return guild.voice_client if guild is not None else None


def _conversation(bot: commands.Bot) -> Conversation:
    """One conversation per process, created on first use."""
    conversation = getattr(bot, "conversation", None)
    if conversation is None:
        conversation = Conversation()
        bot.conversation = conversation  # type: ignore[attr-defined]
    return conversation


def _player_for(bot: commands.Bot, voice_client: discord.VoiceClient) -> VoicePlayer:
    """The playback queue feeding one voice client, created on demand."""
    players = bot.players  # type: ignore[attr-defined]
    player = players.get(voice_client.guild.id)
    if player is None or not voice_client.is_connected():
        player = VoicePlayer()
        players[voice_client.guild.id] = player
        play_in(voice_client, player, pad_silence=True)
    return player


@app_commands.command(name="ping", description="Check that the bot is online.")
async def ping(interaction: discord.Interaction) -> None:
    """Reply with a pong."""
    await interaction.response.send_message("Pong!")


async def _enqueue(interaction: discord.Interaction, clip) -> None:
    """Queue a synthesized clip for the guild's voice client, if there is one."""
    client = _voice_client(interaction)
    if client is None or not client.is_connected():
        await interaction.followup.send(
            "-# not in a voice channel: run /join first, then ask again with speak:true"
        )
        return
    player = _player_for(interaction.client, client)
    player.enqueue(PcmFrameSource(clip))
    LOGGER.info("queued %.2f s of speech", clip.duration_s)



@app_commands.command(name="ask", description="Ask a character a question.")
@app_commands.describe(
    question="What you want to ask",
    character="Character id or name (default: the first in the world)",
    speak="Also say it aloud in the voice channel the bot is in",
)
async def ask(
    interaction: discord.Interaction,
    question: str,
    character: str | None = None,
    speak: bool = False,
) -> None:
    """Answer with dice, the model or the classifier, and optionally speak it."""
    await interaction.response.defer(thinking=True)
    conversation = _conversation(interaction.client)
    speaker = interaction.user.display_name
    # Do not spend a synthesis pass on audio nobody can hear.
    client = _voice_client(interaction)
    can_speak = speak and client is not None and client.is_connected()
    try:
        if can_speak:
            answer, clip = await asyncio.to_thread(
                conversation.answer_and_speak,
                question,
                character=character,
                speaker=speaker,
            )
        else:
            answer = await asyncio.to_thread(
                conversation.answer, question, character=character, speaker=speaker
            )
            clip = None
    except (ConversationError, ValueError, OSError) as error:
        await interaction.followup.send(f"error: {error}")
        return

    text = _describe(answer)
    if speak and not can_speak:
        text += "\n-# asked to speak, but I am not in a voice channel: run /join first"
    elif speak and clip is None:
        text += "\n-# asked to speak, but nothing was spoken: see the log"
    await interaction.followup.send(text)

    if clip is not None:
        await _enqueue(interaction, clip)


@app_commands.command(name="roll", description="Roll dice or a named check.")
@app_commands.describe(
    dice="Notation such as 3d6 or 2d20+3", check="A named check, e.g. stealth",
    character="Who is rolling",
)
async def roll(
    interaction: discord.Interaction,
    dice: str | None = None,
    check: str | None = None,
    character: str | None = None,
) -> None:
    """Roll something, attributed to a character."""
    if not dice and not check:
        await interaction.response.send_message(
            "error: give dice (3d6) or a check (stealth)", ephemeral=True
        )
        return
    await interaction.response.defer(thinking=True)
    prompt = f"roll {check}" if check else f"roll {dice}"
    try:
        answer = await asyncio.to_thread(
            _conversation(interaction.client).answer,
            prompt,
            character=character,
            speaker=interaction.user.display_name,
        )
    except (ConversationError, ValueError, OSError) as error:
        await interaction.followup.send(f"error: {error}")
        return
    await interaction.followup.send(_describe(answer))


@app_commands.command(name="join", description="Join your voice channel.")
async def join(interaction: discord.Interaction) -> None:
    """Connect to the caller's voice channel and start the playback stream."""
    ready, detail = voice_readiness()
    if not ready:
        await interaction.response.send_message(detail, ephemeral=True)
        return
    member = interaction.user
    channel = getattr(member.voice, "channel", None) if getattr(member, "voice", None) else None
    if channel is None:
        await interaction.response.send_message(
            "error: join a voice channel first", ephemeral=True
        )
        return
    await interaction.response.defer(thinking=True)
    guild = interaction.guild
    client: discord.VoiceClient | None = guild.voice_client  # type: ignore[union-attr]
    if client is None:
        try:
            client = await channel.connect(self_deaf=True)  # type: ignore[attr-defined]
        except Exception as error:  # noqa: BLE001 - reported to the user
            await interaction.followup.send(f"error: could not join: {error}")
            return
    player = _player_for(interaction.client, client)
    queued = player.queued
    await interaction.followup.send(
        f"joined **{channel.name}**; playback stream open (queue: {queued})"
    )


@app_commands.command(name="leave", description="Leave the voice channel.")
async def leave(interaction: discord.Interaction) -> None:
    """Disconnect, dropping anything still queued."""
    client = _voice_client(interaction)
    if client is None:
        await interaction.response.send_message("not in a voice channel", ephemeral=True)
        return
    players = interaction.client.players  # type: ignore[attr-defined]
    player = players.pop(client.guild.id, None)
    if player is not None:
        player.close()
    await client.disconnect()
    await interaction.response.send_message("left the voice channel")


@app_commands.command(name="say", description="Speak text aloud in the voice channel.")
@app_commands.describe(text="What to say", character="Whose voice to use")
async def say(
    interaction: discord.Interaction, text: str, character: str | None = None
) -> None:
    """Synthesize arbitrary text and play it."""
    client = _voice_client(interaction)
    if client is None or not client.is_connected():
        await interaction.response.send_message(
            "error: run /join first", ephemeral=True
        )
        return
    await interaction.response.defer(thinking=True)
    try:
        clip = await asyncio.to_thread(
            _conversation(interaction.client).speak, text, character=character
        )
    except Exception as error:  # noqa: BLE001 - synthesis can fail many ways
        await interaction.followup.send(f"error: {error}")
        return
    player = _player_for(interaction.client, client)
    player.enqueue(PcmFrameSource(clip))
    await interaction.followup.send(
        f"speaking {clip.duration_s:.1f} s (queued: {player.queued})"
    )


@app_commands.command(name="stop", description="Stop speaking and clear the queue.")
async def stop(interaction: discord.Interaction) -> None:
    """Drop everything queued; the playback stream stays open."""
    client = _voice_client(interaction)
    players = interaction.client.players  # type: ignore[attr-defined]
    player = players.get(client.guild.id) if client is not None else None
    if player is None:
        await interaction.response.send_message("nothing is playing", ephemeral=True)
        return
    player.clear()
    await interaction.response.send_message("stopped")


@app_commands.command(name="voices", description="Show which voice each character uses.")
async def voices(interaction: discord.Interaction) -> None:
    """List the cast, and whether voice is usable on this machine."""
    await interaction.response.defer(thinking=True)
    ready, detail = voice_readiness()
    try:
        rows = await asyncio.to_thread(_conversation(interaction.client).voices)
    except (ConversationError, ValueError, OSError) as error:
        await interaction.followup.send(f"error: {error}")
        return
    lines = [f"`{row['character']:<12}` {row['name']:<26} {row['voice']}" for row in rows]
    await interaction.followup.send(
        "\n".join(lines) + f"\n-# {detail if not ready else 'voice ready'}"
    )


class TtrpgCommandTree(app_commands.CommandTree):
    """Command tree that never leaves an interaction unanswered.

    A slash command that defers and then raises used to leave "bot is thinking" on screen
    forever: discord.py logs the traceback, but the interaction is never completed. This
    answers with the failure instead, so a bug is visible where it happened rather than
    looking like a hung bot.
    """

    async def on_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
    ) -> None:
        original = getattr(error, "original", error)
        command = interaction.command.qualified_name if interaction.command else "command"
        LOGGER.error(
            "command /%s failed: %s",
            command,
            original,
            exc_info=(type(original), original, original.__traceback__),
        )

        message = _clip_text(f"error in /{command}: {original}")
        try:
            if interaction.response.is_done():
                await interaction.followup.send(message)
            else:
                await interaction.response.send_message(message, ephemeral=True)
        except Exception:  # noqa: BLE001 - the reply is best effort; the log has the cause
            LOGGER.warning("could not report the failure of /%s to the user", command)


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
            tree_cls=TtrpgCommandTree,
        )
        for command in (ping, ask, roll, join, leave, say, stop, voices):
            self.tree.add_command(command)
        self._sync_guild = discord.Object(id=guild_id) if guild_id is not None else None
        # One playback queue per guild, created when the bot joins a channel.
        self.players: dict[int, VoicePlayer] = {}
        # One conversation for the whole process, built on first use.
        self.conversation: Conversation | None = None

    async def setup_hook(self) -> None:
        # Syncing to a single guild is immediate; the global scope can take up to
        # an hour to propagate, so a dev guild id keeps iteration practical.
        #
        # copy_global_to matters: sync(guild=...) uploads only the commands registered
        # for that guild, so without this the payload is empty and nothing appears.
        expected = len(self.tree.get_commands())
        if self._sync_guild is not None:
            self.tree.copy_global_to(guild=self._sync_guild)
            synced = await self.tree.sync(guild=self._sync_guild)
            scope = f"guild {self._sync_guild.id}"
        else:
            synced = await self.tree.sync()
            scope = "global"
        LOGGER.info("synced %d/%d slash commands (%s)", len(synced or ()), expected, scope)
        if not synced:
            LOGGER.warning(
                "Discord accepted no slash commands; check that the invite included the "
                "applications.commands scope"
            )

    async def on_ready(self) -> None:
        LOGGER.info("Connected to Discord as %s", self.user)
        ready, detail = voice_readiness()
        LOGGER.info("voice: %s", "ready" if ready else detail)

    async def close(self) -> None:
        for player in self.players.values():
            player.close()
        self.players.clear()
        if self.conversation is not None:
            self.conversation.close()
        await super().close()


def create_bot(guild_id: int | None = None) -> TtrpgBot:
    """Build the bot without connecting."""
    return TtrpgBot(guild_id=guild_id)


def run_bot(config: DiscordConfig) -> None:
    """Connect to Discord and run until interrupted."""
    bot = create_bot(guild_id=config.guild_id)
    LOGGER.info("Starting bot; slash commands scope: %s", config.guild_id or "global")
    bot.run(config.token, log_handler=None)


def main(argv: list[str] | None = None) -> None:
    """Entry point for the ``ttrpg-chatbots-bot`` console script.

    ``--check`` validates the configuration and reports whether voice can work, without
    contacting Discord: exactly what you want before an invite, and what a smoke test can
    run safely.
    """
    parser = argparse.ArgumentParser(
        prog="ttrpg-chatbots-bot",
        description="Run the Discord bot. Reads DISCORD_TOKEN (or DISCORD_TOKEN_FILE).",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="validate configuration and voice support, then exit without connecting",
    )
    parser.add_argument("--version", action="store_true", help="print the version and exit")
    args = parser.parse_args(argv)

    if args.version:
        from ttrpg_chatbots import __version__

        print(f"ttrpg-chatbots-bot {__version__}")
        return

    discord.utils.setup_logging(level=logging.INFO)
    try:
        config = load_discord_config()
    except ConfigError as error:
        raise SystemExit(f"configuration error: {error}") from error

    ready, detail = voice_readiness()
    if args.check:
        print(f"token: configured ({len(config.token)} characters, not shown)")
        print(f"guild: {config.guild_id if config.guild_id is not None else 'global sync'}")
        print(f"voice: {detail if not ready else 'ready'}")
        print("check only: not connecting to Discord")
        return

    LOGGER.info("voice: %s", "ready" if ready else detail)
    run_bot(config)
