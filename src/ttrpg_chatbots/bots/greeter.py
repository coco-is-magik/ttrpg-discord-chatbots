"""The greet stage, dressed for Discord.

This is the only place the new ladder touches the running bot, and only when
``TTRPG_CONVERSATION=greet`` is set. It exists so the phase can be exercised by a person in a real
channel before any of the other jobs are built.

It gathers the facts the ladder is allowed to know -- relationship from memory, time from the
clock, asleep from the schedule -- and turns the result into a line or a reason for silence.
"""

from __future__ import annotations

import os
from pathlib import Path

from ttrpg_chatbots.conv.types import Abstain, Addressee, Line, Relationship, Utterance
from ttrpg_chatbots.decide.variant import Phrasebook, load as load_book
from ttrpg_chatbots.govern.loop import Scene, reply
from ttrpg_chatbots.govern.repeat import Recent
from ttrpg_chatbots.life.schedule import Schedule, load_schedules
from ttrpg_chatbots.memory import relationship as relationship_of
from ttrpg_chatbots.perceive.clock import Moment, read_clock
from ttrpg_chatbots.reply.style import Style

DATA_ENV = "TTRPG_FRIENDS_DATA"
DEFAULT_DATA = Path("examples/friends_world")


class Greeter:
    """Runs the greet phrasebook against the facts, and nothing else."""

    def __init__(
        self,
        *,
        data: Path | str | None = None,
        friend: str,
        style: Style | None = None,
        book_name: str = "greet",
    ) -> None:
        self._data = Path(data or os.environ.get(DATA_ENV, str(DEFAULT_DATA)))
        self.friend = friend
        self._style = style
        self._book: Phrasebook | None = None
        self._book_name = book_name
        self._recent = Recent()
        self._schedule: Schedule | None = None
        self._schedule_loaded = False

    @property
    def book(self) -> Phrasebook:
        if self._book is None:
            self._book = load_book(self._data / "phrasebooks" / f"{self._book_name}.json")
        return self._book

    def _at(self, moment: Moment) -> Schedule | None:
        if not self._schedule_loaded:
            try:
                self._schedule = load_schedules(self._data / "schedule.json").get(self.friend)
            except Exception:  # noqa: BLE001 - a broken schedule must not silence him
                self._schedule = None
            self._schedule_loaded = True
        return self._schedule

    def asleep(self, moment: Moment) -> bool:
        """True only when the schedule says so; a missing schedule never silences him."""
        schedule = self._at(moment)
        return bool(schedule and schedule.at(moment).asleep)

    def line(
        self,
        *,
        text: str,
        memory=None,
        moment: Moment | None = None,
        addressed: Addressee = "named",
        speaker: str = "",
    ) -> Line | Abstain:
        """A greeting, or the reason there is not one."""
        now = moment or read_clock()
        relationship = _relationship(memory)
        return reply(
            scene=Scene(
                utterance=Utterance(text=text, speaker=speaker),
                addressed=addressed,
                asleep=self.asleep(now),
                moment=now,
                relationship=relationship,
            ),
            book=self.book,
            style=self._style,
            recent=self._recent,
        )


def _relationship(memory) -> Relationship:
    """Read what memory knows into the ladder's own vocabulary."""
    if memory is None:
        return Relationship()
    return relationship_of.read(
        sessions=int(getattr(memory, "sessions", 0) or 0),
        topics=len(getattr(memory, "topics", {}) or {}),
    )
