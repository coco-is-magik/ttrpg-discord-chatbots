"""Command line front end: show the race, force an engine, transcribe a file."""

from __future__ import annotations

import argparse
import json
import logging
import sys
import wave
from pathlib import Path
from typing import Sequence

from ttrpg_chatbots.stt import engines
from ttrpg_chatbots.stt.fixture import DEFAULT_SECONDS
from ttrpg_chatbots.stt.probe import DEFAULT_REPEATS, Measurement, Resolution, resolve_recognizer
from ttrpg_chatbots.stt.recognizer import EngineUnavailable
from ttrpg_chatbots.stt.types import SAMPLE_RATE, AudioClip

LOGGER = logging.getLogger(__name__)


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="ttrpg-chatbots-stt",
        description="Time every installed speech-to-text engine and keep the fastest.",
    )
    parser.add_argument(
        "--list", action="store_true", help="list engines and whether they run here"
    )
    parser.add_argument(
        "--engine", metavar="NAME", help="force an engine instead of racing (also TTRPG_STT_ENGINE)"
    )
    parser.add_argument("--refresh", action="store_true", help="ignore the cached winner")
    parser.add_argument(
        "--repeats", type=int, default=DEFAULT_REPEATS, help="timed calls per engine"
    )
    parser.add_argument("--seconds", type=float, default=DEFAULT_SECONDS, help="timing clip length")
    parser.add_argument(
        "--transcribe", metavar="WAV", help=f"transcribe a {SAMPLE_RATE} Hz mono 16-bit WAV"
    )
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    return parser.parse_args(argv)


def read_wav(path: Path) -> AudioClip:
    """Read a WAV that is already in the engine interchange format."""
    with wave.open(str(path), "rb") as handle:
        channels = handle.getnchannels()
        width = handle.getsampwidth()
        rate = handle.getframerate()
        frames = handle.readframes(handle.getnframes())
    if (channels, width, rate) != (1, 2, SAMPLE_RATE):
        raise ValueError(
            f"need {SAMPLE_RATE} Hz mono 16-bit PCM, got {rate} Hz, "
            f"{channels} channel(s), {width * 8}-bit"
        )
    return AudioClip(pcm=frames)


def _measurement_rows(measurements: Sequence[Measurement]) -> list[dict]:
    return [
        {
            "engine": row.engine,
            "ok": row.ok,
            "load_s": round(row.load_s, 4),
            "median_ms": None if row.median_s is None else round(row.median_s * 1000, 1),
            "rtf": None if row.rtf is None else round(row.rtf, 3),
            "error": row.error,
        }
        for row in measurements
    ]


def _report(resolution: Resolution, measurements: Sequence[Measurement], *, as_json: bool) -> None:
    if as_json:
        print(
            json.dumps(
                {
                    "selected": resolution.engine,
                    "source": resolution.source,
                    "measurements": _measurement_rows(measurements),
                },
                indent=2,
            )
        )
        return

    print(f"{'engine':<16}{'status':<12}{'load':>8}{'median':>10}{'RTF':>8}")
    for row in measurements:
        status = "ok" if row.ok else "unavailable"
        load = f"{row.load_s:.2f}s" if row.ok else "-"
        median = "-" if row.median_s is None else f"{row.median_s * 1000:.0f} ms"
        rtf = "-" if row.rtf is None else f"{row.rtf:.3f}"
        print(f"{row.engine:<16}{status:<12}{load:>8}{median:>10}{rtf:>8}")
        if not row.ok and row.error:
            print(f"    {row.error}")

    chosen = next((row for row in measurements if row.engine == resolution.engine), None)
    latency = ""
    if chosen is not None and chosen.median_s is not None:
        latency = f", {chosen.median_s * 1000:.0f} ms per utterance"
    print(f"\nselected: {resolution.engine} ({resolution.source}{latency})")


def _list_engines(*, as_json: bool) -> int:
    rows = []
    for spec in engines.specs():
        status = engines.availability(spec)
        rows.append(
            {
                "engine": spec.name,
                "available": status.available,
                "detail": status.detail,
                "summary": spec.summary,
            }
        )
    if as_json:
        print(json.dumps(rows, indent=2))
        return 0
    for row in rows:
        mark = "ready" if row["available"] else "unavailable"
        print(f"{row['engine']:<16}{mark:<13}{row['detail']}")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Entry point for the ``ttrpg-chatbots-stt`` console script."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    args = _parse_args(argv)

    if args.list:
        return _list_engines(as_json=args.json)

    try:
        resolution = resolve_recognizer(
            engine=args.engine,
            refresh=args.refresh,
            repeats=args.repeats,
            seconds=args.seconds,
        )
    except EngineUnavailable as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    try:
        if args.transcribe:
            text = resolution.recognizer.transcribe(read_wav(Path(args.transcribe)))
            print(json.dumps({"text": text, "engine": resolution.engine}) if args.json else text)
        else:
            _report(resolution, resolution.measurements, as_json=args.json)
    except (OSError, ValueError, EOFError, wave.Error) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    finally:
        resolution.recognizer.close()
    return 0
