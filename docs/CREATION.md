# Creating a character, in Discord

The terminal wizard (`ttrpg-chatbots-character --new`) already does this, and its **flow** is
right: prose first, then numbers. What it cannot do is be interrupted, resumed over a week, or
shared with a GM. That is what the Discord version has to solve, and it is a different problem
from rendering a sheet.

This document is a plan, not a description of code that exists. The `/pool`, `/edit`,
`/ability`, `/background`, `/specialty`, `/answer`, `/story`, `/undo`, `/done` and `/unlock`
commands that a build stands on **do** exist.

---

## 1. The gap this has to close first

The sheet has two currencies — `freebies` and `xp` — and neither is how a character is *built*.

Per the rules, creation spends **group budgets**: attributes 7/5/3, abilities 13/9/5, virtues 7,
backgrounds 5. Each budget must be assigned to one group and spent exactly. Freebie points
(15 + flaws) are a separate pool for topping up afterwards; XP is for advancement.

`raise_trait` charges freebies per point. That is the *advancement* shape. Using it for creation
would let a player buy a fourth attribute dot with freebies instead of assigning the 3-budget,
which is not the game's arithmetic — and the totals would never add up to a legal character.

So creation needs a **build state**: which budget went to which group, and what is left in each.
It is a creation-time artefact, so it lives on the `Character` (not the `Sheet`), and is archived
on seal rather than deleted:

```python
Build(
    attributes={"Physical": 7, "Social": 5, "Mental": 3},   # which group got 7, 5, 3
    abilities={"talent": 13, "skill": 9, "knowledge": 5},    # which got 13, 9, 5
    virtues=7, backgrounds=5,                                     # scalars
)
```

**The assignment is the player's choice**, not a fixed table: "you may spend seven points in one
group, five points in one group, and three in the remaining group". `/budget` moves the shares,
and because re-assigning can strand an existing spend, it refuses an assignment the current
sheet would overspend.

**Morality and Willpower are derived while building**: "MORALITY begins equal to Conviction +
Self-Control", "WILLPOWER begins equal to Courage", so spending a virtue moves both — and
sealing freezes them. "Increasing Conviction or Self-Control later does not increase Morality"
is why this is a creation-only derivation, not a permanent formula.

`BuildState` is *derived*, never stored: `spend(sheet, build) -> remaining per group`, so the
sheet and the build cannot disagree. Resuming a build is therefore just reading the character —
there is no separate wizard state to get out of step with the data.

**Every step is resumable** because "where am I?" is computed: the next unanswered question, the
next unassigned budget, the next unspent group.

---

## 2. Two input styles, deliberately different

The interview is prose. The mechanics are numbers with a budget. Forcing one interface on both
is why character builders feel bad:

| Stage | Input | Surface | Why |
|---|---|---|---|
| Interview (55 questions) | free text, often a paragraph | **DM conversation**, one message per answer | nobody types a paragraph into a modal; a reply is the natural gesture |
| Mechanics (budgets) | numbers, constrained | **commands**, reusing `/spend`, `/ability`, `/background` | free text with numbers silently costs points; commands validate and show the arithmetic |
| Review | read | `/sheet` (embed) + a build footer | the sheet is already good at this |

So creation is not one wizard — it is a **DM conversation for prose, then the existing sheet
tools for numbers**, with one line that always says what is left.


---

## 3. The flow

```text
/create name:"Ailis Vane"
    → creates a draft (blank interview + empty sheet + build state)
    → seats the player if they have no seat
    → opens (or continues) the DM and asks question 1

… 55 exchanges, each: answer → "12/55" → next question
    /skip            skip one (recorded as unanswered)
    /back            go back one question
    /goto 12         jump to a question
    /story           show everything answered so far
    /answer 12 text  rewrite any answer (already exists)

/build
    → "attributes: which group gets 7, 5 and 3?" (three buttons)
    → then the same for abilities
    → then a progress footer on /sheet: Physical 0/7 · Social 0/3 · Mental 0/5
    → /spend trait:Dexterity to:4   spends from the assigned group, not freebies
    → /ability, /background similarly, until every budget is exactly spent

/review
    → sheet embed + "answers 55/55 · budgets spent · freebies 15" + warnings
    → /done seals; sealing archives the build state and drops the budgets
```

`/done` refuses while anything is incomplete or illegal, listing what is missing — the same
contract as the current sealed-interview rule, so `ready` keeps meaning "playable".

---

## 4. Where it lives, and why

**A private thread per character.** Creation is private, slow, and full of half-finished prose.
A thread named `player · character` is the container: commands work there immediately (guild
scope), a GM with Manage Threads can read it, and the thread itself separates one build from the
next. A DM was the first plan and is abandoned — guild-scoped commands do not exist in DMs, and
publishing globally takes up to an hour. If the thread is deleted, the next refresh opens a new
one and re-posts the panels into it.
place in Discord where a message can be edited forever, where nobody else's chat scrolls the
questions away, and where the answer to "how do I save?" is "you already did".

**Progress is data, not messages.** The thread holds the conversation; the *character file* holds
the position. Kill the bot, restart a week later, and `/story` picks up at question 12 because
question 12 is the first one without an answer.

**The bot never invents an answer.** It asks, it acknowledges, it moves on. No LLM on this
path: an autocompleted backstory is not the player's character, and the questionnaire is the
part of creation that has to be theirs.

---

## 4a. Merits and flaws: "standard cost" means the book

