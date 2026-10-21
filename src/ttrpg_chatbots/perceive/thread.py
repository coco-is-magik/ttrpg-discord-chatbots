"""What is this stretch of conversation about?

Continuity, not topic modelling: if the last few human turns keep making the same move, that is the
thread. It is enough to tell "we are still on this" from "that was three subjects ago"."""

from __future__ import annotations

from collections.abc import Sequence

from ttrpg_chatbots.conv.types import Thread
from ttrpg_chatbots.reply.context import Turn

RUN = 2


def read(turns: Sequence[Turn]) -> Thread:
    """The tag the last few human turns agree on, if they agree."""
    acts = [turn.act for turn in reversed(turns) if not turn.is_bot and turn.act]
    if len(acts) < RUN:
        return Thread()
    head = acts[0]
    if all(act == head for act in acts[:RUN]):
        return Thread(id=head, subject=head)
    return Thread()
