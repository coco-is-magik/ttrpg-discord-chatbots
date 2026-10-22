"""Where in the arc are we?

Opening, pleasantries, hook, substance, closing -- and most conversations never leave the first two.
The phase decides how *deep* a reply may go, which is the structural cure for exposition.
"""

from __future__ import annotations

from ttrpg_chatbots.conv.types import Phase


def read(
    *,
    turns_today: int = 0,
    closing: bool = False,
    named_subject: bool = False,
    depth: int = 0,
    asked_why: bool = False,
    known_subject: bool = False,
    story: bool = False,
) -> Phase:
    """The most specific phase the evidence supports.

    Two things jump the queue. `asked_why`: "why?" is a request for the reason, and the reason is the
    substance tier -- treating it as pleasantries is how a person gets a shrug instead of an answer.
    `known_subject`: a question about something he has facts about is a content question, and content
    needs the room the substance budget gives it. `story`: the same, for the one thing that is
    genuinely longer than a sentence.
    """
    if closing:
        return "closing"
    if depth >= 1 or asked_why or known_subject or story:
        return "substance"
    if named_subject:
        return "hook"
    if turns_today <= 0:
        return "opening"
    return "pleasantries"
