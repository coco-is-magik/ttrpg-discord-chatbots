"""Stories: the three ways in, and the one way the point comes out.

The gate is the whole design here. A story told unprompted is a monologue, so each trigger is a piece
of evidence rather than a mood, and the tests are mostly about the *no* cases.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from ttrpg_chatbots.bots.ladder import Ladder
from ttrpg_chatbots.bots.memory import FriendMemory
from ttrpg_chatbots.conv.types import Line
from ttrpg_chatbots.decide import story as story_rung
from ttrpg_chatbots.life.render import load_lives
from ttrpg_chatbots.reply.context import Turn
from ttrpg_chatbots.reply.style import Style

WORLD = Path("examples/friends_world")
DAY = date(2026, 10, 22)
STYLE = Style(case="lower", drop_apostrophes=True, strip_final_period=True, typo_rate=0.0)


def _life():
    return load_lives(WORLD / "life.json")["friend-a"]


def _say(text: str, *, turns: tuple[Turn, ...] = ()):
    ladder = Ladder(friend="friend-a", data=WORLD, style=STYLE)
    return ladder.line(
        text=text, memory=FriendMemory("friend-a", person="tav"), turns=turns, day=DAY
    )


def _human(text: str) -> Turn:
    return Turn(speaker="tav", text=text, act=None, is_bot=False)


def _bot(act: str) -> Turn:
    return Turn(speaker="friend-a", text="something", act=act, is_bot=True)


def _lean_in() -> tuple[Turn, ...]:
    return (
        _human("i have been rebuilding a fence myself this month"),
        _human("it took me three weekends and a lot of swearing"),
    )


# --- the three ways in ---------------------------------------------------------------------------


def test_asking_about_something_that_happened_gets_the_story() -> None:
    out = _say("how did the fence go?")

    assert isinstance(out, Line)
    assert dict(out.trail.steps)["job"] == "tell_story"
    assert "handle" in out.text.lower(), "the axe story, not a status"


def test_a_follow_up_after_a_hook_reaches_the_story_of_that_thing() -> None:
    # The chain the whole design was built around: hook, then detail, then story. The topic comes
    # from his own last turn, which is why this is the woodworking story.
    turns = (_human("what are you up to"), _bot("ladder|offer_hook|topic:woodworking|"))

    out = _say("how did that go?", turns=turns)

    assert isinstance(out, Line)
    assert dict(out.trail.steps)["story"].startswith("grandfathers-axe")


def test_leaning_in_twice_gets_a_story_unprompted() -> None:
    out = _say("my weekend was long", turns=_lean_in())

    assert isinstance(out, Line)
    assert dict(out.trail.steps)["job"] == "tell_story"


def test_an_ordinary_message_gets_nothing_of_the_sort() -> None:
    out = _say("rough day at work")

    assert isinstance(out, Line)
    assert dict(out.trail.steps)["job"] == "mirror"


def test_a_question_about_the_world_is_never_a_story_moment() -> None:
    # Measured: without this, "what is the plot of dune?" was answered with the deer.
    out = _say("what is the plot of dune?", turns=_lean_in())

    assert isinstance(out, Line)
    assert dict(out.trail.steps)["job"] != "tell_story"


def test_what_are_you_up_to_is_a_hook_even_after_leaning_in() -> None:
    # A question about his day is not an invitation to a story, with or without a question mark.
    out = _say("what are you up to", turns=_lean_in())

    assert isinstance(out, Line)
    assert dict(out.trail.steps)["job"] == "offer_hook"


# --- the point, and only when asked ---------------------------------------------------------------


def test_the_point_only_arrives_when_it_is_asked_for() -> None:
    told = (_human("how did the fence go?"), _bot("ladder|tell_story|topic:woodworking|grandfathers-axe"))

    asked = _say("what was the point of that?", turns=told)
    unasked = _say("how did the fence go?", turns=())

    assert isinstance(asked, Line) and isinstance(unasked, Line)
    assert "bought a new one" in asked.text.lower(), "the point"
    assert "bought a new one" not in unasked.text.lower(), "the body, not the point"


def test_a_story_ends_and_a_point_is_an_explanation() -> None:
    told = (_human("how did the fence go?"), _bot("ladder|tell_story|topic:woodworking|grandfathers-axe"))

    out = _say("what did you learn from that?", turns=told)

    assert isinstance(out, Line)
    assert dict(out.trail.steps)["job"] == "explain"
    assert dict(out.trail.steps)["family"] == "point"


# --- the gate itself ------------------------------------------------------------------------------


def test_the_gate_prefers_the_topic_of_the_conversation() -> None:
    telling = story_rung.choose(
        text="how did that go?", life=_life(), topic="topic:woodworking", told={}
    )

    assert telling is not None
    assert telling.story.id == "grandfathers-axe"


def test_a_question_about_the_past_with_no_context_still_gets_a_story() -> None:
    # Nothing lines up, and a question about the past deserves an answer rather than silence.
    telling = story_rung.choose(text="how did that go?", life=_life(), told={})

    assert telling is not None
    assert telling.mode == "asked"


def test_a_story_about_the_thing_they_asked_about_is_told_again_if_it_is_the_only_one() -> None:
    # A person asked about the fence twice tells the fence story twice. Freshness orders the
    # candidates; it does not overrule what they asked about.
    telling = story_rung.choose(
        text="how did the fence go?", life=_life(), told={"grandfathers-axe": 1}
    )

    assert telling is not None
    assert telling.story.id == "grandfathers-axe"


def test_with_nothing_to_match_freshness_decides() -> None:
    telling = story_rung.choose(text="how did that go?", life=_life(), told={"first-deer": 3})

    assert telling is not None
    assert telling.story.id != "first-deer", "the least-told one comes up"
