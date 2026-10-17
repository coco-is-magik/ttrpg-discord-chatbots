"""Turning a chat message into a roll instruction.

This is the path for when *no* model is deciding: the classifier, a slash command, or
someone typing "roll stealth" into chat. It is a heuristic and is documented as one --
the LLM path uses real tool calling, where the model chooses.

Rules, applied in order:

1. a roll word must appear ("roll", "rolls", "rolling", "rolled");
2. a dice expression wins if present (``roll 3d6``);
3. otherwise a named check from the dataset (``roll stealth``);
4. ``for``/``as``/``by`` names the roller, matched against the world's characters when
   they are supplied, and heuristically otherwise.

Anything that does not look like an instruction returns ``None``, so the caller can fall
through to whatever answers normally.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from ttrpg_chatbots.dice.checks import Check, Checkbook
from ttrpg_chatbots.dice.types import DiceError, RollSpec

ROLL_WORD = re.compile(r"\b(?:roll|rolls|rolling|rolled)\b", re.IGNORECASE)

NOTATION_IN_TEXT = re.compile(
    r"(?<![\w.])(?P<count>\d{0,3})\s*[dD]\s*(?P<sides>\d{1,4})"
    r"(?:\s*(?P<sign>[+-])\s*(?P<modifier>\d{1,4}))?(?![\w])"
)

CHARACTER_IN_TEXT = re.compile(
    r"\b(?:for|as|by)\s+(?P<name>[\w'\u2019-]+(?:\s+[\w'\u2019-]+){0,3})",
    re.IGNORECASE,
)

# Trailing words that end a name rather than belong to it.
NAME_STOPWORDS = frozenset(
    {"please", "now", "then", "and", "with", "to", "against", "vs", "versus", "today"}
)


@dataclass(frozen=True)
class RollRequest:
    """A roll the message asked for, before it is attributed or executed."""

    spec: RollSpec
    character: str | None = None
    check: Check | None = None

    @property
    def label(self) -> str:
        return self.check.name if self.check is not None else self.spec.label


def parse_instruction(
    text: str,
    *,
    checks: Checkbook | None = None,
    characters: Mapping[str, str] | Sequence[str] | None = None,
) -> RollRequest | None:
    """Return the roll this message asks for, or ``None`` if it asks for none."""
    sentence = (text or "").strip()
    if not sentence or not ROLL_WORD.search(sentence):
        return None

    character = _character(sentence, characters)

    match = NOTATION_IN_TEXT.search(sentence)
    if match is not None:
        return RollRequest(spec=_spec_from_match(match), character=character)

    check = checks.find(sentence) if checks is not None else None
    if check is None:
        return None
    return RollRequest(spec=check.spec, character=character, check=check)


def _spec_from_match(match: re.Match[str]) -> RollSpec:
    count = int(match["count"]) if match["count"] else 1
    sides = int(match["sides"])
    modifier = 0
    if match["sign"]:
        modifier = int(match["modifier"]) * (1 if match["sign"] == "+" else -1)
    try:
        return RollSpec(count=count, sides=sides, modifier=modifier)
    except ValueError as error:
        raise DiceError(f"{match.group(0)!r}: {error}") from error


def _character(
    sentence: str,
    characters: Mapping[str, str] | Sequence[str] | None,
) -> str | None:
    index = _character_index(characters)
    lowered = sentence.lower()
    best: tuple[int, str] | None = None
    for alias, display in index.items():
        if _contains_phrase(lowered, alias) and (best is None or len(alias) > best[0]):
            best = (len(alias), display)
    if best is not None:
        return best[1]

    match = CHARACTER_IN_TEXT.search(sentence)
    if match is None:
        return None
    return _clean_name(match["name"])


def _character_index(characters: Mapping[str, str] | Sequence[str] | None) -> dict[str, str]:
    if not characters:
        return {}
    if isinstance(characters, Mapping):
        pairs = ((str(key), str(value)) for key, value in characters.items())
    else:
        pairs = ((str(name), str(name)) for name in characters)
    return {
        alias.strip().lower(): display.strip()
        for alias, display in pairs
        if alias.strip() and display.strip()
    }


def _contains_phrase(haystack: str, needle: str) -> bool:
    return re.search(rf"(?<!\w){re.escape(needle)}(?!\w)", haystack) is not None


def _clean_name(raw: str) -> str | None:
    words: list[str] = []
    for word in raw.split():
        if word.lower() in NAME_STOPWORDS:
            break
        words.append(word)
    name = " ".join(words).strip(" \t,.;:!?")
    return name or None


def describe_request(request: RollRequest) -> dict[str, Any]:
    """Log-safe summary of what was understood."""
    return {
        "notation": request.spec.notation,
        "mode": request.spec.mode,
        "target": request.spec.target,
        "check": request.check.id if request.check is not None else None,
        "character": request.character,
    }
