"""How a character types.

A template says what a character says; a style says how it looks when they type it. The
difference matters more than it sounds: perfectly punctuated, sentence-cased, apostrophe-complete
text reads like a press release no matter how good the writing is, and the fastest way to make a
friend sound like a person is to stop the renderer from tidying them up.

Five honest levers, all deterministic:

* **case** -- sentence case (the default), all lower, or left exactly as written.
* **apostrophes** -- dropped, but only where the result is not another word. "don't" becomes
  "dont"; "I'll" never becomes "ill" and "we'll" never becomes "well", because a style that
  invents ambiguity is a bug, not a voice.
* **typos** -- a small, fixed set of transpositions in very common words, at a low rate. Nothing
  else: a random letter drop in a noun reads as broken rather than human.
* **stutter** -- the first word repeated on its opening letter ("h-hi", "i-i think so"), at a low
  rate. This is how hesitation gets into a *voice* as well as into text: the synthesiser reads the
  stutter, so a hesitant character does not need an engine that can act.
* **emoji** -- a pool of text emoticons and kaomoji, drawn from at a low rate and appended. Western
  and Japanese kinds are one pool on purpose: the choice between them is taste, not language.

The same input always renders the same way, keyed on the text, so a replay is a replay and a test
can assert a specific line. Style never changes what is said, only how it is typed.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Mapping

CASES = ("sentence", "lower", "as-written")

# Dropped only where the un-apostrophised form is not a different word, so the voice never
# creates a misreading. Deliberately excludes I'll/I'd/we'll/he'll/she'll/we're/we've.
_DROPPABLE = frozenset(
    {
        "don't",
        "doesn't",
        "didn't",
        "isn't",
        "wasn't",
        "aren't",
        "weren't",
        "won't",
        "can't",
        "couldn't",
        "shouldn't",
        "wouldn't",
        "haven't",
        "hasn't",
        "hadn't",
        "you're",
        "you've",
        "you'd",
        "you'll",
        "they're",
        "they've",
        "that's",
        "there's",
        "what's",
        "here's",
        "who's",
        "let's",
        "i'm",
        "i've",
    }
)

# Fast-typing slips that read as human rather than broken: transpositions in words nobody
# misreads. Nothing here is a meme spelling.
_TYPOS: Mapping[str, str] = {
    "just": "jsut",
    "about": "abotu",
    "with": "wiht",
    "something": "soemthing",
    "because": "becuase",
}


#: Text emoticons and kaomoji, drawn from when a line gains one. A pool rather than a single value,
#: because one emoticon repeated is a tic and five in rotation is a habit.
EMOTICONS: tuple[str, ...] = (
    "^^",
    ":3",
    "^_^",
    ";;",
    "(´･ω･`)",
    "(◕‿◕)",
    "(｡•́︿•̀｡)",
    "(・ω・)",
    "(>_<)",
    "(＾▽＾)",
    "(*^▽^*)",
    "(￣▽￣)",
    "(╥﹏╥)",
    "owo",
    "(๑•̀ㅂ•́)و",
)


@dataclass(frozen=True)
class Style:
    """How one character types. The default is "nobody has decided", i.e. tidy text."""

    case: str = "sentence"
    drop_apostrophes: bool = False
    strip_final_period: bool = False
    typo_rate: float = 0.0
    stutter_rate: float = 0.0
    filler_rate: float = 0.0
    fillers: tuple[str, ...] = ()
    emoji_rate: float = 0.0
    emojis: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.case not in CASES:
            raise ValueError(f"case must be one of {list(CASES)}, got {self.case!r}")
        if isinstance(self.typo_rate, bool) or not isinstance(self.typo_rate, (int, float)):
            raise ValueError("typo_rate must be a number")
        if not 0.0 <= float(self.typo_rate) <= 1.0:
            raise ValueError(f"typo_rate must be between 0 and 1, got {self.typo_rate}")
        for name in ("stutter_rate", "filler_rate"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"{name} must be a number")
            if not 0.0 <= float(value) <= 1.0:
                raise ValueError(f"{name} must be between 0 and 1, got {value}")
        if isinstance(self.emoji_rate, bool) or not isinstance(self.emoji_rate, (int, float)):
            raise ValueError("emoji_rate must be a number")
        if not 0.0 <= float(self.emoji_rate) <= 1.0:
            raise ValueError(f"emoji_rate must be between 0 and 1, got {self.emoji_rate}")
        if self.emoji_rate and not self.emojis:
            # A rate with no pool would silently do nothing, which is worse than an error.
            raise ValueError("emoji_rate needs a non-empty emojis pool")
        if self.filler_rate and not self.fillers:
            raise ValueError("filler_rate needs a non-empty fillers pool")
        if any(not isinstance(item, str) or not item.strip() for item in self.emojis):
            raise ValueError("emojis must be non-blank strings")
        if any(not isinstance(item, str) or not item.strip() for item in self.fillers):
            raise ValueError("fillers must be non-blank strings")

    def describe(self) -> str:
        bits = [self.case]
        if self.drop_apostrophes:
            bits.append("no apostrophes")
        if self.strip_final_period:
            bits.append("no full stop")
        if self.typo_rate:
            bits.append(f"{self.typo_rate:.0%} typos")
        if self.stutter_rate:
            bits.append(f"{self.stutter_rate:.0%} stutter")
        if self.filler_rate:
            bits.append(f"{self.filler_rate:.0%} fillers ({len(self.fillers)} in the pool)")
        if self.emoji_rate:
            bits.append(f"{self.emoji_rate:.0%} emoticons ({len(self.emojis)} in the pool)")
        return ", ".join(bits)

    @classmethod
    def from_record(cls, record: Mapping[str, object]) -> Style:
        """Read a ``style`` object from a persona, naming the field that is wrong."""
        if not isinstance(record, Mapping):
            raise ValueError("style must be an object")
        case = record.get("case", "sentence")
        if not isinstance(case, str):
            raise ValueError("style.case must be a string")
        flags: dict[str, object] = {}
        for key in ("drop_apostrophes", "strip_final_period"):
            value = record.get(key, False)
            if not isinstance(value, bool):
                raise ValueError(f"style.{key} must be true or false")
            flags[key] = value
        emojis = record.get("emojis") or []
        if isinstance(emojis, str) or not isinstance(emojis, (list, tuple)):
            raise ValueError("style.emojis must be a list of strings")
        fillers = record.get("fillers") or []
        if isinstance(fillers, str) or not isinstance(fillers, (list, tuple)):
            raise ValueError("style.fillers must be a list of strings")
        for key in ("stutter_rate", "filler_rate", "emoji_rate"):
            value = record.get(key, 0.0)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"style.{key} must be a number")
            flags[key] = float(value)
        try:
            return cls(
                case=case,
                typo_rate=record.get("typo_rate", 0.0),
                emojis=tuple(str(item) for item in emojis),
                fillers=tuple(str(item) for item in fillers),
                **flags,  # type: ignore[arg-type]
            )
        except ValueError as error:
            raise ValueError(f"style: {error}") from error


DEFAULT_STYLE = Style()


def _digest(text: str) -> int:
    return int.from_bytes(hashlib.blake2b(text.encode("utf-8"), digest_size=8).digest(), "big")


def _lower_first(text: str) -> str:
    """Lower-case the opening letter unless the whole opening word is shouting."""
    first = text.split(None, 1)[0]
    if first.isupper():  # "HAH" and "NO" keep their volume
        return text
    return text[:1].lower() + text[1:]


def _drop_apostrophes(text: str) -> str:
    """Remove apostrophes only where the result is not another word."""
    out: list[str] = []
    for token in text.split(" "):
        bare = token.strip(".,!?;:").lower()
        if "'" in token and bare in _DROPPABLE:
            out.append(token.replace("'", "", 1))
        else:
            out.append(token)
    return " ".join(out)


def _introduce_stutter(text: str) -> str:
    """False-start the first word: "hi" -> "h- hi", "think" -> "th- think".

    Two letters and a **space** after the hyphen, because that is what is audible. Measured on
    `en_US-ryan-medium`, the first version's "I-I think it is late again" was 1.29 s against a 1.20 s
    baseline -- a 90 ms difference nobody hears -- while "th- this is the train" was 1.35 s against
    0.79 s, a 560 ms false start. The space is what makes piper stop and restart the word.

    A one-letter word keeps a one-letter fragment ("i- i think"), which is the classic typed stutter --
    and it is the commonest opening word there is, so excluding it would leave most lines unstuttered.
    """
    first, _, rest = text.partition(" ")
    if not first or not first[0].isalpha():
        return text
    fragment = first[:2] if len(first) > 2 else first[0]
    stuttered = f"{fragment}- {first}"
    return f"{stuttered} {rest}" if rest else stuttered


def _introduce_filler(text: str, pool: tuple[str, ...]) -> str:
    """Put a hesitation in front of the line: "um, i think so"."""
    return f"{_pick_from(text, pool)}, {text}"


def _already_has_mark(text: str, pool: tuple[str, ...]) -> bool:
    """Whether the line already carries one of these marks as a token.

    A mark is matched as a whole token, optionally followed by punctuation: ``^^.`` counts, ``^^``
    counts, and ``:3`` counts -- while ``3:30`` does not, and neither does a mark that happens to sit
    inside a word. Written after two wrong versions: the first only looked at the final token, the
    second stripped punctuation from both ends and so destroyed every emoticon that *starts* with it.
    """
    for token in text.split():
        for mark in pool:
            if token == mark or (
                token.startswith(mark) and not token[len(mark) :].strip(".,!?;:'")
            ):
                return True
    return False


def _pick_from(text: str, pool: tuple[str, ...]) -> str:
    """A stable pick from a pool, keyed on the line so a replay is a replay."""
    return pool[_digest(text) % len(pool)]


def _introduce_typo(text: str) -> str:
    """Swap two letters in the first eligible word, or leave the text alone."""
    for word, typo in _TYPOS.items():
        if word in text:
            return text.replace(word, typo, 1)
    return text


def apply_style(text: str, style: Style | None = None) -> str:
    """Render one line in a character's typing style. Deterministic for a given text."""
    active = style if style is not None else DEFAULT_STYLE
    result = text.strip()
    if not result:
        return result
    if active.strip_final_period and result.endswith(".") and not result.endswith(".."):
        result = result[:-1].rstrip()
    if active.drop_apostrophes:
        result = _drop_apostrophes(result)
    if active.typo_rate:
        # One slip per line at most, and only on a line that drew the short straw. Keyed on the
        # text, so the same sentence always gets the same treatment.
        if _digest(result) % 10_000 < int(active.typo_rate * 10_000):
            result = _introduce_typo(result)
    if active.stutter_rate:
        # Before casing, so sentence case gives "H- hello" rather than "H- Hello" -- measured on the
        # first attempt, which stuttered the capitalised word and read as shouting.
        if _digest(f"stutter:{result}") % 10_000 < int(active.stutter_rate * 10_000):
            result = _introduce_stutter(result)
    if active.filler_rate and active.fillers:
        # After the stutter, so the hesitation is not itself false-started ("um,-um,"), and before
        # casing so the filler keeps its own lowercase shape.
        if _digest(f"filler:{result}") % 10_000 < int(active.filler_rate * 10_000):
            result = _introduce_filler(result, active.fillers)
    if active.case == "lower":
        result = _lower_first(result)
    elif active.case == "sentence":
        result = result[:1].upper() + result[1:]
    if active.emoji_rate and active.emojis:
        # Not if the line already carries one -- **anywhere in it**, not just at the end. Two failure
        # modes were measured: checking only the last token let "oh nice ^^. how is it going?" collect a
        # second emoticon after the question mark, and stripping punctuation from every token turned
        # ":3" into "3", so the mark went unrecognised and was appended again.
        if not _already_has_mark(result, active.emojis):
            if _digest(f"emoji:{result}") % 10_000 < int(active.emoji_rate * 10_000):
                result = f"{result} {_pick_from(result, active.emojis)}"
    return result
