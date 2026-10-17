# Manual testing: running the bot against Discord

Discord's terms do not allow automated harnesses driving real accounts, so there is no
substitute for a human in a server. Everything in this project's test suite runs offline;
this document is the other half — the part only you can do.

It takes about fifteen minutes the first time, and two minutes after that.

---

## 0. What you will be exercising

The bot is a thin adapter over the same code the CLIs use, so a manual test here is also a
test of the answer chain, the cast, and the voice pipeline.

| Command | What it proves |
|---|---|
| `/ping` | the gateway connection, and that slash commands synced |
| `/voices` | the world loaded, casting resolved, TTS availability |
| `/ask question:… character:…` | dice → classifier (→ model, if configured) chain |
| `/ask … speak:true` | text-to-speech and playback in a call |
| `/roll dice:3d6` | the dice module from Discord input |
| `/roll check:stealth character:sable` | named checks and attribution |
| `/join` / `/leave` | voice connect, encrypted transport, clean shutdown |
| `/say text:… character:…` | TTS with an explicit cast voice |
| `/stop` | interrupting playback mid-sentence |

**Not wired yet — do not expect these to work:**

* **The bot does not listen.** There is no speech-to-text from Discord yet, so speaking in
  the channel does nothing. You drive it with slash commands.
* **No language model by default.** `/ask` uses the compression classifier and the dice.
  To put a model in front, see `TTRPG_LLM_BACKEND` in `.env.example`; with `local` it wants
  text-generation-webui on `127.0.0.1:5000`, with `openai`/`clinepass` it wants a key.
* **No character sheets in the bot.** `/ask` and `/roll` use `examples/demo_world`
  (`brannoc`, `sable`, `orla`). The `character` package is not connected to Discord yet.
* **No message-text commands.** Slash commands only, which is why no privileged intents
  are needed.

---

## 1. Create the application and get a token

1. Open <https://discord.com/developers/applications> and **New Application**.
2. Name it, accept the terms, **Create**.
3. Left sidebar → **Bot**.
   * Copy the **token** with **Reset Token** (it is shown once). This is your
     `DISCORD_TOKEN`.
   * Leave **Public Bot** on if you want to invite it elsewhere; off is fine for testing.
   * **Privileged Gateway Intents:** leave all three **off**. Slash commands do not need
     them, and the code does not request them.
4. Left sidebar → **OAuth2 → General**. Copy the **Application ID** (also called the
   client id) — you need it for the invite link in the next step.

## 2. Invite it to your server

Build this URL, replacing `YOUR_APPLICATION_ID`:

```
https://discord.com/oauth2/authorize?client_id=YOUR_APPLICATION_ID&scope=bot%20applications.commands&permissions=3148800
```

`3148800` is **View Channels (1024) + Send Messages (2048) + Connect (1048576) +
Speak (2097152)**. Nothing else is needed; if you prefer, grant `Administrator` in a test
server and tighten it later.

Both scopes matter: `bot` joins it to the server, `applications.commands` is what lets
slash commands appear. Missing the second is the most common cause of "the bot is online
but has no commands".

## 3. Find your server (guild) id

1. Discord → **User Settings → Advanced → Developer Mode: on**.
2. Right-click your server's icon → **Copy Server ID**.

Guild-scoped sync is instant; a global sync can take up to an hour. Use the guild id while
testing.

## 4. Put the credentials in `.env`

From the repository root:

```bash
cp .env.example .env          # if you do not already have one
chmod 600 .env                # your user only
```

Then edit `.env` so it contains your real values:

```ini
DISCORD_TOKEN=your-real-token-here
DISCORD_GUILD_ID=your-server-id-here
```

Rules the code enforces, so you do not have to remember them:

* A real environment variable always beats `.env` (`override=False`), so an exported
  `DISCORD_TOKEN` wins over a stale file.
* `DISCORD_TOKEN_FILE=/run/secrets/discord_token` reads the token from a file and ignores
  `DISCORD_TOKEN`. Use this on a server; it keeps the secret out of the environment and
  out of `ps`. systemd's `LoadCredential` and Docker secrets both work.
* A token containing whitespace is rejected: a two-line secret file is a copy-paste
  accident, not a token.
* `.env` is git-ignored. Confirm with `git check-ignore -v .env` before pasting anything
  real, and never paste the token into a tracked file, an issue, or a chat log.


---

## 5. Install the voice dependencies

Voice needs three things, and the bot tells you which is missing rather than failing with a
stack trace:

```bash
# 1. Python side: PyNaCl (encryption) and davey (DAVE, now required by Discord)
.venv/bin/python -m pip install -e '.[test,voice,tts]'

# 2. System side: libopus, which discord.py loads at runtime
sudo apt install libopus0          # Debian/Ubuntu
sudo dnf install opus              # Fedora
sudo pacman -S opus                # Arch
sudo emerge media-libs/opus        # Gentoo

# 3. Optional: ffmpeg, only if you want to convert mp3/ogg files to WAV
which ffmpeg
```

