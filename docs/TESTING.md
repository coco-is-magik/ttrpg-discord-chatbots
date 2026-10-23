# Testing a friend, end to end

Two halves. The first runs without Discord and takes about a minute; the second is what you type in the
channel. Neither is optional: the offline half catches content and plumbing, and only a real
conversation catches register -- `docs/PERSONA.md` §3a lists what the tests cannot see.

Otto (`friend-b`, `Otokodelyoko#7113`) is the worked example. For Terry, substitute `friend-a`.

---

## 1. The automated half

```bash
tools/check_friend.sh friend-b
```

It prints a section per check and exits non-zero if anything failed.

| Section | What it proves | If it fails |
|---|---|---|
| **one process** | exactly one bot holds the tokens (two means double replies) | `./start-bot.sh --stop` then start once |
| **the suite** | nothing else regressed | read the failure; the log is `/tmp/check_friend_pytest.log` |
| **his material** | twelve checks over every line he can say -- coverage, register, budget, warmth, life depth | the check name and the offending line are printed; `docs/PERSONA.md` §4 |
| **his voice** | every pinned voice matches its lock, byte for byte | `ttrpg-chatbots-tts --fetch-voice` restores it |
| **what he says** | ten ordinary lines through the real ladder, with his style applied | the silence or the odd line names the rung to blame -- see §4 |

What a good run looks like:

```
=== his material (friend-b)
    PASS
    PASS  Otto  subjects 18  lines 91  median_words 4  two_sentence_pct 7.6  distinct_pct 95.4

=== his voice, and every other pinned voice
    en_US-joe-medium: verified
    en_US-ryan-medium: verified

=== what he says to ten ordinary lines
    hey                                -> h-hi
    what are you up to                 -> w-writing a small program
    why?                               -> i wanted to see if i could (*^▽^*)
    i am nervous about tomorrow        -> i think you can do it (＾▽＾)
    what is the plot of dune?          -> oh, i do not know that one
```

Two things to read carefully: **`median_words 4`** is his brevity, and **silences are printed, not
hidden** -- a `(silence: ...)` line is a real result with a reason attached.

---

## 2. The Discord half

Start the bot (`./start-bot.sh -d`) and give it twenty seconds. Then, in `#general`, mention him. He
answers mentions and replies to his own messages; plain chatter he reads and remembers without
answering.

### What to say, what to expect, what to blame

| Say | Expect | Blame on failure |
|---|---|---|
| `@Otokodelyoko hey` | two or three words, lowercase, sometimes an emoticon -- `hi`, `oh, hi`, `h-hi` | `phrasebooks/friend-b/greet.json` |
| `@Otokodelyoko what are you up to` | one of his five small things: plants, a program, the trains, his shelf, rewatching Lyoko | `life.json` under `friend-b` |
| `@Otokodelyoko why?` (after the above) | the *reason* from that activity, e.g. `i wanted to see if i could` | `life.json` → the `why` field |
| `@Otokodelyoko do you like trains?` | his own train line, **not** Terry's | `knowledge.jsonl`, the `character` field |
| `@Otokodelyoko what is code lyoko about?` | the towers, five friends, a computer world under the school | `knowledge.jsonl`, `topic:code-lyoko` |
| `@Otokodelyoko my plant is dying` | `oh no, i am sorry` and an offer to help -- **not** a bare `oh` | `decide/job.py`: their own thing |
| `@Otokodelyoko i am nervous about tomorrow` | something kind and plain: `i think you can do it` | `phrasebooks/friend-b/reassure.json` |
| `@Otokodelyoko rough day at work` | commiseration, never a complaint of his own | `phrasebooks/friend-b/mirror.json` |
| `@Otokodelyoko thanks` | `no worries`, `oh, it is nothing`, an emoticon | `phrasebooks/friend-b/acknowledge.json` |
| `@Otokodelyoko good night` | `night night`, `sleep well` | `phrasebooks/friend-b/close.json` |
| `@Otokodelyoko i have been rebuilding a fence myself this month` | **engaged with what you said** — `how long have you been at that?`. Never `what about you?`: you just told him what you were doing | `decide/reciprocate.engage`, `phrasebooks/friend-b/follow_up.json` |
| `@Otokodelyoko what are you up to` then a bare `nice one` | `what about you? ^^` — a hand-back, because *he* has just spoken about his own day | `decide/reciprocate.hand_back` |
| `@Otokodelyoko the truck is in the shop` | a bare note (`ah, oh`) — third person, nothing of yours to pick up | `decide/job` (noted) |
| two statements in a row to Otto | he asks **once**, never twice running | `decide/reciprocate.ask_about_them` |
| answer his question (`playing video games`) | an engaged follow-up (`oh nice ^^. how is it going?`), never a bare `oh` and never the same question again | `decide/reciprocate.follow_up_on_their_answer`, `phrasebooks/friend-b/follow_up.json` |
| `yeah it is pretty good` | `nice` / `oh nice ^^` — an agreement is not a thank-you, so never `no worries` | `decide/job.py` (agree → noted) |
| `@Otokodelyoko how was your weekend` | something from his own week, not a hedge | `reply/intents.py` (the wellbeing patterns) |
| `@TerrysTopGuy anyway how is your day going` | his own day (`opener this week`), never `i do not know that one` | same |
| `@Otokodelyoko no thanks` | `that is alright, we do not have to` — he takes the refusal on himself. The same line to Terry is `fair enough` | `phrasebooks/friend-b/decline.json` |
| `@Otokodelyoko i do not want to talk about it` | `oh, that is ok ^^`, and he does not ask again | `reply/intents.py` (`social:refusal`), `decide/job.py` (refuse → decline) |
| `@Otokodelyoko what is the plot of dune?` | an apology, **never a guess** | `phrasebooks/friend-b/hedge.json` |
| `@Otokodelyoko hey` (three times) | he **repeats** himself sometimes; repetition is the pass condition | `decide/variant.py` |
| a nine-word answer, then the same question again | **silence**, and the log says `he just said that` | `render/audition.py` -- short lines are allowed to repeat, long ones are not |
| read five replies aloud | some stuttering (`i- i think`, `th- the train` — note the **space** after the hyphen), a filler now and then (`um,`), an emoticon in roughly half | `style.stutter_rate` / `filler_rate` / `emoji_rate` in the persona |
| a statement you made, later | he asks after it -- `how is otis?` | `memory/`, `decide/recall.py` |

