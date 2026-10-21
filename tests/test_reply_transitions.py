"""The act table: smoothing, the veto rule, and refusing to load nonsense."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ttrpg_chatbots.reply.transitions import (
    SCHEMA_VERSION,
    TransitionError,
    TransitionModel,
    counts_from_pairs,
)


def _model(**kwargs) -> TransitionModel:
    counts = {
        "social:greeting": {"social:greeting": 6, "social:howareyou": 3},
        "social:goodbye": {"social:goodbye": 5},
    }
    return TransitionModel(counts, **kwargs)


def test_an_empty_model_is_uniform_and_vetoes_nothing() -> None:
    model = TransitionModel()

    assert bool(model) is False
    assert model.probability("anything", "anything") == 1.0
    # No data must mean "no opinion", or a dataset without a table would change behaviour.
    assert model.plausible("social:apology", "social:goodbye") is True


def test_probabilities_are_smoothed_and_sum_to_one() -> None:
    model = _model(smoothing=1.0)

    total = sum(probability for _, probability in model.rank("social:greeting"))

    assert total == pytest.approx(1.0)
    # Smoothing spreads mass onto the unseen act, so it is small but not zero.
    assert model.probability("social:goodbye", "social:greeting") > 0


def test_an_unseen_act_after_a_known_turn_is_implausible() -> None:
    model = _model()

    assert model.plausible("social:greeting", "social:greeting") is True
    assert model.plausible("social:apology", "social:greeting") is False


def test_an_unknown_previous_act_vetoes_nothing() -> None:
    model = _model()

    # The table has nothing to say about a row it has never seen, so it says nothing.
    assert model.plausible("social:apology", "lore:relic") is True
    assert model.plausible("social:apology", None) is True


def test_rank_orders_by_probability_then_name() -> None:
    order = [act for act, _ in _model().rank("social:greeting")]

    assert order[:2] == ["social:greeting", "social:howareyou"]
    assert order[2:] == sorted(order[2:])


def test_counts_must_be_non_negative_integers() -> None:
    with pytest.raises(TransitionError, match="non-negative integer"):
        TransitionModel({"a": {"b": -1}})
    # True is an int in Python; a bool here is a mistake, not a count.
    with pytest.raises(TransitionError, match="non-negative integer"):
        TransitionModel({"a": {"b": True}})
    with pytest.raises(TransitionError, match="non-negative integer"):
        TransitionModel({"a": {"b": 1.5}})


def test_rows_and_acts_must_be_named() -> None:
    with pytest.raises(TransitionError, match="non-blank act"):
        TransitionModel({" ": {"b": 1}})
    with pytest.raises(TransitionError, match="blank act"):
        TransitionModel({"a": {" ": 1}})


def test_zero_counts_are_dropped_so_they_veto() -> None:
    model = TransitionModel({"social:greeting": {"social:greeting": 0}})

    assert model.plausible("social:greeting", "social:greeting") is False


def test_a_table_round_trips_through_a_file(tmp_path: Path) -> None:
    original = _model(source="switchboard")

    path = original.save(tmp_path / "nested" / "transitions.json")
    loaded = TransitionModel.load(path)

    assert loaded.source == "switchboard"
    assert loaded.acts == original.acts
    assert loaded.rank("social:greeting") == original.rank("social:greeting")


def test_a_missing_file_is_not_an_error(tmp_path: Path) -> None:
    assert TransitionModel.from_file(tmp_path / "absent.json") is None


def test_a_broken_file_says_where_it_broke(tmp_path: Path) -> None:
    path = tmp_path / "transitions.json"
    path.write_text("{not json", encoding="utf-8")

    with pytest.raises(TransitionError, match="not valid JSON"):
        TransitionModel.load(path)


def test_an_unknown_schema_version_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "transitions.json"
    path.write_text(json.dumps({"schema_version": 99, "counts": {}}), encoding="utf-8")

    with pytest.raises(TransitionError, match="unsupported transition schema version 99"):
        TransitionModel.load(path)


def test_a_table_without_counts_is_refused() -> None:
    with pytest.raises(TransitionError, match="needs a 'counts' object"):
        TransitionModel.from_dict({"schema_version": SCHEMA_VERSION})


def test_counts_from_pairs_drops_unlabelled_turns() -> None:
    counts = counts_from_pairs(
        [
            ("social:greeting", "social:greeting"),
            (None, "social:thanks"),
            ("social:thanks", None),
            ("social:greeting", "social:greeting"),
        ]
    )

    assert counts == {"social:greeting": {"social:greeting": 2}}
