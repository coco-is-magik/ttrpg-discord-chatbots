# ttrpg-chatbots

A private Discord table: one human and three bots who are both **people in the group** and
**characters at the table**. A non-conversational sheet portal for building and maintaining a
character, and a conversational group that plays House Games on game night and chats in
between. The humans do the choosing; the machines do the arithmetic and the remembering.

**Where we are right now**: [`docs/STATUS.md`](docs/STATUS.md) — a dated snapshot of what runs,
what is verified, what is uncommitted, and the next three actions.

**Where it is going**, and the rules it holds itself to:
[`docs/DESIGN.md`](docs/DESIGN.md) — principles, cast, architecture, phases with exit
criteria, risks, open decisions.

**The sheet, as a UI**: [`docs/SHEET_UI.md`](docs/SHEET_UI.md) — the four message surfaces,
why they live in a private thread per character, and how edits stay safe when two things change
at once.

**The group, as a design**: [`docs/GROUP.md`](docs/GROUP.md) — what a bot remembers, who speaks
and when, the ambient rhythm, the table's scene and floor, and the contract for each.

**The classifier, and the corpora behind it**: [`docs/CLASSIFIER.md`](docs/CLASSIFIER.md) — the
three inputs, what context is allowed to do, which published dialogue-act corpora fit and on what
licence, and how to import one.

**How conversation is being rebuilt**: [`docs/CONVERSATION.md`](docs/CONVERSATION.md) — the ~45
module decomposition, the specificity ladder, the dataset layout. **The day**:
[`docs/SCHEDULE.md`](docs/SCHEDULE.md) — the 15-minute NPC schedule he draws on.

**What the friends are doing**: [`docs/LIFE.md`](docs/LIFE.md) — why the old opinion bank read
like forum posts, the three phases of an actual conversation, and the life a friend draws on.

**Who the friends are**: [`docs/PERSONA.md`](docs/PERSONA.md) — the brief for each written friend,
the schema, and the tests that stop the brief and the dataset drifting apart.

**Testing it against Discord by hand**: [`docs/MANUAL_TESTING.md`](docs/MANUAL_TESTING.md).

What exists today is the substrate and the sheet: reading, creation and mutation of a
character, the 55-question interview, merits priced from the book, structured dice, the
compression classifier, three LLM backends, TTS casting and voice playback — fifty slash
commands on one **helper** bot that never reads a message. **Four Discord applications can run
together** (`bots/`): the helper, plus three *friends* that are configured and dormant until
their tokens exist, with a permission audit that logs exactly what Discord is refusing.
Personality, memory and ambient chat are the next phases.

## Install

