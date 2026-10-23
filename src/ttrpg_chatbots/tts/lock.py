"""The voice lock: which model we chose, where it came from, and how to prove it is the same one.

A voice is data with a dependency attached: the casting rule names it, and the audio lives in a cache
that a rebuild, a new box or a cleared disk will not have. This module answers two questions and
nothing else.

* **Is the voice on disk the voice we chose?** Size and SHA-256, per file.
* **Can we get it again?** Sources in order, each verified against the same digests, so a mirror that
  serves something else is rejected rather than trusted.

The lock file is committed; the model is not (63 MB, and the cache is where piper expects it). That
split is the point: the repository records *what* the voice is, and a fresh clone can reproduce it.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen


class LockError(ValueError):
    """Raised when a lock file is malformed or cannot be satisfied."""


@dataclass(frozen=True)
class LockedFile:
    """One file of a voice: its name, its size, and its digests."""

    name: str
    bytes: int
    sha256: str
    md5: str = ""

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise LockError("a locked file needs a name")
        if self.bytes <= 0:
            raise LockError(f"{self.name}: bytes must be positive")
        if len(self.sha256) != 64:
            raise LockError(f"{self.name}: sha256 must be 64 hex characters")

    def matches(self, path: Path) -> bool:
        """True when the file on disk is byte-for-byte this file."""
        if not path.is_file() or path.stat().st_size != self.bytes:
            return False
        return digest(path) == self.sha256


@dataclass(frozen=True)
class VoiceLock:
    """A pinned voice: what it is, why, and where it can be fetched from."""

    voice: str
    engine: str
    files: tuple[LockedFile, ...]
    sources: tuple[str, ...]
    settings: dict[str, float] = field(default_factory=dict)
    provenance: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.voice.strip():
            raise LockError("a lock needs a voice name")
        if not self.files:
            raise LockError(f"{self.voice}: a lock needs at least one file")
        if not self.sources:
            raise LockError(f"{self.voice}: a lock needs at least one source, or it cannot be rebuilt")

    @property
    def missing(self) -> tuple[str, ...]:
        """File names the sources have no template for.

        A source URL contains ``{file}``; a lock whose sources cannot produce every file is a lock
        that would silently half-install a voice.
        """
        return tuple(
            item.name for item in self.files if not any("{file}" in url for url in self.sources)
        )

    def url_for(self, source: str, name: str) -> str:
        return source.replace("{file}", name)


@dataclass(frozen=True)
class VoiceLocks:
    """Every voice a world pins, keyed by voice name.

    Plural because a world has more than one friend: the first version held a single voice, so the
    second friend's startup check verified the *first* friend's model and reported it as his own.
    Measured in the log: `friend-b is Otto (... en_US-ryan-medium ...)` followed by
    `friend-b: voice en_US-joe-medium verified against its lock`.
    """

    locks: tuple[VoiceLock, ...] = ()

    def for_voice(self, name: str) -> VoiceLock | None:
        """The entry for this voice, or nothing. A missing entry is not an error here."""
        for lock in self.locks:
            if lock.voice == name:
                return lock
        return None

    def names(self) -> tuple[str, ...]:
        return tuple(lock.voice for lock in self.locks)

    def __bool__(self) -> bool:
        return bool(self.locks)

    def __len__(self) -> int:
        return len(self.locks)

    def __iter__(self):
        return iter(self.locks)


@dataclass
class LockReport:
    """The result of a verify or a fetch, in words a person can act on."""

    voice: str
    ok: bool = False
    fetched: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    def summary(self) -> str:
        if self.ok:
            state = "fetched " + ", ".join(self.fetched) if self.fetched else "verified"
            return f"{self.voice}: {state}"
        return f"{self.voice}: " + "; ".join(self.problems)


def digest(path: Path, *, algorithm: str = "sha256", chunk: int = 1 << 20) -> str:
    """Hash a file without loading it into memory (a voice is 60 MB)."""
    hasher = hashlib.new(algorithm)
    with path.open("rb") as handle:
        while block := handle.read(chunk):
            hasher.update(block)
    return hasher.hexdigest()


def load(path: Path | str) -> VoiceLocks:
    """Read a lock file, refusing anything that would not be reproducible.

    Two shapes are accepted: ``{"voices": [ ... ]}`` for a world with several friends, and a bare
    single-voice object, which is what the first lock file looked like. The old shape is kept
    working because a lock that stops loading is worse than one that loads oddly.
    """
    where = Path(path)
    if not where.is_file():
        raise LockError(f"no voice lock at {where}")
    try:
        record = json.loads(where.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise LockError(f"{where}: not valid JSON: {error}") from error
    if not isinstance(record, dict):
        raise LockError(f"{where}: the lock must be an object")

    entries = record.get("voices")
    if entries is not None:
        if not isinstance(entries, list) or not entries:
            raise LockError(f"{where}: 'voices' must be a non-empty list")
        locks = []
        for index, entry in enumerate(entries, start=1):
            if not isinstance(entry, dict):
                raise LockError(f"{where}: voices[{index}] must be an object")
            locks.append(_one(entry, f"{where}: voices[{index}]"))
        seen = [lock.voice for lock in locks]
        duplicates = {name for name in seen if seen.count(name) > 1}
        if duplicates:
            raise LockError(f"{where}: two entries for {', '.join(sorted(duplicates))}")
        return VoiceLocks(locks=tuple(locks))
    return VoiceLocks(locks=(_one(record, str(where)),))


def _one(record: dict[str, Any], where: str) -> VoiceLock:
    """Read one voice entry."""

    files = []
    raw_files = record.get("files")
    if not isinstance(raw_files, list) or not raw_files:
        raise LockError(f"{where}: 'files' must be a non-empty list")
    for entry in raw_files:
        if not isinstance(entry, dict):
            raise LockError(f"{where}: every file must be an object")
        try:
            files.append(
                LockedFile(
                    name=str(entry.get("name", "")),
                    bytes=int(entry.get("bytes", 0)),
                    sha256=str(entry.get("sha256", "")),
                    md5=str(entry.get("md5", "")),
                )
            )
        except (LockError, TypeError, ValueError) as error:
            raise LockError(f"{where}: {error}") from error

    sources = record.get("sources")
    if not isinstance(sources, list) or not all(isinstance(url, str) for url in sources):
        raise LockError(f"{where}: 'sources' must be a list of URLs")

    try:
        lock = VoiceLock(
            voice=str(record.get("voice", "")),
            engine=str(record.get("engine", "")),
            files=tuple(files),
            sources=tuple(sources),
            settings=dict(record.get("settings") or {}),
            provenance=dict(record.get("provenance") or {}),
        )
    except LockError as error:
        raise LockError(f"{where}: {error}") from error
    if lock.missing:
        raise LockError(
            f"{where}: no source contains {{file}}, so " + ", ".join(lock.missing) + " cannot be fetched"
        )
    return lock


def verify(lock: VoiceLock, directory: Path) -> LockReport:
    """Check every locked file in ``directory`` against its size and digest."""
    report = LockReport(voice=lock.voice)
    for item in lock.files:
        path = directory / item.name
        if not path.is_file():
            report.problems.append(f"{item.name} is missing")
        elif path.stat().st_size != item.bytes:
            report.problems.append(
                f"{item.name} is {path.stat().st_size} bytes, expected {item.bytes}"
            )
        elif digest(path) != item.sha256:
            report.problems.append(f"{item.name} is not the locked file (sha256 differs)")
    report.ok = not report.problems
    return report


def fetch(lock: VoiceLock, directory: Path, *, timeout: float = 120.0) -> LockReport:
    """Download what is missing or wrong, trying each source until one verifies.

    A source that serves the wrong bytes is not trusted: the file is checked against the lock's own
    digest before it is put in place, so a mirror cannot quietly change the voice.
    """
    report = LockReport(voice=lock.voice)
    directory.mkdir(parents=True, exist_ok=True)
    for item in lock.files:
        path = directory / item.name
        if item.matches(path):
            continue
        problems = []
        for source in lock.sources:
            url = lock.url_for(source, item.name)
            try:
                _download(url, path, timeout=timeout)
            except (URLError, OSError, ValueError) as error:
                problems.append(f"{url} failed: {error}")
                continue
            if item.matches(path):
                report.fetched.append(item.name)
                break
            problems.append(f"{url} served the wrong bytes")
            path.unlink(missing_ok=True)
        else:
            report.problems.append("; ".join(problems) or f"no source for {item.name}")
    report.ok = not report.problems
    return report


def _download(url: str, path: Path, *, timeout: float) -> None:
    """Fetch to a temporary file, then move it into place."""
    temporary = path.with_suffix(path.suffix + ".part")
    with urlopen(url, timeout=timeout) as response, temporary.open("wb") as handle:
        shutil.copyfileobj(response, handle, length=1 << 20)
    temporary.replace(path)
