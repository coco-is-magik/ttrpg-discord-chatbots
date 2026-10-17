import json

import pytest

from ttrpg_chatbots.reply import cli

from reply_support import DEMO_WORLD

DEMO = str(DEMO_WORLD)


def test_validate_prints_the_world_summary(capsys) -> None:
    assert cli.main(["--data", DEMO, "--validate"]) == 0

    output = capsys.readouterr().out
    assert "The Saltreach" in output
    assert "13 items" in output
    assert "brannoc" in output


def test_validate_json_is_machine_readable(capsys) -> None:
    assert cli.main(["--data", DEMO, "--validate", "--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["world"] == "The Saltreach"
    assert payload["knowledge"] == 13
    assert {row["character"] for row in payload["characters"]} == {"brannoc", "sable", "orla"}
    assert payload["characters"][0]["tags_without_templates"] == []


def test_ask_prints_the_reply_and_its_provenance(capsys) -> None:
    args = ["--data", DEMO, "--ask", "what is the sunken crown?", "--character", "brannoc"]
    assert cli.main(args) == 0

    output = capsys.readouterr().out
    assert "tide-iron" in output
    assert "lore:relic" in output
    assert "k-relic-crown" in output


def test_ask_json_includes_the_classification(capsys) -> None:
    args = [
        "--data", DEMO, "--ask", "what is the sunken crown?", "--character", "brannoc", "--json",
    ]
    assert cli.main(args) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["known"] is True
    assert payload["tag"] == "lore:relic"
    assert payload["character_name"] == "Brannoc the Archivist"


def test_ask_reports_a_deflection(capsys) -> None:
    args = ["--data", DEMO, "--ask", "what is the sunken crown?", "--character", "orla"]
    assert cli.main(args) == 0

    output = capsys.readouterr().out
    assert "(deflected)" in output
    assert "tide-iron" not in output


def test_classify_prints_the_ranking_best_first(capsys) -> None:
    assert cli.main(["--data", DEMO, "--classify", "what is the sunken crown?"]) == 0

    lines = capsys.readouterr().out.splitlines()
    assert lines[0].startswith("tag")
    assert lines[1].split()[0] == "lore:relic"
    assert "k-relic-crown" in lines[1]


def test_list_characters(capsys) -> None:
    assert cli.main(["--data", DEMO, "--list-characters"]) == 0
    assert "brannoc" in capsys.readouterr().out


def test_unknown_character_exits_two(capsys) -> None:
    args = ["--data", DEMO, "--ask", "the crown", "--character", "gandalf"]
    assert cli.main(args) == 2
    assert "unknown character" in capsys.readouterr().err


def test_missing_dataset_exits_two(tmp_path, capsys) -> None:
    assert cli.main(["--data", str(tmp_path / "absent"), "--validate"]) == 2
    assert "does not exist" in capsys.readouterr().err


def test_no_action_exits_two(capsys) -> None:
    assert cli.main(["--data", DEMO]) == 2
    assert "give one of" in capsys.readouterr().err


def test_compressor_flag_is_honoured(capsys) -> None:
    args = ["--data", DEMO, "--classify", "the sunken crown", "--compressor", "gzip"]
    assert cli.main(args) == 0
    assert "lore:relic" in capsys.readouterr().out


def test_top_k_must_be_positive(tmp_path, capsys) -> None:
    assert cli.main(["--data", DEMO, "--classify", "the crown", "--top-k", "0"]) == 2
