"""The set of bots this process runs, and where each one's token comes from.

``data/bots.json`` is optional: without it the roster is the single helper that has always
existed, so an installation that never adds friends keeps working exactly as before. Adding a
friend is a data change plus a secret, not a code change.

Tokens follow the same precedence :mod:`ttrpg_chatbots.config` uses for the helper's:

1. ``<VAR>_FILE`` — a path to a file holding the token (Docker secrets, systemd credentials);
2. ``<VAR>`` — the environment;
3. nothing — the bot is **dormant**: configured, reported, and not started.

Dormant is a first-class state, not an error. It is what lets the three friends be committed as
configuration before their applications exist.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import dotenv_values

from ttrpg_chatbots.bots.identity import (
    HELPER_TOKEN_ENV,
    ROLE_HELPER,
    BotSpec,
    BotSpecError,
    bots_from_records,
)

BOTS_ENV = "TTRPG_BOTS_FILE"
DEFAULT_ROSTER_FILE = Path("data") / "bots.json"
DEFAULT_HELPER_ID = "ttrpg-bot"


class RosterError(RuntimeError):
    """Raised when the roster cannot be read, or describes an impossible set."""


@dataclass(frozen=True)
class Roster:
    """Every bot this process knows about, started or dormant."""

    bots: tuple[BotSpec, ...] = ()

    def __post_init__(self) -> None:
        seen: set[str] = set()
        helpers = 0
        for bot in self.bots:
            if bot.id in seen:
                raise RosterError(f"duplicate bot id {bot.id!r}")
            seen.add(bot.id)
            helpers += 1 if bot.is_helper else 0
        if helpers > 1:
            raise RosterError(
                "more than one helper is configured; slash commands belong to exactly one bot"
            )

    def __len__(self) -> int:
        return len(self.bots)

    def __iter__(self):
        return iter(self.bots)

    @property
    def helpers(self) -> tuple[BotSpec, ...]:
        return tuple(bot for bot in self.bots if bot.is_helper)

    @property
    def friends(self) -> tuple[BotSpec, ...]:
        return tuple(bot for bot in self.bots if bot.is_friend)

    @property
    def helper(self) -> BotSpec | None:
        return self.helpers[0] if self.helpers else None

    def enabled(self) -> tuple[BotSpec, ...]:
        """Every bot the operator has not switched off."""
        return tuple(bot for bot in self.bots if bot.enabled)

    def get(self, bot_id: str) -> BotSpec | None:
        wanted = (bot_id or "").strip()
        for bot in self.bots:
            if bot.id == wanted:
                return bot
        return None

    def token_for(self, bot: BotSpec) -> str | None:
        """The token for one bot, or ``None`` when it is dormant."""
        return resolve_token(bot)

    def token_source(self, bot: BotSpec) -> str:
        """Where the token came from, for ``--check``; never the token itself."""
        return token_source(bot)

    def app_id_for(self, bot: BotSpec) -> int | None:
        """The bot's user id, which Discord makes equal to its application id."""
        return app_id(bot)

    def describe(self) -> tuple[str, ...]:
        """One line per bot for ``--check``: role, seat, and whether a token exists."""
        lines = []
        for bot in self.bots:
            if not bot.enabled:
                state = "disabled"
            elif self.token_for(bot):
                state = f"token set ({self.token_source(bot)})"
            elif bot.env_file:
                state = f"dormant (no token in {bot.env_file})"
            else:
                state = f"dormant (no {bot.token_var})"
            lines.append(f"{bot.describe()} — {state}")
        return tuple(lines)


def _env_file_values(bot: BotSpec) -> dict[str, str]:
    """Read one bot's own env file, without touching ``os.environ``.

    ``dotenv_values`` keeps the file's values away from the process environment, which matters:
    every friend's file names its token ``DISCORD_TOKEN``, and loading three of those into
    ``os.environ`` would quietly overwrite the helper's.
    """
    path = Path(bot.env_file).expanduser()
    if not path.is_file():
        raise RosterError(f"{bot.id}: env_file does not exist: {path}")
    values = dotenv_values(path)
    if not values:
        raise RosterError(f"{bot.id}: env_file is empty: {path}")
    return {key: (value or "") for key, value in values.items()}


