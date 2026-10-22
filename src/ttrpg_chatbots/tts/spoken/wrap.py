"""A synthesizer that speaks the spoken form.

Wrapping rather than editing every engine, because there are three ways to reach an engine (the cast,
``resolve_synthesizer`` and a direct build) and only one of them is likely to be remembered. With the
wrap applied where engines are *built*, no caller can forget the step, and a test asserts the wrapping
happens.
"""

from __future__ import annotations

from typing import Any

from ttrpg_chatbots.audio.pcm import PcmAudio
from ttrpg_chatbots.tts.spoken.pipeline import say


class SpokenSynthesizer:
    """Turns text into the spoken form, then hands it to the engine."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.name = getattr(inner, "name", "spoken")

    def load(self) -> None:
        self._inner.load()

    def synthesize(self, text: str) -> PcmAudio:
        return self._inner.synthesize(say(text))

    def close(self) -> None:
        self._inner.close()

    @property
    def inner(self) -> Any:
        """The engine underneath, for inspection and tests."""
        return self._inner

    def __getattr__(self, item: str) -> Any:
        # Anything engine-specific (a voice name, a length scale) still reaches the engine.
        return getattr(self._inner, item)


def wrap(synthesizer: Any) -> SpokenSynthesizer:
    """Idempotent: wrapping twice is a mistake, not a double conversion."""
    if isinstance(synthesizer, SpokenSynthesizer):
        return synthesizer
    return SpokenSynthesizer(synthesizer)


def unwrap(synthesizer: Any) -> Any:
    """The engine underneath a wrapper, or the synthesizer itself if it is not wrapped."""
    return synthesizer.inner if isinstance(synthesizer, SpokenSynthesizer) else synthesizer
