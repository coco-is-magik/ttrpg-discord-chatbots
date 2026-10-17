import pytest

from ttrpg_chatbots.reply import compression
from ttrpg_chatbots.reply.datasets import load_world
from ttrpg_chatbots.reply.ncd import classify, ncd as distance, rank
from ttrpg_chatbots.reply.types import DatasetError

from reply_support import DEMO_WORLD

WORLD = load_world(DEMO_WORLD)
DEFLATE = compression.get("deflate")


def test_identical_text_is_closer_than_unrelated_text() -> None:
    same = distance(b"the tide turns at the quay", b"the tide turns at the quay", DEFLATE)
    other = distance(b"the tide turns at the quay", b"a goblin stole my boots", DEFLATE)
    assert same < other
    assert same < 0.25


def test_similar_text_beats_unrelated_text() -> None:
    shared = distance(b"where is the sunken crown", b"the sunken crown is tide-iron", DEFLATE)
    unrelated = distance(b"where is the sunken crown", b"the guild keeps its ledgers", DEFLATE)
    assert shared < unrelated


def test_distance_is_roughly_symmetric() -> None:
    left = b"the sunken crown is tide iron"
    right = b"the long quay takes deep hulls"
    assert abs(distance(left, right, DEFLATE) - distance(right, left, DEFLATE)) < 0.15


@pytest.mark.parametrize("other", [b"", b"x", b"an unrelated sentence about turnips " * 3])
def test_distance_stays_bounded(other: bytes) -> None:
    assert 0.0 <= distance(b"the tide turns", other, DEFLATE) <= 1.2


def test_two_empty_inputs_are_zero() -> None:
    assert distance(b"", b"", DEFLATE) == 0.0


def test_classify_rejects_an_empty_query() -> None:
    with pytest.raises(ValueError, match="query"):
        classify("   ", WORLD.knowledge)


def test_classify_rejects_an_empty_corpus() -> None:
    with pytest.raises(DatasetError, match="no knowledge"):
        classify("anything", ())


def test_classify_rejects_bad_top_k() -> None:
    with pytest.raises(ValueError, match="top_k"):
        classify("anything", WORLD.knowledge, top_k=0)


@pytest.mark.parametrize(
    "query,expected",
    [
        ("what is the sunken crown?", "lore:relic"),
        ("who controls the dry docks in the reach?", "lore:guild"),
        ("when is the turning tide rite spoken?", "lore:ritual"),
        ("what is the harbour council buying?", "lore:rumour"),
        ("where does a deep water ship berth?", "lore:harbor"),
    ],
)
def test_classify_finds_the_obvious_tag(query: str, expected: str) -> None:
    assert classify(query, WORLD.knowledge).best_tag == expected


def test_top_k_only_trims_the_reported_matches() -> None:
    """Every tag is scored; top_k is provenance, not a filter on the answer."""
    narrow = classify("what is the sunken crown?", WORLD.knowledge, top_k=1)
    wide = classify("what is the sunken crown?", WORLD.knowledge, top_k=10)
    assert len(narrow.matches) == 1
    assert narrow.tags == wide.tags
    assert narrow.best_tag == wide.best_tag


def test_matches_are_ordered_and_carry_provenance() -> None:
    result = classify("does the wreck still ring its bell?", WORLD.knowledge, top_k=3)
    distances = [match.distance for match in result.matches]
    assert distances == sorted(distances)
    assert result.compressor == compression.DEFAULT
    assert result.best_item is not None
    assert result.best_item.id == result.matches[0].ref


def test_tag_scores_are_ordered_best_first() -> None:
    result = classify("how do i cross the brine mire?", WORLD.knowledge)
    distances = [score.distance for score in result.tags]
    assert distances == sorted(distances)


def test_ranking_is_deterministic() -> None:
    first = classify("what is the sunken crown?", WORLD.knowledge)
    second = classify("what is the sunken crown?", WORLD.knowledge)
    assert first.tags == second.tags
    assert first.matches == second.matches


def test_rank_without_top_k_covers_the_whole_corpus() -> None:
    assert len(rank("anything at all", WORLD.knowledge, DEFLATE)) == len(WORLD.knowledge)


def test_the_compressor_is_recorded_and_switchable() -> None:
    result = classify("what is the sunken crown?", WORLD.knowledge, compression.get("gzip"))
    assert result.compressor == "gzip"
