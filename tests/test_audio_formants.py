"""Changing a voice's pitch without changing its perceived gender.

The crude resampler in `audio.pcm` moves pitch and formants together, which is why raising a man's
voice with it produces a woman's. These tests hold the formant-aware path to the two properties that
matter: the pitch target is honoured, and the *pace* is left alone.
"""

from __future__ import annotations

import numpy as np
import pytest

from ttrpg_chatbots.audio import formants
from ttrpg_chatbots.audio.pcm import PcmAudio


def _tone(seconds: float = 1.0, rate: int = 22050, hz: float = 150.0) -> PcmAudio:
    t = np.arange(int(seconds * rate)) / rate
    # A sawtooth-ish tone: a fundamental plus harmonics, so a formant shifter has something to work on.
    wave = sum(np.sin(2 * np.pi * hz * k * t) / k for k in (1, 2, 3, 4, 5))
    pcm = (wave / np.abs(wave).max() * 20000).astype("<i2").tobytes()
    return PcmAudio(pcm=pcm, sample_rate=rate, channels=1)


def _median_f0(clip: PcmAudio) -> float:
    x = np.frombuffer(clip.pcm, dtype="<i2").astype(np.float64)
    rate = clip.sample_rate
    frame, hop = int(rate * 0.04), int(rate * 0.02)
    lo, hi = int(rate / 400), int(rate / 70)
    found: list[float] = []
    for start in range(0, max(1, x.size - frame), hop):
        seg = x[start : start + frame]
        if seg.size < frame or np.sqrt((seg**2).mean()) < 200:
            continue
        seg = seg - seg.mean()
        corr = np.correlate(seg, seg, mode="full")[frame - 1 :]
        if corr[0] <= 0:
            continue
        corr = corr / corr[0]
        window = corr[lo:hi]
        if window.size == 0:
            continue
        peak = int(np.argmax(window)) + lo
        if corr[peak] < 0.3:
            continue
        found.append(rate / peak)
    return float(np.median(found)) if found else 0.0


needs_praat = pytest.mark.skipif(
    not formants.available(), reason="praat-parselmouth is not installed"
)


class TestAvailability:
    def test_availability_is_a_plain_question(self) -> None:
        assert isinstance(formants.available(), bool)

    def test_a_missing_shifter_is_reported_not_ignored(self, monkeypatch) -> None:
        """A voice that asks for a shift and silently does not get one is the bug this prevents."""
        monkeypatch.setattr(formants, "available", lambda: False)
        with pytest.raises(RuntimeError, match="parselmouth"):
            formants.change_voice(_tone(), pitch_hz=200)


@needs_praat
class TestChangingAVoice:
    def test_nothing_asked_for_means_nothing_done(self) -> None:
        clip = _tone()
        assert formants.change_voice(clip) is clip

    def test_the_pitch_target_is_honoured(self) -> None:
        clip = _tone(hz=150.0)
        raised = formants.change_voice(clip, pitch_hz=200)
        assert _median_f0(raised) == pytest.approx(200, abs=15)

    def test_the_pace_is_left_alone(self) -> None:
        """Measured: a 2.86 s line stays 2.86 s at every target, which is why no length compensation
        is needed when this is used (the resampler needed `speed * pitch` to fake it)."""
        clip = _tone(seconds=1.5)
        before = len(clip.pcm) / 2 / clip.sample_rate
        for target in (170, 200, 240):
            after = formants.change_voice(clip, pitch_hz=target)
            assert len(after.pcm) / 2 / after.sample_rate == pytest.approx(before, abs=0.05)

    def test_a_formant_scale_alone_is_allowed(self) -> None:
        shifted = formants.change_voice(_tone(), formant=1.1)
        assert len(shifted.pcm) > 0
        assert shifted.sample_rate == 22050

    def test_output_is_clamped_not_overflowed(self) -> None:
        """Praat's floats overshoot; the first version raised OverflowError on the conversion."""
        shifted = formants.change_voice(_tone(), pitch_hz=240, formant=1.2)
        samples = np.frombuffer(shifted.pcm, dtype="<i2")
        assert samples.size > 0
        assert samples.min() >= -32768 and samples.max() <= 32767

    def test_a_nonsense_formant_is_refused(self) -> None:
        with pytest.raises(ValueError, match="formant must be positive"):
            formants.change_voice(_tone(), formant=0.0)


@needs_praat
class TestTheLevelSurvivesTheShift:
    """The bug that made him unlistenable: 98.6% of samples pinned at the rail.

    parselmouth does **not** normalise an int array -- it keeps the raw sample values, so a `+-16000`
    clip stays `+-16000` inside Praat, and the first version multiplied that by 32768 on the way back.
    The result was a square wave: peak and RMS both at 32768, reported from the channel as "so loud it
    is completely unintelligible".
    """

    def _stats(self, clip) -> tuple[float, float, float]:
        x = np.frombuffer(clip.pcm, dtype="<i2").astype(np.float64)
        peak = float(np.abs(x).max()) / 32767
        rail = float((np.abs(x) >= 32760).sum()) / x.size
        rms = float(np.sqrt((x**2).mean()))
        return peak, rail, rms

    def test_nothing_sits_on_the_rail(self) -> None:
        shifted = formants.change_voice(_tone(), pitch_hz=205, formant=1.06)
        peak, rail, _ = self._stats(shifted)
        assert peak <= 0.96, peak
        assert rail < 0.001, f"{rail:.2%} of samples are clipped"

    def test_the_level_is_in_the_same_place_as_the_input(self) -> None:
        """A shift must not amplify: it is the same voice, higher."""
        source = _tone()
        _, _, before = self._stats(source)
        _, _, after = self._stats(formants.change_voice(source, pitch_hz=205, formant=1.06))
        assert after == pytest.approx(before, rel=0.5)

    def test_a_quiet_clip_is_not_boosted_to_the_ceiling(self) -> None:
        quiet = PcmAudio(
            pcm=(np.frombuffer(_tone().pcm, dtype="<i2") // 8).astype("<i2").tobytes(),
            sample_rate=22050,
            channels=1,
        )
        peak, rail, _ = self._stats(formants.change_voice(quiet, pitch_hz=205))
        assert peak < 0.5, "headroom is for overshoot, not for making quiet clips loud"
        assert rail == 0.0
