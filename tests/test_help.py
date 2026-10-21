"""The guide must cover every command, and stay a menu rather than a wall."""

from __future__ import annotations

import ttrpg_chatbots.bot as bot
from ttrpg_chatbots.help import GROUPS, documented, help_spec, help_text


def test_every_registered_command_is_documented() -> None:
    """A command a player cannot find is a command that does not exist.

    This is the guard that keeps /help honest: adding a command to the registry without
    adding it here fails the suite.
    """
    registered = {command.name for command in bot.COMMANDS}
    missing = sorted(registered - set(documented()))
    assert missing == [], f"undocumented commands: {missing}"


def test_the_guide_documents_nothing_that_does_not_exist() -> None:
    registered = {command.name for command in bot.COMMANDS}
    stale = sorted(set(documented()) - registered)
    assert stale == [], f"documented but not registered: {stale}"


def test_no_command_appears_twice() -> None:
    names = documented()
    assert len(names) == len(set(names))


def test_the_embed_fits_discord() -> None:
    spec = help_spec()
    assert len(spec.fields) == len(GROUPS) <= 25
    for field in spec.fields:
        assert len(field.value) <= 1024, field.name
        assert field.value.strip()
    assert len(spec.description) <= 4096


def test_the_text_version_names_every_group_and_command() -> None:
    text = help_text()
    for title, commands in GROUPS:
        assert title in text
        for name, _ in commands:
            assert f"/{name} " in text


def test_the_guide_says_nothing_is_final_until_finish() -> None:
    assert "/finish" in help_spec().description
