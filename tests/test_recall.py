"""He remembers what you told him -- and brings it up once.

The gate is the interesting part. A system with memory recites; a friend mentions your dog once in a
while. So the tests here are mostly about *restraint*: when he must not bring it up, and what he says
instead when the budget has no room for it.
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

from ttrpg_chatbots.bots.ladder import Ladder
from ttrpg_chatbots.bots.memory import FriendMemory
from ttrpg_chatbots.conv.types import Line
from ttrpg_chatbots.decide import recall as recall_rung
from ttrpg_chatbots.decide.values import build
from ttrpg_chatbots.memory.encode import read as encode
from ttrpg_chatbots.memory.long import Fact
from ttrpg_chatbots.memory.retrieve import read as retrieve
from ttrpg_chatbots.perceive.clock import read_clock
from ttrpg_chatbots.reply.style import Style

WORLD = Path("examples/friends_world")
DAY = date(2026, 10, 22)
EVENING = read_clock(datetime(2026, 10, 22, 20, 15))
STYLE = Style(case="lower", drop_apostrophes=True, strip_final_period=True, typo_rate=0.0)
OTIS = Fact(key="pet.name", value="otis", meta={"word": "dog"})


def _memory(*, last_seen: str = "2026-10-20T09:00:00+00:00") -> FriendMemory:
    memory = FriendMemory("friend-a", person="tav", last_seen=last_seen)
    memory.remember_facts(encode("my dog is called otis"))
    return memory


def _say(text: str, memory: FriendMemory | None = None):
    ladder = Ladder(friend="friend-a", data=WORLD, style=STYLE)
    return ladder.line(text=text, memory=memory or _memory(), moment=EVENING, day=DAY)


# --- what gets kept ------------------------------------------------------------------------------


def test_encoding_finds_the_things_a_friend_would_remember() -> None:
    facts = encode("my dog is called otis and i work at the garage")

    assert {(fact.key, fact.value) for fact in facts} == {
        ("pet.name", "otis"),
        ("job", "the garage"),
    }


def test_a_pet_is_kept_the_first_time_and_a_like_is_not() -> None:
    memory = FriendMemory("probe")

    assert memory.remember_facts(encode("my dog is called otis")), "a pet is worth keeping"
    assert not memory.remember_facts(encode("i really like hockey")), "said once, not worth keeping"
    assert memory.remember_facts(encode("i really like hockey")), "said twice, now it is"


def test_a_fact_survives_a_restart(tmp_path) -> None:
    memory = FriendMemory("friend-a", directory=tmp_path, person="tav")
    memory.remember_facts(encode("my dog is called otis"))
    memory.save()

    reloaded = FriendMemory.load("friend-a", directory=tmp_path)

    assert [(fact.key, fact.value, fact.meta.get("word")) for fact in reloaded.facts] == [
        ("pet.name", "otis", "dog")
    ]
    assert reloaded.person == "tav"


def test_the_word_they_use_is_what_finds_the_fact() -> None:
    # "pet.name" is the key; "dog" is what a person says. Retrieval matched only the key before, so
    # "how is the dog?" found nothing at all.
    assert [fact.value for fact in retrieve(cue="how is the dog?", facts=(OTIS,))] == ["otis"]
    assert retrieve(cue="what is the plot of dune", facts=(OTIS,)) == ()


def test_forgetting_removes_it(tmp_path) -> None:
    memory = FriendMemory("friend-a", directory=tmp_path)
    memory.remember_facts(encode("my dog is called otis"))

    assert memory.forget("pet.name") is True
    assert memory.facts == ()
    assert memory.forget("pet.name") is False


# --- the gate ------------------------------------------------------------------------------------


def test_they_raised_it_so_he_answers_it() -> None:
    decision = recall_rung.choose(
        text="how is the dog?", facts=(OTIS,), bucket="fresh", today=str(DAY)
    )

    assert decision is not None
    assert decision.mode == "raised"


def test_the_start_of_a_session_may_open_with_it() -> None:
    decision = recall_rung.choose(text="hey", facts=(OTIS,), bucket="day", today=str(DAY))

    assert decision is not None
    assert decision.mode == "session"


def test_an_unrelated_question_never_drags_it_in() -> None:
    # Two layers, and both are needed. The gate may offer a fact at the start of a session; only an
    # opening *welcomes* that offer. Measured: without the welcome table, "what is the plot of
    # dune?" was answered with a question about a dog.
    decision = recall_rung.choose(text="what is the plot of dune?", facts=(OTIS,), bucket="day")
    assert decision is not None and decision.mode == "session"

    out = _say("what is the plot of dune?")

    assert isinstance(out, Line)
    assert "otis" not in out.text
    assert dict(out.trail.steps)["family"] != "recall"


def test_he_only_brings_it_up_once_a_day() -> None:
    raised = Fact(key="pet.name", value="otis", meta={"word": "dog", "raised": str(DAY)})

    assert recall_rung.choose(text="hey", facts=(raised,), bucket="day", today=str(DAY)) is None
    assert (
        recall_rung.choose(text="how is the dog?", facts=(raised,), bucket="day", today=str(DAY))
        is None
    )


def test_a_fact_he_cannot_answer_for_is_asked_after() -> None:
    out = _say("how is the dog?")

    assert isinstance(out, Line)
    assert "otis" in out.text
    assert dict(out.trail.steps)["family"] == "recall"


def test_a_greeting_too_short_for_recall_still_says_hello() -> None:
    # "hey" is three words of budget and a recall line is five. Going silent was the bug.
    out = _say("hey")

    assert isinstance(out, Line)
    assert "otis" not in out.text
    assert dict(out.trail.steps)["recall"].endswith("(no room)")


def test_a_complaint_does_not_become_a_question_about_your_dog() -> None:
    out = _say("rough day at work")

    assert isinstance(out, Line)
    assert "otis" not in out.text


def test_no_facts_means_no_recall_at_all() -> None:
    out = _say("hey", FriendMemory("friend-a", person="tav"))

    assert isinstance(out, Line)
    assert dict(out.trail.steps)["recall"] == "nothing"


# --- the slots -----------------------------------------------------------------------------------


def test_recall_slots_are_the_three_words_a_line_needs() -> None:
    slots = build(job="noted", remembered=OTIS)

    assert slots["fact_value"] == "otis"
    assert slots["fact_word"] == "dog"
    assert slots["fact_kind"] == "pet"
