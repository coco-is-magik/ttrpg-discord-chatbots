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

    def describe(self) -> tuple[str, ...]:
        """One line per bot for ``--check``: role, seat, and whether a token exists."""
        lines = []
        for bot in self.bots:
            state = "disabled" if not bot.enabled else (
                "token set" if self.token_for(bot) else f"dormant (no {bot.token_var})"
            )
            lines.append(f"{bot.describe()} — {state}")
        return tuple(lines)


def resolve_token(bot: BotSpec, env=os.environ) -> str | None:
    """Read one bot's token from ``<VAR>_FILE`` or ``<VAR>``; ``None`` means dormant."""
    path = (env.get(bot.token_file_var) or "").strip()
    if path:
        token = _read_token_file(Path(path).expanduser(), bot)
    else:
        token = (env.get(bot.token_var) or "").strip()
    if not token:
        return None
    if any(character.isspace() for character in token):
        raise RosterError(
            f"{bot.id}: the value of {bot.token_var} contains whitespace, so it is not a single "
            "token; check the secret file or environment value"
        )
    return token


def _read_token_file(path: Path, bot: BotSpec) -> str:
    try:
        token = path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError) as error:
        raise RosterError(
            f"{bot.id}: {bot.token_file_var} is not a readable text file: {path}"
        ) from error
    if not token:
        raise RosterError(f"{bot.id}: {bot.token_file_var} file is empty: {path}")
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
