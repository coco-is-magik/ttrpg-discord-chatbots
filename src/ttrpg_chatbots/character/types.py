"""The native character: mechanics, origin story, and everything that happens after.

A :class:`Character` is what the bot actually holds -- a mechanical :class:`Sheet`, the
:class:`Interview` that explains it, and an append-only history. It lives as JSON on
disk, so nothing downstream depends on a spreadsheet's layout again.

**The interview is sealed once.** Answers describe where a character came from; they are
origin, not state. After sealing, only history events are appended -- a change of heart
goes in the log, never back into the origin story. The seal carries a digest, so editing
the JSON by hand is detected rather than silently accepted.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, replace
from typing import Any, Mapping

from ttrpg_chatbots.character.build import Build, BuildError
from ttrpg_chatbots.sheets.interview import Interview
from ttrpg_chatbots.sheets.types import Sheet, SheetError, sheet_from_dict

SCHEMA_VERSION = 1

# What a history may contain. Anything else is a typo, not a new kind of event.
EVENT_KINDS = (
    "created",
    "assigned",
    "answer",
    "revision",
    "import",
    "sealed",
    "session",
    "experience",
    "hurt",
    "heal",
    "willpower",
    "sheet",
    "note",
)


class CharacterError(RuntimeError):
    """Raised when a character cannot be built, sealed or updated."""


class CharacterConflict(CharacterError):
    """Raised when a write is based on a revision that is no longer current.

    This is the compare-and-swap failing, not a bug: somebody else (or another device) wrote
    first. Callers reload and retry rather than overwrite.
    """


def interview_digest(interview: Interview) -> str:
    """A stable fingerprint of the answers, in order.

    The seal stores this, so a hand-edited answer file is caught on load instead of
    quietly becoming canon.
    """
    payload = [
        [question.section, question.prompt, question.answer]
        for question in interview.questions
    ]
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class Event:
    """One line in the character's history."""

    kind: str
    summary: str
    at: str = ""
    detail: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.kind not in EVENT_KINDS:
            raise ValueError(f"unknown event kind {self.kind!r}; expected one of {EVENT_KINDS}")
        if not self.summary.strip():
            raise ValueError("an event needs a summary")

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "summary": self.summary,
            "at": self.at,
            "detail": dict(self.detail),
        }

    @classmethod
    def from_dict(cls, data: Any) -> Event:
        if not isinstance(data, Mapping):
            raise CharacterError("an event must be a JSON object")
        detail = data.get("detail") or {}
        if not isinstance(detail, Mapping):
            raise CharacterError("an event's detail must be an object")
        return cls(
            kind=str(data.get("kind", "")),
            summary=str(data.get("summary", "")),
            at=str(data.get("at", "") or ""),
            detail=dict(detail),
        )


