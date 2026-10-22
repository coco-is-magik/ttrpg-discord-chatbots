"""The plan, as data.

Forty-odd single-purpose modules is a lot to keep in your head, and a folder of empty stub files
rots within a week: nobody knows which are real, so everybody edits the two that are. So the plan
lives here instead, with a status per module, and a test that holds it to the tree:

* **built** -- must be importable, with its one export present;
* **planned** -- must *not* be importable. A stub is a claim that a thing exists.

Adding a module means adding a row. That is the whole ceremony, and it is what makes "one module,
one question" checkable rather than aspirational.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Status = Literal["built", "planned"]
BANDS = ("perceive", "remember", "decide", "render", "govern")


class ManifestError(RuntimeError):
    """Raised when the manifest and the tree disagree."""


@dataclass(frozen=True)
class ModuleSpec:
    """One module: where it lives, the single question it answers, and whether it exists yet."""

    band: str
    module: str  # dotted, importable
    question: str
    status: Status = "planned"

    def __post_init__(self) -> None:
        if self.band not in BANDS:
            raise ManifestError(f"{self.module}: band must be one of {list(BANDS)}")
        if self.status not in ("built", "planned"):
            raise ManifestError(f"{self.module}: status must be built or planned")
        if not self.question.strip():
            raise ManifestError(f"{self.module}: every module answers a question; say which")


def _m(band: str, module: str, question: str, status: Status = "planned") -> ModuleSpec:
    return ModuleSpec(band=band, module=f"ttrpg_chatbots.{module}", question=question, status=status)


MODULES: tuple[ModuleSpec, ...] = (
    # --- perceive: describe the situation, decide nothing -------------------------------------
    _m("perceive", "perceive.clock", "what time is it for him?", "built"),
    _m("perceive", "perceive.inbound", "what arrived, in a sane shape?", "built"),
    _m("perceive", "reply.text", "what do the words actually say?", "built"),
    _m("perceive", "perceive.modality", "is this text, voice, an image, a system notice?", "built"),
    _m("perceive", "perceive.attachments", "is there a picture, and can he see it?", "built"),
    _m("perceive", "perceive.addressee", "was he named, replied to, or neither?", "built"),
    _m("perceive", "perceive.gap", "how long since this person spoke?", "built"),
    _m("perceive", "perceive.events", "what is happening that he would care about?", "built"),
    _m("perceive", "perceive.situation", "what kind of conversation is this?", "built"),
    _m("perceive", "perceive.world", "is a scene open, whose turn, in character?", "built"),
    _m("perceive", "perceive.thread", "what is this thread about?", "built"),
    _m("perceive", "reply.entities", "which subjects did they name?", "built"),
    _m("perceive", "perceive.tone", "how are they saying it?", "built"),
    _m("perceive", "perceive.sentiment", "good or bad, and about what?", "built"),
    _m("perceive", "life.calendar", "what does the year say about today?", "built"),
    _m("perceive", "life.schedule", "what is he doing right now?", "built"),
    # --- remember: hold state, and move it between short and long term ------------------------
    _m("remember", "memory.short", "the last few turns, verbatim", "built"),
    _m("remember", "memory.encode", "does this turn contain a fact worth keeping?", "built"),
    _m("remember", "memory.promote", "which candidates graduate to long-term?", "built"),
    _m("remember", "memory.long", "what do we durably know?", "built"),
    _m("remember", "memory.retrieve", "what is relevant to right now?", "built"),
    _m("remember", "memory.decay", "what should be forgotten?", "built"),
    _m("remember", "memory.open", "what is still unresolved?", "built"),
    _m("remember", "memory.relationship", "how well does he know this person?", "built"),
    _m("remember", "memory.store", "the only disk adapter", "built"),
    _m("remember", "bots.memory", "one friend's durable memory", "built"),
    _m("remember", "reply.context", "what was said just before this?", "built"),
    _m("remember", "reply.transitions", "which act plausibly follows which?", "built"),
    # --- decide: one rung of the ladder each ---------------------------------------------------
    _m("decide", "decide.floor", "should he speak at all?", "built"),
    _m("decide", "decide.phase", "where in the arc are we?", "built"),
    _m("decide", "decide.depth", "how many times has this thread been leaned into?", "built"),
    _m("decide", "decide.job", "which job owns this turn?", "built"),
    _m("decide", "decide.who", "does the friend speak, or the character?", "built"),
    _m("decide", "decide.form", "what shape should the line take?", "built"),
    _m("decide", "decide.family", "which kind of phrasing?", "built"),
    _m("decide", "decide.variant", "which specific line?", "built"),
    _m("decide", "decide.shelf", "which phrasebook answers this job?", "built"),
    _m("decide", "decide.values", "what values does this line get?", "built"),
    _m("decide", "decide.length", "how many words?", "built"),
    _m("decide", "decide.reciprocate", "does he hand the turn back?", "built"),
    _m("decide", "decide.persona_fit", "does this candidate sound like him?", "built"),
    _m("decide", "reply.intents", "is this a social move, and which?", "built"),
    _m("decide", "reply.style", "how does he type?", "built"),
    # --- render: words appear here, and only here ----------------------------------------------
    _m("render", "render.fill", "template plus values equals text", "built"),
    _m("render", "render.trim", "enforce the budget, or refuse", "built"),
    _m("render", "render.typing", "apply the typing style", "built"),
    _m("render", "render.audition", "accept this candidate, or ask for the next", "built"),
    _m("render", "render.line", "assemble the line and its trail", "built"),
    # --- govern: wiring and measurement --------------------------------------------------------
    _m("govern", "govern.loop", "the only place that knows the order", "built"),
    _m("govern", "govern.repeat", "what has he said recently?", "built"),
    _m("govern", "govern.harness", "do the phase numbers hold over a matrix?", "built"),
    _m("govern", "govern.trace", "record every decision, for logs and --explain", "built"),
    _m("govern", "conv.types", "the shared contracts", "built"),
)


def built() -> tuple[ModuleSpec, ...]:
    return tuple(module for module in MODULES if module.status == "built")


def planned() -> tuple[ModuleSpec, ...]:
    return tuple(module for module in MODULES if module.status == "planned")


def by_band() -> dict[str, tuple[ModuleSpec, ...]]:
    groups: dict[str, list[ModuleSpec]] = {band: [] for band in BANDS}
    for module in MODULES:
        groups[module.band].append(module)
    return {band: tuple(items) for band, items in groups.items()}


def check() -> tuple[str, ...]:
    """Compare the plan with the tree. Returns problems; empty means they agree."""
    import importlib

    problems: list[str] = []
    seen: set[str] = set()
    for module in MODULES:
        if module.module in seen:
            problems.append(f"{module.module}: listed twice")
        seen.add(module.module)
        try:
            importlib.import_module(module.module)
        except ModuleNotFoundError:
            if module.status == "built":
                problems.append(f"{module.module}: marked built but cannot be imported")
        else:
            if module.status == "planned":
                problems.append(
                    f"{module.module}: marked planned but it exists -- update the manifest and add "
                    "its test"
                )
    return tuple(problems)


def summary() -> str:
    counts = {band: len(items) for band, items in by_band().items()}
    total = len(MODULES)
    done = len(built())
    parts = ", ".join(f"{band} {count}" for band, count in counts.items())
    return f"{done}/{total} built ({parts})"
