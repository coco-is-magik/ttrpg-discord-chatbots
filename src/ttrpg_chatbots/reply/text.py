"""Normalising how a person types, so the lexicon can match it.

Texting is not prose. "yoooo", "whats good", "howre", "whatre u up to" all failed to match
patterns written for careful English on 2026-10-21, and to a reader those misses look random
rather than systematic. This module turns a message into the form the patterns expect. It is not
spell correction and it does not guess at meaning -- it fixes the three things that actually
vary between one person's typing and another's:

* **repeated letters** -- "yoooo" and "heyyy" are "yo" and "hey";
* **missing apostrophes** -- "whats", "dont", "im" are "what's", "don't", "i'm";
* **texting spellings** -- "howre" is "how are", "u" is "you", "ur" is "your".

Everything is word-by-word, so a substring is never rewritten by accident. Applying this once, at
the lexicon's front door, is why the fix is a mechanism and not six new patterns.
"""

from __future__ import annotations

import re

# Three or more of the same letter is emphasis, not spelling: "yoooo" -> "yo", "sooo" -> "so".
_REPEATS = re.compile(r"([a-z])\1{2,}")

# Word-boundary spellings, mapped to the form the patterns are written against. Conservative on
# purpose: nothing here changes a word that is already a word ("im" is not "Him").
_EXPANSIONS = {
    "whats": "what's",
    "whos": "who's",
    "hows": "how's",
    "whens": "when's",
    "wheres": "where's",
    "whys": "why's",
    "thats": "that's",
    "theres": "there's",
    "heres": "here's",
    "dont": "don't",
    "doesnt": "doesn't",
    "didnt": "didn't",
    "cant": "can't",
    "wont": "won't",
    "isnt": "isn't",
    "arent": "aren't",
    "wasnt": "wasn't",
    "couldnt": "couldn't",
    "wouldnt": "wouldn't",
    "shouldnt": "shouldn't",
    "im": "i'm",
    "ive": "i've",
    "youre": "you're",
    "youve": "you've",
    "theyre": "they're",
    "howre": "how are",
    "whatre": "what are",
    "wherere": "where are",
    "howd": "how did",
    "whatd": "what did",
    "u": "you",
    "ur": "your",
    "ya": "you",
    "sup": "what's up",
}

_WORD = re.compile(r"[a-z']+")


def _expand(match: re.Match[str]) -> str:
    word = match.group(0)
    return _EXPANSIONS.get(word, word)


def normalise_typing(text: str) -> str:
    """Lower-case, de-emphasise and expand a message into the lexicon's vocabulary."""
    lowered = " ".join((text or "").lower().split())
    if not lowered:
        return ""
    collapsed = _REPEATS.sub(r"\1", lowered)
    # Only pure word runs are expanded, so punctuation and mentions survive untouched.
    return _WORD.sub(_expand, collapsed)