def resolve_token(bot: BotSpec, env=os.environ) -> str | None:
    """Read one bot's token, or ``None`` when it is dormant.

    Precedence: ``<VAR>_FILE``, then ``<VAR>``, then the bot's own ``env_file`` (which may name
    it ``DISCORD_TOKEN`` like the helper's). Deployment environment wins over a local file.
    """
    path = (env.get(bot.token_file_var) or "").strip()
    if path:
        token = _read_token_file(Path(path).expanduser(), bot)
    else:
        token = (env.get(bot.token_var) or "").strip()
        if not token and bot.env_file:
            values = _env_file_values(bot)
            token = (values.get(bot.token_var) or values.get(HELPER_TOKEN_ENV) or "").strip()
    if not token:
        return None
    if any(character.isspace() for character in token):
        raise RosterError(
            f"{bot.id}: the value of {bot.token_var} contains whitespace, so it is not a single "
            "token; check the secret file or environment value"
        )
    return token


def token_source(bot: BotSpec, env=os.environ) -> str:
    """The name of the variable or file a token came from, or ``""`` when dormant."""
    if (env.get(bot.token_file_var) or "").strip():
        return bot.token_file_var
    if (env.get(bot.token_var) or "").strip():
        return bot.token_var
    if bot.env_file and resolve_token(bot, env):
        return bot.env_file
    return ""


def app_id(bot: BotSpec, env=os.environ) -> int | None:
    """The bot's user id, read from ``APP_ID`` when it is not written down explicitly.

    A Discord bot's user id is its application id, which is what lets the helper fetch a
    friend's member object and audit its channel permissions.
    """
    if bot.user_id is not None:
        return bot.user_id
    if not bot.env_file:
        return None
    raw = (_env_file_values(bot).get("APP_ID") or "").strip()
    if not raw:
        return None
    if not raw.isdigit():
        raise RosterError(f"{bot.id}: APP_ID in {bot.env_file} is not a number")
    return int(raw)


def _read_token_file(path: Path, bot: BotSpec) -> str:
    """Read a file that holds one token, and diagnose the two ways that goes wrong.

    The common mistake is pointing ``<VAR>_FILE`` at a dotenv file, which looks like a token
    store and is not: the roster cannot know which line is the token. It is worth saying so
    plainly, because otherwise the failure reads as "your token is malformed" and sends people
    to regenerate a perfectly good token.
    """
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise RosterError(
            f"{bot.id}: {bot.token_file_var} is not a readable text file: {path}"
        ) from error
    token = raw.strip()
    if not token:
        raise RosterError(f"{bot.id}: {bot.token_file_var} file is empty: {path}")
    if any(character.isspace() for character in token):
        lines = len([line for line in raw.splitlines() if line.strip()])
        raise RosterError(
            f"{bot.id}: {bot.token_file_var} points at {path}, which holds {lines} non-blank "
            "line(s). That variable wants a file containing exactly one token, not an env file. "
            "Point it at a one-line secret, or name a dotenv file with \"env_file\" in bots.json "
            "and put <VAR> inside it instead"
        )
    return token


def default_roster() -> Roster:
    """The installation that has never heard of ``bots.json``: one helper, as before."""
    return Roster(
        (
            BotSpec(
                id=DEFAULT_HELPER_ID,
                role=ROLE_HELPER,
                commands=True,
                token_env=HELPER_TOKEN_ENV,
            ),
        )
    )


def roster_path() -> Path:
    return Path(os.environ.get(BOTS_ENV, str(DEFAULT_ROSTER_FILE)))


def load_roster(path: Path | str | None = None) -> Roster:
    """Read the roster; a missing file means "just the helper", never an error."""
    target = Path(path) if path is not None else roster_path()
    if not target.is_file():
        return default_roster()
    try:
        text = target.read_text(encoding="utf-8")
    except OSError as error:
        raise RosterError(f"cannot read {target}: {error}") from error
    try:
        data = json.loads(text)
    except ValueError as error:
        raise RosterError(f"{target}: invalid JSON: {error}") from error
    if isinstance(data, dict):
        data = data.get("bots")
    if not isinstance(data, list):
        raise RosterError(f"{target}: expected a list of bots")
    try:
        specs = bots_from_records(data, source=str(target))
    except BotSpecError as error:
        raise RosterError(str(error)) from error
    if not specs:
        raise RosterError(f"{target}: no bots are defined")
    return Roster(specs)