Python 3.12+ is required. A virtual environment is mandatory (no global installs):

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[test,voice,tts]'
```

**Always install with `.venv/bin/python -m pip`, never `.venv/bin/pip`.** A virtualenv is
not relocatable: if it is copied or moved, its `pip` wrapper, activation scripts and console
scripts keep pointing at the old directory, so installs appear to succeed and land in the
wrong place. `python -m pip` always uses the interpreter you named. If you ever suspect a
stale environment, delete it and recreate it — `rm -rf .venv` — rather than repairing it;
`tests/test_layout.py` fails the suite when an environment or a file points at another
checkout.

Runtime dependencies: `discord.py`, `python-dotenv`. Dev dependencies: `pytest`. Optional
extras: `stt`, `tts`, `voice`, `reply`.

Check the configuration without contacting Discord (validates the token format and reports
whether voice can work):

```bash
.venv/bin/ttrpg-chatbots-bot --check
```

## Run

```bash
.venv/bin/ttrpg-chatbots        # console script
.venv/bin/python -m ttrpg_chatbots
```

Both print `Hello, world!`.

## Discord bot

Libraries: `discord.py` 2.7.1 (async gateway client, pulls `aiohttp`) and
`python-dotenv` 1.2 for local credential files.

### 1. Create the application

1. Discord developer portal -> New Application -> **Bot** -> **Reset Token**, copy the token.
2. Invite the app with the `bot` and `applications.commands` scopes.

The scaffold uses slash commands, which need no privileged intents. Adding
message-prefix commands later requires enabling the Message Content intent.

### 2. Provide the token

Credentials are never hardcoded and never committed. Token sources, highest
precedence first:

| Source | Use case |
| --- | --- |
| `DISCORD_TOKEN_FILE` | Docker secrets, systemd `LoadCredential`, password-manager export |
| `DISCORD_TOKEN` | shell export, CI |
| `./.env` | local development only: plain text on disk, git-ignored, mode 600 |

A real environment variable always wins over `.env`. `DISCORD_GUILD_ID` is
optional; set it to a server id so slash commands sync instantly instead of
globally (global sync can take an hour to appear).

```bash
cp .env.example .env       # then edit it and chmod 600 .env
.venv/bin/ttrpg-chatbots-bot
```

The repository ships **dummy credentials** in the ignored `.env`, so the bot
starts, loads config, and is rejected by Discord with
`LoginFailure: Improper token has been passed.` until you supply a real token.

### 3. Secrets hygiene

`.gitignore` blocks `.env`, `.env.*` (except `.env.example`), `*.env`, `secrets/`,
`*.pem`, `*.key`, `*.p12`, `*.token`, `*.secret`, `*creds*.json`,
`*credentials*.json`, `*secret*.json`, and `service-account*.json`.
`tests/test_secrets.py` fails the suite if a Discord-token-shaped string appears
anywhere in the repository, or if any of those paths stops being git-ignored.

### 4. Commands, and testing it yourself

Start it with the convenience script at the project root — it validates the environment,
refuses to run with a secret that git would commit, and gives you one way to stop it:

```bash
./start-bot.sh --check        # config + voice, no connection
./start-bot.sh                # foreground; Ctrl-C stops it
./start-bot.sh --background   # detached, logs to data/logs/bot.log
./start-bot.sh --status       # is it running?
./start-bot.sh --logs         # follow the log
./start-bot.sh --stop         # stop the detached bot
```

Once it is running, the bot answers these slash commands:

| Command | What it does |
| --- | --- |
| `/ping` | `Pong!` — proves the gateway and the command sync |
| `/friendcheck send:…` | are the friends online, can they post, and what did they last hear? |
| `/botcheck` | every permission this bot needs, and the fix for each one it is missing |
| `/voices` | the cast table, plus whether voice is usable on this machine |
| `/ask question:… character:… speak:true` | answer as a character; `speak` also says it aloud |
| `/claim character:…` | claim an unclaimed character; this is how you get a seat |
| `/create name:…` | build a character from scratch, in a private thread |
| `/characters` | your characters, and which one is active |
| `/play character:…` | switch which character you are playing |
| `/budget section:… seven:… five:… three:…` | choose which group gets 7/5/3 (or 13/9/5) |
| `/build` · `/finish` | remaining creation budgets · submit and seal |
| `/flaw name:… rating:…` | take a Flaw; it pays freebie points |
| `/page number:…` | move between questionnaire pages |
| `/sheet` | your own character (or any, with permission) |
| `/spend trait:… to:… pool:…` | raise a trait; replies with the receipt and what is left |
| `/options trait:…` | what the next point costs, or a list of everything raisable |
| `/edit trait:… to:…` | set a trait directly (free; caps still apply) |
| `/ability name:… rank:… category:…` | add a Talent, Skill or Knowledge |
| `/background name:… dots:…` | add a Background |
| `/remove trait:…` | take an ability or background off the sheet |
| `/pool pool:… amount:…` | set a freebie or xp balance (correction) |
| `/specialty ability:… text:…` | name or clear an ability specialty |
| `/ungift name:…` | remove a Gift that should not be there |
| `/hurt levels:…` / `/heal levels:…` | move along the health track |
| `/undo` | reverse your last sheet edit |
| `/gift name:… rating:…` | award a Gift (Harbinger's price; costs nothing) |
| `/mission outcome:win\|loss gift:…` | settle a Game: 10 XP + a Gift, or 5 XP |
| `/history limit:…` | every accepted change, with revision numbers |
| `/answer number:… text:…` | rewrite one interview answer (draft only) |
| `/done` / `/unlock reason:…` | seal the character, or reopen it for a Revision |
| `/export` / `/import file:…` | download the character as JSON, or load it back |
| `/roll count:… sides:… modifier:…` | dice as separate options, no notation to remember |
| `/roll check:stealth character:sable` | named checks and attribution |
| `/join` / `/leave` | join your voice channel and hold a playback stream open |
| `/say text:… character:…` | speak arbitrary text in that character's voice |
| `/stop` | clear the queue mid-sentence |

### More than one bot

`ttrpg-bot` is the **helper**: every command above belongs to it, and it never reads an ordinary
message, so it needs no privileged intent. The three **friends** are separate Discord
applications listed in `data/bots.json` (copy [`examples/bots.example.json`](examples/bots.example.json)) —
each with its own token, and a friend with no token is *dormant* rather than an error:

```bash
./start-bot.sh --check
#   ttrpg-bot (helper) — token set
#   friend-a (friend) — dormant (no TTRPG_FRIEND_A_TOKEN)
```

`/botcheck` audits the helper's own permissions in the channel it is run in; every friend audits
itself when it connects, and logs each missing permission with the setting that fixes it.

**friend-a answers when mentioned**, using the compression classifier — deterministic social
intents (greeting, presence, thanks, goodbye, apology, agreement, smalltalk, comfort) in front of
tagged knowledge, with no model and no API key. It also knows what was just said: a small
act-transition table vetoes a reading that cannot follow the previous turn, and an unaddressed
remark is left alone rather than answered twice.

**friend-a is a person called TopGuy**, not a generic assistant: bombastic, warm, and willing to
tell you what he thinks about hockey (the Rangers), computers, Pokémon, Rome, Terry Davis, the
history of computing, hunting, fishing or woodworking — and to say plainly when he does not know
something. `friend-b` and `friend-c` are connected and listening but switched off
(`reply: off`), and are still deliberately neutral. The brief and the tests that hold it are in
[`docs/PERSONA.md`](docs/PERSONA.md); the group's design and what waits for a model is in
[`docs/GROUP.md`](docs/GROUP.md); the corpus and licensing picture is in
[`docs/CLASSIFIER.md`](docs/CLASSIFIER.md).

To prove the whole pipe — tokens, gateway, Message Content, sending, receiving — with the bot
stopped:

```bash
./start-bot.sh --stop
.venv/bin/ttrpg-chatbots-bot --friendcheck general   # channel id or name
./start-bot.sh --background
```

It posts one labelled line from each friend, reports what each one received, and deletes its
own messages. Live, the same check is `/friendcheck` (add `send:true` to make them speak).

Sheet management is a v1 loop, entirely inside Discord:

```text
/sheet                      → numbers, pools, revision, interview progress
/spend trait:Stealth to:3   → "Stealth 2→3 — 2 freebies — 13 freebies left"
/options                    → "Dexterity 2→3: 5 freebies" … (planning, no commitment)
/unlock                     → reopen for a Revision (the rules' own word for it)
/answer number:12 text:…    → rewrite one answer, recorded in history
/done                       → seal; from then on changes are amendments
/edit trait:Dexterity to:4   → "Dexterity 2→4" (free; /undo reverses it)
/ability name:Sailing rank:2 category:skill
/background name:Contacts dots:3
/remove trait:Academics
/pool pool:freebies amount:15   → "freebies 0→15" (imported sheets start empty)
/specialty ability:Melee text:Improvised
/hurt levels:1              → "hurt 1: health 7/8"
/export                     → edit 55 paragraphs in a real editor, then /import
```

Every write is a compare-and-swap on the character's `revision`, so a second device, a
GM and a player cannot silently lose each other's changes.

Voice needs `PyNaCl`, the DAVE library and a system `libopus`; the `voice` extra
covers the first two, and `voice_readiness()` names whatever is missing.

Discord's terms do not allow automated harnesses on real accounts, so the live bot
is tested by hand. Building a character from scratch in Discord is planned in
**[`docs/CREATION.md`](docs/CREATION.md)**.

**[`docs/MANUAL_TESTING.md`](docs/MANUAL_TESTING.md)** is the
script for that: creating the application, the invite URL, real credentials, and a
step-by-step walkthrough with the expected output and a troubleshooting table.

**Not wired yet:** the friends are connected but do not answer — the listener, memory and
personality are the slices in [`docs/GROUP.md`](docs/GROUP.md); the helper never listens by
design, and there is no speech-to-text from Discord yet. There is no language model unless you
configure one. Freebie pools are only known for characters built by the wizard — imported
sheets start at 0, because the workbook never recorded what was left.

## Speech-to-text: measured engine selection

`ttrpg-chatbots-stt` times every STT engine that can run on this machine against a
deterministic 3 s clip, keeps the fastest one loaded, and caches the winner against
a fingerprint of the box (CPU count, OS, Python and package versions, clip hash).
Nothing is hardcoded: another box races again and may pick another engine, and a
missing package is reported and skipped instead of breaking startup.

```bash
.venv/bin/pip install -e '.[stt]'                     # numpy, vosk, faster-whisper, sherpa-onnx
.venv/bin/ttrpg-chatbots-stt --list                   # what runs here, and why not
.venv/bin/ttrpg-chatbots-stt                          # race, or reuse the cached winner
.venv/bin/ttrpg-chatbots-stt --refresh                # force a new race
.venv/bin/ttrpg-chatbots-stt --engine faster-whisper  # override the race
.venv/bin/ttrpg-chatbots-stt --transcribe clip.wav    # 16 kHz mono 16-bit PCM
```

Measured on this 32-thread box (RTF = compute seconds per second of audio, lower is
better):

| engine | model load | median per 3 s utterance | RTF |
| --- | --- | --- | --- |
| vosk | 1.21 s | **73 ms** | 0.024 |
| faster-whisper (tiny.en int8) | 3.34 s | 124 ms | 0.041 |
| sherpa-onnx | – | – | needs `TTRPG_STT_SHERPA_MODEL` |

Ranking uses steady-state per-utterance latency; model loading happens once per
process and is reported but not ranked. The winner is cached in
`$XDG_CACHE_HOME/ttrpg-chatbots/stt-probe.json`, so a warm startup costs one model
load (~2.5 s wall here) instead of a full race.

From code:

```python
from ttrpg_chatbots.stt import resolve_recognizer

resolution = resolve_recognizer()          # or engine="vosk"
text = resolution.recognizer.transcribe(clip)
```

| Variable | Effect |
| --- | --- |
| `TTRPG_STT_ENGINE` | force an engine (same as `--engine`) |
| `TTRPG_STT_MODEL_DIR` | where downloaded models are cached |
| `TTRPG_STT_OFFLINE` | never download; engines without a local model are skipped |
| `TTRPG_STT_VOSK_MODEL`, `TTRPG_STT_WHISPER_MODEL`, `TTRPG_STT_SHERPA_MODEL` | explicit model paths |
| `TTRPG_STT_LANGUAGE` | faster-whisper language (default `en`) |

The timing clip is synthesised, not recorded: identical bytes on every machine, no
voice data vendored, no network. It measures speed, not accuracy — check accuracy
with real recordings through `--transcribe`. Only the `stt` extra is needed at
runtime, so the core install stays dependency-free.

## In-character replies: compression classification (no LLM)

`ttrpg-chatbots-reply` answers from tagged data only: text is ranked against the
knowledge base with Normalised Compression Distance (no model, no training, no
network), gated by the tags a character is allowed to know, then rendered through
in-character madlib templates.

```bash
.venv/bin/pip install -e '.[reply]'   # optional zstd; the engine itself is stdlib-only
.venv/bin/ttrpg-chatbots-reply --validate                    # dataset check + who-knows-what
.venv/bin/ttrpg-chatbots-reply --ask "what is the sunken crown?" --character brannoc
.venv/bin/ttrpg-chatbots-reply --classify "what is the sunken crown?"
.venv/bin/ttrpg-chatbots-reply --ask "..." --compressor lzma --top-k 3 --json
```

```
$ ttrpg-chatbots-reply --ask "what is the sunken crown?" --character brannoc --speaker Tav
Brannoc the Archivist [lore:relic via k-relic-crown, d=0.682]:
The Sunken Crown? Aye. The Sunken Crown is a tide-iron circlet lost when the Saltreach fleet broke at Greyfall.

$ ttrpg-chatbots-reply --ask "what is the sunken crown?" --character orla --speaker Tav
Orla the Tavernkeep [no knowledge, d=0.682 (deflected)]:
I only know what is said over a cup, Tav.
```

### How classification works

`ncd(x, y) = 2·C(xy) / (C(x) + C(y)) - 1`, where `C` is a compressed length. Every
knowledge item is measured against the query, the best distances fold into per-tag
scores, and the character picks the best tag **it knows**. Two decisions were made
by measurement, and both are recorded next to the code:

- **Headerless deflate** is the default compressor: gzip's constant 18-byte header
  is a large fraction of a short question (13/14 vs 12/14 on the demo questions).
- **Sum normalisation, not `max`**: the classic `(C(xy)-min)/max` form lets a long
  item win by accident (13/14 vs 9/14). Ranking is per item; concatenating each tag
  into one prototype measured far worse (2/10), because a short question is
  swamped by the prototype.

Compressors: `deflate` (default), `gzip`, `zlib`, `bz2`, `lzma`, plus `zstd` when
the `reply` extra is installed.

### Datasets

`corpora/` (downloaded corpora and what is derived from them) and `data/` (this install's runtime
state) are git-ignored, because both grow to sizes that do not belong in a clone. Only
`corpora/README.md` is tracked, so the folder exists and carries its own instructions.
`examples/demo_world/` is a committed toy world, used by the tests and the demo
above. Three JSONL files plus an optional manifest:

| File | One record per line |
| --- | --- |
| `characters.jsonl` | `id`, `name`, `known_tags` (what they know), `tags` (what they are), optional `fallback_tag` |
| `knowledge.jsonl` | `id`, `text`, `tags`, optional `slots` |
| `responses.jsonl` | `id`, `character` (id, name, or `*`), `tags`, `template` |
| `voices.jsonl` | `id`, plus `characters` / `tags` / `default`, and `engine`, `voice`, `speed`, `volume` |
| `world.json` | optional `name` / `schema_version` |

`known_tags` gates knowledge -- a character may only speak about those. `tags`
describe the character itself (`role:scholar`, `species:dwarf`) and are what voice
casting matches on. The two are separate on purpose: knowing about relics and being a
dwarf are different kinds of fact.

`slots` is the madlib vocabulary for a fact, and it is searched too, so "the
Sunken Crown" matches from either field. `#` comments and blank lines are allowed.
Unknown fields are preserved in `meta`, so the file format can grow without code
changes; the loaders are split into `read_jsonl` + `*_from_records`, so a future
CSV or SQLite source only has to produce records.

### Templates

Fillable slots: `{character}`, `{speaker}`, `{topic}`, `{fact}`, and any key from
the matched item's `slots`. A template whose slots cannot all be filled is skipped
rather than shown half-empty, and slot values containing braces are rejected so
dataset content cannot inject placeholders. `{{` / `}}` are literal braces.

From code:

```python
from ttrpg_chatbots.reply import Replier, load_world

replier = Replier(load_world("data/my_world"))
reply = replier.reply("who controls the dry docks?", "brannoc", speaker="Tav")
print(reply.text, reply.tag, reply.knowledge_id, reply.known)
```

## Speaking: text to speech and voice playback

Three layers, deliberately independent:

| Layer | Module | Knows about |
| --- | --- | --- |
| format | `audio/` | PCM, resampling, Discord's 48 kHz stereo 20 ms frame contract, WAV |
| speech out | `tts/` | text → `PcmAudio` (piper, espeak-ng) |
| playback | `voice/` | clips, files and music → frames → a voice client |

`tts` and `voice` do not import each other, and neither imports `reply`. The only
composition root is the CLI, so a classifier reply, an LLM answer, a scripted line,
a WAV or a music file all take the same path.

```bash
.venv/bin/pip install -e '.[tts]'          # piper-tts; playback needs no extra dependency
.venv/bin/ttrpg-chatbots-tts --list
.venv/bin/ttrpg-chatbots-tts --say "The tide turns at the quay." --out speech.wav
.venv/bin/ttrpg-chatbots-voice --say "..." --engine espeak-ng
.venv/bin/ttrpg-chatbots-voice --ask "who controls the dry docks?" --character brannoc
.venv/bin/ttrpg-chatbots-voice --wav music/tavern.wav --json
```

Measured on this box with `en_US-lessac-medium` (22.05 kHz mono):

```
$ ttrpg-chatbots-voice --ask "who controls the dry docks?" --character brannoc
Brannoc the Archivist: The Tidewrights' Guild controls every dry-dock in the reach...
engine: piper
frames: 354 (7.08 s of audio)
bytes: 1359360
synth: 1573 ms
```

354 frames × 3840 bytes is exactly 7.08 s at 192 000 bytes/s, and 1573 ms of
synthesis for 7 s of audio is ~0.22× realtime — the voice is never the bottleneck.

From code:

```python
from ttrpg_chatbots.tts import resolve_synthesizer
from ttrpg_chatbots.voice import PcmFrameSource, VoicePlayer
from ttrpg_chatbots.voice.discord_voice import play_in

synthesizer = resolve_synthesizer()                 # or engine="espeak-ng"
player = VoicePlayer()
player.enqueue(PcmFrameSource(synthesizer.synthesize(text)))
play_in(voice_client, player)                       # voice_client.play(...) under the hood
```

Anything else that makes noise is already a source: `load_file(path)` for a
pre-recorded WAV or music, `SilenceSource(seconds)` for a beat of silence, and
`ChainSource(a, b, c)` to play them back to back.

### Casting: one voice per character

Consistency is data, not luck. A `voices.jsonl` beside the world maps characters to
voice profiles, resolved in a fixed order: a rule naming the **character** (id or
display name), then a rule naming one of the character's **tags** (most matching tags
first), then the **default** rule, then the built-in profile.

