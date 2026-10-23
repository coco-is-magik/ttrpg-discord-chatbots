"""Does he hand the turn back?

A question is the cheapest way to keep a conversation alive, and the cheapest way to make it feel
like an interview. So: yes for a hook, no for a terse human, never twice in a row."""

from __future__ import annotations

import hashlib

from ttrpg_chatbots.conv.types import Form, Reciprocate, Tone

#: How much more likely he is to engage with an answer than to ask out of the blue. Being answered is
#: the strongest invitation a conversation offers, so the same persona asks more readily here.
ANSWERED_BONUS = 1.5


def choose(*, form: Form, tone: Tone = "neutral", already_asked: bool = False) -> Reciprocate:
    """Question, space, or nothing."""
    if already_asked:
        return Reciprocate("none")
    if tone == "terse":
        return Reciprocate("space")
    if form in ("clause_question", "two_beat"):
        return Reciprocate("question")
    return Reciprocate("none")


def engage(
    *,
    question_rate: float,
    text: str,
    tone: Tone = "neutral",
    already_asked: bool = False,
    theirs: bool = False,
    bad_news: bool = False,
) -> bool:
    """Whether the turn belongs to what *they* said -- an engaged follow-up rather than a bare note.

    Two signals, and both mean the same thing: there is something of theirs to pick up.

    * **They answered a question of his** (`already_asked`). The strongest invitation a conversation
      offers, so the bar is lower: `question_rate` is scaled by `ANSWERED_BONUS`.
    * **They said something about themselves** (`theirs` -- a first-person statement).

    Measured, and this is the whole point of the split: the first version spent the turn asking
    "what about you?" in reply to *"i have been rebuilding a fence myself this month"*. They had just
    said what they were doing; asking them what they were doing reads as not having listened.
    """
    if question_rate <= 0.0 or bad_news:
        # **Never curious about bad news.** Curiosity is for news that is neutral or good; a person who
        # says their cat died does not want "is it any good?". This is a guard rather than a routing
        # rule on purpose: it holds even when the routing misses the message entirely.
        return False
    if tone in ("terse", "flat"):
        return False
    if not (already_asked or theirs):
        return False
    rate = question_rate * ANSWERED_BONUS if already_asked else question_rate
    return _roll(text, min(1.0, rate))


def hand_back(
    *,
    question_rate: float,
    text: str,
    tone: Tone = "neutral",
    he_spoke: bool = False,
) -> bool:
    """Whether he hands the turn back with a question about *them*.

    Only after **he** has just spoken about himself -- he offered a hook or explained something -- which
    is when "what about you?" is the natural thing to say. Measured: with the trigger the wrong way
    round, every statement they made was answered with a question about themselves.
    """
    if question_rate <= 0.0 or not he_spoke:
        return False
    if tone in ("terse", "flat"):
        return False
    return _roll(text, question_rate)


def _roll(text: str, rate: float) -> bool:
    """A stable yes/no keyed on the message, so a replay is a replay."""
    if rate <= 0.0:
        return False
    roll = int.from_bytes(hashlib.blake2b(text.encode("utf-8"), digest_size=4).digest(), "big")
    return (roll % 10_000) < int(rate * 10_000)


def ask_about_them(
    *,
    question_rate: float,
    text: str,
    tone: Tone = "neutral",
    already_asked: bool = False,
) -> bool:
    """Deprecated name kept for the callers that predate the split: see :func:`hand_back`."""
    return hand_back(
        question_rate=question_rate,
        text=text,
        tone=tone,
        he_spoke=not already_asked,
    )
