"""A friend's day, laid out like an NPC's.

The rule this enforces: he is always somewhere, doing something, and it is knowable from the clock
alone. Blocks are snapped to **15-minute slots**, so "what is he doing at 14:07" has one answer and
"how far into it is he" has a number.

Sleep is a block like any other; the only thing special about it is that ``asleep`` is true.

Everything is data, and everything is meant to be edited: the point is to move his day towards a
schedule that fits the human's over time, so the file has to be comfortable to hand-edit and the
loader has to say clearly when it does not add up (gaps, overlaps, off-grid times).

Deliberately not here: anything that *happens* rather than *occupies time* -- a match airing at
19:00, a show starting, weather. Those are events that overlay a schedule, and they arrive later
(``docs/SCHEDULE.md`` §5).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping

from ttrpg_chatbots.perceive.clock import WEEKDAYS, Moment

SCHEMA_VERSION = 1
SLOT_MINUTES = 15
DEFAULT_DOING = "pottering about the house"


class ScheduleError(RuntimeError):
    """Raised when a schedule cannot be read."""


def parse_clock(value: str) -> int:
    """``"06:30"`` -> minutes since midnight. Off-grid times are allowed but reported."""
    try:
        hours, minutes = str(value).strip().split(":")
        return int(hours) * 60 + int(minutes)
    except (AttributeError, ValueError) as error:
        raise ScheduleError(f"{value!r} is not a time of day (expected 'HH:MM')") from error


def format_clock(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


@dataclass(frozen=True)
class Block:
    """One stretch of the day, in wall-clock minutes."""

    id: str
    start: int
    end: int
    doing: str
    days: tuple[str, ...] = WEEKDAYS
    topics: tuple[str, ...] = ()
    asleep: bool = False
    # A block that belongs to one date only (Christmas dinner, a day at the garage). It is not
    # part of the weekly pattern, so `day()` never sees it and a weekday cannot leak it.
    only: object = None

    def __post_init__(self) -> None:
        if not self.id.strip():
            raise ScheduleError("a block needs an id")
        if not self.doing.strip():
            raise ScheduleError(f"block {self.id!r} needs something to be doing")
        if not 0 <= self.start < 24 * 60 or not 0 <= self.end <= 24 * 60:
            raise ScheduleError(f"block {self.id!r} is outside the day")
        if self.end <= self.start:
            raise ScheduleError(
                f"block {self.id!r} ends before it starts; a block may not wrap past midnight"
            )
        for day in self.days:
            if day not in WEEKDAYS:
                raise ScheduleError(f"block {self.id!r}: {day!r} is not a weekday")

    def covers(self, day: str, minute: int, on: object = None) -> bool:
        if not self.start <= minute < self.end:
            return False
        if self.only is not None:
            return on == self.only
        return day in self.days


@dataclass(frozen=True)
class Slot:
    """Where he is in the day: one snapped quarter-hour and what fills it."""

    start: int
    end: int
    doing: str
    block_id: str = ""
    topics: tuple[str, ...] = ()
    asleep: bool = False
    filled_by_default: bool = False

    @property
    def duration_minutes(self) -> int:
        return self.end - self.start

    def progress(self, minute_of_day: int) -> float:
        """How far through the block he is, 0.0 to 1.0."""
        span = self.end - self.start
        if span <= 0:
            return 1.0
        return max(0.0, min(1.0, (minute_of_day - self.start) / span))

    def describe(self) -> str:
        return f"{format_clock(self.start)}-{format_clock(self.end)} " + (
            "asleep" if self.asleep else self.doing
        )


@dataclass
class Schedule:
    """One friend's day. ``at()`` is the whole surface that matters."""

    friend: str
    blocks: tuple[Block, ...] = ()
    timezone: str = "system"
    default_doing: str = DEFAULT_DOING
    default_topics: tuple[str, ...] = ()

    def at(self, moment: Moment | datetime | None = None) -> Slot:
        """What he is doing now, snapped down to the quarter hour."""
        point = _point(moment)
        minute = point.minute_of_day
        block = _covering(self.blocks, point.weekday, minute, point.now.date())
        if block is None:
            start = minute - minute % SLOT_MINUTES
            return Slot(
                start=start,
                end=min(start + SLOT_MINUTES, 24 * 60),
                doing=self.default_doing,
                topics=self.default_topics,
                filled_by_default=True,
            )
        start = minute - (minute - block.start) % SLOT_MINUTES
        return Slot(
            start=start,
            end=min(start + SLOT_MINUTES, block.end),
            doing=block.doing,
            block_id=block.id,
            topics=block.topics,
            asleep=block.asleep,
        )

    def day(self, day: str) -> tuple[Slot, ...]:
        """The whole day as quarter-hour slots -- what an editor (and a test) looks at."""
        if day not in WEEKDAYS:
            raise ScheduleError(f"{day!r} is not a weekday")
        slots: list[Slot] = []
        for minute in range(0, 24 * 60, SLOT_MINUTES):
            block = _covering(self.blocks, day, minute)
            slots.append(
                Slot(
                    start=minute,
                    end=minute + SLOT_MINUTES,
                    doing=block.doing if block else self.default_doing,
                    block_id=block.id if block else "",
                    topics=block.topics if block else self.default_topics,
                    asleep=block.asleep if block else False,
                    filled_by_default=block is None,
                )
            )
        return tuple(slots)

    def check(self) -> tuple[str, ...]:
        """Everything wrong with the schedule, as sentences a person can act on."""
        problems: list[str] = []
        by_day: dict[str, list[Block]] = {day: [] for day in WEEKDAYS}
        for block in self.blocks:
            if block.start % SLOT_MINUTES or block.end % SLOT_MINUTES:
                problems.append(
                    f"{block.id}: {format_clock(block.start)}-{format_clock(block.end)} is not on "
                    f"a {SLOT_MINUTES}-minute boundary"
                )
            for day in block.days:
                by_day[day].append(block)
        for day, blocks in by_day.items():
            ordered = sorted(blocks, key=lambda block: block.start)
            for earlier, later in zip(ordered, ordered[1:]):
                if later.start < earlier.end:
                    problems.append(
                        f"{day}: {earlier.id} and {later.id} overlap "
                        f"({format_clock(earlier.start)}-{format_clock(earlier.end)} vs "
                        f"{format_clock(later.start)}-{format_clock(later.end)})"
                    )
                elif later.start > earlier.end:
                    problems.append(
                        f"{day}: nothing between {format_clock(earlier.end)} and "
                        f"{format_clock(later.start)} -- the default fills it"
                    )
            if ordered and ordered[0].start > 0:
                problems.append(f"{day}: nothing before {format_clock(ordered[0].start)}")
            if ordered and ordered[-1].end < 24 * 60:
                problems.append(f"{day}: nothing after {format_clock(ordered[-1].end)}")
        return tuple(problems)


