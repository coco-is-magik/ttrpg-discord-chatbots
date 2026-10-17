"""Registry of text-to-speech engines.

Same shape as the speech-to-text registry: engines are declared here and resolved
lazily, so a missing package or an absent voice is reported rather than fatal.

Order is *priority*, not speed: unlike STT, where the fastest engine wins, TTS
engines differ mostly in voice quality. A ten-year-old robotic voice is not a good
default just because it is quick, so the first available engine wins and callers
can force a different one with ``TTRPG_TTS_ENGINE`` or ``--engine``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from importlib.util import find_spec
from pathlib import Path
from typing import Callable

from ttrpg_chatbots.tts.synthesizer import SpeechSynthesizer, SynthesizerUnavailable


@dataclass(frozen=True)
class EngineSpec:
    """How to build one engine, and how to tell whether it can run here."""

    name: str
    distribution: str
    module: str
    summary: str
    check: Callable[[], tuple[bool, str]]
    build: Callable[[], SpeechSynthesizer]


@dataclass(frozen=True)
class Availability:
    name: str
    available: bool
    detail: str


def specs() -> tuple[EngineSpec, ...]:
    from ttrpg_chatbots.tts.engines import espeak_engine as es
    from ttrpg_chatbots.tts.engines import piper_engine as pi

    return (
        EngineSpec(pi.NAME, pi.DISTRIBUTION, pi.MODULE, pi.SUMMARY, pi.check, pi.build),
        EngineSpec(es.NAME, es.DISTRIBUTION, es.MODULE, es.SUMMARY, es.check, es.build),
    )


def names() -> tuple[str, ...]:
    return tuple(spec.name for spec in specs())


def availability(engine_spec: EngineSpec) -> Availability:
    if surface_missing(engine_spec):
        return Availability(
            engine_spec.name, False, f"package '{engine_spec.distribution}' is not installed"
        )
    try:
        available, detail = engine_spec.check()
    except Exception as error:  # noqa: BLE001 - a broken check must not stop startup
        return Availability(engine_spec.name, False, f"availability check failed: {error}")
    return Availability(engine_spec.name, available, detail)


def surface_missing(engine_spec: EngineSpec) -> bool:
    """True when a Python engine's package is absent; CLI engines have no module."""
    if engine_spec.module == "":
        return False
    return find_spec(engine_spec.module) is None


def build_engine(name: str) -> SpeechSynthesizer:
    for engine_spec in specs():
        if engine_spec.name == name.strip().lower():
            return engine_spec.build()
    raise SynthesizerUnavailable(
        f"unknown TTS engine {name!r}; known engines: {', '.join(names())}"
    )


def model_dir() -> Path:
    """Where downloaded voices are cached, so a box can be pre-seeded."""
    override = os.environ.get("TTRPG_TTS_MODEL_DIR", "").strip()
    base = Path(override) if override else Path.home() / ".cache" / "ttrpg-chatbots" / "models"
    base.mkdir(parents=True, exist_ok=True)
    return base


def offline() -> bool:
    return os.environ.get("TTRPG_TTS_OFFLINE", "").strip().lower() not in {"", "0", "false", "no"}
