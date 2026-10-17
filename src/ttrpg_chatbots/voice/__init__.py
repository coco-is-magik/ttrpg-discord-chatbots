"""Playback into a voice call, independent of what produced the audio.

``sources`` turn clips and files into 20 ms frames, ``player`` queues them, and
``discord_voice`` is the only piece that knows Discord exists. Text-to-speech lives
in :mod:`ttrpg_chatbots.tts` and is composed with this by the caller, so a music
file, a pre-recorded line, a classifier reply or an LLM answer all take the same
path.
"""

from ttrpg_chatbots.voice.player import VoicePlayer
from ttrpg_chatbots.voice.sources import (
    ChainSource,
    FrameSource,
    PcmFrameSource,
    SilenceSource,
    load_file,
)

__all__ = [
    "ChainSource",
    "FrameSource",
    "PcmFrameSource",
    "SilenceSource",
    "VoicePlayer",
    "load_file",
]
