"""One message, or several?

A turn's parts arrive as one or more messages. The rules are about *shape*, not length: a reaction and the
substance are the natural split (`oh nice` then `Messing with the tank`), an emoji alone is a message in its
own right, and two substantial parts stay together.

Why it matters: a bot's most reliable tell is that it always says one tidy thing at a time. Measured from the
first dataset, 260 messages arrived in exactly one package each, so the packaging never varied -- which is
visible even when every word is new.
"""

from __future__ import annotations

from ttrpg_chatbots.conv.parts import Delivery, Part, Turn

#: Parts that read as their own message when they are not the only thing being said. A hand-back is one of
#: them: "Messing with the tank" then "how is otis doing?" is how a person texts it.
SPLIT_ALONE = frozenset({"reaction", "emoji", "aside", "question"})


def package(turn: Turn, *, delivery: Delivery | None = None) -> tuple[str, ...]:
    """The messages this turn arrives as. Never empty, never more than the limit."""
    chosen = delivery or Delivery()
    parts = _ordered(turn.parts, chosen)

    if not chosen.split or len(parts) == 1:
        return (turn.text,)

    groups: list[list[Part]] = []
    for part in parts:
        alone = _stands_alone(part, chosen) and len(parts) > 1
        if alone:
            groups.append([part])
            continue
        if groups and _joinable(groups[-1], part):
            groups[-1].append(part)
        else:
            groups.append([part])

    messages = tuple(" ".join(part.text for part in group) for group in groups if group)
    messages = tuple(message for message in messages if message.strip())
    if not messages:
        return (turn.text,)
    return _merge_down(messages, chosen.max_messages)


def _stands_alone(part: Part, delivery: Delivery) -> bool:
    """Whether this kind of part is its own message, given the delivery switches."""
    if part.kind == "reaction":
        return delivery.separate_reaction
    if part.kind == "emoji":
        return delivery.emoji_alone
    if part.kind == "aside":
        return delivery.aside_last
    if part.kind == "question":
        return delivery.separate_question
    return False


def _ordered(parts: tuple[Part, ...], delivery: Delivery) -> tuple[Part, ...]:
    """An aside goes last: it is a thought after the fact, not before it."""
    if not delivery.aside_last:
        return parts
    asides = tuple(part for part in parts if part.kind == "aside")
    if not asides:
        return parts
    return tuple(part for part in parts if part.kind != "aside") + asides


def _joinable(group: list[Part], part: Part) -> bool:
    """Whether this part belongs with the ones already grouped."""
    if not group:
        return True
    if group[0].kind in SPLIT_ALONE and len(group) == 1:
        return False
    return True


def _merge_down(messages: tuple[str, ...], limit: int) -> tuple[str, ...]:
    """Fewer messages than the limit, by joining the shortest neighbours.

    Merging rather than truncating: dropping a part would lose words the ladder already decided to say.
    """
    if limit < 1:
        raise ValueError(f"max_messages must be at least 1, got {limit}")
    working = list(messages)
    while len(working) > limit:
        index = min(range(len(working) - 1), key=lambda position: len(working[position]))
        working[index : index + 2] = [working[index] + " " + working[index + 1]]
    return tuple(working)
