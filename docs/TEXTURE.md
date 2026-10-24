# Texture

How a reply is *made*, as opposed to what it says.

## 0. The problem this exists to fix

The conversation layer decides well and still reads canned. Measured, from the first dataset
(`DATASET.md`): 260 messages a day from a **register of 25 distinct lines**, one job chosen per turn, and
**half the lines three words or fewer**. The reason is structural, not lexical:

> **The atomic unit of decision is a whole message.** `govern.loop` returns one `Line`, and delivery sends
> it. So the same situation always produces the same *sentence*, and a bigger corpus only makes the canned
> line arrive less often -- never not at all.

Everything in this document shrinks the unit. A turn becomes a set of **parts**, parts become
**fragments**, fragments are **packaged** into one or more messages, and the packaging varies with a
**condition** (tired, rushed, excited, on a phone). The words can stay the same and the *texture* changes,
which is what a person actually notices.

Two honest limits, stated up front:

* **Combinatorial variety from a small part-corpus is variety, not humanity.** It buys a lot (§1.3) and it
  is not the ceiling.
* **The ceiling is a model rendering inside these constraints.** Everything here is the constraint layer --
  what a model is *allowed* to say, and the fallback when there is no model. That is why the work is worth
  doing either way, and why none of it depends on the model decision.

## 1. Area one: the unit below the message

### 1.1 Parts

A turn is a set of parts. Six kinds, each a job in its own right:

| Kind | What it is | Examples from the current register |
|---|---|---|
| `reaction` | the beat before the substance | `oh nice`, `hmm`, `ha` |
| `content` | the substance | `Messing with the tank` |
| `question` | the hand-back | `how is otis doing?` |
| `emoji` | a non-verbal fragment | `🐠`, `(＾▽＾)` |
| `aside` | a self-interruption, a trailing thought | `anyway`, `wait` |
| `correction` | a revision of a fragment already sent | `*the garage, not the shed` |

That last one is the "agonising over every syllable" case: a person sends, re-reads, and *fixes* -- which is
a fragment kind, not a special case in the delivery code.

### 1.2 Where parts come from, first

**Derived before authored.** `Messing with the tank. how is otis doing?` is already a `content` plus a
`question`; today it is one string that always arrives as one message. Splitting existing variants on
sentence and clause boundaries gives parts for free, so the packaging layer can be built, measured and tuned
before a single phrasebook is rewritten. Authored parts (a variant written as a recipe) come later, per job,
as the register is expanded.

### 1.3 Why this multiplies

One job with 6 variants and 3 part-shapes each is not 6 lines. It is 6 texts x 3 packagings x 3 pacings x 2
(edit or not) -- and the *packaging* is what a person reads as "not a bot", because a bot's tell is that it
always says one tidy thing at a time.

### 1.4 Modules

| Module | The one question | Contract |
|---|---|---|
| `conv/parts.py` | what is a part? | value types only: `Part(kind, text)`, `Turn(parts)` |
| `parts/derive.py` | what parts does this text already have? | `Line` -> `tuple[Part, ...]` |
| `parts/recipe.py` | what shape should this turn take? | `job + state` -> `tuple[PartKind, ...]` |
| `render/fragment.py` | what words fill this part? | `PartKind + job + friend` -> `Part` |

## 2. Area two: delivery

The same parts, sent differently. This is where "typing style" stops meaning *how the letters look* and
starts meaning *how the messages arrive*.

| Module | The one question | Contract |
|---|---|---|
| `deliver/split.py` | one message or several? | `Turn + Condition` -> `tuple[Message, ...]` |
| `deliver/pace.py` | how long between them? | `Message + Condition` -> `seconds` |
| `deliver/revise.py` | send it, or send it and fix it? | `Message + Condition` -> `Revise(none, edit, follow_up)` |
| `perceive/assembly.py` | is this one thought or three? | `sequence[Utterance]` -> `Utterance` |

**Splitting** is driven by the parts, not the length: a `reaction` and a `content` are the natural split
(`oh nice` then `Messing with the tank`), two `content` parts stay together unless the condition is *rushed*,
and an `emoji` on its own is a legitimate message -- which is the "images and emojis" behaviour two of the
three briefs ask for.

**Pacing** is the second half of the same thing: a person types for as long as the message takes and pauses
between thoughts. Discord shows a typing indicator, so the pacing is visible rather than an unexplained gap.

**Revision** is the send-then-edit case: a typo fixed, a word changed, a thought corrected -- always *before*
the next message, so the correction lands where a person's would.

