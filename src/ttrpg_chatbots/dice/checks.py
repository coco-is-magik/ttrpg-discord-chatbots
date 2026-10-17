"""Named checks: ``"roll stealth"`` resolved against a dataset.

A check is a named dice pool *plus how to read it*, so a table can say "roll stealth"
instead of "roll 1d20+5 against a 15". The records live in ``checks.jsonl`` beside the
world's other datasets, and a world without one simply has no named checks.

    {"id": "stealth", "label": "Stealth", "aliases": ["sneak"], "count": 1, "sides": 20,
     "modifier": 5, "mode": "check", "target": 15}

or the notation shorthand:

    {"id": "brawn", "notation": "3d6", "mode": "sum"}

Nothing here assumes a system: a d20 check, a d10 hit pool and a d6 total are all just
different fields.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from ttrpg_chatbots import jsonl
from ttrpg_chatbots.dice.notation import parse_notation
from ttrpg_chatbots.dice.types import (
    DEFAULT_MODE,
    MODES,
    TARGET_MODES,
    CheckError,
    NotationError,
    RollSpec,
)

CHECKS_FILE = "checks.jsonl"

_KNOWN_FIELDS = frozenset(
    {"id", "label", "aliases", "notation", "count", "sides", "modifier", "mode", "target"}
)


@dataclass(frozen=True)
class Check:
    """A named pool the table can ask for by name."""

    id: str
    spec: RollSpec
    label: str = ""
    aliases: frozenset[str] = frozenset()
    meta: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.id.strip():
            raise ValueError("check id must not be empty")

    @property
    def name(self) -> str:
        return self.label or self.id

    @property
    def keys(self) -> frozenset[str]:
        """Every lowercase name this check answers to."""
        return frozenset({self.id.lower(), self.name.lower(), *self.aliases})

    def with_overrides(self, *, mode: str | None = None, target: int | None = None) -> RollSpec:
        """The check's pool, read differently -- e.g. "roll stealth for hits"."""
        changes: dict[str, Any] = {}
        if mode is not None:
            changes["mode"] = mode
        if target is not None:
            changes["target"] = target
        return replace(self.spec, **changes) if changes else self.spec


class Checkbook:
    """The named checks a world offers; lookups are case-insensitive."""

    def __init__(self, checks: Iterable[Check] = ()) -> None:
        self._checks: dict[str, Check] = {}
        self._index: dict[str, str] = {}
        for check in checks:
            if check.id in self._checks:
                raise CheckError(f"duplicate check id {check.id!r}")
            self._checks[check.id] = check
            for key in check.keys:
                owner = self._index.get(key)
                if owner is not None and owner != check.id:
                    raise CheckError(
                        f"check name {key!r} is used by both {owner!r} and {check.id!r}"
                    )
                self._index[key] = check.id

    def __len__(self) -> int:
        return len(self._checks)

    def __iter__(self):
        return iter(self._checks.values())

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._checks))

    def get(self, name: str) -> Check:
        wanted = (name or "").strip().lower()
        identifier = self._index.get(wanted)
        if identifier is None:
            known = ", ".join(self.names) or "none defined"
            raise CheckError(f"unknown check {name!r}; known checks: {known}")
        return self._checks[identifier]

    def find(self, text: str) -> Check | None:
        """The check whose name appears in ``text``, the longest name winning.

        Longest-first matters: "sneak attack" must beat "sneak", and "climb" must beat
        "cli". Matching is on whole words, so "stealthy" does not match "stealth".
        """
        haystack = f" {(text or '').lower()} "
        for separator in (",", ".", "?", "!", ";"):
            haystack = haystack.replace(separator, " ")
        words = haystack.split()
        best: tuple[int, Check] | None = None
        for key, identifier in self._index.items():
            key_words = key.split()
            if not key_words or not _contains_run(words, key_words):
                continue
            if best is None or len(key) > best[0]:
                best = (len(key), self._checks[identifier])
        return best[1] if best is not None else None


