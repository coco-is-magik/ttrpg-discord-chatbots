"""Does he hand the turn back?

A question is the cheapest way to keep a conversation alive, and the cheapest way to make it feel
like an interview. So: yes for a hook, no for a terse human, never twice in a row."""

from __future__ import annotations

from ttrpg_chatbots.conv.types import Form, Reciprocate, Tone


def choose(*, form: Form, tone: Tone = "neutral", already_asked: bool = False) -> Reciprocate:
    """Question, space, or nothing."""
    if already_asked:
        return Reciprocate("none")
    if tone == "terse":
        return Reciprocate("space")
    if form in ("clause_question", "two_beat"):
        return Reciprocate("question")
    return Reciprocate("none")
