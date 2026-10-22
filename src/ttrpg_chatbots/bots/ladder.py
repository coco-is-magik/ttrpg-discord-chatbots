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

from ttrpg_chatbots.conv.types import Abstain, Addressee, Line, Relationship, Utterance
from ttrpg_chatbots.decide.shelf import Shelf, load_shelf
from ttrpg_chatbots.govern.loop import Scene, reply
from ttrpg_chatbots.govern.repeat import Recent
from ttrpg_chatbots.life.render import load_lives
from ttrpg_chatbots.life.schedule import Schedule, load_schedules
from ttrpg_chatbots.life.state import Life
from ttrpg_chatbots.memory import relationship as relationship_of
from ttrpg_chatbots.perceive.clock import Moment, read_clock
from ttrpg_chatbots.reply.context import Turn
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

    @property
    def shelf(self) -> Shelf:
        """Every phrasebook this friend owns, loaded once."""
        if self._shelf is None:
            shelf = load_shelf(self._data / "phrasebooks")
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
        now = moment or read_clock()
        return reply(
            scene=Scene(
                utterance=Utterance(text=text, speaker=speaker),
                addressed=addressed,
                asleep=self.asleep(now),
                moment=now,
                relationship=_relationship(memory),
                turns=turns,
                life=self.life,
                name=_name(memory),
                day=day,
            ),
            books=self.shelf,
            style=self._style,
            recent=self._recent,
        )


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
