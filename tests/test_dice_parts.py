"""Structured rolls: the parts a form collects, and the messages it gives back."""

from __future__ import annotations

import random

import pytest

from ttrpg_chatbots.dice.checks import Check, Checkbook
from ttrpg_chatbots.dice.parts import RollParts, build_spec, roll_parts
from ttrpg_chatbots.dice.roller import Roller
from ttrpg_chatbots.dice.types import DiceError, RollSpec

STEALTH = Check(
    id="stealth",
    label="Stealth",
    spec=RollSpec(count=1, sides=20, modifier=5, mode="check", target=15, label="Stealth"),
    aliases=frozenset({"sneak"}),
)
BODY = Checkbook([STEALTH])


def spec_for(**kwargs) -> tuple[RollSpec, str | None]:
    return build_spec(RollParts(**kwargs), checks=BODY)


# -- defaults --------------------------------------------------------------


def test_a_bare_roll_is_a_d20_and_says_so() -> None:
    spec, note = spec_for()
    assert (spec.count, spec.sides, spec.modifier, spec.mode) == (1, 20, 0, "sum")
    assert note == "no dice given, so this is a d20"


def test_a_character_alone_still_counts_as_no_dice() -> None:
    _, note = spec_for(character="Sable")
    assert note == "no dice given, so this is a d20"


def test_each_part_is_taken_literally() -> None:
    spec, note = spec_for(count=4, sides=6, modifier=-1)
    assert (spec.count, spec.sides, spec.modifier) == (4, 6, -1)
    assert spec.notation == "4d6-1"
    assert note == "`4d6-1`"


def test_the_hint_mentions_a_non_default_mode() -> None:
    spec, note = spec_for(count=5, sides=10, mode="hits", target=8)
    assert spec.mode == "hits" and spec.target == 8
    assert note == "`5d10` (hits)"


# -- teaching errors -------------------------------------------------------


def test_hits_without_a_target_shows_the_example() -> None:
    with pytest.raises(DiceError, match="target:8"):
        spec_for(mode="hits")


def test_check_without_a_target_shows_the_example() -> None:
    with pytest.raises(DiceError, match="target:15"):
        spec_for(mode="check")


def test_a_target_without_a_target_mode_is_refused_not_ignored() -> None:
    with pytest.raises(DiceError, match="only used by"):
        spec_for(target=12)


def test_notation_and_parts_cannot_be_mixed() -> None:
    with pytest.raises(DiceError, match="give either notation or"):
        spec_for(notation="3d6", count=2)


def test_notation_is_parsed_when_used_alone() -> None:
    spec, note = spec_for(notation="2d20+3")
    assert spec.notation == "2d20+3"
    assert note is None  # they already know the shorthand


def test_invalid_notation_is_reported_as_a_dice_error() -> None:
    with pytest.raises(DiceError, match="not a dice expression"):
        spec_for(notation="3x6")


def test_unusable_numbers_are_reported() -> None:
    with pytest.raises(DiceError, match="sides must be in 2..1000"):
        spec_for(sides=0)
    with pytest.raises(DiceError, match="dice count must be in 1..1000"):
        spec_for(count=5000)
    with pytest.raises(DiceError, match="hit threshold"):
        spec_for(count=2, sides=6, mode="hits", target=9)


def test_an_unknown_mode_names_the_options() -> None:
    with pytest.raises(DiceError, match="mode must be one of"):
        spec_for(mode="explode")


# -- named checks ----------------------------------------------------------


def test_a_named_check_brings_its_own_dice() -> None:
    spec, note = spec_for(check="stealth")
    assert (spec.count, spec.sides, spec.modifier) == (1, 20, 5)
    assert (spec.mode, spec.target) == ("check", 15)
    assert spec.label == "Stealth"
    assert note is None


def test_a_check_answers_to_its_aliases() -> None:
    spec, _ = spec_for(check="sneak")
    assert spec.label == "Stealth"


def test_a_check_can_be_read_against_a_harder_target() -> None:
    spec, _ = spec_for(check="stealth", target=18)
    assert spec.target == 18


def test_a_check_can_be_read_in_another_mode() -> None:
    spec, _ = spec_for(check="stealth", mode="sum")
    assert spec.mode == "sum"
    # The check's own difficulty is inherited, so it is dropped rather than rejected:
    # asking for the total is legitimate and the target simply does not apply.
    assert spec.target is None


def test_an_explicit_target_for_a_sum_is_still_refused() -> None:
    with pytest.raises(DiceError, match="only used by"):
        spec_for(check="stealth", mode="sum", target=12)


def test_a_check_cannot_be_given_extra_dice() -> None:
    for extra in ({"count": 2}, {"sides": 6}, {"modifier": 1}, {"notation": "2d6"}):
        with pytest.raises(DiceError, match="defines its own dice"):
            spec_for(check="stealth", **extra)


def test_an_unknown_check_lists_the_known_ones() -> None:
    with pytest.raises(Exception, match="known checks: stealth"):
        spec_for(check="flying")


# -- rolling ---------------------------------------------------------------


def test_roll_parts_needs_a_character() -> None:
    with pytest.raises(DiceError, match="needs a character"):
        roll_parts(RollParts(), roller=Roller(random.Random(1)), character="  ")


def test_roll_parts_returns_a_speakable_answer() -> None:
    answer = roll_parts(
        RollParts(count=3, sides=6),
        roller=Roller(random.Random(4)),
        character="Sable",
    )
    assert answer.source == "dice"
    assert answer.text.startswith("Sable rolls 3d6:")
    assert answer.detail["character"] == "Sable"
    assert answer.detail["roll"]["dice"] and len(answer.detail["roll"]["dice"]) == 3
    assert answer.detail["hint"] == "`3d6`"
    assert answer.detail["check"] is None


def test_every_die_is_within_range_and_the_total_adds_up() -> None:
    answer = roll_parts(
        RollParts(count=40, sides=10, modifier=3),
        roller=Roller(random.Random(6)),
        character="Sable",
    )
    dice = answer.detail["roll"]["dice"]
    assert all(1 <= die <= 10 for die in dice)
    assert sum(dice) + 3 == answer.detail["roll"]["total"]


def test_a_named_check_records_which_check_it_was() -> None:
    answer = roll_parts(
        RollParts(check="stealth"),
        roller=Roller(random.Random(2)),
        checks=BODY,
        character="Sable",
    )
    assert answer.detail["check"] == "stealth"
    assert "Stealth" in answer.text


def test_checks_are_optional() -> None:
    answer = roll_parts(
        RollParts(count=2, sides=6), roller=Roller(random.Random(1)), character="Sable"
    )
    assert "2d6" in answer.text

