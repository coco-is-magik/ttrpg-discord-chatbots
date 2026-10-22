"""Numbers as they are said, not as they are written.

One question: given a run of digits, what does a person say? Four kinds of answer, and they are
genuinely different rules:

* a **quantity** -- ``250`` -> ``two hundred fifty``
* a **year** -- ``1984`` -> ``nineteen eighty-four`` (a four-digit number in range is a year; nobody
  says "one thousand nine hundred eighty-four" in conversation)
* an **ordinal** -- ``21st`` -> ``twenty-first``
* a **clock time** -- ``3:30`` -> ``three thirty``, ``3pm`` -> ``three p m``

Currency is *not* here: money.py claims it first, because ``$1.50`` is "one dollar fifty" and not
"one point five zero dollars". That ordering is enforced in pipeline.py, and tested.
"""

from __future__ import annotations

import re

UNITS = (
    "zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
    "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen",
    "nineteen",
)
TENS = ("", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety")
SCALES = ((1_000_000_000, "billion"), (1_000_000, "million"), (1_000, "thousand"))

ORDINAL_IRREGULAR = {
    1: "first", 2: "second", 3: "third", 4: "fourth", 5: "fifth", 6: "sixth", 7: "seventh",
    8: "eighth", 9: "ninth", 10: "tenth", 11: "eleventh", 12: "twelfth",
}

#: A four-digit number in this range is read as a year.
YEAR_RANGE = range(1100, 2100)

DIGITS = re.compile(r"\d+")


def words(number: int) -> str:
    """A whole number in words, up to the billions. Negative gets "minus"."""
    if number < 0:
        return "minus " + words(-number)
    if number < 20:
        return UNITS[number]
    if number < 100:
        tens, unit = divmod(number, 10)
        return TENS[tens] + (f"-{UNITS[unit]}" if unit else "")
    if number < 1000:
        hundreds, rest = divmod(number, 100)
        head = f"{UNITS[hundreds]} hundred"
        return f"{head} {words(rest)}" if rest else head
    for scale, name in SCALES:
        if number >= scale:
            count, rest = divmod(number, scale)
            head = f"{words(count)} {name}"
            return f"{head} {words(rest)}" if rest else head
    return str(number)  # pragma: no cover - the scales cover everything up to 10^12


def year(number: int) -> str:
    """``1984`` -> ``nineteen eighty-four``. The 1900s-2000s exception: ``1905`` -> ``nineteen oh five``."""
    century, rest = divmod(number, 100)
    if rest == 0:
        return f"{words(century)} hundred"
    if rest < 10:
        return f"{words(century)} oh {words(rest)}"
    return f"{words(century)} {words(rest)}"


def ordinal(number: int) -> str:
    if number in ORDINAL_IRREGULAR:
        return ORDINAL_IRREGULAR[number]
    if number < 100:
        tens, unit = divmod(number, 10)
        return TENS[tens] if not unit else f"{TENS[tens]}-{ORDINAL_IRREGULAR[unit]}"
    head, rest = divmod(number, 100)
    if not rest:
        return f"{words(head)} hundredth"
    return f"{words(head)} hundred {ordinal(rest)}"


def _cardinal(match: re.Match[str]) -> str:
    raw = match.group(0)
    number = int(raw)
    if len(raw) == 4 and number in YEAR_RANGE:
        return year(number)
    return words(number)


def _ordinal_match(match: re.Match[str]) -> str:
    return ordinal(int(match.group(1)))


def _decimal_match(match: re.Match[str]) -> str:
    whole, fraction = match.group(1), match.group(2)
    digits = " ".join(UNITS[int(digit)] for digit in fraction)
    return f"{words(int(whole))} point {digits}"


def _clock(hour: int, minute: str | None) -> str:
    """``3`` -> ``three``, ``3:30`` -> ``three thirty``, ``3:05`` -> ``three oh five``."""
    if minute is None or minute == "00":
        return words(hour) if minute is None else f"{words(hour)} o'clock"
    if minute.startswith("0"):
        return f"{words(hour)} oh {words(int(minute))}"
    return f"{words(hour)} {words(int(minute))}"


def _clock_match(match: re.Match[str]) -> str:
    return _clock(int(match.group(1)), match.group(2))


def _meridiem_match(match: re.Match[str]) -> str:
    """``3:30 pm`` -> ``three thirty p m``. The meridiem belongs to the time, not beside it."""
    meridiem = " ".join(match.group(3).lower().replace(".", "").strip())
    return f"{_clock(int(match.group(1)), match.group(2))} {meridiem}"


def _range_match(match: re.Match[str]) -> str:
    return f"{words(int(match.group(1)))} to {words(int(match.group(2)))}"


#: Ordered: the more specific shapes run before the bare-digits sweep.
PATTERNS: tuple[tuple[re.Pattern[str], object], ...] = (
    # The meridiem form runs first: in "3:30 pm" the pm belongs to the time, and a bare clock pattern
    # would consume the digits and leave "pm" orphaned (measured: "three thirty pm").
    (
        re.compile(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm|a\.m\.|p\.m\.)", re.IGNORECASE),
        _meridiem_match,
    ),
    (re.compile(r"\b(\d{1,2}):(\d{2})\b"), _clock_match),
    (re.compile(r"\b(\d+)(st|nd|rd|th)\b", re.IGNORECASE), _ordinal_match),
    (re.compile(r"\b(\d+)\.(\d+)\b"), _decimal_match),
    # Every comma group at once: "1,000,000" is one number, and matching a single group left
    # ",000" behind (measured: "one thousand,zero").
    (re.compile(r"\b\d{1,3}(?:,\d{3})+\b"), lambda m: words(int(m.group(0).replace(",", "")))),
    (re.compile(r"\b(\d+)\s*[-–]\s*(\d+)\b"), _range_match),
    (re.compile(r"\b\d+\b"), _cardinal),
)


def expand(text: str) -> str:
    """Say every number in the text."""
    for pattern, handler in PATTERNS:
        text = pattern.sub(handler, text)  # type: ignore[arg-type]
    return text
