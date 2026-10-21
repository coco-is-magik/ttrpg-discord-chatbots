"""Reading a real corpus into our act table, and refusing to pretend it went well.

The fixtures are Switchboard-shaped, not Switchboard: what is under test is the reading and the
arithmetic, which is the part that can be wrong. ``docs/CLASSIFIER.md`` has the download command
for the real thing.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ttrpg_chatbots.reply.importers import (
    SWDA_MAP,
    CorpusError,
    Import,
    from_jsonl,
    from_switchboard,
)


def _utterance(conversation: str, index: int, *tags: str, shape: str = "tag") -> dict:
    """One Convokit-shaped utterance, with tags in the shape that reader has to handle."""
    record: dict = {
        "id": f"{conversation}-{index}",
        "speaker": "A" if index % 2 else "B",
        "conversation_id": conversation,
        "reply_to": None,
        "text": "something",
        "meta": {},
    }
    if shape == "tag":
        record["meta"]["tag"] = [["something", tag] for tag in tags]
    else:
        record["meta"]["tags"] = list(tags)
    return record


def _write(path: Path, records: list[dict]) -> Path:
    path.write_text(
        "\n".join(json.dumps(record) for record in records) + "\n", encoding="utf-8"
    )
    return path


def test_switchboard_pairs_are_counted_within_a_conversation(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "utterances.jsonl",
        [
            _utterance("4325-0", 0, "fp"),
            _utterance("4325-0", 1, "ft"),
            _utterance("4325-0", 2, "fc"),
            _utterance("5000-0", 0, "fp"),
            _utterance("5000-0", 1, "fp"),
        ],
    )

    result = from_switchboard(path)

    assert result.counts == {
        "social:greeting": {"social:thanks": 1, "social:greeting": 1},
        "social:thanks": {"social:goodbye": 1},
    }
    assert result.pairs == 3
    # Greeting at the end of one call must not be paired with the next call's opening.
    assert "social:goodbye" not in result.counts
    assert result.utterances == 5
    assert result.coverage == 1.0


def test_composite_tags_use_their_first_mapped_part(tmp_path: Path) -> None:
    # SwDA writes combinations as qy^d, sd+sv, qy^t; the turn is one turn either way.
    path = _write(
        tmp_path / "utterances.jsonl",
        [
            _utterance("1", 0, "sd+sv"),
            _utterance("1", 1, "aa^g"),
            _utterance("1", 2, "qy^d"),
        ],
    )

    result = from_switchboard(path)

    assert result.counts["social:smalltalk"] == {"social:agreement": 1}
    # qy^d maps to nothing we have, so the corpus says so instead of inventing an edge.
    assert result.unmapped["qy^d"] == 1
    assert result.coverage == pytest.approx(2 / 3)


def test_the_tags_list_shape_is_read_too(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "utterances.jsonl",
        [_utterance("1", 0, "fp", shape="tags"), _utterance("1", 1, "fc", shape="tags")],
    )

    result = from_switchboard(path)

    assert result.counts == {"social:greeting": {"social:goodbye": 1}}


def test_an_unlabelled_turn_is_bridged_but_reported(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "utterances.jsonl",
        [
            _utterance("1", 0, "fp"),
            _utterance("1", 1, "qw"),
            _utterance("1", 2, "ft"),
        ],
    )

    result = from_switchboard(path)

    # greeting -> thanks, skipping the question we cannot name, and the cost is visible.
    assert result.counts == {"social:greeting": {"social:thanks": 1}}
    assert result.coverage == pytest.approx(2 / 3)
    assert result.unmapped["qw"] == 1


def test_a_custom_mapping_overrides_the_default(tmp_path: Path) -> None:
    path = _write(tmp_path / "utterances.jsonl", [_utterance("1", 0, "fp")])

    result = from_switchboard(path, mapping={"fp": "custom:opening"})

    assert result.mapped == 1
    assert SWDA_MAP["fp"] == "social:greeting"  # the default is untouched


def test_an_utterance_without_a_conversation_is_refused(tmp_path: Path) -> None:
    record = _utterance("1", 0, "fp")
    del record["conversation_id"]
    path = _write(tmp_path / "utterances.jsonl", [record])

    with pytest.raises(CorpusError, match="no conversation_id"):
        from_switchboard(path)


def test_low_coverage_can_be_refused_outright(tmp_path: Path) -> None:
    # Two lines we understand, two we do not, and one usable edge between them.
    path = _write(
        tmp_path / "utterances.jsonl",
        [
            _utterance("1", 0, "fp"),
            _utterance("1", 1, "qw"),
            _utterance("1", 2, "qw"),
            _utterance("1", 3, "fp"),
        ],
    )

    result = from_switchboard(path)

    assert result.coverage == 0.5
    assert result.pairs == 1
    with pytest.raises(CorpusError, match="below the required"):
        result.model(min_coverage=0.9)
    assert result.model(min_coverage=0.5).source == "switchboard"


def test_a_corpus_with_nothing_usable_raises() -> None:
    empty = Import(source="empty", counts={}, utterances=3)

    with pytest.raises(CorpusError, match="no usable transitions"):
        empty.model()


def test_the_report_names_coverage_and_the_worst_labels(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "utterances.jsonl",
        [_utterance("1", 0, "fp"), _utterance("1", 1, "qw")],
    )

    report = from_switchboard(path).report()

    assert "2 utterances" in report
    assert "1 mapped (50%)" in report
    assert "qw=1" in report


def test_jsonl_flat_rows_are_paired_per_conversation(tmp_path: Path) -> None:
    path = tmp_path / "acts.jsonl"
    path.write_text(
        "\n".join(
            json.dumps(row)
            for row in [
                {"conversation": "a", "index": 0, "act": "social:greeting"},
                {"conversation": "a", "index": 1, "act": "social:greeting"},
                {"conversation": "b", "index": 0, "act": "social:thanks"},
                {"conversation": "b", "index": 1, "act": "social:goodbye"},
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    result = from_jsonl(path, source="fixture")

    assert result.counts == {
        "social:greeting": {"social:greeting": 1},
        "social:thanks": {"social:goodbye": 1},
    }
    assert result.model().source == "fixture"


def test_jsonl_dialogue_rows_are_read_in_order(tmp_path: Path) -> None:
    path = tmp_path / "dialogues.jsonl"
    path.write_text(
        json.dumps(
            {
                "conversation": "x",
                "turns": [
                    {"act": "social:greeting"},
                    {"act": "social:howareyou"},
                    {"act": "social:agreement"},
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    result = from_jsonl(path)

    assert result.counts == {
        "social:greeting": {"social:howareyou": 1},
        "social:howareyou": {"social:agreement": 1},
    }


def test_a_broken_line_names_itself(tmp_path: Path) -> None:
    path = tmp_path / "bad.jsonl"
    path.write_text('{"act": "social:greeting"}\nnot json\n', encoding="utf-8")

    with pytest.raises(CorpusError, match=r"bad\.jsonl:2: not valid JSON"):
        from_jsonl(path)


def test_an_empty_file_is_an_error_not_an_empty_table(tmp_path: Path) -> None:
    path = tmp_path / "empty.jsonl"
    path.write_text("# only a comment\n", encoding="utf-8")

    with pytest.raises(CorpusError, match="no records"):
        from_jsonl(path)


def test_a_missing_file_is_reported_as_a_corpus_error(tmp_path: Path) -> None:
    with pytest.raises(CorpusError, match="cannot read"):
        from_switchboard(tmp_path / "absent.jsonl")
