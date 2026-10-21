"""Running the roster: one process, one to four Discord applications.

Why one process rather than one per bot: the group shares state — one scheduler, one memory, one
answer to "who already replied". Two processes would need IPC to answer that.

The helper is today's :class:`~ttrpg_chatbots.bot.TtrpgBot`, unchanged: commands only, default
intents, no listener. A friend is a :class:`discord.Client` with message content when it is
configured to listen, **no command tree**, an ``on_ready`` that audits its own permissions, and a
listener that answers when it is mentioned -- through the classifier, with the last few turns as
context. A friend with ``reply: off`` connects, checks itself, and says nothing.

Failures are isolated per bot. One friend whose token is wrong must not take the sheet portal
down with it, so each client gets its own task and its own explanation.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone

import discord

from ttrpg_chatbots.bots.greeter import Greeter
from ttrpg_chatbots.bots.identity import ROLE_FRIEND, BotSpec
from ttrpg_chatbots.bots.memory import FriendMemory, MemoryError
from ttrpg_chatbots.bots.permissions import audit, log_findings
from ttrpg_chatbots.bots.roster import Roster, RosterError
from ttrpg_chatbots.reply.context import DEFAULT_WINDOW, Context, Turn
from ttrpg_chatbots.conv.types import Abstain, Line
from ttrpg_chatbots.reply.intents import (
    SOCIAL_AGREEMENT,
    SOCIAL_GREETING,
    SOCIAL_PLANS,
    match_intent,
)

LOGGER = logging.getLogger(__name__)

PROBE_READY_TIMEOUT = 30.0
PROBE_WAIT = 6.0


@dataclass(frozen=True)
class Entry:
    """One bot ready to start: its spec, its client, and its token."""

    spec: BotSpec
    client: discord.Client
    token: str = field(repr=False)  # never in a repr, a log line or an error


class FriendBot(discord.Client):
    """One of the people in the group: no commands, and a line only when addressed."""

    def __init__(self, spec: BotSpec, *, chat=None) -> None:
        intents = discord.Intents.default()
        # Requesting an ungranted intent makes Discord refuse the connection (4014), which is
        # why this follows the spec rather than always being on.
        intents.message_content = bool(spec.listen)
        super().__init__(intents=intents)
        self.spec = spec
        # The classifier (or, later, a model) that turns a message into a line.
        self.chat = chat
        # What this friend last heard, so a probe (or /friendcheck) can prove receipt without
        # reading the log. Volatile on purpose: memory arrives in the next slice.
        self.last_message: dict[str, str] = {}
        self.received = 0
        # Deliveries are counted before the "ignore other bots" rule, so a probe can tell
        # "the gateway sent nothing" apart from "we deliberately dropped bot chatter".
        self.last_delivery: dict[str, str] = {}
        self.delivered = 0
        self.replied = 0
        self.stayed_quiet = 0
        self.last_reply = ""
        # Message ids already answered, so a redelivered event cannot produce a second reply.
        self.answered: deque[int] = deque(maxlen=200)
        # What survives a restart: who this person is, when they last spoke, and anything left
        # hanging (an invitation they have not answered).
        # Which phase, if any, is being proved on real traffic. Empty means the old path only.
        self.conversation = os.environ.get("TTRPG_CONVERSATION", "").strip().lower()
        self._greeter: Greeter | None = None
        try:
            self.memory = FriendMemory.load(spec.id)
        except MemoryError as error:
            LOGGER.warning("%s: %s; starting with an empty memory", spec.id, error)
            self.memory = FriendMemory(spec.id)
        # The last few turns as this friend heard them. Volatile and per-process on purpose:
        # durable memory is a later slice, and a restart starting from silence is correct.
        self.history: deque[Turn] = deque(maxlen=DEFAULT_WINDOW)

    def context(self) -> Context:
        """What was said before the message currently being answered."""
        return Context.of(self.history, window=DEFAULT_WINDOW)

    @property
    def greeter(self) -> Greeter | None:
        """The greet stage, when it is switched on; ``None`` keeps the old path."""
        if self.conversation != "greet":
            return None
        if self._greeter is None:
            self._greeter = Greeter(friend=self.spec.id, style=self.style)
        return self._greeter

    @property
    def style(self):
        """How this friend types, from the persona; ``None`` means tidy text."""
        persona = self.spec.persona
        return persona.style if persona is not None else None

    def _remember_human(self, message: discord.Message, content: str) -> None:
        """Record a human turn, with the act it looked like at the time."""
        self.history.append(
            Turn(
                speaker=getattr(message.author, "display_name", "?"),
                text=content,
                act=match_intent(content),
                is_bot=False,
            )
        )

    def _remember_reply(self, text: str, act: str | None) -> None:
        self.history.append(Turn(speaker=self.spec.id, text=text, act=act, is_bot=True))

    async def on_ready(self) -> None:
        LOGGER.info("%s connected as %s", self.spec.id, self.user)
        if not self.spec.listen:
            LOGGER.info(
                "%s is connected but not listening; set \"listen\": true once Message Content "
                "is enabled for this application",
                self.spec.id,
            )
        elif self.spec.reply == "off":
            LOGGER.info(
                "%s is listening but replies are off; set \"reply\": \"mention\" to let it talk",
                self.spec.id,
            )
        else:
            LOGGER.info("%s is listening and answers when mentioned", self.spec.id)
        if self.spec.persona is not None:
            LOGGER.info("%s is %s", self.spec.id, self.spec.persona.describe())
        LOGGER.info("%s", self.memory.describe())
        await self.check_permissions()

    async def on_message(self, message: discord.Message) -> None:
        """Record what was heard, then answer if this friend is addressed."""
        if not self.spec.listen:
            return
        content = message.content or ""
        self.delivered += 1
        self.last_delivery = {
            "author": getattr(message.author, "display_name", "?"),
            "author_id": str(getattr(message.author, "id", "")),
            "channel": getattr(getattr(message, "channel", None), "name", "?"),
            "channel_id": str(getattr(getattr(message, "channel", None), "id", "")),
            "text": content[:200],
            "bot": "yes" if getattr(message.author, "bot", False) else "no",
            "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        if message.author == self.user:
            return
        if getattr(message.author, "bot", False):
            # Another bot is talking. Counted above, but not remembered: a group where the
            # bots answer each other is the chorus the design exists to avoid.
            return
        self.received += 1
        self.last_message = dict(self.last_delivery)
        self._remember_human(message, content)
        mentioned = self.user is not None and self.user in getattr(message, "mentions", ())
        if mentioned:
            LOGGER.info(
                "%s was mentioned by %s in #%s: %s",
                self.spec.id,
                self.last_message["author"],
                self.last_message["channel"],
                content[:100],
            )
        else:
            LOGGER.debug(
                "%s heard %s in #%s: %s",
                self.spec.id,
                self.last_message["author"],
                self.last_message["channel"],
                content[:100],
            )

        if self._should_reply(message):
            await self._answer(message)

    def _should_reply(self, message: discord.Message) -> bool:
        """Only an explicit mention, in a configured channel, when switched on."""
        if self.spec.reply != "mention" or self.chat is None:
            return False
        if getattr(message, "guild", None) is None:
            return False
        if self.user is None or self.user not in getattr(message, "mentions", ()):
            return False
        # A gateway can redeliver an event after a resume. Answering the same message twice is
        # the one failure a reader sees as "the bot is broken", so it is refused here rather than
        # deduplicated afterwards.
        identifier = getattr(message, "id", None)
        if identifier is not None and identifier in self.answered:
            LOGGER.info(
                "%s already answered message %s; ignoring the redelivery", self.spec.id, identifier
            )
            return False
        allowed = self.spec.channels
        if not allowed:
            return True
        channel = getattr(message, "channel", None)
        channel_id = getattr(channel, "id", None)
        parent_id = getattr(channel, "parent_id", None)  # a thread inherits its channel's grant
        return channel_id in allowed or parent_id in allowed

    def _query(self, message: discord.Message) -> str:
        """The message with the mention removed, so "hey @Friend" is just "hey"."""
        text = message.content or ""
        for mention in (self.user.mention, f"<@!{self.user.id}>"):
            text = text.replace(mention, " ")
        return " ".join(text.split()) or "hey"

    async def _answer_greeting(
        self, message: discord.Message, text: str, speaker: str | None
    ) -> None:
        """Answer a greeting through the ladder, or stay quiet for the reason it gives."""
        greeter = self.greeter
        if greeter is None:  # pragma: no cover - guarded by the caller
            return
        try:
            out = await asyncio.to_thread(
                greeter.line, text=text, memory=self.memory, speaker=speaker or ""
            )
        except Exception as error:  # noqa: BLE001 - never take the bot down for a greeting
            LOGGER.warning("%s could not greet: %s", self.spec.id, error)
            return
        if isinstance(out, Abstain):
            self.stayed_quiet += 1
            LOGGER.info("%s stayed quiet on a greeting: %s", self.spec.id, out.reason)
            return
        assert isinstance(out, Line)
        try:
            await message.reply(out.text, mention_author=False)
        except discord.HTTPException as error:
            LOGGER.warning("%s could not send its greeting: %s", self.spec.id, error)
            return
        identifier = getattr(message, "id", None)
        if identifier is not None:
            self.answered.append(identifier)
        self.replied += 1
        self.last_reply = out.text
        self._remember_reply(out.text, "social:greeting")
        self.memory.remember_topic("social:greeting")
        try:
            self.memory.save()
        except MemoryError as error:
            LOGGER.warning("%s could not save its memory: %s", self.spec.id, error)
        LOGGER.info("%s greeted (%s)", self.spec.id, out.trail.describe())

    async def _answer(self, message: discord.Message) -> None:
        """Ask the classifier off the event loop, then reply in the same channel.

        The friend is told what came before, so an ambiguous move is read in context, and
        it is told it was addressed -- a mention always earns a line. Silence is only for
        remarks nobody aimed at anybody.
        """
        text = self._query(message)
        speaker = getattr(message.author, "display_name", None)
        context = self.context()

        # An invitation he offered and the person has just accepted gets a confirmation, not
        # another "sounds good". This is the smallest honest use of long-term memory: the plan
        # survives a restart because it is in his file, not in RAM.
        intent = match_intent(text)
        if self.greeter is not None and intent == SOCIAL_GREETING:
            await self._answer_greeting(message, text, speaker)
            return
        force_tag = None
        if self.memory.pending_plan and intent == SOCIAL_AGREEMENT:
            force_tag = "social:confirm"
            self.memory.clear_plan()

        self.memory.note(person=speaker or "")
        try:
            answer = await asyncio.to_thread(
                self.chat.reply,
                text,
                self.spec.id,
                speaker=speaker,
                context=context,
                addressed=True,
                style=self.style,
                force_tag=force_tag,
            )
        except Exception as error:  # noqa: BLE001 - a bad dataset must not kill the bot
            LOGGER.warning("%s could not answer: %s", self.spec.id, error)
            return
        if answer is None:
            self.stayed_quiet += 1
            LOGGER.info(
                "%s stayed quiet after %s (%s)",
                self.spec.id,
                self.last_message["author"],
                context.sequence() or "no acts",
            )
            return
        try:
            await message.reply(answer.text, mention_author=False)
        except discord.HTTPException as error:
            LOGGER.warning("%s could not send its reply: %s", self.spec.id, error)
            return
        self.replied += 1
        self.last_reply = answer.text
        identifier = getattr(message, "id", None)
        if identifier is not None:
            self.answered.append(identifier)
        tag = answer.detail.get("tag")
        self.memory.remember_topic(tag)
        if tag == SOCIAL_PLANS:
            # He asked them out. Whether they say yes is the next message, possibly tomorrow.
            self.memory.remember_plan()
        try:
            self.memory.save()
        except MemoryError as error:
            LOGGER.warning("%s could not save its memory: %s", self.spec.id, error)
        self._remember_reply(answer.text, tag)
        after = answer.detail.get("after")
        LOGGER.info(
            "%s replied to %s (%s, %s%s)",
            self.spec.id,
            self.last_message["author"],
            answer.source,
            answer.detail.get("tag") or "fallback",
            f" after {after}" if after else "",
        )

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
    create_chat=None,
) -> tuple[Entry, ...]:
    """Clients for every enabled bot that has a token, plus a log line for every dormant one."""
    if create_helper is None:
        # Imported here, not at module scope: bot.py imports this package for /botcheck.
        from ttrpg_chatbots.bot import create_bot as create_helper
    make_friend = create_friend

    chat = None
    if any(spec.is_friend and spec.reply != "off" for spec in roster.enabled()):
        if create_chat is not None:
            chat = create_chat()
        else:
            from ttrpg_chatbots.bots.chat import FriendChat

            chat = FriendChat()

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
        if spec.is_helper:
            client = create_helper(guild_id)
        elif make_friend is not None:
            client = make_friend(spec)
        else:
            client = FriendBot(spec, chat=chat)
        # The helper learns its own spec here, which is how on_ready knows which channels to
        # audit; FriendBot already holds it from __init__.
        client.spec = spec
        entries.append(Entry(spec=spec, client=client, token=token))
    if not entries:
        raise RosterError(
            "no bot has a token: set DISCORD_TOKEN for the helper, and one token per friend"
        )
    # One process, so the helper can reach its friends for /friendcheck without IPC.
    helper = next((entry.client for entry in entries if entry.spec.is_helper), None)
    if helper is not None:
        helper.friends = {
            entry.spec.id: entry.client for entry in entries if entry.spec.is_friend
        }
    return tuple(entries)


def run(
    roster: Roster,
    *,
    helper_token: str,
    guild_id: int | None = None,
    create_helper=None,
    create_friend=None,
    create_chat=None,
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
        create_chat=create_chat,
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


def probe_friends(
    roster: Roster,
    *,
    channel: str,
    wait: float = PROBE_WAIT,
    create_friend=None,
) -> tuple[str, ...]:
    """Connect every friend, send one message each, and report what each one heard.

    This is the plumbing test, not the personality: it proves the tokens work, the gateway
    accepts Message Content, the friends can post, and they receive each other's lines.
    """
    friends = [
        spec for spec in roster.enabled() if spec.is_friend and roster.token_for(spec)
    ]
    if not friends:
        raise RosterError("no friend has a token; add an env_file or a *_TOKEN variable")
    make = create_friend if create_friend is not None else FriendBot
    entries = tuple(
        Entry(spec=spec, client=make(spec), token=roster.token_for(spec)) for spec in friends
    )
    return asyncio.run(_probe(entries, channel=channel, wait=wait))


async def _probe(entries: tuple[Entry, ...], *, channel: str, wait: float) -> tuple[str, ...]:
    tasks = {
        entry.spec.id: asyncio.create_task(entry.client.start(entry.token), name=entry.spec.id)
        for entry in entries
    }
    try:
        ready = await _wait_ready(entries, tasks)
        lines = []
        for entry in entries:
            if entry.spec.id in ready:
                lines.append(f"{entry.spec.id}: online as {entry.client.user}")
            else:
                lines.append(_failure_line(entry, tasks[entry.spec.id]))
        if ready:
            lines.extend(await _send_and_listen(entries, ready, channel=channel, wait=wait))
        return tuple(lines)
    finally:
        for entry in entries:
            try:
                await entry.client.close()
            except Exception:  # noqa: BLE001 - best effort on the way out
                pass
        for task in tasks.values():
            task.cancel()


async def _wait_ready(
    entries: tuple[Entry, ...], tasks: dict[str, asyncio.Task]
) -> set[str]:
    """Wait until every client is ready, or until each one has failed."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + PROBE_READY_TIMEOUT
    while loop.time() < deadline:
        ready = {entry.spec.id for entry in entries if entry.client.is_ready()}
        if len(ready) == len(entries):
            return ready
        unsettled = [
            entry for entry in entries
            if entry.spec.id not in ready and not tasks[entry.spec.id].done()
        ]
        if not unsettled:
            return ready
        await asyncio.sleep(0.25)
    return {entry.spec.id for entry in entries if entry.client.is_ready()}


