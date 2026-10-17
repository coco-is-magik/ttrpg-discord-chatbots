"""Dice notation: what is accepted, what is refused, and how refusals read."""

from __future__ import annotations

import pytest

from ttrpg_chatbots.dice.notation import is_notation, parse_notation
from ttrpg_chatbots.dice.types import MODE_CHECK, NotationError


@pytest.mark.parametrize(
    ("text", "count", "sides", "modifier"),
    [
        ("3d6", 3, 6, 0),
        ("d20", 1, 20, 0),
        ("D20", 1, 20, 0),
        ("2d20+3", 2, 20, 3),
        ("2d20-3", 2, 20, -3),
        ("3d6 - 1", 3, 6, -1),
        ("  4D8  ", 4, 8, 0),
        ("1d2", 1, 2, 0),
        ("10d10+100", 10, 10, 100),
    ],
)
def test_expressions_parse(text: str, count: int, sides: int, modifier: int) -> None:
    parsed = parse_notation(text)
    assert (parsed.count, parsed.sides, parsed.modifier) == (count, sides, modifier)


def test_the_notation_reads_back_the_same_way() -> None:
    assert parse_notation("3d6+2").notation == "3d6+2"
    assert parse_notation("3d6-2").notation == "3d6-2"
    assert parse_notation("d6").notation == "1d6"


def test_mode_target_and_label_are_carried_through() -> None:
    parsed = parse_notation("1d20+5", mode=MODE_CHECK, target=15, label="Stealth")
    assert (parsed.mode, parsed.target, parsed.label) == ("check", 15, "Stealth")


@pytest.mark.parametrize(
    "text",
    [
        "",
        "   ",
        "3d",  # no sides
        "d",  # nothing at all
        "3d6+",  # dangling operator
        "3d6++2",  # double sign
        "3d6 please",  # trailing junk belongs to a sentence, not an expression
        "0d6",  # empty pool
        "3d1",  # a coin is a d2
        "3d0",
        "roll 3d6",
        "3x6",
        "-3d6",
    ],
)
def test_bad_expressions_are_refused(text: str) -> None:
    with pytest.raises(NotationError):
        parse_notation(text)


def test_the_error_says_what_to_write_instead() -> None:
    with pytest.raises(NotationError) as caught:
        parse_notation("banana")
    message = str(caught.value)
    assert "not a dice expression" in message
    assert "3d6" in message


def test_an_out_of_range_pool_names_the_reason() -> None:
    with pytest.raises(NotationError, match="dice count must be in"):
        parse_notation("0d6")


def test_is_notation_is_a_cheap_predicate() -> None:
    assert is_notation("3d6") is True
    assert is_notation("roll 3d6") is False
