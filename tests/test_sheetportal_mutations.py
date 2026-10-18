"""Spending rules: cost, caps and legality, in one place."""

from __future__ import annotations

import pytest

from ttrpg_chatbots.sheetportal.mutations import (
    MutationError,
    award_gift,
    cap_for,
    cost_of,
    explain,
    options,
    raise_trait,
    record_mission,
    resolve_kind,
)
from ttrpg_chatbots.sheets.types import Ability, Gift, Sheet, Trait


def sheet(**kwargs) -> Sheet:
    base = dict(
        name="Molly",
        system="house-games",
        attributes={"Dexterity": 2, "Strength": 1},
        abilities={
            "Stealth": Ability("Stealth", rank=2, category="skill"),
            "Alertness": Ability("Alertness", rank=4, category="talent", specialty="in the dark"),
        },
        virtues={"Courage": 3, "Conscience/Conviction": 3},
        willpower=3,
        willpower_remaining=3,
        morality=6,
        backgrounds=(Trait("Library", dots=2),),
        gifts=(Gift("Thanatosis", rating=1),),
        freebies=15,
        xp=0,
    )
    base.update(kwargs)
    return Sheet(**base)


# -- cost ------------------------------------------------------------------


def test_freebie_cost_is_flat_per_point() -> None:
    assert cost_of("attribute", 2, 3, pool="freebies") == 5
    assert cost_of("attribute", 2, 4, pool="freebies") == 10
    assert cost_of("ability", 0, 3, pool="freebies") == 6
    assert cost_of("background", 1, 2, pool="freebies") == 1


def test_experience_cost_is_priced_per_step() -> None:
    # Ability: 3 for the first rank, then rating x2.
    assert cost_of("ability", 0, 1, pool="xp") == 3
    assert cost_of("ability", 1, 3, pool="xp") == 2 + 4
    # Attribute: rating x4, so 2->4 is 8 + 12.
    assert cost_of("attribute", 2, 4, pool="xp") == 20


def test_going_backwards_is_free() -> None:
    assert cost_of("attribute", 4, 2, pool="freebies") == 0


def test_an_unknown_pool_is_refused() -> None:
    with pytest.raises(MutationError, match="unknown pool"):
        cost_of("attribute", 1, 2, pool="gold")


# -- caps ------------------------------------------------------------------


def test_caps_come_from_the_rules() -> None:
    assert cap_for(sheet(), "attribute", "Dexterity") == 5
    assert cap_for(sheet(), "background", "Library") == 5
    assert cap_for(sheet(), "willpower", "willpower") == 10
    assert cap_for(sheet(veteran=True), "background", "Library") == 8


def test_a_gift_can_raise_a_cap_for_one_trait() -> None:
    raised = sheet(meta={"caps": {"Dexterity": 8}})
    assert cap_for(raised, "attribute", "Dexterity") == 8
    assert cap_for(raised, "attribute", "Strength") == 5


def test_raising_above_the_cap_is_refused() -> None:
    with pytest.raises(MutationError, match="capped at 5"):
        raise_trait(sheet(), "Dexterity", to=6)


def test_raising_to_the_current_value_is_refused() -> None:
    with pytest.raises(MutationError, match="already 2"):
        raise_trait(sheet(), "Dexterity", to=2)


# -- spending --------------------------------------------------------------


def test_raising_spends_and_reports() -> None:
    receipt = raise_trait(sheet(), "Stealth", to=3)
    assert receipt.sheet.ability("Stealth").rank == 3
    assert receipt.spent == {"freebies": 2}
    assert receipt.remaining == {"freebies": 13}
    assert str(receipt) == "Stealth 2→3 — 2 freebies — 13 freebies left"


def test_other_traits_are_untouched() -> None:
    receipt = raise_trait(sheet(), "Stealth", to=3)
    assert receipt.sheet.attributes == {"Dexterity": 2, "Strength": 1}
    assert receipt.sheet.ability("Alertness").specialty == "in the dark"
    assert receipt.sheet.backgrounds == (Trait("Library", dots=2),)


def test_an_unaffordable_raise_says_what_it_costs() -> None:
    with pytest.raises(MutationError, match="costs 15 freebies; Molly has 5"):
        raise_trait(sheet(freebies=5), "Dexterity", to=5)


