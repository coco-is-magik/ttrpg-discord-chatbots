"""How much to say.

Mirroring, with a floor and a ceiling. Our old corpus ran a median of 7 words against the human's 2,
which is what "written" sounds like; the budget makes brevity a constraint rather than a taste.

One exception, and it is a measured one. A *reaction* mirrors: "what are you up to" gets a few words,
because naming the thing is the whole answer. An *explanation* does not -- "why?" is a request for the
reason, and answering a one-word question with a three-word limit produces a shrug. So substance gets
a floor of twelve words and a second sentence, which is exactly enough for one reason and no more.
"""

from __future__ import annotations

from ttrpg_chatbots.conv.types import Budget

FLOOR = 3
CEILING = 14
CONTENT_FLOOR = 12
# A story is two sentences of something that happened. Measured: the bodies are 20-22 words, so a
# substance budget of twelve refused every one of them and the story stage went silent.
STORY_FLOOR = 26


def budget(*, their_words: int, phase: str = "pleasantries", story: bool = False) -> Budget:
    """Their length plus two, clamped; two sentences only when the conversation has depth."""
    words = max(FLOOR, min(CEILING, int(their_words) + 2))
    if story:
        return Budget(max_words=STORY_FLOOR, max_sentences=2)
    if phase == "substance":
        words = max(CONTENT_FLOOR, words)
    sentences = 2 if phase == "substance" else 1
    return Budget(max_words=words, max_sentences=sentences)
