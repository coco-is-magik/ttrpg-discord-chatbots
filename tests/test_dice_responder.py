"""The responder that rolls instead of talking, and delegates everything else."""

from __future__ import annotations

import pytest

from dice_support import DEMO_WORLD, ScriptedRng
from llm_support import StaticResponder
from ttrpg_chatbots.dice.checks import load_checks
from ttrpg_chatbots.dice.responder import DiceResponder
from ttrpg_chatbots.dice.roller import Roller
from ttrpg_chatbots.dice.types import DiceError

CHECKS = load_checks(DEMO_WORLD)
NAMES = {"brannoc": "Brannoc the Archivist", "sable": "Sable"}


def responder(*dice: int, **kwargs) -> tuple[DiceResponder, StaticResponder]:
    fallback = StaticResponder("reply:brannoc", text="Aye, the crown is old.", source="reply:B")
    dice_roller = Roller(ScriptedRng(*dice))
    return (
        DiceResponder(
            dice_roller,
            fallback,
            checks=kwargs.get("checks", CHECKS),
            character=kwargs.get("character", "Brannoc"),
            characters=kwargs.get("characters", NAMES),
        ),
        fallback,
    )


def test_a_roll_instruction_is_rolled() -> None:
    responder_, fallback = responder(3, 4, 5)
    answer = responder_.answer("roll 3d6")
    assert answer.source == "dice"
    assert answer.text == "Brannoc rolls 3d6: 3 + 4 + 5 = 12"
    assert answer.detail["roll"]["dice"] == [3, 4, 5]
    assert answer.detail["character"] == "Brannoc"
    assert fallback.prompts == []


def test_a_named_check_is_rolled_with_its_own_reading() -> None:
    responder_, _ = responder(14)
    answer = responder_.answer("roll stealth")
    assert "Stealth" in answer.text
    assert "vs 15 -> success" in answer.text
    assert answer.detail["check"] == "stealth"


def test_anything_else_goes_to_the_fallback() -> None:
    responder_, fallback = responder()
    answer = responder_.answer("what is the sunken crown?")
    assert answer is not None
    assert answer.source == "reply:B"
    assert fallback.prompts == ["what is the sunken crown?"]


def test_the_message_can_name_who_is_rolling() -> None:
    responder_, _ = responder(6)
    assert responder_.answer("roll d6 for Sable").text.startswith("Sable rolls")


def test_the_default_character_covers_an_unnamed_roll() -> None:
    responder_, _ = responder(6)
    assert responder_.answer("roll d6").text.startswith("Brannoc rolls")


def test_without_any_character_the_error_says_what_to_do() -> None:
    responder_, _ = responder(character="", characters={})
    with pytest.raises(DiceError, match="who is rolling"):
        responder_.answer("roll 3d6")


def test_both_sides_are_named() -> None:
    responder_, _ = responder()
    assert responder_.name == "dice"
    assert responder_.fallback_name == "reply:brannoc"
