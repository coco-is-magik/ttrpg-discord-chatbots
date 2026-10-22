"""Does the whole corpus match the brief?

The per-phase harness in ``govern`` measures what the ladder *does* with one message. This one measures
the *material*: every line he can say, every subject he claims, every story he owns. It exists because
reviewing 50 lines by eye cannot tell you that his opinions run out after one question, or that a
quarter of his lines end on a punchline -- both of which were true, and both of which are numbers.

Each check returns the evidence, not just a verdict, so a failure names the line that caused it. The
suite asserts the whole report passes, which makes this the guard on content edits.
"""

from __future__ import annotations

import json
import re
import statistics
from dataclasses import dataclass, field
from pathlib import Path

from ttrpg_chatbots.bots.persona import Persona, PersonaError
from ttrpg_chatbots.decide import persona_fit, subject
from ttrpg_chatbots.reply.entities import EntityIndex
from ttrpg_chatbots.decide.length import CONTENT_FLOOR
from ttrpg_chatbots.decide.variant import Phrasebook, load as load_book
from ttrpg_chatbots.life.render import load_lives
from ttrpg_chatbots.reply.datasets import load_world
from ttrpg_chatbots.life.state import Life

#: Wording that is contemptuous of the person being answered. Firm opinions about the *world* are the
#: point of a persona like this one; contempt for the human is not, and a template is the wrong place
#: to discover it. Kept here rather than in a test so the harness and the suite share one list.
COLD_PHRASES: tuple[str, ...] = (
    "you are stupid",
    "you're stupid",
    "you are an idiot",
    "you're an idiot",
    "you are wrong",
    "you're wrong",
    "you are boring",
    "you're boring",
    "that's boring",
    "shut up",
    "nobody cares",
    "do not care about you",
    "don't care about you",
    "whatever you say",
    "obviously you",
)

#: Adjectives that are only cold when they are aimed at the person rather than at a thing. "Something
#: boring and fixable" is advice about hardware; "you are boring" is contempt. Measured while building
#: this: the blunt list flagged the first one, which is why the direction is checked.
COLD_ADJECTIVES: tuple[str, ...] = ("stupid", "idiot", "boring", "obviously", "dull")

#: What a placeholder becomes when the harness evaluates a line. A template's final sentence can be a
#: single placeholder ("{hook}. {event_phrase}"), and judging *that* as a short beat is judging the
#: template rather than the sentence he says -- the rendered line is a full clause. These samples are
#: the shapes the slots actually hold, so the register and length checks see what a person would read.
SAMPLES: dict[str, str] = {
    "hook": "sanding a rifle stock",
    "short": "out back with the fence",
    "invite": "you got anything falling apart at your place?",
    "why": "i wanted to know what the machine was doing",
    "fact": "hockey is the best game there is",
    "fact_value": "otis",
    "event_phrase": "the season opener is in six days",
    "plan_what": "get down to a game",
    "plan_when": "next month",
    "story_body": "my grandfather's axe hung in the garage for twenty years",
    "story_point": "that was never the point of it",
    "doing": "trying to get an old machine to boot",
    "phase": "it gets to the boot screen and quits",
    "grievance": "truck failed inspection over a bulb i already replaced",
    "reaction": "yeah, i hear that",
    "topic": "hockey",
    "subject": "the game",
}

#: A placeholder with no sample: long enough that it cannot be mistaken for a beat, so an unfilled
#: template is judged on its own words rather than on the placeholder.
FILLER = "a few words about the thing"

#: How many subjects each declared interest needs before he stops repeating himself.
MIN_ITEMS_PER_TOPIC = 3

#: The jobs where a second declarative sentence is a warning sign. These are the social moves, where
#: the old corpus failed: a greeting that also explains itself, a mirror with a punchline. The content
#: jobs are exempt on purpose -- "what are you up to" answering with a hook and the news of the day is
#: two sentences that are both the point, and a story is allowed to land.
SOCIAL_JOBS = frozenset({"greet", "noted", "acknowledge", "mirror", "close", "reassure", "hedge"})


