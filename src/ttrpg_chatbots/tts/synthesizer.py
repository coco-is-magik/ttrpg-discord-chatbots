"""Text to speech: the interface, and nothing else.

Deliberately narrow so the classifier, an LLM, a scripted line or a test double can
all hand audio to the playback layer. Engines live in ``ttrpg_chatbots.tts.engines``
and are discovered at runtime, so a box with no TTS installed still imports this.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ttrpg_chatbots.audio.pcm import PcmAudio


class SynthesisError(RuntimeError):
    """Raised when text cannot be turned into audio."""


class SynthesizerUnavailable(SynthesisError):
    """Raised when no engine can run here, or a requested engine cannot."""


@runtime_checkable
class SpeechSynthesizer(Protocol):
    """Anything that can turn text into PCM audio."""

    name: str

    def load(self) -> None:
        """Make the engine ready; may download a voice or start a process."""

    def synthesize(self, text: str) -> PcmAudio:
        """Return the spoken audio. Empty text is a ``ValueError``."""

    def close(self) -> None:
        """Release model memory or processes."""


def clean_text(text: str) -> str:
    """Collapse whitespace and reject text with nothing to say."""
    cleaned = " ".join(text.split())
    if not cleaned:
        raise ValueError("text is empty")
    return cleaned
