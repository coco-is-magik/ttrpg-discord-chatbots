"""PCM audio primitives shared by text-to-speech and playback.

Discord voice wants 48 kHz stereo signed 16-bit little-endian frames of exactly
20 ms. Engines emit 16-24 kHz mono, and recordings arrive as anything. This module
is the only place that knows how to cross that gap, so neither side has to.
"""

from __future__ import annotations

import audioop
from dataclasses import dataclass

DISCORD_RATE = 48_000
DISCORD_CHANNELS = 2
DISCORD_FRAME_MS = 20
DISCORD_FRAME_SAMPLES = DISCORD_RATE * DISCORD_FRAME_MS // 1000
DISCORD_FRAME_BYTES = DISCORD_FRAME_SAMPLES * DISCORD_CHANNELS * 2

SAMPLE_WIDTH = 2
DISCORD_BYTES_PER_SECOND = DISCORD_RATE * DISCORD_CHANNELS * SAMPLE_WIDTH


@dataclass(frozen=True)
class PcmAudio:
    """Signed 16-bit little-endian PCM, mono or stereo."""

    pcm: bytes
    sample_rate: int
    channels: int = 1

    def __post_init__(self) -> None:
        if not self.pcm:
            raise ValueError("audio is empty")
        if len(self.pcm) % SAMPLE_WIDTH:
            raise ValueError("PCM must contain whole 16-bit samples")
        if self.sample_rate <= 0:
            raise ValueError(f"sample_rate must be positive, got {self.sample_rate}")
        if self.channels not in (1, 2):
            raise ValueError(f"only mono or stereo is supported, got {self.channels} channels")
        if len(self.pcm) % (SAMPLE_WIDTH * self.channels):
            raise ValueError("PCM length must be a whole number of frames")

    @property
    def frame_count(self) -> int:
        return len(self.pcm) // (SAMPLE_WIDTH * self.channels)

    @property
    def duration_s(self) -> float:
        return self.frame_count / self.sample_rate

    @property
    def peak(self) -> int:
        """Absolute peak sample, handy for asserting something was actually said."""
        return audioop.max(self.pcm, SAMPLE_WIDTH)

    def __add__(self, other: object) -> PcmAudio:
        if not isinstance(other, PcmAudio):
            return NotImplemented
        if (self.sample_rate, self.channels) != (other.sample_rate, other.channels):
            raise ValueError(
                "cannot concatenate clips with different sample_rate/channels: "
                f"{self.sample_rate}Hz/{self.channels}ch vs "
                f"{other.sample_rate}Hz/{other.channels}ch"
            )
        return PcmAudio(
            pcm=self.pcm + other.pcm, sample_rate=self.sample_rate, channels=self.channels
        )


def shift_pitch(clip: PcmAudio, factor: float) -> PcmAudio:
    """Deepen a clip by resampling it, with no extra dependency.

    ``factor`` is the pitch ratio: 1.0 changes nothing, 0.9 is roughly two semitones down. No samples
    are touched at all -- the *declared* sample rate is lowered, so the same audio is stretched when
    it is converted for playback, and stretching is what lowers pitch. Duration grows by ``1/factor``.

    The direction is worth stating because it reads backwards: a *higher* declared rate would mean
    "this audio was recorded faster", which compresses it and raises the pitch. Measured while
    building this: declaring 23710 Hz for 22050 Hz audio produced 178,552 bytes of Discord PCM
    against 191,992 for the untouched clip -- shorter and higher, the opposite of the brief.

    The honest trade: this is a pitch-and-tempo shift, not a phase-vocoder transposition, so a lower
    voice also speaks more slowly. That suits a brief asking for "deep and unhurried"; a voice that
    should be deep but *quick* needs the engine's own rate raised to compensate.
    """
    if not 0.5 <= factor <= 2.0:
        raise ValueError(f"pitch factor must be between 0.5 and 2.0, got {factor}")
    if factor == 1.0:
        return clip
    return PcmAudio(
        pcm=clip.pcm,
        sample_rate=max(1, int(round(clip.sample_rate * factor))),
        channels=clip.channels,
    )


def to_discord_pcm(clip: PcmAudio) -> bytes:
    """Resample and channel-convert a clip into Discord's wire format."""
    data = clip.pcm
    if clip.sample_rate != DISCORD_RATE:
        data = audioop.ratecv(
            data, SAMPLE_WIDTH, clip.channels, clip.sample_rate, DISCORD_RATE, None
        )[0]
    if clip.channels == 1:
        return audioop.tostereo(data, SAMPLE_WIDTH, 1.0, 1.0)
    return data


def frames(pcm: bytes, frame_bytes: int = DISCORD_FRAME_BYTES):
    """Split Discord-format PCM into fixed frames, padding the last one.

    Discord requires every frame to be exactly 20 ms; a short final frame would
    be rejected, so it is padded with silence.
    """
    if frame_bytes <= 0:
        raise ValueError("frame_bytes must be positive")
    if len(pcm) % frame_bytes:
        pcm = pcm + b"\x00" * (frame_bytes - len(pcm) % frame_bytes)
    for start in range(0, len(pcm), frame_bytes):
        yield pcm[start : start + frame_bytes]


def frame_count(pcm: bytes, frame_bytes: int = DISCORD_FRAME_BYTES) -> int:
    return (len(pcm) + frame_bytes - 1) // frame_bytes
