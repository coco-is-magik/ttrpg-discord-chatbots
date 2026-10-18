"""Build small ``.xlsx`` workbooks for the sheet tests.

The shipped workbook is user data and every tab in it is a blank template, so the tests
build their own workbook in the *same* layout: labels in the same cells, values in the
same merged ranges. That keeps the suite hermetic while still pinning the real cell map.

The labels here are deliberately duplicated rather than imported from ``houseg``: a
fixture that borrows the implementation's constants cannot catch a mistake in them.
"""

from __future__ import annotations

import zipfile
from pathlib import Path
from typing import Any, Mapping

MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
DOC_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
CONTENT = "application/vnd.openxmlformats-officedocument.spreadsheetml"

TALENTS = (
    "Alertness",
    "Athletics",
    "Brawl",
    "Dodge",
    "Endurance",
    "Intimidation",
    "Intuition",
    "Legerdemain",
    "Persuasion",
    "Subterfuge",
)
SKILLS = (
    "Animal Ken",
    "Crafts",
    "Engineering",
    "Firearms",
    "Meditation",
    "Melee",
    "Performance",
    "Pilot",
    "Stealth",
    "Survival",
)
KNOWLEDGES = (
    "Academics",
    "Computers",
    "Culture",
    "Investigation",
    "Linguistics",
    "Management",
    "Medicine",
    "Occult",
    "Pyshcology",
    "Science",
)

ABILITY_COLUMNS = (("A", "B", "C", TALENTS), ("D", "E", "F", SKILLS), ("G", "H", "I", KNOWLEDGES))

# name -> (dots cell, specialty cell)
ABILITY_REFS = {
    name: (f"{dots_col}{12 + offset}", f"{spec_col}{12 + offset}")
    for _, spec_col, dots_col, names in ABILITY_COLUMNS
    for offset, name in enumerate(names)
}

ATTRIBUTES = (
    ("A7", "Strength", "B7"),
    ("A8", "Dexterity", "B8"),
    ("A9", "Stamina", "B9"),
    ("D7", "Charisma", "E7"),
    ("D8", "Manipulation", "E8"),
    ("D9", "Appearance", "E9"),
    ("G7", "Perception", "H7"),
    ("G8", "Intelligence", "H8"),
    ("G9", "Wits", "H9"),
)

VIRTUE_REFS = {
    "Conscience/Conviction": "E29",
    "Self-Control/Instinct": "E30",
    "Courage": "E31",
}

HEALTH = (
    (24, "Unharmed"),
    (25, "Bruised"),
    (26, "Hurt (-1)"),
    (27, "Injured (-1)"),
    (28, "Wounded (-2)"),
    (29, "Mauled (-2)"),
    (30, "Crippled (-5)"),
    (31, "Incapacitated"),
)

# Merged ranges the reader must see through: every value sits in the left-hand cell.
HOUSE_MERGES = (
    "B2:C2",
    "B3:C3",
    "E2:F2",
    "E3:F3",
    "H2:I2",
    "H3:I3",
    "H4:I4",
    "B4:C4",
    "E4:F4",
    "B7:C7",
    "B8:C8",
    "B9:C9",
    "E7:F7",
    "E8:F8",
    "E9:F9",
    "H7:I7",
    "H8:I8",
    "H9:I9",
    "D25:F25",
    "B26:C26",
    "E26:F26",
    "B27:C27",
    "E27:F27",
    "B28:C28",
    "D28:F28",
    "B29:C29",
    "E29:F29",
    "H29:I29",
    "B30:C30",
    "E30:F30",
    "B31:C31",
    "E31:F31",
    "H31:I31",
    "D32:F32",
    "A32:C32",
)


