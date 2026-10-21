"""The Discord applications: who is connected, and what each one is allowed to do.

Four bots in total, in two roles: one **helper** that owns slash commands, threads and the
sheet, and any number of **friends** that only talk. The roster is data, the tokens are secrets,
and the permission audit is the thing that says out loud when Discord is quietly refusing
something.
"""

from ttrpg_chatbots.bots.identity import (
    ROLE_FRIEND,
    ROLE_HELPER,
    ROLES,
    BotSpec,
    BotSpecError,
    bots_from_records,
)
from ttrpg_chatbots.bots.permissions import (
    Finding,
    PermissionsError,
    Requirement,
    audit,
    log_findings,
    missing,
    report,
    requirements_for,
    summarise,
)
from ttrpg_chatbots.bots.persona import Persona, PersonaError, VoiceSpec
from ttrpg_chatbots.bots.roster import (
    BOTS_ENV,
    DEFAULT_ROSTER_FILE,
    Roster,
    RosterError,
    app_id,
    default_roster,
    load_roster,
    roster_path,
    token_source,
)

__all__ = [
    "BOTS_ENV",
    "DEFAULT_ROSTER_FILE",
    "ROLE_FRIEND",
    "ROLE_HELPER",
    "ROLES",
    "BotSpec",
    "BotSpecError",
    "Persona",
    "PersonaError",
    "VoiceSpec",
    "Finding",
    "PermissionsError",
    "Requirement",
    "Roster",
    "RosterError",
    "app_id",
    "audit",
    "bots_from_records",
    "default_roster",
    "load_roster",
    "log_findings",
    "missing",
    "report",
    "requirements_for",
    "roster_path",
    "summarise",
    "token_source",
]
