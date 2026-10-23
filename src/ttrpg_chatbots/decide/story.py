"""Should he tell a story now?

Phase three, and the only place he is allowed to be longer than a few words -- because a story is
what somebody asked for, not what he decided to deliver. Three triggers, and the reason each is here
rather than "when he feels like it":

1. **`asked`** -- a direct question about something that happened ("how did the fence go?"). The
   clearest invitation there is.
2. **`follow_up`** -- he offered a hook and the other person asked a question about it. This is the
   chain the whole design was built around: hook, then detail, then story.
3. **`leaned_in`** -- two long turns in a row, and no story told yet this session. The other person is
   clearly settled in; a story is what a friend offers at that point.

Everything else is a no. A story told unprompted is a monologue, and a monologue is what the last
three rounds of tuning were about removing.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass

from ttrpg_chatbots.life.state import Life, Story
from ttrpg_chatbots.perceive.inbound import looks_like_question

# How many consecutive turns count as "settled in". Two: one long message is a mood, two is a
# conversation.
LEANED_IN = 2

_WORDS = re.compile(r"[a-z']+")

ASKED_ABOUT = (
    "how did",
    "how did it",
    "what happened",
    "how was",
    "how goes",
    "did you ever",
    "tell me about the time",
)

# The question that asks what a story meant. Deliberately narrow: "why?" alone is usually about the
# thing he is doing, not about the story he just told.
POINT_QUESTIONS = (
    "what did you learn",
    "what was the point",
    "what is the point",
    "why does that matter",
    "what did that teach you",
    "was there a lesson",
)


@dataclass(frozen=True)
class Telling:
    """A story he may tell, and which of the three reasons made it welcome."""

    story: Story
    mode: str  # "asked" | "follow_up" | "leaned_in"


def choose(
    *,
    text: str,
    life: Life | None,
    depth: int = 0,
    told: Mapping[str, int] | None = None,
    offered_hook: bool = False,
    topic: str = "",
    just_told: str = "",
) -> Telling | None:
    """The story he may tell now, with the reason -- or nothing.

    `topic` is what the conversation is currently about (the activity he offered, or the subject they
    named) and `just_told` is the story id he told in the previous turn, if any. Both come from the
    conversation rather than from a lookup, which is what makes "how did the fence go?" reach the
    fence story and the *point* reachable at all.
    """
    if life is None:
        return None
    stories = tuple(life.stories)
    if not stories:
        return None

    said = (text or "").lower()
    counts = told or {}

    # The point is the one thing that only arrives if asked: the story is already told, and this is
    # the question that asks what it meant.
    if just_told and _asks_for_the_point(said):
        story = _by_id(stories, just_told)
        return Telling(story=story, mode="point") if story else None

    if _asks_about_the_past(said):
        story = _prefer(stories, counts, topic, said)
        return Telling(story=story, mode="asked") if story else None
    if offered_hook and said.endswith("?") and _is_about_the_offering(said, topic):
        # They asked something about the thing he just offered. The story is the honest answer to
        # "how did that go", and it is the story of *that* thing.
        #
        # `_is_about_the_offering` is the fix for a measured failure: "what is the plot of dune?"
        # arrived after he had offered a hook, and answered with the freight train, because any
        # question looked like a follow-up. A question that names something else is not a follow-up.
        story = _prefer(stories, counts, topic, said)
        return Telling(story=story, mode="follow_up") if story else None
    if depth >= LEANED_IN and not looks_like_question(said):
        # Unprompted, and not while they are asking something: "what are you up to" is a question
        # about his day, and answering it with a story is the monologue problem again.
        story = _prefer(stories, counts, topic, said)
        return Telling(story=story, mode="leaned_in") if story else None
    return None


#: Words that point at what was just said, rather than naming something new.
REFERRING = frozenset(
    {"it", "its", "that", "this", "those", "these", "them", "they", "there", "then", "again"}
)


def _is_about_the_offering(said: str, topic: str) -> bool:
    """Whether a question is about the thing he just offered.

    Either it refers ("how did *that* go", "is *it* still doing that"), or it names the same topic he
    offered. "what is the plot of dune" does neither, so it hedges instead of answering with a story.
    """
    words = {word.strip(".,!?;:'\"").lower() for word in said.split()}
    if words & REFERRING:
        return True
    if not topic:
        return False
    named = topic.split(":")[-1].replace("-", " ")
    # "computer" and "computers" are the same subject; the index matches whole words, so a prefix
    # comparison is what keeps "how is the computer?" a follow-up about computers.
    for part in named.split():
        if len(part) <= 3:
            continue
        if any(word.startswith(part) or part.startswith(word) for word in words if len(word) > 3):
            return True
    return False


def _asks_about_the_past(said: str) -> bool:
    return any(phrase in said for phrase in ASKED_ABOUT)


def _asks_for_the_point(said: str) -> bool:
    return any(phrase in said for phrase in POINT_QUESTIONS)


def _by_id(stories: tuple[Story, ...], story_id: str) -> Story | None:
    return next((story for story in stories if story.id == story_id), None)


def _prefer(
    stories: tuple[Story, ...], counts: Mapping[str, int], topic: str, said: str = ""
) -> Story | None:
    """The story for what is being discussed, else the one told least.

    Three tiers, and each one exists because of a measured miss:

    1. the **topic** of the conversation (the activity he offered, or the subject they named);
    2. a **word** shared with the question -- "how did the fence go?" reaches a story that mentions
       a fence, which is what a person does when the topic is not already known;
    3. the least-told story, because a question about the past deserves an answer even when nothing
       lines up.
    """
    if topic:
        matching = [story for story in stories if story.topic == topic]
        if matching:
            stories = tuple(matching)
    words = {word for word in _WORDS.findall(said.lower()) if len(word) > 3}
    if words:
        shared = [
            story
            for story in stories
            if words
            & {word for word in _WORDS.findall(f"{story.body} {story.words}".lower())}
        ]
        if shared:
            stories = tuple(shared)
    ordered = sorted(stories, key=lambda story: (counts.get(story.id, 0), story.id))
    return ordered[0] if ordered else None
