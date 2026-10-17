"""Dice through the voice pipeline: "roll stealth" is spoken, with or without a model."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from llm_support import FakeBackend, completion
from ttrpg_chatbots.llm.types import LlmUnavailable, ToolCall
from ttrpg_chatbots.voice import cli

from tts_support import FakeCast

DEMO = Path(__file__).resolve().parents[1] / "examples" / "demo_world"

LLM_ENV = (
    "TTRPG_LLM_BACKEND",
    "TTRPG_LLM_BASE_URL",
    "TTRPG_LLM_PORT",
    "TTRPG_LLM_MODEL",
    "TTRPG_LLM_API_KEY",
    "OPENAI_API_KEY",
    "CLINE_API_KEY",
)


@pytest.fixture
def cast(monkeypatch, tmp_path) -> FakeCast:
    for name in LLM_ENV:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)
    fake = FakeCast()
    monkeypatch.setattr(cli, "VoiceCast", lambda directory: fake)
    return fake


def ask(text: str, *extra: str) -> list[str]:
    return ["--ask", text, "--character", "brannoc", "--data", str(DEMO), *extra]


def test_a_roll_instruction_is_spoken(cast: FakeCast, capsys) -> None:
    assert cli.main(ask("roll stealth", "--seed", "3")) == 0
    character, line = cast.spoken[0]
    assert character == "brannoc"
    assert "Stealth" in line
    assert "vs 15 ->" in line
    assert "answered by: dice" in capsys.readouterr().out


def test_a_named_character_rolls(cast: FakeCast) -> None:
    assert cli.main(ask("roll 3d6 for sable", "--seed", "3")) == 0
    assert cast.spoken[0][1].startswith("Sable rolls 3d6:")


def test_a_question_still_goes_to_the_classifier(cast: FakeCast, capsys) -> None:
    assert cli.main(ask("what is the sunken crown?")) == 0
    assert "tide-iron" in cast.spoken[0][1]
    assert "answered by: reply:brannoc" in capsys.readouterr().out


def test_no_model_is_built_without_the_flag(cast: FakeCast, monkeypatch) -> None:
    def explode(config):
        raise AssertionError("the dice path must not construct a backend")

    monkeypatch.setattr(cli, "build_backend", explode)
    assert cli.main(ask("roll stealth", "--seed", "3")) == 0


def test_the_model_can_call_the_dice_tool(cast: FakeCast, monkeypatch) -> None:
    call = ToolCall(
        id="c1",
        name="roll_dice",
        arguments='{"check": "stealth", "character": "Brannoc"}',
    )
    backend = FakeBackend(
        completion("", tool_calls=(call,)),
        completion("Brannoc slips past the watch."),
    )
    monkeypatch.setattr(cli, "build_backend", lambda config: backend)

    assert cli.main(ask("roll stealth", "--llm", "--seed", "3")) == 0

    # The real roller ran: its rendered result is what went back to the model.
    fed_back = backend.requests[1][-1].content
    assert "Stealth" in fed_back
    assert "vs 15 ->" in fed_back
    assert cast.spoken[0][1] == "Brannoc slips past the watch."


def test_a_dead_model_falls_through_to_the_dice(
    cast: FakeCast, monkeypatch, capsys, caplog
) -> None:
    def refuse(config):
        raise LlmUnavailable("cannot reach the host", backend="local")

    monkeypatch.setattr(cli, "build_backend", refuse)
    with caplog.at_level(logging.WARNING):
        assert cli.main(ask("roll stealth", "--llm", "--seed", "3")) == 0

    assert "vs 15 ->" in cast.spoken[0][1]
    assert "answered by: dice" in capsys.readouterr().out
    assert any("falling back" in record.getMessage() for record in caplog.records)