```json
{"id": "cast-scholar", "tags": ["role:scholar"], "engine": "piper", "voice": "en_GB-alan-medium", "speed": 0.95}
{"id": "cast-sable", "characters": ["sable"], "engine": "piper", "voice": "en_US-amy-medium", "speed": 1.1}
{"id": "cast-default", "default": true, "engine": "piper", "voice": "en_US-lessac-medium"}
```

```
$ ttrpg-chatbots-voice --list-voices --data examples/demo_world
brannoc     Brannoc the Archivist       piper:en_GB-alan-medium speed=0.95 volume=1
sable       Sable                       piper:en_US-amy-medium speed=1.1 volume=1
orla        Orla the Tavernkeep         piper:en_US-lessac-medium speed=1 volume=0.9
```

`sable` shows the character rule (`amy`) winning over her `role:guide` tag rule, which
is the precedence working. `--ask` and `--say --character` speak in that character's
voice automatically, and the profile appears in `--json` output.

Rules that protect consistency:

- **No silent substitution.** A profile naming a voice must name its engine (voice
  names only mean something inside one engine), an unknown engine raises instead of
  falling back, and a rule naming a tag no character carries — or a character that does
  not exist — fails at load, with the file and line.
- **Ambiguity fails.** Two rules naming the same character, two rules with the same
  tags, or two defaults are rejected rather than letting file order decide.
