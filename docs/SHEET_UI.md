# The character sheet, as a UI

How a player builds and maintains a character in Discord: what is on screen, where it lives,
and what happens when two things try to change it at once. The engine behind it is described
in [`DESIGN.md`](DESIGN.md) phases 1–2.

The goal is that the sheet is **not a thing you interact with**. You think about the
character, and the numbers follow.

## 1. Goals, anti-goals

**Goals**

- Zero navigation: the numbers you care about are in one fixed place, always current.
- Zero arithmetic: costs, caps and remaining budget are computed, never counted by hand.
- Zero state to remember: every message shows what it is and what it can do.
- Hours of tweaking, across days, with a clean diff at the end.
- No accidental commits, and an undo for the ones you meant to take back.

**Anti-goals**

- A control for every number. Most values are read, not written.
- A modal per edit. Modals are for prose and batch entry, not for stepping a trait.
- Menus of menus. If a surface needs a second page to be usable, it is the wrong surface.
- Any use of the play channel for admin. Ever.

## 2. Why DMs

The sheet lives in a **direct message between the bot and its owner**, one per player. This
is the load-bearing decision for "zero disruption":

| Concern | Why a DM solves it |
|---|---|
| Several people building characters at once | each player has their own channel; nothing is shared |
| People talking in the play channel | admin never enters it, so chatter cannot bury a panel |
| Privacy | only the owner and the bot can see it; no permission logic needed |
| Message lifetime | ephemeral interactions expire; DM messages can be edited forever |
| History | the DM *is* the audit trail, in order, with the bot as the only author |

Two constraints to design around:

1. A bot can only DM someone who **shares a guild** with it, and only if that user allows
   DMs from server members. So `/sheet` is always invoked **in the server**; the bot opens
   the DM and posts the panel there.
2. If DMs are closed, fall back to a **private thread** in a `#sheets` channel, created for
   that player only. Same four surfaces, same state, different container — and the panel
   records which container it lives in.

Conversation belongs in the server; the DM is a tool. The panel says so once, in its header,
and never again: `Your character panel. The group is in #general.`

## 3. The four surfaces

Each message has exactly one job, because a message that does two jobs forces the player to
scroll between them.


### 3.1 The sheet — read-only

```
Sable                                  House Games · sealed
Dexterity 4   Wits 3   Stamina 2       Willpower 5/5   Morality 7
Stealth 3 (alleys)  Alertness 2  Dodge 2  Occult 1
Backgrounds 5/5 · Freebies 2 · Health [x][ ][ ][ ]
```

Never a control. Edited in place after every commit. This is the thing your eyes learn;
nothing about it moves except the values.

### 3.2 The workbench — one change at a time

```
Trait  [ Stealth ▾ ]     Value  [ 3 ▾ ]
Stealth 2 → 3 · costs 2 freebies · 3 left
[ Commit ]  [ Undo ]
```

Two taps for a change: pick the trait, pick the value. Illegal values are present but
disabled **with the reason inline** (`5 — cap`, `3 — not enough freebies`), because "why
can't I?" is the main source of friction. `Commit` re-renders both messages; `Undo` reverts
the last committed change.

Batch entry (an initial build) is the exception: one **modal per group** — nine attributes in
one form, ten talents in another — submitted once. That is faster than fifty-seven taps and
is the only place a modal earns its interruption.

### 3.3 The library — questions, not catalogues

```
Ask: what can 2 freebies buy?
• Stealth 2→3 — 2 freebies
• Alertness 2→3 — 2 freebies
• Library (new, 1) — 1 freebie
```

A separate message because browsing and editing are different modes. It is also where
planning happens (`what needs Charisma 4?`, `what am I one point away from?`), and it never
commits anything. Phase 7 fills this in; phase 2 ships the message with a stub.

### 3.4 The story — long-form prose

A **thread** under the panel, one message per section, edited in place as answers change. For
multi-day writing: `export` → edit in a real editor → `import` with a validation diff,
because no Discord control is a good place to write 55 paragraphs.

## 4. Stability

The panel is a small piece of state with a big surface, so it is built like a UI with a single
writer, not like a chat bot that happens to edit messages.

### 4.1 One owner, one writer

The bot owns every panel message; the human never types into them. Their inputs are component
interactions and slash commands only. That removes a whole class of races: there is only ever
one writer per message, and it lives in one process.

### 4.2 State

```json
{
  "guild": "1364544268609523762",
  "user": "…",
  "character": "sable",
  "revision": 7,
  "container": {"kind": "dm", "channel": "…"},
  "messages": {"sheet": "…", "library": "…", "story_thread": "…"},
  "updated": "2026-10-17T13:42:11Z"
}
```

Stored per `(guild, user)` under `data/panels/`, so a restart resumes silently: no reposting,
no "welcome back" noise. The panel is *found*, not announced.



### 4.3 Edit in place, recreate on failure

