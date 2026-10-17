import pytest

pytest.importorskip("numpy")

from ttrpg_chatbots.stt.fixture import fingerprint, synthetic_speech  # noqa: E402
from ttrpg_chatbots.stt.types import SAMPLE_RATE  # noqa: E402


def test_clip_matches_the_interchange_format() -> None:
    clip = synthetic_speech(1.0)
    assert clip.sample_rate == SAMPLE_RATE
    assert clip.frame_count == SAMPLE_RATE
    assert len(clip.pcm) == SAMPLE_RATE * 2


def test_fixture_is_deterministic() -> None:
    """Same bytes on every run and every machine, or cached rankings are meaningless."""
    assert synthetic_speech(0.5).pcm == synthetic_speech(0.5).pcm


def test_seed_changes_the_signal() -> None:
    assert synthetic_speech(0.5, seed=1).pcm != synthetic_speech(0.5, seed=2).pcm


def test_signal_is_audible_but_never_clipped() -> None:
    import numpy as np

    samples = np.frombuffer(synthetic_speech(1.0).pcm, dtype="<i2")
    peak = int(np.max(np.abs(samples.astype(np.int32))))
    assert peak > 2000, "the clip must not be near-silent, or engines short-circuit"
    assert peak < 32767


def test_rejects_non_positive_duration() -> None:
    with pytest.raises(ValueError, match="positive"):
        synthetic_speech(0)


def test_fingerprint_identifies_the_clip() -> None:
    assert fingerprint(synthetic_speech(1.0)) == fingerprint(synthetic_speech(1.0))
    assert fingerprint(synthetic_speech(1.0)) != fingerprint(synthetic_speech(1.5))
