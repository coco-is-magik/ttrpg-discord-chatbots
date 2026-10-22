"""The year: seasons, holidays and one-offs, and what they do to a day.

A weekly schedule says what a normal Tuesday looks like. It cannot say that Christmas is not a
Tuesday, that hockey is over for the summer, or that he is away the second week of March. Those are
**dated facts**, and they need three different shapes:

* **seasons** -- "December to February: cold, dark by five"
* **annual days and ranges** -- "25 December", "15 September to 15 June" (which wraps the new year)
* **one-offs** -- "away 10-17 March 2027"

Resolution is by specificity: a one-off beats an annual day, which beats an annual range, which
beats a season. The output is a `DayView`, and `overlay()` applies it to a `Schedule` to produce the
day he is actually having.

The second job is **temporal recall**: everything here can be asked "when", "how long until", and
"what else is near that", because those are the questions a friend's inferences are made of --
"the game's Thursday", "you're away next week", "hockey's done until September".

Nothing in this module decides what to say. It answers questions about dates.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Mapping

from ttrpg_chatbots.life.schedule import Block, Schedule, parse_clock

CALENDAR_FILE = "calendar.json"
SCHEMA_VERSION = 1

# Most specific first. A one-off outranks an annual day, which outranks a range, which outranks a
# whole season; that ordering is what makes "Christmas" beat "winter".
RANK = {"oneoff": 4, "annual-day": 3, "annual-range": 2, "season": 1}


class CalendarError(RuntimeError):
    """Raised when a calendar file cannot be read."""


@dataclass(frozen=True)
class Entry:
    """One dated fact about the year."""

    id: str
    kind: str
    title: str
    note: str = ""
    short: str = ""  # "hockey's back" -- two or three words, for a spoken line
    # when
    months: tuple[int, ...] = ()
    on: tuple[int, int] | None = None  # (month, day), every year
    annual: tuple[tuple[int, int], tuple[int, int]] | None = None  # ((m,d),(m,d)), may wrap
    dates: tuple[date, date] | None = None  # one-off span, inclusive
    # what it does to the day
    removes: tuple[str, ...] = ()
    adds: tuple[Block, ...] = ()
    doing: str = ""  # overrides the day's default
    topics: tuple[str, ...] = ()

    @property
    def rank(self) -> int:
        return RANK.get(self.kind, 0)

    def matches(self, day: date) -> bool:
        if self.dates is not None:
            return self.dates[0] <= day <= self.dates[1]
        if self.on is not None:
            return (day.month, day.day) == self.on
        if self.annual is not None:
            return _inside_annual(day, *self.annual)
        if self.months:
            return day.month in self.months
        return False


@dataclass(frozen=True)
class DayView:
    """Everything the calendar says about one day, most specific first."""

    day: date
    entries: tuple[Entry, ...] = ()

    def __bool__(self) -> bool:
        return bool(self.entries)

    @property
    def notes(self) -> tuple[str, ...]:
        return tuple(f"{entry.title}: {entry.note}" for entry in self.entries if entry.note)

    @property
    def titles(self) -> tuple[str, ...]:
        return tuple(entry.title for entry in self.entries)

    def describe(self) -> str:
        if not self.entries:
            return f"{self.day.isoformat()}: nothing on"
        return f"{self.day.isoformat()}: " + ", ".join(self.titles)


@dataclass(frozen=True)
class Upcoming:
    """A dated entry and how far away it is, which is what "the game's Thursday" needs."""

    entry: Entry
    day: date
    days_away: int

    @property
    def phrase(self) -> str:
        return phrase_for(self.days_away, self.day)

    def describe(self) -> str:
        return f"{self.entry.title} {self.phrase}"


WEEKDAY_NAMES = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


def phrase_for(days: int, day: date | None = None) -> str:
    """Say a distance in days the way a person says it.

    Inside a week, people name the day ("the game's thursday") rather than counting ("in three
    days"), so ``day`` -- the date being referred to -- matters as much as the gap.
    """
    if days == 0:
        return "today"
    if days == 1:
        return "tomorrow"
    if days == -1:
        return "yesterday"
    if 2 <= days <= 6 and day is not None:
        return f"on {WEEKDAY_NAMES[day.weekday()]}"
    if days == 7:
        return "in a week"
    if days > 6:
        weeks = days // 7
        return f"in {weeks} weeks" if weeks >= 2 else f"in {days} days"
    if days == -7:
        return "a week ago"
    if days < 0:
        return f"{-days} days ago"
    return f"in {days} days"


def _inside_annual(day: date, start: tuple[int, int], end: tuple[int, int]) -> bool:
    """Annual ranges may wrap the new year (a season that starts in September and ends in June)."""
    point = (day.month, day.day)
    if start <= end:
        return start <= point <= end
    return point >= start or point <= end


@dataclass
class Calendar:
    """A friend's year. Answers what a day is, and what is near it."""

    friend: str
    entries: tuple[Entry, ...] = ()

    def on(self, day: date) -> DayView:
        """What the calendar says about this day, most specific first."""
        matching = [entry for entry in self.entries if entry.matches(day)]
        matching.sort(key=lambda entry: (entry.rank, entry.id), reverse=True)
        return DayView(day=day, entries=tuple(matching))

    def ongoing(self, today: date) -> tuple[Entry, ...]:
        """What is true today -- the season, the holiday, the trip he is on."""
        return tuple(entry for entry in self.entries if entry.matches(today))

    def spans(self, day: date) -> tuple[Entry, ...]:
        """Entries that cover this day, including long ones (a whole season)."""
        return tuple(entry for entry in self.entries if entry.matches(day))

    def upcoming(self, today: date, *, days: int = 14) -> tuple[Upcoming, ...]:
        """What is coming, soonest first. Recurring entries appear once, at their next occurrence."""
        found: dict[str, Upcoming] = {}
        # "Upcoming" means *starting* soon. Something already under way is on, not upcoming --
        # otherwise a six-month hockey season would sit at the top of every list forever.
        for day in (today + timedelta(days=n) for n in range(1, days + 1)):
            for entry in self.entries:
                if not entry.matches(day) or entry.id in found:
                    continue
                if entry.matches(today):
                    continue
                found[entry.id] = Upcoming(entry=entry, day=day, days_away=(day - today).days)
        return tuple(sorted(found.values(), key=lambda item: (item.days_away, item.entry.id)))

    def recent(self, today: date, *, days: int = 7) -> tuple[Upcoming, ...]:
        """What happened lately -- the other half of temporal recall."""
        found: dict[str, Upcoming] = {}
        for offset in range(1, days + 1):
            day = today - timedelta(days=offset)
            for entry in self.entries:
                if entry.matches(day) and entry.id not in found and not entry.matches(today):
                    found[entry.id] = Upcoming(entry=entry, day=day, days_away=-offset)
        return tuple(sorted(found.values(), key=lambda item: (-item.days_away, item.entry.id)))

    def between(self, start: date, end: date) -> tuple[Upcoming, ...]:
        """Entries whose span touches this window, each with its distance from ``start``."""
        found: dict[str, Upcoming] = {}
        for offset in range(0, (end - start).days + 1):
            day = start + timedelta(days=offset)
            for entry in self.entries:
                if entry.matches(day) and entry.id not in found:
                    found[entry.id] = Upcoming(entry=entry, day=day, days_away=offset)
        return tuple(sorted(found.values(), key=lambda item: (item.days_away, item.entry.id)))

    def topic_on(self, day: date) -> frozenset[str]:
        """Which subjects today leans towards -- what he is likely to bring up."""
        tags: set[str] = set()
        for entry in self.spans(day):
            tags.update(entry.topics)
        return frozenset(tags)


def overlay(schedule: Schedule, view: DayView) -> Schedule:
    """Apply a day's entries to a weekly schedule, producing the day he is actually having.

    ``removes`` names block ids to drop; ``"*"`` drops the whole weekly pattern (a day away).
    ``adds`` supplies blocks for the day; ``doing`` replaces the fallback text.
    """
    removes: set[str] = set()
    adds: list[Block] = []
    doing = schedule.default_doing
    for entry in view.entries:
        removes.update(entry.removes)
        adds.extend(entry.adds)
        if entry.doing:
            doing = entry.doing
    whole_day = "*" in removes
    blocks = tuple(block for block in schedule.blocks if block.id not in removes)
    if whole_day:
        blocks = ()
    # A block added for one day belongs to that *date*, not to that weekday, or a Friday
    # Christmas dinner would reappear on every Friday of the year.
    adds = [replace(block, days=(), only=view.day) for block in adds]
    # Added blocks come first so they *win* against a weekly block covering the same minutes:
    # Christmas dinner replaces the afternoon reading, it does not merely sit beside it.
    merged = tuple(adds) + blocks
    return replace(schedule, blocks=merged, default_doing=doing)


def load_calendar(path) -> dict[str, Calendar]:
    """Read ``calendar.json``: one file, one reader, keyed by friend id."""
    target = Path(path)
    if not target.is_file():
        return {}
    try:
        data: dict[str, Any] = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise CalendarError(f"cannot read {target}: {error}") from error
    if data.get("schema_version") != SCHEMA_VERSION:
        raise CalendarError(f"{target}: unsupported calendar schema {data.get('schema_version')!r}")
    calendars: dict[str, Calendar] = {}
    for friend, record in (data.get("friends") or {}).items():
        try:
            entries = tuple(_entry(item) for item in record.get("entries") or ())
        except (CalendarError, KeyError, TypeError, ValueError) as error:
            raise CalendarError(f"{target}: {friend}: {error}") from error
        calendars[friend] = Calendar(friend=friend, entries=entries)
    return calendars


def _entry(record: Mapping[str, Any]) -> Entry:
    when = record.get("when") or {}
    months = tuple(int(month) for month in when.get("months") or ())
    on = when.get("on")
    on_pair = _month_day(on) if on else None
    annual = None
    if when.get("annual"):
        start, end = when["annual"]
        annual = (_month_day(start), _month_day(end))
    dates = None
    if when.get("dates"):
        raw = when["dates"]
        span = raw if isinstance(raw, list) and len(raw) == 2 else [raw, raw]
        dates = (date.fromisoformat(str(span[0])), date.fromisoformat(str(span[1])))
    kind = str(record.get("kind") or "")
    if kind not in RANK:
        raise CalendarError(f"{record.get('id')!r}: kind must be one of {sorted(RANK)}")
    adds = tuple(_block(item) for item in record.get("adds") or ())
    return Entry(
        id=str(record["id"]),
        kind=kind,
        title=str(record.get("title") or record["id"]),
        note=str(record.get("note") or ""),
        short=str(record.get("short") or ""),
        months=months,
        on=on_pair,
        annual=annual,
        dates=dates,
        removes=tuple(record.get("removes") or ()),
        adds=adds,
        doing=str(record.get("doing") or ""),
        topics=tuple(record.get("topics") or ()),
    )


def _month_day(value) -> tuple[int, int]:
    text = str(value).strip()
    month, day = text.split("-")
    return (int(month), int(day))


def _block(record: Mapping[str, Any]) -> Block:
    return Block(
        id=str(record["id"]),
        start=parse_clock(record["start"]),
        end=parse_clock(record["end"]),
        doing=str(record["doing"]),
        days=tuple(record.get("days") or ()),
        topics=tuple(record.get("topics") or ()),
        asleep=bool(record.get("asleep", False)),
    )
