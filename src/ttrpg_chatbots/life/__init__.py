"""A friend's life: what they are in the middle of, and what they are annoyed about.

The point of this package is that a person is not a set of answers. They are doing something
right now, they are mildly annoyed about something, and they have reasons for the things they
chose. A reply built from that sounds like somebody; a reply built from a fact sounds like a
caption.

* :mod:`ttrpg_chatbots.life.state` -- activities, grievances, and today's pick.
* :mod:`ttrpg_chatbots.life.render` -- those, as short spoken lines.
"""

from ttrpg_chatbots.life.render import LifeVoice, load_lives
from ttrpg_chatbots.life.state import Activity, Grievance, Life, LifeError

__all__ = [
    "Activity",
    "Grievance",
    "Life",
    "LifeError",
    "LifeVoice",
    "load_lives",
]
