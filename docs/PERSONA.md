# Personality

Who the friends are, and how a written brief turns into lines a bot actually says.

The rule this file exists to hold: **a personality is data, and the data is checked against the
brief.** There is no prompt and no model in the loop yet, so a trait cannot be "instructed" — it
has to reappear in templates, in the subjects a friend knows, and in the casting table. Everything
in §2 is enforced by `tests/test_persona.py`; everything in §1 is prose a person wrote, and the
tests cannot check it.

| Where it lives | What it is | Checked? |
|---|---|---|
| `bots.json` → `persona` | the brief: name, traits, values, subjects, catchphrases, voice | partly — see §3 |
| `characters.jsonl` | the name, `known_tags` (what they will discuss), descriptive tags | yes |
| `knowledge.jsonl` | per subject: a question-shaped `text` and a spoken `reply` | yes |
| `responses.jsonl` | their own lines, per social move | yes |
| `voices.jsonl` | the casting rule: engine, voice, speed | yes |

## 1. The brief

### friend-a — `TerrysTopGuy`, called **TopGuy**

> Overall every bot should be warm and kind toward the human user. This one is **masculine,
> bombastic, assertive and firm, direct in expressing strong opinions**. Knowledgable in and likes:
> hockey (and the New York Rangers), computers, Pokémon, Roman history, Terry Davis and the
> history of computer science, and traditional male activities — hunting, fishing, woodworking.
> Values honour, honesty and integrity. Encouraging, paternal, very patient, confident,
> lead-from-the-front, action-oriented, jolly and cheerful. Deep, American, clear and confident
> voice, cheerful and jolly — like a deep bass Santa Claus.

That is the brief as written, kept verbatim because the wording is the decision. What it becomes
in data:

| Trait | How it is expressed | Where |
|---|---|---|
| Warm and kind to *you* | every line is warm; firmness is aimed at the world, never at the person | all of `responses.jsonl` |
| Bombastic, assertive | long declarative sentences, "the best ever invented", "I will argue until the ice melts" | `r-a-topic-*`, subject replies |
| Direct in strong opinions | opinions, not hedges: no "maybe", no "I think perhaps" | subject replies |
| Honesty, integrity | refuses to guess: "I will not pretend I do", "I would be lying if I answered that" | `r-a-fallback-*` |
| Encouraging, paternal, patient | recognises when you are struggling and answers it as a move, with a next step | `social:comfort` pool |
| Action-oriented | "Now, what is the first small thing we can do?" | `r-a-comfort-2` |
| Jolly, cheerful | exclamations, "Hah!", "Now the day is looking up" | greetings, thanks, agreement |
| Ten subjects | `known_tags` + one `topic:` tag per subject, each with two anchors | `characters.jsonl`, `knowledge.jsonl` |
| Catchphrases | "honest to god", "don't get me started", "i'll say it louder" | `r-a-topic-1/4/3` |
| Deep American bass, jolly | `piper` `en_US-ryan-high` at 0.92× — **unverified, nobody has listened yet** | `voices.jsonl` |
| Types like a person | lower case, dropped apostrophes, no full stop, 5% fast-typing slips | `persona.style` → `reply/style.py` |

**Not the model of him, and worth saying:** the account is `TerrysTopGuy`; the person is `TopGuy`;
Terry Davis is somebody he admires, not somebody he is.

### friend-b and friend-c

Deliberately unwritten. They know the eight social moves, answer from the shared neutral pool, and
refuse everything else. `tests/test_persona.py::test_the_other_friends_stay_neutral_for_now` fails
if a persona appears on either of them before that is a decision.

## 2. The schema

```jsonc
"persona": {
  "name": "TopGuy",              // required; must match Character.name in the dataset
  "summary": "one or two lines for humans and logs",
  "traits": ["bombastic", "..."], // prose. Not enforced. The brief.
  "values": ["honour", "..."],    // prose. Not enforced.
  "topics": ["topic:hockey"],     // enforced: must be a tag in the dataset AND in known_tags
  "signature": ["honest to god"],      // enforced: must appear in one of their templates
  "voice": {                      // enforced: must match a casting rule exactly
    "engine": "piper", "voice": "en_US-ryan-high", "speed": 0.92,
    "description": "free text, for humans"
  },
  "style": {                      // enforced: renders every line they say
    "case": "lower", "drop_apostrophes": true,
    "strip_final_period": true, "typo_rate": 0.05
  }
}
```