Every render is an edit of a stored message id. If the edit fails — message deleted, channel
gone, unknown message — the bot posts a fresh message, updates the id, and continues. The
player sees the panel; they never see an error, and they never see a duplicate.

### 4.4 Revision and compare-and-swap

Each commit carries the revision the view was rendered from. The store applies the change only
if the character is still at that revision; otherwise the commit is refused with
`this view was out of date — refreshed` and the panel re-renders. That is what makes two
devices, or a player and a GM, safe at the same time.

### 4.5 Idempotent interactions

A press can arrive twice (double-tap, Discord retry). Every interaction is keyed by
`(revision, action, target)`; the second is a no-op that re-renders. No double spends, ever.

### 4.6 Coalesced rendering

Discord rate-limits edits per channel, and a fast tweaker can outrun it. Renders are
**debounced** (~400 ms) and coalesced: many commits inside the window produce one edit. If the
limit is still hit, the edit is queued, not dropped — the panel converges, it does not lie.

## 5. Isolation

Isolation is by construction, not by checking permissions at request time.

| Thing | Scope | Why |
|---|---|---|
| Panel state | `(guild, user)` | two players cannot address the same panel |
| Panel messages | one channel per player | nobody else can see or edit them |
| Character writes | `(character, revision)` | the swap is on the data, not the surface |
| GM tools | the GM's own panel | the GM does not get a window into private panels |
| Play channel | never written by the portal | chatter and admin cannot interfere |

Two players building at the same time: two DMs, two states, no shared mutable message, no
ordering dependency. The workbench a player sees belongs to them alone, and the only shared
thing — the world's rules — is read-only data.

## 6. Failure matrix

| Event | Behaviour |
|---|---|
| Bot restarts | state reloaded; panels found and re-rendered if stale; nothing announced |
| Panel message deleted | repost, update id, continue (no error shown) |
| Stale button (older revision) | ephemeral note + re-render; the change is not applied |
| Double-tap / Discord retry | second press is a no-op (idempotency key) |
| Two devices commit at once | first wins; second gets a refreshed view and can retry |
| GM edits the same character | same CAS rule; loser sees the diff |
| Character sealed | workbench disabled, `Unlock` offered; unlocking records an amendment |
| DMs closed | fall back to a private thread, record the container change |
| Discord rate limit | coalesce/queue renders; the panel converges late, never wrong |
| Player leaves the server | panel state retained; `/sheet` on return finds it |

## 7. The editing loop

```
/sheet                 → ensure DM, post or refresh the panel
  pick trait + value   → commit (CAS) → receipt → sheet and workbench re-render
  Undo                 → revert the last commit → both re-render
/story                 → open the prose thread
/diff                  → changes since the last snapshot
/done                  → seal: draft → sealed, with a summary of what changed
```

Twelve commits in a row produce twelve receipts and roughly two edits, because rendering is
coalesced. Closing the panel for the night produces **one** snapshot, so `diff` shows a week
of work in a dozen lines rather than four hundred events.

## 8. Draft lifecycle

| State | Editing | History | Notes |
|---|---|---|---|
| `draft` | free, everything | none (snapshots only) | the state you live in for a week |
| `provisional` | free, but playable | a snapshot per session | "good enough to play Thursday" |
| `sealed` | `Unlock` required | every change is an amendment | the finished character |

Sealing is not a trap: `/unlock` is one command, records an amendment, and returns the
character to `provisional`. What sealing buys is a clean baseline for play and for `verify`.

## 9. Performance

- **Local arithmetic**: microseconds. The only latency is Discord.
- **Ack budget**: interactions are acknowledged immediately; the panel updates arrive as
  edits, not as new messages, so the channel stays at four messages plus one thread.
- **Render budget**: at most one edit per surface per 400 ms, per panel.
- **No model, no network, no synthesis** anywhere in this path. If the sheet ever needs an
  LLM to answer, the answer is wrong.

## 10. Testing

Offline (the existing fake-interaction pattern):

- every mutation returns a receipt, or refuses with a reason and no state change
- CAS: a stale commit cannot win; the loser gets a diff
- idempotency: the same press twice changes state once
- recreate-on-failure: a missing message id is reposted and the id updated
- isolation: two users' panels never share a message id or a revision

Manual, because Discord owns the semantics:

- DM opens from `/sheet`, panel survives a restart, edits land in place
- a deleted panel comes back without duplicates
- two devices at once (phone + desktop) behave
- the play channel contains no admin traffic

## 11. Open questions

1. **Pins**: pin the sheet message in the DM, or rely on it being the newest? (Pinning is one
   tap saved every session.)
2. **`/story` vs `/sheet`**: one entry command with buttons, or separate commands for the
   four surfaces?
3. **The header line**: keep "the group is in #general" permanently, or show it once?
4. **Undo depth**: one step, or a stack of ten? (Ten is cheap and forgiving.)
5. **Batch modal grouping**: attributes/virtues/talents/skills/knowledges as five modals, or
   one "advanced" thread with forms? 

