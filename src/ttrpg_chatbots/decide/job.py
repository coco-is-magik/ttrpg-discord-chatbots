"""Which job owns this turn?

Exactly one. A greeting does not also offer a hook; a hook does not also tell the story. This is the
module that stops a reply from trying to be three things at once.

The one piece of knowledge it needs from outside is whether there is anything to say at all:
`about_me` with no life is not a hook, and `about_world` with nothing to draw on is not an
explanation. Both become `hedge` -- a short, honest, *useful* reply rather than a refusal.
"""

from __future__ import annotations

from ttrpg_chatbots.conv.types import Intent, Job, Phase


def choose(*, intent: Intent, phase: Phase, depth: int = 0, known: bool = False) -> Job:
    """The one job this turn does.

    Depth deliberately does **not** turn a hook into an explanation. Measured live: "what are you up
    to" arrived after a long message, the conversation was already deep, and the answer was a reason
    instead of the thing he is doing. Depth belongs to the *follow-up* ("why?"), not to a fresh
    question about his day.
    """
    if intent == "greet":
        return "greet"
    if intent == "complain":
        return "mirror"
    if intent == "comfort":
        return "reassure"
    if intent == "decline":
        return "close"
    if intent == "remark":
        return "noted"
    if intent in ("agree", "meta"):
        return "acknowledge"
    if intent == "about_me":
        return "offer_hook" if known else "hedge"
    if intent == "explain_me":
        return "explain" if known else "hedge"
    if intent == "about_world":
        return "explain" if known else "hedge"
    if intent == "joke":
        return "mirror"
    return "acknowledge"
