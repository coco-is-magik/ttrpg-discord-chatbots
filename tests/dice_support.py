"""Shared helpers for the dice tests."""

from __future__ import annotations

from pathlib import Path

from ttrpg_chatbots.dice.types import RollSpec

DEMO_WORLD = Path(__file__).resolve().parents[1] / "examples" / "demo_world"


class ScriptedRng:
    """Replays a fixed sequence and refuses to be asked for the wrong range."""

    def __init__(self, *values: int) -> None:
        self._values = list(values)
        self.calls: list[tuple[int, int]] = []

    def randint(self, a: int, b: int) -> int:
        self.calls.append((a, b))
        if not self._values:
            raise AssertionError("ScriptedRng ran out of values")
        value = self._values.pop(0)
        if not a <= value <= b:
            raise AssertionError(f"scripted value {value} is outside {a}..{b}")
        return value

    @property
    def remaining(self) -> int:
        return len(self._values)


def spec(count: int = 1, sides: int = 6, **kwargs) -> RollSpec:
    return RollSpec(count=count, sides=sides, **kwargs)
