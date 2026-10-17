"""Startup race: measure every usable engine, keep the fastest loaded.

Per-utterance wall-clock time is what reply latency is made of, so engines are
ranked by the median time for a fixed synthetic clip. Model loading happens once
per process and is reported, but it is not part of the ranking.

The outcome is cached against a fingerprint of the machine, the engine versions
and the clip, so a long-running bot pays the race once and a different box pays it
again -- the winner is a property of the box, not of the code.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import platform
import statistics
import time
from dataclasses import asdict, dataclass
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Callable, Sequence

from ttrpg_chatbots.stt import engines
from ttrpg_chatbots.stt.engines import EngineSpec
from ttrpg_chatbots.stt.fixture import DEFAULT_SECONDS, fingerprint, synthetic_speech
from ttrpg_chatbots.stt.recognizer import EngineUnavailable, SpeechRecognizer
from ttrpg_chatbots.stt.types import AudioClip

LOGGER = logging.getLogger(__name__)

CACHE_VERSION = 1
DEFAULT_REPEATS = 5
ENV_ENGINE = "TTRPG_STT_ENGINE"


@dataclass(frozen=True)
class Measurement:
    """The result of timing one engine."""

    engine: str
    ok: bool
    load_s: float
    median_s: float | None = None
    min_s: float | None = None
    max_s: float | None = None
    rtf: float | None = None
    error: str | None = None


@dataclass(frozen=True)
class Resolution:
    """The chosen engine, still loaded and ready to transcribe."""

    recognizer: SpeechRecognizer
    engine: str
    source: str
    measurements: tuple[Measurement, ...] = ()


def measure(
    recognizer: SpeechRecognizer,
    clip: AudioClip,
    *,
    repeats: int = DEFAULT_REPEATS,
    clock: Callable[[], float] = time.perf_counter,
) -> Measurement:
    """Load once, warm up once, then time ``repeats`` transcriptions."""
    if repeats < 1:
        raise ValueError("repeats must be at least 1")

    started = clock()
    try:
        recognizer.load()
    except Exception as error:  # noqa: BLE001 - any failure means "unusable here"
        return Measurement(
            engine=recognizer.name,
            ok=False,
            load_s=clock() - started,
            error=f"{type(error).__name__}: {error}",
        )
    load_s = clock() - started

    try:
        recognizer.transcribe(clip)  # warm-up: the first call pays lazy allocation
        timings = []
        for _ in range(repeats):
            call_started = clock()
            recognizer.transcribe(clip)
            timings.append(clock() - call_started)
    except Exception as error:  # noqa: BLE001
        return Measurement(
            engine=recognizer.name,
            ok=False,
            load_s=load_s,
            error=f"{type(error).__name__}: {error}",
        )

    median_s = statistics.median(timings)
    return Measurement(
        engine=recognizer.name,
        ok=True,
        load_s=load_s,
        median_s=median_s,
        min_s=min(timings),
        max_s=max(timings),
        rtf=median_s / clip.duration_s,
    )


def _rank_key(measurement: Measurement) -> tuple[float, float, str]:
    return (measurement.median_s or 0.0, measurement.load_s, measurement.engine)


def fastest(measurements: Sequence[Measurement]) -> Measurement:
    """Return the usable measurement with the lowest median latency."""
    usable = [m for m in measurements if m.ok and m.median_s is not None]
    if not usable:
        reasons = "; ".join(f"{m.engine}: {m.error or 'unusable'}" for m in measurements)
        raise EngineUnavailable(
            f"no usable STT engine on this machine ({reasons or 'none installed'})"
        )
    return min(usable, key=_rank_key)


def environment_fingerprint(
    clip: AudioClip, *, repeats: int, specs: Sequence[EngineSpec]
) -> str:
    """Hash everything that could change which engine wins on this machine."""
    parts = {
        "cache_version": CACHE_VERSION,
        "python": platform.python_version(),
        "system": platform.system(),
        "machine": platform.machine(),
        "cpus": os.cpu_count(),
        "clip": fingerprint(clip),
        "repeats": repeats,
        "engines": [[spec.name, _distribution_version(spec.distribution)] for spec in specs],
    }
    return hashlib.sha256(json.dumps(parts, sort_keys=True).encode()).hexdigest()


def _distribution_version(distribution: str) -> str:
    try:
        return version(distribution)
    except PackageNotFoundError:
        return "absent"


def default_cache_path() -> Path:
    base = os.environ.get("XDG_CACHE_HOME", "").strip() or str(Path.home() / ".cache")
    return Path(base) / "ttrpg-chatbots" / "stt-probe.json"


def _read_cache(path: Path, expected: str) -> Measurement | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    if payload.get("cache_version") != CACHE_VERSION or payload.get("fingerprint") != expected:
        return None
    try:
        return Measurement(**payload["winner"])
    except (KeyError, TypeError):
        return None


def _write_cache(path: Path, expected: str, winner: Measurement) -> None:
    payload = {
        "cache_version": CACHE_VERSION,
        "fingerprint": expected,
        "winner": asdict(winner),
        "measured_at": time.time(),
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        os.replace(temporary, path)
    except OSError as error:  # a read-only cache directory must not break transcription
        LOGGER.warning("could not write STT probe cache %s: %s", path, error)


def resolve_recognizer(
    *,
    engine: str | None = None,
    refresh: bool = False,
    repeats: int = DEFAULT_REPEATS,
    seconds: float = DEFAULT_SECONDS,
    cache_path: Path | None = None,
    clock: Callable[[], float] = time.perf_counter,
    specs: Sequence[EngineSpec] | None = None,
) -> Resolution:
    """Pick an engine and return it loaded.

    ``engine`` (or ``TTRPG_STT_ENGINE``) skips the race entirely. Otherwise a
    cached winner is reused; only a cache miss, ``refresh`` or a changed
    fingerprint triggers fresh measurements.
    """
    candidates = tuple(specs if specs is not None else engines.specs())
    clip = synthetic_speech(seconds)

    requested = (engine or "").strip()
    source = "forced"
    if not requested:
        requested = os.environ.get(ENV_ENGINE, "").strip()
        source = "env"
    if requested:
        chosen = _build_checked(requested, candidates)
        measurement = measure(chosen, clip, repeats=repeats, clock=clock)
        if not measurement.ok:
            chosen.close()
            raise EngineUnavailable(f"engine {requested!r} is not usable here: {measurement.error}")
        LOGGER.info("STT engine forced to %s: %.0f ms per utterance", requested, _ms(measurement))
        return Resolution(chosen, requested, source, (measurement,))

    cache_file = cache_path or default_cache_path()
    expected = environment_fingerprint(clip, repeats=repeats, specs=candidates)

    if not refresh:
        cached = _read_cache(cache_file, expected)
        if cached is not None:
            try:
                reuse = _build_checked(cached.engine, candidates)
                reuse.load()
            except Exception as error:  # noqa: BLE001 - fall through to a fresh race
                LOGGER.info("cached STT engine %s unusable (%s); re-probing", cached.engine, error)
            else:
                LOGGER.info(
                    "STT engine from cache: %s (%.0f ms measured earlier)",
                    cached.engine,
                    _ms(cached),
                )
                return Resolution(reuse, cached.engine, "cache", (cached,))

    winner: Measurement | None = None
    winner_recognizer: SpeechRecognizer | None = None
    measurements: list[Measurement] = []

    for spec in candidates:
        status = engines.availability(spec)
        if not status.available:
            measurements.append(
                Measurement(engine=spec.name, ok=False, load_s=0.0, error=status.detail)
            )
            LOGGER.info("skipping STT engine %s: %s", spec.name, status.detail)
            continue

        recognizer = spec.build()
        measurement = measure(recognizer, clip, repeats=repeats, clock=clock)
        measurements.append(measurement)
        if not measurement.ok:
            LOGGER.warning("STT engine %s failed: %s", spec.name, measurement.error)
            recognizer.close()
            continue
        LOGGER.info(
            "STT engine %s: median %.0f ms (load %.1f s)",
            spec.name,
            _ms(measurement),
            measurement.load_s,
        )
        if winner is None or _rank_key(measurement) < _rank_key(winner):
            if winner_recognizer is not None:
                winner_recognizer.close()  # free the old leader's memory
            winner, winner_recognizer = measurement, recognizer
        else:
            recognizer.close()

    if winner is None or winner_recognizer is None:
        raise EngineUnavailable(
            "no usable STT engine: "
            + "; ".join(f"{m.engine}: {m.error or 'unusable'}" for m in measurements)
        )

    _write_cache(cache_file, expected, winner)
    return Resolution(winner_recognizer, winner.engine, "measured", tuple(measurements))


def _build_checked(name: str, candidates: Sequence[EngineSpec]) -> SpeechRecognizer:
    for spec in candidates:
        if spec.name == name:
            return spec.build()
    known = ", ".join(spec.name for spec in candidates)
    raise EngineUnavailable(f"unknown STT engine {name!r}; known engines: {known}")


def _ms(measurement: Measurement) -> float:
    return (measurement.median_s or 0.0) * 1000.0
