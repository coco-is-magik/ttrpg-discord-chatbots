"""How a character types.

A template says what a character says; a style says how it looks when they type it. The
difference matters more than it sounds: perfectly punctuated, sentence-cased, apostrophe-complete
text reads like a press release no matter how good the writing is, and the fastest way to make a
friend sound like a person is to stop the renderer from tidying them up.

Three honest levers, all deterministic:

* **case** -- sentence case (the default), all lower, or left exactly as written.
* **apostrophes** -- dropped, but only where the result is not another word. "don't" becomes
  "dont"; "I'll" never becomes "ill" and "we'll" never becomes "well", because a style that
  invents ambiguity is a bug, not a voice.
* **typos** -- a small, fixed set of transpositions in very common words, at a low rate. Nothing
  else: a random letter drop in a noun reads as broken rather than human.

The same input always renders the same way, keyed on the text, so a replay is a replay and a test
can assert a specific line. Style never changes what is said, only how it is typed.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Mapping

CASES = ("sentence", "lower", "as-written")

# Dropped only where the un-apostrophised form is not a different word, so the voice never
# creates a misreading. Deliberately excludes I'll/I'd/we'll/he'll/she'll/we're/we've.
_DROPPABLE = frozenset(
    {
        "don't",
        "doesn't",
        "didn't",
        "isn't",
        "wasn't",
        "aren't",
        "weren't",
        "won't",
        "can't",
        "couldn't",
        "shouldn't",
        "wouldn't",
        "haven't",
        "hasn't",
        "hadn't",
        "you're",
        "you've",
        "you'd",
        "you'll",
        "they're",
        "they've",
        "that's",
        "there's",
        "what's",
        "here's",
        "who's",
        "let's",
        "i'm",
        "i've",
    }
)

# Fast-typing slips that read as human rather than broken: transpositions in words nobody
# misreads. Nothing here is a meme spelling.
_TYPOS: Mapping[str, str] = {
    "just": "jsut",
    "about": "abotu",
    "with": "wiht",
    "something": "soemthing",
    "because": "becuase",
}


@dataclass(frozen=True)
class Style:
    """How one character types. The default is "nobody has decided", i.e. tidy text."""

    case: str = "sentence"
    drop_apostrophes: bool = False
    strip_final_period: bool = False
    typo_rate: float = 0.0

    def __post_init__(self) -> None:
        if self.case not in CASES:
            raise ValueError(f"case must be one of {list(CASES)}, got {self.case!r}")
        if isinstance(self.typo_rate, bool) or not isinstance(self.typo_rate, (int, float)):
            raise ValueError("typo_rate must be a number")
        if not 0.0 <= float(self.typo_rate) <= 1.0:
            raise ValueError(f"typo_rate must be between 0 and 1, got {self.typo_rate}")

    def describe(self) -> str:
        bits = [self.case]
        if self.drop_apostrophes:
            bits.append("no apostrophes")
        if self.strip_final_period:
            bits.append("no full stop")
        if self.typo_rate:
            bits.append(f"{self.typo_rate:.0%} typos")
        return ", ".join(bits)

    @classmethod
    def from_record(cls, record: Mapping[str, object]) -> Style:
        """Read a ``style`` object from a persona, naming the field that is wrong."""
        if not isinstance(record, Mapping):
            raise ValueError("style must be an object")
        case = record.get("case", "sentence")
        if not isinstance(case, str):
            raise ValueError("style.case must be a string")
        flags = {}
        for key in ("drop_apostrophes", "strip_final_period"):
            value = record.get(key, False)
            if not isinstance(value, bool):
                raise ValueError(f"style.{key} must be true or false")
            flags[key] = value
        try:
            return cls(case=case, typo_rate=record.get("typo_rate", 0.0), **flags)
        except ValueError as error:
            raise ValueError(f"style: {error}") from error


DEFAULT_STYLE = Style()


def _digest(text: str) -> int:
    return int.from_bytes(hashlib.blake2b(text.encode("utf-8"), digest_size=8).digest(), "big")


def _lower_first(text: str) -> str:
    """Lower-case the opening letter unless the whole opening word is shouting."""
    first = text.split(None, 1)[0]
    if first.isupper():  # "HAH" and "NO" keep their volume
        return text
    return text[:1].lower() + text[1:]


def _drop_apostrophes(text: str) -> str:
    """Remove apostrophes only where the result is not another word."""
    out: list[str] = []
    for token in text.split(" "):
        bare = token.strip(".,!?;:").lower()
        if "'" in token and bare in _DROPPABLE:
            out.append(token.replace("'", "", 1))
        else:
            out.append(token)
    return " ".join(out)


def _introduce_typo(text: str) -> str:
    """Swap two letters in the first eligible word, or leave the text alone."""
    for word, typo in _TYPOS.items():
        if word in text:
            return text.replace(word, typo, 1)
    return text


def apply_style(text: str, style: Style | None = None) -> str:
    """Render one line in a character's typing style. Deterministic for a given text."""
    active = style if style is not None else DEFAULT_STYLE
    result = text.strip()
    if not result:
        return result
    if active.strip_final_period and result.endswith(".") and not result.endswith(".."):
        result = result[:-1].rstrip()
    if active.drop_apostrophes:
        result = _drop_apostrophes(result)
    if active.typo_rate:
        # One slip per line at most, and only on a line that drew the short straw. Keyed on the
        # text, so the same sentence always gets the same treatment.
        if _digest(result) % 10_000 < int(active.typo_rate * 10_000):
            result = _introduce_typo(result)
    if active.case == "lower":
        result = _lower_first(result)
    elif active.case == "sentence":
        result = result[:1].upper() + result[1:]
    return result
