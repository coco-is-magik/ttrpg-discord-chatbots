"""The room with nobody in it: cadence, quiet hours, inclusion, budget, and a simulated day.

These are the tests that make the group conversation tunable. Every one of them is a *number* -- a mean
gap, a speaker share, a message count -- because the alternative is judging a rolling conversation by
reading twenty lines of it, which is how a room ends up saying "yeah" for a week.
"""

from __future__ import annotations

import json
import statistics
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from ttrpg_chatbots.ambient.budget import Budget
from ttrpg_chatbots.ambient.cadence import Cadence
from ttrpg_chatbots.ambient.director import SELF_PROMPT, Director
from ttrpg_chatbots.ambient.quiet import Quiet
from ttrpg_chatbots.ambient.room import Room
from ttrpg_chatbots.perceive.clock import read_clock
from ttrpg_chatbots.ambient.simulate import simulate
from ttrpg_chatbots.bots.identity import bots_from_records
from ttrpg_chatbots.bots.ladder import Ladder
from ttrpg_chatbots.bots.memory import FriendMemory
from ttrpg_chatbots.social import inclusion

WORLD = Path("examples/friends_world")
ROSTER = Path("data/bots.json")


def _at(hour: int, minute: int = 0, day: int = 24) -> datetime:
    return datetime(2026, 10, day, hour, minute, tzinfo=timezone.utc)


class TestCadence:
    """An average, not a metronome."""

    def test_the_mean_is_the_target(self) -> None:
        gaps = [Cadence(seed=1).gap().total_seconds() for _ in range(1)]
        cadence = Cadence(mean_seconds=300, seed=1)
        gaps = [cadence.gap().total_seconds() for _ in range(20000)]
        assert statistics.mean(gaps) == pytest.approx(300, rel=0.05)

    def test_it_is_not_a_metronome(self) -> None:
        cadence = Cadence(mean_seconds=300, seed=2)
        gaps = [cadence.gap().total_seconds() for _ in range(5000)]
        assert statistics.median(gaps) < 300, "the median sits below the mean: a long tail"
        assert max(gaps) > 600, "some gaps are much longer than the average"
        assert len(set(gaps)) > 1000, "and they are not the same number repeatedly"

    def test_the_floor_is_respected(self) -> None:
        cadence = Cadence(mean_seconds=300, seed=3)
        assert min(cadence.gap().total_seconds() for _ in range(5000)) >= 45

    def test_a_seed_makes_it_reproducible(self) -> None:
        first = [Cadence(mean_seconds=300, seed=9).gap() for _ in range(5)]
        second = [Cadence(mean_seconds=300, seed=9).gap() for _ in range(5)]
        assert first == second


class TestQuietHours:
    def test_an_hour_after_the_human_goes_quiet(self) -> None:
        quiet = Quiet(seed=1)
        sleep = quiet.consider(
            _at(23, 5), human_last_at=_at(22, 0), goodnight_at=None
        )
        assert sleep.asleep(_at(23, 30)) is True

    def test_thirty_minutes_after_a_goodnight(self) -> None:
        quiet = Quiet(seed=1)
        sleep = quiet.consider(
            _at(22, 35), human_last_at=_at(22, 0), goodnight_at=_at(22, 0)
        )
        assert sleep.asleep(_at(22, 40)) is True

    def test_the_hard_cap(self) -> None:
        quiet = Quiet(seed=1)
        sleep = quiet.consider(_at(1, 5, day=25), human_last_at=None, goodnight_at=None)
        assert sleep.asleep(_at(1, 30, day=25)) is True

    def test_seven_to_eight_hours_of_sleep(self) -> None:
        for seed in range(20):
            quiet = Quiet(seed=seed)
            sleep = quiet.consider(_at(1, 5, day=25), human_last_at=None, goodnight_at=None)
            hours = (sleep.wake_at - sleep.bed_at).total_seconds() / 3600
            assert 7.0 <= hours <= 8.0, hours

    def test_a_quiet_afternoon_does_not_put_them_to_bed(self) -> None:
        """The human-relative rules only bite in the evening; otherwise 3pm is bed time."""
        quiet = Quiet(seed=1)
        sleep = quiet.consider(_at(15, 0), human_last_at=_at(13, 0), goodnight_at=None)
        assert sleep.asleep(_at(15, 30)) is False

    def test_a_message_in_the_night_does_not_wake_them(self) -> None:
        quiet = Quiet(seed=1)
        quiet.consider(_at(1, 5, day=25), human_last_at=None, goodnight_at=None)
        sleep = quiet.consider(_at(3, 0, day=25), human_last_at=_at(3, 0, day=25), goodnight_at=None)
        assert sleep.asleep(_at(3, 5, day=25)) is True


