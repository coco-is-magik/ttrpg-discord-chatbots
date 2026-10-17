import json

import pytest

pytest.importorskip("numpy")

from ttrpg_chatbots.stt.fixture import synthetic_speech  # noqa: E402
from ttrpg_chatbots.stt.probe import (  # noqa: E402
    CACHE_VERSION,
    DEFAULT_REPEATS,
    Measurement,
    environment_fingerprint,
    fastest,
    measure,
    resolve_recognizer,
)
from ttrpg_chatbots.stt.recognizer import EngineUnavailable  # noqa: E402
from stt_support import FakeClock, FakeEngine, engine_spec  # noqa: E402

CLIP = synthetic_speech(2.0)


class TestMeasure:
    def test_times_steady_state_and_reports_load_separately(self) -> None:
        clock = FakeClock()
        engine = FakeEngine("alpha", clock, load_s=0.2, call_s=0.05)

        result = measure(engine, CLIP, repeats=3, clock=clock)

        assert result.ok and result.engine == "alpha"
        assert result.load_s == pytest.approx(0.2)
        assert result.median_s == pytest.approx(0.05)
        assert result.rtf == pytest.approx(0.05 / CLIP.duration_s)
        assert engine.calls == 4, "the warm-up call must not be timed"

    def test_median_survives_an_outlier(self) -> None:
        clock = FakeClock()
        engine = FakeEngine("alpha", clock, call_times=[0.5, 0.01, 0.09, 0.05])

        result = measure(engine, CLIP, repeats=3, clock=clock)

        assert result.median_s == pytest.approx(0.05)
        assert result.min_s == pytest.approx(0.01)
        assert result.max_s == pytest.approx(0.09)

    def test_a_load_failure_is_reported_not_raised(self) -> None:
        clock = FakeClock()
        result = measure(FakeEngine("alpha", clock, fail_load=True), CLIP, repeats=2, clock=clock)

        assert not result.ok
        assert result.median_s is None
        assert "alpha cannot load" in result.error

    def test_a_transcribe_failure_is_reported_not_raised(self) -> None:
        clock = FakeClock()
        engine = FakeEngine("alpha", clock, fail_transcribe=True)

        result = measure(engine, CLIP, repeats=2, clock=clock)

        assert not result.ok
        assert "alpha cannot transcribe" in result.error

    def test_rejects_zero_repeats(self) -> None:
        with pytest.raises(ValueError, match="repeats"):
            measure(FakeEngine("alpha", FakeClock()), CLIP, repeats=0)


class TestFastest:
    def test_picks_the_lowest_median(self) -> None:
        slow = Measurement("slow", True, 0.1, median_s=0.30)
        fast = Measurement("fast", True, 0.1, median_s=0.05)
        assert fastest([slow, fast]).engine == "fast"

    def test_ignores_failed_engines(self) -> None:
        dead = Measurement("dead", False, 0.0, error="boom")
        alive = Measurement("alive", True, 0.1, median_s=9.0)
        assert fastest([dead, alive]).engine == "alive"

    def test_equal_timings_break_deterministically(self) -> None:
        alpha = Measurement("alpha", True, 0.1, median_s=0.05)
        beta = Measurement("beta", True, 0.1, median_s=0.05)
        assert fastest([beta, alpha]).engine == "alpha", "declaration order must decide ties"

    def test_no_usable_engine_names_every_reason(self) -> None:
        dead = Measurement("dead", False, 0.0, error="boom")
        with pytest.raises(EngineUnavailable) as excinfo:
            fastest([dead])
        assert "dead: boom" in str(excinfo.value)