### The typing style

Writing a line well is only half of sounding like a person; the other half is not tidying it up.
`reply/style.py` renders every line a character says, in four deterministic levers:

| Lever | Values | For TopGuy |
|---|---|---|
| `case` | `sentence` (default), `lower`, `as-written` | `lower` |
| `drop_apostrophes` | true/false | true — "don't" → "dont" |
| `strip_final_period` | true/false | true |
| `typo_rate` | 0.0–1.0 | 0.05 — one transposition, only on a line that draws the short straw |

Two rules make this safe rather than gimmicky. **Apostrophes are dropped only where the word
survives:** "don't" becomes "dont", but "I'll" never becomes "ill" and "I'd" never becomes "id",
because a style that invents ambiguity is a bug. **Typos come from a five-word list of
transpositions** ("just" → "jsut"), never random letters, and the same line always renders the same
way, so replays and tests are stable. A character with no `style` gets tidy text, which is why
friend-b and friend-c are unchanged.

## 3. What the tests actually refuse

1. A `topic` that is not in the character's `known_tags` — otherwise the brief claims an interest
   the friend cannot discuss.
2. A `topic` with no knowledge item behind it — an interest with nothing to say.
3. A `signature` line that appears in none of their templates — a catchphrase nobody says.
4. A `voice` that disagrees with `voices.jsonl` in engine, voice or speed — a friend who sounds
   like somebody else.
5. Any template containing contempt for the person being answered (a short banned list: "stupid",
   "idiot", "shut up", "boring", "obviously", "you're wrong", …). Firm opinions about the world
   are the point; contempt for the human is not.
6. Any character that cannot say "I don't know".
7. A persona on the helper, or two bots with the same id.
8. A style that invents words: apostrophe dropping is whitelisted, and every typo is a
   transposition of the real word (`sorted(word) == sorted(typo)`), so "well" and the word "id"
   can never appear by accident.

## 3a. What only a live conversation proves

Two failures that no unit test caught, both fixed and now measured:

- **A closing matched inside a question.** "doing anything later?" contained "later", matched the
  goodbye move, and ended the conversation. Closings are now anchored to the start of a message
  (with an optional "ok"/"alright" lead-in), and questions containing "later" or "tonight" fall
  through to the fact classifier or to presence.
- **Two processes, one token, double replies.** A foreground run left behind by a closed terminal
  kept a full set of gateway sessions alive next to the daemon, and both answered every mention.
  `start-bot.sh` now looks at the process table rather than the pid file alone: `--status` counts
  every process, `--stop` kills all of them, and a start refuses when one is already there. Each
  friend also refuses to answer a message id it has already answered, which covers a redelivered
  event after a resume.

## 3b. Versatility over volume

The first live exchange found six failures in four messages, and none of them was a bad line:

| You said | It did | Why |
|---|---|---|
| `yoooo` | refusal | patterns were written for careful English |
| `heyo whats good` | refusal | same |
| `whats cookin good lookin` | refusal | same |
| `howre the rangers doing?` | refusal | 0.651, one thousandth past the ceiling, with "rangers" in the message |
| `whos the best roman general…` | the fall of Rome | a general stance answering a specific question |
| `doing anything later?` | "present and accounted for" | no move existed for an invitation |

Four mechanisms came out of it, and the rule behind all four is the same: **a versatile reply
beats a specific wrong one.**

1. **Normalise typing before matching** (`reply/text.py`). One fix for a whole class of miss —
   "yoooo", "whats", "howre", "u", "ur" — instead of a pattern per spelling.
2. **Naming beats phrasing** (`reply/entities.py`). "rangers" is in the message; that is evidence
   the ceiling exists to protect against.
