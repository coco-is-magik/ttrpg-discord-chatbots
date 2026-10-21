"""What each bot must be allowed to do, and whether it actually is.

The two roles need different things, and conflating them is how a bot ends up looking online
while silently failing the one job it has:

* the **helper** writes threads and panels, so it needs *Create Private Threads* (to open a
  build thread) and *Manage Threads* (so a failed build can be cleaned up), plus embeds and
  attachments for sheets, exports and portraits.
* a **friend** only talks, so it needs send/read/history/reactions — and the **Message Content**
  privileged intent, without which it hears an empty string for every message.

Permissions are channel-scoped in Discord: a role can grant *Send Messages* and an overwrite on
one channel can take it away. So an audit never reads the guild-level role alone; it asks each
channel `permissions_for(member)`, which is the same computation Discord itself uses.

Each application audits **itself** at login, because only it can see its own member object. The
helper can additionally audit a friend whose ``user_id`` is known in ``bots.json``, which is the
only way to check another bot's overwrites without the privileged members intent.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

from ttrpg_chatbots.bots.identity import ROLE_FRIEND, ROLE_HELPER, ROLES

SCOPE_CHANNEL = "channel"
SCOPE_INTENT = "intent"

# The check that is not a permission: without this intent a friend reads every message as "".
MESSAGE_CONTENT = "message_content"


class PermissionsError(RuntimeError):
    """Raised when permissions cannot be inspected at all."""


@dataclass(frozen=True)
class Requirement:
    """One thing a bot must be allowed to do, why it needs it, and how to grant it."""

    name: str
    why: str
    fix: str


@dataclass(frozen=True)
class Finding:
    """The result of one check: where, what, whether it passed, and how to fix it."""

    bot: str
    scope: str
    where: str
    requirement: str
    ok: bool
    detail: str = ""
    fix: str = ""


def _grant(permission: str) -> str:
    """The same sentence for every permission, so the fix is never ambiguous."""
    return (
        f"Grant **{permission.replace('_', ' ').title()}** to the bot in that channel's "
        "permission settings, or to the role it holds"
    )


HELPER_REQUIREMENTS: tuple[Requirement, ...] = (
    Requirement("view_channel", "see the channel at all", _grant("view_channel")),
    Requirement("send_messages", "post panels and answers", _grant("send_messages")),
    Requirement(
        "send_messages_in_threads",
        "answer inside the build thread",
        _grant("send_messages_in_threads"),
    ),
    Requirement(
        "read_message_history",
        "edit the panel it posted a moment ago",
        _grant("read_message_history"),
    ),
    Requirement("embed_links", "render a sheet or a panel", _grant("embed_links")),
    Requirement("attach_files", "/export and /import", _grant("attach_files")),
    Requirement(
        "create_private_threads",
        "/create opens a private build thread",
        _grant("create_private_threads"),
    ),
    Requirement(
        "manage_threads",
        "clean up a thread whose build failed, and let a GM read a build",
        _grant("manage_threads"),
    ),
)

FRIEND_REQUIREMENTS: tuple[Requirement, ...] = (
    Requirement("view_channel", "see the conversation", _grant("view_channel")),
    Requirement("send_messages", "say anything at all", _grant("send_messages")),
    Requirement(
        "send_messages_in_threads",
        "take part in a table thread",
        _grant("send_messages_in_threads"),
    ),
    Requirement(
        "read_message_history",
        "remember what was said before it joined",
        _grant("read_message_history"),
    ),
    Requirement("embed_links", "quote a sheet or a roll", _grant("embed_links")),
    Requirement("add_reactions", "react instead of interrupting", _grant("add_reactions")),
    Requirement(
        "use_external_emojis",
        "use the group's own emoji",
        _grant("use_external_emojis"),
    ),
)

VOICE_REQUIREMENTS: tuple[Requirement, ...] = (
    Requirement("connect", "join a voice channel", _grant("connect")),
    Requirement("speak", "be heard once it is there", _grant("speak")),
)

INTENT_REQUIREMENT = Requirement(
    MESSAGE_CONTENT,
    "read ordinary messages, which is the whole of ambient chat",
    "Enable **Message Content Intent** in the Developer Portal (Bot → Privileged Gateway "
    "Intents), save, then restart the bot",
)


def requirements_for(role: str, *, voice: bool = False) -> tuple[Requirement, ...]:
    """The full requirement set for a role, with voice checks only when asked for."""
    if role not in ROLES:
        raise PermissionsError(f"unknown bot role {role!r}; expected one of {list(ROLES)}")
    base = HELPER_REQUIREMENTS if role == ROLE_HELPER else FRIEND_REQUIREMENTS
    return base + VOICE_REQUIREMENTS if voice else base


def missing(findings: Iterable[Finding]) -> tuple[Finding, ...]:
    """Only the failures, in the order they were checked."""
    return tuple(finding for finding in findings if not finding.ok)


def summarise(findings: Sequence[Finding]) -> str:
    """``ttrpg-bot: 8/8 checks passed in #general`` — one line, safe to log every startup."""
    if not findings:
        return "no checks ran"
    bot = findings[0].bot
    passed = sum(1 for finding in findings if finding.ok)
    places = {finding.where for finding in findings if finding.scope == SCOPE_CHANNEL}
    where = ", ".join(sorted(places)) if places else "guild"
    return f"{bot}: {passed}/{len(findings)} checks passed in {where}"


