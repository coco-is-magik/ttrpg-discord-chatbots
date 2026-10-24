"""Domains: the corpus split so it can grow in precise places.

The point of these tests is the *segmentation* -- that one area can be added, changed or broken without
another area noticing -- plus the matching discipline that keeps a name from firing on the wrong subject.
"""

from __future__ import annotations

import json

import pytest

from ttrpg_chatbots.decide.dig import answer_for, question_for
from ttrpg_chatbots.reply.context import Turn
from ttrpg_chatbots.reply.domains import Aspect, Domain, DomainError, load

WORLD = "examples/friends_world"


# --- the real domains in the world ------------------------------------------------------------


def test_the_world_has_domains_and_they_load():
    book = load(f"{WORLD}/domains", friend="friend-b")
    assert book
    assert {"cute-things", "trains", "the-ocean"} <= set(book.domains)


def test_a_domain_is_one_folder_so_it_can_grow_alone():
    """Adding depth to trains must not require opening the file where Rome lives."""
    trains = load(f"{WORLD}/domains").domains["trains"]
    assert {aspect.name for aspect in trains.aspects.values()} == {
        "the-old-ones",
        "the-timetable",
        "the-station",
    }


def test_a_friends_material_is_his_own():
    otto = load(f"{WORLD}/domains", friend="friend-b")
    crusty = load(f"{WORLD}/domains", friend="friend-c")
    assert otto.domains["cute-things"].answers["the-shelf"]
    assert not crusty.domains["cute-things"].answers
    assert crusty.domains["the-ocean"].answers["the-tank"]


def test_a_name_matches_whole_words_only():
    """Fuzzy matching here is how a bot decides the weather is about trains."""
    book = load(f"{WORLD}/domains", friend="friend-b")
    assert book.find("i have been rearranging my shelf") is not None
    assert book.find("the training course was long") is None
    assert book.find("i am training for a run") is None


def test_the_longest_name_wins():
    book = load(f"{WORLD}/domains", friend="friend-b")
    found = book.find("the old trains are best")
    assert found is not None
    assert found[1].name == "the-old-ones"


def test_an_area_named_without_an_aspect_still_has_a_way_in():
    book = load(f"{WORLD}/domains", friend="friend-b")
    found = book.find("i like trains")
    assert found is not None
    assert found[0].id == "trains"


def test_questions_and_answers_can_avoid_what_was_used():
    book = load(f"{WORLD}/domains", friend="friend-c")
    domain = book.domains["the-ocean"]
    aspect = domain.aspects["the-tank"]
    everything = book.questions(aspect)
    assert everything
    assert book.questions(aspect, avoid=everything) == ()
    used = book.answers(domain, aspect)
    assert used
    assert book.answers(domain, aspect, avoid=used) == used  # nothing fresh left, so it repeats


# --- validation --------------------------------------------------------------------------------


def test_an_aspect_needs_names_and_questions():
    """A name nothing can reach, or a question nobody can ask, is a silent hole in the corpus."""
    with pytest.raises(DomainError):
        Aspect(name="the-shelf", names=(), questions=("what is on it?",))
    with pytest.raises(DomainError):
        Aspect(name="the-shelf", names=("shelf",), questions=())


def test_a_domain_needs_a_name_nothing_can_be_reached_without_one():
    with pytest.raises(DomainError):
        Domain(id="trains", names=())


def test_a_material_line_with_an_unknown_aspect_is_refused(tmp_path):
    folder = tmp_path / "domains" / "widgets"
    folder.mkdir(parents=True)
    (folder / "domain.json").write_text(
        json.dumps(
            {
                "id": "widgets",
                "names": ["widgets"],
                "aspects": [
                    {"name": "the-ones", "names": ["widgets"], "questions": ["which one?"]}
                ],
            }
        )
    )
    (folder / "friend-z.jsonl").write_text('{"aspect": "nonsense", "text": "a widget"}\n')
    with pytest.raises(DomainError, match="not in domain.json"):
        load(tmp_path / "domains", friend="friend-z")


