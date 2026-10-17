"""Minimal JSONL reading shared by every dataset loader.

One record per line; blank lines and ``#`` comments are skipped so hand-edited data
stays readable. Errors carry ``path:line`` so a bad row is findable, and the reader
does not know what the records mean -- each loader owns its own validation.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any


class JsonlError(ValueError):
    """Raised when a JSONL file cannot be read or parsed."""


def read_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise JsonlError(f"cannot read {path}: {error}") from error
    for number, line in enumerate(lines, start=1):
        text = line.strip()
        if not text or text.startswith("#"):
            continue
        try:
            record = json.loads(text)
        except ValueError as error:
            raise JsonlError(f"{path}:{number}: invalid JSON: {error}") from error
        if not isinstance(record, dict):
            raise JsonlError(f"{path}:{number}: expected a JSON object")
        yield record
