---
name: japanese-vocab-import
description: Import a Japanese vocab list from a class PDF into a new Anki unit deck under "L7 - Yale" (or any lesson deck), creating produce/read/meaning cards and folding in duplicates. Use when asked to add vocab words from a PDF to Anki, build a new Unit deck, or import marked (asterisked) terms from a handout.
---

# Importing a vocab PDF into the Japanese deck

Class handouts mark the words that appear on quizzes with a full-width asterisk
(`＊`). The job is to turn those marked rows into notes of the `Japanese` note
type, in a new `Unit NN` subdeck, with the card set the user asked for.

Work through the steps in order. Do not skip the verification step — the two
failure modes that matter (a dropped word, a silently mangled kanji) are both
invisible unless you check for them.

## What you need to know first

The collection has one note type, `Japanese`, with these fields:

```
English  Kana  Kanji  Romanji  Diagram  Hint  Memorization Aid
(card - produce)  (card - write)  (card - meaning)  (card - read)
```

The last four are gates: put `1` in one to generate that card, leave it empty
for no card. For a vocab unit the user normally wants **produce, meaning, and
read, but not write**, so:

```
(card - produce) = 1    (card - write) =      (card - meaning) = 1    (card - read) = 1
```

Other conventions, taken from the existing Unit decks:

- **Deck**: `Japanese::L7 - Yale::Unit NN`, a subdeck of the lesson deck.
- **No tags.** Earlier units carry `L7::U1`–`U3`, but the user has since said
  they don't want unit tags. Leave `tags` empty unless asked.
- **English**: sentence case. `Declining birthrate`, not `declining birthrate`.
- **Romanji**: sentence case, wāpuro long vowels (`ou`, `uu`), spaces between
  words. `Doujou suru`, `Shoushika ga susumu`, `Fuan no koe`.
- **Memorization Aid** is the place for extras from the handout — synonyms,
  example phrases, grammar attachment rules. It renders on card *backs*.
  **Never put these in `Hint`**, which renders on the produce front and would
  give away the answer.

## Step 1 — Read the PDF's layout before parsing it

Install nothing; `.venv` already has `pdfplumber` and `pypdf`. There is no
`pdftotext` on this machine.

Do not use `pypdf`'s `extract_text()`. It reflows the table into one blob, and
the asterisk ends up next to the wrong word. Use `pdfplumber` and keep the x
coordinates.

Dump the rows first and look at them:

```bash
.venv/bin/python .claude/skills/japanese-vocab-import/scripts/extract_starred.py --dump "handout.pdf"
```

You get rows like:

```
[168] ＊@77 | 現実感@138 | げんじつかん@256 | sense@383 | of@416 | reality@429
```

Read the column x positions off that output. **They change between handout
batches** — one set of PDFs used `＊@80 / jp@105 / kana@220 / en@318`, another
used `＊@77 / jp@138 / kana@256 / en@383`. Hardcoding last time's numbers
silently produces garbage, so always dump and look.

## Step 2 — Parse the marked rows

```bash
.venv/bin/python .claude/skills/japanese-vocab-import/scripts/extract_starred.py \
  --jp 125 --kana 250 --en 375 "handout.pdf" [more.pdf ...]
```

The script handles the three things that make this table awkward: entries whose
reading or English wraps onto following rows, page numbers that sit in the
English column, and Kangxi radical codepoints. See **Gotchas** for why each one
bites.

Then confirm the count independently, because a parser bug shows up as a
*missing* word, which is easy to miss:

```bash
.venv/bin/python .claude/skills/japanese-vocab-import/scripts/extract_starred.py --count "handout.pdf"
```

`--count` just counts `＊` glyphs in the marker column. It must equal the number
of parsed entries, and the default mode checks this for you and exits non-zero on
a mismatch. If it mismatches, a marked row didn't line up with an entry start —
go back to `--dump`.

To check the parser itself still behaves after any edit:

