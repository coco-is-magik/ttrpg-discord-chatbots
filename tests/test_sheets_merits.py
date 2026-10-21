"""Merits and flaws: book prices, custom values, and the catalogue itself."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ttrpg_chatbots.sheets.merits import Catalogue, MeritEntry, MeritError, load_catalogue
from ttrpg_chatbots.sheets.types import Sheet, Trait
from ttrpg_chatbots.sheetportal import mutations as mutate
from ttrpg_chatbots.sheetportal.mutations import MutationError


def sheet(**kwargs) -> Sheet:
    kwargs.setdefault("freebies", 15)
    return Sheet(name="Ailis", system="house-games", **kwargs)


FIXED = MeritEntry(
    name="Ambidextrous", kind="merit", minimum=1, maximum=1,
    source="Changeling Players Guide", page=23,
)
RATED = MeritEntry(
    name="Enemy", kind="flaw", minimum=1, maximum=5,
    source="Changeling Players Guide", page=31,
)
# The index really does contain a six-point flaw.
BLIND = MeritEntry(name="Blind", kind="flaw", minimum=6, maximum=6, source="Vampire", page=22)


def book(*entries: MeritEntry) -> Catalogue:
    return Catalogue(tuple(entries))


# -- the catalogue ---------------------------------------------------------


def test_an_entry_labels_fixed_and_rated_values() -> None:
    assert FIXED.fixed is True and FIXED.label == "1"
    assert RATED.fixed is False and RATED.label == "1-5"
    assert BLIND.fixed is True and BLIND.label == "6"
    assert "Changeling Players Guide p23" in FIXED.describe()


def test_lookup_is_case_insensitive_and_kind_aware() -> None:
    entries = book(FIXED, RATED)
    assert entries.lookup("ambidextrous").name == "Ambidextrous"
    assert entries.lookup("ENEMY").kind == "flaw"
    assert entries.lookup("nothing here") is None


def test_search_matches_part_of_a_name() -> None:
    entries = book(
        FIXED, MeritEntry(name="Natural Linguist", kind="merit", minimum=2, maximum=2)
    )
    assert [entry.name for entry in entries.search("lingu")] == ["Natural Linguist"]
    assert entries.search("ver") == ()


def test_a_missing_index_is_an_empty_catalogue(tmp_path: Path) -> None:
    # A group that has not built the index can still make custom merits.
    assert len(load_catalogue(tmp_path / "absent.json")) == 0


def test_a_broken_index_says_where(tmp_path: Path) -> None:
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    with pytest.raises(MeritError, match="cannot read the merit catalogue"):
        load_catalogue(broken)


def test_an_index_loads_and_keeps_kinds_apart(tmp_path: Path) -> None:
    path = tmp_path / "book.json"
    path.write_text(
        json.dumps(
            {
                "merits": [{"name": "Ambidextrous", "min": 1, "max": 1, "source": "Book"}],
                "flaws": [{"name": "Enemy", "min": 1, "max": 5}],
            }
        ),
        encoding="utf-8",
    )
    entries = load_catalogue(path)
    assert len(entries) == 2
    assert entries.lookup("enemy").kind == "flaw"
    assert entries.names("merit") == ("Ambidextrous",)


def test_an_entry_with_bad_points_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"merits": [{"name": "X", "min": "one"}]}), encoding="utf-8")
    with pytest.raises(MeritError, match="whole numbers"):
        load_catalogue(path)


# -- taking a merit --------------------------------------------------------


def test_a_fixed_cost_merit_prices_itself() -> None:
    receipt = mutate.add_merit(sheet(), "Ambidextrous", catalogue=book(FIXED))
    assert receipt.sheet.freebies == 14
    assert receipt.sheet.merits == (Trait("Ambidextrous", 1),)
    assert "Changeling Players Guide" in str(receipt)


def test_a_rated_merit_needs_an_explicit_value() -> None:
    entries = book(MeritEntry(name="Natural", kind="merit", minimum=1, maximum=3))
    with pytest.raises(MutationError, match="give it explicitly"):
        mutate.add_merit(sheet(), "Natural", catalogue=entries)


def test_a_custom_merit_names_its_own_price() -> None:
    receipt = mutate.add_merit(sheet(), "Knows a Guy", points=2, catalogue=book(FIXED))
    assert receipt.sheet.freebies == 13
    assert "custom, group-approved" in str(receipt)


def test_a_merit_costs_freebies_the_sheet_does_not_have() -> None:
    with pytest.raises(MutationError, match="costs 5 freebies"):
        mutate.add_merit(sheet(freebies=1), "Eagle Eyes", points=5)


def test_a_merit_above_its_book_rating_is_refused() -> None:
    entries = book(MeritEntry(name="Natural", kind="merit", minimum=1, maximum=2))
    with pytest.raises(MutationError, match="is rated 1-2"):
        mutate.add_merit(sheet(), "Natural", points=4, catalogue=entries)


def test_a_merit_cannot_be_taken_twice() -> None:
    once = mutate.add_merit(sheet(), "Ambidextrous", catalogue=book(FIXED)).sheet
    with pytest.raises(MutationError, match="already has the merit"):
        mutate.add_merit(once, "ambidextrous", catalogue=book(FIXED))


def test_removing_a_merit_refunds_it() -> None:
    taken = mutate.add_merit(sheet(), "Ambidextrous", catalogue=book(FIXED)).sheet
    receipt = mutate.remove_merit(taken, "Ambidextrous")
    assert receipt.sheet.freebies == 15
    assert receipt.sheet.merits == ()


def test_removing_an_absent_merit_lists_what_exists() -> None:
    with pytest.raises(MutationError, match="no merit 'Iron Will'"):
        mutate.remove_merit(sheet(), "Iron Will")


# -- flaws from the index --------------------------------------------------


def test_a_flaw_may_be_rated_from_the_index() -> None:
    receipt = mutate.add_flaw(sheet(), "Enemy", rating=3, catalogue=book(RATED))
    assert receipt.sheet.freebies == 18
    assert "+3 freebies" in str(receipt)


def test_a_flaw_above_its_book_rating_is_refused() -> None:
    with pytest.raises(MutationError, match="is rated 1-5"):
        mutate.add_flaw(sheet(), "Enemy", rating=6, catalogue=book(RATED))


def test_a_six_point_flaw_is_allowed_because_the_index_has_one() -> None:
    receipt = mutate.add_flaw(sheet(), "Blind", rating=6, catalogue=book(BLIND))
    assert receipt.sheet.freebies == 21


def test_a_custom_flaw_takes_any_value_within_the_cap() -> None:
    receipt = mutate.add_flaw(sheet(), "Cursed Tattoo", rating=7, catalogue=book())
    assert receipt.sheet.flaw_points == 7
    with pytest.raises(MutationError, match="rated 1..10"):
        mutate.add_flaw(sheet(), "Too Much", rating=11, catalogue=book())


def test_flaw_totals_still_follow_the_house_rule() -> None:
    once = mutate.add_flaw(sheet(), "Enemy", rating=4, catalogue=book()).sheet
    # Two flaws may total anything…
    twice = mutate.add_flaw(once, "Dark Secret", rating=5, catalogue=book()).sheet
    assert twice.flaw_points == 9
    # …but a third is bounded by the seven-point cap.
    with pytest.raises(MutationError, match="capped at 7"):
        mutate.add_flaw(twice, "Phobia", rating=1, catalogue=book())


def test_buying_off_a_flaw_costs_its_points() -> None:
    taken = mutate.add_flaw(sheet(), "Enemy", rating=3, catalogue=book()).sheet
    receipt = mutate.remove_flaw(taken, "Enemy")
    assert receipt.sheet.freebies == 15
    assert "3 freebies" in str(receipt)


def test_merits_and_flaws_survive_a_round_trip() -> None:
    from ttrpg_chatbots.sheets.types import sheet_from_dict

    character = sheet(merits=(Trait("Ambidextrous", 1),), flaws=(Trait("Enemy", 3),))
    again = sheet_from_dict(character.as_dict())
    assert again.merits == character.merits
    assert again.flaws == character.flaws
    assert again.merit_points == 1
    assert again.flaw_points == 3

