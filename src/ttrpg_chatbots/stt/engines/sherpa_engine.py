"""sherpa-onnx adapter: ONNX transducer models (Zipformer/Parakeet), no PyTorch.

Unlike the other two adapters this one cannot fetch a model by name, because
sherpa-onnx models are published as release tarballs rather than a hub. Point
``TTRPG_STT_SHERPA_MODEL`` at an extracted transducer model directory.
"""

from __future__ import annotations

import os
from pathlib import Path

from ttrpg_chatbots.stt.recognizer import EngineUnavailable
from ttrpg_chatbots.stt.types import SAMPLE_RATE, AudioClip

NAME = "sherpa-onnx"
DISTRIBUTION = "sherpa-onnx"
MODULE = "sherpa_onnx"
SUMMARY = "ONNX transducer (Zipformer/Parakeet); needs a model dir, cheapest per thread"

NUM_THREADS = min(4, os.cpu_count() or 1)


def _model_dir() -> Path | None:
    configured = os.environ.get("TTRPG_STT_SHERPA_MODEL", "").strip()
    return Path(configured) if configured else None


def _required_files(model_dir: Path) -> dict[str, Path]:
    """Resolve the four files a transducer export needs, preferring int8 weights."""

    def pick(pattern: str) -> Path | None:
        matches = sorted(model_dir.glob(pattern))
        int8 = [path for path in matches if "int8" in path.name]
        return (int8 or matches or [None])[0]

    encoder = pick("encoder*.onnx")
    decoder = pick("decoder*.onnx")
    joiner = pick("joiner*.onnx")
    tokens = model_dir / "tokens.txt"
    files = {"encoder": encoder, "decoder": decoder, "joiner": joiner, "tokens": tokens}
    return {name: path for name, path in files.items() if path is not None}


def check() -> tuple[bool, str]:
    model_dir = _model_dir()
    if model_dir is None:
        return False, "set TTRPG_STT_SHERPA_MODEL to an extracted transducer model directory"
    if not model_dir.is_dir():
        return False, f"TTRPG_STT_SHERPA_MODEL is not a directory: {model_dir}"
    files = _required_files(model_dir)
    missing = [name for name in ("encoder", "decoder", "joiner", "tokens") if name not in files]
    if missing:
        return False, f"model directory is missing: {', '.join(missing)}"
    return True, f"model directory: {model_dir}"


class SherpaRecognizer:
    name = NAME

    def __init__(self, model_dir: Path | None = None) -> None:
        self._model_dir = model_dir
        self._recognizer = None

    def load(self) -> None:
        import sherpa_onnx

        model_dir = self._model_dir or _model_dir()
        if model_dir is None:
            raise EngineUnavailable(
                "sherpa-onnx needs a model: set TTRPG_STT_SHERPA_MODEL to a "
                "transducer model directory"
            )
        files = _required_files(model_dir)
        missing = [name for name in ("encoder", "decoder", "joiner", "tokens") if name not in files]
        if missing:
            raise EngineUnavailable(f"model directory {model_dir} is missing: {', '.join(missing)}")

        self._recognizer = sherpa_onnx.OfflineRecognizer.from_transducer(
            encoder=str(files["encoder"]),
            decoder=str(files["decoder"]),
            joiner=str(files["joiner"]),
            tokens=str(files["tokens"]),
            num_threads=NUM_THREADS,
            sample_rate=SAMPLE_RATE,
            feature_dim=80,
            decoding_method="greedy_search",
        )

    def transcribe(self, clip: AudioClip) -> str:
        import numpy as np

        if self._recognizer is None:
            raise EngineUnavailable("sherpa-onnx engine used before load()")
        stream = self._recognizer.create_stream()
        samples = np.frombuffer(clip.pcm, dtype="<i2").astype(np.float32) / 32768.0
        stream.accept_waveform(SAMPLE_RATE, samples)
        self._recognizer.decode_stream(stream)
        return stream.result.text.strip()

    def close(self) -> None:
        self._recognizer = None


def build() -> SherpaRecognizer:
    return SherpaRecognizer()
