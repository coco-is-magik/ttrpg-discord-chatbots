"""Turning a pre-existing dialogue corpus into our act table.

Which corpora are usable, and on what terms, is argued in ``docs/CLASSIFIER.md``. This module
is the mechanical half: read a file, map their labels onto ours, count what followed what, and
write a :class:`~ttrpg_chatbots.reply.transitions.TransitionModel`.

Importing is an offline step. Nothing here runs while a friend is replying, no corpus is
vendored, and no corpus *text* leaves this module -- only integer counts do. That distinction
is deliberate: the counts are a statistic about language, not a copy of anybody's dialogue, and
it means a table derived from a non-commercial corpus can be regenerated on a laptop instead of
being committed.

Coverage is reported, never assumed. A corpus whose labels do not map cleanly produces a table
from the minority of lines that did, and says so -- silently importing 4% of Switchboard would
be worse than not importing it at all.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ttrpg_chatbots.reply import intents as social
from ttrpg_chatbots.reply.transitions import TransitionModel
from ttrpg_chatbots.reply.types import ReplyError


class CorpusError(ReplyError):
    """Raised when a corpus cannot be read or does not look like the format asked for."""


# Switchboard's DAMSL tags, reduced to the moves this project actually has. Only codes whose
# meaning is unambiguous are listed: everything else is counted as unmapped and reported, so a
# gap shows up in the coverage line instead of quietly becoming a wrong edge in the table.
#
# Counts beside each code are from the Convokit Switchboard release (122,646 utterances), which
# is what the coverage line reports against. They are here so a future reader can see which
# decisions carried weight: `sd` and `b` alone are half the corpus.
SWDA_MAP: Mapping[str, str] = {
    "fp": social.SOCIAL_GREETING,  # conventional opening                       (n small)
    "op": social.SOCIAL_GREETING,  # opening, older annotation style             (n small)
    "fc": social.SOCIAL_GOODBYE,  # conventional closing                        (2104)
    "cl": social.SOCIAL_GOODBYE,  # closing, older annotation style             (n small)
    "ft": social.SOCIAL_THANKS,  # thanks                                       (n small)
    "ba": social.SOCIAL_THANKS,  # appreciation: "yeah, thanks"                (4501)
    "fa": social.SOCIAL_APOLOGY,  # apology                                     (n small)
    "aa": social.SOCIAL_AGREEMENT,  # agree / accept                            (10059)
    "+": social.SOCIAL_AGREEMENT,  # agree / accept, the tag is literally "+"   (17683)
    "b": social.SOCIAL_AGREEMENT,  # backchannel acknowledgement               (36043)
    "bk": social.SOCIAL_AGREEMENT,  # backchannel acknowledgement              (1253)
    "br": social.SOCIAL_AGREEMENT,  # backchannel response                      (n small)
    # A statement about nothing in particular is the closest thing to smalltalk in a
    # telephone corpus; the two differ by topic, not by shape.
    "sd": social.SOCIAL_SMALLTALK,  # statement, non-opinion                    (69792)
    "sv": social.SOCIAL_SMALLTALK,  # statement, opinion                        (25427)
}

# Composite tags ("qy^d", "sd+sv", "sd(^q)") carry several parts. Splitting on these separators
# and taking the first part that maps is what SwDA's own scoring tools do; the parentheses in
# "sd(^q)" are stripped before lookup.
_SEPARATORS = ("^", "+", "-", "/")
_TRIM = "()[]{},;:"


@dataclass
class Import:
    """What an import produced, including how much of the corpus it understood."""

    source: str
    counts: dict[str, dict[str, int]]
    utterances: int = 0
    mapped: int = 0
    pairs: int = 0
    unmapped: Counter[str] = field(default_factory=Counter)

    @property
    def coverage(self) -> float:
        """Fraction of utterances that carried a label we understand."""
        return self.mapped / self.utterances if self.utterances else 0.0

    def model(self, *, min_coverage: float = 0.0) -> TransitionModel:
        """Build the table, refusing a corpus we understood too little of."""
        if not self.counts:
            raise CorpusError(
                f"{self.source}: no usable transitions; {self.coverage:.0%} of "
                f"{self.utterances} utterances mapped"
            )
        if self.coverage < min_coverage:
            raise CorpusError(
                f"{self.source}: coverage {self.coverage:.0%} is below the required "
                f"{min_coverage:.0%}; the label mapping is probably wrong"
            )
        return TransitionModel(self.counts, source=self.source)

    def report(self) -> str:
        """One line an operator can paste into a commit message."""
        top = ", ".join(
            f"{label}={count}" for label, count in self.unmapped.most_common(5)
        )
        detail = f"; unmapped: {top}" if top else ""
        return (
            f"{self.source}: {self.utterances} utterances, {self.mapped} mapped "
            f"({self.coverage:.0%}), {self.pairs} transitions, "
            f"{len(self.counts)} rows{detail}"
        )


def _first_mapped(raw: str, mapping: Mapping[str, str]) -> str | None:
    """Map one raw tag, trying each part of a composite left to right."""
    candidate = raw.strip().lower()
    if not candidate:
        return None
    if candidate in mapping:
        return mapping[candidate]
    for separator in _SEPARATORS:
        if separator in candidate:
            for part in candidate.split(separator):
                if part.strip().strip(_TRIM) in mapping:
                    return mapping[part.strip().strip(_TRIM)]
    return None


def _pairs(sequence: Sequence[str]) -> Iterable[tuple[str, str]]:
    """Adjacent pairs in an already-labelled sequence.

    Unlabelled turns are dropped by the caller first. A corpus we only half understand still
    says what followed what, and discarding the neighbours of every line we could not label
    would leave Switchboard with almost no pairs at all. ``Import.coverage`` reports the cost,
    so a bridged estimate is never mistaken for a measured one.
    """
    return zip(sequence, sequence[1:], strict=False)


def _read_records(path: Path) -> list[dict[str, Any]]:
    """Read a JSONL file into records, naming the line that breaks."""
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as error:
        raise CorpusError(f"cannot read {path}: {error}") from error
    records: list[dict[str, Any]] = []
    for number, line in enumerate(raw.splitlines(), start=1):
        text = line.strip()
        if not text or text.startswith("#"):
            continue
        try:
            record = json.loads(text)
        except json.JSONDecodeError as error:
            raise CorpusError(f"{path}:{number}: not valid JSON: {error}") from error
        if not isinstance(record, dict):
            raise CorpusError(f"{path}:{number}: expected an object")
        records.append(record)
    if not records:
        raise CorpusError(f"{path}: no records")
    return records


def _raw_tags(record: Mapping[str, Any]) -> tuple[str, ...]:
    """Every label attached to one utterance, across the shapes Convokit uses."""
    meta = record.get("meta")
    if not isinstance(meta, Mapping):
        return ()
    raw: list[str] = []
    for key in ("tags", "full_tags"):
        value = meta.get(key)
        if isinstance(value, list):
            raw.extend(item for item in value if isinstance(item, str))
    for key in ("tag", "damsl"):
        value = meta.get(key)
        if not isinstance(value, list):
            continue
        for item in value:
            if isinstance(item, (list, tuple)) and len(item) >= 2 and isinstance(item[1], str):
                raw.append(item[1])
    return tuple(raw)


def _position(record: Mapping[str, Any], fallback: int) -> int:
    """Utterance order within a conversation, from the trailing number of the id."""
    identifier = record.get("id")
    if isinstance(identifier, str) and "-" in identifier:
        tail = identifier.rsplit("-", 1)[-1]
        if tail.isdigit():
            return int(tail)
    index = record.get("index")
    if isinstance(index, int) and not isinstance(index, bool) and index >= 0:
        return index
    return fallback


def _assemble(
    source: str,
    grouped: Mapping[str, list[tuple[int, tuple[str, ...]]]],
    *,
    utterances: int,
    mapped: int,
    unmapped: Counter[str],
) -> Import:
    """Count consecutive act pairs within each conversation, never across two of them."""
    counts: dict[str, dict[str, int]] = {}
    pairs = 0
    for items in grouped.values():
        ordered = [acts[0] for _, acts in sorted(items) if acts]
        for previous, act in _pairs(ordered):
            row = counts.setdefault(previous, {})
            row[act] = row.get(act, 0) + 1
            pairs += 1
    return Import(
        source=source,
        counts=counts,
        utterances=utterances,
        mapped=mapped,
        pairs=pairs,
        unmapped=unmapped,
    )


def from_switchboard(
    path: Path | str, *, mapping: Mapping[str, str] | None = None
) -> Import:
    """Count transitions in a Convokit-format Switchboard ``utterances.jsonl``.

    ``mapping`` overrides :data:`SWDA_MAP`; a code missing from it is counted as unmapped
    rather than guessed at. Only the first mapped act of an utterance is used for the pair,
    because a composite tag like ``sd+sv`` describes one turn, not two.
    """
    active = mapping if mapping is not None else SWDA_MAP
    grouped: dict[str, list[tuple[int, tuple[str, ...]]]] = {}
    unmapped: Counter[str] = Counter()
    utterances = mapped = 0
    for fallback, record in enumerate(_read_records(Path(path))):
        conversation = record.get("conversation_id")
        if not isinstance(conversation, str) or not conversation.strip():
            raise CorpusError(
                f"{path}: utterance {record.get('id')!r} has no conversation_id"
            )
        utterances += 1
        acts: list[str] = []
        for raw in _raw_tags(record):
            act = _first_mapped(raw, active)
            if act is None:
                unmapped[raw] += 1
            elif act not in acts:
                acts.append(act)
        if acts:
            mapped += 1
        grouped.setdefault(conversation, []).append(
            (_position(record, fallback), tuple(acts))
        )
    return _assemble(
        "switchboard",
        grouped,
        utterances=utterances,
        mapped=mapped,
        unmapped=unmapped,
    )


def _record_acts(record: Mapping[str, Any]) -> tuple[str, ...]:
    """The act labels on one record, whether given singly or as a list."""
    for key in ("act", "acts"):
        value = record.get(key)
        if isinstance(value, str) and value.strip():
            return (value.strip(),)
        if isinstance(value, list):
            return tuple(
                item.strip() for item in value if isinstance(item, str) and item.strip()
            )
    return ()


def from_jsonl(path: Path | str, *, source: str = "jsonl") -> Import:
    """Count transitions in a corpus already labelled in our own act names.

    Two shapes are accepted, so a hand-built fixture and an export from elsewhere need no
    converter: flat rows (``{"conversation", "index", "act"}``) and dialogue rows
    (``{"conversation", "turns": [{"act": ...}]}``). Labels are taken verbatim -- this reader
    maps nothing, which is exactly why it is the safe one to test against.
    """
    grouped: dict[str, list[tuple[int, tuple[str, ...]]]] = {}
    unmapped: Counter[str] = Counter()
    utterances = mapped = 0
    for fallback, record in enumerate(_read_records(Path(path))):
        conversation = "default"
        for key in ("conversation", "conv_id", "dialogue", "dialog"):
            value = record.get(key)
            if isinstance(value, str) and value.strip():
                conversation = value.strip()
                break
        turns = record.get("turns")
        if isinstance(turns, list):
            for index, turn in enumerate(turns):
                if not isinstance(turn, Mapping):
                    raise CorpusError(f"{path}: turn {index} is not an object")
                acts = _record_acts(turn)
                utterances += 1
                mapped += 1 if acts else 0
                if not acts:
                    unmapped["(no act)"] += 1
                grouped.setdefault(conversation, []).append((index, acts))
            continue
        acts = _record_acts(record)
        utterances += 1
        mapped += 1 if acts else 0
        if not acts:
            unmapped["(no act)"] += 1
        grouped.setdefault(conversation, []).append((_position(record, fallback), acts))
    return _assemble(
        source,
        grouped,
        utterances=utterances,
        mapped=mapped,
        unmapped=unmapped,
    )
