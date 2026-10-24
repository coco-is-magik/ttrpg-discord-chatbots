# Where a bigger corpus comes from

Our authored corpus is the binding constraint: three friends share ~200 hand-written lines and a
handful of domains, so the same job fires in the same situation with the same words. This is the
survey of what already exists, what it actually contains (read, not assumed), and which part of our
architecture each source can feed **without hiding a problem**.

Everything here is measured: sizes come from the HuggingFace API, licences from the dataset cards, and
the sample lines are quoted from files downloaded and opened on this box.

## 1. The survey

| source | size (measured) | licence (verified) | register, from the actual lines | feeds |
|---|---|---|---|---|
| **SODA** (`allenai/soda`) | 816 MB, 1.19M dialogues | **CC BY 4.0** | written, polite, situational roleplay between two named people | domains (dig/answer_dig), reasons, life events |
| **ROCStories** (`hamishivi/ROCStories`) | 28 MB, 70,676 × 5 sentences | **CC BY 4.0** | third-person narration of ordinary events | stories, activities, grievances |
| **GoEmotions** (`google-research-datasets/go_emotions`) | 27 MB, 58k labelled | **Apache 2.0** | single Reddit comments | sentiment/tone lexicon, emotion |
| **Switchboard** (SwDA) | 37 MB, 122,646 utterances | CC BY-NC-SA 3.0 | 1990s telephone speech | act transitions — **already in use** |
| **BlendedSkillTalk** (`ParlAI/blended_skill_talk`) | 10.4 MB, 4,819 convos, ~20 suggestions/turn | **unknown** (aggregates convai2 + empathetic + WoW) | texting-ish, lowercase, contracted | phrasebook candidates, personas |
| **prosocial-dialog** (`allenai/prosocial-dialog`) | 112 MB | **CC BY 4.0** | social norms, "what should I do" | rules, rulings |
| **PersonaChat** (`bavard/personachat_truecased`) | 196 MB | unverified | five short first-person facts per speaker | persona/life lines |
| **NUS SMS Corpus** | 2 MB, 55,835 English | **none — cite and email the author** | real texting, real typos | typo calibration |
| **SILICONE** | script + data pointers | CC BY-SA 4.0 | act labels over 10 corpora | act classifier training |
| **Wikipedia** (`wikimedia/wikipedia`) | 68 GB | CC BY-SA 3.0 | encyclopedic prose | facts only, never speech |
| **ultrachat / oasst2** | 1.5 GB / 332 MB | MIT / Apache 2.0 | assistant register | **not usable** — wrong voice entirely |
| **DailyDialog** | 4.5 MB, 13k dialogues | CC BY-NC-SA 4.0 | learner English | weak: four act labels |

### What the samples actually look like

**SODA** — a situation, a knowledge triple, and a dialogue:

```
narrative: Perry buys supplies at the store because Perry wants to be prepared for the next task…
triple   : PersonX buys supplies | xIntent | to be prepared for the next task
  Hi there! Can I please get a pack of lined paper, a pencil case, some number two pencils…
  Absolutely! Let me grab those for you.
```

The dialogue is not our register — two speakers, full sentences, transactional. **The triples are the
prize**: `xIntent` is a *reason*, which is exactly what `explain` needs, and SODA carries a whole
taxonomy of them (`xIntent`, `xReact`, `xWant`, `xNeed`, `xEffect`, `xAttribute`, `oReact`…) that maps
onto our jobs: `xIntent`→explain, `xReact`→mirror/reassure, `xWant`→plans.

**ROCStories** — five sentences, an ordinary event, a small turn at the end:

```
Cory went fishing with his family for the first time. He didn't know how to cast the line and became
discouraged. Cory's dad helped him cast the line into the water. Cory was able to hook a fish and
started to reel it in. Cory caught the fish and was excited.
```

Third person, past tense — but the *shape* is a story with a point, which is the phase-3 material our
`life.json` has three of. Conversion to first person and a trim is mechanical.

**BlendedSkillTalk** — the closest register match, and the most awkward licence:

