import pytest

from ttrpg_chatbots.audio import (
    DISCORD_BYTES_PER_SECOND,
    DISCORD_FRAME_BYTES,
    DISCORD_FRAME_SAMPLES,
    DISCORD_RATE,
    PcmAudio,
    decode_wav,
    encode_wav,
    frame_count,
    frames,
    read_wav,
    to_discord_pcm,
    write_wav,
)

from tts_support import tone


def test_discord_frame_contract() -> None:
    assert DISCORD_FRAME_SAMPLES == 960
    assert DISCORD_FRAME_BYTES == 3840
    assert DISCORD_BYTES_PER_SECOND == 192_000


def test_duration_and_frames_come_from_the_pcm() -> None:
    clip = tone(1.0, sample_rate=16_000)
    assert clip.sample_rate == 16_000
    assert clip.channels == 1
    assert clip.frame_count == 16_000
    assert clip.duration_s == pytest.approx(1.0)


def test_peak_reports_amplitude() -> None:
    assert tone(0.1, amplitude=1234).peak == pytest.approx(1234, abs=2)


@pytest.mark.parametrize(
    "kwargs,message",
    [
        ({"pcm": b"", "sample_rate": 16_000}, "empty"),
        ({"pcm": b"\x00", "sample_rate": 16_000}, "whole 16-bit"),
        ({"pcm": b"\x00\x00", "sample_rate": 0}, "sample_rate"),
        ({"pcm": b"\x00\x00\x00\x00", "sample_rate": 16_000, "channels": 3}, "mono or stereo"),
        ({"pcm": b"\x00\x00", "sample_rate": 16_000, "channels": 2}, "whole number of frames"),
    ],
)
def test_invalid_clips_are_rejected(kwargs, message) -> None:
    with pytest.raises(ValueError, match=message):
        PcmAudio(**kwargs)


def test_clips_concatenate() -> None:
    left, right = tone(0.2), tone(0.3)
    joined = left + right
    assert joined.frame_count == left.frame_count + right.frame_count
    assert joined.duration_s == pytest.approx(0.5, abs=0.001)


def test_concatenating_different_formats_is_rejected() -> None:
    with pytest.raises(ValueError, match="different sample_rate"):
        _ = tone(0.1, sample_rate=22_050) + tone(0.1, sample_rate=16_000)


def test_mono_is_duplicated_to_stereo_at_48k() -> None:
    clip = tone(1.0, sample_rate=22_050)
    data = to_discord_pcm(clip)
    assert len(data) == pytest.approx(DISCORD_BYTES_PER_SECOND, rel=0.01)
    assert len(data) % 4 == 0
    left = data[0::4]
    right = data[2::4]
    assert left == right, "both channels must carry the same mono signal"


def test_stereo_48k_is_passed_through() -> None:
    clip = tone(0.5, sample_rate=DISCORD_RATE, channels=2)
    assert to_discord_pcm(clip) == clip.pcm


def test_resampling_keeps_the_duration() -> None:
    clip = tone(2.0, sample_rate=16_000)
    data = to_discord_pcm(clip)
    assert len(data) / DISCORD_BYTES_PER_SECOND == pytest.approx(2.0, abs=0.01)


def test_frames_are_exactly_twenty_milliseconds_and_the_last_is_padded() -> None:
    data = to_discord_pcm(tone(0.25, sample_rate=16_000))
    produced = list(frames(data))
    assert produced
    assert all(len(frame) == DISCORD_FRAME_BYTES for frame in produced)
    assert len(produced) == frame_count(data)


def test_empty_pcm_produces_no_frames() -> None:
    assert list(frames(b"")) == []


def test_frame_bytes_must_be_positive() -> None:
    with pytest.raises(ValueError, match="frame_bytes"):
        list(frames(b"\x00\x00", frame_bytes=0))


def test_wav_round_trip(tmp_path) -> None:
    clip = tone(0.3, sample_rate=22_050)
    path = write_wav(clip, tmp_path / "clip.wav")
    assert read_wav(path) == clip


def test_wav_decodes_from_bytes() -> None:
    clip = tone(0.2)
    assert decode_wav(encode_wav(clip)) == clip


def test_wav_rejects_8_bit_audio(tmp_path) -> None:
    import wave

    path = tmp_path / "eight.wav"
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(1)
        handle.setframerate(8000)
        handle.writeframes(b"\x80" * 100)
    with pytest.raises(ValueError, match="16-bit PCM"):
        read_wav(path)


def test_wav_rejects_garbage(tmp_path) -> None:
    path = tmp_path / "nope.wav"
    path.write_bytes(b"definitely not a riff file")
    with pytest.raises(ValueError, match="16-bit PCM"):
        read_wav(path)


def test_wav_rejects_a_missing_file(tmp_path) -> None:
    with pytest.raises(OSError):
        read_wav(tmp_path / "absent.wav")
