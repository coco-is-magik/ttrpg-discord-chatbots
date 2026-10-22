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
   * **Privileged Gateway Intents:** for the helper, leave all three **off**. Slash commands do
     not need them, and the helper never reads messages. The friends are the exception and need
     **Message Content** on — see §2.1.
4. Left sidebar → **OAuth2 → General**. Copy the **Application ID** (also called the
   client id) — you need it for the invite link in the next step.

## 2. Invite it to your server

Build this URL, replacing `YOUR_APPLICATION_ID`:

```
https://discord.com/oauth2/authorize?client_id=YOUR_APPLICATION_ID&scope=bot%20applications.commands&permissions=360780516352
```

`360780516352` is exactly what the helper uses, and nothing more:

| Permission | Bit | Why the helper needs it |
|---|---|---|
| View Channels | 1024 | see the channel at all |
| Send Messages | 2048 | reply and post panels |
| Send Messages in Threads | 274877906944 | answer inside a build thread |
| Read Message History | 65536 | fetch and edit the panel it posted |
| Embed Links | 16384 | the sheet and questionnaire embeds |
| Attach Files | 32768 | `/export` and `/import` |
| Create Private Threads | 68719476736 | `/create` opens a private build thread |
| Manage Threads | 17179869184 | delete a thread whose build failed |
| Connect + Speak | 1048576 + 2097152 | `/join`, `/say` |

Drop the voice pair (`360777370624`) if this instance never joins a channel.

Do **not** grant `Administrator` "to save time": `/botcheck` and the startup log name exactly
what is missing, so least privilege costs nothing to maintain. The invite permissions become the
bot's managed role; a channel or category override can still take them away, which is why the
audit checks the channel rather than the role.

Both scopes matter: `bot` joins it to the server, `applications.commands` is what lets
slash commands appear. Missing the second is the most common cause of "the bot is online
but has no commands".

### 2.1 The three friends

Each friend is a separate application: repeat §1 with its own name and token. Three things
differ from the helper.

1. **Scope is `bot` only.** Friends own no slash commands, so `applications.commands` is
   deliberately not granted — it documents that they cannot register commands.
2. **Message Content must be on** (Bot → **Privileged Gateway Intents**) *before* `"listen":
   true` is set in `bots.json`. It is not part of the invite URL, and requesting it while it is
   off closes the gateway connection with code **4014**.
3. **Permissions stop at talking.** No Manage Threads, no Manage Messages, no Administrator.

| Use | `permissions=` | Grants |
|---|---|---|
| friend, text only | `274878254144` | View Channels, Send Messages, Send Messages in Threads, Read Message History, Embed Links, Add Reactions, Use External Emojis |
| friend, text + voice | `274881399872` | the same, plus Connect and Speak |

```
https://discord.com/oauth2/authorize?client_id=YOUR_FRIEND_APP_ID&scope=bot&permissions=274878254144
```

Grant them at the **category** the group talks in, not server-wide, so a friend that should only
speak in `#general` has no permission anywhere else. A private thread inherits the parent
channel's permissions, so the same grant is what lets a friend talk at the table.

Message Content is per application and cannot be granted by a role: three friends means three
toggles in three portal entries.

**Tokens, one file each.** Each friend's file may name its token `DISCORD_TOKEN`, exactly like
the helper's. Point `bots.json` at it and nothing has to be renamed:

```json
{ "id": "friend-a", "role": "friend", "listen": true, "env_file": ".env.frienda" }
```

Those files are read individually with `dotenv_values`, never merged into the process
environment, so three `DISCORD_TOKEN` values cannot overwrite the helper's. The deploy-style
`TTRPG_FRIEND_A_TOKEN` / `_FILE` variables still win if they are set.

**Then prove it**, with the bot stopped so no token holds two gateway sessions:

```bash
./start-bot.sh --stop
.venv/bin/ttrpg-chatbots-bot --friendcheck general   # channel id or name
./start-bot.sh --background
```

```text
friend-a: online as TerrysTopGuy#2763
friend-a: sent to #general (1364544268609523765)
friend-a: received 3 message(s), only from bots (last: Crusty.chan); it is listening...
```

