"""The LLM CLI: config reporting, a real answer, and the fallback path end to end."""

from __future__ import annotations

import json
import logging

import pytest

from llm_support import FakeBackend, completion
from reply_support import DEMO_WORLD
from ttrpg_chatbots.llm import backends, cli as llm_cli
from ttrpg_chatbots.llm.types import LlmAuthError

KEY = "fake-key-not-a-real-credential"

# Anything the LLM layer can read; cleared so a developer's shell cannot affect a test.
ENV_VARS = (
    "TTRPG_LLM_BACKEND",
    "TTRPG_LLM_BASE_URL",
    "TTRPG_LLM_PORT",
    "TTRPG_LLM_MODEL",
    "TTRPG_LLM_WIRE",
    "TTRPG_LLM_API_KEY",
    "TTRPG_LLM_API_KEY_FILE",
    "TTRPG_LLM_TIMEOUT",
    "TTRPG_LLM_MAX_TOKENS",
    "TTRPG_LLM_TEMPERATURE",
    "OPENAI_API_KEY",
    "OPENAI_API_KEY_FILE",
    "CLINE_API_KEY",
    "CLINE_API_KEY_FILE",
)


@pytest.fixture(autouse=True)
def _hermetic(tmp_path, monkeypatch):
    for name in ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    # Away from the repository, so a local .env cannot leak in either.
    monkeypatch.chdir(tmp_path)


def run(capsys, *argv: str) -> tuple[int, str, str]:
    code = llm_cli.main(list(argv))
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def ask(*extra: str) -> tuple[str, ...]:
    return ("--ask", *extra, "--data", str(DEMO_WORLD))


# -- configuration --------------------------------------------------------


def test_show_config_reports_the_resolution(capsys) -> None:
    code, out, _ = run(capsys, "--show-config", "--backend", "local")
    assert code == 0
    assert "backend: local" in out
    assert "base_url: http://127.0.0.1:5000/v1" in out
    assert "wire: chat" in out
    assert "api_key: unset" in out


def test_show_config_can_be_machine_read(capsys) -> None:
    _, out, _ = run(capsys, "--show-config", "--backend", "clinepass", "--json")
    payload = json.loads(out)
    assert payload["backend"] == "clinepass"
    assert payload["base_url"] == "https://api.cline.bot/api/v1"
    assert payload["model"].startswith("cline-pass/")


def test_the_key_is_never_printed(capsys, monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", KEY)
    _, out, err = run(capsys, "--show-config")
    assert KEY not in out + err
    assert "api_key: set" in out


def test_a_mode_is_required(capsys) -> None:
    code, _, err = run(capsys)
    assert code == 2
    assert "--ask" in err


def test_an_unknown_backend_exits_two(capsys) -> None:
    code, _, err = run(capsys, *ask("hi", "--backend", "telepathy"))
    assert code == 2
    assert "telepathy" in err


def test_a_bad_setting_exits_two(capsys) -> None:
    code, _, err = run(capsys, *ask("hi", "--timeout", "0"))
    assert code == 2
    assert "TTRPG_LLM_TIMEOUT" in err


def test_switching_the_llm_off_is_refused_for_ask(capsys) -> None:
    code, _, err = run(capsys, *ask("hi", "--backend", "off"))
    assert code == 2
    assert "switched off" in err


# -- answering ------------------------------------------------------------


def _fake_backend(monkeypatch, *results) -> FakeBackend:
    backend = FakeBackend(*results)
    monkeypatch.setattr(backends, "build_backend", lambda config, transport=None: backend)
    return backend


def _deny(monkeypatch) -> None:
    def build(config, transport=None):
        raise LlmAuthError(
            "openai rejected the credentials (HTTP 401: Incorrect API key)",
            backend="openai",
            status=401,
        )

    monkeypatch.setattr(backends, "build_backend", build)


def test_ask_prints_the_model_answer(capsys, monkeypatch) -> None:
    _fake_backend(monkeypatch, completion("The Tidewrights hold them.", backend="local"))
    code, out, err = run(capsys, *ask("who holds the dry docks?", "--character", "brannoc"))
    assert code == 0, err
    assert "Brannoc the Archivist:" in out
    assert "The Tidewrights hold them." in out
    assert "source: llm:local" in out
    assert "NOTE" not in out
    assert err == ""


def test_the_model_receives_a_persona_prompt(capsys, monkeypatch) -> None:
    backend = _fake_backend(monkeypatch, completion(backend="local"))
    run(capsys, *ask("who holds the dry docks?", "--character", "brannoc"))
    system = backend.last_request[0]
    assert system.role == "system"
    assert "Brannoc the Archivist" in system.content
    assert backend.last_request[-1].content == "who holds the dry docks?"


def test_grounding_feeds_matched_facts_to_the_model(capsys, monkeypatch) -> None:
    backend = _fake_backend(monkeypatch, completion(backend="local"))
    run(capsys, *ask("what is the sunken crown?", "--character", "brannoc", "--ground"))
    assert "tide-iron" in backend.last_request[0].content


def test_grounding_is_off_by_default(capsys, monkeypatch) -> None:
    backend = _fake_backend(monkeypatch, completion(backend="local"))
    run(capsys, *ask("what is the sunken crown?", "--character", "brannoc"))
    assert "Facts you know" not in backend.last_request[0].content


def test_an_auth_failure_warns_and_answers_with_the_classifier(
    capsys, monkeypatch, caplog
) -> None:
    _deny(monkeypatch)
    with caplog.at_level(logging.WARNING):
        code, out, _ = run(
            capsys,
            *ask("what is the sunken crown?", "--character", "brannoc", "--backend", "openai"),
        )
    # Exit 0 on purpose: the table asked a question and got an answer.
    assert code == 0
    assert "Sunken Crown" in out
    assert "source: reply:brannoc" in out
    assert "NOTE answered by the fallback: openai (HTTP 401): authentication failed" in out

    warnings = [record for record in caplog.records if record.levelno == logging.WARNING]
    assert warnings, "the failure must be logged"
    assert "authentication failed" in warnings[0].getMessage()
    assert warnings[0].exc_info is not None


def test_no_fallback_means_a_hard_failure(capsys, monkeypatch) -> None:
    _deny(monkeypatch)
    code, out, err = run(capsys, *ask("hi", "--backend", "openai", "--no-fallback"))
    assert code == 2
    assert out == ""
    assert "HTTP 401" in err


def test_json_reports_the_degradation(capsys, monkeypatch) -> None:
    _deny(monkeypatch)
    _, out, _ = run(
        capsys,
        *ask(
            "what is the sunken crown?",
            "--character",
            "brannoc",
            "--backend",
            "openai",
            "--json",
        ),
    )
    payload = json.loads(out)
    assert payload["degraded"] is True
    assert payload["fallback_reason"] == "openai (HTTP 401): authentication failed"
    assert payload["source"] == "reply:brannoc"
    assert payload["detail"]["known"] is True
    assert payload["config"]["api_key"] == "unset"


def test_an_unknown_character_exits_two(capsys) -> None:
    code, _, err = run(capsys, *ask("hi", "--character", "nobody"))
    assert code == 2
    assert "nobody" in err

