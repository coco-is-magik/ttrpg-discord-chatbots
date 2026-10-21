# Modules: the full plan

Every module in the conversation layer, its one question, its contract, and the test that proves it.
`src/ttrpg_chatbots/conv/manifest.py` is the same list in code, with a status per row and a test that
fails if the two disagree.

**Rules** (from `CONVERSATION.md`): one question per module · one input type, one output type · no
I/O outside adapters · only `render/line.py` produces words · every stage may abstain · one dataset
file, one reader.

Status key: **built** · *planned*. **The manifest is authoritative** -- run
`python -c "from ttrpg_chatbots.conv import summary; print(summary())"`.
The bold markers below show the state at the time of writing.

Still planned: none -- all 50 modules exist and have tests. What does *not* exist yet is the second job: only `greet` has a phrasebook, and `govern.loop` is not wired to the bot.

---

## 1. Perceive — describe the situation

| Module | Question | In → Out | Test |
|---|---|---|---|
| `perceive.inbound` | what arrived, in a sane shape? | discord-ish fields → `Utterance` | builds from partial input; strips mentions |
| `perceive.clock` **built** | what time is it for him? | `datetime?` → `Moment` | injectable now; part of day |
| `perceive.modality` | text, voice, image, embed, system? | `Utterance` → `Modality` | attachment beats text; system notice |
| `perceive.attachments` | is there a picture, and can he see it? | `Utterance` → `Attachment` | visible=False (no vision) |
| `perceive.addressee` | named, replied to, or neither? | mention/reply flags → `Addressee` | reply wins over bare mention |
| `perceive.gap` | how long since this person spoke? | last_seen, now → `Gap` | buckets: new/today/week/long |
| `perceive.events` | what is happening he'd care about? | `Calendar`, date → `Events` | ongoing vs upcoming; topics |
| `perceive.situation` | what kind of conversation is this? | channel name, table flag → `Situation` | ttrpg/gaming/watching/admin/chatting |
| `perceive.world` | is a scene open, whose turn, in character? | table state file → `TableState` | absent file → no scene |
| `perceive.thread` | what is this thread about? | recent turns → `Thread` | follows the last named subject |
| `perceive.tone` | how are they saying it? | text → `Tone` | haha→warm, ≤2 words→terse, …→flat |
| `perceive.sentiment` | good or bad, and about what? | text → `Sentiment` | polarity + target (self/you/it) |
| `reply.text` **built** | what do the words actually say? | raw → normalised | typing variants |
| `reply.entities` **built** | which subjects did they name? | text → `frozenset[tag]` | rangers, no false positives |
| `life.schedule` **built** | what is he doing right now? | `Moment` → `Slot` | 15-min snapping, sleep |
| `life.calendar` **built** | what does the year say about today? | `date` → `DayView` | precedence, wrap, overlay |

## 2. Remember — hold state, move it between short and long term

| Module | Question | In → Out | Test |
|---|---|---|---|
| `memory.short` | the last few turns, verbatim | append/read → `Turn`s | ring buffer, never grows |
| `memory.encode` | does this turn contain a fact? | text → `Fact`s | "my dog is called Otis" → `pet.name` |
| `memory.promote` | which candidates graduate? | `Fact`s, long → `Promotion`s | twice-said graduates; once does not |
| `memory.long` | what do we durably know? | store → `Fact`s | add/replace/contradiction |
| `memory.retrieve` | what is relevant now? | cue + long → `Recalled` | entity overlap ranks first |
| `memory.decay` | what should be forgotten? | long, now → ids | stale + never recalled |
| `memory.open` | what is still unresolved? | `Memory` → `Open` | pending invitation |
| `memory.relationship` | how well does he know them? | sessions, gap → `Relationship` | new → acquainted → friend |
| `memory.store` | the only disk adapter | path ↔ dict | atomic write, corrupt file |
| `bots.memory` **built** | one friend's durable memory | file → `FriendMemory` | reload |
| `reply.context` **built** | what was said just before? | turns → `Context` | window, previous act |
| `reply.transitions` **built** | which act follows which? | counts → model | veto rule |

## 3. Decide — one rung of the ladder each

