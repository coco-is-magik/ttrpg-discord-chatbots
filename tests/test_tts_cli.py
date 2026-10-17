import json
import os

import pytest

from ttrpg_chatbots.audio import read_wav
from ttrpg_chatbots.tts import cli
from ttrpg_chatbots.tts.synthesizer import SynthesisError

from tts_support import FakeSynthesizer


def test_list_shows_every_engine(capsys) -> None:
    assert cli.main(["--list"]) == 0
    output = capsys.readouterr().out
    assert "piper" in output
    assert "espeak-ng" in output


def test_say_writes_a_wav_and_releases_the_engine(monkeypatch, tmp_path, capsys) -> None:
    fake = FakeSynthesizer(seconds=1.0)
    monkeypatch.setattr(cli, "resolve_synthesizer", lambda engine=None: fake)
    target = tmp_path / "speech.wav"

    assert cli.main(["--say", "the tide turns", "--out", str(target)]) == 0

    output = capsys.readouterr().out
    assert "engine: fake" in output
    assert "wrote:" in output
    assert read_wav(target).duration_s == pytest.approx(1.0, abs=0.01)
    assert fake.spoken == ["the tide turns"]
    assert fake.closes == 1


def test_say_json_reports_the_audio(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        cli, "resolve_synthesizer", lambda engine=None: FakeSynthesizer(seconds=1.0)
    )

    assert cli.main(["--say", "hi", "--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["engine"] == "fake"
    assert payload["sample_rate"] == 22_050
    assert payload["duration_s"] == pytest.approx(1.0, abs=0.01)
    assert payload["out"] is None


def test_missing_text_is_an_error(capsys) -> None:
    assert cli.main([]) == 2
    assert "give --say" in capsys.readouterr().err


def test_a_synthesis_failure_exits_two_and_still_releases(monkeypatch, capsys) -> None:
    fake = FakeSynthesizer(failure=SynthesisError("no voice installed"))
    monkeypatch.setattr(cli, "resolve_synthesizer", lambda engine=None: fake)

    assert cli.main(["--say", "hi"]) == 2

    assert "no voice installed" in capsys.readouterr().err
    assert fake.closes == 1


def test_engine_override_reaches_the_resolver(monkeypatch, capsys) -> None:
    seen = {}

    def fake_resolve(engine=None):
        seen["engine"] = engine
        return FakeSynthesizer()

    monkeypatch.setattr(cli, "resolve_synthesizer", fake_resolve)
    assert cli.main(["--say", "hi", "--engine", "espeak-ng"]) == 0
    assert seen["engine"] == "espeak-ng"


def test_voice_flag_sets_the_environment(monkeypatch) -> None:
    monkeypatch.setattr(cli, "resolve_synthesizer", lambda engine=None: FakeSynthesizer())
    # Seed the variable so monkeypatch restores it: --voice writes process-wide.
    monkeypatch.setenv("TTRPG_TTS_VOICE", "seed")

    assert cli.main(["--say", "hi", "--voice", "en_US-amy-low"]) == 0

    assert os.environ["TTRPG_TTS_VOICE"] == "en_US-amy-low"


def test_out_path_errors_are_reported(monkeypatch, tmp_path, capsys) -> None:
    monkeypatch.setattr(cli, "resolve_synthesizer", lambda engine=None: FakeSynthesizer())
    bad = tmp_path / "missing-dir" / "speech.wav"

    assert cli.main(["--say", "hi", "--out", str(bad)]) == 2
    assert "error:" in capsys.readouterr().err


def test_written_audio_is_not_silent(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(cli, "resolve_synthesizer", lambda engine=None: FakeSynthesizer())
    target = tmp_path / "speech.wav"
    cli.main(["--say", "hi", "--out", str(target)])
    assert read_wav(target).peak > 0
