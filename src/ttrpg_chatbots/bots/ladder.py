"""The ladder, dressed for Discord.

This is the only place the conversation ladder touches the running bot. It gathers the facts the
rungs are allowed to know -- what he is in the middle of, what time it is, whether the schedule says
he is asleep, who this person is -- and turns the result into a line or a reason for silence.

Nothing here decides wording. `bots/greeter.py` is the greet-only facade over this class; a friend
with a full shelf uses this one.
"""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path

from ttrpg_chatbots.conv.types import (
    Abstain,
    Addressee,
    Event,
    Gap,
    Line,
    Relationship,
    Utterance,
)
from ttrpg_chatbots.decide import subject as subject_rung
from ttrpg_chatbots.decide.shelf import Shelf, load_shelf
from ttrpg_chatbots.govern.loop import Scene, reply, would_answer
from ttrpg_chatbots.govern.repeat import Recent
from ttrpg_chatbots.life.calendar import load_calendar
from ttrpg_chatbots.life.render import load_lives
from ttrpg_chatbots.life.schedule import Schedule, load_schedules
from ttrpg_chatbots.life.state import Life
from ttrpg_chatbots.memory import relationship as relationship_of
from ttrpg_chatbots.memory.long import Fact
from ttrpg_chatbots.perceive import events as perceive_events
from ttrpg_chatbots.perceive import gap
from ttrpg_chatbots.perceive.clock import Moment, read_clock
from ttrpg_chatbots.reply.context import Turn
from ttrpg_chatbots.reply.datasets import load_world
from ttrpg_chatbots.reply.entities import EntityIndex
from ttrpg_chatbots.reply.style import Style

DATA_ENV = "TTRPG_FRIENDS_DATA"
DEFAULT_DATA = Path("examples/friends_world")


class Ladder:
    """Runs a friend's phrasebooks against the facts, and nothing else."""

    def __init__(
        self,
        *,
        data: Path | str | None = None,
        friend: str,
        style: Style | None = None,
        jobs: tuple[str, ...] | None = None,
    ) -> None:
        self._data = Path(data or os.environ.get(DATA_ENV, str(DEFAULT_DATA)))
        self.friend = friend
        self._style = style
        self.jobs = jobs
        self._shelf: Shelf | None = None
        self._recent = Recent()
        self._schedule: Schedule | None = None
        self._schedule_loaded = False
        self._life: Life | None = None
        self._life_loaded = False
        self._world = None
        self._world_loaded = False
        self._index = None
        self._year = None
        self._year_loaded = False

    @property
    def shelf(self) -> Shelf:
        """Every phrasebook this friend owns, loaded once."""
        if self._shelf is None:
            # His own books over the world's shared ones, per job: a friend diverges one phase at a
            # time, and a missing directory means he simply speaks the shared register.
            shelf = load_shelf(
                self._data / "phrasebooks" / self.friend,
                fallback=self._data / "phrasebooks",
            )
            if self.jobs is not None:
                shelf = Shelf(
                    books={job: book for job, book in shelf.books.items() if job in self.jobs}
                )
            self._shelf = shelf
        return self._shelf

    @property
    def life(self) -> Life | None:
        """What he is in the middle of. A missing life file is not an error."""
        if not self._life_loaded:
            try:
                self._life = load_lives(self._data / "life.json").get(self.friend)
            except Exception:  # noqa: BLE001 - a broken life must not silence him
                self._life = None
            self._life_loaded = True
        return self._life

    def asleep(self, moment: Moment) -> bool:
        """True only when the schedule says so; a missing schedule never silences him."""
        if not self._schedule_loaded:
            try:
                self._schedule = load_schedules(self._data / "schedule.json").get(self.friend)
            except Exception:  # noqa: BLE001 - a broken schedule must not silence him
                self._schedule = None
            self._schedule_loaded = True
        return bool(self._schedule and self._schedule.at(moment).asleep)

    @property
    def knowledge(self):
        """The world's facts and characters, loaded once. A broken dataset is not fatal: it only
        means he has nothing to say about the world, which is the hedge path anyway."""
        if self._world is None and not self._world_loaded:
            self._world_loaded = True
            try:
                self._world = load_world(self._data)
            except Exception:  # noqa: BLE001 - never take the bot down over a dataset
                self._world = None
        return self._world

    def subject_of(self, text: str):
        """Which subject they named, and what he has to say about it -- or nothing.

        The last thing that used to be the old classifier's job. It lives here rather than in the
        loop because it needs the dataset, and the loop is not allowed to know about files.
        """
        world = self.knowledge
        if world is None:
            return None
        if self._index is None:
            self._index = EntityIndex(world.knowledge)
        character = None
        try:
            character = world.character(self.friend)
        except Exception:  # noqa: BLE001 - a friend with no character knows nothing in particular
            character = None
        return subject_rung.choose(
            text=text,
            index=self._index,
            knowledge=world.knowledge,
            character=character,
        )

    def events(self, day: date | str | None = None, *, days: int = 7) -> tuple[Event, ...]:
        """What is happening in his world: today first, then what is coming.

        This is what makes his day change. Without it every conversation about "what are you up to"
        is answered from the same handful of activities for ever, because nothing else in his world
        moves except the clock.
        """
        calendar = self._calendar()
        if calendar is None:
            return ()
        today = _as_date(day)
        try:
            return perceive_events.read(calendar, today, days=days)
        except Exception:  # noqa: BLE001 - a broken calendar must not silence him
            return ()

    def _calendar(self):
        if self._year is None and not self._year_loaded:
            self._year_loaded = True
            try:
                self._year = load_calendar(self._data / "calendar.json").get(self.friend)
            except Exception:  # noqa: BLE001
                self._year = None
        return self._year

    def owns(
        self,
        *,
        text: str,
        memory=None,
        moment: Moment | None = None,
        addressed: Addressee = "named",
        speaker: str = "",
        turns: tuple[Turn, ...] = (),
        day: date | str | None = None,
    ) -> bool:
        """Whether the ladder has a job for this message.

        The bot asks this instead of keeping its own list of intents: measured, a hardcoded list sent
        "how is the dog?" -- a question about something he remembers -- to the old classifier, which
        answered from a different corpus in a different voice.
        """
        return would_answer(scene=self._scene(
            text=text, memory=memory, moment=moment, addressed=addressed, speaker=speaker,
            turns=turns, day=day,
        ), books=self.shelf)

    def _scene(
        self,
        *,
        text: str,
        memory=None,
        moment: Moment | None = None,
        addressed: Addressee = "named",
        speaker: str = "",
        turns: tuple[Turn, ...] = (),
        day: date | str | None = None,
    ) -> Scene:
        """The facts the ladder is allowed to know, gathered once so both entry points agree."""
        now = moment or read_clock()
        topic, just_told = _carried(turns)
        return Scene(
            utterance=Utterance(text=text, speaker=speaker),
            addressed=addressed,
            asleep=self.asleep(now),
            moment=now,
            relationship=_relationship(memory),
            turns=turns,
            life=self.life,
            name=_name(memory),
            day=day,
            facts=_facts(memory),
            subject=self.subject_of(text),
            events=self.events(day),
            about=topic,
            just_told=just_told,
            told=_told(memory),
            offered_hook=_offered_a_hook(turns),
            gap_bucket=_gap(memory, now).bucket,
        )

    def line(
        self,
        *,
        text: str,
        memory=None,
        moment: Moment | None = None,
        addressed: Addressee = "named",
        speaker: str = "",
        turns: tuple[Turn, ...] = (),
        day: date | str | None = None,
    ) -> Line | Abstain:
        """A line, or the reason there is not one."""
        return reply(
            scene=self._scene(
                text=text, memory=memory, moment=moment, addressed=addressed, speaker=speaker,
                turns=turns, day=day,
            ),
            books=self.shelf,
            style=self._style,
            recent=self._recent,
        )


