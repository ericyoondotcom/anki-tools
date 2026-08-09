# japanese-merge

Merges the **Japanese Vocab** and **Japanese Kanji** note types into a single
**Japanese** note type with four cards — without losing a single card's
scheduling or review history.

Unlike the rest of this repo, this is **not an Anki add-on**. It is a one-shot
migration you run from the command line against a *copy* of your collection,
verify, and only then swap in.

## The four cards

| # | ord | Card | Front | Answer tests | Appears when |
|---|-----|------|-------|--------------|--------------|
| 1 | 0 | Produce | English | recall the Japanese word | flag `p` |
| 2 | 1 | Write | English + kana | hand-write the kanji | flag `w` **and** a Kanji |
| 3 | 2 | Meaning | Japanese + kana | English meaning | flag `m` |
| 4 | 3 | Read | kanji only, no furigana | reading **and** meaning | flag `r` **and** a Kanji |

Cards 3 and 4 are split by *skill*, not just cue strength: card 3 shows the
reading and asks for meaning, card 4 hides it and asks you to read aloud. If
both asked "what does this mean?", card 3 would give away card 4's answer.

## Why nothing is lost

`revlog` rows reference `cards.id`, and every scheduling value (`due`, `ivl`,
`factor`, `reps`, `lapses`, `queue`) lives on the card row. The migration
**preserves every `cards.id`** and only rewrites `nid`, `ord` and `did`, so
scheduling and history follow automatically.

This works because the old cards map 1:1 onto the new ones:

    Vocab  Card 1  (EN -> JP)        ->  ord 0   Produce
    Kanji  Card 1  (EN+kana -> write) ->  ord 1   Write
    Vocab  Card 2  (JP -> EN)         ->  ord 2   Meaning
    Kanji  Card 2  (kanji -> EN)      ->  ord 3   Read

Consequently the migration runs **in place**. Exporting to `.apkg` and
re-importing would mint new card IDs and reset everything; it would also have
forced the 342 stroke-order SVGs through a media round-trip. Neither happens.

## Per-note card selection

The `Cards` field holds any subset of `p w m r` — `pm` for a kana-only word,
`pmrw` for a kanji word you also want to hand-write. Order and case don't
matter (`mrw` == `pwmr` minus `p`).

Anki template conditionals can only test a field for *emptiness*, so one field
cannot gate four cards. `Cards` is therefore expanded into four hidden gate
fields `_P _W _M _R` that the templates actually test. Keep them in sync with
the **Tools → Sync Japanese card flags** action from the `japanese-vocab`
add-on, or with `merge.py resync`.

> **Careful:** removing a letter stops that card being generated. If the card
> already has review history it becomes an *empty card*, and Tools → Empty
> Cards will then delete it along with its history. The add-on detects this
> and offers to suspend the card instead — suspension is fully reversible,
> deletion is not. Prefer suspending.

## Files

| File | Purpose |
|------|---------|
| `merge.py` | The migration. Modes: `plan`, `apply`, `verify`, `resync` |
| `overrides.tsv` | Hand decisions for kanji that automatic matching can't resolve |
| `deckmap.tsv` | Source deck -> target deck + lesson tag |
| `templates/` | The four card templates and the shared stylesheet |
| `report.tsv` | Written by `plan`/`apply`: what happened to every kanji note |

`overrides.tsv` and `deckmap.tsv` are **data, not code** — edit them and re-run.
If `deckmap.tsv` is missing a deck that actually holds cards, the run aborts
rather than silently dropping those cards.

## Running it

Anki must be **closed** for the final swap.

```bash
python3 -m venv .venv
.venv/bin/pip install anki==26.5        # must match your installed Anki

COL=~/"Library/Application Support/Anki2/User 1/collection.anki2"
W=/tmp/japanese-merge
mkdir -p $W && cp "$COL" $W/orig.anki2 && cp "$COL" $W/new.anki2

# 1. dry run — writes report.tsv, changes nothing
.venv/bin/python japanese-merge/merge.py plan --col $W/new.anki2

# 2. review report.tsv, then migrate the copy
.venv/bin/python japanese-merge/merge.py apply --col $W/new.anki2

# 3. prove nothing was lost
.venv/bin/python japanese-merge/merge.py verify --before $W/orig.anki2 --after $W/new.anki2

# 4. only if verify passes
cp "$COL" "$COL.pre-merge-backup"
cp $W/new.anki2 "$COL"
```

`verify` checks that no card was destroyed, that every surviving card's
scheduling is byte-identical, that the revlog is intact and orphans no rows,
that no `(nid, ord)` is duplicated, that every media reference survived, and
that every existing card's flag letter is set (so nothing renders empty).

## Rollback

Restore `collection.anki2.pre-merge-backup`. Anki's own `backups/` folder and
any `.apkg` exports are the second and third lines of defence. The migration
calls `mod_schema()`, so the next sync is a full upload — if you sync, make
sure the local collection is the one you want to keep.

## Notes

- Cross-level merges are allowed; the **vocab card's deck** decides where the
  merged note lives.
- Flattening decks would have destroyed the Tobira/Sun-Academy lesson
  structure, so every note also gets a `Tobira::L03`-style lesson tag and a
  `src::<original deck path>` provenance tag. Nothing is lost, and per-lesson
  study still works: `deck:"L1 - Tobira" tag:Tobira::L03`.
- Matching surfaced **duplicate vocab notes** (運ぶ, 実際に, 送る each appear
  twice). These are left alone — worth a separate cleanup pass.
