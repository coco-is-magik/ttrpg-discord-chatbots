"""Characters on disk: one JSON file each, written atomically.

A directory of files rather than one big blob, because characters are edited one at a
time and a diff of a single character should be readable. Writes go through a temporary
file and ``os.replace``, so an interrupted save cannot leave half a character behind.

The directory is normally git-ignored (it is personal data), which is why nothing here
assumes it exists.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path

from ttrpg_chatbots.character.types import Character, CharacterConflict, CharacterError
from ttrpg_chatbots.sheets.types import identifier, normalise

DEFAULT_ROOT = Path("data") / "characters"
SUFFIX = ".json"

def slug_for(name: str) -> str:
    """A filename stem, using the same rule as :func:`sheets.types.identifier`."""
    slug = identifier(name or "")
    if slug == "unnamed":  # punctuation only: there is no filename to make
        raise CharacterError(f"cannot make a filename from {name!r}")
    return slug


class CharacterStore:
    """Loads and saves characters under one directory."""

    def __init__(self, root: Path | str = DEFAULT_ROOT) -> None:
        self._root = Path(root)

    @property
    def root(self) -> Path:
        return self._root

    def path(self, identifier: str) -> Path:
        return self._root / f"{slug_for(identifier)}{SUFFIX}"

    def exists(self, identifier: str) -> bool:
        return self.path(identifier).is_file()

    def ids(self) -> tuple[str, ...]:
        """Every character in the directory.

        A character file is recognised by carrying ``schema_version``. Anything else in
        the directory -- a questionnaire, a stray export, an editor backup -- is ignored,
        so a shared directory cannot break listing. A file that *is* a character but has
        an unreadable version still raises when loaded explicitly.
        """
        if not self._root.is_dir():
            return ()
        found = []
        for path in sorted(self._root.glob(f"*{SUFFIX}")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if isinstance(data, dict) and "schema_version" in data:
                found.append(path.stem)
        return tuple(found)

    def load(self, identifier: str) -> Character:
        path = self.path(identifier)
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError as error:
            known = ", ".join(self.ids()) or "none"
            raise CharacterError(
                f"no character {identifier!r} in {self._root}; known: {known}"
            ) from error
        except OSError as error:
            raise CharacterError(f"cannot read {path}: {error}") from error
        return Character.from_json(text)

    def all(self) -> tuple[Character, ...]:
        characters = []
        for identifier in self.ids():
            characters.append(self.load(identifier))
        return tuple(characters)

    def save(self, character: Character, *, expect_revision: int | None = None) -> Path:
        """Write a character, optionally only if it is still at ``expect_revision``.

        Passing ``expect_revision`` makes the write a compare-and-swap: if another surface
        wrote first, this raises :class:`CharacterConflict` and nothing is touched. Callers
        that are deliberately overwriting (an import, a repair) omit it.
        """
        path = self.path(character.id)
        existing = None
        if path.is_file():
            existing = self.load(character.id)

        if expect_revision is not None:
            if existing is None:
                raise CharacterConflict(
                    f"{character.name!r} is no longer at {path}; it may have been deleted"
                )
            if existing.revision != expect_revision:
                raise CharacterConflict(
                    f"{character.name!r} changed while this view was open: expected "
                    f"revision {expect_revision}, found {existing.revision}. Reload and retry."
                )

        if existing is not None and existing.name != character.name:
            raise CharacterError(
                f"refusing to overwrite {path.name}: it holds {existing.name!r}, "
                f"not {character.name!r}"
            )
        path.parent.mkdir(parents=True, exist_ok=True)
        handle, temporary = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=SUFFIX)
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                stream.write(character.to_json())
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        except OSError as error:
            Path(temporary).unlink(missing_ok=True)
            raise CharacterError(f"cannot save {path}: {error}") from error
        return path

    def delete(self, identifier: str) -> None:
        self.path(identifier).unlink(missing_ok=True)
