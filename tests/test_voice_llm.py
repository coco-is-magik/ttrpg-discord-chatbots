"""The voice CLI's opt-in LLM half: pick the model, speak it, survive its absence."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from llm_support import FakeBackend, completion
from ttrpg_chatbots.llm.types import LlmUnavailable
from ttrpg_chatbots.voice import cli

from tts_support import FakeCast

DEMO = Path(__file__).resolve().parents[1] / "examples" / "demo_world"

LLM_ENV = (
    "TTRPG_LLM_BACKEND",
    "TTRPG_LLM_BASE_URL",
    "TTRPG_LLM_PORT",
    "TTRPG_LLM_MODEL",
    "TTRPG_LLM_WIRE",
    "TTRPG_LLM_API_KEY",
    "TTRPG_LLM_API_KEY_FILE",
    "OPENAI_API_KEY",
    "CLINE_API_KEY",
)


@pytest.fixture(autouse=True)
def _hermetic(tmp_path, monkeypatch):
    for name in LLM_ENV:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)
    cast = FakeCast()
    monkeypatch.setattr(cli, "VoiceCast", lambda directory: cast)
    return cast


def ask(*extra: str) -> list[str]:
    return ["--ask", *extra, "--character", "brannoc", "--data", str(DEMO)]


def test_llm_answers_are_synthesized_in_the_characters_voice(monkeypatch, capsys, _hermetic):
    backend = FakeBackend(completion("The Tidewrights hold them.", backend="local"))
    monkeypatch.setattr(cli, "build_backend", lambda config: backend)

    assert cli.main(ask("who holds the dry docks?", "--llm")) == 0

    output = capsys.readouterr().out
    assert _hermetic.spoken == [("brannoc", "The Tidewrights hold them.")]
    assert "answered by: llm:local" in output
    assert "NOTE" not in output


def test_a_dead_model_falls_back_and_still_speaks(monkeypatch, capsys, caplog, _hermetic):
    def refuse(config):
        raise LlmUnavailable("cannot reach http://127.0.0.1:5000", backend="local")

    monkeypatch.setattr(cli, "build_backend", refuse)
    with caplog.at_level(logging.WARNING):
        assert cli.main(ask("what is the sunken crown?", "--llm")) == 0

    output = capsys.readouterr().out
    spoken = _hermetic.spoken[0]
    assert spoken[0] == "brannoc"
    assert "tide-iron" in spoken[1], "the classifier's own answer is spoken"
    assert "answered by: reply:brannoc" in output
    assert "NOTE answered by the fallback: local: backend unreachable" in output
    assert any("falling back" in record.getMessage() for record in caplog.records)


def test_without_the_flag_no_model_is_ever_built(monkeypatch, _hermetic):
    def explode(config):
        raise AssertionError("the classifier path must not construct a backend")

    monkeypatch.setattr(cli, "build_backend", explode)
    assert cli.main(ask("what is the sunken crown?")) == 0
    assert "tide-iron" in _hermetic.spoken[0][1]


def test_asking_for_the_llm_when_it_is_off_is_an_error(monkeypatch, capsys):
    monkeypatch.setenv("TTRPG_LLM_BACKEND", "off")
    assert cli.main(ask("hello", "--llm")) == 2
    assert "switched off" in capsys.readouterr().err
