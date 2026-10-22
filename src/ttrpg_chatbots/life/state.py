"""A friend's life: what they are actually in the middle of.

The problem this module exists to solve is not vocabulary. A bot with no life can only answer
questions, and every answer becomes a *finished artifact* -- a setup, an aphorism and a button.
"agrippa. won the war, built the city, handed the power back" is not something a person says in
a group chat; it is a caption.

A person says what they are doing. "been sanding the stock on an old rifle since six, third coat
and it's still tacky" is a sentence with a *body* in it: a task, a snag, a time of day. It
invites the other person to compare ("you ever mess with stocks?") without asking a question.

So a life is a small set of **activities** -- things in progress, with the reason the person
chose them -- plus a few standing **grievances** and **stories**. An activity carries its own
"why", which is the part that makes elaboration personal instead of encyclopedic:

    why: "i liked the look of the wood. no better reason than that"

That is the difference between a fact and a life. A fact is true for everybody; a reason belongs
to somebody.

Selection is day-stable: the same friend has the same activity all day, computed from the date,
so a conversation that wanders away and comes back stays coherent, and a test can pin the clock.
Nothing here is random at call time.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Mapping

LIFE_FILE = "life.json"
SCHEMA_VERSION = 1


class LifeError(RuntimeError):
    """Raised when a life file cannot be read or does not make sense."""


@dataclass(frozen=True)
class Activity:
    """Something this person is in the middle of doing."""

    id: str
    doing: str  # "sanding the stock on an old .30-06"
    short: str  # "up to my elbows in sawdust"
    phase: str  # "third coat of oil and it's still tacky"
    why: str  # "i liked the look of the wood"
    invite: str = ""  # "you ever mess with stocks?"
    topic: str = ""
    hook: str = ""  # "sanding a rifle stock" -- three or four words, for "what are you up to"

    def __post_init__(self) -> None:
        for field in ("id", "doing", "short", "phase", "why"):
            value = getattr(self, field)
            if not isinstance(value, str) or not value.strip():
                raise LifeError(f"activity {self.id!r} needs a non-blank {field!r}")


@dataclass(frozen=True)
class Grievance:
    """A small standing complaint, with an invitation to trade one."""

    id: str
    text: str
    invite: str = ""
    about: str = ""


@dataclass(frozen=True)
class Story:
    """Something that happened, with the point he draws from it.

    Two fields, and the split is the whole design. ``body`` is what he says when the moment comes --
    short, in the past tense, with a snag in it. ``point`` is what he says only if he is asked what
    he learned or why it matters, which is the difference between a story and a sermon.
    """

    id: str
    body: str
    point: str = ""
    topic: str = ""
    # The names this story goes by, so "how did the fence go" reaches it. Same lesson as the
    # entity index for subjects: naming beats phrasing.
    words: str = ""

    def __post_init__(self) -> None:
        for field in ("id", "body"):
            value = getattr(self, field)
            if not isinstance(value, str) or not value.strip():
                raise LifeError(f"story {self.id!r} needs a non-blank {field!r}")


@dataclass(frozen=True)
class Plan:
    """Something he wants to do, so an invitation has somewhere to go."""

    id: str
    what: str  # "get out to the range"
    when: str = ""  # "saturday" -- his words, not a timestamp
    why: str = ""
    topic: str = ""

    def __post_init__(self) -> None:
        for field in ("id", "what"):
            value = getattr(self, field)
            if not isinstance(value, str) or not value.strip():
                raise LifeError(f"plan {self.id!r} needs a non-blank {field!r}")


@dataclass(frozen=True)
class Life:
    """One friend's ongoing life: what they are doing, and what they are annoyed about."""

    friend: str
    activities: tuple[Activity, ...] = ()
    grievances: tuple[Grievance, ...] = ()
    stories: tuple[Story, ...] = ()
    plans: tuple[Plan, ...] = ()

    def __bool__(self) -> bool:
        return bool(self.activities or self.grievances)

    def current(self, day: date | str | None = None) -> Activity | None:
        """The activity this friend is on today -- the same one all day."""
        return _pick(self.activities, f"{self.friend}:{_day(day)}")

    def grievance(self, day: date | str | None = None) -> Grievance | None:
        """The complaint they have been carrying around today."""
        return _pick(self.grievances, f"{self.friend}:grievance:{_day(day)}")

    def plan(self, day: date | str | None = None) -> Plan | None:
        """The thing he would invite you to today."""
        return _pick(self.plans, f"{self.friend}:plan:{_day(day)}")

    def describe(self) -> str:
        activity = self.current()
        return f"{self.friend}: {activity.doing}" if activity else f"{self.friend}: no life yet"


def _day(day: date | str | None) -> str:
    if day is None:
        return date.today().isoformat()
    return day.isoformat() if isinstance(day, date) else str(day)


def _pick(items: tuple, key: str):
    """Deterministic choice: the same key gives the same item, every time."""
    if not items:
        return None
    digest = hashlib.blake2b(key.encode("utf-8"), digest_size=8).digest()
    return items[int.from_bytes(digest, "big") % len(items)]
