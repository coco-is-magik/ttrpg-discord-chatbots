# The classifier, and the corpora behind it

How a friend decides what to say, without a language model — and which pre-existing datasets can
make that decision better. `GROUP.md` §3–4 is the plan; this file is the engineering record:
what exists, what was measured, what was rejected, and on what licence.

The short version: **the classifier was missing context, not vocabulary.** The corpora below are
worth having because they measure *what follows what*, and that is now a first-class input.

---

## 1. Three inputs, in order

| Layer | Module | Decides | Deterministic |
|---|---|---|---|
| Social intents | `reply/intents.py` | is this a greeting / thanks / goodbye / … | yes, regex |
| Knowledge | `reply/ncd.py`, `reply/replier.py` | which tagged fact is this about | yes, compression distance |
| Context | `reply/context.py`, `reply/transitions.py` | does that reading fit here, and should we speak at all | yes, a count table |

Everything is inspectable: a regex list, a distance number, an integer table. No weights are
learned at runtime and nothing is hidden inside a vector.

## 2. What context is allowed to do

Exactly two things, both in `Replier`:

1. **Veto a reading that cannot follow.** `"hey, anyone around tonight?"` matches both presence
   and greeting. Priority alone says presence. If the previous turn was a goodbye, and nothing in
   the table ever follows a goodbye with a presence question, greeting wins instead. The rule is
   one sentence — *this transition was never observed* — with no thresholds to tune.
2. **Stay quiet.** For an *unaddressed* remark: if the human already said this line, or if the
   friend's own last line was the same move, silence beats repetition. A mention always gets an
   answer; naming someone and being ignored is worse than being repetitive.

`context=None` reproduces the old behaviour exactly, which is why every earlier test still passes
unchanged.

**Not** in scope, deliberately:

- **Ellipsis resolution** ("what about the guild?"). Tempting, and it produces confident wrong
  answers from a stale topic. It needs a measurement gate before it earns its place.
- **Durable memory.** The window is in-process and dies with the bot. `memory/` arrives with the
  model slice.
- **Personality.** Nothing here writes a persona. The tables decide *shape*, never voice.

## 3. The corpora, and whether they fit

| Corpus | Size | Context? | Labels | Licence | Verdict |
|---|---|---|---|---|---|
| **Switchboard (SwDA)** | 1,155 conversations / 122,646 utterances | **yes** — turn sequences, `reply_to` links | 42 DAMSL tags (collapsible) | CC BY-NC-SA 3.0 | **used** — the act-transition source |
| **DailyDialog** | 11,118 + 1,000 + 1,000 dialogues | yes, 2–15 turns | 4 acts (inform/question/directive/commissive) + 7 emotions | CC BY-NC-SA 4.0 | rejected — 4 classes cannot express "thanks" |
| **SODA** | 1.19M train / 1.49M total dialogues | yes, 3–11 turns, speakers | none (generated from commonsense tuples) | **CC BY 4.0** | deferred — a response pool, not a labeller |
| **EmpatheticDialogues** | 76,673 + 12,030 + 10,943 rows | yes, plus an emotional situation | 32 emotions | CC BY-NC 4.0 | deferred with personas |
| **GoEmotions** | 54,300 (simplified) / 211,000 (raw) comments | **no** — single Reddit comments | 27 emotions + neutral | **Apache 2.0** | deferred — no context, wrong axis |
| **PersonaChat** | ~10,900 conversations | yes | persona sentences | *not confirmed* | not used |
| **Cornell Movie-Dialogs** | 10,292 conversations / 304,713 utterances | yes | none | ambiguous / research use | not used |

Sizes and licences were read from the dataset cards on 2026-10-21; re-check before relying on
them.

### Why Switchboard is the one that fits

It is the only widely used corpus that annotates **dialogue acts on real turn sequences**, and
its tag set contains the moves we actually have: `fp` conventional-opening, `fc`
conventional-closing, `ft` thanks, `fa` apology, `aa` agree/accept, `bk` backchannel,
`sd`/`sv` statements. That is a direct map onto `social:*`.

The cost is real and worth stating: it is 1990s telephone speech about childcare, recycling and
the news. Its *vocabulary* is nothing like a tabletop group — but we are not using its words, only
which act followed which. Topic mismatch barely touches that statistic.

### Why the others are deferred rather than rejected