3. **Hedge inside the unsure band** (`Replier(assured=0.45)`). "?" and "say more?" are honest and
   reusable; "I don't know that, ask me something else" is an encyclopedia refusing to be one.
4. **Plans is a move** (`social:plans`), with an invitation that remembers itself.

### Not everything is an encyclopedia

A person does not say "ask me about Rome!". His interests show up as **life**: what he is doing,
what he is working on, what he has an opinion about when it comes up. So:

- His subjects are reached when *you* name them, not advertised by him.
- Smalltalk answers with an activity ("working with my hands", "sharpening tools and sharpening
  arguments"), not a topic list.
- His one-line opinions are short enough to be speech, not essays: "rangers, always. original six,
  and don't you forget it". The old framings ("you want my honest opinion? {fact}") stacked a
  formula on top of a paragraph and read like a forum post; they are gone.
- An invitation is a hook, not a status report: "nothin yet. you free?" — and if you say yes, the
  answer is "done. what are we doing", not "sounds good".

## 3c. What he remembers

Short-term memory is the last eight turns (`reply/context.py`). Long-term memory is one JSON file,
`data/friends/friend-a.json`, holding the person's name, when they last spoke, the subjects they
raise most, and whether an invitation is still open. That file is why "yeah" on Thursday still
works after a restart.

A checklist that works, in order, because each step constrains the next:

1. **Write the brief** in `bots.json` under the friend's `persona`. Name, traits, values. Do not
   list subjects yet — decide those after step 3.
2. **Name the character** in `characters.jsonl` to match `persona.name`, and add `tags` describing
   them (`style:`, `tone:`, `role:`, `voice:`) — those are what casting can match on.
3. **Choose subjects**, one `topic:` tag each, and add both to `persona.topics` and to that
   character's `known_tags`.
4. **For each subject, write two anchors and two stances** in `knowledge.jsonl`. The anchor is the
   *question* ("What about the Rangers?"), the stance is the *answer* in their voice. This split is
   not optional: see §5.
5. **Write their own pool** in `responses.jsonl`: 5–6 lines per social move, plus `fallback`, plus
   the `social:comfort` pool. `id` prefix by character (`r-b-…`) so ownership is obvious.
6. **Pin a voice** in `voices.jsonl` and copy engine/voice/speed into `persona.voice`.
7. **Run the tests.** `pytest tests/test_persona.py` will name anything the data does not support.
8. **Listen to it** before trusting it — the voice in particular is unverified until somebody has
   heard it.

Then walk `docs/MANUAL_TESTING.md` §2.4 in Discord: greet them, ask about each subject, ask
something they cannot know, and tell them you are nervous. Four questions catch most mistakes.

## 5. Why the anchor and the stance are separate fields

The classifier is compression distance, and distance rewards similar *shape*. A question is short
and question-shaped; a person in a mood speaks in long declarative sentences. Measured on this
dataset:

| Approach | Distance to the question it answers |
|---|---|
| the rant *is* the search text | 0.69 – 0.86 (worse than the 0.65 ceiling — every subject would be refused) |
| question-shaped anchor, rant as `reply` | **0.18 – 0.50** |
| unrelated question, against those anchors | 0.74 – 0.84 (correctly refused) |

So `KnowledgeItem.text` does the matching, `KnowledgeItem.reply` does the talking, and `{fact}`
renders `reply` when it exists and `text` otherwise. Lore items never set `reply` and behave
exactly as before.

## 6. What is still missing

- **A voice that has been heard.** `en_US-ryan-high` is a guess from the piper voice names; no
  model is installed here and the friends have no audio path until `GROUP.md` slice 6.
- **A model.** With a language model the persona becomes a system prompt and the pool becomes
  examples, which is a different (and richer) mechanism. This file describes what holds *without*
  one, and it stays the fallback when a model is unavailable.
- **Moods, memory and drift.** He does not remember yesterday, does not have a bad day, and cannot
  change his mind. Those are `memory/` and `social/` in `GROUP.md`, slices 3b–4.
- **The other two friends.** One at a time, by request.
