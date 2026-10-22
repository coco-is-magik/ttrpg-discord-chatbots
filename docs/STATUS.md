# Status — where we are right now

Dated snapshot, not a wish list. `DESIGN.md` says where the project is *going*; this says what
is true *today*, so a later session can pick up without re-deriving it. Update it when a slice
lands; it should never be more than one slice out of date.

**Last updated:** 2026-10-22.

---

## 1. Snapshot

| | |
|---|---|
| Tests | **1681 passing**, ~31 s, no network, no GPU |
| Bots live | 4 applications: `ttrpg-bot` (helper) + `friend-a/b/c` |
| Permissions | **8/8 each** in `#general` |
| Slash commands | **51/51** synced to guild 1364544268609523762 |
| Who speaks | `friend-a` only, `reply: mention`; `friend-b`/`friend-c` are `reply: off` |
| Conversation | **nine phases on the module ladder**, live behind `TTRPG_CONVERSATION=ladder`; knowledge questions still take the old classifier |
| Modules | **53/53 built**, manifest clean (`ttrpg-chatbots-conv --manifest`) |
| Personality | **friend-a is TopGuy** (`docs/PERSONA.md`); b and c deliberately neutral |
| Typing | friend-a types lower-case with dropped apostrophes and the odd slip; b and c stay tidy |
| Memory | short-term: last 8 turns in RAM. long-term: `data/friends/friend-a.json` |
| Life | `examples/friends_world/life.json`: 5 activities, 4 grievances, day-stable |
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
- **One personality, fully written** — `friend-a` is TopGuy: ten subjects, his own pool for every
  social move, his own way of refusing, and a voice pinned in the casting table. The brief lives in
  `bots.json`; the lines live in `examples/friends_world/`; `tests/test_persona.py` refuses to let
  the two disagree. `docs/PERSONA.md` is the whole story, including how to write the next one.

## 3. Verified how

| Claim | Evidence |
|---|---|
| All four bots connect, audit 8/8, sync 51 commands | `data/logs/bot.log`, 2026-10-21 12:30 |
| A mention gets a classifier reply | live, plus `tests/test_bots_supervisor.py` |
| A lore question deflects instead of inventing | live, plus `tests/test_friends_chat.py` |
| Every one of TopGuy's ten subjects gets an answer in his own voice | `tests/test_persona.py`, distances 0.18–0.55 |
| He refuses what he does not know, warmly | `test_a_question_outside_his_subjects_is_refused_honestly` |
| He answers somebody who is struggling | `test_he_can_be_moved_by_somebody_having_a_bad_day` |
| No line is contemptuous of the human | `test_no_template_is_ever_cold_to_the_person_being_answered` |
| friend-b and friend-c stay neutral | `test_the_other_friends_stay_neutral_for_now` |
| A redelivered message is never answered twice | `test_a_redelivered_message_is_never_answered_twice` |
| A closing is only a closing at the start of a message | `test_a_closing_is_recognised_only_when_it_leads` |
| His lines are typed, not written | `test_his_replies_are_typed_not_written` |
| Texting spellings are understood | `test_reply_text.py`, `test_reply_entities.py` |
| A named subject is answered past the ceiling | `test_a_named_subject_is_answered_even_past_the_ceiling` |
| An invitation remembered across a restart | `test_memory_survives_a_restart` |
| An accepted invitation gets a confirmation | `test_accepting_the_invitation_confirms_instead_of_agreeing` |
| Context changes the reading (`presence` vs `greeting` after a goodbye) | `test_the_table_vetoes_a_reading_that_cannot_follow` |
| Silence is possible and is not an error | `test_an_unaddressed_repeat_is_left_alone` |
| Switchboard imports in 1.24 s at **86%** coverage | run by hand, numbers in `CLASSIFIER.md` §6 |
| **Unverified by hand**: 55 answers → `/finish` → sealed `/sheet` | nobody has walked it end to end yet |
| **Unverified**: a language model, a voice per friend, memory across restarts | not built |

## 4. Uncommitted work (as of this snapshot)

The persona slice, on top of `b04ca1c`: **22 modified and 6 new paths** — new are
`bots/persona.py`, `reply/style.py`, `docs/PERSONA.md`, `tests/test_persona.py`,
`tests/test_reply_style.py`, `tests/test_reply_text.py`, `tests/test_reply_entities.py`,
`reply/text.py`, `reply/entities.py`, `bots/memory.py`, `examples/friends_world/voices.jsonl`; modified are the dataset (`characters`, `knowledge`,
`responses`, `world`), `reply/{types,datasets,replier,intents}.py`,
`bots/{identity,roster,supervisor,__init__}.py`, `tests/test_bots_roster.py`, and the docs
(`PERSONA.md`, `GROUP.md`, `STATUS.md`, `MANUAL_TESTING.md`, `README.md`,
`examples/bots.example.json`).

Earlier slices are committed: `a1b5215` (four applications), `b6387bf` (per-bot env files,
`/friendcheck`), `c121968` (classifier + corpora docs), `b04ca1c` (ignore rules).

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
- **A token cannot hold two gateway sessions, and two processes are worse than that.** They
  fight over the session and both answer every mention, which reads as double texts. `--status`
  now counts *every* process, not just the pid file, and says so; `--stop` kills them all.
  Stop the bot before a `--friendcheck` probe for the same reason.
- **`<VAR>_FILE` wants a file with one token, not an env file.** Pointing
  `TTRPG_FRIEND_A_TOKEN_FILE` at `.env.frienda` fails with "holds N non-blank line(s)"; the fix is
  `"env_file": ".env.frienda"` in `bots.json`. This actually happened on 2026-10-21 and the error
  now names it.
- **`@Bot` usually pings the bot's *role*, not the bot.** Discord creates a managed role with the
  application's name, that role is not mentionable, and the message then arrives as `<@&id>` with
  **both `mentions` and `mention_roles` empty**. The only surviving evidence is the markup in
  `content`, which `FriendBot._role_named` parses. Without that, every message looks unaddressed and
  nothing at all is logged — the failure mode that looks exactly like a dead bot.
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
| Who a friend is, and how the brief is enforced | `docs/PERSONA.md`, `bots/persona.py` |
| The group's design and invariants | `docs/GROUP.md` |
| Testing against Discord by hand | `docs/MANUAL_TESTING.md` |
