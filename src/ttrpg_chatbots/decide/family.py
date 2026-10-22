"""Which kind of phrasing?

Warm, casual, time-aware, dry -- chosen from how well he knows the person and what time it is, never
from the message, which is what stops "morning" from being said at nine at night.

For the jobs where the *phase* matters more than the register -- a reaction to your bad day versus the
detail of his own -- depth decides the family instead. One question, one answer: which kind of
phrasing is this line.
"""

from __future__ import annotations

from ttrpg_chatbots.conv.types import Family, Job, Relationship


def choose(
    *,
    job: Job,
    relationship: Relationship,
    part_of_day: str = "afternoon",
    depth: int = 0,
) -> Family:
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
    if job == "mirror":
        # Depth 0 is a reaction and nothing else. The grievance only appears once they have leaned
        # in, which is the whole reason a bad day does not turn into a monologue.
        return "detail" if depth >= 1 else "reaction"
    if job in ("explain", "tell_story"):
        return "detail"
    if job == "reassure":
        return "reassure"
    if job == "close":
        return "closing"
    if job == "noted":
        return "noted"
    if job == "hedge":
        return "hedge"
    if relationship.warmth >= 2:
        return "warm"
    if relationship.stage == "new":
        return "dry"
    return "casual"
