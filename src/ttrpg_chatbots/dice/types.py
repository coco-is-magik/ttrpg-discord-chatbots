"""Value types for dice rolls.

Deliberately game-neutral: a die is a number of sides, a pool is a number of dice, and
an *output mode* decides what the table wants highlighted -- the individual results, the
sum, a count of hits, or a total compared against a difficulty. Nothing here assumes a
d20, a d10 pool or a d6-total system; the caller supplies the shape.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Mapping

# A pool of 1000 dice is still instant and keeps a hostile prompt from allocating.
MAX_DICE = 1000
MAX_SIDES = 1000
MAX_MODIFIER = 100_000
# Display truncation only; the data always holds every die.
MAX_DISPLAYED_DICE = 12

MODE_LIST = "list"
MODE_SUM = "sum"
MODE_HITS = "hits"
MODE_CHECK = "check"
MODES = (MODE_LIST, MODE_SUM, MODE_HITS, MODE_CHECK)

DEFAULT_MODE = MODE_SUM
# Modes that are meaningless without a target.
TARGET_MODES = frozenset({MODE_HITS, MODE_CHECK})


class DiceError(RuntimeError):
    """Base class for dice failures."""


class NotationError(DiceError, ValueError):
    """Raised when a dice expression cannot be parsed."""


class CheckError(DiceError, ValueError):
    """Raised when a named check is unknown or its record is malformed."""


def notation_of(count: int, sides: int, modifier: int = 0) -> str:
    """``3, 6, 2`` -> ``3d6+2``."""
    base = f"{count}d{sides}"
    if modifier > 0:
        return f"{base}+{modifier}"
    if modifier < 0:
        return f"{base}{modifier}"
    return base


@dataclass(frozen=True)
class RollSpec:
    """Exactly what to roll and how to read it.

    ``mode`` only affects how the result is presented; every mode still records the
    individual dice, the total and any target, so a caller can re-interpret a roll.
    """

    count: int
    sides: int
    modifier: int = 0
    mode: str = DEFAULT_MODE
    target: int | None = None
    label: str = ""

    def __post_init__(self) -> None:
        if isinstance(self.count, bool) or not isinstance(self.count, int):
            raise ValueError(f"dice count must be a whole number, got {self.count!r}")
        if not 1 <= self.count <= MAX_DICE:
            raise ValueError(f"dice count must be in 1..{MAX_DICE}, got {self.count}")
        if isinstance(self.sides, bool) or not isinstance(self.sides, int):
            raise ValueError(f"sides must be a whole number, got {self.sides!r}")
        if not 2 <= self.sides <= MAX_SIDES:
            raise ValueError(f"sides must be in 2..{MAX_SIDES}, got {self.sides}")
        if isinstance(self.modifier, bool) or not isinstance(self.modifier, int):
            raise ValueError(f"modifier must be a whole number, got {self.modifier!r}")
        if not -MAX_MODIFIER <= self.modifier <= MAX_MODIFIER:
            raise ValueError(f"modifier must be within +/-{MAX_MODIFIER}, got {self.modifier}")
        if self.mode not in MODES:
            raise ValueError(f"mode must be one of {MODES}, got {self.mode!r}")
        if self.mode in TARGET_MODES and self.target is None:
            raise ValueError(f"{self.mode} mode needs a target")
        if self.target is not None:
            if isinstance(self.target, bool) or not isinstance(self.target, int):
                raise ValueError(f"target must be a whole number, got {self.target!r}")
            if self.mode == MODE_HITS and not 1 <= self.target <= self.sides:
                raise ValueError(
                    f"a hit threshold must be in 1..{self.sides} for a d{self.sides}, "
                    f"got {self.target}"
                )
            if not -MAX_MODIFIER <= self.target <= MAX_MODIFIER:
                raise ValueError(f"target must be within +/-{MAX_MODIFIER}, got {self.target}")

    @property
    def notation(self) -> str:
        return notation_of(self.count, self.sides, self.modifier)

    def replace(self, **changes: Any) -> RollSpec:
        return replace(self, **changes)


@dataclass(frozen=True)
class RollResult:
    """One roll: who made it, what came up, and how to read it."""

    spec: RollSpec
    character: str
    dice: tuple[int, ...]
    meta: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.character.strip():
            raise ValueError("a roll needs a character to attribute it to")
        if len(self.dice) != self.spec.count:
            raise ValueError(f"expected {self.spec.count} dice, got {len(self.dice)}")
        for die in self.dice:
            if not 1 <= die <= self.spec.sides:
                raise ValueError(f"die {die} is outside 1..{self.spec.sides}")

    @property
    def total(self) -> int:
        return sum(self.dice) + self.spec.modifier

    @property
    def hits(self) -> int:
        """Dice at or above the hit threshold."""
        target = self.spec.target
        if target is None:
            return 0
        return sum(1 for die in self.dice if die >= target)

    @property
    def success(self) -> bool | None:
        """Meets-or-beats, the near-universal convention; ``None`` outside check mode."""
        if self.spec.mode != MODE_CHECK or self.spec.target is None:
            return None
        return self.total >= self.spec.target

    @property
    def margin(self) -> int | None:
        if self.spec.mode != MODE_CHECK or self.spec.target is None:
            return None
        return self.total - self.spec.target

    def as_dict(self) -> dict[str, Any]:
        """JSON-ready; everything a renderer or an LLM needs, nothing derived twice."""
        return {
            "character": self.character,
            "label": self.spec.label,
            "notation": self.spec.notation,
            "count": self.spec.count,
            "sides": self.spec.sides,
            "modifier": self.spec.modifier,
            "mode": self.spec.mode,
            "dice": list(self.dice),
            "total": self.total,
            "hits": self.hits if self.spec.mode == MODE_HITS else None,
            "target": self.spec.target,
            "success": self.success,
            "margin": self.margin,
        }

    def render(self) -> str:
        """One line a table -- or a speech engine -- can read out loud."""
        name = self.character
        label = f"{self.spec.label} " if self.spec.label else ""
        spec = self.spec

        if spec.mode == MODE_HITS:
            plural = "" if self.hits == 1 else "s"
            return (
                f"{name} rolls {label}{spec.notation} (hits on {spec.target}+): "
                f"{_shown(self.dice)} -> {self.hits} hit{plural}"
            )
        if spec.mode == MODE_CHECK:
            verdict = "success" if self.success else "failure"
            return (
                f"{name} rolls {label}{spec.notation}: {_sum_text(self)} = {self.total} "
                f"vs {spec.target} -> {verdict} (margin {self.margin:+d})"
            )
        if spec.mode == MODE_LIST:
            return f"{name} rolls {label}{spec.notation}: {_shown(self.dice)} -> total {self.total}"
        return f"{name} rolls {label}{spec.notation}: {_sum_text(self)} = {self.total}"


def _shown(dice: tuple[int, ...]) -> str:
    if len(dice) <= MAX_DISPLAYED_DICE:
        return "[" + ", ".join(str(die) for die in dice) + "]"
    head = ", ".join(str(die) for die in dice[:MAX_DISPLAYED_DICE])
    return f"[{head}, ... {len(dice) - MAX_DISPLAYED_DICE} more]"


def _sum_text(result: RollResult) -> str:
    parts = [str(die) for die in result.dice[:MAX_DISPLAYED_DICE]]
    if len(result.dice) > MAX_DISPLAYED_DICE:
        parts.append(f"... ({len(result.dice)} dice)")
    text = " + ".join(parts)
    modifier = result.spec.modifier
    if modifier:
        text = f"{text} {'+' if modifier > 0 else '-'} {abs(modifier)}"
    return text

