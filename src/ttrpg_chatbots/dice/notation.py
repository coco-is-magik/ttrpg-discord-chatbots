"""Dice notation: the small expression language a player types.

Accepted: ``3d6``, ``d20``, ``2d20+3``, ``3d6 - 1`` -- any case, any spacing around the
operator. Rejected with a specific message: a missing side count, a zero pool, a
one-sided die (a coin is a d2), a double sign, and trailing junk.

Trailing junk matters: ``"roll 3d6 please"`` is *not* read as ``3d6`` here. Extracting an
expression out of a sentence is :mod:`ttrpg_chatbots.dice.intent`'s job, and keeping that
separate is what stops a stray number in a question from being rolled.
"""

from __future__ import annotations

import re

from ttrpg_chatbots.dice.types import DEFAULT_MODE, NotationError, RollSpec

NOTATION_RE = re.compile(
    r"^\s*(?P<count>\d{0,4})\s*[dD]\s*(?P<sides>\d{1,4})"
    r"(?:\s*(?P<sign>[+-])\s*(?P<modifier>\d{1,6}))?\s*$"
)

EXAMPLE = "something like 3d6, d20 or 2d20+3"


def parse_notation(
    text: str,
    *,
    mode: str = DEFAULT_MODE,
    target: int | None = None,
    label: str = "",
) -> RollSpec:
    """Parse ``NdS+M`` into a :class:`RollSpec`."""
    match = NOTATION_RE.match(text or "")
    if match is None:
        raise NotationError(f"not a dice expression: {text!r}; expected {EXAMPLE}")

    count = int(match["count"]) if match["count"] else 1
    sides = int(match["sides"])
    modifier = 0
    if match["sign"]:
        modifier = int(match["modifier"]) * (1 if match["sign"] == "+" else -1)
    try:
        return RollSpec(
            count=count,
            sides=sides,
            modifier=modifier,
            mode=mode,
            target=target,
            label=label,
        )
    except ValueError as error:
        raise NotationError(f"{text!r}: {error}") from error


def is_notation(text: str) -> bool:
    """Whether ``text`` is a complete dice expression."""
    try:
        parse_notation(text)
    except NotationError:
        return False
    return True
