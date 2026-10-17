"""Rolling dice, with the random source injectable.

Dice do not need a cryptographic generator; what they need is *reproducibility* when
something goes wrong. Pass ``random.Random(seed)`` to replay a session, or a stub with a
``randint`` method to pin results in a test.
"""

from __future__ import annotations

import random
from typing import Protocol

from ttrpg_chatbots.dice.types import (
    DEFAULT_MODE,
    MAX_DICE,
    MAX_SIDES,
    DiceError,
    RollResult,
    RollSpec,
)


class RandomSource(Protocol):
    """The one method a dice ``RNG`` needs. ``random.Random`` satisfies it."""

    def randint(self, a: int, b: int) -> int: ...


class Roller:
    """Turns a :class:`RollSpec` and a character into a :class:`RollResult`."""

    def __init__(
        self,
        rng: RandomSource | None = None,
        *,
        max_dice: int = MAX_DICE,
        max_sides: int = MAX_SIDES,
    ) -> None:
        if max_dice < 1:
            raise ValueError("max_dice must be at least 1")
        if max_sides < 2:
            raise ValueError("max_sides must be at least 2")
        self._rng = rng if rng is not None else random.Random()
        self._max_dice = max_dice
        self._max_sides = max_sides

    def roll(self, spec: RollSpec, *, character: str) -> RollResult:
        """Roll ``spec`` and attribute it to ``character``."""
        name = (character or "").strip()
        if not name:
            raise DiceError("a roll needs a character: say who is rolling")
        if spec.count > self._max_dice:
            raise DiceError(
                f"this roller allows at most {self._max_dice} dice, asked for {spec.count}"
            )
        if spec.sides > self._max_sides:
            raise DiceError(
                f"this roller allows at most {self._max_sides} sides, asked for d{spec.sides}"
            )
        dice = tuple(self._rng.randint(1, spec.sides) for _ in range(spec.count))
        return RollResult(spec=spec, character=name, dice=dice)

    def roll_dice(
        self,
        count: int,
        sides: int,
        *,
        character: str,
        modifier: int = 0,
        mode: str = DEFAULT_MODE,
        target: int | None = None,
        label: str = "",
    ) -> RollResult:
        """Convenience wrapper for callers that are not holding a :class:`RollSpec`."""
        spec = RollSpec(
            count=count,
            sides=sides,
            modifier=modifier,
            mode=mode,
            target=target,
            label=label,
        )
        return self.roll(spec, character=character)
