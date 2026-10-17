"""PCM primitives shared by the text-to-speech and playback layers."""

from ttrpg_chatbots.audio.pcm import (
    DISCORD_BYTES_PER_SECOND,
    DISCORD_CHANNELS,
    DISCORD_FRAME_BYTES,
    DISCORD_FRAME_MS,
    DISCORD_FRAME_SAMPLES,
    DISCORD_RATE,
    PcmAudio,
    frame_count,
    frames,
    to_discord_pcm,
)
from ttrpg_chatbots.audio.wav import decode_wav, encode_wav, read_wav, write_wav

__all__ = [
    "DISCORD_BYTES_PER_SECOND",
    "DISCORD_CHANNELS",
    "DISCORD_FRAME_BYTES",
    "DISCORD_FRAME_MS",
    "DISCORD_FRAME_SAMPLES",
    "DISCORD_RATE",
    "PcmAudio",
    "decode_wav",
    "encode_wav",
    "frame_count",
    "frames",
    "read_wav",
    "to_discord_pcm",
    "write_wav",
]
