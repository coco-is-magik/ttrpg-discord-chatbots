"""Which kind of phrasing?

Warm, casual, time-aware, name-based or dry. Chosen from how well he knows the person and what time
it is -- never from the message, which is what stops "morning" from being said at nine at night."""

from __future__ import annotations

from ttrpg_chatbots.conv.types import Family, Job, Relationship


def choose(*, job: Job, relationship: Relationship, part_of_day: str = "afternoon") -> Family:
    """The register this line belongs in."""
    if job == "greet":
        # One family per part of day. Before this, "which family" answered "time_aware" and
        # "which variant" then picked an unused line -- so "morning" arrived at 19:20. A family
        # chosen by the clock may only contain lines the clock allows.
        if relationship.warmth >= 1:
            if part_of_day == "morning":
                return "time_morning"
            if part_of_day == "evening":
                return "time_evening"
        if relationship.warmth >= 2:
            return "warm"
        return "casual"
    if relationship.warmth >= 2:
        return "warm"
    if relationship.stage == "new":
        return "dry"
    return "casual"
