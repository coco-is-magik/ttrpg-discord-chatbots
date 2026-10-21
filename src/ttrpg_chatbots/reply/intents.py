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

from ttrpg_chatbots.reply.text import normalise_typing

SOCIAL_GREETING = "social:greeting"
SOCIAL_PRESENCE = "social:presence"
SOCIAL_HOWAREYOU = "social:howareyou"
SOCIAL_THANKS = "social:thanks"
SOCIAL_GOODBYE = "social:goodbye"
SOCIAL_APOLOGY = "social:apology"
SOCIAL_AGREEMENT = "social:agreement"
SOCIAL_SMALLTALK = "social:smalltalk"
# "Doing anything later?" is not presence and not smalltalk: it is somebody opening a door to
# spending time together, and the useful reply is an invitation, not a status report.
SOCIAL_PLANS = "social:plans"
# Somebody had a rough one and wants to say so. Not the same as struggling: this is an invitation
# to trade complaints, and the right answer is one of your own, not sympathy.
SOCIAL_ROUGH = "social:rough"
# "why?" on its own: a follow-up about whatever he just said. Only when the whole message is the
# question, so "why is the sky blue" stays a question about the sky.
SOCIAL_WHY = "social:why"
# Somebody is worried, stuck or worn down. This is a *move*, not a tone: a friend who cannot
# recognise it can only answer "I don't know about that", which is the worst possible reply to
# a person who has just admitted they are struggling.
SOCIAL_COMFORT = "social:comfort"

SOCIAL_TAGS = (
    SOCIAL_GREETING,
    SOCIAL_PRESENCE,
    SOCIAL_HOWAREYOU,
    SOCIAL_THANKS,
    SOCIAL_GOODBYE,
    SOCIAL_APOLOGY,
    SOCIAL_AGREEMENT,
    SOCIAL_SMALLTALK,
    SOCIAL_COMFORT,
    SOCIAL_PLANS,
    SOCIAL_ROUGH,
    SOCIAL_WHY,
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
        # Placed above thanks and agreement: "I'm nervous about tomorrow, thanks for asking"
        # is a person who needs an answer, not a person being polite.
        SOCIAL_COMFORT,
        r"\bi(?:'m| am) (?:so |really |very |kind of |a bit |pretty )?"
        r"(?:nervous|worried|scared|afraid|anxious|stressed|overwhelmed|exhausted|struggling)\b"
        r"|\bi(?:'m| am) not (?:ok|okay|fine|coping)\b"
        r"|\bi (?:can'?t|cannot) (?:cope|do this|handle (?:it|this))\b"
        r"|\bi don'?t know what to do\b"
        r"|\b(?:i )?(?:messed|screwed) (?:it |this )?up\b"
        r"|\bi failed\b"
        r"|\bhelp me (?:out|with this|please)\b",
    ),
    (
        SOCIAL_PLANS,
        r"\bdoing anything (?:later|tonight|tomorrow|this weekend)\b"
        r"|\bgot plans\b"
        r"|\bany plans\b"
        r"|\bfree (?:later|tonight|tomorrow|this weekend|this week)\b"
        r"|\bwhat(?:'?re| are) (?:you|u) (?:doing|up to) (?:later|tonight|tomorrow)\b"
        r"|\bup to anything (?:later|tonight|tomorrow)\b",
    ),
    (
        SOCIAL_PRESENCE,
        r"\bany(?:one|body) (?:around|about|here|on)\b"
        r"|\bare you around\b"
        r"|\byou around\b"
        r"|\banyone up\b"
        # "doing anything later?" is a presence question, not a closing and not a fact.
        r"|\bdoing anything\b"
        r"|\bgot plans\b"
        r"|\bup to anything\b",
    ),
    (
        SOCIAL_THANKS,
        r"\bthanks?\b|\bthank you\b|\bcheers\b|\bta\b|\bappreciate it\b",
    ),
    (
        SOCIAL_GOODBYE,
        # A closing is a whole message, not a word inside one. "doing anything later?" is a
        # question, and answering it with a farewell ends the conversation by accident -- which
        # is exactly what happened on 2026-10-21. Anchored, with an optional lead-in so
        # "ok later" and "alright, night" still count.
        r"^(?:ok|okay|alright|right|well|aight|yeah)?[, ]*"
        r"(?:bye|byebye|goodbye|good night|night|nights|see you|see ya|cya|later|"
        r"catch you|catch you later|take care|ttyl|talk later|off to bed|i'?m off)\b",
    ),
    (SOCIAL_APOLOGY, r"\bsorry\b|\bapologies\b|\bmy bad\b"),
    (
        SOCIAL_AGREEMENT,
        r"^(?:ok|okay|sure|yeah|yep|yes|sounds good|works for me|deal)\b",
    ),
    (
        SOCIAL_GREETING,
        r"^(?:hi|hey|heyo|hello|yo|hiya|howdy|morning|evening)\b"
        r"|^good (?:morning|evening|afternoon)\b",
    ),
    (
        SOCIAL_ROUGH,
        r"\brough (?:day|one|week|night)\b"
        r"|\blong (?:day|one|week)\b"
        r"|\bbad (?:day|one|week)\b"
        r"|\bwork (?:was|sucked|is killing me|has been)\b"
        r"|\bwork'?s (?:a nightmare|madness|been mad)\b"
        r"|\bknackered\b"
        r"|\bwrecked\b"
        r"|\bslammed\b",
    ),
    (
        SOCIAL_WHY,
        r"^(?:why|why'?s that|how come|how so|what for|why not)\??$",
    ),
    (
        SOCIAL_SMALLTALK,
        # "what's good", "what's cookin", "what are you up to": the same move in different clothes.
        r"\bwhat'?s up\b"
        r"|\bnot much\b"
        r"|\bhow'?s your day\b"
        r"|\bsame as usual\b"
        r"|\bwhat'?s good\b"
        r"|\bwhat'?s cook\w*\b"
        r"|\bwhat'?s new\b"
        r"|\bhow goes\b"
        r"|\bwhat (?:are|r) (?:you|u) up to\b"
        r"|\bwhat you up to\b"
        r"|\bwhatcha (?:up to|doing)\b",
    ),
)

_COMPILED: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (tag, re.compile(pattern)) for tag, pattern in _PATTERNS
)


def normalise(text: str) -> str:
    """Reduce a message to the vocabulary the patterns are written against.

    Whitespace, case, repeated letters, missing apostrophes and texting spellings are all
    handled in :func:`ttrpg_chatbots.reply.text.normalise_typing`, so a pattern never has to
    enumerate the ways somebody might type "what's up".
    """
    return normalise_typing(text)


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
