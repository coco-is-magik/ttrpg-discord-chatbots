"""The roller as a tool: a JSON Schema an LLM can call, and an executor.

The schema is provider-neutral JSON Schema in the OpenAI "function" shape;
:mod:`ttrpg_chatbots.llm.tools` converts it to each wire format.

The executor is deliberately suspicious. A model will send ``"3"`` as a string, ``2.5``
for a count, ``true``, or both a named check *and* an explicit pool. Each of those gets a
specific, readable error instead of an exception, because a tool that raises would end
the conversation instead of letting the model correct itself.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Mapping

from ttrpg_chatbots.dice.checks import Checkbook
from ttrpg_chatbots.dice.notation import parse_notation
from ttrpg_chatbots.dice.roller import Roller
from ttrpg_chatbots.dice.types import (
    DEFAULT_MODE,
    MAX_DICE,
    MAX_SIDES,
    MODES,
    CheckError,
    DiceError,
    NotationError,
    RollResult,
    RollSpec,
)

TOOL_NAME = "roll_dice"

_INTEGER_TEXT = re.compile(r"^[+-]?\d+$")


def tool_schema() -> dict[str, Any]:
    """A fresh copy each call, so a caller cannot mutate the shared definition."""
    return {
        "name": TOOL_NAME,
        "description": (
            "Roll dice for a character and report the result. Use `check` for a named "
            "check the world defines (for example 'stealth'), or `notation` for an "
            "explicit pool (for example '3d6' or '2d20+3'), or `count` with `sides`. "
            "Choose `mode` to say how the table reads the roll: 'sum' adds the dice, "
            "'list' shows them individually, 'hits' counts dice at or above `target`, "
            "and 'check' compares the total against `target` (success at or above it)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "character": {
                    "type": "string",
                    "description": "Who is rolling. Required unless the caller supplies one.",
                },
                "check": {
                    "type": "string",
                    "description": "A named check from the world dataset, e.g. 'stealth'.",
                },
                "notation": {
                    "type": "string",
                    "description": "Dice expression, e.g. '3d6', 'd20' or '2d20+3'.",
                },
                "count": {"type": "integer", "minimum": 1, "maximum": MAX_DICE},
                "sides": {"type": "integer", "minimum": 2, "maximum": MAX_SIDES},
                "modifier": {
                    "type": "integer",
                    "description": "Added to the total, after the dice.",
                },
                "mode": {
                    "type": "string",
                    "enum": list(MODES),
                    "description": "How to read the roll; defaults to the check's own mode.",
                },
                "target": {
                    "type": "integer",
                    "description": "Hit threshold for 'hits', difficulty for 'check'.",
                },
                "label": {
                    "type": "string",
                    "description": "What the roll is for, e.g. 'Stealth'.",
                },
            },
            # No JSON Schema "anyOf": some strict tool modes reject it, so the
            # requirement (one of check / notation / count+sides) is enforced by the
            # executor, where the error message can say what to fix.
            "required": ["character"],
        },
    }


@dataclass(frozen=True)
class ToolOutcome:
    """What a tool call produced: speech-ready text plus structured data."""

    text: str
    payload: Mapping[str, Any] = field(default_factory=dict)
    result: RollResult | None = None


class DiceTool:
    """Executes ``roll_dice`` calls for one roller and one world's checks."""

    name = TOOL_NAME

    def __init__(
        self,
        roller: Roller,
        checks: Checkbook | None = None,
        *,
        default_character: str = "",
    ) -> None:
        self._roller = roller
        self._checks = checks if checks is not None else Checkbook()
        self._default_character = (default_character or "").strip()

    @property
    def checks(self) -> Checkbook:
        return self._checks

    def schema(self) -> dict[str, Any]:
        return tool_schema()

    def run_json(self, arguments: str) -> ToolOutcome:
        """Execute a tool call whose arguments arrived as a JSON string."""
        text = (arguments or "").strip()
        if not text:
            raise DiceError("roll_dice needs arguments, and none were given")
        try:
            parsed = json.loads(text)
        except ValueError as error:
            raise DiceError(f"roll_dice arguments were not valid JSON: {error}") from error
        return self.run(parsed)

    def run(self, arguments: Mapping[str, Any]) -> ToolOutcome:
        """Execute one call; raises :class:`DiceError` for anything a caller can fix."""
        if not isinstance(arguments, Mapping):
            raise DiceError(
                f"roll_dice arguments must be an object, got {type(arguments).__name__}"
            )

        character = self._text(arguments, "character") or self._default_character
        if not character:
            raise DiceError("roll_dice needs a character: say who is rolling")

        spec = self._spec(arguments)
        result = self._roller.roll(spec, character=character)
        return ToolOutcome(text=result.render(), payload=result.as_dict(), result=result)

    # -- argument handling -------------------------------------------------

    def _spec(self, arguments: Mapping[str, Any]) -> RollSpec:
        check_name = self._text(arguments, "check")
        notation = self._text(arguments, "notation")
        count = self._integer(arguments, "count")
        sides = self._integer(arguments, "sides")
        modifier = self._integer(arguments, "modifier")
        mode = self._mode(arguments)
        target = self._integer(arguments, "target")
        label = self._text(arguments, "label")

        explicit_pool = notation is not None or count is not None or sides is not None
        if check_name and explicit_pool:
            raise DiceError(
                "roll_dice got both a named check and an explicit pool; give one or the other"
            )

        if check_name:
            check = self._checks.get(check_name)
            spec = check.with_overrides(mode=mode, target=target)
            if modifier is not None:
                spec = spec.replace(modifier=modifier)
            return spec.replace(label=label or check.name)

        if notation is not None:
            try:
                spec = parse_notation(notation, mode=mode or DEFAULT_MODE, target=target)
            except NotationError as error:
                raise DiceError(str(error)) from error
            return spec.replace(label=label or "")

        if count is None or sides is None:
            raise DiceError(
                "roll_dice needs a named check, a notation like 3d6, or both count and sides"
            )
        try:
            return RollSpec(
                count=count,
                sides=sides,
                modifier=modifier or 0,
                mode=mode or DEFAULT_MODE,
                target=target,
                label=label or "",
            )
        except ValueError as error:
            raise DiceError(str(error)) from error

    def _mode(self, arguments: Mapping[str, Any]) -> str | None:
        value = self._text(arguments, "mode")
        if value is None:
            return None
        mode = value.lower()
        if mode not in MODES:
            raise DiceError(f"unknown mode {value!r}; expected one of {MODES}")
        return mode

    def _text(self, arguments: Mapping[str, Any], key: str) -> str | None:
        if key not in arguments or arguments[key] is None:
            return None
        value = arguments[key]
        if not isinstance(value, str):
            raise DiceError(f"{key} must be a string, got {type(value).__name__}")
        return value.strip() or None

    def _integer(self, arguments: Mapping[str, Any], key: str) -> int | None:
        """Accept ``3``, ``3.0`` and ``"3"``; refuse everything that is not whole."""
        if key not in arguments or arguments[key] is None:
            return None
        value = arguments[key]
        if isinstance(value, bool):
            raise DiceError(f"{key} must be a whole number, got {value!r}")
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            if not value.is_integer():
                raise DiceError(f"{key} must be a whole number, got {value!r}")
            return int(value)
        if isinstance(value, str):
            text = value.strip()
            if _INTEGER_TEXT.match(text):
                return int(text)
            raise DiceError(f"{key} must be a whole number, got {value!r}")
        raise DiceError(f"{key} must be a whole number, got {type(value).__name__}")

