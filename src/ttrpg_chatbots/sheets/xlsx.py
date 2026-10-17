"""Read ``.xlsx`` workbooks with the standard library only.

An ``.xlsx`` file is a zip of XML parts, so a reader needs nothing beyond ``zipfile`` and
``xml.etree``. That keeps the sheet layer dependency-free, in the same spirit as the
reply engine, and it lets a test read a generated workbook without a fixture library.

Merged cells matter here: in these sheets a label sits in ``A7`` while its value sits in
``B7`` of a merged ``B7:C7``. :class:`Grid` therefore resolves a reference inside a merge
to the range's top-left cell, so callers never have to know the merge map.
"""

from __future__ import annotations

import re
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

from ttrpg_chatbots.sheets.types import SheetError

MAIN = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
DOC_REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"

REF_RE = re.compile(r"^([A-Za-z]+)(\d+)$")


class WorkbookError(SheetError):
    """Raised when a workbook cannot be opened or a sheet cannot be found."""


def column_index(letters: str) -> int:
    """``B`` -> 2, ``AA`` -> 27."""
    index = 0
    for char in letters.upper():
        index = index * 26 + (ord(char) - 64)
    return index


def column_letters(index: int) -> str:
    """2 -> ``B``; the inverse of :func:`column_index`."""
    if index < 1:
        raise ValueError(f"column index must be >= 1, got {index}")
    letters = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


def join_ref(row: int, column: int) -> str:
    return f"{column_letters(column)}{row}"


def split_ref(ref: str) -> tuple[int, int]:
    """``B7`` -> ``(7, 2)``."""
    match = REF_RE.match(ref.strip())
    if match is None:
        raise WorkbookError(f"not a cell reference: {ref!r}")
    return int(match.group(2)), column_index(match.group(1))


@dataclass(frozen=True)
class Grid:
    """One worksheet: cell text by reference, plus the merge and style maps."""

    name: str
    cells: Mapping[str, str] = field(default_factory=dict)
    merged: tuple[tuple[int, int, int, int], ...] = ()
    styles: Mapping[str, int] = field(default_factory=dict)
    wrapped_styles: frozenset[int] = frozenset()
    # Non-fatal reading complaints (a sentence where a number belonged). Filled by
    # number()/integer(); a reader decides whether to surface them.
    notes: list[str] = field(default_factory=list)

    @property
    def max_row(self) -> int:
        """The last row the sheet actually has a cell in.

        Styled-but-empty cells count: an answer someone has cleared still occupies its
        row, and a reader that ignored it would think the sheet ended a row early.
        """
        refs = set(self.cells) | set(self.styles)
        return max((split_ref(ref)[0] for ref in refs), default=0)

    def wrapped(self, ref: str) -> bool:
        """Whether the cell carries a wrap-text style.

        The character questionnaire uses exactly this to mark answer rows, so it is the
        structure rather than a guess about punctuation.
        """
        style = self.styles.get(ref.strip().upper())
        return style is not None and style in self.wrapped_styles

    def value(self, ref: str) -> str:
        """Text in ``ref``, or in the top-left cell of the merge containing it."""
        text = self.cells.get(ref.strip().upper(), "")
        if text:
            return text
        return self.cells.get(self._anchor(ref), "")

    def _anchor(self, ref: str) -> str:
        row, column = split_ref(ref)
        for row1, col1, row2, col2 in self.merged:
            if row1 <= row <= row2 and col1 <= column <= col2:
                return join_ref(row1, col1)
        return ref.strip().upper()

    def filled(self, ref: str) -> bool:
        return bool(self.value(ref).strip())

    def text(self, ref: str) -> str:
        """Whitespace-collapsed text, for labels."""
        return " ".join(self.value(ref).split())

    def number(self, ref: str, *, default: float = 0.0, strict: bool = False) -> float:
        """A number from ``ref``.

        Filled sheets are human artefacts: a stat cell sometimes holds a sentence
        instead of a figure. Rather than crash the whole import, a cell that is not a
        number returns ``default`` and is *recorded* in :attr:`notes`, so the loss is
        visible to whoever imported the sheet. ``strict=True`` raises instead.
        """
        text = self.value(ref).strip()
        if not text:
            return default
        try:
            return float(text)
        except ValueError as error:
            if strict:
                raise WorkbookError(f"{self.name}!{ref} is not a number: {text!r}") from error
            note = f"{ref}: expected a number, found {text!r}; using {default}"
            if note not in self.notes:
                self.notes.append(note)
            return default

    def integer(self, ref: str, *, default: int = 0, strict: bool = False) -> int:
        return int(round(self.number(ref, default=float(default), strict=strict)))


def sheet_names(path: Path | str) -> tuple[str, ...]:
    """The tab names, in workbook order."""
    with _open(path) as (archive, _):
        return tuple(label for label, _ in _sheet_entries(archive))


def read_grid(path: Path | str, sheet: str | int | None = None) -> Grid:
    """Read one worksheet by name, or by position when ``sheet`` is an int."""
    with _open(path) as (archive, source):
        entries = _sheet_entries(archive)
        if not entries:
            raise WorkbookError(f"{source} contains no sheets")
        label, target = _choose(entries, sheet, source)
        shared = _shared_strings(archive)
        wrapped = _wrap_styles(archive)
        try:
            root = ET.fromstring(archive.read(target))
        except (KeyError, ET.ParseError) as error:
            raise WorkbookError(f"cannot read sheet {label!r}: {error}") from error
    cells, styles = _read_cells(root, shared)
    return Grid(
        name=label,
        cells=cells,
        merged=_read_merges(root),
        styles=styles,
        wrapped_styles=wrapped,
    )


