"""Is a scene open, whose turn, in character?

Table state is written by the sheet portal, not by this layer: the conversation only needs to read
it. An absent or unreadable file means "no scene", which is also what it means in #general."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

DEFAULT_PATH = Path("data/table.json")


@dataclass(frozen=True)
class TableState:
    """Who is at the table, and whether anybody is in character."""

    scene: str = ""
    turn: str = ""
    mode: str = "ooc"

    @property
    def open(self) -> bool:
        return bool(self.scene)


def read(path: Path | str | None = None) -> TableState:
    """The table, or an empty one when there is no table."""
    target = Path(path) if path is not None else DEFAULT_PATH
    if not target.is_file():
        return TableState()
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return TableState()
    if not isinstance(data, dict):
        return TableState()
    return TableState(
        scene=str(data.get("scene") or ""),
        turn=str(data.get("turn") or ""),
        mode=str(data.get("mode") or "ooc"),
    )
