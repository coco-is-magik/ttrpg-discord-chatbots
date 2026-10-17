"""Shared helpers for the reply-engine tests."""

from __future__ import annotations

from pathlib import Path

from ttrpg_chatbots.reply.types import (
    Character,
    KnowledgeItem,
    ResponseTemplate,
    World,
)

DEMO_WORLD = Path(__file__).resolve().parents[1] / "examples" / "demo_world"


def make_world(**overrides) -> World:
    """A three-fact, one-character world that tests can bend per case."""
    defaults = {
        "name": "Testworld",
        "knowledge": (
            KnowledgeItem(
                id="k-crown",
                text="The crown is tide-iron.",
                tags=frozenset({"lore:relic"}),
                slots={"subject": "the crown"},
            ),
            KnowledgeItem(
                id="k-quay",
                text="The quay is deep-water.",
                tags=frozenset({"lore:harbor"}),
                slots={"place": "the quay"},
            ),
            KnowledgeItem(
                id="k-guild",
                text="The guild owns the dry-docks.",
                tags=frozenset({"lore:guild"}),
            ),
        ),
        "responses": (
            ResponseTemplate(
                id="r-1",
                character="ann",
                tags=frozenset({"lore:relic"}),
                template="{subject}: {fact}",
            ),
            ResponseTemplate(
                id="r-2",
                character="ann",
                tags=frozenset({"lore:guild"}),
                template="Guild business. {fact}",
            ),
            ResponseTemplate(
                id="r-3", character="ann", tags=frozenset({"fallback"}), template="I could not say."
            ),
        ),
        "characters": (
            Character(id="ann", name="Ann", known_tags=frozenset({"lore:relic", "lore:guild"})),
        ),
    }
    defaults.update(overrides)
    return World(**defaults)  # type: ignore[arg-type]
