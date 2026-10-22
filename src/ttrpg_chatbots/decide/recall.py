"""Should he bring up what they told him?

The gate that stops memory becoming the exposition failure in a new costume. A friend who remembers
your dog mentions it once in a while; a system with memory recites it. There are exactly two ways a
fact may be raised, and they are not interchangeable:

* **raised** -- the message shares a word with the fact ("how's the dog?"). Answering it is not
  recall, it is listening, and it is welcome in any job that can hold it.
* **session** -- they have not spoken since yesterday at least, and it is the kind of thing a friend
  asks about (a pet, a job). This belongs to *openings*: a greeting may say "morning. how's otis".
  It must never fire on an unrelated question, which is how "what is the plot of dune?" got answered
  with a question about a dog.

Everything else is silence about the fact. It stays in the file for when it is wanted.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from ttrpg_chatbots.memory.long import Fact
from ttrpg_chatbots.memory.retrieve import read as retrieve

# Kinds worth a question at the start of a session. A remembered "i like hockey" is not something a
# person opens with; a dog is.
ASK_ABOUT = ("pet.", "job")

SESSION_BUCKETS = ("day", "week", "long")


@dataclass(frozen=True)
class Recall:
    """A fact he may bring up, and which of the two reasons made it welcome."""

    fact: Fact
    mode: str  # "raised" | "session"


def choose(
    *,
    text: str,
    facts: Iterable[Fact],
    bucket: str = "fresh",
    today: str = "",
) -> Recall | None:
    """The fact he may bring up now, with the reason -- or nothing."""
    known = tuple(facts)
    if not known:
        return None

    def raised_today(fact: Fact) -> bool:
        return bool(today) and fact.meta.get("raised") == today

    mentioned = retrieve(cue=text, facts=known, limit=1)
    if mentioned and not raised_today(mentioned[0]):
        return Recall(fact=mentioned[0], mode="raised")

    if bucket not in SESSION_BUCKETS:
        return None
    candidates = [
        fact for fact in known if fact.key.startswith(ASK_ABOUT) and not raised_today(fact)
    ]
    if not candidates:
        return None
    # The one said most often first, then the most recent: the thing they care about, not the last
    # thing they happened to type.
    candidates.sort(key=lambda fact: (-fact.count, fact.last_seen, fact.key))
    return Recall(fact=candidates[0], mode="session")