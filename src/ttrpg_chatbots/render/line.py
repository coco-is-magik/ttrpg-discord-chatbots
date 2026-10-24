"""Assemble the line and its trail.

The last module before the wire, and the only one whose output has words in it."""

from __future__ import annotations

from ttrpg_chatbots.conv.types import Line, Trail
from ttrpg_chatbots.parts import read as read_parts


def assemble(*, text: str, trail: Trail | None = None, parts=None) -> Line:
    """The finished line, with the parts it is made of.

    Parts are read here rather than at the call sites so every path that builds a line has them -- and a
    caller that already knows the shape can pass its own.
    """
    cleaned = text.strip()
    return Line(
        text=cleaned,
        trail=trail or Trail(),
        parts=tuple(parts) if parts is not None else read_parts(cleaned),
    )