def test_a_domain_with_no_aspects_is_refused(tmp_path):
    folder = tmp_path / "domains" / "empty"
    folder.mkdir(parents=True)
    (folder / "domain.json").write_text(json.dumps({"id": "empty", "names": ["empty"], "aspects": []}))
    with pytest.raises(DomainError, match="no aspects"):
        load(tmp_path / "domains")


def test_a_missing_folder_is_not_an_error():
    """A world with no domains still works; the layer is additive."""
    assert not load("/tmp/definitely-not-a-world/domains")


# --- taking a hook ----------------------------------------------------------------------------


def test_the_exchange_from_the_log_now_works():
    """"i have been rearranging my shelf" used to get "nice" and then the same line again."""
    offered = Turn(
        speaker="friend-b",
        text="i have been rearranging my shelf",
        act="ladder|offer_hook|topic:cute-things|",
        is_bot=True,
    )
    dig = question_for(
        turns=(offered,), domains=load(f"{WORLD}/domains", friend="friend-c"),
        offered_hook=True, question_rate=0.8,
    )
    assert dig is not None
    assert dig.aspect.name == "the-shelf"
    assert dig.question.endswith("?")

    asked = Turn(
        speaker="friend-c", text=dig.question, act=f"ladder|dig|{dig.about}|", is_bot=True
    )
    otto = load(f"{WORLD}/domains", friend="friend-b")
    found = answer_for(turns=(asked,), domains=otto)
    assert found is not None
    assert otto.answers(found[0], found[1])


def test_he_only_digs_at_an_offer():
    turns = (Turn(speaker="tav", text="nice", is_bot=False),)
    assert question_for(
        turns=turns, domains=load(f"{WORLD}/domains"), offered_hook=False, question_rate=1.0
    ) is None


def test_he_does_not_dig_twice_running():
    """Two questions in a row is an interview."""
    asked = Turn(speaker="friend-c", text="what is on it?", act="ladder|dig|cute-things:the-shelf|", is_bot=True)
    assert question_for(
        turns=(asked,), domains=load(f"{WORLD}/domains"), offered_hook=True, question_rate=1.0
    ) is None


def test_a_rate_of_zero_means_he_never_asks():
    offered = Turn(speaker="friend-b", text="watching the trains", is_bot=True)
    assert question_for(
        turns=(offered,), domains=load(f"{WORLD}/domains"), offered_hook=True, question_rate=0.0
    ) is None


def test_a_hook_about_nothing_he_knows_is_left_alone():
    offered = Turn(speaker="friend-b", text="the kettle is broken", is_bot=True)
    assert question_for(
        turns=(offered,), domains=load(f"{WORLD}/domains"), offered_hook=True, question_rate=1.0
    ) is None


def test_the_roll_decides_whether_he_asks():
    offered = Turn(speaker="friend-b", text="watching the trains", is_bot=True)
    book = load(f"{WORLD}/domains", friend="friend-c")
    assert question_for(
        turns=(offered,), domains=book, offered_hook=True, question_rate=0.4, roll=0.9
    ) is None
    assert question_for(
        turns=(offered,), domains=book, offered_hook=True, question_rate=0.4, roll=0.1
    ) is not None


def test_answering_needs_the_act_to_carry_what_was_asked():
    """A question like "what is on it?" names nothing, so the text cannot carry it."""
    plain = Turn(speaker="friend-c", text="what is on it?", is_bot=True)
    assert answer_for(turns=(plain,), domains=load(f"{WORLD}/domains")) is None


def test_answering_a_domain_he_does_not_know_is_ignored():
    asked = Turn(speaker="friend-c", text="what is on it?", act="ladder|dig|cute-things:the-shelf|", is_bot=True)
    crusty = load(f"{WORLD}/domains", friend="friend-c")
    found = answer_for(turns=(asked,), domains=crusty)
    assert found is not None  # she knows the domain...
    assert not crusty.answers(found[0], found[1])  # ...but has nothing of her own to say about it
