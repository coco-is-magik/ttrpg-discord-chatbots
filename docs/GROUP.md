# The group: three friends, one table

The sheet portal answers *"what am I?"*. It is v1-complete and closed. This document is the
other half: **the people**. Three bots who are in the group *and* play characters at the
table, in a private server with one human.

**This document is a contract, not a description of code that exists.** Four modules are
specified here — `memory/`, `social/`, `ambient/`, `table/` — plus the surgical changes to
code that already exists. Nothing below is built yet. Where a decision could go two ways, the
reasoning is written down so it can be argued with rather than rediscovered.

**Status:** the *identity* half is built. `bots/` holds the roster, the supervisor and the
permission audit, so four applications can run together and each says out loud what Discord is
refusing. `memory/`, `social/`, `ambient/` and `table/` are still contracts.

Companions: [`DESIGN.md`](DESIGN.md) (why this project exists), [`SHEET_UI.md`](SHEET_UI.md)
(the other surface), [`CREATION.md`](CREATION.md) (how a character comes to exist).

---

## 1. What is already here, and what is not

The substrate is in better shape than the roadmap assumes. What is missing is not a model or
a voice; it is **a reason to speak, a memory to speak from, and a rule for who speaks first**.

| Piece | State | What it gives the group |
|---|---|---|
| `respond.py` — `Responder`, `Answer` | **exists** | every bot is a responder with provenance; a degraded answer is labelled |
| `conversation.py` | **exists** | dice → model → classifier, plus voice; no front end |
| `reply/` classifier | **exists** | grounded, tag-gated, says "I don't know" by construction, free |
| `llm/` | **exists** | three backends, tool calls, bounded prompts, fallback |
| `seats/` | **exists** | bot seats with a display name and `voices {ic, ooc}` — unused so far |
| `bots/` | **exists** | the roster (helper + three friends), the supervisor, and the permission audit |
| `tts/`, `voice/` | **exists** | per-character voice; a queue that can be cleared mid-sentence |
| `dice/`, `sheetportal/` | **exists** | priced rolls and sheet reads the group may *use*, never mutate |
| **hearing the channel** | **missing** | the helper is commands-only by design; friends will request Message Content, but no listener exists yet |
| **memory** | **missing** | no `memory/`; `LlmResponder` takes a frozen `history` tuple |
| **initiative** | **missing** | no scheduler, no cadence, no quiet hours |
| **arbitration** | **missing** | nothing decides who answers, or who stays quiet |
| **scene** | **missing** | no table state, floor control or GM rotation |
| **personality** | **4 strings** | `Persona(name, role, traits, style)` (`llm/types.py:110`) |
| **IC / OOC** | **missing** | every answer is the character answering; the person never speaks |
| **per-seat model or budget** | **missing** | `LlmConfig` is process-wide; no token accounting |

The four modules below are all new, and each is deliberately small. The social behaviour lives
in data and pure functions, not in prompt wording, because prompt wording cannot be tested for
"never speaks twice in ten minutes".

---

## 2. The missing type: a line of conversation

Everything in this half needs to answer a question the code cannot answer today:
**who just spoke — the person or the character?**

**Four applications, two roles.** `ttrpg-bot` is the *helper*: it owns slash commands, build
threads and the sheet portal, never reads ordinary messages, and holds no personality at all.
The three *friends* are separate applications with their own tokens; they own no commands and
exist to be people. A friend is a **slot** — a name, a seat, a voice, a token — because what
they are actually like has not been decided yet, and nothing in this design assumes an
organiser, a cynic or a caretaker. Personality is configuration to be written later, not
architecture to be guessed now.

They are different people. `Dennis` is in the group; `Sable` is who Dennis plays on game
night. They have different voices (`seats.voices["ooc"]` and `["ic"]`), different knowledge,
and different rules about what may be said. Today there is one persona path — "you are Sable,
answer in character" — which is right for `/ask` and wrong for everything else.

A new seam module, `utterance.py`, imports nothing from the project. That is the same rule
`respond.py` follows, so `memory`, `social`, `ambient` and `table` can all use it without
importing each other:

```python
KIND_IC, KIND_OOC = "ic", "ooc"
MODE_AMBIENT, MODE_TABLE = "ambient", "table"

@dataclass(frozen=True)
class Line:
    """One thing said, by one seat, in one mode."""
    at: str          # ISO-8601 UTC, seconds: the same shape as creation.now_utc()
    channel: str     # Discord channel id as a string; this module never imports discord
    speaker: str     # a seat id ("truman", "dennis") -- a person, not a character
    text: str
    kind: str = KIND_OOC
    mode: str = MODE_AMBIENT
    source: str = ""     # "human" | "llm:openai" | "reply:classifier"
    reply_to: str = ""   # the message id this answers, or ""
```

Why a seat rather than a character id: the seat is the only id that already means *a
participant*. `seats.json` bridges the two namespaces (`character` for the sheet,
`world_character` for the reply engine), and the group is the first surface that needs both at
once — OOC as the person, IC as the character.

What one evening looks like once this exists:

```text
21:41  Truman  anyone around tonight?
21:41  Dennis  I'll be on around eight — work thing first.          <- ooc, Dennis' voice
21:42  Truman  /ask character:sable what's in the north wing?
21:42  Sable   Cold storage, and a door that should be locked.      <- ic, Sable's voice
```