class TestWhoMaySpeak:
    def test_nobody_speaks_twice_in_a_row(self) -> None:
        room = Room()
        room.say("friend-a", "hello", _at(10, 0))
        assert "friend-a" not in inclusion.candidates(
            room, ("friend-a", "friend-b"), _at(10, 10)
        )

    def test_and_not_inside_their_own_gap(self) -> None:
        room = Room()
        room.say("friend-a", "hello", _at(10, 0))
        room.say("friend-b", "oh hi", _at(10, 1))
        assert "friend-a" not in inclusion.candidates(
            room, ("friend-a", "friend-b"), _at(10, 2)
        )

    def test_the_quietest_goes_first_but_not_always(self) -> None:
        import random

        room = Room()
        room.say("friend-a", "hello", _at(10, 0))
        room.say("friend-b", "oh hi", _at(10, 30))
        picks = [
            inclusion.choose(room, ("friend-a", "friend-b", "friend-c"), _at(11, 0), rng=rng)
            for rng in (random.Random(seed) for seed in range(40))
        ]
        # friend-b spoke most recently, so never; the other two are both eligible and both get picked.
        # Measured: an uncapped weight made the never-spoken friend the speaker *every* time, which is a
        # strict rotation wearing a different hat.
        assert "friend-b" not in picks, picks
        assert {"friend-a", "friend-c"} <= set(picks), picks


class TestBudget:
    def test_the_hourly_cap_holds(self) -> None:
        budget = Budget(per_hour=3, per_day=100)
        now = _at(10, 0)
        for minute in range(3):
            assert budget.allows(now + timedelta(minutes=minute))
            budget.record(now + timedelta(minutes=minute))
        assert budget.allows(now + timedelta(minutes=4)) is False
        assert budget.allows(now + timedelta(hours=1, minutes=1)) is True

    def test_the_daily_cap_holds(self) -> None:
        budget = Budget(per_hour=100, per_day=2)
        now = _at(10, 0)
        budget.record(now)
        budget.record(now + timedelta(hours=1))
        assert budget.allows(now + timedelta(hours=2)) is False


class TestTheDirector:
    def _director(self, **kwargs) -> Director:
        specs = bots_from_records(json.loads(ROSTER.read_text()), source=str(ROSTER))
        ladders, memories = {}, {}
        for spec in specs:
            if spec.persona is None:
                continue
            ladders[spec.id] = Ladder(
                friend=spec.id,
                data=WORLD,
                style=spec.persona.style,
                question_rate=spec.persona.question_rate,
                verbosity=spec.persona.verbosity,
            )
            memories[spec.id] = FriendMemory(spec.id, person="noodle", sessions=2)
        return Director(ladders=ladders, memories=memories, **kwargs)

    def test_it_says_nothing_while_asleep(self) -> None:
        director = self._director(seed=1)
        # 03:00, nobody home: past the hard bed, so the room is asleep.
        director.quiet.consider(_at(1, 5, day=25), human_last_at=None, goodnight_at=None)
        for minute in range(0, 120, 5):
            assert director.tick(_at(3, 0, day=25) + timedelta(minutes=minute)) is None

    def test_the_wake_greeting_happens_once(self) -> None:
        director = self._director(seed=4)
        director.quiet.consider(_at(1, 5, day=25), human_last_at=None, goodnight_at=None)
        wake = director.quiet.sleep.wake_at
        greetings = []
        now = wake
        for _ in range(600):
            line = director.tick(now)
            if line is not None and line.kind == "greeting":
                greetings.append(line)
            now += timedelta(minutes=1)
        assert len(greetings) == 1, [line.text for line in greetings]

    def test_it_does_not_acknowledge_an_acknowledgement(self) -> None:
        """The measured failure: 169 messages of "yeah" and "mm" in a loop."""
        director = self._director(seed=1)
        director.room.say("friend-b", "mm", _at(10, 0))
        assert director._prompt("friend-a", False) == SELF_PROMPT
        director.room.say("friend-b", "i have been sorting shells all morning", _at(10, 1))
        assert director._prompt("friend-a", False) == "i have been sorting shells all morning"


