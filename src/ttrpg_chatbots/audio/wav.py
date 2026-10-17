"""WAV in, WAV out -- so pre-recorded audio and music need no extra dependency.

Only uncompressed 16-bit PCM is accepted; anything else has to be converted first
(`ffmpeg -i in.mp3 -ac 2 -ar 48000 -sample_fmt s16 out.wav`) instead of silently
producing garbage.
"""

from __future__ import annotations

import io
import wave
from pathlib import Path

from ttrpg_chatbots.audio.pcm import PcmAudio

_READY = "only uncompressed 16-bit PCM WAV is supported"


def decode_wav(data: bytes) -> PcmAudio:
    """Read WAV bytes (used for engines that write to stdout)."""
    return _read(io.BytesIO(data))


def read_wav(path: str | Path) -> PcmAudio:
    with open(path, "rb") as handle:
        return _read(handle)


def _read(stream) -> PcmAudio:
    try:
        with wave.open(stream, "rb") as handle:
            width = handle.getsampwidth()
            channels = handle.getnchannels()
            rate = handle.getframerate()
            compression = handle.getcomptype()
            pcm = handle.readframes(handle.getnframes())
    except (wave.Error, EOFError) as error:
        raise ValueError(f"{_READY}: {error}") from error
    if compression != "NONE" or width != 2:
        raise ValueError(f"{_READY}, got {width * 8}-bit {compression}")
    if not pcm:
        raise ValueError("WAV file contains no audio")
    return PcmAudio(pcm=pcm, sample_rate=rate, channels=channels)


def write_wav(clip: PcmAudio, path: str | Path) -> Path:
    target = Path(path)
    with wave.open(str(target), "wb") as handle:
        handle.setnchannels(clip.channels)
        handle.setsampwidth(2)
        handle.setframerate(clip.sample_rate)
        handle.writeframes(clip.pcm)
    return target


def encode_wav(clip: PcmAudio) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(clip.channels)
        handle.setsampwidth(2)
        handle.setframerate(clip.sample_rate)
        handle.writeframes(clip.pcm)
    return buffer.getvalue()