def test_experience_spending_uses_the_advancement_table() -> None:
    # Attribute 2->4 is 2x4 + 3x4 = 20 xp, priced step by step.
    receipt = raise_trait(sheet(xp=20), "Dexterity", to=4, pool="xp")
    assert receipt.spent == {"xp": 20}
    assert receipt.sheet.xp == 0


def test_willpower_remaining_is_not_inflated_by_raising_the_rating() -> None:
    receipt = raise_trait(sheet(), "Willpower", to=5)
    assert receipt.sheet.willpower == 5
    assert receipt.sheet.willpower_remaining == 3


def test_lowering_is_allowed_and_costs_nothing() -> None:
    receipt = raise_trait(sheet(), "Alertness", to=2)
    assert receipt.sheet.ability("Alertness").rank == 2
    assert receipt.spent == {"freebies": 0}


def test_an_unknown_trait_lists_what_exists() -> None:
    with pytest.raises(MutationError, match="no trait called 'Flying'"):
        raise_trait(sheet(), "Flying", to=1)


def test_kind_is_inferred_or_named() -> None:
    assert resolve_kind(sheet(), "Stealth") == "ability"
    assert resolve_kind(sheet(), "Library") == "background"
    assert resolve_kind(sheet(), "Courage") == "virtue"
    assert resolve_kind(sheet(), "morality") == "morality"
    assert resolve_kind(sheet(), "Anything", "attribute") == "attribute"
    with pytest.raises(MutationError, match="unknown trait kind"):
        resolve_kind(sheet(), "Stealth", "spaceship")


# -- gifts and missions ----------------------------------------------------


def test_a_gift_costs_nothing_and_counts() -> None:
    receipt = award_gift(sheet(), "Walking Fire", description="Moving x5")
    assert receipt.sheet.gift_count == 2
    assert receipt.spent == {}
    assert receipt.sheet.gift("Walking Fire").rating is None
    assert "gained Walking Fire (flat)" in receipt.lines[0]


def test_the_same_gift_cannot_be_taken_twice() -> None:
    with pytest.raises(MutationError, match="already holds a Gift"):
        award_gift(sheet(), "thanatosis")


def test_crossing_a_tier_is_reported() -> None:
    nearly = sheet(gifts=tuple(Gift(f"g{n}") for n in range(9)))
    receipt = award_gift(nearly, "the tenth")
    assert any("now Seasoned" in warning for warning in receipt.warnings)


def test_a_win_gives_xp_and_a_gift() -> None:
    receipt = record_mission(sheet(), "win", gift="Auspex", rating=2)
    assert receipt.sheet.xp == 10
    assert receipt.sheet.gift_count == 2
    assert receipt.sheet.gift("Auspex").rating == 2


def test_a_surviving_loss_gives_xp_but_no_gift() -> None:
    receipt = record_mission(sheet(), "loss")
    assert receipt.sheet.xp == 5
    assert receipt.sheet.gift_count == 1
    assert receipt.warnings == ()


def test_a_win_without_a_named_gift_warns_about_the_debt() -> None:
    receipt = record_mission(sheet(), "win")
    assert receipt.sheet.xp == 10
    assert any("Gift is owed" in warning for warning in receipt.warnings)


def test_an_unknown_outcome_is_refused() -> None:
    with pytest.raises(MutationError, match="unknown outcome"):
        record_mission(sheet(), "draw")


# -- planning --------------------------------------------------------------


def test_options_lists_only_what_can_be_raised() -> None:
    listed = options(sheet(backgrounds=(Trait("Library", dots=5),)))
    assert any(line.startswith("Dexterity 2→3: 5 freebies") for line in listed)
    assert any(line.startswith("Alertness 4→5") for line in listed)
    # Library is already at its cap, so it cannot be raised.
    assert not any(line.startswith("Library") for line in listed)


def test_options_prices_by_pool() -> None:
    assert "Dexterity 2→3: 8 xp" in options(sheet(), pool="xp")


def test_explain_names_the_trait_and_its_cap() -> None:
    assert explain(sheet(), "Stealth") == "Stealth: 2 of 5 (skill)"
    assert explain(sheet(), "Alertness") == "Alertness: 4 of 5 (talent, in the dark)"

