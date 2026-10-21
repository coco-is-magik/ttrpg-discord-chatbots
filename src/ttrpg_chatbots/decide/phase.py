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
) -> Phase:
    """The most specific phase the evidence supports."""
    if closing:
        return "closing"
    if depth >= 1:
        return "substance"
    if named_subject:
        return "hook"
    if turns_today <= 0:
        return "opening"
    return "pleasantries"
