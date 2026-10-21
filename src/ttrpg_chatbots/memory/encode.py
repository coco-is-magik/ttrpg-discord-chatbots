"""Does this turn contain a fact worth keeping?

Patterns, not comprehension. Four kinds of thing people volunteer about themselves -- pets, work,
plans, and strong likes -- because those are what a friend brings up next time. Everything else is
left alone: a system that tries to remember everything remembers nothing.
"""

from __future__ import annotations

import re

from ttrpg_chatbots.memory.long import Fact

_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "pet.name",
        re.compile(
            r"\bmy (?:dog|cat|puppy|kitten|pup)\s+(?:is called|is named|called|named)?\s*([a-z][a-z'-]{1,20})\b"
            r"|\bmy (?:dog|cat|puppy|kitten|pup)'s name is\s+([a-z][a-z'-]{1,20})\b"
        ),
    ),
    ("job", re.compile(r"\bi work (?:at|in|for)\s+([a-z][\w &'-]{2,40})\b")),
    ("plan", re.compile(r"\bi(?:'m| am) (?:going|off|headed) to\s+([a-z][\w &'-]{2,40})\b")),
    ("like", re.compile(r"\bi (?:really )?(?:love|like|hate)\s+([a-z][\w &'-]{2,30})\b")),
)


def read(text: str, *, said_by: str = "them") -> tuple[Fact, ...]:
    """Facts this message volunteers, in the order they appear."""
    cleaned = " ".join((text or "").lower().split())
    found: list[Fact] = []
    for kind, pattern in _PATTERNS:
        for match in pattern.finditer(cleaned):
            value = next((group for group in match.groups() if group), "").strip(" .,!?")
            if not value or value in {"a", "the", "it", "that", "this"}:
                continue
            fact = Fact(key=f"{kind}", value=value, said_by=said_by)
            if all(existing.key != fact.key or existing.value != fact.value for existing in found):
                found.append(fact)
    return tuple(found)
