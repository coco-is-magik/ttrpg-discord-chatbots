"""espeak-ng adapter: no model, no download, robotic voice.

Kept as the zero-install fallback for boxes where a neural voice is not available
or not permitted. Text goes in as a single argv element, never through a shell.
"""

from __future__ import annotations

import os
import shutil
import subprocess

from ttrpg_chatbots.audio.pcm import PcmAudio
from ttrpg_chatbots.audio.wav import decode_wav
from ttrpg_chatbots.tts.synthesizer import (
    SynthesisError,
    SynthesizerUnavailable,
    clean_text,
)

NAME = "espeak-ng"
DISTRIBUTION = "(system binary)"
MODULE = ""
SUMMARY = "espeak-ng CLI fallback: robotic, no model, no download"
BINARY_CANDIDATES = ("espeak-ng", "espeak")
TIMEOUT_S = 30


def binary() -> str | None:
    override = os.environ.get("TTRPG_TTS_ESPEAK", "").strip()
    if override:
        return override
    for candidate in BINARY_CANDIDATES:
        found = shutil.which(candidate)
        if found:
            return found
    return None


def check() -> tuple[bool, str]:
    found = binary()
    if found is None:
        return False, "espeak-ng is not installed (or set TTRPG_TTS_ESPEAK to its path)"
    return True, found


class EspeakSynthesizer:
    name = NAME

    def __init__(self, voice: str = "en", words_per_minute: int = 165) -> None:
        self.voice = voice
        self.words_per_minute = words_per_minute
        self._binary: str | None = None

    def load(self) -> None:
        found = binary()
        if found is None:
            raise SynthesizerUnavailable(
                "espeak-ng is not installed (or set TTRPG_TTS_ESPEAK to its path)"
            )
        self._binary = found

    def synthesize(self, text: str) -> PcmAudio:
        cleaned = clean_text(text)
        if self._binary is None:
            raise SynthesizerUnavailable("espeak-ng used before load()")
        command = [
            self._binary,
            "-v",
            self.voice,
            "-s",
            str(self.words_per_minute),
            "--stdout",
            cleaned,
        ]
        try:
            result = subprocess.run(command, capture_output=True, timeout=TIMEOUT_S, check=False)
        except (OSError, subprocess.TimeoutExpired) as error:
            raise SynthesisError(f"espeak-ng could not run: {error}") from error
        if result.returncode != 0:
            message = result.stderr.decode("utf-8", "replace").strip()
            raise SynthesisError(f"espeak-ng failed ({result.returncode}): {message}")
        if not result.stdout:
            raise SynthesisError("espeak-ng produced no audio")
        return decode_wav(result.stdout)

    def close(self) -> None:
        self._binary = None


def build() -> EspeakSynthesizer:
    return EspeakSynthesizer()
