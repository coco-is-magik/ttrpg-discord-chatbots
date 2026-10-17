"""The tool surface: schema shape, and every way a model can get an argument wrong."""

from __future__ import annotations

import json

import pytest

from dice_support import DEMO_WORLD, ScriptedRng
from ttrpg_chatbots.dice.checks import load_checks
from ttrpg_chatbots.dice.roller import Roller
from ttrpg_chatbots.dice.tool import TOOL_NAME, DiceTool, tool_schema
from ttrpg_chatbots.dice.types import MODES, DiceError


def make_tool(*dice: int, **kwargs) -> tuple[DiceTool, ScriptedRng]:
    rng = ScriptedRng(*dice)
    checks = load_checks(DEMO_WORLD)
    return DiceTool(Roller(rng), checks, **kwargs), rng


# -- the schema -----------------------------------------------------------


def test_the_schema_names_every_argument_a_roller_needs() -> None:
    schema = tool_schema()
    assert schema["name"] == TOOL_NAME
    assert schema["parameters"]["required"] == ["character"]
    properties = schema["parameters"]["properties"]
    for name in (
        "character",
        "check",
        "notation",
        "count",
        "sides",
        "modifier",
        "mode",
        "target",
        "label",
    ):
        assert name in properties
    assert properties["mode"]["enum"] == list(MODES)
    assert properties["count"]["minimum"] == 1


def test_the_schema_is_a_copy() -> None:
    tool_schema()["name"] = "tampered"
    assert tool_schema()["name"] == "roll_dice"


# -- the happy paths ------------------------------------------------------


def test_a_notation_call_rolls_it() -> None:
    tool, rng = make_tool(3, 4, 5)
    outcome = tool.run({"character": "Brannoc", "notation": "3d6"})
    assert outcome.text == "Brannoc rolls 3d6: 3 + 4 + 5 = 12"
    assert outcome.payload["dice"] == [3, 4, 5]
    assert rng.calls == [(1, 6)] * 3


def test_a_named_check_uses_its_own_pool_and_reading() -> None:
    tool, _ = make_tool(14)
    outcome = tool.run({"character": "Sable", "check": "stealth"})
    assert outcome.text == "Sable rolls Stealth 1d20+5: 14 + 5 = 19 vs 15 -> success (margin +4)"
    assert outcome.payload["success"] is True


def test_a_count_and_sides_call_works() -> None:
    tool, rng = make_tool(2, 5)
    outcome = tool.run({"character": "Orla", "count": 2, "sides": 8, "mode": "list"})
    assert outcome.text == "Orla rolls 2d8: [2, 5] -> total 7"
    assert rng.calls == [(1, 8), (1, 8)]


def test_a_check_can_be_read_as_hits_instead() -> None:
    tool, _ = make_tool(19)
    outcome = tool.run({"character": "Sable", "check": "stealth", "mode": "hits", "target": 18})
    assert outcome.payload["hits"] == 1
    assert outcome.payload["mode"] == "hits"


def test_the_default_character_is_used_when_the_model_omits_one() -> None:
    tool, _ = make_tool(6, default_character="Sable")
    assert tool.run({"notation": "d6"}).text.startswith("Sable rolls 1d6")


def test_the_label_defaults_to_the_check_name() -> None:
    tool, _ = make_tool(1, 2, 3)
    assert tool.run({"character": "B", "check": "brawn"}).payload["label"] == "Brawn"


def test_an_explicit_label_wins() -> None:
    tool, _ = make_tool(3)
    rolled = tool.run({"character": "B", "notation": "d6", "label": "Luck"})
    assert rolled.payload["label"] == "Luck"


# -- argument coercion ----------------------------------------------------


@pytest.mark.parametrize("count", ["3", 3.0, 3])
def test_numeric_strings_and_whole_floats_are_accepted(count) -> None:
    tool, _ = make_tool(1, 1, 1)
    assert len(tool.run({"character": "B", "count": count, "sides": 6}).payload["dice"]) == 3


@pytest.mark.parametrize(
    ("arguments", "fragment"),
    [
        ({"character": "B", "count": 2.5, "sides": 6}, "count must be a whole number"),
        ({"character": "B", "count": True, "sides": 6}, "count must be a whole number"),
        ({"character": "B", "count": "three", "sides": 6}, "count must be a whole number"),
        ({"character": "B", "count": 0, "sides": 6}, "dice count must be in"),
        ({"character": "B", "count": 1, "sides": 1}, "sides must be in"),
        ({"character": 7, "notation": "d6"}, "character must be a string"),
        ({"character": "B", "mode": "dance"}, "unknown mode"),
        ({"character": "B", "check": "stealth", "notation": "d6"}, "both a named check"),
        ({"character": "B", "check": "stealth", "count": 1, "sides": 6}, "both a named check"),
        ({"character": "B"}, "needs a named check"),
        ({}, "needs a character"),
        ({"character": "B", "check": "jump"}, "unknown check"),
        ({"character": "B", "notation": "banana"}, "not a dice expression"),
        ({"character": "B", "notation": "d6", "mode": "hits"}, "needs a target"),
    ],
)
def test_bad_arguments_get_readable_errors(arguments: dict, fragment: str) -> None:
    tool, rng = make_tool()
    with pytest.raises(DiceError, match=fragment):
        tool.run(arguments)
    assert rng.calls == [], "a rejected call must not consume randomness"


def test_unknown_arguments_are_ignored() -> None:
    tool, _ = make_tool(4)
    rolled = tool.run({"character": "B", "notation": "d6", "colour": "blue"})
    assert rolled.payload["total"] == 4


# -- JSON in, JSON out ----------------------------------------------------


def test_arguments_may_arrive_as_json() -> None:
    tool, _ = make_tool(6)
    assert tool.run_json(json.dumps({"character": "B", "notation": "d6"})).payload["total"] == 6


@pytest.mark.parametrize(
    ("text", "fragment"),
    [
        ("", "needs arguments"),
        ("   ", "needs arguments"),
        ("{not json", "not valid JSON"),
        ("[1, 2]", "must be an object"),
        ('"just a string"', "must be an object"),
    ],
)
def test_bad_json_is_rejected_with_a_reason(text: str, fragment: str) -> None:
    tool, _ = make_tool()
    with pytest.raises(DiceError, match=fragment):
        tool.run_json(text)


def test_the_payload_is_json_serialisable() -> None:
    tool, _ = make_tool(2, 2)
    payload = tool.run({"character": "B", "notation": "2d6"}).payload
    assert json.loads(json.dumps(payload))["notation"] == "2d6"

