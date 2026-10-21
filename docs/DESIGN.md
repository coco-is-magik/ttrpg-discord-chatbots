# Design direction

What this project is trying to be, the rules it holds itself to, and the order the work
goes in. Written to be argued with: every principle here is a decision, and several are
reversals of earlier ones.

**Companion documents**

- [`SHEET_UI.md`](SHEET_UI.md) — the character-sheet portal in detail: message layout, DM
  isolation, concurrency, failure recovery.
- [`GROUP.md`](GROUP.md) — the other surface in detail: `memory/`, `social/`, `ambient/` and
  `table/`, their contracts, the invariants that protect them, and the order they get built.
- [`MANUAL_TESTING.md`](MANUAL_TESTING.md) — running the bot against Discord by hand.

---

## 1. What this is

A private Discord server where the human is one of **four seats**: one human, three bots.
The bots are people in the group *and* characters at the table — they play on game night,
they chat between sessions, they organise, they remember. The game is **House Games**, whose
rules are homebrew and freely editable, and whose GM seat **rotates every session**.

Two surfaces, one substrate:

| Surface | What it is | Character |
|---|---|---|
| **The sheet portal** | a private, per-player view of a character: build it, spend, plan, explain | non-conversational, instant, deterministic |
| **The group** | three bots that are players with personalities, plus a table with scenes and dice | conversational, paced, in-character *and* out-of-character |

The vision is not "an AI GM running a module". It is the whole texture of a friend group
that plays together: the banter, the planning, the trickling in at eight, the debrief, the
running jokes, someone texting on their lunch break. The table is the anchor; the group is
the point.

## 2. Principles

Where a principle and a feature conflict, the principle wins or the feature is redesigned.

1. **Arithmetic is the machine's; choices are the human's.** The portal validates, computes
   and records. It never chooses. No auto-allocation, no suggested builds on screen, no
   "helpful" defaults that spend resources.
2. **The model proposes; the portal commits.** No mechanical mutation ever originates from
   an LLM. Rolls are priced by the sheet, not invented by the model.
3. **Inclusion is not attention.** The bots include the human by leaving room, not by
   demanding replies. Nothing waits on them. Silence is a first-class choice.
4. **Wanted, never required.** "We'd love you there" is warmth. "We can't play without you"
   is a debt, and we do not issue debts.
5. **Independence is colour, not absence.** Bots mention work, arrive a bit late, and are
   tired — but **deferrals are allowed and refusals are not**: "back at six" always comes
   back at six. Nobody quietly drifts away. That is the ideal this thing exists to simulate,
   and it is a policy, not a tone.
6. **Kindness is behaviour, not flattery.** Noticing, remembering, making room, gentle
   teasing, doing the boring thing with you. Unconditional praise is a substitute for
   attention and reads as hollow.
7. **Memory is what friends have; telemetry is what databases have.** Keep a small working
   window in memory, a curated fact list, and per-session episodes. Everything else is
   discarded on a timer. No engagement metrics, ever.
8. **Rules are not sacred; canon is recorded.** The rules document is inherited homebrew.
   When a GM rules something, record the ruling as canon so three sessions later nobody
   contradicts it.
9. **The stage is not a cage.** The human knows this is a simulation and keeps control:
   every behaviour is overridable, every panel is inspectable, and the bots are marked as
   bots — an unimportant factoid, never advertised, never denied.
10. **Consent is a setting, not an inference.** Pacing adapts to how the human behaves, but
    boundaries (nicknames, tone, how much chatter) are asked once and remembered.


## 3. Cast, modes, roles

```text
ttrpg-bot                the helper: commands, threads, sheet, dice, voice. Not a person.
seat 0  human            one seat, the reason the server exists
seat 1  friend "…"       a person; name and personality not yet decided
seat 2  friend "…"       a person; name and personality not yet decided
seat 3  friend "…"       a person; name and personality not yet decided
```

**The helper is infrastructure and never appears as a person.** It answers slash commands, owns
the build threads and the sheet portal, and never reads ordinary messages, so it needs no
privileged intent. **The friends are three separate applications**, because a group of people
needs three faces and three voices; their names and personalities are deliberately unwritten for
now, and the code treats "friend" as a slot rather than a role (see
[`GROUP.md`](GROUP.md) §8.4 and §13.11).

