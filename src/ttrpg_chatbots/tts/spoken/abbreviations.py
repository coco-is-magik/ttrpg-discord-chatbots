"""Abbreviations: a dot is not always the end of a sentence.

Multi-word forms (``et al.``, ``a.k.a.``) are replaced first, because the single-word pass would eat
half of them. One deliberate ambiguity is resolved here rather than guessed at silently: ``St.`` is
"Saint" before a capitalised name (St. Louis) and "Street" otherwise (Main St.), which is the reading
that is right more often in chat.
"""

from __future__ import annotations

import re

from ttrpg_chatbots.tts.spoken.tables import ABBREVIATIONS, PHRASES

SAINT = re.compile(r"\bSt\.\s+(?=[A-Z])")


def _pattern(key: str) -> re.Pattern[str]:
    return re.compile(rf"(?<![\w.]){re.escape(key)}", re.IGNORECASE)


def expand(text: str) -> str:
    """Say every abbreviation in the text."""
    text = SAINT.sub("Saint ", text)
    for phrase, spoken in PHRASES.items():
        text = _pattern(phrase).sub(spoken, text)
    for key, spoken in ABBREVIATIONS.items():
        text = _pattern(key).sub(spoken, text)
    return text
