"""How much the room is allowed to say.

Two reasons, and the first is the important one: **Discord**. A room of three bots on a five-minute
average is four hundred messages a day, which is nothing for the API and still worth a ceiling -- a
retry loop, a bug in the cadence, or an accidental second process should hit a wall rather than a rate
limit or a moderator.

The second is that a conversation with no ceiling is not a conversation. A room that has already said
twenty things this hour has nothing left to say, and the quiet is honest.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta

#: One message per five minutes is twelve an hour; the ceiling is a little above that so an ordinary
#: conversation is never clipped, and a runaway is.
PER_HOUR = 20
#: A full day at the target is 288 messages, so the cap has to clear it -- at 260 an overnight run was
#: clipped for its last two hours, which is precisely the stretch a sleep-disabled run exists to observe.
PER_DAY = 400


@dataclass
class Budget:
    """A rolling count of what the room has said."""

    per_hour: int = PER_HOUR
    per_day: int = PER_DAY
    said_at: deque[datetime] = field(default_factory=deque)

    def allows(self, now: datetime) -> bool:
        self._trim(now)
        hour = sum(1 for moment in self.said_at if now - moment < timedelta(hours=1))
        day = sum(1 for moment in self.said_at if now - moment < timedelta(days=1))
        return hour < self.per_hour and day < self.per_day

    def record(self, now: datetime) -> None:
        self.said_at.append(now)
        self._trim(now)

    def _trim(self, now: datetime) -> None:
        cutoff = now - timedelta(days=1)
        while self.said_at and self.said_at[0] < cutoff:
            self.said_at.popleft()

    def used(self, now: datetime) -> tuple[int, int]:
        """(this hour, today) -- for a log line and for the tests."""
        self._trim(now)
        hour = sum(1 for moment in self.said_at if now - moment < timedelta(hours=1))
        return hour, len(self.said_at)
