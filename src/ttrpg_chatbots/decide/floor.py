"""Should he speak at all?

The cheapest quality improvement in the system: most of the ways a bot sounds wrong are ways of
speaking when it had nothing to say. Unaddressed, asleep, or out of budget all mean silence.
"""

from __future__ import annotations

from ttrpg_chatbots.conv.types import Abstain, Addressee, Budget, Speak


def decide(
    *, addressed: Addressee, asleep: bool = False, budget: Budget | None = None
) -> Speak | Abstain:
    """Speak, or say exactly why not."""
    if addressed == "unaddressed":
        return Abstain("nobody was talking to him")
    if asleep:
        return Abstain("he is asleep")
    if budget is not None and budget.max_words < 1:
        return Abstain("no room to say anything")
    return Speak("addressed" if addressed == "named" else "replied to")