def house_cells(
    *,
    name: str | None = "Brannoc the Archivist",
    player: str = "Dan",
    attributes: Mapping[str, int] | None = None,
    abilities: Mapping[str, int] | None = None,
    specialties: Mapping[str, str] | None = None,
    virtues: Mapping[str, int] | None = None,
    willpower: int | None = 5,
    willpower_remaining: int | None = 4,
    morality: int | None = 7,
    gifts: Mapping[str, int] | None = None,
    backgrounds: Mapping[str, int] | None = None,
    merits: Mapping[str, int] | None = None,
) -> dict[str, Any]:
    """A filled House Games tab, using the workbook's own cells."""
    cells: dict[str, Any] = {
        "A1": "Information",
        "A2": "Name",
        "A3": "Player",
        "A5": "Attributes",
        "A6": "Physical",
        "D6": "Social",
        "G6": "Mental",
        "A10": "Abilities",
        "A11": "Talents",
        "D11": "Skills",
        "G11": "Knowledges",
        "A22": "Advantages",
        "A23": "Merits and Flaws",
        "D23": "Morality",
        "G23": "Health",
        "D24": "Total",
        "D25": "Willpower",
        "D26": "Total",
        "D27": "Remaining",
        "D28": "Virtues",
        "D29": "Conscience/Conviction",
        "D30": "Self Control/Instinct",
        "D31": "Courage",
        "A24": "Name",
        "B24": "Point Cost/Bonus",
        "A32": "Powers/Paths",
        "D32": "Backgrounds",
        "A33": "Power",
        "B33": "# dots",
        "D33": "background",
        "E33": "# dots",
    }
    if name is not None:
        cells["B2"] = name
    if player:
        cells["B3"] = player
    for label_ref, label, value_ref in ATTRIBUTES:
        cells[label_ref] = label
        cells[value_ref] = (attributes or {}).get(label, 0)
    for label_col, spec_col, dots_col, names in ABILITY_COLUMNS:
        for offset, label in enumerate(names):
            row = 12 + offset
            cells[f"{label_col}{row}"] = label
            cells[f"{dots_col}{row}"] = 0
            # The template ships the literal "Spec" placeholder in every specialty cell.
            cells[f"{spec_col}{row}"] = "Spec"
    for ability, rank in (abilities or {}).items():
        cells[ABILITY_REFS[ability][0]] = rank
    for ability, text in (specialties or {}).items():
        cells[ABILITY_REFS[ability][1]] = text
    for label, dots in (virtues or {}).items():
        cells[VIRTUE_REFS[label]] = dots
    if willpower is not None:
        cells["E26"] = willpower
    if willpower_remaining is not None:
        cells["E27"] = willpower_remaining
    if morality is not None:
        cells["E24"] = morality
    for row, label in HEALTH:
        cells[f"G{row}"] = label
    for offset, (label, dots) in enumerate((gifts or {}).items()):
        cells[f"A{34 + offset}"] = label
        cells[f"B{34 + offset}"] = dots
    for offset, (label, dots) in enumerate((backgrounds or {}).items()):
        cells[f"D{34 + offset}"] = label
        cells[f"E{34 + offset}"] = dots
    for offset, (label, points) in enumerate((merits or {}).items()):
        cells[f"A{25 + offset}"] = label
        cells[f"B{25 + offset}"] = points
    return cells



