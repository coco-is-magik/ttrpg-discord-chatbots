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
#: Answering a question is longer than asking it. Measured: "what is on it?" is four words, so the budget
#: came out at six and the answer lost its ending -- "a ceramic frog, a tin train, and a leaf i pressed"
#: arrived as "a ceramic frog, a tin train". The floor is what an answer to a question needs.
ANSWER_FLOOR = 16


#: How much room a person needs before they are allowed a third sentence. Above this, `verbosity` buys
#: one: a rambler does not say the same thing in more words, they say more things.
RAMBLING = 1.4


def budget(
    *,
    their_words: int,
    phase: str = "pleasantries",
    story: bool = False,
    answer: bool = False,
    verbosity: float = 1.0,
) -> Budget:
    """Their length plus two, clamped; two sentences only when the conversation has depth.

    ``verbosity`` is the persona's own multiplier, because how much a person says is a property of the
    person: at 1.0 nothing changes, at 1.5 a friend is allowed half again as many words, and above
    :data:`RAMBLING` they get a third sentence as well. Measured against one friend who writes four-word
    lines and another whose brief says she "overexplains and rambles" -- one ladder, two registers.
    """
    if isinstance(verbosity, bool) or not isinstance(verbosity, (int, float)):
        raise ValueError("verbosity must be a number")
    if not 0.5 <= float(verbosity) <= 3.0:
        raise ValueError(f"verbosity must be between 0.5 and 3.0, got {verbosity}")
    factor = float(verbosity)
    base = max(FLOOR, min(CEILING, int(their_words) + 2))
    words = max(FLOOR, int(round(base * factor)))
    if story:
        return Budget(
            max_words=max(STORY_FLOOR, int(round(STORY_FLOOR * factor))),
            max_sentences=3 if factor >= RAMBLING else 2,
        )
    if phase == "substance":
        words = max(int(round(CONTENT_FLOOR * factor)), words)
    if answer:
        # Answering a question somebody asked: longer than the question, and not a ramble. Same shape as
        # the story floor, for the same reason -- the material was written for this and the mirror rule
        # does not apply to it.
        words = max(int(round(ANSWER_FLOOR * factor)), words)
        return Budget(max_words=words, max_sentences=2 if factor < RAMBLING else 3)
    sentences = 2 if phase == "substance" else 1
    if factor >= RAMBLING:
        sentences += 1
    return Budget(max_words=words, max_sentences=sentences)
