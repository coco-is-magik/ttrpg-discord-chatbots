"""How many times has this person leaned in?

Heuristic, and deliberately a crude one: consecutive turns where the human wrote more than a few
words. Short messages mean "not really", and a question after a question means "go on". Depth gates
the story tier: at depth 0 there is nothing but a hook.
"""

from __future__ import annotations

from collections.abc import Sequence

from ttrpg_chatbots.reply.context import Turn

LEAN_IN_WORDS = 5


def read(turns: Sequence[Turn]) -> int:
    """Consecutive human turns long enough to count as leaning in."""
    depth = 0
    for turn in reversed(turns):
        if turn.is_bot:
            continue
        if len(turn.text.split()) < LEAN_IN_WORDS:
            break
        depth += 1
    return depth
