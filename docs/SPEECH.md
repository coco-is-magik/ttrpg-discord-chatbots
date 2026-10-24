# Speech: the text a voice reads, and the voice itself

Two problems that only exist on the spoken side of the bot. Text chat needs neither.

1. **Written text is not speakable text.** `$250 watch` is fine to read and wrong to say. A synthesiser
   trained on prose reads the symbol: *"dollar sign two hundred fifty watch"*.
2. **A voice is a 63 MB file in a cache.** The casting rule names it; the audio is not in the
   repository. A rebuilt box, a cleared disk or a dead mirror has to be recoverable.

---

## 1. The spoken form (`tts/spoken/`)

One module per kind of thing, because the rules do not resemble each other, and one pipeline that fixes
**the order** — which is where the original bug lived.

| Module | The one question | Example |
|---|---|---|
| `money` | what does this amount sound like? | `$1.50` → *one dollar and fifty cents* |
| `symbols` | what is this symbol as a word? | `10%` → *ten percent*, `50/50` → *fifty fifty*, `#1` → *number one* |
| `numbers` | how is this number said? | `250` → *two hundred fifty*, `1984` → *nineteen eighty-four*, `21st` → *twenty-first*, `3:30 pm` → *three thirty p m* |
| `abbreviations` | is this dot an abbreviation? | `Dr.` → *Doctor*, `e.g.` → *for example*, `St. Louis` → *Saint Louis* |
| `acronyms` | spelled out or said as a word? | `NCAA` → *N C A A*, `NASA` → *NASA* |
| `pipeline` | in what order? | see below |
| `wrap` | how does every engine get this? | a decorator around the engine |

### The order is the fix

`$250` is the proof. Money must claim the symbol and the digits **together**:

* symbols first → the `$` becomes "dollars" before the digits are read → *dollars two hundred fifty*
* numbers first → the digits become words before the symbol is recognised → *dollar sign two hundred fifty*

So the pipeline is `money → symbols → numbers → abbreviations → acronyms`, and that order is data
(`pipeline.STEPS`) with a test asserting it.

### Wrapping, not remembering

Three paths reach an engine: a casting rule (`default_factory`), the package resolver
(`resolve_synthesizer`) and a direct build. Only one of them gets remembered, so the wrap happens where
engines are **built**, and a test asserts every built engine is wrapped. `unwrap()` exists for tests and
for anything that needs the engine underneath.

**The text channel is untouched.** He types `$250`, he says *two hundred fifty dollars*. That asymmetry
is the design, not a bug: people write symbols and speak words.

### Bugs this found, in order

| Symptom | Cause |
|---|---|
| *dollar sign two hundred fifty watch* | no normalisation at all (the reported bug) |
| *10percent off* | a symbol glued to a digit was replaced without a separating space, so the number pass could not see `10` |
| *three thirty pm* | the bare clock pattern ate `3:30` and orphaned the `pm` |
| *one thousand,zero* | the thousands pattern matched one comma group, leaving `,000` behind |
| `A T&T` | a run of capitals containing an ampersand: `AT&T` is *A T and T* |
| *fifty slash fifty* | `50/50` is a ratio, not a division |

### Try it without synthesising

```bash
ttrpg-chatbots-tts --spoken '$250 watch and 10% off'
# two hundred fifty dollars watch and ten percent off

ttrpg-chatbots-tts --spoken 'Dr. Smith paid $1,200 in 1984 for the 3:30 pm slot'
# Doctor Smith paid one thousand two hundred dollars in nineteen eighty-four for the three thirty p m slot
```

### What is deliberately not done

* **No pronunciation overrides.** `Terry` is read as two words. Piper supports phoneme overrides per
  voice, which is the right home for it, and it is a persona-level concern rather than a language one.
* **No URL handling.** A URL is read as words (`slash`, `dot`), which is wrong in a specific way and
  rare in a conversation.
* **`St.` is resolved, not guessed.** "Saint" before a capitalised name, "Street" otherwise, because
  chat means street addresses more often than cathedrals.
* **No unit expansion.** `5 km` is read as written, which piper handles acceptably.

---

## 2. The voice lock (`tts/lock.py`, `voices.lock.json`)

A voice is data with a dependency attached. `examples/friends_world/voices.lock.json` is committed; the
63 MB model is not.