Same bot account, same channel, two different people. The name prefix is the attribution the
group already uses; the voice is what makes it feel like two.

**The prompt is not shared between them.** OOC knows it is a person in a Discord group, knows
the human's boundaries, and knows *nothing* from the character's knowledge tags. IC knows the
character's world and nothing about the human's real life. That separation is a tested
invariant (§9), not a paragraph in a prompt.

---

## 3. `memory/` — what a friend remembers

Three stores and one ledger. Every one is bounded, inspectable, and deleted on a timer or by
command. Nothing here is telemetry.

| Store | Lifetime | Bound | What it holds |
|---|---|---|---|
| `Window` | one conversation, in process | 50 lines per channel | what was just said, so replies connect |
| `FactBook` | months | 100 facts per seat | curated truths: names, job, preferences, promises |
| `Episodes` | forever, append-only | one per session | what happened, in a few lines — no prose invention |
| `Canon` | forever, append-only | one per ruling | what the GM decided, with who and when |

```python
class Window:
    """The last N lines. Volatile on purpose: a transcript is not a friendship."""
    def __init__(self, limit: int = 50) -> None: ...
    def add(self, line: Line) -> None: ...
    def lines(self) -> tuple[Line, ...]: ...
    def since(self, at: str) -> tuple[Line, ...]: ...

@dataclass(frozen=True)
class Fact:
    id: str
    text: str
    source: str           # "human" | "interview" | "ruling" | "sheet"
    added: str
    tags: tuple[str, ...] = ()
    pinned: bool = False

class FactBook:
    def add(self, fact: Fact) -> FactBook: ...       # duplicate text is refused, not merged
    def remove(self, fact_id: str) -> FactBook: ...
    def search(self, query: str, *, limit: int = 8) -> tuple[Fact, ...]: ...
```

**Where a fact comes from is part of the fact.** Only three sources may write one: the human
(`/remember`), the character's own interview and sheet, and an accepted ruling. A model's
output is never a source — a bot that can write its own memory can slowly invent a history and
then be sincere about it. `Fact.source` is displayed by `/memory`, so "why do you think that?"
has an answer.

**Eviction is explicit, not silent.** At 100 facts, `add` removes the oldest unpinned fact and
logs it; loading a file with more than the cap is an error, because a cap that quietly drops
data is worse than a loud one. `pinned` facts are never evicted.

**Search is keywords, not embeddings** — no new dependency, explainable, testable. Embeddings
can arrive later behind the same `search()` signature and nothing upstream changes. Relevance
is the same idea the classifier already uses: match the words the question actually contains.

**Episodes are extractive.** A session closes with its topics, its lines, and the facts added
during it. A configured model may add a prose summary tagged `source="llm"`; that summary is
never used as a fact and never becomes canon. The distinction matters: a summary is a
*reminder*, a fact is a *claim*.

Storage lives under `data/memory/` — git-ignored, `0600`, written atomically with the same
mkstemp + `os.replace` pattern `seats/registry.py` uses, because a half-written memory is a
bot with a head injury:

```text
data/memory/
  facts/<seat>.jsonl      # one fact per line, hand-editable, # comments allowed
  episodes/<seat>.jsonl   # one session per line
  canon.jsonl             # rulings, world-wide
```

Two commands make it honest, and both ship before the module counts as done:
`/memory [seat]` prints exactly what a bot knows and where each fact came from;
`/forget fact:<id>` deletes one, and `/forget all` empties a seat's fact file.

**Failure modes.** A corrupt fact file is a loud `MemoryStoreError` naming `path:line`, never a
silently empty memory — an empty memory makes a bot deny knowing a friend, which is worse than
a bot that refuses to start. A missing file is an empty store, exactly like `load_seats`.
A fact file at the cap is not an error; only *loading* an over-cap file is.

---

## 4. `social/` — who speaks, and when silence is kinder

This module exists because the roadmap put `social/` in the architecture table and then never
gave it a phase. It is not a nicety: *inclusion is not attention* and *wanted, never required*
are social policies, and a policy that lives only in prompt wording is a policy that cannot be
tested or overridden.

Four pieces, all pure:

```python
@dataclass(frozen=True)
class Boundaries:
    """Asked once, remembered as data, never inferred."""
    nickname: str = ""                       # what the human wants to be called
    pronouns: str = ""
    teasing: str = "none"                    # "none" | "gentle" | "sharp"
    topics_off_limits: tuple[str, ...] = ()

class InclusionPolicy:
    """May this seat add a line right now, or is silence the kind answer?"""
    def may_answer(self, *, human_lines: int, bot_lines: int,
                   since_human_s: float, addressed: bool) -> bool: ...
    def may_initiate(self, *, room: Room, budget_ok: bool, ritual: bool) -> bool: ...

@dataclass(frozen=True)
class Deferral:
    """A promise with a time on it. A deferral without a due time is not allowed."""
    seat: str
    due: str          # ISO-8601 UTC
    text: str         # what was promised: "I'll be on around eight"
    channel: str
    kept: bool = False

class PromiseBoard:
    def add(self, deferral: Deferral) -> PromiseBoard: ...   # validates that due is in the future
    def due(self, at: str) -> tuple[Deferral, ...]: ...
    def keep(self, deferral: Deferral) -> PromiseBoard: ...
```

