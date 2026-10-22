"""Acronyms: whether a run of capitals is spelled out or said as a word.

``NCAA`` is five syllables spelled out; ``NASA`` is a word. Nothing in the text says which, so the
answer is a list -- and the list is data, because the wrong answer is immediately audible. Words
people already say as words (``TV``, ``OK``) are exempt, and so is a single letter, because "I" is a
word.
"""

from __future__ import annotations

import re

from ttrpg_chatbots.tts.spoken.tables import NEVER_SPELLED, SAID_AS_WORDS

CAPS = re.compile(r"\b[A-Z]{2,6}\b")

#: ``AT&T`` is "A T and T": the ampersand joins two spelled runs, it is not a symbol of its own.
JOINED = re.compile(r"(?<=[A-Z])&(?=[A-Z])")


def _expand(match: re.Match[str]) -> str:
    word = match.group(0)
    if word in SAID_AS_WORDS or word in NEVER_SPELLED:
        return word
    return " ".join(word)


def expand(text: str) -> str:
    """Spell out the capitals that are not said as words."""
    text = JOINED.sub(" and ", text)
    return CAPS.sub(_expand, text)
