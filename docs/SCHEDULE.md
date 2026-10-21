# The day: an NPC schedule

How a friend always has something to be doing, so he has something to talk about.

## 1. The model

Borrowed straight from how a game gives an NPC a life: **a day is a list of blocks**, each naming
what he is doing and when. He is never nowhere.

- **15-minute slots.** Every block starts and ends on a quarter hour, so "what is he doing at 14:07"
  has exactly one answer, and "how far into it is he" is a number between 0 and 1.
- **Sleep is a block.** The only thing that makes it special is `"asleep": true`. That single flag
  is enough for the floor module to decide not to answer at 03:00.
- **Wall-clock time, system locale.** A person's day is local, not UTC: "coffee at half six" means
  half six wherever he is. Times are naive local; a schedule therefore survives a daylight-saving
  change unshifted, which is what a person expects.
- **Everything is data.** The whole point is to move his day towards a schedule that fits the
  human's, so the file is meant to be hand-edited and nothing about it lives in code.

```jsonc
{ "id": "workshop-morning", "start": "07:30", "end": "09:00",
  "doing": "out in the workshop", "days": ["mon","tue","wed","thu","fri"],
  "topics": ["topic:woodworking"] }
```

`topics` is the bridge to conversation: it says which subjects this part of the day belongs to, so
the hook stage can pull a woodworking thing to say at 08:00 and a hockey thing at 20:00.

## 2. Editing it

`Schedule.check()` exists so a half-edited file is not a mystery:

| Problem | Reported as |
|---|---|
| 09:50–10:10 | "not on a 15-minute boundary" |
| two blocks covering 10:00 | "one and two overlap" |
| a hole between blocks | "nothing between 12:30 and 13:00 — the default fills it" |
| a day that starts late | "nothing before 06:30" |

Gaps are not errors: the `default` block ("pottering about the house") fills them, and the slot says
`filled_by_default` so a later stage can be vaguer. That keeps the file usable while it is being
narrowed down, which is how it will actually get edited.

## 3. What it gives the conversation

| Question | Answered by |
|---|---|
| what is he doing right now? | `Schedule.at(moment).doing` |
| how far in is he? | `Slot.progress(minute)` — "just started", "still at it" |
| is he awake? | `Slot.asleep` |
| what could he talk about? | `Slot.topics` → the life hook picks from those subjects |
| is it morning for him? | `perceive/clock.Moment.part_of_day` |

Nothing in `life/schedule.py` decides anything. It answers questions; the decide band uses them.

## 4. What is built

- `src/ttrpg_chatbots/perceive/clock.py` — `Moment`: part of day, weekday, weekend, local time.
  The clock is injectable, so tests never depend on when they run.
- `src/ttrpg_chatbots/life/schedule.py` — `Block`, `Slot`, `Schedule`, `load_schedules`, `check`.
- `examples/friends_world/schedule.json` — 24 blocks: a weekday and a weekend day for `friend-a`,
  including sleep, and `topics` on the blocks where a subject is natural.
- `tests/test_schedule.py` — 12 tests: quarter-hour snapping, sleep at 03:00, weekday vs Saturday,
  a gap falling back, off-grid/overlap/hole reporting, progress, and the real file checking clean.

Example, on a Monday:

```
mon 03:12 -> 03:00-03:15 asleep                          progress 80%
mon 07:40 -> 07:30-07:45 out in the workshop             progress 67%
mon 14:07 -> 14:00-14:15 reading                         progress 47%
mon 20:15 -> 20:15-20:30 got the game on, or a book…     progress 0%
sat 09:00 -> 09:00-09:15 out on the water                progress 0%
```

## 5. Dynamics — deliberately later

A schedule says what *occupies* time. It cannot say what *happens*. These are the worthwhile
sidequests, in the order they'd pay off:

1. **Events that overlay the schedule.** A Rangers game at 19:00, a show airing at 21:00, a
   delivery expected. An `Event(start, end, subject, salience)` layered on top of a block turns
   "hockey or a film" into "the game's on, they're down one" — and it is the difference between a
   schedule and a life. It also needs a source: a hand-kept calendar file first, an API later.
2. **Weather.** One line a day ("rained all morning") is the cheapest possible current event, and
   it gives the grievance and hook stages something new every day without any authoring.
3. **Adapting to the human's schedule.** The stated goal over time: if the human is consistently
   around at 22:00, his evening should drift later. That means the schedule becomes *editable by
   the system* — a proposal module that watches when conversations happen and suggests block
   moves, with the file remaining the source of truth. It needs the schedule to be stable for a
   while first, or it will thrash.
4. **Consequences.** If he said he was going fishing on Saturday, Saturday's block should know.
   That is memory writing back into the schedule, and it is the point at which the two systems are
   genuinely one.
5. **Multi-day continuity.** "Still not finished" is what makes an activity feel real; it needs a
   block to be able to persist its state across days rather than restart every morning.

None of these are built. Item 1 is the one that changes the most for the least.