**`InclusionPolicy.may_answer` is the anti-chorus rule.** One bot answers a human message per
window; the others may react or stay quiet. It takes counts and seconds, not prose, so the rule
is the same in every prompt and every test.

**`may_initiate` has two hard preconditions.** A bot may start a conversation only when the
budget allows it *and* either the room is warm (a human line in the last 30 minutes) or a
ritual/promise is due. A bot must never monologue into an empty room — that is the difference
between a group with a quiet afternoon and a machine talking to itself.

**`Deferral` is `DESIGN.md`'s "deferrals are allowed, refusals are not", as data.** "Back at
six" is a row with `due=18:00`; the scheduler fires it at 18:00 even if the room is cold, and
`keep()` records that it happened. A deferral whose time has passed and was never kept is a
logged warning, not a silent disappearance.

**Read the room, never narrate it.** `Room` is a small, decaying summary of *pacing*: how fast
people are replying and how long the messages are. It becomes one line in the prompt
("short replies, quick pace — keep it brief") and is never spoken aloud as an observation, and
never used to infer mood, health or anything about a person. `"I noticed you seem sad"` is the
uncanny-warmth failure this avoids; `"kept it to one line because the channel was busy"` is the
behaviour it buys.

```python
@dataclass(frozen=True)
class Room:
    pace: str = "steady"     # "quiet" | "steady" | "busy"
    note: str = ""           # one instruction for the prompt; never a claim about a person
```

**Boundaries are asked, not inferred.** `/onboarding` asks nickname, pronouns, teasing level and
off-limits topics once, writes `Boundaries` into the **human seat's** `meta["boundaries"]`, and
never asks again. Teasing defaults to `"none"` until the human says otherwise, because the safe
default is the polite one. No model may widen a boundary, and nothing infers one from behaviour.

**Tests.** Nobody answers twice in a window; a cold room suppresses initiative but not a due
promise; `Deferral` refuses a past due time; boundaries are immutable from the model's side.

---

## 5. `ambient/` — a rhythm, not a timer

Ambient chat is the hardest thing here to get right, and the easiest to make insufferable. The
design rule that keeps it honest: **the scheduler decides *who wants to speak*, and never
speaks.** It returns intents. The Discord layer turns an intent into a message. That split is
what makes "never more than one bot per ten minutes" a test instead of a hope.

```python
class Clock(Protocol):
    def now(self) -> datetime: ...          # aware, UTC; ManualClock in tests

class Cadence:
    """Base gap between a bot's own attempts, with a heavy tail."""
    def next_gap(self, rng: RandomSource) -> timedelta: ...

@dataclass(frozen=True)
class QuietHours:
    start: time                              # 23:00
    end: time                                # 08:00
    tz: str                                  # a zoneinfo key; required, never guessed

class Budget:
    """Hard caps. When it is spent, the answer is silence, not an error."""
    def allow(self, at: datetime) -> bool: ...
    def spend(self, tokens: int, at: datetime) -> None: ...
    def state(self, at: datetime) -> BudgetState: ...

@dataclass(frozen=True)
class Intent:
    seat: str
    channel: str
    at: str
    reason: str        # "answer" | "cadence" | "promise" | "arrival" | "ritual"
    topic: str = ""
    kind: str = KIND_OOC

class Ambient:
    def __init__(self, *, seats, clock, cadence, quiet, budget,
                 topics: TopicBoard, promises: PromiseBoard, rng) -> None: ...
    def tick(self, room: Room) -> tuple[Intent, ...]: ...
```

**Why heavy-tailed and not uniform.** A uniform 4–9 minutes is a metronome and reads as one
within an hour. A lognormal around 6–7 minutes with a long tail produces the real pattern:
a burst of three lines, then twenty quiet minutes. `Cadence` takes an injected `RandomSource`,
the same protocol `dice/roller.py` already defines, so a test can pin the sequence.

**The cadence in `DESIGN.md` is a single-bot number.** Phase 3 tests one bot at 4–9 minutes.
Once three bots exist, per-bot cadence must scale with the seat count and the **group budget is
the binding constraint** — otherwise three independent 6-minute clocks produce twenty-odd
messages an hour and the chorus problem is back. The numbers, as starting defaults and as
configuration rather than constants:

| Knob | One friend (3a–3b) | Three friends (phase 4) |
|---|---|---|
| Per-bot gap | median 6.5 min, heavy tail | median ≈ 18 min (base × 3) |
| Group messages | — | 1 per 10 min (hard) |
| Daily token ceiling | 60k | 200k |
| Quiet hours | 23:00–08:00 | staggered per seat, 30–60 min apart |
| Warm-room window | 30 min since a human line | 30 min |

**Quiet hours use `zoneinfo`, not arithmetic on UTC offsets.** DST is real, the human is in one
place, and subtracting hours from UTC gets this wrong twice a year. A staggered schedule is a
phase-4 decision (see §13) but the type supports it from day one.

**Budget is a wall, not a warning.** `allow()` is consulted before generating text, not after,
so an exhausted budget costs nothing and says nothing. Overspending is impossible by
construction: `spend()` after the fact only records. A budget that raises would make the bot
noisy about being quiet, which is the opposite of the point.