```bash
.venv/bin/python .claude/skills/japanese-vocab-import/scripts/extract_starred.py --selftest
```

It runs synthetic rows covering every parsing gotcha below, so it works without a
handout on hand.

## Step 2b — Some handouts have no reading column

The column parsing above assumes four columns. Not every handout is built that
way. The `おカバさま` list looks like this:

```
[150] 1@95 | ＊@140 | 河馬@176 | かば@212 | hippopotamus@248
[216] ＊@140 | 慌てる（あわてる）be@176 | flustered@299
[474] ＊@140 | 草食（そうしょく）herbivore@176
```

There is **no separate reading column**. The reading is inline in full-width
parentheses, and because nothing is space-separated, pdfplumber emits the word,
its reading, and often the first English word as a **single token** at x≈176.
`慌てる（あわてる）be` is one "word".

So `extract_starred.py`'s column split does not work on this shape. What still
works is the marker column (`＊` at x≈140) and the paragraph column. Use those
to select rows, join everything at x ≥ 170, and then split the text on the
parentheses rather than on x:

```
漢字（かな）English      ->  kanji, reading, gloss
かなEnglish             ->  kana-only word, no kanji
```

Expect to clean up the seams by hand. Transcribing 38 entries is quicker than
making a general parser for a layout that changes every handout.

### Scoping to a range of paragraphs

When the user asks for only part of the list ("paragraphs 1–3"), the paragraph
number sits in its own column left of the marker, at x≈95:

```python
if w["x0"] < 110 and w["top"] > 80 and w["text"].strip().isdigit():
    paragraph = int(w["text"])
```

Record each paragraph's `(page, top)` and keep the rows between the start of the
first one you want and the start of the one after the last. In the `おカバさま`
handout the paragraph starts were p1/150, p1/584, p2/489, p3/170, p3/492,
p4/331, p5/249 — so paragraphs 1–3 are everything from p1/150 up to p3/170.

The handout's own quiz numbering is **not** the unit number: that list headed
paragraphs 1–3 as "クイズ７". Don't name the deck after the quiz.

## Step 3 — Write out the note data by hand

The parser gives you Japanese, reading, and English. You still supply the
Romanji, and you still fix up the English into sentence case. Do this as a
literal Python list so it's reviewable:

```python
NOTES = [
    # English, Kana, Kanji, Romanji
    ("Sense of reality", "げんじつかん", "現実感", "Genjitsukan"),
    ("To consider; to take into account", "こうりょする", "考慮する", "Kouryo suru"),
]
```

Katakana words, set phrases and grammar patterns have no kanji. Put the kana
form in `Kana` and leave `Kanji` empty — keep the handout's `〜` and `（　）`
markers, matching the existing units:

```python
    ("Workplace harassment; power harassment", "パワハラ", "", "Pawahara"),
    ("To put pressure on ~", "（〜に）プレッシャーをかける", "", "(~ ni) puresshaa o kakeru"),
```

## Step 4 — Find duplicates yourself

Anki's own duplicate check only looks at the **first field** (`English`), which
is the wrong field for this job. It misses the same word with different wording,
and it blocks different words that share an English gloss. So search on the
Japanese instead:

```python
hits = ak("findNotes", {"query": f"note:Japanese (Kana:{kana} OR Kanji:{kanji})"})
```

**Then read every hit before calling it a duplicate.** Searching by reading
pulls in homophones, and these are real examples from this collection:

| You're adding | It matches | Same word? |
|---|---|---|
| 家事 (housework) | かじ → 火事 "Fire (destructive)" | No |
| 減少 (decrease) | げんしょう → 現象 "Phenomenon" | No |
| 出生率 しゅっしょうりつ | 出生率 しゅっせいりつ "Birth rate" | **Yes** — both readings are valid |
| 人間関係 | にんげんかんけい, empty Kanji, "Human relationship" | **Yes** — old note, just missing its kanji |

Print the kanji, kana, English, deck and tags of each hit and decide one at a
time. Do not automate this.

