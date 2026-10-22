"""The command guide, grouped by what you are trying to do.

Kept as data rather than a hand-written embed so it cannot drift: a test asserts every
registered command appears here, so adding a command without documenting it fails the suite.

The grouping is by *task*, not alphabetically, because a player mid-build is looking for
"how do I answer the next question", not for the letter A.
"""

from __future__ import annotations

from ttrpg_chatbots.sheets.render import EmbedField, EmbedSpec

# Each entry: the command, then the one-line explanation.
GROUPS: tuple[tuple[str, tuple[tuple[str, str], ...]], ...] = (
    (
        "Start here",
        (
            ("create", "start a character — opens a private thread here with the panels"),
            ("claim", "bind yourself to a character that nobody is playing"),
            ("characters", "your characters; /play switches which one is active"),
            ("play", "make one of your characters the active one"),
            ("discard", "throw away a draft you do not want (types the name to confirm)"),
            ("help", "this guide, here or privately in a channel"),
            ("testthread", "[temporary] probe: can a private thread host a build?"),
        ),
    ),
    (
        "The interview",
        (
            ("answer", "answer or rewrite one question: /answer number:3 text:…"),
            ("skip", "mark a question as deliberately unanswered"),
            ("goto", "read one question and jump the panel to it"),
            ("page", "move between questionnaire pages"),
            ("panel", "re-post the two panels in this thread if you deleted them"),
            ("fill", "import answers from a text file — matched by question text"),
        ),
    ),
    (
        "The mechanics",
        (
            ("spend", "raise a trait; spends the creation budget first, then freebies"),
            ("budget", "choose which group gets 7/5/3 and 13/9/5"),
            ("edit", "set any trait directly, free, inside its cap"),
            ("ability", "add a Talent, Skill or Knowledge"),
            ("background", "add a Background"),
            ("remove", "remove an ability or background"),
            ("specialty", "name or clear an ability's specialty (rank 4+)"),
            ("pool", "set freebie or xp balance, for imported characters"),
        ),
    ),
    (
        "Merits, flaws, gifts",
        (
            ("merit", "take a Merit; priced by the book, or name your own points"),
            ("unmerit", "drop a Merit and refund it"),
            ("flaw", "take a Flaw; it pays freebie points and comes before them"),
            ("lookup", "what does a Merit or Flaw cost in the books?"),
            ("gift", "record an awarded Gift — Gifts are earned, never bought"),
            ("ungift", "remove a Gift"),
            ("mission", "record a Game: a win pays 10 xp and a Gift, a loss 5 xp"),
        ),
    ),
    (
        "Read it back",
        (
            ("sheet", "your character sheet"),
            ("options", "what the next point costs, and what is capped"),
            ("build", "what creation budgets are still unspent"),
            ("history", "what has happened to the character, newest last"),
        ),
    ),
    (
        "Play",
        (
            ("roll", "dice, or a check rolled from your sheet: /roll check:stealth"),
            ("willpower", "spend Willpower without rolling"),
            ("hurt", "walk down the health track"),
            ("heal", "walk back up it"),
            ("undo", "reverse your last sheet edit"),
        ),
    ),
    (
        "Finish and files",
        (
            ("finish", "check the build and seal the character"),
            ("done", "seal once the interview is complete"),
            ("unlock", "reopen a sealed character for a Revision"),
            ("export", "download the character: json, or a questionnaire to fill in"),
            ("import", "replace the character from an exported .json"),
        ),
    ),
    (
        "Table and voice",
        (
            ("ask", "ask a character a question; /ask speak:true to hear it"),
            ("say", "speak text in a character's voice"),
            ("join", "join your voice channel"),
            ("leave", "leave it"),
            ("stop", "stop speaking"),
            ("voices", "which voice each character uses"),
            ("friendcheck", "are the friends online, can they send, and what did they last hear?"),
            ("memory", "what the friends remember about you, and what they have brought up"),
            ("forget", "make a friend forget one thing you told it"),
            ("botcheck", "what this bot is not allowed to do, and how to fix it"),
            ("ping", "is the bot awake?"),
        ),
    ),
)

TITLE = "Building a character"
FOOTER = "a build is not final until /finish · /help any time"

def help_text() -> str:
    """Plain-text version, for tests and for anywhere an embed will not fit."""
    lines = [TITLE, ""]
    for title, commands in GROUPS:
        lines.append(f"{title}:")
        lines.extend(f"  /{name} — {text}" for name, text in commands)
        lines.append("")
    return "\n".join(lines).rstrip()


def documented() -> tuple[str, ...]:
    """Every command name this guide mentions."""
    return tuple(name for _, commands in GROUPS for name, _ in commands)


def help_spec() -> EmbedSpec:
    """The guide as an embed: one field per group, so it reads as a menu."""
    fields = []
    for title, commands in GROUPS:
        # Discord caps a field at 1024 characters; each group is well inside that, and a
        # group that ever grows past it is clipped rather than rejected.
        body = "\n".join(f"**/{name}** — {text}" for name, text in commands)
        fields.append(EmbedField(title, body[:1020] + ("…" if len(body) > 1020 else "")))
    return EmbedSpec(
        title=TITLE,
        description=(
            "Everything lives in this thread: two panels that update as you work — the "
            "questionnaire and the sheet. Nothing is final until `/finish`."
        ),
        fields=tuple(fields),
        footer=FOOTER,
    )
