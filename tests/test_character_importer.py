"""Importing the old workbook, once, into the native model."""

from __future__ import annotations

from pathlib import Path

import pytest

from ttrpg_chatbots.character.importer import (
    import_character,
    import_workbook,
    importable_names,
)
from ttrpg_chatbots.character.types import CharacterError

WORKBOOK = Path("custom_assets/My Character Sheets.xlsx")
CLOCK = "2026-10-17T00:00:00+00:00"

pytestmark = pytest.mark.skipif(
    not WORKBOOK.is_file(), reason="the personal workbook is git-ignored"
)


def test_every_character_with_both_tabs_is_importable() -> None:
    names = importable_names(WORKBOOK)
    # Only characters with an AQ *and* an HG tab can be imported: Aoife, Cormac and
    # Connor have interviews but their mechanics live on VDA/VM2/VMR tabs, which this
    # reader does not read yet.
    assert set(names) == {"Molly MacIntosh", "Robert Ross"}


def test_an_imported_character_is_ready_to_play() -> None:
    character = import_character(WORKBOOK, "Molly MacIntosh", clock=lambda: CLOCK)
    assert character.name == "Molly MacIntosh"
    assert character.system == "house-games"
    assert character.ready is True
    assert character.created == CLOCK
    assert [event.kind for event in character.history] == ["import", "sealed"]
    assert character.interview.answered == character.interview.total > 0


def test_the_mechanics_match_the_workbook() -> None:
    sheet = import_character(WORKBOOK, "Molly MacIntosh").sheet
    # Verified by hand against the HG Molly MacIntosh tab.
    assert sheet.attributes["Dexterity"] == 2
    assert sheet.attributes["Intelligence"] == 5
    assert sheet.ability("Alertness").rank == 4
    assert sheet.ability("Alertness").specialty == "Vision"
    assert sheet.ability("Stealth").rank == 0
    assert sheet.virtues["Courage"] == 2
    assert sheet.virtues["Self-Control/Instinct"] == 5
    assert sheet.willpower == 10
    assert sheet.morality == 8
    assert len(sheet.health) == 8


def test_merits_are_read_from_a_filled_block() -> None:
    # A filled tab puts its first merit in row 24, where the template has a header.
    merits = import_character(WORKBOOK, "Molly MacIntosh").sheet.meta["merits"]
    assert {"name": "Outsider (Clone Vat)", "points": 5} in merits
    assert not any(merit["name"].lower() == "name" for merit in merits)


def test_importing_everything_produces_distinct_characters() -> None:
    characters = import_workbook(WORKBOOK, clock=lambda: CLOCK)
    assert len(characters) == 2
    names = {character.name for character in characters}
    assert names == {"Molly MacIntosh", "Robert Ross"}
    assert all(character.interview is not None for character in characters)


def test_a_character_without_both_tabs_is_refused() -> None:
    with pytest.raises(CharacterError) as caught:
        import_character(WORKBOOK, "Nobody At All")
    assert "no interview" in str(caught.value) or "importable" in str(caught.value)


def test_a_missing_workbook_says_so(tmp_path: Path) -> None:
    with pytest.raises(CharacterError, match="cannot open workbook"):
        importable_names(tmp_path / "absent.xlsx")


def test_prose_in_a_stat_cell_is_recorded_not_fatal() -> None:
    # Robert's HG tab has a sentence in the Stamina cell instead of a number.
    character = import_character(WORKBOOK, "Robert Ross")
    notes = character.sheet.meta.get("notes", [])
    assert any(note.startswith("B9:") for note in notes)
    assert character.ready is True
