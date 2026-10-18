"""Structured roll requests: the parts a chat form collects, validated into a spec.

This is the *typed* way in, as opposed to :mod:`ttrpg_chatbots.dice.intent`, which parses
free text such as "roll 3d6 for Sable". A slash command should never round-trip through
English to reach the roller: the arguments are already structured, so they are validated
here and handed straight to :class:`~ttrpg_chatbots.dice.roller.Roller`.

Every rejection names the fix rather than the rule, because the caller is a person
half-watching a game, not a compiler.
"""

from __future__ import annotations

from dataclasses import dataclass

from ttrpg_chatbots.dice.checks import Checkbook
from ttrpg_chatbots.dice.notation import parse_notation
from ttrpg_chatbots.dice.roller import Roller
from ttrpg_chatbots.dice.types import (
    DEFAULT_MODE,
    MODES,
    TARGET_MODES,
    DiceError,
    NotationError,
    RollSpec,
)
from ttrpg_chatbots.respond import Answer

# What a bare "roll something" means. d20 because that is the most common single die;
# the reply says so, so nobody has to remember.
DEFAULT_COUNT = 1
DEFAULT_SIDES = 20


@dataclass(frozen=True)
class RollParts:
    """The options a roll form offers. ``None`` means "not given"."""

    count: int | None = None
    sides: int | None = None
    modifier: int | None = None
    mode: str | None = None
    target: int | None = None
    notation: str | None = None
    check: str | None = None
    character: str | None = None

    @property
    def empty(self) -> bool:
        """True when no *dice* option was supplied (a character alone does not count)."""
        return all(
            value is None
            for value in (
                self.count,
                self.sides,
                self.modifier,
                self.mode,
                self.target,
                self.notation,
                self.check,
            )
        )


def _has(value: int | None) -> bool:
    return value is not None


def _require_target(mode: str, target: int | None) -> None:
    """A target mode without a target is the most common miss; give the example."""
    if mode in TARGET_MODES and target is None:
        example = "target:8" if mode == "hits" else "target:15"
        raise DiceError(f"mode:{mode} needs a target, for example {example}")


def _require_target_mode(spec: RollSpec) -> RollSpec:
    """A target only means something for hits and check; say so rather than ignore it."""
    if spec.target is not None and spec.mode not in TARGET_MODES:
        raise DiceError(
            f"target is only used by {' and '.join(sorted(TARGET_MODES))}; "
            f"add mode:hits or mode:check (or drop target)"
        )
    return spec


def build_spec(
    parts: RollParts, *, checks: Checkbook | None = None
) -> tuple[RollSpec, str | None]:
    """Turn parts into a spec, plus an optional note to show the user.

    The note teaches the shorthand ("4d6-1 (sum)") so the notation becomes familiar by
    reading results, rather than by memorising a tooltip.
    """
    book = checks if checks is not None else Checkbook()
    mode = (parts.mode or "").strip().lower() or None
    if mode is not None and mode not in MODES:
        raise DiceError(f"mode must be one of {', '.join(MODES)}; got {mode!r}")

    if parts.check:
        if any(_has(value) for value in (parts.count, parts.sides, parts.modifier)) or (
            parts.notation
        ):
            raise DiceError(
                f"'{parts.check}' defines its own dice; drop count, sides, modifier or notation"
            )
        check = book.get(parts.check)  # raises CheckError naming the alternatives
        spec = check.with_overrides(mode=mode, target=parts.target)
        if parts.target is None and spec.mode not in TARGET_MODES and spec.target is not None:
            # The target came from the check's record, not the caller: reading a check as
            # a plain sum is legitimate, and the inherited difficulty is simply unused.
            spec = spec.replace(target=None)
        return _require_target_mode(spec), None

    if parts.notation:
        if any(_has(value) for value in (parts.count, parts.sides, parts.modifier)):
            raise DiceError("give either notation or count/sides/modifier, not both")
        resolved = mode or DEFAULT_MODE
        _require_target(resolved, parts.target)
        try:
            spec = parse_notation(parts.notation, mode=resolved, target=parts.target)
        except NotationError as error:
            raise DiceError(str(error)) from error
        except ValueError as error:
            raise DiceError(str(error)) from error
        return _require_target_mode(spec), None

    resolved = mode or DEFAULT_MODE
    _require_target(resolved, parts.target)
    try:
        spec = RollSpec(
            count=parts.count if parts.count is not None else DEFAULT_COUNT,
            sides=parts.sides if parts.sides is not None else DEFAULT_SIDES,
            modifier=parts.modifier if parts.modifier is not None else 0,
            mode=resolved,
            target=parts.target,
        )
    except ValueError as error:
        raise DiceError(str(error)) from error
    _require_target_mode(spec)

    if parts.empty:
        return spec, "no dice given, so this is a d20"
    return spec, _teach(spec)


def _teach(spec: RollSpec) -> str:
    """A short line showing the shorthand for what was just rolled."""
    if spec.mode == DEFAULT_MODE and spec.label == "":
        return f"`{spec.notation}`"
    return f"`{spec.notation}` ({spec.mode})"


def roll_parts(
    parts: RollParts,
    *,
    roller: Roller,
    checks: Checkbook | None = None,
    character: str = "",
) -> Answer:
    """Roll from structured parts and return a speakable answer."""
    name = (character or "").strip()
    if not name:
        raise DiceError("a roll needs a character; pass one, or set a default")

    spec, note = build_spec(parts, checks=checks)
    result = roller.roll(spec, character=name)
    detail: dict[str, object] = {
        "character": name,
        "roll": result.as_dict(),
        "check": parts.check.lower() if parts.check else None,
    }
    if note:
        detail["hint"] = note
    return Answer(text=result.render(), source="dice", detail=detail)
