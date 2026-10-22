"""How many times has this person leaned in?

Heuristic, and deliberately a crude one: consecutive turns where the human *said something about
themselves*. Two rules, both measured against real messages:

* a **question is not leaning in** -- "what are you up to" is an invitation, not a contribution, and
  counting it pushed the conversation to substance before the other person had said anything;
* short messages mean "not really", so six words is the floor.
"""

from __future__ import annotations

from collections.abc import Sequence

from ttrpg_chatbots.reply.context import Turn

LEAN_IN_WORDS = 6


def read(turns: Sequence[Turn]) -> int:
    """Consecutive human turns that count as leaning in."""
    depth = 0
    for turn in reversed(turns):
        if turn.is_bot:
            continue
        text = turn.text.strip()
        if text.endswith("?"):
            break
        if len(text.split()) < LEAN_IN_WORDS:
            break
        depth += 1
    return depth
