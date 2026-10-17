"""The character CLI: create, randomise, import, list, show, log."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from character_support import ScriptedPrompter, script
from ttrpg_chatbots.character import cli
from ttrpg_chatbots.character.store import CharacterStore
from ttrpg_chatbots.character.types import Character
from ttrpg_chatbots.sheets.interview import Questionnaire

FORM = Questionnaire(name="test", sections=(("Warmup", ("Where from?", "Why leave?")),))


@pytest.fixture
def form_file(tmp_path: Path) -> Path:
    path = tmp_path / "interview.json"
    path.write_text(json.dumps(FORM.as_dict()), encoding="utf-8")
    return path


def test_no_action_is_a_usage_error(tmp_path: Path) -> None:
    assert cli.main(["--dir", str(tmp_path)]) == 2


def test_listing_an_empty_directory_is_not_an_error(tmp_path: Path, capsys) -> None:
    assert cli.main(["--dir", str(tmp_path), "--list"]) == 0
    assert capsys.readouterr().out.strip() == "none"


def test_random_then_list_then_show(tmp_path: Path, form_file: Path, capsys) -> None:
    args = ["--dir", str(tmp_path), "--questionnaire", str(form_file)]
    assert cli.main([*args, "--random", "--name", "Rolled", "--seed", "5"]) == 0
    assert "Rolled" in capsys.readouterr().out

    assert cli.main([*args, "--list"]) == 0
    shown = capsys.readouterr().out
    assert "rolled" in shown
    assert "0/2 answers" in shown

    assert cli.main([*args, "--show", "rolled"]) == 0
    detail = capsys.readouterr().out
    assert "attributes:" in detail
    assert "interview: 0/2 answered, 2 unanswered" in detail


def test_show_can_emit_json(tmp_path: Path, form_file: Path, capsys) -> None:
    args = ["--dir", str(tmp_path), "--questionnaire", str(form_file)]
    cli.main([*args, "--random", "--name", "Rolled", "--seed", "5"])
    capsys.readouterr()
    assert cli.main([*args, "--show", "rolled", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["name"] == "Rolled"
    assert payload["interview"]["total"] == 2


def test_missing_character_reports_what_exists(tmp_path: Path, capsys) -> None:
    assert cli.main(["--dir", str(tmp_path), "--show", "ghost"]) == 2
    assert "ghost" in capsys.readouterr().err


def test_a_missing_questionnaire_says_where_it_looked(tmp_path: Path, capsys) -> None:
    args = ["--dir", str(tmp_path), "--questionnaire", str(tmp_path / "absent.json")]
    assert cli.main([*args, "--random"]) == 2
    assert "no questionnaire" in capsys.readouterr().err


def test_creating_from_stdin(tmp_path: Path, form_file: Path, monkeypatch, capsys) -> None:
    answers = iter(["Piped", *script()])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    args = ["--dir", str(tmp_path), "--questionnaire", str(form_file)]
    assert cli.main([*args, "--new"]) == 0
    assert "Piped" in capsys.readouterr().out

    saved = CharacterStore(tmp_path).load("piped")
    assert saved.name == "Piped"
    assert saved.sealed is True
    assert saved.interview_complete is True


def test_creating_from_stdin_can_defer_the_seal(
    tmp_path: Path, form_file: Path, monkeypatch
) -> None:
    answers = iter(["Piped", *script()])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    args = ["--dir", str(tmp_path), "--questionnaire", str(form_file)]
    assert cli.main([*args, "--new", "--no-seal"]) == 0
    saved = CharacterStore(tmp_path).load("piped")
    assert saved.sealed is False
    assert saved.interview_complete is True


def test_appending_an_event(tmp_path: Path, form_file: Path, capsys) -> None:
    args = ["--dir", str(tmp_path), "--questionnaire", str(form_file)]
    cli.main([*args, "--random", "--name", "Rolled", "--seed", "1"])
    capsys.readouterr()
    assert cli.main([*args, "--event", "rolled", "--kind", "session", "--summary", "s1"]) == 0
    assert "2 event(s)" in capsys.readouterr().out

    character = CharacterStore(tmp_path).load("rolled")
    assert [event.kind for event in character.history] == ["created", "session"]
    assert character.history[-1].summary == "s1"


def test_assigning_a_premade_refuses_to_overwrite_the_pool(
    tmp_path: Path, form_file: Path, capsys
) -> None:
    args = ["--dir", str(tmp_path), "--questionnaire", str(form_file)]
    cli.main([*args, "--random", "--name", "Pool", "--seed", "1"])
    # Make it usable: a random character has no prose, so seal a hand-made one instead.
    store = CharacterStore(tmp_path)
    pool = store.load("pool")
    from ttrpg_chatbots.sheets.interview import blank_interview

    answered = blank_interview(FORM, "Pool")
    from ttrpg_chatbots.sheets.interview import Interview, Question

    filled = Interview(
        character="Pool",
        questions=tuple(
            Question(q.prompt, "Because.", q.section) for q in answered.questions
        ),
    )
    store.save(pool.with_interview(filled).seal())
    capsys.readouterr()

    assert cli.main([*args, "--premade", "--seed", "1"]) == 2
    assert "already exists" in capsys.readouterr().err

    assert cli.main([*args, "--premade", "--seed", "1", "--rename", "Recruit"]) == 0
    assert "Recruit" in capsys.readouterr().out
    recruit = store.load("recruit")
    assert recruit.ready is True
    assert recruit.history[-1].kind == "assigned"


def test_listing_survives_one_broken_file(tmp_path: Path, form_file: Path, capsys) -> None:
    args = ["--dir", str(tmp_path), "--questionnaire", str(form_file)]
    cli.main([*args, "--random", "--name", "Good", "--seed", "1"])
    capsys.readouterr()
    broken = tmp_path / "broken.json"
    broken.write_text('{"schema_version": 1, "sheet": {"name": "Broken"}}', encoding="utf-8")

    assert cli.main([*args, "--list"]) == 0
    out = capsys.readouterr().out
    assert "Good" in out
    assert "broken: UNREADABLE" in out


def test_an_unknown_event_kind_is_refused(tmp_path: Path, form_file: Path, capsys) -> None:
    args = ["--dir", str(tmp_path), "--questionnaire", str(form_file)]
    cli.main([*args, "--random", "--name", "Rolled", "--seed", "1"])
    capsys.readouterr()
    assert cli.main([*args, "--event", "rolled", "--kind", "teleport"]) == 2
    assert "unknown event kind" in capsys.readouterr().err