> **Always install with `.venv/bin/python -m pip`, never `.venv/bin/pip`.**
> A virtualenv is not relocatable: if it is copied or moved, its `pip` wrapper, activation
> scripts and console scripts keep pointing at the old directory. Installs then look
> successful and land in the wrong place. `python -m pip` always uses the interpreter you
> named. This checkout's environment **has been rebuilt** from scratch, so it is consistent
> now, and `tests/test_layout.py` fails the suite if it ever stops being so.
>
> If your shell prompt shows `(.venv)` but `which python` is not this project's `.venv`,
> you are in someone else's environment. Fix it in the shell you are using:
>
> ```bash
> deactivate                      # leave whatever is active
> cd "/nas/contents/Projects/Programming Projects/Python/ttrpg-chatbots-rebuild"
> source .venv/bin/activate
> ```
>
> Then confirm everything agrees before going further:
>
> ```bash
> .venv/bin/ttrpg-chatbots-bot --check
> .venv/bin/python -m pytest -q
> ```

Then check, without touching Discord:

```bash
.venv/bin/ttrpg-chatbots-bot --check             # token shape, guild, voice support
.venv/bin/ttrpg-chatbots-voice --list            # TTS engines
.venv/bin/ttrpg-chatbots-voice --list-voices     # who speaks with which voice
.venv/bin/python -m pytest -q                    # the whole offline suite
```

`voice_readiness()` should print `(True, 'voice ready')`. If it prints `False`, the message
names exactly what is missing — fix that before starting the bot, because `/join` will
refuse with the same message.

**The first speech run downloads a voice model** (~60 MB each) into
`~/.cache/ttrpg-chatbots/models/piper/`. Each character has a different voice, so warm all
three now, otherwise the first `/say` for a character stalls for half a minute:

```bash
for voice in en_GB-alan-medium en_US-amy-medium en_US-lessac-medium; do
  .venv/bin/ttrpg-chatbots-voice --say "testing, one two" --voice "$voice" > /dev/null
done
```

## 6. Start the bot

Use the convenience script from the repository root. It checks that the environment is this
checkout, refuses to start if `.env` could be committed, then starts the bot:

```bash
cd "/nas/contents/Projects/Programming Projects/Python/ttrpg-chatbots-rebuild"
./start-bot.sh              # foreground; Ctrl-C stops it
./start-bot.sh --background # detached, with a log and a pid file
./start-bot.sh --status
./start-bot.sh --logs       # follow data/logs/bot.log
./start-bot.sh --stop
```

`./start-bot.sh --check` validates without connecting, which is the safest first run.

What a healthy start looks like:

```
INFO  ttrpg_chatbots.bot: voice: ready
INFO  ttrpg_chatbots.bot: Starting bot; slash commands scope: 1364544268609523762
INFO  discord.client: logging in using static token
INFO  ttrpg_chatbots.bot: synced 8/8 slash commands (guild 1364544268609523762)
INFO  discord.gateway: Shard ID None has connected to Gateway (Session ID: …)
INFO  ttrpg_chatbots.bot: Connected to Discord as YourBot#1234
```

* `synced 8/8` — Discord accepted every command. If it says `synced 0/8`, the invite is
  missing the `applications.commands` scope; the bot logs a warning in that case.
* `Connected to Discord as …` — the gateway session is live and the bot is online.
* `voice: ready` — if it names something missing, see troubleshooting.
* Leave it running; `Ctrl-C` (foreground) or `./start-bot.sh --stop` (background) ends it.



## 7. The walkthrough

Do these in order; each isolates a layer, so the first failure tells you where to look.
Typing `/` opens the command picker.

### 7.1 Liveness

`/ping` → **Pong!**

Failure: no commands in the picker. The bot is in the server but commands are not synced —
check the invite included `applications.commands`, and that `DISCORD_GUILD_ID` is the id of
*this* server.

### 7.2 The world and the cast

`/voices`

Expect a table like:

```
brannoc  Brannoc the Archivist   piper:en_GB-alan-medium speed=0.95 volume=1
sable    Sable                   piper:en_US-amy-medium speed=1.1 volume=1
orla     Orla the Tavernkeep     piper:en_US-lessac-medium speed=1 volume=0.9
-# voice ready
```

This proves the dataset loaded, casting resolved and voice is usable — without joining a
call.

### 7.3 A text answer

`/ask question:what is the sunken crown? character:brannoc`

Expect the classifier's line, attributed, with a quiet source note:

> The Sunken Crown? Aye. The Sunken Crown is a tide-iron circlet lost when the Saltreach
> fleet broke at Greyfall.
> <sub>answered by `reply:brannoc`</sub>

Now ask the same question as `sable`, then as `orla`:

> I have not walked that ground. I will not guess at it.        `reply:sable`
> Ask someone who reads. I only pour.                          `reply:orla`

That contrast is the whole point of the tag gating: Brannoc's tags let him know that lore,
Sable and Orla's do not, so they deflect instead of inventing. If every character gives the
same answer, the gating is broken — say so, because it is a bug, not a setting.

### 7.4 Refusals are supposed to be refusals

`/ask question:hello character:nobody` → `error: no such character 'nobody'; known: Brannoc
the Archivist, Sable, Orla the Tavernkeep`

