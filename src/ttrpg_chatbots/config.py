"""Discord credentials.

Secrets are never hardcoded or committed. The bot token is read, in order of
precedence, from:

1. ``DISCORD_TOKEN_FILE`` -- path to a file holding the token, for Docker
   secrets, systemd ``LoadCredential``, or a password-manager export.
2. ``DISCORD_TOKEN`` -- process environment, for shell exports and CI.
3. ``./.env`` -- local development only. Plain text on disk, git-ignored, and
   never read when a real environment variable is already set.

Values are validated locally, so a malformed secret fails with an actionable
message instead of a confusing connection error.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

TOKEN_ENV_VAR = "DISCORD_TOKEN"
TOKEN_FILE_ENV_VAR = "DISCORD_TOKEN_FILE"
GUILD_ID_ENV_VAR = "DISCORD_GUILD_ID"

DEFAULT_ENV_FILE = Path(".env")

# Discord ids ("snowflakes") are unsigned 64-bit integers.
MAX_SNOWFLAKE = 2**64 - 1


class ConfigError(RuntimeError):
    """Raised when required configuration is missing or malformed."""


@dataclass(frozen=True)
class DiscordConfig:
    """Everything needed to connect the bot to Discord."""

    token: str = field(repr=False)
    guild_id: int | None = None


def load_discord_config(env_file: Path | str | None = DEFAULT_ENV_FILE) -> DiscordConfig:
    """Read configuration from the environment, filling gaps from ``env_file``.

    ``env_file`` is resolved relative to the working directory. Pass ``None`` to
    ignore it completely.
    """
    if env_file is not None:
        load_dotenv(env_file, override=False)
    return DiscordConfig(token=_read_token(), guild_id=_read_guild_id())


def _read_token() -> str:
    token_file = os.environ.get(TOKEN_FILE_ENV_VAR, "").strip()
    if token_file:
        token = _read_token_file(Path(token_file).expanduser())
    else:
        token = os.environ.get(TOKEN_ENV_VAR, "").strip()
        if not token:
            raise ConfigError(
                f"no Discord bot token: set {TOKEN_ENV_VAR}, or {TOKEN_FILE_ENV_VAR} to "
                "point at a file holding the token. See .env.example."
            )
    if any(character.isspace() for character in token):
        raise ConfigError(
            "the Discord token contains whitespace, so it is not a single token; "
            "check the secret file or environment value"
        )
    return token


def _read_token_file(path: Path) -> str:
    try:
        token = path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError) as error:
        raise ConfigError(f"{TOKEN_FILE_ENV_VAR} is not a readable text file: {path}") from error
    if not token:
        raise ConfigError(f"{TOKEN_FILE_ENV_VAR} file is empty: {path}")
    return token


def _read_guild_id() -> int | None:
    raw = os.environ.get(GUILD_ID_ENV_VAR, "").strip()
    if not raw:
        return None
    try:
        guild_id = int(raw)
    except ValueError as error:
        raise ConfigError(
            f"{GUILD_ID_ENV_VAR} must be a Discord id (digits), got {raw!r}"
        ) from error
    if not 0 < guild_id <= MAX_SNOWFLAKE:
        raise ConfigError(f"{GUILD_ID_ENV_VAR} is out of range for a Discord id: {raw!r}")
    return guild_id