```jsonc
{
  "voice": "en_US-joe-medium",
  "settings": { "speed": 1.05, "volume": 1.0, "pitch": 1.0 },
  "files":   [ { "name": "...onnx", "bytes": 63201294, "sha256": "58afce…", "md5": "74fd6a…" } ],
  "sources": [ "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/joe/medium/{file}?download=true",
               "https://hf-mirror.com/rhasspy/piper-voices/resolve/main/en/en_US/joe/medium/{file}?download=true" ],
  "provenance": { "license": "CC0", "dataset": "github.com/OHF-Voice/voice-datasets",
                  "finetuned_from": "en_US-lessac-medium" },
  "rebuild_from_scratch": [ "…five steps…" ]
}
```

### Check it, or get it back

```bash
ttrpg-chatbots-tts --verify-voice          # is the cached voice the one we chose?
ttrpg-chatbots-tts --fetch-voice           # fetch what is missing, source by source
ttrpg-chatbots-tts --verify-voice --json   # machine-readable, for a startup check
```

The model lives in `$TTRPG_TTS_MODEL_DIR` or `~/.cache/ttrpg-chatbots/models/piper/`.

### The guarantees, each with the test that holds it

| Guarantee | Why it matters |
|---|---|
| Size **and** SHA-256 are checked | a truncated download is the common failure, and a corrupted one can be the right length |
| A mirror that serves other bytes is **rejected and deleted** | the digest decides, not the hostname |
| Sources are tried in order | one mirror is not a plan |
| A lock with no `{file}` in its sources is refused at load | otherwise it would look reproducible while being unable to fetch its own model |
| A bad digest length, missing file or invalid JSON is refused by name | a lock that cannot be satisfied should fail loudly, not half-install |
| The shipped lock's settings are compared against the casting rule | the tuned speed cannot drift away from the voice |

### Rebuilding from first principles

The five steps are in the lock file itself, so the procedure travels with the data:

1. fetch the two files from any source that serves them
2. verify SHA-256 against `files`, and MD5 against the upstream `voices.json` manifest
3. place them in the piper model directory
4. the casting rule in `voices.jsonl` names the voice and its speed (a test keeps the two in step)
5. **fallback if every mirror is gone**: `en_US-lessac-medium` with pitch ≈ 0.85. Joe is finetuned from
   lessac, which is why that lineage is recorded in `provenance` rather than left as trivia — it is the
   one-hop path back to a voice that sounds like him.

Licensing is CC0 on the dataset, so the model could legally be vendored if the 63 MB were ever
worth it; the lock exists so that it does not have to be.

---

## 3. Where this sits in the architecture

`tts/spoken/` is a leaf band like `render/`: pure string functions in, one string out, no engine and no
Discord. The wrapper is the seam, and it is applied at the two places engines are constructed rather
than at the call sites, which is what keeps it from being forgotten as the bot grows.

---

## What the engine cannot do

A running list, because every one of these is a thing a brief might ask for and a casting rule cannot
deliver. They are limitations of **piper**, not of the code around it -- the pitch and formant shifter in
`audio/formants.py` moves resonances, and no amount of it changes how a glottis behaves.

| asked for | status |
|---|---|
| **raspiness / vocal fry** | **not possible.** Irregular glottal pulses; no piper model produces them. Measured and accepted for Crusty (`docs/PERSONA.md` 1c), who asked for it |
| breathiness, a whisper | not possible -- same reason, it is a phonation type |
| acting: warmth, sarcasm, shouting | not possible. Delivery is flat by design; the *words* carry the register |
| emotion conditioned on context | not possible |
| a specific real person's voice | not possible, and not attempted |
| a language other than the model's | only with a model for that language; the friends are all `en_US` |
| pitch and timbre | **possible** -- `pitch_hz` and `formant`, independently, with the duration left alone |
| pace | possible -- the engine's length scale |
| hesitation | possible *in the text* (`style.stutter_rate`, `style.filler_rate`), read by the engine as written |

**When the engine changes, re-audition in this order:** raspiness (the one live gap), then acting, then
emotion conditioning. Everything else is already handled, and each voice's settings are pinned in
`examples/friends_world/voices.lock.json` so a re-audition starts from the accepted state rather than
from nothing.
