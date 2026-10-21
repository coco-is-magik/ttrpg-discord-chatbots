"""What kind of conversation is this?

The same words mean different things in different rooms. "whose turn is it" is small talk in
#general and a rules question at the table; "nice" means something different while watching a game.
Read from the channel's name and an explicit table flag, never guessed from message content.
"""

from __future__ import annotations

from ttrpg_chatbots.conv.types import Situation

# Ordered: the first match wins, so a game-night channel is a table before it is gaming.
_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("ttrpg", ("ttrpg", "table", "session", "game-night", "gamnight", "dnd")),
    ("admin", ("admin", "sheet", "build", "character", "portal")),
    ("watching", ("watch", "film", "movie", "stream", "game-thread")),
    ("gaming", ("gaming", "minecraft", "steam", "squad")),
)


def read(*, channel: str = "", table_active: bool = False) -> Situation:
    """Which room this is, with the evidence that decided it."""
    if table_active:
        return Situation(kind="ttrpg", evidence="a scene is open")
    name = channel.strip().lower()
    for kind, needles in _PATTERNS:
        for needle in needles:
            if needle in name:
                return Situation(kind=kind, evidence=f"#{name}")
    return Situation(kind="chatting", evidence=f"#{name}" if name else "no channel")
