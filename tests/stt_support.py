"""Deterministic doubles for the STT selector tests.

Not a *test* module (no ``test_`` prefix) so pytest does not collect it. Engines
are driven by an injected clock instead of sleeping, which keeps the race tests
instant and reproducible.
"""

from __future__ import annotations

from typing import Sequence

from ttrpg_chatbots.stt.engines import EngineSpec


class FakeClock:
    """A clock that only moves when something asks it to."""

    def __init__(self, start: float = 0.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class FakeEngine:
    """Stand-in recognizer with scripted timings and scripted failures."""

    def __init__(
        self,
        name: str,
        clock: FakeClock,
        *,
        load_s: float = 0.10,
        call_s: float = 0.05,
        call_times: Sequence[float] | None = None,
        fail_load: bool = False,
        fail_transcribe: bool = False,
        text: str = "hello world",
    ) -> None:
        self.name = name
        self._clock = clock
        self._load_s = load_s
        self._call_s = call_s
        self._call_times = list(call_times or [])
        self._fail_load = fail_load
        self._fail_transcribe = fail_transcribe
        self._text = text
        self.loads = 0
        self.calls = 0
        self.closes = 0
        self.loaded = False

    def load(self) -> None:
        self.loads += 1
        self._clock.advance(self._load_s)
        if self._fail_load:
            raise RuntimeError(f"{self.name} cannot load")
        self.loaded = True

    def transcribe(self, clip) -> str:
        self.calls += 1
        self._clock.advance(self._call_times.pop(0) if self._call_times else self._call_s)
        if self._fail_transcribe:
            raise RuntimeError(f"{self.name} cannot transcribe")
        return self._text

    def close(self) -> None:
        self.closes += 1
        self.loaded = False


def engine_spec(
    engine: FakeEngine,
    *,
    module: str = "json",
    available: bool = True,
    detail: str = "ready",
) -> EngineSpec:
    """Wrap a fake engine in a spec whose availability check is controllable."""
    return EngineSpec(
        name=engine.name,
        distribution="fake-stt",
        module=module,
        summary="fake engine for tests",
        check=lambda: (available, detail),
        build=lambda: engine,
    )
