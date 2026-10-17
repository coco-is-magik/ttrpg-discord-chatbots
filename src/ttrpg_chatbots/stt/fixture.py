"""Deterministic audio used to measure engine latency.

The clip is synthesised rather than recorded: no voice data is vendored, the same
bytes appear on every machine, and cost depends on compute rather than content.
It is a *timing* fixture -- it says nothing about transcription accuracy, which
needs real speech.
"""

from __future__ import annotations

import hashlib

from ttrpg_chatbots.stt.types import SAMPLE_RATE, AudioClip

DEFAULT_SECONDS = 3.0


def synthetic_speech(seconds: float = DEFAULT_SECONDS, *, seed: int = 12345) -> AudioClip:
    """Return a deterministic, speech-shaped 16 kHz mono clip."""
    import numpy as np  # only the stt extra needs numpy; vosk-only setups do not

    if seconds <= 0:
        raise ValueError("seconds must be positive")

    rng = np.random.default_rng(seed)
    samples = int(round(seconds * SAMPLE_RATE))
    t = np.arange(samples, dtype=np.float64) / SAMPLE_RATE

    # Wandering pitch in the human range, syllabic amplitude modulation and a few
    # harmonics: enough structure that engines run their real path instead of
    # short-circuiting on digital silence.
    f0 = 110.0 + 25.0 * np.sin(2 * np.pi * 0.7 * t)
    phase = 2 * np.pi * np.cumsum(f0) / SAMPLE_RATE
    voiced = (
        np.sin(phase)
        + 0.6 * np.sin(2 * phase + 0.3)
        + 0.35 * np.sin(3 * phase + 1.1)
        + 0.2 * np.sin(5 * phase)
    )
    syllables = 0.5 + 0.5 * np.sin(2 * np.pi * 4.0 * t)
    envelope = np.clip(syllables, 0.0, 1.0) ** 1.5
    signal = voiced * envelope + 0.02 * rng.standard_normal(samples)

    peak = float(np.max(np.abs(signal)))
    if peak > 0:
        signal = 0.5 * signal / peak  # -6 dBFS, never clipped
    return AudioClip(pcm=(signal * 32767.0).astype("<i2").tobytes())


def fingerprint(clip: AudioClip) -> str:
    """Stable hash of a clip, used to key cached measurements."""
    digest = hashlib.sha256()
    digest.update(str(clip.sample_rate).encode())
    digest.update(b"|")
    digest.update(clip.pcm)
    return digest.hexdigest()
