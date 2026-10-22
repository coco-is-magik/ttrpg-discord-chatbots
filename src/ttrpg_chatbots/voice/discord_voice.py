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
        """Release what this source owns: nothing.

        discord.py calls this at the end of *every* stream, and the AudioPlayer that ended it is
        garbage collected at the same moment the next one starts (``discord/player.py`` calls
        ``cleanup`` from ``AudioPlayer.__del__``). Clearing the shared :class:`VoicePlayer` here
        therefore deleted the audio of the clip that had just been queued: the measured cause of
        "he speaks once and never again". The player outlives the source, so only the owner
        (:class:`~ttrpg_chatbots.bots.voice.FriendVoice`) decides when the queue is dropped.
        """


def play_in(
    voice_client: discord.VoiceClient,
    player: VoicePlayer,
    *,
    pad_silence: bool = False,
    after=None,
):
    """Start playback in a connected voice client and return the source.

    ``after`` is handed to discord.py and fires when the stream ends -- however it ends. The caller
    needs it to know the channel is free again; without it, "is it still playing?" has to be asked of
    discord.py, and a stale answer there means silence forever.
    """
    source = DiscordAudioSource(player, pad_silence=pad_silence)
    voice_client.play(source, after=after)
    return source
