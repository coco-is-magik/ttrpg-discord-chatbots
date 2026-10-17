"""Configuration: which backend, which endpoint, and where a secret may come from."""

from __future__ import annotations

from pathlib import Path

import pytest

from ttrpg_chatbots.llm import config as llm_config
from ttrpg_chatbots.llm import wire
from ttrpg_chatbots.llm.types import LlmConfigError

KEY = "fake-key-not-a-real-credential"


def load(**env: str) -> llm_config.LlmConfig:
    return llm_config.load_llm_config(env)


# -- defaults -------------------------------------------------------------


def test_with_no_settings_the_local_server_is_used() -> None:
    resolved = load()
    assert resolved.backend == "local"
    assert resolved.base_url == "http://127.0.0.1:5000/v1"
    assert resolved.wire == wire.WIRE_CHAT
    assert resolved.model == "local-model"
    assert resolved.api_key == ""
    assert resolved.enabled is True


def test_the_local_port_can_be_moved() -> None:
    assert load(TTRPG_LLM_PORT="8080").base_url == "http://127.0.0.1:8080/v1"


@pytest.mark.parametrize("port", ["abc", "0", "70000", "-1"])
def test_a_bad_port_is_rejected(port: str) -> None:
    with pytest.raises(LlmConfigError, match="TTRPG_LLM_PORT"):
        load(TTRPG_LLM_PORT=port)


def test_an_explicit_base_url_wins_and_loses_its_trailing_slash() -> None:
    resolved = load(TTRPG_LLM_BASE_URL="http://10.0.0.2:9000/v1/")
    assert resolved.base_url == "http://10.0.0.2:9000/v1"


@pytest.mark.parametrize("url", ["127.0.0.1:5000/v1", "ftp://host/v1", "http://"])
def test_a_base_url_needs_a_scheme_and_a_host(url: str) -> None:
    with pytest.raises(LlmConfigError, match="http"):
        load(TTRPG_LLM_BASE_URL=url)


def test_the_model_can_be_overridden() -> None:
    assert load(TTRPG_LLM_MODEL="mistral-7b").model == "mistral-7b"


# -- choosing a backend ---------------------------------------------------


def test_openai_is_chosen_when_its_key_is_present() -> None:
    resolved = load(OPENAI_API_KEY=KEY)
    assert resolved.backend == "openai"
    assert resolved.wire == wire.WIRE_RESPONSES
    assert resolved.model == "gpt-5-codex"
    assert resolved.base_url == "https://api.openai.com/v1"
    assert resolved.api_key == KEY


def test_clinepass_is_chosen_when_only_its_key_is_present() -> None:
    resolved = load(CLINE_API_KEY=KEY)
    assert resolved.backend == "clinepass"
    assert resolved.base_url == "https://api.cline.bot/api/v1"
    assert resolved.model.startswith("cline-pass/")
    assert resolved.wire == wire.WIRE_CHAT


def test_openai_wins_when_both_keys_are_present() -> None:
    # Deterministic, and documented: set TTRPG_LLM_BACKEND to break the tie.
    assert load(OPENAI_API_KEY=KEY, CLINE_API_KEY=KEY).backend == "openai"


def test_an_explicit_backend_beats_auto_detection() -> None:
    assert load(TTRPG_LLM_BACKEND="clinepass", OPENAI_API_KEY=KEY).backend == "clinepass"
    assert load(TTRPG_LLM_BACKEND="local", OPENAI_API_KEY=KEY).backend == "local"


def test_an_explicit_openai_without_a_key_still_resolves() -> None:
    # Resolution does not demand a key; building the backend is what complains.
    resolved = load(TTRPG_LLM_BACKEND="openai")
    assert resolved.api_key == ""


def test_auto_can_be_spelled_out() -> None:
    assert load(TTRPG_LLM_BACKEND="auto", CLINE_API_KEY=KEY).backend == "clinepass"


def test_an_unknown_backend_lists_the_alternatives() -> None:
    with pytest.raises(LlmConfigError) as caught:
        load(TTRPG_LLM_BACKEND="telepathy")
    for name in ("local", "openai", "clinepass", "auto", "off"):
        assert name in str(caught.value)


@pytest.mark.parametrize("value", ["off", "none", "disabled", "no", "OFF"])
def test_the_llm_can_be_switched_off(value: str) -> None:
    resolved = load(TTRPG_LLM_BACKEND=value)
    assert resolved.backend == llm_config.OFF
    assert resolved.enabled is False


