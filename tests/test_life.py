"""A life: what he is in the middle of, and why.

The state has to be stable enough to be coherent (same activity all day) and varied enough to be
interesting (a different one tomorrow), and the rendering has to fill every slot it promises.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from ttrpg_chatbots.life import Activity, Life, LifeError, LifeVoice, load_lives
from ttrpg_chatbots.life.state import Grievance

DATA = Path("examples/friends_world")


def _activity(**overrides) -> Activity:
    record = {
        "id": "test",
        "doing": "doing a thing",
        "short": "busy",
        "phase": "halfway",
        "why": "because i wanted to",
    }
    record.update(overrides)
    return Activity(**record)


def test_an_activity_needs_something_to_be_doing() -> None:
    with pytest.raises(LifeError, match="doing"):
        _activity(doing="  ")


def test_the_same_day_gives_the_same_activity() -> None:
    life = Life(friend="friend-a", activities=tuple(_activity(id=f"a{i}") for i in range(5)))

    first = life.current("2026-10-21")
    second = life.current("2026-10-21")

    assert first is not None and first.id == second.id


def test_different_days_vary() -> None:
    life = Life(friend="friend-a", activities=tuple(_activity(id=f"a{i}") for i in range(5)))

    seen = {life.current(f"2026-11-{day:02d}").id for day in range(1, 15)}

    assert len(seen) > 1, "a friend who does the same thing every day is furniture"


def test_a_life_with_nothing_in_it_is_empty_not_broken() -> None:
    life = Life(friend="friend-a")

    assert bool(life) is False
    assert life.current() is None
    assert life.grievance() is None


def test_a_missing_file_means_nobody_has_a_life_yet(tmp_path) -> None:
    assert load_lives(tmp_path / "absent.json") == {}


def test_the_real_file_loads() -> None:
    lives = load_lives(DATA / "life.json")

    assert "friend-a" in lives
    assert lives["friend-a"].current() is not None
    assert lives["friend-a"].grievance() is not None
    # One at a time: c has no life yet.
    # All three written friends have a day now. A friend with *no* life file is a valid state and is
    # covered below; this one is about the real file being readable end to end.
    assert "friend-c" in lives
    assert lives["friend-c"].current() is not None
    assert lives["friend-c"].plan() is not None


def test_rendering_fills_every_slot() -> None:
    voice = LifeVoice(load_lives(DATA / "life.json"))

    for line in (voice.doing("friend-a"), voice.commiserate("friend-a"), voice.elaborate("friend-a")):
        assert line
        assert "{" not in line and "}" not in line


def test_a_friend_without_a_life_renders_nothing() -> None:
    voice = LifeVoice(load_lives(DATA / "life.json"))

    assert voice.has("friend-d") is False, "a friend with no life file renders nothing"
    assert voice.doing("friend-d") is None


def test_repeated_asks_do_not_repeat_the_line() -> None:
    voice = LifeVoice(load_lives(DATA / "life.json"))

    lines = {voice.doing("friend-a") for _ in range(5)}

    assert len(lines) > 1, "rotation is off"


def test_a_grievance_carries_its_own_invitation() -> None:
    record = Grievance(id="g", text="the thing happened", invite="what about you")

    assert record.invite == "what about you"
