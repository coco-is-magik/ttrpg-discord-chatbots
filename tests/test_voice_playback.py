import threading
import time
from collections import Counter

import pytest

from ttrpg_chatbots.audio import DISCORD_FRAME_BYTES, write_wav
from ttrpg_chatbots.voice.player import VoicePlayer
from ttrpg_chatbots.voice.sources import (
    ChainSource,
    PcmFrameSource,
    SilenceSource,
    load_file,
)

from tts_support import FakeSource, tone

FRAME = b"\x01" * DISCORD_FRAME_BYTES
SILENT = b"\x00" * DISCORD_FRAME_BYTES


def _drain(player) -> list[bytes]:
    return list(iter(player.next_frame, b""))


class TestPcmFrameSource:
    def test_frames_are_full_size_and_the_tail_is_padded(self) -> None:
        source = PcmFrameSource(tone(0.25, sample_rate=16_000))
        produced = _drain(source)
        assert produced
        assert all(len(frame) == DISCORD_FRAME_BYTES for frame in produced)
        assert len(produced) == source.frame_count

    def test_exhausted_sources_stay_exhausted(self) -> None:
        source = PcmFrameSource(tone(0.05))
        _drain(source)
        assert source.next_frame() == b""

    def test_duration_tracks_the_audio(self) -> None:
        assert PcmFrameSource(tone(1.0)).duration_s == pytest.approx(1.0, abs=0.01)

    def test_close_stops_the_source(self) -> None:
        source = PcmFrameSource(tone(1.0))
        source.close()
        assert source.next_frame() == b""


class TestSilenceSource:
    def test_produces_the_requested_length(self) -> None:
        source = SilenceSource(0.5)
        assert source.frame_count == 25
        assert _drain(source) == [SILENT] * 25

    def test_zero_length_is_valid(self) -> None:
        assert SilenceSource(0).next_frame() == b""

    def test_negative_length_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="negative"):
            SilenceSource(-0.1)


class TestLoadFile:
    def test_a_wav_becomes_frames(self, tmp_path) -> None:
        path = write_wav(tone(0.3, sample_rate=44_100, channels=2), tmp_path / "music.wav")
        source = load_file(path)
        produced = _drain(source)
        assert len(produced) == source.frame_count
        assert all(len(frame) == DISCORD_FRAME_BYTES for frame in produced)


class TestChainSource:
    def test_plays_in_order_and_closes_children(self) -> None:
        first = FakeSource([b"a" * DISCORD_FRAME_BYTES])
        second = FakeSource([b"b" * DISCORD_FRAME_BYTES])
        chain = ChainSource(first, second)

        assert chain.next_frame() == b"a" * DISCORD_FRAME_BYTES
        assert chain.next_frame() == b"b" * DISCORD_FRAME_BYTES
        assert chain.next_frame() == b""
        assert (first.closes, second.closes) == (1, 1)

    def test_an_empty_chain_is_silent(self) -> None:
        assert ChainSource().next_frame() == b""

    def test_close_releases_pending_sources(self) -> None:
        pending = FakeSource([b"a" * DISCORD_FRAME_BYTES])
        ChainSource(pending).close()
        assert pending.closes == 1


class TestVoicePlayer:
    def test_drains_queued_sources_in_order(self) -> None:
        player = VoicePlayer()
        player.enqueue(FakeSource([b"1" * DISCORD_FRAME_BYTES]))
        player.say(FakeSource([b"2" * DISCORD_FRAME_BYTES]))

        assert player.next_frame() == b"1" * DISCORD_FRAME_BYTES
        assert player.next_frame() == b"2" * DISCORD_FRAME_BYTES
        assert player.next_frame() == b""
        assert player.is_idle()

    def test_queue_depth_counts_the_in_flight_source(self) -> None:
        player = VoicePlayer()
        player.enqueue(FakeSource([FRAME, FRAME]))
        assert player.queued == 1
        player.next_frame()
        assert player.queued == 1, "the source is still playing"
        player.next_frame()
        assert player.next_frame() == b""
        assert player.queued == 0

    def test_clear_drops_and_closes_everything(self) -> None:
        player = VoicePlayer()
        current = FakeSource([FRAME, FRAME])
        pending = FakeSource([FRAME])
        player.enqueue(current)
        player.enqueue(pending)
        player.next_frame()

        player.clear()

        assert (current.closes, pending.closes) == (1, 1)
        assert player.is_idle()
        assert player.next_frame() == b""

    def test_a_source_yielding_a_short_frame_is_rejected(self) -> None:
        player = VoicePlayer()
        player.enqueue(FakeSource([b"short"]))
        with pytest.raises(ValueError, match="exactly"):
            player.next_frame()

    def test_enqueue_after_close_is_rejected(self) -> None:
        player = VoicePlayer()
        player.close()
        with pytest.raises(RuntimeError, match="closed"):
            player.enqueue(FakeSource([]))

    def test_close_is_idempotent(self) -> None:
        player = VoicePlayer()
        player.close()
        player.close()
        assert player.is_idle()

    def test_concurrent_enqueue_and_read_loses_nothing(self) -> None:
        """The audio thread reads while the event loop writes: no frame may vanish."""
        player = VoicePlayer()
        sources = 40
        frames_each = 3
        expected = sources * frames_each
        received: list[bytes] = []
        errors: list[BaseException] = []
        finished = threading.Event()

        def reader() -> None:
            try:
                while True:
                    frame = player.next_frame()
                    if frame:
                        received.append(frame)
                    elif finished.is_set():
                        return
                    else:
                        time.sleep(0)
            except BaseException as error:  # noqa: BLE001
                errors.append(error)
                return

        thread = threading.Thread(target=reader)
        thread.start()
        for index in range(sources):
            payload = bytes([index]) * DISCORD_FRAME_BYTES
            player.enqueue(FakeSource([payload] * frames_each))
        finished.set()
        thread.join(timeout=10)

        assert not thread.is_alive()
        assert errors == []
        assert len(received) == expected
        assert Counter(frame[0] for frame in received) == {
            index: frames_each for index in range(sources)
        }
