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
| Deep American bass, jolly | `piper` `en_US-joe-medium`, length scale **1.05** — chosen by measuring 13 candidates: 98 Hz median F0 against ryan-high's 144 Hz. See §3d | `voices.jsonl` |
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
    "engine": "piper", "voice": "en_US-joe-medium", "speed": 1.05,
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

## 3d. Hearing him

`/voicetest action:join` (join a voice channel yourself first), then `action:speak`, then
`action:leave`. He joins **self-deafened**, because he does not listen to voice yet. The model lives in
the TTS cache, not the repository.

### The two numbers

| Lever | Where | Direction | Now |
|---|---|---|---|
| `speed` | piper's length scale | **higher is slower** | `1.05` |
| `pitch` | resampling, applied after the engine | **lower is deeper** | `1.0` — off |

`pitch` exists (see `audio/pcm.py::shift_pitch`) and works, but it is **not used**: it is a resample, so
it shifts tempo along with pitch and colours the timbre. Heard in the channel as *"pitching the voice
sounds a bit off"*, which is the honest verdict on a phase-vocoder-less transposition. The lever stays
for a voice that needs it; the fix for "not deep enough" was a deeper voice.

### Three rounds of listening, and the measurement that ended it

| Round | Setting | Verdict |
|---|---|---|
| 1 | ryan-high, 1.15 | *"a bit too fast and not deep or confident enough"* |
| 2 | ryan-high, 1.2 + pitch 0.93 | *"a hair too slow, pitching sounds a bit off"* |
| 3 | **joe-medium, 1.05, no pitch** | naturally deep, pace close to its own |

Round 2's problem was visible in the numbers before it was audible: the resample stretched the clip
7.5% and moved the timbre, on a voice that was already the *highest* of every candidate. So instead of
guessing at names, all the American male piper voices were rendered on the same sentence and their
median fundamental frequency measured (autocorrelation over voiced frames, 60–350 Hz):

| Voice | Median F0 | Line length at neutral | Peak |
|---|---|---|---|
| **`en_US-norman-medium`** | **95.0 Hz** | 6.8 s | 14,930 |
| **`en_US-joe-medium`** ← chosen | **98.2 Hz** | 6.9 s | **22,765** |
| `en_US-john-medium` | 98.9 Hz | 9.8 s | 9,004 |
| `en_US-kusal-medium` | 105.0 Hz | 6.7 s | — |
| `en_US-danny-low` | 106.0 Hz | 6.9 s | — |
| `en_US-hfc_male-medium` | 109.7 Hz | 7.1 s | — |
| `en_US-mike-medium` | 123.2 Hz | 6.4 s | — |
| `en_US-bryce-medium` | 126.0 Hz | 8.6 s | — |
| `en_US-arctic-medium` | 129.7 Hz | 7.1 s | — |
| `en_US-l2arctic-medium` | 138.7 Hz | 8.3 s | — |
| `en_US-sam-medium` | 140.4 Hz | 8.5 s | — |
| `en_US-ryan-high` (was) | **144.1 Hz** | 6.1 s | 20,309 |
| `en_US-lessac-high` | 193.4 Hz | 7.0 s | — |

Three things this settles:

* **The complaint was accurate.** ryan-high was the highest-pitched of thirteen candidates, not a
  deep voice at all — the name promised more than the model delivers.
* **Depth is not a quality tier.** The deepest voices are all `medium`; the two `high` models measured
  the *highest*. There is no deep high-quality American male in piper, so "deep" and "120 MB model"
  were never the same choice.
* **joe over norman** despite being 3 Hz higher: nearly the same depth, and a markedly stronger
  presence (22,765 peak against 14,930), which is what "confident" sounds like. Norman remains the
  one-line alternative.

Depth is measured, not judged: `data/samples/voices/manifest.json` holds every candidate's numbers,
and the rendering script is reproducible in three lines.

### Hearing the alternatives

All saying the same twenty-word line, all git-ignored:

| File | What it is |
|---|---|
| `data/samples/topguy-tuned.wav` | **current**: joe-medium at 1.05 |
| `data/samples/topguy-alt-norman.wav` | norman-medium at 1.05 — 3 Hz deeper, quieter |
| `data/samples/voices/en_US-joe-medium.wav` | every candidate at **neutral** pace, for comparison |
| `data/samples/voices/manifest.json` | the measured F0 table |

Switching voice is one edit in two places (`examples/friends_world/voices.jsonl` and the persona's
`voice` block), then a restart. A test fails if the two disagree.

### Keeping him, not just choosing him

The model is 63 MB in a cache, so `examples/friends_world/voices.lock.json` pins it: size, SHA-256
and MD5 per file, two independent sources, the CC0 provenance, and the five steps to rebuild from
nothing.

```bash
ttrpg-chatbots-tts --verify-voice    # is the cached voice the one we chose?
ttrpg-chatbots-tts --fetch-voice     # get it back, source by source
```

If every mirror ever disappears, joe is finetuned from `en_US-lessac-medium` -- recorded in the
lock's provenance as the one-hop fallback. See `docs/SPEECH.md` §2.

### What he says is not what he types

`$250 watch` was read as *dollar sign two hundred fifty watch*. Speech has its own text form now
(`tts/spoken/`), so he types the symbols and says the words: *two hundred fifty dollars watch*.
Check any line without synthesising it:

```bash
ttrpg-chatbots-tts --spoken 'Dr. Smith paid $1,200 in 1984'
```



