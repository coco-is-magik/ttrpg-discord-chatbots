"""Turning a life into a line.

The templates here are deliberately plain. No aphorism, no three-part rhythm, no closing button:
those are the shapes that read as written. What makes these feel spoken is what fills them -- a
task, a snag, a reason -- not the sentence around it.

Every line is short, lowercase, and leaves room for the other person to say something. Where a
template invites a reply it asks for comparison ("you ever mess with stocks?"), not for
permission to continue.
"""

from __future__ import annotations

import hashlib
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any

from ttrpg_chatbots.life.state import Activity, Grievance, Life, Plan, Story

# Answering "what are you up to".
DOING: tuple[str, ...] = (
    "{doing}. {phase}",
    "{short} over here. {phase}",
    "{doing}, {phase}. what about you",
    "{short}. you?",
    "{doing}. been chipping at it all afternoon",
)

# Somebody had a rough one. Mirror first, then trade a grievance of his own.
COMMISERATING: tuple[str, ...] = (
    "ha. same. {grievance}",
    "yeah, i hear that. {grievance}",
    "tell me about it. {grievance}",
    "ha. {grievance}",
)

# They asked why he is doing the thing. This is the part a fact bank cannot answer.
ELABORATING: tuple[str, ...] = (
    "{why}",
    "honestly, {why}",
)


class LifeVoice:
    """Renders one friend's life as short spoken lines, rotating so it does not repeat."""

    def __init__(self, lives: Mapping[str, Life], *, day: date | str | None = None) -> None:
        self._lives = lives
        self._day = day
        self._turns: Counter[str] = Counter()

    def has(self, friend: str) -> bool:
        life = self._lives.get(friend)
        return bool(life)

    def current(self, friend: str) -> Activity | None:
        life = self._lives.get(friend)
        return life.current(self._day) if life else None

    def doing(self, friend: str) -> str | None:
        activity = self.current(friend)
        if activity is None:
            return None
        return self._fill(DOING, friend, "doing", activity=_values(activity))

    def commiserate(self, friend: str) -> str | None:
        life = self._lives.get(friend)
        grievance = life.grievance(self._day) if life else None
        if grievance is None:
            return None
        return self._fill(COMMISERATING, friend, "rough", activity=_grievance_values(grievance))

    def elaborate(self, friend: str) -> str | None:
        activity = self.current(friend)
        if activity is None:
            return None
        return self._fill(ELABORATING, friend, "why", activity=_values(activity))

    def _fill(
        self,
        templates: Sequence[str],
        friend: str,
        kind: str,
        *,
        activity: Mapping[str, str],
    ) -> str:
        index = self._turns[(friend, kind)]
        self._turns[(friend, kind)] += 1
        digest = hashlib.blake2b(
            f"{friend}:{kind}:{index}".encode("utf-8"), digest_size=8
        ).digest()
        template = templates[int.from_bytes(digest, "big") % len(templates)]
        line = template.format(**activity).strip()
        # A template that ends up half-empty (a missing invite) should still read as a sentence.
        return " ".join(line.split())


def _values(activity: Activity) -> dict[str, str]:
    return {
        "doing": activity.doing,
        "short": activity.short,
        "phase": activity.phase,
        "why": activity.why,
        "invite": activity.invite,
        "topic": activity.topic,
    }


def _grievance_values(grievance: Grievance) -> dict[str, str]:
    return {
        "grievance": grievance.text,
        "invite": grievance.invite,
        "about": grievance.about,
        "doing": grievance.text,
        "short": grievance.text,
        "phase": "",
        "why": "",
        "topic": "",
    }


def load_lives(path) -> dict[str, Life]:
    """Read ``life.json``; a missing file means nobody has a life yet, never an error."""
    import json
    from pathlib import Path

    from ttrpg_chatbots.life.state import SCHEMA_VERSION, LifeError

    target = Path(path)
    if not target.is_file():
        return {}
    try:
        data: dict[str, Any] = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise LifeError(f"cannot read {target}: {error}") from error
    if data.get("schema_version") != SCHEMA_VERSION:
        raise LifeError(f"{target}: unsupported life schema {data.get('schema_version')!r}")
    lives: dict[str, Life] = {}
    for friend, record in (data.get("friends") or {}).items():
        try:
            lives[friend] = Life(
                friend=friend,
                activities=tuple(Activity(**item) for item in record.get("activities") or ()),
                grievances=tuple(
                    Grievance(**item) for item in record.get("grievances") or ()
                ),
                stories=tuple(Story(**item) for item in record.get("stories") or ()),
                plans=tuple(Plan(**item) for item in record.get("plans") or ()),
            )
        except (LifeError, TypeError) as error:
            raise LifeError(f"{target}: {friend}: {error}") from error
    return lives
