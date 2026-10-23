"""Command line front end for text to speech."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

from ttrpg_chatbots.audio.wav import write_wav
from ttrpg_chatbots.tts import (
    SynthesisError,
    SynthesizerUnavailable,
    availability_report,
    resolve_synthesizer,
)
from ttrpg_chatbots.tts import engines


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="ttrpg-chatbots-tts",
        description="Turn text into speech with the best engine this box can run.",
    )
    parser.add_argument("--list", action="store_true", help="list engines and their availability")
    parser.add_argument("--say", metavar="TEXT", help="text to synthesize")
    parser.add_argument("--out", type=Path, metavar="FILE", help="write a WAV file")
    parser.add_argument("--engine", metavar="NAME", help="force an engine (also TTRPG_TTS_ENGINE)")
    parser.add_argument(
        "--voice", metavar="NAME", help="voice name (piper; same as TTRPG_TTS_VOICE)"
    )
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument(
        "--spoken",
        metavar="TEXT",
        help="print the spoken form of TEXT (what a voice reads) and stop",
    )
    parser.add_argument(
        "--verify-voice",
        nargs="?",
        const="",
        metavar="NAME",
        help="check every locked voice, or one by name",
    )
    parser.add_argument(
        "--fetch-voice",
        nargs="?",
        const="",
        metavar="NAME",
        help="download every locked voice (or one), trying each source until it verifies",
    )
    parser.add_argument(
        "--lock",
        type=Path,
        metavar="FILE",
        help="voice lock file (default: <world>/voices.lock.json)",
    )
    return parser.parse_args(argv)


def _report_available(*, as_json: bool) -> int:
    report = availability_report()
    if as_json:
        print(
            json.dumps(
                [
                    {"engine": row.name, "available": row.available, "detail": row.detail}
                    for row in report
                ],
                indent=2,
            )
        )
        return 0
    for row in report:
        mark = "ready" if row.available else "unavailable"
        print(f"{row.name:<12}{mark:<13}{row.detail}")
    return 0


def _world_dir() -> Path:
    """Where the world's data lives: the same variable the bot uses."""
    return Path(os.environ.get("TTRPG_FRIENDS_DATA", "examples/friends_world"))


def _lock_path(explicit: Path | None) -> Path:
    return explicit or _world_dir() / "voices.lock.json"


def _run_lock(args) -> int | None:
    """Handle the two voice-lock commands, or return None to carry on."""
    # `nargs="?"` means "" when the flag is given without a name, which is falsy -- so the test is for
    # None, not for truth. Measured: `--verify-voice` on its own fell through to "give --say TEXT".
    if args.verify_voice is None and args.fetch_voice is None:
        return None
    from ttrpg_chatbots.tts import lock as lock_module
    from ttrpg_chatbots.tts.engines.piper_engine import voice_dir

    path = _lock_path(args.lock)
    try:
        pinned = lock_module.load(path)
    except lock_module.LockError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    directory = voice_dir()
    wanted = args.fetch_voice if args.fetch_voice is not None else args.verify_voice
    chosen = list(pinned)
    if wanted:
        entry = pinned.for_voice(wanted)
        if entry is None:
            print(
                f"error: {path} pins {', '.join(pinned.names())}, not {wanted!r}", file=sys.stderr
            )
            return 2
        chosen = [entry]
    reports = [
        lock_module.fetch(lock, directory) if args.fetch_voice is not None else lock_module.verify(lock, directory)
        for lock in chosen
    ]
    if args.json:
        print(
            json.dumps(
                {
                    "ok": all(report.ok for report in reports),
                    "directory": str(directory),
                    "lock": str(path),
                    "voices": [
                        {
                            "voice": report.voice,
                            "ok": report.ok,
                            "fetched": report.fetched,
                            "problems": report.problems,
                        }
                        for report in reports
                    ],
                },
                indent=2,
            )
        )
    else:
        for report in reports:
            print(report.summary())
    return 0 if all(report.ok for report in reports) else 1


def _report_speech(synthesizer, clip, *, elapsed_s: float, as_json: bool, out: Path | None) -> int:
    realtime = elapsed_s / clip.duration_s if clip.duration_s else 0.0
    if as_json:
        print(
            json.dumps(
                {
                    "engine": synthesizer.name,
                    "sample_rate": clip.sample_rate,
                    "channels": clip.channels,
                    "duration_s": round(clip.duration_s, 3),
                    "frames": clip.frame_count,
                    "peak": clip.peak,
                    "synthesis_ms": round(elapsed_s * 1000, 1),
                    "realtime_ratio": round(realtime, 3),
                    "out": str(out) if out else None,
                },
                indent=2,
            )
        )
        return 0
    print(f"engine: {synthesizer.name}")
    print(
        f"audio: {clip.sample_rate} Hz, {clip.channels} channel(s), "
        f"{clip.duration_s:.2f} s ({clip.frame_count} frames)"
    )
    print(f"synth: {elapsed_s * 1000:.0f} ms ({realtime:.2f}x of realtime)")
    if out:
        print(f"wrote: {out}")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Entry point for the ``ttrpg-chatbots-tts`` console script."""
    args = _parse_args(argv)

    if args.spoken is not None:
        from ttrpg_chatbots.tts.spoken import say

        print(say(args.spoken))
        return 0

    handled = _run_lock(args)
    if handled is not None:
        return handled

    if args.list:
        return _report_available(as_json=args.json)
    if not args.say:
        print("error: give --say TEXT (or --list)", file=sys.stderr)
        return 2
    # --voice writes the process environment on purpose: it is the same knob as
    # TTRPG_TTS_VOICE, and a CLI process is short-lived.
    if args.voice:
        os.environ["TTRPG_TTS_VOICE"] = args.voice

    synthesizer = None
    try:
        synthesizer = resolve_synthesizer(args.engine)
        started = time.perf_counter()
        clip = synthesizer.synthesize(args.say)
        elapsed = time.perf_counter() - started
        out = write_wav(clip, args.out) if args.out else None
        return _report_speech(synthesizer, clip, elapsed_s=elapsed, as_json=args.json, out=out)
    except (SynthesisError, ValueError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    finally:
        if synthesizer is not None:
            synthesizer.close()
