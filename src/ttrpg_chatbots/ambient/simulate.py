"""Run the room with nobody in it, fast.

A day of conversation takes a day of real time to observe and a few seconds to simulate. This steps a
virtual clock in fixed increments, ticks the director, and collects what the room said -- which is the
only way to get a *large* sample of friend-to-friend interaction without a week of waiting and without
hammering Discord.

The rules are identical to the live path because the director is identical to the live path: same
cadence, same quiet hours, same budget, same ladder. What is different is only the clock.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from ttrpg_chatbots.ambient.director import Director, Spoke

#: How finely the virtual clock moves. One minute is finer than the 45-second floor, so no message can
#: be missed by the ticker -- and a day is 1440 ticks, which runs in about a second.
TICK = timedelta(minutes=1)


@dataclass(frozen=True)
class Simulation:
    """What a stretch of simulated time produced."""

    start: datetime
    end: datetime
    spoke: tuple[Spoke, ...]

    @property
    def hours(self) -> float:
        return (self.end - self.start).total_seconds() / 3600

    @property
    def per_hour(self) -> float:
        return len(self.spoke) / self.hours if self.hours else 0.0

    @property
    def mean_gap_minutes(self) -> float:
        if len(self.spoke) < 2:
            return 0.0
        gaps = [
            (later.at - earlier.at).total_seconds()
            for earlier, later in zip(self.spoke, self.spoke[1:])
        ]
        return sum(gaps) / len(gaps) / 60

    def summary(self) -> str:
        if not self.spoke:
            return "nothing was said"
        speakers = {}
        for line in self.spoke:
            speakers[line.speaker] = speakers.get(line.speaker, 0) + 1
        share = ", ".join(f"{name} {count}" for name, count in sorted(speakers.items()))
        return (
            f"{len(self.spoke)} messages over {self.hours:.1f}h "
            f"({self.per_hour:.1f}/hour, mean gap {self.mean_gap_minutes:.1f} min) -- {share}"
        )


def simulate(
    director: Director,
    *,
    start: datetime,
    hours: float = 24.0,
    tick: timedelta = TICK,
) -> Simulation:
    """Step the clock and collect what the room said."""
    now = start
    end = start + timedelta(hours=hours)
    while now < end:
        director.tick(now)
        now += tick
    return Simulation(start=start, end=end, spoke=tuple(director.spoke))