**Rituals are scheduled intents with a due time**: the game-night poll, arrivals at T−30 with
jitter, and the debrief after a session. They are the one thing allowed to speak into a cold
room, because a ritual is a *duty*, not an initiative.

**`tick()` is pure enough to run a week in a test.** It reads the clock, the room and the
budget; it returns at most one intent per seat per window; it never calls Discord, never
sleeps, and never generates text. The production driver is a thin `discord.ext.tasks` loop that
calls `tick()` once a minute — the only part of this module that is not testable offline, and
therefore the only part with no logic in it.

---

## 6. `table/` — the game, with a rotating GM

Table mode is the ambient engine with three differences: the room has a **scene**, the right to
speak has an **order**, and one seat is the **GM**.

```python
@dataclass(frozen=True)
class SceneState:
    id: str
    place: str
    present: tuple[str, ...]        # character ids: who is in the room in the fiction
    stakes: str
    turn: str                       # the character whose turn it is
    open_questions: tuple[str, ...]
    started: str

@dataclass(frozen=True)
class Session:
    id: str
    index: int                      # the nth session; the GM is seats[index % 4]
    gm: str                         # seat id
    started: str
    closed: str = ""

class Floor:
    """Who may speak now, in a scene."""
    def offer(self, line: Line, *, scene: SceneState, gm: str) -> Decision: ...
    # Decision: "speak" | "wait" | "queue" | "drop"
```

**Priority is fixed and published**: GM > a line addressed to you > IC > OOC. A lower
priority does not queue indefinitely — `Floor` applies a cooldown per seat and a staleness TTL,
so a queued line that is no longer relevant is dropped rather than delivered late. A late reply
is worse than no reply, in a game about people talking.

Two id spaces meet here, and the split is deliberate: `SceneState` names **characters** (who is
in the room in the fiction), while `Floor` answers in **seats** (who may type right now).
`SeatBook.for_character` already bridges them, which is why the scene never needs to know a
Discord id.

**The GM rotates by arithmetic, not negotiation**: `seats[session.index % len(seats)]`. That is
the structural answer to "the human must feel needed" — when it is their session, three players
need their rulings. No seat can be GM twice in a row while another has waited.

