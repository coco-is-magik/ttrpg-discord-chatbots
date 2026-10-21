"""Naming a subject is not the same as phrasing a question about it.

The index exists because compression distance refused "howre the rangers doing?" (0.651, past the
0.65 ceiling) with the word "rangers" in the message. These tests hold it to two things: it finds
the subject when the name is there, and it never finds one that is not.
"""

from __future__ import annotations

from pathlib import Path

from ttrpg_chatbots.reply.datasets import load_world
from ttrpg_chatbots.reply.entities import EntityIndex

DATA = Path("examples/friends_world")


def _index() -> EntityIndex:
    return EntityIndex(load_world(DATA).knowledge)


def test_a_name_in_the_message_finds_the_subject() -> None:
    index = _index()

    assert "topic:rangers" in index.tags_for("howre the rangers doing?")
    assert "topic:rome" in index.tags_for("whos the best roman general and why is it agrippa?")
    assert "topic:computers" in index.tags_for("what should i learn first, programming?")


def test_a_name_from_a_slot_counts_too() -> None:
    # "New York Rangers" lives in a slot, not in a tag; the team is still the subject.
    assert "topic:rangers" in _index().tags_for("what about new york")


def test_an_unrelated_message_names_nothing() -> None:
    index = _index()

    assert index.tags_for("what is the plot of dune?") == frozenset()
    assert index.tags_for("how do i bake bread?") == frozenset()


def test_generic_words_are_not_names() -> None:
    # "the game" and "the shot" live in slots and would otherwise match half the corpus.
    index = _index()

    assert index.tags_for("what is the game tonight") == frozenset()


def test_the_vocabulary_is_small_enough_to_read() -> None:
    vocabulary = _index().vocabulary

    assert "hockey" in vocabulary
    assert "rangers" in vocabulary
    assert all(len(term) >= 4 for term in vocabulary)
