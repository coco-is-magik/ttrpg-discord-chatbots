"""Assemble the line and its trail.

The last module before the wire, and the only one whose output has words in it."""

from __future__ import annotations

from ttrpg_chatbots.conv.types import Line, Trail


def assemble(*, text: str, trail: Trail | None = None) -> Line:
    """The finished line."""
    return Line(text=text.strip(), trail=trail or Trail())
