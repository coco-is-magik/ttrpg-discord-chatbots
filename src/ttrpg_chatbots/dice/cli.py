"""Command line front end for the dice roller."""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

from ttrpg_chatbots.dice.checks import load_checks
from ttrpg_chatbots.dice.intent import describe_request, parse_instruction
from ttrpg_chatbots.dice.notation import parse_notation
from ttrpg_chatbots.dice.roller import Roller
from ttrpg_chatbots.dice.types import DEFAULT_MODE, MODES, DiceError, RollResult, RollSpec

DEFAULT_DATA = Path("examples/demo_world")


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="ttrpg-chatbots-dice",
        description="Roll a pool and read it: list, sum, hits, or a check against a target.",
    )
    parser.add_argument("--roll", metavar="NOTATION", help="dice expression, e.g. 3d6 or 2d20+3")
    parser.add_argument("--check", metavar="NAME", help="a named check from the dataset")
    parser.add_argument("--count", type=int, help="number of dice")
    parser.add_argument("--sides", type=int, help="sides per die")
    parser.add_argument("--modifier", type=int, default=None, help="added to the total")
    parser.add_argument("--mode", choices=MODES, default=None, help=f"output mode ({DEFAULT_MODE})")
    parser.add_argument("--target", type=int, default=None, help="hit threshold or difficulty")
    parser.add_argument("--label", help="what the roll is for")
    parser.add_argument("--character", help="who is rolling")
    parser.add_argument("--ask", metavar="TEXT", help="parse an instruction such as 'roll 3d6'")
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA, help="dataset directory")
    parser.add_argument("--list-checks", action="store_true", help="show the named checks")
    parser.add_argument(
        "--seed", type=int, default=None, help="seed the roller for a repeatable result"
    )
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    return parser.parse_args(argv)


def _roller(seed: int | None) -> Roller:
    return Roller(random.Random(seed) if seed is not None else None)


def _list_checks(args: argparse.Namespace) -> int:
    checks = load_checks(args.data)
    if args.json:
        print(
            json.dumps(
                [
                    {
                        "id": check.id,
                        "label": check.name,
                        "aliases": sorted(check.aliases),
                        "notation": check.spec.notation,
                        "mode": check.spec.mode,
                        "target": check.spec.target,
                    }
                    for check in checks
                ],
                indent=2,
            )
        )
        return 0
    if not len(checks):
        print(f"no checks defined in {args.data}")
        return 0
    print(f"{'id':<16}{'pool':<12}{'mode':<8}target")
    for check in checks:
        target = "" if check.spec.target is None else str(check.spec.target)
        print(f"{check.id:<16}{check.spec.notation:<12}{check.spec.mode:<8}{target}")
    return 0


def _spec_from_args(args: argparse.Namespace) -> RollSpec:
    """Resolve the flags into one spec; the flags are mutually exclusive on purpose."""
    explicit = [bool(args.roll), bool(args.check), args.count is not None or args.sides is not None]
    if sum(explicit) > 1:
        raise DiceError("give one of --roll, --check, or --count with --sides")

    if args.check:
        checks = load_checks(args.data)
        check = checks.get(args.check)
        spec = check.with_overrides(mode=args.mode, target=args.target).replace(
            label=args.label or check.name
        )
        if args.modifier is not None:
            spec = spec.replace(modifier=args.modifier)
        return spec

    if args.roll:
        spec = parse_notation(
            args.roll,
            mode=args.mode or DEFAULT_MODE,
            target=args.target,
            label=args.label or "",
        )
        # Only override what was asked for: `--roll 1d20+5` keeps its own modifier.
        if args.modifier is not None:
            spec = spec.replace(modifier=args.modifier)
        return spec

    if args.count is None or args.sides is None:
        raise DiceError("give --roll, --check, or both --count and --sides")
    return RollSpec(
        count=args.count,
        sides=args.sides,
        modifier=args.modifier or 0,
        mode=args.mode or DEFAULT_MODE,
        target=args.target,
        label=args.label or "",
    )


def _report(result: RollResult, *, as_json: bool) -> int:
    if as_json:
        print(json.dumps(result.as_dict(), indent=2))
        return 0
    print(result.render())
    return 0


def main(argv: list[str] | None = None) -> int:
    """Entry point for the ``ttrpg-chatbots-dice`` console script."""
    args = _parse_args(argv)
    request = None
    try:
        if args.list_checks:
            return _list_checks(args)

        if args.ask:
            checks = load_checks(args.data)
            request = parse_instruction(args.ask, checks=checks)
            if request is None:
                print(
                    f"error: {args.ask!r} is not a roll instruction; try 'roll 3d6' or "
                    f"'roll stealth'",
                    file=sys.stderr,
                )
                return 2
            character = args.character or request.character
            spec = request.spec
        else:
            character = args.character
            spec = _spec_from_args(args)

        if not character or not character.strip():
            print(
                "error: say who is rolling (--character), or name them in --ask",
                file=sys.stderr,
            )
            return 2

        result = _roller(args.seed).roll(spec, character=character.strip())
    except (DiceError, ValueError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    if request is not None and not args.json:
        print(f"understood: {describe_request(request)}")
    return _report(result, as_json=args.json)