```
personas: ["i've 2 kids.", 'i love flowers.']
suggestions.convai2: ['yum . i like to make lasagna and it s so good',
                      'it beats ramen noodles for sure ! do you have any hobbies ?']
suggestions.empathetic_dialogues: ['Any favorite actors?', 'One day.']
```

Twenty candidate next-lines per turn, **labelled by the register they came from**. That is a phrasebook
source in the shape of a phrasebook — short, lowercase, first-person, and already sorted into "display
a personality" versus "show empathy" versus "share knowledge". The spacing is tokenised
(`lasagna and it s so good`) and needs cleaning; the licence is `unknown`, so it is study material
rather than committed data.


## 2. Which vein feeds which module

| our module | shape it needs | best source |
|---|---|---|
| `phrasebooks/<friend>/<job>.json` → `families[].variants` | short first-person lines, many per move | BST (study), authored (committed) |
| `reply/domains/*.json` → `Aspect.questions` + `Domain.answers` | a question about an aspect, and answers | **SODA** |
| `life.json` → `activities`, `grievances` | an ordinary thing happening, a snag | **ROCStories**, SODA narratives |
| `life.json` → `stories[].body` + `.point` | an event with a turn and a point | **ROCStories** |
| `perceive/sentiment.py`, `perceive/tone.py` | polarity and tone vocabulary | **GoEmotions** |
| `reply/transitions.json` | act-to-act counts | SwDA (in use), SILICONE |
| `persona.py` → `favourites`, `taste` | what a person likes and why | PersonaChat, authored |
| typo/error modules (planned) | real typing errors, rates | NUS SMS |
| `knowledge.jsonl` | facts and opinions | authored — a corpus cannot have an opinion |

## 3. The verdict: yes for texture, no for depth — and the difference matters

**What our structure absorbs cleanly.** Adding lines to a family, aspects to a domain, or stories to a
life is a data edit. The ladder already chooses by family, budget, gate and repeat, so more candidates
in a family changes *which words*, not *which rules*. `reply/domains.py` was explicitly designed as one
folder per domain for this reason (`CORPUS.md` §1).

**Three conditions, without which bulk data conceals a problem:**

1. **Voice ownership.** Every line in a phrasebook today is authored *for a friend*, and the per-friend
   override plus `persona_fit` exist to keep it his. A bulk line is in a stranger's voice. If we drop
   those in, the *style layer* starts doing the characterisation — which is the canned-line problem
   wearing a disguise. Lines must be **registered**: filtered by the persona's measured properties
   (length, person, register), passed through the gate, then read by a human in samples. Our gate judges
   *shape*, not voice, so the human sample per family stays necessary.