def sample_render(line: str) -> str:
    """Replace every placeholder with the shape of thing it holds."""
    return re.sub(
        r"\{([a-z_]+)\}", lambda match: SAMPLES.get(match.group(1), FILLER), line
    )

#: A reply is a text message, not a paragraph. Measured on the old corpus: median 7 words, but 51%
#: two-sentence lines and 29% ending on a beat.
MAX_MEDIAN_WORDS = 18.0
MAX_WORDS = 30

#: Life depth, so "what are you up to" cannot run dry after a week.
MIN_STORIES = 4
MIN_PLANS = 3
MIN_GRIEVANCES = 4
MIN_ACTIVITIES = 4


@dataclass
class Finding:
    """One check, its verdict, and the lines that decided it."""

    check: str
    question: str
    ok: bool
    evidence: tuple[str, ...] = ()

    def describe(self) -> str:
        mark = "ok  " if self.ok else "FAIL"
        detail = "" if self.ok else "  " + "; ".join(self.evidence[:4])
        return f"{mark} {self.check:24} {self.question}{detail}"


@dataclass
class PersonaReport:
    """Everything the harness measured about one friend's material."""

    friend: str
    findings: list[Finding] = field(default_factory=list)
    stats: dict[str, float] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return all(finding.ok for finding in self.findings)

    @property
    def failures(self) -> tuple[Finding, ...]:
        return tuple(finding for finding in self.findings if not finding.ok)

    def summary(self) -> str:
        lines = [finding.describe() for finding in self.findings]
        stats = "  ".join(f"{key} {value:g}" for key, value in self.stats.items())
        verdict = "PASS" if self.ok else f"FAIL ({len(self.failures)} check(s))"
        return "\n".join([*lines, "", f"{verdict}  {self.friend}  {stats}"])


def _words(text: str) -> int:
    return len(text.split())


def _sentences(text: str) -> int:
    return len([part for part in text.replace("!", ".").replace("?", ".").split(".") if part.strip()])


def _first_sentence(text: str) -> str:
    """The opening sentence: the part trim can never take away."""
    return re.split(r"[.!?]", text.strip())[0].strip()


def _declaratives(text: str) -> int:
    """Sentences that state something. A question at the end is a hand-back, not a stacked statement."""
    parts = [part.strip() for part in re.split(r"[.!?]", text) if part.strip()]
    questions = len(re.findall(r"[^.!?]*\?", text))
    return max(0, len(parts) - questions)


def _cold_phrases(text: str) -> tuple[str, ...]:
    """The person-directed wording in ``text``, if any."""
    lowered = text.lower()
    found = [phrase for phrase in COLD_PHRASES if phrase in lowered]
    for sentence in re.split(r"[.!?]", lowered):
        if "you" in sentence or "your" in sentence:
            found.extend(adj for adj in COLD_ADJECTIVES if adj in sentence)
    return tuple(dict.fromkeys(found))


def load_persona(roster: Path, friend: str) -> Persona:
    """The persona for ``friend`` from the committed roster.

    The roster is a JSON array (``examples/bots.example.json``), not JSONL like the world datasets --
    two formats, one project, and this is the place that knows which is which.
    """
    records = json.loads(roster.read_text(encoding="utf-8"))
    for record in records:
        if record.get("id") == friend:
            persona = record.get("persona")
            if persona is None:
                raise PersonaError(f"{friend} has no persona")
            return Persona.from_record(persona, where=f"{roster}: {friend}")
    raise PersonaError(f"no bot called {friend!r} in {roster}")


def phrasebooks(directory: Path) -> dict[str, Phrasebook]:
    """Every phrasebook in the world directory, by job name."""
    books = {}
    for path in sorted((directory / "phrasebooks").glob("*.json")):
        book = load_book(path)
        books[book.job] = book
    return books


def _all_variants(book: Phrasebook) -> list[str]:
    return [line for family in book.families.values() for line in family.variants]


