"""Standalone symbols: the punctuation that is a word when it is spoken.

Runs *after* money.py, so a currency symbol has already been claimed. Runs *before* numbers.py, so
``10%`` becomes ``10 percent`` and is then read as "ten percent" rather than the other way round.

A symbol is replaced when it is not part of a word: ``10%`` and ``20°C`` are symbols glued to a
number, while ``and/or`` is a slash inside a word and must be left alone. Replacements carry a space
on each side because ``10%`` has to become two tokens for the number pass to see the ``10``; the
pipeline collapses the whitespace again at the end.
"""

from __future__ import annotations

import re

from ttrpg_chatbots.tts.spoken.tables import SYMBOLS

#: Multi-character units read as words. Handled before the single symbols so a degree sign does not
#: become "degrees C".
UNITS: dict[str, str] = {"°C": "degrees Celsius", "°F": "degrees Fahrenheit"}


def _pattern(symbol: str) -> re.Pattern[str]:
    """A symbol that is not part of a word.

    ``(?<![A-Za-z])`` and ``(?![A-Za-z])`` rather than whitespace on both sides. Both are fixed-width,
    which matters: Python rejects a variable-width look-behind, and an earlier attempt to use one did
    not compile.
    """
    return re.compile(rf"(?<![A-Za-z]){re.escape(symbol)}(?![A-Za-z])")


PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(rf"(?<![A-Za-z]){re.escape(unit)}"), spoken) for unit, spoken in UNITS.items()
) + tuple((_pattern(symbol), spoken) for symbol, spoken in SYMBOLS.items())


def _hash_number(match: re.Match[str]) -> str:
    return f" number {match.group(1)} "


def _ratio(match: re.Match[str]) -> str:
    """``50/50`` is "fifty fifty": the slash between two numbers is a ratio, not a slash."""
    return f" {match.group(1)} {match.group(2)} "


def expand(text: str) -> str:
    """Say every standalone symbol in the text."""
    # "#1" is "number one", not "hash one": the hash is a label, not a symbol.
    text = re.sub(r"#\s?(\d+)", _hash_number, text)
    text = re.sub(r"(?<![\w/])(\d+)/(\d+)(?![\w/])", _ratio, text)
    for pattern, spoken in PATTERNS:
        text = pattern.sub(f" {spoken} ", text)
    return text
