"""The dice CLI: the four output modes, the dataset, and the instruction path."""

from __future__ import annotations

import json

import pytest

from dice_support import DEMO_WORLD
from ttrpg_chatbots.dice import cli


def run(capsys, *argv: str) -> tuple[int, str, str]:
    code = cli.main(list(argv))
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def data() -> list[str]:
    return ["--data", str(DEMO_WORLD)]


def test_a_pool_is_rolled_and_summed(capsys) -> None:
    code, out, _ = run(capsys, "--roll", "3d6", "--character", "Brannoc", "--seed", "1")
    assert code == 0
    assert out.startswith("Brannoc rolls 3d6: ")
    assert " = " in out


def test_a_modifier_in_the_notation_is_kept(capsys) -> None:
    _, out, _ = run(capsys, "--roll", "1d20+5", "--character", "B", "--seed", "4")
    assert out.startswith("B rolls 1d20+5: ")


def test_the_same_seed_gives_the_same_line(capsys) -> None:
    first = run(capsys, "--roll", "3d6", "--character", "B", "--seed", "7")[1]
    second = run(capsys, "--roll", "3d6", "--character", "B", "--seed", "7")[1]
    assert first == second


def test_list_mode_shows_the_dice(capsys) -> None:
    _, out, _ = run(capsys, "--roll", "2d6", "--character", "B", "--mode", "list", "--seed", "3")
    assert "[" in out and "]" in out
    assert "total" in out


def test_hits_mode_counts_against_the_target(capsys) -> None:
    _, out, _ = run(
        capsys,
        "--roll",
        "5d10",
        "--character",
        "B",
        "--mode",
        "hits",
        "--target",
        "8",
        "--seed",
        "3",
    )
    assert "(hits on 8+)" in out
    assert "hit" in out


def test_check_mode_reports_a_verdict(capsys) -> None:
    _, out, _ = run(
        capsys,
        "--roll",
        "1d20+5",
        "--character",
        "B",
        "--mode",
        "check",
        "--target",
        "15",
        "--seed",
        "3",
    )
    assert "vs 15 ->" in out
    assert "success" in out or "failure" in out


def test_a_named_check_comes_from_the_dataset(capsys) -> None:
    code, out, _ = run(capsys, *data(), "--check", "stealth", "--character", "Sable")
    assert code == 0
    assert out.startswith("Sable rolls Stealth 1d20+5:")
    assert "vs 15 ->" in out


def test_count_and_sides_work_without_notation(capsys) -> None:
    _, out, _ = run(capsys, "--count", "2", "--sides", "8", "--character", "B", "--seed", "2")
    assert out.startswith("B rolls 2d8:")


def test_json_output(capsys) -> None:
    code, out, _ = run(capsys, "--roll", "2d6", "--character", "Ola", "--seed", "5", "--json")
    assert code == 0
    payload = json.loads(out)
    assert payload["character"] == "Ola"
    assert payload["notation"] == "2d6"
    assert len(payload["dice"]) == 2


def test_list_checks(capsys) -> None:
    code, out, _ = run(capsys, *data(), "--list-checks")
    assert code == 0
    assert "stealth" in out
    assert "1d20+5" in out


def test_list_checks_json(capsys) -> None:
    _, out, _ = run(capsys, *data(), "--list-checks", "--json")
    rows = {row["id"]: row for row in json.loads(out)}
    assert rows["perception"]["mode"] == "hits"
    assert rows["perception"]["target"] == 8


@pytest.mark.parametrize(
    "argv",
    [
        [],
        ["--roll", "3d6", "--check", "stealth"],
        ["--roll", "3d6"],  # no character
        ["--roll", "banana", "--character", "B"],
        ["--count", "3"],  # missing sides
        ["--roll", "3d6", "--character", "B", "--mode", "hits"],  # no target
    ],
)
def test_bad_invocations_exit_two(capsys, argv: list[str]) -> None:
    code, _, err = run(capsys, *argv)
    assert code == 2
    assert err.startswith("error: ")


def test_an_unknown_check_names_the_known_ones(capsys) -> None:
    code, _, err = run(capsys, *data(), "--check", "jump", "--character", "B")
    assert code == 2
    assert "unknown check" in err


def test_ask_parses_an_instruction(capsys) -> None:
    code, out, _ = run(capsys, "--ask", "roll 3d6 for Brannoc", "--seed", "1")
    assert code == 0
    assert "understood:" in out
    assert "Brannoc rolls 3d6" in out


def test_ask_can_use_a_named_check(capsys) -> None:
    code, out, _ = run(capsys, *data(), "--ask", "roll stealth for Sable")
    assert code == 0
    assert "Sable rolls Stealth" in out


def test_ask_that_is_not_a_roll_is_refused(capsys) -> None:
    code, _, err = run(capsys, *data(), "--ask", "what is the sunken crown?")
    assert code == 2
    assert "not a roll instruction" in err