def measure(
    friend: str = "friend-a",
    *,
    data: Path | str = Path("examples/friends_world"),
    roster: Path | str = Path("examples/bots.example.json"),
) -> PersonaReport:
    """Check the material against the brief, and report the numbers behind each verdict."""
    where = Path(data)
    persona = load_persona(Path(roster), friend)
    books = phrasebooks(where)
    # Through the world loader, not the raw file: the items it returns carry `spoken`, which is what
    # "what he actually says" means for a subject line with an anchor and a separate reply.
    knowledge = list(load_world(where).knowledge)
    life: Life = load_lives(where / "life.json")[friend]

    subjects = [item for item in knowledge if any(tag.startswith("topic:") for tag in item.tags)]
    # Rendered with sample values: a template is not a sentence until its placeholders are filled.
    # The job travels with the line, because the register rules differ by job -- a story is allowed to
    # explain itself and land, and a hook is allowed a second sentence because it carries news.
    variants = [
        (job, sample_render(line)) for job, book in books.items() for line in _all_variants(book)
    ]
    social_lines = [line for job, line in variants if job in SOCIAL_JOBS]
    spoken_lines = [item.spoken for item in subjects]
    report = PersonaReport(friend=persona.name)

    # 1. Can he hold up his end of each interest?
    counted = {topic: sum(1 for item in subjects if topic in item.tags) for topic in persona.topics}
    thin = [
        f"{topic} has {count}"
        for topic, count in sorted(counted.items())
        if count < MIN_ITEMS_PER_TOPIC
    ]
    report.findings.append(
        Finding(
            "coverage",
            f"every interest has {MIN_ITEMS_PER_TOPIC}+ things to say",
            ok=not thin,
            evidence=tuple(thin),
        )
    )

    # 2. A subject line without a reply gets its own anchor spoken aloud, which is how the old lore
    #    entries read as an essay about him rather than a man talking.
    silent = [item.id for item in subjects if not item.reply]
    report.findings.append(
        Finding(
            "subjects_have_replies",
            "every subject says something in his own voice",
            ok=not silent,
            evidence=tuple(silent),
        )
    )

    # 5a. Every anchor has to name its own subject. The name is the gate -- `decide/subject` has no
    #     distance ceiling -- so an item whose own anchor names nothing is unreachable, however good
    #     its reply is. Measured live: "do you fish?" and "tell me about rome" both answered nothing,
    #     because the vocabulary held "fishing" and "Roman history" but not "fish" or "rome".
    unnamed = []
    for item in subjects:
        found = subject.choose(
            text=item.text,
            index=EntityIndex(knowledge),
            knowledge=knowledge,
            character=None,
        )
        if found is None or not (found.tag in item.tags):
            unnamed.append(f"{item.id}: {item.text[:40]}")
    report.findings.append(
        Finding(
            "anchors_name_their_subject",
            "every question finds its own subject",
            ok=not unnamed,
            evidence=tuple(unnamed),
        )
    )

    # 5b. The contract between content and the budget. A subject answer goes through `decide/length`,
    #    which gives substance twelve words; `render/trim` can drop a *second* sentence but never part
    #    of the first. So a stance whose opening sentence is longer than twelve words makes the stage
    #    go silent -- measured, when eight freshly written stances were one long sentence each and
    #    "do you like hockey?" stopped answering at all.
    over_budget = [
        f"{item.id}: {_first_sentence(item.spoken)[:52]} ({_words(_first_sentence(item.spoken))} words)"
        for item in subjects
        if _words(_first_sentence(item.spoken)) > CONTENT_FLOOR
    ]
    report.findings.append(
        Finding(
            "fits_the_budget",
            f"every stance opens inside {CONTENT_FLOOR} words",
            ok=not over_budget,
            evidence=tuple(over_budget),
        )
    )

    # 3. The register: no trailing beat, no unexplained biography, no fortune cookie.
    unfit = [
        f"{item.id}: {', '.join(persona_fit.read(item.spoken).reasons)}"
        for item in subjects
        if not persona_fit.read(item.spoken).ok
    ] + [
        f"phrasebook: {line[:40]}: {', '.join(persona_fit.read(line, story=job == 'tell_story').reasons)}"
        for job, line in variants
        if not persona_fit.read(line, story=job == "tell_story").ok
    ]
    report.findings.append(
        Finding(
            "register",
            "nothing lands on a beat or explains itself",
            ok=not unfit,
            evidence=tuple(unfit),
        )
    )

    # 4. Length. A text message is short; a paragraph is a forum post.
    every_line = spoken_lines + [line for _, line in variants]
    words = sorted(_words(line) for line in every_line)
    median = statistics.median(words) if words else 0.0
    long_ones = [
        f"{line[:44]}... ({_words(line)} words)"
        for line in every_line
        if _words(line) > MAX_WORDS
    ]
    report.findings.append(
        Finding(
            "length",
            f"median under {MAX_MEDIAN_WORDS:g} words, nothing over {MAX_WORDS}",
            ok=median <= MAX_MEDIAN_WORDS and not long_ones,
            evidence=tuple(long_ones) or (f"median is {median:g} words",),
        )
    )

    # 5. Two *declarative* sentences is the ceiling for a social line. A greeting with a question
    #    after it ("morning. how is the fence?") is one of the good patterns, not a paragraph, so the
    #    rule is about statements that stack up -- which is what the old corpus did 51% of the time.
    two_sentence = [
        f"{line[:44]} ({_declaratives(line)} statements)"
        for line in social_lines
        if _declaratives(line) >= 2 and _words(line) > 10
    ]
    report.findings.append(
        Finding(
            "short_form",
            "social lines do not stack up statements",
            ok=not two_sentence,
            evidence=tuple(two_sentence),
        )
    )

    # 6. Nothing cold to the person he is answering. The phrases are person-directed on purpose:
    #    "boring" aimed at a piece of hardware is advice, and aimed at the reader it is contempt.
    cold = [
        f"{line[:44]}: {phrase}"
        for line in every_line + [story.body for story in life.stories]
        for phrase in _cold_phrases(line)
    ]
    report.findings.append(
        Finding("warmth", "no line is cold to the human", ok=not cold, evidence=tuple(cold))
    )

    # 7. A catchphrase nobody says is a lie in a config file.
    said = " ".join(every_line)
    missing = [line for line in persona.signature if line not in said]
    report.findings.append(
        Finding(
            "signatures",
            "every catchphrase is really in his mouth",
            ok=not missing,
            evidence=tuple(missing),
        )
    )

    # 8. Repetition *within a family* is a data error -- it means one of the two lines can never be
    #    chosen twice in a row and nobody would notice. The same line in two different families is
    #    fine: a dry register for a stranger and a casual one for a friend may both say "sure".
    duplicated = sorted(
        {
            f"{job}/{family.name}: {line[:36]}"
            for job, book in books.items()
            for family in book.families.values()
            for line in family.variants
            if family.variants.count(line) > 1
        }
    )
    report.findings.append(
        Finding(
            "distinct_lines",
            "no phrasebook repeats itself",
            ok=not duplicated,
            evidence=tuple(duplicated),
        )
    )

    # 9. Depth, so the life cannot run dry.
    depth = (
        f"stories {len(life.stories)}/{MIN_STORIES}",
        f"plans {len(life.plans)}/{MIN_PLANS}",
        f"grievances {len(life.grievances)}/{MIN_GRIEVANCES}",
        f"activities {len(life.activities)}/{MIN_ACTIVITIES}",
    )
    report.findings.append(
        Finding(
            "life_depth",
            "his day has enough in it to keep talking",
            ok=(
                len(life.stories) >= MIN_STORIES
                and len(life.plans) >= MIN_PLANS
                and len(life.grievances) >= MIN_GRIEVANCES
                and len(life.activities) >= MIN_ACTIVITIES
            ),
            evidence=depth,
        )
    )

    # 10. A story without a point is a fact with extra steps.
    pointless = [story.id for story in life.stories if not story.point.strip()]
    report.findings.append(
        Finding(
            "stories_land",
            "every story has a point to arrive at",
            ok=not pointless,
            evidence=tuple(pointless),
        )
    )

    report.stats = {
        "subjects": float(len(subjects)),
        "lines": float(len(variants)),
        "median_words": median,
        "two_sentence_pct": float(
            sum(1 for line in social_lines if _sentences(line) >= 2) / len(social_lines) * 100
            if social_lines
            else 0
        ),
        "distinct_pct": float(len(set(every_line)) / len(every_line) * 100 if every_line else 0),
    }
    return report