class TestResolve:
    @pytest.fixture(autouse=True)
    def _isolate(self, monkeypatch):
        monkeypatch.delenv("TTRPG_STT_ENGINE", raising=False)

    def _resolve(self, clock, tmp_path, specs, **kwargs):
        return resolve_recognizer(
            clock=clock,
            cache_path=tmp_path / "probe.json",
            specs=specs,
            seconds=2.0,
            **kwargs,
        )

    def test_forced_engine_skips_the_others_entirely(self, tmp_path) -> None:
        clock = FakeClock()
        fast = FakeEngine("fast", clock, call_s=0.01)
        slow = FakeEngine("slow", clock, call_s=0.5)

        resolution = self._resolve(
            clock, tmp_path, [engine_spec(fast), engine_spec(slow)], engine="slow", repeats=2
        )

        assert (resolution.engine, resolution.source) == ("slow", "forced")
        assert (fast.loads, fast.calls) == (0, 0), "the override must not probe"
        assert slow.calls == 3, "one warm-up plus two timed calls"

    def test_default_repeats_are_used_when_unspecified(self, tmp_path) -> None:
        clock = FakeClock()
        engine = FakeEngine("alpha", clock)

        self._resolve(clock, tmp_path, [engine_spec(engine)], engine="alpha")

        assert engine.calls == 1 + DEFAULT_REPEATS

    def test_unknown_forced_engine_lists_the_known_ones(self, tmp_path) -> None:
        clock = FakeClock()
        with pytest.raises(EngineUnavailable) as excinfo:
            self._resolve(clock, tmp_path, [engine_spec(FakeEngine("alpha", clock))], engine="nope")
        assert "alpha" in str(excinfo.value)
        assert "nope" in str(excinfo.value)

    def test_environment_can_force_an_engine(self, tmp_path, monkeypatch) -> None:
        clock = FakeClock()
        alpha = FakeEngine("alpha", clock, call_s=0.5)
        beta = FakeEngine("beta", clock, call_s=0.01)
        monkeypatch.setenv("TTRPG_STT_ENGINE", "alpha")

        resolution = self._resolve(
            clock, tmp_path, [engine_spec(alpha), engine_spec(beta)], repeats=1
        )

        assert (resolution.engine, resolution.source) == ("alpha", "env")
        assert beta.calls == 0

    def test_race_selects_the_fastest_and_frees_the_losers(self, tmp_path) -> None:
        clock = FakeClock()
        slow = FakeEngine("slow", clock, call_s=0.5)
        fast = FakeEngine("fast", clock, call_s=0.01)

        resolution = self._resolve(
            clock, tmp_path, [engine_spec(slow), engine_spec(fast)], repeats=2
        )

        assert (resolution.engine, resolution.source) == ("fast", "measured")
        assert slow.closes == 1, "a losing model must be released"
        assert fast.closes == 0 and fast.loaded is True
        assert [m.engine for m in resolution.measurements] == ["slow", "fast"]

    def test_unavailable_engine_is_reported_and_never_built(self, tmp_path) -> None:
        clock = FakeClock()
        missing = FakeEngine("missing", clock, fail_load=True)
        alive = FakeEngine("alive", clock)
        specs = [
            engine_spec(missing, module="definitely_not_a_real_module_xyz"),
            engine_spec(alive),
        ]

        resolution = self._resolve(clock, tmp_path, specs, repeats=1)

        assert resolution.engine == "alive"
        assert missing.loads == 0, "an unavailable engine must not even be constructed"
        reported = {m.engine: m for m in resolution.measurements}["missing"]
        assert reported.ok is False
        assert "not installed" in reported.error

    def test_no_usable_engine_raises_with_reasons(self, tmp_path) -> None:
        clock = FakeClock()
        dead = FakeEngine("dead", clock, fail_load=True)
        with pytest.raises(EngineUnavailable, match="dead"):
            self._resolve(clock, tmp_path, [engine_spec(dead)])

    def test_cache_avoids_a_second_race(self, tmp_path) -> None:
        clock = FakeClock()
        first = FakeEngine("first", clock, call_s=0.4)
        second = FakeEngine("second", clock, call_s=0.1)
        specs = [engine_spec(first), engine_spec(second)]

        raced = self._resolve(clock, tmp_path, specs, repeats=2)
        raced.recognizer.close()
        calls_after_race = first.calls + second.calls

        cached = self._resolve(clock, tmp_path, specs, repeats=2)

        assert (raced.engine, raced.source) == ("second", "measured")
        assert (cached.engine, cached.source) == ("second", "cache")
        assert first.calls + second.calls == calls_after_race, "a cache hit must not re-probe"
        assert cached.recognizer.loaded is True

    def test_refresh_forces_a_new_race(self, tmp_path) -> None:
        clock = FakeClock()
        engine = FakeEngine("alpha", clock)
        specs = [engine_spec(engine)]
        self._resolve(clock, tmp_path, specs, repeats=1)
        calls = engine.calls

        resolution = self._resolve(clock, tmp_path, specs, repeats=1, refresh=True)

        assert resolution.source == "measured"
        assert engine.calls > calls

    def test_a_changed_fingerprint_invalidates_the_cache(self, tmp_path) -> None:
        clock = FakeClock()
        engine = FakeEngine("alpha", clock)
        specs = [engine_spec(engine)]
        self._resolve(clock, tmp_path, specs, repeats=1)
        calls = engine.calls

        resolution = self._resolve(clock, tmp_path, specs, repeats=3)

        assert resolution.source == "measured"
        assert engine.calls > calls

    def test_a_corrupt_cache_is_ignored(self, tmp_path) -> None:
        (tmp_path / "probe.json").write_text("{not json", encoding="utf-8")
        clock = FakeClock()

        resolution = self._resolve(
            clock, tmp_path, [engine_spec(FakeEngine("alpha", clock))], repeats=1
        )

        assert resolution.source == "measured"

    def test_cache_pointing_at_a_now_missing_engine_falls_back(self, tmp_path) -> None:
        clock = FakeClock()
        alive = FakeEngine("alive", clock, call_s=0.1)
        specs = [engine_spec(alive)]
        expected = environment_fingerprint(synthetic_speech(2.0), repeats=2, specs=specs)
        (tmp_path / "probe.json").write_text(
            json.dumps(
                {
                    "cache_version": CACHE_VERSION,
                    "fingerprint": expected,
                    "winner": {"engine": "ghost", "ok": True, "load_s": 0.0, "median_s": 0.001},
                }
            ),
            encoding="utf-8",
        )

        resolution = self._resolve(clock, tmp_path, specs, repeats=2)

        assert (resolution.engine, resolution.source) == ("alive", "measured")

