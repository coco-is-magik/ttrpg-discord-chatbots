"""Fast-forward the room, offline.

```
ttrpg-chatbots-simulate --hours 24 --seed 11 --out /tmp/day.jsonl
ttrpg-chatbots-simulate --hours 168 --seed 3 --start 2026-10-24T09:00 --friends friend-a,friend-b
```

No Discord, no network, no audio: the same director and the same ladder that run live, stepped over a
virtual clock. A week of conversation in a couple of seconds, which is the only practical way to get
data on how the friends interact before tuning how they speak.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

from ttrpg_chatbots.ambient.cadence import Cadence
from ttrpg_chatbots.ambient.director import Director
from ttrpg_chatbots.ambient.simulate import simulate
from ttrpg_chatbots.bots.identity import bots_from_records
from ttrpg_chatbots.bots.ladder import Ladder
from ttrpg_chatbots.bots.memory import FriendMemory

DEFAULT_ROSTER = Path("data/bots.json")
DEFAULT_EXAMPLE = Path("examples/bots.example.json")


def build_director(
    *,
    roster: Path,
    friends: tuple[str, ...] = (),
    seed: int | None = None,
    mean_seconds: float = 300.0,
    data: Path | str | None = None,
    sleep_enabled: bool = True,
) -> Director:
    """A director over the friends in the roster, with in-memory memories.

    In-memory on purpose: a simulation must not touch the live database, and a friend's *history* is not
    what is being tested.
    """
    spec_path = roster if roster.exists() else DEFAULT_EXAMPLE
    specs = bots_from_records(json.loads(spec_path.read_text()), source=str(spec_path))
    ladders: dict[str, Ladder] = {}
    memories: dict[str, object] = {}
    for spec in specs:
        if spec.role != "friend" or spec.persona is None:
            continue
        if friends and spec.id not in friends:
            continue
        ladders[spec.id] = Ladder(
            friend=spec.id,
            data=data,
            style=spec.persona.style,
            question_rate=spec.persona.question_rate,
            verbosity=spec.persona.verbosity,
            obey_schedule=sleep_enabled,
        )
        memories[spec.id] = FriendMemory(spec.id, person="noodle", sessions=3)
    if not ladders:
        raise SystemExit(f"no friends with a persona in {spec_path}")
    from ttrpg_chatbots.ambient.quiet import Quiet

    return Director(
        ladders=ladders,
        memories=memories,
        cadence=Cadence(mean_seconds=mean_seconds, seed=seed),
        quiet=Quiet(seed=seed, sleep_enabled=sleep_enabled),
        seed=seed,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ttrpg-chatbots-simulate",
        description="Run the friends' group conversation offline, faster than real time.",
    )
    parser.add_argument("--hours", type=float, default=24.0)
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--start", default=None, help="ISO local time, e.g. 2026-10-24T09:00")
    parser.add_argument("--mean", type=float, default=300.0, help="target seconds between messages")
    parser.add_argument("--roster", type=Path, default=DEFAULT_ROSTER)
    parser.add_argument("--friends", default="", help="comma-separated ids; default is all of them")
    parser.add_argument("--out", type=Path, default=None, help="write the transcript as jsonl")
    parser.add_argument("--quiet", action="store_true", help="summary only")
    parser.add_argument(
        "--awake",
        action="store_true",
        help="switch bedtime off, to simulate a run that talks through the night",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    # Local, like the live room: a simulated day has to be the same day the friends actually have, or the
    # quiet hours land in the wrong place and a simulation says the room is asleep at tea time.
    if args.start:
        parsed = datetime.fromisoformat(args.start)
        start = parsed.astimezone() if parsed.tzinfo else parsed.astimezone()
    else:
        start = datetime.now().astimezone().replace(second=0, microsecond=0)
    friends = tuple(part.strip() for part in args.friends.split(",") if part.strip())
    director = build_director(
        roster=args.roster,
        friends=friends,
        seed=args.seed,
        mean_seconds=args.mean,
        sleep_enabled=not args.awake,
    )
    run = simulate(director, start=start, hours=args.hours)

    if not args.quiet:
        for line in run.spoke:
            print(f"{line.at:%m-%d %H:%M} {line.speaker:9} {line.text}")
        print()
    print(run.summary())
    if args.out is not None:
        with args.out.open("w", encoding="utf-8") as handle:
            for line in run.spoke:
                # One record per *message*, not per turn: the packaging is the thing being measured, so a
                # transcript that collapsed it would be measuring the old behaviour.
                turn_id = f"{line.speaker}@{line.at.isoformat(timespec='seconds')}"
                offset = 0.0
                for index, message in enumerate(line.arriving()):
                    if index < len(line.waits):
                        offset += line.waits[index]
                    handle.write(
                        json.dumps(
                            {
                                "at": (line.at + timedelta(seconds=offset)).isoformat(),
                                "speaker": line.speaker,
                                "kind": line.kind,
                                "text": message,
                                "trail": line.trail,
                                "turn": turn_id,
                            },
                            ensure_ascii=False,
                        )
                        + "\n"
                    )
        print(f"wrote {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