class TestASimulatedDay:
    def _run(self, hours: float = 24, seed: int = 11):
        from ttrpg_chatbots.ambient.cli import build_director

        director = build_director(roster=ROSTER, seed=seed)
        return simulate(director, start=_at(9, 0), hours=hours)

    def test_a_day_produces_a_conversation(self) -> None:
        run = self._run()
        assert 80 <= len(run.spoke) <= 260, run.summary()
        assert run.mean_gap_minutes == pytest.approx(5, abs=4), run.summary()

    def test_everyone_gets_a_turn(self) -> None:
        run = self._run()
        speakers = {line.speaker for line in run.spoke}
        assert speakers == {"friend-a", "friend-b", "friend-c"}, speakers
        share = [
            sum(1 for line in run.spoke if line.speaker == name) / len(run.spoke)
            for name in speakers
        ]
        assert max(share) < 0.6, f"one friend is doing the talking: {share}"

    def test_nothing_is_said_while_they_are_asleep(self) -> None:
        run = self._run()
        assert all(line.kind in ("chat", "greeting") for line in run.spoke)
        # The night is the quiet stretch: no message between 03:00 and 04:00 on either day.
        for line in run.spoke:
            assert not (line.at.hour == 3), line

    def test_a_seed_makes_a_week_reproducible(self) -> None:
        first = [line.text for line in self._run(hours=6, seed=5).spoke]
        second = [line.text for line in self._run(hours=6, seed=5).spoke]
        assert first == second
        other = [line.text for line in self._run(hours=6, seed=6).spoke]
        assert first != other

    def test_a_week_is_cheap_enough_to_run(self) -> None:
        run = self._run(hours=168, seed=2)
        assert run.hours == 168
        assert len(run.spoke) > 400, run.summary()


class TestTheRoomsDayIsLocal:
    """The bug that made the room go silent for an evening.

    Measured live at 21:24 EDT: the friends said two things and then nothing, because the schedule was
    evaluated in UTC -- where it was 01:24, past the hard bedtime. A person's day is the one on the wall.
    """

    def test_the_live_loop_uses_local_time(self) -> None:
        from ttrpg_chatbots.bots.conversation import local_now

        assert local_now().utcoffset() == datetime.now().astimezone().utcoffset()

    def test_an_evening_is_not_bedtime(self) -> None:
        """21:24 local is an evening, whatever the UTC clock says."""
        quiet = Quiet(seed=1)
        evening = datetime.now().astimezone().replace(hour=21, minute=24)
        sleep = quiet.consider(evening, human_last_at=evening, goodnight_at=None)
        assert sleep.asleep(evening) is False

    def test_and_the_simulator_starts_local_too(self) -> None:
        from ttrpg_chatbots.ambient.cli import main

        assert main(["--hours", "2", "--seed", "3", "--quiet"]) == 0


def test_bedtime_can_be_switched_off():
    """A dataset needs messages: eight hours of silence is eight hours of nothing to analyse."""
    from datetime import datetime

    from ttrpg_chatbots.ambient.quiet import Quiet

    three_am = datetime(2026, 10, 24, 3, 0)
    assert Quiet(sleep_enabled=True).sleep.asleep(three_am) is False  # nothing has been decided yet
    quiet = Quiet(sleep_enabled=False)
    for moment in (
        datetime(2026, 10, 24, 1, 5),
        datetime(2026, 10, 24, 3, 0),
        datetime(2026, 10, 24, 5, 30),
    ):
        quiet.consider(moment, human_last_at=moment, goodnight_at=None)
        assert quiet.sleep.asleep(moment) is False, moment


