import json
import wave

import pytest

from ttrpg_chatbots.stt import cli
from ttrpg_chatbots.stt.probe import Measurement, Resolution
from ttrpg_chatbots.stt.types import SAMPLE_RATE


class FakeRecognizer:
    name = "fake"

    def __init__(self, text: str = "hi there") -> None:
        self._text = text
        self.transcribed = []
        self.closes = 0

    def load(self) -> None:
        pass

    def transcribe(self, clip) -> str:
        self.transcribed.append(clip)
        return self._text

    def close(self) -> None:
        self.closes += 1


def _resolution(*, source: str = "measured") -> Resolution:
    recognizer = FakeRecognizer()
    measurements = (Measurement("fake", True, 0.2, median_s=0.05, rtf=0.02),)
    return Resolution(recognizer, "fake", source, measurements)


def _write_wav(path, *, rate: int = SAMPLE_RATE, channels: int = 1, width: int = 2) -> None:
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(width)
        handle.setframerate(rate)
        handle.writeframes(b"\x00\x00" * rate)


def test_list_shows_every_registered_engine(capsys) -> None:
    assert cli.main(["--list"]) == 0
    output = capsys.readouterr().out
    for name in ("vosk", "faster-whisper", "sherpa-onnx"):
        assert name in output


def test_list_json_is_machine_readable(capsys) -> None:
    assert cli.main(["--list", "--json"]) == 0
    rows = json.loads(capsys.readouterr().out)
    assert {row["engine"] for row in rows} >= {"vosk", "faster-whisper", "sherpa-onnx"}
    assert all({"available", "detail"} <= set(row) for row in rows)


def test_unknown_engine_exits_two_with_a_message(capsys) -> None:
    assert cli.main(["--engine", "nonexistent"]) == 2
    assert "unknown STT engine" in capsys.readouterr().err


def test_report_prints_the_table_and_the_winner(monkeypatch, capsys) -> None:
    monkeypatch.setattr(cli, "resolve_recognizer", lambda **kwargs: _resolution())

    assert cli.main([]) == 0

    output = capsys.readouterr().out
    assert "fake" in output
    assert "selected: fake (measured" in output


def test_report_json_carries_the_measurements(monkeypatch, capsys) -> None:
    monkeypatch.setattr(cli, "resolve_recognizer", lambda **kwargs: _resolution())

    assert cli.main(["--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["selected"] == "fake"
    assert payload["measurements"][0]["median_ms"] == 50.0


def test_the_override_reaches_the_selector(monkeypatch) -> None:
    seen = {}

    def fake_resolve(**kwargs):
        seen.update(kwargs)
        return _resolution(source="forced")

    monkeypatch.setattr(cli, "resolve_recognizer", fake_resolve)
    cli.main(["--engine", "vosk", "--refresh", "--repeats", "2"])

    assert seen == {"engine": "vosk", "refresh": True, "repeats": 2, "seconds": 3.0}


def test_transcribe_prints_text_and_releases_the_engine(monkeypatch, tmp_path, capsys) -> None:
    resolution = _resolution()
    monkeypatch.setattr(cli, "resolve_recognizer", lambda **kwargs: resolution)
    wav = tmp_path / "clip.wav"
    _write_wav(wav)

    assert cli.main(["--transcribe", str(wav)]) == 0

    assert capsys.readouterr().out.strip() == "hi there"
    assert len(resolution.recognizer.transcribed) == 1
    assert resolution.recognizer.closes == 1, "the model must be released on the success path"


@pytest.mark.parametrize("format_kwargs", [{"rate": 8000}, {"channels": 2}, {"width": 1}])
def test_transcribe_rejects_audio_in_the_wrong_format(
    monkeypatch, tmp_path, capsys, format_kwargs
) -> None:
    resolution = _resolution()
    monkeypatch.setattr(cli, "resolve_recognizer", lambda **kwargs: resolution)
    wav = tmp_path / "clip.wav"
    _write_wav(wav, **format_kwargs)

    assert cli.main(["--transcribe", str(wav)]) == 2
    assert "need 16000 Hz mono 16-bit PCM" in capsys.readouterr().err
    assert resolution.recognizer.closes == 1


def test_transcribe_rejects_a_file_that_is_not_audio(monkeypatch, tmp_path, capsys) -> None:
    resolution = _resolution()
    monkeypatch.setattr(cli, "resolve_recognizer", lambda **kwargs: resolution)
    garbage = tmp_path / "not-a-wav.wav"
    garbage.write_bytes(b"this is definitely not a riff file")

    assert cli.main(["--transcribe", str(garbage)]) == 2
    assert "error:" in capsys.readouterr().err
