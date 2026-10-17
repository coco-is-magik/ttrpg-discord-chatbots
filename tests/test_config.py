from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from ttrpg_chatbots.config import (
    GUILD_ID_ENV_VAR,
    MAX_SNOWFLAKE,
    TOKEN_ENV_VAR,
    TOKEN_FILE_ENV_VAR,
    ConfigError,
    load_discord_config,
)

DUMMY_TOKEN = "dummy-token-from-the-environment"


@pytest.fixture
def clean_env(monkeypatch, tmp_path):
    """Run in a temp directory so the repository .env is never read."""
    for var in (TOKEN_ENV_VAR, TOKEN_FILE_ENV_VAR, GUILD_ID_ENV_VAR):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.chdir(tmp_path)


def test_token_from_environment(monkeypatch, clean_env) -> None:
    monkeypatch.setenv(TOKEN_ENV_VAR, DUMMY_TOKEN)
    assert load_discord_config().token == DUMMY_TOKEN


def test_token_is_stripped(monkeypatch, clean_env) -> None:
    monkeypatch.setenv(TOKEN_ENV_VAR, f"  {DUMMY_TOKEN}\n")
    assert load_discord_config().token == DUMMY_TOKEN


def test_token_from_file_takes_precedence(monkeypatch, tmp_path, clean_env) -> None:
    secret = tmp_path / "discord_token"
    secret.write_text(f"{DUMMY_TOKEN}\n", encoding="utf-8")
    monkeypatch.setenv(TOKEN_ENV_VAR, "token-from-the-environment")
    monkeypatch.setenv(TOKEN_FILE_ENV_VAR, str(secret))
    assert load_discord_config().token == DUMMY_TOKEN


def test_missing_token_file_raises(monkeypatch, tmp_path, clean_env) -> None:
    monkeypatch.setenv(TOKEN_FILE_ENV_VAR, str(tmp_path / "absent"))
    with pytest.raises(ConfigError, match=TOKEN_FILE_ENV_VAR):
        load_discord_config()


def test_empty_token_file_raises(monkeypatch, tmp_path, clean_env) -> None:
    secret = tmp_path / "empty"
    secret.write_text("\n", encoding="utf-8")
    monkeypatch.setenv(TOKEN_FILE_ENV_VAR, str(secret))
    with pytest.raises(ConfigError, match="empty"):
        load_discord_config()


@pytest.mark.parametrize("value", ["", "   "])
def test_blank_token_raises(monkeypatch, clean_env, value) -> None:
    monkeypatch.setenv(TOKEN_ENV_VAR, value)
    with pytest.raises(ConfigError, match=TOKEN_ENV_VAR):
        load_discord_config()


def test_missing_token_raises(clean_env) -> None:
    with pytest.raises(ConfigError, match=TOKEN_ENV_VAR):
        load_discord_config()


def test_env_file_is_used_as_fallback(monkeypatch, tmp_path, clean_env) -> None:
    (tmp_path / ".env").write_text(f"{TOKEN_ENV_VAR}={DUMMY_TOKEN}\n", encoding="utf-8")
    assert load_discord_config().token == DUMMY_TOKEN


def test_environment_wins_over_env_file(monkeypatch, tmp_path, clean_env) -> None:
    (tmp_path / ".env").write_text(f"{TOKEN_ENV_VAR}=token-from-the-env-file\n", encoding="utf-8")
    monkeypatch.setenv(TOKEN_ENV_VAR, DUMMY_TOKEN)
    assert load_discord_config().token == DUMMY_TOKEN


