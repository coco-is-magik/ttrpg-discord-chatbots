"""Named checks: loading, lookup, and validation that stops a typo rolling silently."""

from __future__ import annotations

import pytest

from dice_support import DEMO_WORLD
from ttrpg_chatbots.dice.checks import Checkbook, checks_from_records, load_checks
from ttrpg_chatbots.dice.types import CheckError


def book(*records: dict) -> Checkbook:
    return Checkbook(checks_from_records(records))


def one(**record: object) -> Checkbook:
    base = {"id": "stealth", "count": 1, "sides": 20, "mode": "check", "target": 10}
    return book({**base, **record})


def test_the_demo_world_has_checks() -> None:
    checks = load_checks(DEMO_WORLD)
    assert len(checks) == 5
    assert checks.names == ("brawn", "luck", "perception", "persuasion", "stealth")


def test_a_check_is_found_by_id_label_or_alias() -> None:
    checks = load_checks(DEMO_WORLD)
    assert checks.get("stealth").id == "stealth"
    assert checks.get("Stealth").id == "stealth"
    assert checks.get(" SNEAK ").id == "stealth"
    assert checks.get("hide").id == "stealth"


def test_the_pool_and_the_reading_come_across() -> None:
    checks = load_checks(DEMO_WORLD)
    stealth = checks.get("stealth")
    assert stealth.spec.notation == "1d20+5"
    assert (stealth.spec.mode, stealth.spec.target) == ("check", 15)

    perception = checks.get("perception")
    assert (perception.spec.count, perception.spec.sides) == (5, 10)
    assert (perception.spec.mode, perception.spec.target) == ("hits", 8)


def test_the_notation_shorthand_is_accepted() -> None:
    assert book({"id": "brawn", "notation": "3d6"}).get("brawn").spec.notation == "3d6"


def test_the_label_defaults_to_the_id() -> None:
    assert one(id="climb").get("climb").name == "climb"


def test_unknown_fields_are_kept_in_meta() -> None:
    check = one(source="handbook", weight=2).get("stealth")
    assert check.meta == {"source": "handbook", "weight": 2}


def test_an_unknown_check_lists_what_exists() -> None:
    with pytest.raises(CheckError) as caught:
        load_checks(DEMO_WORLD).get("jump")
    assert "unknown check" in str(caught.value)
    assert "stealth" in str(caught.value)


def test_the_longest_name_wins() -> None:
    checks = book(
        {"id": "sneak", "count": 1, "sides": 6},
        {"id": "sneak-attack", "label": "sneak attack", "count": 2, "sides": 6},
    )
    assert checks.find("roll sneak attack").id == "sneak-attack"
    assert checks.find("roll sneak").id == "sneak"


def test_matching_is_on_whole_words() -> None:
    checks = one()
    assert checks.find("roll stealthy") is None
    assert checks.find("roll stealth.") is not None
    assert checks.find("i said 0") is None


def test_a_missing_file_means_no_checks(tmp_path) -> None:
    assert len(load_checks(tmp_path)) == 0


def test_overrides_can_read_the_same_pool_differently() -> None:
    stealth = load_checks(DEMO_WORLD).get("stealth")
    as_hits = stealth.with_overrides(mode="hits", target=18)
    assert (as_hits.mode, as_hits.target) == ("hits", 18)
    assert as_hits.count == stealth.spec.count
    assert stealth.with_overrides() is stealth.spec


@pytest.mark.parametrize(
    ("record", "fragment"),
    [
        ({}, "'id' must be"),
        ({"id": "  "}, "'id' must be"),
        ({"id": "x", "count": 1}, "missing required 'sides'"),
        ({"id": "x", "count": 1, "sides": 6, "mode": "nope"}, "'mode' must be one of"),
        ({"id": "x", "count": 1, "sides": 6, "mode": "check"}, "needs a 'target'"),
        ({"id": "x", "count": 1, "sides": 6, "mode": "hits"}, "needs a 'target'"),
        ({"id": "x", "notation": "3d6", "count": 3}, "not both"),
        ({"id": "x", "notation": "banana"}, "not a dice expression"),
        ({"id": "x", "count": True, "sides": 6}, "whole number"),
        ({"id": "x", "count": 1, "sides": 6, "aliases": "sneak"}, "list of non-blank"),
        ({"id": "x", "count": 1, "sides": 6, "label": ""}, "'label' must be"),
        ({"id": "x", "count": 1, "sides": 6, "mode": 3}, "'mode' must be a string"),
    ],
)
def test_bad_records_are_located(record: dict, fragment: str) -> None:
    with pytest.raises(CheckError, match=fragment):
        checks_from_records([record], source="checks.jsonl")


def test_a_bad_record_says_which_line_it_was() -> None:
    with pytest.raises(CheckError, match=r"checks\.jsonl record 2 \(x\)"):
        checks_from_records(
            [{"id": "ok", "count": 1, "sides": 6}, {"id": "x", "count": 1}],
            source="checks.jsonl",
        )


def test_duplicate_ids_and_shared_names_are_refused() -> None:
    first = checks_from_records([{"id": "a", "count": 1, "sides": 6}])[0]
    again = checks_from_records([{"id": "a", "count": 2, "sides": 6}])[0]
    with pytest.raises(CheckError, match="duplicate check id"):
        Checkbook([first, again])

    one_check = checks_from_records(
        [{"id": "one", "aliases": ["shared"], "count": 1, "sides": 6}]
    )[0]
    two_check = checks_from_records(
        [{"id": "two", "aliases": ["shared"], "count": 1, "sides": 6}]
    )[0]
    with pytest.raises(CheckError, match="used by both"):
        Checkbook([one_check, two_check])