def _permissions(channel: object, member: object):
    """Ask a channel what a member may do, or ``None`` when it cannot be asked."""
    checker = getattr(channel, "permissions_for", None)
    if checker is None:
        return None
    try:
        return checker(member)
    except Exception:  # noqa: BLE001 - an unreadable channel is reported, not raised
        return None


def audit(
    *,
    bot_name: str,
    role: str,
    channels: Sequence[object],
    member: object,
    intents: object | None = None,
    voice: bool = False,
) -> tuple[Finding, ...]:
    """Check one bot against its role's requirements, channel by channel.

    ``channels`` are anything with ``name`` and ``permissions_for(member)`` — real Discord
    channels, or fakes in a test. ``member`` is the bot's own member in the guild. Nothing here
    connects to Discord; the caller supplies objects it already has.
    """
    requirements = requirements_for(role, voice=voice)
    findings: list[Finding] = []

    usable = [channel for channel in channels if channel is not None]
    if not usable:
        findings.append(
            Finding(
                bot=bot_name,
                scope=SCOPE_CHANNEL,
                where="no channel",
                requirement="configured",
                ok=False,
                detail="no channels were supplied, so nothing could be checked",
                fix="add channel ids to bots.json, or run /botcheck inside the channel the bot uses",
            )
        )

    for channel in usable:
        where = f"#{getattr(channel, 'name', getattr(channel, 'id', '?'))}"
        permissions = _permissions(channel, member)
        if permissions is None:
            findings.append(
                Finding(
                    bot=bot_name,
                    scope=SCOPE_CHANNEL,
                    where=where,
                    requirement="inspectable",
                    ok=False,
                    detail="the channel could not be inspected, which usually means the bot is "
                    "not in the server or the id is stale",
                    fix="check the channel id and that the bot has been invited",
                )
            )
            continue
        for requirement in requirements:
            ok = bool(getattr(permissions, requirement.name, False))
            findings.append(
                Finding(
                    bot=bot_name,
                    scope=SCOPE_CHANNEL,
                    where=where,
                    requirement=requirement.name,
                    ok=ok,
                    detail="" if ok else requirement.why,
                    fix="" if ok else requirement.fix,
                )
            )

    if role == ROLE_FRIEND and intents is not None:
        # A friend that cannot read message content is connected and deaf; say so explicitly.
        # With no intents object the caller cannot know (the helper auditing another bot), so
        # the check is skipped rather than reported as a failure it cannot prove.
        ok = bool(getattr(intents, MESSAGE_CONTENT, False))
        findings.append(
            Finding(
                bot=bot_name,
                scope=SCOPE_INTENT,
                where="intent",
                requirement=MESSAGE_CONTENT,
                ok=ok,
                detail="" if ok else INTENT_REQUIREMENT.why,
                fix="" if ok else INTENT_REQUIREMENT.fix,
            )
        )

    return tuple(findings)


def report(findings: Sequence[Finding], *, limit: int = 20) -> str:
    """A message a human can act on: failures first, each with its fix."""
    if not findings:
        return "no permission checks ran"
    lines = [summarise(findings)]
    failures = missing(findings)
    if not failures:
        lines.append("✅ every required permission and intent is in place")
        return "\n".join(lines)

    lines.append("")
    for finding in failures[:limit]:
        label = finding.requirement.replace("_", " ").title()
        lines.append(f"❌ {finding.where} · {label} — {finding.detail}")
        if finding.fix:
            lines.append(f"   fix: {finding.fix}")
    if len(failures) > limit:
        lines.append(f"… and {len(failures) - limit} more")
    return "\n".join(lines)


def log_findings(logger, findings: Sequence[Finding]) -> None:
    """Log every failure as a warning with its fix, then one summary line."""
    for finding in missing(findings):
        logger.warning(
            "%s: %s missing in %s — %s. %s",
            finding.bot,
            finding.requirement,
            finding.where,
            finding.detail,
            finding.fix,
        )
    if findings:
        logger.info("%s", summarise(findings))