def _carried(turns: tuple[Turn, ...]) -> tuple[str, str]:
    """What the conversation is about, read from his own last turn.

    The act on a bot turn is ``ladder|job|topic|story_id``. That is the whole mechanism: a story told
    two turns ago is remembered because it is written on the turn that told it, so a follow-up can
    reach the point and a question about the fence reaches the fence.
    """
    for turn in reversed(turns):
        if not turn.is_bot:
            continue
        parts = (turn.act or "").split("|")
        if len(parts) >= 4 and parts[0] == "ladder":
            return parts[2], parts[3]
        return "", ""
    return "", ""


def _offered_a_hook(turns: tuple[Turn, ...]) -> bool:
    """Whether his last turn was a hook, which is what makes a question a follow-up."""
    for turn in reversed(turns):
        if not turn.is_bot:
            continue
        parts = (turn.act or "").split("|")
        return len(parts) >= 2 and parts[0] == "ladder" and parts[1] in ("offer_hook", "explain")
    return False


def _told(memory) -> tuple[tuple[str, int], ...]:
    """How often each story has been told -- its own counter now, not the capped topic table."""
    counts = getattr(memory, "telling", None) or {}
    return tuple((str(key), int(value)) for key, value in counts.items())


def _as_date(day: date | str | None) -> date:
    """The day being talked about, defaulting to today in the machine's own timezone."""
    if isinstance(day, date):
        return day
    if isinstance(day, str) and day.strip():
        try:
            return date.fromisoformat(day.strip())
        except ValueError:
            return date.today()
    return date.today()


def _facts(memory) -> tuple[Fact, ...]:
    """What he durably knows about this person, as facts he may or may not bring up."""
    return tuple(getattr(memory, "facts", ()) or ())


def _gap(memory, moment: Moment) -> Gap:
    """How long since they last spoke -- the signal that decides whether recall is welcome."""
    return gap.read(last_seen=getattr(memory, "last_seen", "") or None, now=moment.now)


def _name(memory) -> str:
    """What he calls this person, if he knows it."""
    return str(getattr(memory, "person", "") or "").strip()


def _relationship(memory) -> Relationship:
    """Read what memory knows into the ladder's own vocabulary."""
    if memory is None:
        return Relationship()
    return relationship_of.read(
        sessions=int(getattr(memory, "sessions", 0) or 0),
        topics=len(getattr(memory, "topics", {}) or {}),
    )
