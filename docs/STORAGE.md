# Storage: why memory is a database now

The short version: memory used to be one JSON document per friend, rewritten whole on every save, up
to four times per answered message. At 594 bytes that is invisible. It is also O(entire memory) per
message, forever, over NFS — wrong at any size, and not a shape that fixes itself by waiting.

This file records the argument, what was measured, what the database does and does not solve, and the
one thing to know before deploying it anywhere else.

---

## 1. Where I was wrong

I argued for the file on the strength of "594 bytes after heavy use". Both halves of that were bad.

* **"Heavy use"** was a handful of tests, in text only, with one of three bots talking. That is not a
  load test and should not have been presented as evidence.
* **"One process, so no concurrent writers"** ignored where the process runs: `df -T` says
  **NFS, `vers=3`, `local_lock=none`**, mounted from the NAS. Atomic rename over NFSv3 is weaker than
  on a local filesystem, and the single-process assumption is exactly the one that breaks when friend
  b and c start answering.
* **"Portable"** described a file that grows without indexes. That is not portable, it is a monolith
  you have to rewrite to touch.

The argument I should have made, and now do: **the defect was the write pattern, not the byte count.**
`save()` serialised every fact, every topic counter and every pending mention, then replaced the whole
document. A growing memory meant a growing write per message. That is the thing a database fixes, and
it is measurable today rather than hypothetically at 500 GB.

## 2. What replaced it

`src/ttrpg_chatbots/memory/db.py` — one SQLite database, `data/memory.db`, six tables:

| Table | Holds | Notes |
|---|---|---|
| `friend` | who, last seen, sessions, pending invitation | one row per friend |
| `fact` | `pet.name = otis`, said_by, count, meta | primary key `(friend, key)`, so saying it twice updates rather than duplicating |
| `topic` | what they ask about, counted | capped at twenty *on write*, as before |
| `pending` | mentions that did not earn a place yet | capped at fifty, as before |
| `telling` | how often each story was told | **new table**: the told-counts used to ride in the capped topic counter |
| `journal` | append-only: what changed, when, why | the part that makes recovery possible rather than theoretical |

`bots/memory.py` keeps exactly the API it had (`load`, `save`, `facts`, `remember_facts`,
`mark_raised`, `forget`, `note`, `remember_topic`, `remember_plan`, `remember_told`), so the ladder and
the supervisor did not change. The only thing that knows the engine is `Database`.

**SQLite rather than Mongo**, and the reasons can be rejected: no server to keep up, no dependency, no
network hop for a 594-byte write, and `sqlite3 memory.db .dump` gives you readable SQL. Every benefit
claimed for the JSON file — copy it, inspect it, back it up — still holds. Mongo earns its place the
day more than one *host* writes concurrently; until then it is an operations burden in exchange for
problems we do not have.

## 3. What it guarantees, and how that is tested

`tests/test_memory_db.py` exists to hold each claim to account:

| Claim | Test |
|---|---|
| a write is row-scoped, not whole-database | `test_a_save_does_not_rewrite_another_friends_rows` |
| a forgotten fact cannot linger | `test_dropping_the_other_facts_is_a_save_not_a_merge` |
| the file is coherent | `test_integrity_check_says_ok` |
| a backup is a consistent copy | `test_a_backup_is_a_consistent_copy`, `..._survives_the_original_being_destroyed` |
| every change is recorded | `test_every_change_is_journalled` |
| two writers queue instead of clobbering | `test_two_writers_do_not_clobber_each_other` |
| a corrupt file is an error, not an empty memory | `test_a_corrupt_file_is_reported_rather_than_silently_empty` |
| the old data survives the upgrade | `test_the_old_json_files_are_imported_once` |

The migration runs automatically at startup (`build_entries`), imports any `data/friends/*.json` the
database does not already have, and is idempotent. The old files stay where they are: they are a
pre-upgrade snapshot, and they are git-ignored anyway. `story:<id>` entries in the old topic counters
move into `telling`, where they are no longer capped at twenty.

## 4. Operating it

```bash
# what does he know?
sqlite3 data/memory.db "SELECT friend, key, value FROM fact ORDER BY friend, key;"

# what changed recently?
sqlite3 data/memory.db "SELECT at, friend, kind, detail FROM journal ORDER BY id DESC LIMIT 20;"

# is the file coherent?
sqlite3 data/memory.db "PRAGMA integrity_check;"

# a backup you can actually restore, while the bot runs
.venv/bin/python -c "from ttrpg_chatbots.memory.db import Database; print(Database().backup('data/backups/memory.db'))"

# readable text, for review or for moving house
sqlite3 data/memory.db .dump > data/memory.sql
```

Configuration:

| Variable | Meaning |
|---|---|
| `TTRPG_MEMORY_DB` | path to the database (default `data/memory.db`) |
| `TTRPG_MEMORY_JOURNAL` | `DELETE` (default) or `WAL` -- see below |
| `TTRPG_FRIENDS_MEMORY_DIR` | the directory the database lives in, for tests and alternate deployments |

**The one deployment caveat, and it matters.** The default journal mode is `DELETE`, not `WAL`, because
WAL needs shared memory that NFSv3 with `local_lock=none` does not reliably provide. That is the safe
choice for the filesystem we actually have. If the database moves to a **local** disk, set
`TTRPG_MEMORY_JOURNAL=WAL`: readers stop blocking the writer and it is meaningfully faster. If more
than one **host** ever writes, neither mode is enough -- that is the point at which this module gets a
Postgres or Mongo implementation, and `Database` is the only file that would change.

## 5. What the database does not solve

* **It is not a backup strategy on its own.** `backup()` gives a consistent copy; something has to call
  it and put the result somewhere else. A cron job or a startup hook, next.
* **It does not make multi-host safe.** It makes single-host, multi-writer safe. The line is in §4.
* **It does not remember more than it did.** `memory.encode` still recognises four kinds of fact, and
  that is deliberate: a system that tries to remember everything remembers nothing.
* **The write is still whole-friend.** A save replaces one friend's rows rather than doing field-level
  updates. That is a deliberate stopping point -- the cost is bounded by one person's memory, not the
  database -- and it is the first thing to narrow if it ever shows up in a profile.
