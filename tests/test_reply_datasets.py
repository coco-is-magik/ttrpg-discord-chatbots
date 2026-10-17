import json

import pytest

from ttrpg_chatbots.reply.datasets import load_world, read_jsonl
from ttrpg_chatbots.reply.types import DatasetError, UnknownCharacter

from reply_support import DEMO_WORLD


def _write(root, name: str, records) -> None:
    lines = [record if isinstance(record, str) else json.dumps(record) for record in records]
    (root / name).write_text("\n".join(lines) + "\n", encoding="utf-8")


def _minimal(root) -> None:
    _write(root, "characters.jsonl", [{"id": "ann", "name": "Ann", "known_tags": ["t:one"]}])
    _write(root, "knowledge.jsonl", [{"id": "k1", "text": "the tide turns", "tags": ["t:one"]}])
    _write(
        root,
        "responses.jsonl",
        [{"id": "r1", "character": "ann", "tags": ["t:one"], "template": "{fact}"}],
    )


def test_loads_the_demo_world() -> None:
    world = load_world(DEMO_WORLD)
    assert world.name == "The Saltreach"
    assert len(world.knowledge) == 13
    assert len(world.responses) == 20
    assert len(world.characters) == 3
    assert world.knowledge[0].slots["subject"] == "the Sunken Crown"


def test_character_lookup_accepts_id_or_display_name() -> None:
    world = load_world(DEMO_WORLD)
    assert world.character("brannoc").name == "Brannoc the Archivist"
    assert world.character("BRANNOC THE ARCHIVIST").id == "brannoc"
    assert world.character(" Sable ").id == "sable"


def test_unknown_character_lists_the_known_ones() -> None:
    with pytest.raises(UnknownCharacter, match="orla"):
        load_world(DEMO_WORLD).character("gandalf")


def test_id_that_matches_its_name_case_insensitively_is_allowed(tmp_path) -> None:
    """Regression: 'sable'/'Sable' used to collide with itself."""
    _minimal(tmp_path)
    _write(
        tmp_path, "characters.jsonl", [{"id": "sable", "name": "Sable", "known_tags": ["t:one"]}]
    )
    _write(
        tmp_path,
        "responses.jsonl",
        [{"id": "r1", "character": "sable", "tags": ["t:one"], "template": "{fact}"}],
    )
    assert load_world(tmp_path).character("Sable").id == "sable"


def test_two_characters_sharing_a_name_are_rejected(tmp_path) -> None:
    _minimal(tmp_path)
    _write(tmp_path, "characters.jsonl", [{"id": "a", "name": "Same"}, {"id": "b", "name": "same"}])
    with pytest.raises(DatasetError, match="both"):
        load_world(tmp_path)


def test_missing_directory_is_reported(tmp_path) -> None:
    with pytest.raises(DatasetError, match="does not exist"):
        load_world(tmp_path / "absent")


def test_missing_file_is_named(tmp_path) -> None:
    _minimal(tmp_path)
    (tmp_path / "knowledge.jsonl").unlink()
    with pytest.raises(DatasetError, match="knowledge.jsonl"):
        load_world(tmp_path)


def test_bad_json_reports_the_line_number(tmp_path) -> None:
    _minimal(tmp_path)
    (tmp_path / "knowledge.jsonl").write_text(
        '{"id": "k1", "text": "the tide turns", "tags": ["t:one"]}\n{oops\n',
        encoding="utf-8",
    )
    with pytest.raises(DatasetError, match=r"knowledge\.jsonl:2"):
        load_world(tmp_path)


def test_non_object_records_are_rejected(tmp_path) -> None:
    _minimal(tmp_path)
    (tmp_path / "knowledge.jsonl").write_text("[1, 2, 3]\n", encoding="utf-8")
    with pytest.raises(DatasetError, match="JSON object"):
        load_world(tmp_path)


def test_duplicate_ids_are_rejected(tmp_path) -> None:
    _minimal(tmp_path)
    _write(
        tmp_path,
        "knowledge.jsonl",
        [
            {"id": "k1", "text": "first", "tags": ["t:one"]},
            {"id": "k1", "text": "second", "tags": ["t:one"]},
        ],
    )
    with pytest.raises(DatasetError, match="duplicate"):
        load_world(tmp_path)


def test_blank_text_is_rejected(tmp_path) -> None:
    _minimal(tmp_path)
    _write(tmp_path, "knowledge.jsonl", [{"id": "k1", "text": "   ", "tags": ["t:one"]}])
    with pytest.raises(DatasetError, match="text"):
        load_world(tmp_path)