def _open(path: Path | str):
    source = Path(path)
    try:
        archive = zipfile.ZipFile(source)
    except (OSError, zipfile.BadZipFile) as error:
        raise WorkbookError(f"cannot open workbook {source}: {error}") from error
    if "xl/workbook.xml" not in archive.namelist():
        archive.close()
        raise WorkbookError(f"{source} is not an .xlsx workbook (no xl/workbook.xml)")
    return _Closing(archive, source)


class _Closing:
    """``with`` support that keeps the source path around for error messages."""

    def __init__(self, archive: zipfile.ZipFile, source: Path) -> None:
        self._archive = archive
        self._source = source

    def __enter__(self) -> tuple[zipfile.ZipFile, Path]:
        return self._archive, self._source

    def __exit__(self, *exc_info: object) -> None:
        self._archive.close()


def _sheet_entries(archive: zipfile.ZipFile) -> list[tuple[str, str]]:
    """``(tab name, zip path)`` for every sheet, in workbook order."""
    try:
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        rels = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    except (KeyError, ET.ParseError) as error:
        raise WorkbookError(f"cannot read the workbook structure: {error}") from error

    targets: dict[str, str] = {}
    for relation in rels:
        identifier = relation.get("Id")
        target = relation.get("Target") or ""
        if not identifier or not target:
            continue
        targets[identifier] = target.lstrip("/") if target.startswith("/") else f"xl/{target}"

    entries: list[tuple[str, str]] = []
    for sheet in workbook.iter(MAIN + "sheet"):
        label = sheet.get("name") or ""
        target = targets.get(sheet.get(DOC_REL + "id") or "")
        if label and target:
            entries.append((label, target))
    return entries


def _choose(
    entries: list[tuple[str, str]], sheet: str | int | None, source: Path
) -> tuple[str, str]:
    if sheet is None:
        return entries[0]
    if isinstance(sheet, int):
        if not 0 <= sheet < len(entries):
            listed = ", ".join(label for label, _ in entries)
            raise WorkbookError(f"{source}: sheet index {sheet} is out of range ({listed})")
        return entries[sheet]
    wanted = " ".join(str(sheet).split()).lower()
    for label, target in entries:
        if label.strip().lower() == wanted:
            return label, target
    listed = ", ".join(label for label, _ in entries)
    raise WorkbookError(f"{source} has no sheet named {sheet!r}; sheets: {listed}")


def _shared_strings(archive: zipfile.ZipFile) -> list[str]:
    try:
        root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    except KeyError:
        return []
    except ET.ParseError as error:
        raise WorkbookError(f"cannot read shared strings: {error}") from error
    return ["".join(node.text or "" for node in item.iter(MAIN + "t")) for item in root]


def _wrap_styles(archive: zipfile.ZipFile) -> frozenset[int]:
    """Style indices whose cell format wraps text.

    Absent styles are normal (a hand-made sheet has none), so this returns an empty set
    rather than failing; a caller that *needs* the formatting checks for that.
    """
    try:
        root = ET.fromstring(archive.read("xl/styles.xml"))
    except KeyError:
        return frozenset()
    except ET.ParseError as error:
        raise WorkbookError(f"cannot read cell styles: {error}") from error

    formats = root.find(MAIN + "cellXfs")
    if formats is None:
        return frozenset()
    wrapped = set()
    for index, cell_format in enumerate(formats):
        alignment = cell_format.find(MAIN + "alignment")
        if alignment is None:
            continue
        if (alignment.get("wrapText") or "").lower() in {"1", "true"}:
            wrapped.add(index)
    return frozenset(wrapped)


def _read_cells(root: ET.Element, shared: list[str]) -> tuple[dict[str, str], dict[str, int]]:
    cells: dict[str, str] = {}
    styles: dict[str, int] = {}
    for cell in root.iter(MAIN + "c"):
        ref = (cell.get("r") or "").strip().upper()
        if not ref:
            continue
        style = cell.get("s")
        if style is not None:
            try:
                styles[ref] = int(style)
            except ValueError:
                pass
        text = _cell_text(cell, shared)
        if text.strip():
            cells[ref] = text
    return cells, styles


def _cell_text(cell: ET.Element, shared: list[str]) -> str:
    kind = cell.get("t")
    if kind == "inlineStr":
        return "".join(node.text or "" for node in cell.iter(MAIN + "t"))
    value = cell.find(MAIN + "v")
    if value is None or value.text is None:
        return ""
    raw = value.text
    if kind == "s":
        try:
            return shared[int(raw)]
        except (ValueError, IndexError):
            return ""
    if kind == "b":
        return "TRUE" if raw == "1" else "FALSE"
    return raw


def _read_merges(root: ET.Element) -> tuple[tuple[int, int, int, int], ...]:
    ranges: list[tuple[int, int, int, int]] = []
    for merged in root.iter(MAIN + "mergeCell"):
        ref = merged.get("ref") or ""
        start, _, end = ref.partition(":")
        try:
            row1, col1 = split_ref(start)
            row2, col2 = split_ref(end or start)
        except WorkbookError:
            continue
        ranges.append((min(row1, row2), min(col1, col2), max(row1, row2), max(col1, col2)))
    return tuple(ranges)

