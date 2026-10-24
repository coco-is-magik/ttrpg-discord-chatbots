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
import re
from collections import deque
from dataclasses import dataclass, field
from datetime import date, datetime, timezone

import discord

from ttrpg_chatbots.bots.identity import ROLE_FRIEND, BotSpec
from ttrpg_chatbots.bots.ladder import Ladder
from ttrpg_chatbots.bots.memory import FriendMemory, MemoryError, migrate_legacy
from ttrpg_chatbots.memory.encode import read as encode_facts
from ttrpg_chatbots.bots.permissions import audit, log_findings
from ttrpg_chatbots.bots.roster import Roster, RosterError
from ttrpg_chatbots.reply.context import DEFAULT_WINDOW, Context, Turn
from ttrpg_chatbots.conv.types import Abstain, Line
from ttrpg_chatbots.govern.loop import intent_of

from ttrpg_chatbots.reply.intents import (
    SOCIAL_AGREEMENT,
    SOCIAL_GREETING,
    SOCIAL_GOODBYE,
    SOCIAL_PLANS,
    match_intent,
)

# The intents the ladder answers when the whole ladder is on. A knowledge question is not here
# yet: until world knowledge is wired in as a tool, the old classifier is better at it.
LADDER_INTENTS = frozenset(
    {
        "greet",
        "about_me",
        "explain_me",
        "complain",
        "comfort",
        "remark",
        "agree",
        "meta",
        "decline",
    }
)
LOGGER = logging.getLogger(__name__)