def _point(moment: Moment | datetime | None) -> Moment:
    if isinstance(moment, Moment):
        return moment
    if isinstance(moment, datetime):
        return Moment(now=moment)
    from ttrpg_chatbots.perceive.clock import read_clock

    return read_clock()


def _covering(
    blocks: tuple[Block, ...], day: str, minute: int, on: object = None
) -> Block | None:
    for block in blocks:
        if block.covers(day, minute, on):
            return block
    return None

def load_schedules(path) -> dict[str, Schedule]:
    """Read ``schedule.json``: one file, one reader, keyed by friend id."""
    import json
    from pathlib import Path

    target = Path(path)
    if not target.is_file():
        return {}
    try:
        data: dict[str, Any] = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ScheduleError(f"cannot read {target}: {error}") from error
    if data.get("schema_version") != SCHEMA_VERSION:
        raise ScheduleError(
            f"{target}: unsupported schedule schema {data.get('schema_version')!r}"
        )
    default = data.get("default") or {}
    schedules: dict[str, Schedule] = {}
    for friend, record in (data.get("friends") or {}).items():
        blocks: list[Block] = []
        for item in record.get("blocks") or ():
            try:
                blocks.append(_block(item))
            except (ScheduleError, TypeError, KeyError) as error:
                raise ScheduleError(f"{target}: {friend}: {error}") from error
        schedules[friend] = Schedule(
            friend=friend,
            blocks=tuple(blocks),
            timezone=str(record.get("timezone") or "system"),
            default_doing=str(default.get("doing") or DEFAULT_DOING),
            default_topics=tuple(default.get("topics") or ()),
        )
    return schedules


def _block(record: Mapping[str, Any]) -> Block:
    days = record.get("days")
    return Block(
        id=str(record["id"]),
        start=parse_clock(record["start"]),
        end=parse_clock(record["end"]),
        doing=str(record["doing"]),
        days=tuple(days) if days else WEEKDAYS,
        topics=tuple(record.get("topics") or ()),
        asleep=bool(record.get("asleep", False)),
    )
