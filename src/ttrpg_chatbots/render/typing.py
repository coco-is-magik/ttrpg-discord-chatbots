"""Apply the typing style.

One job, delegating to `reply.style`: lower case, dropped apostrophes, the odd transposition. Kept as
its own rung so the ladder can be read without knowing how that is implemented."""

from __future__ import annotations

from ttrpg_chatbots.reply.style import Style, apply_style


def apply(text: str, style: Style | None = None) -> str:
    """Type it the way this character types."""
    return apply_style(text, style)
