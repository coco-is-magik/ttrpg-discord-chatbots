"""The database: incremental writes, recovery, concurrency, and the migration.

Every test here corresponds to a claim I made when arguing for this over a JSON document. If one of
them fails, the argument was wrong.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path

import pytest

from ttrpg_chatbots.bots.memory import FriendMemory, migrate_legacy
from ttrpg_chatbots.memory.db import Database, DatabaseError
from ttrpg_chatbots.memory.encode import read as encode


def _memory(directory: Path, friend: str = "friend-a", person: str = "tav") -> FriendMemory:
    return FriendMemory(friend, directory=directory, person=person)


def _payload(**overrides) -> dict:
    base = {
        "person": "tav",
        "last_seen": "2026-10-22T20:00:00+00:00",
        "sessions": 3,
        "pending_plan": False,
        "facts": [{"key": "pet.name", "value": "otis", "meta": {"word": "dog"}}],
        "topics": {"social:greeting": 2},
        "pending": {"like=hockey": 1},
        "telling": {"grandfathers-axe": 1},
    }
    base.update(overrides)
    return base


# --- the schema and the basics ---------------------------------------------------------------


def test_a_friend_round_trips_through_the_database(tmp_path) -> None:
    db = Database(tmp_path / "memory.db")
    db.save("friend-a", _payload(), changed=["test"])

    loaded = db.load("friend-a")

    assert loaded["person"] == "tav"
    assert loaded["facts"][0]["value"] == "otis"
    assert loaded["facts"][0]["meta"] == {"word": "dog"}
    assert loaded["topics"] == {"social:greeting": 2}
    assert loaded["telling"] == {"grandfathers-axe": 1}


def test_an_unknown_friend_is_empty_rather_than_an_error(tmp_path) -> None:
    loaded = Database(tmp_path / "memory.db").load("nobody")

    assert loaded["person"] == ""
    assert loaded["facts"] == []


def test_the_schema_is_versioned(tmp_path) -> None:
    db = Database(tmp_path / "memory.db")
    db.ensure()

    with sqlite3.connect(db.path) as connection:
        version = connection.execute(
            "SELECT value FROM meta WHERE key = 'schema_version'"
        ).fetchone()[0]

    assert version == "1"


def test_a_corrupt_file_is_reported_rather_than_silently_empty(tmp_path) -> None:
    path = tmp_path / "memory.db"
    path.write_text("this is not a database", encoding="utf-8")

    with pytest.raises(DatabaseError):
        Database(path).load("friend-a")


# --- the property the document could not have ------------------------------------------------


def test_a_save_does_not_rewrite_another_friends_rows(tmp_path) -> None:
    # The document rewrote everything on every save. This is the whole reason for the move: the cost
    # of a write is one friend, not the database.
    db = Database(tmp_path / "memory.db")
    db.save("friend-a", _payload())
    db.save("friend-b", _payload(person="nobody", facts=[]))

    before = _row_count(db)
    db.save("friend-b", _payload(person="nobody", facts=[], sessions=9))
    after = _row_count(db)

    assert db.load("friend-a")["person"] == "tav", "untouched"
    assert after <= before + 2, "one friend's rows, not the whole table"


def test_dropping_the_other_facts_is_a_save_not_a_merge(tmp_path) -> None:
    db = Database(tmp_path / "memory.db")
    db.save("friend-a", _payload())
    db.save("friend-a", _payload(facts=[]))

    assert db.load("friend-a")["facts"] == [], "a forgotten fact must not linger as a row"


def _row_count(db: Database) -> int:
    with sqlite3.connect(db.path) as connection:
        return sum(
            connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            for table in ("friend", "fact", "topic", "pending", "telling")
        )


# --- recovery ---------------------------------------------------------------------------------


def test_integrity_check_says_ok(tmp_path) -> None:
    db = Database(tmp_path / "memory.db")
    db.save("friend-a", _payload())

    assert db.check() == "ok"


def test_a_backup_is_a_consistent_copy(tmp_path) -> None:
    db = Database(tmp_path / "memory.db")
    db.save("friend-a", _payload())

    copy = db.backup(tmp_path / "backup" / "memory.db")

    assert copy.is_file()
    assert Database(copy).load("friend-a")["facts"][0]["value"] == "otis"


def test_a_backup_survives_the_original_being_destroyed(tmp_path) -> None:
    db = Database(tmp_path / "memory.db")
    db.save("friend-a", _payload())
    copy = db.backup(tmp_path / "backup.db")
    db.path.unlink()

    assert Database(copy).load("friend-a")["person"] == "tav"


def test_every_change_is_journalled(tmp_path) -> None:
    # The recovery story: a bad write can be seen, and therefore undone.
    db = Database(tmp_path / "memory.db")
    db.save("friend-a", _payload(), changed=["fact"])
    db.forget("friend-a", "pet.name")

    history = db.history("friend-a")

    assert [entry["kind"] for entry in history] == ["save", "forget"]
    assert history[-1]["detail"] == "pet.name"


# --- concurrency ------------------------------------------------------------------------------


def test_two_writers_do_not_clobber_each_other(tmp_path) -> None:
    # Three bots are planned, not one, and the data is on NFS. The busy timeout is what makes this
    # queue instead of fail.
    db = Database(tmp_path / "memory.db")
    errors: list[BaseException] = []

    def write(friend: str) -> None:
        try:
            for _ in range(10):
                db.save(friend, _payload(person=friend))
        except BaseException as error:  # noqa: BLE001 - the test wants to see it
            errors.append(error)

    threads = [threading.Thread(target=write, args=(name,)) for name in ("friend-a", "friend-b")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not errors
    assert db.load("friend-a")["person"] == "friend-a"
    assert db.load("friend-b")["person"] == "friend-b"



# --- the migration ----------------------------------------------------------------------------


def test_the_old_json_files_are_imported_once(tmp_path) -> None:
    # The dog's name was learned before the database existed; a migration that drops it is not one.
    legacy = tmp_path / "friends"
    legacy.mkdir()
    (legacy / "friend-a.json").write_text(
        json.dumps(
            {
                "person": "tav",
                "sessions": 17,
                "last_seen": "2026-10-22T19:17:11+00:00",
                "pending_plan": False,
                "facts": [
                    {
                        "key": "pet.name",
                        "value": "otis",
                        "said_by": "them",
                        "first_seen": "2026-10-22T19:17:11+00:00",
                        "last_seen": "2026-10-22T19:30:28+00:00",
                        "count": 2,
                        "meta": {"word": "dog", "raised": "2026-10-22"},
                    }
                ],
                "topics": {"social:greeting": 5, "story:grandfathers-axe": 1},
                "pending": {"like=hockey": 1},
            }
        ),
        encoding="utf-8",
    )

    imported = migrate_legacy(tmp_path)

    assert imported == ("friend-a",)
    memory = FriendMemory.load("friend-a", directory=tmp_path)
    assert [(fact.key, fact.value, fact.meta.get("word")) for fact in memory.facts] == [
        ("pet.name", "otis", "dog")
    ]
    assert memory.telling["grandfathers-axe"] == 1, "story counts move to their own table"
    assert "story:grandfathers-axe" not in memory.topics, "and out of the capped topic counter"

    # Idempotent: running it again does not duplicate or overwrite.
    assert migrate_legacy(tmp_path) == ()
    assert FriendMemory.load("friend-a", directory=tmp_path).sessions == 17


def test_a_broken_legacy_file_is_skipped_not_fatal(tmp_path) -> None:
    legacy = tmp_path / "friends"
    legacy.mkdir()
    (legacy / "friend-a.json").write_text("{ not json", encoding="utf-8")

    assert migrate_legacy(tmp_path) == ()


def test_the_database_wins_over_a_stale_json_file(tmp_path) -> None:
    legacy = tmp_path / "friends"
    legacy.mkdir()
    (legacy / "friend-a.json").write_text(json.dumps({"person": "old name"}), encoding="utf-8")

    memory = _memory(tmp_path, person="new name")
    memory.save()

    assert migrate_legacy(tmp_path) == ()
    assert FriendMemory.load("friend-a", directory=tmp_path).person == "new name"


# --- through FriendMemory ----------------------------------------------------------------------


def test_a_fact_survives_a_restart(tmp_path) -> None:
    memory = _memory(tmp_path)
    memory.remember_facts(encode("my dog is called otis"))
    memory.save()

    reloaded = FriendMemory.load("friend-a", directory=tmp_path)

    assert [(fact.key, fact.value, fact.meta.get("word")) for fact in reloaded.facts] == [
        ("pet.name", "otis", "dog")
    ]


def test_a_story_told_is_counted_in_its_own_table(tmp_path) -> None:
    memory = _memory(tmp_path)
    memory.remember_told("grandfathers-axe")

    reloaded = FriendMemory.load("friend-a", directory=tmp_path)

    assert reloaded.telling["grandfathers-axe"] == 1


def test_forgetting_deletes_the_row_and_journals_it(tmp_path) -> None:
    memory = _memory(tmp_path)
    memory.remember_facts(encode("my dog is called otis"))
    memory.save()

    assert memory.forget("pet.name") is True
    assert FriendMemory.load("friend-a", directory=tmp_path).facts == ()
    kinds = [entry["kind"] for entry in Database(tmp_path / "memory.db").history("friend-a")]
    assert "forget" in kinds


def test_a_friend_with_no_database_yet_is_simply_empty(tmp_path) -> None:
    memory = FriendMemory.load("friend-a", directory=tmp_path)

    assert memory.facts == ()
    assert memory.person == ""
