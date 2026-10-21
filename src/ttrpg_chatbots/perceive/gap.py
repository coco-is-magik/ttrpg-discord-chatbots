"""How long since this person last spoke.

The single most useful piece of context for a greeting: five minutes and fourteen hours are
different greetings, and a week is different again.
"""

from __future__ import annotations

from datetime import datetime, timezone

from ttrpg_chatbots.conv.types import Gap

MINUTE = 60.0
HOUR = 60 * MINUTE
DAY = 24 * HOUR


def _when(value: str | datetime | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def read(*, last_seen: str | datetime | None, now: datetime | None = None) -> Gap:
    """The gap, bucketed the way a person thinks about it."""
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    seen = _when(last_seen)
    if seen is None:
        return Gap(seconds=float("inf"), bucket="new")
    seconds = max(0.0, (current - seen).total_seconds())
    if seconds < 5 * MINUTE:
        bucket = "fresh"
    elif seconds < 8 * HOUR:
        bucket = "today"
    elif seconds < 26 * HOUR:
        bucket = "day"
    elif seconds < 8 * DAY:
        bucket = "week"
    else:
        bucket = "long"
    return Gap(seconds=seconds, bucket=bucket)
