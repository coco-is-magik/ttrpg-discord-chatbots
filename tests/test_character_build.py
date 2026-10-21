"""Creation budgets, flaws, and the submit gate."""

from __future__ import annotations

import pytest

from ttrpg_chatbots.character.build import (
    Build,
    BuildError,
    ability_spent,
    attribute_spent,
    group_remaining,
    problems,
    remaining,
)
from ttrpg_chatbots.character.creation import blank_sheet
from ttrpg_chatbots.character.types import Character
from ttrpg_chatbots.sheetportal import mutations as m
from ttrpg_chatbots.sheets.interview import Interview, Question
from ttrpg_chatbots.sheets.types import Ability, Sheet, Trait


def filled() -> Sheet:
    """A sheet whose budgets are spent exactly."""
    sheet = blank_sheet("Ailis Vane")
    attributes = dict(sheet.attributes)
    attributes.update({"Strength": 4, "Dexterity": 4, "Stamina": 2})  # Physical +7
    attributes.update({"Charisma": 3, "Manipulation": 3, "Appearance": 2})  # Social +5
    attributes.update({"Perception": 2, "Intelligence": 2, "Wits": 2})  # Mental +3
    abilities = dict(sheet.abilities)
    for name, rank, category in (
        ("Alertness", 5, "talent"),
        ("Athletics", 4, "talent"),
        ("Brawl", 4, "talent"),
        ("Stealth", 5, "skill"),
        ("Melee", 4, "skill"),
        ("Occult", 5, "knowledge"),
    ):
        abilities[name] = Ability(name, rank=rank, category=category)
    return Sheet(
        name=sheet.name,
        system=sheet.system,
        attributes=attributes,
        abilities=abilities,
        virtues={"Conscience/Conviction": 4, "Self-Control/Instinct": 2, "Courage": 4},
        willpower=4,
        willpower_remaining=4,
        morality=6,
        health=sheet.health,
        backgrounds=(Trait("Mentor", dots=3), Trait("Contacts", dots=2)),
        freebies=15,
    )


# -- the build ---------------------------------------------------------------


def test_defaults_are_the_books_example_assignment() -> None:
    build = Build()
    assert build.attributes == {"Physical": 7, "Social": 5, "Mental": 3}
    assert build.abilities == {"talent": 13, "skill": 9, "knowledge": 5}
    assert build.virtues == 7 and build.backgrounds == 5


def test_budgets_must_be_a_permutation_of_the_rules() -> None:
    with pytest.raises(BuildError, match="attribute budgets"):
        Build(attributes={"Physical": 6, "Social": 5, "Mental": 3})
    with pytest.raises(BuildError, match="ability groups"):
        Build(abilities={"talent": 13, "skill": 9})
    with pytest.raises(BuildError, match="virtues are fixed"):
        Build(virtues=9)


def test_a_blank_sheet_starts_at_the_rules_floor() -> None:
    sheet = blank_sheet("Ailis")
    assert set(sheet.attributes.values()) == {1}
    assert set(sheet.virtues.values()) == {1}
    assert sum(ability.rank for ability in sheet.abilities.values()) == 0
    assert sheet.freebies == 15
    assert not sheet.backgrounds


def test_spending_is_measured_against_the_floor() -> None:
    sheet = blank_sheet("Ailis")
    assert attribute_spent(sheet) == {"Physical": 0, "Social": 0, "Mental": 0}
    assert ability_spent(sheet) == {"talent": 0, "skill": 0, "knowledge": 0}


def test_a_blank_sheet_has_every_budget_unspent() -> None:
    left = remaining(blank_sheet("Ailis"), Build())
    assert left["attributes"] == {"Physical": 7, "Social": 5, "Mental": 3}
    assert left["virtues"] == {"Virtues": 7}
    assert left["backgrounds"] == {"Backgrounds": 5}


def test_exact_spending_leaves_no_problems() -> None:
    assert problems(filled(), Build()) == ()


def test_an_overspent_group_is_reported() -> None:
    sheet = filled()
    greedy = Sheet(**{**sheet.__dict__, "attributes": {**sheet.attributes, "Strength": 5}})
    assert any("over budget" in line for line in problems(greedy, Build()))


