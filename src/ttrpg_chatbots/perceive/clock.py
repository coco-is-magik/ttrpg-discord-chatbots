"""What time is it, for him.

The first of the perceive modules, and deliberately the dullest: it reads the clock and says what
kind of moment it is. It decides nothing, knows nothing about conversation, and has one job --
turn "now" into a `Moment` that later modules can ask questions of.

The locale is the machine's, because the bot lives where the bot runs. A schedule is wall-clock
time for a person ("coffee at half six"), not UTC, so everything here is naive local time unless a
timezone is named explicitly. That is also the correct behaviour across a daylight-saving change:
his day does not shift by an hour, the clock does.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
PART_OF_DAY = {
    range(5, 12): "morning",
    range(12, 17): "afternoon",
    range(17, 22): "evening",
    range(22, 24): "night",
    range(0, 5): "night",
}


def _part_of_day(hour: int) -> str:
    for hours, name in PART_OF_DAY.items():
        if hour in hours:
            return name
    return "night"


@dataclass(frozen=True)
class Moment:
    """Now, in the terms a person's day is measured in."""

    now: datetime
    timezone: str = "system"

    @property
    def minute_of_day(self) -> int:
        return self.now.hour * 60 + self.now.minute

    @property
    def weekday(self) -> str:
        return WEEKDAYS[self.now.weekday()]

    @property
    def is_weekend(self) -> bool:
        return self.weekday in ("sat", "sun")

    @property
    def part_of_day(self) -> str:
        return _part_of_day(self.now.hour)

    def describe(self) -> str:
        return f"{self.weekday} {self.now:%H:%M} ({self.part_of_day})"


def read_clock(now: datetime | None = None, *, timezone: str = "system") -> Moment:
    """Read the clock. ``now`` is injectable so tests never depend on the wall clock."""
    return Moment(now=now or datetime.now(), timezone=timezone)
