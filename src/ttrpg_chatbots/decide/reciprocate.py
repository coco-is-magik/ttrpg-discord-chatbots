"""Does he hand the turn back?

A question is the cheapest way to keep a conversation alive, and the cheapest way to make it feel
like an interview. So: yes for a hook, no for a terse human, never twice in a row."""

from __future__ import annotations

import hashlib

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


def ask_about_them(
    *,
    question_rate: float,
    text: str,
    tone: Tone = "neutral",
    already_asked: bool = False,
) -> bool:
    """Whether he spends this turn asking about *them* rather than only noting what they said.

    This is the knob behind "he prefers to listen and prompts you to keep talking": the rung decides
    *whether* to hand the turn back, and `question_rate` decides how often he would rather do that than
    answer with a bare acknowledgement. Otto 0.8, Terry 0.2 -- same architecture, different person.

    Three refusals, each for a reason:

    * ``question_rate`` of 0 means never, so a friend who does not do this simply does not.
    * A terse or flat reply from them is not an invitation ("k", "fine") -- asking "what about you?"
    into that is the interview problem.
    * **Never twice in a row.** Two questions back to back is an interrogation, and the whole point of
      handing the turn back is that it should feel like interest rather than process.

    The roll is keyed on the message, so the same message always gets the same treatment and a replay
    is a replay.
    """
    if question_rate <= 0.0:
        return False
    if already_asked or tone in ("terse", "flat"):
        return False
    roll = int.from_bytes(hashlib.blake2b(text.encode("utf-8"), digest_size=4).digest(), "big")
    return (roll % 10_000) < int(question_rate * 10_000)