@dataclass(frozen=True)
class Character:
    """A playable character: what they can do, where they came from, what happened since."""

    sheet: Sheet
    interview: Interview | None = None
    history: tuple[Event, ...] = ()
    sealed: bool = False
    digest: str = ""
    created: str = ""
    # Present while a character is being built from scratch: which budget each group got.
    build: Build | None = None
    # Every accepted change bumps this. Writes are compare-and-swap on it, so two surfaces
    # editing one character cannot silently overwrite each other.
    revision: int = 0

    def __post_init__(self) -> None:
        if isinstance(self.revision, bool) or not isinstance(self.revision, int):
            raise CharacterError(f"revision must be a whole number, got {self.revision!r}")
        if self.revision < 0:
            raise CharacterError(f"revision must not be negative, got {self.revision}")
        if self.sealed and self.interview is None:
            raise CharacterError("a sealed character must carry its interview")
        if self.sealed and self.digest != interview_digest(self.interview):
            raise CharacterError(
                "the sealed interview does not match its digest; the answers were edited"
            )

    @property
    def id(self) -> str:
        return self.sheet.key

    @property
    def name(self) -> str:
        return self.sheet.name

    @property
    def system(self) -> str:
        return self.sheet.system

    @property
    def interview_complete(self) -> bool:
        return self.interview is not None and self.interview.complete

    @property
    def ready(self) -> bool:
        """Whether this character may be played: sealed, with a complete interview."""
        return self.sealed and self.interview_complete

    def record(
        self,
        kind: str,
        summary: str,
        *,
        at: str = "",
        detail: Mapping[str, Any] | None = None,
    ) -> Character:
        """Append one history event and return the new state."""
        event = Event(kind=kind, summary=summary, at=at, detail=dict(detail or {}))
        return replace(self, history=self.history + (event,), revision=self.revision + 1)

    def with_interview(self, interview: Interview) -> Character:
        """Attach an interview while the character is still being built."""
        if self.sealed:
            raise CharacterError(
                "the interview is sealed; answer changes belong in the history, not the origin"
            )
        return replace(self, interview=interview, revision=self.revision + 1)

    def with_answer(self, number: int, answer: str, *, at: str = "") -> Character:
        """Rewrite one answer while the character is a draft."""
        if self.interview is None:
            raise CharacterError(f"{self.name} has no interview")
        if self.sealed:
            raise CharacterError(
                f"{self.name} is sealed; run /unlock first, then amend the answer"
            )
        updated = self.interview.with_answer(number, answer)
        return replace(self, interview=updated, revision=self.revision + 1).record(
            "answer", f"amended answer {number}: {updated.at(number).prompt[:60]}", at=at
        )

    def unlock(self, *, reason: str = "", at: str = "") -> Character:
        """Reopen a sealed character for a Revision.

        The rules call this a Character Revision — offered at each level past Novice, and
        taken whenever a GM and a player agree the character needs changing. Unsealing drops
        the digest, so the next seal records a fresh one; the history keeps both.
        """
        if not self.sealed:
            return self
        reopened = replace(self, sealed=False, digest="").record(
            "revision",
            f"reopened for revision{': ' + reason if reason else ''}",
            at=at,
        )
        return replace(reopened, revision=reopened.revision + 1)

    def seal(self, *, at: str = "") -> Character:
        """Lock the answers in, once they are complete."""
        if self.interview is None:
            raise CharacterError(f"{self.name} has no interview to seal")
        if not self.interview.complete:
            missing = len(self.interview.missing)
            raise CharacterError(
                f"{self.name} still has {missing} unanswered question"
                f"{'' if missing == 1 else 's'}"
            )
        if self.sealed:
            return self
        digest = interview_digest(self.interview)
        event = Event(
            kind="sealed",
            summary=f"interview sealed with {self.interview.total} answers",
            at=at,
            detail={"digest": digest},
        )
        # One bump for one action: sealing is a single user decision, not two.
        return replace(
            self,
            sealed=True,
            digest=digest,
            history=self.history + (event,),
            revision=self.revision + 1,
        )

    def with_build(self, build: Build | None) -> Character:
        """Attach or replace the creation budgets (while still a draft)."""
        if self.sealed:
            raise CharacterError(f"{self.name} is sealed; there are no budgets left to set")
        return replace(self, build=build, revision=self.revision + 1)

    def with_sheet(
        self,
        sheet: Sheet,
        *,
        summary: str = "",
        at: str = "",
        detail: Mapping[str, Any] | None = None,
    ) -> Character:
        """Replace the mechanics and log what changed.

        ``detail`` is what makes an edit reversible: recording ``{"trait": "Stealth",
        "before": 2, "after": 3}`` lets ``/undo`` put the old value back without keeping a
        snapshot of the whole sheet in history.
        """
        if not summary:
            summary = f"sheet updated for {sheet.name}"
        event = Event(kind="sheet", summary=summary, at=at, detail=dict(detail or {}))
        return replace(
            self, sheet=sheet, history=self.history + (event,), revision=self.revision + 1
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "id": self.id,
            "name": self.name,
            "system": self.system,
            "sealed": self.sealed,
            "digest": self.digest,
            "created": self.created,
            "build": self.build.as_dict() if self.build is not None else None,
            "revision": self.revision,
            "sheet": self.sheet.as_dict(),
            "interview": self.interview.as_dict() if self.interview is not None else None,
            "history": [event.as_dict() for event in self.history],
        }

    def to_json(self) -> str:
        return json.dumps(self.as_dict(), indent=2, ensure_ascii=False) + "\n"

    @classmethod
    def from_dict(cls, data: Any) -> Character:
        if not isinstance(data, Mapping):
            raise CharacterError("a character must be a JSON object")
        version = data.get("schema_version")
        if version != SCHEMA_VERSION:
            raise CharacterError(
                f"unsupported character schema {version!r}; this build writes {SCHEMA_VERSION}"
            )
        try:
            sheet = sheet_from_dict(data.get("sheet"))
        except SheetError as error:
            raise CharacterError(str(error)) from error

        raw_interview = data.get("interview")
        interview = None
        if raw_interview is not None:
            try:
                interview = Interview.from_dict(raw_interview)
            except (SheetError, ValueError) as error:
                raise CharacterError(str(error)) from error

        raw_history = data.get("history") or []
        if not isinstance(raw_history, list):
            raise CharacterError("'history' must be a list")
        try:
            history = tuple(Event.from_dict(entry) for entry in raw_history)
        except (ValueError, BuildError) as error:
            raise CharacterError(str(error)) from error

        try:
            return cls(
                sheet=sheet,
                interview=interview,
                history=history,
                sealed=bool(data.get("sealed")),
                digest=str(data.get("digest", "") or ""),
                created=str(data.get("created", "") or ""),
                build=Build.from_dict(data["build"]) if data.get("build") else None,
                # Files written before revisions existed are revision 0, which is also the
                # revision a freshly created character has: nothing to migrate.
                revision=int(data.get("revision", 0) or 0),
            )
        except (ValueError, CharacterError) as error:
            raise CharacterError(str(error)) from error

    @classmethod
    def from_json(cls, text: str) -> Character:
        try:
            data = json.loads(text)
        except ValueError as error:
            raise CharacterError(f"invalid character JSON: {error}") from error
        return cls.from_dict(data)