**Assembly** is the reverse direction and the one that is purely a *behavioural* gap: the system currently
treats each human message as a complete turn, so somebody who sends one thought across three messages looks
like three separate statements. A short debounce window (a few seconds, plus a length heuristic) makes it one
turn. Testable with a fake clock and no Discord at all.

## 3. Area three: loops

Necessary however good the register gets, and measurable against the data we already have: the six-line cycle
in `DATASET.md` §5 is a real, recorded example to test against.

| Module | The one question | Contract |
|---|---|---|
| `govern/cycle.py` | is this conversation going in circles? | `Room.tail + acts` -> `Cycle(period, kind, speakers)` or `None` |
| `govern/break_cycle.py` | what should change? | `Cycle + state` -> `Strategy` |

**A loop is a repetition of *shape*, not of words.** The recorded cycle has 0% immediate repeats, so text
comparison finds nothing; what repeats is the *act sequence* (`offer_hook, follow_up, hedge, noted, mirror,
noted`) with a period of six.

**Breaking is not always changing the subject.** Four strategies, and two of them keep the loop:

| Strategy | When | What it does |
|---|---|---|
| `play` | both parties idle/low-energy and the loop is short | leans in -- repeats back deliberately, emoji ping-pong, turns it into a game |
| `escalate` | one party has something new to say | adds a fact (a hook, a story) the loop cannot absorb |
| `withdraw` | the loop is long and nobody is enjoying it | says less, longer gaps, lets it die |
| `invite` | the human is present and silent | hands the turn to the human (see §5) |

The first row is the insight a naive detector gets wrong: *two people sending emojis back and forth for ten
minutes is not a bug, it is the game.* So `cycle.py` reports, and `break_cycle.py` is allowed to answer
`play` or `carry_on`.

## 4. Area four: communication errors

Understanding perfectly and answering correctly every time is itself a tell. Four modules, all fed by one new
piece of context.

| Module | The one question | Contract |
|---|---|---|
| `perceive/condition.py` | how is this person typing right now? | `clock + schedule + their message + subject` -> `Condition` |
| `render/typo.py` | what does a mistake look like here? | `text + Condition` -> `text` |
| `decide/misread.py` | what did he think they meant? | `Utterance + Condition` -> `Utterance` or `None` |
| `decide/feeling.py` | how much does he care about this? | `subject + persona.taste` -> `Feeling` |

`Condition` is the spine: **rushed** (their message was short and fast), **tired** (late in their day, per the
schedule), **fresh** (morning, per the schedule), **device** (phone: shorter messages, more typos; keyboard:
fewer), **stakes** (silly subjects versus serious ones), and **feeling**. Typo rate, message length and pacing
all read it, so "typos" stops being a constant and becomes a *behaviour that varies with how the day is
going* -- which is the thing a reader unconsciously checks for.

**Misreading is the interesting one.** Today every unparsed message gets a hedge, which is correct and
robotic. A person misreads *plausibly*: they answer the question they thought they heard, and the other person
corrects them. That is a two-turn behaviour, which means it needs the loop machinery from §3 to be
recoverable -- a misread that cannot be corrected is just a bug with extra steps.

**Feeling is already data.** Each persona has `taste` and `favourites` (`PERSONA.md` §1b): Terry on TempleOS,
Otto on trains, Crusty on hermit crabs. "Excited" is therefore *not* a dice roll -- it is "this subject is in
his favourites and he is fresh", and it raises typo rate, message length and speed together, because that is
what excitement does to typing.

## 5. Area five: involving the human (deliberately last)

Deferred, and the reason is in the caveat itself: **a lurker must not be punished for lurking.** The ambient
room already carries on without the human, which is right. What is missing is the opposite direction, and it
is the bug the first dataset already found (`DATASET.md` §7): **the friends asked "how is otis doing?" eight
times with nobody there to answer.**

| Module | The one question |
|---|---|
| `invite/presence.py` | is there a human here, and how present are they? |
| `invite/open_door.py` | is this a good moment for a low-stakes invitation? |
| `invite/pester.py` | has he already tried, and how often is too often? |

The rule to write down now, so the modules have something to obey later: **an unanswered invitation is
information, not a prompt to try again.** No more than one open door at a time, never two in a row, and never
about an absent person.

## 6. Slice order

| Slice | What | Why here |
|---|---|---|
| **A** | `conv/parts.py`, `parts/derive.py`, `deliver/split.py`, `deliver/pace.py`, `perceive/assembly.py` | the foundation: parts, packaging, and handling a human's split thought |
| **B** | `parts/recipe.py`, `render/fragment.py` | authored shapes, so the packaging is chosen rather than derived |
| **C** | `govern/cycle.py`, `govern/break_cycle.py` | provable against the recorded loop in `DATASET.md` §5 |
| **D** | `perceive/condition.py`, `render/typo.py`, `decide/feeling.py` | one spine, three consumers |
| **E** | `deliver/revise.py`, `decide/misread.py` | the two that need the rest to be recoverable |
| **F** | `invite/*` | §5, once the foundations hold |

