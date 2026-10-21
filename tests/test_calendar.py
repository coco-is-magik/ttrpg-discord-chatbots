"""The year: what makes one Tuesday different from another, and how far away things are.

Two jobs tested here: resolution (which entries apply to a day, most specific first, and what they
do to the schedule) and recall (when is it, how long until, what happened lately).
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from ttrpg_chatbots.life.calendar import (
    Calendar,
    CalendarError,
    Entry,
    load_calendar,
    overlay,
    phrase_for,
)
from ttrpg_chatbots.life.schedule import load_schedules

DATA = Path("examples/friends_world")


def _calendar() -> Calendar:
    return load_calendar(DATA / "calendar.json")["friend-a"]


def _schedule():
    return load_schedules(DATA / "schedule.json")["friend-a"]


def test_christmas_is_not_a_tuesday() -> None:
    view = _calendar().on(date(2026, 12, 25))

    assert "Christmas" in view.titles
    assert "winter" in view.titles


def test_a_random_june_tuesday_has_nothing_on_it() -> None:
    view = _calendar().on(date(2026, 6, 16))

    assert view.titles == ("summer",)


def test_a_one_off_beats_an_annual_day_beats_a_season() -> None:
    calendar = Calendar(
        friend="x",
        entries=(
            Entry(id="season", kind="season", title="winter", months=(12,)),
            Entry(id="day", kind="annual-day", title="Christmas", on=(12, 25)),
            Entry(id="once", kind="oneoff", title="the thing", dates=(date(2026, 12, 25), date(2026, 12, 25))),
        ),
    )

    assert [entry.id for entry in calendar.on(date(2026, 12, 25)).entries] == ["once", "day", "season"]


def test_an_annual_range_may_wrap_the_new_year() -> None:
    calendar = _calendar()

    assert "hockey-season" in [entry.id for entry in calendar.on(date(2026, 10, 1)).entries]
    assert "hockey-season" in [entry.id for entry in calendar.on(date(2026, 5, 1)).entries]
    assert "hockey-season" not in [entry.id for entry in calendar.on(date(2026, 7, 1)).entries]


def test_a_one_off_only_applies_in_its_own_year() -> None:
    calendar = _calendar()

    assert "truck-service" in [e.id for e in calendar.on(date(2026, 11, 4)).entries]
    assert "truck-service" not in [e.id for e in calendar.on(date(2027, 11, 4)).entries]


def test_christmas_changes_the_day_he_is_having() -> None:
    calendar = _calendar()
    day = date(2026, 12, 25)

    plan = overlay(_schedule(), calendar.on(day))

    ids = {block.id for block in plan.blocks}
    assert "errands" not in ids
    assert "christmas-dinner" in ids
    from datetime import datetime

    assert plan.at(datetime(2026, 12, 25, 14)).doing == "sitting down to dinner with the family"


def test_an_added_block_does_not_leak_into_other_days() -> None:
    plan = overlay(_schedule(), _calendar().on(date(2026, 12, 25)))

    from datetime import datetime

    # Same time, a week later: the dinner block belongs to the 25th only.
    assert plan.at(datetime(2027, 1, 1, 14)).doing != "sitting down to dinner with the family"


def test_a_day_away_replaces_the_whole_pattern() -> None:
    plan = overlay(_schedule(), _calendar().on(date(2027, 3, 11)))

    from datetime import datetime

    slot = plan.at(datetime(2027, 3, 11, 14))
    assert slot.doing == "away up north"
    assert slot.filled_by_default is True


def test_recall_soonest_first_with_a_phrase() -> None:
    calendar = _calendar()

    upcoming = calendar.upcoming(date(2026, 10, 26), days=14)

    first = upcoming[0]
    assert first.entry.id == "season-opener"
    assert first.days_away == 2
    assert first.phrase == "on wednesday"


def test_recall_can_look_backwards() -> None:
    calendar = _calendar()

    recent = calendar.recent(date(2026, 11, 6), days=7)

    assert [item.entry.id for item in recent] == ["truck-service"]
    assert recent[0].phrase == "yesterday"


def test_phrases_say_it_the_way_a_person_would() -> None:
    assert phrase_for(0) == "today"
    assert phrase_for(1) == "tomorrow"
    assert phrase_for(-1) == "yesterday"
    assert phrase_for(2, date(2026, 10, 21)) == "on wednesday"
    assert phrase_for(9) == "in 9 days"
    assert phrase_for(14) == "in 2 weeks"


def test_a_window_of_days() -> None:
    calendar = _calendar()

    window = calendar.between(date(2026, 11, 1), date(2026, 11, 6))

    assert "truck-service" in [item.entry.id for item in window]


def test_today_leans_towards_the_subjects_of_its_events() -> None:
    calendar = _calendar()

    assert "topic:rangers" in calendar.topic_on(date(2026, 10, 28))
    assert "topic:rangers" not in calendar.topic_on(date(2026, 7, 1))


def test_a_calendar_is_optional(tmp_path) -> None:
    assert load_calendar(tmp_path / "absent.json") == {}


def test_an_unknown_kind_is_refused(tmp_path) -> None:
    path = tmp_path / "calendar.json"
    path.write_text(
        '{"schema_version": 1, "friends": {"a": {"entries": [{"id": "x", "kind": "vibes"}]}}}',
        encoding="utf-8",
    )

    with pytest.raises(CalendarError, match="kind must be one of"):
        load_calendar(path)