- **State is cached, not re-decided.** `VoiceCast` keeps one loaded engine per distinct
  profile (LRU, `max_loaded=4`), so a three-character table loads three voices once
  instead of once per line.
- **The voice is pinned; the waveform is not.** Piper's VITS sampler is stochastic, so
  the same line renders ~0.4 % different in length each run (measured: 459 vs 457
  frames). Set `TTRPG_TTS_DETERMINISTIC=1` to pin the sampler and get byte-identical
  audio for the same line — useful when caching pre-rendered lines, at the cost of
  slightly flatter prosody (measured: identical 94208-byte output either way, versus
  91136/91648 by default).

```python
from ttrpg_chatbots.tts import VoiceCast, load_voice_directory

world = load_world("data/my_world")
cast = VoiceCast(load_voice_directory("data/my_world"))
player.enqueue(PcmFrameSource(cast.synthesize(text, world.character("brannoc"))))
```

### What Discord actually needs

Discord pulls exactly 3840 bytes (960 samples × 2 channels × 16-bit) per 20 ms frame
and expects `b""` to mean "done". `audio.to_discord_pcm()` is the only place that
resamples and channel-converts; the last frame is padded with silence rather than
shortened, and the player rejects any source that yields a frame of the wrong size
instead of letting Discord fail later.

