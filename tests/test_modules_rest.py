"""The remaining context modules: memory movement, sentiment, thread, events, world, fit."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from ttrpg_chatbots.decide import persona_fit
from ttrpg_chatbots.life.calendar import load_calendar
from ttrpg_chatbots.memory import decay, encode, promote, retrieve
from ttrpg_chatbots.memory.long import Fact, LongTerm
from ttrpg_chatbots.memory.store import Store, StoreError
from ttrpg_chatbots.perceive import events, sentiment, thread, world
from ttrpg_chatbots.reply.context import Turn

DATA = Path("examples/friends_world")


# --- store -------------------------------------------------------------------------------------


def test_a_store_reads_what_it_writes(tmp_path) -> None:
    store = Store(tmp_path / "memory.json")

    assert store.read() == {}
    store.write({"facts": {"pet.name": "Otis"}})

    assert store.read()["facts"]["pet.name"] == "Otis"


def test_a_corrupt_store_says_so(tmp_path) -> None:
    path = tmp_path / "bad.json"
    path.write_text("not json", encoding="utf-8")

    with pytest.raises(StoreError, match="cannot read"):
        Store(path).read()


# --- long term ---------------------------------------------------------------------------------


def test_a_fact_is_replaced_not_duplicated() -> None:
    facts = LongTerm()
    facts.add(Fact(key="pet.name", value="Otis"), now="t1")
    facts.add(Fact(key="pet.name", value="Rufus"), now="t2")

    assert len(facts) == 1
    assert facts.get("pet.name").value == "Rufus"
    assert facts.get("pet.name").count == 2


def test_a_fact_needs_a_key_and_a_value() -> None:
    with pytest.raises(ValueError):
        Fact(key="  ", value="x")
    with pytest.raises(ValueError):
        Fact(key="pet.name", value=" ")


def test_facts_round_trip() -> None:
    facts = LongTerm([Fact(key="pet.name", value="Otis")])

    again = LongTerm.from_records(facts.to_records())

    assert again.get("pet.name").value == "Otis"


# --- encode / promote / retrieve / decay -------------------------------------------------------


def test_a_pet_is_heard() -> None:
    facts = encode.read("my dog is called Otis")

    assert [fact.value for fact in facts] == ["otis"]


def test_ordinary_sentences_volunteer_nothing() -> None:
    assert encode.read("what is the plot of dune") == ()


def test_importance_and_repetition_decide_what_is_kept() -> None:
    assert promote.decide(kind="pet.name", count=1) is True
    assert promote.decide(kind="like", count=1) is False
    assert promote.decide(kind="like", count=2) is True


def test_retrieval_ranks_by_overlap() -> None:
    facts = [Fact(key="pet.name", value="Otis", count=2), Fact(key="job", value="the mill")]

    assert retrieve.read(cue="how is otis doing", facts=facts)[0].key == "pet.name"
    assert retrieve.read(cue="what is the weather", facts=facts) == ()


def test_only_stale_trivia_is_forgotten() -> None:
    now = datetime.now(timezone.utc)
    old = (now - timedelta(days=400)).isoformat()
    fresh = (now - timedelta(days=2)).isoformat()
    facts = [
        Fact(key="like", value="golf", last_seen=old, count=1),
        Fact(key="pet.name", value="Otis", last_seen=old, count=1),
        Fact(key="like", value="cake", last_seen=fresh, count=1),
        Fact(key="job", value="the mill", last_seen=old, count=3),
    ]

    assert decay.due(facts, now=now) == ("like",)


# --- sentiment ---------------------------------------------------------------------------------


def test_polarity_and_target_are_separate() -> None:
    assert sentiment.read("my day was awful") == sentiment.Sentiment(polarity="negative", target="self")
    assert sentiment.read("your dog is great").target == "you"
    assert sentiment.read("the printer is fine").polarity == "neutral"
    assert sentiment.read("great, another inspection").polarity == "positive"


# --- thread ------------------------------------------------------------------------------------


def test_a_thread_is_a_run_of_the_same_move() -> None:
    same = (Turn("t", "a", act="social:smalltalk"), Turn("t", "b", act="social:smalltalk"))
    mixed = (Turn("t", "a", act="social:smalltalk"), Turn("t", "b", act="social:thanks"))

    assert thread.read(same).subject == "social:smalltalk"
    assert thread.read(mixed).subject == ""


# --- events ------------------------------------------------------------------------------------


def test_events_come_from_the_calendar() -> None:
    calendar = load_calendar(DATA / "calendar.json")["friend-a"]

    today = events.read(calendar, date(2026, 10, 21), days=14)
    summer = events.read(calendar, date(2026, 7, 1), days=14)

    labels = [event.label for event in today]
    assert "the hockey season" in labels
    assert "the season opener" in labels
    assert "the hockey season" not in [event.label for event in summer]


# --- world -------------------------------------------------------------------------------------


def test_no_table_file_means_no_scene(tmp_path) -> None:
    assert world.read(tmp_path / "absent.json").open is False


def test_a_table_file_is_read(tmp_path) -> None:
    path = tmp_path / "table.json"
    path.write_text('{"scene": "the docks", "turn": "sable", "mode": "ic"}', encoding="utf-8")

    state = world.read(path)

    assert state.open is True
    assert state.mode == "ic"


# --- persona fit -------------------------------------------------------------------------------


def test_the_old_corpus_would_have_been_rejected() -> None:
    assert persona_fit.read("rome fell. same as anywhere.").ok is False
    assert persona_fit.read("been a rangers fan since i was eight").ok is False
    assert persona_fit.read("it got lazy. typical.").reasons == ("ends on a beat",)


def test_a_plain_line_passes() -> None:
    for line in ("messing with an old pc", "there he is", "rough day"):
        assert persona_fit.read(line).ok is True, line
