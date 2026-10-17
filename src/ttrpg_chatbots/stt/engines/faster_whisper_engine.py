"""faster-whisper adapter: CTranslate2 Whisper on CPU, int8, greedy decoding."""

from __future__ import annotations

import os
from pathlib import Path

from ttrpg_chatbots.stt.engines import model_dir, offline
from ttrpg_chatbots.stt.recognizer import EngineUnavailable
from ttrpg_chatbots.stt.types import AudioClip

NAME = "faster-whisper"
DISTRIBUTION = "faster-whisper"
MODULE = "faster_whisper"
SUMMARY = "CTranslate2 Whisper, best accuracy per cycle, ~75 MB (tiny.en int8)"

DEFAULT_MODEL = "tiny.en"


def _configured_model() -> str:
    return os.environ.get("TTRPG_STT_WHISPER_MODEL", "").strip() or DEFAULT_MODEL


def check() -> tuple[bool, str]:
    configured = _configured_model()
    local = Path(configured)
    if local.is_dir():
        return True, f"local model directory: {configured}"
    if offline():
        return False, "model is not cached locally and TTRPG_STT_OFFLINE is set"
    return True, f"'{configured}' will be downloaded from Hugging Face on first load"


class FasterWhisperRecognizer:
    name = NAME

    def __init__(self, model_size: str | None = None, language: str | None = None) -> None:
        self._model_size = model_size or _configured_model()
        self._language = language or os.environ.get("TTRPG_STT_LANGUAGE", "").strip() or "en"
        self._model = None

    def load(self) -> None:
        from faster_whisper import WhisperModel

        self._model = WhisperModel(
            self._model_size,
            device="cpu",
            compute_type="int8",
            download_root=str(model_dir()),
        )

    def transcribe(self, clip: AudioClip) -> str:
        import numpy as np

        if self._model is None:
            raise EngineUnavailable("faster-whisper engine used before load()")
        audio = np.frombuffer(clip.pcm, dtype="<i2").astype(np.float32) / 32768.0
        # Every latency-critical knob: greedy, no cross-utterance conditioning
        # (utterances are independent speakers), no internal VAD (we segment
        # upstream), and no timestamps we do not use.
        segments, _ = self._model.transcribe(
            audio,
            language=self._language,
            beam_size=1,
            best_of=1,
            condition_on_previous_text=False,
            vad_filter=False,
            without_timestamps=True,
        )
        return " ".join(segment.text.strip() for segment in segments).strip()

    def close(self) -> None:
        self._model = None


def build() -> FasterWhisperRecognizer:
    return FasterWhisperRecognizer()
