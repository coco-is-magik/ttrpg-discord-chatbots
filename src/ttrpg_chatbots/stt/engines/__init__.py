"""Registry of speech-to-text engines.

The core install carries no STT dependency and this box is not necessarily the
deployment box, so engines are declared here and resolved lazily: anything that
cannot be imported, or has no model available, is reported and skipped instead of
breaking startup. Declaration order is the deterministic tie-break for equal
timings.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from importlib.util import find_spec
from pathlib import Path
from typing import Callable

from ttrpg_chatbots.stt.recognizer import EngineUnavailable, SpeechRecognizer


@dataclass(frozen=True)
class EngineSpec:
    """How to build one engine, and how to tell whether it can run here."""

    name: str
    distribution: str
    module: str
    summary: str
    check: Callable[[], tuple[bool, str]]
    build: Callable[[], SpeechRecognizer]


@dataclass(frozen=True)
class Availability:
    name: str
    available: bool
    detail: str


def specs() -> tuple[EngineSpec, ...]:
    """Return the known engines, in tie-break order."""
    from ttrpg_chatbots.stt.engines import faster_whisper_engine as fw
    from ttrpg_chatbots.stt.engines import sherpa_engine as sh
    from ttrpg_chatbots.stt.engines import vosk_engine as vo

    return (
        EngineSpec(vo.NAME, vo.DISTRIBUTION, vo.MODULE, vo.SUMMARY, vo.check, vo.build),
        EngineSpec(fw.NAME, fw.DISTRIBUTION, fw.MODULE, fw.SUMMARY, fw.check, fw.build),
        EngineSpec(sh.NAME, sh.DISTRIBUTION, sh.MODULE, sh.SUMMARY, sh.check, sh.build),
    )


def names() -> tuple[str, ...]:
    return tuple(spec.name for spec in specs())


def availability(engine_spec: EngineSpec) -> Availability:
    """Report whether an engine is usable here, with a reason either way."""
    if find_spec(engine_spec.module) is None:
        return Availability(
            engine_spec.name, False, f"package '{engine_spec.distribution}' is not installed"
        )
    try:
        available, detail = engine_spec.check()
    except Exception as error:  # noqa: BLE001 - a broken check must not stop startup
        return Availability(engine_spec.name, False, f"availability check failed: {error}")
    return Availability(engine_spec.name, available, detail)


def build_engine(name: str) -> SpeechRecognizer:
    for engine_spec in specs():
        if engine_spec.name == name:
            return engine_spec.build()
    raise EngineUnavailable(f"unknown STT engine {name!r}; known engines: {', '.join(names())}")


def model_dir() -> Path:
    """Where downloaded models are cached, so a box can be pre-seeded."""
    override = os.environ.get("TTRPG_STT_MODEL_DIR", "").strip()
    base = Path(override) if override else Path.home() / ".cache" / "ttrpg-chatbots" / "models"
    base.mkdir(parents=True, exist_ok=True)
    return base


def offline() -> bool:
    """True when engines must not download anything."""
    return os.environ.get("TTRPG_STT_OFFLINE", "").strip().lower() not in {"", "0", "false", "no"}