### Engines

| Engine | Notes |
| --- | --- |
| `piper` | Neural VITS voices, ~60 MB per voice, fetched once into the model cache. Default. |
| `espeak-ng` | Zero-install fallback if the binary is on `PATH`; robotic, no download. |

Engine choice is **priority, not measured speed** — unlike STT, where milliseconds
decide, TTS engines differ mainly in voice quality. Override with `--engine` or
`TTRPG_TTS_ENGINE`. Piper runs with `normalize_audio=False`: normalising pins the
peak at 32767, and measured speech peaks near 22500 instead, leaving Discord's own
gain some headroom.

| Variable | Effect |
| --- | --- |
| `TTRPG_TTS_ENGINE` | force an engine |
| `TTRPG_TTS_VOICE` | piper voice name (default `en_US-lessac-medium`) |
| `TTRPG_TTS_SPEED` | piper length scale, 1.0 normal, must be in (0, 3] |
| `TTRPG_TTS_VOLUME` | piper gain, must be in (0, 2] |
| `TTRPG_TTS_DETERMINISTIC` | pin piper's sampler: byte-identical audio for the same line |
| `TTRPG_TTS_MODEL_DIR` | where voices are cached |
| `TTRPG_TTS_OFFLINE` | never download; engines without a local voice are skipped |
| `TTRPG_TTS_ESPEAK` | path to an espeak-ng binary |