| Module | Question | In → Out | Test |
|---|---|---|---|
| `decide.floor` | should he speak at all? | addressed, asleep, budget → `Speak`/`Abstain` | asleep abstains; unaddressed abstains |
| `decide.phase` | where in the arc? | turns, today → `Phase` | first turn = opening; subject = hook |
| `decide.depth` | how often has this thread been leaned into? | turns, thread → `int` | second question raises depth |
| `decide.job` | which job owns this turn? | intent, phase, depth → `Job` | greet at opening; explain at depth≥1 |
| `decide.who` | friend or character? | situation, table → `Who` | ttrpg scene → character |
| `decide.form` | what shape? | job, budget → `Form` | tight budget → word/clause |
| `decide.family` | which kind of phrasing? | job, relationship, moment → `Family` | morning + friend → time_morning |
| `decide.variant` | which specific line? | family, phrasebook, recent → id | never repeats within N |
| `decide.length` | how many words? | their words, phase → `Budget` | 2 words in → ≤4 out |
| `decide.reciprocate` | does he hand the turn back? | job, tone → `Reciprocate` | hook → question |
| `decide.persona_fit` | does it sound like him? | text, persona → `Fit` | rejects second beats, exposition |
| `reply.intents` **built** | which social move is this? | text → tag | 40 utterances |
| `reply.style` **built** | how does he type? | `Style` → `Style` | apostrophe whitelist |

## 4. Render — words appear here, only here

| Module | Question | In → Out | Test |
|---|---|---|---|
| `render.fill` | template + values → text | `str`, `dict` → `str` | missing slot refuses |
| `render.trim` | enforce the budget, or refuse | text, `Budget` → `str`/`None` | drops a trailing clause |
| `render.typing` | apply the typing style | text, `Style` → `str` | delegates to `reply.style` |
| `render.audition` | accept, or ask for the next | candidate, checks → `Accept`/`Reject` | budget, fit, repeat |
| `render.line` | assemble the line | text, `Trail` → `Line` | empty text refuses |

## 5. Govern — wiring and measurement

| Module | Question | In → Out | Test |
|---|---|---|---|
| `govern.loop` | the only place that knows the order | inputs → `Line`/`Abstain` | greeting end to end |
| `govern.repeat` | what has he said recently? | ids, window → seen? | allows repetition, records it |
| `govern.trace` | record every decision | steps → `Trail` | one entry per rung |
| `govern.abstain` | why did nobody speak? | `Abstain`s → one reason | first reason wins |

---

## Order of work

1. **Perceive** first: no dependencies, and everything downstream reads it.
2. **Remember** second: short/relationship/gap unblock `floor`, `phase` and `family`.
3. **Decide** third, in ladder order, each testable with fixtures.
4. **Render** fourth: trim and audition are the two that enforce quality.
5. **Govern** last: the loop is only written once the rungs exist.

A stage is only marked **built** when its test exists. The manifest test enforces the other
direction: nothing may exist while it is still marked *planned*.

## Datasets, one reader each

| File | Read by |
|---|---|
| `phrasebooks/<job>.json` | `decide.variant` |
| `persona.json` | `decide.persona_fit`, `render.typing` |
| `life.json` | the hook and substance stages |
| `schedule.json` | `perceive.events`, the life stages |
| `calendar.json` | `perceive.events`, `decide.phase` |
| `memory/<friend>.json` | `memory.store` |

`phrasebooks/<job>.json` shape:

```jsonc
{
  "job": "greet",
  "families": {
    "warm":      { "when": { "relationship": ["friend"], "gap": ["day", "week"] },
                   "variants": ["there he is", "hey stranger"] },
    "time_morning": { "when": { "part_of_day": ["morning"] },
                   "variants": ["morning", "morning bud"] }
  }
}
```

## Where the build stands

**51 of 51 modules exist** (`ttrpg-chatbots-conv --harness` runs the measurement; the manifest test
refuses drift in either direction). The ladder is wired live for **one** job — greetings — behind
`TTRPG_CONVERSATION=greet`, and every other job still goes through the old classifier.

Measured on the greet phrasebook, 144 attempts over three relationships and four times of day:

| | old corpus | greet ladder |
|---|---|---|
| words, median | 7 | **1** |
| two-sentence lines | 51% | **0%** |
| ends on a beat | 29% | **0%** |
| distinct lines | 100% | **7%** (10 lines, reused) |

That last row is the design intent, not a defect: a person says "hey" the same way all week.

### Three rules the greet phase added, now enforced by tests

1. `decide/variant` never offers a line the budget cannot fit — a too-long variant does not exist as
   a candidate (`test_greeter.py`).
2. A missing family yields no lines; it does not borrow another family's (`test_ladder.py`).
3. A phrasebook answers its own job only, and abstains otherwise: `the greet phrasebook does not do
   acknowledge` (`test_greeter.py`).

Manual verification, with the module that owns each possible failure, is `MANUAL_TESTING.md` §2.5.
