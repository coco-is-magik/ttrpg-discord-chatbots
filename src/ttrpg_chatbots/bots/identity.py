"""Who is connected: the Discord applications this project runs.

There are two kinds of bot, and they are not interchangeable:

* the **helper** (``ttrpg-bot``) owns every slash command, every thread, and the sheet. It never
  reads ordinary messages, so it needs no privileged intent and stays quiet in the channel.
* a **friend** is one of the people in the group. It reads messages, speaks, and owns no
  commands at all. Its personality is deliberately unspecified here: a friend is a *slot* that
  has a name, a seat and a token, not a character we have decided on yet.

A spec is data (``bots.json``). The token is a secret and is resolved from the environment by
:mod:`ttrpg_chatbots.bots.roster`, the same way :mod:`ttrpg_chatbots.config` resolves the
helper's. Nothing in this module touches the environment or the network.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

ROLE_HELPER = "helper"
ROLE_FRIEND = "friend"
ROLES = (ROLE_HELPER, ROLE_FRIEND)

# When a friend answers. "off" is the default so a newly added bot is silent until it is
# deliberately switched on; "mention" answers only an @mention.
REPLY_MODES = ("off", "mention")

HELPER_TOKEN_ENV = "DISCORD_TOKEN"
FRIEND_TOKEN_PREFIX = "TTRPG_"
FRIEND_TOKEN_SUFFIX = "_TOKEN"

MAX_SNOWFLAKE = 2**64 - 1

# Lower-case, hyphenated, no spaces: it becomes an environment variable prefix and a seat id.
_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]*$")


class BotSpecError(RuntimeError):
    """Raised when a bot definition cannot be read, or describes an impossible bot."""


@dataclass(frozen=True)
class BotSpec:
    """One Discord application: what it is for, and where its token lives.

    ``seat`` is the person a friend speaks for. It may be empty while the friends are still
    being built, which is why it is not required; a friend without a seat can connect but
    cannot answer as anyone.
    """

    id: str
    role: str
    seat: str = ""
    user_id: int | None = None
    token_env: str = ""
    env_file: str = ""
    channels: tuple[int, ...] = ()
    listen: bool = False
    commands: bool = False
    reply: str = "off"
    enabled: bool = True

    def __post_init__(self) -> None:
        identifier = (self.id or "").strip()
        if not identifier:
            raise BotSpecError("a bot needs an id")
        if not _ID_PATTERN.match(identifier):
            raise BotSpecError(
                f"bot id {self.id!r} must be lower-case letters, digits and hyphens"
            )
        if self.role not in ROLES:
            raise BotSpecError(
                f"bot {identifier!r}: role must be one of {list(ROLES)}, got {self.role!r}"
            )
        if not isinstance(self.env_file, str):
            raise BotSpecError(f"bot {identifier!r}: env_file must be a path string")
        if self.reply not in REPLY_MODES:
            raise BotSpecError(
                f"bot {identifier!r}: reply must be one of {list(REPLY_MODES)}, got {self.reply!r}"
            )
        if self.role == ROLE_HELPER and self.reply != "off":
            raise BotSpecError(
                f"bot {identifier!r}: the helper never replies to messages; put the conversation "
                "on a friend"
            )
        if self.role == ROLE_HELPER and self.listen:
            raise BotSpecError(
                f"bot {identifier!r}: the helper does not listen; keep it commands-only so it "
                "needs no privileged intent, and let a friend do the talking"
            )
        if self.role == ROLE_FRIEND and self.commands:
            raise BotSpecError(
                f"bot {identifier!r}: friends own no commands; slash commands belong to the helper"
            )
        if self.user_id is not None:
            if isinstance(self.user_id, bool) or not isinstance(self.user_id, int):
                raise BotSpecError(f"bot {identifier!r}: user_id must be a whole number")
            if not 0 < self.user_id <= MAX_SNOWFLAKE:
                raise BotSpecError(f"bot {identifier!r}: user_id is out of range")
        for channel in self.channels:
            if isinstance(channel, bool) or not isinstance(channel, int):
                raise BotSpecError(f"bot {identifier!r}: channels must be Discord ids")
            if not 0 < channel <= MAX_SNOWFLAKE:
                raise BotSpecError(f"bot {identifier!r}: channel id {channel} is out of range")

    @property
    def env_prefix(self) -> str:
        """``friend-a`` becomes ``FRIEND_A``, so its token variable is predictable."""
        return self.id.strip().upper().replace("-", "_")

    @property
    def token_var(self) -> str:
        """The environment variable holding the token, unless the spec names its own."""
        if self.token_env.strip():
            return self.token_env.strip()
        if self.role == ROLE_HELPER:
            return HELPER_TOKEN_ENV
        return f"{FRIEND_TOKEN_PREFIX}{self.env_prefix}{FRIEND_TOKEN_SUFFIX}"

    @property
    def token_file_var(self) -> str:
        """``DISCORD_TOKEN_FILE``-style companion, for Docker secrets and systemd credentials."""
        return f"{self.token_var}_FILE"

    @property
    def is_helper(self) -> bool:
        return self.role == ROLE_HELPER

    @property
    def is_friend(self) -> bool:
        return self.role == ROLE_FRIEND

    def describe(self) -> str:
        """One line for a log or ``--check`` output. Never includes the token."""
        detail = self.role
        if self.seat:
            detail += f" for {self.seat}"
        if not self.enabled:
            detail += ", disabled"
        return f"{self.id} ({detail})"


def bots_from_records(records, *, source: str = "bots") -> tuple[BotSpec, ...]:
    """Build specs from decoded records, naming the offending entry on failure."""
    bots: list[BotSpec] = []
    seen: set[str] = set()
    for index, record in enumerate(records, start=1):
        where = f"{source}: bot {index}"
        if not isinstance(record, dict):
            raise BotSpecError(f"{where}: expected an object")
        identifier = record.get("id")
        if not isinstance(identifier, str) or not identifier.strip():
            raise BotSpecError(f"{where}: 'id' must be a non-empty string")
        where = f"{source}: bot {identifier!r}"
        if identifier.strip() in seen:
            raise BotSpecError(f"{where}: duplicate id")
        seen.add(identifier.strip())

        role = record.get("role")
        if not isinstance(role, str) or not role.strip():
            raise BotSpecError(f"{where}: 'role' must be 'helper' or 'friend'")

        seat = record.get("seat", "")
        if not isinstance(seat, str):
            raise BotSpecError(f"{where}: 'seat' must be a string")

        token_env = record.get("token_env", "")
        if not isinstance(token_env, str):
            raise BotSpecError(f"{where}: 'token_env' must be a string")

        env_file = record.get("env_file", "")
        if not isinstance(env_file, str):
            raise BotSpecError(f"{where}: 'env_file' must be a path string")

        channels = record.get("channels") or []
        if not isinstance(channels, list):
            raise BotSpecError(f"{where}: 'channels' must be a list of Discord ids")
        cleaned: list[int] = []
        for channel in channels:
            if isinstance(channel, str) and channel.strip().isdigit():
                cleaned.append(int(channel.strip()))
            elif isinstance(channel, int) and not isinstance(channel, bool):
                cleaned.append(channel)
            else:
                raise BotSpecError(f"{where}: channel {channel!r} is not a Discord id")

        try:
            bots.append(
                BotSpec(
                    id=identifier.strip(),
                    role=role.strip().lower(),
                    seat=seat.strip(),
                    user_id=record.get("user_id"),
                    token_env=token_env.strip(),
                    env_file=env_file.strip(),
                    channels=tuple(cleaned),
                    listen=bool(record.get("listen", False)),
                    commands=bool(record.get("commands", role.strip().lower() == ROLE_HELPER)),
                    reply=str(record.get("reply", "off")).strip().lower(),
                    enabled=bool(record.get("enabled", True)),
                )
            )
        except BotSpecError as error:
            raise BotSpecError(f"{where}: {error}") from error
    return tuple(bots)

