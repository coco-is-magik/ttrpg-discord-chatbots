"""Template plus values equals text.

Thin by design: the existing madlib renderer behind one name, so the ladder has one place to call
and one place to test. A missing slot refuses rather than printing ``{slot}``."""

from __future__ import annotations

from typing import Mapping

from ttrpg_chatbots.reply import madlib


def render(template: str, values: Mapping[str, str] | None = None) -> str | None:
    """The filled template, or ``None`` if a slot cannot be filled."""
    try:
        text = madlib.render(template, dict(values or {}))
    except (madlib.MissingSlot, ValueError):
        return None
    return text.strip() or None
