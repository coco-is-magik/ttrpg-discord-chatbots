# Conversation: the decomposition

Why the conversation layer is being rebuilt as ~45 single-purpose modules instead of one `reply()`
function, and the rules that keep it that way.

**Status: design accepted, partially built.** Nothing in the live bot changes until the ladder and
the harness exist. The context pieces are built and wired to nothing: `docs/SCHEDULE.md` (the week)
and its calendar (the year). The plan itself is `src/ttrpg_chatbots/conv/manifest.py` —
**11 of 50 modules built**, with a test that fails if a module is marked built and does not import,
or marked planned and exists anyway. See it with
`python -c "from ttrpg_chatbots.conv import summary, check; print(summary()); print(check())"`.

## 1. The failure being fixed

`Replier.reply()` answers eight questions at once: is this a move, which move, which subject, is it
close enough, how much, what words, how long, does it fit the context. Every fix landed in that one
function, so none of them held. A greeting reply also tried to be a hook, and a hook carried its own
backstory: **one turn has to do one job**, and the job is chosen by the conversation, not by the
reply's ambition.

Measured on the old corpus (112 lines) against the human's own messages (13):

| | bot | human |
|---|---|---|
| words, median | 7.0 | 2.0 |
| sentences, median | 2.0 | 1.0 |
| lines ending in a short beat | 29% | — |
| distinct messages | 112/112 | 10/13 |

Talking at 3.5× the length, twice the clause count, and never repeating a phrase is what "written"
sounds like.

## 2. The rules

1. **One question per module.** One input type, one output type.
2. **No I/O except adapters.** Only `perceive/*`, `memory/store.py` and `render/line.py` touch the
   world.
3. **Only the leaf writes words.** Bands 1–3 return decisions and references.
4. **Every stage may abstain.** `Draft | Abstain(reason)`: a wrong call goes quiet, not strange.
5. **One dataset file, one reader** — enforced by a test.

## 3. Bands

| Band | Job | Modules |
|---|---|---|
| **Perceive** | describe the situation | inbound, typing, modality, attachments, addressee, clock, gap, events, situation, world, thread, entities, intent, tone, sentiment |
| **Remember** | hold and move state | short, encode, promote, long, retrieve, decay, open, relationship, store |
| **Decide** | one rung each | floor, phase, depth, job, who, form, family, variant, length, reciprocate, persona_fit |
| **Render** | words, once | fill, trim, typing, audition, line |
| **Govern** | wiring and measurement | loop, repeat, trace, abstain |

`decide/depth.py` is the structural fix for exposition: a thread carries *how many times this person
has leaned in*, and a hook at depth 0 cannot reach the story tier at all.

## 4. The ladder, one level of specificity at a time

"hey", from a friend not seen for 14 hours:

| Rung | Module | Answer |
|---|---|---|
| 1 | `floor` | speak |
| 2 | `phase` | opening |
| 3 | `job` | greet |
| 4 | `form` | recognise (he knows this person) |
| 5 | `family` | warm |
| 6 | `variant` | `g-warm-03` — "there he is" |
| 7 | `fill` + `typing` | "there he is" |
| 8 | `audition` | 4 words ✓ one clause ✓ no beat ✓ in character ✓ |

If `audition` rejects, it asks **`variant`** for the next candidate. It never re-runs the ladder.
Tuning "he greets too warmly" means editing one family's triggers, not debugging a monolith.

## 5. Datasets

```
personas/base/…                    the neutral friends
personas/friend-a/
  persona.json                     brief: name, voice, style, values
  lexicon/{intents,tone,sentiment,entities}.jsonl
  phrasebooks/greeting/{families.json, warm.jsonl, casual.jsonl, time_morning.jsonl, time_evening.jsonl}
  phrasebooks/{pleasantries,hook,substance}/…
  knowledge/{subjects,stances,stories}.jsonl     # depth-tagged
  life/{activities,grievances,plans}.jsonl
  schedule.json                  # the week, in 15-minute blocks
  calendar.json                  # the year: seasons, holidays, one-offs
  cast/character.json
```

Resolution is base → character override, per file, per id. Changing how warmly he greets touches one
file that nothing else reads. Depth tagging is what makes exposition impossible: `subjects` holds the
hook, `stances` the opinion, `stories` the three-sentence version, and the phase decides which tier is
even addressable.

