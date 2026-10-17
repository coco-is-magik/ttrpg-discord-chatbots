"""Rolling: counts, attribution, and the four ways of reading a result."""

from __future__ import annotations

import random

import pytest

from dice_support import ScriptedRng, spec
from ttrpg_chatbots.dice.roller import Roller
from ttrpg_chatbots.dice.types import (
    MODE_CHECK,
    MODE_HITS,
    MODE_LIST,
    MODE_SUM,
    DiceError,
    RollResult,
)


def test_every_die_is_rolled_within_range() -> None:
    rng = ScriptedRng(3, 1, 6)
    result = Roller(rng).roll(spec(3, 6), character="Brannoc")
    assert result.dice == (3, 1, 6)
    assert rng.calls == [(1, 6), (1, 6), (1, 6)]
    assert rng.remaining == 0


def test_a_roll_needs_a_character() -> None:
    with pytest.raises(DiceError, match="character"):
        Roller(ScriptedRng()).roll(spec(1, 6), character="   ")


def test_the_character_is_trimmed() -> None:
    assert Roller(ScriptedRng(4)).roll(spec(1, 6), character="  Sable ").character == "Sable"


def test_shapes_other_than_a_d6_work_the_same_way() -> None:
    rng = ScriptedRng(19)
    result = Roller(rng).roll(spec(1, 20), character="Sable")
    assert result.dice == (19,)
    assert rng.calls == [(1, 20)]


def test_the_total_includes_the_modifier() -> None:
    assert Roller(ScriptedRng(2, 2, 2)).roll(spec(3, 6, modifier=5), character="O").total == 11
    assert Roller(ScriptedRng(2, 2, 2)).roll(spec(3, 6, modifier=-4), character="O").total == 2


def test_hits_count_dice_at_or_above_the_target() -> None:
    result = Roller(ScriptedRng(3, 9, 8, 1)).roll(
        spec(4, 10, mode=MODE_HITS, target=8), character="Sable"
    )
    assert result.hits == 2
    assert result.success is None
    assert result.margin is None


def test_a_check_compares_the_total_against_the_difficulty() -> None:
    passed = Roller(ScriptedRng(14)).roll(
        spec(1, 20, modifier=5, mode=MODE_CHECK, target=15), character="B"
    )
    assert (passed.total, passed.success, passed.margin) == (19, True, 4)

    failed = Roller(ScriptedRng(2)).roll(
        spec(1, 20, modifier=5, mode=MODE_CHECK, target=15), character="B"
    )
    assert (failed.total, failed.success, failed.margin) == (7, False, -8)


def test_meeting_the_target_exactly_is_a_success() -> None:
    result = Roller(ScriptedRng(10)).roll(spec(1, 20, mode=MODE_CHECK, target=10), character="B")
    assert result.success is True
    assert result.margin == 0


def test_list_and_sum_modes_have_no_verdict() -> None:
    for mode in (MODE_LIST, MODE_SUM):
        result = Roller(ScriptedRng(5)).roll(spec(1, 6, mode=mode), character="B")
        assert result.success is None
        assert result.margin is None


def test_the_result_is_complete_enough_to_reinterpret() -> None:
    result = Roller(ScriptedRng(4, 6)).roll(
        spec(2, 6, modifier=1, mode=MODE_HITS, target=5), character="Ola"
    )
    assert result.as_dict() == {
        "character": "Ola",
        "label": "",
        "notation": "2d6+1",
        "count": 2,
        "sides": 6,
        "modifier": 1,
        "mode": "hits",
        "dice": [4, 6],
        "total": 11,
        "hits": 1,
        "target": 5,
        "success": None,
        "margin": None,
    }


def test_the_same_seed_gives_the_same_roll() -> None:
    first = Roller(random.Random(1234)).roll(spec(5, 20), character="B").dice
    second = Roller(random.Random(1234)).roll(spec(5, 20), character="B").dice
    assert first == second
    assert len(first) == 5


def test_a_roller_can_be_limited() -> None:
    limited = Roller(ScriptedRng(), max_dice=2, max_sides=6)
    with pytest.raises(DiceError, match="at most 2 dice"):
        limited.roll(spec(3, 6), character="B")
    with pytest.raises(DiceError, match="at most 6 sides"):
        limited.roll(spec(1, 20), character="B")


def test_roll_dice_is_a_convenience_over_a_spec() -> None:
    result = Roller(ScriptedRng(3, 3)).roll_dice(
        2, 6, character="B", modifier=1, mode=MODE_SUM
    )
    assert isinstance(result, RollResult)
    assert result.as_dict()["notation"] == "2d6+1"


def test_a_mismatched_result_is_refused() -> None:
    # Guards the roller itself: a bad count or an out-of-range die must not slip through.
    with pytest.raises(ValueError, match="expected 2 dice"):
        RollResult(spec=spec(2, 6), character="B", dice=(1,))
    with pytest.raises(ValueError, match="outside 1..6"):
        RollResult(spec=spec(1, 6), character="B", dice=(7,))