`received N, only from bots` is success: the gateway is delivering, and the friends are
deliberately ignoring each other's chatter. `got N events but the text was empty` means Message
Content is off for that application. The probe deletes its own lines before exiting.

### 2.3 One friend answers (classifier only)

`friend-a` has `"reply": "mention"`. In the channel listed in its `channels`, mention it:

```text
Tav    @TerrysTopGuy hey
```
```text
TerrysTopGuy   there he is. come on in
```

Before you start, check there is exactly one bot process — two processes sharing a token is what
sends every reply twice:

```bash
./start-bot.sh --status
# running (1 process: pid 3174323), logging to …/data/logs/bot.log
```

Then try the edges, which are the point of the design:

| Message | Expected |
|---|---|
| `@TerrysTopGuy anyone around tonight?` | a presence reply in his voice (`i'm here. been here, will be here, what do you need`) |
| `@TerrysTopGuy thanks` | `any time` or similar |
| `@TerrysTopGuy doing anything later?` | an invitation: `nothin yet. you free?` — **never a goodbye** |
| then `yeah` | a confirmation with a time (`done. what are we doing`), not `sounds good` |
| `@TerrysTopGuy howre the rangers doing?` | an opinion about the Rangers, despite the phrasing |
| `@TerrysTopGuy yoooo` | a greeting, not a refusal |
| `@TerrysTopGuy what is the plot of dune?` | a short hedge (`?`, `say more?`) — not a paragraph |
| `@TerrysTopGuy what is the sunken crown?` | an honest refusal — friends know no lore |
| `@TerrysTopGuy hey` twice | **the same or a different greeting** — with `TTRPG_CONVERSATION=greet`
  he reuses lines deliberately (§2.5); repetition here is a pass, not a bug |
| `hey, @friend-b` | silence: `friend-b` has `reply: off` |
| a message that mentions no friend | silence |

`/friendcheck` shows each friend's mode, what it last heard, and how many lines it has sent.
To hear from the others, set `"reply": "mention"` on `friend-b` or `friend-c` and restart — one at
a time is deliberate while the classifier's voice is still being tuned.

The classifier is also the fallback when a model is configured and fails, so it is not a stub.
This command reproduces exactly what the bot runs — note the ceiling, which is what turns a lore
question into an honest refusal:

```bash
.venv/bin/ttrpg-chatbots-reply --data examples/friends_world --character friend-a \
  --max-distance 0.65 --ask "what is the sunken crown?"
# TopGuy [no knowledge, d=0.759 (deflected)]:
# I would be lying if I answered that. Let us find something I do know.
```

### 2.4 The personality holds (friend-a only)

`friend-a` is **TopGuy**, and he has a written brief (`docs/PERSONA.md`) that the dataset is
tested against. Four questions catch most mistakes:

| Message | Expected |
|---|---|
| `@TerrysTopGuy do you like hockey?` | a strong opinion about hockey, in his voice — never a refusal |
| `@TerrysTopGuy what about the rangers?` | the Rangers, with feeling. Original Six will come up |
| `@TerrysTopGuy i'm nervous about tomorrow` | encouragement, and a next step. Not "I don't know" |
| `@TerrysTopGuy what is the plot of dune?` | an honest refusal, still warm: `i'd be lying if i answered that` |

Then check the things a table cannot:

* **He is typed, not written.** Lower case, no full stop, few apostrophes, the odd transposition
  ("jsut"). If a line arrives perfectly punctuated, the style layer did not reach it — that is a
  wiring bug, not a wording one.
* He is **firm about the world and warm to you.** No line should make you feel small; if one does,
  it is a template bug, and `tests/test_persona.py::test_no_template_is_ever_cold…` should have
  caught it.
* He **does not invent.** Ask about something he half-knows ("what about the roman navy?"). A
  refusal is the correct answer; a confident wrong answer is the failure that matters.
* His subjects all work: hockey, the Rangers, computers, Pokémon, Rome, Terry Davis, the history of
  computing, hunting, fishing, woodworking. One refusal among those is a missing anchor.
* He sounds like the same person every time — that is the point of one pool per character.

`friend-b` and `friend-c` are deliberately still neutral. Asking them `do you like hockey?` must
produce a plain "I don't know", not one of TopGuy's lines.

