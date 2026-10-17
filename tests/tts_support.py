"""Doubles for the text-to-speech and playback tests."""

from __future__ import annotations

import math
import struct

from ttrpg_chatbots.audio.pcm import PcmAudio
from ttrpg_chatbots.tts.casting import VoiceProfile
from ttrpg_chatbots.tts.engines import EngineSpec
from ttrpg_chatbots.tts.synthesizer import SynthesisError


def tone(
    seconds: float,
    *,
    sample_rate: int = 22_050,
    channels: int = 1,
    frequency: float = 220.0,
    amplitude: int = 8000,
) -> PcmAudio:
    """Deterministic non-silent PCM, so tests can tell audio from nothing."""
    count = int(round(seconds * sample_rate))
    samples: list[int] = []
    for index in range(count):
        value = int(amplitude * math.sin(2 * math.pi * frequency * index / sample_rate))
        samples.extend([value] * channels)
    return PcmAudio(
        pcm=struct.pack(f"<{len(samples)}h", *samples),
        sample_rate=sample_rate,
        channels=channels,
    )


class FakeSynthesizer:
    """Stands in for a real engine: records calls, returns a tone."""

    name = "fake"

    def __init__(self, *, seconds: float = 0.5, sample_rate: int = 22_050, failure=None) -> None:
        self._seconds = seconds
        self._sample_rate = sample_rate
        self._failure = failure
        self.loads = 0
        self.closes = 0
        self.spoken: list[str] = []

    def load(self) -> None:
        self.loads += 1

    def synthesize(self, text: str) -> PcmAudio:
        self.spoken.append(text)
        if self._failure is not None:
            raise self._failure
        return tone(self._seconds, sample_rate=self._sample_rate)

    def close(self) -> None:
        self.closes += 1


class FakeSource:
    """A frame source with scripted frames that records how it was used."""

    def __init__(self, frames: list[bytes]) -> None:
        self._frames = list(frames)
        self.closes = 0
        self.frames_read = 0

    def next_frame(self) -> bytes:
        if not self._frames:
            return b""
        self.frames_read += 1
        return self._frames.pop(0)

    def close(self) -> None:
        self.closes += 1
        self._frames = []


class FakeCast:
    """Stands in for VoiceCast: records who spoke what, returns a tone."""

    def __init__(self, *, seconds: float = 0.5, profile=None) -> None:
        self._seconds = seconds
        self._profile = profile or VoiceProfile(engine="fake", voice="fake-voice")
        self.spoken: list[tuple[str, str]] = []
        self.closes = 0

    def profile_for(self, speaker) -> VoiceProfile:
        return self._profile

    def synthesize(self, text: str, speaker):
        self.spoken.append((speaker.id, text))
        return tone(self._seconds)

    def close(self) -> None:
        self.closes += 1


def fake_spec(
    name: str,
    synthesizer,
    *,
    module: str = "json",
    available: bool = True,
    detail: str = "ready",
) -> EngineSpec:
    return EngineSpec(
        name=name,
        distribution="fake-tts",
        module=module,
        summary="fake engine for tests",
        check=lambda: (available, detail),
        build=lambda: synthesizer,
    )


__all__ = ["FakeCast", "FakeSource", "FakeSynthesizer", "SynthesisError", "fake_spec", "tone"]
