"""What should be forgotten?

Age is the only rule worth having now: something said once, a long time ago, about something never
mentioned again, is not memory -- it is clutter. Anything said twice, or about a pet, is kept.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timezone

from ttrpg_chatbots.memory.long import Fact


def due(
    facts: Iterable[Fact], *, now: datetime | None = None, max_age_days: int = 120
) -> tuple[str, ...]:
    """Keys that have gone stale."""
    current = now or datetime.now(timezone.utc)
    stale: list[str] = []
    for fact in facts:
        if fact.count >= 2 or fact.key.startswith(("pet.", "job")):
            continue
        if not fact.last_seen:
            continue
        try:
            seen = datetime.fromisoformat(fact.last_seen)
        except ValueError:
            continue
        if seen.tzinfo is None:
            seen = seen.replace(tzinfo=timezone.utc)
        if (current - seen).days > max_age_days:
            stale.append(fact.key)
    return tuple(stale)
