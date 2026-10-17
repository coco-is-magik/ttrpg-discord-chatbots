"""Command line front end: text in, voice-call frames out.

This is deliberately the only place that knows both the reply engine and the
speech/playback layers. ``tts`` and ``voice`` do not import each other, and neither
imports ``reply``, so a music file, an LLM answer and a classifier reply all arrive
through the same playback path.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

from ttrpg_chatbots.audio.pcm import DISCORD_FRAME_BYTES
from ttrpg_chatbots.audio.wav import write_wav
from ttrpg_chatbots.reply.datasets import load_world
from ttrpg_chatbots.reply.replier import Replier
from ttrpg_chatbots.reply.types import ReplyError, World
from ttrpg_chatbots.tts import (
    SynthesisError,
    VoiceCast,
    VoiceDirectory,
    availability_report,
    load_voice_directory,
    resolve_synthesizer,
)
from ttrpg_chatbots.voice.player import VoicePlayer
from ttrpg_chatbots.voice.sources import PcmFrameSource, load_file

DEFAULT_DATA = Path("examples/demo_world")
FRAME_SECONDS = DISCORD_FRAME_BYTES / 192_000


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="ttrpg-chatbots-voice",
        description="Turn text, a reply, or a recording into Discord voice frames.",
    )
    parser.add_argument("--list", action="store_true", help="list TTS engines and availability")
    parser.add_argument(
        "--list-voices", action="store_true", help="show which voice each character gets"
    )
    parser.add_argument("--say", metavar="TEXT", help="text to speak")
    parser.add_argument("--ask", metavar="TEXT", help="ask the reply engine, then speak its answer")
    parser.add_argument("--character", help="character id or name for --ask")
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA, help="dataset for --ask")
    parser.add_argument("--speaker", help="who is being answered; fills {speaker}")
    parser.add_argument("--wav", type=Path, metavar="FILE", help="queue a pre-recorded WAV instead")
    parser.add_argument("--engine", metavar="NAME", help="force a TTS engine")
    parser.add_argument("--voice", metavar="NAME", help="voice name (same as TTRPG_TTS_VOICE)")
    parser.add_argument("--out", type=Path, metavar="FILE", help="also write the speech as WAV")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    return parser.parse_args(argv)


def _drain(player: VoicePlayer) -> int:
    """Pull frames the way a transport would, and count them."""
    frames = 0
    for _ in iter(player.next_frame, b""):
        frames += 1
    return frames


def _report(payload: dict, *, as_json: bool) -> int:
    if as_json:
        print(json.dumps(payload, indent=2))
        return 0
    if payload.get("character"):
        print(f"{payload['character']}: {payload['text']}")
    if payload.get("engine"):
        print(f"engine: {payload['engine']}")
    if payload.get("voice"):
        print(f"voice: {payload['voice']}")
    print(f"frames: {payload['frames']} ({payload['duration_s']:.2f} s of audio)")
    print(f"bytes: {payload['bytes']}")
    if payload.get("synthesis_ms") is not None:
        print(f"synth: {payload['synthesis_ms']:.0f} ms")
    if payload.get("out"):
        print(f"wrote: {payload['out']}")
    return 0


def _voicing(data_dir: Path, world: World) -> VoiceDirectory:
    """Load the world's voice rules, checked against the characters that exist."""
    return load_voice_directory(
        data_dir,
        known_tags={tag for character in world.characters for tag in character.tags},
        known_characters={
            alias
            for character in world.characters
            for alias in (character.id, character.name)
        },
    )


def _report_voices(world: World, directory: VoiceDirectory, *, as_json: bool) -> int:
    rows = [
        {
            "character": character.id,
            "name": character.name,
            "tags": sorted(character.tags),
            "voice": directory.resolve(character).describe(),
        }
        for character in world.characters
    ]
    if as_json:
        print(json.dumps(rows, indent=2))
        return 0
    for row in rows:
        print(f"{row['character']:<12}{row['name']:<28}{row['voice']}")
    return 0


def _availability(*, as_json: bool) -> int:
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


def main(argv: list[str] | None = None) -> int:
    """Entry point for the ``ttrpg-chatbots-voice`` console script."""
    args = _parse_args(argv)

    if args.list:
        return _availability(as_json=args.json)
    if args.list_voices:
        try:
            world = load_world(args.data)
            directory = _voicing(args.data, world)
        except (ReplyError, ValueError, OSError) as error:
            print(f"error: {error}", file=sys.stderr)
            return 2
        return _report_voices(world, directory, as_json=args.json)
    if args.voice:
        os.environ["TTRPG_TTS_VOICE"] = args.voice
    if not (args.say or args.ask or args.wav):
        print(
            "error: give one of --say, --ask, --wav, --list or --list-voices",
            file=sys.stderr,
        )
        return 2

    player = VoicePlayer()
    synthesizer = None
    cast = None
    try:
        if args.wav:
            source = load_file(args.wav)
            player.enqueue(source)
            frames = _drain(player)
            payload = {
                "source": "wav",
                "text": "",
                "character": None,
                "engine": None,
                "voice": None,
                "frames": frames,
                "bytes": frames * DISCORD_FRAME_BYTES,
                "duration_s": frames * FRAME_SECONDS,
                "synthesis_ms": None,
                "out": None,
            }
            return _report(payload, as_json=args.json)

        text = args.say or ""
        character = None
        profile = None
        world = None
        if args.ask or args.character:
            world = load_world(args.data)
            if args.ask:
                replier = Replier(world)
                reply = replier.reply(
                    args.ask,
                    args.character or world.characters[0].id,
                    speaker=args.speaker,
                )
                text = reply.text
                character = world.character(reply.character)
            else:
                character = world.character(args.character or world.characters[0].id)

        started = time.perf_counter()
        if character is not None and world is not None:
            cast = VoiceCast(_voicing(args.data, world))
            profile = cast.profile_for(character)
            clip = cast.synthesize(text, character)
            engine_label = profile.engine or "auto"
        else:
            synthesizer = resolve_synthesizer(args.engine)
            clip = synthesizer.synthesize(text)
            engine_label = synthesizer.name
        synthesis_s = time.perf_counter() - started
        out = write_wav(clip, args.out) if args.out else None

        player.enqueue(PcmFrameSource(clip))
        frames = _drain(player)
        payload = {
            "source": "ask" if args.ask else "say",
            "text": text,
            "character": character.name if character is not None else None,
            "engine": engine_label,
            "voice": profile.describe() if profile is not None else None,
            "frames": frames,
            "bytes": frames * DISCORD_FRAME_BYTES,
            "duration_s": frames * FRAME_SECONDS,
            "synthesis_ms": synthesis_s * 1000,
            "out": str(out) if out else None,
        }
        return _report(payload, as_json=args.json)
    except (SynthesisError, ReplyError, ValueError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    finally:
        player.close()
        if synthesizer is not None:
            synthesizer.close()
        if cast is not None:
            cast.close()
