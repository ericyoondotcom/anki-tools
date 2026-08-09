#!/usr/bin/env python3
"""
Merge the "Japanese Vocab" and "Japanese Kanji" note types into a single
"Japanese" note type with four cards, without losing a single card's
scheduling or review history.

The whole design rests on one invariant:

    revlog rows reference cards.id, and all scheduling state lives on the
    card row itself.  So as long as we PRESERVE every cards.id and only
    rewrite nid / ord / did, scheduling and history follow automatically.

Nothing is exported, re-imported, or recreated.  New cards are only ever
*added* (for kanji notes that gain produce/meaning cards); no existing card
is destroyed or renumbered.

Usage:
    merge.py plan     --col COLLECTION            # analyse, write report, change nothing
    merge.py apply    --col COLLECTION            # perform the migration
    merge.py verify   --before ORIG --after COLLECTION
    merge.py resync   --col COLLECTION            # rebuild _P/_W/_M/_R from Cards
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from collections import defaultdict
from difflib import SequenceMatcher
from pathlib import Path

import anki.lang
from anki.collection import Collection
from anki.utils import field_checksum, int_time, strip_html_media

# strip_html_media() and field_checksum() both go through the Rust i18n
# backend, which is only initialised for us when aqt starts up. We drive the
# library headlessly, so do it ourselves.
anki.lang.set_lang("en_US")

HERE = Path(__file__).resolve().parent
TEMPLATE_DIR = HERE / "templates"

# --- note type names -------------------------------------------------------
NT_VOCAB = "Japanese Vocab"
NT_KANJI = "Japanese Kanji"
NT_READ = "Japanese Kanji - Reading only"
NT_NEW = "Japanese"

# --- the new note type -----------------------------------------------------
FIELDS = [
    "English", "Kana", "Kanji", "Romanji", "Diagram", "Hint",
    "Memorization Aid", "Cards", "_P", "_W", "_M", "_R",
]
FIELD_IDX = {name: i for i, name in enumerate(FIELDS)}

# ord, template name, file stem, flag letter, gate field
CARD_SPECS = [
    (0, "1 Produce", "1-produce", "p", "_P"),
    (1, "2 Write", "2-write", "w", "_W"),
    (2, "3 Meaning", "3-meaning", "m", "_M"),
    (3, "4 Read", "4-read", "r", "_R"),
]
FLAG_ORDER = "pwmr"
LETTER_BY_ORD = {ord_: letter for ord_, _, _, letter, _ in CARD_SPECS}
GATE_BY_LETTER = {letter: gate for _, _, _, letter, gate in CARD_SPECS}

# Source (note type, template ord) -> destination template ord.
ORD_MAP = {
    (NT_VOCAB, 0): 0,   # EN -> JP                  becomes (1) Produce
    (NT_VOCAB, 1): 2,   # JP+kana -> EN             becomes (3) Meaning
    (NT_KANJI, 0): 1,   # EN+kana -> write kanji    becomes (2) Write
    (NT_KANJI, 1): 3,   # kanji -> EN               becomes (4) Read
    (NT_READ, 0): 3,    # kanji -> EN               becomes (4) Read
}

TAG_SRC_PREFIX = "src::"


# ===========================================================================
# helpers
# ===========================================================================

def clean(s: str) -> str:
    """Field text with HTML stripped, for comparison purposes only."""
    return re.sub(r"<[^>]+>", "", s or "").strip()


def has_content(val: str) -> bool:
    """True if a field carries real content.

    Cannot just use clean(): the Diagram field holds nothing but an <img>
    tag, so stripping HTML makes it look empty and the stroke-order
    diagrams get dropped on the floor.
    """
    if not (val or "").strip():
        return False
    if clean(val):
        return True
    return bool(re.search(r"<(img|audio|video|object|svg)\b", val, re.I))


def eng_tokens(s: str) -> set[str]:
    return set(re.sub(r"[^a-z0-9 ]", " ", (s or "").lower()).split())


def english_agrees(a: str, b: str) -> bool:
    if eng_tokens(a) & eng_tokens(b):
        return True
    return SequenceMatcher(None, a.lower(), b.lower()).ratio() > 0.6


def tagify(deck_name: str) -> str:
    """Anki tags cannot contain spaces."""
    return deck_name.replace(" ", "_")


def read_tsv(path: Path) -> list[list[str]]:
    rows = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.rstrip("\n")
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            rows.append(line.split("\t"))
    return rows


def load_overrides() -> dict[tuple[str, str], tuple[str, str]]:
    """(kanji, kana) -> (action, target_english)"""
    out = {}
    for row in read_tsv(HERE / "overrides.tsv"):
        if len(row) < 4:
            sys.exit(f"overrides.tsv: malformed row: {row!r}")
        kanji, kana, action, target = row[0].strip(), row[1].strip(), row[2].strip(), row[3].strip()
        if action not in ("merge", "standalone", "ideograph"):
            sys.exit(f"overrides.tsv: unknown action {action!r}")
        out[(kanji, kana)] = (action, target)
    return out


def load_deckmap() -> dict[str, tuple[str, str]]:
    """source deck name -> (target deck, lesson tag)"""
    out = {}
    for row in read_tsv(HERE / "deckmap.tsv"):
        if len(row) < 3:
            sys.exit(f"deckmap.tsv: malformed row: {row!r}")
        out[row[0].strip()] = (row[1].strip(), row[2].strip())
    return out


def load_templates() -> list[tuple[str, str, str]]:
    """[(template name, qfmt, afmt)] in ord order."""
    out = []
    for _ord, name, stem, _letter, _gate in CARD_SPECS:
        front = (TEMPLATE_DIR / f"{stem}.front.html").read_text(encoding="utf-8")
        back = (TEMPLATE_DIR / f"{stem}.back.html").read_text(encoding="utf-8")
        out.append((name, front, back))
    return out


# ===========================================================================
# collection reading
# ===========================================================================

class SourceNote:
    __slots__ = ("nid", "kind", "eng", "kana", "kanji", "romanji", "diagram",
                 "hint", "aid", "tags", "cards")

    def __init__(self, nid, kind, flds, tags):
        f = flds.split("\x1f")
        self.nid = nid
        self.kind = kind
        self.tags = tags
        self.cards = {}  # source ord -> card row dict
        if kind == NT_VOCAB:
            self.eng, self.romanji, self.kanji, self.kana = f[0], f[1], f[2], f[3]
            self.hint, self.aid = f[4], f[5]
            self.diagram = ""
        elif kind == NT_KANJI:
            self.eng, self.kana, self.kanji, self.diagram, self.hint = f[0], f[1], f[2], f[3], f[4]
            self.romanji, self.aid = "", ""
        else:  # NT_READ
            self.eng, self.kana, self.kanji, self.hint = f[0], f[1], f[2], f[3]
            self.romanji, self.diagram, self.aid = "", "", ""

    @property
    def c_eng(self) -> str:
        return clean(self.eng)

    @property
    def c_kana(self) -> str:
        return clean(self.kana)

    @property
    def c_kanji(self) -> str:
        return clean(self.kanji)

    def reps(self) -> int:
        return sum(c["reps"] for c in self.cards.values())


def load_source(col: Collection) -> dict[int, SourceNote]:
    mids = {}
    for kind in (NT_VOCAB, NT_KANJI, NT_READ):
        nt = col.models.by_name(kind)
        if nt is None:
            sys.exit(f"note type {kind!r} not found in collection")
        mids[nt["id"]] = kind

    notes: dict[int, SourceNote] = {}
    ph = ",".join(str(m) for m in mids)
    for nid, mid, flds, tags in col.db.all(
        f"select id, mid, flds, tags from notes where mid in ({ph})"
    ):
        notes[nid] = SourceNote(nid, mids[mid], flds, tags)

    for cid, nid, ord_, did, odid, reps, queue in col.db.all(
        f"select c.id, c.nid, c.ord, c.did, c.odid, c.reps, c.queue "
        f"from cards c join notes n on n.id = c.nid where n.mid in ({ph})"
    ):
        notes[nid].cards[ord_] = {
            "id": cid, "ord": ord_, "did": did, "odid": odid,
            "reps": reps, "queue": queue,
        }
    return notes


# ===========================================================================
# matching
# ===========================================================================

class Plan:
    def __init__(self):
        self.merges: dict[int, int] = {}          # kanji nid -> vocab nid
        self.standalone: list[int] = []           # kanji nids kept separate
        self.ideographs: set[int] = set()         # subset of standalone, no p/m cards
        self.displaced: list[tuple[int, int]] = []  # (kanji nid, vocab nid) that lost an ord race
        self.notes_report: list[list[str]] = []


def build_plan(notes: dict[int, SourceNote], overrides) -> Plan:
    plan = Plan()

    vocab = {nid: n for nid, n in notes.items() if n.kind == NT_VOCAB}
    kanji = {nid: n for nid, n in notes.items() if n.kind != NT_VOCAB}

    by_kanji_kana: dict[tuple[str, str], int] = {}
    by_kana: dict[str, list[int]] = defaultdict(list)
    by_english: dict[str, list[int]] = defaultdict(list)
    for nid, n in vocab.items():
        by_kana[n.c_kana].append(nid)
        by_english[n.c_eng].append(nid)
        if n.c_kanji:
            by_kanji_kana.setdefault((n.c_kanji, n.c_kana), nid)

    for nid, n in sorted(kanji.items()):
        key = (n.c_kanji, n.c_kana)
        reason = ""
        target = None

        if key in overrides:
            action, want_eng = overrides[key]
            if action == "ideograph":
                plan.standalone.append(nid)
                plan.ideographs.add(nid)
                plan.notes_report.append([str(nid), n.c_kanji, n.c_kana, n.c_eng,
                                          "ideograph", "", "override: no vocab cards"])
                continue
            if action == "standalone":
                plan.standalone.append(nid)
                plan.notes_report.append([str(nid), n.c_kanji, n.c_kana, n.c_eng,
                                          "standalone", "", "override"])
                continue
            cands = by_english.get(want_eng, [])
            if len(cands) != 1:
                sys.exit(
                    f"overrides.tsv: target English {want_eng!r} for {n.c_kanji} "
                    f"matches {len(cands)} vocab notes; must match exactly 1"
                )
            target, reason = cands[0], "override"

        if target is None and key in by_kanji_kana:
            target, reason = by_kanji_kana[key], "exact kanji+kana"

        if target is None:
            cands = [v for v in by_kana.get(n.c_kana, [])
                     if english_agrees(n.c_eng, vocab[v].c_eng)]
            if len(cands) == 1:
                target, reason = cands[0], "kana + english"
            elif len(cands) > 1:
                sys.exit(
                    f"ambiguous kana match for {n.c_kanji} ({n.c_kana}) "
                    f"'{n.c_eng}' -> {[vocab[c].c_eng for c in cands]}; add an overrides.tsv row"
                )

        if target is None:
            if by_kana.get(n.c_kana):
                sys.exit(
                    f"{n.c_kanji} ({n.c_kana}) '{n.c_eng}' shares a reading with "
                    f"{[vocab[c].c_eng for c in by_kana[n.c_kana]]} but no English "
                    f"agreement; add an overrides.tsv row"
                )
            plan.standalone.append(nid)
            plan.notes_report.append([str(nid), n.c_kanji, n.c_kana, n.c_eng,
                                      "standalone", "", "no vocab counterpart"])
            continue

        plan.merges[nid] = target
        plan.notes_report.append([str(nid), n.c_kanji, n.c_kana, n.c_eng,
                                  "merge", vocab[target].c_eng, reason])

    _resolve_ord_conflicts(notes, plan)
    return plan


def _resolve_ord_conflicts(notes, plan: Plan) -> None:
    """Two kanji notes can claim the same destination ord on one vocab note.

    The card with more reviews wins the ord; the loser is re-homed as a
    standalone note rather than deleted, so no history is ever discarded.
    """
    claims: dict[int, dict[int, list[tuple[int, int, int]]]] = defaultdict(lambda: defaultdict(list))
    for knid, vnid in plan.merges.items():
        kn = notes[knid]
        for src_ord, card in kn.cards.items():
            dest = ORD_MAP[(kn.kind, src_ord)]
            claims[vnid][dest].append((card["reps"], knid, src_ord))

    losers: set[int] = set()
    for vnid, per_ord in claims.items():
        for dest, entries in per_ord.items():
            if len(entries) < 2:
                continue
            entries.sort(reverse=True)  # most reviews first
            for _reps, knid, _src in entries[1:]:
                losers.add(knid)

    for knid in sorted(losers):
        vnid = plan.merges.pop(knid)
        plan.displaced.append((knid, vnid))
        plan.standalone.append(knid)
        # rewrite the row this note already has, so it is reported once only
        for row in plan.notes_report:
            if row[0] == str(knid):
                row[4] = "standalone"
                row[5] = notes[vnid].c_eng
                row[6] = "lost ord race (fewer reviews) - kept, not deleted"
                break


# ===========================================================================
# note type creation
# ===========================================================================

def build_notetype(col: Collection) -> dict:
    existing = col.models.by_name(NT_NEW)
    if existing:
        return existing

    mm = col.models
    nt = mm.new(NT_NEW)
    for name in FIELDS:
        fld = mm.new_field(name)
        mm.add_field(nt, fld)
    for name, qfmt, afmt in load_templates():
        tmpl = mm.new_template(name)
        tmpl["qfmt"] = qfmt
        tmpl["afmt"] = afmt
        mm.add_template(nt, tmpl)
    nt["css"] = (TEMPLATE_DIR / "style.css").read_text(encoding="utf-8")
    nt["sortf"] = FIELD_IDX["English"]
    mm.add_dict(nt)
    return col.models.by_name(NT_NEW)


# ===========================================================================
# flags
# ===========================================================================

def flags_to_gates(flags: str) -> dict[str, str]:
    flags = (flags or "").lower()
    return {gate: ("1" if letter in flags else "")
            for letter, gate in GATE_BY_LETTER.items()}


def normalise_flags(flags: str) -> str:
    seen = {c for c in (flags or "").lower() if c in FLAG_ORDER}
    return "".join(c for c in FLAG_ORDER if c in seen)


# ===========================================================================
# apply
# ===========================================================================

def apply_migration(col: Collection, dry_run: bool) -> None:
    overrides = load_overrides()
    deckmap = load_deckmap()
    notes = load_source(col)
    plan = build_plan(notes, overrides)

    deck_names = {did: name for did, name in col.db.all("select id, name from decks")}
    deck_names = {did: name.replace("\x1f", "::") for did, name in deck_names.items()}

    # --- every source deck must be mapped; never silently drop one ---------
    used = set()
    for n in notes.values():
        for c in n.cards.values():
            used.add(deck_names[c["odid"] or c["did"]])
    missing = sorted(used - set(deckmap))
    if missing:
        sys.exit("deckmap.tsv is missing these source decks:\n  " + "\n  ".join(missing))

    write_report(plan, notes)

    survivors = _survivor_map(notes, plan)
    print(f"  merges          : {len(plan.merges)}")
    print(f"  standalone      : {len(plan.standalone)} "
          f"({len(plan.ideographs)} ideograph-only)")
    print(f"  displaced       : {len(plan.displaced)}")
    print(f"  notes after     : {len(survivors)}")

    if dry_run:
        print("\nplan only — nothing written. Re-run with `apply` to migrate.")
        return

    col.mod_schema(check=False)
    nt = build_notetype(col)
    mid = nt["id"]
    now = int_time()

    # ---------------------------------------------------------------- notes
    for vnid, spec in survivors.items():
        flds = _compose_fields(spec, notes)
        _write_note(col, vnid, mid, flds, spec["tags"], now)

    # ---------------------------------------------------------------- cards
    # Park every affected card in a temporary ord namespace first, so that
    # re-pointing nid/ord can never transiently violate the (nid, ord) index.
    all_cids = [c["id"] for n in notes.values() for c in n.cards.values()]
    _chunked(col, "update cards set ord = ord + 1000 where id in", all_cids)

    moves: list[tuple[int, int, int]] = []  # (cid, nid, ord)
    for vnid, spec in survivors.items():
        for dest_ord, card in spec["cards"].items():
            moves.append((card["id"], vnid, dest_ord))

    seen: set[tuple[int, int]] = set()
    for cid, nid, ord_ in moves:
        if (nid, ord_) in seen:
            sys.exit(f"internal error: duplicate destination (nid={nid}, ord={ord_})")
        seen.add((nid, ord_))

    col.db.executemany(
        "update cards set nid = ?, ord = ?, mod = ?, usn = -1 where id = ?",
        [(nid, ord_, now, cid) for cid, nid, ord_ in moves],
    )

    # ------------------------------------------------------- delete emptied
    dead = sorted(plan.merges)
    if dead:
        _chunked(col, "delete from notes where id in", dead)

    # --------------------------------------------- generate the new cards
    need_cards = [nid for nid, spec in survivors.items() if spec["new_cards"]]
    if need_cards:
        col.after_note_updates(need_cards, mark_modified=False, generate_cards=True)
    print(f"  new cards for   : {len(need_cards)} notes")

    # ------------------------------------------------------------- decks
    _apply_decks(col, survivors, deckmap, deck_names, now)

    print("\nmigration applied.")


def _survivor_map(notes, plan: Plan) -> dict[int, dict]:
    """nid -> {sources, cards(dest ord->card), flags, tags, new_cards}"""
    merged_into: dict[int, list[int]] = defaultdict(list)
    for knid, vnid in plan.merges.items():
        merged_into[vnid].append(knid)

    survivors: dict[int, dict] = {}

    for nid, n in notes.items():
        if n.kind == NT_VOCAB:
            sources = [nid] + sorted(merged_into.get(nid, []))
        elif nid in plan.standalone:
            sources = [nid]
        else:
            continue  # merged away

        cards: dict[int, dict] = {}
        for snid in sources:
            sn = notes[snid]
            for src_ord, card in sn.cards.items():
                dest = ORD_MAP[(sn.kind, src_ord)]
                if dest in cards:
                    sys.exit(f"internal error: unresolved ord clash on note {nid}")
                cards[dest] = card

        primary = notes[nid]
        has_kanji = bool(_pick(notes, sources, "kanji"))
        letters = {LETTER_BY_ORD[o] for o in cards}

        new_cards: list[int] = []
        if primary.kind != NT_VOCAB and nid not in plan.ideographs:
            # a standalone kanji note becomes a full vocabulary note
            for o in (0, 2):
                if o not in cards:
                    letters.add(LETTER_BY_ORD[o])
                    new_cards.append(o)
        if not has_kanji:
            letters -= {"w", "r"}

        tags = set()
        for snid in sources:
            tags.update(t for t in notes[snid].tags.split() if t)

        survivors[nid] = {
            "sources": sources,
            "cards": cards,
            "flags": normalise_flags("".join(sorted(letters))),
            "tags": tags,
            "new_cards": new_cards,
        }
    return survivors


def _pick(notes, sources: list[int], attr: str) -> str:
    """First non-empty value of `attr` across the source notes, vocab first."""
    for nid in sources:
        val = getattr(notes[nid], attr)
        if has_content(val):
            return val
    return ""


def _compose_fields(spec: dict, notes) -> list[str]:
    src = spec["sources"]
    flds = [""] * len(FIELDS)
    flds[FIELD_IDX["English"]] = _pick(notes, src, "eng")
    flds[FIELD_IDX["Kana"]] = _pick(notes, src, "kana")
    flds[FIELD_IDX["Kanji"]] = _pick(notes, src, "kanji")
    flds[FIELD_IDX["Romanji"]] = _pick(notes, src, "romanji")
    flds[FIELD_IDX["Diagram"]] = _pick(notes, src, "diagram")
    flds[FIELD_IDX["Hint"]] = _pick(notes, src, "hint")
    flds[FIELD_IDX["Memorization Aid"]] = _pick(notes, src, "aid")
    flds[FIELD_IDX["Cards"]] = spec["flags"]
    for gate, val in flags_to_gates(spec["flags"]).items():
        flds[FIELD_IDX[gate]] = val
    return flds


def _write_note(col: Collection, nid: int, mid: int, flds: list[str],
                tags: set[str], now: int) -> None:
    joined = "\x1f".join(flds)
    sfld = strip_html_media(flds[FIELD_IDX["English"]])
    csum = field_checksum(flds[FIELD_IDX["English"]])
    tagstr = " " + " ".join(sorted(tags)) + " " if tags else " "
    col.db.execute(
        "update notes set mid = ?, flds = ?, sfld = ?, csum = ?, tags = ?, "
        "mod = ?, usn = -1 where id = ?",
        mid, joined, sfld, csum, tagstr, now, nid,
    )


def _apply_decks(col, survivors, deckmap, deck_names, now) -> None:
    target_ids: dict[str, int] = {}
    updates: list[tuple[int, int]] = []
    tag_updates: dict[int, set[str]] = {}

    for nid, spec in survivors.items():
        # The vocab card is the source of truth for where the note lives.
        anchor = spec["cards"].get(0) or spec["cards"].get(2) \
            or next(iter(spec["cards"].values()))
        src_deck = deck_names[anchor["odid"] or anchor["did"]]
        target, lesson = deckmap[src_deck]

        if target not in target_ids:
            target_ids[target] = col.decks.id(target)
        did = target_ids[target]

        tags = set(spec["tags"])
        if lesson:
            tags.add(lesson)
        for snid_card in spec["cards"].values():
            osrc = deck_names[snid_card["odid"] or snid_card["did"]]
            tags.add(TAG_SRC_PREFIX + tagify(osrc))
        tag_updates[nid] = tags

        for card in spec["cards"].values():
            updates.append((did, card["id"]))

    # cards created during generation inherit their siblings' deck
    col.db.executemany(
        "update cards set did = ?, mod = %d, usn = -1 where id = ?" % now,
        updates,
    )
    for nid, tags in tag_updates.items():
        col.db.execute(
            "update notes set tags = ?, mod = ?, usn = -1 where id = ?",
            " " + " ".join(sorted(tags)) + " ", now, nid,
        )
    # sweep any generated card that is still sitting in an old deck
    for nid, spec in survivors.items():
        anchor = spec["cards"].get(0) or next(iter(spec["cards"].values()))
        col.db.execute(
            "update cards set did = (select did from cards where id = ?) "
            "where nid = ? and odid = 0",
            anchor["id"], nid,
        )
    print(f"  target decks    : {len(target_ids)} -> {sorted(target_ids)}")
    _remove_emptied_decks(col, deckmap, set(target_ids))


def _remove_emptied_decks(col, deckmap, keep_names: set[str]) -> None:
    """Delete the source decks we just drained, plus any parents left empty.

    Only decks named in deckmap.tsv (and their ancestors) are eligible, so
    unrelated trees such as Korean:: or Music Theory:: can never be touched.
    """
    eligible: set[str] = set()
    for name in deckmap:
        parts = name.split("::")
        for i in range(1, len(parts) + 1):
            eligible.add("::".join(parts[:i]))
    eligible -= keep_names

    removed = []
    # deepest first, so a parent is only judged once its children are gone
    for name in sorted(eligible, key=lambda n: n.count("::"), reverse=True):
        did = col.db.scalar("select id from decks where name = ?",
                            name.replace("::", "\x1f"))
        if did is None:
            continue
        n_cards = col.db.scalar("select count(*) from cards where did = ? or odid = ?",
                                did, did)
        if n_cards:
            print(f"  ! kept {name!r} — still holds {n_cards} card(s)")
            continue
        col.decks.remove([did])
        removed.append(name)
    print(f"  drained decks   : removed {len(removed)}")


def _chunked(col: Collection, sql_prefix: str, ids: list[int], size: int = 900) -> None:
    for i in range(0, len(ids), size):
        chunk = ids[i:i + size]
        col.db.execute(f"{sql_prefix} ({','.join('?' * len(chunk))})", *chunk)


def write_report(plan: Plan, notes) -> None:
    path = HERE / "report.tsv"
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, delimiter="\t")
        w.writerow(["kanji_nid", "kanji", "kana", "kanji_english",
                    "action", "vocab_english", "reason"])
        w.writerows(plan.notes_report)
    print(f"  report          : {path}")


# ===========================================================================
# resync
# ===========================================================================

def resync(col: Collection) -> None:
    nt = col.models.by_name(NT_NEW)
    if not nt:
        sys.exit(f"note type {NT_NEW!r} not found")
    now = int_time()
    fixed = 0
    for nid, flds in col.db.all("select id, flds from notes where mid = ?", nt["id"]):
        f = flds.split("\x1f")
        want = flags_to_gates(f[FIELD_IDX["Cards"]])
        changed = False
        for gate, val in want.items():
            if f[FIELD_IDX[gate]] != val:
                f[FIELD_IDX[gate]] = val
                changed = True
        if changed:
            col.db.execute(
                "update notes set flds = ?, mod = ?, usn = -1 where id = ?",
                "\x1f".join(f), now, nid,
            )
            fixed += 1
    print(f"resynced {fixed} notes")


# ===========================================================================
# verify
# ===========================================================================

def verify(before_path: Path, after_path: Path) -> int:
    before = Collection(str(before_path))
    after = Collection(str(after_path))
    failures: list[str] = []

    def check(ok: bool, label: str, detail: str = "") -> None:
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f" — {detail}" if detail else ""))
        if not ok:
            failures.append(label)

    SCHED = "due, ivl, factor, reps, lapses, queue, type, odue"
    b_cards = {row[0]: row[1:] for row in
               before.db.all(f"select id, {SCHED} from cards")}
    a_cards = {row[0]: row[1:] for row in
               after.db.all(f"select id, {SCHED} from cards")}

    lost = sorted(set(b_cards) - set(a_cards))
    check(not lost, "no card destroyed",
          f"{len(b_cards)} before" if not lost else f"{len(lost)} lost, e.g. {lost[:5]}")

    added = sorted(set(a_cards) - set(b_cards))
    check(True, "new cards added", f"{len(added)}")

    drift = [cid for cid in b_cards if cid in a_cards and b_cards[cid] != a_cards[cid]]
    check(not drift, "scheduling byte-identical",
          "all preserved" if not drift else f"{len(drift)} changed, e.g. {drift[:5]}")

    b_rev = before.db.scalar("select count(*) from revlog")
    a_rev = after.db.scalar("select count(*) from revlog")
    check(b_rev == a_rev, "revlog intact", f"{b_rev} -> {a_rev}")

    # Orphaned revlog rows pre-exist in any collection where cards were ever
    # deleted, so the invariant is "we added none", not "there are none".
    orphan_sql = "select count(*) from revlog where cid not in (select id from cards)"
    b_orphan = before.db.scalar(orphan_sql)
    a_orphan = after.db.scalar(orphan_sql)
    check(a_orphan <= b_orphan, "no review history orphaned by the migration",
          f"{b_orphan} pre-existing -> {a_orphan}")

    dupes = after.db.all(
        "select nid, ord, count(*) c from cards group by nid, ord having c > 1 limit 5")
    check(not dupes, "no duplicate (nid, ord)", str(dupes) if dupes else "")

    nt = after.models.by_name(NT_NEW)
    check(nt is not None, f"note type {NT_NEW!r} exists")
    if nt:
        n_new = after.db.scalar("select count(*) from notes where mid = ?", nt["id"])
        check(True, "notes on new type", str(n_new))
        bad_ord = after.db.scalar(
            "select count(*) from cards c join notes n on n.id = c.nid "
            "where n.mid = ? and (c.ord < 0 or c.ord > 3)", nt["id"])
        check(bad_ord == 0, "all ords within 0..3", f"{bad_ord} out of range")

    for name in (NT_VOCAB, NT_KANJI, NT_READ):
        old = after.models.by_name(name)
        left = after.db.scalar("select count(*) from notes where mid = ?", old["id"]) if old else 0
        check(left == 0, f"no notes left on {name!r}", f"{left}")

    # every existing card must have its flag letter set
    if nt:
        missing = 0
        for flds, ord_ in after.db.all(
            "select n.flds, c.ord from cards c join notes n on n.id = c.nid "
            "where n.mid = ?", nt["id"]
        ):
            f = flds.split("\x1f")
            if LETTER_BY_ORD[ord_] not in (f[FIELD_IDX["Cards"]] or ""):
                missing += 1
        check(missing == 0, "every card's flag letter is set",
              f"{missing} cards would render empty")

    # --- field content must survive the merge ------------------------------
    # The Diagram field holds nothing but an <img> tag, so a naive "is this
    # field empty?" test drops every stroke-order diagram silently. Compare
    # the actual media references instead.
    def media_refs(col_, mids):
        ph = ",".join(str(m) for m in mids)
        refs = set()
        for (flds,) in col_.db.all(f"select flds from notes where mid in ({ph})"):
            refs.update(re.findall(r'src="([^"]+)"', flds))
        return refs

    b_mids = [m["id"] for m in
              (before.models.by_name(n) for n in (NT_VOCAB, NT_KANJI, NT_READ)) if m]
    b_media = media_refs(before, b_mids)
    a_media = media_refs(after, [nt["id"]]) if nt else set()
    lost_media = sorted(b_media - a_media)
    check(not lost_media, "every media reference preserved",
          f"{len(b_media)} refs" if not lost_media
          else f"{len(lost_media)} lost, e.g. {lost_media[:3]}")

    if nt:
        idx = {f["name"]: i for i, f in enumerate(nt["flds"])}
        counts = {}
        for (flds,) in after.db.all("select flds from notes where mid = ?", nt["id"]):
            f = flds.split("\x1f")
            for name in ("Kanji", "Romanji", "Diagram", "Hint", "Memorization Aid"):
                if f[idx[name]].strip():
                    counts[name] = counts.get(name, 0) + 1
        print("  non-empty fields after: " +
              ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))

    tagged = after.db.scalar(
        "select count(*) from notes where mid = ? and tags not like ?",
        nt["id"], f"%{TAG_SRC_PREFIX}%") if nt else 0
    check(tagged == 0, "every note carries a src:: provenance tag", f"{tagged} without")

    decks = sorted(n.replace("\x1f", "::") for (n,) in after.db.all(
        "select name from decks") if n not in ("Default",))
    print(f"\n  decks: {decks}")

    before.close()
    after.close()
    print()
    if failures:
        print(f"VERIFY FAILED: {len(failures)} check(s) — " + "; ".join(failures))
        return 1
    print("VERIFY PASSED — all cards and review history preserved.")
    return 0


# ===========================================================================
# main
# ===========================================================================

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["plan", "apply", "verify", "resync"])
    ap.add_argument("--col", type=Path, help="collection to read/modify")
    ap.add_argument("--before", type=Path, help="pristine collection (verify)")
    ap.add_argument("--after", type=Path, help="migrated collection (verify)")
    args = ap.parse_args()

    if args.command == "verify":
        if not args.before or not args.after:
            ap.error("verify needs --before and --after")
        return verify(args.before, args.after)

    if not args.col:
        ap.error(f"{args.command} needs --col")
    col = Collection(str(args.col))
    try:
        if args.command == "resync":
            resync(col)
        else:
            apply_migration(col, dry_run=(args.command == "plan"))
    finally:
        col.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
