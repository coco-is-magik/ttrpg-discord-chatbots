# Conversation: the decomposition

Why the conversation layer is being rebuilt as ~45 single-purpose modules instead of one `reply()`
function, and the rules that keep it that way.

**Status: design accepted, partially built.** Nothing in the live bot changes until the ladder and
the harness exist. The context pieces are built and wired to nothing: `docs/SCHEDULE.md` (the week)
and its calendar (the year). The plan itself is `src/ttrpg_chatbots/conv/manifest.py` —
**11 of 50 modules built**, with a test that fails if a module is marked built and does not import,
or marked planned and exists anyway. See it with
`python -c "from ttrpg_chatbots.conv import summary, check; print(summary()); print(check())"`.

## 1. The failure being fixed

`Replier.reply()` answers eight questions at once: is this a move, which move, which subject, is it
close enough, how much, what words, how long, does it fit the context. Every fix landed in that one
function, so none of them held. A greeting reply also tried to be a hook, and a hook carried its own
backstory: **one turn has to do one job**, and the job is chosen by the conversation, not by the
reply's ambition.

Measured on the old corpus (112 lines) against the human's own messages (13):

| | bot | human |
|---|---|---|
| words, median | 7.0 | 2.0 |
| sentences, median | 2.0 | 1.0 |
| lines ending in a short beat | 29% | — |
| distinct messages | 112/112 | 10/13 |

Talking at 3.5× the length, twice the clause count, and never repeating a phrase is what "written"
sounds like.

## 2. The rules

1. **One question per module.** One input type, one output type.
2. **No I/O except adapters.** Only `perceive/*`, `memory/store.py` and `render/line.py` touch the
   world.
3. **Only the leaf writes words.** Bands 1–3 return decisions and references.
4. **Every stage may abstain.** `Draft | Abstain(reason)`: a wrong call goes quiet, not strange.
5. **One dataset file, one reader** — enforced by a test.

## 3. Bands

| Band | Job | Modules |
|---|---|---|
| **Perceive** | describe the situation | inbound, typing, modality, attachments, addressee, clock, gap, events, situation, world, thread, entities, intent, tone, sentiment |
| **Remember** | hold and move state | short, encode, promote, long, retrieve, decay, open, relationship, store |
| **Decide** | one rung each | floor, phase, depth, job, who, form, family, variant, length, reciprocate, persona_fit |
| **Render** | words, once | fill, trim, typing, audition, line |
| **Govern** | wiring and measurement | loop, repeat, trace, abstain |

`decide/depth.py` is the structural fix for exposition: a thread carries *how many times this person
has leaned in*, and a hook at depth 0 cannot reach the story tier at all.

## 4. The ladder, one level of specificity at a time

"hey", from a friend not seen for 14 hours:

| Rung | Module | Answer |
|---|---|---|
| 1 | `floor` | speak |
| 2 | `phase` | opening |
| 3 | `job` | greet |
| 4 | `form` | recognise (he knows this person) |
| 5 | `family` | warm |
| 6 | `variant` | `g-warm-03` — "there he is" |
| 7 | `fill` + `typing` | "there he is" |
| 8 | `audition` | 4 words ✓ one clause ✓ no beat ✓ in character ✓ |

If `audition` rejects, it asks **`variant`** for the next candidate. It never re-runs the ladder.
Tuning "he greets too warmly" means editing one family's triggers, not debugging a monolith.

## 5. Datasets

```
personas/base/…                    the neutral friends
personas/friend-a/
  persona.json                     brief: name, voice, style, values
  lexicon/{intents,tone,sentiment,entities}.jsonl
  phrasebooks/greeting/{families.json, warm.jsonl, casual.jsonl, time_morning.jsonl, time_evening.jsonl}
  phrasebooks/{pleasantries,hook,substance}/…
  knowledge/{subjects,stances,stories}.jsonl     # depth-tagged
  life/{activities,grievances,plans}.jsonl
  schedule.json                  # the week, in 15-minute blocks
  calendar.json                  # the year: seasons, holidays, one-offs
  cast/character.json
```

Resolution is base → character override, per file, per id. Changing how warmly he greets touches one
file that nothing else reads. Depth tagging is what makes exposition impossible: `subjects` holds the
hook, `stances` the opinion, `stories` the three-sentence version, and the phase decides which tier is
even addressable.

> Today's worlds live in `examples/friends_world/`, where `knowledge.jsonl` is read by the matcher,
> the renderer *and* the subject vocabulary. That is the coupling this layout removes.

## 6. Slice 0 — done, and what it proved

`govern/trace.py` (every reply carries its eight rungs) and `govern/harness.py` (a matrix through one
phase, reporting words, distinctness, beat rate and why anything stayed quiet) both exist. The audit
numbers are now a test:
`tests/test_greeter.py::test_the_harness_answers_every_time_and_never_sounds_like_a_caption`.

```bash
.venv/bin/python -m ttrpg_chatbots.conv.cli --harness
# phase: greet
# attempts 144  said 144  abstained 0
# words: median 1, max 3
# distinct: 7% (10 of 144)
# ends on a beat: 0%
```

Under the old corpus: median 7 words, 51% of lines two sentences, 29% ended on a beat, 100% novelty.
The first phase on the ladder: 1 word, 0% beats, 7% distinct — i.e. **repetition**, which is what
familiarity sounds like.

`ttrpg-chatbots-conv --greet "hey" --explain` prints the eight rungs for a single message.

### What the harness caught that review did not

1. **A long variant silenced a whole family.** Twenty of 144 greetings were dropped as "over budget"
   because `decide/variant` offered a six-word line for a three-word budget and `render/trim` then
   refused it. Fixed at the rung that chose it: a line that cannot fit is not a candidate.
2. **A missing family borrowed another family's lines**, so a stranger got "there he is". Removed:
   no family, no lines.
3. **The greet phrasebook answered other jobs** (`offer_hook`, `acknowledge`) because the loop never
   checked. It now abstains: `the greet phrasebook does not do acknowledge`. That is the phase
   boundary, enforced rather than documented.

### Proving it on a person

The ladder runs live for greetings only, behind `TTRPG_CONVERSATION=greet`; everything else still
goes to the old classifier. The script is `docs/MANUAL_TESTING.md` §2.5: eight checks, each naming
the module that owns a failure, plus four outcomes that would mean the decomposition is wrong rather
than the phrasebook.

## 7. Risks

- **Telegraph.** Mitigation: `Abstain` everywhere; silence over improvisation.
- **Debugging.** Mitigation: the trace is mandatory, plus `conv --explain "hey"` printing the rungs.
- **Premature splitting.** Rule: split a module only when it fails its own test for two different
  reasons.
- **Wiring cost.** Mitigation: every module ≤ 60 lines, one export, and a manifest test that fails if
  the module list changes silently.
