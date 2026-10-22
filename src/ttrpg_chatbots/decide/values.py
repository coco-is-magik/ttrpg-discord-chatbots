"""What values does this line get?

The templates in a phrasebook contain slots -- `{hook}`, `{grievance}`, `{name}` -- and this module is
the only place they are filled from. Keeping it separate is what stops a phrasebook from becoming a
second brain: the book decides *how* a thing is said, this decides *what* the thing is.

Every value is optional and every slot is checked downstream, so a missing life produces an abstain
rather than a line reading `{hook}`.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from datetime import date

from ttrpg_chatbots.conv.types import Event
from ttrpg_chatbots.life.state import Activity, Grievance, Life, Plan, Story
from ttrpg_chatbots.memory.long import Fact


def _activity_values(activity: Activity | None) -> dict[str, str]:
    if activity is None:
        return {}
    return {
        "doing": activity.doing,
        "short": activity.short,
        "hook": activity.hook or activity.short,
        "phase": activity.phase,
        "why": activity.why,
        "invite": activity.invite,
        "topic": activity.topic,
    }


def _grievance_values(grievance: Grievance | None) -> dict[str, str]:
    if grievance is None:
        return {}
    return {
        "grievance": grievance.text,
        "about": grievance.about,
        "grievance_invite": grievance.invite,
    }


def build(
    *,
    job: str,
    life: Life | None = None,
    day: date | str | None = None,
    name: str = "",
    subject: str = "",
    facts: Iterable[Fact] = (),
    remembered: Fact | None = None,
    subject_text: str = "",
    events: Sequence[Event] = (),
    story: Story | None = None,
    point: bool = False,
    plan: Plan | None = None,
) -> dict[str, str]:
    """The slot values for one line.

    Only what the job can actually use: a greeting has no business knowing what he is building, and
    handing every job every value is how a phrasebook grows a hook nobody asked for.
    """
    values: dict[str, str] = {"name": name.strip(), "subject": subject.strip()}
    for fact in facts:
        values[f"fact_{_slug(fact.key)}"] = fact.value

    if subject_text.strip():
        # What he says about a subject he knows: a stance when the dataset has one, the fact
        # otherwise. Same slot name either way, so a phrasebook does not care which it got.
        values["fact"] = subject_text.strip()

    if story is not None:
        values["story_body"] = story.body
        values["story_topic"] = story.topic
        if point or not story.point:
            # The point is only ever handed over when it was asked for; the body is what a story
            # is, the point is what it meant.
            values["story_point"] = story.point
    if plan is not None:
        values["plan_what"] = plan.what
        values["plan_when"] = plan.when
        values["plan_why"] = plan.why

    phrase = _event_phrase(events)
    if phrase:
        values["event_phrase"] = phrase

    if remembered is not None:
        # The three words a recall line needs: the value ("otis"), the word the person uses for it
        # ("dog"), and the kind ("pet").
        values["fact_value"] = remembered.value
        values["fact_word"] = str(remembered.meta.get("word") or remembered.key.split(".")[0])
        values["fact_key"] = remembered.key
        values["fact_kind"] = remembered.key.split(".")[0]

    if job in ("offer_hook", "explain"):
        values.update(_activity_values(life.current(day) if life else None))
    elif job == "mirror":
        values.update(_grievance_values(life.grievance(day) if life else None))
    return values


def _event_phrase(events: Sequence[Event]) -> str:
    """What is happening, as a clause a person would say.

    Upcoming things are news ("the season opener is tomorrow"); something already running is a state
    ("it's the hockey season"). The phrasebook gets one ready-made clause so it never has to know
    which kind it was handed.
    """
    if not events:
        return ""
    coming = [event for event in events if event.days_away >= 1]
    if coming:
        soonest = coming[0]
        when = "tomorrow" if soonest.days_away == 1 else "this week"
        name = soonest.short or soonest.label
        return f"{name} is {when}" if not soonest.short else f"{name} {when}"
    first = events[0]
    return first.short or f"it is {first.label}"


def _slug(key: str) -> str:
    """``pet.name`` becomes ``pet_name``, so a template can name a fact directly."""
    return "".join(char if char.isalnum() else "_" for char in key).strip("_")


def missing(template: str, values: Mapping[str, str]) -> tuple[str, ...]:
    """Slots the template needs that this job cannot fill.

    Reported rather than raised: a phrase that cannot be filled is a phrase to skip, and the caller
    decides whether anything else is left.
    """
    from string import Formatter

    needed: list[str] = []
    for _, field, _, _ in Formatter().parse(template):
        if not field:
            continue
        if not str(values.get(field, "")).strip():
            needed.append(field)
    return tuple(needed)


def slots_of(templates: Sequence[str]) -> tuple[str, ...]:
    """Every slot any of these templates needs, for a dataset check."""
    seen: list[str] = []
    for template in templates:
        for slot in missing(template, {}):
            if slot not in seen:
                seen.append(slot)
    return tuple(seen)
