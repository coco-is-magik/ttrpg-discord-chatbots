"""Change a voice's pitch and formants *independently*, using Praat.

The resampling shifter in `pcm.shift_pitch` moves everything together: raising the pitch that way also
raises the formants, which is what makes a raised voice sound like a chipmunk or a woman rather than a
lighter man. Formants are what the ear reads as male or female, so a voice that needs to be *higher but
still male* needs the two moved separately.

Measured on `en_US-ryan-medium`: the source reads 149 Hz, `change_voice(pitch_hz=190)` gives 191.7 Hz
with the duration untouched at 2.86 s, and `formant=1.06` alongside it lifts the timbre slightly while
staying in the male model's character.

Praat is an optional dependency. If it is missing, `available()` says so and the caller can fall back to
the crude resampler rather than the voice silently not being shifted at all.
"""

from __future__ import annotations

from ttrpg_chatbots.audio.pcm import PcmAudio

#: Praat's pitch search range for an adult voice, in Hz.
PITCH_FLOOR = 75
PITCH_CEILING = 500

#: The scale Praat's -1..1 samples map onto.
FULL_SCALE = 32768.0

#: Where a shifted clip is allowed to peak. A little under full scale, so nothing sits on the rail and
#: a loud passage has somewhere to go.
HEADROOM = 0.95


def available() -> bool:
    """Whether the formant-aware shifter can run here."""
    try:
        import parselmouth  # noqa: F401
    except ImportError:
        return False
    return True


def change_voice(
    clip: PcmAudio,
    *,
    pitch_hz: int | None = None,
    formant: float = 1.0,
) -> PcmAudio:
    """Raise or lower the pitch, and the formants, without changing the pace.

    ``pitch_hz`` is the *target median fundamental* -- an absolute number, because "a bit higher" is not
    a ratio a person can judge. ``formant`` scales the timbre: 1.0 leaves it alone, above 1.0 is lighter
    and more feminine, below 1.0 is darker.
    """
    if pitch_hz is None and formant == 1.0:
        return clip
    if not available():
        raise RuntimeError(
            "formant-aware shifting needs parselmouth; install it or use audio.pcm.shift_pitch"
        )
    if formant <= 0:
        raise ValueError(f"formant must be positive, got {formant}")

    import numpy as np
    from parselmouth import Sound
    from parselmouth.praat import call

    # **Praat works in the range -1..1, and parselmouth does not normalise for you.** Feeding it an
    # array of int16 samples leaves the values at their raw scale (+-16000), and the first version
    # multiplied Praat's output by 32768 on the way back -- so every sample hit the rail. Measured on
    # the live path: 98.6% of samples clipped, RMS 32619 out of 32768. That is a square wave, and the
    # report from the channel was "so loud it is completely unintelligible". Divide on the way in.
    samples = np.frombuffer(clip.pcm, dtype="<i2").astype(np.float64) / FULL_SCALE
    sound = Sound(samples, sampling_frequency=clip.sample_rate)
    median = float(pitch_hz) if pitch_hz is not None else 0.0
    shifted = call(
        sound,
        "Change gender",
        PITCH_FLOOR,
        PITCH_CEILING,
        float(formant),
        median,  # 0.0 means "keep the original pitch", per the Praat command
        1.0,
        1.0,
    )
    values = np.asarray(shifted.values[0], dtype=np.float64)

    # Headroom rather than clipping: if Praat's output overshoots full scale, scale the *whole* clip
    # down so the shape survives. Clamping a waveform is what turns speech into noise.
    peak = float(np.abs(values).max()) if values.size else 0.0
    if peak > HEADROOM:
        values = values * (HEADROOM / peak)

    pcm = np.clip(values, -1.0, 1.0)
    pcm = (pcm * (FULL_SCALE - 1)).astype("<i2").tobytes()
    return PcmAudio(pcm=pcm, sample_rate=int(round(shifted.sampling_frequency)), channels=1)