#: The snowflake ids of every bot in *our* roster, and which friend each one is. The friends have to hear
#: each other -- that is the whole point of the group conversation -- while other people's bots stay
#: ignored, so nothing here can start a reply loop with a stranger.
_ROSTER_IDS: set[int] = set()
_ID_TO_FRIEND: dict[int, str] = {}

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
        # The ids of messages *he* sent. Discord does not always include the referenced message
        # in a reply payload, so matching ids is the only reliable way to know a reply-arrow was
        # aimed at him.
        self.sent: deque[int] = deque(maxlen=200)
        # Test switch: treat bot-authored messages as people. Used by --friendcheck and by the
        # live end-to-end probe, because no human can type for us. Off unless asked for.
        self.trust_bots = os.environ.get("TTRPG_TRUST_BOTS") == "1"
        # What survives a restart: who this person is, when they last spoke, and anything left
        # hanging (an invitation they have not answered).
        # Which phase, if any, is being proved on real traffic. "greet" answers greetings only;
        # "ladder" answers every phase the friend has a phrasebook for and leaves the rest to the
        # old classifier. Empty means the old path only.
        self.conversation = os.environ.get("TTRPG_CONVERSATION", "").strip().lower()
        self._ladder: Ladder | None = None
        try:
            self.memory = FriendMemory.load(spec.id)
        except MemoryError as error:
            LOGGER.warning("%s: %s; starting with an empty memory", spec.id, error)
            self.memory = FriendMemory(spec.id)
        # The shared room, when the friends are talking to each other. Set by `build_entries` on every
        # friend, so one conversation is heard by all of them rather than three private ones.
        self.room = None
        # The last few turns as this friend heard them. Volatile and per-process on purpose:
        # durable memory is a later slice, and a restart starting from silence is correct.
        self.history: deque[Turn] = deque(maxlen=DEFAULT_WINDOW)

    def context(self) -> Context:
        """What was said before the message currently being answered."""
        return Context.of(self.history, window=DEFAULT_WINDOW)

    @property
    def ladder(self) -> Ladder | None:
        """The conversation ladder, when a phase is switched on; ``None`` keeps the old path."""
        if self.conversation not in ("greet", "ladder"):
            return None
        if self._ladder is None:
            jobs = ("greet",) if self.conversation == "greet" else None
            persona = self.spec.persona
            from ttrpg_chatbots.bots.conversation import sleep_enabled
            self._ladder = Ladder(
                friend=self.spec.id,
                style=self.style,
                jobs=jobs,
                question_rate=persona.question_rate if persona is not None else 0.0,
                verbosity=persona.verbosity if persona is not None else 1.0,
                obey_schedule=sleep_enabled(),
            )
        return self._ladder

    def _ladder_answers(self, text: str) -> bool:
        """Whether the ladder owns this message, or the old classifier does.

        Asked of the ladder itself, which runs the same decision the answer will run -- intent,
        phase, floor, job, and whether a phrasebook exists. A hardcoded list of intents was wrong
        exactly once, and that once was "how is the dog?".
        """
        ladder = self.ladder
        if ladder is None:
            return False
        if self.conversation == "greet":
            return intent_of(text) == "greet"
        return ladder.owns(
            text=text,
            memory=self.memory,
            speaker=getattr(self, "last_message", {}).get("author", ""),
            turns=tuple(self.history),
        )

    @property
    def style(self):
        """How this friend types, from the persona; ``None`` means tidy text."""
        persona = self.spec.persona
        return persona.style if persona is not None else None

    def _hear(self, text: str, *, speaker: str, at) -> None:
        """Put what was heard into the shared room, so the next turn has a conversation to join.

        Only two things about a message matter to the room: who said it, and whether it was a goodnight,
        which moves bedtime. Everything else is the ladder's business.
        """
        if self.room is None or not text.strip():
            return
        if speaker == "human":
            self.room.say("human", text, at, kind="human")
            if match_intent(text) == SOCIAL_GOODBYE:
                self.room.human_goodnight_at = at
            return
        self.room.say(speaker, text, at)

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
            self._check_voice_lock()
        LOGGER.info("%s", self.memory.describe())
        await self.check_permissions()

    def _check_voice_lock(self) -> None:
        """Report whether the voice this persona names is actually on this box.

        A friend who speaks with a missing model fails at the worst moment -- when somebody has just
        said something to him -- so the check happens once, at startup, and the warning carries the
        command that fixes it. Never raises: a broken lock must not stop the sheet portal.
        """
        voice = getattr(self.spec.persona, "voice", None)
        if voice is None:
            return
        from ttrpg_chatbots.bots.voice import data_directory
        from ttrpg_chatbots.tts import lock as lock_module
        from ttrpg_chatbots.tts.engines.piper_engine import voice_dir

        path = data_directory() / "voices.lock.json"
        try:
            pinned = lock_module.load(path)
        except lock_module.LockError as error:
            LOGGER.warning("%s: no usable voice lock (%s)", self.spec.id, error)
            return
        # *His* voice, not whatever happens to be in the file. Measured before this: Otto started with
        # `en_US-ryan-medium` and the log said `voice en_US-joe-medium verified against its lock` -- a
        # reassurance about somebody else's model, which is worse than no check at all.
        lock = pinned.for_voice(voice.voice or "")
        if lock is None:
            LOGGER.warning(
                "%s: no lock entry for %s, so this voice cannot be rebuilt -- add one to %s "
                "(pinned: %s)",
                self.spec.id,
                voice.voice or "(none)",
                path.name,
                ", ".join(pinned.names()) or "nothing",
            )
            return
        report = lock_module.verify(lock, voice_dir())
        if report.ok:
            LOGGER.info("%s: voice %s verified against its lock", self.spec.id, lock.voice)
            return
        LOGGER.warning(
            "%s: %s -- run `ttrpg-chatbots-tts --fetch-voice %s` to restore it",
            self.spec.id,
            report.summary(),
            lock.voice,
        )

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
        if os.environ.get("TTRPG_LISTEN_TRACE") == "1":
            # Delivery only, before any filtering: the difference between "not addressed" and
            # "never arrived" is invisible otherwise, and that ambiguity is what makes a working
            # bot look dead.
            LOGGER.info(
                "%s TRACE delivery from %s (bot=%s) in #%s: %s",
                self.spec.id,
                self.last_delivery["author"],
                self.last_delivery["bot"],
                self.last_delivery["channel"],
                content[:80],
            )
        if message.author == self.user:
            return
        author_is_bot = getattr(message.author, "bot", False)
        if author_is_bot and not (
            self.trust_bots or getattr(message.author, "id", None) in _ROSTER_IDS
        ):
            # Another bot is talking. Counted above, but not remembered: a group where *strangers'* bots
            # answer each other is the chorus the design exists to avoid. Our own friends are the
            # exception -- the room is supposed to hear them, or there is no group conversation.
            return
        self.received += 1
        self.last_message = dict(self.last_delivery)
        self._hear(content, speaker=_who(message), at=datetime.now(timezone.utc))
        self._remember_human(message, content)
        self._learn(content)
        addressed = self._addressed(message)
        if os.environ.get("TTRPG_LISTEN_TRACE") == "1":
            reference = getattr(message, "reference", None)
            LOGGER.info(
                "%s TRACE addressed=%s me=%s mentions=%s roles=%s held=%s reply_to=%s sent_ids=%s",
                self.spec.id,
                addressed,
                getattr(self.user, "id", None),
                [getattr(member, "id", None) for member in getattr(message, "mentions", ())],
                [getattr(role, "id", None) for role in getattr(message, "mention_roles", ()) or ()],
                [getattr(role, "id", None) for role in self._held_roles(message)],
                getattr(reference, "message_id", None),
                list(self.sent)[-3:],
            )
        if addressed:
            how = "mentioned" if (self._named(message) or self._role_named(message)) else "replied to"
            LOGGER.info(
                "%s was %s by %s in #%s: %s",
                self.spec.id,
                how,
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
        elif addressed:
            # Addressed but refused: say why, once, at INFO. Silence with no log is what made a
            # working bot look dead.
            LOGGER.info(
                "%s did not answer %s: %s",
                self.spec.id,
                self.last_message["author"],
                self._why_not(message),
            )

    def _why_not(self, message: discord.Message) -> str:
        """The reason a message that was addressed got no answer."""
        if self.spec.reply != "mention":
            return "reply is off"
        if self.chat is None:
            return "no classifiers loaded"
        allowed = self.spec.channels
        channel = getattr(message, "channel", None)
        if allowed and channel is not None and getattr(channel, "id", None) not in allowed:
            parent = getattr(channel, "parent_id", None)
            if parent not in allowed:
                return f"#channel {getattr(channel, 'id', '?')} is not in its allowed list"
        return "already answered this message id"

    def _learn(self, content: str) -> None:
        """Keep what this person volunteered about themselves, if it earns it.

        Encoding is patterns, promotion is a rule, and both live in `memory/`. This method is the
        only place they meet the disk, so there is one writer per friend and one place to look when
        a fact does not stick.
        """
        candidates = encode_facts(content, said_by="them")
        if not candidates:
            return
        kept = self.memory.remember_facts(candidates)
        if not kept:
            return
        try:
            self.memory.save()
        except MemoryError as error:
            LOGGER.warning("%s could not save what it learned: %s", self.spec.id, error)
            return
        LOGGER.info(
            "%s will remember %s",
            self.spec.id,
            ", ".join(f"{fact.key}={fact.value}" for fact in kept),
        )

    def _mark_recalled(self, trail) -> None:
        """Note that he brought something up, so he does not bring it up again today."""
        steps = dict(trail.steps)
        if steps.get("family") != "recall":
            return
        key = steps.get("recall", "").split(" ")[0]
        if not key or key == "nothing":
            return
        self.memory.mark_raised(key, day=date.today().isoformat())
        try:
            self.memory.save()
        except MemoryError as error:
            LOGGER.warning("%s could not save its memory: %s", self.spec.id, error)

    def _remember_sent(self, sent) -> None:
        """Remember the id of a message he posted, so a reply-arrow can be recognised later."""
        identifier = getattr(sent, "id", None)
        if identifier is not None:
            self.sent.append(identifier)

    def _held_roles(self, message: discord.Message) -> list:
        """The roles he holds in this guild, as far as the message can tell us."""
        guild = getattr(message, "guild", None)
        member = getattr(guild, "me", None) if guild is not None else None
        if member is None and guild is not None and self.user is not None:
            getter = getattr(guild, "get_member", None)
            member = getter(getattr(self.user, "id", None)) if getter else None
        return list(getattr(member, "roles", ()) or ())

    def _role_named(self, message: discord.Message) -> bool:
        """Whether a ping of one of *his* roles was aimed at him.

        Typing `@TerrysTopGuy` in Discord autocompletes to the managed role Discord created for
        the application, which arrives as `<@&id>` -- `mention_roles`, not `mentions`. That is how
        a person naturally addresses a bot, and ignoring it made every message look unaddressed.
        """
        mentioned = {getattr(role, "id", None) for role in getattr(message, "mention_roles", ()) or ()}
        # A managed bot role is usually *not mentionable*, and Discord then leaves
        # `mention_roles` empty even though the text holds `<@&id>`. The markup in the content is
        # the only evidence that survives, so read it as well.
        for identifier in re.findall(r"<@&(\d+)>", message.content or ""):
            mentioned.add(int(identifier))
        if not mentioned:
            return False
        names = {
            str(getattr(self.user, "name", "")).lower(),
            str(getattr(self.user, "display_name", "")).lower(),
        }
        for role in self._held_roles(message):
            if getattr(role, "id", None) not in mentioned:
                continue
            # A managed role is the one Discord created for this application. A plain role is
            # accepted only when it carries his name, so a shared "@players" ping is not a summons.
            if getattr(role, "managed", False):
                return True
            if str(getattr(role, "name", "")).lower() in names:
                return True
        return False

    def _named(self, message: discord.Message) -> bool:
        """Whether his name is in the message's mention list, by id."""
        me = getattr(self.user, "id", None)
        return any(getattr(member, "id", None) == me for member in getattr(message, "mentions", ()))

    def _addressed(self, message: discord.Message) -> bool:
        """Named with an @, or a direct reply to something he said.

        A reply is a person turning to face him. Discord does not add a mention when you use the
        reply arrow, so requiring `mentions` missed the most natural way to talk to a bot -- the
        reader sees their message vanish into silence with nothing in the log to explain it.
        """
        if self.user is None:
            return False
        # Compare ids, never objects: `mentions` holds Member instances and `self.user` is a
        # ClientUser, and object equality across those is not something to rely on.
        me = getattr(self.user, "id", None)
        if self._named(message) or self._role_named(message):
            return True
        reference = getattr(message, "reference", None)
        if reference is None:
            return False
        for target in (
            getattr(reference, "resolved", None),
            getattr(reference, "cached_message", None),
        ):
            author = getattr(target, "author", None)
            if author is not None and getattr(author, "id", None) == me:
                return True
        return getattr(reference, "message_id", None) in self.sent

    def _should_reply(self, message: discord.Message) -> bool:
        """Only an explicit mention or a reply, in a configured channel, when switched on."""
        if self.spec.reply != "mention" or self.chat is None:
            return False
        if getattr(message, "guild", None) is None:
            return False
        if not self._addressed(message):
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
        # Role pings too: `@TerrysTopGuy` usually arrives as `<@&role_id>`, and leaving it in the
        # text hands the classifier markup instead of a sentence.
        for role in self._held_roles(message):
            identifier = getattr(role, "id", None)
            if identifier is not None:
                text = text.replace(f"<@&{identifier}>", " ")
        return " ".join(text.split()) or "hey"

    async def _answer_through_ladder(
        self, message: discord.Message, text: str, speaker: str | None
    ) -> None:
        """Answer through the ladder, or stay quiet for the reason it gives."""
        ladder = self.ladder
        if ladder is None:  # pragma: no cover - guarded by the caller
            return
        try:
            out = await asyncio.to_thread(
                ladder.line,
                text=text,
                memory=self.memory,
                speaker=speaker or "",
                turns=tuple(self.history),
            )
        except Exception as error:  # noqa: BLE001 - never take the bot down for a reply
            LOGGER.warning("%s could not answer through the ladder: %s", self.spec.id, error)
            return
        if isinstance(out, Abstain):
            self.stayed_quiet += 1
            LOGGER.info("%s stayed quiet: %s", self.spec.id, out.reason)
            return
        assert isinstance(out, Line)
        try:
            sent = await message.reply(out.text, mention_author=False)
        except discord.HTTPException as error:
            LOGGER.warning("%s could not send its reply: %s", self.spec.id, error)
            return
        self._remember_sent(sent)
        self._mark_recalled(out.trail)
        identifier = getattr(message, "id", None)
        if identifier is not None:
            self.answered.append(identifier)
        self.replied += 1
        self.last_reply = out.text
        steps = dict(out.trail.steps)
        job = steps.get("job", "?")
        about = steps.get("about", "|")
        if job in ("ask_back", "follow_up"):
            # Both are about *them* -- one asks about them, the other picks up what they said -- so
            # nothing of his is under discussion. Measured: these turns recorded his activity
            # ("topic:trains"), the next message inherited it, and "playing video games" was matched to
            # his trains at 0.96.
            about = "|"
        # `ladder|job|topic|story_id`: what he said, and what it was about. The next turn reads
        # this, which is how a follow-up reaches the point of a story.
        self._remember_reply(out.text, f"ladder|{job}|{about}")
        if job == "tell_story":
            story_id = about.split("|")[1]
            if story_id:
                self.memory.remember_told(story_id)
        # The person spoke: who they are, when, and what it was about. This used to happen only on the
        # old path, so once the ladder took over, `sessions` and `last_seen` froze at their pre-ladder
        # values -- the relationship never warmed up and the gap never reset. Measured, not guessed:
        # the first friend has been answering through the ladder for days with `sessions` stuck at 17.
        self.memory.note(person=speaker or "")
        topic = about.split("|")[0]
        if topic.startswith("topic:"):
            self.memory.remember_topic(topic)
        try:
            self.memory.save()
        except MemoryError as error:
            LOGGER.warning("%s could not save its memory: %s", self.spec.id, error)
        LOGGER.info("%s answered through the ladder (%s)", self.spec.id, out.trail.describe())

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
        if self._ladder_answers(text):
            await self._answer_through_ladder(message, text, speaker)
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
            sent = await message.reply(answer.text, mention_author=False)
        except discord.HTTPException as error:
            LOGGER.warning("%s could not send its reply: %s", self.spec.id, error)
            return
        self._remember_sent(sent)
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
    # Before any friend loads, make sure the database has whatever the old JSON files held.
    try:
        imported = migrate_legacy()
    except MemoryError as error:
        LOGGER.warning("could not migrate the old memory files: %s", error)
    else:
        if imported:
            LOGGER.info("imported memory for %s from the old JSON files", ", ".join(imported))
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

    _ROSTER_IDS.clear()
    _ROSTER_IDS.update(spec.user_id for spec in roster if spec.user_id)
    _ID_TO_FRIEND.clear()
    _ID_TO_FRIEND.update({spec.user_id: spec.id for spec in roster if spec.user_id})
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
    chatter = _build_chatter(entries)
    try:
        asyncio.run(_run_all(entries, chatter))
    except KeyboardInterrupt:
        LOGGER.info("interrupted; closing %d bot(s)", len(entries))


async def _run_all(entries: tuple[Entry, ...], chatter=None) -> None:
    if chatter is not None:
        chatter.start()
    try:
        await asyncio.gather(*(_supervise(entry) for entry in entries))
    finally:
        if chatter is not None:
            await chatter.stop()


#: How many times a bot's connection is retried before it is left down, and how long between tries.
#: Measured: a Discord gateway hiccup (a 503 on the websocket handshake, then discord.py raising
#: `AttributeError: 'NoneType' object has no attribute 'sequence'` on its own resume path) took the
#: **helper and Terry** offline while the other two connected, and nothing tried again -- so the helper
#: was down for eight minutes and `/voicetest` could not be run at all. A transient failure should cost
#: seconds, not the process lifetime.
START_ATTEMPTS = 3
START_BACKOFF = 5.0

#: Failures that will never fix themselves, so retrying only delays the message.
PERMANENT = ("LoginFailure", "PrivilegedIntentsRequired")


async def _supervise(entry: Entry) -> None:
    """Start one client; retry a transient failure, and report without taking the others down."""
    try:
        for attempt in range(1, START_ATTEMPTS + 1):
            try:
                await entry.client.start(entry.token)
                return
            except asyncio.CancelledError:
                raise
            except Exception as error:  # noqa: BLE001 - one bot's failure is not the process's
                if type(error).__name__ in PERMANENT or attempt == START_ATTEMPTS:
                    LOGGER.error("%s", explain_failure(entry.spec, error))
                    return
                LOGGER.warning(
                    "%s: %s on attempt %d/%d; retrying in %.0fs (a gateway hiccup, not a bad token)",
                    entry.spec.id,
                    type(error).__name__,
                    attempt,
                    START_ATTEMPTS,
                    START_BACKOFF,
                )
                await asyncio.sleep(START_BACKOFF)
    finally:
        # Always, on every path -- a client that connected and then stopped, and one that never got
        # there. The first version returned on success *before* closing, so a clean shutdown left the
        # connection open; the test caught it.
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


def _who(message) -> str:
    """Who said this, in the room's vocabulary: a friend id for our own bots, else "human"."""
    author_id = getattr(getattr(message, "author", None), "id", None)
    return _ID_TO_FRIEND.get(author_id, "human")


def _build_chatter(entries: tuple[Entry, ...]):
    """The group conversation, if it is switched on.

    One room, one director, one loop for the whole process: the friends are meant to be in the *same*
    conversation, and three private ones is the failure mode this exists to avoid.
    """
    from ttrpg_chatbots.ambient.room import Room
    from ttrpg_chatbots.bots import conversation as conversation_module

    if not conversation_module.enabled():
        LOGGER.info(
            "the friends will not talk to each other: set TTRPG_CHATTER=1 to let them"
        )
        return None

    friends = [entry for entry in entries if isinstance(entry.client, FriendBot)]
    if len(friends) < 2:
        LOGGER.warning("TTRPG_CHATTER is on but there is only %d friend listening", len(friends))
        return None

    room = Room()
    for entry in friends:
        entry.client.room = room

    channel_id = os.environ.get("TTRPG_CHATTER_CHANNEL", "").strip()
    channel = int(channel_id) if channel_id.isdigit() else None
    if channel is None:
        for entry in friends:
            if entry.spec.channels:
                channel = int(entry.spec.channels[0])
                break
    if channel is None:
        LOGGER.warning("TTRPG_CHATTER is on but no channel is configured for it")
        return None

    sleep = conversation_module.sleep_enabled()
    from ttrpg_chatbots.ambient.quiet import Quiet

    director = conversation_module.Director(
        ladders={entry.spec.id: entry.client.ladder for entry in friends},
        memories={entry.spec.id: entry.client.memory for entry in friends},
        room=room,
        quiet=Quiet(sleep_enabled=sleep),
    )
    if not sleep:
        LOGGER.info(
            "bedtime is switched off (TTRPG_CHATTER_SLEEP=0): the room and the friends will talk "
            "through the night"
        )
    LOGGER.info(
        "the friends will talk to each other in channel %s (mean gap %.0fs)",
        channel,
        director.cadence.mean_seconds,
    )
    return conversation_module.Chatter(
        director=director,
        room=room,
        channel_id=channel,
        clients={entry.spec.id: entry.client for entry in friends},
    )


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


