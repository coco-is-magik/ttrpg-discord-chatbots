"""The permission audit: every failure names the scope, the reason and the fix."""

from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest

from ttrpg_chatbots.bots.identity import ROLE_FRIEND, ROLE_HELPER
from ttrpg_chatbots.bots.permissions import (
    MESSAGE_CONTENT,
    PermissionsError,
    audit,
    log_findings,
    missing,
    report,
    requirements_for,
    summarise,
)


class _Permissions:
    """The subset of ``discord.Permissions`` an audit reads: attribute lookup only."""

    def __init__(self, allowed: set[str]) -> None:
        self._allowed = frozenset(allowed)

    def __getattr__(self, name: str) -> bool:
        return name in self._allowed


class _Channel:
    def __init__(self, name: str = "general", allowed: set[str] | None = None) -> None:
        self.name = name
        self._allowed = allowed or set()

    def permissions_for(self, member) -> _Permissions:
        return _Permissions(self._allowed)


class _Member:
    """The audit only passes the member through to the channel."""


def _names(role: str) -> set[str]:
    return {requirement.name for requirement in requirements_for(role)}


def _audit(role: str, allowed: set[str], **kwargs):
    return audit(
        bot_name="friend-a" if role == ROLE_FRIEND else "ttrpg-bot",
        role=role,
        channels=[_Channel("general", allowed)],
        member=_Member(),
        **kwargs,
    )


def test_the_helper_needs_thread_permissions() -> None:
    names = _names(ROLE_HELPER)
    assert {"create_private_threads", "manage_threads"} <= names
    assert {"embed_links", "attach_files"} <= names


def test_a_friend_needs_reactions_and_no_thread_management() -> None:
    names = _names(ROLE_FRIEND)
    assert "add_reactions" in names
    assert "manage_threads" not in names
    assert "create_private_threads" not in names


def test_an_unknown_role_is_refused() -> None:
    with pytest.raises(PermissionsError, match="narrator"):
        requirements_for("narrator")


def test_voice_is_only_checked_when_asked_for() -> None:
    assert "connect" not in _names(ROLE_FRIEND)
    assert "connect" in {r.name for r in requirements_for(ROLE_FRIEND, voice=True)}


def test_a_fully_permitted_helper_passes() -> None:
    findings = _audit(ROLE_HELPER, _names(ROLE_HELPER))
    assert missing(findings) == ()
    assert "every required permission" in report(findings)


def test_one_missing_permission_names_the_fix() -> None:
    allowed = _names(ROLE_HELPER) - {"create_private_threads"}
    (failure,) = missing(_audit(ROLE_HELPER, allowed))
    assert failure.requirement == "create_private_threads"
    assert failure.where == "#general"
    assert "Grant" in failure.fix
    assert "private build thread" in failure.detail


def test_the_report_leads_with_the_failure() -> None:
    allowed = _names(ROLE_HELPER) - {"manage_threads"}
    text = report(_audit(ROLE_HELPER, allowed))
    assert text.startswith("ttrpg-bot:")
    assert "❌ #general · Manage Threads" in text
    assert "fix:" in text


def test_no_channels_is_a_finding_not_a_crash() -> None:
    findings = audit(
        bot_name="ttrpg-bot",
        role=ROLE_HELPER,
        channels=[],
        member=_Member(),
    )
    (failure,) = missing(findings)
    assert failure.requirement == "configured"
    assert "bots.json" in failure.fix


def test_an_uninspectable_channel_is_reported() -> None:
    class _Opaque:
        name = "secret"

    findings = audit(
        bot_name="ttrpg-bot",
        role=ROLE_HELPER,
        channels=[_Opaque()],
        member=_Member(),
    )
    (failure,) = missing(findings)
    assert failure.requirement == "inspectable"
    assert "invited" in failure.fix


def test_a_friend_without_message_content_fails_the_intent_check() -> None:
    findings = _audit(
        ROLE_FRIEND,
        _names(ROLE_FRIEND),
        intents=SimpleNamespace(message_content=False),
    )
    (failure,) = missing(findings)
    assert failure.scope == "intent"
    assert failure.requirement == MESSAGE_CONTENT
    assert "Developer Portal" in failure.fix


def test_a_friend_with_message_content_passes() -> None:
    findings = _audit(
        ROLE_FRIEND,
        _names(ROLE_FRIEND),
        intents=SimpleNamespace(message_content=True),
    )
    assert missing(findings) == ()


def test_the_helper_never_checks_message_content() -> None:
    findings = _audit(ROLE_HELPER, _names(ROLE_HELPER))
    assert {finding.scope for finding in findings} == {"channel"}


def test_the_intent_check_is_skipped_when_it_cannot_be_known() -> None:
    """The helper auditing a friend cannot see that friend's intents, so it does not guess."""
    findings = _audit(ROLE_FRIEND, _names(ROLE_FRIEND))
    assert {finding.scope for finding in findings} == {"channel"}


def test_the_summary_names_the_bot_and_the_channel() -> None:
    findings = _audit(ROLE_HELPER, _names(ROLE_HELPER) - {"embed_links"})
    line = summarise(findings)
    assert line.startswith("ttrpg-bot:")
    assert "#general" in line
    assert "/" in line


def test_log_findings_warns_once_per_failure(caplog) -> None:
    logger = logging.getLogger("ttrpg_chatbots.bots.permissions.test")
    allowed = _names(ROLE_HELPER) - {"embed_links", "create_private_threads"}
    findings = _audit(ROLE_HELPER, allowed)
    with caplog.at_level(logging.INFO, logger=logger.name):
        log_findings(logger, findings)

    warnings = [record for record in caplog.records if record.levelno == logging.WARNING]
    assert len(warnings) == 2
    assert "create_private_threads" in caplog.text
    assert "Grant" in caplog.text
    assert any(record.levelno == logging.INFO for record in caplog.records)


def test_findings_are_immutable_and_ordered() -> None:
    findings = _audit(ROLE_HELPER, _names(ROLE_HELPER))
    assert tuple(findings) == findings
    assert findings[0].requirement == "view_channel"


def test_the_invite_integers_match_the_requirement_sets() -> None:
    """The URL generator values in the docs must not drift from what the audit checks.

    Published in MANUAL_TESTING.md §2 and GROUP.md §8.3. If a permission is added to a role,
    this fails and both documents get updated with the new integer.
    """
    import discord

    published = {
        (ROLE_HELPER, False): 360777370624,
        (ROLE_HELPER, True): 360780516352,
        (ROLE_FRIEND, False): 274878254144,
        (ROLE_FRIEND, True): 274881399872,
    }
    for (role, voice), expected in published.items():
        permissions = discord.Permissions(
            **{requirement.name: True for requirement in requirements_for(role, voice=voice)}
        )
        assert permissions.value == expected, (
            f"the invite integer for {role} (voice={voice}) is now {permissions.value}; update "
            "MANUAL_TESTING.md §2 and GROUP.md §8.3"
        )