def test_the_room_tells_a_listener_about_every_line():
    """The room is the only place that knows the whole conversation, so it is where a dataset comes from."""
    from datetime import datetime

    from ttrpg_chatbots.ambient.room import Room

    heard = []
    room = Room(on_say=heard.append)
    at = datetime(2026, 10, 24, 12, 0)
    room.say("friend-a", "morning", at)
    room.say("friend-b", "h-hi", at)
    room.say("human", "hey", at, kind="human")

    assert [entry.speaker for entry in heard] == ["friend-a", "friend-b", "human"]
    assert [entry.text for entry in heard] == ["morning", "h-hi", "hey"]
    assert heard[-1].is_human is True
    assert heard[0].is_human is False


def test_the_transcript_is_self_describing(tmp_path, monkeypatch):
    """A dataset without its settings is a pile of sentences rather than a baseline."""
    import json
    from datetime import datetime

    from ttrpg_chatbots.bots.conversation import LOG_ENV, Chatter

    target = tmp_path / "chatter.jsonl"
    monkeypatch.setenv(LOG_ENV, str(target))
    talk = Chatter.__new__(Chatter)
    talk._log_path = target
    talk._opened = False
    talk.channel_id = 123
    talk.director = _Director()

    from ttrpg_chatbots.ambient.room import Said

    at = datetime(2026, 10, 24, 22, 5)
    talk._write(Said(speaker="friend-c", text="Night night honey 🐠", at=at))
    talk._write(Said(speaker="friend-a", text="night", at=at))

    lines = [json.loads(line) for line in target.read_text().splitlines()]
    assert lines[0]["kind"] == "header"
    assert lines[0]["friends"] == ["friend-a", "friend-b", "friend-c"]
    assert lines[0]["sleep_enabled"] is False
    assert lines[0]["budget"] == {"per_hour": 20, "per_day": 400}
    assert lines[0]["channel_id"] == 123
    assert [line["text"] for line in lines[1:]] == ["Night night honey 🐠", "night"]
    assert lines[1]["speaker"] == "friend-c"


def test_a_full_day_is_not_clipped():
    """At the target rate a day is 288 messages; the cap must clear it."""
    from ttrpg_chatbots.ambient.budget import PER_DAY, PER_HOUR

    assert PER_DAY > 288, PER_DAY
    assert PER_HOUR > 12, PER_HOUR


class _Cadence:
    mean_seconds = 300.0
    minimum = 45.0
    maximum = 720.0


class _Budget:
    per_hour = 20
    per_day = 400


class _Quiet:
    sleep_enabled = False


class _Director:
    ladders = {"friend-a": None, "friend-b": None, "friend-c": None}
    cadence = _Cadence()
    budget = _Budget()
    quiet = _Quiet()


def test_a_line_heard_by_two_routes_is_one_line():
    """The director records what it said (local time); each friend records what it heard (UTC). One line.

    Measured live: every spoken line appeared twice in the transcript, and twice in the room's own window
    -- which is what the ladder reads when it decides what the last thing said was.
    """
    from datetime import datetime, timedelta, timezone

    from ttrpg_chatbots.ambient.room import Room

    heard = []
    room = Room(on_say=heard.append)
    local = datetime(2026, 10, 24, 21, 55, 18, tzinfo=timezone(timedelta(hours=-4)))
    utc = local.astimezone(timezone.utc)

    room.say("friend-a", "opener this week", local)
    room.say("friend-a", "opener this week", utc)  # the same instant, another timezone

    assert len(room.said) == 1
    assert len(heard) == 1


