"""Enforce the budget, or refuse.

Drops the *end* first -- a trailing clause or a second sentence -- because the last thing in a
written line is usually the button that made it sound written. If it still does not fit, the line is
refused so audition can ask for another variant."""

from __future__ import annotations

from ttrpg_chatbots.conv.types import Budget


def enforce(text: str, budget: Budget) -> str | None:
    """A line that fits, or ``None``."""
    candidate = text.strip()
    if budget.fits(candidate):
        return candidate
    parts = [
        part
        for part in candidate.replace("!", ".").replace("?", ".").split(".")
        if part.strip()
    ]
    if len(parts) > 1:
        candidate = parts[0].strip()
        if budget.fits(candidate):
            return candidate
    if "," in candidate:
        candidate = candidate.rsplit(",", 1)[0].strip()
        if budget.fits(candidate):
            return candidate
    return None