The first-field check also **blocks** a genuinely new word when some unrelated
note happens to carry the identical English. Adding 非 "Error; mistake" was
refused because 誤り（あやまり）in `JLPT N3` already had exactly that gloss. The
fix is to reword your gloss so it is both accurate and distinct — 非 became
"Fault; error; wrongdoing" — not to pass `allowDuplicate`.

Duplicates are not confined to the lesson decks. The collection also has
`JLPT N2` and `JLPT N3` decks, and most of the overlap turned up there. Those
notes are often **brand new** (never studied), so moving them costs nothing —
check `type`/`interval` before worrying about what a reset would lose.

## Step 5 — Create the deck, then add the new notes

Create the deck **before** the dry-run check, or every note comes back
`deck was not found` and real duplicate errors are hidden behind it.

```python
ak("createDeck", {"deck": DECK})
chk = ak("canAddNotesWithErrorDetail", {"notes": payload})
blocked = [(n, d.get("error")) for n, d in zip(names, chk) if not d.get("canAdd")]
assert not blocked, blocked
ak("addNotes", {"notes": payload})
```

Always run `canAddNotesWithErrorDetail` first. A single bad note makes
`addNotes` fail the **whole batch** with one top-level error and no indication
of which note caused it.

## Step 6 — Fold in the duplicates

The user's standing instruction: a duplicate is **moved** into the new deck and
its scheduling reset, rather than added a second time. Moving preserves the card
rows, so nothing is deleted.

```python
ak("updateNoteFields", {"note": {"id": nid, "fields": {...}}})   # fix gates/kanji first
cards = ak("notesInfo", {"notes": [nid]})[0]["cards"]
ak("changeDeck", {"cards": cards, "deck": DECK})                  # card ids, not note ids
ak("forgetCards", {"cards": cards})
```

Two fixes usually belong here, before the move:

- An old note with an **empty Kanji** field won't generate a read card. Fill in
  the kanji so the unit's read cards are complete.
- A note from another deck may have `(card - read)` empty. Set it to `1`.

If one word has **two** pre-existing notes, move the richer one and leave the
other alone — don't put two identical notes in the new deck. Report the stray so
the user can merge it; `japanese-merge/README.md` already flags this class of
duplication as a separate cleanup.

## Step 7 — Verify

Check all of these. Each one has actually caught something:

```python
info = ak("cardsInfo", {"cards": ak("findCards", {"query": f'deck:"{DECK}"'})})
Counter(c["ord"] for c in info)           # 0 produce, 1 write, 2 meaning, 3 read
[c for c in info if c["type"] != 0]       # must be empty: everything is new
[c for c in info if c["queue"] == -1]     # unexpected suspensions
```

- **Every marked word is present.** Diff the deck's `Kanji` values against your
  `NOTES` list; don't just trust the note count.
- **No write cards** (`ord == 1`), if the user didn't ask for write.
- **Read card count == number of notes that have kanji.** Read cards gate on
  kanji as well as the flag, so kana-only words get 2 cards, not 3. That's
  correct, not a bug.
- **Nothing kept old scheduling**: every card `type == 0`. Note that `reps`
  survives a reset — it's a lifetime counter. Check `type`/`queue`/`interval`,
  not `reps`.

## Gotchas

### The `＊` marker is positional, not textual

The handout legend uses two different asterisk marks:

- A leading **`＊`** in its own left-hand column — "this is on the quiz". This is
  what you want.
- A trailing **`***`** right after the word, inline — "this is slang, don't use
  it in class". This is **not** a selection mark.

A word can carry both. Matching on the character alone conflates them. Select on
x position: the quiz marker sits left of the Japanese column, around x≈77–80.

The trailing `***` is its own word in the PDF and often sits *inside* the
Japanese column's x range, so a naive column join yields `人柄***` as the
"kanji". Strip asterisks from the Japanese and reading text after joining —
`scripts/extract_starred.py` does this, and its self-test covers the case.

