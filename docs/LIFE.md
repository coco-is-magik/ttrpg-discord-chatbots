# Life: what the friends are actually doing

Why the previous approach read wrong, and what replaces it.

## 1. The diagnosis

These four lines were all *finished artifacts* — a setup, a turn, a button:

> "agrippa. won the war, built the city, handed the power back"
> "rangers, always. original six, and dont you forget it"
> "rome fell cause the men at the top stopped doing the work. same as anywhere. read the republic, then the empire, then tell me youre surprised"
> "i'd be lying if i answered that. lets find something i do know"

They are grammatical, informative and completely dead, because nobody talks like that. Every one
has **rhetorical shape**: a list of three, an imperative, a self-aware shrug. That shape is what
reads as written — not the vocabulary, and not the length.

The deeper problem: a bot with no life can only answer. Answering is what produces artifacts.
A person says what they are *in the middle of*, and the conversation grows out of that.

## 2. How people actually talk

Three phases, in order, and most conversations never leave the first two:

| | Phase | What it looks like | What it needs |
|---|---|---|---|
| 1 | **Pleasantries** | "hey", "yoooo", "what's cookin" | variety, and an opening rather than a status |
| 2 | **Transition** | something being done, a current annoyance, a small event | a life to draw on |
| 3 | **Substance** | a reason, a story, an argument, a plan | *reasons*, not facts |

Phase 3 is rare and cannot be forced. It happens when phase 2 lands on something the person
cares about and the other person asks a second question.

## 3. What a life is

An **activity** is something in progress, with three parts:

```jsonc
{
  "doing": "trying to get an old machine to boot off a disk i made myself",
  "phase": "it gets to the boot screen and quits",        // the snag, right now
  "why":   "because i want to know what it is doing, not just that it works"   // the reason
}
```

The `why` is the whole trick. A fact is true for everybody; a reason belongs to somebody. That is
what makes phase 3 personal instead of encyclopedic:

> **you:** why?
> **him:** because i want to know what it is doing, not just that it works

A **grievance** is a small standing complaint with an invitation to trade one, which is how
commiseration works:

> **you:** rough day at work
> **him:** yeah, i hear that. the truck failed inspection over a bulb. a bulb i replaced last month

Nothing in either sentence is information about the world. Both are information about *him*, and
both leave an obvious place for the other person to put their own.

Selection is **day-stable**: the same friend has the same activity all day, computed from the
date. A conversation that wanders away and comes back stays coherent, and a test can pin the
clock.

## 4. Stances became reasons

Every subject opinion was rewritten from a claim into a piece of personal history. This is the
change that does most of the work, and it is one edit per line rather than a new system:

| Before (claim) | After (reason) |
|---|---|
| "rangers, always. original six, and dont you forget it" | "been a rangers fan since i was about eight. my uncle got me a jersey two sizes too big and i wore it anyway" |
| "rome fell cause the men at the top stopped doing the work…" | "i read the roman stuff for the politics. i could not care less about the battles" |
| "the legions were fine. the men paying them stopped caring" | "what gets me is how long they saw it coming and did nothing about it" |
| "agrippa. won the war, built the city, handed the power back" | "agrippa. i like him because he did the work and let somebody else take the credit" |

They are less clever and more like a person. They also cannot be *wrong* the way a fact can,
because they are his opinion of his own reading.

## 5. What is built now

| Move | Rendered from | Example |
|---|---|---|
| "what are you up to" / smalltalk | today's activity | "fighting with an old computer. you?" |
| "rough day" / "long day" | today's grievance | "ha. same. karen from the office had a go at me because the printer is not her job. not her job!" |
| "why?" (whole message only) | the activity's reason | "because i want to know what it is doing, not just that it works" |
| a named subject ("how're the rangers doing") | his reason for caring | "been a rangers fan since i was about eight…" |

`sms` style still applies: lower case, dropped apostrophes, no full stop.

The move is chosen by the **classifier, context included** (`Replier.choose`), and life only
renders it — so a move the context rules out (a greeting after a goodbye) still gets vetoed, and
life cannot resurrect it.

## 6. What is not built, in the order it matters

1. **Stories.** `life.json` has a `stories` array and nothing reads it. A story is the phase-3
   kernel: three or four sentences about something that happened, with a point he draws from it.
   "I rebuilt my grandfather's axe; the head was fine and the handle was rotten" — and the point
   only arrives if asked.
2. **Plans becoming outings.** He can invite ("you free?") but has no plan to invite you *to*.
   A plan record (what, when, why he wants to) turns phase 3 into "let's do the thing".
3. **Current events.** He has no clock beyond the date: no "the game's on tonight", no weather, no
   "the shop closed down". A small calendar would give phase 2 something new every day.
4. **Relating one thing to another.** A grievance is a swap, not yet a connection. "Same thing
   happened to me when I rebuilt the fence" needs an activity and a grievance to be linked.
5. **Remembering what you said.** Long-term memory stores your name and what you ask about; it
   does not store that your dog is sick, which is the thing a friend would bring up next time.
6. **Escalation.** Phase 3 should only happen when the other person leans in twice. There is no
   "how interested is this person" signal yet.

## 7. How this is tested

- `tests/test_life.py` — activities validate, the pick is day-stable and differs across days, and
  a missing life file is empty rather than fatal.
- `tests/test_friends_chat.py` — "what are you up to" answers from life, "rough day" commiserates,
  and a move the context rules out is still ruled out.
- `tests/test_persona.py` — every signature line still appears in something he says.

The rule the tests encode: **life renders the move; it never chooses it.** The classifier owns
"what kind of thing is this", and the life layer owns "what is he doing today".


## The `hook` field

An activity carries four lengths of the same truth, and each is for a different question:

| Field | Answers | Example |
|---|---|---|
| `hook` | "what are you up to" | "rebuilding the back fence" |
| `short` | a second phrasing, for variety | "out back with the fence" |
| `doing` | what he is actually doing | "rebuilding the back fence before the weather turns" |
| `phase` | where it has got to | "half the posts are rotted at the base" |
| `why` | "why?" -- the reason, which is the part a fact bank cannot supply | "the old one leaned for two years" |

`hook` is deliberately three or four words. Measured: answering "what are you up to" with `doing`
produced a fourteen-word description, which is the monologue the whole design is trying to avoid.

## Stories, and the point

A story is `body` plus `point`, and the split is the design: `body` is what happened, and it is
only ever said when `decide/story` says the moment is right. `point` is what it meant, and it is
reachable **only** by asking what the point was, which is the difference between a story and a
sermon. `words` lists the names the story goes by ("fence axe garage handle"), so a question
that names the thing reaches the right story -- the same lesson as the entity index for
subjects: naming beats phrasing.

## Plans

A plan is `what` plus `when` in his own words ("get out to the range", "saturday") and `why`.
It exists so an invitation has somewhere to go: he could already ask whether you were free, and
this is the thing he was going to suggest.

## The material he actually has

Counted, because "enough" is otherwise a feeling: **5 activities** (each with a hook, a snag and a
reason), **6 grievances**, **6 stories** (each with a body and a separate point), **4 plans** (each with
a time and a why), and **39 subject lines** across ten interests -- at least four per interest, so the
second question about hockey is not the first one again. `ttrpg-chatbots-persona` checks the floor on
all of it, and `docs/PERSONA.md` §5a has the numbers.
