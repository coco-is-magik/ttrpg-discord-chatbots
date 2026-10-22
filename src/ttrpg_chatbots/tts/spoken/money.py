"""Money: the case that proves the pipeline needs an order.

``$250`` read literally is "dollar sign two hundred fifty" -- which is exactly what was heard in the
channel, and the reason this module runs *before* symbols.py and numbers.py. A currency symbol and the
digits after it are one idea, so they have to be claimed together.
"""

from __future__ import annotations

import re

from ttrpg_chatbots.tts.spoken.tables import CURRENCY

SYMBOLS = "".join(re.escape(symbol) for symbol in CURRENCY)

#: Symbol, an amount with optional thousands separators and cents.
MONEY = re.compile(rf"([{SYMBOLS}])\s?(\d{{1,3}}(?:,\d{{3}})*(?:\.\d{{1,2}})?)")


def _amount(raw: str) -> tuple[int, int]:
    whole, _, cents = raw.partition(".")
    return int(whole.replace(",", "")), int(cents.ljust(2, "0")) if cents else 0


def _expand(match: re.Match[str]) -> str:
    symbol, raw = match.group(1), match.group(2)
    major_singular, major_plural, minor_singular, minor_plural = CURRENCY[symbol]
    whole, cents = _amount(raw)

    from ttrpg_chatbots.tts.spoken.numbers import words

    parts = []
    if whole or not cents:
        parts.append(f"{words(whole)} {major_singular if whole == 1 else major_plural}")
    if cents:
        name = minor_singular if cents == 1 else minor_plural
        parts.append(f"{words(cents)} {name}" if name else words(cents))
    return " and ".join(parts)


def expand(text: str) -> str:
    """Say every amount of money in the text."""
    return MONEY.sub(_expand, text)
