"""How much to say.

Mirroring, with a floor and a ceiling. Our old corpus ran a median of 7 words against the human's 2,
which is what "written" sounds like; the budget makes brevity a constraint rather than a taste.
"""

from __future__ import annotations

from ttrpg_chatbots.conv.types import Budget

FLOOR = 3
CEILING = 14


def budget(*, their_words: int, phase: str = "pleasantries") -> Budget:
    """Their length plus two, clamped; two sentences only when the conversation has depth."""
    words = max(FLOOR, min(CEILING, int(their_words) + 2))
    sentences = 2 if phase == "substance" else 1
    return Budget(max_words=words, max_sentences=sentences)