The rules price attributes, abilities, virtues, backgrounds and willpower explicitly, then say
merits are "standard cost". That phrase means **the cost in whatever book the merit comes from**,
so the group's own index is the price list:

- `custom_assets/meritsflaws.pdf` (67 pages) is that index; `custom_assets/merits_flaws.json` is
  it as data — **476 merits and 540 flaws**, each with `min`/`max` (a range like `Enemy 1-5`
  means the rating is the player's choice), the book, and the page.
- `sheets/merits.py` loads it. The catalogue is **optional on purpose**: a missing index yields an
  empty catalogue and custom merits still work, which is the house style ("if the group accepts
  it, you can make whatever").
- `/merit name:Ambidextrous` prices itself when the book gives one value; a rated merit asks for
  `points:`; an unknown name is accepted as **custom, group-approved**.
- `/flaw name:Enemy rating:3` checks the rating against the book's range. `/lookup` answers "what
  does this cost in the books?" without anyone guessing.
- A flaw's *value* is not capped at 5 — the index has `Blind 6` — only the house rule on totals
  (7 points, unless exactly two flaws).

Both appear on the sheet embed under **Merits & Flaws**, merits plain and flaws in parentheses.


## 4b. Spending, navigation, and rolling (the three things underneath)

**Budgets pay before freebies.** `/ability`, `/background` and `/spend` all default to
`pool:auto`: the group's creation budget pays while it has room, then freebies top up at the
freebie rate (an ability is 2 per point, not 1). A build that runs out of budget and freebies
says exactly how much was short. Outside creation, `auto` means freebies; `pool:xp` is
advancement; `pool:freebies` forces freebies even mid-build, which is how you spend the 15 points
the rules give you *on top* of the budgets.

**Navigation.** Position is derived from the data, never stored, so a build resumes wherever it
was left:

| Command | Use |
|---|---|
| `/skip n` | records "(skipped)" — a real answer, distinct from unanswered, so `/finish` can proceed honestly |
| `/goto n` | reads question *n*, turns to its page, and prints the exact answer command |
| `/panel` | re-posts both embeds after a deletion and tracks the new pair |
| `/discard confirm:<name>` | abandons a draft (name typed out on purpose); sealed characters are never deleted |

`/answer` now closes with `next: question N`, so a build always points at the next thing to do.

**Checks come from the sheet.** `/roll check:stealth` builds `attribute + ability` from the
character rather than from `checks.jsonl`:

- the attribute comes from the ability (`ABILITY_ATTRIBUTE`, the World of Darkness defaults:
  Stealth → Dexterity, Brawl → Strength, Occult → Intelligence);
- `attribute:` overrides it, and an unmapped ability says its pairing was **guessed**;
- a wound penalty raises the difficulty (`Hurt (-1)` → +1);
- `willpower:true` buys an automatic success and *writes the spend back to the sheet*;
- untrained knowledges refuse, untrained skills add +2 difficulty, specialties reroll 10s.

`/willpower points:1` spends the point without rolling. Characters with no sheet still fall back
to the static check table, so NPCs keep working.


## 5. What "from scratch" needs that does not exist yet

| Piece | State | Notes |
|---|---|---|
| `Build` on `Character`, `BuildState` derived | **missing** | the rules gap in §1 |
| `/create` (draft + seat + DM handoff) | **missing** | needs a DM-send path and a reply listener |
| `/build`, `/review`, `/finish` | **missing** | `/build` is where budget assignment happens |
| Group-aware spending | **missing** | `/spend` needs a "draw from the build budget" mode |
| Interview resume by position | **exists** | `Interview.missing`, `at()`, `with_answer()` |
| Trait add/edit/remove | **exists** | `/ability`, `/background`, `/edit`, `/remove` |
| Seal / reopen / undo / pools | **exists** | `/done`, `/unlock`, `/undo`, `/pool` |
| Long-form review and file round-trip | **exists** | `/story`, `/export`, `/import` |

Two are plumbing (`/create`'s DM handoff, group-aware `/spend`); one is real modelling
(`Build`). The rest is shipped and only needs wiring into a flow.

---

## 6. Recommended slices

1. **`Build` + `/build` + group-aware `/spend`** — makes creation *legal* even if the wording is
   still done with `/answer`. Smallest slice that produces a rules-valid character.
2. **`/create` + DM question loop with resume** — the part that feels like being asked rather
   than filling in a form.
3. **`/review` + `/finish`** — one screen that says "you are done, or here is what is left".
4. Later: buttons/modals for budget assignment, and a "build together" channel mode.

---

## 7. Open questions

1. **Order: prose first or mechanics first?** The book does prose first; numbers first gives
   faster feedback. I lean prose first, because the mechanics only mean something once you know
   who the person is.
2. **Exact spending or "at most"?** The terminal wizard requires each budget to be spent exactly
   (7/5/3 all used), which is the strict reading and makes characters comparable. "At most, bank
   the rest as freebies" is friendlier but changes the arithmetic.
3. **Where do freebies go?** After the budgets: 15 (+ flaws) tops up anything under its cap. A
   separate step with its own footer, or the same `/spend` with the pool switched?
4. **Flaws before freebies?** The rules give "15 + Flaw value", so a Flaw has to be taken before
   the pool is fixed — or the pool updates when one is taken. Nothing models Flaws yet.
5. **Can a player restart?** `/create` on someone with a draft should offer resume or discard,
   and discard must not silently destroy forty answers.
6. **Group mode:** build in a channel where the table watches, or DM only? DM is simpler; a
   channel is more fun and needs no DM permission.

