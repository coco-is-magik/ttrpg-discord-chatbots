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
import io
import logging
import os
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands

from dataclasses import replace

from ttrpg_chatbots.character.build import (
    Build,
    problems as build_problems,
    remaining as build_remaining,
)
from ttrpg_chatbots.character.creation import blank_sheet, now_utc
from ttrpg_chatbots.character.store import CharacterStore, slug_for
from ttrpg_chatbots.sheets.interview import blank_interview, load_questionnaire
from ttrpg_chatbots.sheets.interview import SKIPPED
from ttrpg_chatbots.sheets.render import (
    QUESTIONS_PER_PAGE,
    build_embed,
    questionnaire_embed,
)
from ttrpg_chatbots.sheets.types import SheetError, normalise
from ttrpg_chatbots.character.types import Character, CharacterConflict, CharacterError
from ttrpg_chatbots.bots import (
    ROLE_FRIEND,
    ROLE_HELPER,
    RosterError,
    audit,
    load_roster,
    log_findings,
    report,
)
from ttrpg_chatbots.config import ConfigError, DiscordConfig, load_discord_config
from ttrpg_chatbots.conversation import Conversation, ConversationError
from ttrpg_chatbots.dice.parts import RollParts
from ttrpg_chatbots.dice.types import DiceError
from ttrpg_chatbots.respond import Answer
from ttrpg_chatbots.seats import Seat, SeatBook, SeatsError, load_seats, save_seats
from ttrpg_chatbots.seats.types import (
    KIND_HUMAN,
    PERMISSION_AWARD_GIFTS,
    PERMISSION_EDIT_ANY_SHEET,
    PERMISSION_EDIT_OWN_SHEET,
    PERMISSION_VIEW_ANY_SHEET,
)
from ttrpg_chatbots.sheetportal import mutations as mutate
from ttrpg_chatbots.sheetportal.mutations import MutationError, current_rating
from ttrpg_chatbots.sheets.render import embed_spec, render_sheet
from ttrpg_chatbots.sheets.systems import houseg
from ttrpg_chatbots.sheets.merits import Catalogue, load_catalogue
from ttrpg_chatbots.voice.discord_voice import play_in
from ttrpg_chatbots.voice.player import VoicePlayer
from ttrpg_chatbots.voice.sources import PcmFrameSource

LOGGER = logging.getLogger(__name__)

# Discord rejects messages longer than 2000 characters.
MAX_MESSAGE = 1900

SEATS_ENV = "TTRPG_SEATS_FILE"
CHARACTERS_ENV = "TTRPG_CHARACTERS_DIR"
COMMANDS: list[app_commands.Command] = []


def command(**kwargs):
    """Register a slash command and remember it for ``setup_hook``.

    The list is filled by the decorator rather than by a hand-written tuple: a command that
    exists but was never added to the tree is invisible in Discord and silent in tests, which
    is exactly the bug this replaces.
    """

    def wrap(func):
        registered = app_commands.command(**kwargs)(func)
        COMMANDS.append(registered)
        return registered

    return wrap


DEFAULT_SEATS_PATH = Path("data") / "seats.json"
DEFAULT_CHARACTERS_PATH = Path("data") / "characters"


def _seats_path() -> Path:
    return Path(os.environ.get(SEATS_ENV, str(DEFAULT_SEATS_PATH)))


def _character_store() -> CharacterStore:
    return CharacterStore(os.environ.get(CHARACTERS_ENV, str(DEFAULT_CHARACTERS_PATH)))


def _seatbook() -> SeatBook:
    return load_seats(_seats_path())


def _seat_for(interaction: discord.Interaction) -> Seat | None:
    """The caller's seat, or ``None``.

    A broken seat list must not break ``/ping``, so a load failure is logged and treated as
    "no seat"; ``/sheet`` re-reads it and reports the error properly.
    """
    try:
        return _seatbook().for_discord(getattr(interaction.user, "id", None))
    except SeatsError:
        LOGGER.exception("could not read the seat list at %s", _seats_path())
        return None


def _default_character(interaction: discord.Interaction) -> str | None:
    """Whose character an unqualified command applies to: the caller's seat, if any."""
    seat = _seat_for(interaction)
    return seat.reply_character if seat is not None else None


def _display_name(bot: commands.Bot, character_id: object) -> str:
    """A character id turned into a display name for attribution."""
    if not isinstance(character_id, str) or not character_id:
        return ""
    try:
        return _conversation(bot).world.character(character_id).name
    except Exception:  # noqa: BLE001 - attribution is cosmetic, never fatal
        return character_id


def _gift_line(sheet) -> str:
    """Gifts as the table says them: rated ones with dots, flat ones named only."""
    parts = []
    for gift in sheet.gifts:
        if gift.rating:
            parts.append(f"{gift.name} {gift.rating}")
        else:
            parts.append(f"{gift.name} (flat)")
    tier = houseg.gift_tier(sheet.gift_count, veteran=sheet.veteran)
    return f"gifts ({sheet.gift_count}, {tier}): " + ", ".join(parts)


def _pools_line(sheet) -> str:
    """The two currencies, always visible: an unanswerable 'can I afford this?' is a bug."""
    return f"freebies {sheet.freebies} · xp {sheet.xp}"


PORTRAITS_ENV = "TTRPG_PORTRAITS_DIR"
DEFAULT_PORTRAITS_PATH = Path("data") / "portraits"


def _portraits_dir() -> Path:
    return Path(os.environ.get(PORTRAITS_ENV, str(DEFAULT_PORTRAITS_PATH)))


def _portrait_for(sheet) -> tuple[str, str]:
    """``(thumbnail, local file)`` for a character's portrait.

    A URL is used as-is. A bare filename is looked up in the portraits directory and uploaded
    with the message, because an embed can only show a local image as ``attachment://<name>``.
    Anything that does not resolve is dropped rather than rendered as a broken image.
    """
    raw = str(sheet.meta.get("portrait", "") or "").strip()
    if not raw:
        return "", ""
    if raw.startswith(("https://", "http://")):
        return raw, ""
    candidate = _portraits_dir() / Path(raw).name
    if candidate.is_file():
        return f"attachment://{candidate.name}", str(candidate)
    LOGGER.warning("portrait %r not found in %s", raw, _portraits_dir())
    return "", ""


def _sheet_footer(character: Character, seat: Seat | None) -> str:
    """The facts the grid cannot hold: state, revision, interview progress."""
    notes = [f"revision {character.revision}", "sealed" if character.sealed else "draft"]
    if character.interview is not None:
        notes.append(f"interview {character.interview.answered}/{character.interview.total}")
    if seat is not None and seat.character.lower() != character.id:
        notes.append(f"shown by {seat.name}")
    return " · ".join(notes)


def _sheet_body(character: Character) -> str:
    """The fixed-width sheet, exactly as the renderer lays it out."""
    return render_sheet(character.sheet)


def _format_sheet(character: Character, *, viewer: Seat | None) -> str:
    """The sheet in a code block, with a quiet footer for what the grid cannot hold."""
    notes = [f"revision {character.revision}", "sealed" if character.sealed else "draft"]
    interview = character.interview
    if interview is not None:
        notes.append(f"interview {interview.answered}/{interview.total}")
    if viewer is not None and viewer.character.lower() != character.id:
        notes.append(f"shown by {viewer.name}")
    fenced = "```" + chr(10) + _sheet_body(character) + "```"
    return _clip_text(fenced + chr(10) + "-# " + " · ".join(notes))


def _to_embed(spec) -> discord.Embed:
    """Turn a transport-free spec into the thing Discord actually sends."""
    embed = discord.Embed(
        title=spec.title,
        description=spec.description or None,
        colour=discord.Colour(spec.colour),
    )
    for item in spec.fields:
        embed.add_field(name=item.name, value=item.value, inline=item.inline)
    if spec.thumbnail:
        embed.set_thumbnail(url=spec.thumbnail)
    if spec.footer:
        embed.set_footer(text=spec.footer)
    return embed


def _sheet_payload_for(
    interaction: discord.Interaction, requested: str | None, style: str = "embed"
) -> tuple[str | None, discord.Embed | None, str]:
    """What /sheet sends: ``(text, embed, attachment path)``.

    An embed by default, because it holds the portrait and lays itself out.
    """
    seat, character = _sheet_target(interaction, requested)
    if style == "code":
        return _format_sheet(character, viewer=seat), None, ""
    thumbnail, attachment = _portrait_for(character.sheet)
    spec = embed_spec(
        character.sheet,
        footer=_sheet_footer(character, seat),
        thumbnail=thumbnail,
        attachment=attachment,
    )
    return None, _to_embed(spec), attachment


def _sheet_target(
    interaction: discord.Interaction, requested: str | None
) -> tuple[Seat, Character]:
    """Resolve who is asking and whose sheet they may see."""
    seats = _seatbook()
    discord_id = getattr(interaction.user, "id", None)
    seat = seats.for_discord(discord_id)
    if seat is None:
        # Say the id: the fix is to paste it into the seat list, and finding it otherwise
        # means turning on Developer Mode and right-clicking.
        claimable = ", ".join(_claimable_ids()) or "none available"
        raise SeatsError(
            "no character is bound to you: run /claim to pick one. "
            f"Unclaimed: {claimable}."
        )

    wanted = (requested or "").strip()
    if wanted:
        allowed = {seat.character.lower(), seat.id.lower()}
        if wanted.lower() not in allowed and not seat.may(PERMISSION_VIEW_ANY_SHEET):
            raise SeatsError(
                f"{wanted!r} is not your character; yours is {seat.character!r}"
            )
        target = wanted
    else:
        target = seat.character

    return seat, _character_store().load(target)


def _sheet_text(interaction: discord.Interaction, requested: str | None) -> str:
    """The sheet as plain text (used by anything that only needs the string)."""
    seat, character = _sheet_target(interaction, requested)
    return _format_sheet(character, viewer=seat)


def voice_readiness() -> tuple[bool, str]:
    """Whether this machine can join a voice channel, and why not."""
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
    hint = answer.detail.get("hint")
    if hint:
        note += f" · {hint}"
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


@command(name="ping", description="Check that the bot is online.")
async def ping(interaction: discord.Interaction) -> None:
    """Reply with a pong."""
    await interaction.response.send_message("Pong!")


@command(
    name="botcheck",
    description="Check this bot's Discord permissions and report what is missing.",
)
async def botcheck(interaction: discord.Interaction) -> None:
    """Audit the helper, and any friend whose ``user_id`` is known, in the channels that matter.

    Only an application can see its own permissions in a channel, so each friend audits itself
    when it connects. This command covers the helper's own audit, plus friends that have a
    ``user_id`` in ``bots.json`` — the one way to check another bot's channel overwrites
    without the privileged members intent.
    """
    await interaction.response.defer(thinking=True, ephemeral=True)
    guild = interaction.guild
    if guild is None:
        await interaction.followup.send("permissions only exist in a server; run this there")
        return
    try:
        roster = await asyncio.to_thread(load_roster)
    except RosterError as error:
        await _fail(interaction, error)
        return

    helper = roster.helper
    name = helper.id if helper is not None else "this bot"
    findings = audit(
        bot_name=name,
        role=ROLE_HELPER,
        channels=_audit_channels(interaction, helper),
        member=guild.me,
    )
    log_findings(LOGGER, findings)

    sections = [report(findings)]
    for spec in roster.friends:
        sections.append(await _friend_report(interaction, spec, roster))
    await interaction.followup.send(_clip_text("\n\n".join(sections)), ephemeral=True)


def _audit_channels(interaction: discord.Interaction, spec) -> list:
    """The channels worth checking: the bot's configured ones, else where we are standing."""
    guild = interaction.guild
    channels = []
    for channel_id in getattr(spec, "channels", ()) or ():
        channel = guild.get_channel(channel_id) if guild is not None else None
        if channel is not None:
            channels.append(channel)
    if channels:
        return channels
    channel = getattr(interaction, "channel", None)
    return [channel] if channel is not None else []


