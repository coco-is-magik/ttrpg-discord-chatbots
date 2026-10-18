"""Command line front end for character sheets.

Reads a workbook tab into the neutral :class:`~ttrpg_chatbots.sheets.types.Sheet`, and
rolls from it through the system module's rules.
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
from pathlib import Path

from ttrpg_chatbots.dice.roller import Roller
from ttrpg_chatbots.sheets.interview import Interview, read_interview
from ttrpg_chatbots.sheets.systems import houseg
from ttrpg_chatbots.sheets.types import Sheet, SheetError
from ttrpg_chatbots.sheets.xlsx import read_grid, sheet_names

SPLIT_RE = re.compile(r"[+/]")
QUESTIONNAIRE_PREFIX = "AQ "


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="ttrpg-chatbots-sheet",
        description="Read a character sheet and roll from it.",
    )
    parser.add_argument("--xlsx", type=Path, required=True, help="workbook to read")
    parser.add_argument("--tab", help=f"worksheet name (default: {houseg.TAB})")
    parser.add_argument("--list-tabs", action="store_true", help="show the worksheet names")
    parser.add_argument("--roll", metavar="ATTR+ABILITY", help='e.g. "Dexterity+Stealth"')
    parser.add_argument(
        "--interview", action="store_true", help="read the character questionnaire"
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="report unanswered questions and exit 1 if any remain",
    )
    parser.add_argument("--difficulty", type=int, default=None, help="default 6")
    parser.add_argument(
        "--willpower", action="store_true", help="spend a Willpower for an automatic success"
    )
    parser.add_argument("--seed", type=int, default=None, help="seed the dice, for demos")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    return parser.parse_args(argv)


def _split_pool(expression: str) -> tuple[str, str | None]:
    parts = [part.strip() for part in SPLIT_RE.split(expression) if part.strip()]
    if not parts:
        raise SheetError(f"no trait names in {expression!r}")
    if len(parts) > 2:
        raise SheetError(f"expected ATTR or ATTR+ABILITY, got {expression!r}")
    return parts[0], parts[1] if len(parts) == 2 else None


def _tab(path: Path, requested: str | None) -> str:
    if requested:
        return requested
    available = sheet_names(path)
    if not available:
        raise SheetError(f"{path} contains no worksheets")
    return houseg.TAB if houseg.TAB in available else available[0]


def _report(sheet: Sheet) -> None:
    print(f"{sheet.system}: {sheet.name}  ({sheet.source})")
    if sheet.attributes:
        values = ", ".join(f"{name} {dots}" for name, dots in sheet.attributes.items())
        print(f"attributes: {values}")

    trained = [
        f"{ability.name} {ability.rank}"
        + (f" ({ability.specialty})" if ability.specialty else "")
        for ability in sheet.abilities.values()
        if ability.rank
    ]
    if trained:
        print("abilities: " + ", ".join(trained))

    if sheet.virtues:
        print("virtues: " + ", ".join(f"{name} {dots}" for name, dots in sheet.virtues.items()))

    trackers = []
    if sheet.willpower:
        trackers.append(f"willpower {sheet.willpower}")
    if sheet.willpower_remaining is not None:
        trackers.append(f"{sheet.willpower_remaining} left")
    if sheet.morality is not None:
        trackers.append(f"morality {sheet.morality}")
    if trackers:
        print("trackers: " + ", ".join(trackers))

    if sheet.health:
        print("health: " + " / ".join(sheet.health))
    if sheet.gifts:
        print("gifts: " + ", ".join(gift.label() for gift in sheet.gifts))
        tier = houseg.gift_tier(sheet.gift_count, veteran=sheet.veteran)
        print(f"gift count {sheet.gift_count} ({tier})")
    if sheet.backgrounds:
        print(
            "backgrounds: "
            + ", ".join(f"{trait.name} {trait.dots}" for trait in sheet.backgrounds)
        )

    details = {name: value for name, value in sheet.meta.items() if name != "merits"}
    if details:
        print("details: " + ", ".join(f"{name} {value}" for name, value in details.items()))
    merits = sheet.meta.get("merits") or []
    if merits:
        print(
            "merits/flaws: "
            + ", ".join(f"{entry['name']} ({entry['points']:+})" for entry in merits)
        )


def _roll(args: argparse.Namespace, sheet: Sheet) -> int:
    attribute, ability = _split_pool(args.roll)
    spec = houseg.build_pool(
        sheet,
        attribute,
        ability,
        difficulty=args.difficulty,
        willpower=args.willpower,
    )
    roller = Roller(random.Random(args.seed) if args.seed is not None else None)
    result = houseg.resolve_pool(spec, roller, character=sheet.name)

    if args.json:
        print(
            json.dumps(
                {
                    "sheet": sheet.as_dict(),
                    "pool": {
                        "attribute": spec.attribute,
                        "ability": spec.ability,
                        "dice": spec.dice,
                        "difficulty": spec.difficulty,
                        "specialty": spec.specialty,
                        "willpower": spec.willpower,
                        "notes": list(spec.notes),
                    },
                    "result": {
                        "rolls": list(result.rolls),
                        "rerolls": list(result.rerolls),
                        "successes": result.successes,
                        "ones": result.ones,
                        "net": result.net,
                        "botch": result.botch,
                    },
                    "text": result.render(),
                },
                indent=2,
            )
        )
        return 0

    print(result.render())
    return 0


def _interview_tab(path: Path, requested: str | None) -> str:
    if requested:
        return requested
    for name in sheet_names(path):
        if name.upper().startswith(QUESTIONNAIRE_PREFIX):
            return name
    raise SheetError(
        f"{path} has no questionnaire tab; expected one named {QUESTIONNAIRE_PREFIX!r} + "
        "the character's name"
    )


def _report_check(interview: Interview) -> None:
    state = "complete" if interview.complete else f"{len(interview.missing)} unanswered"
    print(f"{interview.character}: {interview.answered}/{interview.total} answered ({state})")
    for question in interview.missing:
        print(f"  [{question.section or 'no section'}] {question.prompt}")


def _report_interview(interview: Interview) -> None:
    print(f"{interview.character}  ({interview.source})")
    for section in interview.sections:
        if section:
            print(f"\n== {section} ==")
        for question in interview.in_section(section):
            print(f"\nQ: {question.prompt}")
            print(f"A: {question.answer}" if question.answered else "A: (unanswered)")
    print(f"\n{interview.answered}/{interview.total} answered")
    if not interview.complete:
        print(f"WARNING unanswered: {len(interview.missing)} question(s)")


def _interview(args: argparse.Namespace) -> int:
    tab = _interview_tab(args.xlsx, args.tab)
    grid = read_grid(args.xlsx, tab)
    interview = read_interview(grid, source=f"{args.xlsx.name} [{tab}]")

    if args.json:
        print(json.dumps(interview.as_dict(), indent=2))
    elif args.check:
        _report_check(interview)
    else:
        _report_interview(interview)

    # A distinct code for "read fine, but not finished", so a build can gate on it.
    if args.check and not interview.complete:
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    """Entry point for the ``ttrpg-chatbots-sheet`` console script."""
    args = _parse_args(argv)
    try:
        if args.list_tabs:
            names = sheet_names(args.xlsx)
            if args.json:
                print(json.dumps(list(names), indent=2))
            else:
                print("\n".join(names))
            return 0

        if args.interview or args.check:
            return _interview(args)

        grid = read_grid(args.xlsx, _tab(args.xlsx, args.tab))
        sheet = houseg.read_sheet(grid, source=f"{args.xlsx.name} [{grid.name}]")
        if args.roll:
            return _roll(args, sheet)
        if args.json:
            print(json.dumps(sheet.as_dict(), indent=2))
        else:
            _report(sheet)
        return 0
    except (SheetError, ValueError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # runnable as ``python -m ttrpg_chatbots.sheets.cli``
    raise SystemExit(main())