The user also asks you to ignore the yellow highlighting, which marks kanji they
should be able to write. It's a different axis from the `＊` and is invisible to
text extraction anyway.

### Kangxi radicals masquerading as kanji

These PDFs encode some kanji as **CJK Kangxi radical** codepoints, not normal
kanji: `⽣` (U+2F63) for 生, `⼈` (U+2F08) for 人, also 子, 力, 手, 足, 老, 見,
言, 欠. They look right and compare unequal. Left alone they break duplicate
detection, Anki search, and the stroke-order diagram lookup.

`unicodedata.normalize("NFKC", s)` fixes all of them. The script does it; if you
parse by hand, do it yourself.

### NFKC also half-widths the parentheses

`normalize("NFKC", s)` is what fixes the Kangxi radicals, but it rewrites `（`
and `）` to ASCII `(` and `)` at the same time. The existing Unit decks store
full-width parentheses (`（〜を）責める`), so don't feed NFKC output straight into
the `Kanji` field — normalise for *comparison*, and type the stored form by hand.

### Wrapped rows and stray page numbers

Long readings and English glosses wrap onto the next row, so one entry spans
several rows. Treat a row as starting a new entry only when it has a word in the
Japanese column, and append everything else to the current entry.

Page numbers sit near the top of the page at a high x, which lands them in the
English column and glues a digit onto the previous entry's gloss (`affection;
love 2`). Skip rows above the table — `top < 80` is enough.

### The anki MCP server fails; AnkiConnect still works

The `anki` MCP server usually reports `ECONNREFUSED` at session start. Ignore it
and talk to AnkiConnect directly over HTTP:

```bash
curl -s -X POST http://127.0.0.1:8765 -d '{"action":"version","version":6}'
```

Anki must be running. `scripts/anki.py` wraps this.

### Don't trust `merge.py` for the field names

`japanese-merge/merge.py` has a `FIELDS` constant listing `Cards` and gate
fields `_P _W _M _R`. **The live note type doesn't match it** — the gates were
renamed to `(card - produce)` and friends, and `Cards` is gone. The migration
ran once and the note type was edited afterwards.

Always ask the collection:

```python
ak("modelFieldNames", {"modelName": "Japanese"})
```

### `forgetCards` unsuspends

Resetting a suspended card makes it active again. If you reset a note that had a
suspended write card, that card comes back and starts showing up in a deck
that's supposed to have no write cards. Re-suspend it afterwards, or clear the
gate.

### You cannot delete a single card over the API

AnkiConnect has `deleteNotes` but no `deleteCards`. Clearing a card's gate field
leaves an **empty card** behind — it still exists, it just renders blank.

Removing it means **Tools → Empty Cards** in the Anki GUI, which deletes the
card *and its review history*. Per `japanese-merge/README.md`, prefer suspending
over deleting, and leave the Empty Cards run to the user rather than doing it on
their behalf.

### Moving a duplicate does not always mean resetting it

"Move it in and reset" is the default, but it is irreversible and wrong for a
word the user already knows. Before resetting, look at the intervals: 警察 was
at 1281 days and 怪我 at 571. The user's call on those was to **keep** the
produce and meaning scheduling and only let the new kanji read card come in
fresh — they knew the meanings, just not the kanji.

So split it: fill in the `Kanji` field and set `(card - read)`, which generates
the read card as new on its own, `changeDeck` the cards, and simply skip
`forgetCards`. Quote the actual intervals when you ask.

### Anki has to be running

AnkiConnect lives inside the Anki app, so every step past the PDF parsing needs
Anki open. `scripts/anki.py` turns a refused connection into a one-line message
saying so, rather than a urllib traceback.

### Tags ride along on moved notes

A note moved out of `L3 - Sun Academy` keeps its `SunAcademy::Week3` tag, which
now points at a deck it no longer lives in. Mention these; don't strip the
user's own tags without asking. `clearUnusedTags` purges names from the tag list
after `removeTags`.
