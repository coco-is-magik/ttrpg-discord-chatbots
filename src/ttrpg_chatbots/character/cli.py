"""Command line front end for characters: create, randomise, import, inspect, log."""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

from ttrpg_chatbots.character import creation, importer, randomiser
from ttrpg_chatbots.character.prompting import PrompterError
from ttrpg_chatbots.character.store import CharacterStore
from ttrpg_chatbots.character.types import Character, CharacterError
from ttrpg_chatbots.sheets.interview import load_questionnaire
from ttrpg_chatbots.sheets.types import SheetError

DEFAULT_QUESTIONNAIRE = Path("examples/house_games/interview.json")


class TerminalPrompter:
    """The Prompter for a human at a keyboard. A Discord one would sit beside it."""

    def ask(self, prompt: str) -> str:
        return input(f"{prompt}: ")

    def say(self, text: str) -> None:
        # Flushed: when answers are piped in, an unflushed print arrives *after* the
        # next prompt, which reads as though the bot answered out of order.
        print(text, flush=True)


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="ttrpg-chatbots-character",
        description="Build, randomise, import and update characters without a spreadsheet.",
    )
    parser.add_argument("--dir", type=Path, default=CharacterStore().root)
    parser.add_argument("--questionnaire", type=Path, default=DEFAULT_QUESTIONNAIRE)
    parser.add_argument("--new", action="store_true", help="run the creation interview")
    parser.add_argument("--name", help="character name")
    parser.add_argument("--random", action="store_true", help="roll random but legal mechanics")
    parser.add_argument("--premade", action="store_true", help="assign a finished character")
    parser.add_argument("--rename", help="rename a premade when assigning it")
    parser.add_argument("--import-xlsx", type=Path, metavar="FILE")
    parser.add_argument("--all", action="store_true", help="with --import-xlsx: every character")
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--show", metavar="ID")
    parser.add_argument("--event", metavar="ID", help="append an event to a character's history")
    parser.add_argument("--kind", default="note", help="event kind (default: note)")
    parser.add_argument("--summary", default="", help="event summary")
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--no-seal", action="store_true", help="leave the interview editable")
    parser.add_argument(
        "--force",
        action="store_true",
        help="allow --premade to overwrite an existing character of the same name",
    )
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def _questionnaire(path: Path):
    if not path.is_file():
        raise SheetError(
            f"no questionnaire at {path}; pass --questionnaire, or import an existing "
            "character with --import-xlsx"
        )
    return load_questionnaire(path)


def _describe(character: Character) -> str:
    if character.ready:
        state = "ready"
    elif character.sealed:
        state = "sealed"
    else:
        state = "in progress"
    answers = (
        f"{character.interview.answered}/{character.interview.total} answers"
        if character.interview is not None
        else "no interview"
    )
    return (
        f"{character.name} [{character.id}] {character.system}: {state}, {answers}, "
        f"{len(character.history)} event(s)"
    )


def _report(character: Character, path: Path, *, as_json: bool) -> int:
    if as_json:
        print(character.to_json().strip())
        return 0
    print(_describe(character))
    print(f"saved: {path}")
    return 0


def _show(character: Character, *, as_json: bool) -> int:
    if as_json:
        print(character.to_json().strip())
        return 0
    sheet = character.sheet
    print(_describe(character))
    print("attributes: " + ", ".join(f"{k} {v}" for k, v in sheet.attributes.items()))
    trained = [
        f"{ability.name} {ability.rank}"
        for ability in sheet.abilities.values()
        if ability.rank
    ]
    if trained:
        print("abilities: " + ", ".join(trained))
    if sheet.virtues:
        print("virtues: " + ", ".join(f"{k} {v}" for k, v in sheet.virtues.items()))
    print(
        f"willpower {sheet.willpower}, morality {sheet.morality}, "
        f"{len(sheet.health)} health levels"
    )
    if sheet.backgrounds:
        print("backgrounds: " + ", ".join(f"{t.name} {t.dots}" for t in sheet.backgrounds))
    if sheet.powers:
        print("powers: " + ", ".join(f"{t.name} {t.dots}" for t in sheet.powers))
    if character.interview is not None:
        missing = character.interview.missing
        line = f"interview: {character.interview.answered}/{character.interview.total} answered"
        print(line + (f", {len(missing)} unanswered" if missing else ""))
    for event in character.history[-5:]:
        print(f"  {event.at or '?'} {event.kind}: {event.summary}")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Entry point for the ``ttrpg-chatbots-character`` console script."""
    args = _parse_args(argv)
    store = CharacterStore(args.dir)
    try:
        if args.list:
            rows = []
            lines = []
            for identifier in store.ids():
                try:
                    character = store.load(identifier)
                except CharacterError as error:
                    # One broken file must not hide every other character.
                    rows.append({"id": identifier, "error": str(error)})
                    lines.append(f"{identifier}: UNREADABLE ({error})")
                    continue
                rows.append(
                    {
                        "id": character.id,
                        "name": character.name,
                        "system": character.system,
                        "ready": character.ready,
                        "events": len(character.history),
                    }
                )
                lines.append(_describe(character))
            if args.json:
                print(json.dumps(rows, indent=2))
            else:
                print("\n".join(lines) or "none")
            return 0

        if args.show:
            return _show(store.load(args.show), as_json=args.json)

        if args.event:
            character = store.load(args.event)
            updated = character.record(args.kind, args.summary or args.kind)
            return _report(updated, store.save(updated), as_json=args.json)

        if args.import_xlsx:
            if args.name:
                names = [args.name]
            elif args.all:
                names = list(importer.importable_names(args.import_xlsx))
            else:
                names = []
            if not names:
                found = ", ".join(importer.importable_names(args.import_xlsx)) or "none found"
                raise CharacterError(f"give --name, or --all for every character ({found})")
            for name in names:
                character = importer.import_character(args.import_xlsx, name)
                print(f"imported {character.name} -> {store.save(character)}")
            return 0

        if args.new:
            character = creation.start_character(
                TerminalPrompter(),
                _questionnaire(args.questionnaire),
                name=args.name,
                seal=not args.no_seal,
            )
            return _report(character, store.save(character), as_json=args.json)

        if args.random:
            rng = random.Random(args.seed)
            character = randomiser.random_character(
                rng, name=args.name, questionnaire=_questionnaire(args.questionnaire)
            )
            return _report(character, store.save(character), as_json=args.json)

        if args.premade:
            rng = random.Random(args.seed)
            character = randomiser.assign_premade(
                rng, randomiser.pool_by_system(store.all()), rename=args.rename
            )
            # Handing out a premade must not quietly rewrite the pool's own file: that
            # would pile "assigned" events onto the template every time someone rolls.
            if store.exists(character.id) and not args.force:
                raise CharacterError(
                    f"{character.name!r} already exists in {store.root}; give --rename "
                    "to hand out a copy under another name, or --force to overwrite"
                )
            return _report(character, store.save(character), as_json=args.json)

        print(
            "error: give one of --new, --random, --premade, --import-xlsx, --list, "
            "--show or --event",
            file=sys.stderr,
        )
        return 2
    except (CharacterError, PrompterError, SheetError, ValueError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # runnable as ``python -m ttrpg_chatbots.character.cli``
    raise SystemExit(main())

