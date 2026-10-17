"""How the creation flow asks questions, without knowing who is listening.

The wizard is pure: it asks a :class:`Prompter` and never touches stdin, a socket or a
Discord interaction. The terminal implementation lives in the CLI; a Discord one is a
separate interface module that implements the same two methods. That is the whole reason
this module exists -- the flow has exactly one job, and so does each interface.
"""

from __future__ import annotations

from typing import Protocol


class PrompterError(RuntimeError):
    """Raised when a prompt cannot get a usable answer, or the user gives up."""


class Prompter(Protocol):
    """Everything a wizard needs from a human."""

    def ask(self, prompt: str) -> str:
        """Ask a question and return the raw reply."""

    def say(self, text: str) -> None:
        """Offer context, a section heading, or a validation complaint."""


def ask_text(prompter: Prompter, prompt: str, *, attempts: int = 3) -> str:
    """Ask until a non-blank answer arrives."""
    for _ in range(attempts):
        answer = " ".join(prompter.ask(prompt).split())
        if answer:
            return answer
        prompter.say("  a blank answer is not useful here")
    raise PrompterError(f"no answer given for {prompt!r}")


def ask_int(
    prompter: Prompter,
    prompt: str,
    *,
    default: int | None = None,
    low: int = 0,
    high: int = 10,
    attempts: int = 3,
) -> int:
    """Ask for a whole number within ``low..high``, re-asking on nonsense."""
    for _ in range(attempts):
        raw = prompter.ask(prompt).strip()
        if not raw and default is not None:
            return default
        try:
            value = int(raw)
        except ValueError:
            prompter.say(f"  {raw!r} is not a whole number")
            continue
        if not low <= value <= high:
            prompter.say(f"  {value} is out of range ({low}..{high})")
            continue
        return value
    raise PrompterError(f"too many unusable answers for {prompt!r}")


def ask_optional_text(prompter: Prompter, prompt: str) -> str:
    """Ask for free text; a blank answer means "none"."""
    return " ".join(prompter.ask(prompt).split())
