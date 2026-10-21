"""How are they saying it?

Deliberately separate from sentiment: "that's great, another inspection" is positive wording with
negative feeling and a flat tone. Tone is about *delivery* -- volume, brevity, laughter, trailing
off -- and it is read from a short lexicon, not guessed at.
"""

from __future__ import annotations

import re

from ttrpg_chatbots.conv.types import Tone
from ttrpg_chatbots.reply.text import normalise_typing

_WARM = re.compile(r"\b(?:haha+|lol|lmao|hah|😂|😄|❤|love it|nice one)\b")
_FLAT = re.compile(r"^(?:k|ok|fine|sure|whatever|mm+|hm+)\b|\s*\.\.\.$")
_TEASING = re.compile(r"\b(?:you clown|ya donkey|shut up|no way)\b|\b(?:mate|bud)\b.*\?")


def read(text: str) -> Tone:
    """Warm, terse, teasing, flat or neutral -- in that order of confidence."""
    cleaned = normalise_typing(text)
    if not cleaned:
        return "flat"
    if _WARM.search(cleaned):
        return "warm"
    if _TEASING.search(cleaned):
        return "teasing"
    if _FLAT.search(cleaned):
        return "flat"
    if len(cleaned.split()) <= 2 and not cleaned.endswith("?"):
        return "terse"
    return "neutral"
