"""The only module in the conversation layer that touches the disk.

Everything else passes plain data around, which is what makes the rest testable without a
filesystem. Writes are atomic (temp file then replace), because a half-written memory file after a
crash is worse than no memory file: it silently forgets who you are.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class StoreError(RuntimeError):
    """Raised when a store cannot be read or written."""


class Store:
    """A JSON document on disk, read and written whole."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)

    def read(self) -> dict[str, Any]:
        """The document, or an empty one when the file does not exist yet."""
        if not self.path.is_file():
            return {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise StoreError(f"cannot read {self.path}: {error}") from error
        if not isinstance(data, dict):
            raise StoreError(f"{self.path}: expected an object")
        return data

    def write(self, data: dict[str, Any]) -> None:
        """Replace the document atomically."""
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(self.path.suffix + ".tmp")
            temporary.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
            temporary.replace(self.path)
        except OSError as error:
            raise StoreError(f"cannot write {self.path}: {error}") from error
