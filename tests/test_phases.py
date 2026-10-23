"""The other phases, one at a time.

Same shape as `test_greeter.py`, one section per phase, so a failure names the phase that broke rather
than the responder. The messages are the ones a person actually types: a two-word question, a
one-word "why?", a complaint with no detail in it.
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import pytest

from ttrpg_chatbots.bots.ladder import Ladder
from ttrpg_chatbots.bots.memory import FriendMemory
from ttrpg_chatbots.conv.types import Abstain, Event, Line
from ttrpg_chatbots.decide.shelf import Shelf, load_shelf
from ttrpg_chatbots.decide.values import build, missing
from ttrpg_chatbots.decide.variant import PhrasebookError
from ttrpg_chatbots.govern.harness import run_phases
from ttrpg_chatbots.life.render import load_lives
from ttrpg_chatbots.life.state import Plan, Story
from ttrpg_chatbots.memory.long import Fact
from ttrpg_chatbots.perceive.clock import read_clock
from ttrpg_chatbots.reply.context import Turn

WORLD = Path("examples/friends_world")
EVENING = read_clock(datetime(2026, 10, 21, 20, 15))
DAY = EVENING.now.date()
PHASES = (
    "acknowledge",
    "ask_back",
    "close",
    "explain",
    "follow_up",
    "greet",
    "hedge",
    "mirror",
    "noted",
    "offer_hook",
    "reassure",
    "tell_story",
)


def _memory() -> FriendMemory:
    return FriendMemory("friend-a", sessions=14, person="tav", topics={"topic:rangers": 3})


def _say(text: str, *, turns: tuple[Turn, ...] = (), friend: str = "friend-a"):
    """One message through the ladder, with the day pinned so the life does not move under it."""
    ladder = Ladder(friend=friend, data=WORLD)
    return ladder.line(
        text=text, memory=_memory(), moment=EVENING, turns=turns, day=DAY
    )


def _lean_in(*lines: str) -> tuple[Turn, ...]:
    """Human turns long enough to count as leaning in."""
    return tuple(
        Turn(speaker="tav", text=line, act=None, is_bot=False)
        for line in (lines or ("i have been rebuilding a fence myself this month",))
    )


# --- the shelf ----------------------------------------------------------------------------------


def test_the_shelf_has_one_book_per_phase() -> None:
    shelf = load_shelf(WORLD / "phrasebooks")

    assert shelf.jobs() == PHASES


def test_the_shelf_never_borrows_between_jobs() -> None:
    shelf = load_shelf(WORLD / "phrasebooks")

    assert shelf.for_job("greet") is not None
    assert shelf.for_job("sing") is None


def test_a_missing_phrasebook_directory_is_an_empty_shelf(tmp_path) -> None:
    assert load_shelf(tmp_path / "nothing") == Shelf(books={})

# --- values -------------------------------------------------------------------------------------


def test_a_hook_gets_the_thing_he_is_doing() -> None:
    life = load_lives(WORLD / "life.json")["friend-a"]
    slots = build(job="offer_hook", life=life, day=DAY)

    assert slots["hook"]
    assert len(slots["hook"].split()) <= 5, "a hook is a few words, not a description"
    assert "doing" in slots and "why" in slots


def test_a_mirror_gets_a_grievance_and_a_greeting_gets_nothing() -> None:
    life = load_lives(WORLD / "life.json")["friend-a"]

    mirrored = build(job="mirror", life=life, day=DAY)
    greeted = build(job="greet", life=life, day=DAY)

    assert mirrored["grievance"]
    assert "grievance" not in greeted, "a greeting has no business knowing his complaints"


def test_missing_reports_the_slot_that_cannot_be_filled() -> None:
    assert missing("{hook} and {name}", {"hook": "fencing"}) == ("name",)
    assert missing("{hook}", {"hook": "fencing"}) == ()


# --- one phase at a time ------------------------------------------------------------------------


def test_a_hook_names_one_thing_shortly() -> None:
    out = _say("what are you up to")

    assert isinstance(out, Line)
    assert len(out.text.split()) <= 5
    assert dict(out.trail.steps)["job"] == "offer_hook"


def test_a_rough_day_gets_a_reaction_and_not_a_monologue() -> None:
    out = _say("rough day at work")
    life = load_lives(WORLD / "life.json")["friend-a"]

    assert isinstance(out, Line)
    assert dict(out.trail.steps)["family"] == "reaction"
    grievance = life.grievance(DAY).text
    assert grievance not in out.text, "the grievance arrived before they leaned in"


def test_leaning_in_gets_the_grievance() -> None:
    out = _say("rough day at work", turns=_lean_in())
    life = load_lives(WORLD / "life.json")["friend-a"]

    assert isinstance(out, Line)
    assert dict(out.trail.steps)["family"] == "detail"
    assert life.grievance(DAY).text.lower() in out.text.lower()


def test_why_reaches_the_reason() -> None:
    out = _say("why?")
    life = load_lives(WORLD / "life.json")["friend-a"]

    assert isinstance(out, Line)
    assert dict(out.trail.steps)["job"] == "explain"
    assert life.current(DAY).why.lower() in out.text.lower()


def test_a_question_he_cannot_answer_hedges_shortly() -> None:
    out = _say("what is the plot of dune?")

    assert isinstance(out, Line)
    assert dict(out.trail.steps)["job"] == "hedge"
    assert len(out.text.split()) <= 4


def test_being_nervous_gets_one_encouraging_line() -> None:
    out = _say("i am nervous about tomorrow")

    assert isinstance(out, Line)
    assert dict(out.trail.steps)["job"] == "reassure"


def test_saying_goodnight_ends_it() -> None:
    out = _say("good night")

    assert isinstance(out, Line)
    assert dict(out.trail.steps)["job"] == "close"
    assert len(out.text.split()) <= 3


def test_thanks_is_acknowledged_not_answered() -> None:
    out = _say("thanks")

    assert isinstance(out, Line)
    assert dict(out.trail.steps)["job"] == "acknowledge"


def test_a_friend_with_no_life_hedges_rather_than_inventing_one() -> None:
    out = _say("what are you up to", friend="friend-z")

    if isinstance(out, Line):
        assert dict(out.trail.steps)["job"] == "hedge"
    else:
        assert isinstance(out, Abstain)


# --- the numbers --------------------------------------------------------------------------------


def test_every_phase_answers_every_time_without_sounding_written() -> None:
    shelf = load_shelf(WORLD / "phrasebooks")
    reports = run_phases(books=shelf, life=load_lives(WORLD / "life.json")["friend-a"])

    assert set(reports) == set(PHASES)
    for job, report in reports.items():
        assert report.said == report.attempts, f"{job} went quiet: {report.abstains}"
        if job == "tell_story":
            # The one place he may be long: a story is two sentences of something that happened,
            # and it is only here because somebody asked for it.
            assert 10 <= report.median_words <= 30, f"{job} is not a story"
            assert report.max_words <= 30, f"{job} broke the story ceiling"
            continue
        assert report.median_words <= 4, f"{job} is writing essays"
        assert report.max_words <= 14, f"{job} broke the ceiling"
        assert report.beat_rate == 0, f"{job} ends lines on a beat"
        assert report.distinct_ratio < 0.5, f"{job} invents a new line every time"
        # A trim means the phrasebook and the budget disagree. Live, a comiseration was trimmed from
        # twelve words to "yeah" -- the content gone and the reaction left behind.
        assert report.trim_rate < 0.05, f"{job} needs the trimmer: {report.trim_rate:.0%}"


def test_two_books_claiming_one_job_are_refused(tmp_path) -> None:
    (tmp_path / "a.json").write_text('{"job": "greet", "families": {"x": {"variants": ["hey"]}}}')
    (tmp_path / "b.json").write_text('{"job": "greet", "families": {"x": {"variants": ["yo"]}}}')

    with pytest.raises(PhrasebookError, match="two books claim"):
        load_shelf(tmp_path)


def test_every_slot_in_every_phrasebook_is_fillable_by_its_own_job() -> None:
    # A typo in a slot name is otherwise invisible until it happens to be chosen, and then the stage
    # abstains for a reason nobody reads. This checks the whole shelf against the real dataset,
    # including the recall families, which only have values when there is something to remember.
    shelf = load_shelf(WORLD / "phrasebooks")
    life = load_lives(WORLD / "life.json")["friend-a"]
    remembered = Fact(key="pet.name", value="otis", meta={"word": "dog"})

    for job in shelf.jobs():
        slots = build(
            job=job,
            life=life,
            day=DAY,
            name="tav",
            facts=(remembered,),
            remembered=remembered,
            subject_text="a stance he holds about something he knows",
            events=(Event(label="the season opener", days_away=1, short="opener"),),
            story=Story(id="axe", body="a body that happened", point="a point about it"),
            plan=Plan(id="range", what="get out to the range", when="saturday"),
            # The point is only handed over when it was asked for, so the check has to ask.
            point=True,
        )
        for family in shelf.for_job(job).families.values():
            for template in family.variants:
                assert not missing(template, slots), f"{job}: {template!r} cannot be filled"


def test_his_day_changes_when_the_calendar_does() -> None:
    # The gap this closes: with no events, every "what are you up to" for the rest of the year is
    # answered from the same handful of activities, because nothing in his world moves but the clock.
    ladder = Ladder(friend="friend-a", data=WORLD)
    memory = FriendMemory("friend-a", person="tav")

    quiet = ladder.line(text="what are you up to", memory=memory, day=date(2026, 11, 20))
    news = ladder.line(text="what are you up to", memory=memory, day=date(2026, 10, 27))

    assert isinstance(quiet, Line) and isinstance(news, Line)
    assert "opener" in news.text.lower(), "the season opener is tomorrow and he mentions it"
    assert "opener" not in quiet.text.lower()


def test_an_event_is_never_added_by_appending_a_second_sentence() -> None:
    # The event family has a bare variant for exactly this reason: a pleasantries budget allows one
    # sentence, so "{hook}. {event}" cannot fit and would fall back to the plain hook.
    ladder = Ladder(friend="friend-a", data=WORLD)
    out = ladder.line(
        text="what are you up to", memory=FriendMemory("friend-a"), day=date(2026, 12, 25)
    )

    assert isinstance(out, Line)
    assert out.text.count(".") <= 1


def test_a_friend_can_override_one_phase_and_keep_the_rest(tmp_path) -> None:
    """Phrasebooks resolve per friend, per job, over the shared set.

    A character diverges one phase at a time. Without a per-job fallback, changing his greeting would
    mean copying ten files -- so nobody would ever start.
    """
    import json
    import shutil

    from ttrpg_chatbots.decide.shelf import load_shelf

    world = tmp_path / "world"
    (world / "phrasebooks").mkdir(parents=True)
    shutil.copytree(WORLD / "phrasebooks", world / "phrasebooks", dirs_exist_ok=True)

    # nothing of his own yet: the shared register, unchanged
    shared = load_shelf(world / "phrasebooks")
    alone = load_shelf(world / "phrasebooks" / "friend-b", fallback=world / "phrasebooks")
    assert alone.jobs() == shared.jobs(), "a friend with no books of his own speaks the shared set"

    # one phase of his own, and only that one changes
    mine = world / "phrasebooks" / "friend-b"
    mine.mkdir(parents=True, exist_ok=True)
    (mine / "greet.json").write_text(
        json.dumps({"job": "greet", "families": {"casual": {"when": {}, "variants": ["oh hey"]}}}),
        encoding="utf-8",
    )

    overridden = load_shelf(mine, fallback=world / "phrasebooks")
    assert overridden.jobs() == shared.jobs(), "the other jobs still come from the shared set"
    assert overridden.for_job("greet").variants("casual") == ("oh hey",)
    assert overridden.for_job("hedge").variants("unsure") == shared.for_job("hedge").variants(
        "unsure"
    ), "and the shared books are untouched"


def test_a_question_can_start_with_a_lead_in() -> None:
    """Measured: "also do you like trains" was heard as a statement, so a direct question about his own
    subject got "ah" instead of an answer."""
    from ttrpg_chatbots.perceive.inbound import looks_like_question

    assert looks_like_question("also do you like trains")
    assert looks_like_question("so what are you up to")
    assert looks_like_question("and how are you doing")
    # and a statement with a question word inside it is still a statement
    assert not looks_like_question("i was thinking about getting a plant")
    assert not looks_like_question("i had one before but i killed it")
    assert not looks_like_question("it was a fern")


def test_he_says_the_same_thing_differently_before_repeating_it() -> None:
    """A four-word answer is allowed to repeat, so the identical line came back twice in a minute."""
    from ttrpg_chatbots.bots.ladder import Ladder
    from ttrpg_chatbots.bots.memory import FriendMemory

    ladder = Ladder(friend="friend-b")
    memory = FriendMemory.load("friend-b")

    said = [
        ladder.line(text="what are you up to", memory=memory, speaker="tav")
        for _ in range(3)
    ]
    lines = [line.text for line in said if hasattr(line, "text")]

    assert len(lines) >= 2
    assert len(set(lines)) == len(lines), f"he repeated himself verbatim: {lines}"


def test_a_follow_up_question_is_about_what_he_offered() -> None:
    """Measured: "what is the plot of dune?" arrived after a hook and was answered with the freight
    train, because *any* question counted as a follow-up."""
    from ttrpg_chatbots.decide.story import _is_about_the_offering

    assert _is_about_the_offering("how did that go?", "topic:computers")
    assert _is_about_the_offering("is it still doing that?", "topic:computers")
    assert _is_about_the_offering("how is the computer?", "topic:computers")
    assert not _is_about_the_offering("what is the plot of dune?", "topic:computers")
