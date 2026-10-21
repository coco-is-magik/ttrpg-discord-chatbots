"""The greet phase, on its own, with the numbers it has to meet.

Everything here is about one phase. The point of the module split is that this file can fail for a
reason that has nothing to do with memory, phases or conversation flow -- and that fixing it means
touching the greet stage, not the whole responder.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from ttrpg_chatbots.bots.greeter import Greeter
from ttrpg_chatbots.conv.types import Abstain, Budget, Line
from ttrpg_chatbots.decide import variant
from ttrpg_chatbots.decide.variant import load
from ttrpg_chatbots.govern.harness import run
from ttrpg_chatbots.perceive.clock import read_clock

WORLD = Path("examples/friends_world")
MORNING = read_clock(datetime(2026, 10, 21, 8, 40))
AFTERNOON = read_clock(datetime(2026, 10, 21, 14, 0))
NIGHT = read_clock(datetime(2026, 10, 22, 3, 0))


def _greeter() -> Greeter:
    return Greeter(friend="friend-a", data=WORLD)


def test_a_greeting_gets_a_short_greeting_back() -> None:
    out = _greeter().line(text="hey", moment=MORNING)

    assert isinstance(out, Line)
    assert 0 < len(out.text.split()) <= 3


def test_the_greeting_matches_the_time_of_day() -> None:
    morning = _greeter().line(text="hey", moment=MORNING)
    night = _greeter().line(text="hey", moment=NIGHT)

    assert isinstance(morning, Line)
    # 03:00 is inside the sleep block, so the honest answer is silence, not "morning".
    assert isinstance(night, Abstain)
    assert "asleep" in night.reason


def test_a_stranger_does_not_get_a_warm_line() -> None:
    greeter = _greeter()
    out = greeter.line(text="hey", moment=AFTERNOON)

    assert isinstance(out, Line)
    family = dict(out.trail.steps)["family"]
    assert family != "warm"


def test_another_job_is_refused_by_this_phrasebook() -> None:
    # The phase boundary: greet only greets. "thanks" is an acknowledgement, which this
    # phrasebook deliberately does not contain.
    out = _greeter().line(text="thanks", moment=AFTERNOON)

    assert isinstance(out, Abstain)
    assert "acknowledge" in out.reason


def test_a_variant_that_cannot_fit_the_budget_is_not_a_candidate() -> None:
    # Measured before the fix: one six-word warm line made the whole warm family go silent,
    # because the ladder rendered it and the trimmer then refused it. A line that cannot fit
    # is not a candidate, and a family with nothing that fits declines rather than shouting.
    book = load(WORLD / "phrasebooks" / "greet.json")
    narrow = Budget(max_words=1, max_sentences=1)
    too_long = [line for line in book.variants("warm") if not narrow.fits(line)]
    assert too_long  # otherwise this test proves nothing

    chosen = variant.choose(book=book, family="warm", budget=narrow)

    assert chosen is None or narrow.fits(chosen)


def test_the_harness_answers_every_time_and_never_sounds_like_a_caption() -> None:
    book = load(WORLD / "phrasebooks" / "greet.json")
    report = run(book=book)

    assert report.attempts > 100
    # Silence is for reasons (asleep, unaddressed), never because the line did not fit.
    assert "over budget" not in report.abstains
    assert report.median_words <= 3
    # Zero lines may end on a beat: that cadence is the tell we are designing against.
    assert report.beat_rate == 0
    # Familiarity, not novelty: a person says "hey" the same way all week.
    assert report.distinct_ratio < 0.4


def test_the_greeting_never_contradicts_the_clock() -> None:
    # Caught live: at 19:20 he said "morning", because the family was time-aware but the variants
    # were not. A family chosen by the clock may only contain lines the clock allows.
    book = load(WORLD / "phrasebooks" / "greet.json")
    for hour, forbidden in ((8, "evening"), (20, "morning"), (0, "morning"), (0, "evening")):
        moment = read_clock(datetime(2026, 10, 21, hour, 10))
        out = _greeter().line(text="hey", moment=moment)
        if isinstance(out, Line):
            assert forbidden not in out.text.lower(), (hour, out.text)
