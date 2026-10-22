"""The greet stage, as a facade over the ladder.

`TTRPG_CONVERSATION=greet` runs *only* this: greetings answer through the ladder, everything else
still goes to the old classifier. It exists so one phase can be proved on real traffic before the
next is switched on, which is why it is a ten-line subclass rather than a second implementation.
"""

from __future__ import annotations

from ttrpg_chatbots.bots.ladder import Ladder


class Greeter(Ladder):
    """The greet phrasebook and nothing else."""

    def __init__(self, *, friend: str, **kwargs) -> None:
        kwargs.pop("jobs", None)
        super().__init__(friend=friend, jobs=("greet",), **kwargs)

