#!/usr/bin/env python3
"""
Thin AnkiConnect client for vocab imports. Anki must be running.

    python3 -c "from anki import *; print(fields())"
"""

import json
import urllib.request

URL = "http://127.0.0.1:8765"
MODEL = "Japanese"
CARD_NAMES = {0: "produce", 1: "write", 2: "meaning", 3: "read"}


def ak(action, **params):
    body = json.dumps({"action": action, "version": 6, "params": params}).encode()
    try:
        reply = json.load(urllib.request.urlopen(urllib.request.Request(URL, body)))
    except urllib.error.URLError as exc:
        raise RuntimeError(
            f"no AnkiConnect at {URL} ({exc.reason}). Is Anki running?"
        ) from None
    if reply["error"]:
        raise RuntimeError(f"{action}: {reply['error']}")
    return reply["result"]


def fields():
    return ak("modelFieldNames", modelName=MODEL)


def note(english, kana, kanji, romanji, deck, aid="", cards="pmr"):
    return {
        "deckName": deck,
        "modelName": MODEL,
        "fields": {
            "English": english, "Kana": kana, "Kanji": kanji, "Romanji": romanji,
            "Diagram": "", "Hint": "", "Memorization Aid": aid,
            "(card - produce)": "1" if "p" in cards else "",
            "(card - write)": "1" if "w" in cards else "",
            "(card - meaning)": "1" if "m" in cards else "",
            "(card - read)": "1" if "r" in cards else "",
        },
        "tags": [],
    }


def find_duplicates(kana, kanji):
    """Candidates only — homophones match too, so read every hit before acting."""
    clauses = [f"Kana:{kana}"] + ([f"Kanji:{kanji}"] if kanji else [])
    hits = ak("findNotes", query=f"note:{MODEL} ({' OR '.join(clauses)})")
    out = []
    for n in ak("notesInfo", notes=hits) if hits else []:
        f = n["fields"]
        decks = {c["deckName"] for c in ak("cardsInfo", cards=n["cards"])}
        out.append({"id": n["noteId"], "kanji": f["Kanji"]["value"],
                    "kana": f["Kana"]["value"], "english": f["English"]["value"],
                    "decks": sorted(decks), "tags": n["tags"]})
    return out


def add(notes, deck):
    ak("createDeck", deck=deck)
    checked = ak("canAddNotesWithErrorDetail", notes=notes)
    blocked = [(n["fields"]["Kanji"] or n["fields"]["Kana"], c.get("error"))
               for n, c in zip(notes, checked) if not c.get("canAdd")]
    if blocked:
        raise RuntimeError(f"blocked: {blocked}")
    return ak("addNotes", notes=notes)


def move_and_reset(note_id, deck, field_fixes=None):
    if field_fixes:
        ak("updateNoteFields", note={"id": note_id, "fields": field_fixes})
    cards = ak("notesInfo", notes=[note_id])[0]["cards"]
    suspended = [c["cardId"] for c in ak("cardsInfo", cards=cards) if c["queue"] == -1]
    ak("changeDeck", cards=cards, deck=deck)
    ak("forgetCards", cards=cards)
    if suspended:
        ak("suspend", cards=suspended)
    return cards


def verify(deck):
    cards = ak("cardsInfo", cards=ak("findCards", query=f'deck:"{deck}"'))
    notes = ak("notesInfo", notes=ak("findNotes", query=f'deck:"{deck}"'))
    by_template = {}
    for c in cards:
        by_template[CARD_NAMES[c["ord"]]] = by_template.get(CARD_NAMES[c["ord"]], 0) + 1
    return {
        "notes": len(notes),
        "cards": len(cards),
        "by_template": by_template,
        "with_kanji": sum(1 for n in notes if n["fields"]["Kanji"]["value"]),
        "not_new": [c["cardId"] for c in cards if c["type"] != 0],
        "suspended": [c["cardId"] for c in cards if c["queue"] == -1],
        "tags": sorted({t for n in notes for t in n["tags"]}),
        "kanji": sorted(n["fields"]["Kanji"]["value"] for n in notes),
    }