### 2.5 The greet phase on its own (module ladder)

`TTRPG_CONVERSATION=greet` in `.env` hands **greetings only** to the new ladder; every other message
still goes to the old classifier. This is the first phase proved in isolation, and this script is how
you decide whether the module split is working.

Setup, once:

```bash
./start-bot.sh --status          # exactly one process
.venv/bin/python -m ttrpg_chatbots.conv.cli --harness
# attempts 144  said 144  abstained 0
# words: median 1, max 3
# distinct: 7% (10 of 144)
# ends on a beat: 0%
```

Then in Discord, in `#general`. **Success is not "that was clever"** — success is the pattern below.

| # | Do this | Pass looks like | If it fails, the fault is in |
|---|---|---|---|
| 1 | `@TerrysTopGuy hey` at your local morning | one to three words, recognises you | `decide/family` (warmth) or `perceive/clock` |
| 2 | same at 20:00 local | evening wording, not morning | `perceive/clock` or `decide/family` |
| 3 | `@TerrysTopGuy hey` **three times over a day** | **he repeats himself**. Reused phrasings are the target, not a defect | `decide/variant` (if he invents a new line every time) |
| 4 | `@TerrysTopGuy hey man, how have you been, it has been ages` | short: he does not answer length with length | `decide/length` or `render/trim` |
| 5 | `@TerrysTopGuy thanks` | unchanged old behaviour (acknowledgement) | the flag did not reach `supervisor` |
| 6 | `@TerrysTopGuy hey` at 03:00 local | **silence**, and `stayed quiet: he is asleep` in the log | `life/schedule` or `decide/floor` |
| 7 | read four greetings aloud as a person | nothing ends on a punchline beat, nothing explains itself | `decide/persona_fit` |
| 8 | ask him a non-greeting (`anyone around?`) | unchanged old behaviour | the ladder overreaching |

Log lines that correspond to each pass:

```bash
./start-bot.sh --status && grep -aE 'greeted|stayed quiet on a greeting' data/logs/bot.log | tail
# friend-a greeted (intent=greet > phase=opening > length=Budget(max_words=3, max_sentences=1) >
#   floor=Speak(reason='addressed') > job=greet > who=friend > form=clause > family=time_morning >
#   variant=morning > trim=morning > audition=ok)
```

**What would mean the approach is wrong** — write it down before you start, so this is a real test:

* he produces a **new** greeting nearly every time (familiarity is the goal; novelty is the old bug),
* he is **silent** in an addressed, awake, budget-fine case (the ladder is abstaining to protect itself),
* any greeting runs **longer than four words** or explains something,
* he answers a **non-greeting** through the ladder.

Any of the four is a reason to re-open the decomposition rather than tune the phrasebook.

### 2.8a Speech text (no Discord needed)

The spoken form is separate from the text he types, and it is testable without a voice channel.

```bash
ttrpg-chatbots-tts --spoken '$250 watch'          # two hundred fifty dollars watch
ttrpg-chatbots-tts --spoken '10% off'             # ten percent off
ttrpg-chatbots-tts --spoken 'born in 1984'        # born in nineteen eighty-four
ttrpg-chatbots-tts --spoken 'Dr. Smith vs. the NCAA'   # Doctor Smith versus the N C A A
```

Then hear it: `/voicetest action:speak text:it cost $250 in 1984`. If he reads the symbol aloud,
the wrapper is missing from the build path -- see `docs/SPEECH.md` §1.

| Check | Pass | If it fails |
|---|---|---|
| `$250` | *two hundred fifty dollars* | `money` is not running before `symbols` |
| `10%` | *ten percent* | `symbols` is not running before `numbers` |
| `1984` | *nineteen eighty-four* | the year range in `numbers` |
| plain prose | unchanged | something is matching too greedily |

### 2.8b The voice lock (no Discord needed)

```bash
ttrpg-chatbots-tts --verify-voice     # verified
ttrpg-chatbots-tts --fetch-voice      # fetches anything missing, source by source
```

To prove a rebuild: move the model aside and fetch it back.