def test_missing_tags_are_rejected(tmp_path) -> None:
    _minimal(tmp_path)
    _write(tmp_path, "knowledge.jsonl", [{"id": "k1", "text": "the tide turns"}])
    with pytest.raises(DatasetError, match="tags"):
        load_world(tmp_path)


def test_a_template_for_an_unknown_character_is_rejected(tmp_path) -> None:
    _minimal(tmp_path)
    _write(
        tmp_path,
        "responses.jsonl",
        [{"id": "r1", "character": "ghost", "tags": ["t:one"], "template": "{fact}"}],
    )
    with pytest.raises(DatasetError, match="unknown character"):
        load_world(tmp_path)


def test_an_empty_file_is_rejected(tmp_path) -> None:
    _minimal(tmp_path)
    (tmp_path / "knowledge.jsonl").write_text("# only comments\n\n", encoding="utf-8")
    with pytest.raises(DatasetError, match="no records"):
        load_world(tmp_path)


def test_unknown_fields_survive_in_meta(tmp_path) -> None:
    """Future-proofing: extra columns must not break the loaders."""
    _write(
        tmp_path,
        "characters.jsonl",
        [{"id": "ann", "name": "Ann", "known_tags": ["t:one"], "voice_id": "en_07"}],
    )
    _write(
        tmp_path,
        "knowledge.jsonl",
        [{"id": "k1", "text": "the tide turns", "tags": ["t:one"], "source": "book"}],
    )
    _write(
        tmp_path,
        "responses.jsonl",
        [{"id": "r1", "character": "ann", "tags": ["t:one"], "template": "{fact}", "weight": 3}],
    )
    world = load_world(tmp_path)
    assert world.characters[0].meta == {"voice_id": "en_07"}
    assert world.knowledge[0].meta == {"source": "book"}
    assert world.responses[0].meta == {"weight": 3}


def test_slots_are_coerced_to_strings(tmp_path) -> None:
    _minimal(tmp_path)
    _write(
        tmp_path,
        "knowledge.jsonl",
        [{"id": "k1", "text": "the tide turns", "tags": ["t:one"], "slots": {"count": 3}}],
    )
    assert load_world(tmp_path).knowledge[0].slots == {"count": "3"}


def test_comments_and_blank_lines_are_tolerated(tmp_path) -> None:
    _minimal(tmp_path)
    (tmp_path / "knowledge.jsonl").write_text(
        '# a note\n\n{"id": "k1", "text": "the tide turns", "tags": ["t:one"]}\n',
        encoding="utf-8",
    )
    assert len(load_world(tmp_path).knowledge) == 1


def test_manifest_is_optional(tmp_path) -> None:
    _minimal(tmp_path)
    assert load_world(tmp_path).name == tmp_path.name


def test_character_tags_are_parsed(tmp_path) -> None:
    _minimal(tmp_path)
    _write(
        tmp_path,
        "characters.jsonl",
        [{"id": "ann", "name": "Ann", "known_tags": ["t:one"], "tags": ["role:scout"]}],
    )
    assert load_world(tmp_path).characters[0].tags == frozenset({"role:scout"})


def test_character_tags_default_to_empty(tmp_path) -> None:
    _minimal(tmp_path)
    assert load_world(tmp_path).characters[0].tags == frozenset()


def test_character_tags_are_not_meta(tmp_path) -> None:
    """``tags`` is a known field; anything else still lands in meta."""
    _minimal(tmp_path)
    _write(
        tmp_path,
        "characters.jsonl",
        [
            {
                "id": "ann",
                "name": "Ann",
                "known_tags": ["t:one"],
                "tags": ["role:scout"],
                "voice_note": "cast later",
            }
        ],
    )
    character = load_world(tmp_path).characters[0]
    assert character.tags == frozenset({"role:scout"})
    assert character.meta == {"voice_note": "cast later"}


def test_demo_characters_carry_identity_tags() -> None:
    world = load_world(DEMO_WORLD)
    assert world.character("brannoc").tags == frozenset({"role:scholar", "species:dwarf"})


def test_broken_manifest_is_reported(tmp_path) -> None:
    _minimal(tmp_path)
    (tmp_path / "world.json").write_text("{nope", encoding="utf-8")
    with pytest.raises(DatasetError, match="world.json"):
        load_world(tmp_path)


def test_read_jsonl_reports_a_missing_file(tmp_path) -> None:
    with pytest.raises(DatasetError, match="cannot read"):
        list(read_jsonl(tmp_path / "absent.jsonl"))
