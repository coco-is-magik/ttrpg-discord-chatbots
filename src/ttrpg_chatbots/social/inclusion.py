"""Who may speak.

The anti-chorus policy, as code. Three rules, each from a failure the design already names:

* **Nobody speaks twice in a row.** A friend answering themselves is the clearest tell there is.
* **Nobody speaks inside the floor.** Two messages a second apart is a burst, whatever the cadence drew.
* **The quietest friend goes first**, weighted rather than strict -- strict rotation is as mechanical as
a metronome.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta

from ttrpg_chatbots.ambient.room import Room

#: How long a friend waits after speaking before they may speak again, even if chosen.
SELF_GAP = timedelta(minutes=3)
#: The most "overdue" a friend can be, for weighting purposes. See `choose`.
MAX_WEIGHT_SECONDS = 1800.0


def candidates(room: Room, friends: tuple[str, ...], now: datetime) -> tuple[str, ...]:
    """Who is allowed to speak at all."""
    last = room.last
    allowed = [
        friend
        for friend in friends
        if not room.spoke_recently(friend, now, SELF_GAP)
        and not (last is not None and last.speaker == friend and not last.is_human)
    ]
    return tuple(allowed)


def choose(
    room: Room,
    friends: tuple[str, ...],
    now: datetime,
    *,
    rng: random.Random | None = None,
) -> str | None:
    """The next speaker, weighted by how long they have been quiet, or None if nobody may."""
    allowed = candidates(room, friends, now)
    if not allowed:
        return None
    if len(allowed) == 1:
        return allowed[0]
    draw = rng or random.Random()
    # Capped, and the cap matters: a friend who has never spoken is *infinitely* overdue, and an
    # uncapped weight made them the speaker every single time -- a strict rotation by another name.
    # Past half an hour, "very overdue" is all the same amount of overdue.
    weights = [
        min(room.quiet_for(friend, now).total_seconds(), MAX_WEIGHT_SECONDS)
        for friend in allowed
    ]
    return draw.choices(allowed, weights=weights, k=1)[0]