```bash
mv ~/.cache/ttrpg-chatbots/models/piper/en_US-joe-medium.onnx* /tmp/
ttrpg-chatbots-tts --verify-voice     # "... is missing", exit 1
ttrpg-chatbots-tts --fetch-voice      # fetches and verifies
ttrpg-chatbots-tts --verify-voice     # verified
```

### 2.8c His material, without Discord

The harness reads every line he can say and checks it against the brief. It needs no gateway and no
voice, and it exits 1 on failure, so it is the quickest way to know whether a content edit broke
something.

```bash
ttrpg-chatbots-persona             # the report
ttrpg-chatbots-persona --quiet     # PASS, or the failing check with the offending line
```

Twelve checks: coverage per interest, every subject in his own voice, every anchor naming its own
subject, stances fitting the budget, the register (no beats), length, warmth, catchphrases,
distinctness, life depth, and stories having points. Expected today: `PASS TopGuy  subjects 39  lines
91  median_words 5  two_sentence_pct 7.6`.

| Check | Pass | If it fails |
|---|---|---|
| exit code 0 and `PASS` | every check is ok | the failing line is printed; the check name says which rule |
| `median_words 5` | his lines are short | something long was added to a phrasebook |
| `subjects 39` | ten interests, four each | a topic lost its items |

Then ask him the things the material covers, in `#general`: `@TerrysTopGuy do you like hockey?`,
`what about the playoffs?`, `how are the rangers doing?`, `do you fish?`, `who invented the
computer?`, `what is the plot of dune?` (that last one should hedge, not bluff).

### 2.9 His voice (friend-a, in a voice channel)

There was no way to hear a friend until now: only the helper could join a call. `/voicetest` makes a
**friend** join, speak and leave, using his own casting rule rather than the default voice.

Join a voice channel yourself first — he joins *yours*.

```text
/voicetest action:join                     → friend-a: joined General
/voicetest action:speak                    → friend-a: spoke 6.9s at 22050 Hz
/voicetest action:speak text:there he is    → says exactly that
/voicetest action:leave                    → friend-a: left General
```

**Speak twice.** That is the check that matters most, because it used to be impossible: the second
`action:speak` must make sound. The first version of this command worked exactly once — see
`PERSONA.md` §3d for the cause (`cleanup` from `__del__` wiping the shared queue). If the second one
is silent, the log says `queued` instead of `spoke`, and `started` stays at 1.

What pass sounds like — judge by ear, not by stopwatch:

| Expected | If it is wrong |
|---|---|
| a **deep American bass**, unhurried, cheerful — Santa Claus who played hockey | `engine`/`voice` wrong in `voices.jsonl`; the command reports what it resolved |
| about **6.9 s** for a twenty-word line (`joe-medium`, length scale 1.05, no pitch shift) | change `speed` in `examples/friends_world/voices.jsonl` **and** `data/bots.json`: **higher is slower**, 1.0 neutral. Restart to reload |
| deep enough? | `data/samples/topguy.wav` is the rejected ryan-high take (144 Hz); `topguy-tuned.wav` is current (joe, 98 Hz); `topguy-alt-norman.wav` is the deeper alternative (95 Hz). `data/samples/voices/manifest.json` has the measured F0 of all 13 candidates |
| silence after roughly the spoken length, then idle | playback never started: check the log line, it reports bytes, sample rate, engine and channel |
| `could not join … Check Connect and Speak` | grant Connect + Speak to that bot in that channel; the friends already have both at guild level |

Two facts worth knowing:

* He joins **self-deafened**, because he does not listen to voice yet. An undeafened bot that hears
  nothing is a mystery to debug later; a deafened one is honest.
* The model lives in the TTS cache (`~/.cache/ttrpg-chatbots/models/piper/en_US-joe-medium.onnx`,
  about 60 MB), not in the repository. A fresh box downloads it on first use unless
  `TTRPG_TTS_OFFLINE=1`, in which case the command says the voice is missing rather than guessing.

The same command is the seed of GROUP.md slice 6 (one voice per seat, queues, barge-in): it already
resolves per-friend casting, so the next step is letting a *reply* speak, not just a test line.

### 2.8 Memory, and knowing things (friend-a, whole ladder on)

Two checks that used to be impossible. Both are about the *gate* rather than the wording, so the
failure is usually a module deciding wrongly, not a phrasebook.