## 7. How much further, before the corpus is the only answer

Measured against the data we already have, with no new content:

| Lever | Now | Available | What it multiplies |
|---|---|---|---|
| **Jobs in use** | **2 of 13** (`offer_hook` 50%, `noted` 48%) | ~9 usable with no human present | *situational fit* -- the right kind of line for the moment |
| **Multi-part lines** | **11-17%** of the register (105 lines, 30 families) | authored recipes, and multi-part variants in the jobs that fire | *texture* -- one thought arriving in 1-3 messages |
| **Schedule into the hook** | **5 activities** | **24 blocks a day, 8 topics**, plus the calendar | *situational specificity* -- he is doing the thing the clock says |
| **Condition** | constants: 5% typo, 50% stutter, 45-60% emoji | 4-6 states (tired, fresh, rushed, silly, serious) | *how the same words read* -- variance where there is now a fixed rate |
| **Loops** | closes on a 6-line cycle | detected, then broken or *played* | removes the dominant failure, and adds a new interaction type |
| **Revise / misread** | none | two new event kinds | ~15% of turns become something that has never happened |
| **Memory of the day** | none | prevents repeating what he already said today | preserves perceived variety |

The arithmetic is roughly **4 x 3 x 5 x 4 ≈ 240x**. That number is real and it is not what a reader feels,
because of one asymmetry:

> **Combinatorial variety is arrangement variety.** A reader notices repetition of *meaning* far sooner than
> repetition of *arrangement*. Thirteen jobs x four shapes x five conditions on the same 25 meanings is a
> thousand arrangements of twenty-five ideas, and the twenty-five ideas are what a person is tracking.

So the honest estimate: the levers above buy **3-5x in felt variety**, not 240x. That is still a lot -- it is
the difference between a loop and a conversation -- and it is about **six pieces of work**, none of which is
content: the director's prompts, recipes, the schedule wiring, conditions, loops, and assembling a human's
split thought.

### Where the wall actually is

Not "the corpus is small". It is that the content is **closed**:

* 5 activities, 4 grievances, 4-6 stories, 3-4 plans per friend;
* ~40 knowledge items per friend, 4-5 per interest;
* 30 families per friend, and the two that fire are the two with the least texture.

The wall arrives the first time a reader has heard *all of a friend's opinions about his own interests*. After
that, every further turn is a re-arrangement of something already said, and no amount of shape hides it.

### The three things to do when we get there

1. **Expand the corpus.** Linear effort, and diminishing: 100 lines to 500 buys perhaps 2x felt variety,
   because the *shape* of the content repeats even when the sentences do not.
2. **Draft the corpus offline with a model, and vet it.** Cheap, scales the same way as (1) with less typing,
   and has exactly the same ceiling -- it is still canned lines, just more of them.
3. **Put a model in the render position.** The architecture already anticipates this: the ladder computes the
   constraints (job, budget, depth, subject, condition), a model picks the words inside them, and the
   classifier corpus stays as the style guide and the fallback. That is the only option that is not bounded by
   what somebody typed into a JSON file.

### The instrument, so this is not a guess

The number that says "the corpus is now the binding constraint" is the **repeat interval of a
(job, subject/topic) pair** -- how long before a friend says the same *kind* of thing about the same *thing*
again. The trails record both, so a conversation can be scored. On two simulated days:

```
repetition of meaning (job x topic, from the trails)
  6 distinct pairs over 546 turns (1%)
  first-time in 6h: 6 of 546 (1%)
  repeat interval: median 22.0 min, shortest 0.1, longest 219.0
```

**Six meanings, on a 22-minute cycle.** After the first six turns of a day, every turn is a rerun of one of
six beats -- and the median rerun lands inside a single session. That is the wall, measured, and it is closer
than the multiplier arithmetic above suggested. It also says exactly what to move: the pair count is
`jobs x topics`, so the director's prompts and the schedule wiring raise it, and the corpus is what bounds it
from below.

One caveat, because it matters for reading the number: this is the **humanless room**, where nothing introduces
a new topic. A conversation with a human has a far larger meaning space (the human brings subjects, and each
friend has ~40 knowledge items), so the same instrument should be run on a transcript with a human in it
before drawing conclusions about the human-facing case. The live transcript will have trails from the next run.