def test_group_remaining_names_the_group() -> None:
    sheet = blank_sheet("Ailis")
    assert group_remaining(sheet, "Strength", "attribute") == 7
    assert group_remaining(sheet, "Stealth", "ability") == 9
    assert group_remaining(sheet, "Courage", "virtue") == 7


# -- building through the portal ----------------------------------------------


def test_raising_in_a_build_costs_one_point_and_no_freebies() -> None:
    receipt = m.raise_in_build(blank_sheet("Ailis"), "Strength", to=3, build=Build())
    assert receipt.sheet.attribute("Strength") == 3
    assert receipt.sheet.freebies == 15  # budgets are not freebies
    assert group_remaining(receipt.sheet, "Strength", "attribute") == 5


def test_a_build_refuses_to_overspend_a_group() -> None:
    # Talents have 13 points; three talents at 5/5/4 want 14.
    sheet = blank_sheet("Ailis")
    sheet = m.raise_in_build(sheet, "Alertness", to=5, build=Build()).sheet
    sheet = m.raise_in_build(sheet, "Athletics", to=5, build=Build()).sheet
    with pytest.raises(m.MutationError, match="budget has 3 left"):
        m.raise_in_build(sheet, "Brawl", to=4, build=Build())


def test_a_build_respects_the_trait_cap_too() -> None:
    with pytest.raises(m.MutationError, match="capped at 5"):
        m.raise_in_build(blank_sheet("Ailis"), "Strength", to=9, build=Build())


def test_lowering_in_a_build_gives_the_point_back() -> None:
    raised = m.raise_in_build(blank_sheet("Ailis"), "Strength", to=4, build=Build()).sheet
    lowered = m.raise_in_build(raised, "Strength", to=2, build=Build()).sheet
    assert group_remaining(lowered, "Strength", "attribute") == 6


# -- flaws --------------------------------------------------------------------


def test_a_flaw_pays_freebies() -> None:
    receipt = m.add_flaw(blank_sheet("Ailis"), "Enemy", rating=2)
    assert receipt.sheet.freebies == 17
    assert receipt.sheet.flaw_points == 2
    assert "Enemy" in receipt.lines[0]


def test_flaws_are_capped_unless_there_are_exactly_two() -> None:
    sheet = blank_sheet("Ailis")
    sheet = m.add_flaw(sheet, "Enemy", rating=3).sheet
    sheet = m.add_flaw(sheet, "Phobia", rating=3).sheet
    with pytest.raises(m.MutationError, match="capped at 7"):
        m.add_flaw(sheet, "Notoriety", rating=3)


def test_two_flaws_may_total_anything() -> None:
    sheet = m.add_flaw(blank_sheet("Ailis"), "Enemy", rating=5).sheet
    sheet = m.add_flaw(sheet, "Dark Secret", rating=5).sheet
    assert sheet.flaw_points == 10
    assert sheet.freebies == 25


def test_the_same_flaw_cannot_be_taken_twice() -> None:
    sheet = m.add_flaw(blank_sheet("Ailis"), "Enemy", rating=2).sheet
    with pytest.raises(m.MutationError, match="already has the flaw"):
        m.add_flaw(sheet, "enemy", rating=1)


def test_removing_a_flaw_takes_its_freebies_back() -> None:
    sheet = m.add_flaw(blank_sheet("Ailis"), "Enemy", rating=2).sheet
    receipt = m.remove_flaw(sheet, "Enemy")
    assert receipt.sheet.freebies == 15
    assert receipt.sheet.flaws == ()


def test_a_flaw_whose_points_are_spent_cannot_be_removed() -> None:
    sheet = m.add_flaw(blank_sheet("Ailis"), "Enemy", rating=4).sheet
    spent = Sheet(**{**sheet.__dict__, "freebies": 2})
    with pytest.raises(m.MutationError, match="already spent"):
        m.remove_flaw(spent, "Enemy")


# -- submitting ---------------------------------------------------------------


def complete_character() -> Character:
    interview = Interview(
        character="Ailis Vane",
        questions=(Question(prompt="Where from?", answer="Glasgow."),),
    )
    return Character(sheet=filled(), interview=interview, build=Build())