| # | Do this | Pass looks like | If it fails, blame |
|---|---|---|---|
| 1 | `@TerrysTopGuy my dog is called otis` | a short reply, and `friend-a will remember pet.name=otis` in the log | `memory/encode`, `bots/memory` |
| 2 | `/memory` | `pet.name = **otis**` under friend-a | the write path never ran |
| 3 | `@TerrysTopGuy how is the dog?` | he asks after it by name ("how is otis doing") — the *name* is the answer | `memory/retrieve`, `decide/recall` |
| 4 | ask `how is the dog?` again the same day | he has already asked today, so this is a hedge or a different answer — **the cap working, not a bug** | `decide/recall` (`raised`) |
| 5 | `@TerrysTopGuy what is the plot of dune?` | `?` or another hedge — **never** a question about the dog | `decide/family` mode table |
| 6 | restart the bot, then `@TerrysTopGuy how is the dog?` | he still knows | the fact was never saved |
| 7 | `/forget pet.name`, then `@TerrysTopGuy how is the dog?` | he no longer knows | `bots/memory.forget` |
| 8 | `@TerrysTopGuy do you like hockey?` | a stance, in his voice, inside the budget — **not** a paragraph | `decide/subject`, `explain.json` |
| 9 | `@TerrysTopGuy howre the rangers doing?` | the Rangers, despite the spelling — this was the 0.651 case | `decide/subject` (no ceiling on a name) |
| 10 | `@TerrysTopGuy what is the sunken crown?` | a hedge, because nobody in this world knows it | `decide/subject` returning nothing |
| 11 | `@TerrysTopGuy what are you up to` (today, 2026-10-22) | his activity, and **the season opener this week** — the calendar, not the schedule | `bots/ladder.events`, `values._event_phrase` |
| 12 | same question on 2026-10-28 | "opener today" or similar, and on a quiet day just the activity | the `short` field in `calendar.json` |
| 13 | `@TerrysTopGuy what are you up to`, then `how did that go?` | **a story** — the one about the thing he just offered (the axe, if he was on the fence) | `decide/story`, the `words` field in `life.json` |
| 14 | then `what was the point of that?` | **the point**, not the story again | `explain.json` (`point`), `decide/job` |
| 15 | `@TerrysTopGuy how did the fence go?` (cold, nothing before it) | a story — a question about the past deserves an answer | `decide/story` (`asked`) |
| 16 | two long messages, then `my weekend was long` | a story, unprompted | `decide/story` (`leaned_in`) |
| 17 | the same, but end with a question (`what are you up to`) | **the hook, not a story** | `looks_like_question` |
| 18 | `@TerrysTopGuy doing anything later?` | an invitation with somewhere to go ("want to get out to the range saturday") | `decide/family` (`plan`), `life.json` plans |
| 19 | say yes to that | a confirmation, not another "sounds good" | `pending_plan` in `bots/memory` |

Two things worth knowing when reading the log:

```
friend-a will remember pet.name=otis
friend-a answered through the ladder (… job=hedge > subject=nothing > recall=pet.name (raised) …)
```

`recall=… (raised)` means they raised it; `(session)` means he opened with it; `(no room)` means he
wanted to and the budget said no — which is a pass, not a failure. The trail also carries
`events=` now, so a day with nothing in it is visible rather than guessed at.

### 2.7 The phases (friend-a, whole ladder on)

`TTRPG_CONVERSATION=ladder` answers every phase he has a phrasebook for; knowledge questions still go
to the old classifier until world knowledge is wired in as a tool. Each check names the module that
owns a failure, so a bad answer is a one-file fix.