> Today's worlds live in `examples/friends_world/`, where `knowledge.jsonl` is read by the matcher,
> the renderer *and* the subject vocabulary. That is the coupling this layout removes.

## 6. Slice 0 — done, and what it proved

`govern/trace.py` (every reply carries its eight rungs) and `govern/harness.py` (a matrix through one
phase, reporting words, distinctness, beat rate and why anything stayed quiet) both exist. The audit
numbers are now a test:
`tests/test_greeter.py::test_the_harness_answers_every_time_and_never_sounds_like_a_caption`.

```bash
.venv/bin/python -m ttrpg_chatbots.conv.cli --harness
# phase: greet
# attempts 144  said 144  abstained 0
# words: median 1, max 3
# distinct: 7% (10 of 144)
# ends on a beat: 0%
```

Under the old corpus: median 7 words, 51% of lines two sentences, 29% ended on a beat, 100% novelty.
The first phase on the ladder: 1 word, 0% beats, 7% distinct — i.e. **repetition**, which is what
familiarity sounds like.

`ttrpg-chatbots-conv --greet "hey" --explain` prints the eight rungs for a single message.

### What the harness caught that review did not

1. **A long variant silenced a whole family.** Twenty of 144 greetings were dropped as "over budget"
   because `decide/variant` offered a six-word line for a three-word budget and `render/trim` then
   refused it. Fixed at the rung that chose it: a line that cannot fit is not a candidate.
2. **A missing family borrowed another family's lines**, so a stranger got "there he is". Removed:
   no family, no lines.
3. **The greet phrasebook answered other jobs** (`offer_hook`, `acknowledge`) because the loop never
   checked. It now abstains: `the greet phrasebook does not do acknowledge`. That is the phase
   boundary, enforced rather than documented.

### Proving it on a person

The ladder runs live behind `TTRPG_CONVERSATION`: `greet` answers greetings only, `ladder` answers
every phase the friend has a phrasebook for and leaves knowledge questions to the old classifier
(until world knowledge is wired in as a tool). The script is `docs/MANUAL_TESTING.md` §2.5 and §2.7.

## 7. The phases, as built

Nine jobs, one file each in `examples/friends_world/phrasebooks/`. A phase is added by dropping a
file in; removed by deleting one. The shelf refuses to lend one job's lines to another.

| Phase | Job | Answers | Slots it may use | Measured |
|---|---|---|---|---|
| Opening | `greet` | "hey" | clock, relationship | median 1 word |
| Opening | `close` | "good night" | — | median 1 word |
| Pleasantries | `acknowledge` | "thanks", "yeah" | — | median 1 word |
| Pleasantries | `noted` | a statement with nothing to add to | — | median 1 word |
| Pleasantries | `reassure` | "i am nervous about tomorrow" | — | median 1 word |
| Pleasantries | `mirror` | "rough day at work" | his grievance, **only at depth ≥ 1** | median 1.5 words |
| Hook | `offer_hook` | "what are you up to" | `{hook}`, `{invite}`, `{short}` | median 4 words |
| Substance | `explain` | "why?" | `{why}` | median 2 words |
| Any | `hedge` | a question he cannot answer | — | median 1 word |

`ttrpg-chatbots-conv --harness` prints one report per phase: attempts, abstains, median and maximum
words, distinctness, beat rate, and how often the trimmer had to intervene. `--say "..." --explain`
prints the eight rungs for a single message.

### What the phases cost in the data

* `life.json` gained a **`hook`** per activity -- "rebuilding the back fence", "messing with an old
  computer". A hook is a few words; `doing` is a description and `phase` is a status, and using either
  for "what are you up to" is how a person starts monologuing.
* Every `why` and every grievance was **shortened to what fits in one breath**. A reason is a reason,
  not a paragraph with a twist.
* The `reply` slot split from `text` for the same reason: a template carries the *stance*, and a fact
  carries the anchor.

### The five defects the live channel found that review did not

1. **A hook answered with a reason.** "what are you up to" arrived after a long message, depth was
   already 1, and `decide.job` used depth to promote the hook to an explanation. Depth belongs to the
   follow-up, not to a fresh question about his day; `explain` is now reached only by a why-question.
