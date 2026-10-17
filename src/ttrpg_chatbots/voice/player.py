"""The playback queue.

A transport only needs ``next_frame()``; that is the whole interface, which is why
the tests can drive this directly, and why a file writer, a WebRTC transport or a
Discord voice client all cost nothing to support.

``read()`` is called from discord.py's audio thread while the bot enqueues from the
event loop, so the queue is guarded by a lock.
"""

from __future__ import annotations

import threading
from collections import deque

from ttrpg_chatbots.audio.pcm import DISCORD_FRAME_BYTES
from ttrpg_chatbots.voice.sources import FrameSource


class VoicePlayer:
    """A thread-safe queue of frame sources, drained one 20 ms frame at a time."""

    def __init__(self) -> None:
        self._queue: deque[FrameSource] = deque()
        self._current: FrameSource | None = None
        self._lock = threading.Lock()
        self._closed = False

    def enqueue(self, source: FrameSource) -> None:
        with self._lock:
            if self._closed:
                raise RuntimeError("player is closed")
            self._queue.append(source)

    def say(self, sources: FrameSource | list[FrameSource]) -> None:
        """Convenience: queue one source or a list of them."""
        for source in sources if isinstance(sources, list) else [sources]:
            self.enqueue(source)

    def next_frame(self) -> bytes:
        """Next 20 ms frame, or ``b""`` when there is nothing left to play."""
        with self._lock:
            while True:
                if self._current is None:
                    if not self._queue:
                        return b""
                    self._current = self._queue.popleft()
                frame = self._current.next_frame()
                if frame:
                    if len(frame) != DISCORD_FRAME_BYTES:
                        raise ValueError(
                            f"a source yielded {len(frame)} bytes; Discord needs exactly "
                            f"{DISCORD_FRAME_BYTES} per 20 ms frame"
                        )
                    return frame
                self._current.close()
                self._current = None

    def clear(self) -> None:
        """Stop playback now: drop the queue and the in-flight source."""
        with self._lock:
            current = self._current
            pending = list(self._queue)
            self._current = None
            self._queue.clear()
        for source in ([current] if current is not None else []) + pending:
            source.close()

    def is_idle(self) -> bool:
        with self._lock:
            return self._current is None and not self._queue

    @property
    def queued(self) -> int:
        with self._lock:
            return len(self._queue) + (1 if self._current is not None else 0)

    def close(self) -> None:
        self.clear()
        with self._lock:
            self._closed = True
