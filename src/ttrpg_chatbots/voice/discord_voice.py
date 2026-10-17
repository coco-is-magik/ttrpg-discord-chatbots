"""Discord adapter: the only module in here that imports discord.

Everything else in ``ttrpg_chatbots.voice`` works without it, so playback logic is
testable without a gateway, a token or a network.
"""

from __future__ import annotations

import discord

from ttrpg_chatbots.audio.pcm import DISCORD_FRAME_BYTES
from ttrpg_chatbots.voice.player import VoicePlayer

SILENT_FRAME = b"\x00" * DISCORD_FRAME_BYTES


class DiscordAudioSource(discord.AudioSource):
    """Presents a :class:`VoicePlayer` as a pull-based discord.py AudioSource."""

    def __init__(self, player: VoicePlayer, *, pad_silence: bool = False) -> None:
        self._player = player
        self._pad_silence = pad_silence

    def read(self) -> bytes:
        frame = self._player.next_frame()
        if frame:
            return frame
        # b"" tells discord.py playback is over; silence keeps the bot "talking"
        # (useful when audio arrives faster than it is produced).
        return SILENT_FRAME if self._pad_silence else b""

    def is_opus(self) -> bool:
        return False

    def cleanup(self) -> None:
        self._player.clear()


def play_in(voice_client: discord.VoiceClient, player: VoicePlayer, *, pad_silence=False):
    """Start playback in a connected voice client and return the source."""
    source = DiscordAudioSource(player, pad_silence=pad_silence)
    voice_client.play(source)
    return source
