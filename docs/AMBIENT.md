# The room: three friends talking to each other

The pass that gave the friends a conversation of their own, and a way to observe it without waiting a
week or hammering Discord. Written down because almost every decision here is a *number*, and numbers
are what a tuning pass needs to move.

---

## 1. What it does

With `TTRPG_CHATTER=1`, the three friends hold a rolling group conversation in one channel:

* one message every **five minutes on average**, drawn randomly rather than scheduled;
* nobody speaks twice in a row, and nobody speaks inside their own three-minute gap;
* nothing is said while they are asleep, and nothing is said outside a budget;
* they hear each other, so a message can react to the last thing another friend said;
* the human can join at any time, and does not have to be there for the room to keep going.

```
20:56 friend-c  Half watching an old series 🐠
21:01 friend-a  opener this week
21:04 friend-b  hmm, a- at the station
21:09 friend-c  Oh, that is lovely
```

Off by default. An unprompted bot is a surprise, and a surprise should be opt-in.

---

## 2. The rate is an average, not a metronome

`ambient/cadence.py` draws each gap from a **gamma distribution with shape 2** -- the sum of two
exponentials, which is the shape of "something happened, then somebody decided to say it". Measured over
20,000 draws at a 300-second target:

| | |
|---|---|
| mean | **299.2 s** |
| median | 250.3 s |
| 90th percentile | 581.9 s |
| longest | 1500 s (cut) |
| shortest | 45 s (floor) |
| under a minute | 6% |
| over ten minutes | 9% |

A room that speaks every 300 seconds exactly is a room nobody believes. A room with a median of four
minutes and a tail out to twenty-five reads as three people who are busy.

---

## 3. Bed time

`ambient/quiet.py`. Bed at the **earliest** of:

| rule | |
|---|---|
| 01:00 | the hard cap |
| an hour after the human's last message | |
| half an hour after the human says goodnight | |

Up **7-8 hours later**, drawn per night, and the first thing said after waking is a greeting -- once.

Two interpretations, both deliberate:

* **The human-relative rules only bite from 20:00.** Taken literally, "an hour after the human
disappears" would put them to bed at three in the afternoon on a quiet day.
* **Once asleep, nothing moves bed time.** A message at 03:00 does not wake the room; the alternative is
friends who can never be asleep.

---

## 3b. The room's day is *local*, and silence explains itself

Two things the first live evening got wrong, both worth keeping.

### The clock was UTC

At **21:24 EDT the room put itself to bed** and went silent for the evening. The schedule was being
evaluated in UTC, where the same moment is **01:24** -- past the hard bedtime, so the friends went to
bed at nine in the evening and would have woken at five in the morning.

```
local 2026-10-23 21:24 EDT (-0400)
  utc 2026-10-24 01:24 UTC
  the room decided: bed 2026-10-24 01:24 to wake 08:32      <- the bug
```

A person's day is the one on the wall. `docs/SCHEDULE.md` already said that about the friends' own
schedules; the room now follows the same rule (`bots/conversation.py::local_now`), and so does the
simulator's default start.

### Silence said nothing about why

Before the fix, two messages and then nothing was **indistinguishable from a dead loop**. There are now
three log lines that make a quiet room explain itself:

```
21:26:44  next message at 21:30 (waiting until 21:30)
21:30:44  friend-b said it unprompted (chat): watching the trains
21:30:44  next message at 21:40 (spoke as friend-b; next at 21:40)
```

and if the room goes quiet for longer than twice the longest draw, a warning with the director's reason:

```
the room has been quiet for 26 minutes: asleep (bed 2026-10-23 23:05 to wake 06:19)
```

The director keeps a `reason` at every early return -- *asleep*, *budget spent*, *waiting until HH:MM*,
*nobody may speak yet*, *<friend> had nothing to say* -- because "the room is quiet" and "the room is
broken" are the same observation from outside.

### And the tail was cut

The longest gap was 25 minutes, which at a five-minute average is one draw in sixty -- and one of them
was enough to look like a dead bot. The cap is now **12 minutes**: still a real tail (2.4x the mean, and
the distribution is untruncated below it), but the room can no longer go quiet for long enough to look
broken.

---

## 4. Anti-chorus

`social/inclusion.py`, three rules:

1. **Nobody speaks twice in a row.** A friend answering themselves is the clearest tell there is.
2. **Nobody speaks inside their own gap** (3 minutes), whatever the cadence drew.
3. **The most overdue friend is favoured, weighted not enforced** -- and the weight is *capped at half
   an hour*, because a friend who has never spoken is infinitely overdue and an uncapped weight made