def _failure_line(entry: Entry, task: asyncio.Task) -> str:
    if task.done() and not task.cancelled():
        error = task.exception()
        if error is not None:
            return explain_failure(entry.spec, error)
        return f"{entry.spec.id}: connected and stopped before the probe finished"
    return f"{entry.spec.id}: did not come online within {PROBE_READY_TIMEOUT:.0f}s"


async def _send_and_listen(
    entries: tuple[Entry, ...], ready: set[str], *, channel: str, wait: float
) -> list[str]:
    lines: list[str] = []
    sent: list[tuple[Entry, object]] = []
    for entry in entries:
        if entry.spec.id not in ready:
            continue
        target = await _find_channel(entry.client, channel)
        if target is None:
            guild = entry.client.guilds[0] if entry.client.guilds else None
            visible = (
                ", ".join(sorted(item.name for item in guild.text_channels))
                if guild is not None
                else "no guild"
            )
            lines.append(
                f"{entry.spec.id}: cannot see a channel called {channel!r}; visible: {visible}"
            )
            continue
        try:
            message = await target.send(f"probe from {entry.spec.id}")
        except Exception as error:  # noqa: BLE001 - reported per bot, not raised
            lines.append(f"{entry.spec.id}: could not send ({type(error).__name__}: {error})")
            continue
        sent.append((entry, message))
        lines.append(f"{entry.spec.id}: sent to #{target.name} ({target.id})")

    if sent:
        await asyncio.sleep(wait)

    for entry, _ in sent:
        delivery = getattr(entry.client, "last_delivery", {})
        remembered = entry.client.last_message
        delivered = getattr(entry.client, "delivered", 0)
        if remembered:
            lines.append(
                f"{entry.spec.id}: heard {remembered['author']} in #{remembered['channel']}: "
                f"{remembered['text'][:60]}"
            )
        elif delivery and not delivery.get("text"):
            lines.append(
                f"{entry.spec.id}: got {delivered} message event(s) but the text was empty — "
                "Message Content is not enabled for this application"
            )
        elif delivery:
            lines.append(
                f"{entry.spec.id}: received {delivered} message(s), only from bots "
                f"(last: {delivery['author']}); it is listening, and remembers human messages"
            )
        elif not entry.spec.listen:
            lines.append(f"{entry.spec.id}: heard nothing (listen is off)")
        else:
            lines.append(f"{entry.spec.id}: received no message events at all")

    # Clean up after the probe: a bot may always delete its own message, and a test that
    # leaves "probe from friend-a" in the channel is a test nobody runs twice.
    for _, message in sent:
        try:
            await message.delete()
        except Exception:  # noqa: BLE001 - cleanup is best effort
            pass
    return lines


async def _find_channel(client, wanted: str):
    """A channel by id or by name, from this client's own cache."""
    guild = client.guilds[0] if client.guilds else None
    if guild is None:
        return None
    text = str(wanted).strip()
    if text.isdigit():
        channel = guild.get_channel(int(text))
        if channel is None:
            try:
                channel = await client.fetch_channel(int(text))
            except Exception:  # noqa: BLE001 - a wrong id is reported as "cannot see"
                return None
        return channel
    return discord.utils.get(guild.text_channels, name=text.lstrip("#").lower())