`/roll` with no arguments → an ephemeral "give dice (3d6) or a check (stealth)".

Nothing should crash the bot: errors come back as messages and the process stays up.

### 7.5 Dice

Dice are attributed to the **character you name**, not to you. With no `character`, they go to
the first character in the world (Brannoc here).

* `/roll dice:3d6` → `Brannoc the Archivist rolls 3d6: 5 + 3 + 6 = 14`
* `/roll check:stealth character:sable` → `Sable rolls Stealth 1d20+5: 20 + 5 = 25 vs 15 ->
  success (margin +10)`
* `/roll check:brawn character:brannoc` → `Brannoc the Archivist rolls Brawn 3d6: 3 + 6 + 6 =
  15`

Numbers vary run to run; the shape and the attribution should not. Check names come from
`examples/demo_world/checks.jsonl`: stealth, perception, brawn, persuasion, luck.

Big pools are summarised, not clipped: past twelve dice the list becomes `3 + 5 + 2 + … (30
dice) = 96`. Every die is still rolled and counted — only the display is shortened, so a
large pool stays readable in chat.

### 7.6 Voice: join

1. Join a voice channel yourself.
2. `/join` → `joined **General**; playback stream open (queue: 0)`

The bot appears in the channel and **stays silent** — it holds an open stream so it can speak
later without rejoining.

### 7.7 Voice: speak a fixed line

`/say text:The night is cold and the ale is worse. character:orla`

Expect `speaking 2.6 s (queued: 1)`, then audio within a second or two.

Voices load on demand: the **first** speech of each voice costs a few seconds (piper loads
a ~60 MB model), after which the same voice answers in well under a second. If the first
`/say` seems slow, that is the load, not a hang — the reply still arrives.

If you hear nothing: check your own output device, the bot's volume slider (right-click the
bot in the channel), and the terminal for `queued … s of speech`.

### 7.8 Voice: answer aloud

`/ask question:who controls the dry docks? character:brannoc speak:true`

The text arrives first, speech follows, in Brannoc's voice.

### 7.9 Interrupt, then leave

* `/say text:` something long, then `/stop` mid-sentence → silence; the stream stays open.
* `/say text:` something short → still plays after a stop.
* `/leave` → `left the voice channel`, and the bot leaves the channel.

### 7.10 Restart behaviour

`Ctrl-C`, start again, re-run `/ping`, `/voices`, `/join`, `/say`. Commands should still be
there (guild sync is idempotent) and voice should return cleanly. If `/join` cannot connect,
run `/leave` first — a voice client from a killed process can linger for a minute.



---

## 8. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `Improper token has been passed` | wrong or rotated token, or a stray character | reset the token, paste again, `chmod 600 .env` |
| `configuration error: no Discord bot token` | no `.env`, or wrong directory | run from the repo root, or export `DISCORD_TOKEN` |
| bot online, **no slash commands** | invite lacked `applications.commands`, or global sync pending | re-invite with both scopes; set `DISCORD_GUILD_ID`, restart |
| commands appear in one server only | that is guild sync | expected while testing |
| `/join` → `voice unavailable: missing PyNaCl` | extra not installed | `pip install -e '.[voice]'` |
| `/join` → `… missing libopus` | no system opus | `apt install libopus0`, then restart |
| `/join` → `… missing davey` | DAVE library absent | `pip install 'davey>=0.1.7'`, then restart |
| `/join` → `error: could not join: …` | permissions, or you are not in a channel | grant Connect + Speak; join first |
| joined but **no sound** | output device, volume, or server mute | check your device, the bot's slider, your deafen state |
| `error: run /join first` | speaking before joining | `/join` first |
| speech cuts out mid-word | `/stop`, or the queue was cleared | expected; run `/say` again |
| a long dice list shows `... (30 dice)` | display truncation, by design | every die is still rolled; the total is exact |
| a command shows `error in /command: …` | a bug, reported instead of hanging | read the traceback in the log |
| first `/say` takes ~30 s | downloading a piper voice | warm the cache first (step 5) |
| `/ask` seems to know nothing | the tag gating working as designed | ask a character who knows that tag |
| no `answered by llm:…` | no model configured | set `TTRPG_LLM_BACKEND` and a key, or accept the classifier |
| `NOTE … fallback: …` in an answer | the model failed; the classifier answered | read the `Cause:` line in the terminal |

Everything the bot logs goes to the terminal, and the token is never logged or printed.

---

## 9. After the test

* `Ctrl-C` stops it; players and loaded voices are closed.
* Screenshots are safe: the token never appears in logs or messages. The application id is
  public.
* If a token did leak, **Reset Token** in the portal — the old one dies immediately.
* On a shared machine, blank or delete `.env` when finished.

## 10. What a good result looks like

One session should show: `Pong!`; the cast table; an answer that changes with `character`;
a deflection from a character who should not know something; a dice roll attributed to a
character; your own sentence spoken aloud in a different voice per character; a clean
`/stop`; and a clean `/leave`. If all of that happened, the pipeline is wired end to end and
anything that misbehaves afterwards is a tuning problem, not a plumbing one.