- **DailyDialog** is cleaner English and human-written, but four acts cannot distinguish a
  greeting from thanks. Mapping `inform` onto `social:smalltalk` would be inventing agreement
  between two label systems that mean different things.
- **SODA** is the only permissive *dialogue* corpus here (CC BY 4.0, 1.19M dialogues) and would be
  the obvious source of response *templates*. But its value is variety of phrasing, which only
  matters once a personality exists. Without one, 1.19M neutral lines are 1.19M ways of saying
  nothing in particular.
- **GoEmotions** is the most permissively licensed and very large, and it has no context at all:
  one comment, no parent, no reply. It measures *tone*, not *sequence* — an axis we do not have
  yet and do not want before a persona exists.
- **EmpatheticDialogues** is the closest to "someone is upset, respond well", which is the single
  most valuable friend behaviour after greeting. It is CC BY-NC and its unit is an emotional
  situation, so it belongs with the persona work, not before it.
- **PersonaChat / Cornell** — the licence could not be confirmed from the card (PersonaChat's
  mirrors vary, and ParlAI's repository licence does not automatically cover the data). Not
  worth the ambiguity for a dataset we do not need yet.

## 4. Licences: what may be committed

Two rules, and one judgement call made explicit.

**No corpus text ever enters this repo.** The importer reads a file you downloaded and emits
integer counts; `reply/importers.py` never returns a sentence. That keeps the repository free of
somebody else's dialogue and keeps `data/` small.

**Any table imported from a corpus is regenerated, not vendored.** The importer is the record of
provenance; its output is a build artefact. `examples/friends_world/transitions.json` ships with
`"source": "authored"` and says so in a `note`, so a hand-written guess can never be mistaken for
a measurement.

**The judgement call:** a table of transition counts is a statistic about language, not a copy of
a corpus, and for a private non-commercial game that is within the spirit of a non-commercial
licence. A strict reading of CC BY-NC-SA would still call the derived table a derivative work.
Since that reading is arguable, the safe default wins: **do not commit a table derived from an NC
corpus.** Regenerate it locally with the command below.

## 5. Importing a corpus

### Switchboard, once

The corpus is a **5.5 MiB zip** and needs no library to fetch — `convokit` pulls in pandas,
scikit-learn and spacy for what we only ever read as a file. It lands in `corpora/`, which is
git-ignored (see `corpora/README.md`):

```bash
mkdir -p corpora/switchboard && cd corpora/switchboard
curl -LO https://zissou.infosci.cornell.edu/convokit/datasets/switchboard-corpus/switchboard-corpus.zip
unzip -q switchboard-corpus.zip && mv switchboard-corpus/* . && rmdir switchboard-corpus
rm switchboard-corpus.zip          # 37 MiB of JSONL is what we actually read
```

Point the importer at the file, from the repository root:

```bash
.venv/bin/ttrpg-chatbots-reply \
    --import-acts corpora/switchboard/utterances.jsonl \
    --format switchboard \
    --min-coverage 0.25 \
    --out corpora/switchboard/transitions.json
```

Measured on 2026-10-21, on this box:

```
switchboard: 122646 utterances, 106026 mapped (86%), 104871 transitions, 6 rows;
             unmapped: %=15230, qy=3776, x=3611, ny=2807, qw=1887
wrote corpora/switchboard/transitions.json
```

1.24 s, and the table it writes is **1,122 bytes**.

Coverage is 86% because `sd` (69,792 utterances), `b` (36,043), `sv` (25,427) and `+` (17,683)
are four of the five most frequent tags in the corpus. The leftovers are almost all questions,
non-verbal markers and `%` (uninterpretable/self-talk) — none of which are social moves, and all
of which are reported rather than guessed. A 5% coverage line would mean the mapping is wrong;
86% means the mapping is doing what it should.

To widen the mapping, pass your own; the default is `SWDA_MAP`:

```python
from ttrpg_chatbots.reply import intents as social
from ttrpg_chatbots.reply.importers import SWDA_MAP, from_switchboard

mapping = {**SWDA_MAP, "b^m": social.SOCIAL_AGREEMENT}   # maybe/accept-part
print(from_switchboard(path, mapping=mapping).report())
```

Then put the table beside the dataset — `FriendChat` looks for `transitions.json` next to
`world.json`:

```bash
cp corpora/switchboard/transitions.json examples/friends_world/transitions.json   # only if you accept §4
```

Or leave it in `corpora/` and point at it, which is what the licence rule recommends and what the
layout expects:

```bash
echo 'TTRPG_FRIENDS_TRANSITIONS=corpora/switchboard/transitions.json' >> .env
```

Precedence is: an explicit `transitions=` argument, then `TTRPG_FRIENDS_TRANSITIONS`, then the
file beside the dataset. The committed table stays `authored`, so a fresh clone behaves the same
everywhere and a local measurement can never silently become the default.

### Anything already labelled in our own acts

`--format jsonl` reads either shape verbatim, with no mapping at all:

```jsonc
{"conversation": "c1", "index": 0, "act": "social:greeting"}
{"conversation": "c2", "turns": [{"act": "social:greeting"}, {"act": "social:thanks"}]}
```

That is the path for a hand-made corpus of the group's own transcripts later — the only corpus
whose vocabulary actually matches.


## 6. What has been measured

| Claim | Number | Where |
|---|---|---|
| NCD cannot separate smalltalk from lore | `hey` 0.92 against its own anchor; `tell me about the guild` 0.71 against an apology | `reply/intents.py` |
| A ceiling that refuses unknown questions | closest non-social query 0.714, ceiling set to 0.65 | `bots/chat.py` |
| The friends dataset | 9 anchors, 28 templates, 3 friends | `examples/friends_world/` |
| The authored table | 8 rows, 137–160 counts per row, 2,367 bytes | `transitions.json` |
| The real Switchboard import | 122,646 utterances → **106,026 mapped (86%)**, **104,871 transitions**, 6 rows, **1,122 bytes**, 1.24 s | §5 above |

### What the real table actually says

Measured on Switchboard, 2026-10-21. Rows are the previous act; proportions are of that row.

| previous | n | most likely next | zero cells |
|---|---|---|---|
| agreement | 62,377 | agreement 0.544, smalltalk 0.425, thanks 0.025 | — |
| smalltalk | 37,485 | **agreement 0.721**, smalltalk 0.221, thanks 0.056 | — |
| thanks | 3,734 | smalltalk 0.516, agreement 0.450 | greeting |
| goodbye | 1,068 | goodbye 0.898, agreement 0.070 | apology, greeting |
| greeting | 167 | greeting 0.515, smalltalk 0.251, agreement 0.216 | apology, goodbye |
| apology | 40 | smalltalk 0.525, agreement 0.400 | apology, greeting |

Three things worth knowing before trusting it:

1. **Most talk is acknowledgement.** The two dominant rows are `agreement` and `smalltalk`, and
   `smalltalk → agreement` (0.72) is the single most common move in the corpus. That is what a
   telephone conversation is: someone says something, the other person makes a noise. It is also
   a warning — a friend trained on this would lean towards "mm-hmm", which is exactly the
   behaviour `social/policy.py` will have to resist.
2. **The rows that matter to us are the thin ones.** `greeting` is 167 transitions and `apology`
   is 40, against 62,377 for `agreement`. Their zero cells are therefore weak evidence, not
   strong: greeting→goodbye is zero because a five-minute call does not open and close in one
   exchange. **A zero in a thin row is not a law.**
3. **The binary veto barely fires on a dense table.** `agreement` and `smalltalk` have no zero
   cells at all, so no candidate is ever rejected after them. The authored table vetoes more
   precisely *because* it is sparse — it encodes judgement where the corpus has no data, and it
   vetoes the case we cared about (a presence question after a goodbye). Choose between them on
   that trade, not on size: the measured table is better evidence for *ranking*, the authored one
   is better for *refusing*.

With the measured table loaded, the goodbye case still vetoes (goodbye has zero cells for both
`greeting` and `presence`), but it now falls through to priority order rather than to greeting —
because a phone call never reopens. That is a real difference between the two tables, and it is
visible in the log line's `after` field.

## 7. Ranked ways to push it further

1. **Import the real table** (§5). No runtime cost, no new dependency, and it replaces a guess
   with tens of thousands of observations. Do this before anything else.
2. **A retrieval prefilter.** NCD is O(n) compressions per query. At 9 anchors that is nothing; at
   5,000 knowledge items it is thousands of compressions per message. A TF-IDF cosine pass in
   numpy — already a dependency — to pick the top 50, then NCD to rank those, keeps NCD's quality
   and drops the cost. Build it when the lore dataset passes ~1,000 items, not before.
3. **A learned act classifier.** Logistic regression over character n-grams, trained offline on
   Switchboard, weights exported as JSON. Still dependency-free at runtime, still deterministic,
   and it would catch moves the regexes miss ("evening all", "morning"). Only the training script
   is new, and it never runs in the bot.
4. **Response selection from SODA or EmpatheticDialogues.** Genuinely valuable, genuinely blocked:
   without a persona there is nothing to select *as*.

## 8. What this will not become

- **No embeddings, no vector database.** A 40 MB model to answer "hello" is cost with no
  corresponding gain, and it makes a decision unauditable.
- **No torch or transformers in the runtime.** This box runs Python 3.14 with neither, and the
  engine's claim is that a fresh clone runs.
- **No learned end-to-end responder.** When a language model arrives it arrives as the *primary*,
  with this classifier as the fallback it already is. A fallback has to be good on its own, which
  is why it is measured rather than assumed.

## 9. What it costs on disk

Measured on this box, 2026-10-21. The point of the table is that **the intelligence here is
nearly free**: everything the classifier decides from is smaller than a photograph.

| Thing | Size | Notes |
|---|---|---|
| Switchboard zip | **5.5 MiB** | 5,810,437 bytes; delete after unzipping |
| Switchboard extracted | **37 MiB** | `utterances.jsonl` alone is 36.2 MiB — lives in `corpora/switchboard/` |
| The table it produces | **1.1 KiB** | 1,122 bytes, six rows, 104,871 observations behind it |
| The shipped authored table | **2.3 KiB** | 2,367 bytes, readable and diffable |
| `examples/friends_world/` | **7.8 KiB** | five small files: anchors, templates, characters, world, table |
| Whole `examples/` tree | 21 KiB | includes the demo world |
| `src/` | 2.0 MB | 20 modules' worth of comments included |
| `tests/` | 3.2 MB | fixtures and expected-output files dominate |
| `docs/` | 141 KB | |
| Repo excluding `.venv`, `.git` and `corpora/` | **10.3 MiB** | the whole project, all four bots included |
| `corpora/` (git-ignored) | **37 MiB apparent**, 11 MiB on this filesystem | 38,441,299 bytes, of which the JSONL is 36.2 MiB; the filesystem compresses it |
| `data/` (runtime state) | 308 KB | characters, seats, bots, portraits, logs |
| `.venv` | **332 MB** | already installed; see below |

The corpus is 3.7× the size of the entire tracked repository, which is the argument for
`corpora/` being ignored rather than curated: `git add corpora/` stages exactly one file
(`README.md`), and that is verified by an ignore rule rather than by discipline.

**Do not install `convokit` for this.** It brings pandas, scikit-learn, spacy and nltk — roughly
250–400 MB of dependencies — to read a JSONL file that `curl` fetches in a second. The venv is
already 332 MB because of the speech stack (piper 40 MB, onnxruntime 38 MB, av 52 MB,
ctranslate2 61 MB, numpy 36 MB, sherpa-onnx 19 MB, vosk 11 MB, zstandard 9.1 MB), and none of it
is needed by the reply engine. The reply engine needs CPython and `zlib`.

### The corpora we are *not* using

| Corpus | Download | Verdict |
|---|---|---|
| GoEmotions | 28.3 MB (simplified-only: 3.5 MB) | not downloaded |
| DailyDialog | 4.5 MB | not downloaded |
| EmpatheticDialogues | 28 MB | not downloaded |
| SODA | **816 MiB** (train alone 657 MiB) | not downloaded — half a gigabyte for response variety we cannot use before a persona exists |

### When a model arrives

Nothing here is installed; these are the numbers to plan against, and they dwarf everything
above. A small local ASR model is hundreds of megabytes; a 7B model at Q4 is around 4 GB; a hosted
API is 0 bytes on this disk and a fraction of a cent per day. This is why `GROUP.md` §11 ranks
"hosted cheap model" above "local model" — not for quality, but because the whole classifier
stack, corpora included, currently costs less than one model file.

- **No embeddings, no vector database.** A 40 MB model to answer "hello" is cost with no
  corresponding gain, and it makes a decision unauditable.
- **No torch or transformers in the runtime.** This box runs Python 3.14 with neither, and the
  engine's claim is that a fresh clone runs.
- **No learned end-to-end responder.** When a language model arrives it arrives as the *primary*,
  with this classifier as the fallback it already is. A fallback has to be good on its own, which
  is why it is measured rather than assumed.