**Rulings become canon, with provenance.** When a GM settles something ("flaws cap is 7 unless
two flaws total anything"), the ruling is appended to `memory/canon.jsonl` with who ruled and in
which session. Two ways in: the human types `/rule text:…`, or the GM seat calls a
`record_ruling` tool. That tool is legitimate where a sheet mutation is not, because a ruling
is *the GM's authority recorded*, not a mechanical change; the portal still prices every roll,
and no rule text can move a dot on a sheet.

**Sheets are read-only inputs here.** A character in table mode may read its own numbers for a
check; `dice/` prices the roll from the sheet. An LLM may propose a roll, never a spend — the
invariant that already holds for `/ask` holds in a scene.

**Voice is phase 6, and text barge-in comes first.** In text, a human line cancels whatever a
bot had queued (the same `VoicePlayer.clear()` idea, one layer up). In voice, barge-in needs
speech-to-text from Discord, which is a separate and much larger problem; until then, bots do
not listen in voice and say so.

**The session is the unit of memory.** Opening a session starts a `Window`; closing it writes an
`Episode` and moves the scene's unresolved questions into the next scene's prompt. Nothing else
survives a session, which is what keeps table state small and canon honest.

---

## 7. The changes to code that already exists

Four new modules and two seam files are not a feature by themselves. Seven small changes make
the existing layers usable by them, and one of them fixes a real inefficiency in the current
`/ask` path.

**7.1 The listener the friends need.** The helper never reads messages: its intents stay
`discord.Intents.default()`, and a test asserts it, because a commands-only bot that quietly
started listening would be a permission nobody asked for. The listener belongs to each
**friend**, gated by `listen` in its roster entry (8.1). With it off, the application connects
and does nothing; with it on, it requests **Message Content**, which must be enabled for that
application in the Developer Portal or Discord closes the connection with 4014 — and the
supervisor names that failure instead of retrying forever.

When the listener arrives it does four things in order: ignore itself and other bots, ignore
channels not in its roster entry, record the line in the `Window`, and hand it to the arbiter.
It never generates a reply inline; it asks `Ambient`/`Floor` first. The helper's code path is
untouched, and its command sync does not change.

**7.2 Per-turn history in `llm/`.** `LlmResponder` already takes `context_for(prompt)`; add the
same hook for turns:

```python
history_for: Callable[[str], Sequence[ChatMessage]] | None = None
```

`memory/` supplies the window; `llm/` stays ignorant of `memory/`. Without this, every reply is
an amnesiac's reply, which is exactly what `/ask` does today and exactly what the group cannot.

**7.3 Cache the responder — and stop rebuilding the backend per call.** `Conversation._answers`
caches classifiers in `_responders` but constructs a **new** `LlmResponder` on every call when
`use_llm` is on (`conversation.py:116`), and with it a new backend, a new `Roller()` and a
fresh `load_checks()` read. One `/ask` is fine; twenty ambient replies an hour means twenty
connections and twenty file reads. The group path needs the LLM responder cached per
`(seat, kind, profile)`, keyed the way `_responders` already is. This is a small fix with an
outsized effect on cost and latency, and it is a prerequisite, not a nicety.

**7.4 `conversation.py` grows `respond_as`.** The composition root assembles one answer:

```python
def respond_as(self, seat: Seat, line: Line, *, profile: BotProfile,
               boundaries: Boundaries, room: Room,
               facts: Sequence[Fact], window: Sequence[Line]) -> Answer: ...
```

It picks the persona (OOC: the person; IC: the character), selects the voice from
`seat.voices[kind]`, builds the prompt with the bounded fact/context limits that already exist,
and passes the dice toolbox so a roll in conversation is a real roll. Everything it needs is
plain data, and the dependency arrows only ever point inward: `conversation.py` may import the
`cast` and `utterance` types, and it never imports `memory`, `social` or `ambient`; those never
import it. The bot — the only place that knows about all of them — does the wiring.

**7.5 `BotProfile`, compiled to the existing `Persona`.** `llm/types.Persona` stays four
strings, so the LLM layer keeps no opinion about people. `BotProfile` lives in a small new
top-level module, `cast.py`, and flattens to `Persona`:

```python
@dataclass(frozen=True)
class BotProfile:
    seat: str
    name: str                      # "Dennis" -- the person, not the character
    role: str = ""                 # free text; blank until a personality is chosen
    humour: str = ""               # free text; blank for now
    verbosity: str = "short"       # "clipped" | "short" | "chatty"
    interjection_rate: float = 0.5 # 0..1, how often it takes an opening
    question_rate: float = 0.2     # 0..1, how often it asks rather than tells
    topics: Mapping[str, float] = field(default_factory=dict)
    quiet: str = ""                # "23:30-08:00", "" means the group default
    tz: str = ""                   # required when quiet is set
    model: str = ""                # per-seat backend override, "" means the global one
```

Every field is optional and the defaults are neutral. This is a **slot**, not a character: the
three friends have names and tokens, and what they are like is a writing decision that has not
been made. Nothing in the code may assume a role — "the organiser reminds you", "the cynic
teases" — until that decision exists in data.

It is read from `seat.meta["persona"]`, because `seats/types.py` already preserves unknown keys
inside `meta` and round-trips them (`types.py:175`). One file stays the source of truth for who
exists; a separate `cast.json` was the alternative and lost, because two files keyed by seat id
drift the first time a seat is renamed. Validation is loud: an unknown `verbosity`, a
`quiet` without a `tz`, or an interjection rate outside 0..1 is a `CastError` on load, not a
defaulted surprise at 2 a.m.

**7.6 A per-seat model, from the same config loader.** `load_llm_config()` gains an optional
seat override so ambient can run on a cheap local model while table mode uses the good one. The
seat names a *profile* (`"cheap"`, `"table"`), never a raw model id, so a model can be swapped
in one place. Global behaviour is unchanged when no override exists.

**7.7 One log line per turn, and no metrics.** After every generated line:
`seat · kind · mode · model · tokens in/out · latency · source · degraded`. That is cost and
health, and it is what makes the budget auditable. It is deliberately *not* engagement
analytics — no counts of the human's messages, no streaks, nothing that could become a target.

Also new commands, all thin: `/quiet`, `/on` / `/off`, `/remember`, `/forget`, `/memory`,
`/onboarding`, `/rule`. `help.py` gains a "The group" section, and its coverage test fails until
each one is documented.

---

## 8. Data, configuration, and the four applications

One committed example of each file, everything real git-ignored — the same rule as `seats.json`
and `data/characters/`.

### 8.1 The roster (`bots.json`)

Four applications, listed once, in `data/bots.json` (copy
[`examples/bots.example.json`](../examples/bots.example.json)). A missing file means "just the
helper", so an installation that never adds friends behaves exactly as it did before.

```json
[
  { "id": "ttrpg-bot", "role": "helper", "commands": true,
    "token_env": "DISCORD_TOKEN", "channels": [] },
  { "id": "friend-a", "role": "friend", "seat": "",
    "listen": false, "token_env": "TTRPG_FRIEND_A_TOKEN", "channels": [] }
]
```

- **`role`** — `helper` or `friend`, and the two are not interchangeable. The helper must own
  commands and may not listen; a friend may listen and may not own commands. Both are refused
  at load, not at 2 a.m.
- **`seat`** — which person a friend speaks for. Optional while the friends are still slots.
- **`listen`** — requests **Message Content** for this application. Off until the intent is
  enabled in the Developer Portal, because requesting an ungranted intent makes Discord refuse
  the connection (close code 4014).
- **`channels`** — where this bot is expected to work. These are what the permission audit
  checks; empty means "nothing to check yet", which is logged rather than guessed.
- **`user_id`** — optional; when present, the helper can audit that friend's channel
  permissions too (see 8.3).

### 8.2 Tokens, and "dormant"

Each bot reads its own token, in the same precedence `config.py` uses for the helper:
`<VAR>_FILE`, then `<VAR>`, then nothing. A bot with no token is **dormant**: reported by
`--check`, logged at startup, and simply not started. Dormant is how the three friends are
committed as configuration today and born later when their applications exist.

```text
$ ttrpg-chatbots-bot --check
bots:
  ttrpg-bot (helper) — token set
  friend-a (friend) — dormant (no TTRPG_FRIEND_A_TOKEN)
```

### 8.3 What each role is allowed to do

The audit is role-specific because the failure modes differ: a helper missing *Create Private
Threads* cannot open a build thread, and a friend missing Message Content can connect perfectly
while hearing nothing.

| Role | Required in each configured channel | Also |
|---|---|---|
| helper | View Channel, Send Messages, Send Messages in Threads, Read Message History, Embed Links, Attach Files, **Create Private Threads**, **Manage Threads** | — |
| friend | View Channel, Send Messages, Send Messages in Threads, Read Message History, Embed Links, Add Reactions, Use External Emojis | **Message Content** intent, only when `listen` is on |

Voice (`Connect`, `Speak`) is added only when voice is enabled, because those permissions live
on voice channels and checking them against a text channel would report a false failure.

Every bot audits **itself** at login — only an application can see its own member object — and
the helper exposes `/botcheck` for its own audit plus any friend with a `user_id`. Failures are
logged as warnings that name the channel and the fix, and the *absence* of warnings is itself
logged once (`ttrpg-bot: 8/8 checks passed in #general`), so a silent log means "checked and
fine", not "never ran". Nothing here asserts a permission the code believes it has: the check
asks Discord, per channel, which is the only answer that accounts for overwrites.


### 8.4 The person's slot: personality is not decided yet

A friend is a seat with a persona *block*, and the block is deliberately empty of character.
The slots exist so the wiring can be finished; filling them in is a writing decision, made
later, and it changes no code.

```json
{
  "id": "dennis",
  "kind": "bot",
  "character": "robert-ross",
  "world_character": "sable",
  "voices": { "ic": "en_GB-alan-medium", "ooc": "en_US-amy-medium" },
  "meta": {
    "name": "Dennis",
    "persona": {
      "role": "",
      "humour": "",
      "verbosity": "short",
      "interjection_rate": 0.5,
      "question_rate": 0.2,
      "topics": {},
      "quiet": "00:00-08:30",
      "tz": "America/Toronto",
      "model": "cheap"
    }
  }
}
```

Empty strings are not placeholders for a personality we have in mind; they mean *nobody has
chosen one*. The neutral defaults are the polite ones: short messages, equal willingness to
speak, few questions, no topics weighted above others.

`examples/seats.example.json` already has the `voices` shape; it gains this `persona` block,
and the example becomes the documentation. New environment variables, all optional and all
defaulting to "off, exactly as today":

| Variable | Meaning |
|---|---|
| `TTRPG_BOTS_FILE` | the roster path; defaults to `data/bots.json` |
| `TTRPG_FRIEND_<X>_TOKEN` / `_FILE` | a friend's secret (or whatever its `token_env` names) |
| `TTRPG_MEMORY_DIR` | defaults to `data/memory` *(planned)* |
| `TTRPG_GROUP_BUDGET` | messages per 10 min and tokens per day, e.g. `1/200000` *(planned)* |
| `TTRPG_QUIET` | group-wide quiet hours when a seat names none *(planned)* |

Listener and channel scope are **per bot**, in `bots.json` (`listen`, `channels`), not global
environment flags: a friend that may speak in one channel should not inherit a server-wide
setting because someone edited `.env`.

---

## 9. Invariants, each with a test that fails when broken

These are the ones worth protecting. Every row becomes a named test in the suite, in the same
spirit as the existing sheet invariants.

| # | Invariant | Test |
|---|---|---|
| 1 | A bot never writes its own facts | `test_memory_refuses_model_source` |
| 2 | The window is bounded and evicts oldest-first | `test_window_cap_evicts` |
| 3 | An over-cap fact file fails loudly, with `path:line` | `test_fact_file_over_cap_raises` |
| 4 | One bot answers a human message per window | `test_anti_chorus_one_answer` |
| 5 | No initiative into a cold room, except a ritual or a promise | `test_cold_room_is_silent` |
| 6 | A deferral always comes due and is marked kept | `test_promise_kept_at_due_time` |
| 7 | A deferral cannot be created in the past | `test_deferral_rejects_past` |
| 8 | The budget is checked before generation and fails silent | `test_budget_exhaustion_is_silent` |
| 9 | OOC knows nothing from the IC knowledge tags (and vice versa) | `test_prompt_leakage_ic_ooc` |
| 10 | No LLM output mutates a sheet | `test_group_never_mutates_sheet` |
| 11 | IC and OOC pick different voices from the same seat | `test_voice_follows_kind` |
| 12 | GM rotates `index % seats` and never repeats early | `test_gm_rotation` |
| 13 | A lower-priority queued line goes stale rather than late | `test_floor_drops_stale` |
| 14 | A human line cancels queued bot output | `test_human_barge_in_text` |
| 15 | The listener ignores itself, other bots, and unlisted channels | `test_listener_gates` |
| 16 | A friend requests Message Content only when `listen` is on | `test_a_friend_requests_message_content_only_when_listening` |
| 17 | A model failure degrades to the classifier, never to silence | `test_fallback_keeps_answer` |
| 18 | Boundaries cannot be widened by a model | `test_boundaries_are_data_only` |
| 19 | The helper never requests a privileged intent | `test_bot_uses_no_privileged_intents` |
| 20 | A dormant friend does not stop the helper | `test_a_dormant_friend_is_not_started` |
| 21 | A missing permission names the channel and the fix | `test_one_missing_permission_names_the_fix` |
| 22 | One bot failing does not take the others down | `test_one_failing_bot_does_not_stop_the_other` |
| 23 | A friend with `listen` off is not nagged about the intent | `test_a_friend_that_is_not_listening_is_not_warned_about_message_content` |

Invariant 9 is the one most likely to rot, because it depends on two prompts staying separate
while sharing a persona builder. It gets a scripted scene, not a snapshot: the human asks OOC
"what's Sable hiding?" and IC "what did I tell you about my job?", and the assertions are about
what must *not* appear.

---

## 10. Slices, in the order they can actually be built

Each slice is independently useful and independently revertible, the same rule `DESIGN.md` sets
for its phases. Nothing later requires rewriting earlier work. **3a and 3b are the two halves of
`DESIGN.md` phase 3**; 4, 5 and 6 map to phases 4, 5 and 6 one for one.

### 3a — "It hears you" (one friend, reactive)
**Built already:** `bots/` — the roster, the supervisor, the permission audit and `/botcheck`.
That was the prerequisite: four applications that can run together, with three of them dormant
until their tokens exist, and every missing permission named instead of guessed.

**New:** `utterance.py`; `memory/` (`window.py`, `facts.py`, `store.py`); `cast.py` (the
`BotProfile` loader, ~80 lines).
**Changed:** `llm/responder.py` (`history_for`), `llm/prompt.py` (an OOC system prompt beside
the IC one), `conversation.py` (`respond_as` + the responder cache), `supervisor.py` (the
friend's `on_message` stops being a placeholder), `bot.py` (`/memory`, `/remember`, `/forget`),
`help.py`.

**Done when:** a mention in an allow-listed channel gets an answer grounded in the recent window
(twenty turns of the fifty kept) and the seat's facts; the leakage scene passes; a friend with
`listen` off never requests a privileged intent (a test asserts it); every turn logs one cost
line.

### 3b — "It has a rhythm" (one friend, initiative)
**New:** `social/` (`policy.py`, `boundaries.py`, `promises.py`, `room.py`); `ambient/`
(`clock.py`, `cadence.py`, `quiet.py`, `budget.py`, `topics.py`, `intents.py`).
**Changed:** `bot.py` (the `tasks.loop` driver, `/quiet`, `/on`, `/off`, `/onboarding`).

**Done when:** seven simulated days at fake-clock speed stay inside the budget, say nothing
during quiet hours, never speak into a cold room, and keep **every** promise. That is the
Phase 3 exit criterion from `DESIGN.md`, made measurable.

### 4 — "Three of them"
**Changed:** `ambient/` (group budget, arbitration, staggered quiet), `social/` (anti-chorus),
`cast.py` (three profiles), rituals (poll, arrivals, debrief).

**Done when:** a scripted 200-message day produces at most one bot answer per human message, no
two bots use the same phrasing, and a rubric-scored transcript reads as three people rather
than one person three times.

### 5 — "The table"
**New:** `table/` (`scene.py`, `floor.py`, `gm.py`, `canon.py`).
**Changed:** `bot.py` (`/session start|end`, `/rule`), `conversation.py` (a `record_ruling`
tool for the GM seat only).

**Done when:** a full session with the human as GM, then one with a bot as GM; a ruling made three
scenes earlier is honoured, and nothing moved a dot on a sheet.

### 6 — "Faces and voices"
The applications already exist from 3a, so this phase is about *how they sound*: two voices per
friend (IC and OOC), a playback queue per seat with the same TTL and barge-in rules as text, and
mute/volume. Distinct avatars and names come free with separate applications, which is why
identity moved out of this phase and into the roster.

**Do not start 4 before 3b's simulated week passes.** Chorus problems are indistinguishable from
cadence problems without a rhythm baseline, and debugging both at once is guesswork.

---

## 11. Cost, and what happens when something breaks

Ambient is cheap if the prompt is small, which is why the bounds already in `llm/prompt.py`
(8 facts, 2 sentences, 2000 characters) stay enforced. Rough shape of one ambient line:
~700 prompt tokens (persona, room note, 8 facts, 20 turns) and ~80 completion tokens.

| Volume | Tokens/day | `gpt-4o-mini` | A GPT-4-class model |
|---|---|---|---|
| 48 ambient messages (group budget, 8 active hours) | ~37k | ~$0.01 | ~$0.13 |
| Local model | free | — | — |
| One table session (cap 300k tokens) | 300k | ~$0.09 | ~$1.10 |

The point of the table is not the exact numbers but that **the ceiling is a number, not a hope**:
`Budget` refuses before generating, and the daily log line makes the total auditable.

| Failure | Behaviour |
|---|---|
| Model down, key revoked, host unreachable | `FallbackResponder` answers from the classifier; `Answer.degraded` is true and the log says why |
| Budget exhausted | silence, not an error — the room does not hear about accounting |
| Memory file corrupt | refuse to start with `path:line`; a bot with amnesia is worse than a bot that is off |
| Discord refuses a message (500/Forbidden) | log, drop that line, do not retry into a loop |
| Privileged intent not granted | log once at startup and run commands-only; everything else still works |
| Clock skew / DST | UTC internally, `zoneinfo` only for quiet hours |

The one thing that never degrades silently is a **human's** line: it is recorded in the window
before any decision to answer is made, so a bot that cannot answer still remembers being spoken
to.

---

## 12. How this gets tested without a Discord server

The suite is already offline and credential-free — `tests/conftest.py` refuses socket
connections, `tree.sync` and `Client.run` are recorders, and `test_no_network.py` fails if the
guard is removed. Everything here has to fit inside that.

- **`ManualClock` and seeded `RandomSource`.** `ambient/` takes both; a week is a loop over
  10,080 ticks, which should run in well under a second. No `sleep` anywhere in a test.
- **Scripted transcripts as fixtures.** Scenes live in JSONL beside the test, like
  `examples/demo_world`, so a regression is a diff in readable text rather than a prompt string.
- **Fake Discord, as today.** `_Interaction`, `_Bot` and recorders already exist in
  `tests/test_bot_commands.py`; the listener tests reuse them.
- **Property checks, not just examples.** Gap distribution p95 inside the configured band;
  never two intents for one seat in one window; total intents per hour under the budget for a
  thousand simulated days.
- **A stub synthesizer** for anything that speaks, so voice tests never load a model.
- **Role-shaped fakes for the audit.** A fake channel answers `permissions_for(member)` from a
  set of granted names, so a permission test is a few lines, asserts the exact fix text, and
  needs no gateway. The roster and supervisor get the same treatment: dormant friends, a
  rejected token, and one client failing while the others keep running.
- **One scripted leakage scene per direction**, asserted on what must not appear.

The single most valuable test in this document is the **simulated week**: three bots, seven
days, quiet hours, one human who is present for two hours a day and absent for two days. It is
the only way to see a chorus or an empty room before a real person does.

---

## 13. Decisions still needed from the human

Each has a recommendation, because a plan with no opinion is a menu.

1. **Message Content intent — yes or no?** **Decided: yes, per application.** Each friend sets
   `"listen": true` once the intent is enabled in its own Developer Portal entry; the helper
   never asks for it. A missing intent fails loudly (4014) rather than silently.
2. **One bot account or four?** **Decided: four.** `ttrpg-bot` stays the silent helper — commands,
   threads, sheet, dice, voice — and three separate applications are the friends. The helper is
   not a seat, holds no personality, and never appears in the group as a person.
3. **Which model for ambient?** Recommended: **local first** (free, private, no budget anxiety),
   with a paid model for table mode where quality shows. A paid ambient model is fine too, but
   then the daily ceiling matters from day one.
4. **Chatter level.** Recommended starting point: one group message per ten minutes, quiet hours
   23:00–08:00, no initiative into a cold room. That is *quieter* than `DESIGN.md`'s 4–9 minutes
   for a single bot; err quiet, and loosen after a week if it feels dead.
5. **Your name, pronouns, and how much teasing.** Needed before `/onboarding` can be built —
   the bots cannot ask "what should I call you" and then guess.
6. **Staggered quiet hours or one group schedule?** `DESIGN.md` leaves this open. Recommended:
   staggered by 30–60 minutes, so the group has a winding-down shape instead of a hard cut.
7. **Does memory cross channels?** Recommended: **facts per seat, window per channel.** A friend
   is one person; a conversation is one room.
8. **May a bot DM you?** Recommended: **no.** The sheet portal already moved out of DMs into a
   private thread per character, and a second private inbox would blur the one container that
   means "my character". The group lives in channels; one private space is worth more than two.
9. **Rulings: announced or silent?** `DESIGN.md` leaves this open. Recommended: announced once,
   in one line ("noting that down"), then never again — it teaches the table that canon exists.
10. **Drift outreach: how long is silence, and who breaks it?** Recommended: one week, one friend,
    and only with a ritual attached ("game night is Thursday") rather than a bare "hey". Which
    friend breaks it is a personality question, so it waits for §13.11.
11. **What the friends are like — deliberately deferred.** Names, humour, topics, how much they
    interrupt: all slots in the seat's `meta.persona`, all empty. Nothing in the code may assume
    a role until those are filled in. This is the one decision worth making *last*, because it
    is the one that decides what the group feels like, and it is much easier to write once the
    plumbing is quiet.

---

## 14. What this document deliberately does not cover

- **Voice barge-in and listening.** `stt/` selects and measures engines, but Discord voice
  *receive* (sink, E2E encryption, per-user streams) is a separate project with its own risks.
  Until then, bots speak in voice and do not hear.
- **Sheet-side planning and the library.** That is `DESIGN.md` phase 7 and belongs to the portal.
- **Content moderation beyond boundaries.** A private group of four with one human is a
  different risk profile from a public bot; if this ever leaves a private server, that changes.
- **Multi-bot tokens and the supervisor process.** Phase 6's operational shape deserves its own
  document when it is close enough to matter.
- **The Activity / web UI.** `DESIGN.md` phase 8 considers it only if the message UI becomes the
  bottleneck.

---

## 15. What "working" looks like

Not a feature list — three observations, in the order they become possible:

1. You mention a bot in a channel and it answers as **someone**, remembering the conversation
   from ten minutes ago and the thing you told it last week.
2. You come back after a quiet afternoon and there are two messages: one about the game, one
   about a film, and neither is a prompt to you. You can answer or not.
3. On game night the GM — whoever it is — rules something, and three sessions later nobody
   contradicts it, because it was written down.

Everything in this document exists to make those three ordinary.
