"""Audio types shared by every speech-to-text engine."""

from __future__ import annotations

from dataclasses import dataclass

SAMPLE_RATE = 16_000


@dataclass(frozen=True)
class AudioClip:
    """Mono, signed 16-bit little-endian PCM.

    16 kHz mono is the common denominator every engine accepts, so engines never
    see Discord's 48 kHz stereo buffers.
    """

    pcm: bytes
    sample_rate: int = SAMPLE_RATE

    def __post_init__(self) -> None:
        if self.sample_rate != SAMPLE_RATE:
            raise ValueError(f"sample_rate must be {SAMPLE_RATE}, got {self.sample_rate}")
        if not self.pcm:
            raise ValueError("audio clip is empty")
        if len(self.pcm) % 2:
            raise ValueError("PCM must contain whole 16-bit samples")

    @property
    def frame_count(self) -> int:
        return len(self.pcm) // 2

    @property
    def duration_s(self) -> float:
        return self.frame_count / self.sample_rate
