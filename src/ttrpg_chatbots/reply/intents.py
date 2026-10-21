"""Social intents: the fast, deterministic half of the classifier.

The compression classifier is good at *"which fact is this about"* and poor at *"is this a
greeting"*. Measured on the friend dataset: ``hey`` scores 0.92 against its own anchor, while
``tell me about the guild`` scores 0.71 against an apology -- so no single distance threshold can
separate smalltalk from a lore question.

So the handful of moves a group makes constantly are matched first, by a small lexicon. Only
when no social intent matches does knowledge classification run. This is not a language model
and does not pretend to be: it recognises a fixed set of moves, and everything else is left to
the fact classifier or to an honest "I don't know".

Patterns are ordered from specific to general, because ``"hey, anyone around tonight?"`` is a
presence question, not a greeting, and ``"good night"`` is a goodbye, not a greeting.
"""

from __future__ import annotations

import re

SOCIAL_GREETING = "social:greeting"
SOCIAL_PRESENCE = "social:presence"
SOCIAL_HOWAREYOU = "social:howareyou"
SOCIAL_THANKS = "social:thanks"
SOCIAL_GOODBYE = "social:goodbye"
SOCIAL_APOLOGY = "social:apology"
SOCIAL_AGREEMENT = "social:agreement"
SOCIAL_SMALLTALK = "social:smalltalk"

SOCIAL_TAGS = (
    SOCIAL_GREETING,
    SOCIAL_PRESENCE,
    SOCIAL_HOWAREYOU,
    SOCIAL_THANKS,
    SOCIAL_GOODBYE,
    SOCIAL_APOLOGY,
    SOCIAL_AGREEMENT,
    SOCIAL_SMALLTALK,
)

# (tag, pattern) in priority order. `^` anchors are deliberate for the short moves, which are
# only greetings or agreements when they open the message.
_PATTERNS: tuple[tuple[str, str], ...] = (
    (
        SOCIAL_HOWAREYOU,
        r"\bhow (?:are|r) (?:you|u)\b"
        r"|\bhow'?s it going\b"
        r"|\bhow are things\b"
        r"|\bhow have you been\b"
        r"|\byou (?:ok|okay)\b",
    ),
    (
        SOCIAL_PRESENCE,
        r"\bany(?:one|body) (?:around|about|here|on)\b"
        r"|\bare you around\b"
        r"|\byou around\b"
        r"|\banyone up\b",
    ),
    (
        SOCIAL_THANKS,
        r"\bthanks?\b|\bthank you\b|\bcheers\b|\bta\b|\bappreciate it\b",
    ),
    (
        SOCIAL_GOODBYE,
        r"\bbye\b|\bgoodbye\b|\bsee you\b|\bgood night\b|\bnight\b|\blater\b",
    ),
    (SOCIAL_APOLOGY, r"\bsorry\b|\bapologies\b|\bmy bad\b"),
    (
        SOCIAL_AGREEMENT,
        r"^(?:ok|okay|sure|yeah|yep|yes|sounds good|works for me|deal)\b",
    ),
    (
        SOCIAL_GREETING,
        r"^(?:hi|hey|hello|yo|hiya|morning|evening)\b"
        r"|^good (?:morning|evening|afternoon)\b",
    ),
    (SOCIAL_SMALLTALK, r"\bwhat'?s up\b|\bnot much\b|\bhow'?s your day\b|\bsame as usual\b"),
)

_COMPILED: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (tag, re.compile(pattern)) for tag, pattern in _PATTERNS
)


def normalise(text: str) -> str:
    """Lower-case and collapse whitespace; punctuation is kept for word boundaries."""
    return " ".join((text or "").lower().split())


def match_all(text: str) -> tuple[str, ...]:
    """Every social tag this message could be, in priority order.

    Patterns overlap on purpose -- ``"hey, anyone around?"`` is both a greeting and a
    presence question -- so the caller gets all of them and decides. Priority is the order
    of ``_PATTERNS``, which is why the specific moves are listed before the general ones.
    """
    cleaned = normalise(text)
    if not cleaned:
        return ()
    found: list[str] = []
    for tag, pattern in _COMPILED:
        if tag not in found and pattern.search(cleaned):
            found.append(tag)
    return tuple(found)


def match_intent(text: str) -> str | None:
    """The social tag this message belongs to, or ``None`` for anything else."""
    matches = match_all(text)
    return matches[0] if matches else None
