"""How long between the messages of one turn?

A person types for about as long as the message takes to read, and pauses between thoughts. Discord shows a
typing indicator, so the pacing is visible: a two-message turn arriving instantly reads as a machine, and one
arriving with a real pause reads as somebody thinking.

Deliberately crude arithmetic, because the honest version needs per-person typing speeds we have no
measurements for. The numbers are calibrated to be plausible rather than correct: 45 words per minute is a
slow phone thumb, 75 is a quick keyboard.
"""

from __future__ import annotations

from ttrpg_chatbots.conv.parts import Delivery

#: Words per minute when somebody is typing slowly (a phone, or a distracted evening).
SLOW_WPM = 45.0
#: Words per minute at a keyboard.
FAST_WPM = 75.0
#: Nobody appears to type for less than this before a one-word message.
MIN_TYPING = 0.8
#: Nobody appears to type for longer than this before a message, however long it is.
MAX_TYPING = 12.0


def words(message: str) -> int:
    return len([word for word in message.split() if word.strip("?!.,")])


def typing_seconds(message: str, *, delivery: Delivery | None = None, wpm: float = FAST_WPM) -> float:
    """How long the person types before this message appears."""
    chosen = delivery or Delivery()
    if not chosen.show_typing:
        return 0.0
    if wpm <= 0:
        raise ValueError(f"wpm must be positive, got {wpm}")
    seconds = words(message) / wpm * 60.0
    return max(MIN_TYPING, min(MAX_TYPING, seconds))


def waits(
    messages: tuple[str, ...],
    *,
    delivery: Delivery | None = None,
    wpm: float = FAST_WPM,
) -> tuple[float, ...]:
    """Seconds to wait before each message, in order.

    The first wait is the typing time; each later message waits for the pause *and* its own typing, because a
    person reads what they just sent before starting the next thought.
    """
    chosen = delivery or Delivery()
    if not messages:
        return ()
    waits_out = [typing_seconds(messages[0], delivery=chosen, wpm=wpm)]
    for message in messages[1:]:
        waits_out.append(chosen.pause + typing_seconds(message, delivery=chosen, wpm=wpm))
    return tuple(waits_out)


def total_seconds(messages: tuple[str, ...], *, delivery: Delivery | None = None) -> float:
    """How long the whole turn takes to arrive."""
    return sum(waits(messages, delivery=delivery))
