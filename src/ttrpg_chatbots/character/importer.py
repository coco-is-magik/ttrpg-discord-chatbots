"""Import finished workbook characters into the native model, once.

The workbook stays a *source*, not a dependency: this reads the tabs that exist today,
produces native characters, and from then on no code path needs Excel. Two tabs make one
character -- ``AQ <name>`` for the interview and ``HG <name>`` for the mechanics -- which
is why the importer refuses a name that has only one of them.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from ttrpg_chatbots.character.creation import now_utc
from ttrpg_chatbots.character.types import Character, CharacterError
from ttrpg_chatbots.sheets.interview import character_from_tab, read_interview
from ttrpg_chatbots.sheets.systems import houseg
from ttrpg_chatbots.sheets.types import SheetError, normalise
from ttrpg_chatbots.sheets.xlsx import WorkbookError, read_grid, sheet_names

INTERVIEW_PREFIX = "AQ "
MECHANICS_PREFIX = "HG "


def importable_names(path: Path | str) -> tuple[str, ...]:
    """Character names in a workbook that have both an interview and a sheet tab."""
    try:
        tabs = sheet_names(path)
    except WorkbookError as error:
        raise CharacterError(str(error)) from error
    interviews = {
        normalise(character_from_tab(tab))
        for tab in tabs
        if tab.upper().startswith(INTERVIEW_PREFIX)
    }
    mechanics = {
        normalise(character_from_tab(tab))
        for tab in tabs
        if tab.upper().startswith(MECHANICS_PREFIX)
    }
    names = {}
    for tab in tabs:
        name = character_from_tab(tab)
        if normalise(name) in interviews & mechanics:
            names[normalise(name)] = name
    return tuple(names[key] for key in sorted(names))


def import_character(
    path: Path | str,
    name: str,
    *,
    clock: Callable[[], str] = now_utc,
) -> Character:
    """Read one character out of a workbook."""
    source = Path(path)
    try:
        tabs = sheet_names(source)
    except WorkbookError as error:
        raise CharacterError(str(error)) from error
    wanted = normalise(name)
    matches = [tab for tab in tabs if normalise(character_from_tab(tab)) == wanted]
    interview_tab = next(
        (tab for tab in matches if tab.upper().startswith(INTERVIEW_PREFIX)), None
    )
    mechanics_tab = next(
        (tab for tab in matches if tab.upper().startswith(MECHANICS_PREFIX)), None
    )
    if interview_tab is None or mechanics_tab is None:
        missing = "interview" if interview_tab is None else "mechanics"
        available = ", ".join(importable_names(source)) or "none"
        raise CharacterError(
            f"{source.name} has no {missing} tab for {name!r}; importable: {available}"
        )

    try:
        interview = read_interview(
            read_grid(source, interview_tab),
            character=name,
            source=f"{source.name} [{interview_tab}]",
        )
        sheet = houseg.read_sheet(
            read_grid(source, mechanics_tab),
            source=f"{source.name} [{mechanics_tab}]",
            name=name,
        )
    except SheetError as error:
        raise CharacterError(str(error)) from error

    created = clock()
    character = Character(sheet=sheet, interview=interview, created=created)
    character = character.record(
        "import",
        f"imported from {source.name} [{mechanics_tab}] and [{interview_tab}]",
        at=created,
        detail={
            "workbook": str(source),
            "sheet_tab": mechanics_tab,
            "interview_tab": interview_tab,
        },
    )
    if interview.complete:
        character = character.seal(at=created)
    return character


def import_workbook(
    path: Path | str, *, clock: Callable[[], str] = now_utc
) -> tuple[Character, ...]:
    """Read every complete character in a workbook."""
    return tuple(
        import_character(path, name, clock=clock) for name in importable_names(path)
    )
