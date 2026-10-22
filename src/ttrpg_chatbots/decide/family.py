"""Which kind of phrasing?

Warm, casual, time-aware, dry -- chosen from how well he knows the person and what time it is, never
from the message, which is what stops "morning" from being said at nine at night.

For the jobs where the *phase* matters more than the register -- a reaction to your bad day versus the
detail of his own -- depth decides the family instead. One question, one answer: which kind of
phrasing is this line.
"""

from __future__ import annotations

from ttrpg_chatbots.conv.types import Family, Job, Relationship

# Which way of remembering each job welcomes. An opening may ask after your dog unprompted; a
# question he cannot answer may only ask after it when *they* raised it. Measured: getting this
# wrong meant "what is the plot of dune?" was answered with a question about a dog.
RECALL_MODES: dict[str, frozenset[str]] = {
    "greet": frozenset({"session", "raised"}),
    "offer_hook": frozenset({"session", "raised"}),
    "noted": frozenset({"raised"}),
    "hedge": frozenset({"raised"}),
}
RECALLING: frozenset[str] = frozenset(RECALL_MODES)


def choose(
    *,
    job: Job,
    relationship: Relationship,
    part_of_day: str = "afternoon",
    depth: int = 0,
    recall: str = "",
    subject: bool = False,
    event: bool = False,
    plan: bool = False,
    story: bool = False,
    point: bool = False,
) -> Family:
    """The register this line belongs in."""
    if point and job == "explain":
        # The point of a story he just told: the only phrasing that answers "what was the point of
        # that", and unreachable unless the story came first.
        return "point"
    if story and job == "tell_story":
        return "story"
    if plan and job == "offer_hook":
        # An invitation beats a calendar fact: one is something he wants to do with you, the
        # other is something happening near him.
        return "plan"
    if event and job == "offer_hook":
        # Asked what he is up to, with something on this week: the news is the answer. Recall
        # outranks it, because a question about your dog matters more than his calendar.
        return "event"
    if recall and recall in RECALL_MODES.get(job, frozenset()):
        # A phrasing that remembers what they told him outranks the register: it is the whole
        # point of the line.
        return "recall"
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
        return "subject" if subject else "detail"
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