* **The speed was backwards.** Piper's `speed` is a length scale — 1.0 is neutral, **higher is
  slower** — so the original 0.92 was making him *quicker*, the opposite of "unhurried".
* **A bare cast is not his voice.** `VoiceCast()` with no directory resolves to the built-in narrator,
  so `/voicetest` would have played a stranger. `FriendVoice` loads the world's `voices.jsonl`, and a
  test asserts friend-a resolves to `piper` / `en_US-joe-medium` / >1.0 while friend-b (no rule)
  gets the default.

### The one that made him speak exactly once

`DiscordAudioSource.cleanup()` cleared the **shared** `VoicePlayer`. discord.py calls `cleanup()` at
the end of *every* stream, and the `AudioPlayer` that ended it is garbage collected exactly when the
next one starts (`discord/player.py` calls `cleanup` from `__del__`) — so the audio queued for the
*next* clip was deleted before it could be read. The player outlives the source; `cleanup` now
releases nothing, and only `FriendVoice` drops the queue. Two tests hold it: one at the source level,
one walking speak → stream ends → speak again.

### Listening without Discord

Rendered samples on the box, all saying the same twenty-word line:

| File | What it is |
|---|---|
| `data/samples/topguy.wav` | the **first** setting (1.15, no pitch) — the baseline that was rejected |
| `data/samples/topguy-tuned.wav` | **current**: speed 1.2, pitch 0.93 |
| `data/samples/topguy-pitch-090.wav` | 0.90 — noticeably heavier |
| `data/samples/topguy-pitch-096.wav` | 0.96 — closer to neutral |

Any line, any setting, without the bot:

```bash
TTRPG_TTS_VOICE=en_US-joe-medium .venv/bin/ttrpg-chatbots-tts --say "your text" \
  --engine piper --voice en_US-joe-medium --out /tmp/try.wav
```

Judge it by ear: deep American bass, cheerful, about 6.9 s for a twenty-word line at the current
setting.

## 5a. Proving it: `ttrpg-chatbots-persona`

Reviewing 50 lines by eye cannot tell you that his opinions run out after one question, or that a
quarter of his lines end on a punchline. Both were true of the old corpus, and both are numbers, so
there is a harness (`bots/persona_harness.py`) with **twelve checks** over the whole material:
every phrasebook line, every subject he claims, every story and plan.

```bash
ttrpg-chatbots-persona              # the full report
ttrpg-chatbots-persona --quiet      # verdict and failures only, exit 1 on failure
ttrpg-chatbots-persona --json       # machine-readable
```

```
ok   coverage                 every interest has 3+ things to say
ok   subjects_have_replies    every subject says something in his own voice
ok   anchors_name_their_subject every question finds its own subject
ok   fits_the_budget          every stance opens inside 12 words
ok   register                 nothing lands on a beat or explains itself
ok   length                   median under 18 words, nothing over 30
ok   short_form               social lines do not stack up statements
ok   warmth                   no line is cold to the human
ok   signatures               every catchphrase is really in his mouth
ok   distinct_lines           no phrasebook repeats itself
ok   life_depth               his day has enough in it to keep talking
ok   stories_land             every story has a point to arrive at

PASS  TopGuy  subjects 39  lines 91  median_words 5  two_sentence_pct 7.6  distinct_pct 96.2
```

Against the old corpus: 7 words median but **51%** two-sentence lines and **29%** ending on a
punchline. Now: 5 words median, **7.6%** two sentences, and no beats at all. The suite asserts the
whole report passes, so a content edit that breaks any of it fails the tests and names the line.

### What the harness caught that review did not

| Finding | Mechanism |
|---|---|
| **Nine legacy lines had no `reply`** -- so the anchor text itself was spoken: *"You take only what you need and you thank the animal"* | `subjects_have_replies` |
| **Four topics had two things to say**, so the second question about hockey repeated or hedged | `coverage` |
| **Eight stances were one long sentence** over the twelve-word substance budget, so `render/trim` could not shorten them and *"do you like hockey?"* stopped answering at all | `fits_the_budget` |
| **Two anchors named nothing** -- *"Why do measure twice?"*, *"Is a bad shot cruel?"* -- so they were unreachable however good the reply was | `anchors_name_their_subject` |
| **A generic slot value was a trap**: `"his work"` made *"rough day at work"* match Terry Davis | `subject` routing test |
| **Three catchphrases were not in his mouth** after the rewrite | `signatures` |
| **`explain` had `{fact}` twice** in one family -- variety on paper only | `distinct_lines` |

Two of those were the *gate* being wrong rather than the data, and both were fixed in
`decide/persona_fit.py`: a trailing **question** is a hand-back, not a punchline (*"morning. how is
the fence?"*), and **backchannel** is not a beat (*"ha. same"*, *"ugh. yeah"*).

## 6. What is still missing

- **A voice that has been *settled*.** `en_US-joe-medium` was picked by measurement and heard once;
  model is installed here and the friends have no audio path until `GROUP.md` slice 6.
- **A model.** With a language model the persona becomes a system prompt and the pool becomes
  examples, which is a different (and richer) mechanism. This file describes what holds *without*
  one, and it stays the fallback when a model is unavailable.
- **Moods, memory and drift.** He does not remember yesterday, does not have a bad day, and cannot
  change his mind. Those are `memory/` and `social/` in `GROUP.md`, slices 3b–4.
- **The other two friends.** One at a time, by request.
