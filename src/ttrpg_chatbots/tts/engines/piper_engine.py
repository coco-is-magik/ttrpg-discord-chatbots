"""Piper adapter: small VITS voices, fast on CPU, no GPU needed.

Piper ships its own espeak-ng bridge, so phonemisation needs no system package.
A voice is ~60 MB and is fetched once into the model cache.
"""

from __future__ import annotations

import os
from pathlib import Path

from ttrpg_chatbots.audio.pcm import PcmAudio
from ttrpg_chatbots.tts.engines import model_dir, offline
from ttrpg_chatbots.tts.synthesizer import (
    SynthesisError,
    SynthesizerUnavailable,
    clean_text,
)

NAME = "piper"
DISTRIBUTION = "piper-tts"
MODULE = "piper"
SUMMARY = "Piper VITS voices: neural, fast on CPU, ~60 MB per voice"
DEFAULT_VOICE = "en_US-lessac-medium"

MAX_SPEED = 3.0
MAX_VOLUME = 2.0


def voice_name() -> str:
    return os.environ.get("TTRPG_TTS_VOICE", "").strip() or DEFAULT_VOICE


def voice_dir() -> Path:
    return model_dir() / "piper"


def voice_path(name: str | None = None) -> Path:
    return voice_dir() / f"{name or voice_name()}.onnx"


def check() -> tuple[bool, str]:
    name = voice_name()
    path = voice_path(name)
    if path.is_file():
        return True, f"voice '{name}' at {path}"
    if offline():
        return False, f"voice '{name}' is not downloaded and TTRPG_TTS_OFFLINE is set"
    return True, f"voice '{name}' will be downloaded on first load (~60 MB)"


def speed_from_environment() -> float:
    """``TTRPG_TTS_SPEED``: 1.0 is normal, lower is faster, higher is slower."""
    raw = os.environ.get("TTRPG_TTS_SPEED", "").strip()
    if not raw:
        return 1.0
    try:
        value = float(raw)
    except ValueError as error:
        raise ValueError(f"TTRPG_TTS_SPEED must be a number, got {raw!r}") from error
    if not 0.0 < value <= MAX_SPEED:
        raise ValueError(f"TTRPG_TTS_SPEED must be in (0, {MAX_SPEED}], got {value}")
    return value


def volume_from_environment() -> float:
    """``TTRPG_TTS_VOLUME``: gain applied by the voice itself."""
    raw = os.environ.get("TTRPG_TTS_VOLUME", "").strip()
    if not raw:
        return 1.0
    try:
        value = float(raw)
    except ValueError as error:
        raise ValueError(f"TTRPG_TTS_VOLUME must be a number, got {raw!r}") from error
    if not 0.0 < value <= MAX_VOLUME:
        raise ValueError(f"TTRPG_TTS_VOLUME must be in (0, {MAX_VOLUME}], got {value}")
    return value


def deterministic_from_environment() -> bool:
    """``TTRPG_TTS_DETERMINISTIC``: pin the sampler for byte-identical audio.

    Piper's VITS sampler is stochastic, so the same line renders ~0.4 % different in
    length each run. That is fine for a voice but not for caching pre-rendered lines,
    which is what this switch is for.
    """
    return os.environ.get("TTRPG_TTS_DETERMINISTIC", "").strip().lower() not in {
        "",
        "0",
        "false",
        "no",
    }


class PiperSynthesizer:
    name = NAME

    def __init__(
        self,
        voice: str | None = None,
        length_scale: float | None = None,
        volume: float | None = None,
        deterministic: bool | None = None,
    ) -> None:
        self._voice_name = (voice or voice_name()).strip()
        self._length_scale = speed_from_environment() if length_scale is None else length_scale
        self._volume = volume_from_environment() if volume is None else volume
        self._deterministic = (
            deterministic_from_environment() if deterministic is None else deterministic
        )
        self._voice = None

    def load(self) -> None:
        from piper import PiperVoice

        self._voice = PiperVoice.load(self._ensure_voice())

    def _ensure_voice(self) -> Path:
        path = voice_path(self._voice_name)
        if path.is_file():
            return path
        if offline():
            raise SynthesizerUnavailable(
                f"voice {self._voice_name!r} is not downloaded and TTRPG_TTS_OFFLINE is set"
            )
        from piper.download_voices import download_voice

        voice_dir().mkdir(parents=True, exist_ok=True)
        try:
            download_voice(self._voice_name, voice_dir())
        except Exception as error:  # noqa: BLE001 - network/driver errors vary wildly
            raise SynthesisError(
                f"could not download voice {self._voice_name!r}: {error}"
            ) from error
        if not path.is_file():
            raise SynthesisError(f"download of voice {self._voice_name!r} produced no {path.name}")
        return path

    def synthesize(self, text: str) -> PcmAudio:
        from piper import SynthesisConfig

        cleaned = clean_text(text)
        if self._voice is None:
            raise SynthesizerUnavailable("piper used before load()")
        # normalize_audio=False on purpose: normalising pins the peak at 32767, which
        # leaves no headroom for Discord's own gain. Measured on en_US-lessac-medium
        # the natural level peaks around 22500 (-3.2 dBFS).
        noise = 0.0 if self._deterministic else None
        config = SynthesisConfig(
            length_scale=self._length_scale,
            normalize_audio=False,
            volume=self._volume,
            noise_scale=noise,
            noise_w_scale=noise,
        )
        chunks = list(self._voice.synthesize(cleaned, config))
        if not chunks:
            raise SynthesisError(f"piper produced no audio for {cleaned[:40]!r}")
        pcm = b"".join(chunk.audio_int16_bytes for chunk in chunks)
        if not pcm:
            raise SynthesisError(f"piper produced empty audio for {cleaned[:40]!r}")
        return PcmAudio(
            pcm=pcm,
            sample_rate=chunks[0].sample_rate,
            channels=chunks[0].sample_channels,
        )

    def close(self) -> None:
        self._voice = None


def build() -> PiperSynthesizer:
    return PiperSynthesizer()