them the speaker every single time. That is a strict rotation wearing a different hat.

---

## 5. The one content rule this pass needed

They *heard* each other and immediately got stuck acknowledging each other: the first simulation produced
**169 messages of "yeah", "mm" and "ah, oh" in a loop**. The fix is structural and lives in the director,
not in anybody's speech:

> **If the last thing said was an acknowledgement (under four words), do not acknowledge it -- talk about
your own day instead.**

That is the difference between a room and three people being polite at each other, and it is why the
simulated room now reads like this:

```
09:05 friend-b  watching the trains
09:11 friend-c  Half watching an old series 🐠
09:14 friend-a  yeah
09:21 friend-b  hmm, a- at the station
09:25 friend-a  opener this week
10:22 friend-a  rebuilding the back fence, opener this week
```

No phrasebook was changed to achieve this, which was the point of the pass.

---

## 6. Discord, and not getting in trouble

| concern | what we do |
|---|---|
| message rate | one message per **45 s floor**, one per 5 min average. Discord's bucket is five per five seconds per channel, so we are three orders of magnitude inside it |
| burst after a bug | `ambient/budget.py`: **20 per hour, 260 per day**, checked before every send |
| retry loops | the budget is upstream of the send; the sender counts failures rather than retrying |
| other people's bots | only **our own roster's** bot ids are heard. A stranger's bot cannot start a reply loop with us |
| unprompted posting | opt-in (`TTRPG_CHATTER=1`), and one channel (`TTRPG_CHATTER_CHANNEL`, else the first configured friend channel) |
| the human's own rate | unaffected: a mention still gets an answer as it always did |

---

## 7. Simulating a week in two seconds

```bash
ttrpg-chatbots-simulate --hours 24 --seed 11 --start 2026-10-24T09:00
ttrpg-chatbots-simulate --hours 168 --seed 2 --out /tmp/week.jsonl
ttrpg-chatbots-simulate --hours 6 --friends friend-a,friend-c --quiet
```

No Discord, no network, no audio, no database (memories are in-memory so a simulation cannot touch the
live one). **The same director and the same ladder run in both places**, so a simulated week is evidence
about the live room rather than about a second implementation of it.

Measured: a **24-hour day produces 169 messages** (7.0/hour, mean gap 8.5 minutes, split friend-a 56 /
friend-b 59 / friend-c 54) in about a second. A week is about 1,100 messages.

---

## 8. Where it lives

| module | the one question |
|---|---|
| `ambient/room.py` | who said what, when, and who has been quiet longest |
| `ambient/cadence.py` | when does the next message happen? |
| `ambient/quiet.py` | is the room asleep? |
| `ambient/budget.py` | how much may the room say? |
| `ambient/director.py` | who speaks, and what about? |
| `ambient/simulate.py` | run it faster than real time |
| `ambient/cli.py` | `ttrpg-chatbots-simulate` |
| `social/inclusion.py` | who is allowed to speak? |
| `bots/conversation.py` | the only part that knows about Discord |

---

## 9. Tuning it

| you want | change |
|---|---|
| a faster or slower room | `--mean` in the simulator, `Cadence(mean_seconds=...)` live |
| a longer or shorter tail | `SHAPE` in `cadence.py` (higher = more regular) |
| a stricter floor | `MIN_GAP_SECONDS` |
| earlier or later bed | `HARD_BED`, `AFTER_HUMAN`, `AFTER_GOODNIGHT`, `EARLIEST_BED_HOUR` |
| less chatter overall | `PER_HOUR` / `PER_DAY` in `budget.py` |
| a friend who speaks less often | nothing yet -- speaker choice is by quietness, so the tuning knob is the *persona*, not the room |

**What is deliberately not built:** none of this changes *how* they speak. The words still come from the
same ladder, phrasebooks and life as a one-to-one conversation, which is what makes this pass a
foundation for tuning rather than a rewrite.

## 8. The overnight run — the first dataset

### 8.1 What Discord's rules actually are

Checked against Discord's own rate-limit page rather than folklore. The documented hard numbers:

| Rule | Documented value |
|---|---|
| Global | **50 requests/second** per bot, independent of any route |
| Per-route | varies by endpoint and method; the docs are explicit that these **"should not be hard coded"** — read `X-RateLimit-Bucket` and the reset headers instead |
| Invalid requests | **10,000 per 10 minutes** of `401`/`403`/`429` earns a temporary Cloudflare ban |
| 429 with `X-RateLimit-Scope: shared` | does not count against the invalid-request budget |

