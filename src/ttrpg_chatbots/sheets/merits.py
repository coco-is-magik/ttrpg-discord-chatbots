"""The merits-and-flaws catalogue: what a named merit costs in the books.

House Games says "Merits: Standard cost", which means *the cost in whatever book the merit comes
from*. This module is that lookup, built once from the group's own index (see
``custom_assets/meritsflaws.pdf`` and the parser in the repo history), and it is deliberately
**optional**: the rules also allow a custom merit or flaw, priced by the group. So a missing
entry is not an error — it means "tell me the points".

Costs are a single value or a range (``Enemy 1-5``): a range means the value depends on the
rating chosen, so the caller must pick rather than the loader guessing.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from ttrpg_chatbots.sheets.types import normalise

KIND_MERIT = "merit"
KIND_FLAW = "flaw"
KINDS = (KIND_MERIT, KIND_FLAW)

DEFAULT_PATH = Path("custom_assets") / "merits_flaws.json"
PATH_ENV = "TTRPG_MERITS_DB"


class MeritError(RuntimeError):
    """A catalogue that cannot be read, or a lookup that cannot be answered."""


@dataclass(frozen=True)
class MeritEntry:
    """One merit or flaw as a book prints it."""

    name: str
    kind: str
    minimum: int | None
    maximum: int | None
    source: str = ""
    page: int = 0
    game: str = ""
    category: str = ""

    @property
    def fixed(self) -> bool:
        """Whether the book gives one value rather than a range."""
        return self.minimum is not None and self.minimum == self.maximum

    @property
    def label(self) -> str:
        if self.minimum is None:
            return "value varies"
        if self.fixed:
            return str(self.minimum)
        return f"{self.minimum}-{self.maximum}"

    def describe(self) -> str:
        where = f"{self.source}" + (f" p{self.page}" if self.page else "")
        return f"{self.name} ({self.kind}) {self.label} — {where}"


class Catalogue:
    """Merits and flaws by name, from one index file."""

    def __init__(self, entries: tuple[MeritEntry, ...] = ()) -> None:
        self._entries: dict[tuple[str, str], MeritEntry] = {}
        for entry in entries:
            self._entries.setdefault((entry.kind, normalise(entry.name)), entry)

    def __len__(self) -> int:
        return len(self._entries)

    def lookup(self, name: str, kind: str | None = None) -> MeritEntry | None:
        """The entry for ``name``, preferring ``kind`` when both exist."""
        key = normalise(name)
        order = (kind, *[other for other in KINDS if other != kind]) if kind else KINDS
        for candidate in order:
            if candidate is None:
                continue
            found = self._entries.get((candidate, key))
            if found is not None:
                return found
        return None

    def names(self, kind: str | None = None) -> tuple[str, ...]:
        return tuple(
            sorted(
                entry.name
                for (entry_kind, _), entry in self._entries.items()
                if kind is None or entry_kind == kind
            )
        )

    def search(self, text: str, kind: str | None = None, limit: int = 25) -> tuple[MeritEntry, ...]:
        wanted = normalise(text)
        return tuple(
            entry
            for entry in self._entries.values()
            if wanted in normalise(entry.name) and (kind is None or entry.kind == kind)
        )[:limit]


EMPTY = Catalogue()


def load_catalogue(path: Path | str | None = None) -> Catalogue:
    """Read the index. A missing file is an empty catalogue, not a failure.

    A group that has not built the index yet can still make custom merits, which is the point
    of the catalogue being optional.
    """
    target = Path(path or os.environ.get(PATH_ENV, str(DEFAULT_PATH)))
    if not target.is_file():
        return EMPTY
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise MeritError(f"cannot read the merit catalogue at {target}: {error}") from error
    entries: list[MeritEntry] = []
    for kind in KINDS:
        for raw in data.get(kind + "s", []):
            entries.append(_entry_from(raw, kind))
    return Catalogue(tuple(entries))


def _entry_from(raw: Any, kind: str) -> MeritEntry:
    if not isinstance(raw, Mapping):
        raise MeritError("a catalogue entry must be an object")
    name = raw.get("name")
    if not isinstance(name, str) or not name.strip():
        raise MeritError(f"a {kind} needs a name")
    minimum = raw.get("min")
    maximum = raw.get("max")
    for value in (minimum, maximum):
        if value is not None and (isinstance(value, bool) or not isinstance(value, int)):
            raise MeritError(f"{name}: points must be whole numbers or null")
    return MeritEntry(
        name=name.strip(),
        kind=kind,
        minimum=minimum,
        maximum=maximum,
        source=str(raw.get("source", "") or ""),
        page=int(raw.get("page", 0) or 0),
        game=str(raw.get("game", "") or ""),
        category=str(raw.get("category", "") or ""),
    )
