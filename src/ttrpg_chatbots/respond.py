"""The seam every answerer shares: text to speak, and where it came from.

This module imports nothing from the rest of the project on purpose. ``reply`` (the
compression classifier) and ``llm`` (the language models) both satisfy
:class:`Responder`, so the two never import each other and the voice layer never has to
know which one produced a line.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol


@dataclass(frozen=True)
class Answer:
    """Text to speak, plus where it came from.

    ``fallback_reason`` is set when a primary responder failed and a backup answered,
    so a degraded reply is never mistaken for a healthy one.
    """

    text: str
    source: str
    detail: Mapping[str, Any] = field(default_factory=dict)
    fallback_reason: str | None = None

    def __post_init__(self) -> None:
        if not self.text.strip():
            raise ValueError("answer text must not be empty")
        if not self.source.strip():
            raise ValueError("answer source must not be empty")

    @property
    def degraded(self) -> bool:
        """True when this answer came from a fallback rather than the primary."""
        return self.fallback_reason is not None


class Responder(Protocol):
    """Anything that can turn a prompt into speakable text."""

    @property
    def name(self) -> str: ...

    def answer(self, prompt: str) -> Answer: ...
