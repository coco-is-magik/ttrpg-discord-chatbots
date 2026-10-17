# ttrpg-chatbots

TTRPG chatbot project. This is the initial scaffold: `src/` layout package,
`pyproject.toml` (setuptools), a `tests/` suite, and a `hello world` CLI used to
verify the environment end to end.

## Install

Python 3.12+ is required. A virtual environment is mandatory (no global installs):

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[test]'
```

Runtime dependencies: `discord.py`, `python-dotenv`. Dev dependencies: `pytest`.

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

`data/` and `datasets/` are git-ignored (they will be large).
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
src/ttrpg_chatbots/   package source: cli.py, config.py, bot.py, respond.py,
                      stt/, reply/, llm/, audio/, tts/, voice/
tests/                pytest suite: CLI, config, bot, stt, reply, llm, audio, tts,
                      voice, secrets guard
examples/demo_world/  committed toy dataset; data/ and datasets/ are git-ignored
.env.example          committed credential template; .env itself is ignored
pyproject.toml        packaging, dependencies, entry points, pytest and ruff config
```