def test_env_file_can_be_ignored(monkeypatch, tmp_path, clean_env) -> None:
    (tmp_path / ".env").write_text(f"{TOKEN_ENV_VAR}={DUMMY_TOKEN}\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_discord_config(env_file=None)


def test_guild_id_is_optional(monkeypatch, clean_env) -> None:
    monkeypatch.setenv(TOKEN_ENV_VAR, DUMMY_TOKEN)
    assert load_discord_config().guild_id is None


def test_guild_id_is_parsed(monkeypatch, clean_env) -> None:
    monkeypatch.setenv(TOKEN_ENV_VAR, DUMMY_TOKEN)
    monkeypatch.setenv(GUILD_ID_ENV_VAR, "123456789012345678")
    assert load_discord_config().guild_id == 123456789012345678


@pytest.mark.parametrize(
    "value",
    ["not-a-snowflake", "12abc", "1.5", "0x10", "1e18", "0", "-1", str(MAX_SNOWFLAKE + 1)],
)
def test_garbage_guild_id_raises(monkeypatch, clean_env, value) -> None:
    monkeypatch.setenv(TOKEN_ENV_VAR, DUMMY_TOKEN)
    monkeypatch.setenv(GUILD_ID_ENV_VAR, value)
    with pytest.raises(ConfigError, match=GUILD_ID_ENV_VAR):
        load_discord_config()


def test_guild_id_with_surrounding_whitespace_is_accepted(monkeypatch, clean_env) -> None:
    monkeypatch.setenv(TOKEN_ENV_VAR, DUMMY_TOKEN)
    monkeypatch.setenv(GUILD_ID_ENV_VAR, "  123456789012345678  ")
    assert load_discord_config().guild_id == 123456789012345678


def test_largest_valid_guild_id_is_accepted(monkeypatch, clean_env) -> None:
    monkeypatch.setenv(TOKEN_ENV_VAR, DUMMY_TOKEN)
    monkeypatch.setenv(GUILD_ID_ENV_VAR, str(MAX_SNOWFLAKE))
    assert load_discord_config().guild_id == MAX_SNOWFLAKE


def test_repr_hides_the_token(monkeypatch, clean_env) -> None:
    monkeypatch.setenv(TOKEN_ENV_VAR, DUMMY_TOKEN)
    config = load_discord_config()
    # Exact match on purpose: any future field must opt out of repr the same way,
    # so that logging a config can never leak a credential.
    assert repr(config) == "DiscordConfig(guild_id=None)"
    assert DUMMY_TOKEN not in str(config)


def test_config_is_immutable(monkeypatch, clean_env) -> None:
    monkeypatch.setenv(TOKEN_ENV_VAR, DUMMY_TOKEN)
    config = load_discord_config()
    with pytest.raises(FrozenInstanceError):
        config.token = "replaced"


# --- malformed and incomplete token input ------------------------------------


@pytest.mark.parametrize(
    "value",
    ["two tokens on one line", "line-one\nline-two", "token\twith-tab"],
)
def test_token_containing_whitespace_raises(monkeypatch, clean_env, value) -> None:
    monkeypatch.setenv(TOKEN_ENV_VAR, value)
    with pytest.raises(ConfigError, match="whitespace"):
        load_discord_config(env_file=None)


def test_multiline_token_file_raises(monkeypatch, tmp_path, clean_env) -> None:
    """A secret file holding two lines is a mistake, not a token."""
    secret = tmp_path / "token"
    secret.write_text("first-line\nsecond-line\n", encoding="utf-8")
    monkeypatch.setenv(TOKEN_FILE_ENV_VAR, str(secret))
    with pytest.raises(ConfigError, match="whitespace"):
        load_discord_config()


def test_windows_line_ending_in_token_file_is_stripped(monkeypatch, tmp_path, clean_env) -> None:
    secret = tmp_path / "token"
    secret.write_bytes(f"{DUMMY_TOKEN}\r\n".encode("utf-8"))
    monkeypatch.setenv(TOKEN_FILE_ENV_VAR, str(secret))
    assert load_discord_config().token == DUMMY_TOKEN


def test_binary_token_file_raises_config_error(monkeypatch, tmp_path, clean_env) -> None:
    """A non-UTF-8 secret file reports a config error, not a codec traceback."""
    secret = tmp_path / "token.bin"
    secret.write_bytes(b"\xff\xfe\x00\x01not-text")
    monkeypatch.setenv(TOKEN_FILE_ENV_VAR, str(secret))
    with pytest.raises(ConfigError, match="readable text file"):
        load_discord_config()


def test_directory_as_token_file_raises_config_error(monkeypatch, tmp_path, clean_env) -> None:
    monkeypatch.setenv(TOKEN_FILE_ENV_VAR, str(tmp_path))
    with pytest.raises(ConfigError, match="readable text file"):
        load_discord_config()


def test_token_file_path_expands_the_home_directory(monkeypatch, tmp_path, clean_env) -> None:
    (tmp_path / "token").write_text(DUMMY_TOKEN, encoding="utf-8")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv(TOKEN_FILE_ENV_VAR, "~/token")
    assert load_discord_config().token == DUMMY_TOKEN


def test_blank_token_file_variable_falls_back_to_the_token_variable(
    monkeypatch, clean_env
) -> None:
    monkeypatch.setenv(TOKEN_FILE_ENV_VAR, "   ")
    monkeypatch.setenv(TOKEN_ENV_VAR, DUMMY_TOKEN)
    assert load_discord_config().token == DUMMY_TOKEN


def test_unrelated_variables_are_not_used_as_the_token(monkeypatch, clean_env) -> None:
    monkeypatch.setenv("TOKEN", DUMMY_TOKEN)
    monkeypatch.setenv("DISCORD_CLIENT_SECRET", DUMMY_TOKEN)
    with pytest.raises(ConfigError, match=TOKEN_ENV_VAR):
        load_discord_config()


# --- malformed and incomplete env file input ---------------------------------


def test_env_file_can_be_a_plain_path_string(monkeypatch, tmp_path, clean_env) -> None:
    (tmp_path / "dev.env").write_text(f"{TOKEN_ENV_VAR}={DUMMY_TOKEN}\n", encoding="utf-8")
    assert load_discord_config(env_file="dev.env").token == DUMMY_TOKEN


def test_explicit_missing_env_file_is_tolerated(monkeypatch, clean_env) -> None:
    monkeypatch.setenv(TOKEN_ENV_VAR, DUMMY_TOKEN)
    assert load_discord_config(env_file=Path("absent.env")).token == DUMMY_TOKEN


def test_missing_env_file_still_reports_a_missing_token(clean_env) -> None:
    with pytest.raises(ConfigError, match=TOKEN_ENV_VAR):
        load_discord_config(env_file=Path("absent.env"))


def test_garbage_lines_in_the_env_file_are_ignored(monkeypatch, tmp_path, clean_env) -> None:
    (tmp_path / ".env").write_text(
        f"not a key value pair\n# comment\n\n{TOKEN_ENV_VAR}=\"{DUMMY_TOKEN}\"\n",
        encoding="utf-8",
    )
    assert load_discord_config().token == DUMMY_TOKEN


def test_empty_token_in_the_env_file_raises(monkeypatch, tmp_path, clean_env) -> None:
    (tmp_path / ".env").write_text(f"{TOKEN_ENV_VAR}=\n", encoding="utf-8")
    with pytest.raises(ConfigError, match=TOKEN_ENV_VAR):
        load_discord_config()
