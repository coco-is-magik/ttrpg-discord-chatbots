"""Does the friend speak, or the character?

At the table he is somebody with a sheet; in #general he is himself. One decision, made from the
room, never from the words."""

from __future__ import annotations

from ttrpg_chatbots.conv.types import Who


def choose(*, situation: str = "chatting", table_active: bool = False) -> Who:
    """The character only when a scene is actually open."""
    if situation == "ttrpg" and table_active:
        return "character"
    return "friend"