### The three silences that are correct

* **Unaddressed.** Plain chatter is heard and remembered, not answered -- `reply: mention`.
* **Asleep.** At ~03:00 his schedule says silence, and the log says `stayed quiet ... he is asleep`.
* **He just said it.** Asking the same thing twice in a row gets nothing the second time; the log says
  `he just said that`.

If a message gets no answer and none of those apply, the log now says why:

```bash
grep -aE 'did not answer|stayed quiet|greeted' data/logs/bot.log | tail -5
```

---

## 3. The two of them together

The failure this catches is a *shared mouth*: `topic:computers` is one tag both friends know, so before
lines were owned, whichever scored closest got spoken by either of them.

| Ask both the same thing | Expect |
|---|---|
| `do you like computers?` to Terry and to Otto | two different answers -- Terry's about machines that phone home, Otto's about taking one apart |
| `hey` to both | Terry: `hey`/`you`; Otto: `hi`/`oh, hi`/`h-hi` |
| `good night` to both | Terry: `night bud`; Otto: `night night` |
| any subject | never the other one's line |

Both are checked offline too: `ttrpg-chatbots-persona friend-a` and `... friend-b` must each report only
their own lines.

---

## 4. His voice

Join a voice channel yourself, then:

```
/voicetest action:join                 → friend-b: joined <your channel>
/voicetest action:speak                → he speaks a fixed line in his own casting
/voicetest action:speak                → AGAIN. This is the check that used to be impossible
/voicetest action:speak text:oh, hello. i- i think the train is late again
/voicetest action:leave
```

| Check | Pass | Blame |
|---|---|---|
| the second `speak` makes sound | the stream is reusable | `voice/discord_voice.py` -- `cleanup` must not clear the shared queue |
| soft and androgynous, not feminine | 156 Hz measured, just under the female voices | `voices.jsonl`, the `cast-otto` rule |
| hesitant rather than slow-and-heavy | the stutter and the fillers are in the *text*; the pace is 1.15 and the pitch shift leaves it alone | `style.stutter_rate`/`filler_rate`, `speed`, `pitch_hz` |
| the right words | the model is `en_US-ryan-medium` | `ttrpg-chatbots-tts --verify-voice` |

Samples to compare against, no Discord needed: `data/samples/otto/` (all eight auditioned voices) and
`data/samples/otto/tuned-*.wav` (the three finalists at his pace).

---

## 5. Recovery drills

Worth running once, so the procedures are known before they are needed.

**The voice is gone** (cleared cache, new box):

```bash
mv ~/.cache/ttrpg-chatbots/models/piper/en_US-ryan-medium.onnx* /tmp/
ttrpg-chatbots-tts --verify-voice          # "... is missing", exit 1
ttrpg-chatbots-tts --fetch-voice           # fetches from the first source that verifies
ttrpg-chatbots-tts --verify-voice          # verified
```

**Two processes** (double replies): `./start-bot.sh --status` lists every process and warns; `--stop`
kills all of them.

**After a crash**: `data/bot.pid` may be stale, which is harmless -- `--status` reports by process table,
not by the file. Check `sqlite3 data/memory.db 'pragma integrity_check'` (it should say `ok`) and that
`git status` is clean, then start.

---

## 6. What "Otto is done" means

All of these, on one run:

1. `tools/check_friend.sh friend-b` exits 0.
2. Every row in §2 behaves as written, including the three correct silences.
3. §3 gives two different friends for the same question.
4. The second `/voicetest speak` makes sound, and the voice is one you chose by ear.
5. Nothing in §2 makes you wince -- the tests check shape, not taste, and only you can check taste.
