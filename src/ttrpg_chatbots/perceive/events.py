"""What is happening in his world that he would care about.

The calendar already knows; this module flattens it into the one shape a reply stage wants: a label,
how far away it is, and which subjects it belongs to."""

from __future__ import annotations

from datetime import date

from ttrpg_chatbots.conv.types import Event


def read(calendar, today: date, *, days: int = 7) -> tuple[Event, ...]:
    """Today's events first, then what is coming inside the window."""
    events = [
        Event(label=entry.title, days_away=0, topics=entry.topics, short=entry.short)
        for entry in calendar.ongoing(today)
    ]
    for item in calendar.upcoming(today, days=days):
        events.append(
            Event(
                label=item.entry.title,
                days_away=item.days_away,
                topics=item.entry.topics,
                short=item.entry.short,
            )
        )
    return tuple(events)