Joining the channel and transmitting still needs `PyNaCl`, `davey` and libopus (see
the voice plan above); this layer ends at "here are correctly sized frames".

## Language models: local, OpenAI or ClinePass

The bot can answer with a language model. The compression classifier stays in the loop
as the fallback, so a dead model degrades the wit, not the session.

| Backend | Speaks | Needs | Default endpoint |
| --- | --- | --- | --- |
| `local` | Chat Completions | nothing | `http://127.0.0.1:5000/v1` (text-generation-webui) |
| `openai` | Responses API | `OPENAI_API_KEY` | `https://api.openai.com/v1` |
| `clinepass` | Chat Completions | `CLINE_API_KEY` | `https://api.cline.bot/api/v1` |

No HTTP library was added: the client is `urllib` behind a small `Transport` protocol,
so this whole layer is testable without opening a socket.

```bash
.venv/bin/ttrpg-chatbots-llm --show-config            # which backend, and why
.venv/bin/ttrpg-chatbots-llm --ask "who holds the docks?" --character brannoc
.venv/bin/ttrpg-chatbots-llm --ask "..." --ground     # hand the model matched facts

# The same choice inside the voice pipeline: answer, then speak it in character
.venv/bin/ttrpg-chatbots-voice --ask "who holds the docks?" --character brannoc --llm
```

`--llm` is opt-in on the voice CLI: without it, no socket is opened and the classifier
answers directly. With it, the model answers and the classifier catches the failure,
which is how the live path behaves:

```
Brannoc the Archivist: The Tidewrights' Guild controls every dry-dock in the reach…
answered by: reply:brannoc
NOTE answered by the fallback: local: backend unreachable
engine: piper
voice: piper:en_GB-alan-medium speed=0.95 volume=1
frames: 446 (8.92 s of audio)
```

### Choosing a backend

`TTRPG_LLM_BACKEND` takes `local`, `openai`, `clinepass`, `auto` or `off`. `auto` is the
default: it uses `openai` if its key is present, then `clinepass`, and otherwise the
local server, which needs no key. Set the variable to break a tie.