Against our target:

```
  target      : 12.0 messages/hour = 0.0033 requests/second
  worst case  : 20.0 messages/hour = 0.0056 requests/second (the hourly cap)
  global limit: 50 requests/second  ->  we are ~9000x under it
```

The three rules that matter for staying inside the invalid-request budget, all of which the design already
follows: **the budget is checked before every send** (so we never discover a limit by hitting it), **a failed
send is counted, never retried** (so an error cannot become a loop), and **the channel is fixed and
audited at startup** (so a `403` is found by the audit, not by a message).

### 8.2 The switches

```bash
TTRPG_CHATTER=1                 # the room talks at all
TTRPG_CHATTER_SLEEP=0           # bedtime off, for a run that wants the small hours
TTRPG_CHATTER_LOG=data/chatter.jsonl
```

`TTRPG_CHATTER_SLEEP=0` logs that it is off at startup, so a quiet night is never a mystery.

### 8.3 The transcript

The room is the only place that knows the whole conversation, so the room is where the dataset comes from:
one `on_say` hook, called for every line whoever said it. Each line is `{at, speaker, kind, text}`, and the
file opens with a **header** carrying the settings, the friends, the cadence and the commit — because a
dataset without its settings is a pile of sentences rather than a baseline.

### 8.4 Reading it

```bash
tools/analyse_chatter.py data/chatter.jsonl
tools/analyse_chatter.py /tmp/week.jsonl --top 8      # a simulated week, same format
```

It reports rate and gaps, **how much of the conversation is content** (lines of three words or fewer),
**repetition** including immediate repeats, the **job mix read from the ladder's own trail**, dead ends, and
an hourly histogram.

### 8.5 The baseline — a simulated day

What the simulator says a day looks like, as the reference the live run is compared against:

```
202 lines over 23.9h (8.5/hour)
  friend-c 75 (37%)  friend-b 74 (37%)  friend-a 53 (26%)
  gaps: mean 7.1 min, median 6.0, p90 12.0, longest 42.0; 17% over 10 min
  words: median 3, mean 3.9, max 7;  53% are three words or fewer
  distinct: 21 of 202 (10%);  immediately repeated: 0%
  job mix: offer_hook 53%, noted 47%          <- two jobs, not thirteen
  dead ends: 11 of 202 (5%)
```

Two findings that the dataset exists to surface, both visible in the simulator before the live run:

1. **Only two jobs ever fire.** With no human in the room the director's prompt is always "your own day"
   (`offer_hook`) or a reaction to a short line (`noted`). `follow_up`, `ask_back`, `mirror`, `explain`,
   `tell_story` and `reply` are all reachable and never chosen, because nothing in the room asks a question
   or says something worth explaining.
2. **The rate is 8.5/hour against a 12/hour target**, and the cause is not the cadence: the ladder abstains
   roughly one slot in five, mostly `offer_hook` with nothing left to offer. That is a *content* limit
   showing up as a *rate* symptom — exactly the kind of thing a long run measures and a conversation
   cannot.

Both are content and director-prompt questions, not speech-pattern ones, which is why this pass changed no
phrasebook.

### 8.6 A bug the first transcript exposed immediately

Every line was written **twice**, at the same instant in two timezones: the director records what it said
(local time) and each listening friend records what it heard (Discord's timestamp, UTC). The room's own
window held each line twice as well, which is what the ladder reads when it decides what the last thing said
was. `Room.add` now compares *instants* for the same speaker and text, with a 30-second window — below the
45-second cadence floor, so a genuine repeat can never be inside it.

### 8.7 Keeping it up

An overnight run that dies at 2am is six hours of missing data nobody notices until morning. Two crashes in
one week made that worth fixing:

```bash
tools/watch_bot.sh          # reports "up", or restarts and says so
```

It checks the **process table**, not the pid file — a crash leaves the pid file stale, so trusting it would
report a dead bot as healthy. To run it every ten minutes:

```bash
(crontab -l 2>/dev/null; echo "*/10 * * * * $PWD/tools/watch_bot.sh >> $PWD/data/logs/watchdog.log 2>&1") | crontab -
```

A restart writes a `{"kind": "start"}` marker into the transcript, so a gap in the data can be told from a
silence in the room.
