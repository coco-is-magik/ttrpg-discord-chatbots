"""What did they actually mean? A thought split across three messages is one turn.

The reverse direction from `deliver`. The system currently treats every human message as a complete turn, so
somebody who sends

    i have been thinking
    about the garage
    the whole thing is rotten

looks like three separate statements -- and gets three separate answers, which is not how a person reads it.

The window is a debounce, not a delay: nothing waits for it unless more arrives. `feed` returns a turn the
moment a *later* message proves the previous batch was finished; `flush` returns the batch when the clock says
nobody is still typing. Pure and clock-free, so it is testable without a gateway.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

#: How long a person may pause mid-thought before it counts as a new one.
DEFAULT_WINDOW = 6.0

#: A message this short is almost certainly part of a longer thought, so the window stretches for it.
SHORT_MESSAGE_WORDS = 3


@dataclass
class Assembler:
    """Collects what somebody is saying into one turn."""

    window: float = DEFAULT_WINDOW
    #: Turns handed back, oldest first, for a caller that wants to catch up rather than be called back.
    done: list[str] = field(default_factory=list)
    _pending: list[str] = field(default_factory=list)
    _started_at: datetime | None = None
    _last_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.window <= 0:
            raise ValueError(f"window must be positive, got {self.window}")

    @property
    def pending(self) -> tuple[str, ...]:
        return tuple(self._pending)

    def feed(self, text: str, at: datetime) -> tuple[str, ...]:
        """Add one message. Returns a finished turn when this message proves the last one was over."""
        cleaned = " ".join(text.split())
        if not cleaned:
            return ()
        finished: tuple[str, ...] = ()
        if self._pending and self._last_at is not None and at - self._last_at > self._gap():
            finished = (self._take(),)
        self._pending.append(cleaned)
        if self._started_at is None:
            self._started_at = at
        self._last_at = at
        if finished:
            self.done.extend(finished)
        return finished

    def flush(self, now: datetime) -> tuple[str, ...]:
        """Hand back the pending turn if nobody is still typing. ``()`` if they are."""
        if not self._pending or self._last_at is None:
            return ()
        if now - self._last_at <= self._gap():
            return ()
        finished = (self._take(),)
        self.done.extend(finished)
        return finished

    def _gap(self) -> timedelta:
        """How long to wait, stretched for a message too short to be a whole thought."""
        seconds = self.window
        if self._pending and len(self._pending[-1].split()) <= SHORT_MESSAGE_WORDS:
            seconds *= 2.0
        return timedelta(seconds=seconds)

    def _take(self) -> str:
        """The pending messages as one turn, and start again."""
        turn = " ".join(self._pending).strip()
        self._pending = []
        self._started_at = None
        self._last_at = None
        return turn
