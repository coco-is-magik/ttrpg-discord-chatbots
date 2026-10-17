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
| `characters.jsonl` | `id`, `name`, `known_tags`, optional `fallback_tag` |
| `knowledge.jsonl` | `id`, `text`, `tags`, optional `slots` |
| `responses.jsonl` | `id`, `character` (id, name, or `*`), `tags`, `template` |
| `world.json` | optional `name` / `schema_version` |

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
src/ttrpg_chatbots/   package source: cli.py, config.py, bot.py, stt/, reply/
tests/                pytest suite: CLI, config, bot, stt, reply, secrets guard
examples/demo_world/  committed toy dataset; data/ and datasets/ are git-ignored
.env.example          committed credential template; .env itself is ignored
pyproject.toml        packaging, dependencies, entry points, pytest and ruff config
```
