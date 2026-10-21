# corpora

Downloaded source data lives here, and nothing large is tracked. The folder exists in a clone
because of this README; everything beside it is ignored by git.

The division of labour:

| Folder | Holds | Tracked? |
|---|---|---|
| `corpora/` | what we downloaded, and what we derived from it | no (except this file) |
| `data/` | this install's runtime state — characters, seats, `bots.json`, logs | no |
| `examples/` | the small demo and friends worlds, hand-written | **yes** |
| `tests/fixtures/` | what tests need | **yes** |

Rule of thumb: if it is reachable from a URL or a script, it belongs here; if it is somebody's
character sheet, it belongs in `data/`; if a test cannot pass without it, it belongs in
`tests/fixtures/`.

## Switchboard (the act-transition source)

```bash
mkdir -p corpora/switchboard && cd corpora/switchboard
curl -LO https://zissou.infosci.cornell.edu/convokit/datasets/switchboard-corpus/switchboard-corpus.zip
unzip -q switchboard-corpus.zip && mv switchboard-corpus/* . && rmdir switchboard-corpus
rm switchboard-corpus.zip          # 37 MiB of JSONL is what we actually read
```

Then, from the repository root:

```bash
.venv/bin/ttrpg-chatbots-reply \
    --import-acts corpora/switchboard/utterances.jsonl \
    --format switchboard --min-coverage 0.25 \
    --out corpora/switchboard/transitions.json
```

and point the friends at it:

```bash
echo 'TTRPG_FRIENDS_TRANSITIONS=corpora/switchboard/transitions.json' >> .env
```

## Licence

Switchboard is **CC BY-NC-SA 3.0**. No corpus text is ever committed, and neither is anything
derived from it. That is exactly why this folder is ignored rather than curated: the derived
table is 1 KB, and it would be tempting to commit. `docs/CLASSIFIER.md` §4 has the reasoning.
