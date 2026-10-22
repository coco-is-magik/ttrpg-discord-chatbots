"""Look at the ladder from the outside: one line, explained, or every phase measured."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

from ttrpg_chatbots.bots.memory import FriendMemory
from ttrpg_chatbots.bots.ladder import Ladder
from ttrpg_chatbots.conv.types import Abstain, Line
from ttrpg_chatbots.decide.shelf import load_shelf
from ttrpg_chatbots.decide.variant import PhrasebookError
from ttrpg_chatbots.govern.harness import run_phases
from ttrpg_chatbots.perceive.clock import read_clock
from ttrpg_chatbots.reply.style import Style

DEFAULT_DATA = Path("examples/friends_world")


def _style(name: str) -> Style | None:
    if name == "sms":
        return Style(case="lower", drop_apostrophes=True, strip_final_period=True, typo_rate=0.05)
    return None


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ttrpg-chatbots-conv",
        description="Run the conversation ladder for one message, or measure every phase.",
    )
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA, help="world directory")
    parser.add_argument("--friend", default="friend-a", help="whose phrasebooks to use")
    parser.add_argument("--say", metavar="TEXT", help="a message to answer")
    parser.add_argument("--at", metavar="HH:MM", default="10:00", help="local time to answer at")
    parser.add_argument("--explain", action="store_true", help="print every rung of the ladder")
    parser.add_argument("--harness", action="store_true", help="measure every phase over a matrix")
    parser.add_argument("--style", default="sms", choices=("sms", "none"))
    parser.add_argument(
        "--relationship", default="friend", choices=("new", "acquainted", "friend")
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        shelf = load_shelf(args.data / "phrasebooks")
    except PhrasebookError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    style = _style(args.style)

    if args.harness:
        reports = run_phases(books=shelf, life=_life(args), style=style)
        for job, report in reports.items():
            print(f"phase: {job}")
            print(report.summary())
            print()
        return 0

    if not args.say:
        print("error: give --say TEXT or --harness", file=sys.stderr)
        return 2

    hour, minute = (int(part) for part in args.at.split(":"))
    ladder = Ladder(friend=args.friend, data=args.data, style=style)
    out = ladder.line(
        text=args.say,
        memory=FriendMemory(args.friend, sessions=14, person="tav"),
        moment=read_clock(datetime(2026, 10, 21, hour, minute)),
    )
    if isinstance(out, Abstain):
        print(f"silence: {out.reason}")
        return 0
    assert isinstance(out, Line)
    print(out.text)
    if args.explain:
        print(f"  {out.trail.describe()}")
    return 0


def _life(args):
    """The friend's life, if there is one. Used only by the harness."""
    from ttrpg_chatbots.life.render import load_lives

    try:
        return load_lives(args.data / "life.json").get(args.friend)
    except Exception:  # noqa: BLE001 - a broken life is not a reason to refuse to run
        return None


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