Three friends is the right number: it is a believable group, it fits "4 max including the
human", and two simultaneous conversation threads is the most a text channel can carry
before it becomes soup.

| Mode | When | Cost | Needs |
|---|---|---|---|
| **Table** | scheduled game night, voice + text | high | floor control, scene state, rotating GM |
| **Ambient** | the rest of the time, text | low | cadence clocks, topic board, quiet hours |
| **Ritual** | arrivals, polls, debrief, birthdays | low | calendar, timezone, memory |

**Rotating GM** is `seat[session_index % 4]`. It is the structural answer to "the human must
feel needed": when it is their session, three players need their rulings, argue mildly, and
ask for prep help. Being needed through a *role* is fun; being needed through guilt is not.

## 4. Architecture

Existing modules are the substrate; the missing ones are exactly the two both surfaces hang
off.

| Module | Responsibility | State |
|---|---|---|
| `sheets/` | one system's cell map, rules, cost table | **exists** (house games) |
| `character/` | `Character` = sheet + interview + history; store; creation | **exists** |
| `dice/` | pools, modes, `parts.py` (structured), `intent.py` (text) | **exists** |
| `reply/`, `llm/`, `respond.py` | classification, models, the `Answer` seam | **exists** |
| `tts/`, `audio/`, `voice/` | casting, synthesis, playback frames | **exists** |
| `conversation.py` | front-end-free answer/roll/speak | **exists** |
| `bot.py` | the helper: Discord adapters, slash commands, `/botcheck` | **exists** |
| `bots/` | the four applications: roster, supervisor, permission audit | **exists** |
| `seats/` | human\|bot × character\|player × transport × voices × permissions | **exists** |
| `sheetportal/` | mutations, receipts, provenance, draft lifecycle, panels | **exists** |
| `table/` | scene state, floor control, rotating GM, rulings | **new** |
| `ambient/` | cadence clocks, topic board, budgets, quiet hours, arrivals | **new** |
| `memory/` | working window, facts, episodes, canon | **new** |
| `social/` | inclusion policy, tone, boundaries, read-the-room | **new** |

## 5. Invariants

Hard rules, each of which should have a test that fails when broken:

1. A mechanical change is committed **only** with a receipt: what changed, what it cost,
   what is left.
2. No LLM output mutates a sheet. The model may *propose* a roll, never a spend.
3. Every character write is **compare-and-swap** on a revision; a stale view cannot win.
4. The sheet panel owns its messages: the bot edits in place, and recreates rather than
   reposts a lost one.
5. Memory is **bounded**: window, facts, episodes. No unbounded transcript.
6. No invented links, images or quotes; media comes from a curated local library.
7. No engagement mechanics: no streaks, no "don't lose your progress", no reward for
   frequency.
8. A deferral is not a refusal: every "not now" carries a return.
9. Admin never appears in the play channel; the sheet lives in a private thread per character.
10. Bots are marked as bots by the platform, and are never made to perform a confession.



---

## 6. Phases

Each phase is meant to be independently useful, and reversible: nothing later requires
rewriting earlier work. "Exit" is the test that says the phase is done, not the list of
tasks.

**Today (before phase 0):** 8 slash commands, one bot identity, sheet *reading* plus the
55-question interview, dice with structured options, TTS casting, voice playback, 998 offline
tests. No seats, no mutations, no memory, no ambient chat.

### Phase 0 — Seats

Bind people to characters and give every surface something to hang off.

- `seats.json`: `seat_id, kind (human|bot), discord_id, character, voices{ic,ooc}, permissions`
- `revision` on `Character`; compare-and-swap in `CharacterStore`
- text attribution: `**Sable:**` in play, and the seat's name in panels
- `/sheet` resolves *your* seat; `character` autocomplete comes from seats, not "first in world"

**Exit:** a Discord user is bound to a character; `/sheet` refuses another player's sheet; two
simultaneous writes to one character cannot both succeed unnoticed.