@command(
    name="friendcheck",
    description="Are the friends online, and can they send and hear?",
)
@app_commands.describe(send="Post one short probe from each friend in this channel")
async def friendcheck(interaction: discord.Interaction, send: bool = False) -> None:
    """Report each friend's connection, and optionally prove it by having them speak.

    The friends share this process, so the helper can reach their clients directly: no IPC, no
    second command surface. ``last_message`` is what a friend most recently heard, which is the
    only honest way to prove receipt without asking a human to read the log.
    """
    await interaction.response.defer(thinking=True, ephemeral=True)
    try:
        roster = await asyncio.to_thread(load_roster)
    except RosterError as error:
        await _fail(interaction, error)
        return

    friends = getattr(interaction.client, "friends", {})
    lines: list[str] = []
    if not friends:
        lines.append("no friend is connected: check data/bots.json and each friend's token")
    for spec in roster.friends:
        client = friends.get(spec.id)
        if client is None:
            lines.append(f"**{spec.id}** · not connected (dormant, failed or disabled)")
            continue
        if not client.is_ready():
            lines.append(f"**{spec.id}** · connecting")
            continue
        last = getattr(client, "last_message", {})
        delivered = getattr(client, "delivered", 0)
        if last:
            heard = f"heard {last['author']} in #{last['channel']}: {last['text'][:60]}"
        elif delivered:
            heard = f"received {delivered} message(s), none from a human yet"
        else:
            heard = "received nothing yet"
        lines.append(
            f"**{spec.id}** · online as {client.user} · "
            f"listening={'yes' if spec.listen else 'no'} · {heard}"
        )
        if send:
            lines.append(await _friend_speak(interaction, client, spec))

    await interaction.followup.send(_clip_text("\n".join(lines)), ephemeral=True)


async def _friend_speak(interaction: discord.Interaction, client, spec) -> str:
    """Send one line as the friend, in the channel this command was run in."""
    channel = interaction.channel
    if channel is None:
        return f"-# {spec.id}: there is no channel here to speak in"
    target = client.get_channel(channel.id)
    if target is None:
        try:
            target = await client.fetch_channel(channel.id)
        except discord.HTTPException as error:
            return f"-# {spec.id}: cannot reach this channel ({error})"
    try:
        await target.send(f"probe from {spec.id}")
    except discord.HTTPException as error:
        return f"-# {spec.id}: could not send ({error})"
    return f"-# {spec.id}: sent a probe here"


async def _friend_report(interaction: discord.Interaction, spec, roster) -> str:
    """Audit one friend if its member can be fetched; otherwise say why it could not be."""
    guild = interaction.guild
    if guild is None:
        return f"{spec.id}: no server, so nothing to check"
    try:
        user_id = roster.app_id_for(spec)
    except RosterError as error:
        return f"{spec.id}: cannot read its app id ({error})"
    if user_id is None:
        return (
            f"{spec.id}: no user_id in bots.json and no APP_ID in its env file, so its channel "
            "permissions cannot be checked from here; it checks itself when it connects"
        )
    try:
        member = guild.get_member(user_id) or await guild.fetch_member(user_id)
    except discord.HTTPException:
        return f"{spec.id}: not in this server yet (app id {user_id})"
    findings = audit(
        bot_name=spec.id,
        role=ROLE_FRIEND,
        channels=_audit_channels(interaction, spec),
        member=member,
    )
    log_findings(LOGGER, findings)
    return report(findings)


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



@command(name="ask", description="Ask a character a question.")
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
    asked_of = character or _default_character(interaction)
    # Do not spend a synthesis pass on audio nobody can hear.
    client = _voice_client(interaction)
    can_speak = speak and client is not None and client.is_connected()
    try:
        if can_speak:
            answer, clip = await asyncio.to_thread(
                conversation.answer_and_speak,
                question,
                character=asked_of,
                speaker=speaker,
            )
        else:
            answer = await asyncio.to_thread(
                conversation.answer, question, character=asked_of, speaker=speaker
            )
            clip = None
    except (ConversationError, ValueError, OSError) as error:
        await _fail(interaction, error)
        return

    text = _describe(answer)
    # Attribution: in a group channel, a line without a name is a line nobody owns.
    name = _display_name(interaction.client, answer.detail.get("character"))
    if name:
        text = f"**{name}:** {text}"
    if speak and not can_speak:
        text += "\n-# asked to speak, but I am not in a voice channel: run /join first"
    elif speak and clip is None:
        text += "\n-# asked to speak, but nothing was spoken: see the log"
    await interaction.followup.send(text)

    if clip is not None:
        await _enqueue(interaction, clip)


@command(name="sheet", description="Show a character sheet.")
@app_commands.describe(
    character="Whose sheet (default: yours)",
    style="embed (default: portrait and columns) or code (copyable text)",
)
@app_commands.choices(
    style=[
        app_commands.Choice(name="embed — portrait and columns", value="embed"),
        app_commands.Choice(name="code — plain copyable text", value="code"),
    ]
)
async def sheet(
    interaction: discord.Interaction,
    character: str | None = None,
    style: str = "embed",
) -> None:
    """Show the caller's own sheet, or any sheet if their seat allows it."""
    await interaction.response.defer(thinking=True)
    try:
        text, embed, attachment = await asyncio.to_thread(
            _sheet_payload_for, interaction, character, style
        )
    except (SeatsError, CharacterError, OSError) as error:
        await _fail(interaction, error)
        return
    if attachment:
        await interaction.followup.send(text, embed=embed, file=discord.File(attachment))
    else:
        await interaction.followup.send(text, embed=embed)


def _fail(interaction: discord.Interaction, error: Exception) -> None:
    """Record a handled failure, then tell the user what happened.

    Handled errors used to vanish: the command replied and nothing reached the log, so "I get
    an error every time" left no trace to diagnose. One line per failure is cheap.
    """
    name = interaction.command.qualified_name if interaction.command else "command"
    LOGGER.warning("/%s: %s", name, error)
    return interaction.followup.send(f"error: {error}")


def _own_character(interaction: discord.Interaction) -> tuple[Seat, Character]:
    """The caller's seat and character, or an error that says how to fix it."""
    discord_id = getattr(interaction.user, "id", None)
    seat = _seatbook().for_discord(discord_id)
    if seat is None:
        claimable = ", ".join(_claimable_ids()) or "none available"
        raise SeatsError(
            "no character is bound to you: run /claim to pick one. "
            f"Unclaimed: {claimable}."
        )
    return seat, _character_store().load(seat.character)


