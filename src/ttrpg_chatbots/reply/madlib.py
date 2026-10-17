"""Madlib rendering.

A template is plain text with ``{slot}`` placeholders; ``{{`` and ``}}`` are literal
braces. Rendering never returns a half-filled line: an unresolved slot raises
``MissingSlot`` so the caller can try another template rather than showing a user
``{subject}``. Slot values are whitespace-normalised and rejected if they contain
braces, so dataset content cannot inject placeholders into a rendered reply.
"""

from __future__ import annotations

import re
from typing import Mapping

_TOKEN = re.compile(r"\{\{|\}\}|\{([A-Za-z_][A-Za-z0-9_]*)\}")


class MissingSlot(LookupError):
    """Raised when a template needs a slot the caller could not fill."""


def slots_in(template: str) -> tuple[str, ...]:
    """Required slot names, in first-appearance order."""
    names: list[str] = []
    for match in _TOKEN.finditer(template):
        name = match.group(1)
        if name and name not in names:
            names.append(name)
    return tuple(names)


def _clean(value: object) -> str:
    text = " ".join(str(value).split())
    if "{" in text or "}" in text:
        raise ValueError(f"slot value must not contain braces: {value!r}")
    return text


def render(template: str, values: Mapping[str, str], *, strict: bool = True) -> str:
    """Substitute ``{slot}`` placeholders from ``values``.

    ``strict`` raises ``MissingSlot``; otherwise the placeholder is dropped.
    """

    def substitute(match: re.Match[str]) -> str:
        token = match.group(0)
        if token == "{{":
            return "{"
        if token == "}}":
            return "}"
        name = match.group(1)
        value = values.get(name)
        if value is None or not str(value).strip():
            if strict:
                raise MissingSlot(name)
            return ""
        return _clean(value)

    return " ".join(_TOKEN.sub(substitute, template).split())