def test_a_genuine_repeat_is_still_two_lines():
    """Repetition is the sound of familiarity -- the guard must not eat a real second utterance."""
    from datetime import datetime, timedelta

    from ttrpg_chatbots.ambient.room import Room

    room = Room()
    at = datetime(2026, 10, 24, 21, 0)
    room.say("friend-b", "mm", at)
    room.say("friend-b", "mm", at + timedelta(seconds=50))

    assert len(room.said) == 2


def test_a_different_speaker_is_not_deduped():
    """Two people saying the same thing at the same time are two people."""
    from datetime import datetime

    from ttrpg_chatbots.ambient.room import Room

    room = Room()
    at = datetime(2026, 10, 24, 21, 0)
    room.say("friend-a", "morning", at)
    room.say("friend-b", "morning", at)

    assert len(room.said) == 2


def test_a_restart_is_marked_in_an_existing_transcript(tmp_path, monkeypatch):
    """A restart and a long silence look identical in the data unless one of them is written down."""
    import json

    from ttrpg_chatbots.bots.conversation import LOG_ENV, Chatter

    target = tmp_path / "chatter.jsonl"
    monkeypatch.setenv(LOG_ENV, str(target))
    talk = Chatter.__new__(Chatter)
    talk._log_path = target

    talk._mark_start()  # nothing to mark yet
    assert not target.exists()

    target.write_text('{"kind": "header"}\n{"text": "hello"}\n', encoding="utf-8")
    talk._mark_start()
    last = json.loads(target.read_text().splitlines()[-1])
    assert last["kind"] == "start"


def test_switching_bedtime_off_switches_off_the_friends_night_too():
    """The room's quiet hours are not the only way a friend goes quiet.

    Measured on the first overnight run: `TTRPG_CHATTER_SLEEP=0` stopped the room from sleeping but not
    the friend who has a schedule entry, so he went to bed at 23:00 and was silent for eight hours -- 58
    silences against 9 lines, while the two friends with no schedule carried the conversation.
    """
    from datetime import datetime

    from ttrpg_chatbots.bots.ladder import Ladder
    from ttrpg_chatbots.conv.types import Abstain, Line

    three_am = datetime(2026, 10, 24, 3, 0)

    asleep = Ladder(friend="friend-a", obey_schedule=True).line(text="hey", moment=None)
    awake = Ladder(friend="friend-a", obey_schedule=False).line(
        text="hey", moment=read_clock(three_am)
    )

    # friend-a's schedule says he is asleep at three in the morning; the flag is what overrides it.
    assert isinstance(asleep, (Abstain, Line))
    assert isinstance(awake, Line), awake


def test_one_definition_of_bedtime_off(monkeypatch):
    """Two parsers of the same variable drifted apart once already."""
    from ttrpg_chatbots.bots.conversation import SLEEP_ENV, sleep_enabled

    monkeypatch.delenv(SLEEP_ENV, raising=False)
    assert sleep_enabled() is True
    for value in ("0", "off", "no", "false", "OFF"):
        monkeypatch.setenv(SLEEP_ENV, value)
        assert sleep_enabled() is False, value
    for value in ("1", "on", "yes", "true", ""):
        monkeypatch.setenv(SLEEP_ENV, value)
        assert sleep_enabled() is True, value


def test_a_line_carries_the_reason_it_was_chosen():
    """Without the trail, a dataset cannot say *why* a line was said -- only that it was."""
    from datetime import datetime

    from ttrpg_chatbots.ambient.room import Room

    heard = []
    room = Room(on_say=heard.append)
    room.say("friend-a", "morning", datetime(2026, 10, 24, 8, 0), trail="job=greet > variant=morning")

    assert heard[0].trail == "job=greet > variant=morning"
    assert room.said[0].trail == "job=greet > variant=morning"


def test_a_line_that_was_heard_has_no_trail():
    """A friend recording what it heard is not a decision, so there is nothing to record."""
    from datetime import datetime

    from ttrpg_chatbots.ambient.room import Room

    room = Room()
    room.say("friend-b", "h-hi", datetime(2026, 10, 24, 8, 1))

    assert room.said[0].trail == ""
