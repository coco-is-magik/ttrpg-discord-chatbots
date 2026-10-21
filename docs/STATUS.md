# Status — where we are right now

Dated snapshot, not a wish list. `DESIGN.md` says where the project is *going*; this says what
is true *today*, so a later session can pick up without re-deriving it. Update it when a slice
lands; it should never be more than one slice out of date.

**Last updated:** 2026-10-21.

---

## 1. Snapshot

| | |
|---|---|
| Tests | **1465 passing**, ~27 s, no network, no GPU |
| Bots live | 4 applications: `ttrpg-bot` (helper) + `friend-a/b/c` |
| Permissions | **8/8 each** in `#general` |
| Slash commands | **51/51** synced to guild 1364544268609523762 |
| Who speaks | `friend-a` only, `reply: mention`; `friend-b`/`friend-c` are `reply: off` |
| Model | **none** — classifier only, by choice, until a persona exists |
| Working tree | **uncommitted** (see §4) |

## 2. What exists and works

- **Sheet portal** — seats, sheet mutations with receipts and compare-and-swap, private build
  threads, panels edited in place, `/build`, `/finish`, `/sheet`, `/export`, `/import`.
- **Creation** — 55-question interview, resume by position, questionnaire round-trip.
- **Four applications, two roles** — helper owns every command; friends own none, listen to
  message content, and audit their own permissions on connect. `data/bots.json` describes all
  four; tokens live in `.env` / `.env.friend{a,b,c}`.
- **`/botcheck`** and **`/friendcheck`** — audit permissions, and report what each friend heard,
  said, and stayed quiet about.
- **The classifier** — social lexicon → tagged knowledge (NCD) → context.
  `docs/CLASSIFIER.md` is the full account.
- **Context** — the last 8 turns; a transition table vetoes a reading that cannot follow the
  previous turn, and an unaddressed repeat is met with silence.

## 3. Verified how

| Claim | Evidence |
|---|---|
| All four bots connect, audit 8/8, sync 51 commands | `data/logs/bot.log`, 2026-10-21 12:30 |
| A mention gets a classifier reply | live, plus `tests/test_bots_supervisor.py` |
| A lore question deflects instead of inventing | live, plus `tests/test_friends_chat.py` |
| Context changes the reading (`presence` vs `greeting` after a goodbye) | `test_the_table_vetoes_a_reading_that_cannot_follow` |
| Silence is possible and is not an error | `test_an_unaddressed_repeat_is_left_alone` |
| Switchboard imports in 1.24 s at **86%** coverage | run by hand, numbers in `CLASSIFIER.md` §6 |
| **Unverified by hand**: 55 answers → `/finish` → sealed `/sheet` | nobody has walked it end to end yet |
| **Unverified**: a language model, a voice per friend, memory across restarts | not built |

## 4. Uncommitted work (as of this snapshot)

Everything since commit `a1b5215` is in the working tree: **14 modified and 14 untracked paths** —
`bots/chat.py`, `bots/identity.py`, `bots/supervisor.py`,
`reply/{context,transitions,importers,intents,responder,replier,cli,types}.py`,
`examples/friends_world/`, `corpora/README.md`, the five new test files, and the docs
(`GROUP.md`, `CLASSIFIER.md`, `STATUS.md`, `MANUAL_TESTING.md`, `README.md`, `.gitignore`,
`.env.example`).

Committing is the only thing that makes a handover real; the docs are the content, the commit is
the timestamp.

## 4a. Machine-local, not committed, not reproducible from a clone

| Path | What | Why it is not in git |
|---|---|---|
| `corpora/switchboard/` | the Switchboard corpus (37 MiB, `utterances.jsonl`) and `transitions.json` derived from it | a download plus CC BY-NC-SA — see `CLASSIFIER.md` §4 |
| `data/bots.json` | the four-bot roster | `data/` is ignored; `examples/bots.example.json` is the template |
| `.env`, `.env.friend{a,b,c}` | tokens | secrets |

`corpora/` is ignored by rule, with one tracked exception: `corpora/README.md`, so the folder
exists in a fresh clone and explains the download. `git add corpora/` stages that file and
nothing else — check with `git add --dry-run corpora/` before trusting it.

## 5. Next three actions, with commands

1. **Commit the slice.** Two commits is right: bots/roster/probe, then classifier/context/import.
2. **Walk creation to a sealed sheet by hand** (the one unverified path in §3).
3. **Decide the model** (`CLASSIFIER.md` §7 is the ranked list; the friend voice is the blocker
   for everything after greeting).

To use the measured transition table locally (it is not committed — see §4a):

```bash
echo 'TTRPG_FRIENDS_TRANSITIONS=corpora/switchboard/transitions.json' >> .env
./start-bot.sh --stop && ./start-bot.sh -d
```

The corpus it came from is already at `corpora/switchboard/`; to rebuild the table from scratch,
`corpora/README.md` has the download and import commands.

## 6. Facts that are easy to get wrong

- **`data/` is git-ignored.** Runtime state lives there on purpose; nothing in it is
  reproducible from a clone. That is why the measured table is local-only: CC BY-NC-SA.
- **`corpora/` is git-ignored too, and that is load-bearing.** The corpus is 37 MiB — nearly
  four times the tracked repository. Never `git add -f` anything inside it; if `git status` ever
  lists a megabyte of `.jsonl`, something bypassed the rule.
- **The helper must not request Message Content.** It is a test: `tests/test_bot.py` asserts the
  helper's intents stay at `discord.Intents.default()`.
- **A token cannot hold two gateway sessions.** Stop the bot before `--friendcheck` /
  `--friendcheck` probes, or you get two half-connected clients and confusing logs.
- **`pytest` already passes `-q`.** Adding your own `-q` gives `-qq` and suppresses the summary
  line; run plain `pytest` when you want the count.
- **`./start-bot.sh` with no argument runs in the foreground.** Use `-d` / `--background`.
- **Friends ignore other bots, and count the delivery anyway.** "Only from bots" in
  `/friendcheck` means the pipe works and the message was correctly dropped.
- **Silence is not failure.** `FriendChat.reply` returns `None` to stay quiet;
  `ChatError` is a real problem.

## 7. Where a thing lives

| Looking for | File |
|---|---|
| Slash commands, the helper | `src/ttrpg_chatbots/bot.py` |
| Who is a bot, what they may do | `bots/identity.py`, `bots/roster.py`, `bots/permissions.py` |
| Launching 1–4 applications | `bots/supervisor.py` |
| How a friend answers | `bots/chat.py`, `reply/replier.py` |
| Social moves | `reply/intents.py` |
| What was said before | `reply/context.py` |
| Which act follows which | `reply/transitions.py` |
| Reading a corpus into that table | `reply/importers.py` |
| The classifier's full account | `docs/CLASSIFIER.md` |
| The group's design and invariants | `docs/GROUP.md` |
| Testing against Discord by hand | `docs/MANUAL_TESTING.md` |
