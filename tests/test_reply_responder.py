"""The classifier sitting behind the responder seam: same shape as an LLM answer."""

from __future__ import annotations

import pytest

from reply_support import DEMO_WORLD
from ttrpg_chatbots.reply.datasets import load_world
from ttrpg_chatbots.reply.replier import Replier
from ttrpg_chatbots.reply.responder import ClassifierResponder
from ttrpg_chatbots.reply.types import UnknownCharacter


@pytest.fixture
def replier() -> Replier:
    return Replier(load_world(DEMO_WORLD))


def test_it_answers_with_the_classifier(replier: Replier) -> None:
    answer = ClassifierResponder(replier, "brannoc").answer("what is the sunken crown?")
    assert answer.source == "reply:brannoc"
    assert answer.detail["tag"] == "lore:relic"
    assert answer.detail["knowledge_id"] == "k-relic-crown"
    assert answer.detail["known"] is True
    assert answer.fallback_reason is None
    assert "Sunken Crown" in answer.text


def test_the_name_says_which_character(replier: Replier) -> None:
    assert ClassifierResponder(replier, "brannoc").name == "reply:brannoc"


def test_a_display_name_is_resolved_to_an_id(replier: Replier) -> None:
    responder = ClassifierResponder(replier, "Brannoc the Archivist")
    assert responder.character == "brannoc"
    assert responder.name == "reply:brannoc"


def test_an_unknown_character_fails_at_construction(replier: Replier) -> None:
    with pytest.raises(UnknownCharacter):
        ClassifierResponder(replier, "nobody")


def test_a_deflection_is_marked_unknown(replier: Replier) -> None:
    answer = ClassifierResponder(replier, "orla").answer("when is the turning tide rite spoken?")
    assert answer.detail["known"] is False
    assert answer.detail["tag"] is None


def test_a_speaker_reaches_the_template(replier: Replier) -> None:
    answer = ClassifierResponder(replier, "orla", speaker="Tav").answer(
        "when is the turning tide rite spoken?"
    )
    assert answer.detail["known"] is False
    assert "Tav" in answer.text
