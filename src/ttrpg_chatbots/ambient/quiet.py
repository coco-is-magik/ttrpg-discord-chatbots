"""Bed time, and getting up again.

The rules, as given: bed at the **earliest** of 01:00, an hour after the human goes quiet, or half an
hour after the human says goodnight. Up at a random point 7-8 hours later, and the first thing said
after waking is a greeting.

Two interpretations worth stating, because the rules as written have edges:

* The human-relative rules only bite from :data:`EARLIEST_BED_HOUR` onwards. "An hour after the human
disappears" taken literally would put the friends to bed at three in the afternoon on a quiet day.
* Once asleep, nothing moves bed time. A message at 03:00 from the human does not wake the room -- that
  is what the *next* day's schedule is for, and the alternative is friends who can never be asleep.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime, time, timedelta

#: The hard cap. Nobody is awake past this.
HARD_BED = time(1, 0)
#: An hour after the human's last message.
AFTER_HUMAN = timedelta(hours=1)
#: Half an hour after the human says goodnight.
AFTER_GOODNIGHT = timedelta(minutes=30)
#: How long they sleep, drawn per night.
SLEEP_MIN_HOURS = 7.0
SLEEP_MAX_HOURS = 8.0
#: The human-relative rules do not apply before this hour. See the module docstring.
EARLIEST_BED_HOUR = 20
#: Past 01:00 but before this, the hard cap means "go to bed now" rather than "tomorrow night".
SMALL_HOURS_END = time(6, 0)


@dataclass(frozen=True)
class Sleep:
    """The night in progress, or the last one."""

    bed_at: datetime | None = None
    wake_at: datetime | None = None
    greeted: bool = False

    def asleep(self, now: datetime) -> bool:
        if self.bed_at is None or self.wake_at is None:
            return False
        return self.bed_at <= now < self.wake_at

    def just_woke(self, now: datetime) -> bool:
        """Awake, past wake time, and the greeting has not been said yet."""
        return (
            self.wake_at is not None
            and not self.greeted
            and not self.asleep(now)
            and now >= self.wake_at
        )

    def describe(self) -> str:
        if self.bed_at is None:
            return "awake (no night yet)"
        return (
            f"bed {self.bed_at:%Y-%m-%d %H:%M} to wake {self.wake_at:%H:%M}"
            f"{' (greeted)' if self.greeted else ''}"
        )


@dataclass
class Quiet:
    """Decides when the room sleeps, from the clock and the human's own activity.

    ``sleep_enabled=False`` switches the whole night off, for a run that wants a conversation through the
    small hours -- a dataset needs messages, and eight hours of silence is eight hours of nothing to
    analyse.
    """

    seed: int | None = None
    sleep_enabled: bool = True
    sleep: Sleep = Sleep()

    def __post_init__(self) -> None:
        self._random = random.Random(self.seed)

    def _hard_bed(self, now: datetime) -> datetime:
        """The hard cap that applies to `now`: tonight's 01:00, or right now if we are past it.

        The naive "next 01:00 at or after now" is wrong in the small hours: at 01:05 it returns the
        *following* night, so a room with nobody home sat awake until the next evening. Measured.
        """
        today = datetime.combine(now.date(), HARD_BED, tzinfo=now.tzinfo)
        if now < today:
            return today  # before 01:00: tonight's cap
        if now.time() < SMALL_HOURS_END:
            return now  # past 01:00 and still up: go to bed now
        return today + timedelta(days=1)  # daytime: tonight's cap is tomorrow's 01:00

    def _sleep_length(self) -> timedelta:
        hours = self._random.uniform(SLEEP_MIN_HOURS, SLEEP_MAX_HOURS)
        return timedelta(hours=hours)

    def consider(self, now: datetime, *, human_last_at: datetime | None, goodnight_at: datetime | None) -> Sleep:
        """Move the night forward if it is time. Returns the current state.

        Called often -- once per tick -- so it must be idempotent while asleep.
        """
        if not self.sleep_enabled:
            return self.sleep
        if self.sleep.asleep(now):
            return self.sleep
        if self.sleep.wake_at is not None and now < self.sleep.wake_at:
            return self.sleep

        candidates: list[datetime] = [self._hard_bed(now)]
        if now.hour >= EARLIEST_BED_HOUR:
            if human_last_at is not None and now - human_last_at >= AFTER_HUMAN:
                candidates.append(now)
            if goodnight_at is not None and now - goodnight_at >= AFTER_GOODNIGHT:
                candidates.append(now)
        bed = min(candidates)
        if bed <= now:
            # time to go: bed now, up in seven to eight hours
            self.sleep = Sleep(bed_at=now, wake_at=now + self._sleep_length(), greeted=False)
        return self.sleep

    def greet(self) -> Sleep:
        """Mark the wake greeting as said, so it happens once."""
        self.sleep = Sleep(
            bed_at=self.sleep.bed_at, wake_at=self.sleep.wake_at, greeted=True
        )
        return self.sleep