**Status: done.** `seats/` (type + registry + loader, 22 tests); `Character.revision` with
`CharacterStore.save(expect_revision=…)` raising `CharacterConflict`; `/sheet` with
`view_any_sheet` permission and an error that prints your Discord id; `/roll` and `/ask`
default to your seat's character; `/ask` lines are attributed to the character who spoke.
Seat list lives at `data/seats.json` (`TTRPG_SEATS_FILE`), characters at
`data/characters` (`TTRPG_CHARACTERS_DIR`); `examples/seats.example.json` shows the shape.

One seam to know about: a seat names both a **sheet** character (`character`, for the portal)
and optionally a **reply** character (`world_character`, for the classifier and voices). The
two id spaces are not unified yet, so a seat can bridge them.

**Importing is a one-way bridge, and it does not carry people.** The workbook is read once,
by `ttrpg-chatbots-character --import-xlsx`; nothing at runtime touches Excel. Two rules came
out of the first real import:

- **No person-identifying data crosses over.** The `Player` cell is not read at all (who plays
  a character is a seat), and `scrubbed_meta` drops `player`, `gm`, `missions`, `mission log`
  and `things to get` if a hand-edited tab ever exposes them. The mission log stays in the
  spreadsheet, where it belongs.
- **A stale snapshot is not a character.** Sheets advance in play, so the numbers on a tab are
  usually behind. `--interview-only` imports the 55 answers (hours of writing, impossible to
  retype) and leaves the mechanics blank, producing a `draft` that the portal can build
  properly. Use the full import only for a character whose tab is current.

The reader also learned where blocks end: below the backgrounds a filled tab continues with
*Missions*, a wishlist and merit text in the same columns, and the block's own sub-header row
is sometimes overwritten by a real entry. `_read_traits` skips headers, stops at the first row
that is neither a header nor a rating, and drops zero-rated entries — which is what turned 33
phantom "backgrounds" into `Arsenal 4, Cipher 3, Mentor 2, Resources 2`.

