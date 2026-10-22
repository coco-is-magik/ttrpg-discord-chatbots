import subprocess

import pytest

from ttrpg_chatbots.audio import encode_wav
from ttrpg_chatbots.tts import (
    SynthesisError,
    SynthesizerUnavailable,
    availability_report,
    engines,
    resolve_synthesizer,
)
from ttrpg_chatbots.tts.engines import EngineSpec, espeak_engine, piper_engine
from ttrpg_chatbots.tts.spoken import unwrap
from ttrpg_chatbots.tts.synthesizer import clean_text

from tts_support import FakeSynthesizer, fake_spec, tone


def test_registry_order_is_priority_not_speed() -> None:
    assert engines.names() == ("piper", "espeak-ng")


def test_missing_package_is_reported_as_unavailable() -> None:
    status = engines.availability(fake_spec("x", FakeSynthesizer(), module="no_such_module_xyz"))
    assert status.available is False
    assert "not installed" in status.detail


def test_a_binary_engine_has_no_module_to_check() -> None:
    status = engines.availability(
        fake_spec("cli", FakeSynthesizer(), module="", available=False, detail="binary missing")
    )
    assert status.available is False
    assert status.detail == "binary missing"


def test_a_broken_check_cannot_break_startup() -> None:
    broken = EngineSpec("x", "fake", "json", "summary", lambda: 1 / 0, FakeSynthesizer)
    status = engines.availability(broken)
    assert status.available is False
    assert "availability check failed" in status.detail


def test_unknown_engine_lists_the_choices() -> None:
    with pytest.raises(SynthesizerUnavailable, match="piper"):
        engines.build_engine("nope")


def test_availability_report_covers_every_engine() -> None:
    assert {row.name for row in availability_report()} == {"piper", "espeak-ng"}


class TestResolve:
    def test_forced_engine_loads_only_that_one(self) -> None:
        first, second = FakeSynthesizer(), FakeSynthesizer()
        specs = [fake_spec("first", first), fake_spec("second", second)]

        chosen = resolve_synthesizer("second", specs=specs)

        assert unwrap(chosen) is second
        assert (second.loads, first.loads) == (1, 0)

    def test_unknown_forced_engine_lists_the_choices(self) -> None:
        with pytest.raises(SynthesizerUnavailable, match="first"):
            resolve_synthesizer("nope", specs=[fake_spec("first", FakeSynthesizer())])

    def test_environment_can_force_an_engine(self, monkeypatch) -> None:
        first, second = FakeSynthesizer(), FakeSynthesizer()
        specs = [fake_spec("first", first), fake_spec("second", second)]
        monkeypatch.setenv("TTRPG_TTS_ENGINE", "second")

        assert unwrap(resolve_synthesizer(specs=specs)) is second

    def test_auto_picks_the_first_available_engine(self) -> None:
        unavailable, ready = FakeSynthesizer(), FakeSynthesizer()
        specs = [
            fake_spec("a", unavailable, available=False, detail="no voice"),
            fake_spec("b", ready),
        ]

        assert unwrap(resolve_synthesizer(specs=specs)) is ready
        assert unavailable.loads == 0

    def test_no_usable_engine_lists_every_reason(self) -> None:
        specs = [fake_spec("a", FakeSynthesizer(), available=False, detail="voice missing")]
        with pytest.raises(SynthesizerUnavailable, match="voice missing"):
            resolve_synthesizer(specs=specs)

    def test_a_failing_load_releases_the_engine(self) -> None:
        class Broken(FakeSynthesizer):
            def load(self) -> None:
                self.loads += 1
                raise RuntimeError("boom")

        engine = Broken()
        with pytest.raises(RuntimeError, match="boom"):
            resolve_synthesizer("a", specs=[fake_spec("a", engine)])
        assert engine.closes == 1


def test_clean_text_collapses_whitespace() -> None:
    assert clean_text("  the \n tide\tturns  ") == "the tide turns"


@pytest.mark.parametrize("text", ["", "   ", "\n\t "])
def test_clean_text_rejects_nothing_to_say(text: str) -> None:
    with pytest.raises(ValueError, match="empty"):
        clean_text(text)


