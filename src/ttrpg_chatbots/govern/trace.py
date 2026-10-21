"""Record every decision.

The ladder is eight rungs deep; without a trail, "why did it say that" has no answer. Every reply
carries its rungs so a log line or `--explain` can show the whole path."""

from __future__ import annotations

from ttrpg_chatbots.conv.types import Trail


class Recorder:
    """Builds a trail, one rung at a time."""

    def __init__(self) -> None:
        self._trail = Trail()

    def add(self, module: str, answer: object) -> Recorder:
        self._trail = self._trail.add(module, answer)
        return self

    @property
    def trail(self) -> Trail:
        return self._trail
