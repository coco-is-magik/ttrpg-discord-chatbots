"""Value types shared by every LLM backend.

A backend turns :class:`ChatMessage` objects into a :class:`Completion`; a *responder*
turns a plain prompt into an :class:`Answer`. Nothing here knows about HTTP, JSON or
which vendor is being talked to, so a new provider only has to produce a Completion.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

ROLES = ("system", "user", "assistant")


class LlmError(RuntimeError):
    """Base class for LLM failures.

    ``backend`` and ``status`` are carried beside the message so a caller can log
    *which* backend failed and *how* without parsing text. Messages are built from
    redacted input, so they are safe to log verbatim.
    """

    def __init__(
        self, message: str, *, backend: str | None = None, status: int | None = None
    ) -> None:
        super().__init__(message)
        self.backend = backend
        self.status = status


class LlmConfigError(LlmError):
    """Raised when the configuration is missing, contradictory or malformed."""


class LlmUnavailable(LlmError):
    """Raised when the backend cannot be reached at all (refused, DNS, timeout)."""


class LlmAuthError(LlmError):
    """Raised when the backend rejects the credentials, or none were supplied."""


class LlmRateLimited(LlmError):
    """Raised on HTTP 429: the key was accepted, the timing was not."""


class LlmRequestError(LlmError):
    """Raised when the backend rejects the request itself (bad model, empty prompt)."""


class LlmProtocolError(LlmError):
    """Raised when the backend answers, but the answer cannot be used."""


@dataclass(frozen=True)
class ChatMessage:
    """One turn of a conversation, in the shape every chat API expects."""

    role: str
    content: str

    def __post_init__(self) -> None:
        if self.role not in ROLES:
            raise ValueError(f"unknown message role {self.role!r}; expected one of {ROLES}")
        if not self.content.strip():
            raise ValueError(f"{self.role} message must not be empty")

    def as_dict(self) -> dict[str, str]:
        return {"role": self.role, "content": self.content}


@dataclass(frozen=True)
class Persona:
    """Everything the model needs to stay in character, without any dataset types.

    This is deliberately plain strings: a game world, a config file or a test can all
    build one, and the LLM layer never has to import the reply engine.
    """

    name: str
    role: str = ""
    traits: tuple[str, ...] = ()
    style: str = ""

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("persona name must not be empty")


@dataclass(frozen=True)
class Completion:
    """A backend's raw answer, with enough provenance to log where it came from."""

    text: str
    backend: str
    model: str
    truncated: bool = False
    usage: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.text.strip():
            raise ValueError("completion text must not be empty")
