from dataclasses import FrozenInstanceError

import pytest

from ttrpg_chatbots.stt.types import SAMPLE_RATE, AudioClip

ONE_SECOND_PCM = b"\x00\x00" * SAMPLE_RATE


def test_duration_and_frames_come_from_the_pcm() -> None:
    clip = AudioClip(pcm=ONE_SECOND_PCM)
    assert clip.frame_count == SAMPLE_RATE
    assert clip.duration_s == pytest.approx(1.0)


def test_rejects_empty_audio() -> None:
    with pytest.raises(ValueError, match="empty"):
        AudioClip(pcm=b"")


def test_rejects_a_partial_sample() -> None:
    with pytest.raises(ValueError, match="whole 16-bit samples"):
        AudioClip(pcm=b"\x00\x00\x00")


def test_rejects_the_wrong_sample_rate() -> None:
    with pytest.raises(ValueError, match="sample_rate"):
        AudioClip(pcm=ONE_SECOND_PCM, sample_rate=48_000)


def test_clip_is_immutable() -> None:
    clip = AudioClip(pcm=ONE_SECOND_PCM)
    with pytest.raises(FrozenInstanceError):
        clip.pcm = b"\x00\x00"