2. **The trimmer cut a comiseration to "yeah".** The mirror detail family was `"{reaction}. {grievance}"`
   -- two beats, twelve words, over budget -- so `render.trim` dropped the *content* and kept the
   reaction. Two fixes: the detail family is the grievance alone, and the harness now reports a
   **trim rate** so a phrasebook that fights the budget is visible instead of silent.
3. **A question with no question mark became a statement.** "what is the plot of dune" (no "?") is a
   question; `looks_like_question` reads the opening word as well as the punctuation.
4. **A statement got "?"** -- "i have been rebuilding a fence myself this month" was treated as an
   unanswerable question. Statements now get `noted`, whose whole job is a short noise of having
   heard, because that is the most common reply in any group chat.
5. **A goodbye got "you got it".** Goodbyes were acknowledgements; they are now `close`, whose
   phrasebook has one rule -- answer it and let them go.

Every one of those was invisible in the tests and obvious in a channel. That is the argument for the
harness *and* for testing with a person, not one or the other.

## 8. Memory, and knowing things

Two gaps closed after the phases, both of them "the bot works but is not a friend yet" problems.

### He remembers what you told him

`memory/` was built and wired to nothing. Now:

| Module | Job |
|---|---|
| `memory/encode` | four patterns -- a pet, a job, a plan, a strong like. Patterns, not comprehension |
| `memory/promote` | a pet or a job is kept the first time; everything else has to be said **twice** |
| `memory/db` | the only writer: **SQLite**, facts and topics and tellings and a journal (`docs/STORAGE.md`) |
| `decide/recall` | **should he bring it up?** the gate, and the interesting part |
| `memory/retrieve` | word overlap, which is enough: "how is the dog?" finds `pet.name = otis` |

Memory is a database, not a document per friend: the document was rewritten whole on every save,
up to four times per message, over NFS. `docs/STORAGE.md` has the argument, the schema, the
recovery story, and the one deployment caveat (journal mode on NFS).

**The gate has two modes, and they are not interchangeable.** `raised` means the message shares a word
with the fact -- answering it is listening, not recall, and any job that can hold it may. `session`
means they have not spoken since yesterday and the fact is the kind a friend asks about -- that belongs
to *openings* only. Both are capped at once a day.

Three measured failures shaped it:

1. **"said twice" could never fire.** The first mention left no trace, so the second looked like the
   first. Refusals are now counted in `pending`.
2. **Retrieval dropped three-letter words**, so "dog" and "cat" -- exactly the words a person uses --
   never matched. The filter is a small stoplist now, not a length rule.
3. **An unrelated question got the dog question.** "what is the plot of dune?" was answered with "how
   is otis doing", because a session-mode fact was offered to a job that had no business using it.
   Hence the mode table in `decide/family`.

### He knows things, in one voice

Subject questions ("do you like hockey?", "who is terry davis") used to go to the old compression
classifier, which meant one conversation was answered by two engines with two rule sets: the ladder's
lines were one to four words and never ended on a beat, the classifier's were paragraphs.

`decide/subject` is that engine's knowledge, reduced to one question -- which subject did they name,
and which of his facts fits it:

* the **name** comes from `reply/entities`, a vocabulary of the words each subject goes by;
* **distance** (`reply/ncd`) only ranks *within* that subject, never "is this about hockey at all".

There is deliberately **no ceiling here**, and it is a measurement, not an omission. Applied on top of
a name it refused `howre the rangers doing?` at 0.651 and the correctly spelled version at 0.662 -- in
a message with the word *rangers* in it. The name is the gate; distance only ranks.

The ladder then answers with the item's **stance** when the dataset has one and its fact otherwise, so
the reply is still short, still inside the budget, and still passes `persona_fit`.

### His day changes when the calendar does

`life.calendar` and `perceive.events` were built and read by nothing, so every "what are you up to"
for the rest of the year came from the same handful of activities. Now the nearest event becomes a
clause -- "opener tomorrow", "it is the hockey season" -- and `offer_hook` has a family for it.

Two details are load-bearing:

* **Calendar entries carry a `short` form**, exactly as activities carry a `hook`. `the season
  opener` is a title; "opener" is what a person says, and the full label does not fit a budget.
* **The family has a bare variant**, because a pleasantries budget allows one sentence.
  "{hook}. {event}" is two, so it can never fit and would silently fall back to the plain hook.

