"""The neutral projection: trait lookup, name resolution, and validation."""

from __future__ import annotations

import pytest

from ttrpg_chatbots.sheets.types import (
    KNOWLEDGE,
    SKILL,
    TALENT,
    Ability,
    Sheet,
    Trait,
    UnknownTrait,
    normalise,
    resolve_name,
)


def test_names_normalise_the_way_people_type() -> None:
    assert normalise("  Animal   Ken ") == "animal ken"
    assert normalise("") == ""


def test_an_exact_name_wins() -> None:
    assert resolve_name("Stealth", ("Stealth", "Stealthy")) == "Stealth"


def test_a_unique_prefix_is_accepted() -> None:
    assert resolve_name("dex", ("Strength", "Dexterity")) == "Dexterity"
    assert resolve_name("perc", ("Perception", "Persuasion")) == "Perception"


def test_an_ambiguous_prefix_names_the_candidates() -> None:
    with pytest.raises(UnknownTrait) as caught:
        resolve_name("st", ("Strength", "Stamina"))
    message = str(caught.value)
    assert "ambiguous" in message
    assert "Stamina" in message and "Strength" in message
    # "per" is genuinely ambiguous too: Perception or Persuasion.
    with pytest.raises(UnknownTrait, match="ambiguous"):
        resolve_name("per", ("Perception", "Persuasion"))


def test_an_unknown_name_lists_what_exists() -> None:
    with pytest.raises(UnknownTrait, match="unknown trait"):
        resolve_name("flying", ("Strength", "Dexterity"))


def test_a_blank_name_is_refused() -> None:
    with pytest.raises(UnknownTrait, match="no trait name"):
        resolve_name("   ", ("Strength",))


def test_abilities_validate_themselves() -> None:
    with pytest.raises(ValueError, match="category"):
        Ability(name="Stealth", category="hobby")
    with pytest.raises(ValueError, match="rank"):
        Ability(name="Stealth", rank=11)
    with pytest.raises(ValueError, match="name"):
        Ability(name="  ")
    assert Ability(name="Stealth", rank=2).trained is True
    assert Ability(name="Stealth").trained is False


def test_traits_validate_themselves() -> None:
    with pytest.raises(ValueError, match="name"):
        Trait(name="")
    with pytest.raises(ValueError, match="dots"):
        Trait(name="Jaded", dots=-1)


def sheet() -> Sheet:
    return Sheet(
        name="Brannoc the Archivist",
        system="house-games",
        attributes={"Dexterity": 4, "Intelligence": 3},
        abilities={
            "Stealth": Ability(name="Stealth", rank=2, category=SKILL, specialty="alleys"),
            "Occult": Ability(name="Occult", rank=1, category=KNOWLEDGE),
            "Brawl": Ability(name="Brawl", rank=3, category=TALENT),
        },
        powers=(Trait(name="Auspex", dots=2),),
        backgrounds=(Trait(name="Mentor", dots=3),),
    )


def test_a_sheet_needs_a_name_and_a_system() -> None:
    with pytest.raises(ValueError, match="character name"):
        Sheet(name="  ", system="house-games")
    with pytest.raises(ValueError, match="system"):
        Sheet(name="Brannoc", system="")


def test_attributes_and_abilities_are_looked_up_loosely() -> None:
    character = sheet()
    assert character.attribute("dex") == 4
    assert character.ability("stealth").rank == 2
    assert character.ability("Stealth").specialty == "alleys"
    assert character.ability("brawl").category == TALENT


def test_an_absent_ability_can_be_asked_about_without_raising() -> None:
    character = sheet()
    assert character.find_ability("Firearms") is None
    with pytest.raises(UnknownTrait):
        character.ability("Firearms")


def test_traits_are_found_in_powers_and_backgrounds() -> None:
    character = sheet()
    assert character.trait("auspex").dots == 2
    assert character.trait("Mentor").dots == 3
    with pytest.raises(UnknownTrait, match="no trait"):
        character.trait("Generation")


def test_a_sheet_round_trips_to_json_ready_data() -> None:
    payload = sheet().as_dict()
    assert payload["id"] == "brannoc the archivist"
    assert payload["system"] == "house-games"
    assert payload["abilities"]["Stealth"] == {
        "rank": 2,
        "category": SKILL,
        "specialty": "alleys",
    }
    assert payload["powers"] == [{"name": "Auspex", "dots": 2}]
    assert payload["health"] == []
