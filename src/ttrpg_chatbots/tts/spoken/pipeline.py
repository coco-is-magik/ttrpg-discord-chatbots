"""The order, which is the part that is easy to get wrong.

``$250`` is the proof. Run symbols first and the dollar sign becomes "dollars" before the digits are
read, giving "dollars two hundred fifty"; run numbers first and the digits become words before the
symbol is recognised, giving "dollar sign two hundred fifty". Money has to claim the pair, so it runs
first. Then symbols (so ``%`` is a word before the digits become words), then numbers, then the two
word-level passes.

Every step is a pure string function, so the whole thing is testable without an engine, and the
text channel is untouched: this runs only on the way to a voice.
"""

from __future__ import annotations

from ttrpg_chatbots.tts.spoken import abbreviations, acronyms, money, numbers, symbols

#: The pipeline, in order, as data -- so the order is inspectable and testable.
STEPS = (
    ("money", money.expand),
    ("symbols", symbols.expand),
    ("numbers", numbers.expand),
    ("abbreviations", abbreviations.expand),
    ("acronyms", acronyms.expand),
)


def say(text: str) -> str:
    """The spoken form of ``text``. Never empty, never raises."""
    spoken = text
    for _, step in STEPS:
        spoken = step(spoken)
    spoken = " ".join(spoken.split())
    return spoken or text