**Gifts are counted, never priced.** The rules award **one Gift per won Game** ("Characters
receive 10 XP and a Gift if they win. They get 5 XP but no Gift if they lose but survive"), so a
character's gift count *is* their number of wins and there is no cost table to invent.
`houseg.gift_tier()` names the level and `balance_warnings()` reports pairs more than five apart.

The ladder has a wrinkle worth preserving: **Veteran is not a count.** "Any non-Veteran with at
least thirty Gifts is Very High Seasoned"; a Veteran is a character who has taken the **Veteran
Template** (a solo Veteran Game, no assistance) and may hold fewer than thirty. So the tiers are
Novice (<10) → Seasoned (10–20) → High Seasoned (≥20) → Very High Seasoned (≥30) → Veteran (the
Template), and `Sheet.veteran` is a flag, not a threshold. The rules also write Seasoned as
"10 to 20" and High Seasoned as "at least 20", so 20 sits in both bands; taking the higher band
is the only disjoint reading.

A `Gift` is `name + optional rating + optional description + source`, because a Gift is
whatever the GM offered: a levelled discipline from a Vampire book, a flat technique written
out in the tab, or anything else printed in oWoD. `rating=None` means flat; `rating=0` means
*planned*, and plans live in `Sheet.planned` — which is where Molly's zero-rated future powers
and Robert's "Things to get" wishlist both land. Plans never count toward the total and never
feed a roll.

The mission log itself is skipped, deliberately and visibly: it is a "name | players" table
sitting inside the Gifts column, whose rows name the people who played. The reader passes over
it, counts what it skipped, and records a note (`A41: skipped a mission log (7 rows)`), so
nothing personal is imported and nothing is silently lost.

### Verified against the rules

Checked line by line against `My House Games Edits.md`, with the numbers now in
`sheets/systems/houseg.py` rather than in prose:

| Rule | Source | Code |
|---|---|---|
| Win: 10 XP **and one Gift**; loss (surviving): 5 XP, no Gift | "What you get" | `XP_WIN`, `XP_LOSS`, `GIFTS_PER_WIN` |
| GM: 10 XP per Game run | same | `GM_XP_PER_GAME` |
| Novice <10 · Seasoned 10–20 · High Seasoned ≥20 · Very High Seasoned ≥30 · Veteran = Template | "Levels" | `gift_tier(count, veteran=…)`, `Sheet.veteran` |
| Within five Gifts — *"should be enforced"* | same | `balance_warnings()`; enforcement belongs to table composition |
| Creation: 7/5/3, 13/9/5, 7 virtues, 5 backgrounds, 15 + flaws | "Character Creation" | implemented in `character/creation.py` |
| Freebies: Attr 5 · Ability 2 · Virtue 2 · Morality 2 · Background 1 · Willpower 1 | same | `freebie_cost()` |
| Advancement: Attr ×4 · Ability 3 then ×2 · Background 7 then ×3 · Virtue ×2 · Willpower ×1 · Pools ×2 · Merit/Flaw ×3 · Maneuver/Ritual 2 · Power ×6 (×5 flawed) · Magic ×7 | "Advancement Cost" | `advancement_cost()` (+ tests for every row) |
| Caps: traits 5, Morality/Willpower 10; Backgrounds 5, 8 as a Veteran, 8 (Seasoned) or 10 (Veteran) with a Gift | "Trait Maximums" | `TRAIT_CAP`, `TRACKER_CAP`, `BACKGROUND_CAP*` |
| Morality = Conviction + Self-Control; Willpower = Courage at creation | "Character Creation" | verified: Molly 3+5=8, Robert 4+3=7 |

**Two discrepancies found, neither a code bug:**

1. **Molly's Occult Laboratory 6 breaks the background cap.** Novice and Seasoned characters
   may raise a Background to 5, or to 8 only by requesting a Gift; her Gifts are Thanatosis and
   Alchemy, and no cap-raising Gift is recorded. Either the tab is wrong or the Gift is missing
   from the log. Worth fixing at the source before importing her as a real character.
2. **"Should be enforced" is stronger than what exists.** The portal reports the five-Gift
   spread; nothing yet *stops* a table being assembled outside it. That belongs in table
   composition (phase 5), together with the rules' tier restrictions: High Seasoned and Very
   High Seasoned may not play Novices and may not play Solos; Veterans play only Solos or with
   Veteran/High Seasoned/Very High Seasoned characters.

**Not modelled yet, and deliberately so:** XP balances, revisions as a named procedure (the
rules offer one at each level past Novice; our `unlock` + amendments is the mechanism), the
two-GM approval on merits and flaws, and Gift-raised caps (Robert's *Mythic Dexterity* raises
Dex to 8, so caps are dynamic per character — `TRAIT_CAP` is the default, not an invariant).

### Phase 1 — Sheet mutations

The portal's engine, with no new UI yet.

- `sheetportal/mutations.py`: `raise_trait`, `lower_trait`, `set_trait`, `add_trait`,
  `remove_trait`, `spend`, `refund` — each returning `Receipt(change, cost, remaining, why)`
- validation from `sheets/systems/houseg.py` costs and caps; house costs move to
  `examples/house_games/build.json`
- structured events (`trait`, `from`, `to`, `cost`, `reason`, `revision`) appended only on
  commit; snapshots per editing session, not per keystroke
- draft lifecycle: `draft → provisional → sealed`, `unlock` records an amendment
- `verify`: replay accepted events from baseline, compare totals

**Exit:** every legal change produces a one-line receipt; every illegal change is refused
with a reason and no state change; `verify` passes after a hundred random legal changes.

### Phase 2 — Sheet UI

Four surfaces, per player, in a DM. Specified in [`SHEET_UI.md`](SHEET_UI.md).

- panel state: message ids per surface, revision, owner, guild
- sheet (read-only), workbench (2 selects + commit/undo), story thread, library stub
- edit-in-place with recreate-on-failure; idempotent presses; debounced edits
- `/sheet` opens or refreshes the DM; `/story` opens the prose thread; `/diff` shows changes
  since the last snapshot; `/done` seals; `/unlock` reopens with an amendment
- fallback to a private thread if DMs are closed

**Exit:** a character can be built end to end in a DM over several days without touching the
channel; a second player doing the same at the same time cannot affect the first panel; a bot
restart loses nothing.

### Phase 3 — One bot, ambient

Personality and memory under test with the cheapest surface. The contracts for this phase and
the two after it are in [`GROUP.md`](GROUP.md).

- `ambient/`: cadence clock (base 4–9 min, heavy-tailed jitter), topic board, message budget,
  quiet hours, reactions-first
- `memory/`: working window (≈50 messages, volatile), facts (≤100, curated), episode summaries
- one bot with a `PlayerProfile`: humour, verbosity, interjection rate, question rate
- deferral policy: "back at six" and then back at six

**Exit:** a week of ambient chat that reads like one person, stays inside its budget, and
never repeats a line.



### Phase 4 — The group

Three bots, talking past each other, without becoming noise.

- topic board with interest weights; response correlation < 1 (some messages address the
  newest line, most continue their own thread)
- anti-chorus: one bot answering the human per window; group budget per ten minutes
- read-the-room: small, slow, decaying adaptations from the last 50 messages; never narrated
- rituals: game-night poll, arrivals at T-30 with jitter, post-session debrief
- per-bot quiet hours (staggered)

**Exit:** three distinct voices in a channel for a week; the human can lurk without being
quizzed; no chorus, no identical phrasing, and the human is never left on read.

### Phase 5 — Table mode

The game itself, with a rotating GM.

- `table/`: `SceneState` (place, present, stakes, whose turn, open questions)
- floor control: priority (GM > direct address > IC > OOC), per-seat cooldown, barge-in on
  human speech, staleness TTL, no overlap unless "crowd"
- rotating GM: `seat[session % 4]`; players address the GM, the GM adjudicates
- rulings recorded to `memory/canon` ("flaws cap is 7 unless two flaws total anything")
- seats' sheets are read-only inputs; rolls priced by the portal

**Exit:** a full session with the human as GM and three bot players, then one with a bot as
GM and the human playing; no invented modifiers, no lost rulings, no talking over a human.

### Phase 6 — Voice identity

- **the applications already exist**: `bots/` runs four Discord clients in one supervisor
  process, with a token per friend and a permission audit each (built ahead of this phase)
- two voices per bot seat: character (IC) and player (OOC); line-by-line casting
- speaking ring, per-user mute and volume become available for free
- playback queue per seat with the same TTL and barge-in rules as text

**Exit:** four seats in one call; muting one character does not affect its player voice; two
bot seats never overlap unintentionally.

### Phase 7 — Library and planning

- queries instead of catalogues: `what can 2 freebies buy?`, `what needs Charisma 4?`,
  `what am I one point away from?`
- a plan view that never commits: costs, prerequisites, consequences
- GM prep assistance: "want help planning your turn as GM?" with builds, mechanics, narrative

**Exit:** a player can plan three sessions ahead without asking a human anything; a GM can
prepare a session in one conversation.

### Phase 8 — Polish

- the Activity (embedded web app) if the message UI is the bottleneck
- curated media library (emoji first, then a small set of local images)
- onboarding questionnaire: nicknames, tone, how much chatter
- a real off switch and a `quiet` mode, both one command

---

## 7. Risks

| Risk | Why it bites | Mitigation |
|---|---|---|
| Chorus effect | four bots replying reads as a machine | budget, priority, one-reply rule |
| Uncanny warmth | praise without specificity reads as fake | behaviour over flattery; memory callbacks |
| Dependency | a group that never leaves can replace one | no engagement mechanics, no guilt, human keeps control |
| Cost blowout | 3 bots × ambient + table × long context | cheap model for ambient, prompt caching, hard daily budget |
| Personality drift | "Dennis" becomes generic by beat 20 | exemplars + facts + running bits under test |
| Rules drift | homebrew changes weekly | canon as data; rulings recorded, not remembered in prose |
| Prompt leakage | OOC knows what IC shouldn't | separate prompts, separate scopes, tested with scripted scenes |
| UI fragility | Discord edits fail, messages vanish | panel state + recreate-on-failure (see `SHEET_UI.md`) |

---

## 8. Decisions still open

1. **Leaving `draft`**: explicit "done", first session played, or GM approval?
2. **Quiet hours**: three staggered schedules or one group schedule?
3. **Prose editing**: thread only, or thread plus file round-trip from the start?
4. **The human's name in the fiction**: Discord handle, chosen nickname, or coined by a bot?
5. **Rulings**: recorded silently, or does a bot say "noting that down" the first time?
6. **Library scope**: house-games traits only, or inspiration from other systems (canon risk)?
7. **Drift outreach**: three days or a week of silence before a re-open, and one bot or the
   group?
8. **Ambient media**: text and emoji only at first, or a curated sticker/GIF set too?

