"""The voice lock: the voice on disk is the voice we chose, and we can get it again.

No network here. A ``file://`` source stands in for a mirror, which is enough to prove the parts that
matter: digests are checked, a source that serves the wrong bytes is rejected rather than trusted, and
a lock that cannot reproduce its own files is refused before anything is downloaded.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ttrpg_chatbots.tts import lock as lock_module

WORLD = Path("examples/friends_world/voices.lock.json")


def _write(directory: Path, name: str, payload: bytes) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_bytes(payload)
    return path


def _lock(directory: Path, payload: bytes = b"model-bytes", **overrides) -> lock_module.VoiceLock:
    source = directory / "source"
    source.mkdir(exist_ok=True)
    _write(source, "en_US-fake-medium.onnx", payload)
    record = {
        "voice": "en_US-fake-medium",
        "engine": "piper",
        "files": [
            {
                "name": "en_US-fake-medium.onnx",
                "bytes": len(payload),
                "sha256": lock_module.digest(source / "en_US-fake-medium.onnx"),
            }
        ],
        # Built by hand rather than with Path.as_uri(), which percent-encodes the braces and would
        # make the placeholder invisible to the loader.
        "sources": [f"{source.as_uri()}/{{file}}"],
    }
    record.update(overrides)
    path = directory / "voices.lock.json"
    path.write_text(json.dumps(record), encoding="utf-8")
    return lock_module.load(path).for_voice(record["voice"])


class TestTheRealLock:
    def test_the_shipped_lock_loads(self) -> None:
        pinned = lock_module.load(WORLD)
        assert "en_US-joe-medium" in pinned.names()
        assert pinned.for_voice("en_US-joe-medium").engine == "piper"

    def test_every_speaking_friend_has_his_own_entry(self) -> None:
        """A world has more than one voice, and the second one has to be pinned too.

        Measured before this: Otto started with en_US-ryan-medium and the log said "voice
        en_US-joe-medium verified against its lock" -- a reassurance about somebody else's model.
        """
        import json

        from ttrpg_chatbots.bots.persona import Persona

        roster = json.loads(Path("examples/bots.example.json").read_text(encoding="utf-8"))
        speaking = [
            Persona.from_record(bot["persona"], where=bot["id"])
            for bot in roster
            if bot.get("persona") and bot.get("reply") == "mention"
        ]
        pinned = lock_module.load(WORLD)

        assert speaking, "the roster has somebody who talks"
        for persona in speaking:
            assert persona.voice is not None
            assert pinned.for_voice(persona.voice.voice) is not None, (
                f"{persona.name} speaks {persona.voice.voice}, which the lock does not pin"
            )

    def test_a_voice_nobody_pins_is_not_found_rather_than_guessed(self) -> None:
        assert lock_module.load(WORLD).for_voice("en_US-nope-medium") is None

    def test_the_shipped_lock_names_more_than_one_source(self) -> None:
        """One mirror is not a plan: the point of the lock is surviving a host going away."""
        for lock in lock_module.load(WORLD):
            assert len(lock.sources) >= 2

    def test_the_shipped_lock_carries_provenance(self) -> None:
        pinned = lock_module.load(WORLD)
        joe = pinned.for_voice("en_US-joe-medium")
        assert joe.provenance["license"] == "CC0"
        assert "lessac" in joe.provenance["finetuned_from"]

    def test_every_pinned_voice_records_its_licence(self) -> None:
        """The licences differ between voices, and the difference has to be written down.

        Terry's dataset is CC0 and Otto's is public domain, but an earlier candidate for Otto was CC
        BY-NC-SA -- non-commercial. A private table is fine either way; a commercial thing is not, and
        that is the kind of fact that has to be visible in the lock rather than remembered.
        """
        pinned = lock_module.load(WORLD)

        assert len(pinned) >= 2
        for lock in pinned:
            assert lock.provenance.get("license"), f"{lock.voice} has no licence recorded"
            assert lock.provenance.get("dataset"), f"{lock.voice} has no dataset recorded"

    def test_the_settings_match_the_casting_rule(self) -> None:
        """The lock records the speed that was tuned by ear, so a rebuild is not a re-guess."""
        from ttrpg_chatbots.bots.voice import data_directory
        from ttrpg_chatbots.tts.casting import load_voice_directory

        rules = load_voice_directory(data_directory()).rules
        # Both directions, and the first one used to raise a bare `StopIteration` that said nothing:
        # the lock pins the voices *in use*, so a pinned voice no rule casts is a stale entry (kristin
        # was tuned by ear four times and then replaced), and a rule with no pin cannot be rebuilt.
        cast = {rule.profile.voice for rule in rules if rule.profile.voice}
        pinned = {entry.voice for entry in lock_module.load(WORLD)}
        assert pinned == cast, f"pinned but unused: {pinned - cast}; used but unpinned: {cast - pinned}"
        for entry in lock_module.load(WORLD):
            pinned = entry
            rule = next(rule for rule in rules if rule.profile.voice == pinned.voice)
            assert rule.profile.speed == pinned.settings["speed"]
            # Whatever the lock records about the delivery must match the rule: `pitch` is the crude
            # resample ratio, `pitch_hz`/`formant` the formant-aware pair. A rule that drifted from
            # its lock would be rebuilt as somebody else.
            for key in ("pitch", "pitch_hz", "formant", "volume"):
                if key in pinned.settings:
                    assert getattr(rule.profile, key) == pinned.settings[key], key

    def test_the_locked_files_are_the_ones_cached(self) -> None:
        """If this fails, the voice on this box is not the voice the repository pins."""
        from ttrpg_chatbots.tts.engines.piper_engine import voice_dir

        pinned = lock_module.load(WORLD)
        cached = [item for lock in pinned for item in lock.files if (voice_dir() / item.name).exists()]
        if not cached:
            pytest.skip("no locked voice is cached on this box")
        for lock in pinned:
            if any((voice_dir() / item.name).exists() for item in lock.files):
                report = lock_module.verify(lock, voice_dir())
                assert report.ok, report.summary()


class TestVerify:
    def test_a_matching_file_verifies(self, tmp_path: Path) -> None:
        pinned = _lock(tmp_path)
        assert lock_module.verify(pinned, tmp_path / "source").ok

    def test_a_missing_file_is_reported_by_name(self, tmp_path: Path) -> None:
        pinned = _lock(tmp_path)
        report = lock_module.verify(pinned, tmp_path / "empty")
        assert not report.ok
        assert "en_US-fake-medium.onnx is missing" in report.summary()

    def test_a_truncated_file_is_reported(self, tmp_path: Path) -> None:
        pinned = _lock(tmp_path)
        _write(tmp_path, "en_US-fake-medium.onnx", b"model")
        assert "expected" in lock_module.verify(pinned, tmp_path).summary()

    def test_the_same_size_but_wrong_bytes_is_reported(self, tmp_path: Path) -> None:
        """Size alone is not proof: a corrupted download can be the right length."""
        pinned = _lock(tmp_path)
        _write(tmp_path, "en_US-fake-medium.onnx", b"MODEL-BYTES")
        assert "sha256 differs" in lock_module.verify(pinned, tmp_path).summary()

    def test_a_truncated_file_is_reported_by_size(self, tmp_path: Path) -> None:
        pinned = _lock(tmp_path)
        _write(tmp_path, "en_US-fake-medium.onnx", b"short")
        assert "expected 11" in lock_module.verify(pinned, tmp_path).summary()


class TestFetch:
    def test_it_downloads_what_is_missing(self, tmp_path: Path) -> None:
        pinned = _lock(tmp_path)
        report = lock_module.fetch(pinned, tmp_path / "cache")
        assert report.ok, report.summary()
        assert report.fetched == ["en_US-fake-medium.onnx"]
        assert lock_module.verify(pinned, tmp_path / "cache").ok

    def test_it_leaves_a_correct_file_alone(self, tmp_path: Path) -> None:
        pinned = _lock(tmp_path)
        cache = tmp_path / "cache"
        _write(cache, "en_US-fake-medium.onnx", b"model-bytes")
        report = lock_module.fetch(pinned, cache)
        assert report.ok and report.fetched == []

    def test_a_source_serving_the_wrong_bytes_is_rejected(self, tmp_path: Path) -> None:
        """A mirror cannot quietly change the voice: the digest decides, not the hostname."""
        pinned = _lock(tmp_path)
        _write(tmp_path / "source", "en_US-fake-medium.onnx", b"someone-elses-voice")
        report = lock_module.fetch(pinned, tmp_path / "cache")
        assert not report.ok
        assert "wrong bytes" in report.summary()
        assert not (tmp_path / "cache" / "en_US-fake-medium.onnx").exists()

    def test_it_falls_through_to_the_second_source(self, tmp_path: Path) -> None:
        pinned = _lock(tmp_path)
        broken = tmp_path / "broken"
        broken.mkdir()
        record = json.loads((tmp_path / "voices.lock.json").read_text())
        record["sources"] = [f"{broken.as_uri()}/{{file}}", record["sources"][0]]
        (tmp_path / "voices.lock.json").write_text(json.dumps(record))
        pinned = lock_module.load(tmp_path / "voices.lock.json").for_voice(record["voice"])

        report = lock_module.fetch(pinned, tmp_path / "cache")

        assert report.ok, report.summary()
        assert report.fetched == ["en_US-fake-medium.onnx"]


class TestRefusingBadLocks:
    def test_a_lock_with_no_sources_is_refused(self, tmp_path: Path) -> None:
        _lock(tmp_path)
        record = json.loads((tmp_path / "voices.lock.json").read_text())
        record["sources"] = []
        (tmp_path / "voices.lock.json").write_text(json.dumps(record))
        with pytest.raises(lock_module.LockError, match="at least one source"):
            lock_module.load(tmp_path / "voices.lock.json")

    def test_a_source_without_the_file_placeholder_is_refused(self, tmp_path: Path) -> None:
        """Otherwise the lock would look reproducible while being unable to fetch its own model."""
        _lock(tmp_path)
        record = json.loads((tmp_path / "voices.lock.json").read_text())
        record["sources"] = ["https://example.invalid/one-file.onnx"]
        (tmp_path / "voices.lock.json").write_text(json.dumps(record))
        with pytest.raises(lock_module.LockError, match="no source contains"):
            lock_module.load(tmp_path / "voices.lock.json")

    def test_a_short_digest_is_refused(self, tmp_path: Path) -> None:
        _lock(tmp_path)
        record = json.loads((tmp_path / "voices.lock.json").read_text())
        record["files"][0]["sha256"] = "abc"
        (tmp_path / "voices.lock.json").write_text(json.dumps(record))
        with pytest.raises(lock_module.LockError, match="64 hex"):
            lock_module.load(tmp_path / "voices.lock.json")

    def test_a_missing_lock_says_where_it_looked(self, tmp_path: Path) -> None:
        with pytest.raises(lock_module.LockError, match="no voice lock at"):
            lock_module.load(tmp_path / "nothing.json")

    def test_invalid_json_is_reported_as_such(self, tmp_path: Path) -> None:
        (tmp_path / "voices.lock.json").write_text("{nope")
        with pytest.raises(lock_module.LockError, match="not valid JSON"):
            lock_module.load(tmp_path / "voices.lock.json")
