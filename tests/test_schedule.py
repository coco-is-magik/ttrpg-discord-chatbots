"""A day laid out as blocks: 15-minute slots, sleep as a block, and an editor-friendly check.

What this buys: "what is he doing right now" has one answer for any minute, and the answer is data
that can be moved towards the human's own schedule without touching code.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from ttrpg_chatbots.life.schedule import (
    Block,
    Schedule,
    ScheduleError,
    Slot,
    format_clock,
    load_schedules,
    parse_clock,
)
from ttrpg_chatbots.perceive.clock import read_clock

DATA = Path("examples/friends_world")


def _schedule() -> Schedule:
    return load_schedules(DATA / "schedule.json")["friend-a"]


def _at(day: int, hour: int, minute: int = 0) -> datetime:
    # 2026-10-19 is a Monday, so day offsets are stable.
    return datetime(2026, 10, 19 + day, hour, minute)


def test_times_parse_and_format() -> None:
    assert parse_clock("06:30") == 390
    assert format_clock(390) == "06:30"
    with pytest.raises(ScheduleError, match="not a time of day"):
        parse_clock("half six")


def test_he_is_asleep_at_three_in_the_morning() -> None:
    slot = _schedule().at(_at(0, 3))

    assert slot.asleep is True


def test_a_slot_is_snapped_to_the_quarter_hour() -> None:
    slot = _schedule().at(_at(0, 14, 7))

    assert (slot.start, slot.end) == (14 * 60, 14 * 60 + 15)
    assert slot.start % 15 == 0


def test_monday_and_saturday_are_different_days() -> None:
    weekday = _schedule().at(_at(0, 9))
    saturday = _schedule().at(_at(5, 9))

    assert weekday.doing != saturday.doing
    assert "topic:fishing" in saturday.topics


def test_a_block_carries_the_subjects_it_belongs_to() -> None:
    # This is the bridge to his life: what he is doing hints at what he can talk about.
    slot = _schedule().at(_at(0, 16))

    assert "topic:woodworking" in slot.topics


def test_the_whole_day_is_quarter_hours() -> None:
    day = _schedule().day("mon")

    assert len(day) == 96
    assert all(slot.end - slot.start == 15 for slot in day)
    assert all(slot.filled_by_default is False for slot in day)


def test_progress_through_a_block() -> None:
    slot = _schedule().at(_at(0, 14))
    slot = Slot(start=14 * 60, end=15 * 60, doing="reading")

    assert slot.progress(14 * 60) == 0.0
    assert slot.progress(14 * 60 + 30) == 0.5
    assert slot.progress(16 * 60) == 1.0


def test_a_gap_falls_back_and_says_so() -> None:
    sparse = Schedule(friend="friend-a", blocks=(Block(id="a", start=600, end=660, doing="x"),))
    slot = sparse.at(_at(0, 14))

    assert slot.filled_by_default is True
    assert slot.doing == sparse.default_doing


def test_check_reports_holes_overlaps_and_off_grid_times() -> None:
    broken = Schedule(
        friend="friend-a",
        blocks=(
            Block(id="early", start=590, end=600, doing="a"),  # 09:50, off-grid
            Block(id="one", start=600, end=660, doing="b"),
            Block(id="two", start=630, end=720, doing="c"),  # overlaps "one"
        ),
    )

    problems = " | ".join(broken.check())

    assert "not on a 15-minute boundary" in problems
    assert "overlap" in problems
    assert "nothing before" in problems
    assert "nothing after" in problems


def test_the_real_schedule_is_valid() -> None:
    assert _schedule().check() == ()


def test_a_missing_file_is_empty_not_fatal(tmp_path) -> None:
    assert load_schedules(tmp_path / "absent.json") == {}


def test_the_clock_agrees_with_the_schedule() -> None:
    moment = read_clock(_at(0, 9))

    assert moment.weekday == "mon"
    assert moment.is_weekend is False
    assert moment.part_of_day == "morning"