def _piper_spec() -> EngineSpec:
    return next(spec for spec in engines.specs() if spec.name == "piper")


# Only run the real engine when its default voice is already cached, so a fresh box
# does not download 60 MB in the middle of a test run.
PIPER_READY = (
    not engines.surface_missing(_piper_spec())
    and piper_engine.voice_path(piper_engine.DEFAULT_VOICE).is_file()
)


class TestPiper:
    def test_missing_voice_offline_is_unavailable(self, monkeypatch, tmp_path) -> None:
        monkeypatch.setenv("TTRPG_TTS_MODEL_DIR", str(tmp_path))
        monkeypatch.setenv("TTRPG_TTS_OFFLINE", "1")
        available, detail = piper_engine.check()
        assert available is False
        assert "OFFLINE" in detail

    def test_missing_voice_online_is_announced(self, monkeypatch, tmp_path) -> None:
        monkeypatch.setenv("TTRPG_TTS_MODEL_DIR", str(tmp_path))
        monkeypatch.delenv("TTRPG_TTS_OFFLINE", raising=False)
        available, detail = piper_engine.check()
        assert available is True
        assert "downloaded" in detail

    def test_cached_voice_is_reported(self, monkeypatch, tmp_path) -> None:
        monkeypatch.setenv("TTRPG_TTS_MODEL_DIR", str(tmp_path))
        (tmp_path / "piper").mkdir()
        (tmp_path / "piper" / f"{piper_engine.DEFAULT_VOICE}.onnx").write_bytes(b"stub")
        available, detail = piper_engine.check()
        assert available is True
        assert "at " in detail

    def test_offline_load_without_a_voice_refuses_to_download(self, monkeypatch, tmp_path) -> None:
        monkeypatch.setenv("TTRPG_TTS_MODEL_DIR", str(tmp_path))
        monkeypatch.setenv("TTRPG_TTS_OFFLINE", "1")
        with pytest.raises(SynthesizerUnavailable, match="OFFLINE"):
            piper_engine.build().load()

    @pytest.mark.parametrize("raw", ["nope", "9", "0", "-1"])
    def test_bad_speed_is_rejected(self, monkeypatch, raw: str) -> None:
        monkeypatch.setenv("TTRPG_TTS_SPEED", raw)
        with pytest.raises(ValueError, match="TTRPG_TTS_SPEED"):
            piper_engine.speed_from_environment()

    def test_valid_speed_is_accepted(self, monkeypatch) -> None:
        monkeypatch.setenv("TTRPG_TTS_SPEED", "0.9")
        assert piper_engine.speed_from_environment() == pytest.approx(0.9)

    @pytest.mark.parametrize(
        "raw,expected", [("1", True), ("true", True), ("0", False), ("", False)]
    )
    def test_deterministic_flag_is_parsed(self, monkeypatch, raw: str, expected: bool) -> None:
        monkeypatch.setenv("TTRPG_TTS_DETERMINISTIC", raw)
        assert piper_engine.deterministic_from_environment() is expected

    @pytest.mark.skipif(not PIPER_READY, reason="piper voice is not cached on this box")
    def test_deterministic_mode_renders_identical_audio(self) -> None:
        """The whole point of the switch: the same line caches cleanly."""
        synthesizer = piper_engine.PiperSynthesizer(
            voice=piper_engine.DEFAULT_VOICE, deterministic=True
        )
        try:
            synthesizer.load()
            first = synthesizer.synthesize("The tide turns at the quay.")
            second = synthesizer.synthesize("The tide turns at the quay.")
        finally:
            synthesizer.close()

        assert first.pcm == second.pcm

    @pytest.mark.parametrize("raw", ["nope", "3", "0"])
    def test_bad_volume_is_rejected(self, monkeypatch, raw: str) -> None:
        monkeypatch.setenv("TTRPG_TTS_VOLUME", raw)
        with pytest.raises(ValueError, match="TTRPG_TTS_VOLUME"):
            piper_engine.volume_from_environment()

    @pytest.mark.skipif(not PIPER_READY, reason="piper voice is not cached on this box")
    def test_real_synthesis_produces_speech_with_headroom(self) -> None:
        synthesizer = piper_engine.PiperSynthesizer(voice=piper_engine.DEFAULT_VOICE)
        try:
            synthesizer.load()
            clip = synthesizer.synthesize("The tide turns at the quay.")
        finally:
            synthesizer.close()

        assert clip.sample_rate == 22_050
        assert clip.channels == 1
        assert clip.duration_s > 0.5
        assert 1000 < clip.peak < 32767, "normalising to full scale leaves no headroom"

    @pytest.mark.skipif(not PIPER_READY, reason="piper voice is not cached on this box")
    def test_real_synthesis_rejects_silence_only_input(self) -> None:
        synthesizer = piper_engine.PiperSynthesizer(voice=piper_engine.DEFAULT_VOICE)
        try:
            synthesizer.load()
            with pytest.raises(ValueError, match="empty"):
                synthesizer.synthesize("   ")
        finally:
            synthesizer.close()


