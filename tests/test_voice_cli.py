import json
from pathlib import Path

import pytest

from ttrpg_chatbots.audio import DISCORD_FRAME_BYTES, write_wav
from ttrpg_chatbots.voice import cli

from tts_support import FakeCast, FakeSynthesizer, tone

DEMO = Path(__file__).resolve().parents[1] / "examples" / "demo_world"


@pytest.fixture
def fake_synth(monkeypatch):
    fake = FakeSynthesizer(seconds=0.5)
    monkeypatch.setattr(cli, "resolve_synthesizer", lambda engine=None: fake)
    return fake


def test_list_shows_the_speech_engines(capsys) -> None:
    assert cli.main(["--list"]) == 0
    output = capsys.readouterr().out
    assert "piper" in output
    assert "espeak-ng" in output


def test_say_reports_discord_frames(fake_synth, capsys) -> None:
    assert cli.main(["--say", "the tide turns"]) == 0

    output = capsys.readouterr().out
    assert "frames: 25" in output, "0.5 s of audio is 25 twenty-millisecond frames"
    assert fake_synth.spoken == ["the tide turns"]
    assert fake_synth.closes == 1


def test_ask_speaks_the_reply_text_with_the_characters_voice(monkeypatch, capsys) -> None:
    cast = FakeCast()
    monkeypatch.setattr(cli, "VoiceCast", lambda directory: cast)
    args = ["--ask", "what is the sunken crown?", "--character", "brannoc", "--data", str(DEMO)]

    assert cli.main(args) == 0

    output = capsys.readouterr().out
    assert "Brannoc the Archivist:" in output
    assert "voice: fake:fake-voice" in output
    assert cast.spoken[0][0] == "brannoc"
    assert "tide-iron" in cast.spoken[0][1]
    assert cast.closes == 1


def test_ask_deflects_in_the_characters_voice(monkeypatch) -> None:
    cast = FakeCast()
    monkeypatch.setattr(cli, "VoiceCast", lambda directory: cast)
    args = ["--ask", "what is the sunken crown?", "--character", "orla", "--data", str(DEMO)]

    assert cli.main(args) == 0
    assert "tide-iron" not in cast.spoken[0][1]


def test_say_with_a_character_uses_that_voice(monkeypatch) -> None:
    cast = FakeCast()
    monkeypatch.setattr(cli, "VoiceCast", lambda directory: cast)

    args = ["--say", "hello there", "--character", "orla", "--data", str(DEMO)]
    assert cli.main(args) == 0

    assert cast.spoken == [("orla", "hello there")]


def test_list_voices_shows_the_cast(capsys) -> None:
    assert cli.main(["--list-voices", "--data", str(DEMO)]) == 0

    output = capsys.readouterr().out
    assert "brannoc" in output
    assert "en_GB-alan-medium" in output
    assert "en_US-amy-medium" in output


def test_list_voices_json_reports_tags_and_voice(capsys) -> None:
    assert cli.main(["--list-voices", "--data", str(DEMO), "--json"]) == 0

    rows = {row["character"]: row for row in json.loads(capsys.readouterr().out)}
    assert rows["brannoc"]["tags"] == ["role:scholar", "species:dwarf"]
    assert rows["sable"]["voice"].startswith("piper:en_US-amy-medium")


def test_a_mistyped_cast_tag_exits_two(tmp_path, capsys) -> None:
    """A tag typo would silently change a voice, so it is a hard error."""
    import shutil

    world_dir = tmp_path / "world"
    shutil.copytree(DEMO, world_dir)
    with (world_dir / "voices.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(
            '{"id": "typo", "tags": ["role:schollar"], "engine": "piper", "voice": "v"}\n'
        )

    assert cli.main(["--list-voices", "--data", str(world_dir)]) == 2
    assert "no character carries" in capsys.readouterr().err


def test_a_wav_file_is_queued_directly(tmp_path, capsys) -> None:
    path = write_wav(tone(0.4, sample_rate=44_100, channels=2), tmp_path / "music.wav")

    assert cli.main(["--wav", str(path), "--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["source"] == "wav"
    assert payload["frames"] == 20
    assert payload["bytes"] == 20 * DISCORD_FRAME_BYTES
    assert payload["engine"] is None


def test_no_action_is_an_error(capsys) -> None:
    assert cli.main([]) == 2
    assert "give one of" in capsys.readouterr().err


def test_a_missing_wav_exits_two(tmp_path, capsys) -> None:
    assert cli.main(["--wav", str(tmp_path / "nope.wav")]) == 2
    assert "error:" in capsys.readouterr().err


def test_engine_override_reaches_the_resolver(monkeypatch, capsys) -> None:
    seen = {}

    def fake_resolve(engine=None):
        seen["engine"] = engine
        return FakeSynthesizer()

    monkeypatch.setattr(cli, "resolve_synthesizer", fake_resolve)
    assert cli.main(["--say", "hi", "--engine", "espeak-ng"]) == 0
    assert seen["engine"] == "espeak-ng"


def test_unknown_character_exits_two_before_speaking(fake_synth, capsys) -> None:
    args = ["--ask", "the crown", "--character", "gandalf", "--data", str(DEMO)]
    assert cli.main(args) == 2
    assert "unknown character" in capsys.readouterr().err
    assert fake_synth.spoken == []


def test_synthesis_is_released_on_failure(monkeypatch, capsys) -> None:
    from ttrpg_chatbots.tts.synthesizer import SynthesisError

    fake = FakeSynthesizer(failure=SynthesisError("no voice"))
    monkeypatch.setattr(cli, "resolve_synthesizer", lambda engine=None: fake)

    assert cli.main(["--say", "hi"]) == 2
    assert "no voice" in capsys.readouterr().err
    assert fake.closes == 1
