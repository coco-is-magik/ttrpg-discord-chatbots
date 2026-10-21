"""Which specific line?

The only reader of a phrasebook. A family is a *kind* of phrasing; a variant is one sentence in it.
Recent use is avoided, but not for ever: when every variant has been said, the least recently used
one comes back. Repetition is what familiarity sounds like.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


class PhrasebookError(RuntimeError):
    """Raised when a phrasebook cannot be read."""


@dataclass(frozen=True)
class Family:
    """One kind of phrasing, with the conditions it is chosen under."""

    name: str
    when: Mapping[str, Any]
    variants: tuple[str, ...]


@dataclass(frozen=True)
class Phrasebook:
    """A job's worth of phrasings."""

    job: str
    families: Mapping[str, Family]

    def variants(self, family: str) -> tuple[str, ...]:
        chosen = self.families.get(family)
        # No fallback to another family: borrowing a warm line for a dry moment is how a bot ends
        # up saying "there he is" to a stranger six seconds after meeting them.
        return chosen.variants if chosen is not None else ()


def load(path: Path | str) -> Phrasebook:
    """Read ``phrasebooks/<job>.json``."""
    target = Path(path)
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise PhrasebookError(f"cannot read {target}: {error}") from error
    families: dict[str, Family] = {}
    for name, record in (data.get("families") or {}).items():
        variants = tuple(str(item).strip() for item in record.get("variants") or () if str(item).strip())
        if not variants:
            raise PhrasebookError(f"{target}: family {name!r} has no variants")
        families[name] = Family(name=name, when=record.get("when") or {}, variants=variants)
    if not families:
        raise PhrasebookError(f"{target}: no families")
    return Phrasebook(job=str(data.get("job") or target.stem), families=families)


def choose(
    *,
    book: Phrasebook,
    family: str,
    recent: tuple[str, ...] = (),
    budget=None,
) -> str | None:
    """The best variant for this family: unused if possible, least recently used if not.

    A variant that cannot fit the budget is not a candidate. Without this the longest line in a
    family makes the whole stage go silent -- measured: 20 of 144 greetings were dropped as
    "over budget" because one warm variant was six words and the mirror was three.
    """
    variants = book.variants(family)
    if budget is not None:
        variants = tuple(item for item in variants if budget.fits(item))
    if not variants:
        return None
    said = {item.strip().lower() for item in recent}
    fresh = [item for item in variants if item.lower() not in said]
    if fresh:
        return fresh[0]
    return variants[0]