| # | Say this | Pass looks like | If it fails, blame |
|---|---|---|---|
| 1 | `@TerrysTopGuy what are you up to` | one thing he is doing, in a few words — *not* a reason, not a paragraph | `decide/job`, `decide/values` |
| 2 | `@TerrysTopGuy rough day at work` | a short reaction ("yeah, i hear that") with **no** story of his own | `decide/family` (depth), `mirror.json` |
| 3 | then `@TerrysTopGuy i have been rebuilding a fence myself this month` | a reaction, and now his own grievance appears | `decide/depth`, `mirror.json` |
| 4 | `@TerrysTopGuy why?` | **the reason** for the thing he just said | `decide/phase`, `explain.json` |
| 5 | `@TerrysTopGuy i have been rebuilding a fence myself` (a statement, no question) | a short noise of having heard ("yeah", "nice") — **never "?"** | `govern/loop` `looks_like_question`, `noted.json` |
| 6 | `@TerrysTopGuy i am nervous about tomorrow` | one encouraging line, no pep talk | `reassure.json` |
| 7 | `@TerrysTopGuy good night` | a goodbye and nothing else — no last question | `decide/job` (`close`), `close.json` |
| 8 | `@TerrysTopGuy what is the plot of dune?` | the old classifier's answer, **not** the ladder's | `bots/supervisor` routing |
| 9 | `@TerrysTopGuy thanks` | "any time" or similar | `acknowledge.json` |

Then read four in a row out loud. Nothing should end on a punchline, explain itself, or ask a question
it does not need to ask.

The numbers behind those checks, and the five defects a live channel found that review did not, are in
`docs/CONVERSATION.md` §7.

### 2.6 What counts as "talking to him"

This is the thing that made a working bot look dead, so it is worth knowing exactly:

| You do | He answers |
|---|---|
| `@TerrysTopGuy hey` — picked from the member list | yes, a user mention |
| `@TerrysTopGuy hey` — picked from **the role** (what Discord autocompletes first) | yes — role pings are parsed from the text too |
| click **reply** on his message and type | yes — a reply to *any* message he sent |
| reply to *someone else's* message | no |
| just type in `#general` with no @ and no reply | no — ambient chatter is a later slice |

**The role ping is the important one.** Discord creates a managed role with the bot's name, and that
role is usually *not mentionable*, so `@TerrysTopGuy` can arrive as `<@&id>` with **both** `mentions`
and `mention_roles` empty. The markup inside the message text is the only surviving evidence, which is
why it is parsed by hand. That single omission is what made every message look unaddressed while the
log showed nothing wrong.

Diagnosis, when he does not answer something you think he should:

```bash
# every refused message says why
grep -aE 'was mentioned|was replied to|did not answer' data/logs/bot.log | tail
# friend-a did not answer noodle: #channel 123 is not in its allowed list

# delivery, including other bots: proves the gateway is actually sending events
echo 'TTRPG_LISTEN_TRACE=1' >> .env && ./start-bot.sh --stop && ./start-bot.sh -d
# friend-a TRACE delivery from noodle (bot=no) in #general: hey
# friend-a TRACE addressed=True me=1562… mentions=[1562…] reply_to=None sent_ids=[…]

# end-to-end without a human: let him treat other bots as people, post a probe, watch the log
echo 'TTRPG_TRUST_BOTS=1' >> .env && ./start-bot.sh --stop && ./start-bot.sh -d
```

`TRACE` lines are the difference between *"not addressed"* and *"never arrived"*; `TRUST_BOTS` is only
for probing, never for production (a group of bots answering each other is the chorus the design
avoids). Remove both lines and restart when you are done.

### 2.2 Re-inviting an app that is already in the server

Open the same URL again and approve the new permissions (you need **Manage Server**). If you
cannot re-invite, edit the bot's managed role under **Server Settings → Roles**, or the channel
override directly. Then check the result rather than assuming it:

```bash
./start-bot.sh --check     # which applications are configured, and which are dormant
```

and `/botcheck` in the channel the bot works in, or read the startup log — every missing
permission is one warning line with the fix.

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

### 7.2 Your seat and your sheet

Before anything else, check that the bot knows who you are:

`/sheet`

* **Seated:** your character's numbers come back, with a revision number.
* **Not seated yet:** the reply gives you your Discord id and the file to paste it into:
  `no character is bound to you; your Discord id is 1234… Add a human seat with that id to
  data/seats.json.`

To seat yourself, copy the example and edit the two fields that matter:

```bash
cp examples/seats.example.json data/seats.json
chmod 600 data/seats.json   # it contains Discord ids, not secrets, but it is yours
```

```json
{
  "id": "truman",
  "kind": "human",
  "character": "molly-macintosh",
  "world_character": "brannoc",
  "discord_id": YOUR_ID_HERE,
  "permissions": ["edit_own_sheet"]
}
```