async def _trait_choices(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    """Autocomplete every trait the caller may raise."""
    try:
        _, character = await asyncio.to_thread(_own_character, interaction)
    except Exception:  # noqa: BLE001 - autocomplete must never fail the interaction
        return []
    sheet = character.sheet
    names = [
        *sheet.attributes,
        *sheet.abilities,
        *sheet.virtues,
        *[trait.name for trait in sheet.backgrounds],
        "Willpower",
        "Morality",
    ]
    wanted = (current or "").lower()
    return [
        app_commands.Choice(name=name, value=name)
        for name in names
        if wanted in name.lower()
    ][:25]


@command(name="spend", description="Raise one of your character's traits.")
@app_commands.describe(
    trait="Which trait",
    to="The rating you want it to reach",
    pool="auto (default): the creation budget, then freebies — or force one",
)
@app_commands.choices(
    pool=[
        app_commands.Choice(name="auto — budget first, then freebies", value="auto"),
        app_commands.Choice(name="freebies — creation points", value="freebies"),
        app_commands.Choice(name="xp — advancement", value="xp"),
    ]
)
@app_commands.autocomplete(trait=_trait_choices)
async def spend(
    interaction: discord.Interaction,
    trait: str,
    to: int,
    pool: str = "auto",
) -> None:
    """Spend points on one trait, and say exactly what it cost."""
    await interaction.response.defer(thinking=True)
    try:
        seat, character = await asyncio.to_thread(_own_character, interaction)
        if not seat.may(PERMISSION_EDIT_OWN_SHEET):
            raise SeatsError(
                f"seat {seat.id!r} may not edit its sheet; add "
                f"{PERMISSION_EDIT_OWN_SHEET!r} to its permissions"
            )
        kind, before = await asyncio.to_thread(_before, character, trait)
        note = ""
        if pool == "auto" and character.build is None:
            # Nothing to build from: "auto" is the freebie pool outside creation.
            pool = "freebies"
        if character.build is not None and pool not in ("xp", "freebies"):
            # "auto" during a build: the group budget pays while it has room.
            receipt = await asyncio.to_thread(
                mutate.raise_in_build,
                character.sheet,
                trait,
                to=to,
                build=character.build,
                kind=kind,
            )
            note = " (build)"
        else:
            receipt = await asyncio.to_thread(
                mutate.raise_trait, character.sheet, trait, to=to, pool=pool
            )
        # The write is a compare-and-swap, so a second surface cannot lose this.
        updated = await asyncio.to_thread(
            _record,
            character,
            receipt,
            summary=f"{trait} {before}->{to}{note}",
            detail={"trait": trait, "kind": kind, "before": before, "after": to},
        )
    except (SeatsError, CharacterError, CharacterConflict, MutationError, OSError) as error:
        await _fail(interaction, error)
        return
    await _refresh_creation(interaction, updated)
    await interaction.followup.send(f"{_clip_text(str(receipt))}\n-# {_pools_line(receipt.sheet)}")


def _sheet_owner(interaction: discord.Interaction, target: str | None) -> tuple[Seat, Character]:
    """Whose sheet may be *edited*: your own, or anyone's with ``edit_any_sheet``."""
    seat, own = _own_character(interaction)
    if not target or target.strip().lower() in {seat.character.lower(), seat.id.lower()}:
        if not seat.may(PERMISSION_EDIT_OWN_SHEET):
            raise SeatsError(
                f"seat {seat.id!r} may not edit its sheet; add "
                f"{PERMISSION_EDIT_OWN_SHEET!r} to its permissions"
            )
        return seat, own
    if not seat.may(PERMISSION_EDIT_ANY_SHEET):
        raise SeatsError(
            f"{target!r} is not your character; editing others needs "
            f"{PERMISSION_EDIT_ANY_SHEET!r}"
        )
    return seat, _character_store().load(target.strip())


def _catalogue() -> Catalogue:
    """The merits-and-flaws index, loaded once per process.

    Deliberately tolerant: a group that has not built the index can still price custom merits,
    so a missing or unreadable file yields an empty catalogue rather than a failed command.
    """
    global _CATALOGUE
    if _CATALOGUE is None:
        try:
            _CATALOGUE = load_catalogue()
        except Exception as error:  # noqa: BLE001 - a bad index must not break /merit
            log.warning("merit catalogue unavailable: %s", error)
            _CATALOGUE = Catalogue()
    return _CATALOGUE


_CATALOGUE: Catalogue | None = None


def _record(character: Character, receipt, *, summary: str, detail: dict) -> Character:
    """Write one edit, recording enough detail for /undo to reverse it."""
    updated = character.with_sheet(
        receipt.sheet, summary=summary, detail=detail, at=now_utc()
    )
    return _save(character, updated)


def _before(character: Character, trait: str) -> tuple[str, int]:
    """The trait's kind and current value, for the undo record."""
    kind = mutate.resolve_kind(character.sheet, trait)
    return kind, mutate.current_rating(character.sheet, kind, trait)


@command(name="edit", description="Set a trait to any value (free; caps still apply).")
@app_commands.describe(
    trait="Which trait",
    to="The value it should have",
    target="Whose sheet (default: yours; others need edit_any_sheet)",
)
@app_commands.autocomplete(trait=_trait_choices)
async def edit(
    interaction: discord.Interaction,
    trait: str,
    to: int,
    target: str | None = None,
) -> None:
    """Direct edit: the workbench, and how a wrong number gets fixed."""
    await interaction.response.defer(thinking=True)
    try:
        _, character = await asyncio.to_thread(_sheet_owner, interaction, target)
        kind, before = await asyncio.to_thread(_before, character, trait)
        receipt = await asyncio.to_thread(
            mutate.set_trait, character.sheet, trait, to=to, kind=kind
        )
        updated = await asyncio.to_thread(
            _record,
            character,
            receipt,
            summary=f"{trait} {before}->{to} (edit)",
            detail={"trait": trait, "kind": kind, "before": before, "after": to},
        )
    except (SeatsError, CharacterError, CharacterConflict, MutationError, OSError) as error:
        await _fail(interaction, error)
        return
    await _refresh_creation(interaction, updated)
    await interaction.followup.send(f"{_clip_text(str(receipt))}\n-# /undo reverses it")


async def _ability_choices(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    """Autocomplete ability names only: a specialty belongs to an ability."""
    try:
        _, character = await asyncio.to_thread(_own_character, interaction)
    except Exception:  # noqa: BLE001 - autocomplete must never fail the interaction
        return []
    wanted = (current or "").lower()
    return [
        app_commands.Choice(name=ability.name, value=ability.name)
        for ability in character.sheet.abilities.values()
        if ability.rank and wanted in ability.name.lower()
    ][:25]


@command(name="ungift", description="Remove a Gift that should not be there.")
@app_commands.describe(name="Which Gift")
async def ungift(interaction: discord.Interaction, name: str) -> None:
    """Awarding is /gift; this is the correction."""
    await interaction.response.defer(thinking=True)
    try:
        _, character = await asyncio.to_thread(_sheet_owner, interaction, None)
        held = character.sheet.gift(name)
        receipt = await asyncio.to_thread(mutate.remove_gift, character.sheet, name)
        updated = await asyncio.to_thread(
            _record,
            character,
            receipt,
            summary=f"lost {held.name}",
            detail={"gift": held.name, "action": "remove", "rating": held.rating},
        )
    except (SeatsError, CharacterError, CharacterConflict, MutationError, OSError) as error:
        await _fail(interaction, error)
        return
    await _refresh_creation(interaction, updated)
    await interaction.followup.send(
        f"{_clip_text(str(receipt))}\n-# {_pools_line(receipt.sheet)}"
    )


@command(name="hurt", description="Mark damage on the health track.")
@app_commands.describe(levels="How many levels (default 1)")
async def hurt(interaction: discord.Interaction, levels: int = 1) -> None:
    """The track that changes most often in play."""
    await _health(interaction, -abs(levels or 1))


@command(name="heal", description="Clear damage from the health track.")
@app_commands.describe(levels="How many levels (default 1)")
async def heal(interaction: discord.Interaction, levels: int = 1) -> None:
    """The other half of /hurt."""
    await _health(interaction, abs(levels or 1))


async def _health(interaction: discord.Interaction, levels: int) -> None:
    await interaction.response.defer(thinking=True)
    try:
        _, character = await asyncio.to_thread(_sheet_owner, interaction, None)
        before = mutate.health_level(character.sheet)
        receipt = await asyncio.to_thread(
            mutate.adjust_health, character.sheet, levels=levels
        )
        updated = await asyncio.to_thread(
            _record, character, receipt, summary=receipt.lines[0], detail={"health": before}
        )
    except (SeatsError, CharacterError, CharacterConflict, MutationError, OSError) as error:
        await _fail(interaction, error)
        return
    await _refresh_creation(interaction, updated)
    await interaction.followup.send(_clip_text(str(receipt)))


@command(name="undo", description="Reverse your last sheet edit.")
async def undo(interaction: discord.Interaction) -> None:
    """The safety net that makes fast editing safe: one tap, no confirmation."""
    await interaction.response.defer(thinking=True)
    try:
        _, character = await asyncio.to_thread(_sheet_owner, interaction, None)
        receipt, summary = await asyncio.to_thread(_reverse, character)
        if receipt is None:
            await interaction.followup.send(
                "nothing to undo: no reversible edit in the history"
            )
            return
        updated = character.with_sheet(
            receipt.sheet, summary=f"undo: {summary}", detail={}, at=now_utc()
        )
        await asyncio.to_thread(
            _character_store().save, updated, expect_revision=character.revision
        )
    except (SeatsError, CharacterError, CharacterConflict, MutationError, OSError) as error:
        await _fail(interaction, error)
        return
    await _refresh_creation(interaction, updated)
    await interaction.followup.send(f"undid **{summary}**\n-# {_clip_text(str(receipt))}")


def _reverse(character: Character):
    """Find the newest reversible edit and build its inverse."""
    for event in reversed(character.history):
        if event.kind != "sheet":
            continue
        detail = dict(event.detail)
        sheet = character.sheet
        try:
            if "trait" in detail and "before" in detail:
                receipt = mutate.set_trait(
                    sheet, detail["trait"], to=int(detail["before"]), kind=detail.get("kind")
                )
            elif "gift" in detail and detail.get("action") == "remove":
                receipt = mutate.award_gift(
                    sheet, detail["gift"], rating=detail.get("rating")
                )
            elif "pool" in detail:
                receipt = mutate.set_pool(sheet, detail["pool"], int(detail["before"]))
            elif "health" in detail:
                receipt = mutate.set_health(sheet, int(detail["health"]))
            elif "specialty" in detail:
                receipt = mutate.set_specialty(
                    sheet, detail["specialty"], str(detail.get("before", ""))
                )
            elif "added_background" in detail:
                receipt = mutate.remove_trait(sheet, detail["added_background"])
            elif "added_ability" in detail:
                receipt = mutate.remove_trait(sheet, detail["added_ability"])
            elif "willpower" in detail and "points" in detail:
                restored = replace(
                    sheet, willpower_remaining=int(detail["before"])
                )
                receipt = mutate.Receipt(
                    sheet=restored,
                    lines=(f"restored {detail['points']} Willpower",),
                )
            elif "added_merit" in detail:
                receipt = mutate.remove_merit(sheet, detail["added_merit"])
            elif "added_flaw" in detail:
                receipt = mutate.remove_flaw(sheet, detail["added_flaw"])
            elif "removed_merit" in detail:
                receipt = mutate.add_merit(
                    sheet,
                    detail["removed_merit"],
                    points=int(detail.get("paid", 1)),
                    catalogue=_catalogue(),
                )
            elif "removed" in detail:
                gone = dict(detail["removed"])
                if gone.get("kind") == "ability":
                    receipt = mutate.add_ability(
                        sheet,
                        gone["name"],
                        rank=int(gone.get("rank", 0)),
                        category=str(gone.get("category", "skill")),
                        specialty=str(gone.get("specialty", "")),
                        pool="none",
                    )
                else:
                    receipt = mutate.add_background(
                        sheet, gone["name"], dots=int(gone.get("dots", 1)), pool="none"
                    )
            else:
                continue
        except MutationError:
            # This edit has already been undone (the value is back where it was), so keep
            # walking backwards rather than replaying it and failing.
            continue
        return receipt, event.summary
    return None, ""


@command(name="specialty", description="Set or clear an ability's specialty.")
@app_commands.describe(
    ability="Which ability (rank 4 or more)", text="The specialty; blank clears it"
)
@app_commands.autocomplete(ability=_ability_choices)
async def specialty(
    interaction: discord.Interaction, ability: str, text: str = ""
) -> None:
    """Specialties are the part of a sheet most often wrong, and hardest to retype."""
    await interaction.response.defer(thinking=True)
    try:
        _, character = await asyncio.to_thread(_sheet_owner, interaction, None)
        before = character.sheet.ability(ability).specialty
        receipt = await asyncio.to_thread(
            mutate.set_specialty, character.sheet, ability, text
        )
        updated = await asyncio.to_thread(
            _record,
            character,
            receipt,
            summary=f"{ability} specialty '{before}' -> '{' '.join(text.split())}'",
            detail={"specialty": ability, "before": before},
        )
    except (SeatsError, CharacterError, CharacterConflict, MutationError, OSError) as error:
        await _fail(interaction, error)
        return
    await _refresh_creation(interaction, updated)
    await interaction.followup.send(f"{_clip_text(str(receipt))}\n-# /undo reverses it")


@command(name="background", description="Add a new Background.")
@app_commands.describe(
    name="What it is: Contacts, Mentor, Library…",
    dots="How many dots (default 1)",
    pool="auto (budget first), freebies, xp, or none",
)
@app_commands.choices(
    pool=[
        app_commands.Choice(name="auto — budget first, then freebies", value="auto"),
        app_commands.Choice(name="freebies — creation points", value="freebies"),
        app_commands.Choice(name="xp — advancement", value="xp"),
        app_commands.Choice(name="none — free (GM or draft)", value="none"),
    ]
)
async def background(
    interaction: discord.Interaction,
    name: str,
    dots: int = 1,
    pool: str = "auto",
) -> None:
    """A new Background, priced like any other rating."""
    await interaction.response.defer(thinking=True)
    try:
        _, character = await asyncio.to_thread(_sheet_owner, interaction, None)
        receipt = await asyncio.to_thread(
            mutate.add_background,
            character.sheet,
            name,
            dots=dots,
            pool=pool,
            build=character.build,
        )
        updated = await asyncio.to_thread(
            _record,
            character,
            receipt,
            summary=receipt.lines[0],
            detail={"added_background": " ".join(name.split())},
        )
    except (SeatsError, CharacterError, CharacterConflict, MutationError, OSError) as error:
        await _fail(interaction, error)
        return
    await _refresh_creation(interaction, updated)
    await interaction.followup.send(f"{_clip_text(str(receipt))}\n-# /undo removes it")


@command(name="ability", description="Add a new Talent, Skill or Knowledge.")
@app_commands.describe(
    name="What it is: Stealth, Occult, Firearms…",
    rank="Starting rank (default 1; 0 is allowed for an untrained knowledge)",
    category="Talent, skill or knowledge",
    specialty="A specialty (needs rank 4 or more)",
    pool="auto (budget first), freebies, xp, or none",
)
@app_commands.choices(
    category=[
        app_commands.Choice(name="talent — natural", value="talent"),
        app_commands.Choice(name="skill — trained", value="skill"),
        app_commands.Choice(name="knowledge — studied", value="knowledge"),
    ],
    pool=[
        app_commands.Choice(name="auto — budget first, then freebies", value="auto"),
        app_commands.Choice(name="freebies — creation points", value="freebies"),
        app_commands.Choice(name="xp — advancement", value="xp"),
        app_commands.Choice(name="none — free (GM or draft)", value="none"),
    ],
)
async def ability(
    interaction: discord.Interaction,
    name: str,
    rank: int = 1,
    category: str = "skill",
    specialty: str = "",
    pool: str = "auto",
) -> None:
    """A new ability. Untrained knowledges are listed on purpose: they cannot be rolled."""
    await interaction.response.defer(thinking=True)
    try:
        _, character = await asyncio.to_thread(_sheet_owner, interaction, None)
        receipt = await asyncio.to_thread(
            mutate.add_ability,
            character.sheet,
            name,
            rank=rank,
            category=category,
            specialty=specialty,
            pool=pool,
            build=character.build,
        )
        updated = await asyncio.to_thread(
            _record,
            character,
            receipt,
            summary=receipt.lines[0],
            detail={"added_ability": " ".join(name.split())},
        )
    except (SeatsError, CharacterError, CharacterConflict, MutationError, OSError) as error:
        await _fail(interaction, error)
        return
    await _refresh_creation(interaction, updated)
    await interaction.followup.send(f"{_clip_text(str(receipt))}\n-# /undo removes it")


@command(name="remove", description="Remove an ability or background.")
@app_commands.describe(trait="Which ability or background")
@app_commands.autocomplete(trait=_trait_choices)
async def remove_trait_command(
    interaction: discord.Interaction, trait: str
) -> None:
    """The pair of /ability and /background: a mis-typed name, or a trait never taken."""
    await interaction.response.defer(thinking=True)
    try:
        _, character = await asyncio.to_thread(_sheet_owner, interaction, None)
        found = character.sheet.find_ability(trait)
        if found is not None:
            detail = {
                "removed": {
                    "kind": "ability",
                    "name": found.name,
                    "rank": found.rank,
                    "category": found.category,
                    "specialty": found.specialty,
                }
            }
        else:
            background_trait = character.sheet.trait(trait)
            detail = {
                "removed": {
                    "kind": "background",
                    "name": background_trait.name,
                    "dots": background_trait.dots,
                }
            }
        receipt = await asyncio.to_thread(
            mutate.remove_trait, character.sheet, trait
        )
        updated = await asyncio.to_thread(
            _record, character, receipt, summary=receipt.lines[0], detail=detail
        )
    except (
        SeatsError,
        CharacterError,
        CharacterConflict,
        MutationError,
        OSError,
        ValueError,
    ) as error:
        await _fail(interaction, error)
        return
    await _refresh_creation(interaction, updated)
    await interaction.followup.send(f"{_clip_text(str(receipt))}\n-# /undo restores it")


@command(name="pool", description="Set a character's freebie or xp balance (correction).")
@app_commands.describe(
    pool="Which currency",
    amount="What the balance should be",
    target="Whose sheet (default: yours; others need edit_any_sheet)",
)
@app_commands.choices(
    pool=[
        app_commands.Choice(name="freebies — creation points", value="freebies"),
        app_commands.Choice(name="xp — experience", value="xp"),
    ]
)
async def pool(
    interaction: discord.Interaction,
    pool: str,
    amount: int,
    target: str | None = None,
) -> None:
    """Correct a balance: imported sheets arrive with 0, and experience is earned with /mission."""
    await interaction.response.defer(thinking=True)
    try:
        _, character = await asyncio.to_thread(_sheet_owner, interaction, target)
        before = getattr(character.sheet, pool)
        receipt = await asyncio.to_thread(
            mutate.set_pool, character.sheet, pool, amount
        )
        updated = await asyncio.to_thread(
            _record,
            character,
            receipt,
            summary=receipt.lines[0],
            detail={"pool": pool, "before": before},
        )
    except (SeatsError, CharacterError, CharacterConflict, MutationError, OSError) as error:
        await _fail(interaction, error)
        return
    await _refresh_creation(interaction, updated)
    await interaction.followup.send(
        f"{_clip_text(str(receipt))}\n-# {_pools_line(receipt.sheet)} · /undo reverses it"
    )


class ThreadUnavailable(SeatsError):
    """The bot cannot open a private thread, so a build cannot run."""


CREATION_KEY = "creation"
DEFAULT_QUESTIONNAIRE_PATH = Path("examples/house_games/interview.json")


def _creation_state(character: Character) -> dict:
    raw = character.sheet.meta.get(CREATION_KEY)
    return dict(raw) if isinstance(raw, dict) else {}


def _build_thread_name(interaction: discord.Interaction, character: str) -> str:
    """``noodle · Ailis Vane`` — who and which character, in the thread list."""
    who = getattr(interaction.user, "display_name", "") or "player"
    return f"{who} · {character}"


async def _create_build_thread(interaction: discord.Interaction, character: str):
    """Open the private thread a build lives in.

    A thread rather than a DM: guild-scoped slash commands work in threads, so nothing has to
    be published globally (which takes up to an hour), a GM with *Manage Threads* can read a
    build, and one thread per character is itself the record — no divider needed to separate
    successive builds.

    Every failure is logged with its traceback and turned into one sentence the player can act
    on, because the usual causes are permissions, not logic.
    """
    channel = getattr(interaction, "channel", None)
    if interaction.guild is None or channel is None or not hasattr(channel, "create_thread"):
        LOGGER.warning(
            "build thread: no guild channel (guild=%s channel=%s)",
            getattr(interaction.guild, "id", None),
            getattr(channel, "id", None),
        )
        raise ThreadUnavailable(
            "builds live in a private thread, so run /create in a server text channel "
            "(not a DM). Nothing was created."
        )
    name = _build_thread_name(interaction, character)
    try:
        thread = await channel.create_thread(
            name=name,
            type=discord.ChannelType.private_thread,
            invitable=False,
            auto_archive_duration=1440,
            reason=f"ttrpg-chatbots: build {character}",
        )
    except discord.Forbidden as error:
        LOGGER.exception("build thread: forbidden creating a thread in %s", channel.id)
        raise ThreadUnavailable(
            "I cannot create a private thread here: I need **Manage Threads** and "
            "**Send Messages in Threads** in this channel. Nothing was created."
        ) from error
    except discord.HTTPException as error:
        LOGGER.exception("build thread: Discord refused a thread in %s", channel.id)
        raise ThreadUnavailable(
            f"Discord refused to create a thread here ({error.status} {error.text}). "
            "Some channel types cannot host threads. Nothing was created."
        ) from error
    LOGGER.info("build thread: created %s (%s) for %s", thread.id, name, interaction.user.id)
    try:
        await thread.add_user(interaction.user)
    except (discord.Forbidden, discord.HTTPException):
        # The creator is normally added by Discord, so this is a fallback, not a requirement.
        LOGGER.warning("build thread: could not add %s to %s", interaction.user.id, thread.id)
    return thread


async def _creation_channel(interaction: discord.Interaction, character):
    """The thread this character's build lives in: reopened if known, created if not.

    The thread id is stored in the character, so a restart (or a bot upgrade) reopens the same
    thread instead of littering the channel with a second one.
    """
    state = _creation_state(character)
    thread_id = state.get("thread")
    if thread_id:
        try:
            channel = interaction.client.get_channel(thread_id)
            if channel is None:
                channel = await interaction.client.fetch_channel(thread_id)
            return channel
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            LOGGER.warning(
                "build thread: %s is gone or unreadable; opening a new one", thread_id
            )
    return await _create_build_thread(interaction, character.name)


async def _remove_thread(thread) -> None:
    """Best effort: delete a thread we opened for a build that then failed."""
    if thread is None:
        return
    try:
        await thread.delete()
        LOGGER.info("build thread: removed %s after a failed start", getattr(thread, "id", "?"))
    except (discord.Forbidden, discord.NotFound, discord.HTTPException):
        LOGGER.warning("build thread: could not remove %s", getattr(thread, "id", "?"))



async def _refresh_creation(interaction: discord.Interaction, character: Character) -> None:
    """Edit the two creation embeds in place. Silent when there is no build in progress."""
    state = _creation_state(character)
    if not state:
        return
    quiz = _to_embed(questionnaire_embed(character, page=int(state.get("page", 0))))
    sheet = _to_embed(build_embed(character))
    messages = state.get("messages") or []
    try:
        channel = await _creation_channel(interaction, character)
        if not state.get("thread"):
            # First post in a freshly created thread: remember where it is before writing.
            state["thread"] = getattr(channel, "id", None)
        if len(messages) != 2:
            # One thread per character, so the thread *is* the divider — it is named for the
            # player and the character, and nothing above it belongs to this build. The guide
            # goes first, then the two panels.
            from ttrpg_chatbots.help import help_spec

            await channel.send(embed=_to_embed(help_spec()))
            first = await channel.send(embed=quiz)
            second = await channel.send(embed=sheet)
            state["messages"] = [first.id, second.id]
            updated = replace(
                character,
                sheet=replace(
                    character.sheet, meta={**character.sheet.meta, CREATION_KEY: state}
                ),
            )
            _character_store().save(updated, expect_revision=character.revision)
            return
        await (await channel.fetch_message(messages[0])).edit(embed=quiz)
        await (await channel.fetch_message(messages[1])).edit(embed=sheet)
    except (discord.NotFound, discord.Forbidden, discord.HTTPException) as error:
        # The edit that triggered this has already been saved. A closed thread or a deleted
        # panel must not undo it, but it does stop the panels tracking the build.
        LOGGER.warning("could not refresh the creation embeds: %s", error)


def _questionnaire_file() -> Path:
    return Path(os.environ.get("TTRPG_QUESTIONNAIRE", str(DEFAULT_QUESTIONNAIRE_PATH)))


def _precheck_creation(name: str) -> str:
    """Everything that can be refused *without* touching Discord or the store."""
    cleaned = " ".join(name.split())
    if not cleaned:
        raise CharacterError("a character needs a name")
    if _character_store().exists(slug_for(cleaned)):
        raise CharacterError(
            f"there is already a character called {cleaned!r}; /characters lists yours"
        )
    return cleaned


def _begin_creation(
    interaction: discord.Interaction, name: str, thread_id: int | None = None
) -> Character:
    """Draft + seat, in one step, refusing anything that would overwrite a character."""
    cleaned = _precheck_creation(name)
    store = _character_store()
    identifier = slug_for(cleaned)
    book = _seatbook()
    questionnaire = load_questionnaire(_questionnaire_file())
    character = Character(
        sheet=blank_sheet(cleaned),
        interview=blank_interview(questionnaire, cleaned),
        build=Build(),
        created=now_utc(),
    )
    character = character.record("created", f"began building {cleaned}", at=now_utc())
    state: dict = {"messages": [], "page": 0}
    if thread_id is not None:
        state["thread"] = thread_id
    character = replace(
        character,
        sheet=replace(
            character.sheet,
            meta={**character.sheet.meta, CREATION_KEY: state},
        ),
    )
    owner = interaction.user.id
    seat = Seat(
        id=_seat_id(interaction, book),
        kind=KIND_HUMAN,
        character=identifier,
        discord_id=owner,
        permissions=frozenset({PERMISSION_EDIT_OWN_SHEET}),
        meta={"name": interaction.user.display_name},
    )
    # One character plays at a time: the others stay on file, inactive.
    others = tuple(
        replace(existing, active=False) if existing.discord_id == owner else existing
        for existing in book
    )
    # Validate the seat *before* the character is written, so a refusal leaves nothing behind.
    updated_book = SeatBook((*others, seat))
    store.save(character)
    try:
        save_seats(updated_book, _seats_path())
    except (SeatsError, OSError):
        # Never leave an orphan character that no seat can reach.
        store.delete(identifier)
        raise
    return character


@command(name="create", description="Start building a character from scratch.")
@app_commands.describe(name="The character's name")
async def create(interaction: discord.Interaction, name: str) -> None:
    """Create the draft, open the build thread, and seat the player."""
    await interaction.response.defer(thinking=True, ephemeral=True)
    thread = None
    try:
        # Refuse bad requests before touching Discord, so a doomed /create opens no thread.
        cleaned = await asyncio.to_thread(_precheck_creation, name)
        # Creating the thread *is* the permission check: if this works, the surface exists.
        thread = await _create_build_thread(interaction, cleaned)
        try:
            character = await asyncio.to_thread(
                _begin_creation, interaction, name, thread.id
            )
        except Exception:
            # A character without a thread is unreachable; do not leave one behind.
            await _remove_thread(thread)
            raise
    except ThreadUnavailable as error:
        LOGGER.warning("cannot open a build thread: %s", error)
        await _fail(interaction, error)
        return
    except (SeatsError, CharacterError, SheetError, OSError) as error:
        await _fail(interaction, error)
        return
    await _refresh_creation(interaction, character)
    await interaction.followup.send(
        f"**{character.name}** started in {getattr(thread, 'mention', 'the thread')} · "
        f"seat `{character.id}`\n"
        "-# /answer n text · /spend · /flaw · /page · /finish",
        ephemeral=True,
    )


@command(name="help", description="The command guide, grouped by task.")
async def help_command(interaction: discord.Interaction) -> None:
    """Show the guide. Also posted at the top of every build thread."""
    from ttrpg_chatbots.help import help_spec

    embed = _to_embed(help_spec())
    if interaction.guild is None:
        await interaction.response.send_message(embed=embed)
    else:
        await interaction.response.send_message(embed=embed, ephemeral=True)


@command(
    name="testthread",
    description="[temporary] Make a private thread and try posting the build surface there.",
)
async def testthread(interaction: discord.Interaction) -> None:
    """Probe whether a private thread can host a build, so we can avoid publishing globally.

    Temporary on purpose: it exists to answer one question — can the bot create a private
    thread here, add the player to it, and post into it? Every step is logged at INFO and
    every failure at ERROR with the traceback, so the log says exactly which step Discord
    refused and why.
    """
    await interaction.response.defer(thinking=True, ephemeral=True)
    channel = interaction.channel
    guild = interaction.guild
    LOGGER.info(
        "testthread: guild=%s channel=%s channel_type=%s",
        getattr(guild, "id", None),
        getattr(channel, "id", None),
        getattr(channel, "type", None),
    )
    if guild is None:
        # A DM has no threads: this is the case we are trying to avoid relying on.
        LOGGER.warning("testthread: called outside a guild (channel=%s)", channel)
        await interaction.followup.send(
            "this probe needs a server channel: run it in the text channel where the "
            "thread should live, not in a DM",
            ephemeral=True,
        )
        return

    name = f"{interaction.user.display_name}'s build (probe)"
    try:
        thread = await channel.create_thread(
            name=name,
            type=discord.ChannelType.private_thread,
            invitable=False,
            auto_archive_duration=1440,
            reason="ttrpg-chatbots: private build surface probe",
        )
    except Exception as error:  # noqa: BLE001 - the reply must survive any Discord failure
        LOGGER.exception(
            "testthread: create_thread failed on channel %s (%s)",
            getattr(channel, "id", None),
            type(channel).__name__,
        )
        await interaction.followup.send(
            f"**create_thread failed**: {type(error).__name__}: {error}\n"
            "-# logged with a traceback; the bot needs Manage Threads and a channel that "
            "supports threads",
            ephemeral=True,
        )
        return
    LOGGER.info(
        "testthread: created private thread %s (%s)",
        getattr(thread, "id", None),
        getattr(thread, "name", "unnamed"),
    )

    added = "not needed"
    try:
        await thread.add_user(interaction.user)
        added = "yes"
    except Exception as error:  # noqa: BLE001 - report, do not abort the probe
        added = f"no ({type(error).__name__}: {error})"
        LOGGER.exception("testthread: add_user failed on thread %s", thread.id)

    try:
        first = await thread.send(
            embed=discord.Embed(
                title="━━━━━━━━━━  PROBE  ━━━━━━━━━━",
                description="If you can read this in the thread, the surface works.",
                colour=discord.Colour(0x4F545C),
            )
        )
        LOGGER.info("testthread: posted %s into thread %s", first.id, thread.id)
    except Exception as error:  # noqa: BLE001 - report, do not abort the probe
        LOGGER.exception("testthread: send failed on thread %s", thread.id)
        await interaction.followup.send(
            f"thread {thread.mention} was created but I could not post in it: "
            f"{type(error).__name__}: {error}",
            ephemeral=True,
        )
        return

    await interaction.followup.send(
        f"thread works: {thread.mention}\n"
        f"-# id {thread.id} · added you: {added} · see #bot-log for the step trace",
        ephemeral=True,
    )


@command(name="willpower", description="Spend Willpower without rolling.")
@app_commands.describe(points="How many points (default 1)", target="Someone else's character")
async def willpower(
    interaction: discord.Interaction, points: int = 1, target: str = ""
) -> None:
    """Willpower pays for things that are not a test: an extra action, a steady nerve."""
    await interaction.response.defer(thinking=True)
    try:
        _, character = await asyncio.to_thread(_sheet_owner, interaction, target or None)
        from ttrpg_chatbots.sheetportal.checks import spend_willpower

        before = character.sheet.willpower_remaining
        if before is None:
            before = character.sheet.willpower
        sheet = await asyncio.to_thread(spend_willpower, character.sheet, points)
        receipt = mutate.Receipt(
            sheet=sheet,
            lines=(
                f"spent {points} Willpower "
                f"({sheet.willpower_remaining}/{sheet.willpower} left)",
            ),
        )
        updated = await asyncio.to_thread(
            _record,
            character,
            receipt,
            summary=f"spent {points} Willpower",
            detail={"willpower": True, "points": points, "before": before},
        )
    except Exception as error:  # noqa: BLE001 - one friendly failure line for the user
        await _fail(interaction, error)
        return
    await _refresh_creation(interaction, updated)
    await interaction.followup.send(f"{_clip_text(str(receipt))}\n-# /undo reverses it")


@command(name="skip", description="Mark a question as deliberately unanswered.")
@app_commands.describe(number="Which question, numbered from 1")
async def skip(interaction: discord.Interaction, number: int) -> None:
    """Some questions a character genuinely has no answer to; say so explicitly.

    The answer becomes "(skipped)" rather than staying blank, so /finish can tell the
    difference between "not answered yet" and "answered with nothing".
    """
    await interaction.response.defer(thinking=True)
    try:
        _, character = await asyncio.to_thread(_own_character, interaction)
        updated = await asyncio.to_thread(
            character.with_answer, number, SKIPPED, at=now_utc()
        )
        await asyncio.to_thread(_save, character, updated)
    except (SeatsError, CharacterError, CharacterConflict, OSError, IndexError, ValueError) as e:
        await _fail(interaction, e)
        return
    await _refresh_creation(interaction, updated)
    remaining = updated.interview.next_unanswered
    hint = f"next: question {remaining}" if remaining else "all answered"
    await interaction.followup.send(
        f"skipped **{number}** · {updated.interview.answered}/{updated.interview.total} "
        f"answered\n-# {hint} · answer it later with /answer {number} text:…"
    )


@command(name="goto", description="Jump to a question and read it.")
@app_commands.describe(number="Which question, numbered from 1")
async def goto(interaction: discord.Interaction, number: int) -> None:
    """Show one question, turn to its page, and say how to answer it."""
    await interaction.response.defer(thinking=True)
    try:
        _, character = await asyncio.to_thread(_own_character, interaction)
        interview = character.interview
        if interview is None:
            raise CharacterError(f"{character.name} has no interview")
        question = interview.at(number)
        state = _creation_state(character) or {"messages": [], "page": 0}
        state["page"] = (number - 1) // QUESTIONS_PER_PAGE
        updated = replace(
            character,
            sheet=replace(character.sheet, meta={**character.sheet.meta, CREATION_KEY: state}),
        )
        await asyncio.to_thread(_save, character, updated)
    except (SeatsError, CharacterError, CharacterConflict, OSError, IndexError, ValueError) as e:
        await _fail(interaction, e)
        return
    await _refresh_creation(interaction, updated)
    answered = question.answer if question.answered else "_unanswered_"
    await interaction.followup.send(
        _clip_text(
            f"**{number}/{interview.total}** · {question.section}\n> {question.prompt}\n"
            f"{answered}\n-# /answer {number} text:… to write it, /skip {number} to pass"
        )
    )


@command(name="panel", description="Re-post the questionnaire and sheet panels.")
async def panel(interaction: discord.Interaction) -> None:
    """Recover from a deleted panel: post a fresh pair and track those instead."""
    await interaction.response.defer(thinking=True, ephemeral=True)
    try:
        _, character = await asyncio.to_thread(_own_character, interaction)
        state = _creation_state(character)
        if not state:
            raise CharacterError("no build in progress; start one with /create")
        state["messages"] = []
        updated = replace(
            character,
            sheet=replace(character.sheet, meta={**character.sheet.meta, CREATION_KEY: state}),
        )
        await asyncio.to_thread(_save, character, updated)
    except (SeatsError, CharacterError, CharacterConflict, OSError) as error:
        await _fail(interaction, error)
        return
    await _refresh_creation(interaction, updated)
    await interaction.followup.send("panels re-posted", ephemeral=True)


@command(name="discard", description="Throw away a draft you do not want.")
@app_commands.describe(confirm="Type the character's name to confirm")
async def discard(interaction: discord.Interaction, confirm: str) -> None:
    """Abandon a build. Deliberately awkward: the name has to be typed out."""
    await interaction.response.defer(thinking=True, ephemeral=True)
    try:
        seat, character = await asyncio.to_thread(_own_character, interaction)
        if character.sealed:
            raise CharacterError(
                f"{character.name} is sealed; /discard is for drafts. "
                "A finished character is retired, not deleted"
            )
        if normalise(confirm) != normalise(character.name):
            raise CharacterError(
                f"to discard {character.name!r}, confirm name:{character.name}"
            )
        await asyncio.to_thread(_character_store().delete, character.id)
        remaining = tuple(other for other in _seatbook() if other.id != seat.id)
        await asyncio.to_thread(save_seats, SeatBook(remaining), _seats_path())
        thread_id = _creation_state(character).get("thread")
        if thread_id:
            # The thread held only this character; leaving it behind would be litter.
            try:
                thread = interaction.client.get_channel(thread_id)
                if thread is not None:
                    await thread.delete()
                    LOGGER.info("discard: removed build thread %s", thread_id)
            except (discord.Forbidden, discord.NotFound, discord.HTTPException):
                LOGGER.warning("discard: could not remove thread %s", thread_id)
    except (SeatsError, CharacterError, CharacterConflict, OSError) as error:
        await _fail(interaction, error)
        return
    await interaction.followup.send(
        f"discarded {character.name}. /create starts a new one.", ephemeral=True
    )


@command(name="page", description="Move between questionnaire pages.")
@app_commands.describe(number="Which page (1-based)")
async def page(interaction: discord.Interaction, number: int = 1) -> None:
    """Twelve questions per page, so the embed stays readable."""
    await interaction.response.defer(thinking=True, ephemeral=True)
    try:
        _, character = await asyncio.to_thread(_own_character, interaction)
        state = _creation_state(character)
        if not state:
            raise CharacterError("no build in progress; start one with /create")
        state["page"] = max(0, number - 1)
        updated = replace(
            character,
            sheet=replace(
                character.sheet, meta={**character.sheet.meta, CREATION_KEY: state}
            ),
            revision=character.revision + 1,
        )
        await asyncio.to_thread(
            _character_store().save, updated, expect_revision=character.revision
        )
    except (SeatsError, CharacterError, CharacterConflict, OSError) as error:
        await _fail(interaction, error)
        return
    await _refresh_creation(interaction, updated)
    await interaction.followup.send(f"page {number}", ephemeral=True)


@command(name="flaw", description="Take a Flaw: it pays freebie points.")
@app_commands.describe(name="Enemy, Phobia, Dark Secret…", rating="How many points")
async def flaw(interaction: discord.Interaction, name: str, rating: int = 1) -> None:
    """Flaws come before freebies: the pool is 15 plus whatever they are worth."""
    await interaction.response.defer(thinking=True)
    try:
        _, character = await asyncio.to_thread(_sheet_owner, interaction, None)
        receipt = await asyncio.to_thread(
            mutate.add_flaw, character.sheet, name, rating=rating, catalogue=_catalogue()
        )
        updated = await asyncio.to_thread(
            _record,
            character,
            receipt,
            summary=receipt.lines[0],
            detail={"added_flaw": " ".join(name.split()), "rating": rating},
        )
    except (SeatsError, CharacterError, CharacterConflict, MutationError, OSError) as error:
        await _fail(interaction, error)
        return
    await _refresh_creation(interaction, updated)
    await interaction.followup.send(f"{_clip_text(str(receipt))}\n-# /undo reverses it")


@command(name="merit", description="Take a Merit: it costs freebies at the book's price.")
@app_commands.describe(
    name="Ambidextrous, Natural Linguist… (custom names welcome)",
    points="Leave blank for a fixed-cost merit; required for a rated one or a custom merit",
    target="Someone else's character (needs edit_any_sheet)",
)
async def merit(
    interaction: discord.Interaction, name: str, points: int | None = None, target: str = ""
) -> None:
    """Costs come from the merits-and-flaws index; a custom merit names its own price."""
    await interaction.response.defer(thinking=True)
    try:
        _, character = await asyncio.to_thread(_sheet_owner, interaction, target or None)
        receipt = await asyncio.to_thread(
            mutate.add_merit,
            character.sheet,
            name,
            points=points,
            catalogue=_catalogue(),
        )
        updated = await asyncio.to_thread(
            _record,
            character,
            receipt,
            summary=receipt.lines[0],
            detail={"added_merit": " ".join(name.split()), "paid": points or 0},
        )
    except (SeatsError, CharacterError, CharacterConflict, MutationError, OSError) as error:
        await _fail(interaction, error)
        return
    await _refresh_creation(interaction, updated)
    await interaction.followup.send(f"{_clip_text(str(receipt))}\n-# /undo reverses it")


@command(name="unmerit", description="Drop a Merit and refund its points.")
@app_commands.describe(name="The merit to remove", target="Someone else's character")
async def unmerit(interaction: discord.Interaction, name: str, target: str = "") -> None:
    await interaction.response.defer(thinking=True)
    try:
        _, character = await asyncio.to_thread(_sheet_owner, interaction, target or None)
        receipt = await asyncio.to_thread(mutate.remove_merit, character.sheet, name)
        paid = int(receipt.spent.get("freebies", 0)) or 1
        updated = await asyncio.to_thread(
            _record,
            character,
            receipt,
            summary=receipt.lines[0],
            detail={"removed_merit": " ".join(name.split()), "paid": paid},
        )
    except (SeatsError, CharacterError, CharacterConflict, MutationError, OSError) as error:
        await _fail(interaction, error)
        return
    await _refresh_creation(interaction, updated)
    await interaction.followup.send(f"{_clip_text(str(receipt))}\n-# /undo reverses it")


@command(name="lookup", description="What does a merit or flaw cost in the books?")
@app_commands.describe(
    name="Part of a name; blank lists what exists",
    kind="merit or flaw",
)
async def lookup(interaction: discord.Interaction, name: str = "", kind: str = "") -> None:
    """A read-only glance at the index, so a price never has to be guessed."""
    await interaction.response.defer(thinking=True)
    catalogue = _catalogue()
    wanted = kind.strip().lower() or None
    if wanted not in (None, "merit", "flaw"):
        await interaction.followup.send("kind must be `merit` or `flaw`")
        return
    if not name.strip():
        counts = {k: len(catalogue.names(k)) for k in ("merit", "flaw")}
        await interaction.followup.send(
            f"the index holds {counts['merit']} merits and {counts['flaw']} flaws — "
            "give part of a name to search, e.g. `/lookup name:ambidex`"
        )
        return
    entry = catalogue.lookup(name, wanted)
    if entry is not None:
        await interaction.followup.send(entry.describe())
        return
    matches = catalogue.search(name, wanted)
    if not matches:
        await interaction.followup.send(
            f"nothing in the index matches {name!r}; a custom merit is still legal — "
            "`/merit name:… points:…` prices it yourself"
        )
        return
    lines = [entry.describe() for entry in matches[:10]]
    await interaction.followup.send(_clip_text("\n".join(lines)))



@command(name="build", description="What creation budgets are left.")
async def build_status(interaction: discord.Interaction) -> None:
    """The one screen that says whether the character is legal to submit."""
    await interaction.response.defer(thinking=True, ephemeral=True)
    try:
        _, character = await asyncio.to_thread(_own_character, interaction)
        if character.build is None:
            raise CharacterError("this character has no creation budgets")
        left = build_remaining(character.sheet, character.build)
        problems = build_problems(character.sheet, character.build)
        lines = [
            f"{group}: {value} left"
            for section in left.values()
            for group, value in section.items()
        ]
        if character.interview is not None:
            lines.append(
                f"answers: {character.interview.answered}/{character.interview.total}"
            )
        lines.extend(problems or ["every budget is spent exactly"])
    except (SeatsError, CharacterError, OSError) as error:
        await _fail(interaction, error)
        return
    await interaction.followup.send(_clip_text("\n".join(lines)), ephemeral=True)


def _submit(character: Character) -> Character:
    """Refuse unless every answer and every budget is exactly right."""
    if character.build is None:
        raise CharacterError("this character has no creation budgets to submit")
    blocking = list(build_problems(character.sheet, character.build))
    interview = character.interview
    if interview is None:
        blocking.append("no questionnaire attached")
    elif interview.missing:
        for question in interview.missing[:5]:
            blocking.append(f"unanswered: {question.prompt[:60]}")
        if len(interview.missing) > 5:
            blocking.append(f"… and {len(interview.missing) - 5} more unanswered")
    if blocking:
        raise CharacterError("not ready to submit:" + chr(10) + chr(10).join(blocking[:12]))
    sealed = character.seal(at=now_utc())
    meta = {key: value for key, value in sealed.sheet.meta.items() if key != CREATION_KEY}
    return replace(sealed, build=None, sheet=replace(sealed.sheet, meta=meta))


@command(name="finish", description="Submit a build: seal it if it is legal.")
async def finish(interaction: discord.Interaction) -> None:
    """Nothing is final until this: exact budgets, every answer, then seal."""
    await interaction.response.defer(thinking=True)
    try:
        _, character = await asyncio.to_thread(_own_character, interaction)
        sealed = await asyncio.to_thread(_submit, character)
        await asyncio.to_thread(_save, character, sealed)
    except (SeatsError, CharacterError, CharacterConflict, OSError) as error:
        await _fail(interaction, error)
        return
    await interaction.followup.send(
        f"**{sealed.name}** submitted and sealed · revision {sealed.revision}\n"
        "-# budgets archived; later changes are amendments (/unlock)"
    )


async def _own_character_choices(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    """Autocomplete only the caller's own characters."""
    try:
        seats = _seatbook().all_for_discord(getattr(interaction.user, "id", None))
    except Exception:  # noqa: BLE001 - autocomplete must never fail the interaction
        return []
    wanted = (current or "").lower()
    return [
        app_commands.Choice(name=_display_for(seat.character), value=seat.character)
        for seat in seats
        if wanted in seat.character.lower() or wanted in _display_for(seat.character).lower()
    ][:25]


@command(name="characters", description="List your characters and which one is active.")
async def characters(interaction: discord.Interaction) -> None:
    """A player may own several characters; one of them is the one being played."""
    await interaction.response.defer(thinking=True, ephemeral=True)
    seats = _seatbook().all_for_discord(getattr(interaction.user, "id", None))
    if not seats:
        await interaction.followup.send(
            "you have no characters yet; /create starts one", ephemeral=True
        )
        return
    lines = []
    for seat in sorted(seats, key=lambda item: (not item.active, item.character)):
        marker = "**active**" if seat.active else "inactive"
        lines.append(f"{marker} · {_display_for(seat.character)} · seat `{seat.id}`")
    await interaction.followup.send(
        _clip_text("\n".join(lines) + "\n-# /play character:… to switch"), ephemeral=True
    )


@command(name="play", description="Switch which of your characters is active.")
@app_commands.describe(character="Which of your characters to play")
@app_commands.autocomplete(character=_own_character_choices)
async def play(interaction: discord.Interaction, character: str) -> None:
    """Switching is a seat change, not a sheet edit: nothing about either character moves."""
    await interaction.response.defer(thinking=True, ephemeral=True)
    try:
        seat = await asyncio.to_thread(_activate, interaction, character)
    except (SeatsError, OSError) as error:
        await _fail(interaction, error)
        return
    await interaction.followup.send(
        f"now playing **{_display_for(seat.character)}** · seat `{seat.id}`", ephemeral=True
    )


def _display_for(character_id: str) -> str:
    """The character's own name, falling back to the id when the file is missing."""
    try:
        return _character_store().load(character_id).name
    except (CharacterError, OSError):
        return character_id


def _activate(interaction: discord.Interaction, character: str):
    book = _seatbook()
    chosen = book.for_character(character)
    owner = getattr(interaction.user, "id", None)
    if chosen is None:
        mine = [seat.character for seat in book.all_for_discord(owner)]
        raise SeatsError(
            f"no character called {character!r}; yours: {', '.join(mine) or 'none'}"
        )
    if chosen.discord_id != owner:
        raise SeatsError(f"{character!r} is not yours")
    save_seats(book.activate(chosen.id), _seats_path())
    return chosen


@command(name="budget", description="Choose which group gets 7, 5 and 3 (or 13, 9 and 5).")
@app_commands.describe(
    section="Attributes or abilities",
    seven="The group that gets the largest budget",
    five="The group that gets the middle budget",
    three="The group that gets the smallest budget",
)
@app_commands.choices(
    section=[
        app_commands.Choice(name="attributes — 7 / 5 / 3", value="attributes"),
        app_commands.Choice(name="abilities — 13 / 9 / 5", value="abilities"),
    ],
    seven=[
        app_commands.Choice(name="Physical", value="Physical"),
        app_commands.Choice(name="Social", value="Social"),
        app_commands.Choice(name="Mental", value="Mental"),
        app_commands.Choice(name="Talents", value="talent"),
        app_commands.Choice(name="Skills", value="skill"),
        app_commands.Choice(name="Knowledges", value="knowledge"),
    ],
    five=[
        app_commands.Choice(name="Physical", value="Physical"),
        app_commands.Choice(name="Social", value="Social"),
        app_commands.Choice(name="Mental", value="Mental"),
        app_commands.Choice(name="Talents", value="talent"),
        app_commands.Choice(name="Skills", value="skill"),
        app_commands.Choice(name="Knowledges", value="knowledge"),
    ],
    three=[
        app_commands.Choice(name="Physical", value="Physical"),
        app_commands.Choice(name="Social", value="Social"),
        app_commands.Choice(name="Mental", value="Mental"),
        app_commands.Choice(name="Talents", value="talent"),
        app_commands.Choice(name="Skills", value="skill"),
        app_commands.Choice(name="Knowledges", value="knowledge"),
    ],
)
async def budget(
    interaction: discord.Interaction,
    section: str,
    seven: str,
    five: str,
    three: str,
) -> None:
    """Which group gets which budget is the player's choice, not a fixed table."""
    await interaction.response.defer(thinking=True, ephemeral=True)
    try:
        _, character = await asyncio.to_thread(_own_character, interaction)
        if character.build is None:
            raise CharacterError("this character has no creation budgets")
        assigned = await asyncio.to_thread(
            character.build.assigned, section, (seven, five, three)
        )
        # Re-assigning can make an existing spend illegal; say so rather than silently
        # leaving a character that cannot be submitted.
        over = [
            line
            for line in build_problems(character.sheet, assigned)
            if "over budget" in line
        ]
        if over:
            raise MutationError(
                "that assignment does not fit what is already spent: " + "; ".join(over)
            )
        updated = character.with_build(assigned)
        await asyncio.to_thread(
            _character_store().save, updated, expect_revision=character.revision
        )
    except (SeatsError, CharacterError, CharacterConflict, MutationError, OSError) as error:
        await _fail(interaction, error)
        return
    await _refresh_creation(interaction, updated)
    await interaction.followup.send(
        _clip_text(_assignment_text(updated)), ephemeral=True
    )


def _assignment_text(character: Character) -> str:
    """The chosen assignment, written the way the rules write it."""
    build = character.build
    if build is None:
        return "no creation budgets"
    attributes = " · ".join(f"{g} {b}" for g, b in build.attributes.items())
    abilities = " · ".join(f"{g} {b}" for g, b in build.abilities.items())
    return f"attributes: {attributes}\nabilities: {abilities}"


@command(name="options", description="What your next point would cost.")
@app_commands.describe(
    trait="One trait to explain (default: everything you can raise)",
    pool="Price it in freebies (default) or xp",
)
@app_commands.autocomplete(trait=_trait_choices)
async def options(
    interaction: discord.Interaction, trait: str | None = None, pool: str = "freebies"
) -> None:
    """Plan without committing: costs, caps, and what is already maxed."""
    await interaction.response.defer(thinking=True)
    try:
        _, character = await asyncio.to_thread(_own_character, interaction)
        sheet = character.sheet
        if trait:
            # One trait answers the question a player actually asked.
            kind = mutate.resolve_kind(sheet, trait)
            current = current_rating(sheet, kind, trait)
            ceiling = mutate.cap_for(sheet, kind, trait)
            text = mutate.explain(sheet, trait)
            if current < ceiling:
                cost = mutate.cost_of(kind, current, current + 1, pool=pool)
                text += f"\nnext point: {cost} {pool}"
            else:
                text += "\n-# already at its cap"
        else:
            listed = mutate.options(sheet, pool=pool)
            text = "\n".join(listed) or "nothing can be raised from this sheet"
            text += f"\n-# {_pools_line(sheet)}"
    except (SeatsError, CharacterError, MutationError, OSError) as error:
        await _fail(interaction, error)
        return
    await interaction.followup.send(_clip_text(text))


def _target_character(
    interaction: discord.Interaction, target: str | None
) -> tuple[Seat, Character]:
    """Resolve whose character to change: your own, unless your seat may touch others."""
    seat, own = _own_character(interaction)
    if not target or target.strip().lower() in {seat.character.lower(), seat.id.lower()}:
        return seat, own
    if not seat.may(PERMISSION_AWARD_GIFTS):
        raise SeatsError(
            f"{target!r} is not your character; awarding to others needs "
            f"{PERMISSION_AWARD_GIFTS!r}"
        )
    return seat, _character_store().load(target.strip())


def _view_target(interaction: discord.Interaction, target: str | None) -> tuple[Seat, Character]:
    """Resolve whose character to *read*: your own, or any with permission to view."""
    seat, own = _own_character(interaction)
    if not target or target.strip().lower() in {seat.character.lower(), seat.id.lower()}:
        return seat, own
    if not seat.may(PERMISSION_VIEW_ANY_SHEET):
        raise SeatsError(
            f"{target!r} is not your character; viewing others needs "
            f"{PERMISSION_VIEW_ANY_SHEET!r}"
        )
    return seat, _character_store().load(target.strip())


def _save(character: Character, updated: Character) -> Character:
    """Write through the store as a compare-and-swap against what was loaded."""
    _character_store().save(updated, expect_revision=character.revision)
    return updated


@command(name="gift", description="Award a Gift (the Harbinger's price for a Game).")
@app_commands.describe(
    name="The Gift: any power, ability or technique the table allows",
    rating="Levels, where the source has them (blank for a flat technique)",
    description="Quick reference, for gifts that are described rather than rated",
    target="Whose character (default: yours)",
)
async def gift(
    interaction: discord.Interaction,
    name: str,
    rating: int | None = None,
    description: str = "",
    target: str | None = None,
) -> None:
    """Record a Gift. Gifts are awarded, never bought, so this costs nothing."""
    await interaction.response.defer(thinking=True)
    try:
        character, receipt = await asyncio.to_thread(
            _award, interaction, name, rating, description, target
        )
    except (SeatsError, CharacterError, CharacterConflict, MutationError, OSError) as error:
        await _fail(interaction, error)
        return
    await _refresh_creation(interaction, character)
    await interaction.followup.send(f"**{character.name}** {_clip_text(str(receipt))}")


def _award(interaction, name, rating, description, target):
    seat, character = _target_character(interaction, target)
    if not seat.may(PERMISSION_AWARD_GIFTS):
        raise SeatsError(
            f"seat {seat.id!r} may not award Gifts; add {PERMISSION_AWARD_GIFTS!r}"
        )
    receipt = mutate.award_gift(
        character.sheet, name, rating=rating, description=description
    )
    updated = character.with_sheet(receipt.sheet, summary=f"gained {name}")
    return _save(character, updated), receipt


@command(name="mission", description="Settle a Game: experience, and a Gift on a win.")
@app_commands.describe(
    outcome="Did they win, or lose but survive?",
    gift="The Gift won (leave blank and it is recorded as owed)",
    rating="Levels on that Gift",
    target="Whose character (default: yours)",
)
@app_commands.choices(
    outcome=[
        app_commands.Choice(name="win — 10 xp and a Gift", value="win"),
        app_commands.Choice(name="loss — 5 xp, no Gift", value="loss"),
    ]
)
async def mission(
    interaction: discord.Interaction,
    outcome: str,
    gift: str | None = None,
    rating: int | None = None,
    target: str | None = None,
) -> None:
    """Record one House Game's reward."""
    await interaction.response.defer(thinking=True)
    try:
        character, receipt = await asyncio.to_thread(
            _settle, interaction, outcome, gift, rating, target
        )
    except (SeatsError, CharacterError, CharacterConflict, MutationError, OSError) as error:
        await _fail(interaction, error)
        return
    await interaction.followup.send(f"**{character.name}** {_clip_text(str(receipt))}")


def _settle(interaction, outcome, name, rating, target):
    seat, character = _target_character(interaction, target)
    if not seat.may(PERMISSION_AWARD_GIFTS):
        raise SeatsError(
            f"seat {seat.id!r} may not settle Games; add {PERMISSION_AWARD_GIFTS!r}"
        )
    receipt = mutate.record_mission(character.sheet, outcome, gift=name, rating=rating)
    summary = outcome + (f", gained {name}" if name and outcome == "win" else "")
    updated = character.with_sheet(receipt.sheet, summary=summary)
    return _save(character, updated), receipt


@command(name="history", description="What has happened to a character.")
@app_commands.describe(limit="How many recent events (default 10)", target="Whose (default: yours)")
async def history(
    interaction: discord.Interaction, limit: int = 10, target: str | None = None
) -> None:
    """Provenance: every accepted change, newest last."""
    await interaction.response.defer(thinking=True)
    try:
        _, character = await asyncio.to_thread(_view_target, interaction, target)
        events = character.history[-max(1, min(limit, 25)) :]
    except (SeatsError, CharacterError, OSError) as error:
        await _fail(interaction, error)
        return
    if not events:
        await interaction.followup.send(f"**{character.name}** has no history yet")
        return
    lines = [
        f"`{event.at[:16] or '---------'}` **{event.kind}** {event.summary}"
        for event in events
    ]
    await interaction.followup.send(
        _clip_text(
            f"**{character.name}** · revision {character.revision} · "
            f"showing {len(events)} of {len(character.history)}\n" + "\n".join(lines)
        )
    )


@command(name="answer", description="Rewrite one interview answer (draft only).")
@app_commands.describe(number="Which question, numbered from 1", text="The new answer")
async def answer(interaction: discord.Interaction, number: int, text: str) -> None:
    """Edit one answer. Sealed characters must be unlocked first."""
    await interaction.response.defer(thinking=True)
    try:
        seat, character = await asyncio.to_thread(_own_character, interaction)
        if not seat.may(PERMISSION_EDIT_OWN_SHEET):
            raise SeatsError(f"seat {seat.id!r} may not edit its sheet")
        updated = await asyncio.to_thread(character.with_answer, number, text)
        await asyncio.to_thread(_save, character, updated)
    except (SeatsError, CharacterError, CharacterConflict, OSError, IndexError, ValueError) as e:
        await _fail(interaction, e)
        return
    await _refresh_creation(interaction, updated)
    question = updated.interview.at(number)
    preview = text if len(text) <= 200 else text[:197] + "..."
    await interaction.followup.send(
        _clip_text(
            f"**answer {number}/{updated.interview.total}** · {question.section}\n"
            f"> {question.prompt}\n{preview}\n"
            f"-# {updated.interview.answered}/{updated.interview.total} answered · "
            f"" + (
                f"next: question {updated.interview.next_unanswered}"
                if updated.interview.next_unanswered
                else "all answered"
            )
            + f" · revision {updated.revision}"
        )
    )


@command(name="done", description="Seal the character once the interview is complete.")
async def done(interaction: discord.Interaction) -> None:
    """Seal: from here on, changes are amendments with reasons."""
    await interaction.response.defer(thinking=True)
    try:
        _, character = await asyncio.to_thread(_own_character, interaction)
        sealed = await asyncio.to_thread(character.seal)
        await asyncio.to_thread(_save, character, sealed)
    except (SeatsError, CharacterError, CharacterConflict, OSError) as error:
        await _fail(interaction, error)
        return
    await interaction.followup.send(
        f"**{character.name}** sealed · revision {sealed.revision}\n"
        f"-# {sealed.interview.answered}/{sealed.interview.total} answers locked in; "
        f"/unlock reopens it for a revision"
    )


@command(name="unlock", description="Reopen a sealed character for a Revision.")
@app_commands.describe(reason="Why (goes in the history)")
async def unlock(interaction: discord.Interaction, reason: str = "") -> None:
    """A Revision, as the rules call it: sanctioned, recorded, reversible with /done."""
    await interaction.response.defer(thinking=True)
    try:
        seat, character = await asyncio.to_thread(_own_character, interaction)
        if not seat.may(PERMISSION_EDIT_OWN_SHEET):
            raise SeatsError(f"seat {seat.id!r} may not edit its sheet")
        reopened = await asyncio.to_thread(character.unlock, reason=reason)
        if reopened is character:
            await interaction.followup.send(f"**{character.name}** is not sealed")
            return
        await asyncio.to_thread(_save, character, reopened)
    except (SeatsError, CharacterError, CharacterConflict, OSError) as error:
        await _fail(interaction, error)
        return
    await interaction.followup.send(
        f"**{character.name}** reopened · revision {reopened.revision}\n"
        f"-# edit answers with /answer, then /done to seal again"
    )


@command(name="export", description="Download this character: JSON, or an editable questionnaire.")
@app_commands.describe(
    style="json is the whole character; questionnaire is a text file to fill in and /fill back"
)
@app_commands.choices(
    style=[
        app_commands.Choice(name="json — the whole character", value="json"),
        app_commands.Choice(
            name="questionnaire — a text file of the questions", value="questionnaire"
        ),
    ]
)
async def export(interaction: discord.Interaction, style: str = "json") -> None:
    """The file round-trip: edit long prose in a real editor, then bring it back."""
    await interaction.response.defer(thinking=True)
    try:
        _, character = await asyncio.to_thread(_own_character, interaction)
        if style == "questionnaire":
            from ttrpg_chatbots.character.questionnaire_text import render_text

            text = await asyncio.to_thread(render_text, character)
            payload = text.encode("utf-8")
            filename = f"{character.id}-questionnaire.md"
            label = f"{len(text.splitlines())} lines · fill it in, then /fill"
        else:
            payload = character.to_json().encode("utf-8")
            filename = f"{character.id}.json"
            label = "the whole character — sheet, answers, history"
    except (SeatsError, CharacterError, OSError) as error:
        await _fail(interaction, error)
        return
    answers = len(character.interview.questions) if character.interview else 0
    await interaction.followup.send(
        f"**{character.name}** · revision {character.revision} · {answers} answers\n-# {label}",
        file=discord.File(io.BytesIO(payload), filename=filename),
    )


@command(name="fill", description="Import questionnaire answers from a text file.")
@app_commands.describe(file="The .md from /export style:questionnaire, with your answers filled in")
async def fill(interaction: discord.Interaction, file: discord.Attachment) -> None:
    """Answers are matched by question text, so order and partial fills are fine."""
    await interaction.response.defer(thinking=True)
    try:
        from ttrpg_chatbots.character.questionnaire_text import apply_text

        if file.size and file.size > 1_000_000:
            raise CharacterError(
                f"{file.filename} is {file.size} bytes; that is not a questionnaire file"
            )
        _, character = await asyncio.to_thread(_own_character, interaction)
        raw = await file.read()
        result = await asyncio.to_thread(apply_text, character, raw.decode("utf-8"))
        await asyncio.to_thread(_save, character, result.character)
    except (
        SeatsError,
        CharacterError,
        CharacterConflict,
        OSError,
        UnicodeDecodeError,
    ) as error:
        await _fail(interaction, error)
        return
    await _refresh_creation(interaction, result.character)
    lines = [f"**{result.character.name}** · {result.summary()}"]
    if result.ignored:
        shown = "\n".join(f"· {prompt}" for prompt in result.ignored[:5])
        lines.append(f"not on this form, so ignored:\n{shown}")
    if result.still_missing:
        lines.append(f"next unanswered: {result.still_missing[0]}")
    await interaction.followup.send(_clip_text("\n".join(lines)))


@command(name="import", description="Replace your character from an exported JSON file.")
@app_commands.describe(file="The .json downloaded with /export")
async def import_character(
    interaction: discord.Interaction, file: discord.Attachment
) -> None:
    """Load a character file, refusing anything that is not yours."""
    await interaction.response.defer(thinking=True)
    try:
        _, character = await asyncio.to_thread(_own_character, interaction)
        raw = await file.read()
        incoming = await asyncio.to_thread(Character.from_json, raw.decode("utf-8"))
        if incoming.id != character.id:
            raise CharacterError(
                f"that file is {incoming.name!r} ({incoming.id}); yours is "
                f"{character.name!r} ({character.id})"
            )
        await asyncio.to_thread(_save, character, incoming)
    except (SeatsError, CharacterError, CharacterConflict, OSError, UnicodeDecodeError) as error:
        await _fail(interaction, error)
        return
    interview = incoming.interview
    state = "sealed" if incoming.sealed else "draft"
    await interaction.followup.send(
        f"**{incoming.name}** imported · revision {incoming.revision} · "
        f"{interview.answered if interview else 0}/{interview.total if interview else 0} "
        f"answers\n-# {state}"
    )


def _claimable_ids() -> tuple[str, ...]:
    """Characters nobody is playing yet."""
    book = _seatbook()
    return tuple(
        identifier
        for identifier in _character_store().ids()
        if book.for_character(identifier) is None
    )


def _seat_id(interaction: discord.Interaction, book: SeatBook) -> str:
    """A readable seat id that is guaranteed unique.

    A player may hold several characters, so "name" and "name-discordid" both get used up;
    every further character appends a counter rather than reusing an id and failing.
    """
    base = slug_for(getattr(interaction.user, "display_name", "") or "player") or "player"
    owner = interaction.user.id
    taken = set(book.ids)
    for candidate in (base, f"{base}-{owner}"):
        if candidate not in taken:
            return candidate
    counter = 2
    while f"{base}-{owner}-{counter}" in taken:
        counter += 1
    return f"{base}-{owner}-{counter}"


def _claim(interaction: discord.Interaction, character: str) -> tuple[Seat, Character]:
    """Bind the caller to a character, if nobody else has it."""
    store = _character_store()
    book = _seatbook()
    target = store.load(character)
    existing = book.for_discord(getattr(interaction.user, "id", None))
    if existing is not None:
        if existing.character.lower() == target.id:
            raise SeatsError(f"you already play {target.name}")
        raise SeatsError(
            f"you already play {existing.character!r}; ask a GM to move you to {target.id!r}"
        )
    owner = book.for_character(target.id)
    if owner is not None:
        raise SeatsError(f"{target.name!r} is already being played (seat {owner.id!r})")
    seat = Seat(
        id=_seat_id(interaction, book),
        kind=KIND_HUMAN,
        character=target.id,
        discord_id=interaction.user.id,
        permissions=frozenset({PERMISSION_EDIT_OWN_SHEET}),
        meta={"name": interaction.user.display_name},
    )
    save_seats(book.with_seat(seat), _seats_path())
    return seat, target


async def _claim_choices(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    """Offer only characters nobody is playing, so a claim cannot half-succeed."""
    try:
        names = await asyncio.to_thread(_claimable_ids)
    except Exception:  # noqa: BLE001 - autocomplete must never fail the interaction
        return []
    wanted = (current or "").lower()
    return [app_commands.Choice(name=name, value=name) for name in names if wanted in name][:25]


@command(name="claim", description="Claim a character so /sheet and /spend work.")
@app_commands.describe(character="Which character to play")
@app_commands.autocomplete(character=_claim_choices)
async def claim(interaction: discord.Interaction, character: str) -> None:
    """Self-service seating: no hand-editing of JSON required."""
    await interaction.response.defer(thinking=True, ephemeral=True)
    try:
        seat, target = await asyncio.to_thread(_claim, interaction, character)
    except (SeatsError, CharacterError, OSError) as error:
        await _fail(interaction, error)
        return
    note = ""
    if target.sheet.freebies == 0:
        note = "\n-# no freebie points left on this sheet (it came from an import)"
    await interaction.followup.send(
        f"**{target.name}** is yours, seat `{seat.id}` · revision {target.revision}{note}\n"
        "-# /sheet /spend /options /gift /history are now yours to use",
        ephemeral=True,
    )


async def _character_choices(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    """Autocomplete character names, so nobody has to guess an id."""
    try:
        names = _conversation(interaction.client).character_names()
    except Exception:  # noqa: BLE001 - autocomplete must never fail the interaction
        return []
    wanted = (current or "").lower()
    return [
        app_commands.Choice(name=name, value=name)
        for name in names
        if wanted in name.lower()
    ][:25]


async def _check_choices(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    """Autocomplete named checks from the world's checks.jsonl."""
    try:
        names = _conversation(interaction.client).check_names()
    except Exception:  # noqa: BLE001 - autocomplete must never fail the interaction
        return []
    wanted = (current or "").lower()
    return [
        app_commands.Choice(name=name, value=name) for name in names if wanted in name.lower()
    ][:25]


@command(name="roll", description="Roll dice. Every part is its own option.")
@app_commands.describe(
    count="How many dice (default 1)",
    sides="Sides per die: 6, 10, 20… (default 20)",
    modifier="Add this to the total; negative is allowed (default 0)",
    mode="How to read it: sum (default), list, hits, check",
    target="Difficulty or hit threshold; needed by hits and check",
    check="A named check such as stealth, instead of dice",
    character="Who is rolling (default: your own character)",
    notation="Shorthand instead of the options above: 4d6-1",
    attribute="With a check: force the attribute (default comes from the ability)",
    willpower="With a check: spend 1 Willpower for an automatic success",
)
@app_commands.choices(
    mode=[
        app_commands.Choice(name="sum — add the dice", value="sum"),
        app_commands.Choice(name="list — show each die", value="list"),
        app_commands.Choice(name="hits — count dice at/over target", value="hits"),
        app_commands.Choice(name="check — total versus target", value="check"),
    ]
)
@app_commands.autocomplete(character=_character_choices, check=_check_choices)
async def roll(
    interaction: discord.Interaction,
    count: int | None = None,
    sides: int | None = None,
    modifier: int | None = None,
    mode: str | None = None,
    target: int | None = None,
    check: str | None = None,
    character: str | None = None,
    notation: str | None = None,
    attribute: str | None = None,
    willpower: bool = False,
) -> None:
    """Roll dice, a pool, or a named check, attributed to a character.

    A named check is rolled **from the character's sheet** when one exists: their attribute plus
    their ability, at difficulty 6, with any wound penalty and an optional Willpower spend. The
    static check table remains the fallback for characters with no sheet.
    """
    await interaction.response.defer(thinking=True)
    who = character or _default_character(interaction)
    # A check on a real sheet is its own path: it needs no dice options and cannot be expressed
    # as a plain notation, because the pool depends on the character.
    if check and not notation and count is None and sides is None:
        try:
            outcome = await asyncio.to_thread(
                _roll_from_sheet,
                who,
                check,
                attribute=attribute,
                difficulty=target,
                willpower=willpower,
            )
        except (CharacterError, SheetError, OSError) as error:
            if attribute or willpower:
                await _fail(interaction, error)
                return
            outcome = None
        if outcome is not None:
            await interaction.followup.send(_clip_text(outcome.render()))
            return
    parts = RollParts(
        count=count,
        sides=sides,
        modifier=modifier,
        mode=mode,
        target=target,
        notation=notation,
        check=check,
        # Unqualified rolls belong to the caller's own character, not the first in the world.
        character=who,
    )
    try:
        answer = await asyncio.to_thread(_conversation(interaction.client).roll, parts)
    except (DiceError, ConversationError, ValueError, OSError) as error:
        await _fail(interaction, error)
        return
    await interaction.followup.send(_describe(answer))


def _roll_from_sheet(
    who: str,
    check: str,
    *,
    attribute: str | None = None,
    difficulty: int | None = None,
    willpower: bool = False,
):
    """Roll a check from a stored sheet, saving it when Willpower is spent.

    Returns ``None`` when there is no such character or no such ability, so the caller can fall
    back to the static check table instead of refusing.
    """
    from ttrpg_chatbots.sheetportal.checks import CheckError, roll_check

    store = _character_store()
    try:
        character = store.load(who)
    except CharacterError:
        return None
    if character.interview is not None and not character.sheet.abilities:
        return None
    try:
        outcome = roll_check(
            character.sheet,
            check,
            attribute=attribute,
            difficulty=difficulty,
            willpower=willpower,
        )
    except CheckError:
        return None
    if outcome.willpower_spent:
        # The spend is real: write it, so the next roll sees the lower total.
        updated = replace(
            character,
            sheet=outcome.sheet,
            revision=character.revision + 1,
        ).record(
            "willpower",
            f"spent 1 Willpower on {check}",
            at=now_utc(),
            detail={"willpower": True, "check": check},
        )
        try:
            store.save(updated, expect_revision=character.revision)
        except CharacterConflict:
            pass
    return outcome


@command(name="join", description="Join your voice channel.")
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


@command(name="leave", description="Leave the voice channel.")
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


@command(name="say", description="Speak text aloud in the voice channel.")
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
        await _fail(interaction, error)
        return
    player = _player_for(interaction.client, client)
    player.enqueue(PcmFrameSource(clip))
    await interaction.followup.send(
        f"speaking {clip.duration_s:.1f} s (queued: {player.queued})"
    )


@command(name="stop", description="Stop speaking and clear the queue.")
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


@command(name="voices", description="Show which voice each character uses.")
async def voices(interaction: discord.Interaction) -> None:
    """List the cast, and whether voice is usable on this machine."""
    await interaction.response.defer(thinking=True)
    ready, detail = voice_readiness()
    try:
        rows = await asyncio.to_thread(_conversation(interaction.client).voices)
    except (ConversationError, ValueError, OSError) as error:
        await _fail(interaction, error)
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
        for registered in COMMANDS:
            self.tree.add_command(registered)
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
        await self.check_permissions()

    async def check_permissions(self) -> None:
        """Audit this bot against what the helper needs, where it is configured to work.

        The helper does not listen to messages, so this is the only place it can learn that
        *Create Private Threads* or *Manage Threads* is missing before a player hits the
        failure. Channels come from ``bots.json``; without them there is nothing to check,
        and ``/botcheck`` covers the channel the command is run in.
        """
        spec = getattr(self, "spec", None)
        guild = self.guilds[0] if self.guilds else None
        if guild is None:
            LOGGER.warning("connected but in no server, so permissions were not checked")
            return
        channels = []
        for channel_id in getattr(spec, "channels", ()) or ():
            channel = guild.get_channel(channel_id)
            if channel is not None:
                channels.append(channel)
        if not channels:
            LOGGER.info(
                "no channels configured for the permission audit; run /botcheck in a channel"
            )
            return
        findings = audit(
            bot_name=getattr(spec, "id", "helper"),
            role=ROLE_HELPER,
            channels=channels,
            member=guild.me,
        )
        log_findings(LOGGER, findings)

    async def close(self) -> None:
        for player in self.players.values():
            player.close()
        self.players.clear()
        try:
            if self.conversation is not None:
                self.conversation.close()
        finally:
            # Always release the HTTP session, even if a voice model refuses to close.
            await super().close()


def create_bot(guild_id: int | None = None) -> TtrpgBot:
    """Build the bot without connecting."""
    return TtrpgBot(guild_id=guild_id)


def run_bot(config: DiscordConfig) -> None:
    """Connect every configured bot: the helper, plus any friend that has a token.

    The roster is data. Without ``bots.json`` it is the single helper, and the old one-bot path
    is taken unchanged, so nothing about a plain installation moves.
    """
    from ttrpg_chatbots.bots.supervisor import run as run_roster

    roster = load_roster()
    try:
        lines = roster.describe()
    except RosterError as error:
        raise SystemExit(f"roster error: {error}") from error
    LOGGER.info("Starting bot(s); slash commands scope: %s", config.guild_id or "global")
    for line in lines:
        LOGGER.info("bot: %s", line)
    run_roster(roster, helper_token=config.token, guild_id=config.guild_id)


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
    parser.add_argument(
        "--friendcheck",
        metavar="CHANNEL",
        help=(
            "connect the friends only, send one message each in CHANNEL (id or name), report "
            "what each one heard, then exit"
        ),
    )
    args = parser.parse_args(argv)

    if args.version:
        from ttrpg_chatbots import __version__

        print(f"ttrpg-chatbots-bot {__version__}")
        return

    discord.utils.setup_logging(level=logging.INFO)

    if args.friendcheck:
        from ttrpg_chatbots.bots.supervisor import probe_friends

        try:
            roster = load_roster()
            lines = probe_friends(roster, channel=args.friendcheck)
        except RosterError as error:
            raise SystemExit(f"friendcheck: {error}") from error
        for line in lines:
            print(line)
        return
    try:
        config = load_discord_config()
    except ConfigError as error:
        raise SystemExit(f"configuration error: {error}") from error

    ready, detail = voice_readiness()
    if args.check:
        print(f"token: configured ({len(config.token)} characters, not shown)")
        print(f"guild: {config.guild_id if config.guild_id is not None else 'global sync'}")
        try:
            roster = load_roster()
            lines = roster.describe()
        except RosterError as error:
            raise SystemExit(f"roster error: {error}") from error
        print("bots:")
        for line in lines:
            print(f"  {line}")
        print(f"voice: {detail if not ready else 'ready'}")
        print("check only: not connecting to Discord")
        return

    LOGGER.info("voice: %s", "ready" if ready else detail)
    run_bot(config)
