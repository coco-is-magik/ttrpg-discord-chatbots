"""When does the next message happen?

**An average, not a metronome.** The target is one message every five minutes across the group, and a
person who speaks exactly every five minutes is obviously a machine -- so the gap is drawn from a
distribution with a long right tail: usually a minute or two, sometimes fifteen. Gamma with shape 2 is
the sum of two exponentials (two things have to happen before somebody speaks), which gives that shape
and a mean that is easy to state.

A hard floor is enforced on top: Discord gets one message per interval *at most*, and a room where two
friends fire at the same second is the chorus the design exists to avoid.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime, timedelta

#: The target: one message every five minutes, averaged over the group.
DEFAULT_MEAN_SECONDS = 300.0
#: Nobody speaks twice inside this. A floor rather than a target -- it is what keeps a bad draw or a
#: retry from producing a burst.
MIN_GAP_SECONDS = 45.0
#: The longest a healthy conversation goes quiet. **Cut at twelve minutes**, which is 2.4 times the mean:
#: still a real tail (the distribution is untruncated below it, so the shape is honest), but a room that
#: goes quiet for longer than this reads as broken rather than as busy. Measured: with a 25-minute cap,
#: one draw in sixty produced a silence long enough that the owner reported the bots as offline.
MAX_GAP_SECONDS = 12 * 60.0
#: Gamma shape. 2 is the sum of two exponentials: a minimum "something happened, then somebody decided
#: to say it" and a long tail.
SHAPE = 2.0


@dataclass
class Cadence:
    """Draws the next speaking time. Seeded, so a simulation is reproducible."""

    mean_seconds: float = DEFAULT_MEAN_SECONDS
    seed: int | None = None
    minimum: float = MIN_GAP_SECONDS
    maximum: float = MAX_GAP_SECONDS

    def __post_init__(self) -> None:
        if self.mean_seconds <= 0:
            raise ValueError(f"mean_seconds must be positive, got {self.mean_seconds}")
        if self.minimum <= 0 or self.maximum <= self.minimum:
            raise ValueError(f"the gap bounds are nonsense: {self.minimum}..{self.maximum}")
        self._random = random.Random(self.seed)

    def gap(self) -> timedelta:
        """One gap, in seconds, shaped like a person rather than a clock."""
        drawn = self._random.gammavariate(SHAPE, self.mean_seconds / SHAPE)
        return timedelta(seconds=min(self.maximum, max(self.minimum, drawn)))

    def next_at(self, now: datetime) -> datetime:
        return now + self.gap()
