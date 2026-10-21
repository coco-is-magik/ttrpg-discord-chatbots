"""Was he named, replied to, or neither?

A reply outranks a bare name: replying to somebody's message is a stronger signal than mentioning
them in passing, and the ladder treats the two differently.
"""

from __future__ import annotations

from ttrpg_chatbots.conv.types import Addressee


def classify(*, mentioned: bool, replied: bool) -> Addressee:
    """Named, replied-to, or unaddressed."""
    if replied:
        return "reply"
    if mentioned:
        return "named"
    return "unaddressed"
