# Conversation: the decomposition

Why the conversation layer is being rebuilt as ~45 single-purpose modules instead of one `reply()`
function, and the rules that keep it that way.

**Status: design accepted, not yet built.** Nothing in the live bot changes until the ladder and the
harness exist. The day model is the first piece and is already built (`docs/SCHEDULE.md`).

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
  phrasebooks/greeting/{families.json, warm.jsonl, casual.jsonl, time_aware.jsonl}
  phrasebooks/{pleasantries,hook,substance}/…
  knowledge/{subjects,stances,stories}.jsonl     # depth-tagged
  life/{activities,grievances,plans}.jsonl
  schedule.json
  cast/character.json
```

Resolution is base → character override, per file, per id. Changing how warmly he greets touches one
file that nothing else reads. Depth tagging is what makes exposition impossible: `subjects` holds the
hook, `stances` the opinion, `stories` the three-sentence version, and the phase decides which tier is
even addressable.

> Today's worlds live in `examples/friends_world/`, where `knowledge.jsonl` is read by the matcher,
> the renderer *and* the subject vocabulary. That is the coupling this layout removes.

## 6. Slice 0, before anything else

`govern/trace.py` (every reply carries its eight rungs) + a **conversation harness** that plays a
scripted ten-turn exchange and reports: length ratio vs the human, clause count, lines ending in a
beat, greeting repetition, and expositions at depth 0. The audit numbers above become the failing
test.

Only then build the ladder for one job — greeting — across all eight rungs, with one phrase file.

## 7. Risks

- **Telegraph.** Mitigation: `Abstain` everywhere; silence over improvisation.
- **Debugging.** Mitigation: the trace is mandatory, plus `conv --explain "hey"` printing the rungs.
- **Premature splitting.** Rule: split a module only when it fails its own test for two different
  reasons.
- **Wiring cost.** Mitigation: every module ≤ 60 lines, one export, and a manifest test that fails if
  the module list changes silently.
