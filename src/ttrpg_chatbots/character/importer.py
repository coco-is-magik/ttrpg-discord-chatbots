"""Import finished workbook characters into the native model, once.

The workbook stays a *source*, not a dependency: this reads the tabs that exist today,
produces native characters, and from then on no code path needs Excel. Two tabs make one
character -- ``AQ <name>`` for the interview and ``HG <name>`` for the mechanics -- which
is why the importer refuses a name that has only one of them.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any, Callable, Mapping

from ttrpg_chatbots.character.creation import now_utc
from ttrpg_chatbots.character.types import Character, CharacterError
from ttrpg_chatbots.sheets.interview import character_from_tab, read_interview
from ttrpg_chatbots.sheets.systems import houseg
from ttrpg_chatbots.sheets.types import Sheet, SheetError, normalise
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


PERSONAL_META_KEYS = frozenset(
    {"player", "gm", "g.m.", "missions", "mission log", "things to get"}
)


def scrubbed_meta(meta: Mapping[str, Any]) -> dict[str, Any]:
    """Drop anything that identifies a person rather than a character.

    The workbook has a ``Player`` cell and a **mission log** whose rows name the GM and the
    players ("Me, Hikou", "Me, Driver"). Those belong to the people at that table, not to the
    character, and who plays this character is a **seat** now. Anything with one of these
    names is removed rather than carried into the native file.
    """
    return {
        str(key): value
        for key, value in meta.items()
        if str(key).strip().lower() not in PERSONAL_META_KEYS
    }


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

    # Nothing that identifies a person survives the import: seats own identity.
    if sheet.meta:
        sheet = replace(sheet, meta=scrubbed_meta(sheet.meta))

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


def import_interview(
    path: Path | str,
    name: str,
    *,
    clock: Callable[[], str] = now_utc,
) -> Character:
    """Import only the interview: the prose, with no mechanics.

    A workbook is a snapshot, and snapshots go stale — characters advance past the numbers
    on the tab. The 55 answers are the expensive part (hours of writing, impossible to
    reconstruct), while the mechanics are a few dozen numbers that the creation flow can set
    again. So this produces a **draft** character with the answers and an empty sheet, ready
    to be built mechanically in the portal rather than inheriting numbers nobody trusts.
    """
    source = Path(path)
    tabs = _tabs(source)
    wanted = normalise(name)
    interview_tab = next(
        (
            tab
            for tab in tabs
            if tab.upper().startswith(INTERVIEW_PREFIX)
            and normalise(character_from_tab(tab)) == wanted
        ),
        None,
    )
    if interview_tab is None:
        available = ", ".join(importable_names(source)) or "none"
        raise CharacterError(
            f"{source.name} has no interview tab for {name!r}; importable: {available}"
        )

    try:
        interview = read_interview(
            read_grid(source, interview_tab),
            character=name,
            source=f"{source.name} [{interview_tab}]",
        )
    except SheetError as error:
        raise CharacterError(str(error)) from error

    created = clock()
    sheet = Sheet(
        name=name.strip(),
        system=houseg.SYSTEM,
        source=f"{source.name} [{interview_tab}] (interview only)",
    )
    character = Character(sheet=sheet, interview=interview, created=created)
    return character.record(
        "import",
        f"imported the interview from {source.name} [{interview_tab}]; mechanics to be built",
        at=created,
        detail={
            "workbook": str(source),
            "interview_tab": interview_tab,
            "mechanics": "not imported",
        },
    )


def _tabs(source: Path) -> tuple[str, ...]:
    try:
        return sheet_names(source)
    except WorkbookError as error:
        raise CharacterError(str(error)) from error


def import_workbook(
    path: Path | str, *, clock: Callable[[], str] = now_utc
) -> tuple[Character, ...]:
    """Read every complete character in a workbook."""
    return tuple(
        import_character(path, name, clock=clock) for name in importable_names(path)
    )
