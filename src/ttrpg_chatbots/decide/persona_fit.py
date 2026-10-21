"""Does this candidate sound like him?

Three rules, each aimed at a failure we measured on the old corpus: a trailing beat (29% of lines had
one), exposition nobody asked for, and the aphorism that turns a sentence into a fortune cookie.
This is the rung that would have rejected most of the old content.
"""

from __future__ import annotations

import re

from ttrpg_chatbots.conv.types import Fit

_EXPOSITION = (
    "since i was",
    "when i was",
    "my uncle",
    "my grandfather",
    "growing up",
    "i've been a",
    "i have been a",
)
_APHORISM = (
    "same as anywhere",
    "that's the truth of it",
    "no big reason past",
    "and that's the whole",
    "there it is",
)


def _sentences(text: str) -> list[str]:
    parts = text.replace("!", ".").replace("?", ".").split(".")
    return [part.strip() for part in parts if part.strip()]


def read(text: str) -> Fit:
    """Fit, with the reasons it does not."""
    reasons: list[str] = []
    cleaned = " ".join((text or "").lower().split())
    sentences = _sentences(cleaned)
    if len(sentences) >= 2 and len(sentences[-1].split()) <= 5:
        reasons.append("ends on a beat")
    for phrase in _EXPOSITION:
        if phrase in cleaned:
            reasons.append("explains itself")
            break
    for phrase in _APHORISM:
        if phrase in cleaned:
            reasons.append("closes like a fortune cookie")
            break
    return Fit(ok=not reasons, reasons=tuple(reasons))