class TestEspeak:
    def test_missing_binary_is_unavailable(self, monkeypatch) -> None:
        monkeypatch.delenv("TTRPG_TTS_ESPEAK", raising=False)
        monkeypatch.setattr(espeak_engine.shutil, "which", lambda name: None)
        assert espeak_engine.binary() is None
        assert espeak_engine.check()[0] is False

    def test_override_path_is_used(self, monkeypatch) -> None:
        monkeypatch.setenv("TTRPG_TTS_ESPEAK", "/custom/espeak-ng")
        assert espeak_engine.binary() == "/custom/espeak-ng"

    def test_load_without_a_binary_raises(self, monkeypatch) -> None:
        monkeypatch.delenv("TTRPG_TTS_ESPEAK", raising=False)
        monkeypatch.setattr(espeak_engine.shutil, "which", lambda name: None)
        with pytest.raises(SynthesizerUnavailable):
            espeak_engine.build().load()

    def _loaded_engine(self, monkeypatch, result):
        monkeypatch.setattr(espeak_engine, "binary", lambda: "/usr/bin/espeak-ng")
        monkeypatch.setattr(espeak_engine.subprocess, "run", lambda *a, **k: result)
        synthesizer = espeak_engine.build()
        synthesizer.load()
        return synthesizer

    def test_synthesize_decodes_stdout_and_passes_text_as_one_argument(
        self, monkeypatch
    ) -> None:
        captured = {}

        class Result:
            returncode = 0
            stdout = encode_wav(tone(0.2))
            stderr = b""

        def fake_run(command, **kwargs):
            captured["command"] = command
            return Result()

        monkeypatch.setattr(espeak_engine, "binary", lambda: "/usr/bin/espeak-ng")
        monkeypatch.setattr(espeak_engine.subprocess, "run", fake_run)

        synthesizer = espeak_engine.build()
        synthesizer.load()
        clip = synthesizer.synthesize("hello there")

        assert clip.sample_rate == 22_050
        assert captured["command"][0] == "/usr/bin/espeak-ng"
        assert "--stdout" in captured["command"]
        assert captured["command"][-1] == "hello there"

    def test_non_zero_exit_is_reported(self, monkeypatch) -> None:
        class Result:
            returncode = 3
            stdout = b""
            stderr = b"no such voice"

        synthesizer = self._loaded_engine(monkeypatch, Result())
        with pytest.raises(SynthesisError, match="no such voice"):
            synthesizer.synthesize("hello")

    def test_empty_output_is_reported(self, monkeypatch) -> None:
        class Result:
            returncode = 0
            stdout = b""
            stderr = b""

        synthesizer = self._loaded_engine(monkeypatch, Result())
        with pytest.raises(SynthesisError, match="no audio"):
            synthesizer.synthesize("hello")

    def test_timeout_is_reported(self, monkeypatch) -> None:
        def explode(*args, **kwargs):
            raise subprocess.TimeoutExpired(cmd="espeak-ng", timeout=30)

        monkeypatch.setattr(espeak_engine, "binary", lambda: "/usr/bin/espeak-ng")
        monkeypatch.setattr(espeak_engine.subprocess, "run", explode)
        synthesizer = espeak_engine.build()
        synthesizer.load()
        with pytest.raises(SynthesisError, match="could not run"):
            synthesizer.synthesize("hello")
