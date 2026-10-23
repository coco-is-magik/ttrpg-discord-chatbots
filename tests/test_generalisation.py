"""Messages nobody tuned on.

Every phrase in the phrasebooks, the tests and the docs was written by hand, and the slices that built
`follow_up`, `ask_back` and the sentiment routing were all debugged against real conversations. That is
how overfitting happens: the detectors get narrower and the tests keep passing because they use the same
examples the code was written against.

So this file is held out on purpose. **These messages must not appear in the phrasebooks or in the
source** -- if one of them turns up there, it has stopped being a probe. Expectations are sets, because
some of these have more than one good answer and pretending otherwise would be a test of my taste.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ttrpg_chatbots.bots.identity import bots_from_records
from ttrpg_chatbots.bots.ladder import Ladder

# (message, the jobs that would be a good answer)
PROBE: tuple[tuple[str, frozenset[str]], ...] = (
    ("i got a new bike", frozenset({"follow_up"})),
    ("sorted the garage out this weekend", frozenset({"follow_up"})),
    ("went for a run this morning", frozenset({"follow_up"})),
    ("my sister is visiting next week", frozenset({"follow_up"})),
    ("i have been learning guitar", frozenset({"follow_up"})),
    ("we finally got the shed up", frozenset({"follow_up"})),
    # Big news: engaging is right, and so is a straight note -- the roll may legitimately miss.
    ("i quit my job", frozenset({"follow_up", "noted"})),
    # Something bad happening to something of theirs: commiserate, either way round.
    ("the game got cancelled", frozenset({"mirror", "noted"})),
    ("the boss is being a nightmare", frozenset({"mirror"})),
    ("my cat died", frozenset({"reassure"})),
    ("nice weather for it", frozenset({"noted"})),
    ("the truck is in the shop", frozenset({"noted"})),
    ("thanks for the other day", frozenset({"acknowledge"})),
    ("are you free this weekend", frozenset({"offer_hook"})),
    ("you around", frozenset({"offer_hook"})),
    ("how is the fence coming along", frozenset({"hedge"})),
    ("what do you think of the weather", frozenset({"hedge"})),
    ("did you see the match", frozenset({"hedge"})),
    ("i am going to bed", frozenset({"close"})),
    ("ok", frozenset({"noted"})),
    ("lol", frozenset({"noted"})),
)

WORLD = Path("examples/friends_world")


def _ladder(friend: str = "friend-b") -> Ladder:
    """The friend as the bot builds him, so the probe measures the live routing."""
    roster = bots_from_records(
        json.loads(Path("data/bots.json").read_text()), source="data/bots.json"
    )
    spec = next(bot for bot in roster if bot.id == friend)
    return Ladder(
        friend=friend,
        data=WORLD,
        style=spec.persona.style,
        question_rate=spec.persona.question_rate,
    )


@pytest.mark.parametrize(("message", "expected"), PROBE)
class TestHeldOutMessages:
    def test_it_routes_somewhere_sensible(self, message: str, expected: frozenset[str]) -> None:
        out = _ladder().line(text=message, speaker="tav")
        job = dict(out.trail.steps).get("job", "(silence)")
        assert job in expected, f"{message!r} -> {job} ({out.text if hasattr(out, 'text') else out})"

    def test_and_it_never_says_something_wrong(self, message: str, expected: frozenset[str]) -> None:
        """Silence is allowed to be wrong; a *wrong line* is not -- and curiosity after bad news is the
        worst line there is.

        The failure that started this file: "my cat died" was treated as something of theirs to be
        curious about, and came back as "is it any good?". Only the bad-news cases are checked here:
        for good news, "what kind?" is exactly the right answer.
        """
        if not (expected & {"reassure", "mirror"}):
            return
        out = _ladder().line(text=message, speaker="tav")
        if not hasattr(out, "text"):
            return
        said = out.text.lower()
        for bad in ("is it any good", "how long have you been at that", "what kind", "nice ^^"):
            assert bad not in said, f"{message!r} -> {out.text!r} ({bad!r})"


def test_bad_news_is_never_engaged_with() -> None:
    """A guard rather than a routing rule, so it holds even when the routing misses."""
    from ttrpg_chatbots.decide.reciprocate import engage

    assert not engage(
        question_rate=1.0, text="my cat died", theirs=True, already_asked=True, bad_news=True
    )


def test_the_probe_is_still_held_out() -> None:
    """If a probe message turns up as a variant, the probe has stopped measuring anything.

    Compared against the *variants* rather than the raw file text: a substring search over the JSON
    matches "ok" inside "okay", which is a test of nothing.
    """
    variants: set[str] = set()
    for path in sorted((WORLD / "phrasebooks").rglob("*.json")):
        book = json.loads(path.read_text())
        for family in book.get("families", {}).values():
            for variant in family.get("variants", []):
                variants.add(variant.strip().lower())
    for message, _ in PROBE:
        assert message.strip().lower() not in variants, f"{message!r} is a phrasebook variant now"
