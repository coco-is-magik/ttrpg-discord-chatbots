"""What values does this line get?

The templates in a phrasebook contain slots -- `{hook}`, `{grievance}`, `{name}` -- and this module is
the only place they are filled from. Keeping it separate is what stops a phrasebook from becoming a
second brain: the book decides *how* a thing is said, this decides *what* the thing is.

Every value is optional and every slot is checked downstream, so a missing life produces an abstain
rather than a line reading `{hook}`.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date

from ttrpg_chatbots.life.state import Activity, Grievance, Life


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
    facts: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """The slot values for one line.

    Only what the job can actually use: a greeting has no business knowing what he is building, and
    handing every job every value is how a phrasebook grows a hook nobody asked for.
    """
    values: dict[str, str] = {"name": name.strip(), "subject": subject.strip()}
    for key, value in (facts or {}).items():
        values[f"fact_{key}"] = str(value)

    if job in ("offer_hook", "explain"):
        values.update(_activity_values(life.current(day) if life else None))
    elif job == "mirror":
        values.update(_grievance_values(life.grievance(day) if life else None))
    return values


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