`character` is the sheet in `data/characters`; `world_character` is who the classifier and
voices answer as (the demo world has `brannoc`, `sable`, `orla`). Then `/sheet` again — your
sheet should appear, and `/roll` with no options should now roll **your** character's dice.

Two checks worth doing while you are here:

* `/sheet character:<someone-else>` → refused, because your seat does not hold
  `view_any_sheet`.
* Add `view_any_sheet` to your permissions, restart, and the same command works, marked
  `shown by …`.

### 7.3 The world and the cast

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

### 7.4 A text answer

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

### 7.5 Refusals are supposed to be refusals

`/ask question:hello character:nobody` → `error: no such character 'nobody'; known: Brannoc
the Archivist, Sable, Orla the Tavernkeep`

`/roll` with no arguments → an ephemeral "give dice (3d6) or a check (stealth)".

Nothing should crash the bot: errors come back as messages and the process stays up.

### 7.6 Dice

Every part of a roll is its own option, so nothing depends on remembering shorthand:

| Option | Meaning | Default |
|---|---|---|
| `count` | how many dice | 1 |
| `sides` | sides per die: 6, 10, 20… | 20 |
| `modifier` | added to the total; may be negative | 0 |
| `mode` | `sum`, `list`, `hits`, `check` | sum |
| `target` | difficulty or hit threshold (needed by `hits`/`check`) | – |
| `check` | a named check instead of dice; autocompletes | – |
| `character` | who is rolling; autocompletes | first character |
| `notation` | shorthand instead: `4d6-1` | – |

* `/roll` — a bare d20; the reply says so
* `/roll count:3 sides:6` → `Brannoc the Archivist rolls 3d6: 4 + 5 + 2 = 11`
* `/roll count:4 sides:6 modifier:-1` → `... rolls 4d6-1: 5 + 5 + 2 + 3 - 1 = 14`
* `/roll count:5 sides:10 mode:hits target:8 character:sable` → `Sable rolls 5d10 (hits on 8+):
  [10, 8, 3, 8, 9] -> 4 hits`
* `/roll check:stealth character:sable` → `Sable rolls Stealth 1d20+5: … vs 15 -> success`
* `/roll check:stealth target:18` → the same check against a harder difficulty
* `/roll notation:2d20+3` → the shorthand, for when you already know it

`check` and `character` autocomplete, so you pick a name instead of typing one. Mixing
shorthand with parts (`notation` plus `count`) is refused rather than silently resolved, and
errors name the fix: `mode:hits needs a target, for example target:8`.

The reply ends with the shorthand for what you just rolled (`-# answered by dice · 4d6-1`),
so the notation becomes familiar from reading results rather than from memorising a tooltip.

Big pools are summarised, not clipped: past twelve dice the list becomes `3 + 5 + 2 + … (30
dice) = 96`. Every die is still rolled and counted — only the display is shortened, so a
large pool stays readable in chat.

### 7.7 Voice: join

1. Join a voice channel yourself.
2. `/join` → `joined **General**; playback stream open (queue: 0)`

The bot appears in the channel and **stays silent** — it holds an open stream so it can speak
later without rejoining.

### 7.8 Voice: speak a fixed line

`/say text:The night is cold and the ale is worse. character:orla`

Expect `speaking 2.6 s (queued: 1)`, then audio within a second or two.

Voices load on demand: the **first** speech of each voice costs a few seconds (piper loads
a ~60 MB model), after which the same voice answers in well under a second. If the first
`/say` seems slow, that is the load, not a hang — the reply still arrives.

If you hear nothing: check your own output device, the bot's volume slider (right-click the
bot in the channel), and the terminal for `queued … s of speech`.

### 7.9 Voice: answer aloud

`/ask question:who controls the dry docks? character:brannoc speak:true`

The text arrives first, speech follows, in Brannoc's voice.

### 7.10 Interrupt, then leave

* `/say text:` something long, then `/stop` mid-sentence → silence; the stream stays open.
* `/say text:` something short → still plays after a stop.
* `/leave` → `left the voice channel`, and the bot leaves the channel.

### 7.11 Restart behaviour

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

