"""Audio sources for playback.

A source is pull-based: the transport asks for the next 20 ms frame. That is the
shape Discord's ``AudioSource`` has, and it makes freshly synthesized speech,
pre-recorded WAVs and music interchangeable -- the player never asks what it is
playing, and nothing here knows about text or Discord.
"""

from __future__ import annotations

from collections import deque
from pathlib import Path
from typing import Protocol, runtime_checkable

from ttrpg_chatbots.audio.pcm import (
    DISCORD_BYTES_PER_SECOND,
    DISCORD_FRAME_BYTES,
    DISCORD_FRAME_MS,
    PcmAudio,
    frame_count,
    frames,
    to_discord_pcm,
)
from ttrpg_chatbots.audio.wav import read_wav

SILENT_FRAME = b"\x00" * DISCORD_FRAME_BYTES


@runtime_checkable
class FrameSource(Protocol):
    """Anything that can hand out 20 ms frames until it is exhausted."""

    def next_frame(self) -> bytes:
        """Return exactly one Discord frame, or ``b""`` when finished."""

    def close(self) -> None:
        """Release whatever the source holds."""


class PcmFrameSource:
    """A clip, converted once into 48 kHz stereo frames."""

    def __init__(self, clip: PcmAudio) -> None:
        data = to_discord_pcm(clip)
        self._frames = frames(data)
        self.frame_count = frame_count(data)
        self.duration_s = len(data) / DISCORD_BYTES_PER_SECOND

    def next_frame(self) -> bytes:
        return next(self._frames, b"")

    def close(self) -> None:
        self._frames = iter(())


class SilenceSource:
    """Deliberate silence -- a pause between lines, or a keep-alive gap."""

    def __init__(self, seconds: float) -> None:
        if seconds < 0:
            raise ValueError("seconds must not be negative")
        self.frame_count = int(round(seconds * 1000 / DISCORD_FRAME_MS))
        self.duration_s = self.frame_count * DISCORD_FRAME_MS / 1000
        self._remaining = self.frame_count

    def next_frame(self) -> bytes:
        if self._remaining <= 0:
            return b""
        self._remaining -= 1
        return SILENT_FRAME

    def close(self) -> None:
        self._remaining = 0


class ChainSource:
    """Several sources one after another: speech, a pause, then music."""

    def __init__(self, *sources: FrameSource) -> None:
        self._pending = deque(sources)
        self._current: FrameSource | None = None

    def next_frame(self) -> bytes:
        while True:
            if self._current is None:
                if not self._pending:
                    return b""
                self._current = self._pending.popleft()
            frame = self._current.next_frame()
            if frame:
                return frame
            self._current.close()
            self._current = None

    def close(self) -> None:
        if self._current is not None:
            self._current.close()
            self._current = None
        while self._pending:
            self._pending.popleft().close()


def load_file(path: str | Path) -> PcmFrameSource:
    """Pre-recorded audio or music from a WAV file."""
    return PcmFrameSource(read_wav(path))
