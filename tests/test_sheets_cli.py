"""The sheets CLI: tabs, a summary, and a roll read off a real workbook."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sheets_support import (
    HOUSE_MERGES,
    house_cells,
    house_workbook,
    questionnaire_workbook,
    write_workbook,
)
from ttrpg_chatbots.sheets import cli

REAL = Path(__file__).resolve().parents[1] / "custom_assets" / "My Character Sheets.xlsx"


def build(tmp_path, **cells):
    return house_workbook(tmp_path / "house.xlsx", extra_tabs=("Second Tab",), **cells)


def run(capsys, *argv: str) -> tuple[int, str, str]:
    code = cli.main(list(argv))
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_tabs_are_listed_in_order(tmp_path, capsys) -> None:
    code, out, _ = run(capsys, "--xlsx", str(build(tmp_path)), "--list-tabs")
    assert code == 0
    assert out.splitlines() == ["House Games", "Second Tab"]


def test_a_summary_shows_the_blocks(tmp_path, capsys) -> None:
    path = build(
        tmp_path,
        attributes={"Dexterity": 4},
        abilities={"Stealth": 2},
        specialties={"Stealth": "alleys"},
        virtues={"Courage": 3},
        gifts={"Auspex": 2},
        merits={"Jaded": 2},
    )
    code, out, _ = run(capsys, "--xlsx", str(path))
    assert code == 0
    assert "house-games: Brannoc the Archivist" in out
    assert "Dexterity 4" in out
    assert "Stealth 2 (alleys)" in out
    assert "Courage 3" in out
    assert "Auspex 2" in out
    assert "Jaded (+2)" in out


def test_the_house_games_tab_is_chosen_even_when_not_first(tmp_path, capsys) -> None:
    path = write_workbook(
        tmp_path / "book.xlsx",
        {"Cover": {"A1": "notes"}, "House Games": house_cells(abilities={"Stealth": 2})},
        merges={"House Games": HOUSE_MERGES},
    )
    code, out, _ = run(capsys, "--xlsx", str(path))
    assert code == 0
    assert "Brannoc the Archivist" in out


def test_the_same_seed_rolls_the_same_dice(tmp_path, capsys) -> None:
    path = build(tmp_path, attributes={"Dexterity": 3}, abilities={"Stealth": 2})
    argv = ("--xlsx", str(path), "--roll", "Dex+Stealth", "--seed", "7")
    first = run(capsys, *argv)[1]
    second = run(capsys, *argv)[1]
    assert first == second
    assert "difficulty 6" in first
    assert "successes" in first


def test_the_roll_uses_the_sheet(tmp_path, capsys) -> None:
    path = build(tmp_path, attributes={"Dexterity": 3}, abilities={"Stealth": 2})
    _, out, _ = run(capsys, "--xlsx", str(path), "--roll", "Dexterity+Stealth", "--seed", "3")
    # 3 dice of Attribute + 2 of Ability = five dice in the bracket.
    assert out.count(",") == 4


def test_willpower_is_reported(tmp_path, capsys) -> None:
    path = build(tmp_path, attributes={"Dexterity": 3})
    _, out, _ = run(
        capsys, "--xlsx", str(path), "--roll", "Dexterity", "--willpower", "--seed", "1"
    )
    assert "Willpower" in out


def test_json_output_is_machine_readable(tmp_path, capsys) -> None:
    path = build(tmp_path, attributes={"Dexterity": 3}, abilities={"Stealth": 2})
    code, out, _ = run(
        capsys, "--xlsx", str(path), "--roll", "Dex+Stealth", "--seed", "5", "--json"
    )
    payload = json.loads(out)
    assert code == 0
    assert payload["sheet"]["name"] == "Brannoc the Archivist"
    assert payload["pool"]["dice"] == 5
    assert payload["pool"]["difficulty"] == 6
    assert len(payload["result"]["rolls"]) == 5
    assert payload["text"].startswith("Brannoc the Archivist rolls Dexterity + Stealth")


def test_an_unknown_ability_exits_two(tmp_path, capsys) -> None:
    code, _, err = run(capsys, "--xlsx", str(build(tmp_path)), "--roll", "Dex+Flying")
    assert code == 2
    assert "Alertness" in err


def test_an_untrained_knowledge_exits_two(tmp_path, capsys) -> None:
    path = build(tmp_path, attributes={"Intelligence": 3})
    code, _, err = run(capsys, "--xlsx", str(path), "--roll", "Int+Academics")
    assert code == 2
    assert "untrained knowledges" in err


def test_a_missing_workbook_exits_two(tmp_path, capsys) -> None:
    code, _, err = run(capsys, "--xlsx", str(tmp_path / "nope.xlsx"))
    assert code == 2
    assert err.startswith("error: ")


def test_an_unknown_tab_exits_two(tmp_path, capsys) -> None:
    code, _, err = run(capsys, "--xlsx", str(build(tmp_path)), "--tab", "Nope")
    assert code == 2
    assert "Nope" in err


def test_a_read_only_template_explains_itself(tmp_path, capsys) -> None:
    # The shipped workbook is exactly this: laid out, but with no character in it.
    path = build(tmp_path, name=None)
    code, _, err = run(capsys, "--xlsx", str(path))
    assert code == 2
    assert "no character name" in err


def test_the_workbook_argument_is_required(capsys) -> None:
    with pytest.raises(SystemExit):
        cli.main([])


# -- the questionnaire -----------------------------------------------------

SECTIONS = (
    (
        "Warmup Questions",
        [("Where were they born?", "In a vat."), ("Who are their parents?", "Donors.")],
    ),
    (
        "Autism Questionaire of Doom",
        [("What are their worst fears?", "Goop.")],
    ),
)


def interview_book(tmp_path, *sections, tab: str = "AQ Test Subject") -> Path:
    return questionnaire_workbook(tmp_path / "book.xlsx", *sections, tab=tab)


def test_the_questionnaire_is_printed_with_its_sections(tmp_path, capsys) -> None:
    code, out, _ = run(capsys, "--xlsx", str(interview_book(tmp_path, *SECTIONS)), "--interview")
    assert code == 0
    assert "Test Subject" in out
    assert "== Warmup Questions ==" in out
    assert "== Autism Questionaire of Doom ==" in out
    assert "Q: Where were they born?" in out
    assert "A: In a vat." in out
    assert "3/3 answered" in out


def test_a_complete_questionnaire_passes_the_check(tmp_path, capsys) -> None:
    code, out, _ = run(
        capsys, "--xlsx", str(interview_book(tmp_path, *SECTIONS)), "--check"
    )
    assert code == 0
    assert "3/3 answered (complete)" in out


def test_an_unanswered_question_fails_the_check(tmp_path, capsys) -> None:
    sections = (
        (
            "Warmup Questions",
            [("Where were they born?", "In a vat."), ("Who are their parents?", "")],
        ),
    )
    code, out, _ = run(capsys, "--xlsx", str(interview_book(tmp_path, *sections)), "--check")
    assert code == 1
    assert "1/2 answered (1 unanswered)" in out
    assert "[Warmup Questions] Who are their parents?" in out


def test_the_questionnaire_can_be_machine_read(tmp_path, capsys) -> None:
    code, out, _ = run(
        capsys, "--xlsx", str(interview_book(tmp_path, *SECTIONS)), "--interview", "--json"
    )
    payload = json.loads(out)
    assert code == 0
    assert payload["character"] == "Test Subject"
    assert payload["complete"] is True
    assert payload["total"] == 3
    assert payload["questions"][0]["prompt"] == "Where were they born?"


def test_the_questionnaire_tab_can_be_named(tmp_path, capsys) -> None:
    path = interview_book(tmp_path, *SECTIONS, tab="Interview: Test Subject")
    code, out, _ = run(
        capsys, "--xlsx", str(path), "--tab", "Interview: Test Subject", "--check"
    )
    assert code == 0
    assert "Interview: Test Subject" in out


def test_a_workbook_without_a_questionnaire_explains_itself(tmp_path, capsys) -> None:
    path = build(tmp_path)
    code, _, err = run(capsys, "--xlsx", str(path), "--interview")
    assert code == 2
    assert "no questionnaire tab" in err


real_only = pytest.mark.skipif(not REAL.is_file(), reason="custom_assets is not checked in")


@real_only
def test_the_real_questionnaires_all_pass_the_check(capsys) -> None:
    tabs = (
        "AQ Molly MacIntosh",
        "AQ Robert Ross",
        "AQ Aoife Moon",
        "AQ Cormac Moon",
        "AQ Connor McCoy",
    )
    for tab in tabs:
        code, out, _ = run(capsys, "--xlsx", str(REAL), "--tab", tab, "--check")
        assert code == 0, tab
        assert "55/55 answered (complete)" in out, tab
