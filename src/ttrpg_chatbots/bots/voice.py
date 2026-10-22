"""A friend's presence in a voice channel.

The friend bots had no audio path at all: only the helper could join a call, and only through the old
conversation engine. This gives a friend the three moves that matter -- join, speak, leave -- using the
same casting rules the helper uses, so a friend sounds like *himself* rather than like the default
voice.

Deliberately small. It is the seed of GROUP.md slice 6 (one voice per seat, queues, barge-in), and it
exists now because a voice nobody has heard is a guess: the casting table has been pinned to
`en_US-joe-medium` since the persona was written, and until this module there was no way to listen to
its output.
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from pathlib import Path

import discord

from ttrpg_chatbots.tts.casting import VoiceCast, load_voice_directory
from ttrpg_chatbots.voice.discord_voice import play_in
from ttrpg_chatbots.voice.player import VoicePlayer
from ttrpg_chatbots.voice.sources import PcmFrameSource


LOGGER = logging.getLogger(__name__)

DATA_ENV = "TTRPG_FRIENDS_DATA"
DEFAULT_DATA = Path("examples/friends_world")


class VoiceUnavailable(RuntimeError):
    """Raised when a friend cannot do what was asked of it in voice."""


@dataclass(frozen=True)
class Speaker:
    """The minimum a character needs to be cast a voice: an id, a name, and its tags."""

    id: str
    name: str
    tags: frozenset[str] = frozenset()


class FriendVoice:
    """One friend's voice connection: join a channel, say something, leave."""

    def __init__(
        self,
        *,
        friend: str,
        cast: VoiceCast | None = None,
        player: VoicePlayer | None = None,
    ) -> None:
        self.friend = friend
        self._cast = cast
        self._player = player or VoicePlayer()
        self._client: discord.VoiceClient | None = None
        # Our own view of whether a stream is running. See `say` for why it is not read back.
        self._speaking = False

    @property
    def connected(self) -> bool:
        return self._client is not None and self._client.is_connected()

    @property
    def channel_name(self) -> str:
        channel = getattr(self._client, "channel", None)
        return str(getattr(channel, "name", "") or "")

    async def join(self, channel) -> str:
        """Join a voice channel, or move to it, self-deafened.

        Self-deafened because he is not listening to voice yet -- claiming otherwise would be a lie,
        and an undeafened bot that hears nothing is a mystery to debug later.
        """
        if channel is None:
            raise VoiceUnavailable("no voice channel to join")
        if self.connected:
            if getattr(self._client.channel, "id", None) == getattr(channel, "id", None):
                return f"already in {self.channel_name}"
            await self._client.move_to(channel)
            return f"moved to {self.channel_name}"
        try:
            self._client = await channel.connect(self_deaf=True)
        except (discord.ClientException, discord.Forbidden, discord.HTTPException) as error:
            raise VoiceUnavailable(
                f"could not join {getattr(channel, 'name', '?')}: {error}. "
                "Check Connect and Speak for this bot in that channel"
            ) from error
        return f"joined {self.channel_name}"

    async def leave(self) -> str:
        if not self.connected:
            self._client = None
            return "was not in a voice channel"
        name = self.channel_name
        await self._client.disconnect()
        self._client = None
        self._speaking = False
        return f"left {name}"

    async def say(self, text: str) -> str:
        """Synthesise with his own casting and play it.

        Playback state is tracked here rather than read back from discord.py. The first version asked
        `voice_client.is_playing()` and skipped starting playback when it said yes -- which produced
        "he speaks once and never again" the moment that answer was stale. Two rules instead: while a
        clip is playing, a new one is *appended* to the same stream; when nothing is playing, playback
        is started, and if discord.py disagrees it is stopped and restarted rather than trusted.
        """
        if not self.connected:
            raise VoiceUnavailable("not in a voice channel; join one first")
        clip = await asyncio.to_thread(self._synthesize, text)
        self._player.say(PcmFrameSource(clip))
        started = self._start_playback()
        seconds = len(clip.pcm) // 2 / clip.sample_rate
        LOGGER.info(
            "%s: %s %.1fs of audio (%s, %s)",
            self.friend,
            "playing" if started else "queued",
            seconds,
            self._profile_summary(),
            self.channel_name or "no channel",
        )
        return f"{'spoke' if started else 'queued'} {seconds:.1f}s at {clip.sample_rate} Hz"

    def _start_playback(self) -> bool:
        """Start the stream if it is idle. Returns whether this call started it."""
        if self._speaking:
            return False
        if self._client is None:
            raise VoiceUnavailable("not in a voice channel; join one first")
        try:
            play_in(self._client, self._player, after=self._finished)
        except discord.ClientException:
            # discord.py thinks something is still playing. It is wrong, or it is a stream we lost
            # track of; either way stop it and take the channel back.
            LOGGER.info("%s: taking the voice stream back from a stale player", self.friend)
            self._client.stop()
            play_in(self._client, self._player, after=self._finished)
        self._speaking = True
        return True

    def _finished(self, error: Exception | None = None) -> None:
        """Called by discord.py when the stream ends, however it ends."""
        self._speaking = False
        if error is not None:
            LOGGER.warning("%s: playback ended with %s", self.friend, error)

    def _profile_summary(self) -> str:
        try:
            profile = self._cast_or_default().profile_for(_speaker(self.friend))
        except Exception:  # noqa: BLE001 - a summary must never break playback
            return "voice ?"
        return f"{profile.engine or 'default'}/{profile.voice or 'default'}"

    def _synthesize(self, text: str):
        return self._cast_or_default().synthesize(text, _speaker(self.friend))

    def _cast_or_default(self) -> VoiceCast:
        """His own casting, loaded from the world's `voices.jsonl`.

        Not a bare `VoiceCast()`: with no directory that resolves to the built-in default voice, so
        "his voice" would be some anonymous narrator. The rule file is where the persona pins
        `en_US-joe-medium` at a chosen length scale, and it has to be read for any of that to be true.
        """
        if self._cast is None:
            self._cast = VoiceCast(load_voice_directory(data_directory()))
        return self._cast

    def close(self) -> None:
        self._player.close()


def data_directory() -> Path:
    """Where the friends' data lives: the persona, the casting rules, the phrasebooks."""
    inside = os.environ.get(DATA_ENV, "").strip()
    return Path(inside) if inside else DEFAULT_DATA


def _speaker(friend: str) -> "Speaker":
    return Speaker(id=friend, name=friend)