Priority is deliberate: recall outranks the calendar (a question about your dog matters more than
his week), and both fall back to the ordinary phrasing when the budget has no room rather than
going silent.

### Phase three: stories, and the point that only arrives if asked

A story is the one thing he may be longer than a sentence about, so the gate is the design.
`decide/story` says yes for exactly three reasons, and each is evidence rather than a mood:

| Mode | Evidence | Why it is fair |
|---|---|---|
| `asked` | "how did the fence go?" | the clearest invitation there is |
| `follow_up` | he offered a hook and they asked about it | the hook→detail→story chain the design was built around |
| `leaned_in` | two long turns in a row, and not while they are asking something | a friend offers a story at that point |

Two things are load-bearing:

* **The conversation carries what it is about.** His own turn records `ladder|job|topic|story_id`,
  so "how did that go?" reaches the story of the *thing he just offered*, and the next question
  can reach the point. Nothing else is stored: it lives in the transcript, which is where a
  conversation keeps things.
* **The point is a separate file.** `tell_story` renders the body; the point is reachable only
  through `explain`'s `point` family, which needs the story to have just been told. That is the
  whole difference between a story and a sermon.

Measured defects on the way: a story could not fit a pleasantries budget (so the stage went
silent); "how did the fence go?" was answered with the deer (fixed by a `words` field on each
story -- naming beats phrasing, again); "what was the point of that?" retold the story instead of
answering; and `persona_fit` rejected every story for "explaining itself", which is what a story
is for.

### Plans, so an invitation has somewhere to go

"doing anything later?" is its own intent now, because it is an opening for a *plan* rather than a
question about his day. He answers with the thing he would do with you:

```
what are you up to        → opener this week          (the calendar)
doing anything later?     → clear out the workshop sunday  (the plan)
```

The existing "you free?" machinery then takes over: accept, and `pending_plan` means the next
message is a confirmation rather than another "sounds good".

### What is still not built, in the order it matters

1. **Relating one thing to another.** A grievance is a swap, not yet a connection.

## 9. Risks

- **Telegraph.** Mitigation: `Abstain` everywhere; silence over improvisation.
- **Debugging.** Mitigation: the trace is mandatory, plus `conv --explain "hey"` printing the rungs.
- **Premature splitting.** Rule: split a module only when it fails its own test for two different
  reasons.
- **Wiring cost.** Mitigation: every module ≤ 60 lines, one export, and a manifest test that fails if
  the module list changes silently.

---

## 9. A statement that names a subject

