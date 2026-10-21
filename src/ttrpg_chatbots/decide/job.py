"""Which job owns this turn?

Exactly one. A greeting does not also offer a hook; a hook does not also tell the story. This is the
module that stops a reply from trying to be three things at once.
"""

from __future__ import annotations

from ttrpg_chatbots.conv.types import Intent, Job, Phase


def choose(*, intent: Intent, phase: Phase, depth: int = 0) -> Job:
    """The one job this turn does."""
    if intent == "greet":
        return "greet"
    if intent == "complain":
        return "mirror"
    if intent in ("agree", "decline", "meta"):
        return "acknowledge"
    if intent == "about_me":
        return "explain" if (depth >= 1 or phase == "substance") else "offer_hook"
    if intent == "about_world":
        return "explain"
    if intent == "joke":
        return "mirror"
    return "acknowledge"