def test_a_complete_build_submits() -> None:
    from ttrpg_chatbots.bot import _submit

    sealed = _submit(complete_character())
    assert sealed.sealed is True
    assert sealed.build is None  # budgets are archived on submit
    assert sealed.ready is True


def test_an_incomplete_build_is_refused_with_reasons() -> None:
    from ttrpg_chatbots.bot import _submit

    character = Character(
        sheet=blank_sheet("Ailis"),
        interview=Interview(character="Ailis", questions=(Question("Why?", ""),)),
        build=Build(),
    )
    with pytest.raises(Exception) as caught:
        _submit(character)
    message = str(caught.value)
    assert "not ready to submit" in message
    assert "Physical: 7 point(s) unspent" in message
    assert "unanswered: Why?" in message


# -- the assignment is the player's choice ------------------------------------


def test_any_group_may_take_any_budget() -> None:
    build = Build().assigned("attributes", ("Mental", "Physical", "Social"))
    assert build.attributes == {"Mental": 7, "Physical": 5, "Social": 3}

    abilities = Build().assigned("abilities", ("skill", "knowledge", "talent"))
    assert abilities.abilities == {"skill": 13, "knowledge": 9, "talent": 5}


def test_an_assignment_must_name_each_group_once() -> None:
    with pytest.raises(BuildError, match="exactly once"):
        Build().assigned("attributes", ("Physical", "Physical", "Social"))
    with pytest.raises(BuildError, match="exactly once"):
        Build().assigned("abilities", ("talent", "skill", "skill"))
    with pytest.raises(BuildError, match="unknown section"):
        Build().assigned("virtues", ("Physical", "Social", "Mental"))


def test_attributes_from_the_wrong_section_are_refused() -> None:
    with pytest.raises(BuildError, match="exactly once"):
        Build().assigned("attributes", ("talent", "skill", "knowledge"))


def test_reassigning_moves_the_budgets_not_the_spend() -> None:
    sheet = blank_sheet("Ailis")
    sheet = m.raise_in_build(sheet, "Strength", to=4, build=Build()).sheet  # 3 in Physical
    # Physical had 7; giving it 3 leaves it 0 over, which is not allowed.
    moved = Build().assigned("attributes", ("Social", "Mental", "Physical"))
    over = [line for line in problems(sheet, moved) if "over budget" in line]
    assert over == []  # 3 spent against a 3 budget fits exactly
    assert problems(sheet, moved)  # but the other groups are now unspent


def test_a_moved_budget_that_cannot_fit_is_detectable() -> None:
    sheet = blank_sheet("Ailis")
    sheet = m.raise_in_build(sheet, "Strength", to=5, build=Build()).sheet  # 4 in Physical
    moved = Build().assigned("attributes", ("Social", "Mental", "Physical"))
    over = [line for line in problems(sheet, moved) if "over budget" in line]
    assert over == ["Physical: 1 point(s) over budget"]


# -- Morality and Willpower begin as sums of virtues --------------------------


def test_morality_and_willpower_follow_the_virtues_while_building() -> None:
    from ttrpg_chatbots.character.build import derive_trackers

    sheet = blank_sheet("Ailis")
    assert (sheet.morality, sheet.willpower) == (2, 1)  # three virtues at 1

    raised = m.raise_in_build(sheet, "Courage", to=4, build=Build()).sheet
    assert raised.willpower == 4  # "WILLPOWER begins equal to Courage"
    assert raised.willpower_remaining == 4

    conviction = m.raise_in_build(raised, "Conscience/Conviction", to=4, build=Build()).sheet
    # Conviction 4 + Self-Control 1: "MORALITY begins equal to Conviction + Self-Control".
    assert conviction.morality == 5
    assert derive_trackers(conviction).morality == 5


def test_freeing_a_virtue_lowers_the_trackers_again() -> None:
    sheet = blank_sheet("Ailis")
    sheet = m.raise_in_build(sheet, "Courage", to=5, build=Build()).sheet
    assert sheet.willpower == 5
    sheet = m.raise_in_build(sheet, "Courage", to=2, build=Build()).sheet
    assert sheet.willpower == 2