def test_switching_off_ignores_nonsense_elsewhere() -> None:
    # Nothing reads these values, so they must not raise.
    resolved = load(TTRPG_LLM_BACKEND="off", TTRPG_LLM_TIMEOUT="soon", TTRPG_LLM_WIRE="grpc")
    assert resolved.enabled is False


# -- secrets --------------------------------------------------------------


def test_a_key_file_is_read(tmp_path: Path) -> None:
    path = tmp_path / "key"
    path.write_text(KEY + "\n", encoding="utf-8")
    assert load(**{"TTRPG_LLM_API_KEY_FILE": str(path)}).api_key == KEY


def test_a_key_file_wins_over_a_plain_variable(tmp_path: Path) -> None:
    path = tmp_path / "key"
    path.write_text("from-the-file", encoding="utf-8")
    resolved = load(TTRPG_LLM_API_KEY="from-the-variable", **{"OPENAI_API_KEY_FILE": str(path)})
    assert resolved.api_key == "from-the-file"


def test_the_generic_key_beats_the_backend_specific_one() -> None:
    assert load(TTRPG_LLM_API_KEY="generic", OPENAI_API_KEY="specific").api_key == "generic"


def test_the_backend_specific_key_is_used_when_there_is_no_generic_one() -> None:
    assert load(OPENAI_API_KEY="specific").api_key == "specific"


def test_a_missing_key_file_is_reported_with_the_variable_name(tmp_path: Path) -> None:
    with pytest.raises(LlmConfigError, match="OPENAI_API_KEY_FILE"):
        load(**{"OPENAI_API_KEY_FILE": str(tmp_path / "nope")})


def test_an_empty_key_file_is_reported(tmp_path: Path) -> None:
    path = tmp_path / "key"
    path.write_text("   \n", encoding="utf-8")
    with pytest.raises(LlmConfigError, match="empty"):
        load(**{"TTRPG_LLM_API_KEY_FILE": str(path)})


def test_a_key_file_that_is_not_text_is_reported(tmp_path: Path) -> None:
    path = tmp_path / "key"
    path.write_bytes(b"\xff\xfe\x00")
    with pytest.raises(LlmConfigError, match="readable text file"):
        load(**{"TTRPG_LLM_API_KEY_FILE": str(path)})


def test_a_key_with_whitespace_is_rejected() -> None:
    with pytest.raises(LlmConfigError, match="whitespace"):
        load(OPENAI_API_KEY="two\nlines")


def test_the_key_never_appears_in_repr_or_describe() -> None:
    resolved = load(OPENAI_API_KEY=KEY)
    assert KEY not in repr(resolved)
    described = resolved.describe()
    assert described["api_key"] == "set"
    assert KEY not in str(described)


# -- numeric settings -----------------------------------------------------


def test_the_numbers_can_be_set() -> None:
    resolved = load(
        TTRPG_LLM_TIMEOUT="5.5", TTRPG_LLM_MAX_TOKENS="80", TTRPG_LLM_TEMPERATURE="0.25"
    )
    assert resolved.timeout == 5.5
    assert resolved.max_tokens == 80
    assert resolved.temperature == 0.25


def test_greedy_decoding_is_allowed() -> None:
    assert load(TTRPG_LLM_TEMPERATURE="0").temperature == 0.0


@pytest.mark.parametrize(
    ("variable", "value"),
    [
        ("TTRPG_LLM_TIMEOUT", "0"),
        ("TTRPG_LLM_TIMEOUT", "-1"),
        ("TTRPG_LLM_TIMEOUT", "soon"),
        ("TTRPG_LLM_TIMEOUT", "601"),
        ("TTRPG_LLM_MAX_TOKENS", "0"),
        ("TTRPG_LLM_MAX_TOKENS", "1.5"),
        ("TTRPG_LLM_TEMPERATURE", "-0.1"),
        ("TTRPG_LLM_TEMPERATURE", "2.5"),
    ],
)
def test_out_of_range_numbers_are_rejected(variable: str, value: str) -> None:
    with pytest.raises(LlmConfigError, match=variable):
        load(**{variable: value})


@pytest.mark.parametrize("wire_format", ["grpc", "sse", "chat,responses"])
def test_an_unknown_wire_format_is_rejected(wire_format: str) -> None:
    with pytest.raises(LlmConfigError, match="TTRPG_LLM_WIRE"):
        load(TTRPG_LLM_WIRE=wire_format)


def test_the_wire_format_can_be_overridden() -> None:
    assert load(TTRPG_LLM_WIRE="CHAT").wire == wire.WIRE_CHAT