| variable | meaning |
| --- | --- |
| `TTRPG_LLM_BACKEND` | `local`, `openai`, `clinepass`, `auto`, `off` |
| `TTRPG_LLM_BASE_URL` | full base URL, e.g. another machine's server |
| `TTRPG_LLM_PORT` | local port only (text-generation-webui's default is 5000) |
| `TTRPG_LLM_MODEL` | model id or ClinePass slug (`cline-pass/qwen3.7-max`) |
| `TTRPG_LLM_WIRE` | `chat` (Chat Completions) or `responses` (Responses API) |
| `TTRPG_LLM_TIMEOUT` | seconds, default 30 |
| `TTRPG_LLM_MAX_TOKENS` | default 300; an in-character line is short |
| `TTRPG_LLM_TEMPERATURE` | default 0.7; `0` is allowed (greedy) |
| `TTRPG_LLM_API_KEY` | keys a keyed backend without naming the vendor |
| `OPENAI_API_KEY`, `CLINE_API_KEY` | vendor keys, used by `auto` detection |
| `*_FILE` suffix | read the secret from a file (beats the plain variable) |

Secrets follow the Discord rule: a `*_FILE` variable wins over a plain one, the key
never appears in `repr`, a log line or an error message, and a server that echoes the key
back in its error body gets `***` instead.

### Why two wire formats

Codex models are not served by `/chat/completions`: `gpt-5-codex` answers 404 there and
is only reachable through the Responses API, so `openai` defaults to `wire=responses`.
Chat-completions servers (text-generation-webui, Ollama, llama.cpp, LM Studio, ClinePass)
use `wire=chat`.

Two provider quirks are handled rather than assumed away. ClinePass wraps non-streaming
responses in a `data` envelope, so both the wrapped and plain bodies decode. Reasoning
models reject `temperature`, so the Responses payload sends `instructions` + `input` and
no sampling temperature at all.

### Falling back to the classifier

`FallbackResponder` wraps the model and answers with the classifier when the model
fails. Only `LlmError` triggers it, so a bug in our own code is never hidden behind a
template. Every fallback is logged at WARNING with the cause attached; the traceback is
attached once per distinct cause, because in a live game an unreachable model fails on
every question and a traceback per reply would bury everything else.

```
$ OPENAI_API_KEY=sk-invalid… ttrpg-chatbots-llm --ask "what is the sunken crown?"
WARNING ttrpg_chatbots.llm: llm:openai is unavailable (openai (HTTP 401):
authentication failed); falling back to reply:brannoc. Cause: openai rejected the
credentials (HTTP 401: Incorrect API key provided)
Brannoc the Archivist:
The Sunken Crown? Aye. The sunken crown is a tide-iron circlet lost when the
Saltreach fleet broke at Greyfall.
source: reply:brannoc
NOTE answered by the fallback: openai (HTTP 401): authentication failed
```

Exit status is 0: the table asked a question and got an answer. `--no-fallback` turns
the same situation into exit 2, and `--json` reports `degraded`, `fallback_reason` and
the source on every path.

The backend is built on first use, not at startup, so a missing key or an unreachable
host fails inside the fallback wrapper instead of aborting, and nothing is connected for
a reply the classifier ends up handling.

### Grounding

`--ground` passes the model the facts the classifier judged most relevant *and* that the
character is allowed to know, so the tagging system still governs what a persona can say.
It reuses the same ranking, so nothing new is invented. Off by default: a model that only
talks about what the dataset contains is a different product decision.


## Dice: rolling, reading, and exposing it as a tool

Game-neutral by construction: a roll is *N dice of S sides*, and a **mode** says what the
table cares about. Nothing assumes a d20, a d10 pool or a d6 total.

| mode | reads as | needs |
| --- | --- | --- |
| `sum` | the dice added up (default) | — |
| `list` | the individual dice, plus the total | — |
| `hits` | how many dice reached the target | `target` |
| `check` | total vs a difficulty, meets-or-beats | `target` |

Every mode still records the dice, the total and any target, so a `sum` roll can be
re-read as a check later. A modifier (`+5`) is added after the dice.

```bash
ttrpg-chatbots-dice --roll 3d6 --character "Brannoc the Archivist"
ttrpg-chatbots-dice --count 5 --sides 10 --mode hits --target 8 --character Sable
ttrpg-chatbots-dice --data examples/demo_world --check stealth --character Sable
ttrpg-chatbots-dice --data examples/demo_world --list-checks
ttrpg-chatbots-dice --ask "roll sneak for Sable"      # the instruction path
```

```
Brannoc the Archivist rolls 3d6: 4 + 5 + 4 = 13
Sable rolls Stealth 1d20+5: 15 + 5 = 20 vs 15 -> success (margin +5)
Sable rolls 5d10 (hits on 8+): [8, 9, 8, 8, 9] -> 5 hits
Orla rolls 2d6: [4, 5] -> total 9
```

`--seed` makes a roll repeatable, which is what the tests and demos use; the bot does not
seed. The random source is injectable for the same reason.

### In Discord: one option per part

The slash command does **not** take a notation string. Each part is its own option —
`count`, `sides`, `modifier`, `mode`, `target`, `check`, `character` — with `notation` kept
as an escape hatch for people who already know the shorthand. `check` and `character`
autocomplete, `mode` is a picker, and a bare `/roll` is a d20 that says so.

That is a deliberate split: a chat form collects structure, so the command builds a
`RollSpec` directly (`dice/parts.py`); the free-text parser (`dice/intent.py`) is reserved
for speech and for the language model, where text is the only input there is. Neither
re-parses what the other produced. Every rejection names the fix — `mode:hits needs a
target, for example target:8` — rather than the rule.

### Named checks

`checks.jsonl` sits beside the world's other datasets, so a table says "roll stealth"
instead of "roll 1d20+5 against 15":

```json
{"id": "stealth", "label": "Stealth", "aliases": ["sneak", "hide"], "count": 1, "sides": 20, "modifier": 5, "mode": "check", "target": 15}
{"id": "perception", "count": 5, "sides": 10, "mode": "hits", "target": 8}
{"id": "brawn", "notation": "3d6", "mode": "sum"}
```

`notation` is shorthand for the pool. A missing file means "no named checks", not an
error. Duplicate ids, duplicate names and a `hits`/`check` record without a target are
refused at load with the file and line, because a silent fallback there would roll the
wrong dice.

### As a tool an LLM can call

`ttrpg_chatbots.dice.tool_schema()` is provider-neutral JSON Schema; the LLM layer wraps
it per wire format. `DiceTool.run()` executes a call and returns both speech-ready text
and JSON:

```python
{"character": "Sable", "check": "stealth"}          # named pool
{"character": "Sable", "notation": "3d6"}          # explicit pool
{"character": "Sable", "count": 2, "sides": 8, "mode": "hits", "target": 6}
```

The executor is deliberately suspicious, because models send `"3"` as a string, `2.5` for
a count, `true`, or a named check *and* a pool at once. Each gets a readable error the
model can correct: whole floats and numeric strings are accepted, `2.5` and `"three"` are
not, and a rejected call never consumes randomness. A tool that raises is reported to the
model, not thrown at the caller — a tool must not end the conversation.

`LlmResponder(tools=ToolBox(DiceTool(...)))` runs the loop: the model asks, the responder
rolls, the result goes back, the model answers. It is bounded (`max_tool_rounds`, default
3), and if the model then says nothing, **the roll itself becomes the message** rather
than being dropped.

### Without a model

`DiceResponder` parses the instruction instead: a roll word, then either a dice
expression or a named check, plus an optional `for <name>`. It is a heuristic and says so
— the LLM path uses real tool calling, where the model decides. Anything that is not a
roll instruction is passed through unchanged.

The voice pipeline composes both, cheapest first:

```
--llm :  LLM (with the dice tool)  ->  dice (intent)  ->  classifier
default: dice (intent)             ->  classifier
```

So `ttrpg-chatbots-voice --ask "roll stealth for sable"` speaks the roll in Sable's cast
voice with no model involved, and with `--llm` a model that dies mid-session still leaves
you able to roll dice.


## Test

```bash
.venv/bin/python -m pytest tests/ -q
```

The suite is offline and credential-free. `tests/conftest.py` refuses socket
connections for every test, `tree.sync` and `Client.run` are replaced with
recorders, and `tests/test_no_network.py` fails if that guard is ever removed.
`tests/test_config.py` covers the configuration input surface: missing, blank,
whitespace-bearing, multi-line, binary, and directory secret sources; missing,
malformed, and empty `.env` files; and garbage or out-of-range guild ids.

## Layout

```
src/ttrpg_chatbots/   package source: cli.py, config.py, bot.py, respond.py, conversation.py,
                      sheets/, sheetportal/, character/, seats/, bots/, stt/, reply/, llm/,
                      dice/, audio/, tts/, voice/
tests/                pytest suite: CLI, config, bot, bots, seats, sheets, character, stt,
                      reply, llm, dice, audio, tts, voice, secrets guard
examples/demo_world/  committed toy dataset; examples/friends_world/ is the classifier's
corpora/              downloaded corpora and what is derived from them: git-ignored except
                      its README, which has the commands (37 MiB for Switchboard)
data/                 this install's runtime state: characters, seats, bots.json, logs.
                      git-ignored; nothing in it is reproducible from a clone
.env.example          committed credential template; .env itself is ignored
pyproject.toml        packaging, dependencies, entry points, pytest and ruff config
```
