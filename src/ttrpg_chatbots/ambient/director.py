"""Who speaks next, and about what.

The only module that runs the conversation with nobody in it. It decides *when* (cadence), *whether*
(quiet hours, budget), *who* (inclusion) and *what* (the real ladder, on a synthetic scene), then hands
the line back to whoever called it -- the Discord supervisor in production, the simulator offline.

That split is the point: **the same ladder produces the words in both places**, so a simulated week is
evidence about the live room rather than about a second implementation of it.

There is no Discord import here, and no clock of its own: everything is passed a `now`.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from ttrpg_chatbots.social import inclusion
from ttrpg_chatbots.ambient.budget import Budget
from ttrpg_chatbots.ambient.cadence import Cadence
from ttrpg_chatbots.ambient.quiet import Quiet
from ttrpg_chatbots.ambient.room import Room, Said
from ttrpg_chatbots.bots.ladder import Ladder
from ttrpg_chatbots.conv.parts import Turn as Parts
from ttrpg_chatbots.conv.types import Abstain, Line
from ttrpg_chatbots.deliver.pace import waits as waits_for
from ttrpg_chatbots.deliver.split import package
from ttrpg_chatbots.perceive.clock import read_clock
from ttrpg_chatbots.reply.context import Turn

#: What the ladder is told when there is nothing to react to. It is a *prompt*, not something anybody
#: said: "what are you up to" is the question that makes a friend talk about his own day.
SELF_PROMPT = "what are you up to"
#: And what it is told at the start of the day, which is the one move that should be a greeting.
WAKE_PROMPT = "good morning"


#: Below this many words, the last thing said was an acknowledgement ("yeah", "oh honey", "mm") rather
#: than a thing to react to. Acknowledging an acknowledgement is how a room of friends ends up saying
#: nothing at all -- measured: the first simulation produced 169 messages of "yeah", "mm" and "ah, oh"
#: in a loop. The fix is structural rather than a change to how anybody speaks: if there is nothing to
#: react to, talk about your own day instead.
REACTABLE_WORDS = 4


def _act_from(entry) -> str:
    """The turn's act, rebuilt from the ladder's own trail.

    ``ladder|job|about|`` is what the rest of the system reads -- the dig's aspect, a story's topic, the
    subject a follow-up reaches. The trail already carries both parts (``job=`` and ``about=``), so the
    room reconstructs exactly what the friend recorded rather than inventing a placeholder.
    """
    trail = getattr(entry, "trail", "") or ""
    job = ""
    about = "|"
    if "job=" in trail:
        job = trail.split("job=")[1].split(" >")[0].strip()
    if "about=" in trail:
        # The **last** one: the trail records the ordinary subject and then, for a domain turn, overrides
        # it with the aspect. Measured: taking the first made a dig about "cute-things:the-shelf" read as
        # "topic:rome", so the friend being asked answered a different question and hedged.
        about = trail.rsplit("about=", 1)[1].split(" >")[0].strip()
    if not job:
        job = entry.kind
    if "|" not in about:
        # `about` is a two-part field (`topic|story`), and a domain aspect arrives as one part.
        about = f"{about}|"
    return f"ladder|{job}|{about}"


def _worth_reacting_to(text: str) -> bool:
    """Whether the last line was a *thing said* rather than a nod."""
    return len([word for word in (text or "").split() if word]) >= REACTABLE_WORDS


@dataclass(frozen=True)
class Spoke:
    """A line the room decided to say, and how it arrives.

    ``text`` is the whole turn, for logs and summaries. ``messages`` is what actually gets sent: one or more
    packages of the same parts, which is where the texture lives (`docs/TEXTURE.md`). A spoke with no
    messages is one message -- the behaviour before parts existed.
    """

    speaker: str
    text: str
    at: datetime
    kind: str = "chat"
    trail: str = ""
    messages: tuple[str, ...] = ()
    #: Seconds to wait before each message, in order. Empty means "send at once".
    waits: tuple[float, ...] = ()

    def arriving(self) -> tuple[str, ...]:
        return self.messages or (self.text,)


@dataclass
class Director:
    """The conversation with nobody in it."""

    ladders: dict[str, Ladder]
    #: Each friend's memory, held here rather than inside the ladder (the ladder is stateless about it).
    memories: dict[str, object] = field(default_factory=dict)
    room: Room = field(default_factory=Room)
    cadence: Cadence = field(default_factory=Cadence)
    quiet: Quiet = field(default_factory=Quiet)
    budget: Budget = field(default_factory=Budget)
    seed: int | None = None
    next_at: datetime | None = None
    spoke: list[Spoke] = field(default_factory=list)
    #: Why the last tick produced nothing, in the ladder's own words.
    _abstain_reason: str = ""
    #: Why the last tick said nothing. Silence has to be explainable: a room that has gone quiet and a
    #: room whose loop has died look identical from the outside, which is exactly the confusion this
    #: field removes.
    reason: str = "not started"

    def __post_init__(self) -> None:
        self._rng = random.Random(self.seed)
        if self.cadence.seed is None:
            self.cadence.seed = self.seed
            self.cadence.__post_init__()
        if self.quiet.seed is None:
            self.quiet.seed = self.seed
            self.quiet.__post_init__()

    @property
    def friends(self) -> tuple[str, ...]:
        return tuple(self.ladders)

    def tick(self, now: datetime) -> Spoke | None:
        """One step of the clock. A line, or nothing -- which is the usual answer."""
        self.quiet.consider(
            now,
            human_last_at=self.room.human_last_at,
            goodnight_at=self.room.human_goodnight_at,
        )
        if self.quiet.sleep.asleep(now):
            self.reason = f"asleep ({self.quiet.sleep.describe()})"
            return None
        if not self.budget.allows(now):
            hour, day = self.budget.used(now)
            self.reason = f"budget spent ({hour} this hour, {day} today)"
            return None

        if self.next_at is None:
            self.next_at = self.cadence.next_at(now)
            self.reason = f"waiting until {self.next_at:%H:%M}"
            return None
        if now < self.next_at:
            self.reason = f"waiting until {self.next_at:%H:%M}"
            return None

        waking = self.quiet.sleep.just_woke(now)
        speaker = self._owner_of_the_dig() or inclusion.choose(
            self.room, self.friends, now, rng=self._rng
        )
        if speaker is None:
            self.next_at = self.cadence.next_at(now)
            self.reason = "nobody may speak yet (everyone has just spoken)"
            return None

        self._abstain_reason = ""
        line = self._speak(speaker, now, waking=waking)
        self.next_at = self.cadence.next_at(now)
        if line is None:
            self.reason = f"{speaker} had nothing to say: {self._abstain_reason or 'no reason given'}"
            return None

        turn_id = f"{line.speaker}@{line.at.isoformat(timespec='seconds')}"
        for offset, message in enumerate(line.arriving()):
            self.room.say(
                line.speaker,
                message,
                line.at + timedelta(seconds=sum(line.waits[: offset + 1])),
                kind=line.kind,
                trail=line.trail,
                turn=turn_id,
            )
        self.budget.record(now)
        if waking:
            self.quiet.greet()
        self.spoke.append(line)
        self.reason = f"spoke as {line.speaker}; next at {self.next_at:%H:%M}"
        return line

    def hear_human(self, text: str, at: datetime, *, goodnight: bool = False) -> Said:
        """The human said something. Only two things about it matter to the room: that it happened, and
        whether it was a goodnight."""
        entry = self.room.say("human", text, at, kind="human")
        if goodnight:
            self.room.human_goodnight_at = at
        return entry

    def _owner_of_the_dig(self) -> str | None:
        """Who answers, when the last thing said was a question about somebody's own thing.

        Measured in a three-friend room: Terry asked Otto's shelf a question, the rotation handed the floor
        to Crusty, and she hedged -- because it was never her shelf. A question about somebody's own thing
        is answered by them, which is also what makes the answer available at all.
        """
        tail = self.room.tail()
        if len(tail) < 2:
            return None
        last, offered = tail[-1], tail[-2]
        if offered.is_human or last.is_human:
            return None
        if "job=dig" not in (last.trail or ""):
            return None
        if offered.speaker == last.speaker or offered.speaker not in self.ladders:
            return None
        return offered.speaker

    def _prompt(self, speaker: str, waking: bool) -> str:
        """What the ladder is told. A greeting at the start of the day, a reaction if somebody else has
        just spoken something worth reacting to, and otherwise his own day."""
        if waking:
            return WAKE_PROMPT
        others = self.room.said_by_others(speaker, count=1)
        if others and not others[-1].is_human and _worth_reacting_to(others[-1].text):
            # Another friend spoke: react to *that*, which is what makes this a conversation between
            # them rather than three people talking to nobody.
            return others[-1].text
        return SELF_PROMPT

    def _turns(self) -> tuple[Turn, ...]:
        """The room as the ladder's own history, so depth, follow-ups and the repeat ledger all work
        exactly as they do when a person is talking."""
    def _turns(self) -> tuple[Turn, ...]:
        """The room as the ladder's own history, so depth, follow-ups and the repeat ledger all work
        exactly as they do when a person is talking.

        The act is read from the **trail**, not invented from the message kind. Measured: it used to be
        ``ladder|chat|`` for every line, so the room could not see that a turn was a story (no topic to
        follow up on) or a dig (nothing for the answering side to answer) -- the same two things a person
        talking to a friend gets for free.
        """
        turns: list[Turn] = []
        for entry in self.room.tail():
            if entry.is_human:
                turns.append(Turn(speaker="human", text=entry.text, act=None, is_bot=False))
                continue
            turns.append(
                Turn(
                    speaker=entry.speaker,
                    text=entry.text,
                    act=_act_from(entry),
                    is_bot=True,
                )
            )
        return tuple(turns)

    def _speak(self, speaker: str, now: datetime, *, waking: bool) -> Spoke | None:
        ladder = self.ladders[speaker]
        prompt = self._prompt(speaker, waking)
        out = ladder.line(
            text=prompt,
            speaker="human",
            moment=read_clock(now),
            turns=self._turns(),
            memory=self.memories.get(speaker),
        )
        if isinstance(out, Abstain) or not isinstance(out, Line):
            # Keep the ladder's own reason. Measured: a live night logged 58 silences from one friend and
            # the reason was discarded here, so the only way to find out why was to replay the transcript
            # -- which answered 68 of 68, because the cause was live-only state.
            self._abstain_reason = out.reason if isinstance(out, Abstain) else "not a line"
            return None
        messages = package(Parts(parts=out.parts)) if out.parts else (out.text,)
        return Spoke(
            speaker=speaker,
            text=out.text,
            at=now,
            kind="greeting" if waking else "chat",
            trail=out.trail.describe() if out.trail else "",
            messages=tuple(messages),
            waits=waits_for(tuple(messages)),
        )
