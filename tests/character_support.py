"""Helpers for the character tests: a scripted prompter and a legal answer set."""

from __future__ import annotations

from ttrpg_chatbots.character.prompting import PrompterError


class ScriptedPrompter:
    """Feeds prepared answers, and remembers what was asked and said."""

    def __init__(self, *answers: str) -> None:
        self.answers = list(answers)
        self.asked: list[str] = []
        self.said: list[str] = []

    def ask(self, prompt: str) -> str:
        self.asked.append(prompt)
        if not self.answers:
            raise PrompterError(f"ran out of answers at {prompt!r}")
        return self.answers.pop(0)

    def say(self, text: str) -> None:
        self.said.append(text)

    @property
    def remaining(self) -> int:
        return len(self.answers)


# A full, legal Standard-Build answer script: attributes 7/5/3, abilities 13/9/5,
# virtues 7, backgrounds 5, then a power. No ability reaches 4, so no specialty prompts.
MECHANICS = [
    "4", "4", "2",  # Physical: 7 spent
    "3", "3", "2",  # Social: 5 spent
    "2", "2", "2",  # Mental: 3 spent
    "3", "3", "3", "2", "2", "0", "0", "0", "0", "0",  # Talents: 13
    "3", "3", "3", "0", "0", "0", "0", "0", "0", "0",  # Skills: 9
    "3", "2", "0", "0", "0", "0", "0", "0", "0", "0",  # Knowledges: 5
    "4", "2", "4",  # Virtues: 7 spent (base 1 each)
    "Mentor", "3", "Contacts", "2", "",  # Backgrounds: 5
    "Auspex", "2", "",  # Powers
]

INTERVIEW = ["A vat under New York.", "Boredom, mostly."]


def script(*, name: str | None = None, interview: list[str] | None = None) -> list[str]:
    """A complete answer script: optional name, the interview, then the mechanics."""
    answers: list[str] = []
    if name is not None:
        answers.append(name)
    answers.extend(interview if interview is not None else INTERVIEW)
    answers.extend(MECHANICS)
    return answers


def prompter(*, name: str | None = None, interview: list[str] | None = None) -> ScriptedPrompter:
    return ScriptedPrompter(*script(name=name, interview=interview))