def _contains_run(words: list[str], run: list[str]) -> bool:
    span = len(run)
    return any(words[start : start + span] == run for start in range(len(words) - span + 1))


def checks_from_records(
    records: Iterable[Mapping[str, Any]], *, source: str = "checks"
) -> tuple[Check, ...]:
    return tuple(
        _check_from_record(record, f"{source} record {index}")
        for index, record in enumerate(records, start=1)
    )


def _check_from_record(record: Mapping[str, Any], where: str) -> Check:
    identifier = record.get("id")
    if not isinstance(identifier, str) or not identifier.strip():
        raise CheckError(f"{where}: 'id' must be a non-empty string")
    identifier = identifier.strip()
    where = f"{where} ({identifier})"

    label = record.get("label", identifier)
    if not isinstance(label, str) or not label.strip():
        raise CheckError(f"{where}: 'label' must be a non-empty string")
    label = label.strip()

    aliases = record.get("aliases") or []
    if not isinstance(aliases, list) or any(
        not isinstance(alias, str) or not alias.strip() for alias in aliases
    ):
        raise CheckError(f"{where}: 'aliases' must be a list of non-blank strings")

    mode = record.get("mode", DEFAULT_MODE)
    if not isinstance(mode, str):
        raise CheckError(f"{where}: 'mode' must be a string")
    mode = mode.strip().lower()
    if mode not in MODES:
        raise CheckError(f"{where}: 'mode' must be one of {MODES}, got {mode!r}")

    target = _optional_int(record, "target", where)
    if mode in TARGET_MODES and target is None:
        raise CheckError(f"{where}: {mode} mode needs a 'target'")

    spec = _spec_from_record(record, where=where, mode=mode, target=target, label=label)
    return Check(
        id=identifier,
        spec=spec,
        label=label,
        aliases=frozenset(alias.strip().lower() for alias in aliases),
        meta={key: value for key, value in record.items() if key not in _KNOWN_FIELDS},
    )



def _spec_from_record(
    record: Mapping[str, Any], *, where: str, mode: str, target: int | None, label: str
) -> RollSpec:
    notation = record.get("notation")
    pool_fields = {"count", "sides", "modifier"} & set(record)
    if notation is not None:
        if pool_fields:
            listed = ", ".join(sorted(pool_fields))
            raise CheckError(f"{where}: give either 'notation' or {listed}, not both")
        if not isinstance(notation, str):
            raise CheckError(f"{where}: 'notation' must be a string")
        try:
            return parse_notation(notation, mode=mode, target=target, label=label)
        except NotationError as error:
            raise CheckError(f"{where}: {error}") from error

    count = _required_int(record, "count", where)
    sides = _required_int(record, "sides", where)
    modifier = _optional_int(record, "modifier", where) or 0
    try:
        return RollSpec(
            count=count, sides=sides, modifier=modifier, mode=mode, target=target, label=label
        )
    except ValueError as error:
        raise CheckError(f"{where}: {error}") from error


def _required_int(record: Mapping[str, Any], key: str, where: str) -> int:
    value = _optional_int(record, key, where)
    if value is None:
        raise CheckError(f"{where}: missing required '{key}'")
    return value


def _optional_int(record: Mapping[str, Any], key: str, where: str) -> int | None:
    value = record.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise CheckError(f"{where}: '{key}' must be a whole number, got {value!r}")
    return value


def load_checks(root: Path | str = Path(".")) -> Checkbook:
    """Load ``<root>/checks.jsonl``; a missing file means "no named checks"."""
    base = Path(root)
    path = base / CHECKS_FILE if base.is_dir() else base
    if not path.is_file():
        return Checkbook()
    try:
        records = list(jsonl.read_jsonl(path))
    except jsonl.JsonlError as error:
        raise CheckError(str(error)) from error
    return Checkbook(checks_from_records(records, source=str(path)))

