"""What has he said recently?

A ledger, not a ban. The old system had *rotation*: it existed to avoid ever repeating a line, which
is the opposite of how familiarity sounds. This one records what was said so repetition can be
deliberate -- avoided while there is something fresh, allowed when there is not.
"""

from __future__ import annotations

from collections import deque


class Recent:
    """The last N lines he said."""

    def __init__(self, window: int = 20) -> None:
        if window < 1:
            raise ValueError("window must be at least 1")
        self._said: deque[str] = deque(maxlen=window)

    def __len__(self) -> int:
        return len(self._said)

    def seen(self, text: str) -> bool:
        return text.strip().lower() in (item.lower() for item in self._said)

    def remember(self, text: str) -> None:
        if text.strip():
            self._said.append(text.strip())

    def seen_last(self, text: str, count: int = 2) -> bool:
        """Said in the last few lines? Repetition after a gap is how people talk; repetition
        immediately after itself is how a broken machine talks."""
        window = list(self._said)[-max(1, count) :]
        return text.strip().lower() in (item.lower() for item in window)

    def recent(self) -> tuple[str, ...]:
        return tuple(self._said)
