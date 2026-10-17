"""Reading a roll instruction out of a chat message: the no-model path."""

from __future__ import annotations

import pytest

from dice_support import DEMO_WORLD
from ttrpg_chatbots.dice.checks import load_checks
from ttrpg_chatbots.dice.intent import describe_request, parse_instruction
from ttrpg_chatbots.dice.types import MODE_CHECK, DiceError

CHECKS = load_checks(DEMO_WORLD)
NAMES = {
    "brannoc": "Brannoc the Archivist",
    "sable": "Sable",
    "orla": "Orla the Tavernkeep",
}


def test_a_plain_expression_is_understood() -> None:
    request = parse_instruction("roll 3d6")
    assert request is not None
    assert request.spec.notation == "3d6"
    assert request.check is None
    assert request.character is None


@pytest.mark.parametrize(
    ("text", "notation"),
    [
        ("roll d20", "1d20"),
        ("Roll 2d20 + 3", "2d20+3"),
        ("roll 1d20-2", "1d20-2"),
        ("please roll 4d8", "4d8"),
        ("rolling 2d10", "2d10"),
    ],
)
def test_variations_of_the_same_request(text: str, notation: str) -> None:
    request = parse_instruction(text)
    assert request is not None
    assert request.spec.notation == notation


def test_a_named_check_is_understood() -> None:
    request = parse_instruction("roll stealth", checks=CHECKS)
    assert request is not None
    assert request.check is not None and request.check.id == "stealth"
    assert (request.spec.mode, request.spec.target) == (MODE_CHECK, 15)
    assert request.label == "Stealth"


def test_an_alias_works_too() -> None:
    request = parse_instruction("roll sneak", checks=CHECKS)
    assert request is not None and request.check is not None
    assert request.check.id == "stealth"


def test_the_longest_character_name_wins() -> None:
    names = {"brannoc": "B", "brannoc the archivist": "Brannoc the Archivist"}
    request = parse_instruction(
        "roll 3d6 for Brannoc the Archivist", characters=names
    )
    assert request is not None
    assert request.character == "Brannoc the Archivist"


def test_a_known_alias_resolves_to_the_display_name() -> None:
    request = parse_instruction("roll stealth for sable", checks=CHECKS, characters=NAMES)
    assert request is not None
    assert request.character == "Sable"


def test_an_unknown_name_is_taken_from_the_sentence() -> None:
    request = parse_instruction("roll 3d6 for Ann the Bold")
    assert request is not None
    assert request.character == "Ann the Bold"


def test_trailing_politeness_is_not_part_of_the_name() -> None:
    request = parse_instruction("roll 3d6 for Brannoc please")
    assert request is not None
    assert request.character == "Brannoc"


@pytest.mark.parametrize("text", ["by", "as"])
def test_other_prepositions_name_the_roller(text: str) -> None:
    request = parse_instruction(f"roll a d20 {text} Sable")
    assert request is not None
    assert request.character == "Sable"


@pytest.mark.parametrize(
    "text",
    [
        "",
        "   ",
        "what is the sunken crown?",
        "3d6",
        "hello there",
        "roll the bones",
        "I want to roll a barrel",
    ],
)
def test_messages_that_ask_for_no_roll(text: str) -> None:
    assert parse_instruction(text, checks=CHECKS) is None


def test_a_roll_with_an_impossible_pool_is_an_error_not_a_silent_none() -> None:
    with pytest.raises(DiceError, match="dice count must be in"):
        parse_instruction("roll 0d6")


def test_the_understood_request_can_be_described() -> None:
    request = parse_instruction("roll stealth for sable", checks=CHECKS, characters=NAMES)
    assert describe_request(request) == {
        "notation": "1d20+5",
        "mode": "check",
        "target": 15,
        "check": "stealth",
        "character": "Sable",
    }
