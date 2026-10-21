"""Which act plausibly follows which.

A greeting is followed by a greeting, an answer by thanks, thanks by "no problem". Those
are not rules of English; they are frequencies, and published dialogue-act corpora measure
them. This module holds the frequencies and answers one question about them: *is this act
believable as a reply to that act?*

Why a table rather than a model: the runtime must stay dependency-free and inspectable. A
:class:`TransitionModel` is a JSON file of integer counts, so a decision can be read off
the page, a diff, and a log line. The counts may be authored by hand or produced by
``reply/importers.py`` from a corpus; the model reports which, and never pretends to be
measured when it was not.

Smoothing is additive and shared across the whole act set, so an unobserved pair scores
below a pair that was seen once, instead of zero -- a table that has never seen a goodbye
after a question should say "unlikely", not "impossible".
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from ttrpg_chatbots.reply.types import ReplyError

SCHEMA_VERSION = 1
DEFAULT_SMOOTHING = 1.0


class TransitionError(ReplyError):
    """Raised when a transition table is malformed or cannot be read."""


class TransitionModel:
    """P(next act | previous act), from integer counts.

    An empty model is uniform, and a uniform model vetoes nothing -- which is exactly the
    right behaviour for "no table was supplied": context then changes nothing.
    """

    def __init__(
        self,
        counts: Mapping[str, Mapping[str, int]] | None = None,
        *,
        smoothing: float = DEFAULT_SMOOTHING,
        source: str = "authored",
    ) -> None:
        if smoothing < 0:
            raise ValueError("smoothing must not be negative")
        self._counts: dict[str, dict[str, int]] = {}
        for previous, row in (counts or {}).items():
            if not previous.strip():
                raise TransitionError("a transition row needs a non-blank act")
            if not isinstance(row, Mapping):
                raise TransitionError(f"transitions[{previous!r}] must be an object of counts")
            clean: dict[str, int] = {}
            for act, value in row.items():
                if not act.strip():
                    raise TransitionError(f"transitions[{previous!r}] has a blank act")
                if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                    raise TransitionError(
                        f"transitions[{previous!r}][{act!r}] must be a non-negative integer"
                    )
                if value:
                    clean[act] = value
            self._counts[previous] = clean
        self._smoothing = float(smoothing)
        self._source = source.strip() or "authored"
        seen: set[str] = set(self._counts)
        for row in self._counts.values():
            seen.update(row)
        self._acts: tuple[str, ...] = tuple(sorted(seen))

    @property
    def acts(self) -> tuple[str, ...]:
        """Every act the table mentions, in either column."""
        return self._acts

    @property
    def source(self) -> str:
        """Where the counts came from: ``authored``, ``switchboard``, ..."""
        return self._source

    @property
    def smoothing(self) -> float:
        return self._smoothing

    def __bool__(self) -> bool:
        return bool(self._counts)

    def count(self, act: str, previous: str) -> int:
        return self._counts.get(previous, {}).get(act, 0)

    def total(self, previous: str) -> int:
        return sum(self._counts.get(previous, {}).values())

    def probability(self, act: str, previous: str | None) -> float:
        """Smoothed ``P(act | previous)``; uniform when ``previous`` is unknown."""
        size = len(self._acts)
        if size == 0:
            return 1.0
        uniform = 1.0 / size
        if previous is None or previous not in self._counts:
            return uniform
        total = self.total(previous)
        denominator = total + self._smoothing * size
        if denominator <= 0:
            return uniform
        return (self.count(act, previous) + self._smoothing) / denominator

    def plausible(self, act: str, previous: str | None) -> bool:
        """True unless this transition was never observed at all.

        One rule, no thresholds: if the table has data for ``previous`` and nothing ever
        followed it with ``act``, the act is a poor reading of a message that landed there
        -- provided another reading *has* been observed. With no data, everything is
        plausible, so an empty or missing table changes nothing.
        """
        if not self._counts or previous is None or previous not in self._counts:
            return True
        return self.count(act, previous) > 0

    def rank(self, previous: str) -> tuple[tuple[str, float], ...]:
        """Every act, most likely after ``previous`` first, ties broken by name."""
        scored = [(act, self.probability(act, previous)) for act in self._acts]
        scored.sort(key=lambda pair: (-pair[1], pair[0]))
        return tuple(scored)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "source": self._source,
            "smoothing": self._smoothing,
            "counts": {previous: dict(row) for previous, row in sorted(self._counts.items())},
        }

    def dumps(self) -> str:
        return json.dumps(self.to_dict(), indent=2) + "\n"

    def save(self, path: Path | str) -> Path:
        """Write the table, reporting an unwritable path as a TransitionError."""
        target = Path(path)
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_suffix(target.suffix + ".tmp")
            temporary.write_text(self.dumps(), encoding="utf-8")
            temporary.replace(target)
        except OSError as error:
            raise TransitionError(f"cannot write {target}: {error}") from error
        return target

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> TransitionModel:
        if not isinstance(data, Mapping):
            raise TransitionError("a transition table must be an object")
        version = data.get("schema_version", SCHEMA_VERSION)
        if version != SCHEMA_VERSION:
            raise TransitionError(
                f"unsupported transition schema version {version!r}; this build reads "
                f"{SCHEMA_VERSION}"
            )
        counts = data.get("counts")
        if counts is None:
            raise TransitionError("a transition table needs a 'counts' object")
        if not isinstance(counts, Mapping):
            raise TransitionError("'counts' must be an object")
        smoothing = data.get("smoothing", DEFAULT_SMOOTHING)
        if isinstance(smoothing, bool) or not isinstance(smoothing, (int, float)):
            raise TransitionError("'smoothing' must be a number")
        source = data.get("source", "authored")
        if not isinstance(source, str) or not source.strip():
            raise TransitionError("'source' must be a non-blank string")
        return cls(
            counts,  # type: ignore[arg-type] - each row is validated by __init__
            smoothing=float(smoothing),
            source=source,
        )

    @classmethod
    def load(cls, path: Path | str) -> TransitionModel:
        target = Path(path)
        try:
            raw = target.read_text(encoding="utf-8")
        except OSError as error:
            raise TransitionError(f"cannot read {target}: {error}") from error
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as error:
            raise TransitionError(f"{target}: not valid JSON: {error}") from error
        try:
            return cls.from_dict(data)
        except TransitionError as error:
            raise TransitionError(f"{target}: {error}") from error

    @classmethod
    def from_file(cls, path: Path | str) -> TransitionModel | None:
        """Load a table, or ``None`` when there is no file. A broken file still raises."""
        target = Path(path)
        if not target.exists():
            return None
        return cls.load(target)


def counts_from_pairs(
    pairs: Iterable[tuple[str | None, str | None]],
) -> dict[str, dict[str, int]]:
    """Accumulate ``(previous, act)`` pairs into a counts table, dropping unlabelled ones."""
    counts: dict[str, dict[str, int]] = {}
    for previous, act in pairs:
        if not previous or not act:
            continue
        row = counts.setdefault(previous, {})
        row[act] = row.get(act, 0) + 1
    return counts
