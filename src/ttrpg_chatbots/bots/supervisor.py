"""Running the roster: one process, one to four Discord applications.

Why one process rather than one per bot: the group shares state — one scheduler, one memory, one
answer to "who already replied". Two processes would need IPC to answer that.

The helper is today's :class:`~ttrpg_chatbots.bot.TtrpgBot`, unchanged: commands only, default
intents, no listener. A friend is a :class:`discord.Client` with message content when it is
configured to listen, **no command tree**, and an ``on_ready`` that audits its own permissions.
Until the listener lands it replies to nothing: it connects, checks itself, and says so once.

Failures are isolated per bot. One friend whose token is wrong must not take the sheet portal
down with it, so each client gets its own task and its own explanation.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field

import discord

from ttrpg_chatbots.bots.identity import ROLE_FRIEND, BotSpec
from ttrpg_chatbots.bots.permissions import audit, log_findings
from ttrpg_chatbots.bots.roster import Roster, RosterError

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class Entry:
    """One bot ready to start: its spec, its client, and its token."""

    spec: BotSpec
    client: discord.Client
    token: str = field(repr=False)  # never in a repr, a log line or an error


class FriendBot(discord.Client):
    """One of the people in the group: no commands, and nothing to say yet."""

    def __init__(self, spec: BotSpec) -> None:
        intents = discord.Intents.default()
        # Requesting an ungranted intent makes Discord refuse the connection (4014), which is
        # why this follows the spec rather than always being on.
        intents.message_content = bool(spec.listen)
        super().__init__(intents=intents)
        self.spec = spec

    async def on_ready(self) -> None:
        LOGGER.info("%s connected as %s", self.spec.id, self.user)
        if self.spec.listen:
            LOGGER.info("%s is listening (replies arrive in the next slice)", self.spec.id)
        else:
            LOGGER.info(
                "%s is connected but not listening; set \"listen\": true once Message Content "
                "is enabled for this application",
                self.spec.id,
            )
        await self.check_permissions()

    async def on_message(self, message: discord.Message) -> None:
        """A placeholder with a gate, so turning the listener on is a config change."""
        if not self.spec.listen:
            return
        if message.author == self.user or message.author.bot:
            return
        LOGGER.debug("%s heard a message in #%s", self.spec.id, message.channel)

    async def check_permissions(self) -> None:
        """Audit this bot against what a friend needs, in the channels it is told to use."""
        guild = self.guilds[0] if self.guilds else None
        if guild is None:
            LOGGER.warning("%s is connected but in no server, so nothing can be checked", self.spec.id)
            return
        channels = [guild.get_channel(channel_id) for channel_id in self.spec.channels]
        channels = [channel for channel in channels if channel is not None]
        if not channels:
            LOGGER.warning(
                "%s has no channels configured, so its permissions were not checked; add "
                "channel ids to bots.json",
                self.spec.id,
            )
            return
        findings = audit(
            bot_name=self.spec.id,
            role=ROLE_FRIEND,
            channels=channels,
            member=guild.me,
            # Only check the intent this bot actually asked for: a friend with listen off is
            # deliberately not requesting Message Content, and warning about it every startup
            # would train the operator to ignore the audit.
            intents=self.intents if self.spec.listen else None,
        )
        log_findings(LOGGER, findings)


def explain_failure(spec: BotSpec, error: BaseException) -> str:
    """Turn a connection failure into one sentence naming the fix."""
    if isinstance(error, discord.LoginFailure):
        return (
            f"{spec.id}: the token in {spec.token_var} was rejected; regenerate it in the "
            "Developer Portal and update the secret"
        )
    if isinstance(error, discord.PrivilegedIntentsRequired):
        return (
            f"{spec.id}: the application is missing a privileged intent; enable Message Content "
            "in the Developer Portal, or set \"listen\": false until it is"
        )
    if isinstance(error, discord.ConnectionClosed) and error.code == 4014:
        return (
            f"{spec.id}: Discord closed the connection because Message Content is not enabled "
            "for this application; enable it in the portal, or set \"listen\": false"
        )
    if isinstance(error, discord.HTTPException) and error.status == 401:
        return f"{spec.id}: Discord rejected the credentials (401); check the token"
    return f"{spec.id}: {type(error).__name__}: {error}"


def build_entries(
    roster: Roster,
    *,
    helper_token: str,
    guild_id: int | None = None,
    create_helper=None,
    create_friend=None,
) -> tuple[Entry, ...]:
    """Clients for every enabled bot that has a token, plus a log line for every dormant one."""
    if create_helper is None:
        # Imported here, not at module scope: bot.py imports this package for /botcheck.
        from ttrpg_chatbots.bot import create_bot as create_helper
    make_friend = create_friend if create_friend is not None else FriendBot

    entries: list[Entry] = []
    for spec in roster.enabled():
        token = helper_token if spec.is_helper else roster.token_for(spec)
        if not token:
            LOGGER.info(
                "%s is configured but dormant (no %s); not starting it",
                spec.id,
                spec.token_var,
            )
            continue
        client = create_helper(guild_id) if spec.is_helper else make_friend(spec)
        # The helper learns its own spec here, which is how on_ready knows which channels to
        # audit; FriendBot already holds it from __init__.
        client.spec = spec
        entries.append(Entry(spec=spec, client=client, token=token))
    if not entries:
        raise RosterError(
            "no bot has a token: set DISCORD_TOKEN for the helper, and one token per friend"
        )
    return tuple(entries)


def run(
    roster: Roster,
    *,
    helper_token: str,
    guild_id: int | None = None,
    create_helper=None,
    create_friend=None,
) -> None:
    """Run every configured bot. One bot keeps the old blocking ``run`` path."""
    if not roster.helpers:
        LOGGER.warning("no helper in the roster: slash commands will not be available")
    entries = build_entries(
        roster,
        helper_token=helper_token,
        guild_id=guild_id,
        create_helper=create_helper,
        create_friend=create_friend,
    )
    LOGGER.info(
        "starting %d bot(s): %s",
        len(entries),
        ", ".join(entry.spec.describe() for entry in entries),
    )
    if len(entries) == 1:
        # The single-bot path is unchanged, including signal handling and log_handler=None.
        entry = entries[0]
        entry.client.run(entry.token, log_handler=None)
        return
    try:
        asyncio.run(_run_all(entries))
    except KeyboardInterrupt:
        LOGGER.info("interrupted; closing %d bot(s)", len(entries))


async def _run_all(entries: tuple[Entry, ...]) -> None:
    await asyncio.gather(*(_supervise(entry) for entry in entries))


async def _supervise(entry: Entry) -> None:
    """Start one client; report its failure without taking the other bots down."""
    try:
        await entry.client.start(entry.token)
    except asyncio.CancelledError:
        raise
    except Exception as error:  # noqa: BLE001 - one bot's failure is not the process's
        LOGGER.error("%s", explain_failure(entry.spec, error))
    finally:
        try:
            await entry.client.close()
        except Exception:  # noqa: BLE001 - closing is best effort on the way out
            LOGGER.warning("could not close %s cleanly", entry.spec.id)