Measured live on Otto, and it changed a rule. `my plant is dying` named `topic:plants`, and the
answer was `oh` -- the acknowledgement -- while his actual plant line (*"oh no, i am sorry.
tell me what the leaves look like"*) sat unused. But routing every subject-naming statement to
`explain` was worse: *"the train was late again"* got his own train line back
(*"i go when i can"*), which is a non-sequitur.

The rule that survived is about **whose thing it is**: a statement that names a subject he knows
**and** uses a possessive (*my*, *our*, *mine*) is about *their* thing, so he answers about it;
anything else is acknowledged. `govern/loop` passes `theirs`, `decide/job` decides, and the two
cases are tested.

---

## 10. Handing the turn back

A conversation where only one side asks is an interview. This is the slice that made the other
person's half of it real, and it started from a measurement: **`decide/reciprocate` -- the rung that
answers "does he hand the turn back?" -- was referenced by nothing but its own test.** The job that
would carry it, `ask_back`, was in the vocabulary and never chosen, and no phrasebook existed for it.
Three links missing in a chain that looked finished.

### The rule

One turn, one job -- so handing the turn back is not an extra message, it is a *choice of job*:

| | |
|---|---|
| which turn is worth spending | `noted` -- the job with the least to say ("yeah" to a statement he has nothing to add to) |
| who decides | `decide/reciprocate.ask_about_them()`, gated on the persona's `question_rate` |
| the wording | `phrasebooks/ask_back.json`, overridable per friend (`friend-b` has his own) |
| the register | a family of its own, `ask_back`, because every line is a question and the warm register holds statements too |

Three refusals, each for a reason: a rate of `0` means never; a **terse or flat** reply ("k", "fine") is
not an invitation, so asking "what about you?" into it is the interview problem in miniature; and
**never twice in a row**, read from whether his last turn ended in a question.

The roll is keyed on the message, so the same message always gets the same treatment and a replay is a
replay.

### What it looks like

Same five messages, both friends, their real rates:

| you say | Terry (0.2) | Otto (0.8) |
|---|---|---|
| i have been rebuilding a fence myself this month | `yeah` | `hmm, wh- what about you? ^^` |
| i finally finished the thing i was working on | `what about you?` | `wh- what have you been up to?` |
| i spent the weekend sorting the garage out | `nice` | `wh- what are you working on these days?` |

### The wellbeing question

The other half of "he listens": being asked how *he* is. `anyway how is your day going` was answered
with a hedge -- "oh, i do not know that one" -- because every pattern for that move had the word *you*
in it. The lexicon now covers the phrasings people actually use (`how was your weekend`, `how's your day
been`, `how you been`, `how are you holding up`), and fourteen of them are pinned by a test -- alongside
the four that must **not** match, because a question about a *thing* ("how is the fence coming along") is
not a question about him.

### Two bugs the live channel found

Both from one exchange on 2026-10-23, and both were invisible to 1,953 tests:

```
noodle: i have been rebuilding a fence myself this month
Otto:   what about you? ^^                     (ask_back)  correct
noodle: playing video games                    <- he ANSWERED the question
Otto:   wh- what have you been up to?          (ask_back)  asked again, and ignored the answer
```

**1. A question with an emoticon after it is not a question.** The "never twice in a row" rule read
`turn.text.endswith("?")`, and the style layer appends emoticons *after* the punctuation -- so
`what about you? ^^` looked like a statement and the rule never fired. Since Otto decorates about half
his lines, roughly half his questions were invisible to the rule that exists to stop him interrogating
people. The check now asks whether the **last sentence** contains a question mark, which is independent
of how a friend decorates a line.

**2. An `ask_back` turn recorded a subject of his own.** The turn's act is `ladder|job|topic|story`,
and this one carried `topic:trains` -- the subject left over from earlier -- so the next message
inherited it as a follow-up and "playing video games" was matched to *his trains* at 0.96. He had
asked about **them**, so nothing of his was under discussion; the act now carries no topic.

Held by six ladder tests (including four ways of decorating a question) and two supervisor tests that
walk the exact exchange.

### The third fix: engaging with the answer

The exchange still read wrong after those two, in a way the rules could not see:

```
Otto:   what about you? ^^        (ask_back)
noodle: playing video games
Otto:   ah, oh                    (noted)  correct, and useless
```

`noted` is the job for a statement he has nothing to add to, and something *they* said is not that. So
there is now **`follow_up`**: when there is something of theirs to pick up, that is what the turn is
for.

**Getting the triggers the right way round was the whole problem**, and the first version had them
backwards: it spent the turn asking "what about you? ^^" in reply to *"i have been rebuilding a fence
myself this month"* -- asking them what they were doing, one line after they had said what they were
doing. The two moves are:

| | signal | why |
|---|---|---|
| **`follow_up`** | they answered a question of his (`already_asked`), **or** they said something about themselves (`theirs` -- a first-person statement) | there is something of theirs to pick up |
| **`ask_back`** | **he** has just spoken about himself (his last turn was a hook, an explanation or a story) | "what about you?" is only natural after he has said something about his own day |

Both are gated by `question_rate`, so a reserved friend does neither and simply notes.

| | |
|---|---|
| the signal | `already_asked`, or a first-person statement from them |
| the bar | lower than asking out of the blue: `question_rate` is scaled by `ANSWERED_BONUS` (1.5) when they have just answered him, because being answered is a bigger opening than anything volunteered |
| the wording | `phrasebooks/follow_up.json`, overridable per friend (Otto has his own) |
| generic on purpose | there is no parser here, so the lines have to work for "playing video games", "i sorted the garage out" and "reading a book about trains" alike -- which is what a person does too |

It fires only when there is something of theirs in the message, so it cannot become a way to
interrogate somebody who was simply talking. Chained follow-ups are allowed, because *"is it any
good?"* after *"playing video games"* is engagement; the ledger is what stops him repeating a line
word for word. And it stands aside when there is something better to do: if a fact of theirs is in
play, the **recall** family wins, because asking after their dog beats a generic question.

```
Terry                                          Otto
what are you up to      -> opener this week      -> watching the trains        (offer_hook)
i have been rebuilding… -> yeah                  -> how long have you been at that?  (follow_up)
playing video games     -> nice                  -> oh nice ^^. how is it going?     (follow_up)
yeah it is pretty good  -> ah right              -> ah, oh nice ^^                   (follow_up)
the truck is in the shop -> fair enough          -> ah, oh                           (noted)
```

Two people, one ladder: Terry notes and rarely asks, Otto engages with almost everything.

### Two more bugs it exposed

* **An agreement is not a thank-you.** `yeah it is pretty good` was answered with `no worries`, because
  `agree` and `thanks` shared the `acknowledge` job. `agree` now goes to `noted` ("nice"), and
  `acknowledge` is only for the two moves that have a stock reply: thanks and apologies.
* **"One emoticon per line" had two wrong versions.** Checking only the final token let
  "oh nice ^^. how is it going?" collect a second mark after the question mark; stripping punctuation
  from every token turned ":3" into "3", so the mark went unrecognised and was appended anyway. A mark
  is now matched as a whole token with optional trailing punctuation -- `^^.` counts, `:3` counts,
  `3:30` does not.

### A bug the work found


A phrasebook variant that already ended in an emoticon got a second one appended by the style layer, so
a shy friend said `what about you? ^^ (◕‿◕)`. The pool *is* the vocabulary of those marks, so membership
in it is what the check tests -- not a hand-written list.

**Measured, both friends:** `ask_back` answers 108 of 108 attempts at median 3 words, 0% ending on a
beat, 5% distinct (repetition is the register). Held by five ladder tests, four persona tests and a
fourteen-case lexicon table.


---

## 11. Overfitting, measured

Every phrase in the material was written by hand, and every slice in §10 was debugged against real
conversations. That is how a system quietly narrows: the detectors get tuned to the examples the tests
also use, and the suite keeps passing while the system gets worse at everything else.

So there is a **held-out probe**: twenty ordinary messages, written down with what a person would do,
run through the live routing. `tests/test_generalisation.py` pins it, and refuses to let a probe message
become a phrasebook variant -- the moment it does, the probe stops measuring anything.

**First run: 13 of 20.** Every miss was in a *detector*, not in a mechanism:

| what happened | why | the general fix |
|---|---|---|
| `my cat died` → *"is it any good?"* | **sentiment was read only to rank knowledge items, never to route.** A bereavement was a neutral remark, and a first-person statement was therefore something to be curious about | negative sentiment now routes: about them → sympathy, about the world → a complaint to share. And `engage` refuses outright when the news is bad -- a guard, not a routing rule, so it holds even when the routing misses |
| `the boss is being a nightmare` → noted | the complaint lexicon knew a handful of phrases | same fix: sentiment decides, not the phrase list |
| `sorted the garage out`, `went for a run` → noted | **chat omits the subject.** The first-person detector needed a pronoun, so every subject-less statement looked like a remark about the world | a past-tense verb in front is the signal -- a linguistic category (`-ed` plus the common irregulars), not a list of our examples. `the game got cancelled` opens with a determiner and is correctly not about them |
| `are you free this weekend` → silence | a *plan* phrasing that did not fit the budget produced nothing | the special-register fallback now covers the trim stage and `plan` too: fall back to the ordinary phrasing rather than going silent |
| `i am going to bed` → noted | the closing pattern was anchored and its lead-ins did not include "i am" | lead-ins widened to how people actually open a goodbye |

**After: 18 of 20**, and both remaining are judgement calls rather than faults -- `i quit my job` can
legitimately be noted (the engagement roll misses one time in five) and `the game got cancelled`
commiserated rather than noted, which is better than what I had written down as the expectation.

The lesson is in the table: **the phrase lists were the overfitting, and sentiment plus syntax were the
generalisation.** A detector built on "words that look like a complaint" only ever knows the complaints
somebody thought of; one built on polarity knows the next one too.

### What is still narrow

* The **emotion vocabulary** is a lexicon. It will miss grief that does not use its words ("we said
goodbye to him on tuesday"), and the honest fix for that is the model, not more words.
* **Significance is not measured.** `i quit my job` engages only as often as `i got a new bike`, because
  the roll knows nothing about how big the news is.
* **English only**, by construction: past-tense detection, pronoun lists and the closings are all
  English shapes.
