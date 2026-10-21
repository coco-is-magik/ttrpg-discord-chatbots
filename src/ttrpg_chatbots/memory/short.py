"""The last few turns, verbatim.

Short-term memory is a ring buffer and nothing else: eight turns, oldest dropped, gone when the
process ends. That is not a limitation to fix -- a conversation should not remember this morning's
every word, and the things worth keeping are the ones `memory.encode` lifts out of here.
"""

from __future__ import annotations

from ttrpg_chatbots.reply.context import DEFAULT_WINDOW, Turn


class ShortTerm:
    """A fixed-size window of turns, newest last."""

    def __init__(self, *, window: int = DEFAULT_WINDOW) -> None:
        if window < 1:
            raise ValueError("window must be at least 1")
        self._window = window
        self._turns: list[Turn] = []

    def __len__(self) -> int:
        return len(self._turns)

    @property
    def window(self) -> int:
        return self._window

    def append(self, turn: Turn) -> None:
        self._turns.append(turn)
        if len(self._turns) > self._window:
            del self._turns[: len(self._turns) - self._window]

    def recent(self, count: int | None = None) -> tuple[Turn, ...]:
        return tuple(self._turns[-(count or self._window) :])

    def clear(self) -> None:
        self._turns.clear()