2. **Lines buy texture; structure buys progression.** The evidence is in our own log: hooks went
   untaken because **no domain existed for the aspect** ("rearranging my shelf" → nobody asked "what is
   on it?"). A million generic lines would not have fixed that; the `dig`/`answer_dig` domain did. So
   the honest diagnostic is this pair of numbers together — **if repetition improves while job mix and
   phase progression stay flat, we bought texture, not depth.** Both instruments already exist
   (`tools/analyse_chatter.py` for repetition and the job mix; progression is in the trail).
3. **Licence per source, extended to derived data.** Our rule was "corpora are git-ignored and
   regenerable, only authored data is committed". That now has to cover *derived* material too: a
   phrasebook built from a NC or unknown source cannot be committed. Anything committed should come
   from **CC BY 4.0 or Apache** sources (SODA, ROCStories, GoEmotions); NC and unknown sources stay in
   `corpora/` behind a generator.

**One more that is easy to forget:** these corpora contain crude, offensive and nonsensical lines.
`persona_fit` rejects beats and coldness; it would happily pass an insult. A filter step (profanity,
second-person rate, length, non-speech) plus sampling review is part of the pipeline, not an extra.

## 4. The pipeline

Same pattern as `reply/importers.py` (which already reads Switchboard), one adapter per source:

```
corpora/<source>/            downloaded, git-ignored
corpora/derived/<source>/    extracted, filtered, registered — with `source` on every line
```

- **extract** — pull the candidate shape out of the source (a suggestion, a story, a triple)
- **filter** — register, length, person, banned lexicon; drop the unusable
- **register** — rewrite into our format, keeping `source` provenance per line
- **review** — sample N per family/job and read them; a human gate, because shape ≠ voice
- **promote** — move reviewed lines into the **overlay**, never into `examples/`: `TTRPG_FRIENDS_DATA`
  points at a git-ignored world directory that the loader merges over the shipped one, so a friend's
  expanded corpus is loaded at runtime and can be deleted again without touching the repository

`source` on every line is what makes contribution measurable rather than assumed.

## 5. Ranked plan

1. **ROCStories → `life.json`** (CC BY 4.0, 28 MB). Stories, activities, grievances; first-person
   conversion. Biggest *felt* gain, because phase 3 is where conversation currently dies.
2. **SODA → domains** (CC BY 4.0, 816 MB). Aspects, answers and `xIntent` reasons — the vein that
   moves *progression* rather than texture. Take the `valid` shard first (79 MB) to prove the shape.
3. **GoEmotions → sentiment and tone** (Apache 2.0, 27 MB). Replaces the hand-written lexicons we
   already know were the overfitting axis.
4. **BST → phrasebook shape** (unknown licence, study only). Use it to learn what a family should
   contain and how many variants are normal; commit authored lines.
5. **NUS SMS → typo calibration** (no licence; cite, and email the author). Small, and the only source
   of *real* typing errors.
6. **SILICONE → act model** (CC BY-SA 4.0; share-alike constrains derived tables).

## 6. The fourth vein, which avoids two of these problems

Every source above is in someone else's voice and carries a licence. **Generating variants in the
persona's own voice** — from the authored lines, as seeds — solves the voice-ownership problem by
construction and has no licence question at all. It needs a model decision (`GROUP.md` §12), and its
failure mode is the opposite one: a model will happily write a line that passes the gate and still
sounds like a machine, so the sample-read stays either way.

Worth naming because it changes what "expand the corpus" means: **authored > generated > borrowed**,
in that order, for anything a friend says in his own voice.

## 7. What may be in the repository

**Code, docs, config, and tiny authored examples. Nothing else.** Every dataset is user-sourced: pulled
by a script, written to a git-ignored directory, loaded at runtime, and deletable without touching the
repository. Three things hold that in place, and each is a command rather than an intention:

```bash
# 1. the corpus is ignored, and by which rule
git check-ignore -v corpora/switchboard/utterances.jsonl
#    -> .gitignore:37:corpora/*	corpora/switchboard/utterances.jsonl

# 2. nothing but code, docs, config and LICENSE is tracked
git ls-files | grep -vE '\.(py|md|toml|cfg|txt|sh|yml|yaml|example)$' \
              | grep -vE '^\.gitignore$|^(tests/fixtures|examples)/'
#    -> LICENSE

# 3. a corpus cannot be staged even by accident
git add --dry-run corpora/
#    -> The following paths are ignored by one of your .gitignore files: corpora
```

The rules: `.gitignore` ignores `corpora/*` (keeping `corpora/README.md` so the folder exists and
explains itself), plus `data/`, `datasets/`, `models/`, and anything `.jsonl.gz`.

**This was violated twice**, which is why the section exists:

* commit `b04ca1c` deleted the `corpora/` rules and committed Switchboard's `utterances.jsonl` — 36 MB,
  the largest object in the repository;
* the early `Create LICENSE` commit had swept the user's `OG Character Sheets.xlsx` (2.4 MB) and
  `My House Games Edits.md` (615 KB) into its tree, and that commit was the remote's tip.

Both were purged with `git filter-repo --invert-paths` on 2026-10-24: **139 of 200 commits rewritten,
`.git` from 9.7 MB to 1.4 MB**, and the largest remaining blob is 130 KB of Python. The two user files
were extracted from history *before* the rewrite and now live in `data/user-supplied/`, and the remote
was force-pushed to the same cleaned history — it held only six commits, all present in the rewrite, so
nothing was published.

**One caveat that is not ours to fix:** GitHub may keep the unreachable objects on its side until its own
garbage collection. The refs no longer point at them, but if the data must be gone from GitHub's storage
immediately, the only guaranteed way is to delete and recreate the repository.