def write_workbook(
    path: Path,
    sheets: Mapping[str, Mapping[str, Any]],
    *,
    merges: Mapping[str, tuple[str, ...]] | None = None,
    wrapped: Mapping[str, tuple[str, ...]] | None = None,
) -> Path:
    """Write a minimal but valid ``.xlsx``; strings go through sharedStrings.

    ``wrapped`` marks cells that should carry a wrap-text style — the signal the
    questionnaire reader uses to tell answers from questions.
    """
    merges = merges or {}
    wrapped = wrapped or {}
    strings: list[str] = []
    index: dict[str, int] = {}

    def shared(text: str) -> int:
        if text not in index:
            index[text] = len(strings)
            strings.append(text)
        return index[text]

    parts: dict[str, str] = {}
    for position, (name, cells) in enumerate(sheets.items(), start=1):
        wrapped_refs = set(wrapped.get(name, ()))
        rows: dict[int, list[str]] = {}
        for ref, value in cells.items():
            if value is None:
                continue
            style = ' s="1"' if ref in wrapped_refs else ""
            row = int("".join(character for character in ref if character.isdigit()))
            if isinstance(value, str):
                if value:
                    cell = f'<c r="{ref}"{style} t="s"><v>{shared(value)}</v></c>'
                else:
                    cell = f'<c r="{ref}"{style}/>'
            else:
                cell = f'<c r="{ref}"{style}><v>{value}</v></c>'
            rows.setdefault(row, []).append(cell)
        body = "".join(
            f'<row r="{row}">{"".join(items)}</row>' for row, items in sorted(rows.items())
        )
        ranges = merges.get(name, ())
        merge_block = ""
        if ranges:
            inner = "".join(f'<mergeCell ref="{item}"/>' for item in ranges)
            merge_block = f'<mergeCells count="{len(ranges)}">{inner}</mergeCells>'
        parts[f"xl/worksheets/sheet{position}.xml"] = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            f'<worksheet xmlns="{MAIN}"><sheetData>{body}</sheetData>'
            f"{merge_block}</worksheet>"
        )

    workbook_sheets = "".join(
        f'<sheet name="{name}" sheetId="{position}" r:id="rId{position}"/>'
        for position, name in enumerate(sheets, start=1)
    )
    relationships = "".join(
        f'<Relationship Id="rId{position}" Type="{DOC_REL}/worksheet" '
        f'Target="worksheets/sheet{position}.xml"/>'
        for position in range(1, len(sheets) + 1)
    )
    overrides = "".join(
        f'<Override PartName="/xl/worksheets/sheet{position}.xml" '
        f'ContentType="{CONTENT}.worksheet+xml"/>'
        for position in range(1, len(sheets) + 1)
    )
    shared_items = "".join(f"<si><t>{_escape(item)}</t></si>" for item in strings)

    parts["[Content_Types].xml"] = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<Types xmlns="{PKG_REL}-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package'
        '.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        f'<Override PartName="/xl/workbook.xml" ContentType="{CONTENT}.sheet.main+xml"/>'
        f'<Override PartName="/xl/sharedStrings.xml" '
        f'ContentType="{CONTENT}.sharedStrings+xml"/>'
        f'<Override PartName="/xl/styles.xml" ContentType="{CONTENT}.styles+xml"/>'
        f"{overrides}</Types>"
    )
    parts["_rels/.rels"] = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<Relationships xmlns="{PKG_REL}">'
        f'<Relationship Id="rId1" Type="{DOC_REL}/officeDocument" '
        'Target="xl/workbook.xml"/></Relationships>'
    )
    parts["xl/workbook.xml"] = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<workbook xmlns="{MAIN}" xmlns:r="{DOC_REL}">'
        f"<sheets>{workbook_sheets}</sheets></workbook>"
    )
    parts["xl/_rels/workbook.xml.rels"] = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<Relationships xmlns="{PKG_REL}">{relationships}</Relationships>'
    )
    parts["xl/sharedStrings.xml"] = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<sst xmlns="{MAIN}" count="{len(strings)}" uniqueCount="{len(strings)}">'
        f"{shared_items}</sst>"
    )
    # Style 1 is the wrapped body style; that is what marks an answer row.
    parts["xl/styles.xml"] = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<styleSheet xmlns="{MAIN}">'
        '<fonts count="1"><font/></fonts>'
        '<fills count="1"><fill><patternFill patternType="none"/></fill></fills>'
        '<borders count="1"><border/></borders>'
        '<cellStyleXfs count="1"><xf/></cellStyleXfs>'
        '<cellXfs count="2"><xf/><xf><alignment wrapText="1"/></xf></cellXfs>'
        "</styleSheet>"
    )

    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, text in parts.items():
            archive.writestr(name, text)
    return path


def questionnaire(*sections: tuple[str, list[tuple[str, str]]]) -> tuple[dict[str, Any], list[str]]:
    """Build a questionnaire tab: ``(cells, wrapped refs)``.

    Sections are ``(title, [(question, answer), ...])``. An answer of ``""`` leaves a
    styled but empty cell, which is how an unanswered question looks; ``None`` omits the
    cell entirely, which is how a deleted row looks.
    """
    cells: dict[str, Any] = {}
    wrapped: list[str] = []
    row = 1
    for title, pairs in sections:
        cells[f"A{row}"] = title
        row += 1
        for question, answer in pairs:
            cells[f"A{row}"] = question
            if answer is not None:
                cells[f"A{row + 1}"] = answer
                wrapped.append(f"A{row + 1}")
            row += 2
    return cells, wrapped


def questionnaire_workbook(
    path: Path,
    *sections: tuple[str, list[tuple[str, str]]],
    tab: str = "AQ Test Subject",
) -> Path:
    """A workbook whose only tab is a questionnaire."""
    cells, wrapped = questionnaire(*sections)
    return write_workbook(path, {tab: cells}, wrapped={tab: tuple(wrapped)})



def _escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def house_workbook(
    path: Path,
    *,
    tab: str = "House Games",
    extra_tabs: tuple[str, ...] = (),
    **cells: Any,
) -> Path:
    """A workbook with one filled House Games tab (and any extra empty tabs)."""
    sheets: dict[str, Mapping[str, Any]] = {tab: house_cells(**cells)}
    for name in extra_tabs:
        sheets[name] = {"A1": name}
    return write_workbook(path, sheets, merges={tab: HOUSE_MERGES})

