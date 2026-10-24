# The first dataset

What the overnight run said, and what to do about it. The run itself is documented in `AMBIENT.md` §8; this
is the reading of it.

## 1. The run

| | |
|---|---|
| started | 2026-10-23 22:08 local, one process, four bots at 8/8 |
| settings | mean gap 300 s (12/hour), bedtime off, channel `#general` |
| transcript | `data/chatter.jsonl` — header, then one line per utterance |
| read it with | `tools/analyse_chatter.py data/chatter.jsonl --top 8` |

## 2. The numbers

| | live night (11 h) | simulated day, before | simulated day, after the fix |
|---|---|---|---|
| messages | 67 | 224 | **260** |
| rate | 6.1/hour | 9.3/hour | **10.9/hour** |
| per speaker | 29 / 29 / **9** | 75 / 74 / 53 | **87 / 87 / 86** |
| gaps: mean / p90 / longest | 10.0 / 23.7 / **35.0** min | 7.1 / 12.0 / 12.0 | **5.5 / 10.0 / 12.0** |
| over 10 min | 38% | 17% | **9%** |
| three words or fewer | 28% | 53% | 50% |
| distinct | 39% | 10% | 10% |
| jobs used | 2 | 2 | 2 |

The target was 12/hour. The fix in §3 takes it to 10.9, which is the tail of the distribution rather than a
separate problem.

## 3. Finding one: bedtime was only half switched off

**The single biggest thing in the dataset.** `TTRPG_CHATTER_SLEEP=0` stopped the *room* from sleeping but not
the *friends*: `decide/floor` reads each friend's own schedule, and Terry's puts him to bed at 23:00. Otto and
Crusty have no schedule entry, so they never slept.

The evidence, from the log:

```
58  friend-a had nothing to say
30  spoke as friend-c
29  spoke as friend-b
 9  spoke as friend-a
```

and then, once the director stopped throwing the reason away:

```
52  friend-a had nothing to say: he is asleep
```

Terry spoke nine times, all before 23:00, and was silent for the remaining ten hours. **The log said "the
ladder abstained", which was true and useless** — the ladder was fine, the schedule was the cause. The
director now keeps the ladder's own reason, which is why this took one command instead of an afternoon.

Fixed by giving the ladder an `obey_schedule` flag, set from the same variable the room uses, with the parsing
in one place (`conversation.sleep_enabled()`) because two parsers of one variable had already drifted. A
simulated day goes from 224 to **260** messages and from 9.3 to **10.9/hour**, with an even 87/87/86 split.

A second lesson from the same investigation: **replaying the transcript could not reproduce it.** Pushing the
night's 68 lines back through Terry's ladder, he answered 68 of 68 — because the cause was live-only state
(his schedule) rather than anything in the conversation. A replay is not a reproduction.

## 4. Finding two: the room only uses two jobs, out of thirteen

```
offer_hook  49.6%
noted       47.7%
hedge        2.3%
```

`greet`, `acknowledge`, `mirror`, `reassure`, `explain`, `tell_story`, `ask_back`, `follow_up`, `decline` and
`close` are all reachable and never chosen. The cause is the director's prompt, not the ladder: with nobody in
the room, every turn is either "say something about your own day" (`offer_hook`) or "react to that short line"
(`noted`). Nothing ever asks a question, names a subject, or says something worth explaining.

This is the next thing to fix, and it is a **prompt** problem in `ambient/director.py::_prompt`: the room needs
turns that invite a *subject* (reaching `explain`), a *story* (which needs depth ≥ 2), and a *question*
(reaching `ask_back`/`follow_up` and giving the others something they can answer).

## 5. Finding three: a six-line loop, and why it closes

From the transcript, verbatim, repeating from 00:04 until the run ended:

```
friend-c  Messing with the tank. how is otis doing? ♡
friend-b  hmm, ho- how long have you been at that?
friend-c  Oh honey, i do not know that one 🌿
friend-b  ah, oh nice ^^
friend-c  Mm, i hear you honey 🌊
friend-b  ah, oh
```

Nobody introduces information, so nothing can change. Three separate mechanisms hold it shut:

1. **`follow_up` asks a question the other friend cannot answer.** "how long have you been at that?" is about
   *their* activity, and a friend has no data on another friend's duration — so it always meets a hedge.
2. **The hedge is treated as something to acknowledge**, which produces `noted`, which produces a
   commiseration, which produces another `noted` — and the cycle is back at the top.
3. **Nothing in the prompt ever introduces a new fact.** `offer_hook` re-offers the same two or three
   activities ("Messing with the tank" x26, "re- rearranging my shelf" x23) because the hook is drawn from a
   five-item life with no memory of what was already said today.

Repetition itself is intended — a person reuses their phrasing — but a *closed* loop is not. The discriminator
in the data is **immediate repeats: 0%**, so the repeat guard is working; a cycle of six distinct lines is
simply not what that guard measures.

## 6. Finding four: half the lines carry nothing

50% of lines are three words or fewer (`ah, oh` x22, `yeah` x18, `mm`). A room that is technically alive and
says nothing. Some of this is the two-job problem (§4) — `noted` is a job whose whole purpose is a short
acknowledgement — and some is the small register: 10% distinct over 260 lines.

## 7. Finding five: they ask about a person who is not there

`how is otis doing?` appears **eight times**, appended to a hook: *"Messing with the tank. how is otis
doing? ♡"*. The recall family fires from the human's memory — and with no human in the channel that is eight
questions nobody can answer, each pulling the conversation into the same hedge-acknowledge cycle (§5).

The fix is a gate rather than content: **recall should require the person it is about to be present** — or at
least not fire more than once a session, which is the rule it already applies in a live conversation.

## 8. What the dataset could not tell us

**The live transcript had no trails.** The simulator records the ladder's own trail on every line; the live
path did not, so the job mix in §4 had to be inferred from the words — and "ah, oh" twenty-two times does not
say whether that was `noted` or `acknowledge`. Fixed: `Said` carries the trail, the director passes it, and the
transcript records it. The next run answers §4 and §5 directly.

## 9. What to do next, in order

1. **Give the room prompts that invite subjects, stories and questions** (§4) — the one change that unlocks
   ten unused jobs.
2. **Gate recall on the human being present** (§7) — cheap, and it removes a class of unanswerable questions.
3. **Make `follow_up`'s questions answerable by another friend** (§5.1).
4. **Give each friend a memory of what they already said today**, so `offer_hook` stops re-offering the same
   activity (§5.3). The same "said twice" machinery the human memory already has.
5. **Content depth** — more life items and more register per job (§6), once 1–4 have stopped the loop from
   being the dominant shape.

Items 1–4 are structural and testable offline with `ttrpg-chatbots-simulate` + `tools/analyse_chatter.py`. The
metrics to move are the **job mix** (more than two jobs) and the **cycle length** (a loop that does not close).
