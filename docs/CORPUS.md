# The corpus, split so it can grow

## 0. Why this exists

Two things were true at once in the log:

```
12:36  Otto:   re- rearranging my shelf
12:46  Crusty: Oh, that is lovely
12:58  Terry:  ah right
```

**Every line was an offer nobody took.** `"what do you put on it?"` never happened, and the conversation never
left the entry point -- a series of shallow microconversations, each one closing itself. The words were fine.
What was missing was the ability to *reach* the thing that was offered, and reaching it needs material about
shelves, not about conversation.

And the corpus was not shaped to be extended: `knowledge.jsonl` is 294 lines covering every subject for every
friend, so adding depth to *trains* means editing a file where a mistake lands on Rome.

So the corpus is now three kinds, each answering a different question, each segmented on its own axis.

| Kind | Answers | Segmented by | Where |
|---|---|---|---|
| **Phrasebooks** | *how* he says a thing | **job** (and per-friend override) | `phrasebooks/<job>.json`, `phrasebooks/<friend>/<job>.json` |
| **Life** | what is happening to *him* | kind (activities, grievances, stories, plans) | `life.json` |
| **Domains** | what he knows and can discuss | **subject area** | `domains/<area>/` |

## 1. A domain is a folder

```
domains/trains/
  domain.json        the area: how it is referred to, and its aspects
  friend-b.jsonl     one friend's material in that area, tagged by aspect
```

```jsonc
// domain.json
{
  "id": "trains",
  "names": ["trains", "the trains", "the railway", "the station", "the line"],
  "aspects": [
    {
      "name": "the-old-ones",
      "names": ["the old ones", "old trains", "the carriages", "the old stock"],
      "questions": ["what is different about the old ones?", "do you have a favourite?"]
    }
  ]
}
```

```jsonc
// friend-b.jsonl  -- Otto, one line per thing he can say when asked
{"aspect": "the-old-ones", "text": "the old ones have windows you can open"}
```

**An aspect is the part of an area a conversation can actually reach.** That is the whole idea: "trains" is too
big to ask about, "the old ones" is a thing somebody can ask a question about and somebody else can answer.
Each aspect carries the questions a friend might ask and, per friend, the lines he can answer with -- so both
sides of a dig have material for *the shelf* rather than for shelves in general.

Validation is loud, because a silent hole is worse than a refusal: an aspect with no names is unreachable, an
aspect with no questions cannot be asked about, a domain with no aspects is empty, and a material line tagged
with an aspect that does not exist names the file and the valid options.

## 2. Taking a hook

`decide/dig.py` does one thing: given an offer and the domains a friend knows, produce the question that takes
it. The answering half says which aspect he was asked about.

```
Otto:   i have been rearranging my shelf          (offer_hook)
Crusty: what is on it?                            (dig, act = ladder|dig|cute-things:the-shelf|)
Otto:   a ceramic frog, a tin train, and a leaf i pressed   (answer_dig)
```

A question like *"what is on it?"* names nothing, so the text cannot carry what it is about -- the turn's act
does (`<domain>:<aspect>`), and that is how the answering side knows what it was asked.

Four refusals, all tested, all of them things a person does: he only digs at an **offer**, never **twice in a
row** (two questions running is an interview), only at his own `question_rate` (with the same offer bonus
`follow_up` uses, because they have just handed him something to ask about), and never a question he has
**just asked**.

Matching is whole words and the **longest name wins**: "the old ones" beats "the old", `train` does not match
`training`. Same discipline as the entity index -- fuzzy matching here is how a bot decides the weather is
about trains.

## 3. How to expand, precisely

Four sizes of edit, smallest first. Each one touches exactly one place.

| You want | You edit | Nothing else reads it |
|---|---|---|
| another way he can answer an aspect | one line in `domains/<area>/<friend>.jsonl` | ✓ |
| another question that can be asked about an aspect | the `questions` list of one aspect | ✓ |
| another way something is referred to | the `names` list of one aspect (or the area) | ✓ |
| a whole new subject area | a new `domains/<area>/` folder | ✓ |

Worked example, run for real: adding `"the 8:15"` to `trains:the-station` made *"the 8:15 was late"* reach the
station aspect, and changed nothing else -- `rearranging my shelf` still reached `cute-things:the-shelf`, and
`the old carriages` still reached nothing, because that phrase is not one of the names.

**A domain at a time.** A domain is also the migration unit: move a subject's lines out of `knowledge.jsonl`
into `domains/<area>/` when you want to deepen it, and leave the rest where it is. The loader reads both, so a
half-migrated world works, and no migration has to happen in one sitting.

**Where a big corpus comes from.** The four sizes above are how we grow by hand. When that runs out,
`SOURCES.md` is the survey of external corpora (measured sizes, verified licences, sampled lines), which
one feeds which module, and the three conditions under which bulk data is honest rather than a way of
hiding a structural problem.

## 4. It is wired, and what that took

`dig` and `answer_dig` are jobs in the vocabulary, the loop sources their words from domain material, and
the room does the exchange for real:

```
friend-b: i have been rearranging my shelf        (offer_hook)
friend-a: what is on it?                          (dig, cute-things:the-shelf)
friend-b: a- a ceramic frog, a tin train, and a leaf i pressed   (answer_dig)
friend-c: Oh, that is lovely                      (noted)
```

Four things had to change, and each was found by running it rather than by reading it:

* **A domain line is not a phrasebook line.** The render path had one invariant -- *only the leaf writes
  words, and it writes them from a phrasebook* -- so the loop now has one branch that takes its text from the
  domain and still runs it through the budget, the typing style and the persona gate. A domain cannot smuggle
  in a line the rest of the ladder would have refused, and a test asserts exactly that.
* **The budget knows what the turn is for.** A question is longer than the hook it answers: "what is
  different about the old ones?" is seven words against a three-word hook, and the mirror rule trimmed it to
  nothing. `decide.length` gained an answer floor, the same shape as the story floor.
* **The room reads the act from the trail.** It used to invent `ladder|chat|` for every line, so the room
  could not see that a turn was a story or a dig. Measured consequence: the friend being asked answered a
  different question and hedged. It now rebuilds the real act, and takes the **last** `about=` (the trail
  carries the ordinary subject and then the aspect).
* **The floor goes to whoever offered.** Terry asked Otto's shelf a question, the rotation handed the floor to
  Crusty, and she hedged -- it was never her shelf. After a dig the offerer answers, which is also what makes
  the answer available at all.

Measured effect on a simulated day: the job mix went from **two jobs to eight** (offer_hook 54, noted 40, dig
34, answer_dig 34, ask_back 4, mirror 3, greet 1, follow_up 1, hedge 1), with zero silences.

## 5. How growth is measured

The instrument is already in `tools/analyse_chatter.py` (see `TEXTURE.md` §7): the **distinct (job, topic)
pairs** and the **median repeat interval** for a day. Today the room has six meanings on a 22-minute cycle.
Adding a domain adds aspects, and an aspect is a new pair the conversation can reach -- so the number to move
is the pair count, and the number that says "this is working" is the repeat interval climbing past the length
of a session.
