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

from ttrpg_chatbots.character.creation import now_utc
from ttrpg_chatbots.character.store import CharacterStore, slug_for
from ttrpg_chatbots.character.types import Character, CharacterConflict, CharacterError
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
    pool="Spend freebies (creation) or xp (advancement)",
)
@app_commands.choices(
    pool=[
        app_commands.Choice(name="freebies — creation points", value="freebies"),
        app_commands.Choice(name="xp — advancement", value="xp"),
    ]
)
@app_commands.autocomplete(trait=_trait_choices)
async def spend(
    interaction: discord.Interaction,
    trait: str,
    to: int,
    pool: str = "freebies",
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
        receipt = await asyncio.to_thread(
            mutate.raise_trait, character.sheet, trait, to=to, pool=pool
        )
        # The write is a compare-and-swap, so a second surface cannot silently lose this.
        updated = character.with_sheet(
            receipt.sheet, summary=f"{trait} {to} for {receipt.spent.get(pool, 0)} {pool}"
        )
        await asyncio.to_thread(
            _character_store().save, updated, expect_revision=character.revision
        )
    except (SeatsError, CharacterError, CharacterConflict, MutationError, OSError) as error:
        await _fail(interaction, error)
        return
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
        await asyncio.to_thread(
            _record,
            character,
            receipt,
            summary=f"{trait} {before}->{to} (edit)",
            detail={"trait": trait, "kind": kind, "before": before, "after": to},
        )
    except (SeatsError, CharacterError, CharacterConflict, MutationError, OSError) as error:
        await _fail(interaction, error)
        return
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
        await asyncio.to_thread(
            _record,
            character,
            receipt,
            summary=f"lost {held.name}",
            detail={"gift": held.name, "action": "remove", "rating": held.rating},
        )
    except (SeatsError, CharacterError, CharacterConflict, MutationError, OSError) as error:
        await _fail(interaction, error)
        return
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
        await asyncio.to_thread(
            _record, character, receipt, summary=receipt.lines[0], detail={"health": before}
        )
    except (SeatsError, CharacterError, CharacterConflict, MutationError, OSError) as error:
        await _fail(interaction, error)
        return
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
            elif "health" in detail:
                receipt = mutate.set_health(sheet, int(detail["health"]))
            elif "specialty" in detail:
                receipt = mutate.set_specialty(
                    sheet, detail["specialty"], str(detail.get("before", ""))
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
        await asyncio.to_thread(
            _record,
            character,
            receipt,
            summary=f"{ability} specialty '{before}' -> '{' '.join(text.split())}'",
            detail={"specialty": ability, "before": before},
        )
    except (SeatsError, CharacterError, CharacterConflict, MutationError, OSError) as error:
        await _fail(interaction, error)
        return
    await interaction.followup.send(f"{_clip_text(str(receipt))}\n-# /undo reverses it")


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
    question = updated.interview.at(number)
    preview = text if len(text) <= 200 else text[:197] + "..."
    await interaction.followup.send(
        _clip_text(
            f"**answer {number}/{updated.interview.total}** · {question.section}\n"
            f"> {question.prompt}\n{preview}\n"
            f"-# {updated.interview.answered}/{updated.interview.total} answered · "
            f"revision {updated.revision}"
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


@command(name="export", description="Download this character as JSON.")
async def export(interaction: discord.Interaction) -> None:
    """The file round-trip: edit long prose in a real editor, then /import."""
    await interaction.response.defer(thinking=True)
    try:
        _, character = await asyncio.to_thread(_own_character, interaction)
    except (SeatsError, CharacterError, OSError) as error:
        await _fail(interaction, error)
        return
    answers = len(character.interview.questions) if character.interview else 0
    buffer = io.BytesIO(character.to_json().encode("utf-8"))
    await interaction.followup.send(
        f"**{character.name}** · revision {character.revision} · {answers} answers",
        file=discord.File(buffer, filename=f"{character.id}.json"),
    )


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
    """A readable seat id, made unique with the Discord id if the name is taken."""
    base = slug_for(getattr(interaction.user, "display_name", "") or "player")
    if not base:
        return f"player-{interaction.user.id}"
    return f"{base}-{interaction.user.id}" if base in book.ids else base


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
    character="Who is rolling (default: the first character)",
    notation="Shorthand instead of the options above: 4d6-1",
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
) -> None:
    """Roll dice, a pool, or a named check, attributed to a character."""
    await interaction.response.defer(thinking=True)
    parts = RollParts(
        count=count,
        sides=sides,
        modifier=modifier,
        mode=mode,
        target=target,
        notation=notation,
        check=check,
        # Unqualified rolls belong to the caller's own character, not the first in the world.
        character=character or _default_character(interaction),
    )
    try:
        answer = await asyncio.to_thread(_conversation(interaction.client).roll, parts)
    except (DiceError, ConversationError, ValueError, OSError) as error:
        await _fail(interaction, error)
        return
    await interaction.followup.send(_describe(answer))


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
