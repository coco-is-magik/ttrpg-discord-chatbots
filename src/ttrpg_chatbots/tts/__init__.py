"""Text to speech, pluggable and lazy.

``resolve_synthesizer()`` returns a loaded engine: the highest-priority engine that
can run on this machine, or the one named by ``engine=`` / ``TTRPG_TTS_ENGINE``.
Nothing here knows what produced the text -- classifier, LLM or a scripted line.
"""

from __future__ import annotations

import os
from typing import Sequence

from ttrpg_chatbots.tts import engines
from ttrpg_chatbots.tts.casting import (
    CastingError,
    Speaker,
    VoiceCast,
    VoiceDirectory,
    VoiceProfile,
    VoiceRule,
    load_voice_directory,
)
from ttrpg_chatbots.tts.engines import Availability, EngineSpec
from ttrpg_chatbots.tts.synthesizer import (
    SpeechSynthesizer,
    SynthesisError,
    SynthesizerUnavailable,
    clean_text,
)

ENV_ENGINE = "TTRPG_TTS_ENGINE"

__all__ = [
    "Availability",
    "CastingError",
    "ENV_ENGINE",
    "Speaker",
    "SpeechSynthesizer",
    "SynthesisError",
    "SynthesizerUnavailable",
    "VoiceCast",
    "VoiceDirectory",
    "VoiceProfile",
    "VoiceRule",
    "availability_report",
    "clean_text",
    "engines",
    "load_voice_directory",
    "resolve_synthesizer",
]


def availability_report(specs: Sequence[EngineSpec] | None = None) -> tuple[Availability, ...]:
    """Availability of every known engine, with the reason either way."""
    return tuple(engines.availability(spec) for spec in (specs or engines.specs()))


def resolve_synthesizer(
    engine: str | None = None, *, specs: Sequence[EngineSpec] | None = None
) -> SpeechSynthesizer:
    """Return a loaded synthesizer: the requested engine, or the first usable one."""
    candidates = tuple(specs if specs is not None else engines.specs())

    requested = (engine or "").strip() or os.environ.get(ENV_ENGINE, "").strip()
    if requested:
        for spec in candidates:
            if spec.name == requested.lower():
                return _load(spec)
        known = ", ".join(spec.name for spec in candidates)
        raise SynthesizerUnavailable(f"unknown TTS engine {requested!r}; known engines: {known}")

    reasons = []
    for spec in candidates:
        status = engines.availability(spec)
        if status.available:
            return _load(spec)
        reasons.append(f"{spec.name}: {status.detail}")
    raise SynthesizerUnavailable(
        "no usable TTS engine on this machine (" + "; ".join(reasons) + ")"
    )


def _load(spec: EngineSpec) -> SpeechSynthesizer:
    """Build the engine and wrap it so no caller can forget the spoken form.

    Wrapping at the single place engines are built, rather than at each call site: there are three
    ways to reach an engine and only one of them gets remembered.
    """
    from ttrpg_chatbots.tts.spoken import wrap

    return wrap(_build(spec))


def _build(spec: EngineSpec) -> SpeechSynthesizer:
    synthesizer = spec.build()
    try:
        synthesizer.load()
    except Exception:  # noqa: BLE001 - release partial state, then surface the cause
        synthesizer.close()
        raise
    return synthesizer
