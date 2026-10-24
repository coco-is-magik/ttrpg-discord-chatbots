"""The room, running in Discord.

The only Discord-facing part of ambient conversation. `ambient/` decides *what* and *when* with no
knowledge of Discord; this posts it, and feeds everything the friends hear back into the room so the
next turn has a conversation to be part of.

Off unless `TTRPG_CHATTER=1`. An unprompted bot is a surprise, and a surprise should be opt-in.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
from datetime import datetime
from pathlib import Path

import discord

from ttrpg_chatbots.ambient.director import Director
from ttrpg_chatbots.ambient.room import Room

LOGGER = logging.getLogger(__name__)

#: How often the loop looks at the clock. Much finer than the cadence, so a message is never late by
#: more than this -- and cheap, because a tick is arithmetic.
TICK_SECONDS = 20.0

#: Where the transcript goes. One jsonl line per thing said, plus a header describing the run, because a
#: dataset without its settings is a pile of sentences rather than a baseline.
LOG_ENV = "TTRPG_CHATTER_LOG"
DEFAULT_LOG = "data/chatter.jsonl"


def local_now() -> datetime:
    """Now, in the machine's own time zone.

    **The room's day is local.** Measured live: at 21:24 EDT the room put itself to bed and went silent for
    the evening, because the schedule was being evaluated in UTC -- where it was 01:24, past the hard
    bedtime. A person's day is the one on the wall, which is what `docs/SCHEDULE.md` already says about
    the friends' own schedules; this is the same rule applied to the room.
    """
    return datetime.now().astimezone()


#: Set to 0 to switch bedtime off for a run. One definition, because the room and the friends both need
#: it: the room's quiet hours are not the only way a friend goes quiet, and they drifted apart once.
SLEEP_ENV = "TTRPG_CHATTER_SLEEP"


def sleep_enabled() -> bool:
    """Whether the friends keep a night. ``0``/``off``/``no``/``false`` switches it off for the run."""
    return os.environ.get(SLEEP_ENV, "1").strip().lower() not in ("0", "off", "no", "false")


def enabled() -> bool:
    """Whether the friends talk to each other at all."""
    return os.environ.get("TTRPG_CHATTER", "").strip().lower() in ("1", "on", "yes", "true")


class Chatter:
    """Runs the director on a timer and posts what it produces.

    Every send goes through one place, so the two things that could annoy Discord -- too many requests,
    and a retry loop -- are both visible in one method. The budget upstream is the real ceiling; this is
    the last line of defence.
    """

    def __init__(
        self,
        *,
        director: Director,
        room: Room,
        channel_id: int,
        clients: dict[str, discord.Client],
        tick_seconds: float = TICK_SECONDS,
    ) -> None:
        self.director = director
        self.room = room
        self.channel_id = channel_id
        self.clients = clients
        self.tick_seconds = tick_seconds
        self.posted = 0
        self.failures = 0
        self._task: asyncio.Task | None = None
        self._announced = None
        self._last_posted = None
        self._log_path = Path(os.environ.get(LOG_ENV, DEFAULT_LOG))
        self._opened = False
        self.room.on_say = self._write

    def start(self) -> None:
        self._mark_start()
        self._task = asyncio.create_task(self._run(), name="chatter")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _run(self) -> None:
        while True:
            try:
                await self._step()
            except asyncio.CancelledError:
                raise
            except Exception as error:  # noqa: BLE001 - the room must not take the bots down
                self.failures += 1
                LOGGER.warning("chatter tick failed: %s", error)
            await asyncio.sleep(self.tick_seconds)

    def _mark_start(self) -> None:
        """Note this start in an existing transcript.

        The header is written once, when the file is fresh. If the process is restarted mid-run the file
        keeps growing, so without a marker a restart and a long silence look identical in the data -- and
        telling those apart is the difference between a bug and a quiet night.
        """
        if not self._log_path.exists() or self._log_path.stat().st_size == 0:
            return
        try:
            with self._log_path.open("a", encoding="utf-8") as handle:
                handle.write(
                    json.dumps(
                        {
                            "kind": "start",
                            "at": datetime.now().astimezone().isoformat(timespec="seconds"),
                        }
                    )
                    + "\n"
                )
        except OSError as error:
            LOGGER.warning("could not mark the transcript: %s", error)

    def _header(self) -> dict:
        """Everything needed to read the dataset later: the settings, the people, and the commit."""
        try:
            commit = subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            ).stdout.strip()
        except Exception:  # noqa: BLE001 - a missing git must not stop the room
            commit = ""
        return {
            "kind": "header",
            "at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "commit": commit,
            "friends": sorted(self.director.ladders),
            "cadence": {
                "mean_seconds": self.director.cadence.mean_seconds,
                "min_seconds": self.director.cadence.minimum,
                "max_seconds": self.director.cadence.maximum,
                "shape": __import__("ttrpg_chatbots.ambient.cadence", fromlist=["SHAPE"]).SHAPE,
            },
            "budget": {
                "per_hour": self.director.budget.per_hour,
                "per_day": self.director.budget.per_day,
            },
            "sleep_enabled": self.director.quiet.sleep_enabled,
            "channel_id": self.channel_id,
        }

    def _write(self, entry) -> None:
        """Append one line of the conversation, opening the file and writing the header first."""
        try:
            self._log_path.parent.mkdir(parents=True, exist_ok=True)
            fresh = not self._log_path.exists() or self._log_path.stat().st_size == 0
            with self._log_path.open("a", encoding="utf-8") as handle:
                if fresh and not self._opened:
                    handle.write(json.dumps(self._header(), ensure_ascii=False))
                    handle.write("\n")
                self._opened = True
                record = {
                    "at": entry.at.isoformat(timespec="seconds"),
                    "speaker": entry.speaker,
                    "kind": entry.kind,
                    "text": entry.text,
                }
                if getattr(entry, "trail", ""):
                    record["trail"] = entry.trail
                if getattr(entry, "turn", ""):
                    record["turn"] = entry.turn
                handle.write(json.dumps(record, ensure_ascii=False))
                handle.write("\n")
        except OSError as error:
            LOGGER.warning("could not write the transcript: %s", error)

    def _watch(self, now) -> None:
        """Say what is scheduled, and complain if the room has gone quiet for too long.

        Measured: the first live run said two things and then nothing for nineteen minutes, and there was
        no way to tell a legitimate long draw from a dead loop. Silence now explains itself -- one line
        when the schedule changes, and a warning if the gap exceeds twice the longest draw.
        """
        from datetime import timedelta

        scheduled = self.director.next_at
        if scheduled is not None and scheduled != self._announced:
            self._announced = scheduled
            LOGGER.info("next message at %s (%s)", scheduled.strftime("%H:%M"), self.director.reason)
        if self._last_posted is not None and now - self._last_posted > 2 * timedelta(
            seconds=self.director.cadence.maximum
        ):
            LOGGER.warning(
                "the room has been quiet for %.0f minutes: %s",
                (now - self._last_posted).total_seconds() / 60,
                self.director.reason,
            )
            self._last_posted = now  # once per stall, not every tick

    async def _step(self) -> None:
        now = local_now()
        line = self.director.tick(now)
        self._watch(now)
        if line is None:
            return
        client = self.clients.get(line.speaker)
        if client is None:
            LOGGER.warning("chatter picked %s, which has no client", line.speaker)
            return
        channel = client.get_channel(self.channel_id)
        if channel is None:
            LOGGER.warning(
                "chatter could not find channel %s for %s", self.channel_id, line.speaker
            )
            return
        # One turn, one or more messages. The parts were decided by the ladder and packaged by the
        # director, so this only has to send them the way a person would: typing for as long as it takes,
        # then the pause between thoughts (`docs/TEXTURE.md` section 2).
        arriving = line.arriving()
        sent = 0
        for index, message in enumerate(arriving):
            wait = line.waits[index] if index < len(line.waits) else 0.0
            if wait:
                try:
                    async with channel.typing():
                        await asyncio.sleep(wait)
                except discord.HTTPException:
                    await asyncio.sleep(wait)
            try:
                await channel.send(message)
            except discord.HTTPException as error:
                self.failures += 1
                LOGGER.warning("chatter could not post as %s: %s", line.speaker, error)
                if sent:
                    self.posted += 1
                    self._last_posted = now
                return
            sent += 1
        self.posted += 1
        self._last_posted = now
        LOGGER.info(
            "%s said it unprompted (%s) in %d message(s): %s",
            line.speaker,
            line.kind,
            len(arriving),
            " | ".join(arriving),
        )
