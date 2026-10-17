"""Vosk (Kaldi) adapter: ~40 MB model, no ML runtime, plain CPU."""

from __future__ import annotations

import json
import os
from pathlib import Path

from ttrpg_chatbots.stt.engines import offline
from ttrpg_chatbots.stt.recognizer import EngineUnavailable
from ttrpg_chatbots.stt.types import SAMPLE_RATE, AudioClip

NAME = "vosk"
DISTRIBUTION = "vosk"
MODULE = "vosk"
SUMMARY = "Kaldi decoder, tiny model, lowest memory; no float runtime needed"

# 250 ms chunks: the recognizer endpoints internally, which keeps one long clip
# from being one giant decode step.
CHUNK_FRAMES = 4000


def check() -> tuple[bool, str]:
    model_path = os.environ.get("TTRPG_STT_VOSK_MODEL", "").strip()
    if model_path:
        if Path(model_path).exists():
            return True, f"model from TTRPG_STT_VOSK_MODEL: {model_path}"
        return False, f"TTRPG_STT_VOSK_MODEL points at a missing path: {model_path}"
    if offline():
        return False, "no local model and TTRPG_STT_OFFLINE is set"
    return True, "small English model will be downloaded on first load (~40 MB)"


class VoskRecognizer:
    name = NAME

    def __init__(self, model_path: str | None = None) -> None:
        self._model_path = model_path or os.environ.get("TTRPG_STT_VOSK_MODEL") or None
        self._model = None
        self._recognizer = None

    def load(self) -> None:
        import vosk

        vosk.SetLogLevel(-1)
        self._model = vosk.Model(self._model_path) if self._model_path else vosk.Model(lang="en-us")
        self._recognizer = vosk.KaldiRecognizer(self._model, SAMPLE_RATE)

    def transcribe(self, clip: AudioClip) -> str:
        if self._recognizer is None:
            raise EngineUnavailable("vosk engine used before load()")
        self._recognizer.Reset()
        step = CHUNK_FRAMES * 2
        for start in range(0, len(clip.pcm), step):
            chunk = clip.pcm[start : start + step]
            if len(chunk) >= 2:
                self._recognizer.AcceptWaveform(chunk)
        return str(json.loads(self._recognizer.FinalResult()).get("text", "")).strip()

    def close(self) -> None:
        self._recognizer = None
        self._model = None


def build() -> VoskRecognizer:
    return VoskRecognizer()
