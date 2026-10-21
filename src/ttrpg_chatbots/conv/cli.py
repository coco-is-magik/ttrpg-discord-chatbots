"""Look at the ladder from the outside: one line, explained, or a whole matrix measured."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

from ttrpg_chatbots.conv.types import Abstain, Line, Relationship, Utterance
from ttrpg_chatbots.decide.variant import PhrasebookError, load
from ttrpg_chatbots.govern.harness import run as harness
from ttrpg_chatbots.govern.loop import Scene, reply
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
        description="Run the conversation ladder for one message, or measure a phase.",
    )
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA, help="world directory")
    parser.add_argument("--book", default="greet", help="phrasebook name (default: greet)")
    parser.add_argument("--greet", metavar="TEXT", help="a message to answer")
    parser.add_argument("--at", metavar="HH:MM", default="10:00", help="local time to answer at")
    parser.add_argument("--explain", action="store_true", help="print every rung of the ladder")
    parser.add_argument("--harness", action="store_true", help="measure the phase over a matrix")
    parser.add_argument("--style", default="sms", choices=("sms", "none"))
    parser.add_argument(
        "--relationship", default="friend", choices=("new", "acquainted", "friend")
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        book = load(args.data / "phrasebooks" / f"{args.book}.json")
    except PhrasebookError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    if args.harness:
        report = harness(book=book, style=_style(args.style))
        print(f"phase: {book.job}")
        print(report.summary())
        return 0

    if not args.greet:
        print("error: give --greet TEXT or --harness", file=sys.stderr)
        return 2

    hour, minute = (int(part) for part in args.at.split(":"))
    moment = read_clock(datetime(2026, 10, 21, hour, minute))
    warmth = {"new": 0, "acquainted": 1, "friend": 3}[args.relationship]
    out = reply(
        scene=Scene(
            utterance=Utterance(text=args.greet, speaker="tav"),
            addressed="named",
            moment=moment,
            relationship=Relationship(stage=args.relationship, warmth=warmth),
        ),
        book=book,
        style=_style(args.style),
    )
    if isinstance(out, Abstain):
        print(f"silence: {out.reason}")
        return 0
    assert isinstance(out, Line)
    print(out.text)
    if args.explain:
        print(f"  {out.trail.describe()}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
