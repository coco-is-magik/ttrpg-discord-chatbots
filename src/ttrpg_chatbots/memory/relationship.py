"""How well does he know this person?

Counted, not felt: sessions and how long they have been talking. `warmth` is what the greeting
family is chosen from -- a stranger and a friend do not say the same hello, and the difference is
observable rather than invented.
"""

from __future__ import annotations

from datetime import datetime

from ttrpg_chatbots.conv.types import Relationship


def read(*, sessions: int = 0, topics: int = 0, days_known: float = 0.0) -> Relationship:
    """New, acquainted or friend -- plus a warmth from 0 to 3."""
    if sessions < 3:
        stage = "new"
    elif sessions < 12:
        stage = "acquainted"
    else:
        stage = "friend"
    warmth = 0
    if sessions >= 3:
        warmth += 1
    if sessions >= 12 or days_known >= 14:
        warmth += 1
    if topics >= 3:
        warmth += 1
    return Relationship(stage=stage, warmth=min(3, warmth))
