"""The interface the selector and the bot program against."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ttrpg_chatbots.stt.types import AudioClip


class EngineUnavailable(RuntimeError):
    """Raised when no engine can run here, or a requested engine cannot."""


@runtime_checkable
class SpeechRecognizer(Protocol):
    """A speech-to-text engine.

    ``load`` is allowed to be slow (model weights, first-run download) and is
    reported separately; ``transcribe`` is the hot path the startup race measures.
    """

    name: str

    def load(self) -> None:
        """Make the engine ready for ``transcribe`` calls."""

    def transcribe(self, clip: AudioClip) -> str:
        """Return the text for one utterance."""

    def close(self) -> None:
        """Release model memory."""
